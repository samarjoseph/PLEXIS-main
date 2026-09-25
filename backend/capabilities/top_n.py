"""TopNCapability — finds the top N rows by a numeric column."""
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

_KEYWORDS = ['top ', 'top-', 'top5', 'top10', 'best ', 'highest ', 'leading ']
_N_PATTERN = re.compile(r'top[\s\-]?(\d+)', re.IGNORECASE)


class TopNCapability(IAnalyticalCapability):
    """Finds the top N rows by the target numeric column."""

    @property
    def capability_id(self) -> str:
        return "top_n"

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
            n = min(n, 50)  # safety cap

            top_df = df.nlargest(n, col)
            mask = df.index.isin(top_df.index)
            locator = LocatorBuilder().build(df, mask, getattr(context, 'dko', None))

            preview = [self._row_to_dict(row) for _, row in top_df.head(3).iterrows()]

            evidence = EvidenceReference(
                type=EvidenceType.TOP_N,
                dataset_id=context.dataset_id,
                locator=locator,
                column_names=[col],
                description=f"Top {n} rows by {col}",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                preview_rows=preview,
                metadata={"column": col, "n": n, "values": top_df[col].tolist()},
            )

            return CapabilityResult(
                facts={
                    "column": col, "n": n,
                    "top_rows": [self._row_to_dict(r) for _, r in top_df.iterrows()],
                },
                evidence=evidence,
                narrative_hint=f"The top {n} rows by {col} have been identified.",
            )
        except Exception as e:
            logger.error(f"TopNCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
