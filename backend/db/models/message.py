"""Message ORM model with deterministic sequence ordering."""
import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class Message(Base):
    """
    Persistent chat message.

    sequence_number: Deterministic ordering within a chat.
        Assigned by message_repository using SELECT MAX(sequence_number)+1 ... FOR UPDATE.
        UNIQUE(chat_id, sequence_number) enforced at DB level — safe for concurrent requests.

    metadata_json: Carries non-content metadata:
        {evidence_id, operation_id, intent, source, dataset_id, ...}
    """
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "sequence_number", name="uq_chat_sequence"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)       # 'user' | 'assistant' | 'system'
    content = Column(Text, nullable=False)
    message_type = Column(String(50), server_default="conversation")
    sequence_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_json = Column(JSONB, nullable=True)    # evidence_id, operation_id, etc.

    # Relationships
    chat = relationship("Chat", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} chat={self.chat_id} seq={self.sequence_number} role={self.role}>"
