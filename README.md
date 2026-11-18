# SkillSphere

SkillSphere is a full-stack career and recruitment platform using React, FastAPI, and PostgreSQL. The repository is split into Backend and Frontend.

## What is implemented

- Candidate and recruiter registration/login with Argon2 password hashing, JWT auth, role checks, token-invalidating logout, SMTP-based password reset, account status, and admin bootstrap from environment variables.
- Candidate profile editing and dashboard, document-based profile prefill with reviewed OCR results, resume uploads with size/type checks, private downloads, asynchronous PDF/image OCR, and analysis history.
- Job publishing/search/detail, saved jobs, application submission with duplicate protection, application tracking and withdrawal.
- Recruiter company profile, job management, applicant review, resume access, and application status changes.
- Application notifications, admin analytics with live monthly trends, user activation, job moderation, and company listing.
- Dark/light theme persistence, responsive navigation, public landing and job pages, and role-specific dashboards.

OCR uses PyMuPDF for PDF text/raster processing and Tesseract via pytesseract for scanned PDFs and images. Install the Tesseract application and put it on PATH for image OCR. Text-based PDFs do not require Tesseract.

## Start the backend

Use Python 3.10 or newer.

    cd Backend
    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    Copy-Item .env.example .env
    # Set a private JWT_SECRET_KEY of at least 32 characters in .env
    # Set DATABASE_URL to your PostgreSQL connection string
    # For an admin account, set ADMIN_EMAIL and ADMIN_PASSWORD
    pip install -r requirements.txt
    uvicorn app.main:app --reload

The API is at http://127.0.0.1:8000; interactive API docs are at /docs. The backend can start while PostgreSQL is unavailable, but database workflows require a connection. /api/health/ready checks database readiness. Apply schema migrations with `alembic upgrade head`.

## Start the frontend

In a second terminal:

    cd Frontend
    Copy-Item .env.example .env.local
    npm install
    npm run dev

Vite prints the local URL. The default API address is http://127.0.0.1:8000/api. To change it, update VITE_API_URL in Frontend/.env.local.

## Database and initial admin

The default local database name is skillsphere_db. Apply additive schema migrations with `alembic upgrade head`. For a first admin, set ADMIN_EMAIL and ADMIN_PASSWORD in Backend/.env, then restart the backend. Admin registration is not public. Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, and optional SMTP_FROM_NAME to enable password-reset, interview, and shortlisting email delivery.

## Neon Postgres

The backend uses its existing FastAPI, SQLAlchemy async, and asyncpg stack. Neon CLI writes branch connection variables to the root `.env.local`, which is ignored by Git. The backend loads that file after `Backend/.env`, so Neon connection values take precedence without replacing SMTP, JWT, Cloudinary, or AI settings. Web requests use Neon’s pooled `DATABASE_URL`; Alembic uses `DATABASE_URL_UNPOOLED` for schema migrations. Both connection URL formats are normalized for asyncpg.

After provisioning the Neon branch, run `alembic upgrade head` from `Backend` (or activate the backend environment and run the same command), then start the API as usual.

## Demo job listings

To populate an empty job board with eight clearly labeled, browse-only sample listings:

    cd Backend
    .\.venv\Scripts\python.exe -m app.database.demo_jobs

The command is idempotent and skips seeding when real published jobs already exist. Demo roles can be searched and viewed, but cannot be saved or applied to; admin job totals and candidate recommendations exclude them.

## Checks

Backend smoke checks (with the API server running):

    cd Backend
    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Frontend production build:

    npm run build

Backend tests and their latest results are listed in Backend/tests/TEST_RESULTS.md. Database-backed workflows require a reachable PostgreSQL instance. Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, and optional SMTP_FROM_NAME in Backend/.env to enable interview, shortlisting, and password-reset emails.

## Security notes

- .env, generated uploads, virtual environments, npm packages, and build output are excluded by .gitignore.
- JWT signing secret must be private and at least 32 characters.
- Password hashes are never returned by API endpoints.
- Resume files are stored under opaque generated names and served only after ownership checks.
- Recruiter access is scoped to their own jobs and applications.
- Do not use this local starter configuration as a public production deployment without HTTPS, rate limiting, audit logging, robust email verification, and a managed secret store.
