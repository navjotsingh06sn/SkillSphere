from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    APPLICATIONS,
    CANDIDATE_PROFILES,
    JOBS,
    SAVED_JOBS,
    USERS,
)
from app.dependencies import candidate_required, get_database
from app.schemas import ProfileInput
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/profile")
async def get_profile(
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    profile = await database[CANDIDATE_PROFILES].find_one({"user_id": ObjectId(user["id"])})
    if profile is None:
        raise HTTPException(status_code=404, detail="Candidate profile was not found.")
    profile["email"] = user["email"]
    return serialize_document(profile)


@router.put("/profile")
async def update_profile(
    data: ProfileInput,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    updates = data.model_dump(exclude_unset=True)
    if "skills" in updates:
        updates["skills"] = sorted({skill.strip() for skill in updates["skills"] if skill.strip()})
    updates["updated_at"] = datetime.now(timezone.utc)
    await database[CANDIDATE_PROFILES].update_one(
        {"user_id": ObjectId(user["id"])},
        {"$set": updates, "$setOnInsert": {"user_id": ObjectId(user["id"])}},
        upsert=True,
    )
    if updates.get("full_name"):
        await database[USERS].update_one(
            {"_id": ObjectId(user["id"])},
            {"$set": {"full_name": updates["full_name"]}},
        )
    profile = await database[CANDIDATE_PROFILES].find_one({"user_id": ObjectId(user["id"])})
    profile["email"] = user["email"]
    return serialize_document(profile)


@router.get("/dashboard")
async def candidate_dashboard(
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    candidate_id = ObjectId(user["id"])
    profile = await database[CANDIDATE_PROFILES].find_one({"user_id": candidate_id}) or {}
    applications = database[APPLICATIONS]
    counts = {}
    for key, value in [
        ("pending", ["applied", "under_review"]),
        ("shortlisted", ["shortlisted"]),
        ("interviews", ["interview"]),
        ("selected", ["selected"]),
    ]:
        counts[key] = await applications.count_documents({
            "candidate_id": candidate_id,
            "status": {"$in": value},
        })
    total_fields = ["full_name", "phone", "location", "headline", "summary", "skills", "education", "experience"]
    completed = sum(bool(profile.get(field)) for field in total_fields)
    activity_cursor = applications.find({"candidate_id": candidate_id}).sort("applied_at", -1).limit(5)
    recent = [serialize_document(item) async for item in activity_cursor]
    from app.routers.matching import normalize

    candidate_skills = profile.get("skills", [])
    latest_resume = await database["resumes"].find_one(
        {"candidate_id": candidate_id, "status": "completed"},
        {"extracted_data.skills": 1},
        sort=[("created_at", -1)],
    )
    if latest_resume:
        candidate_skills = list(set(candidate_skills) | set(latest_resume.get("extracted_data", {}).get("skills", [])))
    candidate_keys = {normalize(skill) for skill in candidate_skills}
    job_cursor = database[JOBS].find({
        "status": "published",
        "is_demo": {"$ne": True},
    }).sort("created_at", -1).limit(100)
    scored_jobs = []
    async for job in job_cursor:
        required = {normalize(skill) for skill in job.get("required_skills", []) if normalize(skill)}
        score = round(100 * len(candidate_keys & required) / len(required)) if required else None
        job_view = serialize_document(job)
        job_view["match_percentage"] = score
        scored_jobs.append((score if score is not None else -1, job.get("created_at"), job_view))
    scored_jobs.sort(key=lambda item: (item[0], item[1] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    recommended = [item[2] for item in scored_jobs[:5]]
    return {
        "total_applications": await applications.count_documents({"candidate_id": candidate_id}),
        "pending_applications": counts["pending"],
        "shortlisted": counts["shortlisted"],
        "interviews": counts["interviews"],
        "selected": counts["selected"],
        "profile_completion": round(completed / len(total_fields) * 100),
        "recent_applications": recent,
        "recommended_jobs": recommended,
    }


@router.get("/saved-jobs")
async def saved_jobs(
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    cursor = database[SAVED_JOBS].find({"candidate_id": ObjectId(user["id"])}).sort("created_at", -1)
    results = []
    async for saved in cursor:
        job = await database[JOBS].find_one({"_id": saved["job_id"]})
        if job:
            results.append(serialize_document(job))
    return results


@router.post("/saved-jobs/{job_id}")
async def save_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    job_oid = parse_object_id(job_id, "job id")
    job = await database[JOBS].find_one({"_id": job_oid, "status": "published"})
    if not job:
        raise HTTPException(status_code=404, detail="Published job was not found.")
    if job.get("is_demo"):
        raise HTTPException(status_code=409, detail="Demo jobs cannot be saved.")
    from datetime import datetime, timezone
    from pymongo.errors import DuplicateKeyError
    try:
        await database[SAVED_JOBS].insert_one({
            "candidate_id": ObjectId(user["id"]),
            "job_id": job_oid,
            "created_at": datetime.now(timezone.utc),
        })
    except DuplicateKeyError:
        pass
    return {"saved": True}


@router.delete("/saved-jobs/{job_id}")
async def unsave_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    await database[SAVED_JOBS].delete_one({
        "candidate_id": ObjectId(user["id"]),
        "job_id": parse_object_id(job_id, "job id"),
    })
    return {"saved": False}
