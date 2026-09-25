"""
Capability base classes — IAnalyticalCapability and CapabilityResult.

Design rules:
  - Each capability is self-contained: knows how to detect its intent,
    execute deterministic analysis, and produce typed evidence.
  - The AnalysisEngine is a pure dispatcher — it never contains if/elif blocks.
  - Adding a new capability = creating a new class + registering it.
    No existing code is modified (OCP).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from core.context import ExecutionContext
    from evidence.contracts import EvidenceReference, EvidenceCollection


@dataclass
class CapabilityResult:
    """
    Output of a single analytical capability execution.

    facts:          Structured data for the LLM context block (dict).
    evidence:       Typed evidence reference for frontend verification.
    narrative_hint: Short prose sent to LLM as additional context.
                    LLM uses this to frame its response — never raw evidence JSON.
    success:        False if the capability failed gracefully.
    error:          Error message if success=False.
    """
    facts: Dict[str, Any] = field(default_factory=dict)
    evidence: Optional[Any] = None            # EvidenceReference | EvidenceCollection
    narrative_hint: str = ""
    success: bool = True
    error: Optional[str] = None


class IAnalyticalCapability(ABC):
    """
    Abstract base for all analytical capabilities.

    Subclasses implement:
      capability_id  — unique string identifier
      can_handle()   — returns True if this capability applies to the context
      execute()      — deterministic analysis → CapabilityResult

    Resolution order in the registry is significant: more specific capabilities
    should be registered before more general ones.
    """

    @property
    @abstractmethod
    def capability_id(self) -> str:
        """Unique identifier for this capability (e.g. 'max_value')."""
        ...

    @abstractmethod
    def can_handle(self, context: "ExecutionContext") -> bool:
        """
        Returns True if this capability can handle the given context.
        Fast — no I/O, no DataFrame operations.
        """
        ...

    @abstractmethod
    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        """
        Execute deterministic analysis and return a CapabilityResult.
        Python calculates. LLMs explain. Never the opposite.
        """
        ...

    # ── Shared helpers available to all capabilities ─────────────────────────

    def _keyword_match(self, text: str, keywords: list) -> bool:
        """True if any keyword appears in text (case-insensitive)."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    def _detect_target_column(self, context: "ExecutionContext", df: pd.DataFrame) -> Optional[str]:
        """
        Find the most likely numeric target column from the context.
        Uses extracted_entities and possible_columns from query normalization.
        """
        # Try exact match from possible_columns (from query normalizer)
        for col in getattr(context, 'possible_columns', []):
            if col in df.columns:
                return col
        # Try fuzzy match against numeric columns
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        query = (context.normalized_query or context.message).lower()
        for col in numeric_cols:
            if col.lower() in query or any(
                word in col.lower() for word in query.split()
                if len(word) > 3
            ):
                return col
        # Return first numeric column if nothing matched
        return numeric_cols[0] if numeric_cols else None

    def _safe_value(self, val: Any) -> Any:
        """Convert numpy/pandas scalar to Python native type."""
        try:
            import numpy as np
            if isinstance(val, (np.integer,)):
                return int(val)
            if isinstance(val, (np.floating,)):
                return float(val)
            if isinstance(val, (np.bool_,)):
                return bool(val)
        except ImportError:
            pass
        return val

    def _row_to_dict(self, row: Any) -> Dict[str, Any]:
        """Convert a DataFrame row to a JSON-safe dict."""
        return {k: self._safe_value(v) for k, v in row.to_dict().items()}
