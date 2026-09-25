"""
PandasExecutor — the ONLY analytical execution engine in Plexis.

Rules:
  - NO LLM calls of any kind
  - Receives a validated AnalyticalPlan
  - Executes against a real pandas DataFrame
  - Returns ExecutorResult with value + row_indices + matching_rows
  - All operations are on an allowlist
  - Arbitrary code strings are NEVER executed

Both /api/ask (chat) and /api/spreadsheet/operate (spreadsheet) converge here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from planner.schema import AnalyticalPlan

logger = logging.getLogger(__name__)


@dataclass
class ExecutorResult:
    """
    The structured output of PandasExecutor.

    value:          Scalar result (int, float, str) or list for multi-row ops.
    row_indices:    DataFrame integer indices of matching rows.
    matching_rows:  Preview rows as dicts (up to 10).
    operation:      Canonical operation name (from plan).
    column:         Target column name.
    success:        False if the executor failed.
    error:          Error message if success=False.
    """
    value: Any = None
    row_indices: List[int] = field(default_factory=list)
    matching_rows: List[Dict[str, Any]] = field(default_factory=list)
    operation: str = ""
    column: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class PandasExecutor:
    """
    Canonical Pandas executor for all analytical operations.

    Maps AnalyticalPlan → safe pandas operations → ExecutorResult.
    No LLM. No arbitrary code. No exec/eval.
    """

    def execute(self, plan: AnalyticalPlan, df: pd.DataFrame) -> ExecutorResult:
        """
        Execute the validated plan against the DataFrame.

        Args:
            plan: Validated AnalyticalPlan (MUST be validated before calling).
            df:   Real DataFrame from the dataset registry.

        Returns:
            ExecutorResult with value, row_indices, matching_rows.
        """
        if df is None or df.empty:
            return ExecutorResult(
                success=False,
                error="DataFrame is empty or not loaded.",
            )

        col = plan.target_column
        op = plan.operation
        params = plan.parameters or {}

        try:
            # Resolve column (case-insensitive fallback)
            if col:
                col = self._resolve_column(col, df)
                if col is None:
                    return ExecutorResult(
                        success=False,
                        error=f"Column '{plan.target_column}' not found in DataFrame.",
                    )

            # Dispatch to operation handler
            return self._dispatch(op, col, df, params, plan)

        except Exception as e:
            logger.error("[PandasExecutor] execute() error: %s", e, exc_info=True)
            return ExecutorResult(success=False, error=str(e))

    # -------------------------------------------------------------------------
    # Dispatch
    # -------------------------------------------------------------------------

    def _dispatch(
        self,
        op: str,
        col: Optional[str],
        df: pd.DataFrame,
        params: dict,
        plan: AnalyticalPlan,
    ) -> ExecutorResult:
        # ── Aggregates ────────────────────────────────────────────────────────
        if op == "max":
            return self._aggregate(df, col, "max")
        if op == "min":
            return self._aggregate(df, col, "min")
        if op == "mean":
            return self._scalar(df, col, "mean")
        if op == "median":
            return self._scalar(df, col, "median")
        if op == "sum":
            return self._scalar(df, col, "sum")
        if op == "std":
            return self._scalar(df, col, "std")
        if op == "variance":
            return self._scalar(df, col, "var")
        if op == "range":
            return self._range(df, col)
        if op == "count":
            return self._count(df, col, params)
        if op == "nunique":
            return self._nunique(df, col)
        if op == "mode":
            return self._mode(df, col)

        # ── Ranking ───────────────────────────────────────────────────────────
        if op == "top_n":
            return self._top_n(df, col, params, ascending=False)
        if op == "bottom_n":
            return self._top_n(df, col, params, ascending=True)

        # ── Quality ───────────────────────────────────────────────────────────
        if op == "missing_values":
            return self._missing_values(df, col)
        if op == "duplicates":
            return self._duplicates(df, plan.columns or ([col] if col else []))
        if op == "unique_values":
            return self._unique_values(df, col)
        if op == "outliers":
            return self._outliers(df, col)

        # ── Filtering ─────────────────────────────────────────────────────────
        if op == "filter":
            return self._filter(df, col, params)

        # ── Sorting ───────────────────────────────────────────────────────────
        if op == "sort":
            return self._sort(df, col, params)

        # ── Grouping ──────────────────────────────────────────────────────────
        if op in ("group_by", "group_mean", "group_sum", "group_count",
                   "group_min", "group_max"):
            return self._group_by(df, col, op, params, plan.columns)

        # ── Distribution ──────────────────────────────────────────────────────
        if op == "frequency":
            return self._frequency(df, col, params)
        if op == "quantile":
            return self._quantile(df, col, params)

        # ── Relationships ─────────────────────────────────────────────────────
        if op == "correlation":
            return self._correlation(df, col, plan.columns, params)
        if op == "covariance":
            return self._covariance(df, col, plan.columns, params)

        # ── Row retrieval ─────────────────────────────────────────────────────
        if op in ("locate_row", "locate_rows"):
            return self._locate_rows(df, col, params)

        return ExecutorResult(
            success=False,
            error=f"Operation '{op}' not implemented in PandasExecutor.",
        )

    # -------------------------------------------------------------------------
    # Aggregate with row matching
    # -------------------------------------------------------------------------

    def _aggregate(self, df: pd.DataFrame, col: str, func: str) -> ExecutorResult:
        """Compute max/min and return matching rows."""
        series = pd.to_numeric(df[col], errors="coerce")
        if func == "max":
            value = series.max()
            matching_df = df[series == value]
        else:  # min
            value = series.min()
            matching_df = df[series == value]

        value = self._safe(value)
        indices = matching_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in matching_df.head(10).iterrows()]

        return ExecutorResult(
            value=value,
            row_indices=indices,
            matching_rows=rows,
            operation=func,
            column=col,
        )

    def _scalar(self, df: pd.DataFrame, col: str, func: str) -> ExecutorResult:
        """Return a scalar aggregate (mean, median, sum, std, var)."""
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        fn = getattr(series, func)
        value = self._safe(fn())
        return ExecutorResult(value=value, operation=func, column=col)

    def _range(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        value = self._safe(series.max() - series.min())
        return ExecutorResult(value=value, operation="range", column=col)

    def _count(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        value = int(len(df)) if not col else int(df[col].count())
        return ExecutorResult(value=value, operation="count", column=col)

    def _nunique(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        value = int(df[col].nunique())
        return ExecutorResult(value=value, operation="nunique", column=col)

    def _mode(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        modes = df[col].mode().tolist()
        value = modes[0] if modes else None
        value = self._safe(value)
        return ExecutorResult(value=value, operation="mode", column=col)

    # -------------------------------------------------------------------------
    # Ranking
    # -------------------------------------------------------------------------

    def _top_n(self, df: pd.DataFrame, col: str, params: dict, ascending: bool) -> ExecutorResult:
        n = int(params.get("n") or 10)
        n = min(n, 1000)
        ranked = df.nsmallest(n, col) if ascending else df.nlargest(n, col)
        indices = ranked.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in ranked.iterrows()]
        op = "bottom_n" if ascending else "top_n"
        return ExecutorResult(
            value=[self._safe(v) for v in ranked[col].tolist()],
            row_indices=indices,
            matching_rows=rows,
            operation=op,
            column=col,
        )

    # -------------------------------------------------------------------------
    # Quality
    # -------------------------------------------------------------------------

    def _missing_values(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if col:
            count = int(df[col].isna().sum())
            return ExecutorResult(value=count, operation="missing_values", column=col)
        result = df.isna().sum().to_dict()
        result = {k: int(v) for k, v in result.items()}
        return ExecutorResult(value=result, operation="missing_values")

    def _duplicates(self, df: pd.DataFrame, cols: List[str]) -> ExecutorResult:
        subset = [c for c in cols if c in df.columns] or None
        dup_df = df[df.duplicated(subset=subset, keep=False)]
        indices = dup_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in dup_df.head(10).iterrows()]
        return ExecutorResult(
            value=len(indices),
            row_indices=indices,
            matching_rows=rows,
            operation="duplicates",
        )

    def _unique_values(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        values = df[col].dropna().unique().tolist()
        values = [self._safe(v) for v in values]
        return ExecutorResult(value=values, operation="unique_values", column=col)

    def _outliers(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        mask = (df[col].apply(pd.to_numeric, errors="coerce") < lower) | \
               (df[col].apply(pd.to_numeric, errors="coerce") > upper)
        outlier_df = df[mask]
        indices = outlier_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in outlier_df.head(10).iterrows()]
        return ExecutorResult(
            value=len(indices),
            row_indices=indices,
            matching_rows=rows,
            operation="outliers",
            column=col,
        )

    # -------------------------------------------------------------------------
    # Filtering / Sorting
    # -------------------------------------------------------------------------

    def _filter(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        operator = params.get("operator", "==")
        value = params.get("value")
        if value is None:
            return ExecutorResult(success=False, error="FILTER requires 'value' parameter.")

        numeric = pd.to_numeric(df[col], errors="coerce")
        try:
            num_value = float(value)
        except (ValueError, TypeError):
            num_value = None

        if num_value is not None and not numeric.isna().all():
            col_series = numeric
            cmp_value = num_value
        else:
            col_series = df[col].astype(str)
            cmp_value = str(value)

        _ops = {
            "==": col_series == cmp_value,
            "!=": col_series != cmp_value,
            ">":  col_series > cmp_value,
            "<":  col_series < cmp_value,
            ">=": col_series >= cmp_value,
            "<=": col_series <= cmp_value,
            "contains": df[col].astype(str).str.contains(str(value), na=False),
            "startswith": df[col].astype(str).str.startswith(str(value), na=False),
            "endswith": df[col].astype(str).str.endswith(str(value), na=False),
        }
        mask = _ops.get(operator, col_series == cmp_value)
        result_df = df[mask]
        indices = result_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in result_df.head(10).iterrows()]
        return ExecutorResult(
            value=len(indices),
            row_indices=indices,
            matching_rows=rows,
            operation="filter",
            column=col,
        )

    def _sort(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        ascending = str(params.get("order", "asc")).lower() in ("asc", "ascending")
        sorted_df = df.sort_values(by=col, ascending=ascending)
        indices = sorted_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in sorted_df.head(10).iterrows()]
        return ExecutorResult(
            value=len(indices),
            row_indices=indices,
            matching_rows=rows,
            operation="sort",
            column=col,
        )

    # -------------------------------------------------------------------------
    # Grouping
    # -------------------------------------------------------------------------

    def _group_by(self, df: pd.DataFrame, col: Optional[str], op: str,
                  params: dict, extra_cols: list) -> ExecutorResult:
        group_col = params.get("group_by") or (extra_cols[0] if extra_cols else col)
        if not group_col or group_col not in df.columns:
            return ExecutorResult(success=False, error=f"group_by column '{group_col}' not found.")

        agg_col = col
        func_map = {
            "group_mean": "mean", "group_sum": "sum",
            "group_count": "count", "group_min": "min", "group_max": "max",
        }
        func = func_map.get(op, "count")

        if agg_col and agg_col in df.columns and func != "count":
            result_series = getattr(df.groupby(group_col)[agg_col], func)()
        else:
            result_series = df.groupby(group_col).size()

        result_dict = {str(k): self._safe(v) for k, v in result_series.items()}
        return ExecutorResult(value=result_dict, operation=op, column=group_col)

    # -------------------------------------------------------------------------
    # Distribution
    # -------------------------------------------------------------------------

    def _frequency(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        n = int(params.get("top") or 20)
        counts = df[col].value_counts().head(n)
        value = {str(k): int(v) for k, v in counts.items()}
        return ExecutorResult(value=value, operation="frequency", column=col)

    def _quantile(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        q = float(params.get("q") or 0.5)
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        value = self._safe(series.quantile(q))
        return ExecutorResult(value=value, operation="quantile", column=col)

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------

    def _correlation(self, df: pd.DataFrame, col: Optional[str],
                     cols: list, params: dict) -> ExecutorResult:
        if col and cols:
            col_b = cols[0] if cols[0] != col else (cols[1] if len(cols) > 1 else None)
        elif len(cols) >= 2:
            col, col_b = cols[0], cols[1]
        else:
            return ExecutorResult(success=False, error="correlation requires two columns.")

        if col_b is None or col_b not in df.columns:
            return ExecutorResult(success=False, error=f"Second column for correlation not found.")

        a = pd.to_numeric(df[col], errors="coerce")
        b = pd.to_numeric(df[col_b], errors="coerce")
        value = self._safe(a.corr(b))
        return ExecutorResult(value=value, operation="correlation", column=col)

    def _covariance(self, df: pd.DataFrame, col: Optional[str],
                    cols: list, params: dict) -> ExecutorResult:
        if col and cols:
            col_b = cols[0]
        elif len(cols) >= 2:
            col, col_b = cols[0], cols[1]
        else:
            return ExecutorResult(success=False, error="covariance requires two columns.")

        if col_b not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col_b}' not found.")

        a = pd.to_numeric(df[col], errors="coerce")
        b = pd.to_numeric(df[col_b], errors="coerce")
        value = self._safe(a.cov(b))
        return ExecutorResult(value=value, operation="covariance", column=col)

    # -------------------------------------------------------------------------
    # Row retrieval
    # -------------------------------------------------------------------------

    def _locate_rows(self, df: pd.DataFrame, col: Optional[str],
                     params: dict) -> ExecutorResult:
        value = params.get("value")
        if col and value is not None:
            num = pd.to_numeric(df[col], errors="coerce")
            try:
                num_val = float(value)
                mask = num == num_val
            except (ValueError, TypeError):
                mask = df[col].astype(str) == str(value)
            result_df = df[mask]
        else:
            result_df = df.head(10)

        indices = result_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in result_df.head(10).iterrows()]
        return ExecutorResult(
            value=len(indices),
            row_indices=indices,
            matching_rows=rows,
            operation="locate_rows",
            column=col,
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _resolve_column(self, col: str, df: pd.DataFrame) -> Optional[str]:
        """Case-insensitive column name resolution."""
        if col in df.columns:
            return col
        for c in df.columns:
            if c.lower() == col.lower():
                return c
        return None

    def _safe(self, val: Any) -> Any:
        """Convert numpy scalars to Python native types."""
        if val is None:
            return None
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        if isinstance(val, (np.bool_,)):
            return bool(val)
        if isinstance(val, (np.ndarray,)):
            return val.tolist()
        return val

    def _row_dict(self, row, df_index: Optional[int] = None) -> Dict[str, Any]:
        """Convert a DataFrame row to a JSON-safe dict with _row_number (1-based)."""
        d = {k: self._safe(v) for k, v in row.to_dict().items()}
        # _row_number is the 1-based canonical source row identity.
        # Derived from the DataFrame integer index (which was set at ingestion and never changes).
        idx = df_index if df_index is not None else (row.name if hasattr(row, "name") else None)
        if idx is not None:
            d["_row_number"] = int(idx) + 1
        return d


# Singleton
pandas_executor = PandasExecutor()
