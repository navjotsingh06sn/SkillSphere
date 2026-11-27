import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import AliasChoices, BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.dependencies import get_current_user, get_database, recruiter_required
from app.models import (
    Application, Interview, InterviewCodeSubmission, InterviewCodingProblem, Job,
    InterviewFeedback, InterviewRoomEvent, Notification, User,
)
from app.pg_utils import parse_uuid, serialize_model

router = APIRouter(prefix="/interviews", tags=["interview room"])
logger = logging.getLogger("uvicorn.error")

SUSPICIOUS_EVENTS = {
    "tab_hidden", "window_blur", "fullscreen_exited", "copy_attempt", "paste_attempt",
}
LANGUAGE_NAMES = {
    "python": "Python 3", "javascript": "JavaScript", "cpp": "C++", "java": "Java",
    "go": "Go", "c": "C", "csharp": "C#", "php": "PHP", "ruby": "Ruby",
    "rust": "Rust", "typescript": "TypeScript", "bash": "Bash",
}


class ProblemInput(BaseModel):
    question: str = Field(
        min_length=10,
        max_length=12000,
        validation_alias=AliasChoices("question", "prompt"),
    )
    allowed_languages: list[str] = Field(default_factory=lambda: ["python", "javascript"], min_length=1, max_length=12)
    time_limit_seconds: int = Field(default=1800, ge=60, le=7200)

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Question must contain at least 10 non-whitespace characters.")
        return value


class RunInput(BaseModel):
    language: str = Field(max_length=40)
    source_code: str = Field(min_length=1, max_length=30000)
    stdin: str = Field(default="", max_length=4000)
    final: bool = False


class EventInput(BaseModel):
    event_type: str = Field(max_length=50)
    occurred_at: datetime | None = None
    details: dict = Field(default_factory=dict)


class ConsentInput(BaseModel):
    accepted: bool


class FeedbackInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    strengths: str | None = Field(default=None, max_length=5000)
    improvement_areas: str | None = Field(default=None, max_length=5000)
    private_notes: str | None = Field(default=None, max_length=10000)
    recommendation: str = Field(pattern="^(strong_yes|yes|undecided|no)$")


class RoomHub:
    def __init__(self):
        self.rooms: dict[str, dict[WebSocket, dict]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, interview_id: str, websocket: WebSocket, participant: dict):
        await websocket.accept(subprotocol="skillsphere-room")
        async with self.lock:
            room = self.rooms.setdefault(interview_id, {})
            peers = list(room.values())
            room[websocket] = participant
        await websocket.send_json({"type": "room_state", "participants": [*peers, participant]})
        await self.broadcast(interview_id, {"type": "participant_joined", "participant": participant}, exclude=websocket)

    async def disconnect(self, interview_id: str, websocket: WebSocket):
        async with self.lock:
            room = self.rooms.get(interview_id, {})
            participant = room.pop(websocket, None)
            if not room:
                self.rooms.pop(interview_id, None)
        if participant:
            await self.broadcast(interview_id, {"type": "participant_left", "participant": participant})

    async def broadcast(self, interview_id: str, payload: dict, exclude: WebSocket | None = None):
        room = self.rooms.get(interview_id, {})
        dead = []
        for websocket in list(room):
            if websocket is exclude:
                continue
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            await self.disconnect(interview_id, websocket)


hub = RoomHub()


def _authorize(interview: Interview, user: dict) -> str:
    user_id = parse_uuid(user["id"], "user id")
    if user.get("role") == "candidate" and interview.candidate_id == user_id:
        return "candidate"
    if user.get("role") == "recruiter" and interview.recruiter_id == user_id:
        return "recruiter"
    raise HTTPException(status_code=404, detail="Interview was not found.")


async def _get_owned(db: AsyncSession, interview_id: str, user: dict):
    interview = await db.scalar(select(Interview).where(Interview.id == parse_uuid(interview_id, "interview id")))
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview was not found.")
    role = _authorize(interview, user)
    return interview, role


def _language_ids() -> dict[str, int]:
    try:
        raw = json.loads(settings.judge0_language_ids)
        return {str(key): int(value) for key, value in raw.items() if key in LANGUAGE_NAMES and int(value) > 0}
    except (ValueError, TypeError, AttributeError):
        logger.error("JUDGE0_LANGUAGE_IDS is invalid JSON; code execution is unavailable.")
        return {}


