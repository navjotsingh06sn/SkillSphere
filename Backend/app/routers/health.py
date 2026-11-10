from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import PyMongoError

from app.database.indexes import create_indexes
from app.db import seed_admin

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(request: Request):
    client = request.app.state.mongo_client
    try:
        await client.admin.command("ping")
        await create_indexes(request.app.state.database)
        await seed_admin(request.app.state.database)
        request.app.state.database_ready = True
        return {"status": "ready", "database": "connected"}
    except PyMongoError as error:
        request.app.state.database_ready = False
        raise HTTPException(status_code=503, detail="MongoDB is not reachable.") from error
