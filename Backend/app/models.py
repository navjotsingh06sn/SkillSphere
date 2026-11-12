
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# ==================================================
# COMMON HELPERS
# ==================================================

def uuid_pk():
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


def utc_now():
    return datetime.now(timezone.utc)


# ==================================================
# 1. USERS
# ==================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    password_reset_token_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 2. CANDIDATE PROFILES
# ==================================================

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    education: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    experience: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    projects: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    certifications: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    links: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 3. COMPANIES
# ==================================================

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(255))
    logo_url: Mapped[str | None] = mapped_column(String(500))

    extra_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==================================================
# 4. RECRUITER PROFILES
# ==================================================

class RecruiterProfile(Base):
    __tablename__ = "recruiter_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )

    designation: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 5. JOBS
# ==================================================

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()

    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    company_name: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    job_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)

    responsibilities: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    requirements: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    required_skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )

    experience_min: Mapped[int | None] = mapped_column(Integer)
    experience_max: Mapped[int | None] = mapped_column(Integer)

    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str] = mapped_column(
        String(30), default="draft", index=True, nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    extra_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 6. RESUMES
# ==================================================

class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = uuid_pk()

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    file_name: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_type: Mapped[str | None] = mapped_column(String(50))

    status: Mapped[str] = mapped_column(
        String(30), default="pending", index=True, nullable=False
    )

    raw_text: Mapped[str | None] = mapped_column(Text)
    extracted_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==================================================
# 7. RESUME ANALYSES
# ==================================================

class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id: Mapped[uuid.UUID] = uuid_pk()

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
    )

    match_percentage: Mapped[float | None] = mapped_column(Float)

    matched_skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    missing_skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    additional_skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    recommendations: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )

    explanation: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==================================================
# 8. APPLICATIONS
# ==================================================

class Application(Base):
    __tablename__ = "applications"

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "job_id",
            name="uq_candidate_job_application",
        ),
        Index(
            "ix_application_recruiter_screening",
            "recruiter_id",
            "screening_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )

    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_analyses.id", ondelete="SET NULL")
    )

    match_score: Mapped[float | None] = mapped_column(Float)
    screening_threshold: Mapped[float | None] = mapped_column(Float)

    screening_status: Mapped[str] = mapped_column(
        String(40), default="pending_review", index=True, nullable=False
    )

    screening_reasons: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(40), default="applied", index=True, nullable=False
    )

    recruiter_decision: Mapped[str | None] = mapped_column(String(40))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    reconsideration_status: Mapped[str | None] = mapped_column(String(40))
    reconsideration_reason: Mapped[str | None] = mapped_column(Text)

    reconsideration_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 9. SAVED JOBS
# ==================================================

class SavedJob(Base):
    __tablename__ = "saved_jobs"

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "job_id",
            name="uq_saved_candidate_job",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==================================================
# 10. NOTIFICATIONS
# ==================================================

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    related_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True)
    )

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )

    match_score: Mapped[float | None] = mapped_column(Float)
    screening_status: Mapped[str | None] = mapped_column(String(40))

    missing_skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==================================================
# 11. INTERVIEWS
# ==================================================

class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = uuid_pk()

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    interview_type: Mapped[str | None] = mapped_column(String(40))
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    location: Mapped[str | None] = mapped_column(String(500))
    meeting_link: Mapped[str | None] = mapped_column(String(1000))

    status: Mapped[str] = mapped_column(
        String(40), default="scheduled", nullable=False
    )

    candidate_response: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)

    extra_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 12. QUESTION BANK QUESTIONS
# ==================================================

class QuestionBankQuestion(Base):
    __tablename__ = "question_bank_questions"

    id: Mapped[uuid.UUID] = uuid_pk()

    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    technology: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(
        String(150), nullable=False, index=True
    )

    difficulty: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)

    correct_option: Mapped[str] = mapped_column(
        String(10), nullable=False
    )

    explanation: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 13. ASSESSMENTS
# ==================================================

class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = uuid_pk()

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(40), default="pending", nullable=False
    )

    total_questions: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )

    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )

    passing_percentage: Mapped[float] = mapped_column(
        Float, default=70, nullable=False
    )

    score: Mapped[float | None] = mapped_column(Float)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    extra_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


# ==================================================
# 14. ASSESSMENT QUESTIONS
# ==================================================

class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    __table_args__ = (
        UniqueConstraint(
            "assessment_id",
            "order_number",
            name="uq_assessment_question_order",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    question_bank_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_bank_questions.id", ondelete="SET NULL")
    )

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)

    difficulty: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    order_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )


# ==================================================
# 15. ASSESSMENT ANSWER KEYS
# ==================================================

class AssessmentAnswerKey(Base):
    __tablename__ = "assessment_answer_keys"

    id: Mapped[uuid.UUID] = uuid_pk()

    assessment_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    correct_option: Mapped[str] = mapped_column(
        String(10), nullable=False
    )

    explanation: Mapped[str | None] = mapped_column(Text)


# ==================================================
# 16. ASSESSMENT ANSWERS
# ==================================================

class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"

    __table_args__ = (
        UniqueConstraint(
            "assessment_question_id",
            name="uq_assessment_answer_question",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    assessment_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE"),
        nullable=False,
    )

    selected_option: Mapped[str | None] = mapped_column(String(10))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)

    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