def _problem_title(question: str) -> str:
    first_line = next((line.strip() for line in question.splitlines() if line.strip()), "Live coding question")
    return first_line[:200]


def _question_payload(problem: InterviewCodingProblem) -> dict:
    return {
        "id": str(problem.id), "question": problem.prompt, "title": problem.title,
        "allowed_languages": problem.allowed_languages,
        "time_limit_seconds": problem.time_limit_seconds,
        "created_at": problem.created_at.isoformat() if problem.created_at else None,
    }


@router.get("/{interview_id}/room")
async def get_room(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    candidate = await db.get(User, interview.candidate_id)
    recruiter = await db.get(User, interview.recruiter_id)
    application = await db.get(Application, interview.application_id)
    job = await db.get(Job, interview.job_id)
    extra = dict(interview.extra_data or {})
    problems = (await db.scalars(select(InterviewCodingProblem).where(InterviewCodingProblem.interview_id == interview.id).order_by(InterviewCodingProblem.created_at.desc()))).all()
    feedback = await db.scalar(select(InterviewFeedback).where(InterviewFeedback.interview_id == interview.id))
    feedback_payload = serialize_model(feedback) if feedback else None
    if role == "candidate" and feedback_payload:
        feedback_payload.pop("private_notes", None)
    return {
        "id": str(interview.id), "status": interview.status, "scheduled_at": interview.scheduled_at.isoformat() if interview.scheduled_at else None,
        "room_started_at": interview.room_started_at.isoformat() if interview.room_started_at else None,
        "room_ended_at": interview.room_ended_at.isoformat() if interview.room_ended_at else None,
        "candidate_response": interview.candidate_response, "interview_type": interview.interview_type,
        "duration_minutes": extra.get("duration_minutes", 30), "job_title": (job.title if job else "Interview"),
        "active_coding_problem": extra.get("active_coding_problem"),
        "role": role, "candidate": {"id": str(candidate.id), "full_name": candidate.full_name} if candidate else None,
        "recruiter": {"id": str(recruiter.id), "full_name": recruiter.full_name} if recruiter else None,
        "application_id": str(application.id) if application else None,
        "candidate_room_consent": extra.get("candidate_room_consent", {"accepted": False}),
        "problems": [{"id": str(problem.id), "title": problem.title, "question": problem.prompt, "prompt": problem.prompt, "allowed_languages": problem.allowed_languages, "time_limit_seconds": problem.time_limit_seconds} for problem in problems],
        "language_ids": _language_ids(), "language_labels": LANGUAGE_NAMES, "feedback": feedback_payload,
    }


@router.post("/{interview_id}/room/consent")
async def record_candidate_consent(interview_id: str, data: ConsentInput, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only the candidate can provide room monitoring consent.")
    if not data.accepted:
        raise HTTPException(status_code=400, detail="Consent is required before joining the monitored interview room.")
    extra = dict(interview.extra_data or {})
    extra["candidate_room_consent"] = {"accepted": True, "at": datetime.now(timezone.utc).isoformat()}
    interview.extra_data = extra
    await db.commit()
    return {"accepted": True}


@router.post("/{interview_id}/room/ticket")
async def issue_room_ticket(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    if interview.status in {"cancelled", "completed"} or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="This interview room has ended.")
    if role == "candidate" and interview.candidate_response == "declined":
        raise HTTPException(status_code=403, detail="You declined this interview invitation and cannot join its room.")
    if role == "candidate" and not (interview.extra_data or {}).get("candidate_room_consent", {}).get("accepted"):
        raise HTTPException(status_code=403, detail="Accept the transparent monitoring notice before joining.")
    now = datetime.now(timezone.utc)
    ticket = jwt.encode({"sub": user["id"], "role": role, "iid": str(interview.id), "purpose": "interview_room", "iat": now, "exp": now + timedelta(seconds=max(30, min(settings.interview_room_ticket_seconds, 180)))}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return {"ticket": ticket, "expires_in": max(30, min(settings.interview_room_ticket_seconds, 180))}


@router.get("/{interview_id}/room/ice")
async def get_room_ice(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    servers = []
    stun_urls = [item.strip() for item in settings.interview_stun_urls.split(",") if item.strip()]
    if stun_urls:
        servers.append({"urls": stun_urls})
    turn_urls = [item.strip() for item in settings.interview_turn_urls.split(",") if item.strip()]
    if turn_urls and settings.interview_turn_shared_secret.strip():
        expires = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
        username = f"{expires}:{user['id']}"
        credential = base64.b64encode(hmac.new(settings.interview_turn_shared_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        servers.append({"urls": turn_urls, "username": username, "credential": credential})
    return {"ice_servers": servers, "turn_available": any("turn:" in url or "turns:" in url for url in turn_urls) and len(servers) > 1}


@router.post("/{interview_id}/room/start")
async def start_room(interview_id: str, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    if interview.status not in {"scheduled", "in_progress"} or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="This interview cannot be started.")
    now = datetime.now(timezone.utc)
    should_notify = interview.status == "scheduled"
    interview.room_started_at = interview.room_started_at or now
    interview.status = "in_progress"
    interview.updated_at = now
    if should_notify:
        db.add(Notification(user_id=interview.candidate_id, type="interview_room_started", message="Your recruiter has started the in-platform interview room.", related_id=interview.id, job_id=interview.job_id, is_read=False, created_at=now))
    await db.commit()
    await hub.broadcast(str(interview.id), {"type": "room_started", "at": now.isoformat()})
    return {"status": interview.status, "room_started_at": now.isoformat()}


@router.post("/{interview_id}/room/end")
async def end_room(interview_id: str, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    if interview.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled interviews cannot be ended as a room session.")
    if interview.status == "completed" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="This interview room has already ended.")
    now = datetime.now(timezone.utc)
    interview.room_started_at = interview.room_started_at or now
    interview.room_ended_at = now
    interview.status = "completed"
    interview.updated_at = now
    db.add(Notification(user_id=interview.candidate_id, type="interview_room_ended", message="The in-platform interview room has ended.", related_id=interview.id, job_id=interview.job_id, is_read=False, created_at=now))
    await db.commit()
    await hub.broadcast(str(interview.id), {"type": "room_ended", "at": now.isoformat()})
    return {"status": interview.status, "room_ended_at": now.isoformat()}


@router.get("/coding-languages")
async def coding_languages(user: dict = Depends(recruiter_required)):
    return {"language_ids": _language_ids(), "language_labels": LANGUAGE_NAMES}


@router.get("/coding-question-bank")
async def list_coding_question_bank(user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    recruiter_id = parse_uuid(user["id"], "recruiter id")
    questions = (await db.scalars(
        select(InterviewCodingProblem)
        .where(
            InterviewCodingProblem.created_by == recruiter_id,
            InterviewCodingProblem.interview_id.is_(None),
        )
        .order_by(InterviewCodingProblem.created_at.desc())
        .limit(500)
    )).all()
    return [_question_payload(question) for question in questions]


@router.post("/coding-question-bank", status_code=201)
async def create_coding_bank_question(data: ProblemInput, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    languages = _language_ids()
    if any(language not in languages for language in data.allowed_languages):
        raise HTTPException(status_code=422, detail="Choose languages enabled by the configured code sandbox.")
    problem = InterviewCodingProblem(
        interview_id=None,
        created_by=parse_uuid(user["id"], "recruiter id"),
        title=_problem_title(data.question),
        prompt=data.question.strip(),
        allowed_languages=data.allowed_languages,
        time_limit_seconds=data.time_limit_seconds,
    )
    db.add(problem)
    await db.commit()
    await db.refresh(problem)
    return _question_payload(problem)


@router.post("/{interview_id}/room/questions/{question_id}/send")
async def send_coding_bank_question(interview_id: str, question_id: str, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    if interview.status != "in_progress" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="Start the live interview before sending a coding question.")

    application = await db.get(Application, interview.application_id)
    if not application or application.status not in {"shortlisted", "selected", "interview"}:
        raise HTTPException(status_code=409, detail="Coding questions can only be sent to shortlisted or selected candidates.")

    bank_question = await db.scalar(
        select(InterviewCodingProblem).where(
            InterviewCodingProblem.id == parse_uuid(question_id, "question id"),
            InterviewCodingProblem.created_by == parse_uuid(user["id"], "recruiter id"),
            InterviewCodingProblem.interview_id.is_(None),
        )
    )
    if not bank_question:
        raise HTTPException(status_code=404, detail="Coding question was not found in your question bank.")

    languages = _language_ids()
    allowed_languages = [item for item in bank_question.allowed_languages if item in languages]
    if not allowed_languages:
        raise HTTPException(status_code=409, detail="This question has no languages enabled by the current code sandbox.")

    problem = InterviewCodingProblem(
        interview_id=interview.id,
        created_by=bank_question.created_by,
        title=bank_question.title,
        prompt=bank_question.prompt,
        allowed_languages=allowed_languages,
        time_limit_seconds=bank_question.time_limit_seconds,
    )
    db.add(problem)
    await db.flush()
    now = datetime.now(timezone.utc)
    extra = dict(interview.extra_data or {})
    active_problem = {
        "problem_id": str(problem.id), "started_at": now.isoformat(),
        "ends_at": (now + timedelta(seconds=problem.time_limit_seconds)).isoformat(),
    }
    extra["active_coding_problem"] = active_problem
    interview.extra_data = extra
    await db.commit()
    await db.refresh(problem)

    payload = {
        **_question_payload(problem), "prompt": problem.prompt,
        **active_problem,
    }
    await hub.broadcast(str(interview.id), {"type": "problem_activated", "problem": payload})
    return payload


@router.post("/{interview_id}/room/problems")
async def create_problem(interview_id: str, data: ProblemInput, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    if interview.status != "in_progress" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="Start the live interview before sending a coding question.")
    languages = _language_ids()
    if any(language not in languages for language in data.allowed_languages):
        raise HTTPException(status_code=422, detail="Choose languages enabled by the configured code sandbox.")
    recruiter_id = parse_uuid(user["id"], "recruiter id")
    question_text = data.question.strip()

    bank_question = InterviewCodingProblem(
        interview_id=None, created_by=recruiter_id,
        title=_problem_title(question_text), prompt=question_text,
        allowed_languages=data.allowed_languages,
        time_limit_seconds=data.time_limit_seconds,
    )
    db.add(bank_question)
    await db.flush()
    problem = InterviewCodingProblem(
        interview_id=interview.id, created_by=recruiter_id,
        title=bank_question.title, prompt=question_text,
        allowed_languages=data.allowed_languages,
        time_limit_seconds=data.time_limit_seconds,
    )
    db.add(problem)
    await db.flush()
    now = datetime.now(timezone.utc)
    extra = dict(interview.extra_data or {})
    active_problem = {
        "problem_id": str(problem.id), "started_at": now.isoformat(),
        "ends_at": (now + timedelta(seconds=problem.time_limit_seconds)).isoformat(),
    }
    extra["active_coding_problem"] = active_problem
    interview.extra_data = extra
    await db.commit()
    await db.refresh(bank_question)
    await db.refresh(problem)

    payload = {**_question_payload(problem), "prompt": problem.prompt, **active_problem}
    await hub.broadcast(str(interview.id), {"type": "problem_activated", "problem": payload})
    await hub.broadcast(str(interview.id), {"type": "question_saved", "question": _question_payload(bank_question)})
    return {**payload, "saved_to_question_bank": True}


@router.post("/{interview_id}/room/problems/{problem_id}/activate")
async def activate_problem(interview_id: str, problem_id: str, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    if interview.status != "in_progress" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="Start the interview room before activating a problem.")
    problem = await db.scalar(select(InterviewCodingProblem).where(InterviewCodingProblem.id == parse_uuid(problem_id, "problem id"), InterviewCodingProblem.interview_id == interview.id))
    if problem is None:
        raise HTTPException(status_code=404, detail="Coding problem not found.")
    now = datetime.now(timezone.utc)
    extra = dict(interview.extra_data or {})
    active_problem = {"problem_id": str(problem.id), "started_at": now.isoformat(), "ends_at": (now + timedelta(seconds=problem.time_limit_seconds)).isoformat()}
    extra["active_coding_problem"] = active_problem
    interview.extra_data = extra
    await db.commit()
    payload = {"id": str(problem.id), "title": problem.title, "question": problem.prompt, "prompt": problem.prompt, "allowed_languages": problem.allowed_languages, "time_limit_seconds": problem.time_limit_seconds, **active_problem}
    await hub.broadcast(str(interview.id), {"type": "problem_activated", "problem": payload})
    return payload


@router.post("/{interview_id}/room/problems/{problem_id}/run")
async def run_code(interview_id: str, problem_id: str, data: RunInput, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only the candidate can run interview code.")
    if interview.status != "in_progress" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="The interview room is not active.")
    if not settings.judge0_api_url.strip():
        raise HTTPException(status_code=503, detail="Secure code execution is unavailable. Configure JUDGE0_API_URL for the isolated sandbox.")
    problem = await db.scalar(select(InterviewCodingProblem).where(InterviewCodingProblem.id == parse_uuid(problem_id, "problem id"), InterviewCodingProblem.interview_id == interview.id))
    if problem is None:
        raise HTTPException(status_code=404, detail="Coding problem not found.")
    active_problem = (interview.extra_data or {}).get("active_coding_problem") or {}
    if active_problem.get("problem_id") != str(problem.id):
        raise HTTPException(status_code=409, detail="The recruiter has not activated this coding problem.")
    ends_at = active_problem.get("ends_at")
    if not ends_at or datetime.now(timezone.utc) >= datetime.fromisoformat(ends_at):
        raise HTTPException(status_code=409, detail="The coding time limit has ended.")
    language_ids = _language_ids()
    if data.language not in problem.allowed_languages or data.language not in language_ids:
        raise HTTPException(status_code=422, detail="This language is not allowed for the selected problem.")
    headers = {"Content-Type": "application/json"}
    if settings.judge0_api_key.strip():
        headers["X-Auth-Token"] = settings.judge0_api_key.strip()
    base_url = settings.judge0_api_url.strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/submissions?base64_encoded=false&wait=true",
                headers=headers,
                json={
                    "language_id": language_ids[data.language],
                    "source_code": data.source_code,
                    "stdin": data.stdin,
                    "cpu_time_limit": 3,
                    "wall_time_limit": 5,
                    "memory_limit": 128000,
                    "max_processes_and_or_threads": 32,
                },
            )
            response.raise_for_status()
            runner_result = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="The isolated code runner timed out. Try again with a smaller program.") from exc
    except httpx.HTTPError as exc:
        logger.exception("Interview sandbox request failed")
        raise HTTPException(status_code=502, detail="The isolated code runner is temporarily unavailable.") from exc
    runner_status = runner_result.get("status") or {}
    summary = {
        "status": runner_status.get("description", "Unknown"),
        "status_id": runner_status.get("id"),
        "successful": runner_status.get("id") == 3,
        "stdout": (runner_result.get("stdout") or "")[:8000],
        "stderr": (runner_result.get("stderr") or runner_result.get("compile_output") or "")[:8000],
        "time": runner_result.get("time"),
        "memory": runner_result.get("memory"),
    }
    submission = InterviewCodeSubmission(interview_id=interview.id, problem_id=problem.id, candidate_id=parse_uuid(user["id"], "user id"), language=data.language, source_code=data.source_code, result=summary, is_final=data.final)
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    safe_result = {"id": str(submission.id), **summary, "language": data.language, "source_code": submission.source_code, "question": problem.prompt, "is_final": submission.is_final, "created_at": submission.created_at.isoformat()}
    await hub.broadcast(str(interview.id), {"type": "coding_result", "submission": safe_result})
    return safe_result


@router.get("/{interview_id}/room/submissions")
async def list_submissions(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    query = select(InterviewCodeSubmission, InterviewCodingProblem).join(
        InterviewCodingProblem,
        InterviewCodeSubmission.problem_id == InterviewCodingProblem.id,
    ).where(InterviewCodeSubmission.interview_id == interview.id).order_by(InterviewCodeSubmission.created_at.desc()).limit(100)
    if role == "candidate":
        query = query.where(InterviewCodeSubmission.candidate_id == parse_uuid(user["id"], "user id"))
    rows = (await db.execute(query)).all()
    return [{"id": str(item.id), "problem_id": str(item.problem_id), "question": problem.prompt, "language": item.language, "source_code": item.source_code if role == "recruiter" else None, "result": item.result, "is_final": item.is_final, "created_at": item.created_at.isoformat()} for item, problem in rows]


@router.post("/{interview_id}/room/activity")
async def log_activity(interview_id: str, data: EventInput, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only candidate browser-observable events are accepted here.")
    if interview.status != "in_progress" or interview.room_ended_at:
        raise HTTPException(status_code=409, detail="Activity can only be recorded during an active interview.")
    if not (interview.extra_data or {}).get("candidate_room_consent", {}).get("accepted"):
        raise HTTPException(status_code=403, detail="Candidate monitoring consent is required.")
    if data.event_type not in SUSPICIOUS_EVENTS:
        raise HTTPException(status_code=422, detail="Unsupported interview activity event.")
    details = {key: str(value)[:160] for key, value in data.details.items() if key in {"source", "reason"}}
    event = InterviewRoomEvent(interview_id=interview.id, actor_id=parse_uuid(user["id"], "user id"), event_type=data.event_type, details=details, occurred_at=datetime.now(timezone.utc))
    db.add(event)
    await db.commit()
    item = {"id": str(event.id), "event_type": event.event_type, "occurred_at": event.occurred_at.isoformat(), "details": event.details, "actor_role": role}
    await hub.broadcast(str(interview.id), {"type": "activity_alert", "event": item})
    return item


@router.get("/{interview_id}/room/activity")
async def list_activity(interview_id: str, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_database)):
    interview, role = await _get_owned(db, interview_id, user)
    events = (await db.scalars(select(InterviewRoomEvent).where(InterviewRoomEvent.interview_id == interview.id).order_by(InterviewRoomEvent.occurred_at.desc()).limit(250))).all()
    return [{"id": str(event.id), "event_type": event.event_type, "occurred_at": event.occurred_at.isoformat(), "details": event.details, "actor_role": "candidate" if event.actor_id == interview.candidate_id else "recruiter"} for event in events]


@router.put("/{interview_id}/room/feedback")
async def save_feedback(interview_id: str, data: FeedbackInput, user: dict = Depends(recruiter_required), db: AsyncSession = Depends(get_database)):
    interview, _ = await _get_owned(db, interview_id, user)
    feedback = await db.scalar(select(InterviewFeedback).where(InterviewFeedback.interview_id == interview.id))
    if feedback is None:
        feedback = InterviewFeedback(interview_id=interview.id, recruiter_id=parse_uuid(user["id"], "user id"), rating=data.rating, strengths=data.strengths, improvement_areas=data.improvement_areas, private_notes=data.private_notes, recommendation=data.recommendation)
    else:
        feedback.rating, feedback.strengths, feedback.improvement_areas = data.rating, data.strengths, data.improvement_areas
        feedback.private_notes, feedback.recommendation = data.private_notes, data.recommendation
        feedback.updated_at = datetime.now(timezone.utc)
    db.add(feedback)
    await db.commit()
    return {key: value for key, value in serialize_model(feedback).items() if key != "private_notes"}


@router.websocket("/{interview_id}/room/ws")
async def interview_room_socket(websocket: WebSocket, interview_id: str):
    try:
        interview_uuid = UUID(interview_id)
    except ValueError:
        await websocket.close(code=4404)
        return
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    ticket = protocols[1] if len(protocols) > 1 and protocols[0] == "skillsphere-room" else ""
    try:
        claims = jwt.decode(ticket, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if claims.get("purpose") != "interview_room" or claims.get("iid") != str(interview_uuid):
            raise ValueError("Wrong interview ticket scope")
        user_id = UUID(claims["sub"])
        async with AsyncSessionLocal() as db:
            interview = await db.get(Interview, interview_uuid)
            user = await db.get(User, user_id)
            if not interview or not user or not user.is_active or user.role != claims.get("role"):
                await websocket.close(code=4401)
                return
            role = _authorize(interview, {"id": str(user.id), "role": user.role})
            if role == "candidate" and interview.candidate_response == "declined":
                await websocket.close(code=4403)
                return
            if role == "candidate" and not (interview.extra_data or {}).get("candidate_room_consent", {}).get("accepted"):
                await websocket.close(code=4403)
                return
            if interview.room_ended_at or interview.status in {"cancelled", "completed"}:
                await websocket.close(code=4409)
                return
            participant = {"id": str(user.id), "name": user.full_name or role.title(), "role": role}
    except Exception:
        await websocket.close(code=4401)
        return

    room_id = str(interview_uuid)
    await hub.connect(room_id, websocket, participant)
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict) or len(json.dumps(message)) > 30000:
                await websocket.send_json({"type": "error", "message": "Invalid or oversized room message."})
                continue
            event_type = message.get("type")
            if event_type in {"offer", "answer", "ice_candidate", "candidate_joined", "room_started", "coding_update"}:
                if event_type == "coding_update" and (role != "candidate" or not isinstance(message.get("source_code"), str) or len(message["source_code"]) > 30000):
                    await websocket.send_json({"type": "error", "message": "Invalid live code update."})
                    continue
                if event_type in {"offer", "answer", "ice_candidate"} and not isinstance(message.get("payload"), dict):
                    await websocket.send_json({"type": "error", "message": "Invalid WebRTC signaling payload."})
                    continue
                await hub.broadcast(room_id, {**message, "sender": participant}, exclude=websocket)
            else:
                await websocket.send_json({"type": "error", "message": "Unsupported room message."})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Interview room websocket failed")
    finally:
        await hub.disconnect(room_id, websocket)
