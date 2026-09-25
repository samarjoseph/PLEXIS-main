"""RowExplainCapability — handles explicit workspace row-explain actions."""
import logging
from typing import TYPE_CHECKING, Any, Dict

import pandas as pd

from capabilities.base import CapabilityResult, IAnalyticalCapability
from evidence.contracts import EvidenceReference, EvidenceType
from evidence.locator_builder import LocatorBuilder

if TYPE_CHECKING:
    from core.context import ExecutionContext

logger = logging.getLogger(__name__)


class RowExplainCapability(IAnalyticalCapability):
    """
    Handles workspace_action.type == 'explain_row' or 'explain_selection'.
    Triggered by right-click → 'Explain this row' in the DatasetWorkspace.

    The workspace sends row data directly in workspace_action, so no DataFrame
    lookup is needed — the capability just packages it into a response.
    """

    @property
    def capability_id(self) -> str:
        return "row_explain"

    def can_handle(self, context: "ExecutionContext") -> bool:
        action = getattr(context, 'workspace_action', None)
        if not action:
            return False
        action_type = action.get('type', '')
        return action_type in ('explain_row', 'explain_selection', 'ask_about_rows')

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        try:
            action = context.workspace_action or {}
            action_type = action.get('type', 'explain_row')
            row_indices = action.get('row_indices', [])
            row_data = action.get('row_data', {})
            column_names = action.get('column_names', list(df.columns[:10]))

            # Resolve actual rows from DataFrame when indices are given
            if row_indices and df is not None:
                valid_indices = [i for i in row_indices if i < len(df)]
                if valid_indices:
                    selected_df = df.iloc[valid_indices]
                    mask = df.index.isin(selected_df.index)
                    locator = LocatorBuilder().build(df, mask, getattr(context, 'dko', None))
                    preview = [
                        {k: self._safe_value(v) for k, v in row.to_dict().items()}
                        for _, row in selected_df.head(5).iterrows()
                    ]
                    description = (
                        f"Selected {len(valid_indices)} row(s) for explanation"
                        if len(valid_indices) > 1
                        else f"Row {valid_indices[0]} selected for explanation"
                    )
                    evidence = EvidenceReference(
                        type=EvidenceType.ROWS,
                        dataset_id=context.dataset_id,
                        locator=locator,
                        column_names=column_names,
                        description=description,
                        source_query=context.message,
                        dataset_fingerprint=getattr(context, 'dataset_fingerprint', ''),
                        preview_rows=preview,
                        metadata={
                            "row_indices": valid_indices,
                            "action_type": action_type,
                        },
                    )
                    facts = {
                        "row_count": len(valid_indices),
                        "rows": preview,
                        "action_type": action_type,
                    }
                    return CapabilityResult(
                        facts=facts,
                        evidence=evidence,
                        narrative_hint=f"Explaining {len(valid_indices)} selected row(s): {preview[:2]}",
                    )

            # Fallback: use row_data passed from frontend
            if row_data:
                safe_row = {k: self._safe_value(v) for k, v in row_data.items()}
                facts = {"row_count": 1, "rows": [safe_row], "action_type": action_type}
                return CapabilityResult(
                    facts=facts,
                    narrative_hint=f"Explaining row data: {safe_row}",
                )

            return CapabilityResult(
                facts={"error": "No row data provided for explanation."},
                success=False, error="No row data"
            )
        except Exception as e:
            logger.error(f"RowExplainCapability.execute error: {e}", exc_info=True)
            return CapabilityResult(facts={"error": str(e)}, success=False, error=str(e))
