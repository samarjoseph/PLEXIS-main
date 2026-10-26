"""
TransformationStore — L1 in-memory store for TransformationPlan objects.

L2 persistence is PostgreSQL (transformation_plans table).
This store keeps recently created plans in memory for fast retrieval
without a DB round-trip on every /apply call.

Plan expiry: Plans older than 1 hour are evicted from L1.
The DB remains the source of truth.
"""
from __future__ import annotations
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from transformation.contracts import TransformationPlan

logger = logging.getLogger(__name__)

_PLAN_TTL_HOURS = 1  # L1 eviction after 1 hour


@dataclass
class PendingTransformationContext:
    """Structured state for an active transformation conversation."""
    transformation_id: str
    conversation_id: str
    dataset_id: str
    dataset_version: int
    dataset_fingerprint: str
    operation_type: str
    operation_payload: dict
    candidate_columns: list[str]
    missing_slots: list[str]
    original_request: str
    latest_question: str
    source_typed_literal: Optional[dict] = None
    destination_typed_literal: Optional[dict] = None
    clarification_type: str = 'COLUMN_SCOPE'
    status: str = 'AWAITING_CLARIFICATION'
    selected_columns: Optional[list[str]] = None
    scope: Optional[dict] = None
    current_plan_id: Optional[str] = None
    correction_history: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(cls, **kwargs):
        kwargs.setdefault('transformation_id', str(uuid.uuid4()))
        return cls(**kwargs)


