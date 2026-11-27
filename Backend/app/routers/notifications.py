
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user,
    get_database,
)
from app.models import Application, Job, Notification, User
from app.pg_utils import parse_uuid, serialize_model

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
)


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_id = parse_uuid(user["id"], "user id")

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 1 and 100.",
        )

    if offset < 0:
        raise HTTPException(
            status_code=422,
            detail="Offset cannot be negative.",
        )

    conditions = [Notification.user_id == user_id]

    if unread_only:
        conditions.append(Notification.is_read.is_(False))

    result = await db.execute(
        select(Notification, Job.title, Application.id, User.full_name)
        .outerjoin(Job, Job.id == Notification.job_id)
        .outerjoin(Application, Application.id == Notification.related_id)
        .outerjoin(User, User.id == Application.candidate_id)
        .where(*conditions)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()
    payloads = []
    for notification, job_title, application_id, candidate_name in rows:
        item = serialize_model(notification)
        if job_title:
            item["job_title"] = job_title
        if notification.type == "new_application":
            item["candidate_name"] = candidate_name or "Candidate"
            item["application_time"] = notification.created_at.isoformat()
            if application_id is not None:
                item["related_url"] = f"/recruiter/applicants/{application_id}"
        elif user.get("role") == "candidate" and notification.type in {"interview_scheduled", "interview_room_started"} and notification.related_id:
            item["related_url"] = f"/candidate/interviews/{notification.related_id}/room"
        payloads.append(item)

    return {
        "notifications": payloads,
        "count": len(payloads),
        "limit": limit,
        "offset": offset,
    }


@router.get("/unread-count")
async def unread_notification_count(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_id = parse_uuid(user["id"], "user id")

    unread_count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )
    unread_applications = 0
    if user.get("role") == "recruiter":
        unread_applications = await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.type == "new_application",
                Notification.is_read.is_(False),
            )
        ) or 0

    return {"unread_count": unread_count or 0, "unread_applications": unread_applications}


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    notification_uuid = parse_uuid(
        notification_id,
        "notification id",
    )
    user_id = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_uuid,
            Notification.user_id == user_id,
        )
    )

    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification not found.",
        )

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "message": "Notification marked as read.",
        "notification": serialize_model(notification),
    }


@router.patch("/read-all")
async def mark_all_notifications_read(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_id = parse_uuid(user["id"], "user id")

    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )

    await db.commit()

    return {
        "message": "All notifications marked as read.",
        "updated_count": result.rowcount or 0,
    }


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    notification_uuid = parse_uuid(
        notification_id,
        "notification id",
    )
    user_id = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_uuid,
            Notification.user_id == user_id,
        )
    )

    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification not found.",
        )

    await db.delete(notification)
    await db.commit()

    return {"message": "Notification deleted successfully."}
