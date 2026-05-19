import os
from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).resolve().parent

    # Server settings
    HOST = os.getenv("BAYOU_HOST", "0.0.0.0")
    PORT = int(os.getenv("BAYOU_PORT", "8000"))
    DEBUG = os.getenv("BAYOU_DEBUG", "false").lower() == "true"

    # Security and session settings
    SECRET_KEY = os.getenv("BAYOU_SECRET_KEY", "change-this-in-production")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("BAYOU_SECURE_COOKIE", "false").lower() == "true"

    # Database and app behavior
    DATABASE_PATH = os.getenv("BAYOU_DATABASE_PATH", str(BASE_DIR / "data" / "bayou_bombers.db"))
    POLL_SECONDS = int(os.getenv("BAYOU_POLL_SECONDS", "20"))
    MAX_FORM_TEXT = int(os.getenv("BAYOU_MAX_FORM_TEXT", "1000"))

    # Bootstrap admin options (password is always hashed in DB)
    ADMIN_DEFAULT_USERNAME = os.getenv("BAYOU_ADMIN_USERNAME", "admin")
    ADMIN_DEFAULT_PASSWORD = os.getenv("BAYOU_ADMIN_PASSWORD", "ChangeMeNow!")
