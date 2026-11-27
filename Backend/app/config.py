
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIRECTORY = Path(__file__).resolve().parent.parent
PROJECT_DIRECTORY = BACKEND_DIRECTORY.parent


class Settings(BaseSettings):
    app_name: str = "SkillSphere API"

    database_url: str = Field(min_length=1)
    database_url_unpooled: str | None = None

    frontend_url: str = "http://127.0.0.1:5173"

    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    max_upload_size_mb: int = 10
    upload_directory: str = "uploads"

    admin_email: str = ""
    admin_password: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

    smtp_from_name: str = "SkillSphere"
    resend_api_key: str = ""
    resend_from_email: str = ""

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    assessment_ai_base_url: str = ""
    assessment_ai_api_key: str = ""
    assessment_ai_model: str = ""
    assessment_ai_timeout_seconds: int = 45

    chatbot_ai_base_url: str = ""
    chatbot_ai_api_key: str = ""
    chatbot_ai_model: str = ""
    chatbot_ai_timeout_seconds: int = 30

    # Interview code always runs in an isolated Judge0-compatible service.
    judge0_api_url: str = ""
    judge0_api_key: str = ""
    judge0_language_ids: str = '{"python":71,"javascript":63,"cpp":54,"java":62,"go":60,"c":50,"csharp":51,"php":68,"ruby":72,"rust":73,"typescript":74,"bash":46}'
    interview_room_ticket_seconds: int = 90
    interview_stun_urls: str = "stun:stun.l.google.com:19302"
    interview_turn_urls: str = ""
    interview_turn_shared_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIRECTORY / ".env", PROJECT_DIRECTORY / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
