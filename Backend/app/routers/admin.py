
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import admin_required, get_database
from app.models import (
    Application,
    Company,
    Job,
    User,
)
from app.pg_utils import parse_uuid, serialize_model

router = APIRouter(prefix="/admin", tags=["admin"])


def serialize_public_user(user: User) -> dict:
    doc = serialize_model(user)

    excluded_fields = {
        "password_hash",
        "password_reset_token_hash",
        "password_reset_expires_at",
    }

    for field in excluded_fields:
        doc.pop(field, None)

    return doc


async def monthly_counts(
    db: AsyncSession,
    model,
    date_column,
    extra_filter=None,
) -> list[dict]:
    month_col = func.to_char(date_column, "YYYY-MM").label("month")

    stmt = (
        select(month_col, func.count(model.id))
        .where(date_column.isnot(None))
    )

    if extra_filter is not None:
        stmt = stmt.where(extra_filter)

    stmt = (
        stmt.group_by(month_col)
        .order_by(month_col.desc())
        .limit(6)
    )

    rows = (await db.execute(stmt)).all()

    results = [
        {"month": row[0], "count": row[1]}
        for row in rows
    ]

    return list(reversed(results))


@router.get("/analytics")
async def analytics(
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    total_users = (
        await db.scalar(select(func.count(User.id)))
    ) or 0

    total_candidates = (
        await db.scalar(
            select(func.count(User.id)).where(
                User.role == "candidate"
            )
        )
    ) or 0

    total_recruiters = (
        await db.scalar(
            select(func.count(User.id)).where(
                User.role == "recruiter"
            )
        )
    ) or 0

    total_companies = (
        await db.scalar(select(func.count(Company.id)))
    ) or 0

    total_jobs = (
        await db.scalar(
            select(func.count(Job.id)).where(
                Job.is_demo.is_(False)
            )
        )
    ) or 0

    active_jobs = (
        await db.scalar(
            select(func.count(Job.id)).where(
                Job.status == "published",
                Job.is_demo.is_(False),
            )
        )
    ) or 0

    total_applications = (
        await db.scalar(
            select(func.count(Application.id))
        )
    ) or 0

    roles_data = []

    for role in ["candidate", "recruiter", "admin"]:
        count = (
            await db.scalar(
                select(func.count(User.id)).where(
                    User.role == role
                )
            )
        ) or 0

        roles_data.append({
            "role": role,
            "count": count,
        })

    user_growth = await monthly_counts(
        db,
        User,
        User.created_at,
    )

    job_trends = await monthly_counts(
        db,
        Job,
        Job.created_at,
        extra_filter=Job.is_demo.is_(False),
    )

    app_trends = await monthly_counts(
        db,
        Application,
        Application.applied_at,
    )

    return {
        "total_users": total_users,
        "total_candidates": total_candidates,
        "total_recruiters": total_recruiters,
        "total_companies": total_companies,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_applications": total_applications,
        "users_by_role": roles_data,
        "user_growth": user_growth,
        "job_posting_trends": job_trends,
        "application_trends": app_trends,
    }


@router.get("/users")
async def list_users(
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    total = (
        await db.scalar(select(func.count(User.id)))
    ) or 0

    stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    users = (await db.execute(stmt)).scalars().all()

    return {
        "items": [
            serialize_public_user(item)
            for item in users
        ],
        "total": total,
        "page": page,
    }


@router.put("/users/{user_id}/status")
async def set_user_status(
    user_id: str,
    data: dict,
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    if user_id == user["id"]:
        raise HTTPException(
            status_code=400,
            detail="You cannot disable your own account.",
        )

    if not isinstance(data.get("is_active"), bool):
        raise HTTPException(
            status_code=422,
            detail="is_active must be true or false.",
        )

    user_uuid = parse_uuid(user_id, "user id")

    target_user = await db.scalar(
        select(User).where(User.id == user_uuid)
    )

    if not target_user:
        raise HTTPException(
            status_code=404,
            detail="User was not found.",
        )

    target_user.is_active = data["is_active"]

    await db.commit()

    return {
        "is_active": data["is_active"]
    }


@router.get("/jobs")
async def admin_jobs(
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    stmt = (
        select(Job)
        .order_by(Job.created_at.desc())
        .limit(200)
    )

    jobs = (await db.execute(stmt)).scalars().all()

    return [
        serialize_model(job)
        for job in jobs
    ]


@router.put("/jobs/{job_id}/status")
async def moderate_job(
    job_id: str,
    data: dict,
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    new_status = data.get("status")

    if new_status not in {
        "draft",
        "published",
        "closed",
        "rejected",
    }:
        raise HTTPException(
            status_code=422,
            detail="Unsupported job status.",
        )

    job_uuid = parse_uuid(job_id, "job id")

    job = await db.scalar(
        select(Job).where(Job.id == job_uuid)
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job was not found.",
        )

    now = datetime.now(timezone.utc)

    job.status = new_status

    extra = dict(job.extra_data or {})
    extra["moderated_by"] = user["id"]
    extra["moderated_at"] = now.isoformat()

    job.extra_data = extra
    job.updated_at = now

    await db.commit()

    return {
        "status": new_status
    }


@router.get("/companies")
async def admin_companies(
    user: dict = Depends(admin_required),
    db: AsyncSession = Depends(get_database),
):
    stmt = (
        select(Company)
        .order_by(Company.created_at.desc())
        .limit(500)
    )

    companies = (await db.execute(stmt)).scalars().all()

    items = []

    for company in companies:
        doc = serialize_model(company)
        doc["company_name"] = company.name
        items.append(doc)

    return items
