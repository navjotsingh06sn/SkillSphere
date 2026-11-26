from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class RegisterInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["candidate", "recruiter"]


class LoginInput(BaseModel):
    email: str
    password: str


class ForgotPasswordInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class ResetPasswordInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class AccountSettingsInput(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    email: str | None = Field(default=None, min_length=5, max_length=254)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=120)
    headline: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=2000)
    skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[dict] = Field(default_factory=list, max_length=30)
    experience: list[dict] = Field(default_factory=list, max_length=30)
    projects: list[dict] = Field(default_factory=list, max_length=30)
    certifications: list[dict] = Field(default_factory=list, max_length=30)
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None


class CompanyInput(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=5000)
    website: str | None = None
    industry: str | None = None
    location: str | None = None
    contact_email: str | None = None


class ActiveCompanyInput(BaseModel):
    company_id: UUID


class JobInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=10, max_length=12000)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    location: str = Field(min_length=2, max_length=160)
    experience_requirement: str | None = Field(default=None, max_length=120)
    job_type: str = "Full-time"
    expected_salary: str | None = Field(default=None, max_length=160)
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    application_deadline: datetime | None = None
    status: Literal["draft", "published", "closed"] = "draft"

    @field_validator("experience_requirement", "expected_salary", mode="before")
    @classmethod
    def normalize_optional_job_text(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class ApplicationStatusInput(BaseModel):
    status: Literal[
        "under_review",
        "shortlisted",
        "interview",
        "selected",
        "rejected",
    ]
    rejection_reason: str | None = Field(default=None, max_length=1000)


class ReconsiderationInput(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class InterviewScheduleInput(BaseModel):
    interview_type: Literal[
        "technical",
        "hr",
        "managerial",
        "other",
    ] = "technical"

    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=15, le=240)

    mode: Literal["in_platform", "offline"] = "in_platform"
    meeting_link: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class InterviewRescheduleInput(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=15, le=240)
    mode: Literal["in_platform", "offline"] | None = None
    meeting_link: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class InterviewResponseInput(BaseModel):
    response: Literal["accepted", "declined"]


class AssessmentAnswersInput(BaseModel):
    answers: dict[str, StrictInt] = Field(default_factory=dict, max_length=30)


class SecondRoundDecisionInput(BaseModel):
    decision: Literal["invited", "not_invited"]
