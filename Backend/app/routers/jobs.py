
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_database, recruiter_required
from app.models import Application, Company, Job, RecruiterProfile
from app.pg_utils import parse_uuid, serialize_model
from app.schemas import JobInput

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
    db: AsyncSession = Depends(get_database),
):
    conditions = [Job.status == "published"]

    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern),
                Job.company_name.ilike(pattern),
            )
        )

    if location:
        conditions.append(Job.location.ilike(f"%{location.strip()}%"))

    if job_type:
        conditions.append(Job.job_type == job_type)

    if skill:
        conditions.append(
            cast(Job.required_skills, String).ilike(f"%{skill.strip()}%")
        )

    if min_salary is not None:
        conditions.append(
            or_(
                Job.salary_min >= min_salary,
                Job.salary_max >= min_salary,
            )
        )

    if max_experience is not None:
        conditions.append(Job.experience_min <= max_experience)

    total_result = await db.execute(
        select(func.count(Job.id)).where(*conditions)
    )
    total = total_result.scalar() or 0

    query = select(Job).where(*conditions)

    if sort == "oldest":
        query = query.order_by(Job.created_at.asc())
    elif sort == "salary_high":
        query = query.order_by(
            Job.salary_min.desc().nullslast(),
            Job.created_at.desc(),
        )
    elif sort == "salary_low":
        query = query.order_by(
            Job.salary_min.asc().nullslast(),
            Job.created_at.desc(),
        )
    else:
        query = query.order_by(Job.created_at.desc())

    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return {
        "items": [serialize_model(job) for job in jobs],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobInput,
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

    company = None

    if profile and profile.company_id:
        result = await db.execute(
            select(Company).where(Company.id == profile.company_id)
        )
        company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(
            status_code=400,
            detail="Create your company profile before posting a job.",
        )

    if (
        data.experience_max is not None
        and data.experience_max < data.experience_min
    ):
        raise HTTPException(
            status_code=422,
            detail="Maximum experience must be at least the minimum.",
        )

    extra = {}

    if data.application_deadline:
        extra["application_deadline"] = (
            data.application_deadline.isoformat()
        )

    job = Job(
        recruiter_id=recruiter_uuid,
        company_id=company.id,
        company_name=company.name,
        title=data.title,
        description=data.description,
        responsibilities=data.responsibilities,
        requirements=data.requirements,
        required_skills=data.required_skills,
        location=data.location,
        experience_min=data.experience_min,
        experience_max=data.experience_max,
        job_type=data.job_type,
        salary_min=(
            float(data.salary_min)
            if data.salary_min is not None
            else None
        ),
        salary_max=(
            float(data.salary_max)
            if data.salary_max is not None
            else None
        ),
        status=data.status,
        extra_data=extra,
    )

    db.add(job)
    await db.commit()
    await db.refresh(job)

    return serialize_model(job)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_database),
):
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
            detail="Job was not found.",
        )

    return serialize_model(job)


@router.put("/{job_id}")
async def update_job(
    job_id: str,
    data: JobInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    job_uuid = parse_uuid(job_id, "job id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(Job).where(
            Job.id == job_uuid,
            Job.recruiter_id == recruiter_uuid,
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job was not found.",
        )

    if (
        data.experience_max is not None
        and data.experience_max < data.experience_min
    ):
        raise HTTPException(
            status_code=422,
            detail="Maximum experience must be at least the minimum.",
        )

    job.title = data.title
    job.description = data.description
    job.responsibilities = data.responsibilities
    job.requirements = data.requirements
    job.required_skills = data.required_skills
    job.location = data.location
    job.experience_min = data.experience_min
    job.experience_max = data.experience_max
    job.job_type = data.job_type
    job.salary_min = (
        float(data.salary_min)
        if data.salary_min is not None
        else None
    )
    job.salary_max = (
        float(data.salary_max)
        if data.salary_max is not None
        else None
    )
    job.status = data.status
    job.updated_at = datetime.now(timezone.utc)

    extra = dict(job.extra_data or {})

    if data.application_deadline:
        extra["application_deadline"] = (
            data.application_deadline.isoformat()
        )

    job.extra_data = extra

    await db.commit()
    await db.refresh(job)

    return serialize_model(job)


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_job(
    job_id: str,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    job_uuid = parse_uuid(job_id, "job id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    result = await db.execute(
        select(Job).where(
            Job.id == job_uuid,
            Job.recruiter_id == recruiter_uuid,
        )
    )

    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job was not found.",
        )

    app_count_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.job_id == job_uuid
        )
    )

    application_count = app_count_result.scalar() or 0

    if application_count:
        raise HTTPException(
            status_code=409,
            detail="Close this role instead of deleting a job with applications.",
        )

    await db.delete(job)
    await db.commit()

    return None
