"""AnalysisOperation repository with before/after state for Undo/Redo."""
import logging
import uuid
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.operation import AnalysisOperation

logger = logging.getLogger(__name__)


class OperationRepository:
    """All DB access for AnalysisOperation model."""

    def create_operation(
        self,
        db: Session,
        analysis_session_id: UUID,
        dataset_id: UUID,
        operation_type: str,
        column_name: Optional[str] = None,
        parameters_json: Optional[dict] = None,
        result_json: Optional[dict] = None,
        before_state_json: Optional[dict] = None,
        after_state_json: Optional[dict] = None,
        status: str = "completed",
    ) -> AnalysisOperation:
        """
        Persist an analysis operation.

        before_state_json: Workspace state BEFORE this operation (for Undo).
        after_state_json: Workspace state AFTER this operation (for Redo).
        Both are required for state-changing spreadsheet operations.
        """
        op = AnalysisOperation(
            id=uuid.uuid4(),
            analysis_session_id=analysis_session_id,
            dataset_id=dataset_id,
            operation_type=operation_type,
            column_name=column_name,
            parameters_json=parameters_json or {},
            result_json=result_json or {},
            before_state_json=before_state_json,
            after_state_json=after_state_json,
            status=status,
        )
        db.add(op)
        db.flush()
        logger.debug(
            "[OP_REPO] Created operation id=%s type=%s session=%s",
            op.id, operation_type, analysis_session_id,
        )
        return op

    def get_recent_for_session(
        self,
        db: Session,
        session_id: UUID,
        last_n: int = 20,
    ) -> List[AnalysisOperation]:
        """Get the N most recent operations for a session, newest first."""
        return (
            db.query(AnalysisOperation)
            .filter(
                AnalysisOperation.analysis_session_id == session_id,
                AnalysisOperation.status == "completed",
            )
            .order_by(AnalysisOperation.created_at.desc())
            .limit(last_n)
            .all()
        )

    def get_for_undo(
        self,
        db: Session,
        session_id: UUID,
    ) -> Optional[AnalysisOperation]:
        """
        Get the most recent completed operation for Undo.
        Returns the operation with before_state_json for state restoration.
        """
        return (
            db.query(AnalysisOperation)
            .filter(
                AnalysisOperation.analysis_session_id == session_id,
                AnalysisOperation.status == "completed",
            )
            .order_by(AnalysisOperation.created_at.desc())
            .first()
        )

    def get_by_id(self, db: Session, op_id: UUID) -> Optional[AnalysisOperation]:
        """Fetch an AnalysisOperation by UUID."""
        return db.query(AnalysisOperation).filter(AnalysisOperation.id == op_id).first()

    def mark_undone(self, db: Session, op_id: UUID) -> None:
        """Mark an operation as undone after Undo action."""
        db.query(AnalysisOperation).filter(AnalysisOperation.id == op_id).update(
            {"status": "undone"},
            synchronize_session=False,
        )


operation_repository = OperationRepository()
