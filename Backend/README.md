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
    uvicorn app.main:app --reload --port 8013

The local API is at http://127.0.0.1:8013 and Swagger docs are at http://127.0.0.1:8013/docs.

## In-platform interviews and live coding

Apply migrations with `alembic upgrade head`. Newly scheduled online interviews default to the built-in SkillSphere room. The room uses browser WebRTC for one recruiter and one candidate; camera and microphone streams are not recorded. Candidates see a plain-language notice and must consent before joining. Tab/window focus, fullscreen exits, and code-editor copy/paste attempts are timestamped review signals, not proof of misconduct.

For live code execution, configure `JUDGE0_API_URL` to a trusted, isolated Judge0 CE deployment and optionally set `JUDGE0_API_KEY` (the server sends it only in the backend-to-runner request). `JUDGE0_LANGUAGE_IDS` maps enabled language names to IDs installed by that runner. The API enforces CPU, memory, wall-time, source-size, and test-count limits. Without Judge0 configured, interview/video still work and code execution returns an unavailable message. Never point this setting at an untrusted runner.

WebRTC peer-to-peer calls can fail across restrictive NATs. For production availability, deploy TURN (for example, coturn) and provide short-lived TURN credentials to the browser through an authenticated credential endpoint; do not place a TURN shared secret in `VITE_*` variables. The current room signaling hub is process-local, so run one API worker for rooms until the hub is moved to Redis/pub-sub. A self-hosted TURN service and Judge0 runner are infrastructure requirements, not bundled with SkillSphere.

Interview invitations and shortlist notifications use SMTP. If SMTP is unavailable or rejects a message, the database change remains saved and its email status and failure reason are tracked; only failed messages can be retried from the relevant recruiter view.

## Round 1 camera monitoring and recording

Candidates grant camera and screen-share permission and explicit consent before starting or resuming a Round 1 attempt. Face-presence and multiple-face checks still run locally in the browser using MediaPipe. Camera video recording starts with the attempt and stops on submit or timeout. The assessment never submits because of warnings; it continues until the candidate submits or the server-enforced deadline expires. Tab/window focus losses and proctoring warnings are timestamped. The browser keeps a local retry copy when browser storage permits, until Cloudinary confirms the upload; successful uploads are stored as authenticated Cloudinary assets. Only the recruiter responsible for the candidate’s application can request a five-minute playback URL. Recruiters can delete uploaded recordings from the assessment review page. Recordings remain until explicitly deleted; automatic expiration is not configured.

Cloudinary credentials are optional at startup. If they are missing or invalid, the API remains available, uploads show a failure state, and the candidate can retry after configuration. Add the three Cloudinary values to Backend/.env and install the backend requirements to enable uploads. The API key and signature are used only for the direct signed upload; the API secret never leaves the backend. Existing SMTP email delivery is unchanged. No Video Assessment or LiveKit recording pipeline is part of this Round 1 integration.

Apply the additive database migrations before using the assessment, proctoring, and recording APIs:

    alembic upgrade head

The server can start while PostgreSQL is unavailable. Database-backed API routes require PostgreSQL; /api/health/ready returns 503 until it is reachable. Apply schema changes with `alembic upgrade head`.

## OCR

The existing saved-resume upload and reprocessing routes remain unchanged and continue to use Tesseract for scanned files. The candidate resume page also has a separate quick OCR option that extracts text without saving the uploaded file.

The quick OCR route uses PaddleOCR 3.x on CPU. It extracts selectable PDF text directly and uses the lightweight PP-OCRv5 mobile models for scanned PDF pages and PNG/JPG/JPEG images. Model weights are loaded the first time OCR is needed and cached for later requests. The route processes one document at a time and accepts files up to the configured upload limit.

Use the same `.venv` environment for the API and OCR. It includes both PaddleOCR and the Cloudinary SDK required for private assessment video uploads:

    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt

Start FastAPI in that activated environment:

    uvicorn app.main:app --reload

To try the API, open http://127.0.0.1:8013/docs, authorize with a candidate account, and submit a PDF, PNG, JPG, or JPEG to `POST /api/ocr/extract`. The first OCR request may download the model weights; selectable-text PDFs do not need to initialize the OCR models.

To try it from the frontend, sign in as a candidate, open **My resume** at `/candidate/resume`, and use the **Quick OCR** panel. This extracts text for review without adding a file to resume history; the existing **Upload a resume** form still uses the saved-resume workflow.

## Tests

With the API running, execute:

    python -m unittest discover -s tests -v

See tests/TEST_RESULTS.md for the latest test results and any database limitations.


### Proctoring evidence

During an active attempt, the candidate camera and shared assessment screen are captured every 30 seconds and when a suspicious action is recorded. Audio is not captured in the video. Evidence images are stored on the backend server in the private folder configured by `PROCTORING_EVIDENCE_DIR` (default: `Backend/private_proctoring_evidence`) and are served only through recruiter-authenticated, assessment-owner-checked API routes. Configure this path on a persistent private volume in production; the default container filesystem may not persist across redeployments. The additive migration `4e5f6a7b8c9d_add_proctoring_evidence.py` must be applied with `alembic upgrade head`. Recruiter review shows warning totals, timestamps, descriptions, and images; names with five or more warnings are highlighted.
