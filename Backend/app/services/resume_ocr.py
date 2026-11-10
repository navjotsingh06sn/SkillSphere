import logging
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, TypedDict

import pymupdf
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_IMAGE_PIXELS = 30_000_000
MAX_IMAGE_SIDE = 2400
MIN_MEANINGFUL_CHARACTERS = 10

_DOCUMENT_LOCK = threading.Lock()


class ResumeExtraction(TypedDict):
    extracted_text: str
    extraction_method: str
    page_count: int | None


class ResumeOCRInputError(ValueError):
    pass


class UnsupportedResumeFormat(ResumeOCRInputError):
    pass


class ResumeOCREngineError(RuntimeError):
    pass


def _clean_text(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line).strip()


def _has_meaningful_text(text: str) -> bool:
    return sum(character.isalnum() for character in text) >= MIN_MEANINGFUL_CHARACTERS


@lru_cache(maxsize=1)
def _get_ocr_engine() -> Any:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise ResumeOCREngineError(
            "PaddleOCR is unavailable. Activate the PaddleOCR environment and install the backend requirements."
        ) from exc

    try:
        return PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="en_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device="cpu",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Could not initialize the PaddleOCR resume models.")
        raise ResumeOCREngineError(
            "PaddleOCR could not initialize its CPU models. Check the model download and backend logs."
        ) from exc


def _recognize_image(image: Image.Image) -> str:
    engine = _get_ocr_engine()
    try:
        import numpy as np
    except ImportError as exc:
        raise ResumeOCREngineError(
            "NumPy is unavailable. Install the PaddleOCR backend requirements."
        ) from exc

    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    with image.convert("RGB") as rgb_image:
        bgr_image = np.asarray(rgb_image)[:, :, ::-1].copy()

    try:
        predictions = engine.predict(bgr_image)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("PaddleOCR failed while extracting resume text.")
        raise ResumeOCREngineError(
            "PaddleOCR could not process this document. Check the backend logs and try again."
        ) from exc

    recognized_lines = []
    for prediction in predictions:
        recognized_lines.extend(prediction.get("rec_texts", []))
    return _clean_text("\n".join(str(line) for line in recognized_lines))


def _render_pdf_page(page: pymupdf.Page) -> Image.Image:
    page_size = max(page.rect.width, page.rect.height)
    if page_size <= 0:
        raise ResumeOCRInputError("The PDF contains an unreadable page.")

    scale = min(1.5, MAX_IMAGE_SIDE / page_size)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _extract_pdf(contents: bytes) -> ResumeExtraction:
    try:
        document = pymupdf.open(stream=contents, filetype="pdf")
    except (pymupdf.FileDataError, OSError) as exc:
        raise ResumeOCRInputError("The PDF is invalid or unreadable.") from exc

    with document:
        if document.is_encrypted:
            raise ResumeOCRInputError("Password-protected PDFs are not supported.")
        if not document.page_count:
            raise ResumeOCRInputError("The PDF does not contain any pages.")

        page_texts = []
        used_selectable_text = False
        used_ocr = False

        for page in document:
            selectable_text = _clean_text(page.get_text("text"))
            if _has_meaningful_text(selectable_text):
                page_texts.append(selectable_text)
                used_selectable_text = True
                continue

            with _render_pdf_page(page) as page_image:
                page_texts.append(_recognize_image(page_image))
            used_ocr = True

        extracted_text = _clean_text("\n\n".join(page_texts))
        if not extracted_text:
            raise ResumeOCRInputError("No readable text was found in the PDF.")

        if used_selectable_text and used_ocr:
            method = "selectable_text_and_paddle_ocr"
        elif used_ocr:
            method = "paddle_ocr"
        else:
            method = "selectable_text"

        return {
            "extracted_text": extracted_text,
            "extraction_method": method,
            "page_count": document.page_count,
        }


def _extract_image(contents: bytes) -> ResumeExtraction:
    try:
        with Image.open(BytesIO(contents)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ResumeOCRInputError(
                    "The image resolution is too large to process safely."
                )
            image.load()
            with image.convert("RGB") as rgb_image:
                extracted_text = _recognize_image(rgb_image)
    except ResumeOCRInputError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as exc:
        raise ResumeOCRInputError("The image is invalid or unreadable.") from exc

    if not extracted_text:
        raise ResumeOCRInputError("No readable text was found in the image.")

    return {
        "extracted_text": extracted_text,
        "extraction_method": "paddle_ocr",
        "page_count": None,
    }


def extract_resume(filename: str, contents: bytes) -> ResumeExtraction:
    if not contents:
        raise ResumeOCRInputError("The uploaded file is empty.")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedResumeFormat(
            "Unsupported file type. Upload a PDF, PNG, JPG, or JPEG file."
        )

    with _DOCUMENT_LOCK:
        if extension == ".pdf":
            return _extract_pdf(contents)
        return _extract_image(contents)
