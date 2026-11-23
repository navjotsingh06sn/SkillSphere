import asyncio
import logging
import time
import base64
import binascii
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import admin_required, candidate_required, get_current_user, get_database, recruiter_required
from app.models import Assessment, AssessmentRecording, ProctoringEvidence, ProctoringEvent, ProctoringSession, User
from app.services.cloudinary_storage import (
    CloudinaryUnavailable, delete_video_resource, fetch_video_resource,
    signed_upload_parameters, signed_video_download_url,
)


router = APIRouter(prefix="/proctoring", tags=["proctoring"])
logger = logging.getLogger(__name__)

WARNING_EVENTS = {
    "face_missing",
    "face_away",
    "multiple_faces",
    "restricted_item",
    "tab_hidden",
    "window_blur",
    "camera_interrupted",
    "screen_interrupted",
}
EVENT_DESCRIPTIONS = {
    "face_missing": "No face was detected in the camera view.",
    "face_away": "The candidate moved outside the camera's expected viewing area.",
    "multiple_faces": "More than one face was detected in the camera view.",
    "restricted_item": "A restricted item was detected in the camera view.",
    "tab_hidden": "The assessment page was hidden or backgrounded.",
    "window_blur": "The assessment window lost focus.",
    "camera_interrupted": "The camera feed was interrupted.",
    "camera_reconnected": "The camera feed was reconnected.",
    "screen_interrupted": "The shared assessment screen was disconnected.",
    "screen_reconnected": "The shared assessment screen was reconnected.",
}


class ProctoringStartInput(BaseModel):
    assessment_id: UUID
    consent_accepted: bool
    camera_permission_granted: bool
    recording_consent_accepted: bool
    screen_permission_granted: bool


class ProctoringEventInput(BaseModel):
    event_type: Literal[
        "face_missing",
        "face_away",
        "multiple_faces",
        "restricted_item",
        "tab_hidden",
        "window_blur",
        "camera_interrupted",
        "camera_reconnected",
        "screen_interrupted",
        "screen_reconnected",
    ]
    face_count: int | None = Field(default=None, ge=0, le=20)
    item_name: Literal["cell phone", "book", "remote"] | None = None


class SessionReviewInput(BaseModel):
    is_flagged: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


