
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_database
from app.models import (
    Application,
    Assessment,
    Interview,
    Job,
    Notification,
)
from app.pg_utils import parse_uuid, serialize_model

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")

    notifs_res = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_uuid)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )

    notifications = notifs_res.scalars().all()

    items = []

    for notification in notifications:
        item = serialize_model(notification)
        related_id = notification.related_id
        job_id = notification.job_id

        notif_type = notification.type or ""

        if notif_type.startswith("assessment"):
            if related_id:
                ass_cond = (
                    Assessment.candidate_id == user_uuid
                    if user["role"] == "candidate"
                    else Assessment.recruiter_id == user_uuid
                )

                ass_res = await db.execute(
                    select(Assessment).where(
                        Assessment.id == related_id,
                        ass_cond,
                    )
                )

                assessment = ass_res.scalar_one_or_none()

                if assessment:
                    item["assessment_id"] = str(assessment.id)

                    item["related_url"] = (
                        f"/candidate/assessments/{assessment.id}"
                        if user["role"] == "candidate"
                        else f"/recruiter/assessments/{assessment.id}"
                    )

                    job_id = assessment.job_id

        elif notif_type.startswith("interview"):
            if related_id:
                int_cond = (
                    Interview.candidate_id == user_uuid
                    if user["role"] == "candidate"
                    else Interview.recruiter_id == user_uuid
                )

                int_res = await db.execute(
                    select(Interview).where(
                        Interview.id == related_id,
                        int_cond,
                    )
                )

                interview = int_res.scalar_one_or_none()

                if interview:
                    item["application_id"] = str(
                        interview.application_id
                    )

                    item["related_url"] = (
                        "/candidate/interviews"
                        if user["role"] == "candidate"
                        else "/recruiter/interviews"
                    )

                    job_id = interview.job_id

        else:
            if related_id:
                app_cond = (
                    Application.candidate_id == user_uuid
                    if user["role"] == "candidate"
                    else Application.recruiter_id == user_uuid
                )

                app_res = await db.execute(
                    select(Application).where(
                        Application.id == related_id,
                        app_cond,
                    )
                )

                application = app_res.scalar_one_or_none()

                if application:
                    item["application_id"] = str(application.id)

                    item["related_url"] = (
                        f"/candidate/applications/{application.id}"
                        if user["role"] == "candidate"
                        else f"/recruiter/applicants/{application.id}"
                    )

                    job_id = application.job_id

        if job_id:
            job_res = await db.execute(
                select(Job.title).where(Job.id == job_id)
            )

            job_title = job_res.scalar_one_or_none()

            if job_title:
                item["job_title"] = job_title

        items.append(item)

    unread_res = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_uuid,
            Notification.is_read.is_(False),
        )
    )

    unread = unread_res.scalar() or 0

    return {
        "items": items,
        "unread_count": unread,
    }


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    notif_uuid = parse_uuid(notification_id, "notification id")
    user_uuid = parse_uuid(user["id"], "user id")

    res = await db.execute(
        select(Notification).where(
            Notification.id == notif_uuid,
            Notification.user_id == user_uuid,
        )
    )

    notification = res.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification was not found.",
        )

    notification.is_read = True
    notification.read_at = datetime.now(timezone.utc)

    await db.commit()

    return {"is_read": True}
