
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_database, recruiter_required
from app.models import (
    Application,
    CandidateProfile,
    Company,
    Interview,
    Job,
    RecruiterProfile,
    Resume,
    ResumeAnalysis,
    User,
)
from app.pg_utils import parse_uuid, serialize_model
from app.schemas import CompanyInput

router = APIRouter(prefix="/recruiter", tags=["recruiters"])


def format_company_response(company: Company | None) -> dict:
    if not company:
        return {}

    doc = serialize_model(company)
    doc["company_name"] = company.name

    extra = company.extra_data or {}

    for key in ("industry", "contact_email"):
        if key in extra and key not in doc:
            doc[key] = extra[key]

    return doc


def get_resume_data(resume: Resume | None) -> dict:
    if not resume:
        return {}

    return (
        getattr(resume, "extracted_data", None)
        or getattr(resume, "parsed_data", None)
        or {}
    )


@router.get("/company")
async def get_company(
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(RecruiterProfile).where(
            RecruiterProfile.user_id == recruiter_uuid
        )
    )
    profile = result.scalar_one_or_none()

    if not profile or not profile.company_id:
        return {}

    result = await db.execute(
        select(Company).where(
            Company.id == profile.company_id
        )
    )
    company = result.scalar_one_or_none()

    return format_company_response(company)


