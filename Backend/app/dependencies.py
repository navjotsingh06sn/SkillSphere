from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.security import settings
from app.database.collections import USERS

bearer_scheme = HTTPBearer(auto_error=False)


async def get_database(request: Request) -> AsyncDatabase:
    return request.app.state.database


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    database: AsyncDatabase = Depends(get_database),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if not user_id or not ObjectId.is_valid(user_id):
            raise ValueError("Invalid user id")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = await database[USERS].find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("is_active", True) or payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status_code=401, detail="User account is unavailable.")
    user["id"] = str(user.pop("_id"))
    user.pop("password_hash", None)
    user.pop("token_version", None)
    return user


def require_roles(*allowed_roles: str):
    async def role_check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="You do not have permission.")
        return user
    return role_check


candidate_required = require_roles("candidate")
recruiter_required = require_roles("recruiter")
admin_required = require_roles("admin")



