
import jwt
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Company, RecruiterProfile, User


bearer_scheme = HTTPBearer(auto_error=False)


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_database),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        token_version = payload.get("ver", 0)

        if not user_id:
            raise ValueError("Missing user id")

        parsed_id = UUID(str(user_id))

    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    result = await db.execute(select(User).where(User.id == parsed_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is unavailable.",
        )

    company_name = None
    if user.role == "recruiter":
        recruiter_result = await db.execute(
            select(RecruiterProfile).where(RecruiterProfile.user_id == user.id)
        )
        recruiter = recruiter_result.scalar_one_or_none()
        if recruiter and recruiter.company_id:
            company_result = await db.execute(
                select(Company).where(Company.id == recruiter.company_id)
            )
            company = company_result.scalar_one_or_none()
            if company:
                company_name = company.name

    return {
        "id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "company_name": company_name,
        "is_active": user.is_active,
    }


def require_roles(*allowed_roles: str):
    async def role_check(
        user: dict = Depends(get_current_user),
    ) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission.",
            )
        return user

    return role_check


candidate_required = require_roles("candidate")
recruiter_required = require_roles("recruiter")
admin_required = require_roles("admin")
