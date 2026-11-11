
from datetime import datetime, timezone
import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    CANDIDATE_PROFILES,
    JOBS,
    RESUMES,
    RESUME_ANALYSES,
)

from app.dependencies import (
    candidate_required,
    get_database,
)

from app.utils import parse_object_id, serialize_document


router = APIRouter(
    prefix="/matching",
    tags=["matching"],
)


# Minimum match percentage for initial screening
SCREENING_THRESHOLD = 75


# Common skill name variations
ALIASES = {
    "js": "javascript",
    "react": "react.js",
    "py": "python",
    "mongo": "mongodb",
    "rest": "restapi",
}


def normalize(skill: str) -> str:
    """
    Convert skill names into a common format.

    Example:
    JS -> javascript
    Python -> python
    REST API -> restapi
    """

    value = re.sub(
        r"[^a-z0-9.+#]",
        "",
        skill.lower().strip(),
    )

    return ALIASES.get(value, value)


def calculate_match(candidate_skills, required_skills):
    """
    Compare candidate skills with job required skills.

    Returns:
    - Match percentage
    - Matched skills
    - Missing skills
    - Candidate skills dictionary
    """

    candidate = {
        normalize(skill): skill
        for skill in candidate_skills
        if isinstance(skill, str) and normalize(skill)
    }

    required = {
        normalize(skill): skill
        for skill in required_skills
        if isinstance(skill, str) and normalize(skill)
    }

    # No required skills means automatic matching is not possible
    if not required:
        return None, [], [], candidate

    matched_keys = set(required) & set(candidate)

    missing_keys = set(required) - matched_keys

    score = round(
        (len(matched_keys) / len(required)) * 100
    )

    matched = [
        required[key]
        for key in sorted(matched_keys)
    ]

    missing = [
        required[key]
        for key in sorted(missing_keys)
    ]

    return score, matched, missing, candidate


@router.post("/analyze")
async def analyze_resume(
    data: dict,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    """
    Analyze the candidate's resume against a job.
    """

    # 1. Validate job ID
    job_oid = parse_object_id(
        data.get("job_id"),
        "job id",
    )

    candidate_id = ObjectId(user["id"])

    # 2. Find published job
    job = await database[JOBS].find_one({
        "_id": job_oid,
        "status": "published",
    })

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Published job was not found.",
        )

    # 3. Find candidate profile
    profile = await database[CANDIDATE_PROFILES].find_one({
        "user_id": candidate_id,
    }) or {}

    # 4. Find resume
    resume_id = data.get("resume_id")

    if resume_id:
        resume_oid = parse_object_id(
            resume_id,
            "resume id",
        )

        resume = await database[RESUMES].find_one({
            "_id": resume_oid,
            "candidate_id": candidate_id,
            "status": "completed",
        })

    else:
        # Use latest completed resume
        resume = await database[RESUMES].find_one(
            {
                "candidate_id": candidate_id,
                "status": "completed",
            },
            sort=[("created_at", -1)],
        )

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No completed resume was found. Upload and process a resume first.",
        )

    # 5. Get skills from candidate profile
    candidate_skills = set()

    for skill in profile.get("skills", []):
        if isinstance(skill, str):
            candidate_skills.add(skill)

    # 6. Get skills extracted from resume
    extracted_data = resume.get("extracted_data") or {}

    for skill in extracted_data.get("skills", []):
        if isinstance(skill, str):
            candidate_skills.add(skill)

    # 7. Get required skills from job
    required_skills = job.get("required_skills", [])

    # 8. Calculate match
    match_score, matched, missing, candidate = calculate_match(
        candidate_skills,
        required_skills,
    )

    # 9. Find additional skills
    required_keys = {
        normalize(skill)
        for skill in required_skills
        if isinstance(skill, str) and normalize(skill)
    }

    additional_skills = [
        candidate[key]
        for key in sorted(set(candidate) - required_keys)
    ]

    # 10. Generate recommendations
    recommendations = [
        f"Build experience with {skill}."
        for skill in missing
    ]

    # 11. Generate explanation
    if match_score is None:
        explanation = (
            "No required skills were defined for this job. "
            "Manual recruiter review is required."
        )

        screening_status = "pending_review"

    elif match_score >= SCREENING_THRESHOLD:
        explanation = (
            f"Your profile matches {match_score}% "
            "of this job's required skills. "
            "You have passed the initial screening threshold."
        )

        screening_status = "shortlisted"

    else:
        explanation = (
            f"Your profile matches {match_score}% "
            f"of this job's required skills. "
            f"The minimum screening threshold is "
            f"{SCREENING_THRESHOLD}%."
        )

        screening_status = "not_shortlisted"

    # 12. Prepare analysis document
    now = datetime.now(timezone.utc)

    analysis = {
        "candidate_id": candidate_id,
        "job_id": job_oid,
        "resume_id": resume["_id"],

        "match_percentage": match_score,

        "matched_skills": matched,
        "missing_skills": missing,
        "additional_skills": additional_skills,

        "recommendations": recommendations,
        "explanation": explanation,

        "screening_threshold": SCREENING_THRESHOLD,
        "screening_status": screening_status,

        "created_at": now,
    }

    # 13. Save analysis in MongoDB
    result = await database[RESUME_ANALYSES].insert_one(
        analysis
    )

    analysis["_id"] = result.inserted_id

    return serialize_document(analysis)


@router.get("/history")
async def get_matching_history(
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    """
    Get all previous resume matching analyses
    of the logged-in candidate.
    """

    candidate_id = ObjectId(user["id"])

    cursor = (
        database[RESUME_ANALYSES]
        .find({
            "candidate_id": candidate_id,
        })
        .sort("created_at", -1)
    )

    history = []

    async for analysis in cursor:

        # Get related job information
        job = await database[JOBS].find_one(
            {
                "_id": analysis["job_id"],
            },
            {
                "title": 1,
                "company_name": 1,
                "required_skills": 1,
            },
        )

        item = serialize_document(analysis)

        item["job"] = serialize_document(job)

        history.append(item)

    return history


@router.get("/{analysis_id}")
async def get_matching_analysis(
    analysis_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    """
    Get one particular matching analysis.
    """

    analysis_oid = parse_object_id(
        analysis_id,
        "analysis id",
    )

    candidate_id = ObjectId(user["id"])

    analysis = await database[RESUME_ANALYSES].find_one({
        "_id": analysis_oid,
        "candidate_id": candidate_id,
    })

    if not analysis:
        raise HTTPException(
            status_code=404,
            detail="Matching analysis was not found.",
        )

    # Get related job information
    job = await database[JOBS].find_one({
        "_id": analysis["job_id"],
    })

    result = serialize_document(analysis)

    result["job"] = serialize_document(job)

    return result
