from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import APPLICATIONS, JOBS, RESUMES, NOTIFICATIONS
from app.dependencies import candidate_required, get_current_user, get_database, recruiter_required
from app.schemas import ApplicationStatusInput
from app.utils import parse_object_id, serialize_document

router = APIRouter(tags=["applications"])


@router.post("/jobs/{job_id}/apply", status_code=status.HTTP_201_CREATED)
async def apply_to_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    job_oid = parse_object_id(job_id, "job id")
    job = await database[JOBS].find_one({"_id": job_oid, "status": "published"})
    if not job:
        raise HTTPException(status_code=404, detail="Published job was not found.")
    if job.get("is_demo"):
        raise HTTPException(status_code=409, detail="Demo jobs are for browsing only.")
    resume = await database[RESUMES].find_one(
        {"candidate_id": ObjectId(user["id"]), "status": "completed"},
        sort=[("created_at", -1)],
    )
    if not resume:
        raise HTTPException(status_code=409, detail="Upload and process a resume before applying.")
    application = {
        "candidate_id": ObjectId(user["id"]),
        "job_id": job_oid,
        "recruiter_id": job["recruiter_id"],
        "resume_id": resume["_id"],
        "status": "applied",
        "applied_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    try:
        result = await database[APPLICATIONS].insert_one(application)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="You have already applied to this job.")
    application["_id"] = result.inserted_id
    await database[NOTIFICATIONS].insert_one({
        "user_id": job["recruiter_id"],
        "type": "new_application",
        "message": "A candidate applied to " + job["title"] + ".",
        "related_id": result.inserted_id,
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
    })
    return serialize_document(application)


@router.get("/applications")
async def list_applications(
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    if user["role"] == "candidate":
        query = {"candidate_id": ObjectId(user["id"])}
    elif user["role"] == "recruiter":
        query = {"recruiter_id": ObjectId(user["id"])}
    else:
        query = {}
    cursor = database[APPLICATIONS].find(query).sort("applied_at", -1)
    applications = []
    async for application in cursor:
        job = await database[JOBS].find_one({"_id": application["job_id"]}, {"title": 1, "company_name": 1})
        item = serialize_document(application)
        item["job"] = serialize_document(job)
        applications.append(item)
    return applications


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")
    application = await database[APPLICATIONS].find_one({"_id": oid})
    if not application:
        raise HTTPException(status_code=404, detail="Application was not found.")
    if user["role"] == "candidate" and application["candidate_id"] != ObjectId(user["id"]):
        raise HTTPException(status_code=404, detail="Application was not found.")
    if user["role"] == "recruiter" and application["recruiter_id"] != ObjectId(user["id"]):
        raise HTTPException(status_code=404, detail="Application was not found.")
    return serialize_document(application)


@router.put("/applications/{application_id}/withdraw")
async def withdraw_application(
    application_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")
    result = await database[APPLICATIONS].update_one(
        {"_id": oid, "candidate_id": ObjectId(user["id"]), "status": {"$in": ["applied", "under_review"]}},
        {"$set": {"status": "withdrawn", "updated_at": datetime.now(timezone.utc)}},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=409, detail="This application cannot be withdrawn.")
    application = await database[APPLICATIONS].find_one({"_id": oid})
    await database[NOTIFICATIONS].insert_one({
        "user_id": application["recruiter_id"],
        "type": "application_withdrawn",
        "message": "A candidate withdrew an application.",
        "related_id": oid,
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
    })
    return {"status": "withdrawn"}


@router.put("/applications/{application_id}/status")
async def update_application_status(
    application_id: str,
    data: ApplicationStatusInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")
    result = await database[APPLICATIONS].update_one(
        {"_id": oid, "recruiter_id": ObjectId(user["id"])},
        {"$set": {"status": data.status, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Application was not found.")
    application = await database[APPLICATIONS].find_one({"_id": oid})
    await database[NOTIFICATIONS].insert_one({
        "user_id": application["candidate_id"],
        "type": "application_status",
        "message": "Your application status changed to " + data.status.replace("_", " ") + ".",
        "related_id": oid,
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
    })
    return {"status": data.status}


