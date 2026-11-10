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

Text in PDFs is extracted directly. Scanned PDFs and image files use the Tesseract executable through pytesseract. Install the Tesseract application and make it available on PATH to enable OCR for scans.

## Tests

With the API running, execute:

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

See tests/TEST_RESULTS.md for the observed smoke-check results and the MongoDB limitation.
