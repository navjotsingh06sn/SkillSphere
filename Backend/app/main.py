
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.cloudinary_storage import configure_cloudinary

from app.db import (
    connect_to_database,
    close_database,
)

from app.routers import (
    admin,
    assessments,
    applications,
    auth,
    candidates,
    chatbot,
    health,
    interviews,
    jobs,
    matching,
    notifications,
    ocr,
    proctoring,
    recruiter,
    resumes,
)

from app.rate_limit import SensitiveRouteRateLimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Connect to PostgreSQL when the application starts
    and close the connection when it shuts down.
    """

    configure_cloudinary()
    await connect_to_database(app)

    yield

    await close_database(app)


app = FastAPI(
    title="SkillSphere API",
    description="AI-powered recruitment and job matching platform",
    version="1.0.0",
    lifespan=lifespan,
)


# Sensitive route rate limiting
app.add_middleware(SensitiveRouteRateLimit)


# Register API routers
app.include_router(admin.router, prefix="/api")
app.include_router(assessments.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(candidates.router, prefix="/api")
app.include_router(chatbot.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(interviews.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(matching.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(ocr.router, prefix="/api")
app.include_router(proctoring.router, prefix="/api")
app.include_router(recruiter.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "message": "Welcome to SkillSphere API",
        "status": "running",
        "database": "PostgreSQL",
        "docs": "/docs",
    }


# Wrap the completed FastAPI app so CORS also decorates unhandled 500 responses.
# add_middleware alone sits inside ServerErrorMiddleware and cannot do that.
app = CORSMiddleware(
    app=app,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
