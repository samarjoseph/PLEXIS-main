"""AnalysisOperation ORM model with before/after state for Undo/Redo."""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


from db.base import Base


class AnalysisOperation(Base):
    """
    A single analytical or spreadsheet operation within an AnalysisSession.

    before_state_json / after_state_json:
        Snapshots of workspace state before and after this operation.
        Required because knowing an operation happened is not always enough to reverse it.
        State-changing spreadsheet operations persist enough info to reconstruct previous state.
        Integrated with the existing SpreadsheetOperationEngine — NOT a separate undo system.

    parameters_json: Input parameters used to reproduce the operation.
    result_json: The computed analytical result.
    """
    __tablename__ = "analysis_operations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_type = Column(String(100), nullable=False)    # e.g. "MIN", "MAX", "SORT", "FILTER"
    column_name = Column(String(255), nullable=True)

    parameters_json = Column(JSONB, nullable=True)          # Input parameters
    result_json = Column(JSONB, nullable=True)              # Computed result

    # State snapshots for Undo/Redo
    before_state_json = Column(JSONB, nullable=True)        # Workspace state BEFORE operation
    after_state_json = Column(JSONB, nullable=True)         # Workspace state AFTER operation

    # ── Fields added by migration 002 — analytical brain persistence ─────────
    value_json           = Column(JSONB, nullable=True)           # {"value": 65}
    row_indices_json     = Column(JSONB, nullable=True)           # [0, 4, 7, ...]
    matching_rows_json   = Column(JSONB, nullable=True)           # [{...}, ...]
    dataset_fingerprint  = Column(String(64), nullable=True)      # SHA-256 of dataset
    verified             = Column(Boolean, nullable=True, server_default="false")  # verifier pass
    verification_details = Column(JSONB, nullable=True)           # verifier output
    plan_json            = Column(JSONB, nullable=True)           # AnalyticalPlan dict
    normalized_intent    = Column(String(100), nullable=True)     # e.g. "highest_age"
    query_text           = Column(Text, nullable=True)            # original user query
    # ── Fields added by migration 003 ─────────────────────────────────────────
    retry_of_operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_operations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ─────────────────────────────────────────────────────────────────────────

    status = Column(String(20), server_default="completed") # 'completed' | 'failed' | 'pending'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    analysis_session = relationship("AnalysisSession", back_populates="operations")
    evidence_references = relationship(
        "EvidenceReference",
        back_populates="operation",
        cascade="all, delete-orphan",
    )
    result_rows = relationship(
        "AnalysisResultRow",
        back_populates="operation",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    actions = relationship(
        "AnalysisAction",
        back_populates="operation",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    # Self-referential: the operation this is a retry of
    retry_of = relationship(
        "AnalysisOperation",
        foreign_keys=[retry_of_operation_id],
        remote_side="AnalysisOperation.id",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<AnalysisOperation id={self.id} type={self.operation_type} session={self.analysis_session_id}>"
