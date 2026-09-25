"""EvidenceReference repository."""
import logging
import uuid
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.evidence import EvidenceReference

logger = logging.getLogger(__name__)


class EvidenceRepository:
    """
    All DB access for EvidenceReference model.

    Ownership is verified by traversing the chain:
    evidence → operation → analysis_session → chat → user_id
    """

    def create_evidence(
        self,
        db: Session,
        operation_id: UUID,
        dataset_id: UUID,
        row_locator_json: Optional[dict] = None,
        column_names: Optional[List[str]] = None,
        operation_type: Optional[str] = None,
        result_value: Optional[str] = None,
        description: Optional[str] = None,
        preview_rows_json: Optional[dict] = None,
        metadata_json: Optional[dict] = None,
    ) -> EvidenceReference:
        """
        Create a new evidence reference for an operation.

        row_locator_json: Serialized RowLocator containing original_row_index values
            (absolute, pre-sort, pre-filter). NOT display/filtered indices.
        """
        ev = EvidenceReference(
            id=uuid.uuid4(),
            operation_id=operation_id,
            dataset_id=dataset_id,
            row_locator_json=row_locator_json or {},
            column_names=column_names or [],
            operation_type=operation_type,
            result_value=result_value,
            description=description,
            preview_rows_json=preview_rows_json,
            metadata_json=metadata_json or {},
        )
        db.add(ev)
        db.flush()
        logger.debug(
            "[EVIDENCE_REPO] Created evidence id=%s op=%s type=%s",
            ev.id, operation_id, operation_type,
        )
        return ev

    def get_by_id(
        self,
        db: Session,
        evidence_id: UUID,
        user_id: UUID,
    ) -> Optional[EvidenceReference]:
        """
        Fetch EvidenceReference by UUID with ownership verification.

        Ownership chain: evidence → operation → analysis_session → chat → user_id
        Returns None if not found or not owned by user.
        """
        from db.models.operation import AnalysisOperation
        from db.models.analysis_session import AnalysisSession
        from db.models.chat import Chat

        return (
            db.query(EvidenceReference)
            .join(AnalysisOperation, EvidenceReference.operation_id == AnalysisOperation.id)
            .join(AnalysisSession, AnalysisOperation.analysis_session_id == AnalysisSession.id)
            .join(Chat, AnalysisSession.chat_id == Chat.id)
            .filter(
                EvidenceReference.id == evidence_id,
                Chat.user_id == user_id,
            )
            .first()
        )

    def get_by_id_unsafe(self, db: Session, evidence_id: UUID) -> Optional[EvidenceReference]:
        """
        Fetch EvidenceReference WITHOUT ownership check.
        INTERNAL USE ONLY.
        """
        return db.query(EvidenceReference).filter(EvidenceReference.id == evidence_id).first()

    def get_for_operation(self, db: Session, operation_id: UUID) -> List[EvidenceReference]:
        """Get all evidence references for an operation."""
        return (
            db.query(EvidenceReference)
            .filter(EvidenceReference.operation_id == operation_id)
            .all()
        )


evidence_repository = EvidenceRepository()
