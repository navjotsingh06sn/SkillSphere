
import html
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.models import (
    Application,
    Interview,
    Job,
    Notification,
    User,
)
from app.pg_utils import parse_uuid, serialize_model
from app.services.smtp import EmailDeliveryError, send_smtp_email
from app.schemas import (
    InterviewRescheduleInput,
    InterviewResponseInput,
    InterviewScheduleInput,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])
logger = logging.getLogger("uvicorn.error")


def interview_room_url(interview_id: UUID) -> str:
    return (
        f"{settings.frontend_url.rstrip('/')}/candidate/interviews/"
        f"{interview_id}/room"
    )


def validate_interview_eligibility(application: Application) -> None:
    # Selection is the recruiter decision that unlocks interview scheduling.
    # Assessment screening is optional and must not block this workflow.
    if application.status not in ("selected", "shortlisted"):
        raise HTTPException(
            status_code=409,
            detail="Select the candidate before scheduling an interview.",
        )


def validate_future_datetime(value: datetime):
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="Please provide a timezone-aware interview date and time.",
        )

    if value <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail="Interview date and time must be in the future.",
        )


def format_interview_doc(interview: Interview | None) -> dict:
    if interview is None:
        return {}

    doc = serialize_model(interview)
    # Legacy links remain stored for migration safety, but rooms never redirect externally.
    doc.pop("meeting_link", None)
    extra = interview.extra_data or {}

    for key, value in extra.items():
        if key not in doc or doc[key] is None:
            doc[key] = value

    return doc


async def notify_user(
    db: AsyncSession,
    user_id: UUID,
    notification_type: str,
    message: str,
    interview_id: UUID,
    job_id: UUID | None = None,
):
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        message=message,
        related_id=interview_id,
        job_id=job_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )

    db.add(notification)


async def deliver_interview_email(
    db: AsyncSession,
    interview_id: UUID,
    event: str,
) -> Interview:
    interview = await db.scalar(
        select(Interview)
        .where(Interview.id == interview_id)
        .with_for_update()
    )
    if not interview:
        raise RuntimeError("Interview disappeared before email delivery.")
    if interview.email_status in {"sent", "sending"}:
        raise HTTPException(
            status_code=409,
            detail="This interview email has already been sent or is being delivered.",
        )
    if interview.email_status not in {"pending", "failed"}:
        raise HTTPException(
            status_code=409,
            detail="This interview email is not available for delivery.",
        )

    interview.email_status = "sending"
    interview.email_attempts += 1
    interview.email_error = None
    interview.email_message_id = None
    interview.email_sent_at = None
    interview.updated_at = datetime.now(timezone.utc)
    extra = dict(interview.extra_data or {})
    extra["last_email_event"] = event
    interview.extra_data = extra

    await db.commit()
    await db.refresh(interview)

    candidate = await db.scalar(
        select(User).where(User.id == interview.candidate_id)
    )
    job = await db.scalar(select(Job).where(Job.id == interview.job_id))
    if not candidate or not candidate.email:
        delivery_error = EmailDeliveryError(
            "The candidate does not have a deliverable email address."
        )
    else:
        job_title = job.title if job else "your role"
        scheduled_at = (
            interview.scheduled_at.isoformat()
            if interview.scheduled_at
            else "Not specified"
        )
        event_titles = {
            "scheduled": "Interview invitation",
            "rescheduled": "Interview schedule updated",
            "cancelled": "Interview cancelled",
        }
        title = event_titles[event]
        mode = (extra.get("mode") or "in_platform").casefold()
        details = (
            f"Location: {interview.location}"
            if mode == "offline" and interview.location
            else
            f"Join your interview room in SkillSphere: "
            f"{interview_room_url(interview.id)}"
        )
        notes = interview.notes or ""
        text_content = (
            f"Hello {candidate.full_name or 'there'},\n\n"
            f"{title} for {job_title}.\n"
            f"Date and time: {scheduled_at}\n"
            f"Duration: {extra.get('duration_minutes', 30)} minutes\n"
            f"{details}\n"
            + (f"\nNotes: {notes}\n" if notes else "")
            + "\nRegards,\nSkillSphere"
        )
        html_content = (
            f"<p>Hello {html.escape(candidate.full_name or 'there')},</p>"
            f"<p>{html.escape(title)} for "
            f"<strong>{html.escape(job_title)}</strong>.</p>"
            f"<p><strong>Date and time:</strong> {html.escape(scheduled_at)}<br>"
            f"<strong>Duration:</strong> {int(extra.get('duration_minutes', 30))} minutes</p>"
            f"<p>{html.escape(details)}</p>"
            + (
                f"<p><strong>Notes:</strong> {html.escape(notes)}</p>"
                if notes
                else ""
            )
            + "<p>Regards,<br>SkillSphere</p>"
        )
        try:
            message_id = await send_smtp_email(
                candidate.email,
                f"{title}: {job_title}",
                text_content,
                html_content,
            )
        except EmailDeliveryError as exc:
            delivery_error = exc
        else:
            interview.email_status = "sent"
            interview.email_message_id = message_id
            interview.email_sent_at = datetime.now(timezone.utc)
            interview.email_error = None
            await db.commit()
            await db.refresh(interview)
            return interview

    interview.email_status = "failed"
    interview.email_error = str(delivery_error)[:2000]
    logger.warning(
        "Interview email delivery failed for interview %s: %s",
        interview.id,
        delivery_error,
    )
    await db.commit()
    await db.refresh(interview)
    return interview


