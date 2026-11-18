
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    candidate_required,
    get_current_user,
    get_database,
    recruiter_required,
)
from app.models import (
    Application,
    AssessmentAnswer,
    AssessmentAnswerKey,
    AssessmentQuestion,
    Assessment as PGAssessment,
    Company,
    Job,
    Notification,
    ProctoringSession,
    QuestionBankQuestion,
    User,
)
from app.services.assessment_ai import AssessmentAIError, generate_assessment_questions
from app.services.assessments import (
    assign_assessment_to_candidates,
    complete_if_expired,
    create_assessment_draft,
    deadline_after,
    get_assessment_for_user,
    get_correct_index,
    normalize_distribution,
    publish_assessment_draft,
    publish_assessment_result,
    save_assessment_answers,
    serialize_assessment,
    serialize_pg_assessment,
)


router = APIRouter(prefix="/assessments", tags=["assessments"])


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class AssessmentDraftInput(BaseModel):
    job_id: UUID
    title: str = Field(min_length=3, max_length=200)
    question_count: int = Field(ge=1, le=100)
    duration_minutes: int = Field(default=30, ge=1, le=240)
    passing_marks: float = Field(ge=0)
    difficulty_distribution: dict[str, float] | None = None
    categories: list[str] = Field(default_factory=list)
    technology: str | None = None
    topic: str | None = None
    marks_per_question: float = Field(default=1, gt=0)
    randomize: bool = True
    question_ids: list[UUID] | None = None


class AssessmentAIDraftInput(AssessmentDraftInput):
    question_count: int = Field(ge=1, le=50)


class QuestionBankInput(BaseModel):
    technology: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=150)
    category: str | None = Field(default=None, max_length=150)
    topic: str | None = Field(default=None, max_length=150)
    subtopic: str | None = Field(default=None, max_length=150)
    difficulty: Literal["easy", "medium", "hard"]
    question: str = Field(min_length=1, max_length=10000)
    options: list[str] = Field(min_length=2, max_length=5)
    correct_option: str = Field(min_length=1, max_length=10)
    explanation: str | None = Field(default=None, max_length=10000)
    marks: float = Field(default=1, gt=0)


class AssessmentAssignmentInput(BaseModel):
    application_ids: list[UUID] = Field(min_length=1)


class AssessmentAnswersInput(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict)


class SecondRoundDecisionInput(BaseModel):
    decision: Literal["invited", "not_invited"]


# ============================================================
# COMMON HELPERS
# ============================================================

