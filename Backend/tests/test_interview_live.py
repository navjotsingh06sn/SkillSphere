import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.interview_live import SUSPICIOUS_EVENTS, _authorize
from app.routers.interviews import (
    interview_room_url,
    validate_interview_eligibility,
)
from app.schemas import InterviewScheduleInput


class InterviewLiveAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.recruiter_id = uuid4()
        self.candidate_id = uuid4()
        self.interview = SimpleNamespace(
            recruiter_id=self.recruiter_id,
            candidate_id=self.candidate_id,
        )

    def test_interview_participants_are_authorized_by_role_and_owner(self):
        self.assertEqual(
            _authorize(self.interview, {"id": str(self.recruiter_id), "role": "recruiter"}),
            "recruiter",
        )
        self.assertEqual(
            _authorize(self.interview, {"id": str(self.candidate_id), "role": "candidate"}),
            "candidate",
        )

    def test_other_users_and_admins_cannot_access_interview(self):
        with self.assertRaises(HTTPException) as other_user:
            _authorize(self.interview, {"id": str(uuid4()), "role": "candidate"})
        self.assertEqual(other_user.exception.status_code, 404)

        with self.assertRaises(HTTPException) as admin:
            _authorize(self.interview, {"id": str(self.recruiter_id), "role": "admin"})
        self.assertEqual(admin.exception.status_code, 404)

    def test_monitoring_events_are_limited_to_disclosed_browser_signals(self):
        self.assertEqual(
            SUSPICIOUS_EVENTS,
            {"tab_hidden", "window_blur", "fullscreen_exited", "copy_attempt", "paste_attempt"},
        )

    def test_new_remote_interviews_use_the_builtin_room(self):
        scheduled = InterviewScheduleInput(scheduled_at="2030-01-01T12:00:00Z")
        self.assertEqual(scheduled.mode, "in_platform")
        with self.assertRaises(ValidationError):
            InterviewScheduleInput(scheduled_at="2030-01-01T12:00:00Z", mode="online")

    def test_interview_email_room_url_uses_frontend_configuration(self):
        interview_id = uuid4()
        self.assertTrue(interview_room_url(interview_id).endswith(
            f"/candidate/interviews/{interview_id}/room"
        ))

    def test_selected_candidate_can_be_scheduled_without_assessment_screening(self):
        application = SimpleNamespace(
            status="selected",
            screening_status="not_shortlisted",
            reconsideration_status="not_requested",
        )
        validate_interview_eligibility(application)

    def test_unselected_application_cannot_be_scheduled(self):
        application = SimpleNamespace(
            status="under_review",
            screening_status="pending_review",
            reconsideration_status="not_requested",
        )
        with self.assertRaises(HTTPException) as error:
            validate_interview_eligibility(application)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("Select the candidate", error.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
