"""
db package — PostgreSQL persistence layer for Plexis.

Public API:
    from db.session import get_db, init_db, db_session
    from db.identity import identity_resolver, CurrentUser, IdentityError
    from db.models import User, Chat, Dataset, Message, AnalysisSession, AnalysisOperation, EvidenceReference
    from db.dko_serializer import dko_serializer
"""
from .session import get_db, init_db, db_session
from .identity import identity_resolver, CurrentUser, IdentityError

__all__ = [
    "get_db",
    "init_db",
    "db_session",
    "identity_resolver",
    "CurrentUser",
    "IdentityError",
]
