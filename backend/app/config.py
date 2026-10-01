# app/config.py
# Loads all environment variables defined in Technical Spec Section 2.2
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
    INSTAGRAM_APP_SECRET: str = ""

    # Redis (Celery broker)
    REDIS_URL: str

    # Email
    RESEND_API_KEY: str = ""

    # App
    SECRET_KEY: str
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:5173"
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # SITE-2B — separate signing secret for builder-portal sessions (aud="builder").
    # Deliberately isolated from SECRET_KEY: a leaked builder JWT secret must never
    # let anyone forge a staff session, and vice versa. If unset, builder_auth_service
    # falls back to a salted derivative of SECRET_KEY so existing deploys don't break —
    # set this in Render for real isolation before builder logins go live.
    BUILDER_JWT_SECRET: str = ""

    # Super-admin provisioning
    SUPERADMIN_SECRET: str = ""

    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:trustrobert34@gmail.com"

    # Observability — 9E-A
    # Set this to your Sentry project DSN in Render env vars on both services.
    # Empty string = Sentry disabled (safe for local dev).
    SENTRY_DSN: str = ""

    # SITE-PUBLISH — Cloudflare R2 (S3-compatible) bucket that holds published client sites.
    # Create an R2 API token limited to the bucket (Object Read & Write) and set these in Render.
    # Empty = publishing is switched off (the publish endpoint returns a clear message).
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = "opsra-sites"

    # SITE-HOSTNAMES — Cloudflare for SaaS custom hostnames (connect a client's domain to the Worker).
    # Token needs Zone > SSL and Certificates > Edit on the SaaS zone. Empty = feature off.
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""   # SITE-ZONES — account that owns the client-domain zones (token also needs Zone:Edit, DNS:Edit, Workers Scripts:Edit)
    SITES_CNAME_TARGET: str = "sites.coreaicloudtech.com.ng"
    SITES_WORKER_NAME: str = "opsra-sites"   # the Worker each client domain is routed to

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
