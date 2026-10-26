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
    "get_schema",
    "columns_with_missing_values",
    "dataset_completeness",
    "unique_counts",
    "column_with_most_unique_values",
    "column_with_fewest_unique_values",
    "get_numeric_columns",
    "get_text_columns",
    "missing_count_total",
    "missing_count_column",
    "column_with_most_missing_values",
    "columns_without_missing_values",
    "duplicate_count",
    "has_duplicates",
    "duplicates",
    "unique_values",
    "column_count",
    "frequency",
    "most_frequent_value",
    "least_frequent_value",
    "missing_values",
    "get_column_names",
    "get_data_types",
    "dataset_profile",
    "non_null_counts",
    "missing_percentages",
    "describe_column",
    # Deterministic Completeness & Integrity
    "total_cell_count",
    "complete_cell_count",
    "rows_with_missing_count",
    "complete_rows_count",
    "duplicate_rows_after_deduplication",
    "cross_column_condition",
    "rows_age_below_mean",
    "rows_age_equal_median",
    "city_age_stats",
    "cities_above_average_age",
    "city_completeness_report",
    "valid_and_missing_counts",
    "column_uniqueness",
    # Retail domain operations
    "hypothetical_fill_mean",
    "category_normalization",
    "normalized_group_sum",
    "yearly_return_stats",
    "channel_comparison",
    "rating_threshold_stats",
    "city_return_rate",
    "country_return_rate",
    "overall_return_rate",
    "year_above_median_count",
    "weighted_average",
    "peak_month_profit",
    "category_profit_margins",
    "average_order_value",
    "customer_lifetime_value_proxy",
    "year_agreement",
    "margin_aggregation_comparison",
    "promotion_code_usage",
    "top_country_in_year",
    "top_category_per_year",
    "order_id_vs_duplicates",
    "year_over_year_comparison",
    "return_flag_status_mismatch",
    "missingness_implications",
    "discount_profit_correlation",
    "hypothetical",
    "quantiles",
    "rows_below_mean",
    "rows_above_mean",
    "rows_above_median",
    "rows_below_median",
    "rows_equal_median",
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
    "group_count_filtered",
    "group_min", "group_max", "group_median", "pair_frequencies",
    "compound_filter",
    "crosstab", "grouped_rate", "two_factor_aggregation",
    "grouped_binary_comparison", "grouped_multi_stat", "binned_target_rate",
    "zero_vs_positive_comparison",
    "binary_indicator_comparison",
    "filtered_group_ranking",
    "median_split_comparison",
    "tail_risk_group_rate",
    "date_month_audit",
    "audit_numeric_conversion",
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
    "group_metric_difference", "overall_event_rate", "derived_group_comparison",
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
    "mean", "median", "sum", "std", "variance", "range",
    "top_n", "bottom_n", "correlation", "covariance",
    "histogram", "quantile", "outliers",
    "group_mean", "group_sum",
})

# Operations that require an orderable column (numeric, datetime, date, string)
ORDERABLE_OPERATIONS = frozenset({
    "min", "max", "group_min", "group_max",
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

    intent: str = "DATA_OPERATION"           # Descriptive label, e.g. "highest_age"
    operation: str = ""                      # Canonical operation from SUPPORTED_OPERATIONS
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
