
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    APPLICATIONS,
    INTERVIEWS,
    JOBS,
    NOTIFICATIONS,
)
from app.dependencies import get_current_user, get_database
from app.utils import parse_object_id, serialize_document


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    query = {
        "user_id": ObjectId(user["id"])
    }

    cursor = (
        database[NOTIFICATIONS]
        .find(query)
        .sort("created_at", -1)
        .limit(50)
    )

    items = []
    async for notification in cursor:
        item = serialize_document(notification)
        related_id = notification.get("related_id")

        if notification.get("type", "").startswith("interview"):
            interview = await database[INTERVIEWS].find_one({
                "_id": related_id,
                "candidate_id" if user["role"] == "candidate" else "recruiter_id": ObjectId(user["id"]),
            }) if related_id else None
            if interview:
                item["application_id"] = str(interview["application_id"])
                item["related_url"] = (
                    "/candidate/interviews"
                    if user["role"] == "candidate"
                    else "/recruiter/interviews"
                )
                job_id = interview["job_id"]
            else:
                job_id = notification.get("job_id")
        else:
            application = await database[APPLICATIONS].find_one({
                "_id": related_id,
                "candidate_id" if user["role"] == "candidate" else "recruiter_id": ObjectId(user["id"]),
            }) if related_id else None
            job_id = application["job_id"] if application else notification.get("job_id")
            if application:
                item["application_id"] = str(application["_id"])
                item["related_url"] = (
                    f"/candidate/applications/{application['_id']}"
                    if user["role"] == "candidate"
                    else f"/recruiter/applicants/{application['_id']}"
                )

        if job_id:
            job = await database[JOBS].find_one({"_id": job_id}, {"title": 1})
            if job:
                item["job_title"] = job.get("title")
        items.append(item)

    unread = await database[NOTIFICATIONS].count_documents({
        **query,
        "is_read": False,
    })

    return {
        "items": items,
        "unread_count": unread,
    }


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    result = await database[NOTIFICATIONS].update_one(
        {
            "_id": parse_object_id(
                notification_id,
                "notification id",
            ),
            "user_id": ObjectId(user["id"]),
        },
        {
            "$set": {
                "is_read": True,
                "read_at": datetime.now(timezone.utc),
            }
        },
    )

    if not result.matched_count:
        raise HTTPException(
            status_code=404,
            detail="Notification was not found.",
        )

    return {"is_read": True}
