"""CorrelationCapability — computes Pearson correlation between two numeric columns."""
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

import pandas as pd

from capabilities.base import CapabilityResult, IAnalyticalCapability
from evidence.contracts import EvidenceReference, EvidenceType

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)

_KEYWORDS = [
    'correlation', 'correlate', 'correlated', 'relationship between',
    'vs ', 'versus', 'related to', 'associated with', 'depends on',
    'influence', 'affect', 'impact',
]


class CorrelationCapability(IAnalyticalCapability):
    """Computes Pearson correlation between two numeric columns."""

    @property
    def capability_id(self) -> str:
        return "correlation"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        try:
            numeric_cols = df.select_dtypes(include='number').columns.tolist()
            if len(numeric_cols) < 2:
                return CapabilityResult(
                    facts={"error": "Need at least 2 numeric columns for correlation."},
                    success=False, error="Insufficient numeric columns"
                )

            col_a, col_b = self._pick_columns(context, numeric_cols)

            corr = df[col_a].corr(df[col_b])
            corr_val = round(float(corr), 4)
            strength = self._describe_correlation(corr_val)

            # Top corr matrix if no specific columns were asked
            corr_matrix = {}
            if len(numeric_cols) <= 10:
                corr_df = df[numeric_cols].corr()
                corr_matrix = {
                    col: {
                        other: round(float(corr_df.loc[col, other]), 4)
                        for other in numeric_cols if other != col
                    }
                    for col in numeric_cols
                }

            evidence = EvidenceReference(
                type=EvidenceType.CORRELATION,
                dataset_id=context.dataset_id,
                column_names=[col_a, col_b],
                description=f"Correlation between {col_a} and {col_b}: r={corr_val} ({strength})",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                metadata={
                    "col_a": col_a, "col_b": col_b,
                    "correlation": corr_val, "strength": strength,
                },
            )

            return CapabilityResult(
                facts={
                    "col_a": col_a, "col_b": col_b,
                    "correlation": corr_val, "strength": strength,
                    "correlation_matrix": corr_matrix,
                },
                evidence=evidence,
                narrative_hint=(
                    f"The Pearson correlation between {col_a} and {col_b} is "
                    f"{corr_val} ({strength} relationship)."
                ),
            )
        except Exception as e:
            logger.error(f"CorrelationCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))

    def _pick_columns(self, context, numeric_cols: List[str]) -> Tuple[str, str]:
        possible = getattr(context, 'possible_columns', [])
        matched = [c for c in possible if c in numeric_cols]
        if len(matched) >= 2:
            return matched[0], matched[1]
        if len(matched) == 1:
            return matched[0], numeric_cols[1] if numeric_cols[0] == matched[0] else numeric_cols[0]
        return numeric_cols[0], numeric_cols[1]

    def _describe_correlation(self, r: float) -> str:
        abs_r = abs(r)
        direction = "positive" if r >= 0 else "negative"
        if abs_r >= 0.9:
            return f"very strong {direction}"
        elif abs_r >= 0.7:
            return f"strong {direction}"
        elif abs_r >= 0.5:
            return f"moderate {direction}"
        elif abs_r >= 0.3:
            return f"weak {direction}"
        else:
            return "very weak / negligible"
