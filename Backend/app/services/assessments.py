
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    Assessment as PGAssessment,
    AssessmentAnswer,
    AssessmentAnswerKey,
    AssessmentQuestion,
    ProctoringSession,
    Job as PGJob,
    Notification as PGNotification,
    QuestionBankQuestion,
)


ASSESSMENT_DURATION_MINUTES = 30
PASSING_SCORE = 70
MAX_QUESTION_COUNT = 100

DEFAULT_DIFFICULTY_DISTRIBUTION = {
    "easy": 40,
    "medium": 40,
    "hard": 20,
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


# ============================================================
# COMMON HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def normalize_text(value: Any) -> str:
    return re.sub(r"[\s\-_/]+", "", str(value or "").casefold())


def normalize_options(options: Any) -> list[str]:
    if isinstance(options, dict):
        return [str(value) for value in options.values()]
    if isinstance(options, list):
        return [str(value) for value in options]
    return []


def get_correct_index(correct_option: Any, options: list[str]) -> int:
    value = str(correct_option).strip()
    labels = ["A", "B", "C", "D", "E"]

    if value.upper() in labels:
        index = labels.index(value.upper())
        if index < len(options):
            return index

    if value.isdigit():
        index = int(value)
        if 0 <= index < len(options):
            return index

    for index, option in enumerate(options):
        if option.strip().casefold() == value.casefold():
            return index

    raise ValueError("Question bank contains an invalid correct_option value.")


def _safe_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

    if not (float("-inf") < result < float("inf")):
        raise ValueError(f"{field_name} must be a finite number.")

    return result


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


# ============================================================
# JOB AND QUESTION CATEGORIES
# ============================================================

def relevant_categories(job: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    title = str(job.get("title", "")).casefold()
    description = str(job.get("description", "")).casefold()
    skills = job.get("required_skills") or []

    if isinstance(skills, str):
        skills = [skills]

    combined = " ".join([title, description] + [str(x).casefold() for x in skills])
    normalized = normalize_text(combined)
    normalized_title = normalize_text(title)

    selected = set()
    weights = {}

    for role, categories in ROLE_CATEGORIES.items():
        if normalize_text(role.replace("_", " ")) in normalized_title:
            selected.update(categories)

    for category, keywords in CATEGORY_KEYWORDS.items():
        matches = [k for k in keywords if normalize_text(k) in normalized]
        if not matches:
            continue

        selected.add(category)
        weight = 1

        for keyword in keywords:
            if any(normalize_text(keyword) in normalize_text(skill) for skill in skills):
                weight += 3
            if normalize_text(keyword) in normalized_title:
                weight += 4

        weights[category] = weight

    for category in selected:
        weights.setdefault(category, 1)

    return sorted(selected), weights


def question_categories(question: QuestionBankQuestion) -> set[str]:
    # Use all available classification fields, not only role/technology.
    source = " ".join(
        str(value or "")
        for value in (
            question.category,
            question.topic,
            question.subtopic,
            question.technology,
            question.role,
        )
    )

    normalized = normalize_text(source)
    categories = set()

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(normalize_text(k) in normalized for k in keywords):
            categories.add(category)

    for role, role_categories in ROLE_CATEGORIES.items():
        if normalize_text(role.replace("_", " ")) in normalized:
            categories.update(role_categories)

    return categories


# ============================================================
# DIFFICULTY DISTRIBUTION
# ============================================================

def normalize_distribution(
    distribution: dict[str, Any] | None,
    total: int,
) -> dict[str, int]:
    if not 1 <= total <= MAX_QUESTION_COUNT:
        raise ValueError(
            f"Question count must be between 1 and {MAX_QUESTION_COUNT}."
        )

    distribution = distribution or DEFAULT_DIFFICULTY_DISTRIBUTION
    values = {}

    for difficulty in ("easy", "medium", "hard"):
        try:
            value = float(distribution.get(difficulty, 0))
        except (TypeError, ValueError):
            raise ValueError("Difficulty distribution must contain valid numbers.")

        if not (0 <= value <= 100):
            raise ValueError("Difficulty percentages must be between 0 and 100.")

        values[difficulty] = value

    if round(sum(values.values()), 5) != 100:
        raise ValueError("Difficulty distribution must total 100%.")

    raw = {key: total * value / 100 for key, value in values.items()}
    counts = {key: int(value) for key, value in raw.items()}
    remaining = total - sum(counts.values())

    order = sorted(raw, key=lambda key: raw[key] - counts[key], reverse=True)
    for key in order[:remaining]:
        counts[key] += 1

    return counts


# ============================================================
# QUESTION SELECTION
# ============================================================

def _valid_bank_question(question: QuestionBankQuestion) -> dict[str, Any] | None:
    if not question.is_active:
        return None

    difficulty = str(question.difficulty or "").casefold()
    if difficulty not in ("easy", "medium", "hard"):
        return None

    options = normalize_options(question.options)
    if not 2 <= len(options) <= 5:
        return None

    normalized_options = [x.strip().casefold() for x in options]
    if len(set(normalized_options)) != len(options):
        return None

    prompt = str(question.question or "").strip()
    if not prompt:
        return None

    try:
        correct_index = get_correct_index(question.correct_option, options)
    except ValueError:
        return None

    marks = _safe_float(question.marks or 1, "Question marks")
    if marks <= 0:
        return None

    categories = question_categories(question)

    return {
        "bank_id": question.id,
        "category": str(question.category or (sorted(categories)[0] if categories else "general")),
        "topic": str(question.topic or question.subtopic or question.role or "General"),
        "subtopic": str(question.subtopic or ""),
        "technology": str(question.technology or ""),
        "difficulty": difficulty,
        "prompt": prompt,
        "options": options,
        "correct_index": correct_index,
        "explanation": str(question.explanation or ""),
        "marks": marks,
        "_categories": categories,
    }


def select_configured_questions(
    bank_questions: list[QuestionBankQuestion],
    total: int,
    distribution: dict[str, Any] | None = None,
    categories: list[str] | None = None,
    technology: str | None = None,
    topic: str | None = None,
    randomize: bool = True,
    question_ids: list[Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:

    required = normalize_distribution(distribution, total)
    requested_categories = {normalize_text(x) for x in (categories or [])}
    requested_ids = [str(as_uuid(value)) for value in (question_ids or [])]

    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("Duplicate question IDs are not allowed.")
    if requested_ids and len(requested_ids) != total:
        raise ValueError("Select exactly the configured number of questions.")

    # Filter first; deduplicate only eligible questions.
    eligible = []
    seen = set()

    for question in bank_questions:
        item = _valid_bank_question(question)
        if not item:
            continue

        if requested_categories:
            available = {normalize_text(x) for x in item["_categories"]}
            available.add(normalize_text(item["category"]))
            if not available.intersection(requested_categories):
                continue

        if technology and normalize_text(technology) not in normalize_text(item["technology"]):
            continue

        topic_text = " ".join(
            (item["topic"], item["subtopic"], item["technology"], item["category"])
        )
        if topic and normalize_text(topic) not in normalize_text(topic_text):
            continue

        identity = normalize_text(item["prompt"])
        if identity in seen:
            continue

        seen.add(identity)
        item.pop("_categories", None)
        eligible.append(item)

    if requested_ids:
        eligible_by_id = {str(item["bank_id"]): item for item in eligible}
        missing_ids = [item for item in requested_ids if item not in eligible_by_id]
        if missing_ids:
            raise ValueError(
                "A selected question is unavailable or does not match the assessment filters."
            )
        selected = [eligible_by_id[item] for item in requested_ids]
        actual = {
            difficulty: sum(
                question["difficulty"] == difficulty for question in selected
            )
            for difficulty in ("easy", "medium", "hard")
        }
        if actual != required:
            raise ValueError(
                "Manually selected questions must match the configured difficulty distribution."
            )
        if randomize:
            random.shuffle(selected)
        return selected, None

    selected = []
    shortages = {}

    for difficulty, needed in required.items():
        pool = [x for x in eligible if x["difficulty"] == difficulty]

        if len(pool) < needed:
            shortages[difficulty] = {
                "required": needed,
                "available": len(pool),
            }
            continue

        chosen = random.sample(pool, needed) if randomize else pool[:needed]
        selected.extend(chosen)

    if shortages:
        return [], {
            "shortages": shortages,
            "required_total": total,
            "available_total": len(eligible),
        }

    if randomize:
        random.shuffle(selected)

    return selected, None


def select_assessment_questions(
    job: dict[str, Any],
    bank_questions: list[QuestionBankQuestion],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:

    categories, weights = relevant_categories(job)
    eligible = []
    seen = set()

    for question in bank_questions:
        item = _valid_bank_question(question)
        if not item:
            continue

        matched = item["_categories"].intersection(categories)
        if not matched:
            continue

        identity = normalize_text(item["prompt"])
        if identity in seen:
            continue

        seen.add(identity)
        item["category"] = sorted(matched)[0]
        item.pop("_categories", None)
        eligible.append(item)

    required = {"easy": 10, "medium": 15, "hard": 5}
    selected = []
    shortages = {}

    for difficulty, needed in required.items():
        pool = [x for x in eligible if x["difficulty"] == difficulty]

        if len(pool) < needed:
            shortages[difficulty] = {
                "required": needed,
                "available": len(pool),
            }
            continue

        chosen = []
        while pool and len(chosen) < needed:
            chosen_item = random.choices(
                pool,
                weights=[max(1, weights.get(x["category"], 1)) for x in pool],
                k=1,
            )[0]
            chosen.append(chosen_item)
            pool.remove(chosen_item)

        selected.extend(chosen)

    if shortages:
        return [], {
            "categories": categories,
            "shortages": shortages,
            "required_total": 30,
            "available_total": len(eligible),
        }

    random.shuffle(selected)
    return selected, None


# ============================================================
# EVALUATION
# ============================================================

def evaluate_assessment(
    questions: list[dict[str, Any]],
    answer_key: dict[str, dict[str, Any]],
    answers: dict[str, int],
    passing_marks: float | None = None,
) -> dict[str, Any]:

    earned = 0.0
    maximum = 0.0
    correct = 0
    incorrect = 0
    topic_results = {}
    difficulty_results = {}

    for question in questions:
        question_id = str(question["question_id"])
        key = answer_key.get(question_id)

        if not key:
            raise ValueError(f"Answer key missing for question {question_id}.")

        marks = _safe_float(key.get("marks", question.get("marks", 1)), "Question marks")
        if marks <= 0:
            raise ValueError("Question marks must be greater than zero.")

        maximum += marks
        selected = answers.get(question_id)
        is_correct = selected == key.get("correct_index")

        if selected is None:
            outcome = "unanswered"
        elif is_correct:
            outcome = "correct"
            correct += 1
            earned += marks
        else:
            outcome = "incorrect"
            incorrect += 1

        for result, name in (
            (topic_results, key.get("topic", "General")),
            (difficulty_results, key.get("difficulty", "unknown")),
        ):
            stats = result.setdefault(
                name,
                {"correct": 0, "incorrect": 0, "unanswered": 0, "total": 0},
            )
            stats[outcome] += 1
            stats["total"] += 1

    unanswered = len(questions) - correct - incorrect
    percentage = round(earned * 100 / maximum, 2) if maximum else 0

    required_marks = (
        _safe_float(passing_marks, "Passing marks")
        if passing_marks is not None
        else maximum * PASSING_SCORE / 100
    )

    if not 0 <= required_marks <= maximum:
        raise ValueError("Passing marks are outside the valid range.")

    def summarize(results):
        return {
            name: {
                **stats,
                "percentage": round(stats["correct"] * 100 / stats["total"], 2)
                if stats["total"] else 0,
            }
            for name, stats in sorted(results.items())
        }

    topics = summarize(topic_results)
    difficulties = summarize(difficulty_results)

    strong = [name for name, stats in topics.items() if stats["percentage"] >= PASSING_SCORE]
    weak = [name for name, stats in topics.items() if stats["percentage"] < PASSING_SCORE]

    report = {
        "summary": (
            "Strong, consistent performance across the assessed topics."
            if strong and not weak
            else "Good progress on several topics, with focused practice needed in weaker areas."
            if strong
            else "This attempt shows foundational areas to strengthen before the next assessment."
        ),
        "strong_skills": strong,
        "weak_areas": weak,
        "topic_performance": topics,
        "difficulty_performance": difficulties,
        "improvement_suggestions": [
            f"Review {name} and practice applying it to short, realistic problems."
            for name in weak
        ] or ["Continue practicing mixed-difficulty problems to retain these skills."],
        "recommended_learning_topics": weak or strong,
        "report_source": "deterministic_template",
    }

    return {
        "correct_count": correct,
        "incorrect_count": incorrect,
        "unanswered_count": unanswered,
        "total_questions": len(questions),
        "earned_marks": round(earned, 2),
        "total_marks": round(maximum, 2),
        "passing_marks": round(required_marks, 2),
        "percentage": percentage,
        "result": "pass" if earned >= required_marks else "fail",
        "second_round_eligible": earned >= required_marks,
        "performance_report": report,
    }


# ============================================================
# SERIALIZATION
# ============================================================

def candidate_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": question["question_id"],
        "category": question.get("category"),
        "topic": question.get("topic"),
        "difficulty": question.get("difficulty"),
        "prompt": question["prompt"],
        "options": question["options"],
        "marks": question.get("marks", 1),
    }


def serialize_pg_assessment(model: Any) -> dict[str, Any]:
    if model is None:
        return {}

    extra = dict(model.extra_data or {})
    extra.pop("answer_key", None)
    percentage = extra.get("percentage")
    if percentage is None:
        percentage = model.score

    # Never allow JSON extra_data to overwrite authoritative DB fields.
    result = {
        "_id": str(model.id),
        "id": str(model.id),
        "application_id": str(model.application_id) if model.application_id else None,
        "candidate_id": str(model.candidate_id) if model.candidate_id else None,
        "recruiter_id": str(model.recruiter_id) if model.recruiter_id else None,
        "job_id": str(model.job_id) if model.job_id else None,
        "title": model.title,
        "status": model.status,
        "total_questions": model.total_questions,
        "question_count": model.total_questions,
        "total_marks": model.total_marks,
        "passing_marks": model.passing_marks,
        "duration_minutes": model.duration_minutes,
        "time_limit_minutes": model.duration_minutes,
        "passing_percentage": model.passing_percentage,
        "score": model.score,
        "percentage": percentage,
        "started_at": model.started_at,
        "expires_at": model.expires_at,
        "deadline_at": model.expires_at,
        "submitted_at": model.submitted_at,
        "published_at": model.published_at,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }

    # Do not expose internal answer keys.
    for key, value in extra.items():
        if key != "answer_key":
            result[key] = _json_safe(value)

    # Reassert authoritative fields after extra-data merge.
    result.update({
        "_id": str(model.id),
        "id": str(model.id),
        "application_id": str(model.application_id) if model.application_id else None,
        "candidate_id": str(model.candidate_id) if model.candidate_id else None,
        "recruiter_id": str(model.recruiter_id) if model.recruiter_id else None,
        "job_id": str(model.job_id) if model.job_id else None,
        "title": model.title,
        "status": model.status,
        "total_questions": model.total_questions,
        "question_count": model.total_questions,
        "total_marks": model.total_marks,
        "passing_marks": model.passing_marks,
        "duration_minutes": model.duration_minutes,
        "time_limit_minutes": model.duration_minutes,
        "passing_percentage": model.passing_percentage,
        "score": model.score,
        "percentage": percentage,
        "started_at": model.started_at,
        "expires_at": model.expires_at,
        "deadline_at": model.expires_at,
        "submitted_at": model.submitted_at,
        "published_at": model.published_at,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "answer_key": None,
    })

    return result


def serialize_assessment(
    assessment: dict[str, Any],
    include_questions: bool = False,
) -> dict[str, Any]:

    safe = {
        key: value
        for key, value in assessment.items()
        if key not in {"_id", "answer_key"}
    }

    safe["id"] = str(assessment.get("_id") or assessment.get("id"))

    for field in ("candidate_id", "application_id", "job_id", "recruiter_id"):
        if safe.get(field) is not None:
            safe[field] = str(safe[field])

    if include_questions:
        safe["questions"] = [
            candidate_question(q)
            for q in assessment.get("questions", [])
        ]
        safe["answers"] = dict(assessment.get("answers") or {})
    else:
        safe.pop("questions", None)
        safe.pop("answers", None)

    return safe


# ============================================================
# QUESTION BANK
# ============================================================

async def _get_bank_questions(
    database: AsyncSession,
    recruiter_id: UUID,
) -> list[QuestionBankQuestion]:

    result = await database.scalars(
        select(QuestionBankQuestion)
        .where(
            QuestionBankQuestion.is_active.is_(True),
            or_(
                QuestionBankQuestion.recruiter_id == recruiter_id,
                QuestionBankQuestion.recruiter_id.is_(None),
            ),
        )
        .order_by(QuestionBankQuestion.created_at.desc())
    )
    return list(result.all())


# ============================================================
# SNAPSHOT BUILDING
# ============================================================

def _build_assessment_snapshot(
    selected: list[dict[str, Any]],
    marks_per_question: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:

    questions = []
    answer_key = {}

    for item in selected:
        question_id = str(uuid4())
        marks = _safe_float(item.get("marks", marks_per_question), "Question marks")

        if marks <= 0:
            raise ValueError("Question marks must be greater than zero.")

        snapshot = {
            "question_id": question_id,
            "category": item.get("category", "general"),
            "topic": item.get("topic", "General"),
            "difficulty": item["difficulty"],
            "prompt": item["prompt"],
            "options": list(item["options"]),
            "marks": marks,
        }

        questions.append(snapshot)
        answer_key[question_id] = {
            "correct_index": int(item["correct_index"]),
            "topic": snapshot["topic"],
            "difficulty": snapshot["difficulty"],
            "explanation": item.get("explanation", ""),
            "marks": marks,
        }

    return questions, answer_key


def _question_orm_rows(
    assessment_id: UUID,
    selected: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> tuple[list[AssessmentQuestion], list[AssessmentAnswerKey]]:

    question_rows = []
    key_rows = []

    for item, snapshot in zip(selected, questions):
        question_uuid = as_uuid(snapshot["question_id"])
        marks = float(snapshot.get("marks", item.get("marks", 1)))

        question_rows.append(
            AssessmentQuestion(
                id=question_uuid,
                assessment_id=assessment_id,
                question_bank_id=item.get("bank_id"),
                question_text=item["prompt"],
                options=list(item["options"]),
                difficulty=item["difficulty"],
                order_number=len(question_rows) + 1,
                marks=marks,
            )
        )

        key_rows.append(
            AssessmentAnswerKey(
                assessment_question_id=question_uuid,
                correct_option=chr(65 + int(item["correct_index"])),
                explanation=item.get("explanation", ""),
            )
        )

    return question_rows, key_rows


async def _ensure_assessment_question_rows(
    database: AsyncSession,
    model: PGAssessment,
    extra: dict[str, Any],
    questions: list[dict[str, Any]],
    answer_key: dict[str, dict[str, Any]],
) -> tuple[list[AssessmentQuestion], dict[str, str]]:
    """Create normalized question rows for legacy assignments that only have snapshots."""
    existing_rows = list((await database.scalars(
        select(AssessmentQuestion).where(
            AssessmentQuestion.assessment_id == model.id
        )
    )).all())
    existing_by_id = {str(row.id): row for row in existing_rows}
    used_order_numbers = {row.order_number for row in existing_rows}
    id_map = {}
    new_questions = []
    new_keys = []

    for index, snapshot in enumerate(questions):
        old_id = str(snapshot.get("question_id") or "")
        existing = existing_by_id.get(old_id)
        if existing:
            id_map[old_id] = old_id
            continue

        key = answer_key.get(old_id)
        if not key:
            raise RuntimeError("Answer key is missing for an assessment question.")
        options = list(snapshot.get("options") or [])
        try:
            correct_index = int(key["correct_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Assessment answer key is invalid.") from exc
        if not 0 <= correct_index < len(options):
            raise RuntimeError("Assessment answer key is outside the question options.")

        new_id = str(uuid4())
        id_map[old_id] = new_id
        snapshot["question_id"] = new_id
        order_number = index + 1
        while order_number in used_order_numbers:
            order_number += 1
        used_order_numbers.add(order_number)
        new_questions.append(AssessmentQuestion(
            id=UUID(new_id),
            assessment_id=model.id,
            question_bank_id=None,
            question_text=str(snapshot.get("prompt") or ""),
            options=options,
            difficulty=str(snapshot.get("difficulty") or "medium"),
            order_number=order_number,
            marks=float(snapshot.get("marks", 1)),
        ))
        new_keys.append(AssessmentAnswerKey(
            assessment_question_id=UUID(new_id),
            correct_option=chr(65 + correct_index),
            explanation=str(key.get("explanation") or ""),
        ))

    if new_questions:
        remapped_keys = {
            id_map.get(str(question_id), str(question_id)): value
            for question_id, value in answer_key.items()
        }
        remapped_answers = {
            id_map.get(str(question_id), str(question_id)): value
            for question_id, value in (extra.get("answers") or {}).items()
        }
        extra["questions"] = questions
        extra["answer_key"] = remapped_keys
        extra["answers"] = remapped_answers
        model.extra_data = extra
        database.add_all(new_questions)
        await database.flush()
        database.add_all(new_keys)
        await database.flush()
        existing_rows.extend(new_questions)

    return existing_rows, id_map


# ============================================================
# CREATE RECRUITER DRAFT
# ============================================================

async def create_assessment_draft(
    database: AsyncSession,
    recruiter_id: Any,
    job_id: Any,
    title: str,
    question_count: int,
    duration_minutes: int,
    passing_marks: float,
    difficulty_distribution: dict[str, Any] | None = None,
    categories: list[str] | None = None,
    technology: str | None = None,
    topic: str | None = None,
    marks_per_question: float = 1.0,
    randomize: bool = True,
    question_ids: list[Any] | None = None,
    generated_questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:

    recruiter_uuid = as_uuid(recruiter_id)
    job_uuid = as_uuid(job_id)

    if not title or not title.strip():
        raise ValueError("Assessment title is required.")

    if not 1 <= question_count <= MAX_QUESTION_COUNT:
        raise ValueError(
            f"Question count must be between 1 and {MAX_QUESTION_COUNT}."
        )

    if not 1 <= duration_minutes <= 240:
        raise ValueError("Duration must be between 1 and 240 minutes.")

    marks_per_question = _safe_float(marks_per_question, "Marks per question")
    if marks_per_question <= 0:
        raise ValueError("Marks per question must be positive.")

    job = await database.scalar(
        select(PGJob).where(
            PGJob.id == job_uuid,
            PGJob.recruiter_id == recruiter_uuid,
        )
    )
    if not job:
        raise ValueError("Job not found or not owned by this recruiter.")

    if generated_questions is not None:
        required = normalize_distribution(difficulty_distribution, question_count)
        if len(generated_questions) != question_count:
            raise ValueError("AI must generate exactly the configured number of questions.")
        selected = []
        for item in generated_questions:
            options = [str(option).strip() for option in item.get("options", [])]
            correct_index = int(item.get("correct_index", -1))
            if len(options) != 4 or any(not option for option in options) or len({option.casefold() for option in options}) != 4 or not 0 <= correct_index < 4:
                raise ValueError("AI generated a question with invalid answer options.")
            selected.append({
                "bank_id": None,
                "category": item.get("category") or "AI generated",
                "topic": item.get("topic") or "Role skills",
                "difficulty": item.get("difficulty"),
                "prompt": item.get("question", "").strip(),
                "options": options,
                "correct_index": correct_index,
                "explanation": item.get("explanation", ""),
                "marks": marks_per_question,
            })
        actual = {level: sum(item["difficulty"] == level for item in selected) for level in ("easy", "medium", "hard")}
        if actual != required:
            raise ValueError("AI-generated question difficulty counts do not match the requested distribution.")
        if randomize:
            random.shuffle(selected)
    else:
        bank = await _get_bank_questions(database, recruiter_uuid)
        selected, shortage = select_configured_questions(
            bank,
            question_count,
            difficulty_distribution,
            categories,
            technology,
            topic,
            randomize,
            question_ids,
        )
        if shortage:
            raise ValueError(f"Question bank shortage: {shortage}")

    for item in selected:
        item["marks"] = marks_per_question

    questions, answer_key = _build_assessment_snapshot(selected, marks_per_question)
    total_marks = sum(float(q["marks"]) for q in questions)

    passing_marks = _safe_float(passing_marks, "Passing marks")
    if not 0 <= passing_marks <= total_marks:
        raise ValueError("Passing marks must be between zero and total marks.")

    assessment_id = uuid4()
    now = utcnow()
    question_rows, key_rows = _question_orm_rows(assessment_id, selected, questions)

    model = PGAssessment(
        id=assessment_id,
        application_id=None,
        candidate_id=None,
        recruiter_id=recruiter_uuid,
        job_id=job_uuid,
        title=title.strip(),
        status="draft",
        total_questions=len(questions),
        total_marks=total_marks,
        passing_marks=passing_marks,
        duration_minutes=duration_minutes,
        passing_percentage=passing_marks / total_marks * 100 if total_marks else 0,
        published_at=None,
        extra_data={
            "job_title": job.title or "",
            "questions": questions,
            "answer_key": answer_key,
            "answers": {},
            "difficulty_distribution": difficulty_distribution or DEFAULT_DIFFICULTY_DISTRIBUTION,
            "categories": categories or [],
            "technology": technology,
            "topic": topic,
            "attempt_count": 0,
            "randomize": bool(randomize),
            "template_assessment_id": str(assessment_id),
        },
        created_at=now,
        updated_at=now,
    )

    try:
        database.add(model)
        database.add_all(question_rows)
        await database.flush()
        database.add_all(key_rows)
        await database.commit()
        await database.refresh(model)
    except Exception:
        await database.rollback()
        raise

    return serialize_pg_assessment(model)


# ============================================================
# PUBLISH DRAFT
# ============================================================

async def publish_assessment_draft(
    database: AsyncSession,
    assessment_id: Any,
    recruiter_id: Any,
) -> dict[str, Any]:

    model = await database.scalar(
        select(PGAssessment)
        .where(
            PGAssessment.id == as_uuid(assessment_id),
            PGAssessment.recruiter_id == as_uuid(recruiter_id),
        )
        .with_for_update()
    )

    if not model:
        raise ValueError("Assessment not found.")

    if model.status != "draft":
        raise ValueError("Only draft assessments can be published.")

    extra = dict(model.extra_data or {})
    questions = extra.get("questions") or []
    answer_key = extra.get("answer_key") or {}

    if not questions or len(questions) != model.total_questions:
        raise ValueError("Assessment questions are incomplete.")

    if len(answer_key) != len(questions):
        raise ValueError("Assessment answer key is incomplete.")

    question_ids = set()

    for question in questions:
        question_id = str(question.get("question_id"))
        if question_id in question_ids:
            raise ValueError("Duplicate question IDs found.")
        question_ids.add(question_id)

        key = answer_key.get(question_id)
        if not key:
            raise ValueError("An assessment question has no answer key.")

        if not str(question.get("prompt") or "").strip():
            raise ValueError("Assessment contains an empty question.")

        options = question.get("options") or []
        if not 2 <= len(options) <= 5:
            raise ValueError("Every question must have 2 to 5 options.")

        correct_index = key.get("correct_index")
        if (
            not isinstance(correct_index, int)
            or isinstance(correct_index, bool)
            or not 0 <= correct_index < len(options)
        ):
            raise ValueError("Assessment contains an invalid correct answer.")

    db_questions = (
        await database.scalars(
            select(AssessmentQuestion).where(
                AssessmentQuestion.assessment_id == model.id
            )
        )
    ).all()

    if len(db_questions) != len(questions):
        raise ValueError("Assessment question records are incomplete.")

    db_keys = (
        await database.scalars(
            select(AssessmentAnswerKey).where(
                AssessmentAnswerKey.assessment_question_id.in_(
                    [q.id for q in db_questions]
                )
            )
        )
    ).all()

    if len(db_keys) != len(questions):
        raise ValueError("Assessment answer-key records are incomplete.")

    now = utcnow()
    model.published_at = now
    model.status = "published"
    model.updated_at = now

    try:
        await database.commit()
        await database.refresh(model)
    except Exception:
        await database.rollback()
        raise

    return serialize_pg_assessment(model)


# ============================================================
# ASSIGN PUBLISHED TEMPLATE TO SHORTLISTED CANDIDATES
# ============================================================

async def assign_assessment_to_candidates(
    database: AsyncSession,
    assessment_id: Any,
    recruiter_id: Any,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    recruiter_uuid = as_uuid(recruiter_id)

    source = await database.scalar(
        select(PGAssessment)
        .where(
            PGAssessment.id == as_uuid(assessment_id),
            PGAssessment.recruiter_id == recruiter_uuid,
        )
        .with_for_update()
    )

    if not source:
        raise ValueError("Assessment not found.")

    if source.status != "published" or source.candidate_id is not None:
        raise ValueError("Only a published recruiter template can be assigned.")

    if not candidates:
        raise ValueError("Select at least one candidate.")

    results = []
    now = utcnow()
    source_extra = dict(source.extra_data or {})

    if not source_extra.get("questions") or not source_extra.get("answer_key"):
        raise ValueError("Template questions or answer key are missing.")

    seen_applications = set()

    try:
        for candidate in candidates:
            candidate_id = as_uuid(candidate["candidate_id"])
            application_id = as_uuid(candidate["application_id"])

            if application_id in seen_applications:
                raise ValueError("Duplicate application IDs were supplied.")
            seen_applications.add(application_id)

            application = await database.scalar(
                select(Application)
                .where(
                    Application.id == application_id,
                    Application.candidate_id == candidate_id,
                    Application.job_id == source.job_id,
                    Application.recruiter_id == recruiter_uuid,
                )
                .with_for_update()
            )

            if not application:
                raise ValueError("Application not found or not owned by this recruiter.")

            if str(application.status).casefold() not in {"shortlisted", "shortlist"}:
                raise ValueError("Assessment can only be assigned to shortlisted candidates.")

            existing = await database.scalar(
                select(PGAssessment)
                .where(PGAssessment.application_id == application_id)
                .with_for_update()
            )

            if existing:
                existing_extra = dict(existing.extra_data or {})
                if (
                    existing.candidate_id == candidate_id
                    and existing.job_id == source.job_id
                    and existing.recruiter_id == recruiter_uuid
                    and existing_extra.get("template_assessment_id") == str(source.id)
                ):
                    results.append(existing)
                    continue

                raise ValueError(
                    "This application already has an assessment assigned from another template."
                )

            extra = dict(source_extra)
            extra.update({
                "answers": {},
                "attempt_count": 0,
                "template_assessment_id": str(source.id),
            })

            assigned = PGAssessment(
                id=uuid4(),
                application_id=application_id,
                candidate_id=candidate_id,
                recruiter_id=recruiter_uuid,
                job_id=source.job_id,
                title=source.title,
                status="assigned",
                total_questions=source.total_questions,
                total_marks=source.total_marks,
                passing_marks=source.passing_marks,
                duration_minutes=source.duration_minutes,
                passing_percentage=source.passing_percentage,
                published_at=source.published_at,
                extra_data=extra,
                created_at=now,
                updated_at=now,
            )

            database.add(assigned)
            await database.flush()
            await _ensure_assessment_question_rows(
                database,
                assigned,
                extra,
                extra["questions"],
                extra["answer_key"],
            )

            database.add(
                PGNotification(
                    user_id=candidate_id,
                    type="assessment_assigned",
                    message=(
                        f"You have been assigned {source.title} for "
                        f"{extra.get('job_title', 'a job')}. "
                        "Open your candidate dashboard to begin."
                    ),
                    related_id=assigned.id,
                    job_id=assigned.job_id,
                    is_read=False,
                    created_at=now,
                )
            )

            results.append(assigned)

        await database.commit()

        for item in results:
            await database.refresh(item)

    except IntegrityError as exc:
        await database.rollback()
        raise ValueError(
            "An application already has an assessment. Refresh and retry."
        ) from exc
    except Exception:
        await database.rollback()
        raise

    return [serialize_pg_assessment(item) for item in results]


# ============================================================
# LEGACY APPLICATION ASSESSMENT
# Disabled: recruiter-created template workflow is authoritative.
# ============================================================

async def create_assessment_for_application(
    database: AsyncSession,
    application: Any,
) -> tuple[dict[str, Any], bool]:

    raise ValueError(
        "Automatic assessment creation is disabled. "
        "Recruiters must create and publish an assessment template first."
    )


# ============================================================
# GET ASSESSMENT FOR AUTHENTICATED USER
# ============================================================

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

    role = user.get("role")

    if role == "candidate":
        conditions = [
            PGAssessment.id == assessment_uuid,
            PGAssessment.candidate_id == user_uuid,
        ]
    elif role == "recruiter":
        conditions = [
            PGAssessment.id == assessment_uuid,
            PGAssessment.recruiter_id == user_uuid,
        ]
    else:
        return None

    model = await database.scalar(
        select(PGAssessment).where(*conditions)
    )

    return serialize_pg_assessment(model) if model else None


# ============================================================
# SAVE CANDIDATE ANSWERS
# ============================================================

async def save_assessment_answers(
    database: AsyncSession,
    assessment_id: Any,
    candidate_id: Any,
    answers: dict[str, int],
) -> dict[str, Any]:

    model = await database.scalar(
        select(PGAssessment)
        .where(
            PGAssessment.id == as_uuid(assessment_id),
            PGAssessment.candidate_id == as_uuid(candidate_id),
        )
        .with_for_update()
    )

    if not model:
        raise ValueError("Assessment not found.")

    if model.status != "in_progress":
        raise ValueError("Assessment is not in progress.")

    now = utcnow()
    deadline = _normalize_datetime(model.expires_at)

    if not deadline or now >= deadline:
        raise ValueError("Assessment time has expired.")

    extra = dict(model.extra_data or {})
    questions = extra.get("questions") or []
    existing_answers = dict(extra.get("answers") or {})

    lookup = {
        str(q["question_id"]): len(q.get("options") or [])
        for q in questions
    }

    normalized_updates = {}

    for question_id, selected in (answers or {}).items():
        question_id = str(question_id)

        if question_id not in lookup:
            raise ValueError("An answer references an invalid question.")

        if isinstance(selected, bool) or not isinstance(selected, int):
            raise ValueError("Answer option must be an integer index.")

        if not 0 <= selected < lookup[question_id]:
            raise ValueError("Answer option index is out of range.")

        normalized_updates[question_id] = selected

    existing_answers.update(normalized_updates)
    extra["answers"] = existing_answers
    extra["last_saved_at"] = now.isoformat()

    model.extra_data = extra
    model.updated_at = now

    question_models = (
        await database.scalars(
            select(AssessmentQuestion).where(
                AssessmentQuestion.assessment_id == model.id
            )
        )
    ).all()

    question_lookup = {str(q.id): q for q in question_models}

    for question_id, selected_index in normalized_updates.items():
        question_model = question_lookup.get(question_id)
        if not question_model:
            raise ValueError("Assessment question record is missing.")

        selected_label = chr(65 + selected_index)

        answer_record = await database.scalar(
            select(AssessmentAnswer).where(
                AssessmentAnswer.assessment_question_id == question_model.id
            )
        )

        if answer_record is None:
            answer_record = AssessmentAnswer(
                assessment_id=model.id,
                assessment_question_id=question_model.id,
            )

        answer_record.selected_option = selected_label
        answer_record.answered_at = now
        database.add(answer_record)

    try:
        await database.commit()
        await database.refresh(model)
    except Exception:
        await database.rollback()
        raise

    return serialize_pg_assessment(model)


# ============================================================
# SUBMIT AND EVALUATE ASSESSMENT
# ============================================================

async def publish_assessment_result(
    database: AsyncSession,
    assessment: dict[str, Any],
    answers: dict[str, int],
) -> dict[str, Any]:

    assessment_id = assessment.get("id") or assessment.get("_id")

    model = await database.scalar(
        select(PGAssessment)
        .where(PGAssessment.id == as_uuid(assessment_id))
        .with_for_update()
    )

    if not model:
        raise RuntimeError("Assessment was not found.")

    if model.status in {"submitted", "passed", "failed", "expired"}:
        return serialize_pg_assessment(model)

    if model.status != "in_progress":
        raise RuntimeError("Assessment is not in progress.")

    extra = dict(model.extra_data or {})
    answer_key = extra.get("answer_key") or {}
    questions = extra.get("questions") or []

    if not answer_key or not questions:
        raise RuntimeError("Assessment questions or answer key are unavailable.")

    question_models, question_id_map = await _ensure_assessment_question_rows(
        database,
        model,
        extra,
        questions,
        answer_key,
    )
    answer_key = extra.get("answer_key") or answer_key

    now = utcnow()
    deadline = _normalize_datetime(model.expires_at)

    # After deadline, only previously saved answers are accepted.
    if deadline and now >= deadline:
        submitted_answers = dict(extra.get("answers") or {})
    else:
        submitted_answers = dict(extra.get("answers") or {})

        normalized_answers = {
            question_id_map.get(str(question_id), str(question_id)): selected
            for question_id, selected in (answers or {}).items()
        }
        for question_id, selected in normalized_answers.items():

            question = next(
                (q for q in questions if str(q["question_id"]) == question_id),
                None,
            )

            if not question:
                raise ValueError("Submission contains an invalid question ID.")

            if isinstance(selected, bool) or not isinstance(selected, int):
                raise ValueError("Submitted answer must be an integer index.")

            if not 0 <= selected < len(question.get("options") or []):
                raise ValueError("Submitted answer index is out of range.")

            submitted_answers[question_id] = selected

    evaluation = evaluate_assessment(
        questions,
        answer_key,
        submitted_answers,
        model.passing_marks,
    )

    question_lookup = {str(q.id): q for q in question_models}

    for snapshot in questions:
        question_id = str(snapshot["question_id"])
        question_model = question_lookup.get(question_id)

        if not question_model:
            raise RuntimeError("Assessment question record is missing.")

        selected_index = submitted_answers.get(question_id)
        key = answer_key.get(question_id)

        if not key:
            raise RuntimeError("Answer key is missing for a question.")

        answer_record = await database.scalar(
            select(AssessmentAnswer).where(
                AssessmentAnswer.assessment_question_id == question_model.id
            )
        )

        if answer_record is None:
            answer_record = AssessmentAnswer(
                assessment_id=model.id,
                assessment_question_id=question_model.id,
            )

        answer_record.selected_option = (
            chr(65 + selected_index) if selected_index is not None else None
        )
        answer_record.is_correct = (
            selected_index == key["correct_index"]
            if selected_index is not None else None
        )

        # Unanswered questions must not receive an answer timestamp.
        if selected_index is not None and answer_record.answered_at is None:
            answer_record.answered_at = now

        database.add(answer_record)

    final_status = "passed" if evaluation["result"] == "pass" else "failed"

    model.status = final_status
    model.score = float(evaluation["percentage"])
    model.submitted_at = now
    model.updated_at = now

    extra.update(evaluation)
    extra["answers"] = submitted_answers
    extra["status"] = final_status
    extra["submitted_at"] = now.isoformat()
    model.extra_data = extra

    proctoring_session = await database.scalar(
        select(ProctoringSession)
        .where(ProctoringSession.assessment_id == model.id)
        .with_for_update()
    )
    if proctoring_session is not None:
        proctoring_session.status = "completed"
        proctoring_session.ended_at = now
        proctoring_session.updated_at = now

    if model.candidate_id:
        job = await database.scalar(
            select(PGJob).where(PGJob.id == model.job_id)
        )
        job_title = job.title if job else "your assessment"

        database.add(
            PGNotification(
                user_id=model.candidate_id,
                type="assessment_result_published",
                message=(
                    f"Your assessment for {job_title} is complete: "
                    f"{evaluation['earned_marks']}/{evaluation['total_marks']} marks "
                    f"({evaluation['percentage']}%). Result: {final_status.upper()}."
                ),
                related_id=model.id,
                job_id=model.job_id,
                is_read=False,
                created_at=now,
            )
        )

    try:
        await database.commit()
        await database.refresh(model)
    except Exception:
        await database.rollback()
        raise

    return serialize_pg_assessment(model)


# ============================================================
# AUTO-COMPLETE EXPIRED ASSESSMENT
# ============================================================

async def complete_if_expired(
    database: AsyncSession,
    assessment: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:

    now = now or utcnow()
    deadline = _normalize_datetime(
        assessment.get("deadline_at") or assessment.get("expires_at")
    )

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


# ============================================================
# DEADLINE HELPER
# ============================================================

def deadline_after(
    minutes: int,
    now: datetime | None = None,
) -> datetime:

    if minutes < 1:
        raise ValueError("Assessment duration must be positive.")

    return (now or utcnow()) + timedelta(minutes=minutes)
