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
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
    MAX_UPLOAD_SIZE_MB: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "100"))
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    
    # Parse comma-separated CORS origins into a list
    CORS_ORIGINS: List[str] = [
        origin.strip() 
        for origin in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
        if origin.strip()
    ]
    
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "storage/uploads")
    # Ensure upload folder exists at config load time
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    @classmethod
    def validate(cls) -> None:
        """Validate configuration settings."""
        if not cls.GEMINI_API_KEY and not cls.OPENROUTER_API_KEY:
            warnings.warn("No API keys found for LLM providers (Gemini or OpenRouter).")
