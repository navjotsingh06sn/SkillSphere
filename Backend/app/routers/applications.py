
import html
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.models import (
    Application,
    Assessment,
    CandidateProfile,
    Job,
    Notification,
    Resume,
    ResumeAnalysis,
    User,
)
from app.pg_utils import parse_uuid, serialize_model
from app.config import settings
from app.schemas import (
    ApplicationStatusInput,
    ReconsiderationInput,
)
from app.services.smtp import EmailDeliveryError, send_smtp_email

logger = logging.getLogger(__name__)

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


def hide_shortlist_email_state(application: dict) -> dict:
    for field in (
        "shortlist_email_status",
        "shortlist_email_message_id",
        "shortlist_email_error",
        "shortlist_email_sent_at",
        "shortlist_email_attempts",
    ):
        application.pop(field, None)
    return application


async def deliver_shortlist_email(
    db: AsyncSession,
    application_id: UUID,
) -> Application:
    application = await db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
    )
    if not application:
        raise RuntimeError("Application disappeared before shortlist email delivery.")
    if application.status != "shortlisted":
        return application
    if application.shortlist_email_status in {"sent", "sending"}:
        return application

    application.shortlist_email_status = "sending"
    application.shortlist_email_attempts += 1
    application.shortlist_email_message_id = None
    application.shortlist_email_error = None
    application.shortlist_email_sent_at = None
    await db.commit()
    await db.refresh(application)

    candidate = await db.scalar(
        select(User).where(User.id == application.candidate_id)
    )
    job = await db.scalar(select(Job).where(Job.id == application.job_id))
    assessment = await db.scalar(
        select(Assessment).where(
            Assessment.application_id == application.id,
            Assessment.candidate_id == application.candidate_id,
        )
    )
    if not candidate or not candidate.email:
        delivery_error = EmailDeliveryError(
            "The candidate does not have a deliverable email address."
        )
    else:
        job_title = job.title if job else "the role"
        assessment_text = ""
        assessment_html = ""
        if assessment:
            assessment_url = (
                f"{settings.frontend_url.rstrip('/')}/candidate/assessments/"
                f"{assessment.id}"
            )
            details = (
                f"Round 1 assessment: {assessment.title}\n"
                f"Questions: {assessment.total_questions}\n"
                f"Time limit: {assessment.duration_minutes} minutes\n"
                f"Open your assessment: {assessment_url}"
            )
            assessment_text = f"\n\n{details}"
            assessment_html = (
                "<p><strong>Round 1 assessment</strong><br>"
                f"{html.escape(assessment.title)} · "
                f"{assessment.total_questions} questions · "
                f"{assessment.duration_minutes} minutes<br>"
                f'<a href="{html.escape(assessment_url, quote=True)}">'
                "Open your assessment</a></p>"
            )
        greeting = candidate.full_name or "there"
        subject = f"You've been shortlisted for {job_title}"
        text_content = (
            f"Hello {greeting},\n\n"
            f"Congratulations — your application for {job_title} has been "
            f"shortlisted. The recruiter will share next steps in SkillSphere."
            f"{assessment_text}\n\n"
            "Regards,\nSkillSphere"
        )
        html_content = (
            f"<p>Hello {html.escape(greeting)},</p>"
            "<p>Congratulations — your application for "
            f"<strong>{html.escape(job_title)}</strong> has been shortlisted. "
            "The recruiter will share next steps in SkillSphere.</p>"
            f"{assessment_html}"
            "<p>Regards,<br>SkillSphere</p>"
        )
        try:
            message_id = await send_smtp_email(
                candidate.email,
                subject,
                text_content,
                html_content,
            )
        except EmailDeliveryError as exc:
            delivery_error = exc
        else:
            application.shortlist_email_status = "sent"
            application.shortlist_email_message_id = message_id
            application.shortlist_email_sent_at = datetime.now(timezone.utc)
            application.shortlist_email_error = None
            await db.commit()
            await db.refresh(application)
            return application

    application.shortlist_email_status = "failed"
    application.shortlist_email_error = str(delivery_error)[:2000]
    logger.warning(
        "Shortlist email delivery failed for application %s: %s",
        application.id,
        delivery_error,
    )
    await db.commit()
    await db.refresh(application)
    return application


def normalize(skill: str) -> str:
    value = re.sub(
        r"[^a-z0-9.+#]",
        "",
        skill.lower().strip(),
    )
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
    missing_keys = set(required) - set(candidate)

    score = round(
        100 * len(matched_keys) / len(required),
        2,
    )

    matched = [
        required[key]
        for key in sorted(matched_keys)
    ]

    missing = [
        required[key]
        for key in sorted(missing_keys)
    ]

    return score, matched, missing, candidate


