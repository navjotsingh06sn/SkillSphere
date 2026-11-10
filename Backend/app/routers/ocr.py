from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings
from app.database.collections import RESUMES
from app.dependencies import candidate_required, get_database
from app.routers.resumes import process_resume
from app.utils import parse_object_id

router = APIRouter(prefix="/ocr", tags=["resume OCR"])


@router.post("/process/{resume_id}", status_code=202)
async def process_existing_resume(
    resume_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(resume_id, "resume id")
    resume = await database[RESUMES].find_one({
        "_id": oid,
        "candidate_id": ObjectId(user["id"]),
    })
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")
    if resume["status"] == "processing":
        raise HTTPException(status_code=409, detail="Resume is already being processed.")
    path = Path(settings.upload_directory) / resume["storage_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Resume file is unavailable.")
    await database[RESUMES].update_one(
        {"_id": oid},
        {"$set": {"status": "processing"}, "$unset": {"error": ""}},
    )
    background_tasks.add_task(process_resume, database, oid, str(path), path.suffix.lower())
    return {"status": "processing"}
