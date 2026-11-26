import unittest
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import HTTPException

from app.config import settings
from app.models import User
from app.routers.auth import login
from app.schemas import LoginInput
from app.security import hash_password


class FakeResult:
    def __init__(self, user):
        self.user = user

    def scalar_one_or_none(self):
        return self.user


class FakeDatabase:
    def __init__(self, user=None, error=None):
        self.user = user
        self.error = error
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        if self.error:
            raise self.error
        return FakeResult(self.user)


def make_user(password="CorrectHorse123!", active=True):
    now = datetime.now(timezone.utc)
    return User(
        id=uuid4(),
        full_name="Example Candidate",
        email="candidate@example.test",
        password_hash=hash_password(password),
        role="candidate",
        is_active=active,
        token_version=0,
        created_at=now,
        updated_at=now,
    )


class LoginRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_password_returns_candidate_and_signed_token(self):
        user = make_user()
        db = FakeDatabase(user=user)

        result = await login(
            LoginInput(email="  CANDIDATE@EXAMPLE.TEST ", password="CorrectHorse123!"),
            db,
        )

        claims = jwt.decode(
            result["access_token"],
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        self.assertEqual(result["user"]["id"], str(user.id))
        self.assertEqual(result["user"]["role"], "candidate")
        self.assertEqual(claims["sub"], str(user.id))
        self.assertNotIn("password_hash", result["user"])
        self.assertIn("candidate@example.test", str(db.statement.compile().params.values()).lower())

    async def test_wrong_password_remains_401(self):
        with self.assertRaises(HTTPException) as response:
            await login(
                LoginInput(email="candidate@example.test", password="WrongPassword123!"),
                FakeDatabase(user=make_user()),
            )
        self.assertEqual(response.exception.status_code, 401)

    async def test_disabled_account_remains_forbidden(self):
        with self.assertRaises(HTTPException) as response:
            await login(
                LoginInput(email="candidate@example.test", password="CorrectHorse123!"),
                FakeDatabase(user=make_user(active=False)),
            )
        self.assertEqual(response.exception.status_code, 403)

    async def test_database_failure_is_logged_and_returns_safe_unavailable_response(self):
        with self.assertLogs("app.routers.auth", level="ERROR"):
            with self.assertRaises(HTTPException) as response:
                await login(
                    LoginInput(email="candidate@example.test", password="CorrectHorse123!"),
                    FakeDatabase(error=OSError("database unavailable")),
                )
        self.assertEqual(response.exception.status_code, 503)
        self.assertNotIn("database unavailable", response.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
