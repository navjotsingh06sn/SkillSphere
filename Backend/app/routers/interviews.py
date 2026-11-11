from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.asynchronous.database import AsyncDatabase

from app.database.collections import (
    APPLICATIONS,
    INTERVIEWS,
    JOBS,
    NOTIFICATIONS,
)
from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.schemas import (
    InterviewScheduleInput,
    InterviewRescheduleInput,
    InterviewResponseInput,
)
from app.utils import parse_object_id, serialize_document


router = APIRouter(prefix="/interviews", tags=["interviews"])


def validate_future_datetime(value: datetime):
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="Please provide a timezone-aware interview date and time.",
        )

    if value <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail="Interview date and time must be in the future.",
        )


async def notify_user(
    database: AsyncDatabase,
    user_id: ObjectId,
    notification_type: str,
    message: str,
    interview_id: ObjectId,
):
    await database[NOTIFICATIONS].insert_one({
        "user_id": user_id,
        "type": notification_type,
        "message": message,
        "related_id": interview_id,
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
    })


@router.post(
    "/applications/{application_id}",
    status_code=status.HTTP_201_CREATED,
)
async def schedule_interview(
    application_id: str,
    data: InterviewScheduleInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    application_oid = parse_object_id(
        application_id,
        "application id",
    )

    validate_future_datetime(data.scheduled_at)

    application = await database[APPLICATIONS].find_one({
        "_id": application_oid,
        "recruiter_id": ObjectId(user["id"]),
    })

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if application.get("status") not in ("applied", "shortlisted", "under_review", "selected"):
        raise HTTPException(
            status_code=409,
            detail="Only accepted or shortlisted applications can be scheduled for an interview.",
        )

    if application.get("screening_status") not in (
        "shortlisted",
        "pending_review",
    ) and application.get("reconsideration_status") != "requested":
        raise HTTPException(
            status_code=409,
            detail="This application is not eligible for interview scheduling.",
        )

    if data.mode == "offline" and not data.location:
        raise HTTPException(
            status_code=422,
            detail="A location is required for an offline interview.",
        )
    if data.mode == "online" and not data.meeting_link:
        raise HTTPException(
            status_code=422,
            detail="A meeting link is required for an online interview.",
        )
    if data.mode == "offline" and data.meeting_link:
        raise HTTPException(
            status_code=422,
            detail="Use a location instead of a meeting link for an offline interview.",
        )

    active_interview = await database[INTERVIEWS].find_one({
        "application_id": application_oid,
        "status": "scheduled",
    })
    if active_interview:
        raise HTTPException(
            status_code=409,
            detail="This application already has a scheduled interview.",
        )

    now = datetime.now(timezone.utc)

    interview = {
        "application_id": application_oid,
        "candidate_id": application["candidate_id"],
        "recruiter_id": application["recruiter_id"],
        "job_id": application["job_id"],
        "interview_type": data.interview_type,
        "scheduled_at": data.scheduled_at,
        "duration_minutes": data.duration_minutes,
        "mode": data.mode,
        "meeting_link": data.meeting_link,
        "location": data.location,
        "notes": data.notes,
        "status_before_interview": application.get("status", "applied"),
        "status": "scheduled",
        "candidate_response": "pending",
        "created_at": now,
        "updated_at": now,
    }

    result = await database[INTERVIEWS].insert_one(interview)
    interview["_id"] = result.inserted_id

    await database[APPLICATIONS].update_one(
        {"_id": application_oid},
        {
            "$set": {
                "status": "interview",
                "updated_at": now,
            }
        },
    )

    job = await database[JOBS].find_one(
        {"_id": application["job_id"]},
        {"title": 1},
    )

    job_title = job.get("title", "the job") if job else "the job"

    await notify_user(
        database,
        application["candidate_id"],
        "interview_scheduled",
        (
            f"Your {data.interview_type} interview for {job_title} "
            f"has been scheduled for {data.scheduled_at.isoformat()}."
        ),
        result.inserted_id,
    )

    return serialize_document(interview)


@router.get("")
async def list_interviews(
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
        }
    else:
        query = {}

    cursor = (
        database[INTERVIEWS]
        .find(query)
        .sort("scheduled_at", 1)
    )

    interviews = []

    async for interview in cursor:
        job = await database[JOBS].find_one(
            {"_id": interview["job_id"]},
            {"title": 1},
        )

        item = serialize_document(interview)
        item["job"] = serialize_document(job)

        interviews.append(item)

    return interviews


@router.get("/{interview_id}")
async def get_interview(
    interview_id: str,
    user: dict = Depends(get_current_user),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(interview_id, "interview id")

    interview = await database[INTERVIEWS].find_one({
        "_id": oid,
    })

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )

    if user["role"] == "candidate":
        allowed = interview["candidate_id"] == ObjectId(user["id"])
    elif user["role"] == "recruiter":
        allowed = interview["recruiter_id"] == ObjectId(user["id"])
    else:
        allowed = True

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail="Interview was not found.",
        )

    return serialize_document(interview)


