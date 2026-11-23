import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.routers.proctoring import ProctoringEventInput, record_proctoring_event
from pydantic import ValidationError


class ProctoringEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_warning_event_is_persisted_without_media_payload(self):
        session_id = uuid4()
        session = SimpleNamespace(
            id=session_id,
            candidate_id=uuid4(),
            status="active",
            warning_count=0,
            updated_at=None,
        )
        database = SimpleNamespace(
            scalar=AsyncMock(side_effect=[session, SimpleNamespace(status="in_progress")]),
            add=Mock(),
            commit=AsyncMock(),
        )

        result = await record_proctoring_event(
            session_id,
            ProctoringEventInput(event_type="multiple_faces", face_count=2),
            {"id": str(session.candidate_id)},
            database,
        )

        event = database.add.call_args.args[0]
        self.assertTrue(result["recorded"])
        self.assertEqual(session.warning_count, 1)
        self.assertEqual(event.event_type, "multiple_faces")
        self.assertEqual(event.severity, "warning")
        self.assertIn("(2 detected)", event.description)
        self.assertFalse(hasattr(event, "screenshot"))
        database.commit.assert_awaited_once()

    async def test_repeated_warning_is_recorded_with_a_fresh_timestamp(self):
        session_id = uuid4()
        session = SimpleNamespace(
            id=session_id,
            candidate_id=uuid4(),
            status="active",
            warning_count=1,
        )
        database = SimpleNamespace(
            scalar=AsyncMock(side_effect=[session, SimpleNamespace(status="in_progress")]),
            add=Mock(),
            commit=AsyncMock(),
        )

        result = await record_proctoring_event(
            session_id,
            ProctoringEventInput(event_type="face_missing"),
            {"id": str(session.candidate_id)},
            database,
        )

        self.assertTrue(result["recorded"])
        self.assertEqual(result["warning_count"], 2)
        self.assertEqual(database.add.call_count, 1)
        database.commit.assert_awaited_once()

    def test_only_known_monitoring_events_are_accepted(self):
        with self.assertRaises(ValidationError):
            ProctoringEventInput(event_type="screenshot_captured")


if __name__ == "__main__":
    unittest.main()
