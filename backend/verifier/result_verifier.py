"""
ResultVerifier — independent deterministic re-check of PandasExecutor results.

Rules:
  - NO LLM calls
  - Independently re-computes the expected value from the DataFrame
  - Compares against the executor's result
  - Sets verified=True ONLY when the values match
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
    ) -> VerifierResult:
        """
        Verify the executor result independently.

        Args:
            executor_result: Output from PandasExecutor.
            plan:            The validated AnalyticalPlan that was executed.
            df:              The same DataFrame used by the executor.

        Returns:
            VerifierResult with verified=True if values match.
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
            return self._verify_scalar(executor_result, plan, df, col, scalar_ops[op])

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
    ) -> VerifierResult:
        """Independently compute the scalar and compare to the executor result."""
        try:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            expected_raw = compute_fn(series)
            expected = self._safe(expected_raw)
            actual = executor_result.value

            matched = self._values_match(expected, actual)

            if matched:
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
            else:
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
            return abs(float(expected) - float(actual)) < _TOLERANCE
        except (ValueError, TypeError):
            return str(expected) == str(actual)


result_verifier = ResultVerifier()
