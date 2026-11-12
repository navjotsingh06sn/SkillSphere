
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import candidate_required, get_database
from app.models import (
    CandidateProfile,
    Job,
    Resume,
    ResumeAnalysis,
)
from app.pg_utils import parse_uuid, serialize_model

router = APIRouter(
    prefix="/matching",
    tags=["matching"],
)

SCREENING_THRESHOLD = 75

ALIASES = {
    "js": "javascript",
    "react": "react.js",
    "py": "python",
    "mongo": "mongodb",
    "rest": "restapi",
}


def normalize(skill: str) -> str:
    value = re.sub(
        r"[^a-z0-9.+#]",
        "",
        skill.lower().strip(),
    )
    return ALIASES.get(value, value)


def calculate_match(candidate_skills, required_skills):
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

    if not required:
        return None, [], [], candidate

    matched_keys = set(required) & set(candidate)
    missing_keys = set(required) - matched_keys

    score = round((len(matched_keys) / len(required)) * 100)

    matched = [required[key] for key in sorted(matched_keys)]
    missing = [required[key] for key in sorted(missing_keys)]

    return score, matched, missing, candidate


def format_analysis_doc(
    analysis: ResumeAnalysis,
    job: Job | None = None,
) -> dict:
    doc = serialize_model(analysis)

    extra = analysis.raw_ai_response or {}

    for key, val in extra.items():
        doc.setdefault(key, val)

    if job:
        doc["job"] = serialize_model(job)

    return doc


@router.post("/analyze")
async def analyze_resume(
    data: dict,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    job_uuid = parse_uuid(data.get("job_id"), "job id")
    candidate_id = parse_uuid(user["id"], "candidate id")

    job = await db.scalar(
        select(Job).where(
            Job.id == job_uuid,
            Job.status == "published",
        )
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Published job was not found.",
        )

    profile = await db.scalar(
        select(CandidateProfile).where(
            CandidateProfile.user_id == candidate_id
        )
    )

    resume_id = data.get("resume_id")

    if resume_id:
        resume_uuid = parse_uuid(resume_id, "resume id")

        resume = await db.scalar(
            select(Resume).where(
                Resume.id == resume_uuid,
                Resume.candidate_id == candidate_id,
                Resume.status == "completed",
            )
        )
    else:
        resume = await db.scalar(
            select(Resume)
            .where(
                Resume.candidate_id == candidate_id,
                Resume.status == "completed",
            )
            .order_by(Resume.created_at.desc())
            .limit(1)
        )

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No completed resume was found. Upload and process a resume first.",
        )

    candidate_skills = set()

    if profile and profile.skills:
        for skill in profile.skills:
            if isinstance(skill, str):
                candidate_skills.add(skill)

    extracted_data = resume.extracted_data or {}

    for skill in extracted_data.get("skills", []):
        if isinstance(skill, str):
            candidate_skills.add(skill)

    required_skills = job.required_skills or []

    match_score, matched, missing, candidate = calculate_match(
        candidate_skills,
        required_skills,
    )

    required_keys = {
        normalize(skill)
        for skill in required_skills
        if isinstance(skill, str) and normalize(skill)
    }

    additional_skills = [
        candidate[key]
        for key in sorted(set(candidate) - required_keys)
    ]

    recommendations = [
        f"Build experience with {skill}."
        for skill in missing
    ]

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
            "of this job's required skills. "
            f"The minimum screening threshold is {SCREENING_THRESHOLD}%."
        )
        screening_status = "not_shortlisted"

    raw_ai = {
        "match_percentage": match_score,
        "matched_skills": matched,
        "missing_skills": missing,
        "additional_skills": additional_skills,
        "recommendations": recommendations,
        "explanation": explanation,
        "screening_threshold": SCREENING_THRESHOLD,
        "screening_status": screening_status,
    }

    analysis = ResumeAnalysis(
        candidate_id=candidate_id,
        job_id=job_uuid,
        resume_id=resume.id,
        overall_score=(
            float(match_score)
            if match_score is not None
            else None
        ),
        matched_skills=matched,
        missing_skills=missing,
        raw_ai_response=raw_ai,
    )

    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    return format_analysis_doc(analysis)


@router.get("/history")
async def get_matching_history(
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    candidate_id = parse_uuid(user["id"], "candidate id")

    stmt = (
        select(ResumeAnalysis, Job)
        .outerjoin(Job, ResumeAnalysis.job_id == Job.id)
        .where(ResumeAnalysis.candidate_id == candidate_id)
        .order_by(ResumeAnalysis.created_at.desc())
    )

    rows = (await db.execute(stmt)).all()

    return [
        format_analysis_doc(analysis, job)
        for analysis, job in rows
    ]


@router.get("/{analysis_id}")
async def get_matching_analysis(
    analysis_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    analysis_uuid = parse_uuid(analysis_id, "analysis id")
    candidate_id = parse_uuid(user["id"], "candidate id")

    stmt = (
        select(ResumeAnalysis, Job)
        .outerjoin(Job, ResumeAnalysis.job_id == Job.id)
        .where(
            ResumeAnalysis.id == analysis_uuid,
            ResumeAnalysis.candidate_id == candidate_id,
        )
    )

    row = (await db.execute(stmt)).first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Matching analysis was not found.",
        )

    analysis, job = row

    return format_analysis_doc(analysis, job)
