import io
import unittest
from unittest.mock import patch

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.dependencies import candidate_required, get_database
from app.routers.ocr import router
from app.services import resume_ocr


def create_pdf(pages):
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    contents = document.tobytes()
    document.close()
    return contents


def create_image():
    image = Image.new("RGB", (500, 140), "white")
    ImageDraw.Draw(image).text((20, 45), "Resume OCR image sample", fill="black")
    contents = io.BytesIO()
    image.save(contents, format="PNG")
    return contents.getvalue()


class ResumeOCRServiceTests(unittest.TestCase):
    def test_selectable_pdf_text_does_not_load_ocr(self):
        contents = create_pdf(["Ada Lovelace Software Engineer"])

        with patch.object(resume_ocr, "_recognize_image") as recognize:
            result = resume_ocr.extract_resume("resume.pdf", contents)

        self.assertIn("Ada Lovelace", result["extracted_text"])
        self.assertEqual(result["extraction_method"], "selectable_text")
        self.assertEqual(result["page_count"], 1)
        recognize.assert_not_called()

    def test_scanned_pdf_uses_ocr(self):
        contents = create_pdf([""])

        with patch.object(
            resume_ocr, "_recognize_image", return_value="Scanned resume content"
        ) as recognize:
            result = resume_ocr.extract_resume("scanned.pdf", contents)

        self.assertEqual(result["extracted_text"], "Scanned resume content")
        self.assertEqual(result["extraction_method"], "paddle_ocr")
        recognize.assert_called_once()

    def test_image_uses_ocr(self):
        with patch.object(
            resume_ocr, "_recognize_image", return_value="Image resume content"
        ) as recognize:
            result = resume_ocr.extract_resume("resume.png", create_image())

        self.assertEqual(result["extracted_text"], "Image resume content")
        self.assertEqual(result["extraction_method"], "paddle_ocr")
        self.assertIsNone(result["page_count"])
        recognize.assert_called_once()

    def test_rejects_unsupported_file_type(self):
        with self.assertRaises(resume_ocr.UnsupportedResumeFormat):
            resume_ocr.extract_resume("resume.docx", b"not a resume")

    def test_rejects_empty_and_unreadable_files(self):
        with self.assertRaisesRegex(resume_ocr.ResumeOCRInputError, "empty"):
            resume_ocr.extract_resume("resume.pdf", b"")
        with self.assertRaisesRegex(resume_ocr.ResumeOCRInputError, "invalid"):
            resume_ocr.extract_resume("resume.pdf", b"not a PDF")

    def test_multiple_pages_preserve_page_order_and_method(self):
        contents = create_pdf(["Selectable first page content", ""])

        with patch.object(
            resume_ocr, "_recognize_image", return_value="OCR second page content"
        ):
            result = resume_ocr.extract_resume("multi-page.pdf", contents)

        self.assertEqual(result["page_count"], 2)
        self.assertEqual(
            result["extraction_method"], "selectable_text_and_paddle_ocr"
        )
        self.assertLess(
            result["extracted_text"].index("first page"),
            result["extracted_text"].index("second page"),
        )


class ResumeOCRRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[candidate_required] = lambda: {
            "id": "0123456789abcdef01234567",
            "role": "candidate",
        }
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_extract_endpoint_returns_structured_pdf_response(self):
        contents = create_pdf(["Grace Hopper Engineer"])
        response = self.client.post(
            "/api/ocr/extract",
            files={"file": ("resume.pdf", contents, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], "resume.pdf")
        self.assertEqual(result["extraction_method"], "selectable_text")
        self.assertEqual(result["page_count"], 1)
        self.assertIn("Grace Hopper", result["extracted_text"])

    def test_extract_endpoint_reports_invalid_and_unsupported_files(self):
        unsupported = self.client.post(
            "/api/ocr/extract",
            files={"file": ("resume.docx", b"content")},
        )
        unreadable = self.client.post(
            "/api/ocr/extract",
            files={"file": ("resume.pdf", b"not a PDF")},
        )

        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(unreadable.status_code, 422)

    def test_extract_endpoint_enforces_upload_size_limit(self):
        with patch.object(settings, "max_upload_size_mb", 0):
            response = self.client.post(
                "/api/ocr/extract",
                files={"file": ("resume.pdf", b"oversized")},
            )

        self.assertEqual(response.status_code, 413)

    def test_extract_endpoint_requires_candidate_authentication(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: None
        with TestClient(app) as client:
            response = client.post(
                "/api/ocr/extract",
                files={"file": ("resume.pdf", create_pdf(["Private resume content"]))},
            )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
