
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assessment as PGAssessment,
    AssessmentAnswer,
    AssessmentAnswerKey,
    AssessmentQuestion,
    Job as PGJob,
    Notification as PGNotification,
    QuestionBankQuestion,
)


ASSESSMENT_DURATION_MINUTES = 30
PASSING_SCORE = 70

DIFFICULTY_COUNTS = {
    "easy": 10,
    "medium": 15,
    "hard": 5,
}

CATEGORY_KEYWORDS = {
    "python": ("python", "django", "fastapi", "flask", "pandas"),
    "java": ("java", "jvm", "spring boot"),
    "oop": ("oop", "object-oriented", "object oriented", "inheritance", "polymorphism"),
    "data_structures": ("data structures", "algorithm", "algorithms", "complexity"),
    "web_frontend": ("html", "css", "javascript", "frontend", "front-end"),
    "react": ("react", "jsx", "hooks"),
    "backend_api": ("api", "rest", "backend", "back-end", "http", "node.js"),
    "databases": ("database", "mongodb", "postgres", "mysql", "nosql", "redis", "sql"),
    "networking": ("networking", "network", "tcp", "dns", "routing", "firewall"),
    "linux": ("linux", "bash", "shell", "system administration"),
    "cybersecurity": ("cybersecurity", "security", "vulnerability", "penetration testing", "infosec"),
    "statistics_visualization": ("statistics", "visualization", "tableau", "power bi", "analytics"),
    "machine_learning": ("machine learning", "deep learning", "model training"),
    "model_evaluation": ("model evaluation", "evaluation metrics", "precision", "recall"),
}

ROLE_CATEGORIES = {
    "python_developer": ("python", "oop", "data_structures"),
    "java_developer": ("java", "oop", "data_structures"),
    "full_stack_developer": ("web_frontend", "react", "backend_api", "databases"),
    "cybersecurity_analyst": ("networking", "linux", "cybersecurity"),
    "cyber_security_analyst": ("networking", "linux", "cybersecurity"),
    "data_analyst": ("databases", "statistics_visualization", "python"),
    "ai_ml_engineer": ("python", "machine_learning", "statistics_visualization", "model_evaluation"),
    "machine_learning_engineer": ("python", "machine_learning", "statistics_visualization", "model_evaluation"),
}


def as_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def normalize_text(value: Any) -> str:
    return re.sub(r"[\s\-_/]+", "", str(value or "").casefold())


def relevant_categories(
    job: dict[str, Any],
) -> tuple[list[str], dict[str, int]]:
    title = str(job.get("title", "")).casefold()
    description = str(job.get("description", "")).casefold()

    skills = job.get("required_skills") or []

    if isinstance(skills, str):
        skills = [skills]

    skill_text = " ".join(str(skill).casefold() for skill in skills)

    combined = " ".join((title, description, skill_text))
    normalized = normalize_text(combined)
    normalized_title = normalize_text(title)

    selected = set()
    weights = {}

    for role, categories in ROLE_CATEGORIES.items():
        role_name = normalize_text(role.replace("_", " "))

        if role_name in normalized_title:
            selected.update(categories)

    for category, keywords in CATEGORY_KEYWORDS.items():
        matches = [
            keyword
            for keyword in keywords
            if normalize_text(keyword) in normalized
        ]

        if not matches:
            continue

        selected.add(category)
        weight = 1

        for keyword in keywords:
            if any(
                normalize_text(keyword) in normalize_text(skill)
                for skill in skills
            ):
                weight += 3

        if any(
            normalize_text(keyword) in normalized_title
            for keyword in keywords
        ):
            weight += 4

        weights[category] = weight

    for category in selected:
        weights.setdefault(category, 1)

    return sorted(selected), weights


def question_categories(
    question: QuestionBankQuestion,
) -> set[str]:
    source = " ".join(
        str(value or "")
        for value in (question.technology, question.role)
    )

    normalized = normalize_text(source)
    categories = set()

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(
            normalize_text(keyword) in normalized
            for keyword in keywords
        ):
            categories.add(category)

    for role, role_categories in ROLE_CATEGORIES.items():
        if normalize_text(role.replace("_", " ")) in normalized:
            categories.update(role_categories)

    return categories


def normalize_options(options: Any) -> list[str]:
    if isinstance(options, dict):
        return [str(value) for value in options.values()]

    if isinstance(options, list):
        return [str(value) for value in options]

    return []


