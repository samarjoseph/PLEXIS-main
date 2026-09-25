"""Plexis configuration management."""
import os
import warnings
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration."""

    FLASK_PORT: int = int(os.environ.get("FLASK_PORT", "5000"))
    FLASK_DEBUG: bool = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "groq")

    # API Keys
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    MISTRAL_API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")

    # Gemini key rotation pool — primary + up to 3 fallback keys
    # Used by GeminiProvider to round-robin when a key hits rate limits.
    GEMINI_API_KEYS: List[str] = [
        k for k in [
            os.environ.get("GEMINI_API_KEY", ""),
            os.environ.get("GEMINI_API_KEY_2", ""),
            os.environ.get("GEMINI_API_KEY_3", ""),
            os.environ.get("GEMINI_API_KEY_4", ""),
        ] if k
    ]

    # PRIMARY: openai/gpt-oss-20b — conversation, planner, all standard tasks
    GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

    # FALLBACK: gpt-oss-120b — used when primary fails (Llama/Qwen decommissioned on Groq)
    GROQ_MODEL_FALLBACK: str = os.environ.get(
        "GROQ_MODEL_FALLBACK", "openai/gpt-oss-120b"
    )

    # HIGH-REASONING: GPT-OSS 120B — complex queries
    GROQ_MODEL_HIGH_REASONING: str = os.environ.get(
        "GROQ_MODEL_HIGH_REASONING", "openai/gpt-oss-120b"
    )

    # ── Temperature Policy ────────────────────────────────────────────────────
    # Planner MUST be 0.0 — analytical plans must be deterministic
    PLANNER_TEMPERATURE: float = float(os.environ.get("PLANNER_TEMPERATURE", "0.0"))
    # Conversation temperature — allows natural variation
    CONVERSATION_TEMPERATURE: float = float(os.environ.get("CONVERSATION_TEMPERATURE", "0.7"))

    MAX_UPLOAD_SIZE_MB: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "100"))
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")

    # Parse comma-separated CORS origins into a list
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:5174"
        ).split(",")
        if origin.strip()
    ]

    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "storage/uploads")
    # Ensure upload folder exists at config load time
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # PostgreSQL database URL
    # Format: postgresql+psycopg2://user:password@host:port/dbname
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

    # SQLAlchemy connection pool size (concurrent DB connections)
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "10"))

    @classmethod
    def validate(cls) -> None:
        """Validate configuration settings."""
        if not cls.GROQ_API_KEY and not cls.OPENROUTER_API_KEY:
            warnings.warn(
                "No primary API keys found. Set GROQ_API_KEY for best performance."
            )
        if not cls.DATABASE_URL:
            warnings.warn(
                "DATABASE_URL is not set. PostgreSQL persistence is disabled. "
                "Set DATABASE_URL in .env to enable multi-user persistence."
            )
