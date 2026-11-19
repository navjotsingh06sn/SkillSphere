import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from unittest.mock import patch

from app.dependencies import candidate_required
from fastapi.routing import APIRoute
from app.routers.chatbot import (
    _application_payload,
    _chatbot_ai_config,
    _is_application_status_question,
    _needs_application_context,
    _owned_conversation,
    _status_summary,
    MessageInput,
    send_message,
)


class CandidateChatbotTests(unittest.TestCase):
    def test_general_chat_uses_backend_provider_and_authenticated_candidate_context(self):
        candidate_id = uuid4()
        conversation = SimpleNamespace(
            id=uuid4(), candidate_id=candidate_id, title="New conversation", updated_at=None,
        )

        class EmptyResult:
            def all(self):
                return []

        class FakeDatabase:
            def __init__(self):
                self.scalar_calls = 0
                self.saved_messages = []

            async def scalar(self, _statement):
                self.scalar_calls += 1
                return conversation if self.scalar_calls == 1 else SimpleNamespace(full_name="Candidate")

            async def execute(self, _statement):
                return EmptyResult()

            async def scalars(self, _statement):
                return EmptyResult()

            def add_all(self, messages):
                for message in messages:
                    message.id = uuid4()
                self.saved_messages.extend(messages)

            async def commit(self):
                return None

            async def refresh(self, _message):
                return None

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "A focused profile helps recruiters understand your strengths."}}]}

        class FakeClient:
            def __init__(self, **_kwargs):
                self.request = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, url, headers, json):
                self.request = {"url": url, "headers": headers, "json": json}
                return FakeResponse()

        database = FakeDatabase()
        client = FakeClient()
        with patch.multiple(
            "app.routers.chatbot.settings",
            chatbot_ai_base_url="https://chat.example/v1",
            chatbot_ai_api_key="backend-only-key",
            chatbot_ai_model="chat-model",
            chatbot_ai_timeout_seconds=19,
        ), patch("app.routers.chatbot.httpx.AsyncClient", return_value=client):
            result = asyncio.run(send_message(
                str(conversation.id), MessageInput(content="How can I update my profile?"),
                {"id": str(candidate_id), "role": "candidate"}, database,
            ))
        self.assertEqual(client.request["url"], "https://chat.example/v1/chat/completions")
        self.assertEqual(client.request["headers"]["Authorization"], "Bearer backend-only-key")
        self.assertIn('"candidate_name": "Candidate"', client.request["json"]["messages"][0]["content"])
        self.assertEqual(result["messages"][1]["content"], "A focused profile helps recruiters understand your strengths.")
        self.assertEqual(len(database.saved_messages), 2)

    def test_status_question_is_persisted_without_ai_configuration(self):
        candidate_id = uuid4()
        conversation = SimpleNamespace(
            id=uuid4(), candidate_id=candidate_id, title="New conversation", updated_at=None,
        )

        class EmptyResult:
            def all(self):
                return []

        class FakeDatabase:
            def __init__(self):
                self.scalar_calls = 0
                self.saved_messages = []
                self.commits = 0

            async def scalar(self, _statement):
                self.scalar_calls += 1
                return conversation if self.scalar_calls == 1 else SimpleNamespace(full_name="Candidate")

            async def execute(self, _statement):
                return EmptyResult()

            async def scalars(self, _statement):
                return EmptyResult()

            def add_all(self, messages):
                for message in messages:
                    message.id = uuid4()
                self.saved_messages.extend(messages)

            async def commit(self):
                self.commits += 1

            async def refresh(self, _message):
                return None

        database = FakeDatabase()
        result = asyncio.run(send_message(
            str(conversation.id), MessageInput(content="What is my application status?"),
            {"id": str(candidate_id), "role": "candidate"}, database,
        ))
        self.assertEqual([message["role"] for message in result["messages"]], ["user", "assistant"])
        self.assertIn("can’t see any submitted applications", result["messages"][1]["content"])
        self.assertEqual(len(database.saved_messages), 2)
        self.assertEqual(database.commits, 1)

    def test_conversation_lookup_rejects_missing_or_unowned_conversation(self):
        class MissingConversationDatabase:
            async def scalar(self, _statement):
                return None

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_owned_conversation(MissingConversationDatabase(), str(uuid4()), uuid4()))
        self.assertEqual(raised.exception.status_code, 404)

    def test_every_chatbot_api_route_requires_candidate_role(self):
        from app.routers.chatbot import router

        for route in router.routes:
            if isinstance(route, APIRoute):
                dependencies = {dependency.call for dependency in route.dependant.dependencies}
                self.assertIn(candidate_required, dependencies, route.path)

    def test_dedicated_ai_configuration_overrides_existing_assessment_ai_settings(self):
        with patch.multiple(
            "app.routers.chatbot.settings",
            chatbot_ai_base_url="https://chat.example/v1",
            chatbot_ai_api_key="chat-key",
            chatbot_ai_model="chat-model",
            chatbot_ai_timeout_seconds=19,
            assessment_ai_base_url="https://assessment.example/v1",
            assessment_ai_api_key="assessment-key",
            assessment_ai_model="assessment-model",
            assessment_ai_timeout_seconds=44,
        ):
            self.assertEqual(
                _chatbot_ai_config(),
                ("https://chat.example/v1", "chat-key", "chat-model", 19),
            )

    def test_existing_assessment_ai_configuration_is_a_backend_only_fallback(self):
        with patch.multiple(
            "app.routers.chatbot.settings",
            chatbot_ai_base_url="",
            chatbot_ai_api_key="",
            chatbot_ai_model="",
            chatbot_ai_timeout_seconds=19,
            assessment_ai_base_url="https://assessment.example/v1",
            assessment_ai_api_key="assessment-key",
            assessment_ai_model="assessment-model",
            assessment_ai_timeout_seconds=44,
        ):
            self.assertEqual(
                _chatbot_ai_config(),
                ("https://assessment.example/v1", "assessment-key", "assessment-model", 44),
            )

    def test_application_timeline_uses_recorded_application_state(self):
        now = datetime.now(timezone.utc)
        application = SimpleNamespace(
            id="app-id", status="applied", screening_status="pending_review",
            applied_at=now, updated_at=now,
        )
        job = SimpleNamespace(id="job-id", title="Engineer", company_name="Acme", location="Remote")
        result = _application_payload(application, job, None, [])
        self.assertEqual(result["current_stage"], "Applied")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["timeline"][0]["state"], "complete")

    def test_assessment_and_interview_stages_come_from_database_records(self):
        now = datetime.now(timezone.utc)
        application = SimpleNamespace(
            id="app-id", status="shortlisted", screening_status="shortlisted",
            applied_at=now, updated_at=now,
        )
        job = SimpleNamespace(id="job-id", title="Engineer", company_name="Acme", location=None)
        assessment = SimpleNamespace(title="Round 1", status="passed", score=84, updated_at=now)
        result = _application_payload(application, job, assessment, [])
        self.assertEqual(result["current_stage"], "Assessment")
        self.assertEqual(result["assessment"]["score"], 84)
        interview = SimpleNamespace(status="scheduled", interview_type="technical", scheduled_at=now)
        result = _application_payload(application, job, assessment, [interview])
        self.assertEqual(result["current_stage"], "Interview")
        self.assertEqual(result["timeline"][3]["state"], "current")

    def test_selected_is_a_final_decision_and_cancelled_interviews_are_not_active(self):
        now = datetime.now(timezone.utc)
        job = SimpleNamespace(id="job-id", title="Engineer", company_name="Acme", location=None)
        for status in ("selected", "rejected", "withdrawn"):
            application = SimpleNamespace(
                id="app-id", status=status, screening_status=None,
                applied_at=now, updated_at=now,
            )
            result = _application_payload(application, job, None, [])
            self.assertEqual(result["current_stage"], "Final Decision")
            self.assertEqual(result["timeline"][-1]["state"], "complete")

        application = SimpleNamespace(
            id="app-id", status="shortlisted", screening_status="shortlisted",
            applied_at=now, updated_at=now,
        )
        cancelled = SimpleNamespace(status="cancelled", interview_type="technical", scheduled_at=now)
        result = _application_payload(application, job, None, [cancelled])
        self.assertEqual(result["current_stage"], "Under Review")
        self.assertEqual(result["timeline"][3]["state"], "upcoming")

    def test_candidate_context_is_included_only_for_candidate_specific_questions(self):
        self.assertTrue(_needs_application_context("What happened with my application?"))
        self.assertTrue(_needs_application_context("What was my assessment result?"))
        self.assertFalse(_needs_application_context("How can I update my profile?"))
        self.assertFalse(_needs_application_context("How can I prepare for an interview?"))

    def test_status_question_matching_does_not_capture_unrelated_updates(self):
        self.assertTrue(_is_application_status_question("What is my application status?"))
        self.assertTrue(_is_application_status_question("When is my interview scheduled?"))
        self.assertFalse(_is_application_status_question("How can I update my profile?"))
        self.assertFalse(_is_application_status_question("How can I prepare for an interview?"))

    def test_final_decision_takes_precedence_and_summary_never_fills_missing_data(self):
        now = datetime.now(timezone.utc)
        application = SimpleNamespace(
            id="app-id", status="rejected", screening_status="not_shortlisted",
            applied_at=now, updated_at=now,
        )
        job = SimpleNamespace(id="job-id", title="Engineer", company_name="Acme", location=None)
        result = _application_payload(application, job, None, [])
        self.assertEqual(result["current_stage"], "Final Decision")
        self.assertEqual(result["timeline"][-1]["state"], "complete")
        self.assertIn("can’t see any submitted applications", _status_summary([]))


if __name__ == "__main__":
    unittest.main()
