
import logging
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("uvicorn.error")


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={
        "server_settings": {
            "application_name": "skillsphere_backend",
        }
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def seed_admin() -> None:
    if not settings.admin_email or not settings.admin_password:
        logger.info("Admin seed skipped: credentials are not configured.")
        return

    from app.models import User
    from app.security import hash_password

    email = settings.admin_email.strip().lower()

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(User)
                    .where(User.email == email)
                    .with_for_update()
                )
                existing = result.scalar_one_or_none()

                if existing:
                    logger.info("Admin account already exists.")
                    return

                admin = User(
                    full_name="Administrator",
                    email=email,
                    password_hash=hash_password(
                        settings.admin_password
                    ),
                    role="admin",
                    is_active=True,
                    token_version=0,
                )

                session.add(admin)

            logger.info("Admin account seeded successfully.")

    except SQLAlchemyError:
        logger.exception("Database error while seeding admin account.")
    except Exception:
        logger.exception("Could not seed admin account.")


async def connect_to_database(app) -> None:
    app.state.database_ready = False

    try:
        upload_path = Path(settings.upload_directory)
        upload_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        app.state.database_ready = True

        logger.info(
            "Connected to PostgreSQL database successfully."
        )

        await seed_admin()

    except SQLAlchemyError:
        logger.exception(
            "PostgreSQL connection failed. Database readiness is false."
        )

    except OSError:
        logger.exception(
            "Could not create or access the upload directory."
        )

    except Exception:
        logger.exception(
            "Unexpected error during database initialization."
        )


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def close_database(app) -> None:
    app.state.database_ready = False

    try:
        await engine.dispose()
        logger.info("PostgreSQL connection pool disposed.")
    except Exception:
        logger.exception("Error while closing PostgreSQL connections.")