@router.put("/company")
async def save_company(
    data: CompanyInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(RecruiterProfile).where(
            RecruiterProfile.user_id == recruiter_uuid
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = RecruiterProfile(user_id=recruiter_uuid)
        db.add(profile)
        await db.flush()

    company = None

    if profile.company_id:
        result = await db.execute(
            select(Company).where(
                Company.id == profile.company_id
            )
        )
        company = result.scalar_one_or_none()

    if not company:
        company = Company(
            name=data.company_name.strip(),
            description=data.description,
            website=data.website,
            location=data.location,
            extra_data={
                "industry": data.industry,
                "contact_email": data.contact_email,
            },
        )

        db.add(company)
        await db.flush()

        profile.company_id = company.id

    else:
        company.name = data.company_name.strip()
        company.description = data.description
        company.website = data.website
        company.location = data.location

        extra = dict(company.extra_data or {})
        extra["industry"] = data.industry
        extra["contact_email"] = data.contact_email

        company.extra_data = extra

    profile.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(company)

    return format_company_response(company)


@router.get("/jobs")
async def my_jobs(
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(Job)
        .where(Job.recruiter_id == recruiter_uuid)
        .order_by(Job.created_at.desc())
    )

    jobs = result.scalars().all()

    return [
        serialize_model(job)
        for job in jobs
    ]


@router.get("/dashboard")
async def recruiter_dashboard(
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    total_jobs = (
        await db.scalar(
            select(func.count(Job.id)).where(
                Job.recruiter_id == recruiter_uuid
            )
        )
    ) or 0

    active_jobs = (
        await db.scalar(
            select(func.count(Job.id)).where(
                Job.recruiter_id == recruiter_uuid,
                Job.status == "published",
            )
        )
    ) or 0

    closed_jobs = (
        await db.scalar(
            select(func.count(Job.id)).where(
                Job.recruiter_id == recruiter_uuid,
                Job.status == "closed",
            )
        )
    ) or 0

    total_applications = (
        await db.scalar(
            select(func.count(Application.id)).where(
                Application.recruiter_id == recruiter_uuid
            )
        )
    ) or 0

    shortlisted = (
        await db.scalar(
            select(func.count(Application.id)).where(
                Application.recruiter_id == recruiter_uuid,
                Application.status == "shortlisted",
            )
        )
    ) or 0

    pending_review = (
        await db.scalar(
            select(func.count(Application.id)).where(
                Application.recruiter_id == recruiter_uuid,
                Application.screening_status == "pending_review",
            )
        )
    ) or 0

    reconsideration_requests = (
        await db.scalar(
            select(func.count(Application.id)).where(
                Application.recruiter_id == recruiter_uuid,
                Application.reconsideration_status == "requested",
            )
        )
    ) or 0

    interviews = (
        await db.scalar(
            select(func.count(Interview.id)).where(
                Interview.recruiter_id == recruiter_uuid,
                Interview.status == "scheduled",
            )
        )
    ) or 0

    return {
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "closed_jobs": closed_jobs,
        "total_applicants": total_applications,
        "shortlisted": shortlisted,
        "pending_review": pending_review,
        "reconsideration_requests": reconsideration_requests,
        "interviews": interviews,
    }


@router.get("/applicants")
async def applicants(
    job_id: str | None = None,
    skill: str | None = None,
    status: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
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
        raise HTTPException(
            status_code=422,
            detail="Invalid application status.",
        )

    if min_score is not None and not 0 <= min_score <= 100:
        raise HTTPException(
            status_code=422,
            detail="Minimum score must be between 0 and 100.",
        )

    if max_score is not None and not 0 <= max_score <= 100:
        raise HTTPException(
            status_code=422,
            detail="Maximum score must be between 0 and 100.",
        )

    if (
        min_score is not None
        and max_score is not None
        and min_score > max_score
    ):
        raise HTTPException(
            status_code=422,
            detail="Minimum score cannot exceed maximum score.",
        )

    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(Job.id).where(
            Job.recruiter_id == recruiter_uuid,
            Job.status == "published",
        )
    )

    published_job_ids = result.scalars().all()

    if not published_job_ids:
        return []

    conditions = [
        Application.recruiter_id == recruiter_uuid,
        Application.job_id.in_(published_job_ids),
    ]

    if job_id:
        requested_job_id = parse_uuid(job_id, "job id")

        if requested_job_id not in published_job_ids:
            return []

        conditions.append(
            Application.job_id == requested_job_id
        )

    if status:
        conditions.append(
            Application.status == status
        )

    if min_score is not None:
        conditions.append(
            Application.match_score >= min_score
        )

    if max_score is not None:
        conditions.append(
            Application.match_score <= max_score
        )

    result = await db.execute(
        select(Application)
        .where(*conditions)
        .order_by(Application.applied_at.desc())
    )

    applications = result.scalars().all()

    results = []

    for application in applications:

        result = await db.execute(
            select(CandidateProfile).where(
                CandidateProfile.user_id == application.candidate_id
            )
        )
        profile = result.scalar_one_or_none()

        resume = None

        if application.resume_id:
            result = await db.execute(
                select(Resume).where(
                    Resume.id == application.resume_id,
                    Resume.candidate_id == application.candidate_id,
                )
            )
            resume = result.scalar_one_or_none()

        parsed_resume_data = get_resume_data(resume)

        candidate_skills = (
            (profile.skills if profile else None)
            or parsed_resume_data.get("skills", [])
        )

        if isinstance(candidate_skills, str):
            candidate_skills = [
                item.strip()
                for item in candidate_skills.split(",")
                if item.strip()
            ]

        if skill:
            skills_text = " ".join(
                str(item) for item in candidate_skills
            ).casefold()

            if skill.casefold() not in skills_text:
                continue

        result = await db.execute(
            select(User).where(
                User.id == application.candidate_id
            )
        )
        account = result.scalar_one_or_none()

        result = await db.execute(
            select(Job).where(
                Job.id == application.job_id
            )
        )
        job = result.scalar_one_or_none()

        analysis = None

        if application.analysis_id:
            result = await db.execute(
                select(ResumeAnalysis).where(
                    ResumeAnalysis.id == application.analysis_id
                )
            )
            analysis = result.scalar_one_or_none()

        app_doc = serialize_model(application)

        results.append({
            **app_doc,
            "candidate": {
                "id": str(application.candidate_id),
                "full_name": (
                    (account.full_name if account else "")
                    or (profile.headline if profile else "")
                ),
                "email": account.email if account else "",
                "phone": (
                    (profile.phone if profile else None)
                    or parsed_resume_data.get("phone")
                ),
                "education": (
                    (profile.education if profile else None)
                    or parsed_resume_data.get("education", [])
                ),
                "skills": candidate_skills,
                "experience": (
                    (profile.experience if profile else None)
                    or parsed_resume_data.get("experience", [])
                ),
            },
            "job": serialize_model(job),
            "analysis": serialize_model(analysis),
            "resume": (
                {
                    "id": str(resume.id),
                    "original_name": getattr(
                        resume,
                        "file_name",
                        "Resume",
                    ),
                    "status": resume.status,
                }
                if resume
                else None
            ),
        })

    return results
