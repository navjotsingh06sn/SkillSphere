import asyncio
import unittest
from types import SimpleNamespace

from bson import ObjectId
from fastapi import HTTPException

from app.database.collections import (
    APPLICATIONS,
    JOBS,
    NOTIFICATIONS,
    RESUMES,
    RESUME_ANALYSES,
)
from app.routers.applications import (
    apply_to_job,
    calculate_match,
    get_application,
)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    async def find_one(self, query, *args, **kwargs):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    async def insert_one(self, document):
        document = {**document, "_id": ObjectId()}
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def delete_one(self, query):
        self.documents = [
            document
            for document in self.documents
            if not all(document.get(key) == value for key, value in query.items())
        ]


class FakeDatabase:
    def __init__(self, collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections[name]


class ApplicationScreeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.candidate_id = ObjectId()
        self.job_id = ObjectId()
        self.resume_id = ObjectId()
        self.job = {
            "_id": self.job_id,
            "recruiter_id": ObjectId(),
            "title": "Test role",
            "status": "published",
            "required_skills": ["Python", "FastAPI", "MongoDB", "Docker"],
        }
        self.resume = {
            "_id": self.resume_id,
            "candidate_id": self.candidate_id,
            "status": "completed",
            "extracted_data": {"skills": ["Python", "FastAPI"]},
        }

    def database(self, resume_skills=None, existing_application=None):
        resume = {**self.resume}
        if resume_skills is not None:
            resume["extracted_data"] = {"skills": resume_skills}
        return FakeDatabase({
            JOBS: FakeCollection([self.job]),
            APPLICATIONS: FakeCollection(
                [existing_application] if existing_application else []
            ),
            RESUMES: FakeCollection([resume]),
            RESUME_ANALYSES: FakeCollection(),
            NOTIFICATIONS: FakeCollection(),
        })

    async def submit(self, required_skills, resume_skills):
        self.job["required_skills"] = required_skills
        database = self.database(resume_skills)
        result = await apply_to_job(
            str(self.job_id),
            {"id": str(self.candidate_id)},
            database,
        )
        return result, database

    async def test_eighty_percent_match_is_reviewable(self):
        result, database = await self.submit(
            ["Python", "FastAPI", "MongoDB", "Docker", "AWS"],
            ["Python", "FastAPI", "MongoDB", "Docker"],
        )
        application = database[APPLICATIONS].documents[0]
        self.assertEqual(result["match_score"], 80)
        self.assertEqual(application["status"], "under_review")
        self.assertEqual(application["screening_status"], "shortlisted")
        self.assertEqual(application["required_score"], 75)
        self.assertEqual(len(database[NOTIFICATIONS].documents), 1)
        self.assertEqual(database[NOTIFICATIONS].documents[0]["type"], "application_applied")
        self.assertEqual(
            database[NOTIFICATIONS].documents[0]["message"],
            "Your application for Test role has been submitted successfully. "
            "You meet the required screening criteria.",
        )

    async def test_exactly_seventy_five_percent_is_reviewable(self):
        result, database = await self.submit(
            ["Python", "FastAPI", "MongoDB", "Docker"],
            ["Python", "FastAPI", "MongoDB"],
        )
        application = database[APPLICATIONS].documents[0]
        self.assertEqual(result["match_score"], 75)
        self.assertEqual(application["status"], "under_review")
        self.assertEqual(application["screening_status"], "shortlisted")

    async def test_rounded_score_below_threshold_is_rejected(self):
        required = [f"skill-{index}" for index in range(99)]
        candidate = required[:74]
        result, database = await self.submit(required, candidate)
        application = database[APPLICATIONS].documents[0]
        self.assertEqual(result["match_score"], 74.75)
        self.assertEqual(application["status"], "rejected")

    async def test_fifty_percent_is_rejected_and_candidate_is_notified(self):
        result, database = await self.submit(
            ["Python", "FastAPI", "MongoDB", "Docker"],
            ["Python", "FastAPI"],
        )
        application = database[APPLICATIONS].documents[0]
        self.assertEqual(result["match_score"], 50)
        self.assertEqual(application["status"], "rejected")
        self.assertEqual(application["required_score"], 75)
        self.assertEqual(application["matched_skills"], ["FastAPI", "Python"])
        self.assertEqual(application["missing_skills"], ["Docker", "MongoDB"])
        self.assertIn("50%", application["rejection_reason"])
        notifications = database[NOTIFICATIONS].documents
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "application_rejected")
        self.assertEqual(
            notifications[0]["message"],
            "Your application for Test role has been rejected because your "
            "resume did not meet the required screening criteria. "
            "Click to view the reason.",
        )

    async def test_missing_resume_skills_go_to_manual_review(self):
        result, database = await self.submit(
            ["Python", "FastAPI"],
            [],
        )
        application = database[APPLICATIONS].documents[0]
        self.assertIsNone(result["match_score"])
        self.assertEqual(application["status"], "under_review")
        self.assertEqual(application["screening_status"], "pending_review")
        self.assertEqual(len(database[NOTIFICATIONS].documents), 1)

    async def test_job_without_required_skills_goes_to_manual_review(self):
        result, database = await self.submit([], ["Python"])
        self.assertIsNone(result["match_score"])
        self.assertEqual(database[APPLICATIONS].documents[0]["status"], "under_review")

    async def test_duplicate_application_is_rejected(self):
        existing = {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
        }
        database = self.database(existing_application=existing)
        with self.assertRaises(HTTPException) as raised:
            await apply_to_job(
                str(self.job_id),
                {"id": str(self.candidate_id)},
                database,
            )
        self.assertEqual(raised.exception.status_code, 409)

    async def test_candidate_application_details_include_screening_analysis(self):
        application_id = ObjectId()
        application = {
            "_id": application_id,
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "status": "rejected",
            "match_score": 50,
            "required_score": 75,
            "matched_skills": ["Python"],
            "missing_skills": ["Docker"],
            "analysis_id": ObjectId(),
            "applied_at": None,
        }
        analysis = {
            "_id": application["analysis_id"],
            "candidate_id": self.candidate_id,
            "matched_skills": ["Python"],
            "missing_skills": ["Docker"],
        }
        database = FakeDatabase({
            APPLICATIONS: FakeCollection([application]),
            JOBS: FakeCollection([self.job]),
            RESUME_ANALYSES: FakeCollection([analysis]),
        })

        result = await get_application(
            str(application_id),
            {"id": str(self.candidate_id), "role": "candidate"},
            database,
        )

        self.assertEqual(result["job"]["id"], str(self.job_id))
        self.assertEqual(result["analysis"]["missing_skills"], ["Docker"])
        self.assertEqual(result["required_score"], 75)

    async def test_candidate_cannot_open_another_candidates_application(self):
        application_id = ObjectId()
        database = FakeDatabase({
            APPLICATIONS: FakeCollection([{
                "_id": application_id,
                "candidate_id": self.candidate_id,
                "job_id": self.job_id,
            }]),
        })

        with self.assertRaises(HTTPException) as raised:
            await get_application(
                str(application_id),
                {"id": str(ObjectId()), "role": "candidate"},
                database,
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_empty_skill_data_does_not_create_zero_score(self):
        score, matched, missing, candidate = calculate_match(
            [],
            ["Python", "FastAPI"],
        )
        self.assertIsNone(score)
        self.assertEqual(matched, [])
        self.assertEqual(missing, [])
        self.assertEqual(candidate, {})


if __name__ == "__main__":
    unittest.main()
