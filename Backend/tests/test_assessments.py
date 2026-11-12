import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bson import ObjectId
from fastapi import HTTPException

from app.database.collections import (
    ASSESSMENTS,
    ASSESSMENT_ANSWER_KEYS,
    ASSESSMENT_QUESTIONS,
    JOBS,
    NOTIFICATIONS,
)
from app.routers.assessments import (
    get_assessment,
    start_assessment,
    submit_assessment,
)
from app.schemas import AssessmentAnswersInput
from app.services.assessments import (
    DIFFICULTY_COUNTS,
    build_question_bank,
    candidate_question,
    create_assessment_for_application,
    evaluate_assessment,
    relevant_categories,
    select_assessment_questions,
)


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    def __aiter__(self):
        self.iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    async def find_one(self, query, *_args, **_kwargs):
        for document in self.documents:
            if matches(document, query):
                return document
        return None

    def find(self, query):
        return FakeCursor([
            document for document in self.documents if matches(document, query)
        ])

    async def insert_one(self, document):
        if document.get("_id") is None:
            document["_id"] = ObjectId()
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, **_kwargs):
        for document in self.documents:
            if matches(document, query):
                document.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


def matches(document, query):
    for key, value in query.items():
        actual = document.get(key)
        if isinstance(value, dict) and "$in" in value:
            if actual not in value["$in"]:
                return False
        elif isinstance(value, dict) and "$gt" in value:
            if actual is None or actual <= value["$gt"]:
                return False
        elif actual != value:
            return False
    return True


