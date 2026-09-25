"""
Chat service — high-level chat operations.

Handles:
- User resolution (get-or-create)
- Chat creation and loading
- Full chat state assembly (messages + sessions + memories)
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.chat import Chat
from db.models.message import Message
from db.models.analysis_session import AnalysisSession
from db.models.memory import ChatMemory
from db.repositories.user_repository import user_repository
from db.repositories.chat_repository import chat_repository
from db.repositories.message_repository import message_repository
from db.repositories.analysis_session_repository import analysis_session_repository
from db.repositories.memory_repository import memory_repository

logger = logging.getLogger(__name__)


@dataclass
class ChatState:
    """Full chat state loaded from PostgreSQL."""
    chat: Chat
    messages: List[Message] = field(default_factory=list)
    analysis_sessions: List[AnalysisSession] = field(default_factory=list)
    memories: List[ChatMemory] = field(default_factory=list)
    current_dataset_id: Optional[str] = None


class ChatService:
    """High-level chat operations."""

    def resolve_user(self, db: Session, email: str):
        """
        Resolve or create a User from an email address.
        Delegates to user_repository.get_or_create_by_email().
        """
        user = user_repository.get_or_create_by_email(db, email)
        user_repository.update_last_seen(db, user.id)
        return user

    def create_chat(
        self,
        db: Session,
        user_id: UUID,
        title: str = "New Chat",
        current_dataset_id: Optional[UUID] = None,
    ) -> Chat:
        """Create a new Chat for a user."""
        return chat_repository.create_chat(
            db, user_id=user_id, title=title, current_dataset_id=current_dataset_id
        )

    def load_chat(self, db: Session, slug: str, user_id: UUID) -> Optional[ChatState]:
        """
        Load a full ChatState by slug (ownership verified).

        Returns:
            ChatState with chat, messages, analysis_sessions, memories
            None if not found or not owned
        """
        chat = chat_repository.get_by_slug(db, slug, user_id)
        if not chat:
            return None

        messages = message_repository.get_all(db, chat.id)
        sessions = analysis_session_repository.get_by_chat(db, chat.id)
        memories = memory_repository.get_chat_memories(db, user_id, chat.id)

        return ChatState(
            chat=chat,
            messages=messages,
            analysis_sessions=sessions,
            memories=memories,
            current_dataset_id=str(chat.current_dataset_id) if chat.current_dataset_id else None,
        )

    def load_chat_by_id(self, db: Session, chat_id: UUID, user_id: UUID) -> Optional[ChatState]:
        """Load a full ChatState by chat ID (ownership verified)."""
        chat = chat_repository.get_by_id(db, chat_id, user_id)
        if not chat:
            return None

        messages = message_repository.get_all(db, chat.id)
        sessions = analysis_session_repository.get_by_chat(db, chat.id)
        memories = memory_repository.get_chat_memories(db, user_id, chat.id)

        return ChatState(
            chat=chat,
            messages=messages,
            analysis_sessions=sessions,
            memories=memories,
            current_dataset_id=str(chat.current_dataset_id) if chat.current_dataset_id else None,
        )

    def get_or_create_chat(
        self,
        db: Session,
        user_id: UUID,
        chat_id: Optional[UUID] = None,
        title: str = "New Chat",
    ) -> Chat:
        """
        Get an existing chat or create a new one.
        Used by the /api/ask pipeline when chat_id may or may not be provided.
        """
        if chat_id:
            chat = chat_repository.get_by_id(db, chat_id, user_id)
            if chat:
                return chat
            logger.warning("[CHAT_SVC] chat_id=%s not found or not owned by user=%s; creating new", chat_id, user_id)

        return self.create_chat(db, user_id=user_id, title=title)

    def list_chats(self, db: Session, user_id: UUID) -> List[Chat]:
        """List all non-archived chats for a user."""
        return chat_repository.list_for_user(db, user_id)

    def update_current_dataset(
        self,
        db: Session,
        chat_id: UUID,
        dataset_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Update the currently active dataset for a chat."""
        return chat_repository.update_current_dataset(db, chat_id, dataset_id, user_id)

    def delete_chat(self, db: Session, chat_id: UUID, user_id: UUID) -> bool:
        """Hard delete a chat (cascades to all children)."""
        return chat_repository.delete(db, chat_id, user_id)


chat_service = ChatService()
