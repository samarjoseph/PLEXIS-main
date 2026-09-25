"""OutlierCapability — detects statistical outliers using the IQR method."""
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
    'outlier', 'outliers', 'anomaly', 'anomalies', 'unusual', 'abnormal',
    'extreme', 'extremes', 'out of range', 'suspicious', 'weird values',
]


class OutlierCapability(IAnalyticalCapability):
    """Detects statistical outliers in a numeric column using the IQR method."""

    @property
    def capability_id(self) -> str:
        return "outliers"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        col = self._detect_target_column(context, df)
        if not col:
            # No specific column — check all numeric columns, use first with outliers
            numeric_cols = df.select_dtypes(include='number').columns.tolist()
            for c in numeric_cols:
                result = self._analyze_column(c, df, context)
                if result and result.facts.get('outlier_count', 0) > 0:
                    return result
            return CapabilityResult(
                facts={"outlier_count": 0, "message": "No significant outliers detected."},
                narrative_hint="No statistical outliers were detected in the dataset.",
            )
        return self._analyze_column(col, df, context)

    def _analyze_column(self, col: str, df: pd.DataFrame, context) -> CapabilityResult:
        try:
            series = df[col].dropna()
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr

            outlier_mask = (df[col] < lower) | (df[col] > upper)
            outlier_df = df[outlier_mask]

            if outlier_df.empty:
                return CapabilityResult(
                    facts={"column": col, "outlier_count": 0},
                    narrative_hint=f"No outliers detected in {col}.",
                )

            locator = LocatorBuilder().build(df, outlier_mask, getattr(context, 'dko', None))
            preview = [self._row_to_dict(r) for _, r in outlier_df.head(3).iterrows()]

            evidence = EvidenceReference(
                type=EvidenceType.OUTLIERS,
                dataset_id=context.dataset_id,
                locator=locator,
                column_names=[col],
                description=f"{len(outlier_df)} outliers in {col} (IQR method)",
                source_query=context.message,
                dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                preview_rows=preview,
                metadata={
                    "column": col,
                    "outlier_count": int(len(outlier_df)),
                    "lower_fence": float(lower),
                    "upper_fence": float(upper),
                    "q1": float(q1),
                    "q3": float(q3),
                    "iqr": float(iqr),
                },
            )

            return CapabilityResult(
                facts={
                    "column": col,
                    "outlier_count": int(len(outlier_df)),
                    "total_rows": int(len(df)),
                    "lower_fence": float(lower),
                    "upper_fence": float(upper),
                    "outlier_values": outlier_df[col].tolist()[:10],
                },
                evidence=evidence,
                narrative_hint=(
                    f"{len(outlier_df)} outliers found in {col}. "
                    f"Normal range: [{lower:.2f}, {upper:.2f}]. "
                    f"Values outside this range are statistically unusual."
                ),
            )
        except Exception as e:
            logger.error(f"OutlierCapability._analyze_column error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