@router.put("/{interview_id}/response")
async def respond_to_interview(
    interview_id: str,
    data: InterviewResponseInput,
    user: dict = Depends(candidate_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(interview_id, "interview id")
    now = datetime.now(timezone.utc)

    interview = await database[INTERVIEWS].find_one({
        "_id": oid,
        "candidate_id": ObjectId(user["id"]),
        "status": "scheduled",
    })

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    await database[INTERVIEWS].update_one(
        {"_id": oid},
        {
            "$set": {
                "candidate_response": data.response,
                "candidate_responded_at": now,
                "updated_at": now,
            }
        },
    )

    await notify_user(
        database,
        interview["recruiter_id"],
        "interview_response",
        f"The candidate has {data.response} the interview invitation.",
        oid,
    )

    return {
        "message": f"Interview invitation {data.response}.",
        "candidate_response": data.response,
    }


@router.put("/{interview_id}/reschedule")
async def reschedule_interview(
    interview_id: str,
    data: InterviewRescheduleInput,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(interview_id, "interview id")
    validate_future_datetime(data.scheduled_at)

    interview = await database[INTERVIEWS].find_one({
        "_id": oid,
        "recruiter_id": ObjectId(user["id"]),
        "status": "scheduled",
    })

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    now = datetime.now(timezone.utc)
    mode = data.mode or interview.get("mode", "online")
    meeting_link = data.meeting_link if data.meeting_link is not None else interview.get("meeting_link")
    location = data.location if data.location is not None else interview.get("location")
    if mode == "online" and not meeting_link:
        raise HTTPException(status_code=422, detail="A meeting link is required for an online interview.")
    if mode == "offline" and not location:
        raise HTTPException(status_code=422, detail="A location is required for an offline interview.")
    updates = {
        "scheduled_at": data.scheduled_at,
        "duration_minutes": data.duration_minutes,
        "mode": mode,
        "meeting_link": meeting_link if mode == "online" else None,
        "location": location if mode == "offline" else None,
        "candidate_response": "pending",
        "updated_at": now,
    }
    if data.notes is not None:
        updates["notes"] = data.notes

    await database[INTERVIEWS].update_one(
        {"_id": oid},
        {"$set": updates},
    )

    await notify_user(
        database,
        interview["candidate_id"],
        "interview_rescheduled",
        (
            "Your interview has been rescheduled to "
            f"{data.scheduled_at.isoformat()}."
        ),
        oid,
    )

    return {
        "message": "Interview rescheduled successfully.",
        "scheduled_at": data.scheduled_at,
    }


@router.put("/{interview_id}/cancel")
async def cancel_interview(
    interview_id: str,
    user: dict = Depends(recruiter_required),
    database: AsyncDatabase = Depends(get_database),
):
    oid = parse_object_id(interview_id, "interview id")
    now = datetime.now(timezone.utc)

    interview = await database[INTERVIEWS].find_one({
        "_id": oid,
        "recruiter_id": ObjectId(user["id"]),
        "status": "scheduled",
    })

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Scheduled interview was not found.",
        )

    await database[INTERVIEWS].update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "cancelled",
                "updated_at": now,
            }
        },
    )

    await database[APPLICATIONS].update_one(
        {"_id": interview["application_id"], "status": "interview"},
        {"$set": {
            "status": interview.get("status_before_interview", "shortlisted"),
            "updated_at": now,
        }},
    )

    await notify_user(
        database,
        interview["candidate_id"],
        "interview_cancelled",
        "Your interview has been cancelled by the recruiter.",
        oid,
    )

    return {"message": "Interview cancelled successfully."}