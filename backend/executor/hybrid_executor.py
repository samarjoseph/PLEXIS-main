"""
HybridExecutor — capability-based adaptive execution engine selector for Plexis.

Rules:
  - Dynamically routes validated AnalyticalPlan nodes to DuckDB when supported and advantageous.
  - Automatically retains / falls back to PandasExecutor for unsupported operations or errors.
  - Guarantees zero regression: both engines adhere to the identical ExecutorResult contract.
  - Tracks execution statistics (DuckDB executions, Pandas executions, fallbacks, timings).
  - Can be rolled back or disabled instantly via Config.ENABLE_DUCKDB_ENGINE or runtime flag.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import pandas as pd

from config import Config
from executor.duckdb_executor import duckdb_executor, DuckDBExecutor
from executor.pandas_executor import pandas_executor, PandasExecutor, ExecutorResult
from planner.schema import AnalyticalPlan

logger = logging.getLogger(__name__)


class HybridExecutor:
    """
    Orchestrates execution between DuckDB and Pandas.
    """

    def __init__(self):
        self.pandas_executor: PandasExecutor = pandas_executor
        self.duckdb_executor: DuckDBExecutor = duckdb_executor
        self._duckdb_enabled_override: Optional[bool] = None

        # Telemetry & routing statistics
        self._stats = {
            "duckdb_executions": 0,
            "pandas_executions": 0,
            "fallback_count": 0,
            "duckdb_errors": 0,
            "last_engine_used": None,
        }

    @property
    def is_duckdb_enabled(self) -> bool:
        """Check whether DuckDB execution is enabled."""
        if self._duckdb_enabled_override is not None:
            return self._duckdb_enabled_override
        return getattr(Config, "ENABLE_DUCKDB_ENGINE", True)

    def set_duckdb_enabled(self, enabled: bool) -> None:
        """Runtime toggle for DuckDB engine (permits instant zero-downtime rollback)."""
        self._duckdb_enabled_override = enabled
        logger.info("[HybridExecutor] DuckDB engine enabled state set to: %s", enabled)

    def reset_duckdb_override(self) -> None:
        """Reset runtime toggle to follow Config.ENABLE_DUCKDB_ENGINE."""
        self._duckdb_enabled_override = None

    def get_stats(self) -> Dict[str, Any]:
        """Return cumulative engine routing statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset engine routing statistics."""
        self._stats = {
            "duckdb_executions": 0,
            "pandas_executions": 0,
            "fallback_count": 0,
            "duckdb_errors": 0,
            "last_engine_used": None,
        }

    def execute(self, plan: AnalyticalPlan, df: pd.DataFrame) -> ExecutorResult:
        """
        Execute the analytical plan using the optimal engine.

        1. Inspects plan capabilities and DuckDB compatibility.
        2. Routes to DuckDB if supported and beneficial.
        3. Falls back safely to PandasExecutor on failure or incompatibility.
        """
        op = plan.operation or ""
        col = plan.target_column or ""

        # Check if DuckDB is enabled and capable
        if self.is_duckdb_enabled and self.duckdb_executor.can_execute(plan, df):
            logger.debug("[HybridExecutor] Routing operation '%s' on column '%s' to DuckDB", op, col)
            t0 = time.perf_counter()
            try:
                res = self.duckdb_executor.execute(plan, df)
                if res.success:
                    self._stats["duckdb_executions"] += 1
                    self._stats["last_engine_used"] = "duckdb"
                    logger.info(
                        "[HybridExecutor] Executed '%s' via DuckDB in %.2fms",
                        op, (time.perf_counter() - t0) * 1000.0
                    )
                    return res

                # DuckDB returned success=False — fall back to Pandas
                logger.warning(
                    "[HybridExecutor] DuckDB execution failed: %s. Falling back to PandasExecutor for '%s'.",
                    res.error, op
                )
                self._stats["duckdb_errors"] += 1
                self._stats["fallback_count"] += 1

            except Exception as e:
                logger.warning(
                    "[HybridExecutor] DuckDB exception (%s). Falling back to PandasExecutor for '%s'.",
                    e, op, exc_info=True
                )
                self._stats["duckdb_errors"] += 1
                self._stats["fallback_count"] += 1

        # Fallback / standard Pandas execution path
        logger.debug("[HybridExecutor] Executing operation '%s' via PandasExecutor", op)
        t0 = time.perf_counter()
        res = self.pandas_executor.execute(plan, df)
        self._stats["pandas_executions"] += 1
        self._stats["last_engine_used"] = "pandas"

        if res.success:
            if not res.details:
                res.details = {}
            if "engine" not in res.details:
                res.details["engine"] = "pandas"
            res.details["execution_time_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)

        return res


hybrid_executor = HybridExecutor()
