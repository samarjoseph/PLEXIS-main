"""AnalysisResultRow — normalized per-row source evidence for analytical results."""
import uuid
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class AnalysisResultRow(Base):
    """
    One source row that contributed to an AnalyticalResult.

    source_row_number:  1-based spreadsheet row number (user-visible).
    dataframe_index:    0-based positional index in the DataFrame at execution time.
    record_data_json:   Full row values as a dict (snapshot at execution time).
    column_value:       The analytical value for this row's target column.

    Never regenerated after ingestion — source_row_number is canonical and immutable.
    """
    __tablename__ = "analysis_result_rows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_row_number = Column(Integer, nullable=False)   # 1-based row visible to user
    dataframe_index   = Column(Integer, nullable=True)    # 0-based df positional index
    record_data_json  = Column(JSONB, nullable=True)      # full row snapshot
    column_value      = Column(JSONB, nullable=True)      # specific column value

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship
    operation = relationship("AnalysisOperation", back_populates="result_rows")

    def to_dict(self):
        data = self.record_data_json or {}
        return {
            "source_row_number": self.source_row_number,
            "dataframe_index": self.dataframe_index,
            "column_value": self.column_value,
            **data,
        }

    def __repr__(self) -> str:
        return (
            f"<AnalysisResultRow id={self.id} "
            f"op={self.operation_id} row={self.source_row_number}>"
        )