@router.post(
    "/jobs/{job_id}/apply",
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_job(
    job_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    job_uuid = parse_uuid(job_id, "job id")
    candidate_id = parse_uuid(user["id"], "candidate id")

    job_res = await db.execute(
        select(Job).where(
            Job.id == job_uuid,
            Job.status == "published",
        )
    )
    job = job_res.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Published job was not found.",
        )

    if job.is_demo:
        raise HTTPException(
            status_code=409,
            detail="Demo jobs are for browsing only.",
        )

    existing_res = await db.execute(
        select(Application).where(
            Application.candidate_id == candidate_id,
            Application.job_id == job_uuid,
        )
    )

    if existing_res.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job.",
        )

    resume_res = await db.execute(
        select(Resume)
        .where(
            Resume.candidate_id == candidate_id,
            Resume.status == "completed",
        )
        .order_by(Resume.created_at.desc())
        .limit(1)
    )

    resume = resume_res.scalar_one_or_none()

    if not resume:
        raise HTTPException(
            status_code=409,
            detail="Upload and process a resume before applying.",
        )

    candidate_skills = set()
    extracted_data = resume.extracted_data or {}

    for skill in extracted_data.get("skills", []):
        if isinstance(skill, str):
            candidate_skills.add(skill)

    match_score, matched, missing, candidate = calculate_match(
        candidate_skills,
        job.required_skills or [],
    )

    if match_score is None:
        screening_status = "pending_review"
        application_status = "under_review"
        rejection_reason = None
        notification_type = "application_applied"

        notification_message = (
            f"Your application for {job.title} has been submitted successfully. "
            "A recruiter will review it because an automatic screening score "
            "could not be calculated."
        )

    elif match_score >= SCREENING_THRESHOLD:
        screening_status = "shortlisted"
        application_status = "under_review"
        rejection_reason = None
        notification_type = "application_applied"

        notification_message = (
            f"Your application for {job.title} has been submitted successfully. "
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
            f"Your application for {job.title} has been rejected because "
            "your resume did not meet the required screening criteria. "
            "Click to view the reason."
        )

    now = datetime.now(timezone.utc)

    required_keys = {
        normalize(skill)
        for skill in (job.required_skills or [])
        if isinstance(skill, str) and normalize(skill)
    }

    additional_skills = [
        candidate[key]
        for key in sorted(set(candidate) - required_keys)
    ]

    recommendations = [
        f"Build experience with {skill}."
        for skill in missing
    ]

    explanation = (
        f"Your resume matches {match_score}% of this job's required skills."
        if match_score is not None
        else (
            "No required skills were defined. Manual review is required."
            if not job.required_skills
            else (
                "No usable resume skills were extracted. "
                "Manual review is required."
            )
        )
    )

    analysis = ResumeAnalysis(
        candidate_id=candidate_id,
        job_id=job_uuid,
        resume_id=resume.id,
        match_percentage=(
            float(match_score)
            if match_score is not None
            else None
        ),
        matched_skills=matched,
        missing_skills=missing,
        additional_skills=additional_skills,
        recommendations=recommendations,
        explanation=explanation,
    )

    db.add(analysis)

    try:
        await db.flush()

        application = Application(
            candidate_id=candidate_id,
            job_id=job_uuid,
            recruiter_id=job.recruiter_id,
            resume_id=resume.id,
            analysis_id=analysis.id,
            match_score=match_score,
            screening_threshold=SCREENING_THRESHOLD,
            screening_status=screening_status,
            screening_reasons={
                "matched_skills": matched,
                "missing_skills": missing,
            },
            reconsideration_status="not_requested",
            status=application_status,
            rejection_reason=rejection_reason,
            applied_at=now,
            updated_at=now,
        )

        db.add(application)
        await db.flush()

        notification = Notification(
            user_id=candidate_id,
            type=notification_type,
            message=notification_message,
            related_id=application.id,
            job_id=job_uuid,
            match_score=match_score,
            screening_status=screening_status,
            missing_skills=missing,
            is_read=False,
            created_at=now,
        )

        db.add(notification)

        recruiter_notification = Notification(
            user_id=job.recruiter_id,
            type="new_application",
            message=f"{user.get('full_name') or 'A candidate'} applied for {job.title}.",
            related_id=application.id,
            job_id=job_uuid,
            is_read=False,
            created_at=now,
        )
        db.add(recruiter_notification)

        await db.commit()
        await db.refresh(application)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job.",
        )

    return hide_shortlist_email_state(serialize_model(application))


