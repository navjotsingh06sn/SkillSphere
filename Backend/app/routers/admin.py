from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import USERS, JOBS, APPLICATIONS, CANDIDATE_PROFILES, RECRUITER_PROFILES, COMPANIES
from app.dependencies import admin_required, get_database
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/admin", tags=["admin"])


async def monthly_counts(
    collection,
    date_field: str,
    filters: dict | None = None,
) -> list[dict]:
    cursor = await collection.aggregate([
        {"$match": {
            **(filters or {}),
            date_field: {"$type": "date"},
        }},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$" + date_field}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 6},
    ])
    results = [{"month": item["_id"], "count": item["count"]} async for item in cursor]
    return list(reversed(results))


@router.get("/analytics")
async def analytics(user: dict = Depends(admin_required), database: AsyncDatabase = Depends(get_database)):
    users = database[USERS]
    jobs = database[JOBS]
    return {
        "total_users": await users.count_documents({}),
        "total_candidates": await users.count_documents({"role": "candidate"}),
        "total_recruiters": await users.count_documents({"role": "recruiter"}),
        "total_companies": await database[COMPANIES].count_documents({}),
        "total_jobs": await jobs.count_documents({"is_demo": {"$ne": True}}),
        "active_jobs": await jobs.count_documents({
            "status": "published",
            "is_demo": {"$ne": True},
        }),
        "total_applications": await database[APPLICATIONS].count_documents({}),
        "users_by_role": [
            {"role": role, "count": await users.count_documents({"role": role})}
            for role in ["candidate", "recruiter", "admin"]
        ],
        "user_growth": await monthly_counts(users, "created_at"),
        "job_posting_trends": await monthly_counts(
            jobs,
            "created_at",
            {"is_demo": {"$ne": True}},
        ),
        "application_trends": await monthly_counts(database[APPLICATIONS], "applied_at"),
    }


@router.get("/users")
async def list_users(
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(admin_required),
    database: AsyncDatabase = Depends(get_database),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    cursor = database[USERS].find({}, {"password_hash": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    return {
        "items": [serialize_document(item) async for item in cursor],
        "total": await database[USERS].count_documents({}),
        "page": page,
    }


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: str,
    data: dict,
    user: dict = Depends(admin_required),
    database: AsyncDatabase = Depends(get_database),
):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    if not isinstance(data.get("is_active"), bool):
        raise HTTPException(status_code=422, detail="is_active must be true or false.")
    result = await database[USERS].update_one(
        {"_id": parse_object_id(user_id, "user id")},
        {"$set": {"is_active": data["is_active"]}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User was not found.")
    return {"is_active": data["is_active"]}


@router.get("/jobs")
async def admin_jobs(user: dict = Depends(admin_required), database: AsyncDatabase = Depends(get_database)):
    cursor = database[JOBS].find({}).sort("created_at", -1).limit(200)
    return [serialize_document(job) async for job in cursor]


@router.put("/jobs/{job_id}/status")
async def moderate_job(
    job_id: str,
    data: dict,
    user: dict = Depends(admin_required),
    database: AsyncDatabase = Depends(get_database),
):
    new_status = data.get("status")
    if new_status not in {"draft", "published", "closed", "rejected"}:
        raise HTTPException(status_code=422, detail="Unsupported job status.")
    oid = parse_object_id(job_id, "job id")
    result = await database[JOBS].update_one(
        {"_id": oid},
        {"$set": {
            "status": new_status,
            "moderated_by": ObjectId(user["id"]),
            "moderated_at": datetime.now(timezone.utc),
        }},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Job was not found.")
    return {"status": new_status}

@router.get("/companies")
async def admin_companies(
    user: dict = Depends(admin_required),
    database: AsyncDatabase = Depends(get_database),
):
    cursor = database[COMPANIES].find({}).sort("created_at", -1).limit(500)
    return [serialize_document(item) async for item in cursor]

