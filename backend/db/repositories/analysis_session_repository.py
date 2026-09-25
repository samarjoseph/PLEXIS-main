"""AnalysisSession repository."""
import logging
import uuid
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from db.models.analysis_session import AnalysisSession

logger = logging.getLogger(__name__)


class AnalysisSessionRepository:
    """All DB access for AnalysisSession model."""

    def get_or_create(
        self,
        db: Session,
        chat_id: UUID,
        dataset_id: UUID,
    ) -> AnalysisSession:
        """
        Find or create an AnalysisSession for a chat+dataset combination.
        Returns the most recent existing session if found.
        """
        existing = self.get_latest_for_chat_dataset(db, chat_id, dataset_id)
        if existing:
            return existing

        session = AnalysisSession(
            id=uuid.uuid4(),
            chat_id=chat_id,
            dataset_id=dataset_id,
        )
        db.add(session)
        db.flush()
        logger.info(
            "[SESSION_REPO] Created AnalysisSession id=%s chat=%s dataset=%s",
            session.id, chat_id, dataset_id,
        )
        return session

    def get_latest_for_chat_dataset(
        self,
        db: Session,
        chat_id: UUID,
        dataset_id: UUID,
    ) -> Optional[AnalysisSession]:
        """Get most recently created AnalysisSession for a specific chat+dataset pair."""
        return (
            db.query(AnalysisSession)
            .filter(
                AnalysisSession.chat_id == chat_id,
                AnalysisSession.dataset_id == dataset_id,
            )
            .order_by(AnalysisSession.created_at.desc())
            .first()
        )

    def get_by_id(self, db: Session, session_id: UUID) -> Optional[AnalysisSession]:
        """Fetch AnalysisSession by UUID."""
        return db.query(AnalysisSession).filter(AnalysisSession.id == session_id).first()

    def get_by_chat(self, db: Session, chat_id: UUID) -> List[AnalysisSession]:
        """Get all AnalysisSessions for a chat, newest first."""
        return (
            db.query(AnalysisSession)
            .filter(AnalysisSession.chat_id == chat_id)
            .order_by(AnalysisSession.created_at.desc())
            .all()
        )

    def update_state(
        self,
        db: Session,
        session_id: UUID,
        state_json: dict,
    ) -> None:
        """Update workspace state snapshot for a session."""
        db.query(AnalysisSession).filter(AnalysisSession.id == session_id).update(
            {
                "current_state_json": state_json,
                "last_active_at": func.now(),
            },
            synchronize_session=False,
        )

    def touch(self, db: Session, session_id: UUID) -> None:
        """Update last_active_at timestamp."""
        db.query(AnalysisSession).filter(AnalysisSession.id == session_id).update(
            {"last_active_at": func.now()},
            synchronize_session=False,
        )


analysis_session_repository = AnalysisSessionRepository()