@router.post(
    "/applications/{application_id}",
    status_code=status.HTTP_201_CREATED,
)
async def schedule_interview(
    application_id: str,
    data: InterviewScheduleInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    validate_future_datetime(data.scheduled_at)

    result = await db.execute(
        select(Application).where(
            Application.id == app_uuid,
            Application.recruiter_id == recruiter_uuid,
        )
    )
    application = result.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    validate_interview_eligibility(application)

    if data.mode == "offline" and not data.location:
        raise HTTPException(
            status_code=422,
            detail="A location is required for an offline interview.",
        )

    if data.mode == "online" and not data.meeting_link:
        raise HTTPException(
            status_code=422,
            detail="A meeting link is required for an online interview.",
        )

    if data.mode == "offline" and data.meeting_link:
        raise HTTPException(
            status_code=422,
            detail="Use a location instead of a meeting link for an offline interview.",
        )

    active_result = await db.execute(
        select(Interview).where(
            Interview.application_id == app_uuid,
            Interview.status == "scheduled",
        )
    )

    if active_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="This application already has a scheduled interview.",
        )

    now = datetime.now(timezone.utc)

    interview = Interview(
        application_id=app_uuid,
        candidate_id=application.candidate_id,
        recruiter_id=application.recruiter_id,
        job_id=application.job_id,
        interview_type=data.interview_type,
        scheduled_at=data.scheduled_at,
        location=data.location,
        meeting_link=data.meeting_link if data.mode == "online" else None,
        status="scheduled",
        candidate_response="pending",
        notes=data.notes,
        extra_data={
            "duration_minutes": data.duration_minutes,
            "mode": data.mode,
            "status_before_interview": application.status or "applied",
        },
        created_at=now,
        updated_at=now,
    )

    db.add(interview)
    await db.flush()

    application.status = "interview"
    application.updated_at = now

    job_result = await db.execute(
        select(Job).where(Job.id == application.job_id)
    )
    job = job_result.scalar_one_or_none()
    job_title = job.title if job else "the job"

    await notify_user(
        db,
        application.candidate_id,
        "interview_scheduled",
        (
            f"Your {data.interview_type} interview for {job_title} "
            f"has been scheduled for {data.scheduled_at.isoformat()}."
        ),
        interview.id,
        application.job_id,
    )

    await db.commit()
    await db.refresh(interview)
    interview = await deliver_interview_email(db, interview.id, "scheduled")

    return format_interview_doc(interview)


@router.get("")
async def list_interviews(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")

    conditions = []

    if user["role"] == "candidate":
        conditions.append(Interview.candidate_id == user_uuid)

    elif user["role"] == "recruiter":
        conditions.append(Interview.recruiter_id == user_uuid)

    stmt = (
        select(Interview, Job)
        .outerjoin(Job, Interview.job_id == Job.id)
        .where(*conditions)
        .order_by(Interview.scheduled_at.asc())
    )

    rows = (await db.execute(stmt)).all()

    interviews = []

    for interview, job in rows:
        item = format_interview_doc(interview)
        if user["role"] == "candidate":
            item.pop("email_status", None)
            item.pop("email_message_id", None)
            item.pop("email_error", None)
            item.pop("email_attempts", None)
        item["job"] = serialize_model(job)
        interviews.append(item)

    return interviews


@router.get("/{interview_id}")
async def get_interview(
    interview_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    int_uuid = parse_uuid(interview_id, "interview id")
    user_uuid = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(Interview).where(Interview.id == int_uuid)
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )

    if (
        user["role"] == "candidate"
        and interview.candidate_id != user_uuid
    ):
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )

    if (
        user["role"] == "recruiter"
        and interview.recruiter_id != user_uuid
    ):
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )

    item = format_interview_doc(interview)
    if user["role"] == "candidate":
        item.pop("email_status", None)
        item.pop("email_message_id", None)
        item.pop("email_error", None)
        item.pop("email_attempts", None)
    return item


