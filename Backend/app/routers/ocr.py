from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pymongo.asynchronous.database import AsyncDatabase
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.collections import RESUMES
from app.dependencies import candidate_required, get_database
from app.routers.resumes import process_resume
from app.services.resume_ocr import (
    ResumeOCREngineError,
    ResumeOCRInputError,
    UnsupportedResumeFormat,
    extract_resume,
)
from app.utils import parse_object_id

router = APIRouter(prefix="/ocr", tags=["resume OCR"])


@router.post("/extract")
async def extract_uploaded_resume(
    file: UploadFile = File(...),
    _user: dict = Depends(candidate_required),
):
    del _user
    max_size = settings.max_upload_size_mb * 1024 * 1024
    contents = bytearray()

    try:
        while chunk := await file.read(64 * 1024):
            contents.extend(chunk)
            if len(contents) > max_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"File is too large. The maximum upload size is {settings.max_upload_size_mb} MB.",
                )

        result = await run_in_threadpool(
            extract_resume, file.filename or "", bytes(contents)
        )
    except UnsupportedResumeFormat as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ResumeOCRInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ResumeOCREngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        await file.close()

    response = {
        "success": True,
        "message": "Resume text extracted successfully.",
        "filename": file.filename,
        "extracted_text": result["extracted_text"],
        "extraction_method": result["extraction_method"],
    }
    if result["page_count"] is not None:
        response["page_count"] = result["page_count"]
    return response


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
