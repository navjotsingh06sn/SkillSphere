
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.models import (
    Assessment,
    CandidateProfile,
    Job,
    Notification,
    User,
)
from app.pg_utils import parse_uuid, serialize_model
from app.schemas import AssessmentAnswersInput, SecondRoundDecisionInput
from app.services.assessments import (
    ASSESSMENT_DURATION_MINUTES,
    complete_if_expired,
    deadline_after,
    get_assessment_for_user,
    publish_assessment_result,
    serialize_assessment,
    serialize_pg_assessment,
)

router = APIRouter(prefix="/assessments", tags=["assessments"])


def validate_answers(assessment: dict, answers: dict[str, int]) -> None:
    allowed_ids = {
        question["question_id"]: len(question["options"])
        for question in assessment.get("questions", [])
    }

    for question_id, selected_index in answers.items():
        if question_id not in allowed_ids:
            raise HTTPException(
                status_code=422,
                detail="An answer references a question that is not in this assessment.",
            )

        if not isinstance(selected_index, int) or isinstance(selected_index, bool):
            raise HTTPException(
                status_code=422,
                detail="An answer option must be an integer index.",
            )

        if not 0 <= selected_index < allowed_ids[question_id]:
            raise HTTPException(
                status_code=422,
                detail="An answer option is outside the available choices.",
            )


async def require_assessment(
    assessment_id: str,
    user: dict,
    db: AsyncSession,
) -> dict:
    assessment_uuid = parse_uuid(assessment_id, "assessment id")

    assessment = await get_assessment_for_user(
        db,
        assessment_uuid,
        user,
    )

    if not assessment:
        raise HTTPException(
            status_code=404,
            detail="Assessment was not found.",
        )

    return assessment