class TransformationStore:
    """Thread-safe in-memory store for TransformationPlan objects."""

    def __init__(self):
        self._plans: Dict[str, TransformationPlan] = {}  # plan_id -> plan
        self._session_latest: Dict[str, str] = {}       # session_id -> plan_id
        self._pending: Dict[tuple[str, str], PendingTransformationContext] = {}
        self._pending_by_id: Dict[str, PendingTransformationContext] = {}
        self._pending_by_dataset: Dict[str, PendingTransformationContext] = {}
        self._lock = threading.Lock()

    def store(self, plan: TransformationPlan, session_id: Optional[str] = None) -> None:
        """Store a plan in L1 cache."""
        with self._lock:
            self._plans[plan.plan_id] = plan
            if session_id:
                self._session_latest[session_id] = plan.plan_id
            self._evict_stale()

    def get(self, plan_id: str) -> Optional[TransformationPlan]:
        """Retrieve a plan from L1 cache."""
        with self._lock:
            return self._plans.get(plan_id)

    def remove(self, plan_id: str) -> None:
        """Remove a plan from L1 cache."""
        with self._lock:
            self._plans.pop(plan_id, None)
            self._session_latest = {
                sid: pid for sid, pid in self._session_latest.items() if pid != plan_id
            }

    def latest_for_session(self, session_id: str, dataset_id: str) -> Optional[TransformationPlan]:
        """Return the latest in-memory plan for this session and dataset."""
        with self._lock:
            plan_id = self._session_latest.get(session_id)
            plan = self._plans.get(plan_id) if plan_id else None
            if plan and plan.dataset_id == dataset_id:
                return plan
            return None

    def invalidate(self, plan_id: str) -> Optional[TransformationPlan]:
        """Remove a plan from L1 so it cannot be reused after replanning."""
        with self._lock:
            plan = self._plans.pop(plan_id, None)
            self._session_latest = {
                sid: pid for sid, pid in self._session_latest.items() if pid != plan_id
            }
            return plan

    def set_pending(self, pending: PendingTransformationContext) -> None:
        with self._lock:
            key = (str(pending.conversation_id), str(pending.dataset_id))
            old = self._pending.get(key)
            if old:
                old.status = 'INVALIDATED'
            self._pending[key] = pending
            if getattr(pending, 'transformation_id', None):
                self._pending_by_id[str(pending.transformation_id)] = pending
            if getattr(pending, 'dataset_id', None):
                self._pending_by_dataset[str(pending.dataset_id)] = pending

    def get_pending_by_id(self, transformation_id: str) -> Optional[PendingTransformationContext]:
        """Look up active pending clarification context directly by its transformation_id."""
        with self._lock:
            if not transformation_id:
                return None
            pending = self._pending_by_id.get(str(transformation_id))
            if pending and pending.status in ('AWAITING_CLARIFICATION', 'READY_FOR_REVIEW', 'CORRECTING'):
                if datetime.now(timezone.utc) - pending.created_at > timedelta(hours=_PLAN_TTL_HOURS):
                    pending.status = 'EXPIRED'
                    return None
                return pending
            return None

    def pending_for(self, conversation_id: str, dataset_id: str) -> Optional[PendingTransformationContext]:
        with self._lock:
            pending = self._pending.get((str(conversation_id), str(dataset_id)))
            if pending and pending.status in ('AWAITING_CLARIFICATION', 'READY_FOR_REVIEW', 'CORRECTING'):
                if datetime.now(timezone.utc) - pending.created_at > timedelta(hours=_PLAN_TTL_HOURS):
                    pending.status = 'EXPIRED'
                    return None
                return pending
            return None

    def pending_for_dataset(self, dataset_id: str) -> Optional[PendingTransformationContext]:
        """Look up active pending clarification context directly by dataset_id."""
        with self._lock:
            if not dataset_id:
                return None
            pending = self._pending_by_dataset.get(str(dataset_id))
            if pending and pending.status in ('AWAITING_CLARIFICATION', 'READY_FOR_REVIEW', 'CORRECTING'):
                if datetime.now(timezone.utc) - pending.created_at > timedelta(hours=_PLAN_TTL_HOURS):
                    pending.status = 'EXPIRED'
                    return None
                return pending
            for (cid, did), p in list(self._pending.items()):
                if did == str(dataset_id) and p and p.status in ('AWAITING_CLARIFICATION', 'READY_FOR_REVIEW', 'CORRECTING'):
                    if datetime.now(timezone.utc) - p.created_at > timedelta(hours=_PLAN_TTL_HOURS):
                        p.status = 'EXPIRED'
                        return None
                    return p
            return None

    def update_pending(self, pending: PendingTransformationContext) -> None:
        with self._lock:
            key = (str(pending.conversation_id), str(pending.dataset_id))
            if self._pending.get(key) is pending:
                self._pending[key] = pending

    def activate_plan(self, pending: PendingTransformationContext) -> None:
        """Keep the structured transformation alive while its plan is reviewable."""
        with self._lock:
            pending.status = 'READY_FOR_REVIEW'
            pending.missing_slots = []
            pending.latest_question = ''
            key = (str(pending.conversation_id), str(pending.dataset_id))
            old = self._pending.get(key)
            if old and old is not pending:
                old.status = 'INVALIDATED'
            self._pending[key] = pending

    def finish_pending(self, conversation_id: str, dataset_id: str, status: str = 'COMPLETED') -> None:
        with self._lock:
            key = (str(conversation_id), str(dataset_id))
            pending = self._pending.get(key)
            if pending:
                pending.status = status
                if status not in ('READY_FOR_REVIEW', 'AWAITING_CLARIFICATION'):
                    self._pending.pop(key, None)
                    if getattr(pending, 'transformation_id', None):
                        self._pending_by_id.pop(str(pending.transformation_id), None)
                    if getattr(pending, 'dataset_id', None):
                        self._pending_by_dataset.pop(str(pending.dataset_id), None)

    def finish_plan_context(self, plan_id: str, status: str) -> None:
        """Close the active conversation when its plan is applied/cancelled."""
        with self._lock:
            for key, pending in list(self._pending.items()):
                if pending.current_plan_id == plan_id:
                    pending.status = status
                    self._pending.pop(key, None)
                    if getattr(pending, 'transformation_id', None):
                        self._pending_by_id.pop(str(pending.transformation_id), None)
                    if getattr(pending, 'dataset_id', None):
                        self._pending_by_dataset.pop(str(pending.dataset_id), None)

    def _evict_stale(self) -> None:
        """Evict plans older than TTL."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_PLAN_TTL_HOURS)
        to_remove = []
        for pid, plan in self._plans.items():
            if plan.created_at:
                try:
                    created = datetime.fromisoformat(plan.created_at)
                    if created < cutoff:
                        to_remove.append(pid)
                except Exception:
                    pass
        for pid in to_remove:
            del self._plans[pid]


transformation_store = TransformationStore()
