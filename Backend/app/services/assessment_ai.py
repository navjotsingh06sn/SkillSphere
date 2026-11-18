"""Optional OpenAI-compatible assessment question generator.

No provider is contacted until an administrator configures a base URL and API key.
"""

import asyncio
from collections import Counter
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings


class AssessmentAIError(RuntimeError):
    pass


def _request_questions(context: dict, count: int, required_difficulties: list[str]) -> list[dict]:
    payload = {
        "model": settings.assessment_ai_model,
        "temperature": 0.4,
        "max_completion_tokens": min(12000, max(1500, count * 250)),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": (
                "Create a fair first-round job assessment. Return JSON with one key "
        "questions: up to the requested number of MCQs, and never more. "
                "If you cannot fit all questions, return as many complete questions as possible. "
        "Each question object must have question (string), options (array of exactly "
        "four strings), correct_option (one letter A/B/C/D), difficulty (easy/medium/hard), "
        "topic (string), and explanation (string). Do not omit any required field. The user message "
                "contains required_difficulties_in_order: question at each array index "
                "must use that exact difficulty. Ground questions in the role, avoid "
                "duplicates and trivia, and use one defensible answer."
            )},
            {"role": "user", "content": json.dumps({"count": count, **context})},
        ],
    }
    request = Request(
        f"{settings.assessment_ai_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.assessment_ai_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SkillSphere/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.assessment_ai_timeout_seconds) as response:
            provider_result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            error_body = json.loads(exc.read(4000).decode("utf-8", "replace"))
            provider_error = error_body.get("error", {})
            provider_message = provider_error.get("message") if isinstance(provider_error, dict) else None
            provider_code = provider_error.get("code") if isinstance(provider_error, dict) else None
        except (ValueError, OSError):
            provider_message = None
            provider_code = None
        explanation = f": {provider_message}" if provider_message else ". Check the configured AI service."
        code = f" [{provider_code}]" if provider_code else ""
        raise AssessmentAIError(f"AI provider returned an error ({exc.code}){code}{explanation}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AssessmentAIError("Could not reach the configured AI provider. Check its URL and try again.") from exc
    try:
        content = provider_result["choices"][0]["message"]["content"]
        decoded = json.loads(content)
        questions = decoded if isinstance(decoded, list) else decoded.get("questions", []) if isinstance(decoded, dict) else []
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise AssessmentAIError("The AI provider returned an unreadable question set. Please try again.") from exc
    if not isinstance(questions, list):
        raise AssessmentAIError("The AI provider returned an invalid number of questions. Please try again.")
    questions = questions[:count]
    normalized = []
    seen_questions = set()
    difficulty_aliases = {
        "beginner": "easy", "basic": "easy", "intermediate": "medium",
        "moderate": "medium", "advanced": "hard", "challenging": "hard",
    }
    for index, item in enumerate(questions):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("prompt") or "").strip()
        options = item.get("options")
        if isinstance(options, dict):
            options = [options[key] for key in ("A", "B", "C", "D") if key in options]
        if not isinstance(options, list):
            continue
        clean_options = [str(option).strip()[:2000] for option in options]
        if not question or len(clean_options) != 4 or any(not option for option in clean_options) or len({option.casefold() for option in clean_options}) != 4:
            continue
        raw_correct = item.get("correct_option", item.get("correct_answer", item.get("answer")))
        if isinstance(raw_correct, int) and not isinstance(raw_correct, bool) and 0 <= raw_correct < 4:
            correct_index = raw_correct
        else:
            correct_text = str(raw_correct or "").strip()
            correct_index = next((i for i, option in enumerate(clean_options) if option.casefold() == correct_text.casefold()), -1)
            if correct_index < 0:
                match = re.match(r"(?i)^\s*(?:(?:option|choice|answer)\s*)?([A-D])\b", correct_text)
                if match:
                    correct_index = ord(match.group(1).upper()) - 65
        if not 0 <= correct_index < 4:
            continue
        difficulty = str(item.get("difficulty") or "").strip().lower()
        difficulty = difficulty_aliases.get(difficulty, difficulty)
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = required_difficulties[index] if index < len(required_difficulties) else ""
        if difficulty not in {"easy", "medium", "hard"}:
            continue
        question_key = " ".join(question.casefold().split())
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)
        normalized.append({
            "question": question[:10000],
            "options": clean_options,
            "correct_option": chr(65 + correct_index),
            "difficulty": difficulty,
            "topic": str(item.get("topic") or context.get("domain") or "Role skills")[:150],
            "explanation": str(item.get("explanation") or "")[:2000],
        })
    return normalized


async def generate_assessment_questions(context: dict, count: int, required_difficulties: list[str]) -> list[dict]:
    if not settings.assessment_ai_base_url.strip() or not settings.assessment_ai_api_key.strip() or not settings.assessment_ai_model.strip():
        raise AssessmentAIError("AI question generation is not configured. Set ASSESSMENT_AI_BASE_URL, ASSESSMENT_AI_API_KEY, and ASSESSMENT_AI_MODEL in Backend/.env.")
    if len(required_difficulties) != count:
        raise AssessmentAIError("The requested difficulty mix does not match the question count.")
    target = Counter(required_difficulties)
    collected: dict[str, list[dict]] = {level: [] for level in ("easy", "medium", "hard")}
    seen = set()
    pending = list(required_difficulties)
    for _ in range(4):
        if not pending:
            break
        request_context = {
            **context,
            "difficulty_counts": dict(Counter(pending)),
            "required_difficulties_in_order": pending,
        }
        batch = await asyncio.to_thread(_request_questions, request_context, len(pending), pending)
        for item in batch:
            level = item["difficulty"]
            key = " ".join(item["question"].casefold().split())
            if level not in collected or len(collected[level]) >= target[level] or key in seen:
                continue
            collected[level].append(item)
            seen.add(key)
        pending = [level for level in ("easy", "medium", "hard") for _ in range(target[level] - len(collected[level]))]
    result = [item for level in ("easy", "medium", "hard") for item in collected[level]]
    if len(result) != count:
        raise AssessmentAIError(f"AI returned {len(result)} of {count} unique questions after retries. Try again or lower the question count.")
    return result
