"""UserMemory and ChatMemory ORM models."""
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class UserMemory(Base):
    """
    Key-value memory store scoped to a User.

    All lookups MUST include user_id — never query by key alone.
    UNIQUE(user_id, key) — upsert semantics for updates.
    """
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_memory_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=True)
    memory_type = Column(String(50), server_default="preference")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user = relationship("User", back_populates="user_memories")

    def __repr__(self) -> str:
        return f"<UserMemory user={self.user_id} key={self.key}>"


class ChatMemory(Base):
    """
    Key-value memory store scoped to a specific Chat (and its owning User).

    All lookups MUST include BOTH user_id AND chat_id.
    This prevents cross-user contamination even if chat_ids are guessed.
    UNIQUE(user_id, chat_id, key) — upsert semantics for updates.
    """
    __tablename__ = "chat_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "key", name="uq_chat_memory_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    chat = relationship("Chat", back_populates="chat_memories")

    def __repr__(self) -> str:
        return f"<ChatMemory user={self.user_id} chat={self.chat_id} key={self.key}>"
