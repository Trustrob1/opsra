from dotenv import load_dotenv
load_dotenv()
import sentry_sdk
from app.config import settings

sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT)
sentry_sdk.capture_message("Sentry test from Opsra backend")
sentry_sdk.flush(timeout=10)  # wait up to 10 seconds
print("Done — check your Sentry dashboard")