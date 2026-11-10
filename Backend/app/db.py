import logging
from pathlib import Path

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.config import settings

logger = logging.getLogger("uvicorn.error")


async def connect_to_mongodb(app) -> None:
    client = AsyncMongoClient(settings.mongodb_url, serverSelectionTimeoutMS=3000)
    app.state.mongo_client = client
    app.state.database = client[settings.database_name]
    app.state.database_ready = False
    Path(settings.upload_directory).mkdir(parents=True, exist_ok=True)

    try:
        await client.admin.command("ping")
        from app.database.indexes import create_indexes
        await create_indexes(app.state.database)
        await seed_admin(app.state.database)
        app.state.database_ready = True
        logger.info("Connected to MongoDB database %s", settings.database_name)
    except PyMongoError as error:
        logger.warning(
            "MongoDB is unavailable. API started without database readiness (%s: %s).",
            type(error).__name__,
            error,
        )


async def seed_admin(database: AsyncDatabase) -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    from app.security import hash_password
    await database.users.update_one(
        {"email": settings.admin_email.lower()},
        {"$setOnInsert": {
            "email": settings.admin_email.lower(),
            "password_hash": hash_password(settings.admin_password),
            "role": "admin",
            "is_active": True,
        }},
        upsert=True,
    )


async def close_mongodb(app) -> None:
    client = getattr(app.state, "mongo_client", None)
    if client is not None:
        await client.close()


def get_database(app) -> AsyncDatabase:
    return app.state.database
