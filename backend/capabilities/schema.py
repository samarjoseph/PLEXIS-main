from typing import TYPE_CHECKING
import pandas as pd
from capabilities.base import IAnalyticalCapability, CapabilityResult

if TYPE_CHECKING:
    from core.context import ExecutionContext

class GetSchemaCapability(IAnalyticalCapability):
    @property
    def capability_id(self) -> str:
        return "get_schema"

    def can_handle(self, context: "ExecutionContext") -> bool:
        op_type = getattr(context, 'operation', {}).get('type', '')
        if op_type == "GET_SCHEMA":
            return True
        
        # Fallback if no operation type but strong keyword match
        intent = getattr(context, 'intent', '')
        if intent == "DATA_OPERATION" and not op_type:
            query = (context.normalized_query or getattr(context, 'message', '')).lower()
            return self._keyword_match(query, [
                "what are the columns", 
                "what columns",
                "list columns", 
                "list all fields", 
                "show columns",
                "column names"
            ])
        return False

    def execute(self, context: "ExecutionContext", df: pd.DataFrame) -> CapabilityResult:
        columns = df.columns.tolist()
        
        # Build factual payload
        facts = {
            "query_type": "columns",
            "columns": columns,
            "column_count": len(columns),
            "row_count": len(df)
        }
        
        # The narrative hint replaces the need for the LLM to invent things
        # It provides the deterministic, authoritative text base.
        narrative_hint = (
            f"The dataset contains {len(columns)} columns: " + ", ".join(columns) + "."
        )
        
        return CapabilityResult(
            facts=facts,
            narrative_hint=narrative_hint,
            success=True
        )
