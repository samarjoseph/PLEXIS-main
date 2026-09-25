"""
Alembic migration environment configuration.

Imports all ORM models via db.models so Alembic can auto-detect schema.
Reads DATABASE_URL from config (which reads from .env).
"""
import sys
import os

# Add backend directory to path so imports work from this file
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# Load all models so Alembic can detect schema
from db.base import Base
import db.models  # noqa — ensures all models register with Base

# Read Alembic config
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    """Get DATABASE_URL from config."""
    from config import Config
    url = Config.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Cannot run Alembic migrations.\n"
            "Set DATABASE_URL in backend/.env or as an environment variable."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and execute)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
