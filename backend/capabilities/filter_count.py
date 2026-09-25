"""FilterCountCapability — counts rows matching a filter condition."""
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
    'how many', 'count', 'number of', 'total number', 'how much',
    'how often', 'frequency', 'occurrences', 'instances of',
]


class FilterCountCapability(IAnalyticalCapability):
    """Counts rows matching filter conditions derived from the context."""

    @property
    def capability_id(self) -> str:
        return "filter_count"

    def can_handle(self, context: "ExecutionContext") -> bool:
        if not getattr(context, 'dataset_id', None):
            return False
        return self._keyword_match(
            context.normalized_query or context.message, _KEYWORDS
        )

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        try:
            filters = getattr(context, 'filters', []) or []
            possible_cols = getattr(context, 'possible_columns', [])

            if not filters:
                # No filters extracted — just return total row count with dataset summary
                col = self._detect_target_column(context, df)
                if col:
                    value_counts = df[col].value_counts().head(10)
                    facts = {
                        "total_rows": int(len(df)),
                        "column": col,
                        "value_counts": {str(k): int(v) for k, v in value_counts.items()},
                    }
                    return CapabilityResult(
                        facts=facts,
                        narrative_hint=f"The dataset has {len(df)} rows. Distribution of {col}: {dict(list(value_counts.items())[:5])}.",
                    )
                return CapabilityResult(
                    facts={"total_rows": int(len(df))},
                    narrative_hint=f"The dataset contains {len(df)} total rows.",
                )

            # Apply available filters
            mask = pd.Series([True] * len(df), index=df.index)
            applied = []
            for f in filters:
                col = f.get('col') or f.get('column')
                val = f.get('val') or f.get('value')
                op = f.get('op', 'eq')
                if col and col in df.columns and val is not None:
                    try:
                        if op == 'eq':
                            mask &= df[col].astype(str).str.lower() == str(val).lower()
                        elif op == 'gt':
                            mask &= pd.to_numeric(df[col], errors='coerce') > float(val)
                        elif op == 'lt':
                            mask &= pd.to_numeric(df[col], errors='coerce') < float(val)
                        elif op == 'contains':
                            mask &= df[col].astype(str).str.lower().str.contains(str(val).lower(), na=False)
                        applied.append(f"{col} {op} {val}")
                    except Exception as fe:
                        logger.debug(f"Filter application failed: {fe}")

            count = int(mask.sum())
            filter_desc = " AND ".join(applied) if applied else "applied filters"
            filtered_df = df[mask]

            if count > 0:
                locator = LocatorBuilder().build(df, mask, getattr(context, 'dko', None))
                preview = [self._row_to_dict(r) for _, r in filtered_df.head(3).iterrows()]
                evidence = EvidenceReference(
                    type=EvidenceType.FILTERED,
                    dataset_id=context.dataset_id,
                    locator=locator,
                    column_names=possible_cols[:5] if possible_cols else list(df.columns[:5]),
                    description=f"{count} rows matching: {filter_desc}",
                    source_query=context.message,
                    dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                    preview_rows=preview,
                    metadata={"count": count, "filter": filter_desc},
                )
            else:
                evidence = None

            return CapabilityResult(
                facts={
                    "count": count,
                    "total_rows": int(len(df)),
                    "percentage": round(count / len(df) * 100, 2),
                    "filter": filter_desc,
                },
                evidence=evidence,
                narrative_hint=f"{count} rows match the condition ({round(count/len(df)*100,1)}% of data).",
            )
        except Exception as e:
            logger.error(f"FilterCountCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
