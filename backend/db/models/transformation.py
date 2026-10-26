"""TransformationPlan and DatasetVersion ORM models."""
import uuid
from sqlalchemy import (
    Column, String, DateTime, Integer, Text, ForeignKey
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class TransformationPlan(Base):
    """
    Records a proposed (or applied) data-transformation operation for a dataset.

    Lifecycle:
        pending  → applied   (apply endpoint succeeded)
        pending  → cancelled (user explicitly cancelled)
        pending  → expired   (dataset changed before apply, detected by fingerprint)

    dataset_fingerprint:
        SHA-256 of the dataset content at plan creation time.
        Before applying, the engine re-hashes the current dataset and compares;
        a mismatch means the underlying data changed and the plan must be
        recreated (conflict / staleness guard).
    """
    __tablename__ = "transformation_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Best-effort user/chat tracking — no FK constraint so stateless mode works.
    user_id = Column(UUID(as_uuid=True), nullable=True)
    chat_id = Column(UUID(as_uuid=True), nullable=True)

    operation_type = Column(String(100), nullable=False)          # e.g. 'FILL_MISSING'
    operation_payload = Column(JSONB, nullable=False)              # full params dict
    operation_code = Column(Text, nullable=False)                  # human-readable pandas code

    affected_rows_count = Column(Integer, nullable=False)
    affected_cells_count = Column(Integer, nullable=False)

    # Up to 20 rows of [{row, col, before, after}] for UI preview
    before_sample_json = Column(JSONB, nullable=True)

    # SHA-256 of dataset at plan creation — used for staleness detection
    dataset_fingerprint = Column(String(64), nullable=True)

    status = Column(String(20), server_default="pending", nullable=False)  # pending|applied|cancelled|expired

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    dataset = relationship(
        "Dataset",
        backref="transformation_plans",
        foreign_keys=[dataset_id],
    )
    dataset_versions = relationship(
        "DatasetVersion",
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<TransformationPlan id={self.id} type={self.operation_type} "
            f"dataset={self.dataset_id} status={self.status}>"
        )


class DatasetVersion(Base):
    """
    Records a versioned snapshot of a dataset after a transformation was applied.

    Storage strategy:
        The actual versioned DataFrame bytes are NOT stored inline.
        Instead, a new Dataset + DatasetFile row is created (reusing the
        existing BYTEA storage in dataset_files) and version_dataset_id
        points to it.  On undo, the engine reads that DatasetFile's content
        and restores the in-memory registry.

    Version chain:
        parent_version_id forms a linked list from the first version to the
        latest, enabling sequential undo/redo traversal.
    """
    __tablename__ = "dataset_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The original (base) dataset this version descends from
    original_dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The versioned copy — a new Dataset row holding the transformed bytes
    version_dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Forms the version chain (self-referential)
    parent_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The plan that produced this version (nullable — version may be manual)
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transformation_plans.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    operation_label = Column(String(500), nullable=False)     # e.g. "Fill missing with 0"
    version_number = Column(Integer, nullable=False, server_default="1")   # sequential per original_dataset_id
    revision = Column(Integer, nullable=True, server_default="0")
    storage_account = Column(String(50), nullable=True, server_default="primary")
    storage_key = Column(String(1024), nullable=True)
    changed_cells_count = Column(Integer, nullable=False)
    metadata_json = Column(JSONB, nullable=True)              # extra info: op type, affected cols, etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    original_dataset = relationship(
        "Dataset",
        foreign_keys=[original_dataset_id],
        backref="versions",
    )
    version_dataset = relationship(
        "Dataset",
        foreign_keys=[version_dataset_id],
    )
    plan = relationship(
        "TransformationPlan",
        back_populates="dataset_versions",
    )
    parent = relationship(
        "DatasetVersion",
        remote_side="DatasetVersion.id",
        foreign_keys=[parent_version_id],
        uselist=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DatasetVersion id={self.id} v={self.version_number} "
            f"original={self.original_dataset_id}>"
        )
