
import logging
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

logger = logging.getLogger("uvicorn.error")


# Base class for all PostgreSQL models
class Base(DeclarativeBase):
    pass


# PostgreSQL async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


# Async database session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def seed_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    from app.models import User
    from app.security import hash_password
    try:
        async with AsyncSessionLocal() as session:
            email = settings.admin_email.strip().lower()
            res = await session.execute(select(User).where(User.email == email))
            existing = res.scalar_one_or_none()
            if not existing:
                user = User(
                    full_name="Administrator",
                    email=email,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    is_active=True,
                    token_version=0,
                )
                session.add(user)
                await session.commit()
                logger.info("Seeded admin account %s", email)
    except Exception as error:
        logger.warning("Could not seed admin user: %s", error)


async def connect_to_database(app) -> None:
    app.state.database_ready = False
    Path(settings.upload_directory).mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        app.state.database_ready = True

        logger.info(
            "Connected to PostgreSQL database successfully."
        )
        await seed_admin()

    except SQLAlchemyError as error:
        logger.warning(
            "PostgreSQL is unavailable. "
            "Database readiness is false (%s: %s).",
            type(error).__name__,
            error,
        )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def close_database(app) -> None:
    await engine.dispose()
    logger.info("PostgreSQL connection closed.")

