"""
AnalysisActionService — high-level action logging for analytical results.

This is the correct entrypoint for all action logging; call this from API
endpoints rather than the repository directly so we get consistent error
handling and structured logging.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from db.repositories.analysis_action_repository import analysis_action_repository
from db.models.analysis_action import AnalysisAction

logger = logging.getLogger(__name__)

_VALID_ACTION_TYPES = frozenset({"explain", "locate", "locate_selection", "retry"})


class AnalysisActionService:
    """
    Records user interactions against analytical results.

    All log() calls are best-effort — failures are logged but NEVER propagated
    to callers, so they never break an API response.
    """

    def log(
        self,
        db,
        operation_id: UUID,
        action_type: str,
        user_id: Optional[UUID] = None,
        chat_id: Optional[UUID] = None,
        dataset_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisAction]:
        """
        Log a user action. Returns the created AnalysisAction or None on failure.

        Failures do NOT raise — they are swallowed so API endpoints always succeed.
        """
        if action_type not in _VALID_ACTION_TYPES:
            logger.warning(
                "[AnalysisActionService] Unknown action_type=%s for op=%s",
                action_type, operation_id,
            )

        try:
            action = analysis_action_repository.log_action(
                db,
                operation_id=operation_id,
                action_type=action_type,
                user_id=user_id,
                chat_id=chat_id,
                dataset_id=dataset_id,
                metadata=metadata or {},
            )
            db.commit()
            logger.info(
                "[AnalysisActionService] Logged %s for op=%s user=%s",
                action_type, operation_id, user_id,
            )
            return action
        except Exception as e:
            logger.error(
                "[AnalysisActionService] Failed to log %s for op=%s: %s",
                action_type, operation_id, e,
            )
            try:
                db.rollback()
            except Exception:
                pass
            return None

    def get_history(
        self,
        db,
        operation_id: UUID,
    ) -> List[AnalysisAction]:
        """Return action history for an operation (newest first)."""
        try:
            return analysis_action_repository.get_by_operation(db, operation_id)
        except Exception as e:
            logger.error(
                "[AnalysisActionService] get_history failed for op=%s: %s",
                operation_id, e,
            )
            return []


analysis_action_service = AnalysisActionService()
