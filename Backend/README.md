# SkillSphere API

FastAPI service and PostgreSQL data layer for the SkillSphere career platform.

## Start

From this folder:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    Copy-Item .env.example .env

Edit .env before starting:
- Use a private JWT_SECRET_KEY with at least 32 characters.
- Set DATABASE_URL to a PostgreSQL connection string.
- Optionally set ADMIN_EMAIL and ADMIN_PASSWORD to bootstrap the first admin.
- Interview invitations and shortlist notifications use the existing SMTP settings: SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, and optional SMTP_FROM_NAME.
- For Round 1 video uploads, set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET. Keep the API secret in Backend/.env only; do not add it to frontend environment variables.

Then run:

    pip install -r requirements.txt
    uvicorn app.main:app --reload

The API is at http://127.0.0.1:8000 and Swagger docs are at http://127.0.0.1:8000/docs.

Interview invitations and shortlist notifications use SMTP. If SMTP is unavailable or rejects a message, the database change remains saved and its email status and failure reason are tracked; only failed messages can be retried from the relevant recruiter view.

## Round 1 camera monitoring and recording

Candidates grant camera permission and explicit recording consent before starting or resuming a Round 1 attempt. Face-presence and multiple-face checks still run locally in the browser using MediaPipe. A video-only recording (no audio or screenshots) starts with the attempt and stops on submit or timeout. The browser keeps a local retry copy when browser storage permits, until Cloudinary confirms the upload; successful uploads are stored as authenticated Cloudinary assets. Only the recruiter responsible for the candidate’s application can request a five-minute playback URL. Recruiters can delete uploaded recordings from the assessment review page. Recordings remain until explicitly deleted; automatic expiration is not configured.

Cloudinary credentials are optional at startup. If they are missing or invalid, the API remains available, uploads show a failure state, and the candidate can retry after configuration. Add the three Cloudinary values to Backend/.env and install the backend requirements to enable uploads. The API key and signature are used only for the direct signed upload; the API secret never leaves the backend. Existing SMTP email delivery is unchanged. No Video Assessment or LiveKit recording pipeline is part of this Round 1 integration.

Apply the additive database migrations before using the assessment, proctoring, and recording APIs:

    alembic upgrade head

The server can start while PostgreSQL is unavailable. Database-backed API routes require PostgreSQL; /api/health/ready returns 503 until it is reachable. Apply schema changes with `alembic upgrade head`.

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

See tests/TEST_RESULTS.md for the latest test results and any database limitations.
