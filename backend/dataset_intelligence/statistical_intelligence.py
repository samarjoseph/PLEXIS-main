"""
Dataset Intelligence Engine — Stage 2: Statistical Intelligence

Computes deep statistical profiles for every column.
All computation is deterministic Python/pandas/numpy — no LLM calls.

For large datasets (> 100,000 rows) it operates on a stratified sample
of 50,000 rows to maintain consistent latency.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .models import (
    CategoricalStats, ColumnStats, DatetimeStats, NumericStats, ColumnSchema
)
from .utils import (
    compute_entropy, detect_outliers_iqr, get_working_sample, infer_datetime_granularity,
    label_skewness, safe_float, safe_int
)

logger = logging.getLogger(__name__)


class StatisticalIntelligenceStage:
    """
    Stage 2 — Statistical Intelligence

    Produces a full ColumnStats object for every column by dispatching
    to the appropriate profiler based on column type.
    """

    def analyze(self, df: pd.DataFrame, schemas: List[ColumnSchema]) -> Dict[str, ColumnStats]:
        """
        Compute statistical profiles for all columns.

        Args:
            df: The full DataFrame (may be very large)
            schemas: The ColumnSchema list from Stage 1

        Returns:
            A dict mapping column_name → ColumnStats
        """
        sample = get_working_sample(df)
        logger.info(f"StatisticalIntelligenceStage: profiling {len(df.columns)} columns on {len(sample):,} rows")

        schema_map = {s.name: s for s in schemas}
        stats: Dict[str, ColumnStats] = {}

        for col_name in df.columns:
            col_name_str = str(col_name)
            try:
                schema = schema_map.get(col_name_str)
                dtype_category = schema.dtype_category if schema else "text"
                col_stats = self._profile_column(sample, col_name_str, dtype_category)
                stats[col_name_str] = col_stats
            except Exception as e:
                logger.warning(f"Failed to profile column '{col_name_str}': {e}")
                stats[col_name_str] = ColumnStats(
                    column_name=col_name_str,
                    column_type="unknown",
                    total_count=len(sample),
                )

        return stats

    def _profile_column(self, df: pd.DataFrame, col_name: str, dtype_category: str) -> ColumnStats:
        """Dispatch to the appropriate profiler for this column's type."""
        series = df[col_name]
        total = len(series)
        null_count = int(series.isna().sum())
        null_pct = round((null_count / total) * 100, 2) if total > 0 else 0.0
        distinct_count = int(series.nunique(dropna=True))
        duplicate_count = int(total - series.nunique(dropna=False) - null_count)

        base = dict(
            column_name=col_name,
            total_count=total,
            null_count=null_count,
            null_pct=null_pct,
            distinct_count=distinct_count,
            duplicate_count=max(0, duplicate_count),
        )

        if dtype_category in ("integer", "float"):
            return ColumnStats(**base, column_type="numeric", numeric=self._profile_numeric(series))
        elif dtype_category == "datetime":
            return ColumnStats(**base, column_type="datetime", datetime=self._profile_datetime(series))
        elif dtype_category == "boolean":
            return ColumnStats(**base, column_type="boolean")
        else:
            return ColumnStats(**base, column_type="categorical", categorical=self._profile_categorical(series))

    def _profile_numeric(self, series: pd.Series) -> NumericStats:
        """Compute full numeric statistics."""
        clean = series.dropna()
        if clean.empty:
            return NumericStats()

        try:
            q1 = safe_float(clean.quantile(0.25))
            q3 = safe_float(clean.quantile(0.75))
            iqr = round(q3 - q1, 6) if (q1 is not None and q3 is not None) else None
            outlier_count, outlier_pct = detect_outliers_iqr(series)
            skew = safe_float(clean.skew())

            return NumericStats(
                min=safe_float(clean.min()),
                max=safe_float(clean.max()),
                mean=safe_float(clean.mean()),
                median=safe_float(clean.median()),
                mode=safe_float(clean.mode().iloc[0]) if not clean.mode().empty else None,
                variance=safe_float(clean.var()),
                std=safe_float(clean.std()),
                q1=q1,
                q3=q3,
                iqr=iqr,
                p5=safe_float(clean.quantile(0.05)),
                p95=safe_float(clean.quantile(0.95)),
                range=safe_float(clean.max() - clean.min()),
                skewness=skew,
                kurtosis=safe_float(clean.kurtosis()),
                skewness_label=label_skewness(skew),
                zero_count=int((clean == 0).sum()),
                negative_count=int((clean < 0).sum()),
                positive_count=int((clean > 0).sum()),
                outlier_count=outlier_count,
                outlier_pct=outlier_pct,
            )
        except Exception as e:
            logger.warning(f"Numeric profile error: {e}")
            return NumericStats()

    def _profile_categorical(self, series: pd.Series) -> CategoricalStats:
        """Compute full categorical statistics."""
        clean = series.dropna().astype(str)
        if clean.empty:
            return CategoricalStats()

        try:
            value_counts = clean.value_counts()
            cardinality = int(series.nunique(dropna=True))
            total_non_null = len(clean)

            # Top 10 most frequent values
            top_values = [(str(k), int(v)) for k, v in value_counts.head(10).items()]

            # Rare values: appear in < 1% of rows
            threshold = max(1, int(total_non_null * 0.01))
            rare_values = [str(k) for k, v in value_counts.items() if v <= threshold]
            rare_values = rare_values[:20]  # Cap at 20

            # Dominant value
            dominant_value = str(value_counts.index[0]) if len(value_counts) > 0 else None
            dominant_pct = round((value_counts.iloc[0] / total_non_null) * 100, 2) if len(value_counts) > 0 and total_non_null > 0 else 0.0

            # Shannon entropy (diversity of categories)
            entropy = compute_entropy(series)

            # High cardinality flag: more than 50% of values are unique
            is_high_cardinality = (cardinality / total_non_null) > 0.5 if total_non_null > 0 else False

            return CategoricalStats(
                cardinality=cardinality,
                top_values=top_values,
                rare_values=rare_values,
                dominant_value=dominant_value,
                dominant_pct=dominant_pct,
                entropy=entropy,
                is_high_cardinality=is_high_cardinality,
            )
        except Exception as e:
            logger.warning(f"Categorical profile error: {e}")
            return CategoricalStats()

    def _profile_datetime(self, series: pd.Series) -> DatetimeStats:
        """Compute full datetime statistics."""
        clean = series.dropna()
        if clean.empty:
            return DatetimeStats()

        try:
            min_date = clean.min()
            max_date = clean.max()
            range_days = int((max_date - min_date).days) if pd.notna(min_date) and pd.notna(max_date) else None
            range_years = round(range_days / 365.25, 2) if range_days is not None else None

            coverage_pct = round((len(clean) / len(series)) * 100, 2)
            granularity = infer_datetime_granularity(clean)

            # Year distribution (top 15 years)
            year_dist = clean.dt.year.value_counts().sort_index().head(15).to_dict()
            year_dist = {str(k): int(v) for k, v in year_dist.items()}

            # Month distribution
            month_dist = clean.dt.month.value_counts().sort_index().to_dict()
            month_dist = {str(k): int(v) for k, v in month_dist.items()}

            # Detect gaps (basic: are all dates sequential?)
            has_gaps = False
            if granularity in ("daily", "monthly") and range_days is not None:
                expected_count = range_days if granularity == "daily" else range_days // 30
                has_gaps = len(clean) < expected_count * 0.8

            return DatetimeStats(
                min_date=min_date.isoformat() if pd.notna(min_date) else None,
                max_date=max_date.isoformat() if pd.notna(max_date) else None,
                range_days=range_days,
                range_years=range_years,
                granularity=granularity,
                coverage_pct=coverage_pct,
                year_distribution=year_dist,
                month_distribution=month_dist,
                has_gaps=has_gaps,
            )
        except Exception as e:
            logger.warning(f"Datetime profile error: {e}")
            return DatetimeStats()


statistical_intelligence_stage = StatisticalIntelligenceStage()
