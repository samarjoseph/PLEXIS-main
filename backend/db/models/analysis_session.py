"""AnalysisSession ORM model."""
import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class AnalysisSession(Base):
    """
    An analytical session within a chat, tied to a specific dataset.

    Ownership structure:
        Chat (owned by User)
          └── AnalysisSession
                └── dataset_id → Dataset (owned by User)

    Dataset belongs to User, NOT to AnalysisSession.
    AnalysisSession merely references the Dataset being analyzed.

    A chat can have multiple AnalysisSessions (one per dataset switch).
    The Chat.current_dataset_id tracks the currently active dataset,
    while AnalysisSession.dataset_id records historical relationships.
    """
    __tablename__ = "analysis_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    current_state_json = Column(JSONB, nullable=True)       # workspace state snapshot
    analysis_context_json = Column(JSONB, nullable=True)    # DKO-derived context
    conversation_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    chat = relationship("Chat", back_populates="analysis_sessions")
    dataset = relationship("Dataset", back_populates="analysis_sessions")
    operations = relationship(
        "AnalysisOperation",
        back_populates="analysis_session",
        cascade="all, delete-orphan",
        order_by="AnalysisOperation.created_at",
    )

    def __repr__(self) -> str:
        return f"<AnalysisSession id={self.id} chat={self.chat_id} dataset={self.dataset_id}>"