@router.get("")
async def list_assessments(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")

    conditions = []

    if user["role"] == "candidate":
        conditions.append(Assessment.candidate_id == user_uuid)

    elif user["role"] == "recruiter":
        conditions.append(Assessment.recruiter_id == user_uuid)

    stmt = (
        select(Assessment, Job)
        .outerjoin(Job, Assessment.job_id == Job.id)
        .where(*conditions)
        .order_by(Assessment.created_at.desc())
    )

    rows = (await db.execute(stmt)).all()

    results = []

    for assessment_model, job in rows:
        item = serialize_assessment(
            serialize_pg_assessment(assessment_model)
        )

        item["job"] = serialize_model(job)

        if user["role"] == "recruiter":
            candidate = await db.scalar(
                select(User).where(
                    User.id == assessment_model.candidate_id
                )
            )

            profile = await db.scalar(
                select(CandidateProfile).where(
                    CandidateProfile.user_id == assessment_model.candidate_id
                )
            )

            item["candidate"] = {
                "full_name": (
                    (profile.headline if profile else "")
                    or (candidate.full_name if candidate else "")
                ),
                "email": candidate.email if candidate else "",
            }

        results.append(item)

    return results


@router.get("/{assessment_id}")
async def get_assessment(
    assessment_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    assessment = await require_assessment(
        assessment_id,
        user,
        db,
    )

    if user["role"] == "candidate":
        assessment = await complete_if_expired(db, assessment)

    result = serialize_assessment(
        assessment,
        include_questions=(
            user["role"] == "candidate"
            and assessment.get("status") == "in_progress"
        ),
    )

    job_uuid = parse_uuid(assessment["job_id"], "job id")

    job = await db.scalar(
        select(Job).where(Job.id == job_uuid)
    )

    result["job"] = serialize_model(job)

    if user["role"] == "recruiter":
        candidate_uuid = parse_uuid(
            assessment["candidate_id"],
            "candidate id",
        )

        candidate = await db.scalar(
            select(User).where(User.id == candidate_uuid)
        )

        profile = await db.scalar(
            select(CandidateProfile).where(
                CandidateProfile.user_id == candidate_uuid
            )
        )

        result["candidate"] = {
            "full_name": (
                (profile.headline if profile else "")
                or (candidate.full_name if candidate else "")
            ),
            "email": candidate.email if candidate else "",
        }

    return result


@router.post("/{assessment_id}/start")
async def start_assessment(
    assessment_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    assessment = await require_assessment(
        assessment_id,
        user,
        db,
    )

    if assessment.get("status") == "question_shortage":
        raise HTTPException(
            status_code=409,
            detail="This role does not have enough relevant questions for an assessment.",
        )

    if assessment.get("status") == "assigned":
        now = datetime.now(timezone.utc)

        assessment_uuid = parse_uuid(
            assessment["id"],
            "assessment id",
        )

        candidate_uuid = parse_uuid(
            user["id"],
            "candidate id",
        )

        model = await db.scalar(
            select(Assessment).where(
                Assessment.id == assessment_uuid,
                Assessment.candidate_id == candidate_uuid,
                Assessment.status == "assigned",
            )
        )

        if model:
            model.status = "in_progress"
            model.started_at = now

            deadline = deadline_after(
                ASSESSMENT_DURATION_MINUTES,
                now,
            )

            model.expires_at = deadline

            extra = dict(model.extra_data or {})
            extra["attempt_count"] = 1
            extra["deadline_at"] = deadline.isoformat()
            extra["started_at"] = now.isoformat()

            model.extra_data = extra
            model.updated_at = now

            await db.commit()
            await db.refresh(model)

            assessment = serialize_pg_assessment(model)

    assessment = await complete_if_expired(
        db,
        assessment,
    )

    if assessment.get("status") not in {
        "in_progress",
        "submitted",
    }:
        raise HTTPException(
            status_code=409,
            detail="This assessment can no longer be started.",
        )

    return serialize_assessment(
        assessment,
        include_questions=(
            assessment.get("status") == "in_progress"
        ),
    )


@router.put("/{assessment_id}/answers")
async def save_assessment_answers(
    assessment_id: str,
    data: AssessmentAnswersInput,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    assessment = await require_assessment(
        assessment_id,
        user,
        db,
    )

    assessment = await complete_if_expired(
        db,
        assessment,
    )

    if assessment.get("status") != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="Answers can only be saved while the assessment is in progress.",
        )

    validate_answers(assessment, data.answers)

    now = datetime.now(timezone.utc)

    assessment_uuid = parse_uuid(
        assessment["id"],
        "assessment id",
    )

    candidate_uuid = parse_uuid(
        user["id"],
        "candidate id",
    )

    model = await db.scalar(
        select(Assessment).where(
            Assessment.id == assessment_uuid,
            Assessment.candidate_id == candidate_uuid,
            Assessment.status == "in_progress",
            Assessment.expires_at > now,
        )
    )

    if not model:
        raise HTTPException(
            status_code=409,
            detail="The assessment deadline has passed.",
        )

    extra = dict(model.extra_data or {})
    extra["answers"] = data.answers

    model.extra_data = extra
    model.updated_at = now

    await db.commit()

    return {
        "saved": True,
        "answered_count": len(data.answers),
    }


@router.post("/{assessment_id}/submit")
async def submit_assessment(
    assessment_id: str,
    data: AssessmentAnswersInput,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    assessment = await require_assessment(
        assessment_id,
        user,
        db,
    )

    assessment = await complete_if_expired(
        db,
        assessment,
    )

    if assessment.get("status") != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="This assessment has already been submitted or is not in progress.",
        )

    now = datetime.now(timezone.utc)

    deadline = (
        assessment.get("deadline_at")
        or assessment.get("expires_at")
        or now
    )

    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline)
        except ValueError:
            deadline = now

    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    expired = now >= deadline

    if expired:
        answers = assessment.get("answers", {})
    else:
        validate_answers(assessment, data.answers)

        answers = {
            **assessment.get("answers", {}),
            **data.answers,
        }

    result = await publish_assessment_result(
        db,
        assessment,
        answers,
    )

    if result.get("status") != "submitted":
        raise HTTPException(
            status_code=409,
            detail="This assessment has already been submitted.",
        )

    return serialize_assessment(result)


@router.put("/{assessment_id}/second-round")
async def decide_second_round(
    assessment_id: str,
    data: SecondRoundDecisionInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    assessment = await require_assessment(
        assessment_id,
        user,
        db,
    )

    if assessment.get("status") != "submitted":
        raise HTTPException(
            status_code=409,
            detail="The assessment must be submitted before making a second-round decision.",
        )

    if not assessment.get("second_round_eligible"):
        raise HTTPException(
            status_code=409,
            detail="This candidate did not meet the second-round eligibility threshold.",
        )

    now = datetime.now(timezone.utc)

    previous_decision = assessment.get(
        "second_round_decision",
        "pending",
    )

    if previous_decision != data.decision:
        assessment_uuid = parse_uuid(
            assessment["id"],
            "assessment id",
        )

        recruiter_uuid = parse_uuid(
            user["id"],
            "recruiter id",
        )

        model = await db.scalar(
            select(Assessment).where(
                Assessment.id == assessment_uuid,
                Assessment.recruiter_id == recruiter_uuid,
                Assessment.status == "submitted",
            )
        )

        if not model:
            raise HTTPException(
                status_code=404,
                detail="Assessment was not found.",
            )

        extra = dict(model.extra_data or {})

        extra["second_round_decision"] = data.decision
        extra["second_round_decided_at"] = now.isoformat()

        model.extra_data = extra
        model.updated_at = now

        notification_message = (
            "The recruiter has invited you to the next round."
            if data.decision == "invited"
            else "The recruiter has decided not to invite you to the next round at this time."
        )

        notification = Notification(
            user_id=model.candidate_id,
            type="assessment_second_round_decision",
            message=notification_message,
            related_id=model.id,
            job_id=model.job_id,
            is_read=False,
            created_at=now,
        )

        db.add(notification)

        await db.commit()
        await db.refresh(model)

        assessment = serialize_pg_assessment(model)

    return {
        "second_round_decision": assessment.get(
            "second_round_decision",
            "pending",
        ),
        "second_round_eligible": assessment.get(
            "second_round_eligible",
            False,
        ),
    }
