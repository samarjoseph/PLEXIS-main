"""SpreadsheetAction ORM model for persistent cell edits, transformations, and revision history."""
import uuid
from sqlalchemy import (
    Column, String, DateTime, Integer, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class SpreadsheetAction(Base):
    """
    Represents an atomic, reversible spreadsheet modification.
    
    Supports:
      - Direct cell edits (CELL_EDIT)
      - Batch cell edits (BATCH_CELL_EDIT)
      - Applied transformations (TRANSFORMATION)
      - Row/column structure mutations (ROW_DELETE, COLUMN_RENAME, etc.)
    
    Concurrency:
      base_revision is checked against dataset.current_revision to guard
      against optimistic concurrency conflicts.
    
    Undo/Redo:
      Status tracks 'committed', 'undone', or 'failed'.
      inverse_payload stores the exact inverse operation to cleanly rollback
      state without requiring full table replay every time.
    """
    __tablename__ = "spreadsheet_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    session_id = Column(String(100), nullable=True)

    base_revision = Column(Integer, nullable=False)
    resulting_revision = Column(Integer, nullable=False)
    sequence_number = Column(Integer, nullable=False)

    action_type = Column(String(50), nullable=False)  # CELL_EDIT, BATCH_CELL_EDIT, TRANSFORMATION, etc.
    operation_payload = Column(JSONB, nullable=False)  # full operation details (row, col, value, etc.)
    inverse_payload = Column(JSONB, nullable=True)    # reverse operation (previous value, etc.)

    storage_account = Column(String(50), nullable=False, server_default="primary")
    storage_key = Column(String(1024), nullable=True)  # Snapshot or segment key in R2 if applicable

    status = Column(String(20), nullable=False, server_default="committed")  # committed | undone | failed

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    dataset = relationship(
        "Dataset",
        backref="spreadsheet_actions",
        foreign_keys=[dataset_id],
    )

    def __repr__(self) -> str:
        return (
            f"<SpreadsheetAction id={self.id} type={self.action_type} "
            f"dataset={self.dataset_id} base_rev={self.base_revision} -> rev={self.resulting_revision} "
            f"status={self.status}>"
        )
