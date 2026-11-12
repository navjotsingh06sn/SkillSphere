
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database": "PostgreSQL",
    }


@router.get("/health/ready")
async def readiness_check(request: Request):
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        request.app.state.database_ready = True

        return {
            "status": "ready",
            "database": "PostgreSQL",
        }

    except SQLAlchemyError as error:
        request.app.state.database_ready = False

        raise HTTPException(
            status_code=503,
            detail="PostgreSQL is not reachable.",
        ) from error
