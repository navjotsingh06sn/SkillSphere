from datetime import datetime, timezone
import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    APPLICATIONS,
    CANDIDATE_PROFILES,
    JOBS,
    RESUMES,
    RESUME_ANALYSES,
    NOTIFICATIONS,
    USERS,
)
from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.schemas import (
    ApplicationStatusInput,
    ReconsiderationInput,
)
from app.utils import parse_object_id, serialize_document


router = APIRouter(tags=["applications"])

SCREENING_THRESHOLD = 75
WITHDRAWABLE_APPLICATION_STATUSES = (
    "applied",
    "under_review",
    "shortlisted",
    "interview",
)

ALIASES = {
    "js": "javascript",
    "react": "react.js",
    "py": "python",
    "mongo": "mongodb",
    "rest": "restapi",
}


def normalize(skill: str) -> str:
    value = re.sub(r"[^a-z0-9.+#]", "", skill.lower().strip())
    return ALIASES.get(value, value)


def calculate_match(candidate_skills, required_skills):
    candidate = {
        normalize(skill): skill
        for skill in candidate_skills
        if isinstance(skill, str) and normalize(skill)
    }

    required = {
        normalize(skill): skill
        for skill in required_skills
        if isinstance(skill, str) and normalize(skill)
    }

    if not required or not candidate:
        return None, [], [], candidate

    matched_keys = set(required) & set(candidate)
    missing_keys = set(required) - matched_keys

    score = round(100 * len(matched_keys) / len(required), 2)

    matched = [required[key] for key in sorted(matched_keys)]
    missing = [required[key] for key in sorted(missing_keys)]

    return score, matched, missing, candidate


@router.post(
    "/jobs/{job_id}/apply",
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    job_oid = parse_object_id(job_id, "job id")

    job = await database[JOBS].find_one({
        "_id": job_oid,
        "status": "published",
    })

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Published job was not found.",
        )

    if job.get("is_demo"):
        raise HTTPException(
            status_code=409,
            detail="Demo jobs are for browsing only.",
        )

    candidate_id = ObjectId(user["id"])

    existing_application = await database[APPLICATIONS].find_one({
        "candidate_id": candidate_id,
        "job_id": job_oid,
    })

    if existing_application:
        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job.",
        )

    # Use the latest successfully processed resume.
    resume = await database[RESUMES].find_one(
        {
            "candidate_id": candidate_id,
            "status": "completed",
        },
        sort=[("created_at", -1)],
    )

    if not resume:
        raise HTTPException(
            status_code=409,
            detail="Upload and process a resume before applying.",
        )

    candidate_skills = set()

    extracted_data = resume.get("extracted_data") or {}

    for skill in extracted_data.get("skills", []):
        if isinstance(skill, str):
            candidate_skills.add(skill)

    match_score, matched, missing, candidate = calculate_match(
        candidate_skills,
        job.get("required_skills", []),
    )

    if match_score is None:
        screening_status = "pending_review"
        application_status = "under_review"
        rejection_reason = None
        notification_type = "application_applied"
        notification_message = (
            f"Your application for {job['title']} has been submitted successfully. "
            "A recruiter will review it because an automatic screening score "
            "could not be calculated."
        )

    elif len(matched) / (len(matched) + len(missing)) >= SCREENING_THRESHOLD / 100:
        screening_status = "shortlisted"
        application_status = "under_review"
        rejection_reason = None
        notification_type = "application_applied"
        notification_message = (
            f"Your application for {job['title']} has been submitted successfully. "
            "You meet the required screening criteria."
        )

    else:
        screening_status = "not_shortlisted"
        application_status = "rejected"

        rejection_reason = (
            f"Your resume matched {match_score:g}% of the required skills, "
            f"below the {SCREENING_THRESHOLD}% screening threshold."
        )
        notification_type = "application_rejected"
        notification_message = (
            f"Your application for {job['title']} has been rejected because "
            "your resume did not meet the required screening criteria. "
            "Click to view the reason."
        )

    now = datetime.now(timezone.utc)

    required_keys = {
        normalize(skill)
        for skill in job.get("required_skills", [])
        if isinstance(skill, str) and normalize(skill)
    }

    analysis = {
        "candidate_id": candidate_id,
        "job_id": job_oid,
        "resume_id": resume["_id"],
        "match_percentage": match_score,
        "screening_threshold": SCREENING_THRESHOLD,
        "screening_recommendation": screening_status,
        "matched_skills": matched,
        "missing_skills": missing,
        "additional_skills": [
            candidate[key]
            for key in sorted(set(candidate) - required_keys)
        ],
        "recommendations": [
            f"Build experience with {skill}."
            for skill in missing
        ],
        "explanation": (
            f"Your resume matches {match_score}% of this job's required skills."
            if match_score is not None
            else (
                "No required skills were defined. Manual review is required."
                if not job.get("required_skills")
                else "No usable resume skills were extracted. Manual review is required."
            )
        ),
        "created_at": now,
    }

    analysis_result = await database[RESUME_ANALYSES].insert_one(analysis)

    application = {
        "candidate_id": candidate_id,
        "job_id": job_oid,
        "recruiter_id": job["recruiter_id"],
        "resume_id": resume["_id"],
        "analysis_id": analysis_result.inserted_id,
        "match_score": match_score,
        "required_score": SCREENING_THRESHOLD,
        "matched_skills": matched,
        "missing_skills": missing,
        "screening_threshold": SCREENING_THRESHOLD,
        "screening_status": screening_status,
        "screening_reasons": {
            "matched_skills": matched,
            "missing_skills": missing,
        },
        "reconsideration_status": "not_requested",
        "status": application_status,
        "rejection_reason": rejection_reason,
        "applied_at": now,
        "updated_at": now,
    }

    try:
        result = await database[APPLICATIONS].insert_one(application)
    except DuplicateKeyError:
        await database[RESUME_ANALYSES].delete_one({
            "_id": analysis_result.inserted_id,
        })

        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job.",
        )

    application["_id"] = result.inserted_id

    await database[NOTIFICATIONS].insert_one({
        "user_id": candidate_id,
        "type": notification_type,
        "message": notification_message,
        "related_id": result.inserted_id,
        "job_id": job_oid,
        "match_score": match_score,
        "screening_status": screening_status,
        "missing_skills": missing,
        "is_read": False,
        "created_at": now,
    })

    return serialize_document(application)


