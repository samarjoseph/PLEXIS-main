"""MissingValueCapability — analyzes missing/null values in the dataset."""
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
    'missing', 'null', 'empty', 'blank', 'nan', 'none', 'not filled',
    'incomplete', 'no value', 'absent', 'gaps', 'gap in',
]


class MissingValueCapability(IAnalyticalCapability):
    """Analyzes missing/null values across the dataset or a specific column."""

    @property
    def capability_id(self) -> str:
        return "missing_values"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        try:
            target_cols = getattr(context, 'possible_columns', [])
            target_cols = [c for c in target_cols if c in df.columns]

            if target_cols:
                # Analyze specific columns
                col = target_cols[0]
                missing_mask = df[col].isna()
                missing_df = df[missing_mask]
                missing_count = int(missing_mask.sum())
                missing_pct = round(missing_count / len(df) * 100, 2)

                facts = {
                    "column": col,
                    "missing_count": missing_count,
                    "missing_percentage": missing_pct,
                    "total_rows": int(len(df)),
                }
                narrative = f"{missing_count} missing values in '{col}' ({missing_pct}% of rows)."

                if missing_df.empty:
                    return CapabilityResult(facts=facts, narrative_hint=narrative)

                locator = LocatorBuilder().build(df, missing_mask, getattr(context, 'dko', None))
                preview = [self._row_to_dict(r) for _, r in missing_df.head(3).iterrows()]

                evidence = EvidenceReference(
                    type=EvidenceType.MISSING,
                    dataset_id=context.dataset_id,
                    locator=locator,
                    column_names=[col],
                    description=f"{missing_count} missing values in '{col}'",
                    source_query=context.message,
                    dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                    preview_rows=preview,
                    metadata=facts,
                )
            else:
                # Dataset-wide missing value summary
                missing_per_col = df.isnull().sum()
                missing_cols = missing_per_col[missing_per_col > 0].sort_values(ascending=False)

                facts = {
                    "total_missing_cells": int(df.isnull().sum().sum()),
                    "columns_with_missing": int(len(missing_cols)),
                    "total_columns": int(len(df.columns)),
                    "missing_by_column": {
                        col: {"count": int(cnt), "pct": round(cnt / len(df) * 100, 2)}
                        for col, cnt in missing_cols.head(10).items()
                    },
                }
                narrative = (
                    f"{facts['total_missing_cells']} missing cells across "
                    f"{facts['columns_with_missing']} columns."
                )

                # Build evidence for the most-missing rows
                any_missing_mask = df.isnull().any(axis=1)
                if any_missing_mask.any():
                    locator = LocatorBuilder().build(df, any_missing_mask, getattr(context, 'dko', None))
                    missing_rows_df = df[any_missing_mask]
                    preview = [self._row_to_dict(r) for _, r in missing_rows_df.head(3).iterrows()]
                    evidence = EvidenceReference(
                        type=EvidenceType.MISSING,
                        dataset_id=context.dataset_id,
                        locator=locator,
                        column_names=list(missing_cols.head(5).index),
                        description=f"Rows with missing values ({int(any_missing_mask.sum())} rows)",
                        source_query=context.message,
                        dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                        preview_rows=preview,
                        metadata=facts,
                    )
                else:
                    evidence = None

            return CapabilityResult(
                facts=facts,
                evidence=evidence if 'evidence' in dir() else None,
                narrative_hint=narrative,
            )
        except Exception as e:
            logger.error(f"MissingValueCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
