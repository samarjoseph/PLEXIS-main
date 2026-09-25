"""Message repository — deterministic sequence ordering with safe locking."""
import logging
import uuid
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, aliased

from db.models.message import Message

logger = logging.getLogger(__name__)


class MessageRepository:
    """
    All DB access for Message model.

    Sequence assignment uses a chat-row-level lock (SELECT ... FOR UPDATE on the
    chats table) to prevent concurrent duplicate sequence numbers.

    PostgreSQL does NOT allow FOR UPDATE with aggregate functions directly.
    The correct pattern is:
        1. Lock the parent chat row
        2. Then query MAX(sequence_number) safely
    UNIQUE(chat_id, sequence_number) is enforced at DB level as a safety net.
    """

    def append_message(
        self,
        db: Session,
        chat_id: UUID,
        role: str,
        content: str,
        message_type: str = "conversation",
        metadata_json: Optional[dict] = None,
    ) -> Message:
        """
        Append a message to a chat with a deterministic sequence number.

        Uses SELECT FOR UPDATE on the parent chats row to serialize concurrent writes.
        DB constraint UNIQUE(chat_id, sequence_number) catches any races.

        Args:
            db: SQLAlchemy session
            chat_id: Chat UUID
            role: 'user' | 'assistant' | 'system'
            content: Message text
            message_type: Message category (default: 'conversation')
            metadata_json: Optional metadata dict

        Returns:
            Newly created Message
        """
        # Step 1: Lock the parent chat row to prevent concurrent sequence collision.
        # This is the PostgreSQL-correct pattern — FOR UPDATE on aggregate functions
        # is not supported. We lock the chat row, then query the max sequence.
        db.execute(
            text("SELECT id FROM chats WHERE id = :chat_id FOR UPDATE"),
            {"chat_id": str(chat_id)},
        )

        # Step 2: Now safely get the next sequence number
        result = db.execute(
            text(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_seq "
                "FROM messages WHERE chat_id = :chat_id"
            ),
            {"chat_id": str(chat_id)},
        )
        next_seq = result.scalar()

        msg = Message(
            id=uuid.uuid4(),
            chat_id=chat_id,
            role=role,
            content=content,
            message_type=message_type,
            sequence_number=next_seq,
            metadata_json=metadata_json,
        )
        db.add(msg)
        db.flush()

        logger.debug(
            "[MSG_REPO] Appended message chat=%s seq=%d role=%s",
            chat_id, next_seq, role,
        )
        return msg

    def get_recent(self, db: Session, chat_id: UUID, last_n: int = 20) -> List[Message]:
        """
        Get the N most recent messages for a chat, ordered oldest-first.

        Args:
            db: SQLAlchemy session
            chat_id: Chat UUID
            last_n: Number of most recent messages to return

        Returns:
            List of Messages in chronological order
        """
        # Subquery to get last N by sequence, then re-order ascending
        subq = (
            db.query(Message)
            .filter(Message.chat_id == chat_id)
            .order_by(Message.sequence_number.desc())
            .limit(last_n)
            .subquery()
        )
        msg_alias = aliased(Message, subq)
        return (
            db.query(msg_alias)
            .order_by(subq.c.sequence_number.asc())
            .all()
        )

    def get_recent_simple(self, db: Session, chat_id: UUID, last_n: int = 20) -> List[Message]:
        """Simplified version: get last N messages in chronological order."""
        messages = (
            db.query(Message)
            .filter(Message.chat_id == chat_id)
            .order_by(Message.sequence_number.desc())
            .limit(last_n)
            .all()
        )
        return list(reversed(messages))

    def get_all(self, db: Session, chat_id: UUID) -> List[Message]:
        """Get all messages for a chat in chronological order."""
        return (
            db.query(Message)
            .filter(Message.chat_id == chat_id)
            .order_by(Message.sequence_number.asc())
            .all()
        )

    def get_count(self, db: Session, chat_id: UUID) -> int:
        """Get total message count for a chat."""
        return db.query(Message).filter(Message.chat_id == chat_id).count()


message_repository = MessageRepository()
