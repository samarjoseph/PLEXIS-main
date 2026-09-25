"""Dataset and DatasetFile ORM models."""
import uuid
from sqlalchemy import (
    Column, String, DateTime, Integer, BigInteger, Float,
    ForeignKey, UniqueConstraint, LargeBinary
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class Dataset(Base):
    """
    Represents a user-uploaded dataset.

    Ownership: Dataset belongs directly to User (not to Chat or AnalysisSession).
    AnalysisSessions reference datasets they analyze via dataset_id FK.

    Deduplication: UNIQUE(user_id, file_hash) — user-scoped.
    Two different users uploading the same file get separate Dataset records.
    The same user uploading the same file twice reuses this record.
    """
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_user_file_hash"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = Column(String(500), nullable=False)
    stored_filename = Column(String(500), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    file_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hex

    row_count = Column(Integer, nullable=True)
    column_count = Column(Integer, nullable=True)

    schema_json = Column(JSONB, nullable=True)      # {columns: [{name, dtype, ...}]}
    profile_json = Column(JSONB, nullable=True)     # dataset_profiler output
    dko_json = Column(JSONB, nullable=True)          # DKOSerializer.to_dict(dko) — for restore
    quality_score = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    user = relationship("User", back_populates="datasets")
    file = relationship(
        "DatasetFile",
        back_populates="dataset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    analysis_sessions = relationship("AnalysisSession", back_populates="dataset")

    def __repr__(self) -> str:
        return f"<Dataset id={self.id} filename={self.original_filename} user={self.user_id}>"


class DatasetFile(Base):
    """
    Stores the compressed binary content (BYTEA) of a dataset file.

    Separate from Dataset to keep the datasets table lightweight.
    One-to-one with Dataset.
    """
    __tablename__ = "dataset_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content = Column(LargeBinary, nullable=False)           # gzip-compressed file bytes
    compression = Column(String(20), server_default="gzip")
    checksum = Column(String(64), nullable=True)             # SHA-256 of original (uncompressed) content
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    dataset = relationship("Dataset", back_populates="file")

    def __repr__(self) -> str:
        return f"<DatasetFile dataset_id={self.dataset_id} compression={self.compression}>"
