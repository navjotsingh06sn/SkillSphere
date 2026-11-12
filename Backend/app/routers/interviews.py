
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.pg_utils import parse_uuid, serialize_model
from app.schemas import (
    InterviewRescheduleInput,
    InterviewResponseInput,
    InterviewScheduleInput,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])


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

    if application.status not in (
        "applied",
        "shortlisted",
        "under_review",
        "selected",
    ):
        raise HTTPException(
            status_code=409,
            detail="Only accepted or shortlisted applications can be scheduled for an interview.",
        )

    if (
        application.screening_status not in (
            "shortlisted",
            "pending_review",
        )
        and application.reconsideration_status != "requested"
    ):
        raise HTTPException(
            status_code=409,
            detail="This application is not eligible for interview scheduling.",
        )

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
        meeting_link=data.meeting_link,
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

    return format_interview_doc(interview)


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
        select(Interview).where(
            Interview.id == int_uuid,
            Interview.recruiter_id == recruiter_uuid,
            Interview.status == "scheduled",
        )
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

    return {
        "message": "Interview rescheduled successfully.",
        "scheduled_at": data.scheduled_at,
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
        select(Interview).where(
            Interview.id == int_uuid,
            Interview.recruiter_id == recruiter_uuid,
            Interview.status == "scheduled",
        )
    )
    interview = result.scalar_one_or_none()

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    interview.status = "cancelled"
    interview.updated_at = now

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

    return {
        "message": "Interview cancelled successfully."
    }
