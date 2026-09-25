"""Dataset repository — all DB queries for Dataset and DatasetFile models."""
import gzip
import hashlib
import logging
import uuid
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.dataset import Dataset, DatasetFile

logger = logging.getLogger(__name__)


class DatasetRepository:
    """
    All DB access for Dataset and DatasetFile models.

    Deduplication rule: UNIQUE(user_id, file_hash)
        - Same user + same file hash → reuse existing Dataset
        - Different users + same file hash → separate Dataset records

    Ownership is verified on every resource-fetch method.
    """

    def get_by_hash(
        self,
        db: Session,
        file_hash: str,
        user_id: UUID,
    ) -> Optional[Dataset]:
        """
        Find existing Dataset by SHA-256 hash, scoped to user.
        Returns None if not found for this user.
        Used for user-scoped deduplication.
        """
        return (
            db.query(Dataset)
            .filter(Dataset.file_hash == file_hash, Dataset.user_id == user_id)
            .first()
        )

    def create_dataset(
        self,
        db: Session,
        user_id: UUID,
        original_filename: str,
        file_bytes: bytes,
        file_hash: str,
        schema_json: Optional[dict] = None,
        profile_json: Optional[dict] = None,
        row_count: Optional[int] = None,
        column_count: Optional[int] = None,
        mime_type: str = "text/csv",
    ) -> Dataset:
        """
        Create a new Dataset + DatasetFile (BYTEA) in a single transaction.

        The file content is gzip-compressed before storage.
        Schema and profile metadata are stored as JSONB.

        Args:
            db: SQLAlchemy session
            user_id: Owner's UUID
            original_filename: Original upload filename
            file_bytes: Raw (uncompressed) file content
            file_hash: SHA-256 hex digest of file_bytes
            schema_json: Column schema dict (optional, added later)
            profile_json: Profile analysis dict (optional, added later)
            row_count: Number of rows (optional)
            column_count: Number of columns (optional)
            mime_type: MIME type of the file

        Returns:
            Newly created Dataset (with DatasetFile populated)
        """
        dataset_id = uuid.uuid4()

        # gzip compress the file content
        compressed = gzip.compress(file_bytes)
        content_checksum = hashlib.sha256(file_bytes).hexdigest()

        dataset = Dataset(
            id=dataset_id,
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=original_filename,
            mime_type=mime_type,
            file_size=len(file_bytes),
            file_hash=file_hash,
            row_count=row_count,
            column_count=column_count,
            schema_json=schema_json,
            profile_json=profile_json,
        )
        db.add(dataset)
        db.flush()  # Get dataset.id before creating DatasetFile

        dataset_file = DatasetFile(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            content=compressed,
            compression="gzip",
            checksum=content_checksum,
        )
        db.add(dataset_file)
        db.flush()

        logger.info(
            "[DATASET_REPO] Created dataset id=%s filename=%s user=%s size=%d → compressed=%d",
            dataset_id, original_filename, user_id, len(file_bytes), len(compressed),
        )
        return dataset

    def get_by_id(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
    ) -> Optional[Dataset]:
        """
        Fetch Dataset by UUID, verifying ownership.
        Returns None if not found OR if owned by a different user.
        """
        return (
            db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.user_id == user_id)
            .first()
        )

    def get_by_id_unsafe(self, db: Session, dataset_id: UUID) -> Optional[Dataset]:
        """
        Fetch Dataset by UUID WITHOUT ownership check.
        INTERNAL USE ONLY — ownership must be verified upstream.
        """
        return db.query(Dataset).filter(Dataset.id == dataset_id).first()

    def get_file_bytes(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
    ) -> Optional[bytes]:
        """
        Retrieve and decompress the file content for a Dataset.

        Verifies ownership. Returns raw (uncompressed) bytes.
        Returns None if dataset or file not found/not owned.
        """
        dataset = self.get_by_id(db, dataset_id, user_id)
        if not dataset:
            logger.warning("[DATASET_REPO] get_file_bytes: dataset %s not found or not owned by %s", dataset_id, user_id)
            return None

        if not dataset.file:
            logger.warning("[DATASET_REPO] get_file_bytes: DatasetFile missing for dataset %s", dataset_id)
            return None

        content = dataset.file.content
        compression = dataset.file.compression or "gzip"

        if compression == "gzip":
            try:
                return gzip.decompress(content)
            except Exception as e:
                logger.error("[DATASET_REPO] Decompression failed for dataset %s: %s", dataset_id, e)
                return None
        else:
            return content

    def update_dko(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
        dko_json: dict,
    ) -> bool:
        """
        Store serialized DKO JSON for a dataset.
        Called after DKO pipeline completes.
        Verifies ownership.
        """
        rows = (
            db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.user_id == user_id)
            .update({"dko_json": dko_json}, synchronize_session=False)
        )
        return rows > 0

    def update_schema_profile(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
        schema_json: Optional[dict] = None,
        profile_json: Optional[dict] = None,
        row_count: Optional[int] = None,
        column_count: Optional[int] = None,
        quality_score: Optional[float] = None,
    ) -> bool:
        """Update schema/profile metadata after analysis. Verifies ownership."""
        updates = {}
        if schema_json is not None:
            updates["schema_json"] = schema_json
        if profile_json is not None:
            updates["profile_json"] = profile_json
        if row_count is not None:
            updates["row_count"] = row_count
        if column_count is not None:
            updates["column_count"] = column_count
        if quality_score is not None:
            updates["quality_score"] = quality_score

        if not updates:
            return True

        rows = (
            db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.user_id == user_id)
            .update(updates, synchronize_session=False)
        )
        return rows > 0

    def list_for_user(self, db: Session, user_id: UUID) -> list:
        """List all datasets for a user, newest first."""
        return (
            db.query(Dataset)
            .filter(Dataset.user_id == user_id)
            .order_by(Dataset.created_at.desc())
            .all()
        )


dataset_repository = DatasetRepository()
