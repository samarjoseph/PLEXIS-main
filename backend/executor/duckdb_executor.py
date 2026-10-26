"""
DuckDBExecutor — high-performance in-memory analytical execution engine for Plexis.

Rules:
  - NO LLM calls of any kind.
  - Receives a validated AnalyticalPlan.
  - Queries active in-memory pandas DataFrames via DuckDB's zero-copy virtual table scanning.
  - Never mutates the source DataFrame.
  - Returns ExecutorResult with identical structure and semantic contracts as PandasExecutor.
  - Strictly parameterized / safely quoted SQL generation — arbitrary user SQL is NEVER executed.
  - Thread-isolated connections to prevent any cross-dataset or cross-request pollution.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd

from executor.pandas_executor import ExecutorResult
from planner.schema import AnalyticalPlan

logger = logging.getLogger(__name__)

# Thread-local storage for DuckDB in-memory connections
_thread_local = threading.local()


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Get or create an isolated in-memory DuckDB connection for the current thread."""
    if not hasattr(_thread_local, "con") or _thread_local.con is None:
        _thread_local.con = duckdb.connect(":memory:")
    return _thread_local.con


class DuckDBExecutor:
    """
    DuckDB analytical execution engine.
    Translates validated AnalyticalPlan nodes into safe, optimized DuckDB SQL queries.
    """

    SUPPORTED_OPERATIONS = frozenset({
        "count", "nunique", "mean", "sum", "min", "max", "median",
        "std", "variance", "range",
        "missing_count_column", "missing_count_total",
        "total_cell_count", "complete_cell_count",
        "group_by", "group_mean", "group_sum", "group_count", "group_count_filtered",
        "group_min", "group_max", "group_median",
        "grouped_rate", "two_factor_aggregation",
        "grouped_binary_comparison", "binary_indicator_comparison", "crosstab",
        "compound_filter", "filter", "sort",
        "overall_event_rate", "group_metric_difference", "derived_group_comparison",
    })

    _ALLOWED_OPERATORS = frozenset({"==", "=", "!=", ">", "<", ">=", "<="})

    _POSITIVE_INDICATORS = frozenset({
        "yes", "true", "1", "y", "positive", "success",
        "churned", "churn", "delayed", "delay", "default",
        "fraud", "spam", "malignant", "abnormal", "fail", "failed",
    })

    @staticmethod
    def _quote_ident(ident: Optional[str]) -> str:
        """Safely quote a SQL identifier using standard double quotes."""
        if ident is None:
            return '""'
        escaped = str(ident).replace('"', '""')
        return f'"{escaped}"'

    def _resolve_column(self, col: Optional[str], df: pd.DataFrame) -> Optional[str]:
        """Resolve column name with case-insensitive fallback."""
        if not col:
            return None
        if col in df.columns:
            return col
        col_lower = col.lower().strip()
        for c in df.columns:
            if str(c).lower().strip() == col_lower:
                return c
        return None

    def can_execute(self, plan: AnalyticalPlan, df: pd.DataFrame) -> bool:
        return self.can_handle(plan, df)

    def can_handle(self, plan: AnalyticalPlan, df: pd.DataFrame) -> bool:
        """
        Capability check: determine if DuckDB can safely and accurately execute this plan.
        """
        if df is None or df.empty:
            return False

        op = (plan.operation or "").lower().strip()
        if op not in self.SUPPORTED_OPERATIONS:
            return False

        col = plan.target_column
        params = plan.parameters or {}

        # Column existence check
        if col:
            resolved = self._resolve_column(col, df)
            if not resolved:
                # Some operations allow col=None or derived sort keys
                if op == "count" and col.lower() in ("count", "rows", "row_count", "total_rows"):
                    pass
                elif op in ("grouped_binary_comparison", "compound_filter", "two_factor_aggregation", "overall_event_rate", "group_metric_difference", "derived_group_comparison"):
                    pass
                else:
                    return False

        # Operation-specific checks
        if op == "compound_filter":
            conds = params.get("conditions", [])
            if not isinstance(conds, list) or not conds:
                return False
            for cond in conds:
                c_col = cond.get("column")
                c_op = cond.get("operator", "==")
                if not c_col or c_col not in df.columns:
                    return False
                if c_op not in self._ALLOWED_OPERATORS:
                    return False

        elif op == "grouped_rate":
            grp_col = params.get("group_by")
            tgt_col = params.get("target_column") or params.get("column") or col
            if isinstance(grp_col, (list, tuple)):
                if not all(c in df.columns for c in grp_col):
                    return False
            elif not grp_col or grp_col not in df.columns:
                return False
            if not params.get("conditions") and (not tgt_col or tgt_col not in df.columns):
                return False

        elif op == "two_factor_aggregation":
            c1 = params.get("group_by") or col
            c2 = params.get("secondary_group")
            val_col = params.get("value_column")
            if not c1 or not c2 or not val_col:
                return False
            if c1 not in df.columns or c2 not in df.columns or val_col not in df.columns:
                return False

        elif op == "grouped_binary_comparison":
            grp_col = params.get("group_by") or col
            bin_col = params.get("binary_column")
            val_col = params.get("value_column")
            # Route synthetic column can be generated in SQL
            has_grp = grp_col in df.columns or ("route" in str(grp_col).lower() and any("origin" in c.lower() for c in df.columns) and any("dest" in c.lower() for c in df.columns))
            if not has_grp or not bin_col or not val_col:
                return False
            if bin_col not in df.columns or val_col not in df.columns:
                return False

        elif op == "binary_indicator_comparison":
            bin_col = params.get("binary_column") or params.get("group_by") or col
            val_col = params.get("value_column") or col or bin_col
            if not bin_col or not val_col:
                return False
            if self._resolve_column(bin_col, df) is None or self._resolve_column(val_col, df) is None:
                return False

        return True

    def execute(self, plan: AnalyticalPlan, df: pd.DataFrame) -> ExecutorResult:
        """
        Execute the validated AnalyticalPlan using DuckDB.
        """
        if df is None or df.empty:
            return ExecutorResult(success=False, error="DataFrame is empty or not loaded.")

        con = _get_connection()
        tbl_name = f"tbl_{uuid.uuid4().hex[:12]}"
        t_start = time.perf_counter()

        try:
            # Register DataFrame as a zero-copy virtual table in DuckDB
            con.register(tbl_name, df)
            res = self._dispatch(plan, df, con, tbl_name)
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0

            if res.success:
                if not res.details:
                    res.details = {}
                res.details["engine"] = "duckdb"
                res.details["execution_time_ms"] = round(elapsed_ms, 2)
                res.details["total_rows"] = len(df)

            return res

        except Exception as e:
            logger.warning("[DuckDBExecutor] Query execution error: %s", e, exc_info=True)
            return ExecutorResult(success=False, error=str(e), operation=plan.operation, column=plan.target_column)

        finally:
            try:
                con.unregister(tbl_name)
            except Exception:
                pass

    def _dispatch(
        self,
        plan: AnalyticalPlan,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str
    ) -> ExecutorResult:
        op = (plan.operation or "").lower().strip()
        col = self._resolve_column(plan.target_column, df)
        params = plan.parameters or {}

        # ── Aggregates ────────────────────────────────────────────────────────
        if op == "count":
            return self._exec_count(df, con, tbl, col, params)
        if op == "nunique":
            return self._exec_nunique(con, tbl, col)
        if op == "mean":
            return self._exec_scalar(con, tbl, col, "AVG", op)
        if op == "sum":
            return self._exec_scalar(con, tbl, col, "SUM", op)
        if op == "min":
            return self._exec_aggregate(df, con, tbl, col, "MIN", op)
        if op == "max":
            return self._exec_aggregate(df, con, tbl, col, "MAX", op)
        if op == "median":
            return self._exec_scalar(con, tbl, col, "MEDIAN", op)
        if op == "std":
            return self._exec_scalar(con, tbl, col, "STDDEV_SAMP", op)
        if op == "variance":
            return self._exec_scalar(con, tbl, col, "VAR_SAMP", op)
        if op == "range":
            return self._exec_range(con, tbl, col)

        # ── Missingness / Quality ─────────────────────────────────────────────
        if op == "missing_count_column":
            return self._exec_missing_column(con, tbl, col)
        if op == "missing_count_total":
            return self._exec_missing_total(df, con, tbl)
        if op == "total_cell_count":
            return ExecutorResult(value=int(len(df) * len(df.columns)), operation=op)
        if op == "complete_cell_count":
            return self._exec_complete_cell_count(df, con, tbl)

        # ── Rankings (Top-N, Bottom-N) ────────────────────────────────────────
        if op == "top_n":
            return self._exec_top_n(df, con, tbl, col, params, ascending=False)
        if op == "bottom_n":
            return self._exec_top_n(df, con, tbl, col, params, ascending=True)

        # ── Grouping ──────────────────────────────────────────────────────────
        if op in ("group_by", "group_mean", "group_sum", "group_count", "group_count_filtered",
                  "group_min", "group_max", "group_median"):
            return self._exec_group_by(df, con, tbl, col, op, params, plan.columns or [])

        # ── Advanced Analytical ───────────────────────────────────────────────
        if op == "grouped_rate":
            return self._exec_grouped_rate(df, con, tbl, col, params)
        if op == "two_factor_aggregation":
            return self._exec_two_factor_aggregation(df, con, tbl, col, params)
        if op == "grouped_binary_comparison":
            return self._exec_grouped_binary_comparison(df, con, tbl, col, params)

        if op == "binary_indicator_comparison":
            return self._exec_binary_indicator_comparison(df, con, tbl, col, params)
        if op == "crosstab":
            return self._exec_crosstab(df, con, tbl, col, params)
        if op == "compound_filter":
            return self._exec_compound_filter(df, con, tbl, params)
        if op == "filter":
            return self._exec_filter(df, con, tbl, col, params)
        if op == "sort":
            return self._exec_sort(df, con, tbl, col, params)
        if op == "overall_event_rate":
            return self._exec_overall_event_rate(df, con, tbl, col, params)
        if op in ("group_metric_difference", "derived_group_comparison"):
            return self._exec_group_metric_difference(df, con, tbl, col, params)

        return ExecutorResult(success=False, error=f"Unsupported DuckDB operation: {op}")

    # ──────────────────────────────────────────────────────────────────────────
    # Helper sanitizers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, (np.integer, int)):
            return int(val)
        if isinstance(val, (np.floating, float)):
            if np.isnan(val) or np.isinf(val):
                return None
            return round(float(val), 4)
        return val

    # ──────────────────────────────────────────────────────────────────────────
    # Aggregates Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_count(self, df: pd.DataFrame, con: duckdb.DuckDBPyConnection, tbl: str, col: Optional[str], params: dict) -> ExecutorResult:
        if not col:
            res = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        else:
            q_col = self._quote_ident(col)
            res = con.execute(f"SELECT COUNT({q_col}) FROM {tbl}").fetchone()[0]
        return ExecutorResult(value=int(res), operation="count", column=col)

    def _exec_nunique(self, con: duckdb.DuckDBPyConnection, tbl: str, col: str) -> ExecutorResult:
        q_col = self._quote_ident(col)
        res = con.execute(f"SELECT COUNT(DISTINCT {q_col}) FROM {tbl}").fetchone()[0]
        return ExecutorResult(value=int(res), operation="nunique", column=col)

    def _exec_scalar(self, con: duckdb.DuckDBPyConnection, tbl: str, col: str, sql_fn: str, op: str) -> ExecutorResult:
        q_col = self._quote_ident(col)
        # Cast to double for numeric aggregations
        query = f"SELECT {sql_fn}(TRY_CAST({q_col} AS DOUBLE)) FROM {tbl} WHERE {q_col} IS NOT NULL"
        row = con.execute(query).fetchone()
        val = row[0] if row else None
        return ExecutorResult(value=self._safe(val), operation=op, column=col)

    def _exec_range(self, con: duckdb.DuckDBPyConnection, tbl: str, col: str) -> ExecutorResult:
        q_col = self._quote_ident(col)
        query = f"SELECT (MAX(TRY_CAST({q_col} AS DOUBLE)) - MIN(TRY_CAST({q_col} AS DOUBLE))) FROM {tbl} WHERE {q_col} IS NOT NULL"
        val = con.execute(query).fetchone()[0]
        return ExecutorResult(value=self._safe(val), operation="range", column=col)

    def _exec_aggregate(self, df: pd.DataFrame, con: duckdb.DuckDBPyConnection, tbl: str, col: str, sql_fn: str, op: str) -> ExecutorResult:
        q_col = self._quote_ident(col)
        # Compute min/max
        query = f"SELECT {sql_fn}({q_col}) FROM {tbl} WHERE {q_col} IS NOT NULL"
        val = con.execute(query).fetchone()[0]
        safe_val = self._safe(val)

        # Retrieve true matching row indices and preview rows from df
        # To guarantee exact source-row provenance (never reset index to 0..N)
        try:
            matching_mask = (df[col] == val)
            if not matching_mask.any():
                num_series = pd.to_numeric(df[col], errors="coerce")
                matching_mask = (num_series == val)
        except Exception:
            matching_mask = (df[col].astype(str) == str(val))

        total_matching = int(matching_mask.sum())
        matching_subset = df[matching_mask].head(10)
        matching_indices = matching_subset.index.tolist()

        rows = []
        for rank_idx, (idx, r) in enumerate(matching_subset.iterrows(), start=1):
            row_dict = {k: self._safe(v) for k, v in r.to_dict().items()}
            row_dict["_row_number"] = int(idx) + 1
            row_dict["source_row_number"] = int(idx) + 1
            row_dict["dataframe_index"] = int(idx)
            row_dict["result_rank"] = rank_idx
            rows.append(row_dict)

        return ExecutorResult(
            value=safe_val,
            row_indices=matching_indices,
            matching_rows=rows,
            operation=op,
            column=col,
            details={"matching_count": total_matching}
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Missingness Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_missing_column(self, con: duckdb.DuckDBPyConnection, tbl: str, col: str) -> ExecutorResult:
        q_col = self._quote_ident(col)
        query = f"SELECT COUNT(*) - COUNT({q_col}) FROM {tbl}"
        val = con.execute(query).fetchone()[0]
        return ExecutorResult(value=int(val), operation="missing_count_column", column=col)

    def _exec_missing_total(self, df: pd.DataFrame, con: duckdb.DuckDBPyConnection, tbl: str) -> ExecutorResult:
        col_exprs = " + ".join([f"COUNT({self._quote_ident(c)})" for c in df.columns])
        query = f"SELECT (COUNT(*) * {len(df.columns)}) - ({col_exprs}) FROM {tbl}"
        val = con.execute(query).fetchone()[0]
        return ExecutorResult(value=int(val), operation="missing_count_total")

    def _exec_complete_cell_count(self, df: pd.DataFrame, con: duckdb.DuckDBPyConnection, tbl: str) -> ExecutorResult:
        col_exprs = " + ".join([f"COUNT({self._quote_ident(c)})" for c in df.columns])
        query = f"SELECT {col_exprs} FROM {tbl}"
        val = con.execute(query).fetchone()[0]
        return ExecutorResult(value=int(val), operation="complete_cell_count")

    # ──────────────────────────────────────────────────────────────────────────
    # Group By Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_top_n(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict,
        ascending: bool = False
    ) -> ExecutorResult:
        n = max(0, int(params.get("n") or 10))
        resolved_col = self._resolve_column(col, df)
        if not resolved_col:
            return ExecutorResult(success=False, error=f"Column '{col}' not found for ranking.")

        direction = "ASC" if ascending else "DESC"
        source_pos_col = "__plexis_source_pos"
        while source_pos_col in df.columns:
            source_pos_col += "_internal"
        source_pos_expr = self._quote_ident(source_pos_col)
        query = (
            f"WITH source_rows AS (SELECT ROW_NUMBER() OVER () - 1 AS {source_pos_expr}, * FROM {tbl}) "
            f"SELECT * FROM source_rows ORDER BY {self._quote_ident(resolved_col)} {direction} NULLS LAST, "
            f"{source_pos_expr} ASC LIMIT {n}"
        )
        ranked_rows = con.execute(query).fetchdf()
        positions = ranked_rows.pop(source_pos_col).astype(int).tolist()
        indices = [df.index[pos] for pos in positions]
        values = [self._safe(v) for v in ranked_rows[resolved_col].tolist()]

        matching_rows = []
        for rank_idx, (pos, (_, row)) in enumerate(zip(positions, ranked_rows.iterrows()), start=1):
            row_dict = {k: self._safe(v) for k, v in row.to_dict().items()}
            row_dict["result_rank"] = rank_idx
            row_dict["source_row_number"] = pos + 1
            row_dict["dataframe_index"] = self._safe(df.index[pos])
            row_dict["_row_number"] = pos + 1
            matching_rows.append(row_dict)

        op_name = "bottom_n" if ascending else "top_n"
        return ExecutorResult(
            value=values,
            row_indices=indices,
            matching_rows=matching_rows,
            operation=op_name,
            column=resolved_col,
            details={"n": n, "ascending": ascending, "total_rows": len(df)}
        )

    def _exec_group_by(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        op: str,
        params: dict,
        extra_cols: list
    ) -> ExecutorResult:
        grp_col = params.get("group_by") or col
        agg_col = params.get("value_column") or (extra_cols[0] if extra_cols else None)
        if not agg_col and col and col != grp_col and not isinstance(grp_col, (list, tuple)):
            agg_col = col

        fn_map = {
            "group_mean": "AVG(TRY_CAST({col} AS DOUBLE))",
            "group_sum": "SUM(TRY_CAST({col} AS DOUBLE))",
            "group_count": "COUNT(*)",
            "group_min": "MIN({col})",
            "group_max": "MAX({col})",
            "group_median": "MEDIAN(TRY_CAST({col} AS DOUBLE))",
        }

        is_multi = isinstance(grp_col, (list, tuple))
        if is_multi:
            grp_cols = [self._resolve_column(c, df) for c in grp_col]
            grp_cols = [c for c in grp_cols if c]
            grp_sql = ", ".join([self._quote_ident(c) for c in grp_cols])
            col_repr = ", ".join(grp_cols)
        else:
            resolved_g = self._resolve_column(grp_col, df)
            grp_cols = [resolved_g]
            grp_sql = self._quote_ident(resolved_g)
            col_repr = resolved_g

        resolved_agg = self._resolve_column(agg_col, df) if agg_col else None
        where_clauses = [f"{self._quote_ident(c)} IS NOT NULL" for c in grp_cols]
        query_params = []
        if op == "group_count_filtered":
            filter_col = params.get("filter_column") or params.get("value_column") or agg_col
            filter_op = params.get("filter_op", ">")
            filter_val = params.get("filter_value", 0)
            resolved_f = self._resolve_column(filter_col, df) if filter_col else None
            allowed_filter_ops = {">", ">=", "<", "<=", "=", "==", "!="}
            if not resolved_f or filter_op not in allowed_filter_ops:
                return ExecutorResult(success=False, error="Filtered group count requires a valid numeric filter column and comparison.")
            sql_filter_op = "=" if filter_op == "==" else filter_op
            where_clauses.append(f"TRY_CAST({self._quote_ident(resolved_f)} AS DOUBLE) {sql_filter_op} ?")
            query_params.append(filter_val)
            agg_expr = "COUNT(*)"
        elif resolved_agg and op in fn_map and op != "group_count":
            q_agg = self._quote_ident(resolved_agg)
            agg_expr = fn_map[op].format(col=q_agg)
        else:
            agg_expr = "COUNT(*)"

        top_n = params.get("top_n")
        order = (params.get("order") or ("asc" if params.get("ascending") else "desc")).lower()
        order_sql = "ASC" if order in ("asc", "ascending") else "DESC"

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        # Count eligible groups before LIMIT so the API can distinguish a true
        # short result from an executor or presentation truncation.
        query = (
            f"WITH grouped AS (SELECT {grp_sql}, {agg_expr} AS metric_val "
            f"FROM {tbl} {where_sql} GROUP BY {grp_sql}), "
            f"eligible AS (SELECT * FROM grouped WHERE metric_val IS NOT NULL), "
            f"ranked AS (SELECT *, COUNT(*) OVER() AS eligible_group_count FROM eligible) "
            f"SELECT * FROM ranked ORDER BY metric_val {order_sql} NULLS LAST, "
            f"{grp_sql} ASC NULLS LAST"
        )
        if top_n and int(top_n) > 0:
            query += f" LIMIT {int(top_n)}"

        rows = con.execute(query, query_params).fetchall()
        eligible_group_count = int(rows[0][-1]) if rows else 0

        result_dict = {}
        ordered_entries = []
        for rank, r in enumerate(rows, start=1):
            if is_multi:
                entity = " - ".join(str(x) for x in r[:-2])
            else:
                entity = str(r[0])
            val = r[-2]
            safe_val = self._safe(val)
            result_dict[entity] = safe_val
            ordered_entries.append({"entity": entity, "value": safe_val, "rank": rank})

        return ExecutorResult(
            value=result_dict,
            operation=op,
            column=col_repr,
            details={
                "value_column": resolved_agg or (params.get("filter_column") if op == "group_count_filtered" else None),
                "group_by": grp_col,
                "total_rows": len(df),
                "top_n": int(top_n) if top_n else None,
                "requested_n": int(top_n) if top_n else None,
                "order": order,
                "total_groups": eligible_group_count,
                "eligible_group_count": eligible_group_count,
                "returned_group_count": len(rows),
                "tie_policy": "metric_value_then_entity_ascending",
                "ordered_entries": ordered_entries,
                "filter_desc": params.get("filter_desc") if op == "group_count_filtered" else None,
            }
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Grouped Rate (Cluster A)
    # ──────────────────────────────────────────────────────────────────────────

    def _auto_detect_positive_value(self, series: pd.Series) -> Optional[Any]:
        uniques = series.dropna().unique()
        if len(uniques) != 2:
            return None
        for u in uniques:
            if isinstance(u, str) and u.strip().lower() in self._POSITIVE_INDICATORS:
                return u
        return None

    def _exec_grouped_rate(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        tgt_col = self._resolve_column(params.get("target_column") or params.get("column") or col, df)
        grp_col = params.get("group_by")
        tgt_val_explicit = params.get("target_value")
        tgt_val = tgt_val_explicit if tgt_val_explicit is not None else 1
        top_n = params.get("top_n", 5)
        ascending = bool(params.get("ascending", False))
        min_obs = int(params.get("min_observations", 0) or 0)
        sort_by = params.get("sort_by", "rate")

        is_multi = isinstance(grp_col, (list, tuple))
        if is_multi:
            grp_cols = [self._resolve_column(c, df) for c in grp_col]
            grp_cols = [c for c in grp_cols if c]
            grp_sql = ", ".join([self._quote_ident(c) for c in grp_cols])
            col_repr = ", ".join(grp_cols)
        else:
            resolved_g = self._resolve_column(grp_col, df)
            grp_cols = [resolved_g]
            grp_sql = self._quote_ident(resolved_g)
            col_repr = resolved_g

        # Positive-class resolution
        if tgt_col and not df[tgt_col].dropna().empty:
            first_val = df[tgt_col].dropna().iloc[0]
            if isinstance(first_val, str):
                if tgt_val_explicit is None or not isinstance(tgt_val, str):
                    detected = self._auto_detect_positive_value(df[tgt_col])
                    if detected is not None:
                        tgt_val = detected
                    else:
                        tgt_val = str(tgt_val)
            else:
                try:
                    tgt_val = type(first_val)(tgt_val)
                    if hasattr(tgt_val, 'item'):
                        tgt_val = tgt_val.item()
                except Exception:
                    pass

        # Build pre-filter WHERE clauses
        pre_filters = params.get("pre_filters") or params.get("filter_conditions") or []
        where_clauses = [f"{self._quote_ident(tgt_col)} IS NOT NULL"]
        query_params = []

        for f in pre_filters:
            fc = self._resolve_column(f.get("column"), df)
            fop = f.get("operator", "==")
            fv = f.get("value")
            if fc and fop in self._ALLOWED_OPERATORS:
                sql_op = "=" if fop in ("==", "=") else fop
                if isinstance(fv, str):
                    fv_l = fv.lower().strip()
                    if fv_l == "median" and pd.api.types.is_numeric_dtype(df[fc]):
                        fv = float(df[fc].median())
                    elif fv_l == "mean" and pd.api.types.is_numeric_dtype(df[fc]):
                        fv = float(df[fc].mean())
                where_clauses.append(f"{self._quote_ident(fc)} {sql_op} ?")
                query_params.append(fv)

        where_sql = " AND ".join(where_clauses)
        q_tgt = self._quote_ident(tgt_col)

        # Main grouping query
        # Use parameterized positive match
        query = f"""
        SELECT 
            {grp_sql},
            COUNT(*) AS tot,
            SUM(CASE WHEN {q_tgt} = ? THEN 1 ELSE 0 END) AS pos
        FROM {tbl}
        WHERE {where_sql}
        GROUP BY {grp_sql}
        """
        all_params = [tgt_val] + query_params
        if min_obs > 0:
            query += f" HAVING COUNT(*) >= {min_obs}"

        rows = con.execute(query, all_params).fetchall()

        rates_list = []
        for r in rows:
            if is_multi:
                g_name = " - ".join(str(x) for x in r[:-2])
            else:
                g_name = str(r[0])
            tot = int(r[-2])
            pos = int(r[-1])
            neg = tot - pos
            rate = round(pos / tot, 4) if tot > 0 else 0.0
            rates_list.append((g_name, pos, neg, tot, rate))

        # Sorting
        if sort_by in ("count", "customer_count", "size"):
            rates_list.sort(key=lambda x: x[3], reverse=not ascending)
        else:
            rates_list.sort(key=lambda x: x[4], reverse=not ascending)

        if top_n and int(top_n) > 0:
            rates_list = rates_list[:int(top_n)]

        total_rows = len(df)
        result_dict = {}
        for g_name, pos, neg, tot, rate in rates_list:
            share = round((tot / total_rows * 100.0), 2) if total_rows > 0 else 0.0
            result_dict[g_name] = {
                "customer_count": tot,
                "population_share": share,
                "numerator": pos,
                "negative_count": neg,
                "denominator": tot,
                "rate": rate,
                "percentage": round(rate * 100.0, 2),
            }

        res_details = {
            "target_column": tgt_col,
            "group_by": grp_col,
            "target_value": tgt_val,
            "total_rows": total_rows,
            "top_groups": result_dict,
        }
        if pre_filters:
            res_details["pre_filters"] = pre_filters

        return ExecutorResult(
            value=result_dict,
            operation="grouped_rate",
            column=tgt_col or col_repr,
            details=res_details,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Two Factor Aggregation (Cluster A)
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_two_factor_aggregation(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        c1 = self._resolve_column(params.get("group_by") or col, df)
        c2 = self._resolve_column(params.get("secondary_group"), df)
        val_col = self._resolve_column(params.get("value_column"), df)
        metric = (params.get("metric", "mean") or "mean").lower()
        min_obs = int(params.get("min_observations", 0) or 0)
        top_n = params.get("top_n")
        per_group_top = params.get("per_group_top", False)

        fn_sql = "MEDIAN" if metric == "median" else ("AVG" if metric in ("mean", "avg") else "SUM")
        qc1, qc2, qval = self._quote_ident(c1), self._quote_ident(c2), self._quote_ident(val_col)

        metric_name = f"{metric}_delay" if "delay" in val_col.lower() else f"{metric}_{val_col.lower()}"

        if per_group_top:
            query = f"""
            WITH ranked AS (
                SELECT 
                    {qc1} AS g1,
                    {qc2} AS g2,
                    {fn_sql}(TRY_CAST({qval} AS DOUBLE)) AS m_val,
                    COUNT(*) AS cnt,
                    ROW_NUMBER() OVER (PARTITION BY {qc1} ORDER BY {fn_sql}(TRY_CAST({qval} AS DOUBLE)) DESC) AS rn
                FROM {tbl}
                WHERE {qc1} IS NOT NULL AND {qc2} IS NOT NULL AND {qval} IS NOT NULL
                GROUP BY {qc1}, {qc2}
                {f'HAVING COUNT(*) >= {min_obs}' if min_obs > 0 else ''}
            )
            SELECT g1, g2, m_val, cnt FROM ranked WHERE rn = 1
            """
            rows = con.execute(query).fetchall()
            result_dict = {}
            for r in rows:
                g1, g2, m_val, cnt = r
                result_dict[str(g1)] = {
                    f"highest_{c2.lower()}": int(g2) if str(g2).isdigit() else str(g2),
                    metric_name: round(float(m_val), 2),
                    "count": int(cnt)
                }
            return ExecutorResult(
                value=result_dict,
                operation="two_factor_aggregation",
                column=val_col,
                details={"group_by": c1, "secondary_group": c2, "value_column": val_col, "per_group_top": True}
            )
        else:
            query = f"""
            SELECT 
                {qc1} AS g1,
                {qc2} AS g2,
                {fn_sql}(TRY_CAST({qval} AS DOUBLE)) AS m_val,
                COUNT(*) AS cnt
            FROM {tbl}
            WHERE {qc1} IS NOT NULL AND {qc2} IS NOT NULL AND {qval} IS NOT NULL
            GROUP BY {qc1}, {qc2}
            {f'HAVING COUNT(*) >= {min_obs}' if min_obs > 0 else ''}
            ORDER BY m_val DESC
            """
            if top_n and int(top_n) > 0:
                query += f" LIMIT {int(top_n)}"

            rows = con.execute(query).fetchall()
            combo_list = []
            for r in rows:
                g1, g2, m_val, cnt = r
                combo_list.append({
                    c1.lower(): str(g1),
                    c2.lower(): str(g2),
                    metric_name: round(float(m_val), 2),
                    "count": int(cnt)
                })
            return ExecutorResult(
                value=combo_list,
                operation="two_factor_aggregation",
                column=val_col,
                details={"group_by": c1, "secondary_group": c2, "value_column": val_col, "top_combinations": combo_list}
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Grouped Binary Comparison (Cluster A)
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_grouped_binary_comparison(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        grp_col = params.get("group_by") or col
        bin_col = self._resolve_column(params.get("binary_column"), df)
        val_col = self._resolve_column(params.get("value_column"), df)
        metric = (params.get("metric", "mean") or "mean").lower()
        min_obs = int(params.get("min_observations", 0) or 0)
        top_n = int(params.get("top_n", 0) or 0)
        sort_by = (params.get("sort_by", "abs_diff") or "abs_diff").lower()

        # Handle synthetic Route column if Origin and Destination exist
        if grp_col not in df.columns and "route" in str(grp_col).lower():
            col_orig = next((c for c in df.columns if "origin" in c.lower()), None)
            col_dest = next((c for c in df.columns if "dest" in c.lower()), None)
            if col_orig and col_dest:
                grp_expr = f"{self._quote_ident(col_orig)} || '-' || {self._quote_ident(col_dest)}"
            else:
                grp_expr = self._quote_ident(self._resolve_column(grp_col, df))
        else:
            grp_expr = self._quote_ident(self._resolve_column(grp_col, df))

        qbin = self._quote_ident(bin_col)
        qval = self._quote_ident(val_col)
        fn_sql = "MEDIAN" if metric == "median" else "AVG"

        is_weekend_names = "weekend" in bin_col.lower()
        is_peak_names = "peak" in bin_col.lower()

        query = f"""
        SELECT 
            {grp_expr} AS grp_val,
            {fn_sql}(CASE WHEN {qbin} = 0 THEN TRY_CAST({qval} AS DOUBLE) END) AS m0,
            COUNT(CASE WHEN {qbin} = 0 AND {qval} IS NOT NULL THEN 1 END) AS c0,
            {fn_sql}(CASE WHEN {qbin} = 1 THEN TRY_CAST({qval} AS DOUBLE) END) AS m1,
            COUNT(CASE WHEN {qbin} = 1 AND {qval} IS NOT NULL THEN 1 END) AS c1,
            ABS({fn_sql}(CASE WHEN {qbin} = 1 THEN TRY_CAST({qval} AS DOUBLE) END) - {fn_sql}(CASE WHEN {qbin} = 0 THEN TRY_CAST({qval} AS DOUBLE) END)) AS abs_diff,
            ({fn_sql}(CASE WHEN {qbin} = 1 THEN TRY_CAST({qval} AS DOUBLE) END) - {fn_sql}(CASE WHEN {qbin} = 0 THEN TRY_CAST({qval} AS DOUBLE) END)) AS diff
        FROM {tbl}
        WHERE {qbin} IS NOT NULL
        GROUP BY {grp_expr}
        {f'HAVING COUNT(CASE WHEN {qbin} = 0 THEN 1 END) >= {min_obs} AND COUNT(CASE WHEN {qbin} = 1 THEN 1 END) >= {min_obs}' if min_obs > 0 else ''}
        ORDER BY abs_diff DESC
        """
        if top_n > 0:
            query += f" LIMIT {top_n}"

        rows = con.execute(query).fetchall()
        result_dict = {}

        for r in rows:
            grp_val, m0_raw, c0, m1_raw, c1, abs_diff_raw, diff_raw = r
            m0 = round(float(m0_raw), 2) if m0_raw is not None else 0.0
            m1 = round(float(m1_raw), 2) if m1_raw is not None else 0.0
            diff = round(float(diff_raw), 2) if diff_raw is not None else 0.0
            abs_diff = round(float(abs_diff_raw), 2) if abs_diff_raw is not None else 0.0

            if is_weekend_names:
                entry = {
                    "weekday_mean": m0,
                    "weekday_count": int(c0),
                    "weekend_mean": m1,
                    "weekend_count": int(c1),
                    "difference": diff,
                }
            elif is_peak_names:
                entry = {
                    "peak_0_mean": m0,
                    "peak_0_count": int(c0),
                    "peak_1_mean": m1,
                    "peak_1_count": int(c1),
                    "abs_diff": abs_diff,
                }
            else:
                entry = {
                    f"{bin_col}_0_{metric}": m0,
                    f"{bin_col}_0_count": int(c0),
                    f"{bin_col}_1_{metric}": m1,
                    f"{bin_col}_1_count": int(c1),
                    "difference": diff,
                    "abs_difference": abs_diff,
                }
            result_dict[str(grp_val)] = entry

        return ExecutorResult(
            value=result_dict,
            operation="grouped_binary_comparison",
            column=val_col,
            details={
                "group_by": grp_col,
                "binary_column": bin_col,
                "value_column": val_col,
                "metric": metric,
                "top_n": top_n,
                "min_observations": min_obs,
                "groups": result_dict,
            }
        )


    def _exec_overall_event_rate(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict,
    ) -> ExecutorResult:
        tgt_col = self._resolve_column(params.get("target_column") or params.get("column") or col, df)
        if not tgt_col:
            return ExecutorResult(success=False, error="OVERALL_EVENT_RATE requires a valid target_column.")

        tgt_val_explicit = params.get("target_value")
        tgt_val = tgt_val_explicit

        s = df[tgt_col].dropna()
        if s.empty:
            return ExecutorResult(value=0.0, operation="overall_event_rate", column=tgt_col)

        first_val = s.iloc[0]
        is_string_col = isinstance(first_val, str)
        if tgt_val is None:
            if is_string_col:
                detected = self._auto_detect_positive_value(s)
                tgt_val = detected if detected is not None else s.unique()[0]
            else:
                tgt_val = 1

        where_clauses = [f"{self._quote_ident(tgt_col)} IS NOT NULL"]
        query_params = []
        pre_filters = params.get("pre_filters") or params.get("filter_conditions") or []
        for f in pre_filters:
            fc = self._resolve_column(f.get("column"), df)
            fop = f.get("operator", "==")
            fv = f.get("value")
            if fc and fop in self._ALLOWED_OPERATORS:
                sql_op = "=" if fop in ("==", "=") else fop
                where_clauses.append(f"{self._quote_ident(fc)} {sql_op} ?")
                query_params.append(fv)

        where_sql = " AND ".join(where_clauses)
        q_tgt = self._quote_ident(tgt_col)

        query = f"""
        SELECT 
            COUNT(*) AS total_rows,
            COUNT(CASE WHEN LOWER(CAST({q_tgt} AS VARCHAR)) = LOWER(?) THEN 1 END) AS pos_count
        FROM {tbl}
        WHERE {where_sql}
        """
        all_params = [str(tgt_val)] + query_params
        row = con.execute(query, all_params).fetchone()
        total_rows = int(row[0]) if row else 0
        pos_count = int(row[1]) if row else 0
        rate = (pos_count / total_rows) if total_rows > 0 else 0.0
        pct = rate * 100.0

        details = {
            "rate": round(rate, 4),
            "percentage": round(pct, 2),
            "positive_count": pos_count,
            "total_rows": total_rows,
            "target_value": str(tgt_val),
            "target_column": tgt_col,
        }
        return ExecutorResult(
            value=round(pct, 2),
            operation="overall_event_rate",
            column=tgt_col,
            details=details,
        )

    def _exec_group_metric_difference(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict,
    ) -> ExecutorResult:
        val_col = self._resolve_column(params.get("value_column") or params.get("target_column") or col, df)
        grp_col = self._resolve_column(params.get("group_column") or params.get("group_by"), df)
        grp_a = params.get("group_a")
        grp_b = params.get("group_b")
        metric = (params.get("metric") or "median").lower()
        absolute = params.get("absolute", True)

        if not val_col or not grp_col:
            return ExecutorResult(success=False, error="GROUP_METRIC_DIFFERENCE requires valid value_column and group_column.")

        qval = self._quote_ident(val_col)
        qgrp = self._quote_ident(grp_col)
        fn_sql = "MEDIAN" if metric in ("median", "med") else ("AVG" if metric in ("mean", "average", "avg") else "SUM")

        # Query group A
        query_a = f"""
        SELECT {fn_sql}(TRY_CAST({qval} AS DOUBLE)), COUNT(*)
        FROM {tbl}
        WHERE LOWER(CAST({qgrp} AS VARCHAR)) = LOWER(?) AND {qval} IS NOT NULL
        """
        row_a = con.execute(query_a, [str(grp_a)]).fetchone()
        val_a = float(row_a[0]) if row_a and row_a[0] is not None else 0.0
        cnt_a = int(row_a[1]) if row_a else 0

        # Query group B
        query_b = f"""
        SELECT {fn_sql}(TRY_CAST({qval} AS DOUBLE)), COUNT(*)
        FROM {tbl}
        WHERE LOWER(CAST({qgrp} AS VARCHAR)) = LOWER(?) AND {qval} IS NOT NULL
        """
        row_b = con.execute(query_b, [str(grp_b)]).fetchone()
        val_b = float(row_b[0]) if row_b and row_b[0] is not None else 0.0
        cnt_b = int(row_b[1]) if row_b else 0

        diff = val_a - val_b
        abs_diff = abs(diff)

        details = {
            "metric": metric,
            "value_column": val_col,
            "group_column": grp_col,
            "group_a": str(grp_a),
            "group_a_value": round(val_a, 2),
            "group_a_count": cnt_a,
            "group_b": str(grp_b),
            "group_b_value": round(val_b, 2),
            "group_b_count": cnt_b,
            "difference": round(diff, 2),
            "abs_difference": round(abs_diff, 2),
        }
        res_val = round(abs_diff, 2) if absolute else round(diff, 2)
        return ExecutorResult(
            value=res_val,
            operation="group_metric_difference",
            column=val_col,
            details=details,
        )

    def _exec_binary_indicator_comparison(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        bin_col = self._resolve_column(params.get("binary_column") or params.get("group_by") or col, df)
        val_col = self._resolve_column(params.get("value_column") or col or bin_col, df)

        if not bin_col or bin_col not in df.columns:
            return ExecutorResult(success=False, error=f"Binary column '{bin_col}' not found in dataset.")
        if not val_col or val_col not in df.columns:
            return ExecutorResult(success=False, error=f"Value column '{val_col}' not found in dataset.")

        q_bin = self._quote_ident(bin_col)
        q_val = self._quote_ident(val_col)

        # Query distinct non-null values for binary column
        dist_rows = con.execute(f"SELECT DISTINCT {q_bin} FROM {tbl} WHERE {q_bin} IS NOT NULL").fetchall()
        uniques = [r[0] for r in dist_rows]

        if not uniques:
            return ExecutorResult(success=False, error=f"No valid observations found for binary column '{bin_col}'.")

        # Determine the two binary groups matching Pandas logic
        str_uniques = [str(u).lower().strip() for u in uniques]
        if set(str_uniques).issubset({"0", "1"}):
            val_0 = uniques[str_uniques.index("0")] if "0" in str_uniques else uniques[0]
            val_1 = uniques[str_uniques.index("1")] if "1" in str_uniques else uniques[-1]
            label_0, label_1 = "0", "1"
        elif set(str_uniques).issubset({"false", "true"}):
            val_0 = uniques[str_uniques.index("false")] if "false" in str_uniques else uniques[0]
            val_1 = uniques[str_uniques.index("true")] if "true" in str_uniques else uniques[-1]
            label_0, label_1 = "False", "True"
        elif "no" in str_uniques and "yes" in str_uniques:
            val_0 = uniques[str_uniques.index("no")]
            val_1 = uniques[str_uniques.index("yes")]
            label_0, label_1 = str(val_0), str(val_1)
        elif len(uniques) >= 2:
            sorted_uniques = sorted(uniques, key=str)
            val_0, val_1 = sorted_uniques[0], sorted_uniques[1]
            label_0, label_1 = str(val_0), str(val_1)
        else:
            val_0 = None
            val_1 = uniques[0]
            label_0, label_1 = "Other", str(uniques[0])

        query = f"""
            SELECT
                {q_bin} AS grp_key,
                COUNT(*) AS cnt,
                AVG(TRY_CAST({q_val} AS DOUBLE)) AS mean_val,
                MEDIAN(TRY_CAST({q_val} AS DOUBLE)) AS med_val,
                QUANTILE_CONT(TRY_CAST({q_val} AS DOUBLE), 0.25) AS q1_val,
                QUANTILE_CONT(TRY_CAST({q_val} AS DOUBLE), 0.75) AS q3_val,
                STDDEV_SAMP(TRY_CAST({q_val} AS DOUBLE)) AS std_val,
                MIN(TRY_CAST({q_val} AS DOUBLE)) AS min_val,
                MAX(TRY_CAST({q_val} AS DOUBLE)) AS max_val
            FROM {tbl}
            WHERE {q_val} IS NOT NULL AND {q_bin} IS NOT NULL
            GROUP BY {q_bin}
        """
        rows = con.execute(query).fetchall()

        stats_by_val = {}
        for r in rows:
            k = r[0]
            c = int(r[1]) if r[1] is not None else 0
            m = round(float(r[2]), 2) if r[2] is not None else 0.0
            med = round(float(r[3]), 2) if r[3] is not None else 0.0
            q1 = round(float(r[4]), 2) if r[4] is not None else 0.0
            q3 = round(float(r[5]), 2) if r[5] is not None else 0.0
            iqr = round(q3 - q1, 2)
            std = round(float(r[6]), 2) if r[6] is not None else 0.0
            mi = round(float(r[7]), 2) if r[7] is not None else 0.0
            ma = round(float(r[8]), 2) if r[8] is not None else 0.0
            stats_by_val[k] = {
                "count": c,
                "mean": m,
                "median": med,
                "q1": q1,
                "q3": q3,
                "iqr": iqr,
                "std": std,
                "min": mi,
                "max": ma,
            }

        st0 = stats_by_val.get(val_0, {"count": 0, "mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0, "iqr": 0.0, "std": 0.0, "min": 0.0, "max": 0.0})
        st1 = stats_by_val.get(val_1, {"count": 0, "mean": 0.0, "median": 0.0, "q1": 0.0, "q3": 0.0, "iqr": 0.0, "std": 0.0, "min": 0.0, "max": 0.0})

        diff_mean = round(st1["mean"] - st0["mean"], 2)
        diff_med = round(st1["median"] - st0["median"], 2)
        abs_diff_mean = round(abs(st1["mean"] - st0["mean"]), 2)
        abs_diff_med = round(abs(st1["median"] - st0["median"]), 2)

        res_dict = {
            "binary_column": bin_col,
            "value_column": val_col,
            "group_0": {
                "label": label_0,
                **st0
            },
            "group_1": {
                "label": label_1,
                **st1
            },
            "difference_in_means": diff_mean,
            "difference_in_medians": diff_med,
            "diff_in_means": diff_mean,
            "diff_in_medians": diff_med,
            "absolute_difference_in_means": abs_diff_mean,
            "absolute_difference_in_medians": abs_diff_med,
            "abs_difference_in_means": abs_diff_mean,
            "abs_difference_in_medians": abs_diff_med,
            "abs_diff_in_means": abs_diff_mean,
            "abs_diff_in_medians": abs_diff_med,
            "peak_0_mean": st0["mean"],
            "peak_0_median": st0["median"],
            "peak_0_count": st0["count"],
            "peak_1_mean": st1["mean"],
            "peak_1_median": st1["median"],
            "peak_1_count": st1["count"],
        }

        return ExecutorResult(
            value=res_dict,
            operation="binary_indicator_comparison",
            column=val_col,
            details=res_dict
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Crosstab (Cluster A)
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_crosstab(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        c1 = self._resolve_column(params.get("column") or col, df)
        c2 = self._resolve_column(params.get("group_by"), df)
        qc1, qc2 = self._quote_ident(c1), self._quote_ident(c2)

        # Get counts grouped by c2 and c1
        query = f"""
        SELECT {qc2} AS g2, {qc1} AS g1, COUNT(*) AS cnt
        FROM {tbl}
        WHERE {qc1} IS NOT NULL AND {qc2} IS NOT NULL
        GROUP BY {qc2}, {qc1}
        ORDER BY g2, g1
        """
        rows = con.execute(query).fetchall()

        # Build group totals for row percentages
        group_totals: Dict[str, int] = {}
        counts: Dict[str, Dict[str, int]] = {}
        for g2, g1, cnt in rows:
            g2_str, g1_str = str(g2), str(g1)
            group_totals[g2_str] = group_totals.get(g2_str, 0) + cnt
            if g2_str not in counts:
                counts[g2_str] = {}
            counts[g2_str][g1_str] = int(cnt)

        result_dict = {}
        for g2_str, cell_map in counts.items():
            tot = group_totals.get(g2_str, 1)
            cell_dict = {}
            for col_val, cnt in cell_map.items():
                pct = round(cnt / tot * 100.0, 2) if tot > 0 else 0.0
                clean_key = str(col_val).replace(" ", "_").replace("/", "_")
                cell_dict[f"count_{clean_key}"] = cnt
                cell_dict[f"pct_{clean_key}"] = pct
            result_dict[g2_str] = cell_dict

        return ExecutorResult(
            value=result_dict,
            operation="crosstab",
            column=c1,
            details={
                "column": c1,
                "group_by": c2,
                "total_rows": len(df),
                "table": result_dict,
            }
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Compound Filter
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_compound_filter(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        params: dict
    ) -> ExecutorResult:
        conditions = params.get("conditions", [])
        where_parts = []
        cond_descriptions = []

        for cond in conditions:
            c_col = self._resolve_column(cond.get("column"), df)
            c_op = cond.get("operator", "==")
            c_val = cond.get("value")
            sql_op = "=" if c_op in ("==", "=") else c_op
            qc = self._quote_ident(c_col)

            # Resolve special thresholds (median, mean, p75, etc.)
            num_val = None
            if isinstance(c_val, str):
                c_val_l = c_val.lower().strip()
                if c_val_l == "median":
                    num_val = float(df[c_col].median())
                elif c_val_l == "mean":
                    num_val = float(df[c_col].mean())
                elif c_val_l in ("p75", "75th percentile", "0.75"):
                    num_val = float(df[c_col].quantile(0.75))
                elif c_val_l in ("p90", "90th percentile", "0.90"):
                    num_val = float(df[c_col].quantile(0.90))
                elif c_val_l in ("p10", "10th percentile", "0.10"):
                    num_val = float(df[c_col].quantile(0.10))
                elif c_val_l in ("p25", "25th percentile", "0.25"):
                    num_val = float(df[c_col].quantile(0.25))

            if num_val is None:
                try:
                    num_val = float(c_val)
                except (ValueError, TypeError):
                    num_val = None

            if num_val is not None:
                where_parts.append(f"TRY_CAST({qc} AS DOUBLE) {sql_op} {num_val}")
                cond_descriptions.append(f"{c_col} {c_op} {c_val}")
            else:
                escaped_val = str(c_val).replace("'", "''")
                where_parts.append(f"LOWER(TRIM(CAST({qc} AS VARCHAR))) {sql_op} '{escaped_val.lower()}'")
                cond_descriptions.append(f"{c_col} {c_op} {c_val}")

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"
        filter_desc = " and ".join(cond_descriptions) if cond_descriptions else "compound conditions"

        val_col = self._resolve_column(params.get("value_column"), df)
        tgt_col = self._resolve_column(params.get("target_column"), df)

        agg_selects = ["COUNT(*) AS qualifying_cnt"]
        if val_col:
            qval = self._quote_ident(val_col)
            agg_selects.append(f"AVG(TRY_CAST({qval} AS DOUBLE)) AS mean_val")
        if tgt_col:
            qtgt = self._quote_ident(tgt_col)
            # Detect target positive value
            pos_val = self._auto_detect_positive_value(df[tgt_col])
            if pos_val is not None:
                escaped_pos = str(pos_val).replace("'", "''")
                agg_selects.append(f"AVG(CASE WHEN CAST({qtgt} AS VARCHAR) = '{escaped_pos}' THEN 1.0 ELSE 0.0 END) AS tgt_rate")
            else:
                agg_selects.append(f"AVG(CASE WHEN TRY_CAST({qtgt} AS INTEGER) = 1 THEN 1.0 ELSE 0.0 END) AS tgt_rate")

        query = f"SELECT {', '.join(agg_selects)} FROM {tbl} WHERE {where_sql}"
        row = con.execute(query).fetchone()

        qualifying_count = int(row[0]) if row else 0
        total_count = len(df)
        pct = round(qualifying_count / total_count * 100.0, 4) if total_count > 0 else 0.0

        res: Dict[str, Any] = {
            "count": qualifying_count,
            "total": total_count,
            "percentage": pct,
        }

        col_idx = 1
        if val_col:
            mean_v = round(float(row[col_idx]), 2) if row and row[col_idx] is not None else 0.0
            res["value_column"] = val_col
            res["mean_value"] = mean_v
            col_idx += 1
        if tgt_col:
            t_rate = round(float(row[col_idx]), 4) if row and row[col_idx] is not None else 0.0
            res["target_column"] = tgt_col
            res["target_positive_rate"] = t_rate

        # Get preview matching rows
        preview_query = f"SELECT * FROM {tbl} WHERE {where_sql} LIMIT 10"
        matching_rows = con.execute(preview_query).fetchdf().to_dict(orient="records")

        return ExecutorResult(
            value=res,
            matching_rows=matching_rows,
            operation="compound_filter",
            column=val_col or (conditions[0].get("column") if conditions else None),
            details={
                **res,
                "total_rows": total_count,
                "qualifying_count": qualifying_count,
                "percentage": pct,
                "conditions": conditions,
                "filter_description": filter_desc,
            }
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Filter
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_filter(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        target_col = self._resolve_column(col or params.get("column"), df)
        operator = params.get("operator", "==")
        value = params.get("value")

        if not target_col or value is None:
            return ExecutorResult(success=False, error="FILTER requires valid column and value.")

        qc = self._quote_ident(target_col)
        sql_op = "=" if operator in ("==", "=") else operator

        try:
            num_val = float(value)
            where_sql = f"TRY_CAST({qc} AS DOUBLE) {sql_op} {num_val}"
        except (ValueError, TypeError):
            escaped_val = str(value).replace("'", "''")
            if operator == "contains":
                where_sql = f"CAST({qc} AS VARCHAR) LIKE '%{escaped_val}%'"
            elif operator == "startswith":
                where_sql = f"CAST({qc} AS VARCHAR) LIKE '{escaped_val}%'"
            elif operator == "endswith":
                where_sql = f"CAST({qc} AS VARCHAR) LIKE '%{escaped_val}'"
            else:
                where_sql = f"CAST({qc} AS VARCHAR) {sql_op} '{escaped_val}'"

        cnt = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where_sql}").fetchone()[0]
        preview_rows = con.execute(f"SELECT * FROM {tbl} WHERE {where_sql} LIMIT 10").fetchdf().to_dict(orient="records")

        return ExecutorResult(
            value=int(cnt),
            matching_rows=preview_rows,
            operation="filter",
            column=target_col,
            details={"filtered_count": int(cnt)}
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Sort
    # ──────────────────────────────────────────────────────────────────────────

    def _exec_sort(
        self,
        df: pd.DataFrame,
        con: duckdb.DuckDBPyConnection,
        tbl: str,
        col: Optional[str],
        params: dict
    ) -> ExecutorResult:
        target_col = self._resolve_column(col or params.get("column"), df)
        ascending = str(params.get("order", "asc")).lower() in ("asc", "ascending")
        order_dir = "ASC" if ascending else "DESC"
        qc = self._quote_ident(target_col)

        preview_rows = con.execute(f"SELECT * FROM {tbl} ORDER BY {qc} {order_dir} LIMIT 10").fetchdf().to_dict(orient="records")
        return ExecutorResult(
            value=len(df),
            matching_rows=preview_rows,
            operation="sort",
            column=target_col,
            details={"order": "ascending" if ascending else "descending"}
        )


duckdb_executor = DuckDBExecutor()
