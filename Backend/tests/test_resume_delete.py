import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import candidate_required, get_database
from app.routers.resumes import router


class ResumeDeleteTests(unittest.TestCase):
    candidate_id = ObjectId("0123456789abcdef01234567")
    resume_id = ObjectId("abcdef0123456789abcdef01")

    def setUp(self):
        self.collection = SimpleNamespace(
            find_one=AsyncMock(),
            delete_one=AsyncMock(),
        )
        collection = self.collection

        class FakeDatabase:
            def __getitem__(self, _name):
                return collection

        database = FakeDatabase()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[candidate_required] = lambda: {
            "id": str(self.candidate_id),
            "role": "candidate",
        }
        app.dependency_overrides[get_database] = lambda: database
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_deletes_owned_resume_file_and_record(self):
        with tempfile.TemporaryDirectory() as upload_directory:
            file_path = Path(upload_directory) / "stored-resume.pdf"
            file_path.write_bytes(b"%PDF-1.7")
            self.collection.find_one.return_value = {
                "_id": self.resume_id,
                "candidate_id": self.candidate_id,
                "storage_name": file_path.name,
            }
            self.collection.delete_one.return_value = SimpleNamespace(deleted_count=1)

            with patch.object(settings, "upload_directory", upload_directory):
                response = self.client.delete(f"/api/resumes/{self.resume_id}")

            self.assertEqual(response.status_code, 204)
            self.assertFalse(file_path.exists())
            self.collection.find_one.assert_awaited_once_with({
                "_id": self.resume_id,
                "candidate_id": self.candidate_id,
            })
            self.collection.delete_one.assert_awaited_once_with({
                "_id": self.resume_id,
                "candidate_id": self.candidate_id,
            })

    def test_cannot_delete_another_candidates_resume(self):
        self.collection.find_one.return_value = None

        with tempfile.TemporaryDirectory() as upload_directory:
            with patch.object(settings, "upload_directory", upload_directory):
                response = self.client.delete(f"/api/resumes/{self.resume_id}")

        self.assertEqual(response.status_code, 404)
        self.collection.delete_one.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
