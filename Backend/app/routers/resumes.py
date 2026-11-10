import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytesseract
from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image
from pymongo.asynchronous.database import AsyncDatabase
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.collections import CANDIDATE_PROFILES, RESUMES, APPLICATIONS
from app.dependencies import candidate_required, get_current_user, get_database
from app.utils import parse_object_id, serialize_document

router = APIRouter(prefix="/resumes", tags=["resumes"])
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def extract_resume_text(file_path: str, extension: str) -> str:
    if extension == ".pdf":
        with pymupdf.open(file_path) as document:
            text = "\n".join(page.get_text() for page in document).strip()
            if text:
                return text
            page_text = []
            for page in document:
                pixmap = page.get_pixmap(colorspace=pymupdf.csRGB, alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                page_text.append(pytesseract.image_to_string(image))
            return "\n".join(page_text).strip()
    with Image.open(file_path) as image:
        return pytesseract.image_to_string(image).strip()


def extract_resume_sections(text: str) -> dict:
    headings = {
        "education": {"education", "academic background", "education and training"},
        "experience": {"experience", "work experience", "professional experience", "employment history"},
        "projects": {"projects", "project experience"},
        "certifications": {"certifications", "certificates", "licenses and certifications"},
    }
    sections = {name: [] for name in headings}
    current_section = None
    for line in text.splitlines():
        cleaned = line.strip()
        heading = cleaned.casefold().rstrip(":")
        matched = next(
            (name for name, titles in headings.items() if heading in titles),
            None,
        )
        if matched:
            current_section = matched
        elif cleaned and current_section and len(cleaned) <= 300:
            sections[current_section].append({"text": cleaned})
            sections[current_section] = sections[current_section][:30]
    return sections


def parse_resume(text: str) -> dict:
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone_match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    known_skills = [
        "Python", "JavaScript", "TypeScript", "React", "FastAPI", "Django",
        "Node.js", "MongoDB", "SQL", "Docker", "AWS", "Git", "HTML", "CSS",
        "Java", "C++", "Machine Learning", "REST API",
    ]
    lowered_text = text.casefold()
    skills = [skill for skill in known_skills if skill.casefold() in lowered_text]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return {
        "full_name": first_line[:100] if first_line and "@" not in first_line else None,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "skills": skills,
        **extract_resume_sections(text),
    }


async def process_resume(database: AsyncDatabase, resume_id: ObjectId, file_path: str, extension: str):
    try:
        text = await run_in_threadpool(extract_resume_text, file_path, extension)
        if not text:
            raise ValueError("No readable text was found in this file.")
        extracted = parse_resume(text)
        await database[RESUMES].update_one(
            {"_id": resume_id},
            {"$set": {
                "status": "completed",
                "raw_text": text[:100000],
                "extracted_data": extracted,
                "processed_at": datetime.now(timezone.utc),
            }},
        )
    except Exception as error:
        await database[RESUMES].update_one(
            {"_id": resume_id},
            {"$set": {"status": "failed", "error": str(error)[:300]}},
        )


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_resume(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload a PDF, JPG, JPEG, or PNG resume.")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    file_path = Path(settings.upload_directory) / f"{user['id']}_{uuid4().hex}{extension}"
    total_bytes = 0
    try:
        with file_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    destination.close()
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"Resume must be {settings.max_upload_size_mb} MB or smaller.")
                destination.write(chunk)
    finally:
        await file.close()
    if total_bytes == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    with file_path.open("rb") as stored_file:
        header = stored_file.read(8)
    valid_signature = (
        (extension == ".pdf" and header.startswith(b"%PDF-"))
        or (extension in {".jpg", ".jpeg"} and header.startswith(bytes([255, 216, 255])))
        or (extension == ".png" and header.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])))
    )
    if not valid_signature:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="The file contents do not match the selected format.")

    now = datetime.now(timezone.utc)
    resume = {
        "candidate_id": ObjectId(user["id"]),
        "original_name": Path(file.filename or "resume").name[:200],
        "storage_name": file_path.name,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": total_bytes,
        "status": "processing",
        "created_at": now,
    }
    result = await database[RESUMES].insert_one(resume)
    resume["_id"] = result.inserted_id
    background_tasks.add_task(process_resume, database, result.inserted_id, str(file_path), extension)
    return serialize_document(resume)


@router.get("")
async def list_resumes(user: dict = Depends(candidate_required), database: AsyncDatabase = Depends(get_database)):
    cursor = database[RESUMES].find(
        {"candidate_id": ObjectId(user["id"])},
        {"raw_text": 0},
    ).sort("created_at", -1)
    return [serialize_document(item) async for item in cursor]


@router.get("/{resume_id}")
async def get_resume(
    resume_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    resume = await database[RESUMES].find_one(
        {"_id": parse_object_id(resume_id, "resume id"), "candidate_id": ObjectId(user["id"])},
        {"raw_text": 0},
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")
    return serialize_document(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    candidate_id = ObjectId(user["id"])
    resume_id_object = parse_object_id(resume_id, "resume id")
    resume = await database[RESUMES].find_one({
        "_id": resume_id_object,
        "candidate_id": candidate_id,
    })
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")

    upload_directory = Path(settings.upload_directory).resolve()
    storage_name = resume.get("storage_name", "")
    file_path = (upload_directory / storage_name).resolve()
    if file_path.parent != upload_directory:
        raise HTTPException(status_code=500, detail="Resume storage path is invalid.")

    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The resume file could not be deleted. Please try again.",
        ) from exc

    await database[RESUMES].delete_one({
        "_id": resume_id_object,
        "candidate_id": candidate_id,
    })


@router.get("/{resume_id}/status")
async def resume_status(
    resume_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    resume = await database[RESUMES].find_one(
        {"_id": parse_object_id(resume_id, "resume id"), "candidate_id": ObjectId(user["id"])},
        {"status": 1, "error": 1},
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")
    return serialize_document(resume)


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(resume_id, "resume id")
    if user["role"] == "candidate":
        resume = await database[RESUMES].find_one({"_id": oid, "candidate_id": ObjectId(user["id"])})
    elif user["role"] == "recruiter":
        application = await database[APPLICATIONS].find_one({
            "resume_id": oid,
            "recruiter_id": ObjectId(user["id"]),
        })
        resume = await database[RESUMES].find_one({"_id": oid}) if application else None
    else:
        resume = await database[RESUMES].find_one({"_id": oid})
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")
    path = Path(settings.upload_directory) / resume["storage_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Resume file is unavailable.")
    return FileResponse(path, filename=resume["original_name"], media_type=resume["content_type"])


@router.put("/{resume_id}/profile-data")
async def save_resume_profile_data(
    resume_id: str,
    data: dict,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(resume_id, "resume id")
    resume = await database[RESUMES].find_one({"_id": oid, "candidate_id": ObjectId(user["id"])})
    if not resume:
        raise HTTPException(status_code=404, detail="Resume was not found.")
    allowed = {"full_name", "email", "phone", "location", "skills", "education", "experience", "projects", "certifications"}
    cleaned = {key: value for key, value in data.items() if key in allowed}
    await database[RESUMES].update_one({"_id": oid}, {"$set": {"extracted_data": cleaned}})
    profile_updates = {key: value for key, value in cleaned.items() if key != "email"}
    if profile_updates:
        await database[CANDIDATE_PROFILES].update_one(
            {"user_id": ObjectId(user["id"])},
            {"$set": profile_updates},
            upsert=True,
        )
    return {"message": "Resume information saved to your profile.", "profile_data": cleaned}