@router.get("/applications")
async def list_applications(
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    if user["role"] == "candidate":
        query = {
            "candidate_id": ObjectId(user["id"]),
        }

    elif user["role"] == "recruiter":
        query = {
            "recruiter_id": ObjectId(user["id"]),
            "$or": [
                {
                    "screening_status": {
                        "$in": ["shortlisted", "pending_review"],
                    },
                },
                {
                    "reconsideration_status": "requested",
                },
            ],
        }

    else:
        query = {}

    cursor = (
        database[APPLICATIONS]
        .find(query)
        .sort("applied_at", -1)
    )

    applications = []

    async for application in cursor:
        job = await database[JOBS].find_one(
            {"_id": application["job_id"]},
            {"title": 1, "company_name": 1},
        )

        item = serialize_document(application)
        item["job"] = serialize_document(job)

        applications.append(item)

    return applications


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")

    application = await database[APPLICATIONS].find_one({
        "_id": oid,
    })

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if (
        user["role"] == "candidate"
        and application["candidate_id"] != ObjectId(user["id"])
    ):
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    result = serialize_document(application)

    if user["role"] == "candidate":
        job = await database[JOBS].find_one({"_id": application["job_id"]})
        analysis = await database[RESUME_ANALYSES].find_one({
            "_id": application["analysis_id"],
            "candidate_id": application["candidate_id"],
        }) if application.get("analysis_id") else None
        result["job"] = serialize_document(job)
        result["analysis"] = serialize_document(analysis)

    if user["role"] == "recruiter":
        if application["recruiter_id"] != ObjectId(user["id"]):
            raise HTTPException(
                status_code=404,
                detail="Application was not found.",
            )

        candidate_id = application["candidate_id"]
        profile = await database[CANDIDATE_PROFILES].find_one({
            "user_id": candidate_id,
        }) or {}
        account = await database[USERS].find_one(
            {"_id": candidate_id},
            {"full_name": 1, "email": 1},
        ) or {}
        job = await database[JOBS].find_one({
            "_id": application["job_id"],
            "recruiter_id": ObjectId(user["id"]),
        })
        resume = await database[RESUMES].find_one({
            "_id": application["resume_id"],
            "candidate_id": candidate_id,
        }) if application.get("resume_id") else None
        analysis = await database[RESUME_ANALYSES].find_one({
            "_id": application["analysis_id"],
            "candidate_id": candidate_id,
        }) if application.get("analysis_id") else None

        result["candidate"] = {
            "id": str(candidate_id),
            "full_name": profile.get("full_name") or account.get("full_name", ""),
            "email": account.get("email", ""),
            "phone": profile.get("phone") or (resume or {}).get("extracted_data", {}).get("phone"),
            "education": profile.get("education") or (resume or {}).get("extracted_data", {}).get("education", []),
            "experience": profile.get("experience") or (resume or {}).get("extracted_data", {}).get("experience", []),
            "skills": profile.get("skills") or (resume or {}).get("extracted_data", {}).get("skills", []),
        }
        result["job"] = serialize_document(job)
        result["resume"] = (
            {
                "id": str(resume["_id"]),
                "original_name": resume.get("original_name", "Resume"),
                "status": resume.get("status"),
                "extracted_data": resume.get("extracted_data", {}),
            }
            if resume else None
        )
        result["analysis"] = serialize_document(analysis)

    return result


@router.put("/applications/{application_id}/withdraw")
async def withdraw_application(
    application_id: str,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")

    result = await database[APPLICATIONS].update_one(
        {
            "_id": oid,
            "candidate_id": ObjectId(user["id"]),
            "status": {"$in": WITHDRAWABLE_APPLICATION_STATUSES},
        },
        {
            "$set": {
                "status": "withdrawn",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This application cannot be withdrawn.",
        )

    application = await database[APPLICATIONS].find_one({"_id": oid})

    await database[NOTIFICATIONS].insert_one({
        "user_id": application["recruiter_id"],
        "type": "application_withdrawn",
        "message": "A candidate withdrew an application.",
        "related_id": oid,
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
    })

    return {"status": "withdrawn"}


@router.put("/applications/{application_id}/status")
async def update_application_status(
    application_id: str,
    data: ApplicationStatusInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")

    if data.status == "rejected" and not data.rejection_reason:
        raise HTTPException(
            status_code=422,
            detail="A rejection reason is required.",
        )

    application = await database[APPLICATIONS].find_one({
        "_id": oid,
        "recruiter_id": ObjectId(user["id"]),
    })

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    eligible = application.get("screening_status") in (
        "shortlisted",
        "pending_review",
    )

    reconsideration_requested = (
        application.get("reconsideration_status") == "requested"
    )

    if not eligible and not reconsideration_requested:
        raise HTTPException(
            status_code=409,
            detail="This application is not available for recruiter review.",
        )

    now = datetime.now(timezone.utc)

    update_fields = {
        "status": data.status,
        "updated_at": now,
        "rejection_reason": (
            data.rejection_reason if data.status == "rejected" else None
        ),
    }

    if data.status == "shortlisted":
        update_fields["recruiter_decision"] = "accepted"
    elif data.status == "rejected":
        update_fields["recruiter_decision"] = "rejected"

    await database[APPLICATIONS].update_one(
        {"_id": oid, "recruiter_id": ObjectId(user["id"])},
        {"$set": update_fields},
    )

    message = (
        f"Your application has been {data.status.replace('_', ' ')}."
    )

    if data.status == "rejected":
        message += f" Reason: {data.rejection_reason}"

    await database[NOTIFICATIONS].insert_one({
        "user_id": application["candidate_id"],
        "type": "application_status",
        "message": message,
        "related_id": oid,
        "job_id": application["job_id"],
        "is_read": False,
        "created_at": now,
    })

    return {
        "status": data.status,
        "rejection_reason": data.rejection_reason,
    }


@router.post("/applications/{application_id}/reconsider")
async def request_reconsideration(
    application_id: str,
    data: ReconsiderationInput,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(application_id, "application id")
    candidate_id = ObjectId(user["id"])

    application = await database[APPLICATIONS].find_one({
        "_id": oid,
        "candidate_id": candidate_id,
        "screening_status": "not_shortlisted",
        "status": "rejected",
    })

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Eligible application for reconsideration was not found.",
        )

    if application.get("reconsideration_status") == "requested":
        raise HTTPException(
            status_code=409,
            detail="You have already requested a manual review.",
        )

    now = datetime.now(timezone.utc)

    await database[APPLICATIONS].update_one(
        {"_id": oid},
        {
            "$set": {
                "reconsideration_status": "requested",
                "reconsideration_reason": data.reason,
                "reconsideration_requested_at": now,
                "updated_at": now,
            }
        },
    )

    await database[NOTIFICATIONS].insert_one({
        "user_id": application["recruiter_id"],
        "type": "reconsideration_requested",
        "message": (
            "A candidate has requested a manual review of an AI screening result."
        ),
        "related_id": oid,
        "job_id": application["job_id"],
        "is_read": False,
        "created_at": now,
    })

    await database[NOTIFICATIONS].insert_one({
        "user_id": candidate_id,
        "type": "reconsideration_submitted",
        "message": "Your manual review request has been sent to the recruiter.",
        "related_id": oid,
        "job_id": application["job_id"],
        "is_read": False,
        "created_at": now,
    })

    return {"message": "Manual review request submitted successfully."}