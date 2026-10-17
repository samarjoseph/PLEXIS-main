"""
Transformation repository — SQL queries for transformation_plans and dataset_versions.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.transformation import TransformationPlan, DatasetVersion

logger = logging.getLogger(__name__)


class TransformationRepository:
    """CRUD operations for transformation_plans and dataset_versions."""

    # ── TransformationPlan ────────────────────────────────────────────────────

    def create_plan(
        self,
        db: Session,
        *,
        plan_id: Optional[UUID] = None,
        dataset_id: UUID,
        operation_type: str,
        operation_payload: dict,
        operation_code: str,
        affected_rows_count: int,
        affected_cells_count: int,
        before_sample: Optional[list] = None,
        dataset_fingerprint: Optional[str] = None,
        user_id: Optional[UUID] = None,
        chat_id: Optional[UUID] = None,
    ) -> TransformationPlan:
        """Insert a new transformation plan with status='pending'."""
        plan = TransformationPlan(
            id=plan_id or uuid.uuid4(),
            dataset_id=dataset_id,
            user_id=user_id,
            chat_id=chat_id,
            operation_type=operation_type,
            operation_payload=operation_payload,
            operation_code=operation_code,
            affected_rows_count=affected_rows_count,
            affected_cells_count=affected_cells_count,
            before_sample_json=before_sample,
            dataset_fingerprint=dataset_fingerprint,
            status="pending",
        )
        db.add(plan)
        db.flush()  # populate id without committing
        logger.debug("Created TransformationPlan %s for dataset %s", plan.id, dataset_id)
        return plan

    def get_plan(self, db: Session, plan_id: UUID) -> Optional[TransformationPlan]:
        """Fetch a single plan by PK."""
        return (
            db.query(TransformationPlan)
            .filter(TransformationPlan.id == plan_id)
            .first()
        )

    def get_pending_plans_for_dataset(
        self, db: Session, dataset_id: UUID
    ) -> List[TransformationPlan]:
        """Return all pending plans for a dataset, newest first."""
        return (
            db.query(TransformationPlan)
            .filter(
                TransformationPlan.dataset_id == dataset_id,
                TransformationPlan.status == "pending",
            )
            .order_by(TransformationPlan.created_at.desc())
            .all()
        )

    def mark_plan_applied(
        self, db: Session, plan_id: UUID
    ) -> Optional[TransformationPlan]:
        """Transition plan status to 'applied' and stamp applied_at."""
        plan = self.get_plan(db, plan_id)
        if plan:
            plan.status = "applied"
            plan.applied_at = datetime.now(timezone.utc)
            db.flush()
            logger.debug("Marked TransformationPlan %s as applied", plan_id)
        return plan

    def mark_plan_cancelled(
        self, db: Session, plan_id: UUID
    ) -> Optional[TransformationPlan]:
        """Transition plan status to 'cancelled'."""
        plan = self.get_plan(db, plan_id)
        if plan:
            plan.status = "cancelled"
            db.flush()
            logger.debug("Marked TransformationPlan %s as cancelled", plan_id)
        return plan

    def mark_plan_expired(
        self, db: Session, plan_id: UUID
    ) -> Optional[TransformationPlan]:
        """Transition plan status to 'expired' (dataset changed after plan was created)."""
        plan = self.get_plan(db, plan_id)
        if plan:
            plan.status = "expired"
            db.flush()
            logger.debug("Marked TransformationPlan %s as expired", plan_id)
        return plan

    # ── DatasetVersion ────────────────────────────────────────────────────────

    def create_version(
        self,
        db: Session,
        *,
        original_dataset_id: UUID,
        version_dataset_id: UUID,
        plan_id: Optional[UUID],
        operation_label: str,
        changed_cells_count: int,
        parent_version_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
    ) -> DatasetVersion:
        """Insert a new dataset version record and auto-assign version_number."""
        existing_count = (
            db.query(DatasetVersion)
            .filter(DatasetVersion.original_dataset_id == original_dataset_id)
            .count()
        )
        version_number = existing_count + 1

        version = DatasetVersion(
            id=uuid.uuid4(),
            original_dataset_id=original_dataset_id,
            version_dataset_id=version_dataset_id,
            parent_version_id=parent_version_id,
            plan_id=plan_id,
            operation_label=operation_label,
            version_number=version_number,
            changed_cells_count=changed_cells_count,
            metadata_json=metadata or {},
        )
        db.add(version)
        db.flush()
        logger.debug(
            "Created DatasetVersion %s (v%s) for original_dataset %s",
            version.id, version_number, original_dataset_id,
        )
        return version

    def get_versions_for_dataset(
        self, db: Session, original_dataset_id: UUID
    ) -> List[DatasetVersion]:
        """Return all versions for a dataset ordered oldest → newest."""
        return (
            db.query(DatasetVersion)
            .filter(DatasetVersion.original_dataset_id == original_dataset_id)
            .order_by(DatasetVersion.version_number.asc())
            .all()
        )

    def get_latest_version(
        self, db: Session, original_dataset_id: UUID
    ) -> Optional[DatasetVersion]:
        """Return the most recent version for a dataset."""
        return (
            db.query(DatasetVersion)
            .filter(DatasetVersion.original_dataset_id == original_dataset_id)
            .order_by(DatasetVersion.version_number.desc())
            .first()
        )

    def get_version(
        self, db: Session, version_id: UUID
    ) -> Optional[DatasetVersion]:
        """Fetch a single DatasetVersion by PK."""
        return (
            db.query(DatasetVersion)
            .filter(DatasetVersion.id == version_id)
            .first()
        )


# Module-level singleton — mirrors the pattern used by other repositories
transformation_repository = TransformationRepository()
