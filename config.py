import os
import sys
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-production")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB max upload

    # Job APIs
    RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
    ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
    ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
    SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

    # SMTP
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")

    # Intelligence — Claude API (cloud) or Ollama (local)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")  # e.g., "llama3", "mistral", "gemma2"

    # Database
    DB_PATH = os.getenv("DB_PATH", os.path.join("data", "db", "jobs.db"))

    # Upload
    ALLOWED_EXTENSIONS = {".pdf", ".docx"}

    @classmethod
    def validate(cls):
        warnings = []
        if cls.SECRET_KEY == "dev-secret-change-in-production":
            warnings.append("FLASK_SECRET_KEY is using default value - set it in .env for production")
        if not cls.RAPIDAPI_KEY:
            warnings.append("RAPIDAPI_KEY not set - JSearch API will be unavailable")
        if not cls.ADZUNA_APP_ID or not cls.ADZUNA_APP_KEY:
            warnings.append("Adzuna credentials not set - Adzuna API will be unavailable")
        if not cls.SERPAPI_KEY:
            warnings.append("SERPAPI_KEY not set - SerpApi (Google Jobs) will be unavailable")
        if not cls.SMTP_USER or not cls.SMTP_PASSWORD:
            warnings.append("SMTP credentials not set - email notifications will be unavailable")
        if not cls.ANTHROPIC_API_KEY and not cls.OLLAMA_MODEL:
            warnings.append("No AI provider configured (set ANTHROPIC_API_KEY or OLLAMA_MODEL) - will use heuristic matching")
        return warnings
