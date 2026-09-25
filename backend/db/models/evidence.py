"""EvidenceReference ORM model."""
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class EvidenceReference(Base):
    """
    Persistent evidence reference linking an operation to its source rows.

    row_locator_json: Serialized RowLocator — stable identity for navigating to the evidence
        in a virtualized spreadsheet grid. Contains original_row_index values
        (absolute, pre-sort, pre-filter — NOT display/filtered indices).
    """
    __tablename__ = "evidence_references"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # RowLocator serialized — contains original_row_index (absolute, pre-sort)
    row_locator_json = Column(JSONB, nullable=True)

    column_names = Column(ARRAY(String), nullable=True)     # Evidence columns
    operation_type = Column(String(100), nullable=True)
    result_value = Column(String(500), nullable=True)       # Serialized result value (for display)
    description = Column(Text, nullable=True)
    preview_rows_json = Column(JSONB, nullable=True)        # Up to 3 sample rows for preview
    metadata_json = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    operation = relationship("AnalysisOperation", back_populates="evidence_references")

    def __repr__(self) -> str:
        return f"<EvidenceReference id={self.id} op={self.operation_id} type={self.operation_type}>"
