from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import NOTIFICATIONS
from app.dependencies import get_current_user, get_database
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    query = {"user_id": ObjectId(user["id"])}
    cursor = database[NOTIFICATIONS].find(query).sort("created_at", -1).limit(50)
    items = [serialize_document(item) async for item in cursor]
    unread = await database[NOTIFICATIONS].count_documents({**query, "is_read": False})
    return {"items": items, "unread_count": unread}


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    result = await database[NOTIFICATIONS].update_one(
        {
            "_id": parse_object_id(notification_id, "notification id"),
            "user_id": ObjectId(user["id"]),
        },
        {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc)}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Notification was not found.")
    return {"is_read": True}
