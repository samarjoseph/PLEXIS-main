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

from planner.schema import AnalyticalPlan, NUMERIC_OPERATIONS, _FORBIDDEN_PATTERNS

logger = logging.getLogger(__name__)

# ── Canonical types considered numeric by the validator ───────────────────────
# These align exactly with PlannerContext's _NUMERIC_CANONICAL set.
_NUMERIC_CANONICAL = frozenset({"integer", "float", "numeric"})

# Raw pandas dtype substrings — used as a last-resort fallback if context
# provides non-canonical types (e.g., "int64", "float32").
_NUMERIC_DTYPE_HINTS = ("int", "float", "double", "decimal", "num")


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
            resolved = self._resolve_column(plan.target_column, col_lower)
            if resolved is None:
                return PlanValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=(
                        f"Column '{plan.target_column}' not found in dataset. "
                        f"Available: {columns[:15]}"
                    ),
                )
            # Normalize to exact column name in-place
            plan.target_column = resolved

        for col in list(plan.columns):
            resolved = self._resolve_column(col, col_lower)
            if resolved is None:
                return PlanValidationResult(
                    valid=False,
                    error_code="COLUMN_NOT_FOUND",
                    error_message=f"Column '{col}' not found in dataset.",
                )

        # ── 5. Numeric type compatibility ─────────────────────────────────────
        if plan.target_column and plan.operation in NUMERIC_OPERATIONS:
            dtype = column_types.get(plan.target_column, "")
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
        Case-insensitive column lookup.
        Returns the exact column name from the dataset, or None if not found.
        Does NOT do partial matching — only exact case-insensitive.
        """
        return col_lower.get(col.lower())

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


plan_validator = PlanValidator()