def _user_id(user: dict[str, Any]) -> UUID:
    try:
        return UUID(str(user["id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity.",
        )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


async def _owned_assessment(
    database: AsyncSession,
    assessment_id: UUID,
    recruiter_id: UUID,
) -> PGAssessment:
    model = await database.scalar(
        select(PGAssessment).where(
            PGAssessment.id == assessment_id,
            PGAssessment.recruiter_id == recruiter_id,
        )
    )

    if not model:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    return model


async def _candidate_assessment_for_update(
    database: AsyncSession,
    assessment_id: UUID,
    candidate_id: UUID,
) -> PGAssessment:
    model = await database.scalar(
        select(PGAssessment)
        .where(
            PGAssessment.id == assessment_id,
            PGAssessment.candidate_id == candidate_id,
        )
        .with_for_update()
    )

    if not model:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    return model


async def _require_active_proctoring_session(
    database: AsyncSession,
    assessment_id: UUID,
    candidate_id: UUID,
) -> ProctoringSession:
    session = await database.scalar(
        select(ProctoringSession).where(
            ProctoringSession.assessment_id == assessment_id,
            ProctoringSession.candidate_id == candidate_id,
            ProctoringSession.status == "active",
        )
    )
    if session is None:
        raise HTTPException(
            status_code=409,
            detail="Enable camera monitoring before continuing this assessment.",
        )
    return session


# ============================================================
# CREATE RECRUITER DRAFT
# ============================================================

@router.post("/generate-draft", status_code=status.HTTP_201_CREATED)
async def generate_assessment_draft(
    data: AssessmentAIDraftInput,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)
    job = await database.scalar(select(Job).where(Job.id == data.job_id, Job.recruiter_id == recruiter_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if data.question_ids:
        raise HTTPException(status_code=400, detail="AI-generated assessments do not select questions from the question bank.")
    company = await database.scalar(select(Company).where(Company.id == job.company_id)) if job.company_id else None
    company_data = dict(company.extra_data or {}) if company else {}
    skills = job.required_skills if isinstance(job.required_skills, list) else []
    requirements = job.requirements if isinstance(job.requirements, list) else []
    responsibilities = job.responsibilities if isinstance(job.responsibilities, list) else []
    domain = str(company_data.get("industry") or (job.extra_data or {}).get("industry") or "")
    context = {
        "job_title": job.title,
        "description": (job.description or "")[:5000],
        "skills": skills[:40],
        "requirements": requirements[:30],
        "responsibilities": responsibilities[:30],
        "domain": domain[:200],
        "focus_technology": data.technology or "",
        "focus_topic": data.topic or "",
    }
    try:
        distribution = normalize_distribution(data.difficulty_distribution, data.question_count)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    required_difficulties = [level for level in ("easy", "medium", "hard") for _ in range(distribution[level])]
    context["difficulty_counts"] = distribution
    context["required_difficulties_in_order"] = required_difficulties
    try:
        generated = await generate_assessment_questions(context, data.question_count, required_difficulties)
    except AssessmentAIError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    prepared = [{
        **item,
        "category": domain or "AI generated",
        "correct_index": ord(item["correct_option"]) - 65,
    } for item in generated]
    try:
        assessment = await create_assessment_draft(
            database=database,
            recruiter_id=recruiter_id,
            job_id=data.job_id,
            title=data.title,
            question_count=data.question_count,
            duration_minutes=data.duration_minutes,
            passing_marks=data.passing_marks,
            difficulty_distribution=data.difficulty_distribution,
            categories=data.categories,
            technology=data.technology,
            topic=data.topic,
            marks_per_question=data.marks_per_question,
            randomize=data.randomize,
            generated_questions=prepared,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    generated_by_prompt = {item["question"]: item for item in generated}
    preview = []
    for question in assessment.get("questions", []):
        source = generated_by_prompt[question["prompt"]]
        preview.append({**source, "id": question["question_id"]})
    return {"assessment": assessment, "questions": preview, "total": len(preview)}

@router.get("/question-bank")
async def list_question_bank(
    technology: str | None = None,
    category: str | None = None,
    difficulty: Literal["easy", "medium", "hard"] | None = None,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)
    query = select(QuestionBankQuestion).where(
        QuestionBankQuestion.is_active.is_(True),
        (
            (QuestionBankQuestion.recruiter_id == recruiter_id)
            | QuestionBankQuestion.recruiter_id.is_(None)
        ),
    )
    if technology:
        query = query.where(
            QuestionBankQuestion.technology.ilike(f"%{technology.strip()}%")
        )
    if category:
        query = query.where(
            QuestionBankQuestion.category.ilike(f"%{category.strip()}%")
        )
    if difficulty:
        query = query.where(QuestionBankQuestion.difficulty == difficulty)

    questions = (
        await database.scalars(
            query.order_by(QuestionBankQuestion.created_at.desc()).limit(500)
        )
    ).all()
    return {
        "questions": [
            {
                "id": str(question.id),
                "technology": question.technology,
                "role": question.role,
                "category": question.category,
                "topic": question.topic,
                "subtopic": question.subtopic,
                "difficulty": question.difficulty,
                "question": question.question,
                "options": question.options,
                "correct_option": question.correct_option,
                "explanation": question.explanation,
                "marks": question.marks,
            }
            for question in questions
        ],
        "total": len(questions),
    }


@router.post("/question-bank", status_code=status.HTTP_201_CREATED)
async def add_question_bank_item(
    data: QuestionBankInput,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    if not data.technology.strip() or not data.role.strip() or not data.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Technology, role, and question text are required.",
        )
    options = [option.strip() for option in data.options]
    if any(not option for option in options) or len(
        {option.casefold() for option in options}
    ) != len(options):
        raise HTTPException(
            status_code=400,
            detail="Question options must be non-empty and unique.",
        )
    try:
        correct_index = get_correct_index(data.correct_option, options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    question = QuestionBankQuestion(
        recruiter_id=_user_id(user),
        technology=data.technology.strip(),
        role=data.role.strip(),
        category=data.category.strip() if data.category else None,
        topic=data.topic.strip() if data.topic else None,
        subtopic=data.subtopic.strip() if data.subtopic else None,
        difficulty=data.difficulty,
        question=data.question.strip(),
        options=options,
        correct_option=chr(65 + correct_index),
        explanation=data.explanation.strip() if data.explanation else None,
        marks=data.marks,
        is_active=True,
    )
    database.add(question)
    try:
        await database.commit()
        await database.refresh(question)
    except Exception:
        await database.rollback()
        raise

    return {"id": str(question.id), "message": "Question added to the bank."}


@router.post(
    "/draft",
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    data: AssessmentDraftInput,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    try:
        return await create_assessment_draft(
            database=database,
            recruiter_id=_user_id(user),
            job_id=data.job_id,
            title=data.title,
            question_count=data.question_count,
            duration_minutes=data.duration_minutes,
            passing_marks=data.passing_marks,
            difficulty_distribution=data.difficulty_distribution,
            categories=data.categories,
            technology=data.technology,
            topic=data.topic,
            marks_per_question=data.marks_per_question,
            randomize=data.randomize,
            question_ids=data.question_ids,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


# ============================================================
# LIST ASSESSMENTS
# ============================================================

@router.get("")
async def list_assessments(
    user: dict = Depends(get_current_user),
    database: AsyncSession = Depends(get_database),
):
    user_id = _user_id(user)
    role = user.get("role")

    if role == "candidate":
        query = select(PGAssessment).where(
            PGAssessment.candidate_id == user_id,
            PGAssessment.application_id.is_not(None),
        )

    elif role == "recruiter":
        query = select(PGAssessment).where(
            PGAssessment.recruiter_id == user_id,
            PGAssessment.status != "draft",
        )

    else:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    models = (
        await database.scalars(
            query.order_by(
                PGAssessment.created_at.desc()
            )
        )
    ).all()

    results = []

    for model in models:
        item = serialize_pg_assessment(model)

        if role == "candidate":
            item.pop("answer_key", None)
            item.pop("questions", None)
            item.pop("answers", None)

        results.append(item)

    return {
        "assessments": results,
        "total": len(results),
    }


# ============================================================
# LIST RECRUITER TEMPLATES
# ============================================================

@router.get("/templates")
async def list_recruiter_templates(
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)

    models = (
        await database.scalars(
            select(PGAssessment)
            .where(
                PGAssessment.recruiter_id == recruiter_id,
                PGAssessment.application_id.is_(None),
            )
            .order_by(
                PGAssessment.created_at.desc()
            )
        )
    ).all()

    return {
        "assessments": [
            serialize_pg_assessment(model)
            for model in models
        ],
        "total": len(models),
    }


# ============================================================
# GET SINGLE ASSESSMENT
# ============================================================

@router.get("/{assessment_id}")
async def get_assessment(
    assessment_id: UUID,
    user: dict = Depends(get_current_user),
    database: AsyncSession = Depends(get_database),
):
    assessment = await get_assessment_for_user(
        database,
        assessment_id,
        user,
    )

    if not assessment:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    role = user.get("role")

    if role == "candidate":
        assessment = await complete_if_expired(
            database,
            assessment,
        )

        if assessment.get("status") == "in_progress":
            proctoring_session = await database.scalar(
                select(ProctoringSession).where(
                    ProctoringSession.assessment_id == assessment_id,
                    ProctoringSession.candidate_id == UUID(user["id"]),
                    ProctoringSession.status == "active",
                )
            )
            if proctoring_session is None:
                safe = serialize_assessment(assessment)
                safe.pop("answer_key", None)
                safe.pop("questions", None)
                safe.pop("answers", None)
                return safe
            return serialize_assessment(
                assessment,
                include_questions=True,
            )

        safe = serialize_assessment(assessment)

        safe.pop("answer_key", None)
        safe.pop("questions", None)
        safe.pop("answers", None)

        return safe

    if role == "recruiter":
        return serialize_assessment(
            assessment,
            include_questions=True,
        )

    raise HTTPException(
        status_code=403,
        detail="Access denied.",
    )


# ============================================================
# PUBLISH DRAFT
# ============================================================

@router.post("/{assessment_id}/publish")
async def publish_draft(
    assessment_id: UUID,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    try:
        return await publish_assessment_draft(
            database,
            assessment_id,
            _user_id(user),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


# ============================================================
# ASSIGN TO SHORTLISTED CANDIDATES
# ============================================================

@router.post("/{assessment_id}/assign")
async def assign_candidates(
    assessment_id: UUID,
    data: AssessmentAssignmentInput,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)

    template = await _owned_assessment(
        database,
        assessment_id,
        recruiter_id,
    )

    if template.application_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only a recruiter assessment template "
                "can be assigned."
            ),
        )

    if template.status != "published":
        raise HTTPException(
            status_code=400,
            detail="Publish the assessment before assigning it.",
        )

    requested_ids = data.application_ids

    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate application IDs are not allowed.",
        )

    applications = (
        await database.scalars(
            select(Application).where(
                Application.id.in_(requested_ids),
                Application.job_id == template.job_id,
                Application.recruiter_id == recruiter_id,
                Application.status == "shortlisted",
            )
        )
    ).all()

    if len(applications) != len(requested_ids):
        raise HTTPException(
            status_code=400,
            detail=(
                "Every application must belong to this recruiter "
                "and job and have shortlisted status."
            ),
        )

    candidates = [
        {
            "candidate_id": application.candidate_id,
            "application_id": application.id,
        }
        for application in applications
    ]

    try:
        assigned = await assign_assessment_to_candidates(
            database,
            assessment_id,
            recruiter_id,
            candidates,
        )

        return {
            "message": "Assessment assignment processed.",
            "assigned_count": len(assigned),
            "assessments": assigned,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


# ============================================================
# START CANDIDATE ASSESSMENT
# ============================================================

@router.post("/{assessment_id}/start")
async def start_assessment(
    assessment_id: UUID,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    candidate_id = _user_id(user)

    model = await _candidate_assessment_for_update(
        database,
        assessment_id,
        candidate_id,
    )
    proctoring_session = await database.scalar(
        select(ProctoringSession)
        .where(
            ProctoringSession.assessment_id == model.id,
            ProctoringSession.candidate_id == candidate_id,
        )
        .with_for_update()
    )
    if proctoring_session is None or proctoring_session.status not in {
        "ready",
        "active",
    }:
        raise HTTPException(
            status_code=409,
            detail="Enable camera monitoring before starting this assessment.",
        )

    if model.status == "in_progress":
        assessment = serialize_pg_assessment(model)

        assessment = await complete_if_expired(
            database,
            assessment,
        )

        if assessment.get("status") != "in_progress":
            return assessment

        return serialize_assessment(
            assessment,
            include_questions=True,
        )

    if model.status != "assigned":
        raise HTTPException(
            status_code=409,
            detail="This assessment cannot be started.",
        )

    extra = dict(model.extra_data or {})

    if int(extra.get("attempt_count", 0)) >= 1:
        raise HTTPException(
            status_code=409,
            detail="Only one attempt is allowed.",
        )

    now = datetime.now(timezone.utc)

    model.status = "in_progress"
    model.started_at = now
    model.expires_at = deadline_after(
        model.duration_minutes,
        now,
    )
    model.updated_at = now

    extra["attempt_count"] = 1
    extra["started_at"] = now.isoformat()
    extra["answers"] = {}

    model.extra_data = extra
    proctoring_session.status = "active"
    proctoring_session.warning_count = 0
    proctoring_session.started_at = proctoring_session.started_at or now
    proctoring_session.updated_at = now

    try:
        await database.commit()
        await database.refresh(model)

    except Exception:
        await database.rollback()
        raise

    return serialize_assessment(
        serialize_pg_assessment(model),
        include_questions=True,
    )


# ============================================================
# SAVE ANSWERS
# ============================================================

@router.put("/{assessment_id}/answers")
async def save_answers(
    assessment_id: UUID,
    data: AssessmentAnswersInput,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    await _require_active_proctoring_session(
        database,
        assessment_id,
        _user_id(user),
    )
    try:
        result = await save_assessment_answers(
            database,
            assessment_id,
            _user_id(user),
            data.answers,
        )

        result.pop("answer_key", None)
        result.pop("questions", None)

        return {
            "message": "Answers saved.",
            "assessment": result,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


# ============================================================
# SUBMIT ASSESSMENT
# ============================================================

@router.post("/{assessment_id}/submit")
async def submit_assessment(
    assessment_id: UUID,
    data: AssessmentAnswersInput,
    user: dict = Depends(candidate_required),
    database: AsyncSession = Depends(get_database),
):
    candidate_id = _user_id(user)

    # Lock and verify candidate ownership before evaluation.
    model = await _candidate_assessment_for_update(
        database,
        assessment_id,
        candidate_id,
    )

    if model.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail=(
                "Assessment has already been submitted "
                "or is not active."
            ),
        )

    await _require_active_proctoring_session(
        database,
        assessment_id,
        candidate_id,
    )

    assessment = serialize_pg_assessment(model)

    deadline = _as_utc(
        model.expires_at
    )

    now = datetime.now(timezone.utc)

    if deadline and now >= deadline:
        try:
            final = await complete_if_expired(
                database,
                assessment,
                now,
            )

        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

    else:
        try:
            final = await publish_assessment_result(
                database,
                assessment,
                data.answers,
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            )

        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

    return {
        "message": "Assessment evaluated.",
        **serialize_assessment(final, include_questions=True),
    }


# ============================================================
# CANDIDATE / RECRUITER RESULT
# ============================================================

@router.get("/{assessment_id}/review")
async def recruiter_assessment_review(
    assessment_id: UUID,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)
    model = await _owned_assessment(database, assessment_id, recruiter_id)
    if model.application_id is None or model.status not in {"submitted", "passed", "failed", "expired"}:
        raise HTTPException(status_code=409, detail="Candidate answers are available after submission.")
    rows = (await database.execute(
        select(AssessmentQuestion, AssessmentAnswerKey, AssessmentAnswer)
        .outerjoin(AssessmentAnswerKey, AssessmentAnswerKey.assessment_question_id == AssessmentQuestion.id)
        .outerjoin(AssessmentAnswer, AssessmentAnswer.assessment_question_id == AssessmentQuestion.id)
        .where(AssessmentQuestion.assessment_id == model.id)
        .order_by(AssessmentQuestion.order_number.asc())
    )).all()
    questions = []
    for question, key, answer in rows:
        selected = answer.selected_option if answer else None
        correct = key.correct_option if key else None
        questions.append({
            "question": question.question_text,
            "options": question.options,
            "selected_option": selected,
            "selected_answer": question.options[ord(selected.upper()) - 65] if selected and selected.upper() in "ABCD" and ord(selected.upper()) - 65 < len(question.options) else None,
            "correct_option": correct,
            "correct_answer": question.options[ord(correct.upper()) - 65] if correct and correct.upper() in "ABCD" and ord(correct.upper()) - 65 < len(question.options) else None,
            "is_correct": bool(answer.is_correct) if answer and answer.is_correct is not None else False,
            "marks": question.marks,
        })
    extra = dict(model.extra_data or {})
    return {
        "assessment_id": str(model.id),
        "status": model.status,
        "score": model.score,
        "earned_marks": extra.get("earned_marks", model.score),
        "total_marks": extra.get("total_marks", model.total_marks),
        "percentage": extra.get("percentage"),
        "result": extra.get("result"),
        "submitted_at": model.submitted_at,
        "questions": questions,
    }

@router.get("/{assessment_id}/result")
async def get_assessment_result(
    assessment_id: UUID,
    user: dict = Depends(get_current_user),
    database: AsyncSession = Depends(get_database),
):
    assessment = await get_assessment_for_user(
        database,
        assessment_id,
        user,
    )

    if not assessment:
        raise HTTPException(
            status_code=404,
            detail="Assessment not found.",
        )

    role = user.get("role")

    if role == "candidate":
        if assessment.get("status") not in (
            "submitted",
            "passed",
            "failed",
            "expired",
        ):
            raise HTTPException(
                status_code=409,
                detail="Result is not available yet.",
            )

        return {
            key: assessment.get(key)
            for key in (
                "id",
                "status",
                "score",
                "earned_marks",
                "total_marks",
                "passing_marks",
                "percentage",
                "result",
                "submitted_at",
                "performance_report",
            )
        }

    if role == "recruiter":
        return {
            "assessment": serialize_assessment(
                assessment,
                include_questions=True,
            )
        }

    raise HTTPException(
        status_code=403,
        detail="Access denied.",
    )


# ============================================================
# RECRUITER RESULTS DASHBOARD
# ============================================================

@router.get("/{assessment_id}/results")
async def recruiter_assessment_results(
    assessment_id: UUID,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)

    template = await _owned_assessment(
        database,
        assessment_id,
        recruiter_id,
    )

    if template.application_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Results must be opened from an assessment template.",
        )

    rows = (
        await database.execute(
            select(PGAssessment, User)
            .outerjoin(User, User.id == PGAssessment.candidate_id)
            .where(
                PGAssessment.recruiter_id == recruiter_id,
                PGAssessment.job_id == template.job_id,
                PGAssessment.application_id.is_not(None),
            )
            .order_by(
                PGAssessment.created_at.desc()
            )
        )
    ).all()

    # Only include candidate assessments created from this template.
    results = []

    for model, candidate in rows:
        extra = dict(model.extra_data or {})

        if extra.get("template_assessment_id") != str(template.id):
            continue

        results.append({
            "id": str(model.id),
            "application_id": (
                str(model.application_id)
                if model.application_id
                else None
            ),
            "candidate_id": (
                str(model.candidate_id)
                if model.candidate_id
                else None
            ),
            "candidate": {
                "full_name": candidate.full_name if candidate else "",
                "email": candidate.email if candidate else "",
            },
            "status": model.status,
            "score": model.score,
            "total_marks": extra.get("total_marks", model.total_marks),
            "earned_marks": extra.get("earned_marks"),
            "passing_marks": model.passing_marks,
            "percentage": extra.get("percentage"),
            "result": extra.get("result"),
            "submitted_at": model.submitted_at,
        })

    return {
        "template_id": str(template.id),
        "job_id": str(template.job_id),
        "results": results,
        "total": len(results),
    }


@router.put("/{assessment_id}/second-round")
async def decide_second_round(
    assessment_id: UUID,
    data: SecondRoundDecisionInput,
    user: dict = Depends(recruiter_required),
    database: AsyncSession = Depends(get_database),
):
    recruiter_id = _user_id(user)
    model = await database.scalar(
        select(PGAssessment)
        .where(
            PGAssessment.id == assessment_id,
            PGAssessment.recruiter_id == recruiter_id,
            PGAssessment.application_id.is_not(None),
        )
        .with_for_update()
    )
    if not model:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if model.status not in {"passed", "failed", "expired"}:
        raise HTTPException(
            status_code=409,
            detail="A decision is available after the assessment is completed.",
        )

    extra = dict(model.extra_data or {})
    eligible = bool(extra.get("second_round_eligible"))
    if data.decision == "invited" and not eligible:
        raise HTTPException(
            status_code=409,
            detail="Only candidates who meet the passing threshold can be invited.",
        )

    previous_decision = extra.get("second_round_decision", "pending")
    extra["second_round_decision"] = data.decision
    extra["second_round_decided_at"] = datetime.now(timezone.utc).isoformat()
    model.extra_data = extra
    model.updated_at = datetime.now(timezone.utc)

    if previous_decision != data.decision and model.candidate_id:
        database.add(
            Notification(
                user_id=model.candidate_id,
                type="assessment_second_round",
                message=(
                    "The recruiter invited you to the next round."
                    if data.decision == "invited"
                    else "The recruiter decided not to invite you to the next round."
                ),
                related_id=model.id,
                job_id=model.job_id,
                is_read=False,
                created_at=datetime.now(timezone.utc),
            )
        )

    try:
        await database.commit()
        await database.refresh(model)
    except Exception:
        await database.rollback()
        raise

    return serialize_assessment(
        serialize_pg_assessment(model),
        include_questions=True,
    )
