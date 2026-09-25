"""
AnalyticalPlan schema — the structured output from the AnalyticalPlanner.

Rules:
  - target_column MUST be an exact column name from the dataset (validated externally)
  - operation MUST be in SUPPORTED_OPERATIONS
  - plan steps MUST only use SUPPORTED_PLAN_OPS
  - No arbitrary Python, no code strings, no shell commands
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Supported high-level analytical operations ────────────────────────────────
# Keep in sync with PlanValidator and PandasExecutor operation_map.
SUPPORTED_OPERATIONS = frozenset({
    # Descriptive
    "count", "nunique", "mean", "median", "mode", "min", "max",
    "sum", "std", "variance", "range",
    # Ranking
    "top_n", "bottom_n",
    # Filtering
    "filter",
    # Sorting
    "sort",
    # Grouping
    "group_by", "group_mean", "group_sum", "group_count",
    "group_min", "group_max",
    # Quality
    "missing_values", "duplicates", "unique_values", "outliers",
    # Distribution
    "histogram", "frequency", "quantile",
    # Relationships
    "correlation", "covariance",
    # Row retrieval
    "locate_row", "locate_rows",
    # Comparison
    "compare_groups", "compare_columns",
})

# ── Plan step operations (executor level) ─────────────────────────────────────
SUPPORTED_PLAN_OPS = frozenset({
    "select_column", "drop_nulls", "to_numeric",
    "aggregate",  # {function: max|min|mean|median|std|sum|count|var|range}
    "locate_rows",
    "sort",
    "filter",
    "group_by",
    "compare",
    "locate_row",
    "top_n", "bottom_n",
    "nunique", "mode",
    "frequency", "quantile", "histogram",
    "correlation", "covariance",
    "outliers",
})

# Operations that require a numeric column
NUMERIC_OPERATIONS = frozenset({
    "mean", "median", "min", "max", "sum", "std", "variance", "range",
    "top_n", "bottom_n", "correlation", "covariance",
    "histogram", "quantile", "outliers",
    "group_mean", "group_sum", "group_min", "group_max",
})

# Forbidden code strings in any plan field
_FORBIDDEN_PATTERNS = [
    "eval(", "exec(", "__import__", "os.system", "subprocess",
    "open(", "import ", "lambda ", "compile(",
]


@dataclass
class AnalyticalPlan:
    """
    The structured output from the AnalyticalPlanner.

    Produced by the LLM (temperature=0.0) and validated by PlanValidator
    before being passed to PandasExecutor.
    """

    intent: str                              # Descriptive label, e.g. "highest_age"
    operation: str                           # Canonical operation from SUPPORTED_OPERATIONS
    target_column: Optional[str] = None      # Exact column name (validated against schema)
    columns: List[str] = field(default_factory=list)  # Secondary columns
    parameters: Dict[str, Any] = field(default_factory=dict)
    plan: List[Dict[str, Any]] = field(default_factory=list)  # Step-by-step executor plan
    raw: Dict[str, Any] = field(default_factory=dict)          # Original LLM output

    # -------------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "AnalyticalPlan":
        """Build from LLM output dict. Does NOT validate — call validation_error() after."""
        op = (d.get("operation") or "").lower().strip()
        return cls(
            intent=str(d.get("intent") or "unknown"),
            operation=op,
            target_column=d.get("target_column") or d.get("column") or None,
            columns=list(d.get("columns") or []),
            parameters=dict(d.get("parameters") or {}),
            plan=list(d.get("plan") or []),
            raw=d,
        )

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validation_error(self, context: Optional[dict] = None) -> Optional[str]:
        """
        Return an error string if the plan is invalid, else None.

        Args:
            context: Optional planner context (used to validate column names).
        """
        if not self.intent:
            return "Plan missing 'intent'"
        if not self.operation:
            return "Plan missing 'operation'"
        if self.operation not in SUPPORTED_OPERATIONS:
            return f"Unsupported operation: '{self.operation}'"

        # Security: reject forbidden code strings anywhere in the plan
        plan_str = str(self.raw)
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in plan_str:
                return f"Forbidden code pattern detected: '{pattern}'"

        # Validate plan steps
        for i, step in enumerate(self.plan):
            op_name = (step.get("op") or "").lower()
            if op_name and op_name not in SUPPORTED_PLAN_OPS:
                return f"Unsupported plan step op at index {i}: '{op_name}'"

        # Column validation against real schema (if context available)
        if context and self.target_column:
            columns = context.get("columns", [])
            col_lower = {c.lower() for c in columns}
            if self.target_column.lower() not in col_lower:
                return (
                    f"Column '{self.target_column}' not found in dataset. "
                    f"Available: {columns[:10]}"
                )

        # Numeric column requirement check (if column_types available)
        if context and self.operation in NUMERIC_OPERATIONS and self.target_column:
            col_types = context.get("column_types", {})
            dtype = col_types.get(self.target_column) or col_types.get(
                next((c for c in col_types if c.lower() == self.target_column.lower()), ""),
                "",
            )
            if dtype and not _is_numeric_dtype(dtype):
                return (
                    f"Operation '{self.operation}' requires a numeric column, "
                    f"but '{self.target_column}' has type '{dtype}'."
                )

        return None  # Valid

    def is_valid(self, context: Optional[dict] = None) -> bool:
        return self.validation_error(context) is None


def _is_numeric_dtype(dtype: str) -> bool:
    return any(t in dtype.lower() for t in ("int", "float", "double", "decimal", "num"))
