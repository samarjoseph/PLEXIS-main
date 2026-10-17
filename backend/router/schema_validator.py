"""
SchemaValidator — validates LLM interpretation output against the dataset schema.

PURPOSE:
  After the LLM produces a structured intent/operation, this module verifies:
    - operation.type is in the supported operations list
    - operation.column exists in the dataset
    - column dtype is compatible with the operation (e.g. no MIN on text)
    - operation-specific parameters are valid (n, order, operator, func)

  If validation fails, returns a typed ValidationResult with a human-readable
  error. The router treats this as a failed interpretation and does NOT execute.

WHAT THIS DOES NOT DO:
  - Does not make semantic decisions
  - Does not re-interpret the query
  - Does not guess missing parameters
  - Does not silently substitute wrong columns

INTEGRATION:
  Called by MasterRouter after _llm_interpret() returns.
  Result attached to context; engine can inspect context.interpretation_error.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Supported operation types (maps to capability_id or spreadsheet operate op)
SUPPORTED_OPERATIONS = {
    "GET_NUMERIC_COLUMNS",
    "COLUMNS_WITH_MISSING_VALUES",
    "DATASET_COMPLETENESS",
    "UNIQUE_COUNTS",
    "COLUMN_WITH_MOST_UNIQUE_VALUES",
    "COLUMN_WITH_FEWEST_UNIQUE_VALUES",
    "GET_TEXT_COLUMNS",
    "GET_ROW_COUNT",
    "RANGE",
    "UNIQUE_COUNT",
    "MOST_FREQUENT_VALUE",
    "LEAST_FREQUENT_VALUE",
    "GET_COLUMN_COUNT",
    "MISSING_COUNT_TOTAL",
    "MISSING_COUNT_COLUMN",
    "COLUMN_WITH_MOST_MISSING_VALUES",
    "COLUMNS_WITHOUT_MISSING_VALUES",
    "DUPLICATE_COUNT",
    "HAS_DUPLICATES",
    "GET_SCHEMA",
    "GET_COLUMN_NAMES",
    "GET_DATA_TYPES",
    "DATASET_PROFILE",
    "NON_NULL_COUNTS",
    "MISSING_PERCENTAGES",
    "VALUE_COUNTS",
    "DESCRIBE_COLUMN",
    # Aggregate operations -> AnalysisEngine
    "MIN",
    "MAX",
    "SUM",
    "MEAN",
    "MEDIAN",
    "STD",
    "COUNT",
    # Discovery
    "TOP_N",
    "BOTTOM_N",
    "FIND_DUPLICATES",
    "FIND_MISSING",
    "FIND_OUTLIERS",
    "UNIQUE_VALUES",
    "MISSING_VALUES",
    "FILTER",
    "CORRELATION",
    "AGGREGATE",
    "GROUP_SUM",
    "GROUP_MEAN",
    "GROUP_COUNT",
    "GROUP_MIN",
    "GROUP_MAX",
    "PAIR_FREQUENCIES",
    "COMPOUND_FILTER",
    "QUANTILE",
    "QUANTILES",
    "HYPOTHETICAL",
    "HYPOTHETICAL_FILL_MEAN",
    "ROWS_BELOW_MEAN",
    "ROWS_ABOVE_MEAN",
    "ROWS_BELOW_MEDIAN",
    "ROWS_ABOVE_MEDIAN",
    "ROWS_EQUAL_MEDIAN",
    "YEAR_AGREEMENT",
    "CATEGORY_PROFIT_MARGINS",
    "ORDER_ID_VS_DUPLICATE_ROWS",
    "RETURN_FLAG_STATUS_MISMATCH",
    "MISSINGNESS_IMPLICATIONS",
    "DISCOUNT_PROFIT_CORRELATION",
    "PROMOTION_CODE_USAGE",
    "TOP_COUNTRY_IN_YEAR",
    "TOP_CATEGORY_PER_YEAR",
    "OVERALL_RETURN_RATE",
    "COUNTRY_RETURN_RATE",
    "PEAK_MONTH_PROFIT",
    "CATEGORY_NORMALIZATION",
    "NORMALIZED_GROUP_SUM",
    "YEARLY_RETURN_STATS",
    "CHANNEL_COMPARISON",
    "RATING_THRESHOLD_STATS",
    "CITY_RETURN_RATE",
    "YEAR_ABOVE_MEDIAN_COUNT",
    "WEIGHTED_AVERAGE",
    "AVERAGE_ORDER_VALUE",
    "CUSTOMER_LIFETIME_VALUE_PROXY",
    "MARGIN_AGGREGATION_COMPARISON",
    "YEAR_OVER_YEAR_COMPARISON",
    "SORT_ROWS",
    "GROUP_MEDIAN",
    # Multi-dimensional grouping & grouped target rates (Cluster A & B)
    "CROSSTAB",
    "GROUPED_RATE",
    "TWO_FACTOR_AGGREGATION",
    "GROUPED_BINARY_COMPARISON",
    "GROUPED_MULTI_STAT",
    "BINNED_TARGET_RATE",
    "ZERO_VS_POSITIVE_COMPARISON",
    "BINARY_INDICATOR_COMPARISON",
    "FILTERED_GROUP_RANKING",
    "MEDIAN_SPLIT_COMPARISON",
    "TAIL_RISK_GROUP_RATE",
    "DATE_MONTH_AUDIT",
}

# ── Generic token taxonomy: distinguishing columns, metrics, and aliases ──────
ROW_COUNT_ALIASES = frozenset({
    "count", "row_count", "rows", "n_rows", "records", "frequency", "size", "total_rows"
})

RANKING_DERIVED_ALIASES = frozenset({
    "count", "row_count", "rows", "frequency", "size",
    "rate", "percentage", "proportion", "ratio",
    "difference", "absolute_difference", "abs_diff", "absolute_difference_mean", "diff",
    "mean", "average", "median", "sum", "total", "std", "min", "max",
    "target_positive_rate", "target-positive_rate", "target_rate", "positive_rate"
})

TARGET_RATE_ALIASES = frozenset({
    "target_positive_rate", "target-positive_rate", "target_rate", "positive_rate",
    "target_percentage", "target_proportion"
})

NO_COLUMN_REQUIRED_OPS = frozenset({
    "PAIR_FREQUENCIES", "COMPOUND_FILTER", "FIND_DUPLICATES", "FIND_MISSING",
    "GET_COLUMN_COUNT", "MISSING_COUNT_TOTAL", "COLUMN_WITH_MOST_MISSING_VALUES",
    "COLUMNS_WITHOUT_MISSING_VALUES", "DUPLICATE_COUNT", "HAS_DUPLICATES",
    "GET_ROW_COUNT", "MISSING_VALUES", "UNIQUE_VALUES", "GET_SCHEMA", "COUNT",
    "GET_COLUMN_NAMES", "GET_DATA_TYPES", "DATASET_PROFILE", "NON_NULL_COUNTS",
    "MISSING_PERCENTAGES", "GET_NUMERIC_COLUMNS", "GET_TEXT_COLUMNS",
    "COLUMNS_WITH_MISSING_VALUES", "DATASET_COMPLETENESS", "UNIQUE_COUNTS",
    "COLUMN_WITH_MOST_UNIQUE_VALUES", "COLUMN_WITH_FEWEST_UNIQUE_VALUES",
    "YEAR_AGREEMENT", "CATEGORY_PROFIT_MARGINS", "ORDER_ID_VS_DUPLICATE_ROWS",
    "RETURN_FLAG_STATUS_MISMATCH", "MISSINGNESS_IMPLICATIONS",
    "DISCOUNT_PROFIT_CORRELATION", "OVERALL_RETURN_RATE", "COUNTRY_RETURN_RATE",
    "YEARLY_RETURN_STATS", "CHANNEL_COMPARISON", "CITY_RETURN_RATE",
    "AVERAGE_ORDER_VALUE", "CUSTOMER_LIFETIME_VALUE_PROXY",
    "MARGIN_AGGREGATION_COMPARISON", "TOP_CATEGORY_PER_YEAR",
})

# Operations that require a numeric column
NUMERIC_REQUIRED_OPS = {
    "MEAN", "MEDIAN", "STD", "SUM",
    "FIND_OUTLIERS", "CORRELATION",
}

# Operations that require an orderable column (numeric, string, text, date, datetime)
ORDERABLE_REQUIRED_OPS = {"MIN", "MAX"}


# Operations that use a list of columns instead of single column
MULTI_COLUMN_OPS = {"FIND_DUPLICATES", "FIND_MISSING", "CORRELATION"}

# Valid filter operators
VALID_FILTER_OPERATORS = {">", "<", ">=", "<=", "==", "!=", "contains", "startswith", "endswith"}

# Valid sort/order directions
VALID_ORDERS = {"asc", "desc", "ascending", "descending"}

# Valid aggregate functions
VALID_AGGREGATE_FUNCS = {"mean", "median", "std", "sum", "count", "min", "max"}


@dataclass
class ValidationResult:
    valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    # Corrected operation (minor coercions only, e.g. lowercase → uppercase)
    corrected_operation: Optional[Dict] = None


class SchemaValidator:
    """
    Validates a parsed LLM interpretation against the actual dataset schema.
    """

    def validate(
        self,
        interpretation: Dict,
        columns: List[Dict],
    ) -> ValidationResult:
        """
        Validate the interpretation dict.

        Args:
            interpretation: The parsed LLM output {intent, operation, confidence, reason}.
            columns: Column list from SemanticContextBuilder [{name, type, ...}].

        Returns:
            ValidationResult with valid=True or valid=False + error details.
        """
        intent = interpretation.get("intent", "CONVERSATION")

        # Non-operation intents don't need operation validation
        if intent != "DATA_OPERATION":
            return ValidationResult(valid=True)

        operation = interpretation.get("operation")
        if not operation:
            return ValidationResult(
                valid=False,
                error_code="MISSING_OPERATION",
                error_message="Intent is DATA_OPERATION but no operation was specified.",
            )

        op_type = (operation.get("type") or "").upper()

        # Canonical aliases for common LLM variations
        _OP_ALIASES = {
            "COLUMN_WITHOUT_MISSING_VALUES": "COLUMNS_WITHOUT_MISSING_VALUES",
            "COLUMN_WITH_MISSING_VALUES": "COLUMN_WITH_MOST_MISSING_VALUES",
            "COLUMNS_WITHOUT_MISSING": "COLUMNS_WITHOUT_MISSING_VALUES",
            "COLUMNS_WITH_MISSING": "COLUMNS_WITH_MISSING_VALUES",
            "FEWEST_UNIQUE_VALUES": "COLUMN_WITH_FEWEST_UNIQUE_VALUES",
            "MOST_UNIQUE_VALUES": "COLUMN_WITH_MOST_UNIQUE_VALUES",
            "MOST_MISSING_VALUES": "COLUMN_WITH_MOST_MISSING_VALUES",
        }
        if op_type in _OP_ALIASES:
            op_type = _OP_ALIASES[op_type]
            operation = {**operation, "type": op_type}

        # ── Validate operation type ───────────────────────────────────────────
        if op_type not in SUPPORTED_OPERATIONS:
            return ValidationResult(
                valid=False,
                error_code="UNSUPPORTED_OPERATION",
                error_message=(
                    f"Operation type '{op_type}' is not supported. "
                    f"Supported: {', '.join(sorted(SUPPORTED_OPERATIONS))}"
                ),
            )

        # Build column lookup {name_lower: col_dict}
        col_lookup = {c.get("name", "").lower(): c for c in columns}
        if "route" not in col_lookup:
            has_orig = any("origin" in c for c in col_lookup)
            has_dest = any("dest" in c for c in col_lookup)
            if has_orig and has_dest:
                col_lookup["route"] = {"name": "Route", "type": "categorical"}

        # ── Multi-column operations ───────────────────────────────────────────
        if op_type in {"FIND_DUPLICATES", "FIND_MISSING", "MISSING_VALUES", "UNIQUE_VALUES"}:
            cols = operation.get("columns", [])
            if not isinstance(cols, list) or len(cols) == 0:
                # Default to all columns for FIND_MISSING; first column for FIND_DUPLICATES
                operation = {**operation, "columns": []}
                return ValidationResult(valid=True, corrected_operation=operation)
            invalid = [c for c in cols if c.lower() not in col_lookup]
            if invalid:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=(
                        f"Column(s) {invalid} not found in dataset. "
                        f"Available: {[c.get('name') for c in columns[:20]]}"
                    ),
                )
            return ValidationResult(valid=True)

        if op_type == "CORRELATION":
            col_a = (operation.get("column_a") or "").lower()
            col_b = (operation.get("column_b") or "").lower()
            for cname, label in [(col_a, "column_a"), (col_b, "column_b")]:
                if not cname:
                    return ValidationResult(
                        valid=False,
                        error_code="MISSING_COLUMN",
                        error_message=f"CORRELATION requires '{label}'.",
                    )
                if cname not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Column '{cname}' not found for CORRELATION.",
                    )
                if col_lookup[cname].get("type") != "numeric":
                    return ValidationResult(
                        valid=False,
                        error_code="TYPE_MISMATCH",
                        error_message=f"CORRELATION requires numeric columns; '{cname}' is {col_lookup[cname].get('type')}.",
                    )
            return ValidationResult(valid=True)

        # ── Grouping operations ───────────────────────────────────────────────
        if op_type in {"GROUP_MEAN", "GROUP_SUM", "GROUP_COUNT", "GROUP_MEDIAN", "GROUP_MIN", "GROUP_MAX"}:
            grp_raw = (operation.get("column") or operation.get("group_col") or operation.get("group_by") or "").strip().lower()
            if not grp_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message=f"Operation {op_type} requires a grouping column.",
                )
            if grp_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{grp_raw}' not found in dataset. Available columns: {[c.get('name') for c in columns[:20]]}",
                )
            corrected = {**operation, "column": col_lookup[grp_raw]["name"]}
            val_raw = (operation.get("value_column") or operation.get("val_col") or "").strip().lower()
            if val_raw:
                if val_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Value column '{val_raw}' not found in dataset.",
                    )
                corrected["value_column"] = col_lookup[val_raw]["name"]
                if op_type in {"GROUP_MEAN", "GROUP_SUM", "GROUP_MEDIAN"} and col_lookup[val_raw].get("type") not in ("numeric", "unknown"):
                    return ValidationResult(
                        valid=False,
                        error_code="TYPE_MISMATCH",
                        error_message=f"Operation {op_type} requires a numeric value column, but '{val_raw}' is type '{col_lookup[val_raw].get('type')}'.",
                    )
            return ValidationResult(valid=True, corrected_operation=corrected)

        # ── Multi-dimensional grouping & grouped target rates (Cluster A) ─────
        if op_type == "CROSSTAB":
            c1_raw = (operation.get("column") or operation.get("col1") or "").strip().lower()
            c2_raw = (operation.get("group_by") or operation.get("col2") or "").strip().lower()
            if not c1_raw or not c2_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="CROSSTAB requires both 'column' and 'group_by' columns.",
                )
            if c1_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{c1_raw}' not found in dataset for CROSSTAB.",
                )
            if c2_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Group column '{c2_raw}' not found in dataset for CROSSTAB.",
                )
            corrected = {**operation, "column": col_lookup[c1_raw]["name"], "group_by": col_lookup[c2_raw]["name"]}
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "GROUPED_RATE":
            tgt_raw = (operation.get("target_column") or operation.get("column") or "").strip().lower()
            grp_raw = (operation.get("group_by") or operation.get("group_col") or "").strip().lower()
            if not tgt_raw or not grp_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="GROUPED_RATE requires both 'target_column' and 'group_by' columns.",
                )
            if tgt_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Target column '{tgt_raw}' not found in dataset for GROUPED_RATE.",
                )
            if grp_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Group column '{grp_raw}' not found in dataset for GROUPED_RATE.",
                )
            corrected = {
                **operation,
                "target_column": col_lookup[tgt_raw]["name"],
                "column": col_lookup[tgt_raw]["name"],
                "group_by": col_lookup[grp_raw]["name"]
            }
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "TWO_FACTOR_AGGREGATION":
            c1_raw = (operation.get("group_by") or operation.get("col1") or "").strip().lower()
            c2_raw = (operation.get("secondary_group") or operation.get("col2") or "").strip().lower()
            v_raw = (operation.get("value_column") or operation.get("column") or "").strip().lower()
            if not c1_raw or not c2_raw or not v_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="TWO_FACTOR_AGGREGATION requires 'group_by', 'secondary_group', and 'value_column'.",
                )
            if c1_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Primary group column '{c1_raw}' not found in dataset.",
                )
            if c2_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Secondary group column '{c2_raw}' not found in dataset.",
                )
            if v_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{v_raw}' not found in dataset.",
                )
            if col_lookup[v_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"TWO_FACTOR_AGGREGATION requires numeric value column, but '{v_raw}' is type '{col_lookup[v_raw].get('type')}'.",
                )
            corrected = {
                **operation,
                "group_by": col_lookup[c1_raw]["name"],
                "secondary_group": col_lookup[c2_raw]["name"],
                "value_column": col_lookup[v_raw]["name"],
                "column": col_lookup[c1_raw]["name"],
            }
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "GROUPED_BINARY_COMPARISON":
            grp_raw = (operation.get("group_by") or operation.get("column") or "").strip().lower()
            bin_raw = (operation.get("binary_column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            if not grp_raw or not bin_raw or not val_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="GROUPED_BINARY_COMPARISON requires 'group_by', 'binary_column', and 'value_column'.",
                )
            if grp_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Group column '{grp_raw}' not found in dataset.",
                )
            if bin_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Binary column '{bin_raw}' not found in dataset.",
                )
            if val_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{val_raw}' not found in dataset.",
                )
            corrected = {
                **operation,
                "group_by": col_lookup[grp_raw]["name"],
                "binary_column": col_lookup[bin_raw]["name"],
                "value_column": col_lookup[val_raw]["name"],
                "column": col_lookup[grp_raw]["name"],
            }
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "GROUPED_MULTI_STAT":
            grp_raw = (operation.get("group_by") or operation.get("column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            tgt_raw = (operation.get("target_column") or "").strip().lower()
            if not grp_raw or not val_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="GROUPED_MULTI_STAT requires 'group_by' and 'value_column'.",
                )
            if grp_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Group column '{grp_raw}' not found in dataset.",
                )
            if val_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{val_raw}' not found in dataset.",
                )
            corrected = {
                **operation,
                "group_by": col_lookup[grp_raw]["name"],
                "value_column": col_lookup[val_raw]["name"],
                "column": col_lookup[grp_raw]["name"],
            }
            if tgt_raw:
                if tgt_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Target column '{tgt_raw}' not found in dataset.",
                    )
                corrected["target_column"] = col_lookup[tgt_raw]["name"]
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "BINNED_TARGET_RATE":
            bin_raw = (operation.get("bin_column") or operation.get("column") or "").strip().lower()
            tgt_raw = (operation.get("target_column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            if not bin_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="BINNED_TARGET_RATE requires a 'bin_column' parameter.",
                )
            if bin_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Bin column '{bin_raw}' not found in dataset.",
                )
            if col_lookup[bin_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"BINNED_TARGET_RATE requires numeric bin column, but '{bin_raw}' is type '{col_lookup[bin_raw].get('type')}'.",
                )
            corrected = {**operation, "bin_column": col_lookup[bin_raw]["name"], "column": col_lookup[bin_raw]["name"]}
            if tgt_raw:
                if tgt_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Target column '{tgt_raw}' not found in dataset.",
                    )
                corrected["target_column"] = col_lookup[tgt_raw]["name"]
            if val_raw:
                if val_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Value column '{val_raw}' not found in dataset.",
                    )
                corrected["value_column"] = col_lookup[val_raw]["name"]
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "ZERO_VS_POSITIVE_COMPARISON":
            split_raw = (operation.get("split_column") or operation.get("column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            if not split_raw or not val_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="ZERO_VS_POSITIVE_COMPARISON requires 'split_column' and 'value_column'.",
                )
            if split_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Split column '{split_raw}' not found in dataset.",
                )
            if val_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{val_raw}' not found in dataset.",
                )
            if col_lookup[split_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"ZERO_VS_POSITIVE_COMPARISON requires numeric split column, but '{split_raw}' is type '{col_lookup[split_raw].get('type')}'.",
                )
            if col_lookup[val_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"ZERO_VS_POSITIVE_COMPARISON requires numeric value column, but '{val_raw}' is type '{col_lookup[val_raw].get('type')}'.",
                )
            corrected = {
                **operation,
                "split_column": col_lookup[split_raw]["name"],
                "value_column": col_lookup[val_raw]["name"],
                "column": col_lookup[val_raw]["name"],
            }
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "BINARY_INDICATOR_COMPARISON":
            bin_raw = (operation.get("binary_column") or operation.get("column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            if not bin_raw or not val_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="BINARY_INDICATOR_COMPARISON requires 'binary_column' and 'value_column'.",
                )
            if bin_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Binary column '{bin_raw}' not found in dataset.",
                )
            if val_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{val_raw}' not found in dataset.",
                )
            if col_lookup[val_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"BINARY_INDICATOR_COMPARISON requires numeric value column, but '{val_raw}' is type '{col_lookup[val_raw].get('type')}'.",
                )
            corrected = {
                **operation,
                "binary_column": col_lookup[bin_raw]["name"],
                "value_column": col_lookup[val_raw]["name"],
                "column": col_lookup[val_raw]["name"],
            }
            return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "FILTERED_GROUP_RANKING":
            grp_raw = (operation.get("group_by") or operation.get("column") or "").strip().lower()
            val_raw = (operation.get("value_column") or "").strip().lower()
            if not grp_raw or not val_raw:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="FILTERED_GROUP_RANKING requires 'group_by' and 'value_column'.",
                )
            if grp_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Group column '{grp_raw}' not found in dataset.",
                )
            if val_raw not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Value column '{val_raw}' not found in dataset.",
                )
            if col_lookup[val_raw].get("type") not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"FILTERED_GROUP_RANKING requires numeric value column, but '{val_raw}' is type '{col_lookup[val_raw].get('type')}'.",
                )
            corrected = {
                **operation,
                "group_by": col_lookup[grp_raw]["name"],
                "value_column": col_lookup[val_raw]["name"],
                "column": col_lookup[val_raw]["name"],
            }
            cond_raw = (operation.get("condition_column") or operation.get("filter_column") or "").strip().lower()
            if cond_raw:
                if cond_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Filter column '{cond_raw}' not found in dataset.",
                    )
                corrected["condition_column"] = col_lookup[cond_raw]["name"]
                corrected["filter_column"] = col_lookup[cond_raw]["name"]
            bin_raw = (operation.get("binary_column") or "").strip().lower()
            if bin_raw:
                if bin_raw not in col_lookup:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=f"Binary column '{bin_raw}' not found in dataset.",
                    )
                corrected["binary_column"] = col_lookup[bin_raw]["name"]
            return ValidationResult(valid=True, corrected_operation=corrected)


        # ── Row count operations ──────────────────────────────────────────────
        if op_type in {"COUNT", "GET_ROW_COUNT"}:
            raw_c = (operation.get("column") or "").strip().lower()
            if raw_c in col_lookup:
                corrected = {**operation, "column": col_lookup[raw_c]["name"]}
                return ValidationResult(valid=True, corrected_operation=corrected)
            if not raw_c or raw_c in ROW_COUNT_ALIASES:
                corrected = {**operation, "column": None}
                return ValidationResult(valid=True, corrected_operation=corrected)
            return ValidationResult(
                valid=False,
                error_code="COLUMN_NOT_FOUND",
                error_message=f"Column '{raw_c}' not found in dataset. Available columns: {[c.get('name') for c in columns[:20]]}",
            )

        # ── Ranking / Sorting operations ──────────────────────────────────────
        if op_type in {"TOP_N", "BOTTOM_N", "SORT_ROWS", "SORT"}:
            raw_c = (operation.get("column") or operation.get("by") or "").strip().lower()
            if not raw_c:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message=f"Operation {op_type} requires a 'column' parameter.",
                )
            if raw_c in col_lookup:
                corrected = {**operation, "column": col_lookup[raw_c]["name"]}
            elif raw_c in RANKING_DERIVED_ALIASES:
                corrected = {**operation, "column": raw_c}
            else:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{raw_c}' not found in dataset. Available columns: {[c.get('name') for c in columns[:20]]}",
                )
            # Parameter validation (n, order, ascending)
            if op_type in ("TOP_N", "BOTTOM_N"):
                n = operation.get("n")
                if n is not None:
                    try:
                        n_int = int(n)
                        if n_int < 1 or n_int > 100000:
                            return ValidationResult(
                                valid=False,
                                error_code="INVALID_PARAMETER",
                                error_message=f"Parameter 'n' must be between 1 and 100000, got {n}.",
                            )
                    except (ValueError, TypeError):
                        return ValidationResult(
                            valid=False,
                            error_code="INVALID_PARAMETER",
                            error_message=f"Parameter 'n' must be an integer, got '{n}'.",
                        )
                order = (operation.get("order") or ("desc" if op_type == "TOP_N" else "asc")).lower()
                if order not in VALID_ORDERS:
                    order = "desc" if op_type == "TOP_N" else "asc"
                corrected["order"] = order
            return ValidationResult(valid=True, corrected_operation=corrected)

        # ── Aggregation operations ────────────────────────────────────────────
        if op_type == "AGGREGATE":
            raw_c = (operation.get("column") or "").strip().lower()
            func = (operation.get("func") or "mean").lower()
            if raw_c not in col_lookup and raw_c in ROW_COUNT_ALIASES and func in ("count", "row_count", ""):
                corrected = {**operation, "column": None, "func": "count"}
                return ValidationResult(valid=True, corrected_operation=corrected)
            if raw_c not in col_lookup and raw_c in TARGET_RATE_ALIASES:
                target_cand = None
                for ckey, cinfo in col_lookup.items():
                    if ckey == "target" or ckey.endswith("_target") or ckey.startswith("target_") or "target" in ckey:
                        target_cand = cinfo["name"]
                        break
                if target_cand:
                    corrected = {**operation, "column": target_cand, "func": "mean"}
                    return ValidationResult(valid=True, corrected_operation=corrected)
                else:
                    return ValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message="Target column not found in dataset for target rate calculation.",
                    )
            if not raw_c:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="Operation AGGREGATE requires a 'column' parameter.",
                )
            if raw_c not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{raw_c}' not found in dataset. Available columns: {[c.get('name') for c in columns[:20]]}",
                )
            col_info = col_lookup[raw_c]
            col_type = col_info.get("type", "unknown")
            if func in ("mean", "median", "std", "sum") and col_type not in ("numeric", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"Aggregate function '{func}' requires a numeric column, but '{raw_c}' is type '{col_type}'.",
                )
            if func in ("min", "max") and col_type not in ("numeric", "string", "text", "date", "datetime", "categorical", "unknown"):
                return ValidationResult(
                    valid=False,
                    error_code="TYPE_MISMATCH",
                    error_message=f"Aggregate function '{func}' requires an orderable column, but '{raw_c}' is type '{col_type}'.",
                )
            if func not in VALID_AGGREGATE_FUNCS:
                return ValidationResult(
                    valid=False,
                    error_code="INVALID_PARAMETER",
                    error_message=f"Aggregate function '{func}' is not valid. Use: {', '.join(sorted(VALID_AGGREGATE_FUNCS))}",
                )
            corrected = {**operation, "column": col_info["name"]}
            return ValidationResult(valid=True, corrected_operation=corrected)

        # ── Filter operations ─────────────────────────────────────────────────
        if op_type == "FILTER":
            raw_c = (operation.get("column") or "").strip().lower()
            if raw_c not in col_lookup and raw_c in ROW_COUNT_ALIASES:
                operator = operation.get("operator", ">=")
                if operator not in VALID_FILTER_OPERATORS:
                    return ValidationResult(
                        valid=False,
                        error_code="INVALID_OPERATOR",
                        error_message=f"Filter operator '{operator}' is not valid. Use: {', '.join(sorted(VALID_FILTER_OPERATORS))}",
                    )
                return ValidationResult(valid=True)
            if not raw_c:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMN",
                    error_message="FILTER requires a 'column' parameter.",
                )
            if raw_c not in col_lookup:
                return ValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{raw_c}' not found in dataset. Available columns: {[c.get('name') for c in columns[:20]]}",
                )
            operator = operation.get("operator")
            if operator not in VALID_FILTER_OPERATORS:
                return ValidationResult(
                    valid=False,
                    error_code="INVALID_OPERATOR",
                    error_message=f"Filter operator '{operator}' is not valid. Use: {', '.join(sorted(VALID_FILTER_OPERATORS))}",
                )
            if operation.get("value") is None:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_PARAMETER",
                    error_message="FILTER requires a 'value' parameter.",
                )
            corrected = {**operation, "column": col_lookup[raw_c]["name"]}
            return ValidationResult(valid=True, corrected_operation=corrected)

        # ── Single-column operations (standard fallback) ──────────────────────
        col_name = (operation.get("column") or "").strip().lower()
        if not col_name and op_type not in NO_COLUMN_REQUIRED_OPS:
            return ValidationResult(
                valid=False,
                error_code="MISSING_COLUMN",
                error_message=f"Operation {op_type} requires a 'column' parameter.",
            )

        if col_name and col_name not in col_lookup:
            return ValidationResult(
                valid=False,
                error_code="COLUMN_NOT_FOUND",
                error_message=(
                    f"Column '{col_name}' not found in dataset. "
                    f"Available columns: {[c.get('name') for c in columns[:20]]}"
                ),
            )

        col_info = col_lookup.get(col_name, {})
        col_type = col_info.get("type", "unknown")

        # ── Type compatibility ────────────────────────────────────────────────
        if op_type in NUMERIC_REQUIRED_OPS and col_type not in ("numeric", "unknown"):
            return ValidationResult(
                valid=False,
                error_code="TYPE_MISMATCH",
                error_message=(
                    f"Operation {op_type} requires a numeric column, "
                    f"but '{col_name}' is type '{col_type}'."
                ),
            )

        if op_type in ORDERABLE_REQUIRED_OPS and col_type not in ("numeric", "string", "text", "date", "datetime", "categorical", "unknown"):
            return ValidationResult(
                valid=False,
                error_code="TYPE_MISMATCH",
                error_message=(
                    f"Operation {op_type} requires an orderable column, "
                    f"but '{col_name}' is type '{col_type}'."
                ),
            )

        corrected = {**operation}
        if col_name:
            corrected["column"] = col_info.get("name", col_name)

        return ValidationResult(valid=True, corrected_operation=corrected)

    def map_to_capability_operation(self, operation: Dict) -> Dict:
        """
        Map LLM operation types to the AnalysisEngine capability format.

        The LLM may return MIN/MAX/MEAN/MEDIAN/STD/SUM which are logical operation
        names. The AnalysisEngine uses capability_ids. This bridges the gap.
        """
        op_type = (operation.get("type") or "").upper()

        # MIN → normalized_query will contain 'lowest'/'minimum' for MinValueCapability
        # MAX → normalized_query will contain 'highest'/'maximum' for MaxValueCapability
        # These are handled by the capability's can_handle() which reads from normalized_query.
        # We inject the operation into context.workspace_action for direct dispatch.
        return operation


schema_validator = SchemaValidator()
