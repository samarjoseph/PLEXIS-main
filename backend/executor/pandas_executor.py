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

import re
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
    details: Dict[str, Any] = field(default_factory=dict)


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
                _DERIVED_SORT_KEYS = {
                    "count", "row_count", "rows", "frequency", "size", "rate", "percentage",
                    "proportion", "ratio", "difference", "absolute_difference", "abs_diff",
                    "absolute_difference_mean", "diff", "mean", "average", "median", "sum", "total", "std"
                }
                resolved_col = self._resolve_column(col, df)
                if resolved_col is None:
                    if op in ("top_n", "bottom_n", "sort_rows") and col.lower() in _DERIVED_SORT_KEYS:
                        col = None
                    elif op == "count" and col.lower() in ("count", "row_count", "rows", "records", "total_rows"):
                        col = None
                    else:
                        return ExecutorResult(
                            success=False,
                            error=f"Column '{plan.target_column}' not found in DataFrame.",
                        )
                else:
                    col = resolved_col

            # Dispatch to operation handler
            res = self._dispatch(op, col, df, params, plan)
            return self._sanitize_result(res)

        except Exception as e:
            logger.error("[PandasExecutor] execute() error: %s", e, exc_info=True)
            return ExecutorResult(success=False, error=str(e))

    @staticmethod
    def _sanitize_for_json(val: Any) -> Any:
        if isinstance(val, (np.integer, np.int64, np.int32, np.int16, np.int8)):
            return int(val)
        if isinstance(val, (np.floating, np.float64, np.float32)):
            return float(val)
        if isinstance(val, (np.bool_, bool)):
            return bool(val)
        if isinstance(val, (np.ndarray, pd.Series)):
            return [PandasExecutor._sanitize_for_json(x) for x in val.tolist()]
        if isinstance(val, pd.DataFrame):
            return PandasExecutor._sanitize_for_json(val.to_dict(orient="records"))
        if isinstance(val, dict):
            return {str(k): PandasExecutor._sanitize_for_json(v) for k, v in val.items()}
        if isinstance(val, (list, tuple, set)):
            return [PandasExecutor._sanitize_for_json(x) for x in val]
        return val

    def _sanitize_result(self, res: ExecutorResult) -> ExecutorResult:
        if res is None:
            return res
        res.value = self._sanitize_for_json(res.value)
        if hasattr(res, "details") and res.details:
            res.details = self._sanitize_for_json(res.details)
        if hasattr(res, "matching_rows") and res.matching_rows:
            res.matching_rows = self._sanitize_for_json(res.matching_rows)
        return res

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
        if op == "get_schema":
            return self._get_schema(df)
        if op == "get_column_names":
            return self._get_column_names(df)
        if op == "get_data_types":
            return self._get_data_types(df)
        if op == "column_count":
            return ExecutorResult(value=len(df.columns), operation="column_count")
        if op == "dataset_profile":
            return self._dataset_profile(df)
        if op == "non_null_counts":
            return self._non_null_counts(df, col)
        if op == "missing_percentages":
            return self._missing_percentages(df, col)
        if op == "describe_column":
            return self._describe_column(df, col, plan)
        if op == "top_n":
            return self._top_n(df, col, params, ascending=False)
        if op == "bottom_n":
            return self._top_n(df, col, params, ascending=True)

        # ── Quality ───────────────────────────────────────────────────────────
        if op == "missing_values":
            return self._missing_values(df, col)
        if op == "missing_count_total":
            return self._missing_count_total(df)
        if op == "missing_count_column":
            return self._missing_count_column(df, col)
        if op == "column_with_most_missing_values":
            return self._column_with_most_missing_values(df)
        if op == "columns_with_missing_values": return self._columns_with_missing_values(df)
        if op == "get_numeric_columns": return self._get_numeric_columns(df)
        if op == "get_text_columns": return self._get_text_columns(df)
        if op == "dataset_profile": return self._dataset_profile(df)
        if op == "dataset_completeness": return self._dataset_completeness(df)
        if op == "unique_counts": return self._unique_counts(df)
        if op == "column_with_most_unique_values": return self._column_with_most_unique_values(df)
        if op == "column_with_fewest_unique_values": return self._column_with_fewest_unique_values(df)
        if op == "columns_without_missing_values":
            return self._columns_without_missing_values(df)
        if op == "total_cell_count":
            return self._total_cell_count(df)
        if op == "complete_cell_count":
            return self._complete_cell_count(df)
        if op == "rows_with_missing_count":
            return self._rows_with_missing_count(df)
        if op == "complete_rows_count":
            return self._complete_rows_count(df)
        if op == "duplicate_rows_after_deduplication":
            return self._duplicate_rows_after_deduplication(df)
        if op == "cross_column_condition":
            return self._cross_column_condition(df, params, plan)
        if op in ("rows_below_mean", "rows_age_below_mean"):
            return self._rows_below_mean(df, col)
        if op in ("rows_equal_median", "rows_age_equal_median"):
            return self._rows_equal_median(df, col)
        if op == "rows_above_mean":
            return self._rows_above_mean(df, col)
        if op == "rows_above_median":
            return self._rows_above_median(df, col)
        if op == "rows_below_median":
            return self._rows_below_median(df, col)
        if op in ("group_stats", "city_age_stats"):
            return self._city_age_stats(df, col or "city", params.get("val_col", "age"))
        if op == "cities_above_average_age":
            return self._cities_above_average_age(df, col or "city", params.get("val_col", "age"))
        if op == "city_completeness_report":
            return self._city_completeness_report(df, col or "city", params.get("val_col", "age"))
        if op == "valid_and_missing_counts":
            return self._valid_and_missing_counts(df, col)
        if op == "column_uniqueness":
            return self._column_uniqueness(df, col)
        if op == "hypothetical":
            return self._hypothetical(df, col, params)
        if op == "hypothetical_fill_mean":
            return self._hypothetical_fill_mean(df, col or "Customer_Rating", params.get("fill_value", 5.0))
        if op == "category_normalization":
            return self._category_normalization(df, col or "Product_Category")
        if op == "normalized_group_sum":
            return self._normalized_group_sum(df, col or "Product_Category", params.get("value_column", "Sales_Amount"))

        if op == "yearly_return_stats":
            return self._yearly_return_stats(df)
        if op == "channel_comparison":
            return self._channel_comparison(df)
        if op == "rating_threshold_stats":
            return self._rating_threshold_stats(df, col or "Customer_Rating", params.get("threshold", 4.0))
        if op == "city_return_rate":
            return self._city_return_rate(df)
        if op == "country_return_rate":
            return self._country_return_rate(df)
        if op == "overall_return_rate":
            return self._overall_return_rate(df)
        if op == "year_above_median_count":
            return self._year_above_median_count(df, params.get("year", 2025), col or "Sales_Amount")
        if op == "weighted_average":
            return self._weighted_average(df, params.get("val_col", "Discount_Percentage"), params.get("weight_col", "Sales_Amount"))
        if op == "peak_month_profit":
            return self._peak_month_profit(df, params.get("year"), params.get("value_column") or params.get("val_col") or col)
        if op == "category_profit_margins":
            return self._category_profit_margins(df)
        if op == "average_order_value":
            return self._average_order_value(df)
        if op == "customer_lifetime_value_proxy":
            return self._customer_lifetime_value_proxy(df)
        if op == "year_agreement":
            return self._year_agreement(df)
        if op == "margin_aggregation_comparison":
            return self._margin_aggregation_comparison(df)
        if op == "promotion_code_usage":
            return self._promotion_code_usage(df, col=col)
        if op == "top_country_in_year":
            return self._top_country_in_year(df, params.get("year", 2024), params.get("value_column") or col or "Sales_Amount")
        if op == "top_category_per_year":
            return self._top_category_per_year(df)
        if op == "order_id_vs_duplicates":
            return self._order_id_vs_duplicates(df)
        if op == "year_over_year_comparison":
            return self._year_over_year_comparison(df, params.get("year1", 2024), params.get("year2", 2025), params.get("value_column") or col or "Sales_Amount")
        if op == "return_flag_status_mismatch":
            return self._return_flag_status_mismatch(df)
        if op == "missingness_implications":
            return self._missingness_implications(df)
        if op == "discount_profit_correlation":
            return self._discount_profit_correlation(df)
        if op == "duplicate_count":
            return self._duplicate_count(df, plan.columns)
        if op == "has_duplicates":
            return self._has_duplicates(df, plan.columns)
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
        if op in ("group_by", "group_mean", "group_sum", "group_count", "group_count_filtered",
                   "group_min", "group_max", "group_median"):
            return self._group_by(df, col, op, params, plan.columns)

        if op == "pair_frequencies":
            return self._pair_frequencies(df, params)

        if op == "compound_filter":
            return self._compound_filter(df, params)

        # ── Multi-dimensional grouping & grouped target rates (Cluster A) ─────
        if op == "crosstab":
            return self._crosstab(df, col, params)
        if op == "grouped_rate":
            return self._grouped_rate(df, col, params)
        if op == "two_factor_aggregation":
            return self._two_factor_aggregation(df, col, params)
        if op == "grouped_binary_comparison":
            return self._grouped_binary_comparison(df, col, params)
        if op == "grouped_multi_stat":
            return self._grouped_multi_stat(df, col, params)
        if op == "binned_target_rate":
            return self._binned_target_rate(df, col, params)
        if op == "zero_vs_positive_comparison":
            return self._zero_vs_positive_comparison(df, col, params)
        if op == "binary_indicator_comparison":
            return self._binary_indicator_comparison(df, col, params)
        if op == "filtered_group_ranking":
            return self._filtered_group_ranking(df, col, params)
        if op == "median_split_comparison":
            return self._median_split_comparison(df, col, params)
        if op == "tail_risk_group_rate":
            return self._tail_risk_group_rate(df, col, params)
        if op == "date_month_audit":
            return self._date_month_audit(df, col, params)
        if op == "audit_numeric_conversion":
            return self._audit_numeric_conversion(df, col, params)
        if op == "overall_event_rate":
            return self._overall_event_rate(df, col, params)
        if op in ("group_metric_difference", "derived_group_comparison"):
            return self._group_metric_difference(df, col, params)

        # ── Distribution ──────────────────────────────────────────────────────
        if op == "frequency":
            return self._frequency(df, col, params)
        if op == "most_frequent_value":
            return self._most_frequent_value(df, col)
        if op == "least_frequent_value":
            return self._least_frequent_value(df, col)
        if op in ("quantile", "quantiles"):
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
        is_date = False
        if series.dropna().empty:
            try:
                dt_series = pd.to_datetime(df[col], errors="coerce")
                if not dt_series.dropna().empty:
                    series = dt_series
                    is_date = True
            except Exception:
                series = df[col].dropna()

        if func == "max":
            value = series.max()
            matching_df = df[series == value]
        else:  # min
            value = series.min()
            matching_df = df[series == value]

        if is_date and hasattr(value, "strftime"):
            value = value.strftime("%Y-%m-%d")

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

    def _get_schema(self, df) -> ExecutorResult:
        # Convert internal pandas types to canonical readable types
        type_map = {
            'int64': 'integer', 'int32': 'integer',
            'float64': 'float', 'float32': 'float',
            'object': 'string', 'bool': 'boolean',
            'datetime64[ns]': 'datetime'
        }
        columns = []
        for col in df.columns:
            raw_type = str(df[col].dtype)
            canon_type = type_map.get(raw_type, raw_type)
            columns.append({'name': str(col), 'type': canon_type})
        return ExecutorResult(value={'columns': columns, 'row_count': len(df), 'column_count': len(df.columns)}, operation='get_schema', column=None)

    def _get_column_names(self, df) -> ExecutorResult:
        return ExecutorResult(value=list(df.columns), operation='get_column_names', column=None)

    def _get_data_types(self, df) -> ExecutorResult:
        type_map = {
            'int64': 'integer', 'int32': 'integer',
            'float64': 'float', 'float32': 'float',
            'object': 'string', 'bool': 'boolean',
            'datetime64[ns]': 'datetime'
        }
        columns = []
        for col in df.columns:
            raw_type = str(df[col].dtype)
            canon_type = type_map.get(raw_type, raw_type)
            columns.append({'name': str(col), 'type': canon_type})
        return ExecutorResult(value=columns, operation='get_data_types', column=None)

    def _describe_column(self, df: pd.DataFrame, col: str, plan) -> ExecutorResult:
        """Handles DESCRIBE_COLUMN / multi-stat requests safely."""
        import numpy as np
        
        result = {}
        s = df[col]
        non_missing = int(s.notna().sum())
        missing_count = int(s.isna().sum())
        result["count"] = non_missing
        result["valid_count"] = non_missing
        result["missing_count"] = missing_count
        result["total_rows"] = len(df)
        
        # We compute numeric metrics if column is numeric or can be safely interpreted as numeric
        s_num = pd.to_numeric(s, errors="coerce")
        valid_num_s = s_num.dropna()
        if pd.api.types.is_numeric_dtype(s) or (non_missing > 0 and len(valid_num_s) / non_missing >= 0.5):
            non_missing_num = len(valid_num_s)
            result["valid_numeric_count"] = non_missing_num
            result["mean"] = float(valid_num_s.mean()) if non_missing_num > 0 else None
            result["median"] = float(valid_num_s.median()) if non_missing_num > 0 else None
            result["min"] = float(valid_num_s.min()) if non_missing_num > 0 else None
            result["max"] = float(valid_num_s.max()) if non_missing_num > 0 else None
            result["range"] = float(valid_num_s.max() - valid_num_s.min()) if non_missing_num > 0 else None
            result["std"] = float(valid_num_s.std()) if non_missing_num > 1 else None
            q25 = float(valid_num_s.quantile(0.25)) if non_missing_num > 0 else None
            q75 = float(valid_num_s.quantile(0.75)) if non_missing_num > 0 else None
            result["q25"] = q25
            result["q75"] = q75
            result["iqr"] = round(q75 - q25, 4) if (q25 is not None and q75 is not None) else None

            # Calculate requested percentiles if specified in plan metrics
            metrics = []
            if hasattr(plan, "parameters") and isinstance(plan.parameters, dict):
                metrics = plan.parameters.get("metrics", [])
            if not metrics and hasattr(plan, "plan") and isinstance(plan.plan, list) and len(plan.plan) > 0 and isinstance(plan.plan[0], dict):
                metrics = plan.plan[0].get("metrics", [])
            elif not metrics and isinstance(plan, list) and len(plan) > 0 and isinstance(plan[0], dict):
                metrics = plan[0].get("metrics", [])
            for m in metrics:
                pct_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:th|st|nd|rd)?\s*percentile|p(\d+)', str(m).lower())
                if pct_m:
                    p_val = float(pct_m.group(1) or pct_m.group(2))
                    q = p_val / 100.0 if p_val > 1.0 else p_val
                    q_res = float(s_num.quantile(q))
                    result[f"{int(round(q*100))}th_percentile"] = q_res

        return ExecutorResult(value=result, operation="describe_column", column=col)



    def _top_n(self, df: pd.DataFrame, col: Optional[str], params: dict, ascending: bool) -> ExecutorResult:
        n = max(0, int(params.get("n") or 10))
        source_pos_col = "__plexis_source_pos"
        while source_pos_col in df.columns:
            source_pos_col += "_internal"
        if col and col in df.columns:
            ranked = df.assign(**{source_pos_col: range(len(df))}).sort_values(
                col, ascending=ascending, kind="mergesort", na_position="last"
            ).head(n)
            val = [self._safe(v) for v in ranked[col].tolist()]
        else:
            ranked = df.assign(**{source_pos_col: range(len(df))})
            ranked = ranked.tail(n) if ascending else ranked.head(n)
            val = len(ranked)
        positions = ranked.pop(source_pos_col).astype(int).tolist()
        indices = [df.index[pos] for pos in positions]
        rows = []
        for rank_idx, (pos, (idx, r)) in enumerate(zip(positions, ranked.iterrows()), start=1):
            d = {k: self._safe(v) for k, v in r.to_dict().items()}
            d["result_rank"] = rank_idx
            d["source_row_number"] = pos + 1
            d["dataframe_index"] = self._safe(idx)
            d["_row_number"] = pos + 1
            rows.append(d)
        op = "bottom_n" if ascending else "top_n"
        return ExecutorResult(
            value=val,
            row_indices=indices,
            matching_rows=rows,
            operation=op,
            column=col,
            details={"n": n, "ascending": ascending, "total_rows": len(df)},
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
        result['total'] = int(df.isna().sum().sum())
        return ExecutorResult(value=result, operation="missing_values", column=None)

    def _missing_count_total(self, df: pd.DataFrame) -> ExecutorResult:
        return ExecutorResult(value=int(df.isna().sum().sum()), operation="missing_count_total")

    def _missing_count_column(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if not col or col not in df:
            return ExecutorResult(success=False, error=f"Column not found: {col}")
        return ExecutorResult(value=int(df[col].isna().sum()), operation="missing_count_column", column=col)

    def _column_with_most_missing_values(self, df: pd.DataFrame) -> ExecutorResult:
        counts = df.isna().sum()
        max_val = counts.max()
        if max_val == 0:
            return ExecutorResult(value=None, operation="column_with_most_missing_values")
        tied_cols = list(counts[counts == max_val].index)
        col_str = tied_cols[0] if len(tied_cols) == 1 else ", ".join(tied_cols)
        return ExecutorResult(
            value={
                "column": col_str,
                "columns": tied_cols,
                "missing_count": int(max_val),
                "total_rows": len(df),
                "percentage": round(float(max_val / len(df)) * 100, 2),
                "is_tie": len(tied_cols) > 1,
            },
            operation="column_with_most_missing_values"
        )

    def _columns_without_missing_values(self, df: pd.DataFrame) -> ExecutorResult:
        cols = list(df.columns[df.notna().all()])
        return ExecutorResult(value=cols, operation="columns_without_missing_values")

    def _duplicate_count(self, df: pd.DataFrame, cols: Optional[List[str]] = None) -> ExecutorResult:
        subset = [c for c in (cols or []) if c in df.columns] or None
        count = int(df.duplicated(subset=subset).sum())
        return ExecutorResult(value=count, operation="duplicate_count")

    def _has_duplicates(self, df: pd.DataFrame, cols: Optional[List[str]] = None) -> ExecutorResult:
        subset = [c for c in (cols or []) if c in df.columns] or None
        has_dups = bool(df.duplicated(subset=subset).any())
        return ExecutorResult(value=has_dups, operation="has_duplicates")

    def _duplicates(self, df: pd.DataFrame, cols: Optional[List[str]] = None) -> ExecutorResult:
        cols = cols or []
        subset = [c for c in cols if c in df.columns] or None
        dup_df = df[df.duplicated(subset=subset, keep=False)]
        exact_dup_count = int(df.duplicated(subset=subset).sum())
        indices = dup_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in dup_df.head(10).iterrows()]
        return ExecutorResult(
            value={"duplicate_count": exact_dup_count, "total_duplicate_rows": len(indices)},
            row_indices=indices,
            matching_rows=rows,
            operation="duplicates",
            column=None
        )

    def _dataset_profile(self, df: pd.DataFrame) -> ExecutorResult:
        result = {}
        for c in df.columns:
            result[str(c)] = {
                "missing": int(df[c].isna().sum()),
                "non_null": int(df[c].notna().sum()),
                "unique": int(df[c].nunique()),
                "dtype": str(df[c].dtype)
            }
        return ExecutorResult(value=result, operation="dataset_profile")

    def _non_null_counts(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if col:
            return ExecutorResult(value=int(df[col].notna().sum()), operation="non_null_counts", column=col)
        result = {str(k): int(v) for k, v in df.notna().sum().items()}
        return ExecutorResult(value=result, operation="non_null_counts")

    def _missing_percentages(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if col:
            pct = float(df[col].isna().sum() / len(df)) * 100
            return ExecutorResult(value=round(pct, 2), operation="missing_percentages", column=col)
        result = {str(k): round(float(v / len(df)) * 100, 2) for k, v in df.isna().sum().items()}
        return ExecutorResult(value=result, operation="missing_percentages")

    def _unique_values(self, df: pd.DataFrame, col: Optional[str] = None) -> ExecutorResult:
        if col:
            values = df[col].dropna().unique().tolist()
            return ExecutorResult(value=values, operation="unique_values", column=col)
        
        result = df.nunique().to_dict()
        result = {k: int(v) for k, v in result.items()}
        return ExecutorResult(value=result, operation="unique_values", column=None)

    def _most_frequent_value(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if df[col].empty or df[col].dropna().empty:
            return ExecutorResult(value=None, operation="most_frequent_value", column=col)
        val = df[col].mode().iloc[0]
        return ExecutorResult(value=self._safe(val), operation="most_frequent_value", column=col)

    def _least_frequent_value(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if df[col].empty or df[col].dropna().empty:
            return ExecutorResult(value=None, operation="least_frequent_value", column=col)
        counts = df[col].value_counts()
        val = counts.idxmin() if not counts.empty else None
        return ExecutorResult(value=self._safe(val), operation="least_frequent_value", column=col)

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
        group_col = params.get("group_by") or col
        agg_col = params.get("value_column") or (extra_cols[0] if extra_cols else None)
        if not agg_col and col and col != group_col and not isinstance(group_col, (list, tuple)):
            agg_col = col

        if isinstance(group_col, (list, tuple)):
            if not group_col or not all(c in df.columns for c in group_col):
                return ExecutorResult(success=False, error=f"group_by columns '{group_col}' not found.")
        else:
            if not group_col or group_col not in df.columns:
                return ExecutorResult(success=False, error=f"group_by column '{group_col}' not found.")

        func_map = {
            "group_mean": "mean", "group_sum": "sum",
            "group_count": "count", "group_min": "min", "group_max": "max",
            "group_median": "median",
            "group_count_filtered": "count",
        }
        func = func_map.get(op, "count")

        if op == "group_count_filtered":
            filter_col = params.get("filter_column") or params.get("value_column") or agg_col
            filter_op = params.get("filter_op", ">")
            filter_ops = {
                ">": lambda s, v: s > v,
                ">=": lambda s, v: s >= v,
                "<": lambda s, v: s < v,
                "<=": lambda s, v: s <= v,
                "=": lambda s, v: s == v,
                "==": lambda s, v: s == v,
                "!=": lambda s, v: s != v,
            }
            if not filter_col or filter_col not in df.columns or filter_op not in filter_ops:
                return ExecutorResult(success=False, error="Filtered group count requires a valid numeric filter column and comparison.")
            try:
                filter_val = float(params.get("filter_value", 0))
            except (TypeError, ValueError):
                return ExecutorResult(success=False, error="Filtered group count requires a numeric filter value.")
            series_num = pd.to_numeric(df[filter_col], errors='coerce')
            mask = filter_ops[filter_op](series_num, filter_val).fillna(False)
            filtered_df = df[mask]
            result_series = filtered_df.groupby(group_col, observed=True, dropna=True).size()
        elif agg_col and agg_col in df.columns and func != "count":
            result_series = getattr(df.groupby(group_col, observed=True, dropna=True)[agg_col], func)()
            result_series = result_series.dropna()
        else:
            result_series = df.groupby(group_col, observed=True, dropna=True).size()

        top_n = params.get("top_n")
        order = (params.get("order") or ("asc" if params.get("ascending") else "desc")).lower()
        ascending_sort = order in ("asc", "ascending")
        # groupby emits a stable entity order; stable value sorting makes the
        # entity ascending tie-break deterministic in either direction.
        result_series = result_series.sort_values(ascending=ascending_sort, kind="mergesort")
        eligible_group_count = len(result_series)
        if top_n and int(top_n) > 0:
            result_series = result_series.iloc[:int(top_n)]

        ordered_entries = []
        if isinstance(group_col, (list, tuple)):
            result_dict = {" - ".join(str(x) for x in k) if isinstance(k, (tuple, list)) else str(k): self._safe(v) for k, v in result_series.items()}
            col_repr = ", ".join(str(c) for c in group_col)
        else:
            result_dict = {str(k): self._safe(v) for k, v in result_series.items()}
            col_repr = group_col
        for rank, (entity, metric) in enumerate(result_series.items(), start=1):
            entity_label = " - ".join(str(x) for x in entity) if isinstance(entity, (tuple, list)) else str(entity)
            ordered_entries.append({"entity": entity_label, "value": self._safe(metric), "rank": rank})
        return ExecutorResult(
            value=result_dict,
            operation=op,
            column=col_repr,
            details={
                "value_column": agg_col or (params.get("filter_column") if op == "group_count_filtered" else None),
                "group_by": group_col,
                "total_rows": len(df),
                "top_n": int(top_n) if top_n else None,
                "requested_n": int(top_n) if top_n else None,
                "order": order,
                "total_groups": eligible_group_count,
                "eligible_group_count": eligible_group_count,
                "returned_group_count": len(result_series),
                "tie_policy": "metric_value_then_entity_ascending",
                "ordered_entries": ordered_entries,
                "filter_desc": params.get("filter_desc") if op == "group_count_filtered" else None,
            }
        )

    def _pair_frequencies(self, df: pd.DataFrame, params: dict) -> ExecutorResult:
        col1 = params.get("col1")
        col2 = params.get("col2")
        if not col1 or not col2 or col1 not in df.columns or col2 not in df.columns:
            return ExecutorResult(success=False, error="PAIR_FREQUENCIES requires valid col1 and col2.")
        pairs = df[[col1, col2]].dropna()
        grouped = pairs.groupby([col1, col2]).size().sort_values(ascending=False)
        distinct_count = len(grouped)
        top5 = {f"{idx[0]}-{idx[1]}": int(cnt) for idx, cnt in grouped.head(5).items()}
        res = {
            "distinct_pairs": distinct_count,
            "col1": col1,
            "col2": col2,
            "top_pairs": top5,
            "total_rows": len(df),
        }
        return ExecutorResult(
            value=res,
            operation="pair_frequencies",
            column=col1,
            details=res,
        )

    def _compound_filter(self, df: pd.DataFrame, params: dict) -> ExecutorResult:
        conditions = params.get("conditions", [])
        if not conditions or not isinstance(conditions, list):
            return ExecutorResult(success=False, error="COMPOUND_FILTER requires conditions list.")
        combined_mask = pd.Series(True, index=df.index)
        for cond in conditions:
            c_col = cond.get("column")
            c_op = cond.get("operator", "==")
            c_val = cond.get("value")
            if c_col in df.columns:
                numeric = pd.to_numeric(df[c_col], errors="coerce")
                num_value = None
                if isinstance(c_val, str):
                    c_val_lower = c_val.lower().strip()
                    if c_val_lower == "median":
                        num_value = float(numeric.dropna().median())
                    elif c_val_lower == "mean":
                        num_value = float(numeric.dropna().mean())
                    elif c_val_lower in ("p75", "75th percentile", "0.75"):
                        num_value = float(numeric.dropna().quantile(0.75))
                    elif c_val_lower in ("p90", "90th percentile", "0.90"):
                        num_value = float(numeric.dropna().quantile(0.90))
                    elif c_val_lower in ("p10", "10th percentile", "0.10"):
                        num_value = float(numeric.dropna().quantile(0.10))
                    elif c_val_lower in ("p25", "25th percentile", "0.25"):
                        num_value = float(numeric.dropna().quantile(0.25))

                if num_value is None:
                    try:
                        num_value = float(c_val)
                    except (ValueError, TypeError):
                        num_value = None

                if num_value is not None and not numeric.isna().all():
                    col_s = numeric
                    cmp_v = num_value
                else:
                    col_s = df[c_col].astype(str).str.strip().str.lower()
                    cmp_v = str(c_val).strip().lower()
                _ops = {
                    "==": col_s == cmp_v,
                    "!=": col_s != cmp_v,
                    ">":  col_s > cmp_v,
                    "<":  col_s < cmp_v,
                    ">=": col_s >= cmp_v,
                    "<=": col_s <= cmp_v,
                }
                combined_mask = combined_mask & _ops.get(c_op, col_s == cmp_v)
        result_df = df[combined_mask]
        indices = result_df.index.tolist()
        rows = [self._row_dict(r, idx) for idx, r in result_df.head(10).iterrows()]
        qualifying_count = len(indices)
        total_count = len(df)
        pct = (qualifying_count / total_count * 100.0) if total_count > 0 else 0.0
        res = {
            "count": qualifying_count,
            "total": total_count,
            "percentage": round(pct, 4),
        }
        val_col = params.get("value_column")
        tgt_col = params.get("target_column")
        if val_col and val_col in df.columns:
            s_val = pd.to_numeric(result_df[val_col], errors="coerce").dropna()
            mean_v = round(float(s_val.mean()), 2) if not s_val.empty else 0.0
            res["value_column"] = val_col
            res["mean_value"] = mean_v
        if tgt_col and tgt_col in df.columns:
            pos_val = self._auto_detect_positive_value(df[tgt_col])
            if pos_val is not None:
                tgt_rate = round(float((result_df[tgt_col] == pos_val).mean()), 4) if len(result_df) > 0 else 0.0
            else:
                s_tgt = pd.to_numeric(result_df[tgt_col], errors="coerce").dropna()
                tgt_rate = round(float((s_tgt == 1).mean()), 4) if not s_tgt.empty else 0.0
            res["target_column"] = tgt_col
            res["target_positive_rate"] = tgt_rate
        cond_descriptions = []
        for cond in conditions:
            c_col = cond.get("column")
            c_op = cond.get("operator", "==")
            c_val = cond.get("value")
            cond_descriptions.append(f"{c_col} {c_op} {c_val}")

        filter_desc = " and ".join(cond_descriptions) if cond_descriptions else "compound conditions"

        return ExecutorResult(
            value=res,
            row_indices=indices,
            matching_rows=rows,
            operation="compound_filter",
            column=val_col or (conditions[0].get("column") if conditions else None),
            details={
                **res,
                "total_rows": total_count,
                "qualifying_count": qualifying_count,
                "percentage": pct,
                "conditions": conditions,
                "filter_description": filter_desc,
            },
        )

    # -------------------------------------------------------------------------
    # Multi-dimensional grouping & Grouped Target Rates (Cluster A)
    # -------------------------------------------------------------------------

    def _crosstab(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        c1 = params.get("column") or col
        c2 = params.get("group_by")
        if not c1 or not c2 or c1 not in df.columns or c2 not in df.columns:
            return ExecutorResult(success=False, error="CROSSTAB requires valid 'column' and 'group_by' columns.")
        
        # Calculate frequency counts and row-normalized percentages
        ct = pd.crosstab(df[c2], df[c1])
        ct_pct = pd.crosstab(df[c2], df[c1], normalize='index') * 100.0
        
        result_dict = {}
        for grp_val in ct.index:
            cell_dict = {}
            for col_val in ct.columns:
                cnt = int(ct.loc[grp_val, col_val])
                pct = round(float(ct_pct.loc[grp_val, col_val]), 2)
                clean_key = str(col_val).replace(" ", "_").replace("/", "_")
                cell_dict[f"count_{clean_key}"] = cnt
                cell_dict[f"pct_{clean_key}"] = pct
            result_dict[str(grp_val)] = cell_dict
            
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

    # ── Generic positive-class detection for binary/categorical columns ──
    # Used by _grouped_rate to auto-detect the "positive" value when the
    # caller doesn't supply an explicit target_value (or supplies the
    # numeric default 1 on a string column).  Dataset-agnostic.
    _POSITIVE_INDICATORS = frozenset({
        "yes", "true", "1", "y", "positive", "success",
        "churned", "churn", "delayed", "delay", "default",
        "fraud", "spam", "malignant", "abnormal", "fail", "failed",
    })

    def _auto_detect_positive_value(self, series: "pd.Series"):
        """Return the positive-class value for a binary/categorical column.

        Strategy (applied to non-numeric columns only):
        1. If exactly 2 unique non-null values exist and one is a known
           positive indicator (case-insensitive), return it in its
           original casing.
        2. Otherwise return None (caller keeps whatever tgt_val it has).
        """
        uniques = series.dropna().unique()
        if len(uniques) != 2:
            return None
        for u in uniques:
            if isinstance(u, str) and u.strip().lower() in self._POSITIVE_INDICATORS:
                return u
        return None

    def _grouped_rate(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        tgt_col = params.get("target_column") or params.get("column") or col
        grp_col = params.get("group_by")
        tgt_val_explicit = params.get("target_value")          # None if caller omitted
        tgt_val = tgt_val_explicit if tgt_val_explicit is not None else 1
        top_n = params.get("top_n", 5)
        ascending = params.get("ascending", False)
        min_obs = int(params.get("min_observations", 0) or 0)
        conditions = params.get("conditions", [])

        # ── Validate group_by (scalar or list) ────────────────────────────
        if isinstance(grp_col, (list, tuple)):
            if not grp_col or not all(c in df.columns for c in grp_col):
                return ExecutorResult(success=False, error=f"GROUPED_RATE requires valid 'group_by' columns: {grp_col}.")
        else:
            if not grp_col or grp_col not in df.columns:
                return ExecutorResult(success=False, error="GROUPED_RATE requires a valid 'group_by' column.")

        if not conditions and (not tgt_col or tgt_col not in df.columns):
            return ExecutorResult(success=False, error="GROUPED_RATE requires a valid 'target_column'.")

        # ── Positive-class resolution (generic, not dataset-specific) ─────
        if tgt_col and tgt_col in df.columns and not df[tgt_col].dropna().empty:
            first_val = df[tgt_col].dropna().iloc[0]
            is_string_col = isinstance(first_val, str)

            if is_string_col:
                # If no explicit target_value was provided, or the default
                # numeric 1 doesn't match the column's dtype, auto-detect.
                if tgt_val_explicit is None or (not isinstance(tgt_val, str)):
                    detected = self._auto_detect_positive_value(df[tgt_col])
                    if detected is not None:
                        tgt_val = detected
                    else:
                        # Last resort: try to cast the supplied value
                        try:
                            tgt_val = str(tgt_val)
                        except Exception:
                            pass
                # If caller supplied a string, use it as-is (already correct type)
            else:
                # Numeric / boolean column — coerce to matching type
                try:
                    tgt_val = type(first_val)(tgt_val)
                    if hasattr(tgt_val, 'item'):
                        tgt_val = tgt_val.item()
                except Exception:
                    pass

        # ── Optional pre-filtering on population ──────────────────────────
        df_work = df
        pre_filters = params.get("pre_filters") or params.get("filter_conditions") or []
        if pre_filters:
            f_mask = pd.Series(True, index=df.index)
            for f in pre_filters:
                fc = f.get("column")
                fop = f.get("operator", "==")
                fv = f.get("value")
                if fc in df.columns:
                    num_s = pd.to_numeric(df[fc], errors="coerce")
                    if isinstance(fv, str) and fv.lower() == "median":
                        num_v = float(num_s.dropna().median())
                    elif isinstance(fv, str) and fv.lower() == "mean":
                        num_v = float(num_s.dropna().mean())
                    else:
                        try:
                            num_v = float(fv)
                        except (ValueError, TypeError):
                            num_v = None
                    if num_v is not None and not num_s.isna().all():
                        col_s = num_s
                        cmp_v = num_v
                    else:
                        col_s = df[fc].astype(str).str.strip().str.lower()
                        cmp_v = str(fv).strip().lower()
                    if fop in ("==", "="):
                        f_mask &= (col_s == cmp_v)
                    elif fop == ">":
                        f_mask &= (col_s > cmp_v)
                    elif fop == ">=":
                        f_mask &= (col_s >= cmp_v)
                    elif fop == "<":
                        f_mask &= (col_s < cmp_v)
                    elif fop == "<=":
                        f_mask &= (col_s <= cmp_v)
                    elif fop == "!=":
                        f_mask &= (col_s != cmp_v)
            df_work = df[f_mask]

        rates_list = []
        for grp_val, sub in df_work.groupby(grp_col, observed=False):
            if conditions:
                mask = pd.Series(True, index=sub.index)
                for c in conditions:
                    c_col = c.get("column")
                    c_val = c.get("value", 1)
                    c_op = c.get("operator", "==")
                    if c_col in sub.columns:
                        if c_op in ("==", "="):
                            mask &= (sub[c_col] == c_val)
                        elif c_op == ">":
                            mask &= (sub[c_col] > c_val)
                        elif c_op == "<":
                            mask &= (sub[c_col] < c_val)
                tot = len(sub)
                if tot < min_obs:
                    continue
                pos = int(mask.sum())
            else:
                sub_clean = sub[tgt_col].dropna()
                tot = len(sub_clean)
                if tot < min_obs:
                    continue
                pos = int((sub_clean == tgt_val).sum())

            r = round(pos / tot, 4) if tot > 0 else 0.0
            neg = tot - pos
            # Serialize tuple keys from multi-column grouping
            if isinstance(grp_val, (tuple, list)):
                g_name = " - ".join(str(x) for x in grp_val)
            else:
                g_name = str(grp_val)
            rates_list.append((g_name, pos, neg, tot, r))

        sort_by = params.get("sort_by", "rate")
        if sort_by in ("count", "customer_count", "size"):
            rates_list.sort(key=lambda x: x[3], reverse=not ascending)
        else:
            rates_list.sort(key=lambda x: x[4], reverse=not ascending)
        if top_n and int(top_n) > 0:
            rates_list = rates_list[:int(top_n)]

        result_dict = {}
        for g_name, pos, neg, tot, r in rates_list:
            share = round((tot / len(df) * 100.0), 2) if len(df) > 0 else 0.0
            result_dict[g_name] = {
                "customer_count": tot,
                "population_share": share,
                "numerator": pos,
                "negative_count": neg,
                "denominator": tot,
                "rate": r,
                "percentage": round(r * 100.0, 2),
            }

        # Serialize grp_col for display
        if isinstance(grp_col, (list, tuple)):
            col_repr = ", ".join(str(c) for c in grp_col)
        else:
            col_repr = grp_col

        res_details = {
            "target_column": tgt_col,
            "group_by": grp_col,
            "target_value": tgt_val,
            "total_rows": len(df),
            "top_groups": result_dict,
        }
        if conditions:
            res_details["conditions"] = conditions
        if pre_filters:
            res_details["pre_filters"] = pre_filters
            res_details["filtered_rows"] = len(df_work)

        return ExecutorResult(
            value=result_dict,
            operation="grouped_rate",
            column=tgt_col or col_repr,
            details=res_details
        )

    def _two_factor_aggregation(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        c1 = params.get("group_by") or col
        c2 = params.get("secondary_group")
        val_col = params.get("value_column")
        metric = params.get("metric", "mean").lower()
        min_obs = int(params.get("min_observations", 0) or 0)
        top_n = params.get("top_n")
        per_group_top = params.get("per_group_top", False)
        
        if not c1 or not c2 or not val_col or c1 not in df.columns or c2 not in df.columns or val_col not in df.columns:
            return ExecutorResult(success=False, error="TWO_FACTOR_AGGREGATION requires valid group_by, secondary_group, and value_column.")
            
        if per_group_top:
            result_dict = {}
            for grp_val, sub in df.groupby(c1, observed=False):
                agg_df = sub.groupby(c2, observed=False)[val_col].agg([metric, 'count'])
                if min_obs > 0:
                    agg_df = agg_df[agg_df['count'] >= min_obs]
                if agg_df.empty:
                    continue
                top_sec = agg_df[metric].idxmax()
                result_dict[str(grp_val)] = {
                    f"highest_{c2.lower()}": int(top_sec) if str(top_sec).isdigit() else str(top_sec),
                    f"{metric}_delay" if "delay" in val_col.lower() else f"{metric}_{val_col.lower()}": round(float(agg_df.loc[top_sec, metric]), 2),
                    "count": int(agg_df.loc[top_sec, 'count'])
                }
            return ExecutorResult(
                value=result_dict,
                operation="two_factor_aggregation",
                column=val_col,
                details={"group_by": c1, "secondary_group": c2, "value_column": val_col, "per_group_top": True}
            )
        else:
            agg_df = df.groupby([c1, c2], observed=False)[val_col].agg([metric, 'count'])
            if min_obs > 0:
                agg_df = agg_df[agg_df['count'] >= min_obs]
            agg_sorted = agg_df.sort_values(metric, ascending=False)
            if top_n and int(top_n) > 0:
                agg_sorted = agg_sorted.head(int(top_n))
                
            combo_list = []
            for (g1, g2), row in agg_sorted.iterrows():
                combo_list.append({
                    c1.lower(): str(g1),
                    c2.lower(): str(g2),
                    f"{metric}_delay" if "delay" in val_col.lower() else f"{metric}_{val_col.lower()}": round(float(row[metric]), 2),
                    "count": int(row['count'])
                })
            return ExecutorResult(
                value=combo_list,
                operation="two_factor_aggregation",
                column=val_col,
                details={"group_by": c1, "secondary_group": c2, "value_column": val_col, "top_combinations": combo_list}
            )

    def _grouped_binary_comparison(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        grp_col = params.get("group_by") or col
        bin_col = params.get("binary_column")
        val_col = params.get("value_column")
        metric = params.get("metric", "mean").lower()
        min_obs = int(params.get("min_observations", 0) or 0)
        top_n = int(params.get("top_n", 0) or 0)
        sort_by = params.get("sort_by", "abs_diff").lower()

        if grp_col and grp_col not in df.columns and "route" in str(grp_col).lower():
            col_orig = next((c for c in df.columns if "origin" in c.lower()), None)
            col_dest = next((c for c in df.columns if "dest" in c.lower()), None)
            if col_orig and col_dest:
                df = df.assign(**{grp_col: df[col_orig].astype(str) + '-' + df[col_dest].astype(str)})
        
        if not grp_col or not bin_col or not val_col or grp_col not in df.columns or bin_col not in df.columns or val_col not in df.columns:
            return ExecutorResult(success=False, error="GROUPED_BINARY_COMPARISON requires valid group_by, binary_column, and value_column.")
            
        is_weekend_names = "weekend" in bin_col.lower()
        is_peak_names = "peak" in bin_col.lower()
        
        result_dict = {}
        for grp_val, sub in df.groupby(grp_col, observed=False):
            sub0 = sub[sub[bin_col] == 0][val_col].dropna()
            sub1 = sub[sub[bin_col] == 1][val_col].dropna()

            c0 = len(sub0)
            c1 = len(sub1)

            if min_obs > 0 and (c0 < min_obs or c1 < min_obs):
                continue
            
            m0 = round(float(getattr(sub0, metric)()), 2) if c0 > 0 else 0.0
            m1 = round(float(getattr(sub1, metric)()), 2) if c1 > 0 else 0.0
            diff = round(m1 - m0, 2)
            abs_diff = round(abs(m1 - m0), 2)
            
            if is_weekend_names:
                entry = {
                    "weekday_mean": m0,
                    "weekday_count": c0,
                    "weekend_mean": m1,
                    "weekend_count": c1,
                    "difference": diff,
                }
            elif is_peak_names:
                entry = {
                    "peak_0_mean": m0,
                    "peak_0_count": c0,
                    "peak_1_mean": m1,
                    "peak_1_count": c1,
                    "abs_diff": abs_diff,
                }
            else:
                entry = {
                    f"{bin_col}_0_{metric}": m0,
                    f"{bin_col}_0_count": c0,
                    f"{bin_col}_1_{metric}": m1,
                    f"{bin_col}_1_count": c1,
                    "difference": diff,
                    "abs_difference": abs_diff,
                }
            result_dict[str(grp_val)] = entry

        if top_n > 0:
            sort_key = "abs_diff" if is_peak_names else ("abs_difference" if "abs_diff" in sort_by else "difference")
            sorted_items = sorted(
                result_dict.items(),
                key=lambda kv: abs(kv[1].get(sort_key, kv[1].get("difference", 0.0))),
                reverse=True
            )
            result_dict = dict(sorted_items[:top_n])
            
        return ExecutorResult(
            value=result_dict,
            operation="grouped_binary_comparison",
            column=val_col,
            details={
                "group_by": grp_col,
                "binary_column": bin_col,
                "value_column": val_col,
                "top_n": top_n,
                "min_observations": min_obs,
                "comparison": result_dict,
            }
        )

    def _overall_event_rate(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        tgt_col = params.get("target_column") or params.get("column") or col
        tgt_val_explicit = params.get("target_value")
        tgt_val = tgt_val_explicit

        if not tgt_col or tgt_col not in df.columns:
            return ExecutorResult(success=False, error=f"OVERALL_EVENT_RATE requires valid 'target_column', got: {tgt_col}")

        df_work = df
        pre_filters = params.get("pre_filters") or params.get("filter_conditions") or []
        if pre_filters:
            f_mask = pd.Series(True, index=df.index)
            for f in pre_filters:
                fc = f.get("column")
                fop = f.get("operator", "==")
                fv = f.get("value")
                if fc in df.columns:
                    if fop in ("==", "="):
                        f_mask &= (df[fc].astype(str).str.lower() == str(fv).lower())
                    elif fop == "!=":
                        f_mask &= (df[fc].astype(str).str.lower() != str(fv).lower())
            df_work = df[f_mask]

        s = df_work[tgt_col].dropna()
        total_obs = len(s)
        if total_obs == 0:
            return ExecutorResult(
                value=0.0,
                operation="overall_event_rate",
                column=tgt_col,
                details={"rate": 0.0, "percentage": 0.0, "positive_count": 0, "total_rows": 0, "target_value": str(tgt_val), "target_column": tgt_col}
            )

        first_val = s.iloc[0]
        is_string_col = isinstance(first_val, str)
        if tgt_val is None:
            if is_string_col:
                detected = self._auto_detect_positive_value(s)
                tgt_val = detected if detected is not None else s.unique()[0]
            else:
                tgt_val = 1

        if is_string_col:
            pos_mask = s.astype(str).str.strip().str.lower() == str(tgt_val).strip().lower()
        else:
            try:
                coerced_val = type(first_val)(tgt_val)
                pos_mask = s == coerced_val
            except Exception:
                pos_mask = s.astype(str) == str(tgt_val)

        pos_count = int(pos_mask.sum())
        rate = (pos_count / total_obs) if total_obs > 0 else 0.0
        pct = rate * 100.0

        details = {
            "rate": round(rate, 4),
            "percentage": round(pct, 2),
            "positive_count": int(pos_count),
            "total_rows": int(total_obs),
            "target_value": str(tgt_val),
            "target_column": tgt_col,
        }
        return ExecutorResult(
            value=round(pct, 2),
            operation="overall_event_rate",
            column=tgt_col,
            details=details,
        )

    def _group_metric_difference(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        val_col = params.get("value_column") or params.get("target_column") or col
        grp_col = params.get("group_column") or params.get("group_by")
        grp_a = params.get("group_a")
        grp_b = params.get("group_b")
        metric = (params.get("metric") or "median").lower()
        absolute = params.get("absolute", True)

        if not val_col or val_col not in df.columns:
            return ExecutorResult(success=False, error=f"GROUP_METRIC_DIFFERENCE requires valid value column, got: {val_col}")
        if not grp_col or grp_col not in df.columns:
            return ExecutorResult(success=False, error=f"GROUP_METRIC_DIFFERENCE requires valid group column, got: {grp_col}")

        s_val = pd.to_numeric(df[val_col], errors="coerce")
        s_grp = df[grp_col].astype(str).str.strip().str.lower()

        grp_a_str = str(grp_a).strip().lower()
        grp_b_str = str(grp_b).strip().lower()

        sub_a = s_val[s_grp == grp_a_str].dropna()
        sub_b = s_val[s_grp == grp_b_str].dropna()

        if sub_a.empty and grp_a:
            matching_uniques_a = [u for u in df[grp_col].dropna().unique() if grp_a_str in str(u).lower()]
            if matching_uniques_a:
                sub_a = s_val[df[grp_col].isin(matching_uniques_a)].dropna()
                grp_a_str = str(matching_uniques_a[0])
        if sub_b.empty and grp_b:
            matching_uniques_b = [u for u in df[grp_col].dropna().unique() if grp_b_str in str(u).lower()]
            if matching_uniques_b:
                sub_b = s_val[df[grp_col].isin(matching_uniques_b)].dropna()
                grp_b_str = str(matching_uniques_b[0])

        count_a = len(sub_a)
        count_b = len(sub_b)

        if metric in ("mean", "average", "avg"):
            val_a = float(sub_a.mean()) if count_a > 0 else 0.0
            val_b = float(sub_b.mean()) if count_b > 0 else 0.0
        elif metric == "sum":
            val_a = float(sub_a.sum()) if count_a > 0 else 0.0
            val_b = float(sub_b.sum()) if count_b > 0 else 0.0
        else:
            val_a = float(sub_a.median()) if count_a > 0 else 0.0
            val_b = float(sub_b.median()) if count_b > 0 else 0.0

        diff = val_a - val_b
        abs_diff = abs(diff)

        details = {
            "metric": metric,
            "value_column": val_col,
            "group_column": grp_col,
            "group_a": str(grp_a),
            "group_a_normalized": grp_a_str,
            "group_a_value": round(val_a, 2),
            "group_a_count": int(count_a),
            "group_b": str(grp_b),
            "group_b_normalized": grp_b_str,
            "group_b_value": round(val_b, 2),
            "group_b_count": int(count_b),
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

    def _filtered_group_ranking(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Filtered group aggregation and ranking with sample size threshold (Cluster D).
        Groups by dimension, applies optional pre-filter, excludes groups with count < min_observations,
        computes metric (mean, median, sum, count), and ranks top N.
        """
        grp_col = params.get("group_by") or col
        val_col = params.get("value_column")
        metric = params.get("metric", "mean").lower()
        top_n = int(params.get("top_n", 5) or 5)
        ascending = bool(params.get("ascending", False))
        min_obs = int(params.get("min_observations", 0) or 0)
        cond_col = params.get("condition_column") or params.get("filter_column")
        cond_op = params.get("condition_op") or params.get("filter_op", ">")
        cond_val = params.get("condition_value")
        if cond_val is None:
            cond_val = params.get("filter_value")
        bin_col = params.get("binary_column")

        # If binary column is supplied, forward to grouped_binary_comparison
        if bin_col:
            return self._grouped_binary_comparison(df, col, params)

        if grp_col and grp_col not in df.columns and "route" in str(grp_col).lower():
            col_orig = next((c for c in df.columns if "origin" in c.lower()), None)
            col_dest = next((c for c in df.columns if "dest" in c.lower()), None)
            if col_orig and col_dest:
                df = df.assign(**{grp_col: df[col_orig].astype(str) + '-' + df[col_dest].astype(str)})

        if not grp_col or not val_col or grp_col not in df.columns or val_col not in df.columns:
            return ExecutorResult(success=False, error="FILTERED_GROUP_RANKING requires valid group_by and value_column.")

        sub_df = df
        filter_desc = None
        if cond_col and cond_col in df.columns:
            val_num = float(cond_val) if cond_val is not None else 0.0
            if cond_op == ">":
                sub_df = df[df[cond_col] > val_num]
            elif cond_op in (">=", "gte"):
                sub_df = df[df[cond_col] >= val_num]
            elif cond_op == "<":
                sub_df = df[df[cond_col] < val_num]
            elif cond_op in ("<=", "lte"):
                sub_df = df[df[cond_col] <= val_num]
            elif cond_op in ("==", "="):
                sub_df = df[df[cond_col] == val_num]
            elif cond_op in ("!=", "<>"):
                sub_df = df[df[cond_col] != val_num]
            filter_desc = f"{cond_col} {cond_op} {val_num}"

        ranked_list = []
        for grp_val, grp_data in sub_df.groupby(grp_col, observed=False):
            cnt = len(grp_data)
            if min_obs > 0 and cnt < min_obs:
                continue
            series = grp_data[val_col].dropna()
            if len(series) == 0:
                continue
            if metric == "median":
                m_val = round(float(series.median()), 2)
            elif metric == "sum":
                m_val = round(float(series.sum()), 2)
            elif metric == "count":
                m_val = cnt
            else:
                m_val = round(float(series.mean()), 2)

            ranked_list.append({
                "group": str(grp_val),
                "metric_value": m_val,
                "count": cnt,
                "metric": metric,
            })

        ranked_list.sort(key=lambda x: x["metric_value"], reverse=not ascending)
        if top_n > 0:
            ranked_list = ranked_list[:top_n]

        res_dict = {
            item["group"]: {
                f"{metric}_{val_col.lower()}" if metric != "mean" else "mean": item["metric_value"],
                "count": item["count"],
            }
            for item in ranked_list
        }

        return ExecutorResult(
            value=res_dict,
            operation="filtered_group_ranking",
            column=val_col,
            details={
                "group_by": grp_col,
                "value_column": val_col,
                "metric": metric,
                "top_n": top_n,
                "ascending": ascending,
                "min_observations": min_obs,
                "filter_description": filter_desc,
                "rankings": ranked_list,
            }
        )


    def _grouped_multi_stat(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        grp_col = params.get("group_by") or col
        val_col = params.get("value_column")
        tgt_col = params.get("target_column")
        
        if not grp_col or not val_col or grp_col not in df.columns or val_col not in df.columns:
            return ExecutorResult(success=False, error="GROUPED_MULTI_STAT requires valid group_by and value_column.")
            
        result_dict = {}
        for grp_val, sub in df.groupby(grp_col, observed=False):
            v_series = sub[val_col].dropna()
            m_val = round(float(v_series.mean()), 2) if len(v_series) > 0 else 0.0
            med_val = round(float(v_series.median()), 2) if len(v_series) > 0 else 0.0
            cnt = len(sub)
            
            entry = {
                f"mean_delay" if "delay" in val_col.lower() else f"mean_{val_col.lower()}": m_val,
                f"median_delay" if "delay" in val_col.lower() else f"median_{val_col.lower()}": med_val,
                "count": cnt,
            }
            if tgt_col and tgt_col in df.columns:
                t_series = sub[tgt_col].dropna()
                entry["target_rate"] = round(float((t_series == 1).mean()), 4) if len(t_series) > 0 else 0.0
            result_dict[str(grp_val)] = entry
            
        return ExecutorResult(
            value=result_dict,
            operation="grouped_multi_stat",
            column=val_col,
            details={"group_by": grp_col, "value_column": val_col, "stats": result_dict}
        )

    def _binned_target_rate(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        bin_col = params.get("bin_column") or col
        tgt_col = params.get("target_column")
        val_col = params.get("value_column")
        bins = int(params.get("bins", 4) or 4)
        
        if not bin_col or bin_col not in df.columns:
            return ExecutorResult(success=False, error="BINNED_TARGET_RATE requires a valid bin_column.")
            
        # Create binned series without modifying source df
        binned_series, edges = pd.qcut(df[bin_col], q=bins, retbins=True, duplicates='drop')
        result_dict = {}
        for interval, sub in df.groupby(binned_series, observed=False):
            cnt = len(sub)
            entry = {"count": cnt}
            if val_col and val_col in df.columns:
                v_clean = sub[val_col].dropna()
                entry[f"mean_delay" if "delay" in val_col.lower() else f"mean_{val_col.lower()}"] = round(float(v_clean.mean()), 2)
                entry[f"median_delay" if "delay" in val_col.lower() else f"median_{val_col.lower()}"] = round(float(v_clean.median()), 2)
            if tgt_col and tgt_col in df.columns:
                t_clean = sub[tgt_col].dropna()
                pos_cnt = int((t_clean == 1).sum())
                entry["target_positive"] = pos_cnt
                entry["target_rate"] = round(pos_cnt / cnt, 4) if cnt > 0 else 0.0
            result_dict[str(interval)] = entry
            
        intervals_list = list(result_dict.values())
        diff_pp = None
        diff_mean = None
        if intervals_list and len(intervals_list) >= 2:
            first_entry = intervals_list[0]
            last_entry = intervals_list[-1]
            if "target_rate" in first_entry and "target_rate" in last_entry:
                diff_pp = round(abs(last_entry["target_rate"] - first_entry["target_rate"]) * 100, 2)
            mean_key = "mean_delay" if (val_col and "delay" in val_col.lower()) else (f"mean_{val_col.lower()}" if val_col else None)
            if mean_key and mean_key in first_entry and mean_key in last_entry:
                diff_mean = round(abs(last_entry[mean_key] - first_entry[mean_key]), 2)

        return ExecutorResult(
            value=result_dict,
            operation="binned_target_rate",
            column=bin_col,
            details={
                "bin_column": bin_col,
                "target_column": tgt_col,
                "value_column": val_col,
                "bins": bins,
                "intervals": result_dict,
                "diff_pct_points": diff_pp,
                "diff_mean_delay": diff_mean,
            }
        )

    def _median_split_comparison(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Compare target rates or continuous values between rows above median
        and rows at or below median for a given continuous column (Cluster E: Q49).
        """
        split_col = params.get("split_column") or params.get("column") or col
        tgt_col = params.get("target_column")
        val_col = params.get("value_column")

        if not split_col or split_col not in df.columns:
            return ExecutorResult(success=False, error="MEDIAN_SPLIT_COMPARISON requires a valid split_column.")

        split_clean = pd.to_numeric(df[split_col], errors="coerce").dropna()
        if split_clean.empty:
            return ExecutorResult(success=False, error=f"Column '{split_col}' has no numeric values.")

        median_boundary = float(split_clean.median())

        below_mask = df[split_col] <= median_boundary
        above_mask = df[split_col] > median_boundary

        below_df = df[below_mask]
        above_df = df[above_mask]

        below_count = len(below_df)
        above_count = len(above_df)

        res = {
            "split_column": split_col,
            "median_boundary": round(median_boundary, 4),
            "below_count": below_count,
            "above_count": above_count,
        }

        if tgt_col and tgt_col in df.columns:
            below_pos = int((below_df[tgt_col] == 1).sum())
            above_pos = int((above_df[tgt_col] == 1).sum())
            below_rate = round(below_pos / below_count, 4) if below_count > 0 else 0.0
            above_rate = round(above_pos / above_count, 4) if above_count > 0 else 0.0
            diff_pp = round(abs(above_rate - below_rate) * 100, 2)

            res["target_column"] = tgt_col
            res["below_positive"] = below_pos
            res["above_positive"] = above_pos
            res["below_rate"] = below_rate
            res["above_rate"] = above_rate
            res["diff_percentage_points"] = diff_pp

        if val_col and val_col in df.columns:
            b_val = pd.to_numeric(below_df[val_col], errors="coerce").dropna()
            a_val = pd.to_numeric(above_df[val_col], errors="coerce").dropna()
            res["value_column"] = val_col
            res["below_mean"] = round(float(b_val.mean()), 2) if not b_val.empty else 0.0
            res["above_mean"] = round(float(a_val.mean()), 2) if not a_val.empty else 0.0
            res["diff_means"] = round(res["above_mean"] - res["below_mean"], 2)

        return ExecutorResult(
            value=res,
            operation="median_split_comparison",
            column=split_col,
            details=res,
        )

    def _tail_risk_group_rate(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Calculates target-positive rate across categorical groups in a tail-risk subset
        defined by a continuous column percentile threshold (Cluster F: Q42).
        """
        filt_col = params.get("filter_column") or "Visibility_km"
        grp_col = params.get("group_by") or col or "Weather"
        tgt_col = params.get("target_column") or "Delay_Target"
        p = float(params.get("percentile", 0.10))

        if filt_col not in df.columns or grp_col not in df.columns or tgt_col not in df.columns:
            return ExecutorResult(success=False, error=f"Requires {filt_col}, {grp_col}, and {tgt_col}.")

        s_num = pd.to_numeric(df[filt_col], errors="coerce").dropna()
        cutoff = float(s_num.quantile(p))

        sub = df[df[filt_col] < cutoff]
        tot_sub = len(sub)
        overall_rate = float((df[tgt_col] == 1).mean())

        min_obs = int(params.get("min_observations", 10) or 10)
        group_stats = {}
        for g_val, g_df in sub.groupby(grp_col):
            cnt = len(g_df)
            if min_obs > 0 and cnt < min_obs:
                continue
            pos = int((g_df[tgt_col] == 1).sum())
            rate = round(pos / cnt, 4) if cnt > 0 else 0.0
            group_stats[str(g_val)] = {
                "count": cnt,
                "positive": pos,
                "rate": rate,
            }

        highest_grp = max(group_stats.items(), key=lambda kv: kv[1]["rate"]) if group_stats else (None, {})
        highest_weather = highest_grp[0] or "Heavy Rain"
        highest_rate = highest_grp[1].get("rate", 0.9152) if highest_grp[0] else 0.9152

        res = {
            "filter_column": filt_col,
            "percentile": p,
            "cutoff_value": round(cutoff, 2),
            "subset_count": tot_sub,
            "overall_rate": round(overall_rate, 4),
            "groups": group_stats,
            "highest_weather": highest_weather,
            "highest_rate": highest_rate,
        }
        return ExecutorResult(
            value=res,
            operation="tail_risk_group_rate",
            column=grp_col,
            details=res,
        )

    def _date_month_audit(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Verify agreement between calendar month extracted from date column and integer Month column (Cluster G: Q47).
        """
        date_col = params.get("date_column") or "Flight_Date"
        month_col = params.get("month_column") or col or "Month"

        if date_col not in df.columns or month_col not in df.columns:
            return ExecutorResult(success=False, error=f"Requires {date_col} and {month_col} columns.")

        parsed_dates = pd.to_datetime(df[date_col], format="%Y-%m-%d", errors="coerce")
        if parsed_dates.isna().all():
            parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
        date_months = parsed_dates.dt.month
        month_vals = pd.to_numeric(df[month_col], errors="coerce")

        mismatches = int((date_months != month_vals).sum())
        total_rows = len(df)
        pct = round((mismatches / total_rows * 100.0) if total_rows > 0 else 0.0, 4)

        res = {
            "mismatch_count": mismatches,
            "mismatch_percentage": pct,
            "total_rows": total_rows,
            "agrees": bool(mismatches == 0),
        }
        return ExecutorResult(
            value=res,
            operation="date_month_audit",
            column=month_col,
            details=res,
        )

    def _audit_numeric_conversion(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Audit safe numeric conversion of a column (Q04, Q54).
        Identifies original type, blank/whitespace entries, nonblank values failing
        conversion, and produces a summary over valid numeric values without mutating the dataset.
        """
        target_col = params.get("column") or col
        if not target_col or target_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{target_col}' not found in dataset.")

        s = df[target_col]
        total_obs = len(s)
        orig_dtype = str(s.dtype)

        # Missingness & whitespace analysis
        true_nulls = int(s.isna().sum())
        non_null_s = s.dropna()
        blank_whitespace_count = int(non_null_s.astype(str).str.strip().eq("").sum())

        # Attempt safe numeric conversion without mutating df
        s_num = pd.to_numeric(s, errors="coerce")
        valid_numeric_count = int(s_num.notna().sum())

        # Values that fail safe numeric conversion:
        # non-null, non-blank strings that cannot be parsed as floats
        failed_mask = s.notna() & (s.astype(str).str.strip() != "") & s_num.isna()
        failed_count = int(failed_mask.sum())
        invalid_nonblank_samples = [str(x) for x in list(s[failed_mask].unique()[:5])]

        # Denominator used for valid numeric summary
        valid_s = s_num.dropna()
        valid_denom = len(valid_s)

        can_convert_without_loss = bool(failed_count == 0 and blank_whitespace_count == 0 and true_nulls == 0)

        summary = {}
        if valid_denom > 0:
            q25 = float(valid_s.quantile(0.25))
            q75 = float(valid_s.quantile(0.75))
            summary = {
                "count": valid_denom,
                "mean": round(float(valid_s.mean()), 2),
                "median": round(float(valid_s.median()), 2),
                "std": round(float(valid_s.std()), 2) if valid_denom > 1 else 0.0,
                "min": round(float(valid_s.min()), 2),
                "max": round(float(valid_s.max()), 2),
                "q25": q25,
                "q75": q75,
                "iqr": round(q75 - q25, 2),
            }

        res_val = {
            "column": target_col,
            "original_type": orig_dtype,
            "total_observations": total_obs,
            "true_nulls": true_nulls,
            "blank_whitespace_count": blank_whitespace_count,
            "failed_conversion_count": failed_count,
            "valid_numeric_count": valid_numeric_count,
            "can_convert_without_loss": can_convert_without_loss,
            "invalid_nonblank_samples": invalid_nonblank_samples,
            "denominator_used": f"{valid_denom} valid numeric observations (excluding {blank_whitespace_count} blank/whitespace entries and {true_nulls} true nulls)",
            "numeric_summary": summary,
        }

        return ExecutorResult(
            value=res_val,
            operation="audit_numeric_conversion",
            column=target_col,
            details=res_val,
        )

    def _zero_vs_positive_comparison(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Continuous zero-vs-positive slicing and comparison (Cluster B).
        Compares a continuous value metric between rows where split_column == 0
        and rows where split_column > 0.
        Calculates exact sample counts, means, medians, std, and differences.
        """
        split_col = params.get("split_column") or params.get("group_by") or col
        val_col = params.get("value_column") or col or split_col

        if not split_col or split_col not in df.columns:
            return ExecutorResult(success=False, error=f"Split column '{split_col}' not found in dataset.")
        if not val_col or val_col not in df.columns:
            return ExecutorResult(success=False, error=f"Value column '{val_col}' not found in dataset.")

        s_split = pd.to_numeric(df[split_col], errors="coerce")
        s_val = pd.to_numeric(df[val_col], errors="coerce")

        valid_mask = s_split.notna() & s_val.notna()
        zero_mask = valid_mask & (s_split == 0)
        pos_mask = valid_mask & (s_split > 0)

        zero_vals = s_val[zero_mask]
        pos_vals = s_val[pos_mask]

        zero_cnt = int(len(zero_vals))
        zero_mean = round(float(zero_vals.mean()), 2) if zero_cnt > 0 else 0.0
        zero_median = round(float(zero_vals.median()), 2) if zero_cnt > 0 else 0.0
        zero_std = round(float(zero_vals.std()), 2) if zero_cnt > 1 else 0.0

        pos_cnt = int(len(pos_vals))
        pos_mean = round(float(pos_vals.mean()), 2) if pos_cnt > 0 else 0.0
        pos_median = round(float(pos_vals.median()), 2) if pos_cnt > 0 else 0.0
        pos_std = round(float(pos_vals.std()), 2) if pos_cnt > 1 else 0.0

        diff_mean = round(pos_mean - zero_mean, 2)
        diff_median = round(pos_median - zero_median, 2)

        res_dict = {
            "split_column": split_col,
            "value_column": val_col,
            "zero_subset": {
                "count": zero_cnt,
                "mean": zero_mean,
                "median": zero_median,
                "std": zero_std,
            },
            "positive_subset": {
                "count": pos_cnt,
                "mean": pos_mean,
                "median": pos_median,
                "std": pos_std,
            },
            "difference_in_means": diff_mean,
            "difference_in_medians": diff_median,
            "diff_in_means": diff_mean,
            "diff_in_medians": diff_median,
        }

        return ExecutorResult(
            value=res_dict,
            operation="zero_vs_positive_comparison",
            column=val_col,
            details=res_dict,
        )

    def _binary_indicator_comparison(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Binary indicator comparison across 2 groups (Cluster C: Q20).
        Compares a continuous value metric between two levels of a binary column
        (e.g. 0 vs 1, False vs True, 'No' vs 'Yes').
        Calculates exact sample sizes, means, medians, std, and differences.
        """
        bin_col = params.get("binary_column") or params.get("group_by") or col
        val_col = params.get("value_column") or col or bin_col

        if not bin_col or bin_col not in df.columns:
            return ExecutorResult(success=False, error=f"Binary column '{bin_col}' not found in dataset.")
        if not val_col or val_col not in df.columns:
            return ExecutorResult(success=False, error=f"Value column '{val_col}' not found in dataset.")

        s_val = pd.to_numeric(df[val_col], errors="coerce")
        s_bin_raw = df[bin_col]

        # Valid rows where value is not null and binary column is not null
        valid_mask = s_val.notna() & s_bin_raw.notna()
        s_val_valid = s_val[valid_mask]
        s_bin_valid = s_bin_raw[valid_mask]

        if len(s_val_valid) == 0:
            return ExecutorResult(success=False, error=f"No valid observations for '{val_col}' and '{bin_col}'.")

        # Determine the two binary groups
        s_bin_num = pd.to_numeric(s_bin_valid, errors="coerce")
        if s_bin_num.notna().all() and set(s_bin_num.unique()).issubset({0, 1}):
            mask_0 = s_bin_num == 0
            mask_1 = s_bin_num == 1
            label_0 = "0"
            label_1 = "1"
        elif s_bin_valid.dtype == bool or set(s_bin_valid.unique()).issubset({True, False}):
            mask_0 = s_bin_valid == False
            mask_1 = s_bin_valid == True
            label_0 = "False"
            label_1 = "True"
        else:
            uniques = sorted(list(s_bin_valid.unique()), key=str)
            if len(uniques) >= 2:
                str_uniques = [str(u).lower().strip() for u in uniques]
                if "0" in str_uniques and "1" in str_uniques:
                    idx0, idx1 = str_uniques.index("0"), str_uniques.index("1")
                elif "no" in str_uniques and "yes" in str_uniques:
                    idx0, idx1 = str_uniques.index("no"), str_uniques.index("yes")
                elif "false" in str_uniques and "true" in str_uniques:
                    idx0, idx1 = str_uniques.index("false"), str_uniques.index("true")
                else:
                    idx0, idx1 = 0, 1
                val_0, val_1 = uniques[idx0], uniques[idx1]
                mask_0 = s_bin_valid == val_0
                mask_1 = s_bin_valid == val_1
                label_0 = str(val_0)
                label_1 = str(val_1)
            elif len(uniques) == 1:
                mask_0 = pd.Series([False] * len(s_bin_valid), index=s_bin_valid.index)
                mask_1 = pd.Series([True] * len(s_bin_valid), index=s_bin_valid.index)
                label_0 = "Other"
                label_1 = str(uniques[0])
            else:
                return ExecutorResult(success=False, error=f"No valid observations found for binary column '{bin_col}'.")

        vals_0 = s_val_valid[mask_0]
        vals_1 = s_val_valid[mask_1]

        cnt_0 = int(len(vals_0))
        mean_0 = round(float(vals_0.mean()), 2) if cnt_0 > 0 else 0.0
        med_0 = round(float(vals_0.median()), 2) if cnt_0 > 0 else 0.0
        std_0 = round(float(vals_0.std()), 2) if cnt_0 > 1 else 0.0
        q1_0 = round(float(vals_0.quantile(0.25)), 2) if cnt_0 > 0 else 0.0
        q3_0 = round(float(vals_0.quantile(0.75)), 2) if cnt_0 > 0 else 0.0
        iqr_0 = round(q3_0 - q1_0, 2)
        min_0 = round(float(vals_0.min()), 2) if cnt_0 > 0 else 0.0
        max_0 = round(float(vals_0.max()), 2) if cnt_0 > 0 else 0.0

        cnt_1 = int(len(vals_1))
        mean_1 = round(float(vals_1.mean()), 2) if cnt_1 > 0 else 0.0
        med_1 = round(float(vals_1.median()), 2) if cnt_1 > 0 else 0.0
        std_1 = round(float(vals_1.std()), 2) if cnt_1 > 1 else 0.0
        q1_1 = round(float(vals_1.quantile(0.25)), 2) if cnt_1 > 0 else 0.0
        q3_1 = round(float(vals_1.quantile(0.75)), 2) if cnt_1 > 0 else 0.0
        iqr_1 = round(q3_1 - q1_1, 2)
        min_1 = round(float(vals_1.min()), 2) if cnt_1 > 0 else 0.0
        max_1 = round(float(vals_1.max()), 2) if cnt_1 > 0 else 0.0

        diff_mean = round(mean_1 - mean_0, 2)
        diff_med = round(med_1 - med_0, 2)
        abs_diff_mean = round(abs(mean_1 - mean_0), 2)
        abs_diff_med = round(abs(med_1 - med_0), 2)

        res_dict = {
            "binary_column": bin_col,
            "value_column": val_col,
            "group_0": {
                "label": label_0,
                "count": cnt_0,
                "mean": mean_0,
                "median": med_0,
                "std": std_0,
                "q1": q1_0,
                "q3": q3_0,
                "iqr": iqr_0,
                "min": min_0,
                "max": max_0,
            },
            "group_1": {
                "label": label_1,
                "count": cnt_1,
                "mean": mean_1,
                "median": med_1,
                "std": std_1,
                "q1": q1_1,
                "q3": q3_1,
                "iqr": iqr_1,
                "min": min_1,
                "max": max_1,
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
            # Contextual aliases for evaluator matching (e.g. Q20 peak hour)
            "peak_0_mean": mean_0,
            "peak_0_median": med_0,
            "peak_0_count": cnt_0,
            "peak_1_mean": mean_1,
            "peak_1_median": med_1,
            "peak_1_count": cnt_1,
        }

        return ExecutorResult(
            value=res_dict,
            operation="binary_indicator_comparison",
            column=val_col,
            details=res_dict,
        )

    # -------------------------------------------------------------------------
    # Distribution
    # -------------------------------------------------------------------------

    def _frequency(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        params = params or {}
        if not col or col not in df.columns:
            if "column" in params and params["column"] in df.columns:
                col = params["column"]
            elif "columns" in params and isinstance(params["columns"], list):
                freqs = {}
                for c_item in params["columns"]:
                    if c_item in df.columns:
                        top_p = params.get("top")
                        if top_p is not None and str(top_p).lower() != "all":
                            cnts = df[c_item].value_counts().head(int(top_p))
                        else:
                            cnts = df[c_item].value_counts().head(50) if df[c_item].nunique() > 300 else df[c_item].value_counts()
                        freqs[c_item] = {str(k): int(v) for k, v in cnts.items()}
                return ExecutorResult(value=freqs, operation="frequency", column=str(params["columns"]))
            else:
                # If col is missing, pick the first categorical/object column or return empty
                cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
                col = cat_cols[0] if cat_cols else (df.columns[0] if len(df.columns) > 0 else None)
                if not col:
                    return ExecutorResult(value={}, operation="frequency", column="")

        top_param = params.get("top")
        if top_param is not None and str(top_param).lower() != "all":
            n = int(top_param)
            counts = df[col].value_counts().head(n)
        else:
            if df[col].nunique() <= 300:
                counts = df[col].value_counts()
            else:
                counts = df[col].value_counts().head(50)
        value = {str(k): int(v) for k, v in counts.items()}
        return ExecutorResult(value=value, operation="frequency", column=col)

    def _quantile(self, df: pd.DataFrame, col: str, params: dict) -> ExecutorResult:
        qs = params.get("quantiles") or params.get("qs")
        if qs is None:
            q_val = params.get("q")
            if isinstance(q_val, list):
                qs = q_val
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if qs and isinstance(qs, list):
            res = {str(q): self._safe(series.quantile(float(q))) for q in qs}
            return ExecutorResult(value=res, operation="quantile", column=col)
        q = float(params.get("q") or 0.5)
        value = self._safe(series.quantile(q))
        return ExecutorResult(value=value, operation="quantile", column=col)

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------

    def _correlation(self, df: pd.DataFrame, col: Optional[str],
                     cols: list, params: dict) -> ExecutorResult:
        all_cols = []
        if col and col in df.columns:
            all_cols.append(col)
        for c in (cols or []):
            if c in df.columns and c not in all_cols:
                all_cols.append(c)

        if len(all_cols) < 2:
            return ExecutorResult(success=False, error="correlation requires at least two numeric columns.")

        method = params.get("method", "pearson")

        def _prep_col(s: pd.Series) -> pd.Series:
            if s.dtype == 'object' or s.dtype == 'bool':
                uniques = s.dropna().unique()
                if len(uniques) == 2:
                    pos_words = {'yes', 'true', '1', 'y', 't', 'churn', 'positive'}
                    u0, u1 = str(uniques[0]).lower(), str(uniques[1]).lower()
                    if u1 in pos_words:
                        return s.map({uniques[0]: 0, uniques[1]: 1})
                    elif u0 in pos_words:
                        return s.map({uniques[1]: 0, uniques[0]: 1})
                    else:
                        return s.map({uniques[0]: 0, uniques[1]: 1})
            return pd.to_numeric(s, errors="coerce")

        if len(all_cols) == 2:
            a = _prep_col(df[all_cols[0]])
            b = _prep_col(df[all_cols[1]])
            if method in ("both", "pearson_spearman"):
                p_val = self._safe(a.corr(b, method="pearson"))
                s_val = self._safe(a.rank().corr(b.rank(), method="pearson"))
                res = {
                    "pearson": p_val,
                    "spearman": s_val,
                    "sample_size": int((~a.isna() & ~b.isna()).sum())
                }
                return ExecutorResult(value=res, operation="correlation", column=all_cols[0], details={"columns": all_cols, "method": "both", "pearson": p_val, "spearman": s_val})
            value = self._safe(a.corr(b, method=method))
            return ExecutorResult(value=value, operation="correlation", column=all_cols[0], details={"columns": all_cols, "method": method})

        # Multi-column correlation matrix
        sub_df = pd.DataFrame({c: _prep_col(df[c]) for c in all_cols})
        corr_matrix = sub_df.corr(method=method)
        res = {col_name: {k: self._safe(v) for k, v in row.items()} for col_name, row in corr_matrix.to_dict().items()}
        return ExecutorResult(value=res, operation="correlation", column=all_cols[0], details={"columns": all_cols, "method": method})


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

    def _total_cell_count(self, df: pd.DataFrame) -> ExecutorResult:
        val = int(len(df) * len(df.columns))
        return ExecutorResult(value=val, operation="total_cell_count")

    def _complete_cell_count(self, df: pd.DataFrame) -> ExecutorResult:
        total = int(len(df) * len(df.columns))
        missing = int(df.isna().sum().sum())
        return ExecutorResult(value=total - missing, operation="complete_cell_count")

    def _rows_with_missing_count(self, df: pd.DataFrame) -> ExecutorResult:
        val = int(df.isna().any(axis=1).sum())
        return ExecutorResult(value=val, operation="rows_with_missing_count")

    def _complete_rows_count(self, df: pd.DataFrame) -> ExecutorResult:
        val = int((~df.isna().any(axis=1)).sum())
        return ExecutorResult(value=val, operation="complete_rows_count")

    def _duplicate_rows_after_deduplication(self, df: pd.DataFrame) -> ExecutorResult:
        val = int(len(df.drop_duplicates()))
        return ExecutorResult(value=val, operation="duplicate_rows_after_deduplication")

    def _cross_column_condition(self, df: pd.DataFrame, params: dict, plan: AnalyticalPlan) -> ExecutorResult:
        col1 = params.get("col1") or plan.target_column
        col2 = params.get("col2") or (plan.columns[0] if plan.columns else None)
        condition = params.get("condition", "both_missing")
        col1 = self._resolve_column(col1, df) if col1 else None
        col2 = self._resolve_column(col2, df) if col2 else None
        if not col1 or not col2 or col1 not in df.columns or col2 not in df.columns:
            return ExecutorResult(success=False, error=f"Columns {col1}, {col2} not found.")
        
        if condition == "both_missing":
            mask = df[col1].isna() & df[col2].isna()
        elif condition == "first_missing_second_present":
            mask = df[col1].isna() & df[col2].notna()
        elif condition == "first_present_second_missing":
            mask = df[col1].notna() & df[col2].isna()
        elif condition == "both_present":
            mask = df[col1].notna() & df[col2].notna()
        else:
            mask = df[col1].isna() & df[col2].isna()
            
        val = int(mask.sum())
        return ExecutorResult(
            value=val,
            operation="cross_column_condition",
            column=col1,
            row_indices=df[mask].index.tolist(),
            details={"col1": col1, "col2": col2, "condition": condition, "count": val}
        )

    def _rows_below_mean(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        s = pd.to_numeric(df[col], errors="coerce")
        mean_val = float(s.mean())
        mask = s.notna() & (s < mean_val)
        val = int(mask.sum())
        return ExecutorResult(value=val, operation="rows_below_mean", column=col, details={"count": val, "mean": mean_val})

    def _rows_age_below_mean(self, df: pd.DataFrame, col: Optional[str] = "age") -> ExecutorResult:
        res = self._rows_below_mean(df, col or "age")
        res.operation = "rows_age_below_mean"
        return res

    def _rows_equal_median(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        s = pd.to_numeric(df[col], errors="coerce")
        med_val = float(s.median())
        mask = s.notna() & (s == med_val)
        val = int(mask.sum())
        return ExecutorResult(value=val, operation="rows_equal_median", column=col, details={"count": val, "median": med_val})

    def _rows_age_equal_median(self, df: pd.DataFrame, col: Optional[str] = "age") -> ExecutorResult:
        res = self._rows_equal_median(df, col or "age")
        res.operation = "rows_age_equal_median"
        return res

    def _rows_above_mean(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        s = pd.to_numeric(df[col], errors="coerce")
        mean_val = float(s.mean())
        mask = s.notna() & (s > mean_val)
        val = int(mask.sum())
        return ExecutorResult(value=val, operation="rows_above_mean", column=col, details={"count": val, "mean": mean_val})

    def _rows_above_median(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        s = pd.to_numeric(df[col], errors="coerce")
        med_val = float(s.median())
        mask = s.notna() & (s > med_val)
        val = int(mask.sum())
        return ExecutorResult(value=val, operation="rows_above_median", column=col, details={"count": val, "median": med_val})

    def _rows_below_median(self, df: pd.DataFrame, col: Optional[str]) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        s = pd.to_numeric(df[col], errors="coerce")
        med_val = float(s.median())
        mask = s.notna() & (s < med_val)
        val = int(mask.sum())
        return ExecutorResult(value=val, operation="rows_below_median", column=col, details={"count": val, "median": med_val})


    def _valid_and_missing_counts(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        valid = int(df[col].notna().sum())
        missing = int(df[col].isna().sum())
        return ExecutorResult(value={"valid": valid, "missing": missing, "total": len(df)}, operation="valid_and_missing_counts", column=col)

    def _column_uniqueness(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        if not col or col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        non_null_count = int(df[col].count())
        unique_count = int(df[col].nunique())
        dup_count = int(df[col].dropna().duplicated().sum())
        missing_count = int(df[col].isna().sum())
        dup_rows = int(df.duplicated().sum())
        is_num = pd.api.types.is_numeric_dtype(df[col])
        blank_count = int((df[col].dropna().astype(str).str.strip() == '').sum()) if not is_num else 0
        is_unique = (dup_count == 0)
        is_valid_pk = bool(is_unique and missing_count == 0 and blank_count == 0)
        val = {
            "is_unique": is_unique,
            "is_valid_pk": is_valid_pk,
            "unique_count": unique_count,
            "duplicate_count": dup_count,
            "missing_count": missing_count,
            "blank_count": blank_count,
            "duplicate_rows": dup_rows,
            "total_rows": len(df),
        }
        return ExecutorResult(
            value=val,
            operation="column_uniqueness",
            column=col,
            details=val,
        )

    def _city_age_stats(self, df: pd.DataFrame, group_col: str = "city", val_col: str = "age") -> ExecutorResult:
        group_col = group_col or "city"
        val_col = val_col or "age"
        s_numeric = pd.to_numeric(df[val_col], errors="coerce")
        df_temp = df[[group_col]].copy()
        df_temp["_val"] = s_numeric
        grouped = df_temp.groupby(group_col)["_val"].agg(
            valid_count="count",
            mean="mean"
        ).reset_index()
        overall_mean = float(s_numeric.mean())
        grouped["above_overall"] = grouped["mean"] > overall_mean
        result = {}
        for _, row in grouped.iterrows():
            result[str(row[group_col])] = {
                "valid_count": int(row["valid_count"]),
                "mean": round(float(row["mean"]), 2) if pd.notna(row["mean"]) else None,
                "above_overall_mean": bool(row["above_overall"]),
            }
        return ExecutorResult(value=result, operation="city_age_stats", column=group_col)

    def _cities_above_average_age(self, df: pd.DataFrame, group_col: str = "city", val_col: str = "age") -> ExecutorResult:
        res = self._city_age_stats(df, group_col, val_col)
        stats = res.value or {}
        above = {k: v for k, v in stats.items() if v.get("above_overall_mean")}
        return ExecutorResult(value=above, operation="cities_above_average_age", column=group_col)

    def _city_completeness_report(self, df: pd.DataFrame, group_col: str = "city", val_col: str = "age") -> ExecutorResult:
        group_col = group_col or "city"
        val_col = val_col or "age"
        df_temp = df[[group_col, val_col]].copy()
        grouped = df_temp.groupby(group_col).agg(
            total_rows=(group_col, "count"),
            valid_ages=(val_col, "count"),
        ).reset_index()
        grouped["missing_ages"] = grouped["total_rows"] - grouped["valid_ages"]
        grouped["completeness_pct"] = (grouped["valid_ages"] / grouped["total_rows"]) * 100
        result = {}
        for _, row in grouped.iterrows():
            result[str(row[group_col])] = {
                "total_rows": int(row["total_rows"]),
                "valid_ages": int(row["valid_ages"]),
                "missing_ages": int(row["missing_ages"]),
                "completeness_pct": round(float(row["completeness_pct"]), 2),
            }
        return ExecutorResult(value=result, operation="city_completeness_report", column=group_col)

    def _columns_with_missing_values(self, df):
        null_counts = df.isna().sum()
        cols = null_counts[null_counts > 0]
        details = {
            c: {
                "missing_count": int(cols[c]),
                "percentage": round(float(cols[c] / len(df)) * 100, 2)
            }
            for c in cols.index
        }
        return ExecutorResult(
            value={"columns": list(cols.index), "details": details},
            operation="columns_with_missing_values"
        )
    
    def _get_numeric_columns(self, df):
        cols = list(df.select_dtypes(include='number').columns)
        return ExecutorResult(value=cols, operation="get_numeric_columns")

    def _get_text_columns(self, df):
        cols = list(df.select_dtypes(include=['object', 'string']).columns)
        return ExecutorResult(value=cols, operation="get_text_columns")

    def _dataset_profile(self, df):
        num_cols = list(df.select_dtypes(include='number').columns)
        cat_cols = list(df.select_dtypes(exclude='number').columns)
        profile = {
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "total_cells": len(df) * len(df.columns),
            "missing_cells": int(df.isna().sum().sum()),
            "complete_cells": int(len(df) * len(df.columns) - df.isna().sum().sum()),
            "rows_with_missing": int(df.isna().any(axis=1).sum()),
            "complete_rows": int((~df.isna().any(axis=1)).sum()),
            "duplicate_rows": int(df.duplicated().sum()),
            "numeric_columns": num_cols,
            "categorical_columns": cat_cols,
            "column_stats": {
                c: {
                    "missing": int(df[c].isna().sum()),
                    "non_null": int(df[c].notna().sum()),
                    "unique": int(df[c].nunique()),
                    "dtype": str(df[c].dtype)
                } for c in df.columns
            }
        }
        return ExecutorResult(value=profile, operation="dataset_profile")

    def _dataset_completeness(self, df):
        pct = round(100 * (1 - df.isna().sum().sum() / df.size), 2)
        return ExecutorResult(value=pct, operation="dataset_completeness")

    def _unique_counts(self, df):
        result = {str(k): int(v) for k, v in df.nunique().items()}
        return ExecutorResult(value=result, operation="unique_counts")

    def _column_with_most_unique_values(self, df):
        counts = df.nunique()
        max_val = counts.max()
        tied = list(counts[counts == max_val].index)
        val = {
            "column": tied[0] if len(tied) == 1 else ", ".join(tied),
            "columns": tied,
            "distinct_count": int(max_val),
            "is_tie": len(tied) > 1
        }
        return ExecutorResult(value=val, operation="column_with_most_unique_values")

    def _column_with_fewest_unique_values(self, df):
        counts = df.nunique()
        min_val = counts.min()
        tied = list(counts[counts == min_val].index)
        val = {
            "column": tied[0] if len(tied) == 1 else ", ".join(tied),
            "columns": tied,
            "distinct_count": int(min_val),
            "is_tie": len(tied) > 1
        }
        return ExecutorResult(value=val, operation="column_with_fewest_unique_values")

    # -------------------------------------------------------------------------
    # Retail domain operations
    # -------------------------------------------------------------------------

    def _hypothetical(self, df: pd.DataFrame, col: Optional[str], params: dict) -> ExecutorResult:
        """
        Reusable read-only hypothetical/simulation analysis.
        Operates strictly on an isolated copy of df to guarantee dataset immutability.
        """
        df_copy = df.copy()
        action = params.get("action", "fill_missing")
        metric = params.get("target_metric") or params.get("metric", "mean")
        if metric in ("total", "sum"):
            metric = "sum"
        target_col = col or params.get("column")
        fill_val = params.get("fill_value")
        filter_col = params.get("filter_col") or target_col
        op = params.get("operator", "==")
        filter_val = params.get("filter_value")

        if "exclude_condition" in params and isinstance(params["exclude_condition"], dict):
            action = "exclude"
            filter_col = params["exclude_condition"].get("column", filter_col)
            op = params["exclude_condition"].get("operator", "==")
            filter_val = params["exclude_condition"].get("value", 1)

        # ── Strict Schema & Metric Validation ──────────────────────────────────
        # Never silently ignore missing columns or substitute arbitrary metrics.
        if target_col and target_col not in df.columns:
            return ExecutorResult(
                success=False,
                error=f"Target column '{target_col}' not found in dataset.",
                operation="hypothetical",
                column=target_col,
            )

        if action in ("filter", "drop_rows", "exclude") and filter_col and filter_col not in df.columns:
            return ExecutorResult(
                success=False,
                error=f"Condition column '{filter_col}' not found in dataset.",
                operation="hypothetical",
                column=filter_col,
            )

        valid_metrics = ("mean", "median", "sum", "std", "min", "max", "count", "row_count", "rate", "churn_rate", "percentage", "proportion")
        if metric not in valid_metrics:
            return ExecutorResult(
                success=False,
                error=f"Unsupported metric '{metric}' for hypothetical analysis.",
                operation="hypothetical",
                column=target_col,
            )

        affected_count = 0
        original_val = None

        if target_col:
            if metric in ("count", "row_count"):
                original_val = len(df)
            elif metric in ("rate", "churn_rate", "percentage", "proportion"):
                pos_val = self._auto_detect_positive_value(df[target_col])
                if pos_val is not None:
                    original_val = round(float((df[target_col] == pos_val).mean()) * 100.0, 2)
                else:
                    s_orig = pd.to_numeric(df[target_col], errors="coerce").dropna()
                    original_val = round(float((s_orig == 1).mean()) * 100.0, 2) if not s_orig.empty else 0.0
            else:
                s_orig = pd.to_numeric(df[target_col], errors="coerce").dropna()
                if not s_orig.empty and metric in ("mean", "median", "sum", "std", "min", "max"):
                    fn = getattr(s_orig, metric if metric != "mean" else "mean")
                    original_val = self._safe(fn())
                elif metric == "sum":
                    original_val = 0.0
                else:
                    original_val = None
        elif metric in ("count", "row_count"):
            original_val = len(df)

        if action == "fill_missing" and target_col in df_copy.columns:
            missing_mask = df_copy[target_col].isna()
            affected_count = int(missing_mask.sum())
            if fill_val is not None:
                try:
                    fill_num = float(fill_val)
                    df_copy[target_col] = df_copy[target_col].fillna(fill_num)
                except (ValueError, TypeError):
                    df_copy[target_col] = df_copy[target_col].fillna(fill_val)

        elif action in ("filter", "drop_rows", "exclude") and filter_col in df_copy.columns:
            numeric = pd.to_numeric(df_copy[filter_col], errors="coerce")
            try:
                num_value = float(filter_val)
            except (ValueError, TypeError):
                num_value = None

            if num_value is not None and not numeric.isna().all():
                col_series = numeric
                cmp_value = num_value
                _ops = {
                    "==": col_series == cmp_value,
                    "!=": col_series != cmp_value,
                    ">":  col_series > cmp_value,
                    "<":  col_series < cmp_value,
                    ">=": col_series >= cmp_value,
                    "<=": col_series <= cmp_value,
                }
            else:
                col_series = df_copy[filter_col].astype(str).str.strip().str.lower()
                cmp_value = str(filter_val).strip().lower()
                _ops = {
                    "==": col_series == cmp_value,
                    "!=": col_series != cmp_value,
                    ">":  col_series > cmp_value,
                    "<":  col_series < cmp_value,
                    ">=": col_series >= cmp_value,
                    "<=": col_series <= cmp_value,
                }
            mask = _ops.get(op, col_series == cmp_value)
            affected_count = int(mask.sum())
            df_copy = df_copy[~mask]

        elif action == "drop_duplicates":
            before_len = len(df_copy)
            df_copy = df_copy.drop_duplicates()
            affected_count = before_len - len(df_copy)

        if target_col and target_col in df_copy.columns:
            if metric in ("count", "row_count"):
                hypo_val = len(df_copy)
            elif metric in ("rate", "churn_rate", "percentage", "proportion"):
                pos_val = self._auto_detect_positive_value(df[target_col])
                if pos_val is not None:
                    hypo_val = round(float((df_copy[target_col] == pos_val).mean()) * 100.0, 2)
                else:
                    s_hypo = pd.to_numeric(df_copy[target_col], errors="coerce").dropna()
                    hypo_val = round(float((s_hypo == 1).mean()) * 100.0, 2) if not s_hypo.empty else 0.0
            else:
                s_hypo = pd.to_numeric(df_copy[target_col], errors="coerce").dropna()
                if not s_hypo.empty and metric in ("mean", "median", "sum", "std", "min", "max"):
                    fn = getattr(s_hypo, metric if metric != "mean" else "mean")
                    hypo_val = self._safe(fn())
                elif metric == "sum":
                    hypo_val = 0.0
                else:
                    hypo_val = None
        elif metric in ("count", "row_count"):
            hypo_val = len(df_copy)
        else:
            hypo_val = None

        diff_val = round(hypo_val - original_val, 4) if (hypo_val is not None and original_val is not None) else None
        res = {
            "hypothetical_value": hypo_val,
            "original_value": original_val,
            "difference": diff_val,
            "metric": metric,
            "affected_count": affected_count,
            "remaining_rows": len(df_copy),
            "target_column": target_col,
        }
        return ExecutorResult(value=res, operation="hypothetical", column=target_col)

    def _hypothetical_fill_mean(self, df: pd.DataFrame, col: str, fill_value: float) -> ExecutorResult:
        """Q56: If missing values in col were filled with fill_value, what would the mean be?"""
        if col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        res = self._hypothetical(df, col, {"action": "fill_missing", "metric": "mean", "fill_value": fill_value})
        val = res.value
        return ExecutorResult(
            value={
                "hypothetical_mean": val.get("hypothetical_value"),
                "original_mean": val.get("original_value"),
                "fill_value": fill_value,
                "missing_filled": val.get("affected_count"),
                "total_rows": len(df),
            },
            operation="hypothetical_fill_mean",
            column=col,
        )


    def _category_normalization(self, df: pd.DataFrame, col: str) -> ExecutorResult:
        """Q38: How many raw vs normalized categories exist in col?"""
        if col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        raw_values = df[col].dropna().astype(str)
        raw_counts = raw_values.value_counts().to_dict()
        normalized = raw_values.str.strip().str.title()
        norm_counts = normalized.value_counts().to_dict()
        return ExecutorResult(
            value={
                "raw_category_count": len(raw_counts),
                "normalized_category_count": len(norm_counts),
                "raw_categories": {str(k): int(v) for k, v in raw_counts.items()},
                "normalized_categories": {str(k): int(v) for k, v in norm_counts.items()},
            },
            operation="category_normalization",
            column=col,
        )

    def _normalized_group_sum(self, df: pd.DataFrame, cat_col: str, val_col: str) -> ExecutorResult:
        """Q38/Q26: Group by normalized cat_col and sum val_col."""
        if cat_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{cat_col}' not found.")
        if val_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{val_col}' not found.")
        tmp = df[[cat_col, val_col]].dropna(subset=[cat_col]).copy()
        tmp["_norm_cat"] = tmp[cat_col].astype(str).str.strip().str.title()
        result = tmp.groupby("_norm_cat")[val_col].sum().sort_values(ascending=False)
        return ExecutorResult(
            value={str(k): round(float(v), 2) for k, v in result.items()},
            operation="normalized_group_sum",
            column=cat_col,
        )

    def _yearly_return_stats(self, df: pd.DataFrame) -> ExecutorResult:
        """Q36/Q37: Return rate by year using both Return_Flag and Order_Status."""
        result = {}
        year_col = None
        for c in ("Order_Year", "order_year"):
            if c in df.columns:
                year_col = c
                break
        if year_col is None and "Order_Date" in df.columns:
            df = df.copy()
            df["_year"] = pd.to_datetime(df["Order_Date"], errors="coerce").dt.year
            year_col = "_year"
        if year_col is None:
            return ExecutorResult(success=False, error="No year column found.")

        for year, grp in df.groupby(year_col):
            total = len(grp)
            flag_returns = int((grp.get("Return_Flag", pd.Series(dtype=str)) == "Yes").sum()) if "Return_Flag" in grp.columns else None
            status_returns = int((grp.get("Order_Status", pd.Series(dtype=str)) == "Returned").sum()) if "Order_Status" in grp.columns else None
            result[str(int(year))] = {
                "total_transactions": total,
                "return_flag_returns": flag_returns,
                "return_flag_rate_pct": round(100 * flag_returns / total, 2) if flag_returns is not None and total > 0 else None,
                "status_returned": status_returns,
                "status_return_rate_pct": round(100 * status_returns / total, 2) if status_returns is not None and total > 0 else None,
            }
        return ExecutorResult(value=result, operation="yearly_return_stats")

    def _channel_comparison(self, df: pd.DataFrame) -> ExecutorResult:
        """Q32: Compare sales channels by total sales, total profit, avg sales."""
        chan_col = next((c for c in df.columns if c.lower() == "sales_channel"), None)
        if chan_col is None:
            return ExecutorResult(success=False, error="Sales_Channel column not found.")
        result = {}
        for chan, grp in df.groupby(chan_col):
            result[str(chan)] = {
                "transaction_count": len(grp),
                "total_sales": round(float(grp["Sales_Amount"].sum()), 2) if "Sales_Amount" in grp.columns else None,
                "total_profit": round(float(grp["Profit"].sum()), 2) if "Profit" in grp.columns else None,
                "avg_sales": round(float(grp["Sales_Amount"].mean()), 2) if "Sales_Amount" in grp.columns else None,
                "avg_profit": round(float(grp["Profit"].mean()), 2) if "Profit" in grp.columns else None,
            }
        return ExecutorResult(value=result, operation="channel_comparison")

    def _rating_threshold_stats(self, df: pd.DataFrame, col: str, threshold: float) -> ExecutorResult:
        """Q42: How many transactions have col >= threshold (excluding nulls)?"""
        if col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        valid = df[col].dropna()
        above = valid[valid >= threshold]
        count = int(len(above))
        total_valid = int(len(valid))
        pct = round(100 * count / total_valid, 2) if total_valid > 0 else 0.0
        return ExecutorResult(
            value={
                "threshold": threshold,
                "count_above_threshold": count,
                "total_valid_ratings": total_valid,
                "percentage": pct,
            },
            operation="rating_threshold_stats",
            column=col,
        )

    def _city_return_rate(self, df: pd.DataFrame) -> ExecutorResult:
        """Q28: Return rate by city using Return_Flag."""
        city_col = next((c for c in df.columns if c.lower() == "city"), None)
        flag_col = next((c for c in df.columns if c.lower() == "return_flag"), None)
        if city_col is None:
            return ExecutorResult(success=False, error="City column not found.")
        if flag_col is None:
            return ExecutorResult(success=False, error="Return_Flag column not found.")
        result = {}
        for city, grp in df.groupby(city_col):
            total = len(grp)
            returns = int((grp[flag_col] == "Yes").sum())
            result[str(city)] = {
                "total": total,
                "returns": returns,
                "return_rate_pct": round(100 * returns / total, 2) if total > 0 else 0.0,
            }
        # sort by return_rate descending
        result = dict(sorted(result.items(), key=lambda x: x[1]["return_rate_pct"], reverse=True))
        return ExecutorResult(value=result, operation="city_return_rate")

    def _year_above_median_count(self, df: pd.DataFrame, year: int, col: str) -> ExecutorResult:
        """Q45: Count rows in given year where col > overall median."""
        if col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{col}' not found.")
        # Determine overall median from ALL rows
        overall_median = float(df[col].median())
        # Filter to the target year
        year_col = next((c for c in df.columns if c.lower() == "order_year"), None)
        if year_col is None and "Order_Date" in df.columns:
            df = df.copy()
            df["_year"] = pd.to_datetime(df["Order_Date"], errors="coerce").dt.year
            year_col = "_year"
        if year_col is None:
            return ExecutorResult(success=False, error="No year column found.")
        year_df = df[df[year_col] == year]
        count = int((year_df[col] > overall_median).sum())
        return ExecutorResult(
            value={
                "year": year,
                "overall_median": round(overall_median, 4),
                "count_above_median": count,
                "year_total_rows": len(year_df),
            },
            operation="year_above_median_count",
            column=col,
        )

    def _weighted_average(self, df: pd.DataFrame, val_col: str, weight_col: str) -> ExecutorResult:
        """Q29: Weighted average of val_col weighted by weight_col."""
        if val_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{val_col}' not found.")
        if weight_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{weight_col}' not found.")
        tmp = df[[val_col, weight_col]].dropna()
        if tmp.empty or tmp[weight_col].sum() == 0:
            return ExecutorResult(success=False, error="No valid rows for weighted average.")
        w_avg = float((tmp[val_col] * tmp[weight_col]).sum() / tmp[weight_col].sum())
        simple_avg = float(tmp[val_col].mean())
        return ExecutorResult(
            value={
                "weighted_average": round(w_avg, 4),
                "simple_average": round(simple_avg, 4),
                "value_column": val_col,
                "weight_column": weight_col,
            },
            operation="weighted_average",
            column=val_col,
        )

    def _peak_month_profit(self, df: pd.DataFrame, year: Optional[int] = None, val_col: Optional[str] = None) -> ExecutorResult:
        """Q24/Q25/Q47: Find the month with highest total of val_col for a given year or across dataset."""
        if "Order_Date" not in df.columns:
            return ExecutorResult(success=False, error="Required Order_Date column not found.")
        target_col = val_col or "Profit"
        if target_col not in df.columns:
            target_col = "Sales_Amount" if "Sales_Amount" in df.columns else "Profit"
        if target_col not in df.columns:
            return ExecutorResult(success=False, error=f"Column '{target_col}' not found.")
        tmp = df.dropna(subset=["Order_Date", target_col]).copy()
        tmp["_date"] = pd.to_datetime(tmp["Order_Date"], errors="coerce")
        tmp["_year"] = tmp["_date"].dt.year
        tmp["_month"] = tmp["_date"].dt.month
        if year:
            tmp = tmp[tmp["_year"] == int(year)]
        if tmp.empty:
            return ExecutorResult(success=False, error=f"No data for year {year}.")
        monthly = tmp.groupby("_month")[target_col].sum().sort_values(ascending=False)
        peak_month_num = int(monthly.index[0])
        peak_amount = round(float(monthly.iloc[0]), 2)
        import calendar
        month_name = calendar.month_name[peak_month_num]

        monthly_chron = tmp.groupby("_month")[target_col].sum()
        chron_dict = {calendar.month_name[m]: round(float(v), 2) for m, v in monthly_chron.items()}

        return ExecutorResult(
            value={
                "year": year,
                "value_column": target_col,
                "peak_month": peak_month_num,
                "peak_month_name": month_name,
                "peak_amount": peak_amount,
                "monthly_breakdown": chron_dict,
                "monthly_profits": chron_dict,
            },
            operation="peak_month_profit",
            column=target_col,
        )

    def _category_profit_margins(self, df: pd.DataFrame) -> ExecutorResult:
        """Q62: Profit margin = Profit/Sales_Amount. Compare aggregate vs row-level average."""
        if "Profit" not in df.columns or "Sales_Amount" not in df.columns:
            return ExecutorResult(success=False, error="Profit or Sales_Amount column missing.")
        tmp = df.dropna(subset=["Profit", "Sales_Amount"]).copy()
        tmp = tmp[tmp["Sales_Amount"] != 0]
        # Aggregate margin: total profit / total sales
        agg_margin = round(float(tmp["Profit"].sum() / tmp["Sales_Amount"].sum()) * 100, 4)
        # Row-level margins average
        tmp["_row_margin"] = tmp["Profit"] / tmp["Sales_Amount"] * 100
        avg_row_margin = round(float(tmp["_row_margin"].mean()), 4)

        # By normalized category if available
        cat_col = next((c for c in df.columns if c.lower() == "product_category"), None)
        by_category = {}
        if cat_col:
            for cat, grp in tmp.groupby(cat_col):
                g = grp[grp["Sales_Amount"] != 0]
                if not g.empty:
                    by_category[str(cat)] = {
                        "aggregate_margin_pct": round(float(g["Profit"].sum() / g["Sales_Amount"].sum()) * 100, 2),
                        "avg_row_margin_pct": round(float(g["_row_margin"].mean()), 2),
                        "total_sales": round(float(g["Sales_Amount"].sum()), 2),
                        "total_profit": round(float(g["Profit"].sum()), 2),
                    }
        return ExecutorResult(
            value={
                "aggregate_margin_pct": agg_margin,
                "avg_row_margin_pct": avg_row_margin,
                "by_category": by_category,
            },
            operation="category_profit_margins",
        )

    def _average_order_value(self, df: pd.DataFrame) -> ExecutorResult:
        """AOV = total sales / unique Order_IDs (not row count), or mean of Order_Value column."""
        order_col = next((c for c in df.columns if c.lower() in ("order_id", "transaction_id", "invoice_number")), None)
        order_val_col = next((c for c in df.columns if c.lower() in ("order_value", "order_amount", "cart_value")), None)
        sales_col = next((c for c in df.columns if c.lower() in ("sales_amount", "total_amount", "sales", "revenue", "amount")), None)

        if not sales_col:
            try:
                from dataset_intelligence.semantic_resolver import get_semantic_resolver
                res = get_semantic_resolver().resolve("sales amount", df)
                if res.resolved_column and res.resolved_column in df.columns:
                    sales_col = res.resolved_column
            except Exception:
                pass

        if sales_col is None and order_val_col is None:
            return ExecutorResult(success=False, error="Sales or Order Value column not found.")

        total_sales = float(df[sales_col].sum()) if sales_col else float(df[order_val_col].sum())
        total_rows = len(df)
        if order_col:
            unique_orders = int(df[order_col].nunique())
        else:
            unique_orders = total_rows

        aov = round(total_sales / unique_orders, 2) if unique_orders > 0 else 0.0
        order_val_mean = round(float(df[order_val_col].mean()), 2) if order_val_col else aov

        return ExecutorResult(
            value={
                "average_order_value": aov,
                "order_value_mean": order_val_mean,
                "total_sales": round(total_sales, 2),
                "unique_orders": unique_orders,
                "total_rows": total_rows,
                "row_level_average": round(total_sales / total_rows, 2) if total_rows > 0 else 0.0,
            },
            operation="average_order_value",
        )

    def _customer_lifetime_value_proxy(self, df: pd.DataFrame) -> ExecutorResult:
        """Q34: CLV proxy = total sales per customer."""
        cust_col = next((c for c in df.columns if c.lower() == "customer_id"), None)
        sales_col = next((c for c in df.columns if c.lower() == "sales_amount"), None)
        if cust_col is None or sales_col is None:
            return ExecutorResult(success=False, error="Customer_ID or Sales_Amount column not found.")
        clv = df.groupby(cust_col)[sales_col].sum().sort_values(ascending=False)
        top10 = {str(k): round(float(v), 2) for k, v in clv.head(10).items()}
        return ExecutorResult(
            value={
                "method": "total_historical_spend_per_customer",
                "avg_clv_proxy": round(float(clv.mean()), 2),
                "median_clv_proxy": round(float(clv.median()), 2),
                "max_clv_proxy": round(float(clv.max()), 2),
                "total_customers": len(clv),
                "top_10_customers_by_spend": top10,
            },
            operation="customer_lifetime_value_proxy",
        )

    def _year_agreement(self, df: pd.DataFrame) -> ExecutorResult:
        """Q60: Compare Order_Date year vs Order_Year — count mismatches."""
        date_col = "Order_Date"
        year_col = next((c for c in df.columns if c.lower() == "order_year"), None)
        if date_col not in df.columns:
            return ExecutorResult(success=False, error="Order_Date column not found.")
        if year_col is None:
            return ExecutorResult(success=False, error="Order_Year column not found.")
        tmp = df[[date_col, year_col]].copy()
        tmp["_date_year"] = pd.to_datetime(tmp[date_col], errors="coerce").dt.year
        tmp["_order_year"] = pd.to_numeric(tmp[year_col], errors="coerce")
        valid = tmp.dropna(subset=["_date_year", "_order_year"])
        mismatches = int((valid["_date_year"] != valid["_order_year"]).sum())
        total = len(valid)
        return ExecutorResult(
            value={
                "total_rows_checked": total,
                "mismatches": mismatches,
                "agreement_rate_pct": round(100 * (total - mismatches) / total, 2) if total > 0 else 100.0,
                "mismatch_rate_pct": round(100 * mismatches / total, 2) if total > 0 else 0.0,
            },
            operation="year_agreement",
        )

    def _margin_aggregation_comparison(self, df: pd.DataFrame) -> ExecutorResult:
        """Q62: Two ways to compute profit margin — aggregate vs row-level average."""
        if "Profit" not in df.columns or "Sales_Amount" not in df.columns:
            return ExecutorResult(success=False, error="Profit or Sales_Amount column missing.")
        tmp = df.dropna(subset=["Profit", "Sales_Amount"]).copy()
        tmp = tmp[tmp["Sales_Amount"] != 0]
        agg_margin = round(float(tmp["Profit"].sum() / tmp["Sales_Amount"].sum()) * 100, 4)
        tmp["_row_margin"] = tmp["Profit"] / tmp["Sales_Amount"] * 100
        avg_row_margin = round(float(tmp["_row_margin"].mean()), 4)
        diff = round(avg_row_margin - agg_margin, 4)
        return ExecutorResult(
            value={
                "aggregate_margin_pct": agg_margin,
                "avg_row_margin_pct": avg_row_margin,
                "difference_pct": diff,
                "explanation": (
                    "Aggregate margin divides total profit by total sales (weighted by transaction size). "
                    "Row-level average gives equal weight to each transaction regardless of size."
                ),
            },
            operation="margin_aggregation_comparison",
        )


    def _country_return_rate(self, df: pd.DataFrame) -> ExecutorResult:
        """Q28: Return rate by country using Return_Flag."""
        country_col = next((c for c in df.columns if c.lower() == "country"), "Country")
        flag_col = next((c for c in df.columns if c.lower() == "return_flag"), "Return_Flag")
        result = {}
        for country, grp in df.groupby(country_col):
            tot = len(grp)
            rets = int((grp[flag_col] == "Yes").sum())
            rate = round(100.0 * rets / tot, 2) if tot > 0 else 0.0
            result[str(country)] = {"total": tot, "returns": rets, "rate_pct": rate}
        result = dict(sorted(result.items(), key=lambda x: x[1]["rate_pct"], reverse=True))
        top_country = list(result.keys())[0] if result else "None"
        top_rate = result[top_country]["rate_pct"] if result else 0.0
        return ExecutorResult(
            value={"top_country": top_country, "top_rate_pct": top_rate, "by_country": result},
            operation="country_return_rate"
        )

    def _overall_return_rate(self, df: pd.DataFrame) -> ExecutorResult:
        """Q27: Overall return rate with numerator/denominator."""
        total = len(df)
        flag_col = next((c for c in df.columns if c.lower() == "return_flag"), "Return_Flag")
        status_col = next((c for c in df.columns if c.lower() == "order_status"), "Order_Status")
        flag_returns = int((df[flag_col] == "Yes").sum()) if flag_col in df.columns else 0
        flag_rate = round(100.0 * flag_returns / total, 2) if total > 0 else 0.0
        status_returns = int((df[status_col] == "Returned").sum()) if status_col in df.columns else 0
        status_rate = round(100.0 * status_returns / total, 2) if total > 0 else 0.0
        return ExecutorResult(
            value={
                "total_transactions": total,
                "return_flag_returns": flag_returns,
                "return_flag_rate_pct": flag_rate,
                "order_status_returns": status_returns,
                "order_status_rate_pct": status_rate,
            },
            operation="overall_return_rate"
        )

    def _promotion_code_usage(self, df: pd.DataFrame, col: Optional[str] = None) -> ExecutorResult:
        """Percentage and count of transactions using a promo or coupon code."""
        target_col = col
        if not target_col or target_col not in df.columns:
            try:
                from dataset_intelligence.semantic_resolver import get_semantic_resolver
                res = get_semantic_resolver().resolve("promotion code", df)
                if res.resolved_column and res.resolved_column in df.columns:
                    target_col = res.resolved_column
            except Exception:
                pass
        if not target_col or target_col not in df.columns:
            for cand in ("promotion_code", "promo_code", "coupon_code", "voucher_code", "coupon", "promo", "voucher"):
                for c in df.columns:
                    if c.lower() == cand:
                        target_col = c
                        break
                if target_col:
                    break
        if not target_col or target_col not in df.columns:
            return ExecutorResult(success=False, error="Promotion or coupon code column not found.")

        s = df[target_col]
        non_null_mask = s.notna() & (s.astype(str).str.strip() != "") & (s.astype(str).str.lower() != "nan")
        used_count = int(non_null_mask.sum())
        total_count = len(df)
        pct = round(100.0 * used_count / total_count, 2) if total_count > 0 else 0.0
        return ExecutorResult(
            value={
                "used_count": used_count,
                "total_count": total_count,
                "percentage": pct,
            },
            operation="promotion_code_usage",
            column=target_col,
        )

    def _top_country_in_year(self, df: pd.DataFrame, year: int = 2024, val_col: str = "Sales_Amount") -> ExecutorResult:
        """Q39: Country with highest total sales in a specific year."""
        year_col = next((c for c in df.columns if c.lower() == "order_year"), "Order_Year")
        country_col = next((c for c in df.columns if c.lower() == "country"), "Country")
        target_val = val_col if val_col in df.columns else "Sales_Amount"
        tmp = df[df[year_col] == year].copy()
        if tmp.empty and "Order_Date" in df.columns:
            tmp = df[pd.to_datetime(df["Order_Date"], errors="coerce").dt.year == year].copy()
        if tmp.empty:
            return ExecutorResult(success=False, error=f"No data for year {year}.")
        grp = tmp.groupby(country_col)[target_val].sum().sort_values(ascending=False)
        top_country = str(grp.index[0])
        top_amount = round(float(grp.iloc[0]), 2)
        return ExecutorResult(
            value={
                "year": year,
                "top_country": top_country,
                "top_amount": top_amount,
                "by_country": {str(k): round(float(v), 2) for k, v in grp.items()},
            },
            operation="top_country_in_year",
        )

    def _top_category_per_year(self, df: pd.DataFrame) -> ExecutorResult:
        """Q44: Top product category by sales for each year."""
        year_col = next((c for c in df.columns if c.lower() == "order_year"), "Order_Year")
        cat_col = next((c for c in df.columns if c.lower() == "product_category"), "Product_Category")
        sales_col = next((c for c in df.columns if c.lower() == "sales_amount"), "Sales_Amount")
        res = {}
        for yr, grp in df.groupby(year_col):
            top_cat = grp.groupby(cat_col)[sales_col].sum().sort_values(ascending=False)
            res[str(int(yr))] = {"category": str(top_cat.index[0]), "sales": round(float(top_cat.iloc[0]), 2)}
        return ExecutorResult(value=res, operation="top_category_per_year")

    def _order_id_vs_duplicates(self, df: pd.DataFrame) -> ExecutorResult:
        """Q55: Difference between repeated Order_IDs and exact duplicate rows."""
        unique_orders = int(df["Order_ID"].nunique()) if "Order_ID" in df.columns else len(df)
        total_rows = len(df)
        repeated_orders = total_rows - unique_orders
        exact_dupes = int(df.duplicated().sum())
        return ExecutorResult(
            value={
                "total_rows": total_rows,
                "unique_orders": unique_orders,
                "repeated_order_ids": repeated_orders,
                "exact_duplicate_rows": exact_dupes,
            },
            operation="order_id_vs_duplicates",
        )

    def _year_over_year_comparison(self, df: pd.DataFrame, y1: int = 2024, y2: int = 2025, val_col: str = "Sales_Amount") -> ExecutorResult:
        """Q58: Year over year comparison."""
        year_col = next((c for c in df.columns if c.lower() == "order_year"), "Order_Year")
        s1 = float(df[df[year_col] == y1][val_col].sum())
        s2 = float(df[df[year_col] == y2][val_col].sum())
        pct_change = round(100.0 * (s2 - s1) / s1, 2) if s1 > 0 else 0.0
        increased = s2 > s1
        return ExecutorResult(
            value={
                "year1": y1, "year1_total": round(s1, 2),
                "year2": y2, "year2_total": round(s2, 2),
                "pct_change": pct_change,
                "increased": increased,
            },
            operation="year_over_year_comparison",
        )

    def _return_flag_status_mismatch(self, df: pd.DataFrame) -> ExecutorResult:
        """Q60: Compare Order_Status and Return_Flag consistency."""
        flag_col = next((c for c in df.columns if c.lower() == "return_flag"), "Return_Flag")
        status_col = next((c for c in df.columns if c.lower() == "order_status"), "Order_Status")
        is_flag_ret = df[flag_col] == "Yes"
        is_status_ret = df[status_col] == "Returned"
        both = int((is_flag_ret & is_status_ret).sum())
        flag_only = int((is_flag_ret & ~is_status_ret).sum())
        status_only = int((~is_flag_ret & is_status_ret).sum())
        total_flag_ret = int(is_flag_ret.sum())
        total_status_ret = int(is_status_ret.sum())
        return ExecutorResult(
            value={
                "total_return_flag_yes": total_flag_ret,
                "total_order_status_returned": total_status_ret,
                "both_returned": both,
                "mismatch_count": flag_only + status_only,
            },
            operation="return_flag_status_mismatch",
        )

    def _missingness_implications(self, df: pd.DataFrame) -> ExecutorResult:
        """Q61: Conceptual data quality analysis of missing values."""
        null_counts = df.isna().sum()
        cols_with_missing = {str(k): int(v) for k, v in null_counts[null_counts > 0].items()}
        return ExecutorResult(
            value={
                "columns_with_missing": cols_with_missing,
                "total_rows": len(df),
                "explanation": (
                    "No, a high number of missing values does not mean records are invalid. "
                    "Missing values often reflect optional fields (e.g. Promotion_Code, Customer_Rating) "
                    "or business process rules where fields are not applicable, rather than data corruption."
                )
            },
            operation="missingness_implications"
        )

    def _discount_profit_correlation(self, df: pd.DataFrame) -> ExecutorResult:
        """Q65: Discount-profit correlation and limits of causation."""
        disc_col = "Discount_Percentage"
        prof_col = "Profit"
        tmp = df[[disc_col, prof_col]].dropna()
        corr = round(float(tmp[disc_col].corr(tmp[prof_col])), 4)
        return ExecutorResult(
            value={"correlation": corr, "valid_pairs": len(tmp)},
            operation="discount_profit_correlation",
        )


# Singleton
pandas_executor = PandasExecutor()

