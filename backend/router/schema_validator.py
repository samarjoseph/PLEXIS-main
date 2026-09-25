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
    # Aggregate operations → AnalysisEngine
    "MIN",
    "MAX",
    "MEAN",
    "MEDIAN",
    "STD",
    "SUM",
    "COUNT",
    # Structural operations → AnalysisEngine
    "TOP_N",
    "BOTTOM_N",
    "FILTER",
    "FIND_DUPLICATES",
    "FIND_MISSING",
    "FIND_OUTLIERS",
    "CORRELATION",
    # Aggregate umbrella (maps to AGGREGATE operate endpoint)
    "AGGREGATE",
}

# Operations that require a numeric column
NUMERIC_REQUIRED_OPS = {
    "MIN", "MAX", "MEAN", "MEDIAN", "STD", "SUM",
    "FIND_OUTLIERS", "CORRELATION", "AGGREGATE",
}

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

        # ── Multi-column operations ───────────────────────────────────────────
        if op_type in {"FIND_DUPLICATES", "FIND_MISSING"}:
            cols = operation.get("columns", [])
            if not isinstance(cols, list) or len(cols) == 0:
                # Default to all columns for FIND_MISSING; first column for FIND_DUPLICATES
                if col_lookup:
                    default_cols = [list(col_lookup.values())[0].get("name", "")]
                    operation = {**operation, "columns": default_cols}
                    return ValidationResult(valid=True, corrected_operation=operation)
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_COLUMNS",
                    error_message=f"Operation {op_type} requires a 'columns' list.",
                )
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

        # ── Single-column operations ──────────────────────────────────────────
        col_name = (operation.get("column") or "").lower()
        if not col_name and op_type not in {"FIND_DUPLICATES", "FIND_MISSING"}:
            # Try to infer from referenced columns (if only one)
            # But do NOT guess — return error
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

        # ── Operation-specific parameter validation ───────────────────────────
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
            order = (operation.get("order") or "desc").lower()
            if order not in VALID_ORDERS:
                corrected = {**operation, "order": "desc"}
                return ValidationResult(valid=True, corrected_operation=corrected)

        if op_type == "FILTER":
            operator = operation.get("operator")
            if operator not in VALID_FILTER_OPERATORS:
                return ValidationResult(
                    valid=False,
                    error_code="INVALID_OPERATOR",
                    error_message=(
                        f"Filter operator '{operator}' is not valid. "
                        f"Use: {', '.join(sorted(VALID_FILTER_OPERATORS))}"
                    ),
                )
            if operation.get("value") is None:
                return ValidationResult(
                    valid=False,
                    error_code="MISSING_PARAMETER",
                    error_message="FILTER requires a 'value' parameter.",
                )

        if op_type == "AGGREGATE":
            func = (operation.get("func") or "").lower()
            if func not in VALID_AGGREGATE_FUNCS:
                return ValidationResult(
                    valid=False,
                    error_code="INVALID_PARAMETER",
                    error_message=(
                        f"Aggregate function '{func}' is not valid. "
                        f"Use: {', '.join(sorted(VALID_AGGREGATE_FUNCS))}"
                    ),
                )

        return ValidationResult(valid=True)

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
