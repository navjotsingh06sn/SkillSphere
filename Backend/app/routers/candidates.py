
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import candidate_required, get_database
from app.models import (
    Application,
    CandidateProfile,
    Job,
    Resume,
    SavedJob,
    User,
)
from app.pg_utils import parse_uuid, serialize_model
from app.routers.matching import normalize
from app.schemas import ProfileInput

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/profile")
async def get_profile(
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(CandidateProfile).where(
            CandidateProfile.user_id == user_uuid
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="Candidate profile was not found.",
        )

    doc = serialize_model(profile)
    doc["email"] = user.get("email")
    doc["full_name"] = user.get("full_name")

    links = doc.get("links") or {}

    for key in ["linkedin", "github", "portfolio"]:
        if not doc.get(key) and key in links:
            doc[key] = links[key]

    return doc


@router.put("/profile")
async def update_profile(
    data: ProfileInput,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")
    updates = data.model_dump(exclude_unset=True)

    if "skills" in updates and updates["skills"]:
        updates["skills"] = sorted({
            skill.strip()
            for skill in updates["skills"]
            if skill.strip()
        })

    result = await db.execute(
        select(CandidateProfile).where(
            CandidateProfile.user_id == user_uuid
        )
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = CandidateProfile(user_id=user_uuid)
        db.add(profile)

    if updates.get("full_name"):
        user_result = await db.execute(
            select(User).where(User.id == user_uuid)
        )
        user_record = user_result.scalar_one_or_none()

        if user_record:
            user_record.full_name = updates["full_name"]

    profile_fields = [
        "phone",
        "location",
        "headline",
        "bio",
        "summary",
        "skills",
        "education",
        "experience",
        "projects",
        "certifications",
    ]

    for field in profile_fields:
        if field in updates:
            setattr(profile, field, updates[field])

    current_links = dict(profile.links or {})

    for link_key in ["linkedin", "github", "portfolio"]:
        if link_key in updates:
            current_links[link_key] = updates[link_key]

    profile.links = current_links
    profile.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(profile)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not update candidate profile.",
        )

    doc = serialize_model(profile)
    doc["email"] = user.get("email")

    user_result = await db.execute(
        select(User).where(User.id == user_uuid)
    )
    user_record = user_result.scalar_one_or_none()

    doc["full_name"] = (
        user_record.full_name
        if user_record
        else user.get("full_name")
    )

    for link_key in ["linkedin", "github", "portfolio"]:
        doc[link_key] = current_links.get(link_key)

    return doc


@router.get("/dashboard")
async def candidate_dashboard(
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    candidate_id = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(CandidateProfile).where(
            CandidateProfile.user_id == candidate_id
        )
    )
    profile = result.scalar_one_or_none()

    counts = {}

    for key, statuses in [
        ("pending", ["applied", "under_review"]),
        ("shortlisted", ["shortlisted"]),
        ("interviews", ["interview"]),
        ("selected", ["selected"]),
    ]:
        res = await db.execute(
            select(func.count(Application.id)).where(
                Application.candidate_id == candidate_id,
                Application.status.in_(statuses),
            )
        )
        counts[key] = res.scalar() or 0

    total_apps_res = await db.execute(
        select(func.count(Application.id)).where(
            Application.candidate_id == candidate_id
        )
    )
    total_applications = total_apps_res.scalar() or 0

    total_fields = [
        "full_name",
        "phone",
        "location",
        "headline",
        "summary",
        "skills",
        "education",
        "experience",
    ]

    completed = 0

    if profile:
        profile_dict = {
            "full_name": user.get("full_name"),
            "phone": profile.phone,
            "location": profile.location,
            "headline": profile.headline,
            "summary": profile.summary or profile.bio,
            "skills": profile.skills,
            "education": profile.education,
            "experience": profile.experience,
        }

        completed = sum(
            bool(profile_dict.get(field))
            for field in total_fields
        )

    recent_cursor = await db.execute(
        select(Application, Job)
        .outerjoin(Job, Application.job_id == Job.id)
        .where(Application.candidate_id == candidate_id)
        .order_by(Application.applied_at.desc())
        .limit(5)
    )

    recent = []

    for app_row, job_row in recent_cursor.all():
        app_data = serialize_model(app_row)

        if job_row:
            app_data["job_title"] = job_row.title
            app_data["company_name"] = job_row.company_name
            app_data["location"] = job_row.location

        recent.append(app_data)

    candidate_skills = (
        list(profile.skills)
        if profile and profile.skills
        else []
    )

    resume_res = await db.execute(
        select(Resume)
        .where(
            Resume.candidate_id == candidate_id,
            Resume.status == "completed",
        )
        .order_by(Resume.created_at.desc())
        .limit(1)
    )

    latest_resume = resume_res.scalar_one_or_none()

    if latest_resume and latest_resume.parsed_data:
        extracted = latest_resume.parsed_data.get("skills", [])

        if extracted:
            candidate_skills = list(
                set(candidate_skills) | set(extracted)
            )

    candidate_keys = {
        normalize(skill)
        for skill in candidate_skills
        if normalize(skill)
    }

    jobs_res = await db.execute(
        select(Job)
        .where(
            Job.status == "published",
            Job.is_demo.is_(False),
        )
        .order_by(Job.created_at.desc())
        .limit(100)
    )

    jobs = jobs_res.scalars().all()

    scored_jobs = []

    for job in jobs:
        req_skills = job.required_skills or []

        required = {
            normalize(skill)
            for skill in req_skills
            if normalize(skill)
        }

        score = (
            round(
                100 * len(candidate_keys & required) / len(required)
            )
            if required
            else None
        )

        job_view = serialize_model(job)

        job_view["match_percentage"] = score

        scored_jobs.append(
            (
                score if score is not None else -1,
                job.created_at,
                job_view,
            )
        )

    scored_jobs.sort(
        key=lambda item: (
            item[0],
            item[1] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    recommended = [
        item[2]
        for item in scored_jobs[:5]
    ]

    return {
        "total_applications": total_applications,
        "pending_applications": counts["pending"],
        "shortlisted": counts["shortlisted"],
        "interviews": counts["interviews"],
        "selected": counts["selected"],
        "profile_completion": round(
            completed / len(total_fields) * 100
        ),
        "recent_applications": recent,
        "recommended_jobs": recommended,
    }


@router.get("/saved-jobs")
async def saved_jobs(
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    candidate_id = parse_uuid(user["id"], "user id")

    result = await db.execute(
        select(Job)
        .join(SavedJob, SavedJob.job_id == Job.id)
        .where(SavedJob.candidate_id == candidate_id)
        .order_by(SavedJob.created_at.desc())
    )

    jobs = result.scalars().all()

    return [
        serialize_model(job)
        for job in jobs
    ]


@router.post("/saved-jobs/{job_id}")
async def save_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    candidate_id = parse_uuid(user["id"], "user id")
    job_uuid = parse_uuid(job_id, "job id")

    result = await db.execute(
        select(Job).where(
            Job.id == job_uuid,
            Job.status == "published",
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Published job was not found.",
        )

    if job.is_demo:
        raise HTTPException(
            status_code=409,
            detail="Demo jobs cannot be saved.",
        )

    saved_entry = SavedJob(
        candidate_id=candidate_id,
        job_id=job_uuid,
    )

    db.add(saved_entry)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()

    return {"saved": True}


@router.delete("/saved-jobs/{job_id}")
async def unsave_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    candidate_id = parse_uuid(user["id"], "user id")
    job_uuid = parse_uuid(job_id, "job id")

    await db.execute(
        delete(SavedJob).where(
            SavedJob.candidate_id == candidate_id,
            SavedJob.job_id == job_uuid,
        )
    )

    await db.commit()

    return {"saved": False}
