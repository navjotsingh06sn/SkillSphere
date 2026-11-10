from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_mongodb, connect_to_mongodb
from app.routers import admin, applications, auth, candidates, health, jobs, matching, notifications, ocr, recruiter, resumes
from app.rate_limit import SensitiveRouteRateLimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongodb(app)
    yield
    await close_mongodb(app)


app = FastAPI(
    title=settings.app_name,
    description="SkillSphere career and recruitment platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(SensitiveRouteRateLimit)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(candidates.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(ocr.router, prefix="/api")
app.include_router(matching.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(recruiter.router, prefix="/api")
app.include_router(admin.router, prefix="/api")



