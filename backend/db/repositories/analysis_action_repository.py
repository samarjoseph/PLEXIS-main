"""
AnalysisActionRepository — CRUD for AnalysisAction.

Records every user interaction with an analytical result
(explain, locate, locate_selection, retry).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from db.models.analysis_action import AnalysisAction

logger = logging.getLogger(__name__)


class AnalysisActionRepository:
    """
    Data access for analysis_actions.

    Logging is best-effort — failures should never break the API response.
    """

    def log_action(
        self,
        db,
        operation_id: UUID,
        action_type: str,
        user_id: Optional[UUID] = None,
        chat_id: Optional[UUID] = None,
        dataset_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnalysisAction:
        """
        Insert one AnalysisAction row.

        action_type must be one of:
            'explain' | 'locate' | 'locate_selection' | 'retry'

        Returns the created ORM object (id assigned after flush).
        """
        obj = AnalysisAction(
            operation_id=operation_id,
            user_id=user_id,
            chat_id=chat_id,
            dataset_id=dataset_id,
            action_type=action_type,
            action_metadata_json=metadata or {},
        )
        db.add(obj)
        try:
            db.flush()
            logger.debug(
                "[AnalysisActionRepository] Logged %s action for op %s",
                action_type, operation_id,
            )
        except Exception as e:
            logger.error(
                "[AnalysisActionRepository] log_action failed: %s", e, exc_info=True
            )
            raise
        return obj

    def get_by_operation(
        self,
        db,
        operation_id: UUID,
    ) -> List[AnalysisAction]:
        """Return all actions for the given operation, newest first."""
        return (
            db.query(AnalysisAction)
            .filter(AnalysisAction.operation_id == operation_id)
            .order_by(AnalysisAction.created_at.desc())
            .all()
        )

    def get_by_type(
        self,
        db,
        operation_id: UUID,
        action_type: str,
    ) -> List[AnalysisAction]:
        """Return actions of a specific type for this operation."""
        return (
            db.query(AnalysisAction)
            .filter(
                AnalysisAction.operation_id == operation_id,
                AnalysisAction.action_type == action_type,
            )
            .order_by(AnalysisAction.created_at.desc())
            .all()
        )


analysis_action_repository = AnalysisActionRepository()
