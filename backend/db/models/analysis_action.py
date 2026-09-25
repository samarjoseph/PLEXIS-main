"""AnalysisAction — user interaction log for analytical results."""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class AnalysisAction(Base):
    """
    Records every user action against an analytical result.

    action_type values:
        'explain'          — user clicked Explain
        'locate'           — user clicked Locate
        'locate_selection' — user selected a specific row from a multi-row Locate
        'retry'            — user clicked Retry

    action_metadata_json:
        For locate:           { "row_count": N, "row_indices": [...] }
        For locate_selection: { "selected_source_row": 72 }
        For explain:          { "analysis_id": "..." }
        For retry:            { "new_operation_id": "..." }
    """
    __tablename__ = "analysis_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type           = Column(String(30), nullable=False, index=True)
    action_metadata_json  = Column(JSONB, nullable=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship back to operation
    operation = relationship("AnalysisOperation", back_populates="actions")

    def __repr__(self) -> str:
        return (
            f"<AnalysisAction id={self.id} type={self.action_type} "
            f"op={self.operation_id}>"
        )
