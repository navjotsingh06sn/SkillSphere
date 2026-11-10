import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.routers.matching import normalize
from app.routers.resumes import parse_resume

BASE_URL = "http://127.0.0.1:8000"


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except HTTPError as response:
        result = response.code, response.read()
        response.close()
        return result


class SkillSphereSmokeTests(unittest.TestCase):
    def test_health_endpoint(self):
        status_code, body = call("/api/health")
        self.assertEqual(status_code, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_protected_current_user_requires_token(self):
        status_code, _ = call("/api/auth/me")
        self.assertEqual(status_code, 401)

    def test_registration_rejects_short_password(self):
        status_code, _ = call(
            "/api/auth/register",
            "POST",
            {
                "full_name": "Example User",
                "email": "user@example.com",
                "password": "short",
                "role": "candidate",
            },
        )
        self.assertEqual(status_code, 422)

    def test_readiness_reports_database_state(self):
        status_code, _ = call("/api/health/ready")
        self.assertIn(status_code, (200, 503))

    def test_openapi_lists_core_workflows(self):
        status_code, body = call("/openapi.json")
        self.assertEqual(status_code, 200)
        paths = json.loads(body)["paths"]
        required_paths = [
            "/api/auth/register",
            "/api/auth/forgot-password",
            "/api/notifications",
            "/api/resumes/upload",
            "/api/matching/analyze",
            "/api/jobs/{job_id}/apply",
            "/api/recruiter/applicants",
            "/api/admin/analytics",
        ]
        for path in required_paths:
            self.assertIn(path, paths)

    def test_resume_parser_extracts_only_text_found_in_document(self):
        result = parse_resume(
            "Ada Lovelace\nada@example.com\nPython and React\n"
            "Education\nBachelor of Science, Example University\n"
            "Experience\nSoftware developer, Example Co."
        )
        self.assertEqual(result["email"], "ada@example.com")
        self.assertIn("Python", result["skills"])
        self.assertEqual(result["education"][0]["text"], "Bachelor of Science, Example University")
        self.assertEqual(result["experience"][0]["text"], "Software developer, Example Co.")

    def test_matching_aliases_are_normalized(self):
        self.assertEqual(normalize("JS"), normalize("JavaScript"))
        self.assertEqual(normalize("React"), normalize("React.js"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
