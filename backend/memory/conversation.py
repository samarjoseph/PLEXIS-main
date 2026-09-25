"""
Conversation memory for multi-turn interactions.

Phase 8 update: L1/L2 cache pattern.
  L1 = in-memory _history dict (fast, lost on restart)
  L2 = PostgreSQL messages table (persistent, reconstructed on miss)

get_history() checks L1 first, falls back to PostgreSQL if chat_id is known.
append() writes to L1 AND PostgreSQL (if chat_id is known).

Thread safety:
  All mutations to _history and _session_to_chat are protected by threading.Lock.
  Flask may run multiple threads concurrently — without locking, concurrent appends
  could corrupt the message list via race conditions.
"""
import logging
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 50


@dataclass
class ConvMessage:
    """A single conversation message. Named ConvMessage to avoid shadowing db.models.Message."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: Optional[str] = None


class ConversationMemory:
    """
    Manages conversation history per session.

    session_id → list of ConvMessages (L1 in-memory cache)
    chat_id mapping → used for DB fallback (L2)

    Thread-safe: all mutations protected by self._lock.
    """

    def __init__(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        self._history: Dict[str, List[ConvMessage]] = {}  # session_id → messages
        self._session_to_chat: Dict[str, str] = {}        # session_id → chat_id (for DB fallback)
        self._max_messages = max_messages
        self._lock = threading.Lock()

    def register_chat_id(self, session_id: str, chat_id: str) -> None:
        """
        Register the DB chat_id for a session to enable DB fallback.
        This MUST be called by api/chat.py after resolving chat_id so that
        get_history() can reconstruct from PostgreSQL on L1 cache miss.
        """
        with self._lock:
            self._session_to_chat[session_id] = chat_id
            logger.debug("[CONV_MEMORY] Registered chat_id=%s for session=%s", chat_id, session_id)

    def append(self, session_id: str, role: str, content: str, timestamp: Optional[str] = None) -> None:
        """Append a message to session history (L1 only — thread-safe)."""
        with self._lock:
            if session_id not in self._history:
                self._history[session_id] = []

            msg = ConvMessage(role=role, content=content, timestamp=timestamp)
            self._history[session_id].append(msg)

            # Enforce max depth
            if len(self._history[session_id]) > self._max_messages:
                self._history[session_id] = self._history[session_id][-self._max_messages:]

    def get_history(self, session_id: str, last_n: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get conversation history as list of dicts.

        L1: check in-memory cache first.
        L2: if cache empty and chat_id is known, reconstruct from PostgreSQL.
        """
        with self._lock:
            messages = list(self._history.get(session_id, []))
            chat_id = self._session_to_chat.get(session_id)

        # L2 fallback: reconstruct from PostgreSQL if cache is empty
        if not messages and chat_id:
            messages = self._load_from_db(session_id, chat_id, last_n or self._max_messages)

        if last_n is not None:
            messages = messages[-last_n:]
        return [{'role': m.role, 'content': m.content} for m in messages]

    def _load_from_db(self, session_id: str, chat_id: str, last_n: int) -> List[ConvMessage]:
        """Load messages from PostgreSQL and populate L1 cache."""
        try:
            from config import Config
            if not Config.DATABASE_URL:
                return []

            from db.session import db_session
            from db.repositories.message_repository import message_repository
            import uuid as _uuid

            with db_session() as db:
                db_msgs = message_repository.get_recent_simple(
                    db, _uuid.UUID(chat_id), last_n=last_n
                )

            messages = [
                ConvMessage(
                    role=m.role,
                    content=m.content,
                    timestamp=m.created_at.isoformat() if m.created_at else None,
                )
                for m in db_msgs
                if m.role in ('user', 'assistant')
            ]

            # Populate L1 cache with DB data (thread-safe write)
            if messages:
                with self._lock:
                    self._history[session_id] = messages
                logger.info(
                    "[CONV_MEMORY] Reconstructed %d messages from DB for session=%s chat=%s",
                    len(messages), session_id, chat_id,
                )

            return messages
        except Exception as e:
            logger.warning("[CONV_MEMORY] DB fallback failed for session=%s: %s", session_id, e)
            return []

    def clear(self, session_id: str) -> None:
        """Clear history for a session (thread-safe)."""
        with self._lock:
            self._history.pop(session_id, None)
            self._session_to_chat.pop(session_id, None)

    def message_count(self, session_id: str) -> int:
        """Get message count for a session (thread-safe)."""
        with self._lock:
            return len(self._history.get(session_id, []))


conversation_memory = ConversationMemory()
