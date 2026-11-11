from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    COMPANIES,
    JOBS,
    APPLICATIONS,
    CANDIDATE_PROFILES,
    USERS,
    INTERVIEWS,
    RESUMES,
    RESUME_ANALYSES,
)
from app.dependencies import get_database, recruiter_required
from app.schemas import CompanyInput
from app.utils import serialize_document


router = APIRouter(prefix="/recruiter", tags=["recruiters"])


@router.get("/company")
async def get_company(
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    company = await database[COMPANIES].find_one({
        "recruiter_id": ObjectId(user["id"]),
    })

    return serialize_document(company) if company else {}


@router.put("/company")
async def save_company(
    data: CompanyInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    now = datetime.now(timezone.utc)
    recruiter_id = ObjectId(user["id"])

    await database[COMPANIES].update_one(
        {"recruiter_id": recruiter_id},
        {
            "$set": {
                **data.model_dump(),
                "updated_at": now,
            },
            "$setOnInsert": {
                "recruiter_id": recruiter_id,
                "created_at": now,
            },
        },
        upsert=True,
    )

    await database[USERS].update_one(
        {"_id": recruiter_id},
        {"$set": {"company_name": data.company_name}},
    )

    company = await database[COMPANIES].find_one({
        "recruiter_id": recruiter_id,
    })

    return serialize_document(company)


@router.get("/jobs")
async def my_jobs(
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    cursor = (
        database[JOBS]
        .find({"recruiter_id": ObjectId(user["id"])})
        .sort("created_at", -1)
    )

    return [serialize_document(job) async for job in cursor]


@router.get("/dashboard")
async def recruiter_dashboard(
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    recruiter_id = ObjectId(user["id"])

    jobs = database[JOBS]
    applications = database[APPLICATIONS]
    interviews = database[INTERVIEWS]

    job_ids = [
        item["_id"]
        async for item in jobs.find(
            {"recruiter_id": recruiter_id},
            {"_id": 1},
        )
    ]

    total_applications = await applications.count_documents({
        "recruiter_id": recruiter_id,
    })

    return {
        "total_jobs": len(job_ids),

        "active_jobs": await jobs.count_documents({
            "recruiter_id": recruiter_id,
            "status": "published",
        }),

        "closed_jobs": await jobs.count_documents({
            "recruiter_id": recruiter_id,
            "status": "closed",
        }),

        "total_applicants": total_applications,

        "shortlisted": await applications.count_documents({
            "recruiter_id": recruiter_id,
            "status": "shortlisted",
        }),

        "pending_review": await applications.count_documents({
            "recruiter_id": recruiter_id,
            "screening_status": "pending_review",
        }),

        "reconsideration_requests": await applications.count_documents({
            "recruiter_id": recruiter_id,
            "reconsideration_status": "requested",
        }),

        "interviews": await interviews.count_documents({
            "recruiter_id": recruiter_id,
            "status": "scheduled",
        }),
    }


@router.get("/applicants")
async def applicants(
    job_id: str | None = None,
    skill: str | None = None,
    status: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    allowed_statuses = {
        "applied",
        "under_review",
        "shortlisted",
        "interview",
        "selected",
        "rejected",
    }
    if status and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Invalid application status.")
    if min_score is not None and not 0 <= min_score <= 100:
        raise HTTPException(status_code=422, detail="Minimum score must be between 0 and 100.")
    if max_score is not None and not 0 <= max_score <= 100:
        raise HTTPException(status_code=422, detail="Maximum score must be between 0 and 100.")
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=422, detail="Minimum score cannot exceed maximum score.")

    recruiter_id = ObjectId(user["id"])
    published_job_ids = [
        job["_id"]
        async for job in database[JOBS].find(
            {"recruiter_id": recruiter_id, "status": "published"},
            {"_id": 1},
        )
    ]
    query = {
        "recruiter_id": recruiter_id,
        "job_id": {"$in": published_job_ids},
    }

    if job_id:
        if not ObjectId.is_valid(job_id):
            raise HTTPException(
                status_code=400,
                detail="Invalid job id.",
            )

        requested_job_id = ObjectId(job_id)
        if requested_job_id not in published_job_ids:
            return []
        query["job_id"] = requested_job_id

    if status:
        query["status"] = status

    score_filter = {}
    if min_score is not None:
        score_filter["$gte"] = min_score
    if max_score is not None:
        score_filter["$lte"] = max_score
    if score_filter:
        query["match_score"] = score_filter

    cursor = (
        database[APPLICATIONS]
        .find(query)
        .sort("applied_at", -1)
    )

    results = []

    async for application in cursor:
        profile = await database[CANDIDATE_PROFILES].find_one({
            "user_id": application["candidate_id"],
        }) or {}

        resume = await database[RESUMES].find_one({
            "_id": application.get("resume_id"),
            "candidate_id": application["candidate_id"],
        }) if application.get("resume_id") else None
        extracted_data = (resume or {}).get("extracted_data", {})
        candidate_skills = profile.get("skills") or extracted_data.get("skills", [])

        if skill and skill.casefold() not in " ".join(
            candidate_skills
        ).casefold():
            continue

        account = await database[USERS].find_one(
            {"_id": application["candidate_id"]},
            {"email": 1, "full_name": 1},
        )

        job = await database[JOBS].find_one(
            {"_id": application["job_id"]},
            {"title": 1, "company_name": 1, "status": 1},
        )

        analysis = None

        if application.get("analysis_id"):
            analysis = await database[RESUME_ANALYSES].find_one({
                "_id": application["analysis_id"],
            })

        results.append({
            **serialize_document(application),

            "candidate": {
                "id": str(application["candidate_id"]),
                "full_name": profile.get("full_name") or (
                    account.get("full_name") if account else ""
                ),
                "email": account.get("email") if account else "",
                "phone": profile.get("phone") or extracted_data.get("phone"),
                "education": profile.get("education") or extracted_data.get("education", []),
                "skills": candidate_skills,
                "experience": profile.get("experience") or extracted_data.get("experience", []),
            },

            "job": serialize_document(job),

            "analysis": serialize_document(analysis),
            "resume": (
                {
                    "id": str(resume["_id"]),
                    "original_name": resume.get("original_name", "Resume"),
                    "status": resume.get("status"),
                }
                if resume else None
            ),
        })

    return results