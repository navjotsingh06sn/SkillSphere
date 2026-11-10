# SkillSphere

SkillSphere is a full-stack career and recruitment platform using React, FastAPI, and MongoDB. The repository is split into Backend and Frontend.

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
    # Set MONGODB_URL to local MongoDB or your Atlas URI
    # For an admin account, set ADMIN_EMAIL and ADMIN_PASSWORD
    pip install -r requirements.txt
    uvicorn app.main:app --reload

The API is at http://127.0.0.1:8000; interactive API docs are at /docs. The backend can start while MongoDB is unavailable, but database workflows require a connection. /api/health/ready checks MongoDB and prepares the indexes.

## Start the frontend

In a second terminal:

    cd Frontend
    Copy-Item .env.example .env.local
    npm install
    npm run dev

Vite prints the local URL. The default API address is http://127.0.0.1:8000/api. To change it, update VITE_API_URL in Frontend/.env.local.

## Database and initial admin

The default local database name is skillsphere_db. Collections and indexes are created idempotently when MongoDB becomes reachable. For a first admin, set ADMIN_EMAIL and ADMIN_PASSWORD in Backend/.env, then restart the backend. Admin registration is not public. Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL to enable password-reset email delivery.

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

    cd Frontend
    npm run build

Five API smoke cases and their latest actual results are listed in Backend/tests/TEST_RESULTS.md. Full database workflows need a reachable MongoDB instance; the current development machine does not have mongod installed and no Atlas URI has been configured.

## Security notes

- .env, generated uploads, virtual environments, npm packages, and build output are excluded by .gitignore.
- JWT signing secret must be private and at least 32 characters.
- Password hashes are never returned by API endpoints.
- Resume files are stored under opaque generated names and served only after ownership checks.
- Recruiter access is scoped to their own jobs and applications.
- Do not use this local starter configuration as a public production deployment without HTTPS, rate limiting, audit logging, robust email verification, and a managed secret store.