def get_correct_index(
    correct_option: Any,
    options: list[str],
) -> int:
    value = str(correct_option).strip()
    labels = ["A", "B", "C", "D", "E", "F"]

    if value.upper() in labels:
        index = labels.index(value.upper())
        if index < len(options):
            return index

    if value.isdigit():
        index = int(value)
        if 0 <= index < len(options):
            return index

    for index, option in enumerate(options):
        if option.strip() == value:
            return index

    raise ValueError(
        "Question bank contains an invalid correct_option value."
    )


def select_assessment_questions(
    job: dict[str, Any],
    bank_questions: list[QuestionBankQuestion],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:

    categories, category_weights = relevant_categories(job)
    eligible = []

    for question in bank_questions:
        if question.difficulty not in DIFFICULTY_COUNTS:
            continue

        if not question.is_active:
            continue

        matching_categories = (
            question_categories(question).intersection(categories)
        )

        if not matching_categories:
            continue

        options = normalize_options(question.options)

        if len(options) < 2:
            continue

        try:
            correct_index = get_correct_index(
                question.correct_option,
                options,
            )
        except ValueError:
            continue

        category = sorted(matching_categories)[0]

        eligible.append({
            "bank_id": question.id,
            "category": category,
            "topic": question.technology or question.role or "General",
            "difficulty": question.difficulty,
            "prompt": question.question,
            "options": options,
            "correct_index": correct_index,
            "explanation": question.explanation or "",
        })

    counts = {
        difficulty: sum(
            item["difficulty"] == difficulty
            for item in eligible
        )
        for difficulty in DIFFICULTY_COUNTS
    }

    shortages = {
        difficulty: {
            "required": required,
            "available": counts[difficulty],
        }
        for difficulty, required in DIFFICULTY_COUNTS.items()
        if counts[difficulty] < required
    }

    if shortages:
        return [], {
            "categories": categories,
            "shortages": shortages,
            "required_total": sum(DIFFICULTY_COUNTS.values()),
            "available_total": len(eligible),
        }

    selected = []

    for difficulty, required in DIFFICULTY_COUNTS.items():
        pool = [
            item.copy()
            for item in eligible
            if item["difficulty"] == difficulty
        ]

        for _ in range(required):
            weights = [
                category_weights.get(item["category"], 1)
                for item in pool
            ]

            chosen = random.choices(
                pool,
                weights=weights,
                k=1,
            )[0]

            selected.append(chosen)
            pool.remove(chosen)

    random.shuffle(selected)

    return selected, None


def evaluate_assessment(
    questions: list[dict[str, Any]],
    answer_key: dict[str, dict[str, Any]],
    answers: dict[str, int],
) -> dict[str, Any]:

    correct = 0
    incorrect = 0
    topic_results = {}
    difficulty_results = {}

    for question in questions:
        question_id = question["question_id"]
        key = answer_key[question_id]

        selected = answers.get(question_id)
        is_correct = selected == key["correct_index"]

        if selected is None:
            outcome = "unanswered"
        elif is_correct:
            correct += 1
            outcome = "correct"
        else:
            incorrect += 1
            outcome = "incorrect"

        for result, name in (
            (topic_results, key["topic"]),
            (difficulty_results, key["difficulty"]),
        ):
            stats = result.setdefault(
                name,
                {
                    "correct": 0,
                    "incorrect": 0,
                    "unanswered": 0,
                    "total": 0,
                },
            )

            stats[outcome] += 1
            stats["total"] += 1

    total = len(questions)
    unanswered = total - correct - incorrect

    percentage = (
        round(correct * 100 / total, 2)
        if total
        else 0
    )

    passed = percentage >= PASSING_SCORE

    def summarize(results):
        return {
            topic: {
                **stats,
                "percentage": round(
                    stats["correct"] * 100 / stats["total"],
                    2,
                ),
            }
            for topic, stats in sorted(results.items())
        }

    topics = summarize(topic_results)
    difficulties = summarize(difficulty_results)

    strong = [
        topic
        for topic, stats in topics.items()
        if stats["percentage"] >= PASSING_SCORE
    ]

    weak = [
        topic
        for topic, stats in topics.items()
        if stats["percentage"] < PASSING_SCORE
    ]

    if not strong:
        summary = (
            "This attempt shows foundational areas to strengthen "
            "before the next assessment."
        )
    elif not weak:
        summary = (
            "Strong, consistent performance across the assessed topics."
        )
    else:
        summary = (
            "Good progress on several topics, with focused practice "
            "needed in weaker areas."
        )

    suggestions = [
        f"Review {topic} and practice applying it to short, realistic problems."
        for topic in weak
    ]

    if not suggestions:
        suggestions = [
            "Continue practicing mixed-difficulty problems to retain these skills."
        ]

    report = {
        "summary": summary,
        "strong_skills": strong,
        "weak_areas": weak,
        "topic_performance": topics,
        "difficulty_performance": difficulties,
        "improvement_suggestions": suggestions,
        "recommended_learning_topics": weak or strong,
        "report_source": "deterministic_template",
    }

    return {
        "correct_count": correct,
        "incorrect_count": incorrect,
        "unanswered_count": unanswered,
        "total_questions": total,
        "percentage": percentage,
        "result": "pass" if passed else "fail",
        "second_round_eligible": passed,
        "performance_report": report,
    }


def candidate_question(
    question: dict[str, Any],
) -> dict[str, Any]:
    return {
        "question_id": question["question_id"],
        "category": question["category"],
        "topic": question["topic"],
        "difficulty": question["difficulty"],
        "prompt": question["prompt"],
        "options": question["options"],
    }


def serialize_pg_assessment(model: Any) -> dict[str, Any]:
    if model is None:
        return {}

    extra = dict(model.extra_data or {})

    result = {
        "_id": str(model.id),
        "id": str(model.id),
        "application_id": (
            str(model.application_id)
            if model.application_id
            else None
        ),
        "candidate_id": str(model.candidate_id),
        "recruiter_id": str(model.recruiter_id),
        "job_id": str(model.job_id),
        "status": model.status,
        "total_questions": model.total_questions,
        "question_count": model.total_questions,
        "duration_minutes": model.duration_minutes,
        "time_limit_minutes": model.duration_minutes,
        "passing_percentage": model.passing_percentage,
        "score": model.score,
        "started_at": model.started_at,
        "expires_at": model.expires_at,
        "deadline_at": model.expires_at,
        "submitted_at": model.submitted_at,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }

    result.update(extra)

    # Database columns remain authoritative.
    result["_id"] = str(model.id)
    result["id"] = str(model.id)
    result["status"] = model.status
    result["score"] = model.score

    return result


def serialize_assessment(
    assessment: dict[str, Any],
    include_questions: bool = False,
) -> dict[str, Any]:

    safe = {
        key: value
        for key, value in assessment.items()
        if key not in {
            "_id",
            "answers",
            "questions",
            "answer_key",
        }
    }

    safe["id"] = str(
        assessment.get("_id") or assessment.get("id")
    )

    for field in (
        "candidate_id",
        "application_id",
        "job_id",
        "recruiter_id",
    ):
        if safe.get(field) is not None:
            safe[field] = str(safe[field])

    if include_questions:
        safe["questions"] = [
            candidate_question(question)
            for question in assessment.get("questions", [])
        ]
        safe["answers"] = assessment.get("answers", {})

    return safe


async def create_assessment_for_application(
    database: AsyncSession,
    application: Any,
) -> tuple[dict[str, Any], bool]:

    application_id = getattr(application, "id", None)
    job_id = getattr(application, "job_id", None)
    candidate_id = getattr(application, "candidate_id", None)
    recruiter_id = getattr(application, "recruiter_id", None)

    if isinstance(application, dict):
        application_id = (
            application.get("id") or application.get("_id")
        )
        job_id = application.get("job_id")
        candidate_id = application.get("candidate_id")
        recruiter_id = application.get("recruiter_id")

    application_id = as_uuid(application_id)
    job_id = as_uuid(job_id)
    candidate_id = as_uuid(candidate_id)
    recruiter_id = as_uuid(recruiter_id)

    existing = await database.scalar(
        select(PGAssessment).where(
            PGAssessment.application_id == application_id
        )
    )

    if existing:
        return serialize_pg_assessment(existing), False

    job = await database.scalar(
        select(PGJob).where(PGJob.id == job_id)
    )

    if not job:
        raise ValueError(
            "The job for this application no longer exists."
        )

    job_dict = {
        "title": job.title,
        "description": job.description,
        "required_skills": job.required_skills or [],
    }

    categories, _ = relevant_categories(job_dict)

    # Only use this recruiter's own active question bank.
    bank_questions = (
        await database.scalars(
            select(QuestionBankQuestion).where(
                QuestionBankQuestion.is_active.is_(True),
                QuestionBankQuestion.recruiter_id == recruiter_id,
            )
        )
    ).all()

    selected, shortage = select_assessment_questions(
        job_dict,
        list(bank_questions),
    )

    now = datetime.now(timezone.utc)
    assessment_id = uuid4()

    questions = []
    answer_key = {}
    question_models = []
    answer_key_models = []

    for order_number, question in enumerate(selected, start=1):
        question_uuid = uuid4()
        question_id = str(question_uuid)

        question_snapshot = {
            "question_id": question_id,
            "category": question["category"],
            "topic": question["topic"],
            "difficulty": question["difficulty"],
            "prompt": question["prompt"],
            "options": list(question["options"]),
        }

        questions.append(question_snapshot)

        answer_key[question_id] = {
            "correct_index": question["correct_index"],
            "topic": question["topic"],
            "difficulty": question["difficulty"],
            "explanation": question["explanation"],
        }

        question_models.append(
            AssessmentQuestion(
                id=question_uuid,
                assessment_id=assessment_id,
                question_bank_id=question["bank_id"],
                question_text=question["prompt"],
                options=list(question["options"]),
                difficulty=question["difficulty"],
                order_number=order_number,
            )
        )

        correct_label = chr(65 + question["correct_index"])

        answer_key_models.append(
            AssessmentAnswerKey(
                assessment_question_id=question_uuid,
                correct_option=correct_label,
                explanation=question["explanation"],
            )
        )

    assessment_status = (
        "question_shortage" if shortage else "assigned"
    )

    extra = {
        "job_title": job.title or "",
        "questions": questions,
        "answer_key": answer_key,
        "shortage": shortage,
        "attempt_count": 0,
        "second_round_decision": "pending",
        "categories": categories,
    }

    new_assessment = PGAssessment(
        id=assessment_id,
        application_id=application_id,
        candidate_id=candidate_id,
        recruiter_id=recruiter_id,
        job_id=job.id,
        status=assessment_status,
        total_questions=len(questions),
        duration_minutes=ASSESSMENT_DURATION_MINUTES,
        passing_percentage=float(PASSING_SCORE),
        extra_data=extra,
        created_at=now,
        updated_at=now,
    )

    notification = PGNotification(
        user_id=candidate_id,
        type=(
            "assessment_assigned"
            if not shortage
            else "assessment_unavailable"
        ),
        message=(
            (
                "You have been selected for the next round! "
                "Your First Round Technical Assessment is now available. "
                "Please complete it within the given time limit."
            )
            if not shortage
            else (
                f"An assessment could not be prepared for "
                f"{job.title or 'this role'}: the role-specific question "
                f"bank has {shortage['available_total']} questions; "
                "30 are required. Please contact the recruiter."
            )
        ),
        related_id=assessment_id,
        job_id=job.id,
        is_read=False,
        created_at=now,
    )

    try:
        database.add(new_assessment)

        if question_models:
            database.add_all(question_models)
            database.add_all(answer_key_models)

        database.add(notification)

        await database.commit()
        await database.refresh(new_assessment)

    except IntegrityError:
        await database.rollback()

        existing = await database.scalar(
            select(PGAssessment).where(
                PGAssessment.application_id == application_id
            )
        )

        if existing:
            return serialize_pg_assessment(existing), False

        raise

    return serialize_pg_assessment(new_assessment), True


async def get_assessment_for_user(
    database: AsyncSession,
    assessment_id: Any,
    user: dict[str, Any],
) -> dict[str, Any] | None:

    try:
        assessment_uuid = as_uuid(assessment_id)
        user_uuid = as_uuid(user["id"])
    except (ValueError, TypeError, AttributeError, KeyError):
        return None

    conditions = [
        PGAssessment.id == assessment_uuid,
    ]

    if user["role"] == "candidate":
        conditions.append(
            PGAssessment.candidate_id == user_uuid
        )

    elif user["role"] == "recruiter":
        conditions.append(
            PGAssessment.recruiter_id == user_uuid
        )

    model = await database.scalar(
        select(PGAssessment).where(*conditions)
    )

    if not model:
        return None

    return serialize_pg_assessment(model)


async def publish_assessment_result(
    database: AsyncSession,
    assessment: dict[str, Any],
    answers: dict[str, int],
) -> dict[str, Any]:

    assessment_id = assessment.get("id") or assessment.get("_id")

    model = await database.scalar(
        select(PGAssessment).where(
            PGAssessment.id == as_uuid(assessment_id)
        )
    )

    if not model:
        raise RuntimeError("Assessment was not found.")

    if model.status != "in_progress":
        return serialize_pg_assessment(model)

    extra = dict(model.extra_data or {})
    answer_key = extra.get("answer_key", {})
    questions = extra.get("questions", [])

    if not answer_key:
        raise RuntimeError(
            "The answer key for this assessment is unavailable."
        )

    normalized_answers = {}

    for question_id, selected in (answers or {}).items():
        try:
            normalized_answers[str(question_id)] = int(selected)
        except (ValueError, TypeError):
            continue

    evaluation = evaluate_assessment(
        questions,
        answer_key,
        normalized_answers,
    )

    now = datetime.now(timezone.utc)

    question_models = (
        await database.scalars(
            select(AssessmentQuestion).where(
                AssessmentQuestion.assessment_id == model.id
            )
        )
    ).all()

    question_lookup = {
        str(question.id): question
        for question in question_models
    }

    for question_snapshot in questions:
        question_id = question_snapshot["question_id"]
        question_model = question_lookup.get(question_id)

        if not question_model:
            continue

        selected_index = normalized_answers.get(question_id)
        key = answer_key[question_id]

        selected_label = (
            chr(65 + selected_index)
            if selected_index is not None
            and 0 <= selected_index < len(question_snapshot["options"])
            else None
        )

        answer_record = await database.scalar(
            select(AssessmentAnswer).where(
                AssessmentAnswer.assessment_question_id
                == question_model.id
            )
        )

        if answer_record is None:
            answer_record = AssessmentAnswer(
                assessment_id=model.id,
                assessment_question_id=question_model.id,
            )

        answer_record.selected_option = selected_label
        answer_record.is_correct = (
            selected_index == key["correct_index"]
            if selected_label is not None
            else None
        )
        answer_record.answered_at = now

        database.add(answer_record)

    model.status = "submitted"
    model.score = float(evaluation["percentage"])
    model.submitted_at = now
    model.updated_at = now

    extra.update(evaluation)
    extra["answers"] = normalized_answers
    extra["status"] = "submitted"
    extra["submitted_at"] = now.isoformat()
    extra["updated_at"] = now.isoformat()

    model.extra_data = extra

    job = await database.scalar(
        select(PGJob).where(PGJob.id == model.job_id)
    )

    title = job.title if job else "your assessment"

    database.add_all([
        PGNotification(
            user_id=model.candidate_id,
            type="assessment_submitted",
            message=(
                f"Your assessment for {title} was submitted and evaluated."
            ),
            related_id=model.id,
            job_id=model.job_id,
            is_read=False,
            created_at=now,
        ),
        PGNotification(
            user_id=model.candidate_id,
            type="assessment_result_published",
            message=(
                f"Your assessment for {title} is complete: "
                f"{evaluation['percentage']}% "
                f"({evaluation['result'].upper()}). "
                + (
                    "You are eligible for the second round; "
                    "the recruiter will decide whether to invite you."
                    if evaluation["second_round_eligible"]
                    else "You are not eligible for the second round."
                )
            ),
            related_id=model.id,
            job_id=model.job_id,
            is_read=False,
            created_at=now,
        ),
    ])

    await database.commit()
    await database.refresh(model)

    return serialize_pg_assessment(model)


async def complete_if_expired(
    database: AsyncSession,
    assessment: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:

    now = now or datetime.now(timezone.utc)

    deadline = (
        assessment.get("deadline_at")
        or assessment.get("expires_at")
    )

    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline)
        except ValueError:
            deadline = None

    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    if (
        assessment.get("status") == "in_progress"
        and deadline
        and now >= deadline
    ):
        return await publish_assessment_result(
            database,
            assessment,
            assessment.get("answers", {}),
        )

    return assessment


def deadline_after(
    minutes: int,
    now: datetime | None = None,
) -> datetime:
    return (
        now or datetime.now(timezone.utc)
    ) + timedelta(minutes=minutes)
