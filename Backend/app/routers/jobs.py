import re
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import JOBS, RECRUITER_PROFILES, COMPANIES
from app.dependencies import get_database, recruiter_required, get_current_user
from app.schemas import JobInput
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    keyword: str | None = None,
    location: str | None = None,
    job_type: str | None = None,
    skill: str | None = None,
    min_salary: int | None = Query(default=None, ge=0),
    max_experience: int | None = Query(default=None, ge=0, le=60),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=50),
    sort: str = "newest",
    database: AsyncDatabase = Depends(get_database),
):
    query: dict = {"status": "published"}
    if keyword:
        query["$text"] = {"$search": keyword.strip()}
    if location:
        query["location"] = {"$regex": re.escape(location.strip()), "$options": "i"}
    if job_type:
        query["job_type"] = job_type
    if skill:
        query["required_skills"] = {"$regex": re.escape(skill.strip()), "$options": "i"}
    if min_salary is not None:
        query["$or"] = [
            {"salary_min": {"$gte": min_salary}},
            {"salary_max": {"$gte": min_salary}},
        ]
    if max_experience is not None:
        query["experience_min"] = {"$lte": max_experience}

    sort_field = "created_at"
    direction = 1 if sort == "oldest" else -1
    if sort in {"salary_high", "salary_low"}:
        sort_field = "salary_min"
        direction = -1 if sort == "salary_high" else 1

    total = await database[JOBS].count_documents(query)
    cursor = database[JOBS].find(query).sort(sort_field, direction).skip((page - 1) * page_size).limit(page_size)
    items = [serialize_document(item) async for item in cursor]
    return {"items": items, "page": page, "page_size": page_size, "total": total}

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    company = await database[COMPANIES].find_one({"recruiter_id": ObjectId(user["id"])})
    profile = await database[RECRUITER_PROFILES].find_one({"user_id": ObjectId(user["id"])})
    if not company:
        raise HTTPException(status_code=400, detail="Create your company profile before posting a job.")
    if data.experience_max and data.experience_max < data.experience_min:
        raise HTTPException(status_code=422, detail="Maximum experience must be at least the minimum.")
    job = data.model_dump()
    job.update({
        "recruiter_id": ObjectId(user["id"]),
        "company_id": company["_id"],
        "company_name": company["company_name"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    result = await database[JOBS].insert_one(job)
    job["_id"] = result.inserted_id
    return serialize_document(job)


@router.get("/{job_id}")
async def get_job(job_id: str, database: AsyncDatabase = Depends(get_database)):
    job = await database[JOBS].find_one({"_id": parse_object_id(job_id, "job id"), "status": "published"})
    if not job:
        raise HTTPException(status_code=404, detail="Job was not found.")
    return serialize_document(job)


@router.put("/{job_id}")
async def update_job(
    job_id: str,
    data: JobInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(job_id, "job id")
    job = await database[JOBS].find_one({"_id": oid, "recruiter_id": ObjectId(user["id"])})
    if not job:
        raise HTTPException(status_code=404, detail="Job was not found.")
    updates = data.model_dump()
    updates["updated_at"] = datetime.now(timezone.utc)
    await database[JOBS].update_one({"_id": oid}, {"$set": updates})
    return serialize_document(await database[JOBS].find_one({"_id": oid}))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(job_id, "job id")
    job = await database[JOBS].find_one({"_id": oid, "recruiter_id": ObjectId(user["id"])})
    if not job:
        raise HTTPException(status_code=404, detail="Job was not found.")
    application_count = await database["applications"].count_documents({"job_id": oid})
    if application_count:
        raise HTTPException(status_code=409, detail="Close this role instead of deleting a job with applications.")
    await database[JOBS].delete_one({"_id": oid})






