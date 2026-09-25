"""DuplicateCapability — finds duplicate rows across one or more columns."""
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
    'duplicate', 'duplicates', 'repeated', 'repeating', 'same ',
    'appear more than once', 'occur multiple', 'double entries',
]


class DuplicateCapability(IAnalyticalCapability):
    """Detects duplicate rows and returns them as evidence."""

    @property
    def capability_id(self) -> str:
        return "duplicates"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        try:
            # Detect target columns from query; default to all columns
            target_cols = getattr(context, 'possible_columns', [])
            target_cols = [c for c in target_cols if c in df.columns]
            subset = target_cols if target_cols else None

            dup_mask = df.duplicated(subset=subset, keep=False)
            dup_df = df[dup_mask]

            if dup_df.empty:
                return CapabilityResult(
                    facts={"duplicate_count": 0, "message": "No duplicates found."},
                    narrative_hint="No duplicate rows were found in the dataset.",
                )

            locator = LocatorBuilder().build(df, dup_mask, getattr(context, 'dko', None))
            preview = [self._row_to_dict(r) for _, r in dup_df.head(3).iterrows()]

            evidence = EvidenceReference(
                type=EvidenceType.DUPLICATES,
                dataset_id=context.dataset_id,
                locator=locator,
                column_names=target_cols or list(df.columns[:5]),
                description=f"{len(dup_df)} duplicate rows found",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                preview_rows=preview,
                metadata={
                    "duplicate_count": int(len(dup_df)),
                    "total_rows": int(len(df)),
                    "columns_checked": target_cols or "all",
                },
            )

            return CapabilityResult(
                facts={
                    "duplicate_count": int(len(dup_df)),
                    "total_rows": int(len(df)),
                    "duplicate_percentage": round(len(dup_df) / len(df) * 100, 2),
                    "columns_checked": target_cols or "all",
                },
                evidence=evidence,
                narrative_hint=f"{len(dup_df)} duplicate rows were found ({round(len(dup_df)/len(df)*100,1)}% of data).",
            )
        except Exception as e:
            logger.error(f"DuplicateCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
