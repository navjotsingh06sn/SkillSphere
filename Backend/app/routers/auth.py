
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_database
from app.models import CandidateProfile, RecruiterProfile, User
from app.pg_utils import serialize_model
from app.schemas import (
    AccountSettingsInput,
    ForgotPasswordInput,
    LoginInput,
    RegisterInput,
    ResetPasswordInput,
)
from app.security import create_access_token, hash_password, verify_password
from app.services.smtp import EmailDeliveryError, send_smtp_email_sync
from app.services.smtp import EmailDeliveryError, send_smtp_email_sync
from app.services.smtp import EmailDeliveryError, send_smtp_email_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

AUTH_EXCLUDE_FIELDS = {
    "password_hash",
    "token_version",
    "password_reset_token_hash",
    "password_reset_expires_at",
}


def get_public_user(user: User) -> dict:
    user_data = serialize_model(user)

    return {
        key: value
        for key, value in user_data.items()
        if key not in AUTH_EXCLUDE_FIELDS
    }


def send_reset_email(email: str, token: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("Password reset requested but SMTP is not configured.")
        return

    reset_link = (
        settings.frontend_url.rstrip("/")
        + "/reset-password?email="
        + quote(email)
        + "&token="
        + quote(token)
    )
    text_content = (
        "Use this one-time link to reset your SkillSphere password. "
        "It expires in 15 minutes. If you did not request this, ignore this email.\n\n"
        + reset_link
    )
    try:
        send_smtp_email_sync(email, "Reset your SkillSphere password", text_content)
    except EmailDeliveryError:
        logger.exception("Could not send a SkillSphere password reset email.")

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterInput,
    db: AsyncSession = Depends(get_database),
):
    email = data.email.strip().lower()
    full_name = data.full_name.strip()

    if len(full_name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Name must contain at least 2 characters.",
        )

    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(
            status_code=422,
            detail="Enter a valid email address.",
        )

    if data.role not in {"candidate", "recruiter"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid account role.",
        )

    user = User(
        full_name=full_name,
        email=email,
        password_hash=hash_password(data.password),
        role=data.role,
        token_version=0,
        is_active=True,
    )

    db.add(user)

    try:
        await db.flush()

        if data.role == "candidate":
            profile = CandidateProfile(
                user_id=user.id,
                skills=[],
                education=[],
                experience=[],
                projects=[],
                certifications=[],
                links={},
            )
        else:
            profile = RecruiterProfile(user_id=user.id)

        db.add(profile)

        await db.commit()
        await db.refresh(user)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    except Exception:
        await db.rollback()
        logger.exception("Account registration failed.")
        raise HTTPException(
            status_code=500,
            detail="Could not create the account.",
        )

    public_user = get_public_user(user)

    return {
        "user": public_user,
        "access_token": create_access_token(
            str(user.id),
            user.role,
            user.token_version,
        ),
        "token_type": "bearer",
    }


@router.post("/login")
async def login(
    data: LoginInput,
    db: AsyncSession = Depends(get_database),
):
    email = data.email.strip().lower()

    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(
        data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Email or password is incorrect.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="This account has been disabled.",
        )

    public_user = get_public_user(user)

    return {
        "user": public_user,
        "access_token": create_access_token(
            str(user.id),
            user.role,
            user.token_version,
        ),
        "token_type": "bearer",
    }


@router.put("/account")
async def update_account(
    data: AccountSettingsInput,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    try:
        user_uuid = UUID(str(user["id"]))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid user session.",
        )

    result = await db.execute(
        select(User).where(User.id == user_uuid)
    )
    account = result.scalar_one_or_none()

    if not account or not verify_password(
        data.current_password,
        account.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect.",
        )

    updates = False

    if data.full_name is not None:
        full_name = data.full_name.strip()

        if len(full_name) < 2:
            raise HTTPException(
                status_code=422,
                detail="Name must contain at least 2 characters.",
            )

        account.full_name = full_name
        updates = True

    if data.email is not None:
        email = data.email.strip().lower()

        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise HTTPException(
                status_code=422,
                detail="Enter a valid email address.",
            )

        account.email = email
        updates = True

    if data.new_password is not None:
        if len(data.new_password) < 8:
            raise HTTPException(
                status_code=422,
                detail="New password must contain at least 8 characters.",
            )

        account.password_hash = hash_password(data.new_password)
        account.token_version += 1
        updates = True

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Enter at least one account change.",
        )

    try:
        await db.commit()
        await db.refresh(account)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    except Exception:
        await db.rollback()
        logger.exception("Account update failed.")
        raise HTTPException(
            status_code=500,
            detail="Could not update the account.",
        )

    public_user = get_public_user(account)

    return {
        "user": public_user,
        "access_token": create_access_token(
            str(account.id),
            account.role,
            account.token_version,
        ),
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    try:
        user_uuid = UUID(str(user["id"]))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid user session.",
        )

    result = await db.execute(
        select(User).where(User.id == user_uuid)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=401,
            detail="User account not found.",
        )

    account.token_version += 1
    await db.commit()

    return {"message": "Logged out."}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_database),
):
    email = data.email.strip().lower()

    result = await db.execute(
        select(User).where(
            User.email == email,
            User.is_active.is_(True),
        )
    )

    user = result.scalar_one_or_none()

    if user:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=15)
        )

        await db.commit()

        background_tasks.add_task(
            send_reset_email,
            email,
            token,
        )

    return {
        "message": (
            "If the account exists, password reset instructions "
            "will be sent."
        )
    }


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordInput,
    db: AsyncSession = Depends(get_database),
):
    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=422,
            detail="Password must contain at least 8 characters.",
        )

    token_hash = hashlib.sha256(
        data.token.encode()
    ).hexdigest()

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(User).where(
            User.email == data.email.strip().lower(),
            User.is_active.is_(True),
            User.password_reset_token_hash == token_hash,
            User.password_reset_expires_at > now,
        ).with_for_update()
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=400,
            detail="The reset link is invalid or expired.",
        )

    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None

    await db.commit()

    return {
        "message": (
            "Password updated. Please log in with your new password."
        )
    }


@router.get("/me")
async def current_user(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    try:
        user_uuid = UUID(str(user["id"]))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid user session.",
        )

    result = await db.execute(
        select(User).where(
            User.id == user_uuid,
            User.is_active.is_(True),
        )
    )

    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=401,
            detail="User account not found or disabled.",
        )

    return get_public_user(account)
