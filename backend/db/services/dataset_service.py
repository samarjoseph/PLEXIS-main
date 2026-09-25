"""
Dataset service — high-level dataset operations bridging PostgreSQL and in-memory caches.

Handles:
- Persist dataset (deduplicate by user-scoped hash, store BYTEA)
- Restore dataset from PostgreSQL to in-memory DatasetRegistry
- Get dataset with DataFrame (cache-first, DB fallback)
- DKO pipeline integration
"""
import hashlib
import io
import logging
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.dataset import Dataset
from db.repositories.dataset_repository import dataset_repository

logger = logging.getLogger(__name__)


class DatasetService:
    """
    High-level dataset operations.

    L1 Cache: DatasetRegistry (in-memory)
    L2 Source of Truth: PostgreSQL datasets + dataset_files tables

    If all processes restart and L1 is empty, restore from PostgreSQL.
    """

    def persist_dataset(
        self,
        db: Session,
        user_id: UUID,
        file_obj,
        filename: str,
        mime_type: str = "text/csv",
    ) -> Dataset:
        """
        Persist a dataset for a user with user-scoped deduplication.

        Flow:
            1. Read file bytes
            2. Compute SHA-256 hash
            3. Check UNIQUE(user_id, file_hash) — if exists, return cached
            4. gzip-compress and store BYTEA
            5. Return Dataset record

        Args:
            db: SQLAlchemy session
            user_id: Owner's UUID
            file_obj: File-like object (seekable)
            filename: Original filename
            mime_type: MIME type

        Returns:
            Dataset (existing or newly created)
        """
        file_obj.seek(0)
        file_bytes = file_obj.read()

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        logger.debug("[DATASET_SVC] Hash computed: %s for %s", file_hash[:12] + "...", filename)

        # User-scoped deduplication
        existing = dataset_repository.get_by_hash(db, file_hash, user_id)
        if existing:
            logger.info(
                "[DATASET_SVC] Dedup hit: user=%s file=%s → dataset_id=%s",
                user_id, filename, existing.id,
            )
            return existing

        # Create new dataset record + BYTEA
        dataset = dataset_repository.create_dataset(
            db,
            user_id=user_id,
            original_filename=filename,
            file_bytes=file_bytes,
            file_hash=file_hash,
            mime_type=mime_type,
        )
        return dataset

    def restore_dataset_df(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
    ):
        """
        Restore a DataFrame from PostgreSQL BYTEA storage.

        Downloads compressed bytes, decompresses, reconstructs DataFrame.
        Re-registers in DatasetRegistry L1 cache.

        Args:
            db: SQLAlchemy session
            dataset_id: Dataset UUID
            user_id: Owner's UUID (ownership verified)

        Returns:
            (Dataset, pd.DataFrame) or (None, None) if not found
        """
        import pandas as pd

        dataset = dataset_repository.get_by_id(db, dataset_id, user_id)
        if not dataset:
            logger.warning("[DATASET_SVC] Dataset %s not found for user %s", dataset_id, user_id)
            return None, None

        raw_bytes = dataset_repository.get_file_bytes(db, dataset_id, user_id)
        if raw_bytes is None:
            logger.error("[DATASET_SVC] No file bytes for dataset %s", dataset_id)
            return dataset, None

        try:
            df = self._bytes_to_dataframe(raw_bytes, dataset.original_filename)
        except Exception as e:
            logger.error("[DATASET_SVC] Failed to reconstruct DataFrame for %s: %s", dataset_id, e)
            return dataset, None

        # Re-register in in-memory L1 cache
        self._register_in_cache(dataset, df)

        logger.info(
            "[DATASET_SVC] Restored dataset %s from DB (%d rows × %d cols)",
            dataset_id, len(df), len(df.columns),
        )
        return dataset, df

    def get_dataset_with_df(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
    ) -> Tuple[Optional[Dataset], object]:
        """
        Get a Dataset and its DataFrame.

        Check L1 cache (DatasetRegistry) first.
        On cache miss, restore from PostgreSQL and re-populate cache.

        Returns:
            (Dataset, DataFrame) or (Dataset, None) or (None, None)
        """
        # L1 cache check
        cached = self._get_from_cache(dataset_id)
        if cached is not None:
            dataset = dataset_repository.get_by_id(db, dataset_id, user_id)
            if dataset:
                logger.debug("[DATASET_SVC] L1 cache hit for dataset %s", dataset_id)
                return dataset, cached

        # L2 PostgreSQL restore
        logger.info("[DATASET_SVC] L1 cache miss for dataset %s — restoring from DB", dataset_id)
        return self.restore_dataset_df(db, dataset_id, user_id)

    def update_dko(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
        dko,
    ) -> None:
        """
        Serialize and persist a DKO to PostgreSQL JSONB.
        Called after the DKO analysis pipeline completes.
        """
        from db.dko_serializer import dko_serializer
        try:
            dko_dict = dko_serializer.serialize(dko)
            dataset_repository.update_dko(db, dataset_id, user_id, dko_dict)
            logger.info("[DATASET_SVC] DKO persisted for dataset %s", dataset_id)
        except Exception as e:
            logger.error("[DATASET_SVC] Failed to persist DKO for %s: %s", dataset_id, e)

    def update_metadata(
        self,
        db: Session,
        dataset_id: UUID,
        user_id: UUID,
        schema_json: Optional[dict] = None,
        row_count: Optional[int] = None,
        column_count: Optional[int] = None,
        quality_score: Optional[float] = None,
    ) -> None:
        """Update dataset metadata after analysis."""
        dataset_repository.update_schema_profile(
            db, dataset_id, user_id,
            schema_json=schema_json,
            row_count=row_count,
            column_count=column_count,
            quality_score=quality_score,
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _bytes_to_dataframe(self, raw_bytes: bytes, filename: str):
        """Convert raw file bytes to a pandas DataFrame."""
        import pandas as pd

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
        buf = io.BytesIO(raw_bytes)

        if ext == "csv":
            return pd.read_csv(buf)
        elif ext in ("xlsx", "xls"):
            return pd.read_excel(buf)
        elif ext == "json":
            return pd.read_json(buf)
        elif ext == "parquet":
            return pd.read_parquet(buf)
        else:
            # Attempt CSV fallback
            logger.warning("[DATASET_SVC] Unknown extension '%s' — trying CSV", ext)
            buf.seek(0)
            return pd.read_csv(buf)

    def _get_from_cache(self, dataset_id: UUID):
        """Try to get DataFrame from DatasetRegistry L1 cache."""
        try:
            from datasets.registry import dataset_registry
            entry = dataset_registry.get(str(dataset_id))
            if entry and hasattr(entry, "dataframe") and entry.dataframe is not None:
                return entry.dataframe
        except Exception:
            pass
        return None

    def _register_in_cache(self, dataset: Dataset, df) -> None:
        """Re-register a restored Dataset + DataFrame into the L1 cache."""
        try:
            from datasets.registry import dataset_registry, DatasetEntry
            from datetime import datetime, timezone
            entry = DatasetEntry(
                dataset_id=str(dataset.id),
                filename=dataset.original_filename,
                file_path="",  # file is in DB BYTEA, not local path
                upload_timestamp=dataset.created_at.isoformat() if dataset.created_at else datetime.now(timezone.utc).isoformat(),
                row_count=len(df) if df is not None else (dataset.row_count or 0),
                column_count=len(df.columns) if df is not None else (dataset.column_count or 0),
                file_fingerprint=dataset.file_hash or "",
                schema_fingerprint=dataset.file_hash or "",
                dataframe=df,
                profile={},
                schema_profile=[],
                column_profiles={},
                ontology=None,
                dko=None,  # DKO will be loaded/regenerated separately
            )
            dataset_registry.register(entry)
            logger.debug("[DATASET_SVC] Re-registered dataset %s in L1 cache", dataset.id)
        except Exception as e:
            logger.warning("[DATASET_SVC] Could not register in L1 cache: %s", e)



dataset_service = DatasetService()
