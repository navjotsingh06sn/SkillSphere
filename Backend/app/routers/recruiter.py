from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import COMPANIES, JOBS, APPLICATIONS, CANDIDATE_PROFILES, USERS
from app.dependencies import get_database, recruiter_required
from app.schemas import CompanyInput
from app.utils import serialize_document

router = APIRouter(prefix="/recruiter", tags=["recruiters"])


@router.get("/company")
async def get_company(user: dict = Depends(recruiter_required), database: AsyncDatabase = Depends(get_database)):
    company = await database[COMPANIES].find_one({"recruiter_id": ObjectId(user["id"])})
    return serialize_document(company) if company else {}


@router.put("/company")
async def save_company(
    data: CompanyInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    now = datetime.now(timezone.utc)
    await database[COMPANIES].update_one(
        {"recruiter_id": ObjectId(user["id"])},
        {"$set": {**data.model_dump(), "updated_at": now},
         "$setOnInsert": {"recruiter_id": ObjectId(user["id"]), "created_at": now}},
        upsert=True,
    )
    await database[USERS].update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"company_name": data.company_name}},
    )
    return serialize_document(await database[COMPANIES].find_one({"recruiter_id": ObjectId(user["id"])}))


@router.get("/jobs")
async def my_jobs(user: dict = Depends(recruiter_required), database: AsyncDatabase = Depends(get_database)):
    cursor = database[JOBS].find({"recruiter_id": ObjectId(user["id"])}).sort("created_at", -1)
    return [serialize_document(job) async for job in cursor]


@router.get("/dashboard")
async def recruiter_dashboard(user: dict = Depends(recruiter_required), database: AsyncDatabase = Depends(get_database)):
    recruiter_id = ObjectId(user["id"])
    jobs = database[JOBS]
    applications = database[APPLICATIONS]
    job_ids = [item["_id"] async for item in jobs.find({"recruiter_id": recruiter_id}, {"_id": 1})]
    total_applications = await applications.count_documents({"recruiter_id": recruiter_id})
    return {
        "total_jobs": len(job_ids),
        "active_jobs": await jobs.count_documents({"recruiter_id": recruiter_id, "status": "published"}),
        "closed_jobs": await jobs.count_documents({"recruiter_id": recruiter_id, "status": "closed"}),
        "total_applicants": total_applications,
        "shortlisted": await applications.count_documents({"recruiter_id": recruiter_id, "status": "shortlisted"}),
        "interviews": await applications.count_documents({"recruiter_id": recruiter_id, "status": "interview"}),
    }


@router.get("/applicants")
async def applicants(
    job_id: str | None = None,
    skill: str | None = None,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    query = {"recruiter_id": ObjectId(user["id"])}
    if job_id:
        if not ObjectId.is_valid(job_id):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid job id.")
        query["job_id"] = ObjectId(job_id)
    cursor = database[APPLICATIONS].find(query).sort("applied_at", -1)
    results = []
    async for application in cursor:
        profile = await database[CANDIDATE_PROFILES].find_one({"user_id": application["candidate_id"]}) or {}
        if skill and skill.casefold() not in " ".join(profile.get("skills", [])).casefold():
            continue
        account = await database[USERS].find_one({"_id": application["candidate_id"]}, {"email": 1, "full_name": 1})
        job = await database[JOBS].find_one({"_id": application["job_id"]}, {"title": 1})
        results.append({
            **serialize_document(application),
            "candidate": {
                "id": str(application["candidate_id"]),
                "full_name": profile.get("full_name", account.get("full_name") if account else ""),
                "email": account.get("email") if account else "",
                "skills": profile.get("skills", []),
                "experience": profile.get("experience", []),
            },
            "job": serialize_document(job),
        })
    return results