@router.put("/{interview_id}/response")
async def respond_to_interview(
    interview_id: str,
    data: InterviewResponseInput,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    int_uuid = parse_uuid(interview_id, "interview id")
    user_uuid = parse_uuid(user["id"], "user id")
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Interview).where(
            Interview.id == int_uuid,
            Interview.candidate_id == user_uuid,
            Interview.status == "scheduled",
        )
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    interview.candidate_response = data.response

    extra = dict(interview.extra_data or {})
    extra["candidate_responded_at"] = now.isoformat()

    interview.extra_data = extra
    interview.updated_at = now

    await notify_user(
        db,
        interview.recruiter_id,
        "interview_response",
        f"The candidate has {data.response} the interview invitation.",
        int_uuid,
        interview.job_id,
    )

    await db.commit()

    return {
        "message": f"Interview invitation {data.response}.",
        "candidate_response": data.response,
    }


@router.put("/{interview_id}/reschedule")
async def reschedule_interview(
    interview_id: str,
    data: InterviewRescheduleInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    int_uuid = parse_uuid(interview_id, "interview id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    validate_future_datetime(data.scheduled_at)

    result = await db.execute(
        select(Interview)
        .where(
            Interview.id == int_uuid,
            Interview.recruiter_id == recruiter_uuid,
            Interview.status == "scheduled",
        )
        .with_for_update()
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    now = datetime.now(timezone.utc)
    extra = dict(interview.extra_data or {})

    mode = data.mode or extra.get("mode", "online")

    meeting_link = (
        data.meeting_link
        if data.meeting_link is not None
        else interview.meeting_link
    )

    location = (
        data.location
        if data.location is not None
        else interview.location
    )

    if mode == "online" and not meeting_link:
        raise HTTPException(
            status_code=422,
            detail="A meeting link is required for an online interview.",
        )

    if mode == "offline" and not location:
        raise HTTPException(
            status_code=422,
            detail="A location is required for an offline interview.",
        )

    interview.scheduled_at = data.scheduled_at
    interview.meeting_link = meeting_link if mode == "online" else None
    interview.location = location if mode == "offline" else None
    interview.candidate_response = "pending"
    interview.updated_at = now

    if data.notes is not None:
        interview.notes = data.notes

    extra["mode"] = mode
    interview.email_status = "pending"
    interview.email_message_id = None
    interview.email_error = None
    interview.email_sent_at = None

    if data.duration_minutes is not None:
        extra["duration_minutes"] = data.duration_minutes

    interview.extra_data = extra

    await notify_user(
        db,
        interview.candidate_id,
        "interview_rescheduled",
        (
            "Your interview has been rescheduled to "
            f"{data.scheduled_at.isoformat()}."
        ),
        int_uuid,
        interview.job_id,
    )

    await db.commit()
    await db.refresh(interview)
    interview = await deliver_interview_email(
        db,
        interview.id,
        "rescheduled",
    )

    return {
        "message": "Interview rescheduled successfully.",
        "scheduled_at": data.scheduled_at,
        "email_status": interview.email_status,
        "email_error": interview.email_error,
    }


@router.put("/{interview_id}/cancel")
async def cancel_interview(
    interview_id: str,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    int_uuid = parse_uuid(interview_id, "interview id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Interview)
        .where(
            Interview.id == int_uuid,
            Interview.recruiter_id == recruiter_uuid,
            Interview.status == "scheduled",
        )
        .with_for_update()
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    interview.status = "cancelled"
    interview.updated_at = now
    interview.email_status = "pending"
    interview.email_message_id = None
    interview.email_error = None
    interview.email_sent_at = None

    extra = interview.extra_data or {}
    status_before = extra.get(
        "status_before_interview",
        "shortlisted",
    )

    app_result = await db.execute(
        select(Application).where(
            Application.id == interview.application_id,
            Application.status == "interview",
        )
    )
    application = app_result.scalar_one_or_none()

    if application:
        application.status = status_before
        application.updated_at = now

    await notify_user(
        db,
        interview.candidate_id,
        "interview_cancelled",
        "Your interview has been cancelled by the recruiter.",
        int_uuid,
        interview.job_id,
    )

    await db.commit()
    await db.refresh(interview)
    interview = await deliver_interview_email(
        db,
        interview.id,
        "cancelled",
    )

    return {
        "message": "Interview cancelled successfully.",
        "email_status": interview.email_status,
        "email_error": interview.email_error,
    }


@router.post("/{interview_id}/email/resend")
async def resend_interview_email(
    interview_id: str,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    int_uuid = parse_uuid(interview_id, "interview id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")
    interview = await db.scalar(
        select(Interview)
        .where(
            Interview.id == int_uuid,
            Interview.recruiter_id == recruiter_uuid,
        )
        .with_for_update()
    )
    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )
    if interview.email_status != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only failed interview emails can be resent.",
        )

    event = (interview.extra_data or {}).get("last_email_event")
    if event not in {"scheduled", "rescheduled", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="The failed email event cannot be identified for a safe resend.",
        )

    await db.commit()
    interview = await deliver_interview_email(db, interview.id, event)
    return {
        "message": "Interview email resend attempted.",
        "email_status": interview.email_status,
        "email_error": interview.email_error,
    }
