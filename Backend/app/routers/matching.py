from datetime import datetime, timezone
import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import CANDIDATE_PROFILES, JOBS, RESUMES, RESUME_ANALYSES
from app.dependencies import candidate_required, get_database
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/matching", tags=["matching"])

ALIASES = {
    "js": "javascript",
    "react": "react.js",
    "py": "python",
    "mongo": "mongodb",
    "rest": "rest api",
}


def normalize(skill: str) -> str:
    value = re.sub(r"[^a-z0-9.+#]", "", skill.lower().strip())
    return ALIASES.get(value, value)


@router.post("/analyze")
async def analyze_match(
    data: dict,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=422, detail="job_id is required.")
    job = await database[JOBS].find_one({
        "_id": parse_object_id(job_id, "job id"),
        "status": "published",
    })
    if not job:
        raise HTTPException(status_code=404, detail="Published job was not found.")
    profile = await database[CANDIDATE_PROFILES].find_one({"user_id": ObjectId(user["id"])}) or {}
    resume_id = data.get("resume_id")
    resume = None
    if resume_id:
        resume = await database[RESUMES].find_one({
            "_id": parse_object_id(resume_id, "resume id"),
            "candidate_id": ObjectId(user["id"]),
            "status": "completed",
        })
    else:
        resume = await database[RESUMES].find_one(
            {"candidate_id": ObjectId(user["id"]), "status": "completed"},
            sort=[("created_at", -1)],
        )
    candidate_skills = profile.get("skills", [])
    if resume:
        candidate_skills = list(set(candidate_skills) | set(resume.get("extracted_data", {}).get("skills", [])))
    required = {normalize(skill): skill for skill in job.get("required_skills", []) if normalize(skill)}
    candidate = {normalize(skill): skill for skill in candidate_skills if normalize(skill)}
    if not required:
        score = None
        matched = []
        missing = []
        explanation = "This job has no required skills, so a match score cannot be calculated."
    else:
        matched_keys = set(required) & set(candidate)
        missing_keys = set(required) - matched_keys
        score = round(100 * len(matched_keys) / len(required))
        matched = [required[key] for key in sorted(matched_keys)]
        missing = [required[key] for key in sorted(missing_keys)]
        explanation = f"Your profile matches {score}% of this job's listed skills."
    analysis = {
        "candidate_id": ObjectId(user["id"]),
        "job_id": job["_id"],
        "resume_id": resume["_id"] if resume else None,
        "match_percentage": score,
        "matched_skills": matched,
        "missing_skills": missing,
        "additional_skills": [candidate[key] for key in sorted(set(candidate) - set(required))],
        "recommendations": [f"Build experience with {skill}." for skill in missing],
        "explanation": explanation,
        "created_at": datetime.now(timezone.utc),
    }
    result = await database[RESUME_ANALYSES].insert_one(analysis)
    analysis["_id"] = result.inserted_id
    return serialize_document(analysis)


@router.get("/history")
async def matching_history(
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    cursor = database[RESUME_ANALYSES].find({"candidate_id": ObjectId(user["id"])}).sort("created_at", -1).limit(100)
    history = []
    async for item in cursor:
        job = await database[JOBS].find_one({"_id": item["job_id"]}, {"title": 1, "company_name": 1})
        value = serialize_document(item)
        value["job"] = serialize_document(job)
        history.append(value)
    return history


@router.get("/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    item = await database[RESUME_ANALYSES].find_one({
        "_id": parse_object_id(analysis_id, "analysis id"),
        "candidate_id": ObjectId(user["id"]),
    })
    if not item:
        raise HTTPException(status_code=404, detail="Analysis was not found.")
    return serialize_document(item)
