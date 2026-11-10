# SkillSphere API

FastAPI service and MongoDB layer for the SkillSphere career platform.

## Start

From this folder:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    Copy-Item .env.example .env

Edit .env before starting:
- Use a private JWT_SECRET_KEY with at least 32 characters.
- Set MONGODB_URL to local MongoDB or a MongoDB Atlas URI.
- Optionally set ADMIN_EMAIL and ADMIN_PASSWORD to bootstrap the first admin.

Then run:

    pip install -r requirements.txt
    uvicorn app.main:app --reload

The API is at http://127.0.0.1:8000 and Swagger docs are at http://127.0.0.1:8000/docs.

The server can start while MongoDB is down. Database-backed API routes require MongoDB; /api/health/ready returns 503 until a database can be reached and indexed.

## OCR

The existing saved-resume upload and reprocessing routes remain unchanged and continue to use Tesseract for scanned files. The candidate resume page also has a separate quick OCR option that extracts text without saving the uploaded file.

The quick OCR route uses PaddleOCR 3.x on CPU. It extracts selectable PDF text directly and uses the lightweight PP-OCRv5 mobile models for scanned PDF pages and PNG/JPG/JPEG images. Model weights are loaded the first time OCR is needed and cached for later requests. The route processes one document at a time and accepts files up to the configured upload limit.

From this folder, activate the PaddleOCR environment and install the backend requirements:

    .\paddle_env\Scripts\Activate.ps1
    python -m pip install -r requirements.txt

Start FastAPI in that activated environment:

    uvicorn app.main:app --reload

To try the API, open http://127.0.0.1:8000/docs, authorize with a candidate account, and submit a PDF, PNG, JPG, or JPEG to `POST /api/ocr/extract`. The first OCR request may download the model weights; selectable-text PDFs do not need to initialize the OCR models.

To try it from the frontend, sign in as a candidate, open **My resume** at `/candidate/resume`, and use the **Quick OCR** panel. This extracts text for review without adding a file to resume history; the existing **Upload a resume** form still uses the saved-resume workflow.

## Tests

With the API running, execute:

    python -m unittest discover -s tests -v

See tests/TEST_RESULTS.md for the observed smoke-check results and the MongoDB limitation.
