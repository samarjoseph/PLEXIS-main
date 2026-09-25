"""
AnalyticalResult — canonical in-memory result object.

Backed by AnalysisOperation (PostgreSQL). Every analytical operation
produces one AnalyticalResult. This is the ONLY authoritative source
of an analytical answer — the LLM Composer is NEVER allowed to change
any numerical values in this object.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID


@dataclass
class AnalyticalResult:
    """
    In-memory representation of one analytical operation backed by a DB row.

    Rules:
      - value is ALWAYS from Pandas, never from an LLM
      - verified must be True before the result is shown as fact
      - analysis_id must always be set; it is the FK to analysis_operations.id
    """

    # Identity
    analysis_id: UUID = field(default_factory=uuid.uuid4)
    user_id: Optional[UUID] = None
    chat_id: Optional[UUID] = None
    dataset_id: Optional[UUID] = None
    dataset_fingerprint: Optional[str] = None

    # Query
    query: str = ""
    normalized_intent: str = ""
    operation: str = ""          # e.g. "max", "min", "mean"
    column: Optional[str] = None

    # Plan
    plan: Dict[str, Any] = field(default_factory=dict)

    # Execution result — always from Pandas executor
    value: Any = None            # scalar (int, float, str) or list
    row_indices: List[int] = field(default_factory=list)
    matching_rows: List[Dict[str, Any]] = field(default_factory=list)

    # Verification
    verified: bool = False
    verification_details: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -------------------------------------------------------------------------
    # Convenience properties
    # -------------------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """True when we have a verified value and an analysis_id."""
        return self.verified and self.analysis_id is not None and self.value is not None

    def to_response_dict(self) -> Dict[str, Any]:
        """Minimal dict for API responses (no internal bookkeeping)."""
        return {
            "analysis_id": str(self.analysis_id),
            "operation": self.operation,
            "column": self.column,
            "value": self.value,
            "row_indices": self.row_indices,
            "matching_rows": self.matching_rows[:5],
            "verified": self.verified,
            "dataset_fingerprint": self.dataset_fingerprint,
        }

    def to_persistence_dict(self) -> Dict[str, Any]:
        """Full dict for storing in result_json / value_json DB columns."""
        return {
            "analysis_id": str(self.analysis_id),
            "query": self.query,
            "normalized_intent": self.normalized_intent,
            "operation": self.operation,
            "column": self.column,
            "value": self.value,
            "row_indices": self.row_indices,
            "matching_rows": self.matching_rows[:10],
            "verified": self.verified,
            "verification_details": self.verification_details,
            "dataset_fingerprint": self.dataset_fingerprint,
            "created_at": self.created_at.isoformat(),
        }
