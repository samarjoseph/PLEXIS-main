"""
SQLAlchemy engine and session factory.

Reads DATABASE_URL from environment via config.
Pool is configured for multi-threaded Flask use.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config

logger = logging.getLogger(__name__)

# Build engine — DATABASE_URL must be set before this module is imported
if Config.DATABASE_URL:
    engine = create_engine(
        Config.DATABASE_URL,
        pool_pre_ping=True,       # detect stale connections
        pool_size=Config.DB_POOL_SIZE,
        max_overflow=20,
        echo=False,               # set True for SQL debug output
    )
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    logger.debug("SQLAlchemy engine created: %s", Config.DATABASE_URL.split("@")[-1] if "@" in Config.DATABASE_URL else "configured")
else:
    engine = None
    SessionLocal = None
    logger.debug("SQLAlchemy engine not created (DATABASE_URL not set)")
