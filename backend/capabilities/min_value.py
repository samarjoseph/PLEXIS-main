"""MinValueCapability — finds the row(s) with the lowest value in a numeric column."""
import logging
from typing import TYPE_CHECKING

import pandas as pd

from capabilities.base import CapabilityResult, IAnalyticalCapability
from evidence.contracts import EvidenceReference, EvidenceType
from evidence.locator_builder import LocatorBuilder

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)

_KEYWORDS = [
    'lowest', 'minimum', 'min', 'cheapest', 'smallest', 'least',
    'worst', 'bottom value', 'least expensive', 'fewest',
]


class MinValueCapability(IAnalyticalCapability):
    """Finds the row with the minimum value in the target numeric column."""

    @property
    def capability_id(self) -> str:
        return "min_value"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        col = self._detect_target_column(context, df)
        if not col:
            return CapabilityResult(
                facts={"error": "Could not identify a numeric column for min analysis."},
                success=False, error="No numeric column found"
            )
        try:
            idx = df[col].idxmin()
            row = df.loc[idx]
            value = self._safe_value(row[col])

            mask = df.index == idx
            locator = LocatorBuilder().build(df, mask, getattr(context, 'dko', None))

            preview = [self._row_to_dict(row)]

            evidence = EvidenceReference(
                type=EvidenceType.BOTTOM_N,
                dataset_id=context.dataset_id,
                locator=locator,
                column_names=[col],
                description=f"Lowest {col}: {value}",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                preview_rows=preview,
                metadata={"column": col, "value": value, "row_index": int(idx)},
            )

            return CapabilityResult(
                facts={"column": col, "min_value": value, "row": self._row_to_dict(row)},
                evidence=evidence,
                narrative_hint=(
                    f"In **{getattr(context, 'dataset_filename', 'the dataset')}**, "
                    f"the lowest **{col}** is **{value}**."
                ),
            )
        except Exception as e:
            logger.error(f"MinValueCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(
                facts={"error": str(e)}, success=False, error=str(e)
            )
