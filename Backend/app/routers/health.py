
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import engine

router = APIRouter(tags=["health"])
logger = logging.getLogger("uvicorn.error")


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "database": "PostgreSQL",
    }


@router.get("/health/ready")
async def readiness_check():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return {
            "status": "ready",
            "database": "PostgreSQL",
        }

    except (SQLAlchemyError, OSError) as error:
        logger.warning("Database readiness check failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL is not reachable.",
        ) from error
