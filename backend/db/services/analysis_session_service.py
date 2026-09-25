"""
Analysis session service — manages AnalysisSessions with L1/L2 cache pattern.

Handles:
- Get-or-restore session for a chat+dataset pair
- Operation recording (operation + evidence in one transaction)
- Session state snapshots
"""
import logging
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.analysis_session import AnalysisSession
from db.models.operation import AnalysisOperation
from db.models.evidence import EvidenceReference
from db.repositories.analysis_session_repository import analysis_session_repository
from db.repositories.operation_repository import operation_repository
from db.repositories.evidence_repository import evidence_repository

logger = logging.getLogger(__name__)


class AnalysisSessionService:
    """
    High-level analysis session management.

    L1 Cache: In-memory SessionManager._sessions dict
    L2 Source of Truth: PostgreSQL analysis_sessions table
    """

    def get_or_restore_session(
        self,
        db: Session,
        chat_id: UUID,
        dataset_id: UUID,
        user_id: UUID,
    ) -> AnalysisSession:
        """
        Get or create an AnalysisSession for a chat+dataset pair.

        Flow:
            1. Check in-memory SessionManager cache (L1)
            2. Cache miss → query PostgreSQL (L2)
            3. If found in DB: restore DataFrame via dataset_service
            4. If not found: create new AnalysisSession

        Args:
            db: SQLAlchemy session
            chat_id: Chat UUID
            dataset_id: Dataset UUID
            user_id: User UUID (for dataset ownership verification)

        Returns:
            AnalysisSession (existing from DB or newly created)
        """
        # L1 cache check — try in-memory SessionManager
        cached = self._get_from_session_cache(str(chat_id), str(dataset_id))
        if cached:
            logger.debug("[SESSION_SVC] L1 cache hit for chat=%s dataset=%s", chat_id, dataset_id)
            return cached

        # L2 PostgreSQL
        session = analysis_session_repository.get_or_create(db, chat_id, dataset_id)

        # Ensure DataFrame is available in DatasetRegistry
        self._ensure_dataset_in_cache(db, dataset_id, user_id)

        return session

    def record_operation(
        self,
        db: Session,
        analysis_session: AnalysisSession,
        operation_type: str,
        column_name: Optional[str] = None,
        parameters_json: Optional[dict] = None,
        result_json: Optional[dict] = None,
        before_state_json: Optional[dict] = None,
        after_state_json: Optional[dict] = None,
        row_locator_json: Optional[dict] = None,
        column_names: Optional[list] = None,
        result_value: Optional[str] = None,
        description: Optional[str] = None,
        preview_rows_json: Optional[dict] = None,
        evidence_metadata: Optional[dict] = None,
    ) -> Tuple[AnalysisOperation, Optional[EvidenceReference]]:
        """
        Persist an operation and its evidence atomically.

        Both operation and evidence are created in the same DB transaction.
        Caller is responsible for committing the session.

        Args:
            db: SQLAlchemy session (caller commits)
            analysis_session: The active AnalysisSession
            operation_type: e.g. "MIN", "MAX", "SORT", "FILTER"
            column_name: Column the operation was performed on
            parameters_json: Input parameters
            result_json: Computed result
            before_state_json: Workspace state BEFORE (for Undo)
            after_state_json: Workspace state AFTER (for Redo)
            row_locator_json: Serialized RowLocator for evidence
            column_names: Evidence column names
            result_value: String representation of result
            description: Human-readable description
            preview_rows_json: Up to 3 sample rows
            evidence_metadata: Additional evidence metadata

        Returns:
            (AnalysisOperation, EvidenceReference or None)
        """
        op = operation_repository.create_operation(
            db,
            analysis_session_id=analysis_session.id,
            dataset_id=analysis_session.dataset_id,
            operation_type=operation_type,
            column_name=column_name,
            parameters_json=parameters_json or {},
            result_json=result_json or {},
            before_state_json=before_state_json,
            after_state_json=after_state_json,
        )

        ev = None
        if row_locator_json or column_names:
            ev = evidence_repository.create_evidence(
                db,
                operation_id=op.id,
                dataset_id=analysis_session.dataset_id,
                row_locator_json=row_locator_json,
                column_names=column_names,
                operation_type=operation_type,
                result_value=result_value,
                description=description,
                preview_rows_json=preview_rows_json,
                metadata_json=evidence_metadata,
            )

        # Touch session last_active_at
        analysis_session_repository.touch(db, analysis_session.id)

        logger.debug(
            "[SESSION_SVC] Recorded operation type=%s op_id=%s evidence_id=%s",
            operation_type, op.id, ev.id if ev else None,
        )
        return op, ev

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_from_session_cache(self, chat_id: str, dataset_id: str) -> Optional[AnalysisSession]:
        """
        Try to get AnalysisSession from in-memory cache.

        NOTE: The previous implementation attempted session_manager.get(chat_id) which
        is not a valid method (correct method is get_session(session_id)) and also
        checked for session_data.db_session which doesn't exist on the Session dataclass.

        This method now returns None unconditionally, letting the caller fall through to
        the reliable DB lookup via analysis_session_repository.get_or_create().
        The in-memory session cache does not track AnalysisSession ORM objects.
        """
        return None


    def _ensure_dataset_in_cache(self, db: Session, dataset_id: UUID, user_id: UUID) -> None:
        """Ensure the dataset's DataFrame is in the L1 DatasetRegistry cache."""
        try:
            from datasets.registry import dataset_registry
            entry = dataset_registry.get(str(dataset_id))
            if entry and hasattr(entry, "dataframe") and entry.dataframe is not None:
                return  # Already in cache

            # Not in cache — restore from PostgreSQL
            logger.info("[SESSION_SVC] Dataset %s not in cache — restoring from DB", dataset_id)
            from db.services.dataset_service import dataset_service
            dataset_service.restore_dataset_df(db, dataset_id, user_id)
        except Exception as e:
            logger.warning("[SESSION_SVC] Could not ensure dataset in cache: %s", e)


analysis_session_service = AnalysisSessionService()