@router.get("/applications")
async def list_applications(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    user_uuid = parse_uuid(user["id"], "user id")

    conditions = []

    if user["role"] == "candidate":
        conditions.append(
            Application.candidate_id == user_uuid
        )

    elif user["role"] == "recruiter":
        conditions.extend([
            Application.recruiter_id == user_uuid,
            or_(
                Application.screening_status.in_(
                    ["shortlisted", "pending_review"]
                ),
                Application.reconsideration_status == "requested",
                Application.status == "rejected",
            ),
        ])

    else:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    stmt = (
        select(Application, Job)
        .outerjoin(Job, Application.job_id == Job.id)
        .where(*conditions)
        .order_by(Application.applied_at.desc())
    )

    rows = (await db.execute(stmt)).all()

    applications = []

    for application, job in rows:
        item = serialize_model(application)
        if user["role"] == "candidate":
            hide_shortlist_email_state(item)
        item["job"] = serialize_model(job)
        applications.append(item)

    return applications


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    user_uuid = parse_uuid(user["id"], "user id")

    app_res = await db.execute(
        select(Application).where(
            Application.id == app_uuid
        )
    )

    application = app_res.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if (
        user["role"] == "candidate"
        and application.candidate_id != user_uuid
    ):
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if (
        user["role"] == "recruiter"
        and application.recruiter_id != user_uuid
    ):
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if user["role"] not in ("candidate", "recruiter"):
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    result = serialize_model(application)
    if user["role"] == "candidate":
        hide_shortlist_email_state(result)

    job_res = await db.execute(
        select(Job).where(
            Job.id == application.job_id
        )
    )

    job = job_res.scalar_one_or_none()
    result["job"] = serialize_model(job)

    analysis = None

    if application.analysis_id:
        ana_res = await db.execute(
            select(ResumeAnalysis).where(
                ResumeAnalysis.id == application.analysis_id
            )
        )
        analysis = ana_res.scalar_one_or_none()

    result["analysis"] = serialize_model(analysis)

    if user["role"] == "recruiter":
        candidate_id = application.candidate_id

        prof_res = await db.execute(
            select(CandidateProfile).where(
                CandidateProfile.user_id == candidate_id
            )
        )
        profile = prof_res.scalar_one_or_none()

        usr_res = await db.execute(
            select(User).where(
                User.id == candidate_id
            )
        )
        account = usr_res.scalar_one_or_none()

        resume = None

        if application.resume_id:
            res_res = await db.execute(
                select(Resume).where(
                    Resume.id == application.resume_id,
                    Resume.candidate_id == candidate_id,
                )
            )
            resume = res_res.scalar_one_or_none()

        parsed_data = (
            resume.extracted_data or {}
            if resume
            else {}
        )

        result["candidate"] = {
            "id": str(candidate_id),
            "full_name": (
                (account.full_name if account else "")
                or (profile.headline if profile else "")
            ),
            "email": account.email if account else "",
            "phone": (
                (profile.phone if profile else None)
                or parsed_data.get("phone")
            ),
            "education": (
                (profile.education if profile else None)
                or parsed_data.get("education", [])
            ),
            "experience": (
                (profile.experience if profile else None)
                or parsed_data.get("experience", [])
            ),
            "skills": (
                (profile.skills if profile else None)
                or parsed_data.get("skills", [])
            ),
        }

        result["resume"] = (
            {
                "id": str(resume.id),
                "original_name": getattr(
                    resume,
                    "filename",
                    "Resume",
                ),
                "status": resume.status,
                "extracted_data": parsed_data,
            }
            if resume
            else None
        )

    return result


@router.put("/applications/{application_id}/withdraw")
async def withdraw_application(
    application_id: str,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    user_uuid = parse_uuid(user["id"], "candidate id")

    app_res = await db.execute(
        select(Application).where(
            Application.id == app_uuid,
            Application.candidate_id == user_uuid,
        )
    )

    application = app_res.scalar_one_or_none()

    if (
        not application
        or application.status not in WITHDRAWABLE_APPLICATION_STATUSES
    ):
        raise HTTPException(
            status_code=409,
            detail="This application cannot be withdrawn.",
        )

    now = datetime.now(timezone.utc)

    application.status = "withdrawn"
    application.updated_at = now

    notification = Notification(
        user_id=application.recruiter_id,
        type="application_withdrawn",
        message="A candidate withdrew an application.",
        related_id=app_uuid,
        job_id=application.job_id,
        is_read=False,
        created_at=now,
    )

    db.add(notification)

    await db.commit()

    return {"status": "withdrawn"}


@router.put("/applications/{application_id}/status")
async def update_application_status(
    application_id: str,
    data: ApplicationStatusInput,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")

    app_res = await db.execute(
        select(Application).where(
            Application.id == app_uuid,
            Application.recruiter_id == recruiter_uuid,
        )
    )

    application = app_res.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application was not found.",
        )

    if application.status == "rejected":
        raise HTTPException(status_code=409, detail="Rejected applications cannot be changed.")

    eligible = application.screening_status in (
        "shortlisted",
        "pending_review",
    )

    reconsideration_requested = (
        application.reconsideration_status == "requested"
    )

    if not eligible and not reconsideration_requested:
        raise HTTPException(
            status_code=409,
            detail="This application is not available for recruiter review.",
        )

    allowed_statuses = {
        "shortlisted",
        "rejected",
        "interview",
        "selected",
        "under_review",
    }

    if data.status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid application status.",
        )

    previous_status = application.status
    now = datetime.now(timezone.utc)

    application.status = data.status
    application.updated_at = now

    application.rejection_reason = (
        data.rejection_reason
        if data.status == "rejected"
        else None
    )

    if data.status == "shortlisted":
        application.recruiter_decision = "accepted"

    elif data.status == "rejected":
        application.recruiter_decision = "rejected"

    # Assessment creation is intentionally not triggered here.
    # Recruiters create and publish assessments through the
    # dedicated assessment endpoints, then assign them to shortlisted
    # applications.

    if previous_status != data.status:
        message = (
            f"Your application has been "
            f"{data.status.replace('_', ' ')}."
        )

        if data.status == "rejected" and data.rejection_reason:
            message += f" Reason: {data.rejection_reason}"

        notification = Notification(
            user_id=application.candidate_id,
            type="application_status",
            message=message,
            related_id=app_uuid,
            job_id=application.job_id,
            is_read=False,
            created_at=now,
        )

        db.add(notification)

    await db.commit()

    if previous_status != "shortlisted" and data.status == "shortlisted":
        application = await deliver_shortlist_email(db, app_uuid)
    else:
        await db.refresh(application)

    return {
        "status": data.status,
        "rejection_reason": application.rejection_reason,
        "shortlist_email_status": application.shortlist_email_status,
        "shortlist_email_error": application.shortlist_email_error,
        "shortlist_email_attempts": application.shortlist_email_attempts,
    }


@router.post("/applications/{application_id}/shortlist-email/resend")
async def resend_shortlist_email(
    application_id: str,
    user: dict = Depends(recruiter_required),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    recruiter_uuid = parse_uuid(user["id"], "recruiter id")
    application = await db.scalar(
        select(Application)
        .where(
            Application.id == app_uuid,
            Application.recruiter_id == recruiter_uuid,
            Application.status == "shortlisted",
        )
        .with_for_update()
    )
    if not application:
        raise HTTPException(
            status_code=404,
            detail="Shortlisted application was not found.",
        )
    if application.shortlist_email_status != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only failed shortlisting emails can be resent.",
        )

    await db.commit()
    application = await deliver_shortlist_email(db, app_uuid)
    return {
        "message": "Shortlisting email resend attempted.",
        "shortlist_email_status": application.shortlist_email_status,
        "shortlist_email_error": application.shortlist_email_error,
        "shortlist_email_attempts": application.shortlist_email_attempts,
    }


@router.post("/applications/{application_id}/reconsider")
async def request_reconsideration(
    application_id: str,
    data: ReconsiderationInput,
    user: dict = Depends(candidate_required),
    db: AsyncSession = Depends(get_database),
):
    app_uuid = parse_uuid(application_id, "application id")
    candidate_id = parse_uuid(user["id"], "candidate id")

    app_res = await db.execute(
        select(Application).where(
            Application.id == app_uuid,
            Application.candidate_id == candidate_id,
            Application.screening_status == "not_shortlisted",
            Application.status == "rejected",
        )
    )

    application = app_res.scalar_one_or_none()

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Eligible application for reconsideration was not found.",
        )

    if application.reconsideration_status == "requested":
        raise HTTPException(
            status_code=409,
            detail="You have already requested a manual review.",
        )

    now = datetime.now(timezone.utc)

    application.reconsideration_status = "requested"
    application.reconsideration_reason = data.reason
    application.reconsideration_requested_at = now
    application.updated_at = now

    recruiter_notification = Notification(
        user_id=application.recruiter_id,
        type="reconsideration_requested",
        message=(
            "A candidate has requested a manual review "
            "of an AI screening result."
        ),
        related_id=app_uuid,
        job_id=application.job_id,
        is_read=False,
        created_at=now,
    )

    candidate_notification = Notification(
        user_id=candidate_id,
        type="reconsideration_submitted",
        message=(
            "Your manual review request has been sent to the recruiter."
        ),
        related_id=app_uuid,
        job_id=application.job_id,
        is_read=False,
        created_at=now,
    )

    db.add(recruiter_notification)
    db.add(candidate_notification)

    await db.commit()

    return {
        "message": "Manual review request submitted successfully."
    }