class FakeDatabase:
    def __init__(self, collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def complete_assessment(assessment_id, candidate_id, recruiter_id, job_id):
    questions = []
    answer_key = {}
    for number in range(30):
        question_id = f"q{number}"
        questions.append({
            "question_id": question_id,
            "category": "python",
            "topic": f"topic-{number}",
            "difficulty": ("easy", "medium", "hard")[number % 3],
            "prompt": f"Question {number}",
            "options": ["A", "B", "C", "D"],
        })
        answer_key[question_id] = {
            "correct_index": 0,
            "topic": f"topic-{number}",
            "difficulty": ("easy", "medium", "hard")[number % 3],
            "explanation": "Test explanation",
        }
    return {
        "_id": assessment_id,
        "candidate_id": candidate_id,
        "recruiter_id": recruiter_id,
        "job_id": job_id,
        "application_id": ObjectId(),
        "job_title": "Python Developer",
        "status": "in_progress",
        "questions": questions,
        "time_limit_minutes": 30,
        "attempt_count": 1,
        "started_at": datetime.now(timezone.utc),
        "deadline_at": datetime.now(timezone.utc) + timedelta(minutes=30),
        "answers": {},
        "second_round_decision": "pending",
        "created_at": datetime.now(timezone.utc),
    }, answer_key


class AssessmentTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = build_question_bank()

    def test_seeded_common_roles_have_enough_relevant_questions(self):
        roles = [
            ("Python Developer", ["Python"], "Build Python services."),
            ("Java Developer", ["Java"], "Build JVM applications."),
            ("Full Stack Developer", ["React", "REST API", "MongoDB"], "Build web applications."),
            ("Cybersecurity Analyst", ["Linux", "Networking"], "Investigate security incidents."),
            ("Data Analyst", ["SQL", "Statistics"], "Analyze business data."),
            ("AI/ML Engineer", ["Machine Learning"], "Train and evaluate predictive models."),
        ]
        for title, skills, description in roles:
            job = {"title": title, "required_skills": skills, "description": description}
            questions, shortage = select_assessment_questions(job, self.bank)
            self.assertIsNone(shortage, title)
            self.assertEqual(len(questions), 30, title)
            self.assertEqual(
                {
                    difficulty: sum(q["difficulty"] == difficulty for q in questions)
                    for difficulty in DIFFICULTY_COUNTS
                },
                DIFFICULTY_COUNTS,
            )
            categories, _ = relevant_categories(job)
            self.assertTrue(all(q["category"] in categories for q in questions))
            self.assertTrue(all(len(q["options"]) == 4 for q in questions))

    def test_fullstack_role_detects_frontend_concerns_even_without_separators(self):
        categories, _ = relevant_categories({
            "title": "Fullstack Developer",
            "description": "Build production APIs and polished web experiences.",
            "required_skills": ["React", "REST API"],
        })
        self.assertIn("web_frontend", categories)
        self.assertIn("react", categories)
        self.assertIn("backend_api", categories)

    def test_unsupported_custom_role_reports_shortage_without_unrelated_questions(self):
        job = {
            "title": "Quantum Horticulture Specialist",
            "description": "Cultivate quantum crops.",
            "required_skills": ["Quantum botany"],
        }
        questions, shortage = select_assessment_questions(job, self.bank)
        self.assertEqual(questions, [])
        self.assertEqual(shortage["available_total"], 0)
        self.assertEqual(shortage["shortages"]["medium"]["required"], 15)

    def test_candidate_question_does_not_expose_answer_key(self):
        question = self.bank[0]
        public = candidate_question({
            **question,
            "question_id": "qid",
        })
        self.assertNotIn("correct_index", public)
        self.assertNotIn("explanation", public)
        self.assertEqual(len(public["options"]), 4)

    def test_evaluation_passes_at_exactly_seventy_percent_and_reports_breakdown(self):
        assessment_id, candidate_id, recruiter_id, job_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        assessment, key = complete_assessment(
            assessment_id, candidate_id, recruiter_id, job_id
        )
        answers = {f"q{number}": 0 for number in range(21)}
        answers.update({f"q{number}": 1 for number in range(21, 29)})
        result = evaluate_assessment(assessment["questions"], key, answers)
        self.assertEqual(result["correct_count"], 21)
        self.assertEqual(result["incorrect_count"], 8)
        self.assertEqual(result["unanswered_count"], 1)
        self.assertEqual(result["percentage"], 70)
        self.assertEqual(result["result"], "pass")
        self.assertTrue(result["second_round_eligible"])
        self.assertIn("topic_performance", result["performance_report"])
        self.assertIn("difficulty_performance", result["performance_report"])

    async def test_assessment_is_created_once_and_notifies_once(self):
        application = {
            "_id": ObjectId(),
            "candidate_id": ObjectId(),
            "recruiter_id": ObjectId(),
            "job_id": ObjectId(),
        }
        job = {
            "_id": application["job_id"],
            "title": "Python Developer",
            "description": "Develop Python services.",
            "required_skills": ["Python"],
        }
        db = FakeDatabase({
            JOBS: FakeCollection([job]),
            ASSESSMENT_QUESTIONS: FakeCollection(self.bank),
            ASSESSMENTS: FakeCollection(),
            ASSESSMENT_ANSWER_KEYS: FakeCollection(),
            NOTIFICATIONS: FakeCollection(),
        })
        first, created = await create_assessment_for_application(db, application)
        second, created_again = await create_assessment_for_application(db, application)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["_id"], second["_id"])
        self.assertEqual(len(db[ASSESSMENTS].documents), 1)
        self.assertEqual(len(db[ASSESSMENT_ANSWER_KEYS].documents), 1)
        self.assertEqual(len(db[NOTIFICATIONS].documents), 1)
        self.assertEqual(first["question_count"], 30)

    async def test_start_is_stable_and_answer_key_is_not_returned(self):
        assessment_id, candidate_id, recruiter_id, job_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        assessment, key = complete_assessment(
            assessment_id, candidate_id, recruiter_id, job_id
        )
        assessment["status"] = "assigned"
        assessment["attempt_count"] = 0
        db = FakeDatabase({
            ASSESSMENTS: FakeCollection([assessment]),
            ASSESSMENT_ANSWER_KEYS: FakeCollection([{"_id": assessment_id, "answers": key}]),
        })
        user = {"id": str(candidate_id), "role": "candidate"}
        first = await start_assessment(str(assessment_id), user, db)
        first_ids = [question["question_id"] for question in first["questions"]]
        second = await start_assessment(str(assessment_id), user, db)
        self.assertEqual(first_ids, [question["question_id"] for question in second["questions"]])
        self.assertEqual(first["deadline_at"], second["deadline_at"])
        self.assertEqual(assessment["attempt_count"], 1)
        self.assertNotIn("correct_index", str(first))
        self.assertNotIn("explanation", str(first))

    async def test_expired_deadline_uses_saved_answers_and_submits(self):
        assessment_id, candidate_id, recruiter_id, job_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        assessment, key = complete_assessment(
            assessment_id, candidate_id, recruiter_id, job_id
        )
        assessment["deadline_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        assessment["answers"] = {f"q{number}": 0 for number in range(21)}
        db = FakeDatabase({
            ASSESSMENTS: FakeCollection([assessment]),
            ASSESSMENT_ANSWER_KEYS: FakeCollection([{"_id": assessment_id, "answers": key}]),
            JOBS: FakeCollection([{"_id": job_id, "title": "Python Developer"}]),
            NOTIFICATIONS: FakeCollection(),
        })
        result = await get_assessment(
            str(assessment_id),
            {"id": str(candidate_id), "role": "candidate"},
            db,
        )
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["correct_count"], 21)
        self.assertEqual(result["unanswered_count"], 9)

    async def test_candidate_cannot_read_another_candidates_assessment(self):
        assessment_id, candidate_id, recruiter_id, job_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        assessment, _ = complete_assessment(
            assessment_id, candidate_id, recruiter_id, job_id
        )
        db = FakeDatabase({ASSESSMENTS: FakeCollection([assessment])})
        with self.assertRaises(HTTPException) as raised:
            await get_assessment(
                str(assessment_id),
                {"id": str(ObjectId()), "role": "candidate"},
                db,
            )
        self.assertEqual(raised.exception.status_code, 404)

    async def test_duplicate_submission_is_rejected_and_result_notified_once(self):
        assessment_id, candidate_id, recruiter_id, job_id = (
            ObjectId(), ObjectId(), ObjectId(), ObjectId()
        )
        assessment, key = complete_assessment(
            assessment_id, candidate_id, recruiter_id, job_id
        )
        db = FakeDatabase({
            ASSESSMENTS: FakeCollection([assessment]),
            ASSESSMENT_ANSWER_KEYS: FakeCollection([{"_id": assessment_id, "answers": key}]),
            JOBS: FakeCollection([{"_id": job_id, "title": "Python Developer"}]),
            NOTIFICATIONS: FakeCollection(),
        })
        user = {"id": str(candidate_id), "role": "candidate"}
        result = await submit_assessment(
            str(assessment_id),
            AssessmentAnswersInput(answers={f"q{number}": 0 for number in range(30)}),
            user,
            db,
        )
        self.assertEqual(result["result"], "pass")
        self.assertEqual(len(db[NOTIFICATIONS].documents), 2)
        with self.assertRaises(HTTPException) as raised:
            await submit_assessment(
                str(assessment_id),
                AssessmentAnswersInput(),
                user,
                db,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(db[NOTIFICATIONS].documents), 2)


if __name__ == "__main__":
    unittest.main()
