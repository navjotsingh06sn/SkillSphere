import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings
from app.database.collections import USERS, CANDIDATE_PROFILES, RECRUITER_PROFILES
from app.dependencies import get_database, get_current_user
from app.schemas import AccountSettingsInput, RegisterInput, LoginInput, ForgotPasswordInput, ResetPasswordInput
from app.security import create_access_token, hash_password, verify_password
from app.utils import serialize_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


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
    message = EmailMessage()
    message["Subject"] = "Reset your SkillSphere password"
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message.set_content(
        "Use this one-time link to reset your SkillSphere password. "
        "It expires in 15 minutes. If you did not request this, ignore this email.\\n\\n"
        + reset_link
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception:
        logger.exception("Could not send a SkillSphere password reset email.")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterInput, database: AsyncDatabase = Depends(get_database)):
    email = data.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    user = {
        "full_name": data.full_name.strip(),
        "email": email,
        "password_hash": hash_password(data.password),
        "role": data.role,
        "token_version": 0,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        result = await database[USERS].insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    profile_collection = CANDIDATE_PROFILES if data.role == "candidate" else RECRUITER_PROFILES
    await database[profile_collection].insert_one({
        "user_id": result.inserted_id,
        "full_name": user["full_name"],
        "created_at": user["created_at"],
    })
    public_user = serialize_document(user)
    public_user.pop("password_hash", None)
    public_user.pop("token_version", None)
    return {
        "user": public_user,
        "access_token": create_access_token(public_user["id"], public_user["role"]),
        "token_type": "bearer",
    }


@router.post("/login")
async def login(data: LoginInput, database: AsyncDatabase = Depends(get_database)):
    email = data.email.strip().lower()
    user = await database[USERS].find_one({"email": email})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="This account has been disabled.")
    public_user = serialize_document(user)
    public_user.pop("password_hash", None)
    public_user.pop("token_version", None)
    return {
        "user": public_user,
        "access_token": create_access_token(
            public_user["id"],
            user["role"],
            user.get("token_version", 0),
        ),
        "token_type": "bearer",
    }


@router.put("/account")
async def update_account(
    data: AccountSettingsInput,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    account = await database[USERS].find_one({"_id": ObjectId(user["id"])})
    if not account or not verify_password(data.current_password, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    updates = {}
    if data.full_name is not None:
        full_name = data.full_name.strip()
        if len(full_name) < 2:
            raise HTTPException(status_code=422, detail="Name must contain at least 2 characters.")
        updates["full_name"] = full_name
    if data.email is not None:
        email = data.email.strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        updates["email"] = email
    if data.new_password is not None:
        updates["password_hash"] = hash_password(data.new_password)

    if not updates:
        raise HTTPException(status_code=422, detail="Enter at least one account change.")

    try:
        result = await database[USERS].update_one(
            {"_id": ObjectId(user["id"])},
            {
                "$set": updates,
                **({"$inc": {"token_version": 1}} if data.new_password else {}),
            },
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Account was not found.")

    if "full_name" in updates:
        await database[CANDIDATE_PROFILES].update_one(
            {"user_id": ObjectId(user["id"])},
            {"$set": {"full_name": updates["full_name"]}},
        )
        await database[RECRUITER_PROFILES].update_one(
            {"user_id": ObjectId(user["id"])},
            {"$set": {"full_name": updates["full_name"]}},
        )

    account.update(updates)
    if data.new_password:
        account["token_version"] = account.get("token_version", 0) + 1
    public_user = serialize_document(account)
    public_user.pop("password_hash", None)
    public_user.pop("token_version", None)
    return {
        "user": public_user,
        "access_token": create_access_token(
            public_user["id"],
            public_user["role"],
            account.get("token_version", 0),
        ),
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    await database[USERS].update_one(
        {"_id": ObjectId(user["id"])},
        {"$inc": {"token_version": 1}},
    )
    return {"message": "Logged out."}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordInput,
    background_tasks: BackgroundTasks,
    database: AsyncDatabase = Depends(get_database),
):
    email = data.email.strip().lower()
    user = await database[USERS].find_one({"email": email, "is_active": True})
    if user:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await database[USERS].update_one(
            {"_id": user["_id"]},
            {"$set": {
                "password_reset_token_hash": token_hash,
                "password_reset_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
            }},
        )
        background_tasks.add_task(send_reset_email, email, token)
    return {"message": "If the account exists, password reset instructions will be sent."}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordInput,
    database: AsyncDatabase = Depends(get_database),
):
    token_hash = hashlib.sha256(data.token.encode()).hexdigest()
    result = await database[USERS].update_one(
        {
            "email": data.email.strip().lower(),
            "is_active": True,
            "password_reset_token_hash": token_hash,
            "password_reset_expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        {
            "$set": {"password_hash": hash_password(data.new_password)},
            "$inc": {"token_version": 1},
            "$unset": {
                "password_reset_token_hash": "",
                "password_reset_expires_at": "",
            },
        },
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="The reset link is invalid or expired.")
    return {"message": "Password updated. Please log in with your new password."}


@router.get("/me")
async def current_user(user: dict = Depends(get_current_user)):
    return user
