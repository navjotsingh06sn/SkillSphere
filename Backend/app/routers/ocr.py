
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.dependencies import candidate_required, get_database
from app.models import Resume
from app.pg_utils import parse_uuid
from app.routers.resumes import process_resume
from app.services.resume_ocr import (
    ResumeOCREngineError,
    ResumeOCRInputError,
    UnsupportedResumeFormat,
    extract_resume,
)

router = APIRouter(prefix="/ocr", tags=["resume OCR"])


@router.post("/extract")
async def extract_uploaded_resume(
    file: UploadFile = File(...),
    _user: dict = Depends(candidate_required),
):
    max_size = settings.max_upload_size_mb * 1024 * 1024
    contents = bytearray()

    try:
        while chunk := await file.read(64 * 1024):
            contents.extend(chunk)

            if len(contents) > max_size:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File is too large. The maximum upload size "
                        f"is {settings.max_upload_size_mb} MB."
                    ),
                )

        result = await run_in_threadpool(
            extract_resume,
            file.filename or "",
            bytes(contents),
        )

    except UnsupportedResumeFormat as exc:
        raise HTTPException(
            status_code=415,
            detail=str(exc),
        ) from exc

    except ResumeOCRInputError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except ResumeOCREngineError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

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
    db: AsyncSession = Depends(get_database),
):
    resume_uuid = parse_uuid(resume_id, "resume id")
    candidate_uuid = parse_uuid(user["id"], "candidate id")

    resume = await db.scalar(
        select(Resume).where(
            Resume.id == resume_uuid,
            Resume.candidate_id == candidate_uuid,
        )
    )

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="Resume was not found.",
        )

    if resume.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Resume is already being processed.",
        )

    path = (
        Path(resume.file_path)
        if resume.file_path
        else (
            Path(settings.upload_directory)
            / (resume.file_name or "")
        )
    )

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Resume file is unavailable.",
        )

    resume.status = "processing"
    resume.error = None

    await db.commit()

    background_tasks.add_task(
        process_resume,
        resume.id,
        str(path),
        path.suffix.lower(),
    )

    return {
        "status": "processing"
    }
