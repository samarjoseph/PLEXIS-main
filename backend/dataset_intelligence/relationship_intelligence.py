"""
Dataset Intelligence Engine — Stage 4: Relationship Intelligence

Discovers meaningful relationships between columns:
  - Pearson correlations between numeric columns
  - Grouping dimensions best suited for GROUP BY operations
  - Candidate KPI (metric) columns
  - Potential foreign keys
  - Time-metric pairings

All computation is deterministic Python — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from .models import ColumnCorrelation, ColumnRole, ColumnSchema, ColumnStats, RelationshipMap
from .utils import correlation_strength, get_working_sample

logger = logging.getLogger(__name__)


class RelationshipIntelligenceStage:
    """
    Stage 4 — Relationship Intelligence

    Builds a RelationshipMap from the dataset by detecting:
    - Strong correlations between numeric columns
    - The best dimension columns for grouping
    - KPI/metric column candidates
    - Foreign key patterns
    - Time-series pairings (which time columns best complement which metrics)
    """

    # Correlation threshold: only report correlations with |r| >= this value
    CORRELATION_THRESHOLD = 0.4

    # Maximum number of correlations to report (avoid overwhelming output)
    MAX_CORRELATIONS = 15

    def analyze(self, df: pd.DataFrame, schemas: List[ColumnSchema], column_stats: Dict[str, ColumnStats]) -> RelationshipMap:
        """
        Analyze relationships between columns.

        Args:
            df: The full DataFrame
            schemas: Stage 1 column schemas
            column_stats: Stage 2 column statistics

        Returns:
            A RelationshipMap describing all discovered relationships.
        """
        sample = get_working_sample(df)
        logger.info(f"RelationshipIntelligenceStage: analyzing relationships in {len(df.columns)} columns")

        schema_map: Dict[str, ColumnSchema] = {s.name: s for s in schemas}

        correlations = self._compute_correlations(sample, schemas)
        grouping_dims = self._find_grouping_dimensions(schemas, column_stats)
        metric_cols = self._find_metric_columns(schemas)
        fk_candidates = self._find_foreign_key_candidates(schemas)
        target_candidates = self._find_target_candidates(schemas, column_stats)
        time_metrics = self._build_time_metric_map(schemas)

        return RelationshipMap(
            correlations=correlations,
            grouping_dimensions=grouping_dims,
            metric_columns=metric_cols,
            foreign_key_candidates=fk_candidates,
            target_candidates=target_candidates,
            time_metrics=time_metrics,
        )

    def _compute_correlations(self, df: pd.DataFrame, schemas: List[ColumnSchema]) -> List[ColumnCorrelation]:
        """Compute Pearson correlations between all numeric column pairs."""
        numeric_cols = [
            s.name for s in schemas
            if s.dtype_category in ("integer", "float")
            and s.role not in (ColumnRole.IDENTIFIER,)
            and not s.is_constant
            and s.name in df.columns
        ]

        if len(numeric_cols) < 2:
            return []

        try:
            corr_matrix = df[numeric_cols].corr(method='pearson', numeric_only=True)
        except Exception as e:
            logger.warning(f"Correlation computation failed: {e}")
            return []

        correlations: List[ColumnCorrelation] = []
        seen = set()

        for i, col_a in enumerate(numeric_cols):
            for col_b in numeric_cols[i + 1:]:
                pair_key = tuple(sorted([col_a, col_b]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                try:
                    r = float(corr_matrix.loc[col_a, col_b])
                    if abs(r) >= self.CORRELATION_THRESHOLD and r == r:  # NaN check
                        strength, direction = correlation_strength(r)
                        correlations.append(ColumnCorrelation(
                            col_a=col_a,
                            col_b=col_b,
                            pearson_r=round(r, 4),
                            strength=strength,
                            direction=direction,
                        ))
                except Exception:
                    continue

        # Sort by absolute correlation strength descending
        correlations.sort(key=lambda c: abs(c.pearson_r), reverse=True)
        return correlations[:self.MAX_CORRELATIONS]

    def _find_grouping_dimensions(self, schemas: List[ColumnSchema], column_stats: Dict[str, ColumnStats]) -> List[str]:
        """
        Identify the best columns for GROUP BY operations.
        Ideal dimensions have low-to-moderate cardinality (2–50 unique values)
        and are categorical in nature.
        """
        good_dims = []
        for s in schemas:
            if s.role not in (ColumnRole.DIMENSION, ColumnRole.GEOGRAPHIC, ColumnRole.BOOLEAN_FLAG):
                continue
            if s.is_constant:
                continue
            stats = column_stats.get(s.name)
            if stats and stats.categorical:
                cardinality = stats.categorical.cardinality
                if 2 <= cardinality <= 100:
                    good_dims.append(s.name)
        return good_dims

    def _find_metric_columns(self, schemas: List[ColumnSchema]) -> List[str]:
        """Find all columns that can serve as KPIs or aggregation targets."""
        return [
            s.name for s in schemas
            if s.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.ACADEMIC, ColumnRole.HEALTHCARE)
            and not s.is_constant
        ]

    def _find_foreign_key_candidates(self, schemas: List[ColumnSchema]) -> List[str]:
        """
        Find columns that look like foreign keys: high uniqueness + ID-like name
        but with some repetition (so not the primary key).
        """
        fk_candidates = []
        for s in schemas:
            if s.role == ColumnRole.IDENTIFIER and 30 < s.unique_pct < 95:
                fk_candidates.append(s.name)
        return fk_candidates

    def _find_target_candidates(self, schemas: List[ColumnSchema], column_stats: Dict[str, ColumnStats]) -> List[str]:
        """
        Identify columns that are good ML target variable candidates.
        Heuristic: numeric columns that are not identifiers and have reasonable variance.
        """
        candidates = []
        for s in schemas:
            if s.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL) and not s.is_constant:
                stats = column_stats.get(s.name)
                if stats and stats.numeric and stats.numeric.std and stats.numeric.std > 0:
                    candidates.append(s.name)
        return candidates[:5]  # Limit to top 5

    def _build_time_metric_map(self, schemas: List[ColumnSchema]) -> Dict[str, List[str]]:
        """
        Build a mapping of time columns to the metric columns they can be paired with
        for time-series analysis.
        """
        time_cols = [s.name for s in schemas if s.role == ColumnRole.TIME]
        metric_cols = [
            s.name for s in schemas
            if s.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.ACADEMIC, ColumnRole.HEALTHCARE)
        ]

        if not time_cols or not metric_cols:
            return {}

        return {tc: metric_cols for tc in time_cols}


relationship_intelligence_stage = RelationshipIntelligenceStage()
