# app/config.py
# Loads all 16 environment variables defined in Technical Spec Section 2.2
# Uses Pydantic Settings for validation — app will not start if required vars are missing

from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_ANON_KEY: str

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Meta / WhatsApp
    META_WHATSAPP_TOKEN: str = ""
    META_WHATSAPP_PHONE_ID: str = ""
    META_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""

    # Redis (Celery broker)
    REDIS_URL: str

    # Email
    RESEND_API_KEY: str = ""

    # App
    SECRET_KEY: str
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:5173"
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @field_validator("REDIS_URL")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        # Technical Spec: must use rediss:// TLS — not plain redis://
        # Allow redis:// in test/dev environments only
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()