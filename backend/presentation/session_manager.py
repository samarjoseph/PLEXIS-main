"""
Presentation Layer — Session Manager

Maps session/browser context to dataset_ids.
Prevents the "/active" anti-pattern (audit fix C-1).

Every API route uses explicit dataset_id, NOT "active".
This class exists to help callers find the most recent dataset_id
for a given session when the frontend hasn't stored it yet (edge case).
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional


class SessionManager:
    """
    Tracks which dataset_ids are associated with each session.
    Session scope: (user_scope, session_token) → [dataset_ids ordered by upload time]
    """

    def __init__(self) -> None:
        # user_scope → list of dataset_ids (most recent last)
        self._sessions: Dict[str, List[str]] = {}
        self._lock = threading.Lock()

    def register_upload(self, session_token: str, dataset_id: str) -> None:
        """Record that a session uploaded a dataset."""
        with self._lock:
            if session_token not in self._sessions:
                self._sessions[session_token] = []
            ids = self._sessions[session_token]
            if dataset_id not in ids:
                ids.append(dataset_id)

    def get_most_recent(self, session_token: str) -> Optional[str]:
        """Return the most recently uploaded dataset_id for a session."""
        with self._lock:
            ids = self._sessions.get(session_token, [])
            return ids[-1] if ids else None

    def get_all(self, session_token: str) -> List[str]:
        """Return all dataset_ids for a session, oldest first."""
        with self._lock:
            return list(self._sessions.get(session_token, []))


# Module-level singleton
session_manager = SessionManager()
