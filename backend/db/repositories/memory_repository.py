"""Memory repository — user and chat-scoped key-value memory."""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db.models.memory import UserMemory, ChatMemory

logger = logging.getLogger(__name__)


class MemoryRepository:
    """
    All DB access for UserMemory and ChatMemory models.

    All methods require user_id.
    ChatMemory methods also require chat_id.
    This prevents cross-user contamination even if chat_ids are guessed.
    """

    # -------------------------------------------------------------------------
    # UserMemory
    # -------------------------------------------------------------------------

    def upsert_user_memory(
        self,
        db: Session,
        user_id: UUID,
        key: str,
        value: str,
        memory_type: str = "preference",
    ) -> None:
        """
        Insert or update a user memory entry.
        UNIQUE(user_id, key) — upsert semantics.
        """
        stmt = (
            pg_insert(UserMemory)
            .values(user_id=user_id, key=key, value=value, memory_type=memory_type)
            .on_conflict_do_update(
                constraint="uq_user_memory_key",
                set_={"value": value, "memory_type": memory_type},
            )
        )
        db.execute(stmt)
        db.flush()

    def get_user_memories(self, db: Session, user_id: UUID) -> List[UserMemory]:
        """
        Get all memory entries for a user.
        Always scoped to user_id — never leaks to other users.
        """
        return (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id)
            .order_by(UserMemory.key)
            .all()
        )

    def get_user_memory(
        self,
        db: Session,
        user_id: UUID,
        key: str,
    ) -> Optional[UserMemory]:
        """Get a specific memory entry for a user by key."""
        return (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id, UserMemory.key == key)
            .first()
        )

    def delete_user_memory(self, db: Session, user_id: UUID, key: str) -> bool:
        """Delete a specific memory entry. Returns True if deleted."""
        rows = (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id, UserMemory.key == key)
            .delete(synchronize_session=False)
        )
        return rows > 0

    # -------------------------------------------------------------------------
    # ChatMemory
    # -------------------------------------------------------------------------

    def upsert_chat_memory(
        self,
        db: Session,
        user_id: UUID,
        chat_id: UUID,
        key: str,
        value: str,
    ) -> None:
        """
        Insert or update a chat memory entry.
        Requires BOTH user_id AND chat_id — prevents cross-user contamination.
        UNIQUE(user_id, chat_id, key) — upsert semantics.
        """
        stmt = (
            pg_insert(ChatMemory)
            .values(user_id=user_id, chat_id=chat_id, key=key, value=value)
            .on_conflict_do_update(
                constraint="uq_chat_memory_key",
                set_={"value": value},
            )
        )
        db.execute(stmt)
        db.flush()

    def get_chat_memories(
        self,
        db: Session,
        user_id: UUID,
        chat_id: UUID,
    ) -> List[ChatMemory]:
        """
        Get all memory entries for a specific chat.
        Requires BOTH user_id AND chat_id to prevent cross-user access.
        """
        return (
            db.query(ChatMemory)
            .filter(
                ChatMemory.user_id == user_id,
                ChatMemory.chat_id == chat_id,
            )
            .order_by(ChatMemory.key)
            .all()
        )

    def get_chat_memory(
        self,
        db: Session,
        user_id: UUID,
        chat_id: UUID,
        key: str,
    ) -> Optional[ChatMemory]:
        """Get a specific chat memory entry. Requires both user_id and chat_id."""
        return (
            db.query(ChatMemory)
            .filter(
                ChatMemory.user_id == user_id,
                ChatMemory.chat_id == chat_id,
                ChatMemory.key == key,
            )
            .first()
        )


memory_repository = MemoryRepository()