@router.post("/sessions/start")
async def start_proctoring_session(
    data: ProctoringStartInput,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    if not data.consent_accepted:
        raise HTTPException(status_code=400, detail="Proctoring consent is required.")
    if not data.recording_consent_accepted:
        raise HTTPException(status_code=400, detail="Recording consent is required.")
    if not data.screen_permission_granted:
        raise HTTPException(status_code=400, detail="Screen sharing permission is required.")
    if not data.camera_permission_granted:
        raise HTTPException(
            status_code=400, detail="Camera permission is required."
        )

    candidate_id = UUID(user["id"])
    assessment = await database.scalar(
        select(Assessment)
        .where(
            Assessment.id == data.assessment_id,
            Assessment.candidate_id == candidate_id,
        )
        .with_for_update()
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if assessment.status not in {"assigned", "in_progress"}:
        raise HTTPException(
            status_code=409, detail="This assessment is not available to start."
        )

    now = datetime.now(timezone.utc)
    session = await database.scalar(
        select(ProctoringSession)
        .where(ProctoringSession.assessment_id == assessment.id)
        .with_for_update()
    )
    status = "active" if assessment.status == "in_progress" else "ready"

    if session is None:
        session = ProctoringSession(
            assessment_id=assessment.id,
            candidate_id=candidate_id,
            status=status,
            consented_at=now,
            camera_permission_at=now,
            recording_consented_at=now,
            started_at=now if status == "active" else None,
        )
        database.add(session)
    else:
        if session.candidate_id != candidate_id:
            raise HTTPException(status_code=404, detail="Assessment not found.")
        if session.status == "completed":
            raise HTTPException(
                status_code=409, detail="This proctoring session is complete."
            )
        session.status = status
        session.consented_at = now
        session.camera_permission_at = now
        session.recording_consented_at = now
        if status == "active" and session.started_at is None:
            session.started_at = now
        session.updated_at = now

    await database.commit()
    await database.refresh(session)
    return {
        "session_id": str(session.id),
        "status": session.status,
        "warning_count": session.warning_count,
    }


@router.post("/sessions/{session_id}/events")
async def record_proctoring_event(
    session_id: UUID,
    data: ProctoringEventInput,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    candidate_id = UUID(user["id"])
    session = await database.scalar(
        select(ProctoringSession)
        .where(
            ProctoringSession.id == session_id,
            ProctoringSession.candidate_id == candidate_id,
        )
        .with_for_update()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Proctoring session not found.")
    if session.status not in {"ready", "active"}:
        raise HTTPException(
            status_code=409, detail="This proctoring session is not active."
        )

    now = datetime.now(timezone.utc)

    description = EVENT_DESCRIPTIONS[data.event_type]
    if data.event_type == "multiple_faces" and data.face_count is not None:
        description = (
            f"More than one face was detected in the camera view "
            f"({data.face_count} detected)."
        )
    assessment = await database.scalar(
        select(Assessment).where(Assessment.id == session.assessment_id)
    )
    assessment_active = assessment is not None and assessment.status == "in_progress"
    severity = "warning" if data.event_type in WARNING_EVENTS and assessment_active else "info"
    if data.event_type == "restricted_item" and data.item_name:
        description = f"A {data.item_name} was detected in the camera view."
    event = ProctoringEvent(
            session_id=session.id,
            event_type=data.event_type,
            severity=severity,
            description=description,
            occurred_at=now,
        )
    database.add(event)
    if severity == "warning":
        session.warning_count += 1
    warning_count = session.warning_count
    session.updated_at = now
    await database.commit()
    return {"recorded": True, "warning_count": warning_count, "event_id": str(event.id)}


class EvidenceCaptureInput(BaseModel):
    capture_type: Literal["camera", "screen"]
    image_data: str = Field(min_length=32, max_length=4_200_000)
    event_id: UUID | None = None


def _evidence_root() -> Path:
    configured = os.getenv("PROCTORING_EVIDENCE_DIR")
    root = Path(configured).expanduser() if configured else Path("private_proctoring_evidence")
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


@router.post("/sessions/{session_id}/evidence")
async def save_proctoring_evidence(
    session_id: UUID, data: EvidenceCaptureInput,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    candidate_id = UUID(user["id"])
    session = await database.scalar(select(ProctoringSession).where(
        ProctoringSession.id == session_id, ProctoringSession.candidate_id == candidate_id,
    ))
    if session is None or session.status not in {"ready", "active"}:
        raise HTTPException(status_code=404, detail="Active proctoring session not found.")
    assessment = await database.get(Assessment, session.assessment_id)
    if assessment is None or assessment.status not in {"assigned", "in_progress"}:
        raise HTTPException(status_code=409, detail="Evidence can only be saved during an active attempt.")
    description = None
    if data.event_id is not None:
        event = await database.scalar(select(ProctoringEvent).where(
            ProctoringEvent.id == data.event_id, ProctoringEvent.session_id == session.id,
        ))
        if event is None:
            raise HTTPException(status_code=400, detail="The associated violation was not found.")
        description = event.description
    try:
        header, encoded = data.image_data.split(",", 1)
        if header not in {"data:image/jpeg;base64", "data:image/png;base64"}:
            raise ValueError
        image_format = "jpg" if "jpeg" in header else "png"
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="Evidence must be a JPEG or PNG image.")
    valid_signature = image_bytes.startswith(b"\xff\xd8\xff") if image_format == "jpg" else image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if not valid_signature:
        raise HTTPException(status_code=400, detail="The evidence image is invalid.")
    if len(image_bytes) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Evidence images must be smaller than 3 MB.")
    evidence_id = __import__("uuid").uuid4()
    path = _evidence_root() / f"{evidence_id}.{image_format}"
    try:
        await asyncio.to_thread(path.write_bytes, image_bytes)
        path.chmod(0o600)
        evidence = ProctoringEvidence(
            id=evidence_id, session_id=session.id, assessment_id=assessment.id,
            candidate_id=candidate_id, recruiter_id=assessment.recruiter_id, event_id=data.event_id,
            capture_type=data.capture_type, storage_path=path.name,
            storage_key=str(evidence_id), format=image_format, description=description,
            captured_at=datetime.now(timezone.utc),
        )
        database.add(evidence)
        await database.commit()
    except Exception:
        await database.rollback()
        path.unlink(missing_ok=True)
        logger.exception("Could not persist proctoring evidence %s", evidence_id)
        raise HTTPException(status_code=500, detail="Evidence could not be saved securely.")
    return {"id": str(evidence.id), "captured_at": evidence.captured_at.isoformat()}


@router.get("/assessments/{assessment_id}/evidence")
async def list_assessment_evidence(
    assessment_id: UUID, user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = UUID(user["id"])
    assessment = await database.scalar(select(Assessment).where(
        Assessment.id == assessment_id, Assessment.recruiter_id == recruiter_id,
    ))
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    events = (await database.scalars(select(ProctoringEvent).join(
        ProctoringSession, ProctoringSession.id == ProctoringEvent.session_id,
    ).where(ProctoringSession.assessment_id == assessment.id).order_by(ProctoringEvent.occurred_at.asc()))).all()
    evidence_rows = (await database.scalars(select(ProctoringEvidence).where(
        ProctoringEvidence.assessment_id == assessment.id, ProctoringEvidence.recruiter_id == recruiter_id,
    ).order_by(ProctoringEvidence.captured_at.asc()))).all()
    return {
        "false_actions": sum(1 for event in events if event.severity == "warning"),
        "events": [{"id": str(event.id), "event_type": event.event_type, "severity": event.severity, "description": event.description, "occurred_at": event.occurred_at.isoformat()} for event in events],
        "evidence": [{"id": str(item.id), "capture_type": item.capture_type, "captured_at": item.captured_at.isoformat(), "description": item.description, "event_id": str(item.event_id) if item.event_id else None, "image_path": f"/proctoring/evidence/{item.id}/image"} for item in evidence_rows],
    }


@router.get("/evidence/{evidence_id}/image")
async def get_proctoring_evidence_image(
    evidence_id: UUID, user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    item = await database.scalar(select(ProctoringEvidence).where(
        ProctoringEvidence.id == evidence_id, ProctoringEvidence.recruiter_id == UUID(user["id"]),
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence image not found.")
    root = _evidence_root().resolve()
    path = (root / item.storage_path).resolve()
    if not path.is_file() or path.parent != root:
        raise HTTPException(status_code=404, detail="Evidence image is no longer available.")
    return FileResponse(path, media_type="image/jpeg" if item.format == "jpg" else "image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/admin/sessions")
async def list_proctoring_sessions(
    user: dict = Depends(admin_required),
    database: AsyncSession = Depends(get_database),
):
    rows = (
        await database.execute(
            select(
                ProctoringSession,
                User.full_name,
                User.email,
                Assessment.title,
                Assessment.status,
            )
            .join(User, User.id == ProctoringSession.candidate_id)
            .join(Assessment, Assessment.id == ProctoringSession.assessment_id)
            .order_by(ProctoringSession.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "sessions": [
            {
                "id": str(session.id),
                "candidate_name": candidate_name,
                "candidate_email": candidate_email,
                "assessment_title": title,
                "assessment_status": assessment_status,
                "status": session.status,
                "warning_count": session.warning_count,
                "is_flagged": session.is_flagged,
                "created_at": session.created_at.isoformat(),
            }
            for session, candidate_name, candidate_email, title, assessment_status in rows
        ]
    }


@router.get("/admin/sessions/{session_id}")
async def get_proctoring_session(
    session_id: UUID,
    user: dict = Depends(admin_required),
    database: AsyncSession = Depends(get_database),
):
    row = await database.execute(
        select(
            ProctoringSession,
            User.full_name,
            User.email,
            Assessment.title,
            Assessment.status,
        )
        .join(User, User.id == ProctoringSession.candidate_id)
        .join(Assessment, Assessment.id == ProctoringSession.assessment_id)
        .where(ProctoringSession.id == session_id)
    )
    result = row.one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Proctoring session not found.")

    session, candidate_name, candidate_email, title, assessment_status = result
    events = (
        await database.scalars(
            select(ProctoringEvent)
            .where(ProctoringEvent.session_id == session.id)
            .order_by(ProctoringEvent.occurred_at.asc())
        )
    ).all()
    return {
        "id": str(session.id),
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "assessment_title": title,
        "assessment_status": assessment_status,
        "status": session.status,
        "warning_count": session.warning_count,
        "is_flagged": session.is_flagged,
        "admin_notes": session.admin_notes,
        "consented_at": session.consented_at.isoformat(),
        "camera_permission_at": session.camera_permission_at.isoformat(),
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "events": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "severity": event.severity,
                "description": event.description,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in events
        ],
    }


@router.put("/admin/sessions/{session_id}")
async def review_proctoring_session(
    session_id: UUID,
    data: SessionReviewInput,
    user: dict = Depends(admin_required),
    database: AsyncSession = Depends(get_database),
):
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No review changes were provided.")

    session = await database.scalar(
        select(ProctoringSession)
        .where(ProctoringSession.id == session_id)
        .with_for_update()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Proctoring session not found.")
    if "is_flagged" in changes:
        session.is_flagged = bool(changes["is_flagged"])
    if "notes" in changes:
        session.admin_notes = changes["notes"]
    session.updated_at = datetime.now(timezone.utc)
    await database.commit()
    return {
        "id": str(session.id),
        "is_flagged": session.is_flagged,
        "admin_notes": session.admin_notes,
    }


# Round 1 assessment recordings use private Cloudinary authenticated assets.
def _recording_payload(recording: AssessmentRecording | None):
    if recording is None:
        return {"recording": None}
    return {"recording": {
        "id": str(recording.id),
        "assessment_id": str(recording.assessment_id),
        "recording_type": recording.recording_type,
        "upload_status": recording.upload_status,
        "format": recording.format,
        "duration": recording.duration,
        "file_size": recording.file_size,
        "upload_error": recording.upload_error,
        "created_at": recording.created_at.isoformat() if recording.created_at else None,
        "uploaded_at": recording.uploaded_at.isoformat() if recording.uploaded_at else None,
    }}


@router.post("/assessments/{assessment_id}/recording/start")
async def start_round1_recording(
    assessment_id: UUID,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    candidate_id = UUID(user["id"])
    assessment = await database.scalar(
        select(Assessment).where(
            Assessment.id == assessment_id, Assessment.candidate_id == candidate_id,
        )
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if assessment.status not in {"in_progress", "submitted", "passed", "failed", "expired"}:
        raise HTTPException(status_code=409, detail="The assessment attempt is not available for recording upload.")
    consent = await database.scalar(
        select(ProctoringSession.id).where(
            ProctoringSession.assessment_id == assessment.id,
            ProctoringSession.candidate_id == candidate_id,
            ProctoringSession.status.in_(["active", "completed"]),
            ProctoringSession.recording_consented_at.is_not(None),
        )
    )
    if consent is None:
        raise HTTPException(status_code=403, detail="Recording consent is required.")
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.assessment_id == assessment.id,
            AssessmentRecording.recording_type == "ROUND_1",
        ).with_for_update()
    )
    if recording is None:
        recording = AssessmentRecording(
            assessment_id=assessment.id, candidate_id=candidate_id,
            recruiter_id=assessment.recruiter_id, application_id=assessment.application_id,
            job_id=assessment.job_id, recording_type="ROUND_1",
            cloudinary_public_id=f"skillsphere/round1/{assessment.id}",
            upload_status="recording",
        )
        database.add(recording)
        await database.commit()
        await database.refresh(recording)
    return _recording_payload(recording)["recording"]


@router.post("/recordings/{recording_id}/signature")
async def sign_round1_upload(
    recording_id: UUID,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.id == recording_id,
            AssessmentRecording.candidate_id == UUID(user["id"]),
        ).with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.upload_status == "uploaded":
        return {"already_uploaded": True, **_recording_payload(recording)["recording"]}
    assessment = await database.get(Assessment, recording.assessment_id)
    if assessment is None or assessment.status not in {"in_progress", "submitted", "passed", "failed", "expired"}:
        raise HTTPException(status_code=409, detail="This assessment recording cannot be uploaded yet.")
    timestamp = int(time.time())
    try:
        signature = signed_upload_parameters(recording.cloudinary_public_id, timestamp)
    except CloudinaryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not sign Cloudinary upload parameters")
        raise HTTPException(status_code=503, detail="Video upload is temporarily unavailable.") from exc
    recording.upload_status = "uploading"
    recording.upload_error = None
    await database.commit()
    from app.config import settings
    return {
        "cloud_name": settings.cloudinary_cloud_name,
        "api_key": settings.cloudinary_api_key,
        "timestamp": timestamp,
        "signature": signature,
        "public_id": recording.cloudinary_public_id,
        "type": "authenticated",
        "resource_type": "video",
    }


class RecordingUploadResult(BaseModel):
    public_id: str = Field(min_length=1, max_length=500)
    asset_id: str = Field(min_length=1, max_length=100)


@router.post("/recordings/{recording_id}/complete")
async def complete_round1_upload(
    recording_id: UUID,
    data: RecordingUploadResult,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.id == recording_id,
            AssessmentRecording.candidate_id == UUID(user["id"]),
        ).with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.upload_status == "uploaded":
        return _recording_payload(recording)["recording"]
    if data.public_id != recording.cloudinary_public_id:
        raise HTTPException(status_code=400, detail="Uploaded asset does not match this assessment.")
    try:
        resource = await asyncio.to_thread(fetch_video_resource, recording.cloudinary_public_id)
    except CloudinaryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Cloudinary did not confirm round 1 asset %s", recording.id)
        raise HTTPException(status_code=502, detail="Cloudinary could not confirm the uploaded video.") from exc
    if resource.get("asset_id") != data.asset_id or resource.get("public_id") != recording.cloudinary_public_id:
        raise HTTPException(status_code=400, detail="Cloudinary asset verification failed.")
    recording.cloudinary_asset_id = resource["asset_id"]
    recording.resource_type = resource.get("resource_type", "video")
    recording.delivery_type = "authenticated"
    recording.format = resource.get("format")
    recording.duration = resource.get("duration")
    recording.file_size = resource.get("bytes")
    recording.upload_status = "uploaded"
    recording.upload_error = None
    recording.uploaded_at = datetime.now(timezone.utc)
    recording.updated_at = recording.uploaded_at
    await database.commit()
    await database.refresh(recording)
    return _recording_payload(recording)["recording"]


class RecordingUploadFailure(BaseModel):
    message: str = Field(default="Video upload failed. The local recording is available to retry.", max_length=500)


@router.post("/recordings/{recording_id}/failed")
async def fail_round1_upload(
    recording_id: UUID,
    data: RecordingUploadFailure,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.id == recording_id,
            AssessmentRecording.candidate_id == UUID(user["id"]),
        ).with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.upload_status != "uploaded":
        recording.upload_status = "failed"
        recording.upload_error = data.message.strip()[:1000]
        recording.updated_at = datetime.now(timezone.utc)
        await database.commit()
    return _recording_payload(recording)["recording"]


@router.get("/assessments/{assessment_id}/recording")
async def get_round1_recording(
    assessment_id: UUID,
    user: dict = Depends(get_current_user),
    database: AsyncSession = Depends(get_database),
):
    assessment = await database.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if user["role"] == "candidate" and assessment.candidate_id == UUID(user["id"]):
        pass
    elif user["role"] == "recruiter" and assessment.recruiter_id == UUID(user["id"]):
        pass
    else:
        raise HTTPException(status_code=403, detail="You cannot access this recording.")
    recording = await database.scalar(
        select(AssessmentRecording).where(AssessmentRecording.assessment_id == assessment.id)
    )
    return _recording_payload(recording)


@router.get("/recordings/{recording_id}/playback")
async def get_round1_playback_url(
    recording_id: UUID,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.id == recording_id,
            AssessmentRecording.recruiter_id == UUID(user["id"]),
        )
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.upload_status != "uploaded" or not recording.format:
        raise HTTPException(status_code=409, detail="This recording is not ready to play.")
    try:
        url = await asyncio.to_thread(
            signed_video_download_url, recording.cloudinary_public_id,
            recording.format, int(time.time()) + 300,
        )
    except CloudinaryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not create temporary playback link for recording %s", recording.id)
        raise HTTPException(status_code=503, detail="Video playback is temporarily unavailable.") from exc
    return {"playback_url": url, "expires_in_seconds": 300}


@router.delete("/recordings/{recording_id}")
async def delete_round1_recording(
    recording_id: UUID,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recording = await database.scalar(
        select(AssessmentRecording).where(
            AssessmentRecording.id == recording_id,
            AssessmentRecording.recruiter_id == UUID(user["id"]),
        ).with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found.")
    if recording.upload_status == "uploaded":
        try:
            result = await asyncio.to_thread(delete_video_resource, recording.cloudinary_public_id)
        except CloudinaryUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Could not delete Cloudinary recording %s", recording.id)
            raise HTTPException(status_code=502, detail="Cloudinary could not delete the recording.") from exc
        if result.get("result") not in {"ok", "not found"}:
            raise HTTPException(status_code=502, detail="Cloudinary did not confirm recording deletion.")
    await database.delete(recording)
    await database.commit()
    return {"deleted": True}
