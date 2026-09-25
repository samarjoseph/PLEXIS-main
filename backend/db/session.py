"""
Flask-scoped database session management.

Usage in routes:
    from db.session import get_db

    @blueprint.route("/example")
    def example():
        db = get_db()
        # use db for queries; session is closed automatically after request
"""
import logging
from contextlib import contextmanager

from flask import g
from sqlalchemy.orm import Session

from .engine import SessionLocal

logger = logging.getLogger(__name__)


def get_db() -> Session:
    """
    Return the SQLAlchemy session for the current Flask request context.

    Creates a new session if one doesn't exist yet for this request.
    The session is automatically closed at the end of the request via teardown.
    """
    if SessionLocal is None:
        return None
    if "db" not in g:
        g.db = SessionLocal()
    return g.db


def close_db(error=None) -> None:
    """Teardown: close and remove the session from the current request context."""
    db: Session = g.pop("db", None)
    if db is not None:
        if error is not None:
            logger.warning("Rolling back DB session due to request error: %s", error)
            try:
                db.rollback()
            except Exception:
                pass
        db.close()


def init_db(app) -> None:
    """
    Register DB session teardown with the Flask app.
    Call this inside create_app() after creating the Flask instance.
    """
    app.teardown_appcontext(close_db)
    logger.info("[DB] Session management initialized")


@contextmanager
def db_session():
    """
    Standalone context manager for use OUTSIDE Flask request context
    (e.g., background tasks, CLI scripts, Alembic scripts).

    Usage:
        with db_session() as db:
            user = user_repository.get_by_id(db, user_id)
    """
    if SessionLocal is None:
        yield None
        return
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
