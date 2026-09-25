"""BottomNCapability — finds the bottom N rows by a numeric column."""
import logging
import re
from typing import TYPE_CHECKING

import pandas as pd

from capabilities.base import CapabilityResult, IAnalyticalCapability
from evidence.contracts import EvidenceReference, EvidenceType
from evidence.locator_builder import LocatorBuilder

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)

_KEYWORDS = ['bottom ', 'bottom-', 'worst ', 'lowest ', 'least ']
_N_PATTERN = re.compile(r'bottom[\s\-]?(\d+)', re.IGNORECASE)


class BottomNCapability(IAnalyticalCapability):
    """Finds the bottom N rows by the target numeric column."""

    @property
    def capability_id(self) -> str:
        return "bottom_n"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        query = (context.normalized_query or context.message).lower()
        return any(kw in query for kw in _KEYWORDS)

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        col = self._detect_target_column(context, df)
        if not col:
            return CapabilityResult(
                facts={"error": "Could not identify a numeric column."},
                success=False, error="No numeric column found"
            )
        try:
            query = context.normalized_query or context.message
            m = _N_PATTERN.search(query)
            n = int(m.group(1)) if m else 5
            n = min(n, 50)

            bottom_df = df.nsmallest(n, col)
            mask = df.index.isin(bottom_df.index)
            locator = LocatorBuilder().build(df, mask, getattr(context, 'dko', None))

            preview = [self._row_to_dict(row) for _, row in bottom_df.head(3).iterrows()]

            evidence = EvidenceReference(
                type=EvidenceType.BOTTOM_N,
                dataset_id=context.dataset_id,
                locator=locator,
                column_names=[col],
                description=f"Bottom {n} rows by {col}",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                preview_rows=preview,
                metadata={"column": col, "n": n, "values": bottom_df[col].tolist()},
            )

            return CapabilityResult(
                facts={
                    "column": col, "n": n,
                    "bottom_rows": [self._row_to_dict(r) for _, r in bottom_df.iterrows()],
                },
                evidence=evidence,
                narrative_hint=f"The bottom {n} rows by {col} have been identified.",
            )
        except Exception as e:
            logger.error(f"BottomNCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
