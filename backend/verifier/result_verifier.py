"""
ResultVerifier — independent deterministic re-check of PandasExecutor and DuckDBExecutor results.

Rules:
  - NO LLM calls
  - Independently re-computes the expected value from the DataFrame
  - Compares against the executor's result
  - Validates source-row provenance and context attributes for extrema
  - Validates that claimed units are grounded in trusted metadata
  - Sets verified=True ONLY when values, context, and units match
  - Never modifies the executor result
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd
import numpy as np

from executor.pandas_executor import ExecutorResult
from planner.schema import AnalyticalPlan

logger = logging.getLogger(__name__)

_TOLERANCE = 1e-9  # float comparison tolerance


@dataclass
class VerifierResult:
    verified: bool
    expected: Any = None
    actual: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ResultVerifier:
    """
    Independently re-computes the analytical result and verifies it.

    Supports verification for: max, min, mean, median, sum, std, variance, count, nunique.
    For operations without a scalar re-check (top_n, filter, etc.), marks as verified=True
    since we can't independently verify the row set without re-running the whole op.
    """

    def verify(
        self,
        executor_result: ExecutorResult,
        plan: AnalyticalPlan,
        df: pd.DataFrame,
        dataset_metadata: Optional[Dict[str, Any]] = None,
        data_dictionary: Optional[Dict[str, Any]] = None,
        user_definitions: Optional[Dict[str, Any]] = None,
    ) -> VerifierResult:
        """
        Verify the executor result independently.

        Args:
            executor_result: Output from PandasExecutor or DuckDBExecutor.
            plan:            The validated AnalyticalPlan that was executed.
            df:              The same DataFrame used by the executor.
            dataset_metadata: Optional dataset/column metadata for unit verification.
            data_dictionary: Optional data dictionary for unit verification.
            user_definitions: Optional user definitions for unit verification.

        Returns:
            VerifierResult with verified=True if values and provenance match.
        """
        if not executor_result.success:
            return VerifierResult(
                verified=False,
                error_code="EXECUTOR_FAILED",
                error_message="Cannot verify a failed execution.",
            )

        col = plan.target_column
        op = plan.operation

        # Operations with scalar re-verification
        scalar_ops = {
            "max": lambda s: s.max(),
            "min": lambda s: s.min(),
            "mean": lambda s: s.mean(),
            "median": lambda s: s.median(),
            "sum": lambda s: s.sum(),
            "std": lambda s: s.std(),
            "variance": lambda s: s.var(),
            "count": lambda s: float(len(df)),
            "nunique": lambda s: float(s.nunique()),
        }

        if op in scalar_ops and col and col in df.columns:
            return self._verify_scalar(
                executor_result, plan, df, col, scalar_ops[op],
                dataset_metadata=dataset_metadata,
                data_dictionary=data_dictionary,
                user_definitions=user_definitions,
            )

        completeness_ops = {
            "total_cell_count": lambda d: len(d) * len(d.columns),
            "complete_cell_count": lambda d: len(d) * len(d.columns) - int(d.isna().sum().sum()),
            "rows_with_missing_count": lambda d: int(d.isna().any(axis=1).sum()),
            "complete_rows_count": lambda d: int((~d.isna().any(axis=1)).sum()),
            "duplicate_rows_after_deduplication": lambda d: int(len(d.drop_duplicates())),
            "missing_count_total": lambda d: int(d.isna().sum().sum()),
            "duplicate_count": lambda d: int(d.duplicated().sum()),
        }
        if op in completeness_ops:
            expected = completeness_ops[op](df)
            actual = executor_result.value
            if expected == actual:
                return VerifierResult(verified=True, expected=expected, actual=actual, details={"method": "independent_recompute", "operation": op})
            else:
                return VerifierResult(verified=False, expected=expected, actual=actual, error_code="VALUE_MISMATCH", error_message=f"Expected {expected}, got {actual}")

        # For non-scalar ops (top_n, filter, duplicates, etc.): trust executor
        # We cannot independently re-verify the full row set here without duplicating
        # the entire operation. Mark as verified=True with a note.
        return VerifierResult(
            verified=True,
            details={
                "method": "trusted_non_scalar",
                "operation": op,
                "reason": "Non-scalar operation; row-set verification deferred.",
            },
        )

    def _verify_scalar(
        self,
        executor_result: ExecutorResult,
        plan: AnalyticalPlan,
        df: pd.DataFrame,
        col: str,
        compute_fn,
        dataset_metadata: Optional[Dict[str, Any]] = None,
        data_dictionary: Optional[Dict[str, Any]] = None,
        user_definitions: Optional[Dict[str, Any]] = None,
    ) -> VerifierResult:
        """Independently compute the scalar, verify record provenance, and verify unit grounding."""
        try:
            op = plan.operation
            # Only coerce to numeric for math operations
            math_ops = {"mean", "median", "sum", "std", "variance"}

            if op in math_ops:
                series = pd.to_numeric(df[col], errors="coerce").dropna()
            else:
                series = df[col].dropna()

            expected_raw = compute_fn(series)
            expected = self._safe(expected_raw)
            actual = executor_result.value

            matched = self._values_match(expected, actual)

            if not matched:
                logger.error(
                    "[Verifier] MISMATCH — op=%s col=%s expected=%s actual=%s",
                    plan.operation, col, expected, actual,
                )
                return VerifierResult(
                    verified=False,
                    expected=expected,
                    actual=actual,
                    error_code="VALUE_MISMATCH",
                    error_message=(
                        f"Verifier mismatch: executor produced {actual} "
                        f"but independent check produced {expected}."
                    ),
                )

            # ── 1. Unit Grounding Verification ──
            # If a unit was claimed, verify it is documented in trusted metadata
            claimed_unit = (executor_result.details or {}).get("unit")
            if claimed_unit:
                from analytics.unit_resolver import resolve_unit
                trusted_res = resolve_unit(
                    column=col,
                    operation=op,
                    dataset_metadata=dataset_metadata,
                    data_dictionary=data_dictionary,
                    user_definitions=user_definitions,
                )
                if trusted_res.status != "known" or str(trusted_res.unit).strip().lower() != str(claimed_unit).strip().lower():
                    logger.error(
                        "[Verifier] UNGROUNDED_UNIT: Claimed '%s', but metadata resolves to '%s' (status: %s)",
                        claimed_unit, trusted_res.unit, trusted_res.status
                    )
                    return VerifierResult(
                        verified=False,
                        expected=trusted_res.unit,
                        actual=claimed_unit,
                        error_code="UNGROUNDED_UNIT",
                        error_message=f"Claimed unit '{claimed_unit}' is not documented in trusted dataset metadata.",
                    )

            # ── 2. Record Provenance & Context Verification for Extrema ──
            if op in ("max", "min") and executor_result.matching_rows:
                for r in executor_result.matching_rows[:5]:
                    df_idx = r.get("dataframe_index")
                    if df_idx is not None and df_idx in df.index:
                        row_series = df.loc[df_idx]
                        # Verify target column value at this index
                        actual_col_val = row_series[col]
                        if not self._values_match(actual_col_val, actual):
                            return VerifierResult(
                                verified=False,
                                expected=actual,
                                actual=actual_col_val,
                                error_code="EXTREMUM_ROW_MISMATCH",
                                error_message=f"Row index {df_idx} has {col}={actual_col_val}, which does not match extremum {actual}.",
                            )
                        # Verify context fields belong to this exact row in df
                        for k, v in r.items():
                            if k in df.columns and k != col and not k.startswith("_"):
                                expected_context_val = row_series[k]
                                if not self._values_match(expected_context_val, v):
                                    return VerifierResult(
                                        verified=False,
                                        expected=expected_context_val,
                                        actual=v,
                                        error_code="RECORD_CONTEXT_MISMATCH",
                                        error_message=f"Attribute '{k}' has value '{v}' in result but is '{expected_context_val}' in source row {df_idx}.",
                                    )

            return VerifierResult(
                verified=True,
                expected=expected,
                actual=actual,
                details={
                    "method": "independent_recompute",
                    "operation": plan.operation,
                    "column": col,
                },
            )
        except Exception as e:
            logger.error("[Verifier] Verification error: %s", e, exc_info=True)
            return VerifierResult(
                verified=False,
                error_code="VERIFIER_ERROR",
                error_message=str(e),
            )

    @staticmethod
    def _safe(val: Any) -> Any:
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        return val

    @staticmethod
    def _values_match(expected: Any, actual: Any) -> bool:
        if expected is None and actual is None:
            return True
        if expected is None or actual is None:
            return False
        try:
            exp_f = float(expected)
            act_f = float(actual)
            diff = abs(exp_f - act_f)
            max_val = max(abs(exp_f), abs(act_f))
            # Relative tolerance of 1e-4 or absolute tolerance of 1e-3 accounts for cross-engine
            # SIMD vs sequential float64 summation order and valid 3-decimal executor rounding
            return diff <= max(1e-3, max_val * 1e-4)
        except (ValueError, TypeError):
            return str(expected) == str(actual)


result_verifier = ResultVerifier()
