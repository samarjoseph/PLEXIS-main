"""
PlanValidator — deterministic validation of AnalyticalPlan against real dataset schema.

This is NOT an LLM. It is a deterministic gate.

Validates:
  1. Schema validity (fields, types, operation names, plan step ops)
  2. Dataset validity (column exists, column type compatible, fingerprint match)
  3. Logical validity (numeric op on numeric column, no mean(name), etc.)
  4. Security validity (no eval/exec/import/os.system)

Column type checking uses the CANONICAL vocabulary:
  integer | float | numeric | string | categorical | boolean | datetime | unknown

Returns a PlanValidationResult with a typed error_code if invalid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from planner.schema import AnalyticalPlan, NUMERIC_OPERATIONS, ORDERABLE_OPERATIONS, _FORBIDDEN_PATTERNS

logger = logging.getLogger(__name__)

# ── Canonical types considered numeric by the validator ───────────────────────
# These align exactly with PlannerContext's _NUMERIC_CANONICAL set.
_NUMERIC_CANONICAL = frozenset({"integer", "float", "numeric"})

# Raw pandas dtype substrings — used as a last-resort fallback if context
# provides non-canonical types (e.g., "int64", "float32").
_NUMERIC_DTYPE_HINTS = ("int", "float", "double", "decimal", "num")

# Canonical types considered orderable (valid for min, max)
_ORDERABLE_CANONICAL = frozenset({"integer", "float", "numeric", "datetime", "date", "string", "categorical"})
_ORDERABLE_DTYPE_HINTS = ("int", "float", "double", "decimal", "num", "date", "time", "str", "object", "char")



@dataclass
class PlanValidationResult:
    valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class PlanValidator:
    """
    Validates an AnalyticalPlan against the real dataset schema.

    All checks are deterministic — no LLM calls.
    """

    def validate(
        self,
        plan: AnalyticalPlan,
        columns: List[str],
        column_types: Dict[str, str],
        dataset_fingerprint: Optional[str] = None,
        expected_fingerprint: Optional[str] = None,
    ) -> PlanValidationResult:
        """
        Validate the plan against the real dataset schema.

        Args:
            plan:                 The AnalyticalPlan from the planner.
            columns:              Real column names from the dataset.
            column_types:         {col_name: canonical_type_str}
            dataset_fingerprint:  SHA-256 of the current dataset.
            expected_fingerprint: Fingerprint stored in a previous analysis (for stale check).

        Returns:
            PlanValidationResult — valid=True or valid=False with error_code.
        """
        # ── 1. Security ───────────────────────────────────────────────────────
        plan_str = str(plan.raw)
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in plan_str:
                return PlanValidationResult(
                    valid=False,
                    error_code="SECURITY_VIOLATION",
                    error_message=f"Forbidden code pattern detected: '{pattern}'",
                )

        # ── 2. Schema validity ────────────────────────────────────────────────
        schema_error = plan.validation_error()  # checks operation, plan steps, etc.
        if schema_error:
            return PlanValidationResult(
                valid=False,
                error_code="SCHEMA_INVALID",
                error_message=schema_error,
            )

        # ── 3. Stale dataset check ────────────────────────────────────────────
        if expected_fingerprint and dataset_fingerprint:
            if dataset_fingerprint != expected_fingerprint:
                return PlanValidationResult(
                    valid=False,
                    error_code="STALE_DATASET",
                    error_message=(
                        "The current dataset has changed since the plan was created. "
                        "Please re-run the analysis."
                    ),
                )

        # ── 4. Column existence (case-insensitive) ────────────────────────────
        col_lower = {c.lower(): c for c in columns}   # {lower: original}

        if plan.target_column:
            if isinstance(plan.target_column, (list, tuple)):
                resolved_list = []
                for tc in plan.target_column:
                    r = self._resolve_column(tc, col_lower)
                    if r is not None:
                        resolved_list.append(r)
                    else:
                        return PlanValidationResult(
                            valid=False,
                            error_code="COLUMN_NOT_FOUND",
                            error_message=(
                                f"Column '{tc}' not found in dataset. "
                                f"Available: {columns[:15]}"
                            ),
                        )
                plan.target_column = resolved_list
            else:
                resolved = self._resolve_column(plan.target_column, col_lower)
                if resolved is not None:
                    # Explicit physical column in dataset takes precedence
                    plan.target_column = resolved
                elif plan.operation in ("count", "row_count") and plan.target_column.lower() in (
                    "count", "row_count", "rows", "records", "total_rows"
                ):
                    plan.target_column = None
                elif plan.operation in ("top_n", "bottom_n", "sort_rows") and plan.target_column.lower() in (
                    "count", "row_count", "rows", "frequency", "size", "rate", "percentage",
                    "proportion", "ratio", "difference", "absolute_difference", "abs_diff",
                    "absolute_difference_mean", "diff", "mean", "average", "median", "sum", "total", "std"
                ):
                    pass  # Valid derived ranking metric
                else:
                    return PlanValidationResult(
                        valid=False,
                        error_code="COLUMN_NOT_FOUND",
                        error_message=(
                            f"Column '{plan.target_column}' not found in dataset. "
                            f"Available: {columns[:15]}"
                        ),
                    )

        for col in list(plan.columns):
            resolved = self._resolve_column(col, col_lower)
            if resolved is None:
                return PlanValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{col}' not found in dataset.",
                )

        # ── 5. Numeric / Orderable type compatibility ────────────────────────
        # For group_* operations, target_column is the GROUP KEY (categorical), not the
        # value being aggregated. Skip the numeric check — executor validates internally.
        _GROUP_OPS = frozenset({
            "group_by", "group_mean", "group_sum", "group_count", "group_count_filtered", "group_min", "group_max", "group_median",
            "crosstab", "grouped_rate", "two_factor_aggregation", "grouped_binary_comparison", "grouped_multi_stat", "binned_target_rate",
            "zero_vs_positive_comparison",
            "binary_indicator_comparison",
            "filtered_group_ranking",
            "median_split_comparison",
            "tail_risk_group_rate",
            "date_month_audit",
            "group_metric_difference", "overall_event_rate", "derived_group_comparison",
        })
        if plan.target_column and plan.operation not in _GROUP_OPS and not isinstance(plan.target_column, (list, tuple)):
            dtype = column_types.get(plan.target_column, "")
            if plan.operation in NUMERIC_OPERATIONS:
                if dtype and not self._is_numeric(dtype):
                    logger.warning(
                        "[PlanValidator] TYPE_INCOMPATIBLE: op=%s col=%s canonical_type=%s",
                        plan.operation, plan.target_column, dtype,
                    )
                    return PlanValidationResult(
                        valid=False,
                        error_code="TYPE_INCOMPATIBLE",
                        error_message=(
                            f"Operation '{plan.operation}' requires a numeric column, "
                            f"but '{plan.target_column}' has type '{dtype}'."
                        ),
                    )
            elif plan.operation in ORDERABLE_OPERATIONS:
                if dtype and not self._is_orderable(dtype):
                    logger.warning(
                        "[PlanValidator] TYPE_INCOMPATIBLE: op=%s col=%s canonical_type=%s",
                        plan.operation, plan.target_column, dtype,
                    )
                    return PlanValidationResult(
                        valid=False,
                        error_code="TYPE_INCOMPATIBLE",
                        error_message=(
                            f"Operation '{plan.operation}' requires an orderable column, "
                            f"but '{plan.target_column}' has type '{dtype}'."
                        ),
                    )

            # Log successful validation for observability
            logger.info(
                "[PlanValidator] VALID: op=%s col=%s canonical_type=%s",
                plan.operation, plan.target_column, dtype,
            )

        return PlanValidationResult(valid=True)


    # ─────────────────────────── helpers ──────────────────────────────────────

    @staticmethod
    def _resolve_column(col: str, col_lower: dict) -> Optional[str]:
        """
        Case-insensitive column lookup with stripped-punctuation fallback.
        Returns the exact column name from the dataset, or None if not found.
        """
        res = col_lower.get(col.lower())
        if res:
            return res
        # Stripped punctuation fallback (e.g. orderyear -> Order_Year, departuredelay -> Departure_Delay)
        col_clean = col.lower().replace("_", "").replace(" ", "")
        col_stripped = {c.replace("_", "").replace(" ", ""): orig for c, orig in col_lower.items()}
        return col_stripped.get(col_clean)

    @staticmethod
    def _is_numeric(dtype: str) -> bool:
        """
        Check if a type string represents a numeric column.

        Accepts:
          - Canonical types:  "integer", "float", "numeric"
          - Raw pandas types: "int64", "float32", "int8", etc. (fallback)
          - "unknown" → False (NOT assumed numeric)
        """
        dt = dtype.lower().strip()

        # Canonical check (primary — PlannerContext always provides canonical types)
        if dt in _NUMERIC_CANONICAL:
            return True

        # Unknown → non-numeric (do not guess)
        if dt == "unknown":
            return False

        # Raw pandas dtype fallback (e.g. if context bypassed canonical normalization)
        return any(hint in dt for hint in _NUMERIC_DTYPE_HINTS)

    @staticmethod
    def _is_orderable(dtype: str) -> bool:
        """
        Check if a type string represents an orderable column (numbers, dates, strings).
        """
        dt = dtype.lower().strip()
        if dt in _ORDERABLE_CANONICAL:
            return True
        if dt == "unknown":
            return True
        return any(hint in dt for hint in _ORDERABLE_DTYPE_HINTS)


plan_validator = PlanValidator()

