"""
Dataset Intelligence Engine — Stage 9: Insight Engine

Generates prioritized, human-interpretable insights from the deterministic
findings of Stages 1–7.

This stage does NOT just report statistics.
It interprets what the statistics mean for the analyst.

Each insight has:
  - A title (headline)
  - A description (explanation)
  - A severity (critical, high, medium, low, positive)
  - A category (quality, statistical, relationship, schema)
  - Evidence (supporting numbers)
  - A recommendation (actionable next step)
  - An importance score (for ranking)

All insight generation is deterministic — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .models import (
    CapabilitySet, ColumnRole, ColumnSchema, ColumnStats,
    DataInsight, DomainResult, InsightSeverity,
    QualityReport, RelationshipMap, SemanticMap
)

logger = logging.getLogger(__name__)


class InsightEngine:
    """
    Stage 9 — Insight Engine

    Transforms raw statistical findings into presentation-style insights.
    Insights are prioritized by importance_score to avoid overwhelming the user.

    Categories:
      - 'schema':       Observations about column structure
      - 'quality':      Data quality issues (derived from Stage 3)
      - 'statistical':  Findings from Stage 2 statistics
      - 'relationship': Correlation/grouping findings from Stage 4
      - 'capability':   What analyses the dataset enables/lacks
    """

    MAX_INSIGHTS = 12  # Never surface more than this many insights

    def generate(
        self,
        schemas: List[ColumnSchema],
        column_stats: Dict[str, ColumnStats],
        quality: QualityReport,
        relationships: RelationshipMap,
        semantics: SemanticMap,
        domain: DomainResult,
        capabilities: CapabilitySet,
    ) -> List[DataInsight]:
        """
        Generate all insights and return them sorted by importance.
        """
        logger.info("InsightEngine: generating insights")
        insights: List[DataInsight] = []

        insights.extend(self._schema_insights(schemas, semantics))
        insights.extend(self._statistical_insights(schemas, column_stats))
        insights.extend(self._quality_insights(quality))
        insights.extend(self._relationship_insights(relationships))
        insights.extend(self._capability_insights(capabilities, semantics))

        # Sort by importance, take top N
        insights.sort(key=lambda x: x.importance_score, reverse=True)
        top = insights[:self.MAX_INSIGHTS]

        logger.info(f"InsightEngine: surfacing {len(top)} insights from {len(insights)} total")
        return top

    # -----------------------------------------------------------------------
    # Schema Insights
    # -----------------------------------------------------------------------

    def _schema_insights(self, schemas: List[ColumnSchema], semantics: SemanticMap) -> List[DataInsight]:
        insights = []
        metrics = semantics.metrics
        dimensions = semantics.dimensions
        time_cols = semantics.time_columns
        identifiers = semantics.identifiers

        # Dataset structure summary (always positive)
        insights.append(DataInsight(
            title=f"Dataset has {len(metrics)} metric(s), {len(dimensions)} dimension(s)",
            description=(
                f"Found {len(metrics)} quantitative metric column(s) ({', '.join(metrics[:3])}{'...' if len(metrics) > 3 else ''}) "
                f"and {len(dimensions)} categorical dimension(s) ({', '.join(dimensions[:3])}{'...' if len(dimensions) > 3 else ''})."
            ),
            severity=InsightSeverity.POSITIVE,
            category="schema",
            affected_columns=metrics + dimensions,
            evidence={"metric_count": len(metrics), "dimension_count": len(dimensions)},
            importance_score=7.0,
        ))

        # No metrics found — critical for analysis
        if not metrics:
            insights.append(DataInsight(
                title="No quantitative metrics detected",
                description="The dataset has no numeric columns that can serve as metrics. Aggregation, ranking, and trend analysis will not be possible.",
                severity=InsightSeverity.CRITICAL,
                category="schema",
                affected_columns=[],
                recommendation="Add numeric columns (e.g., Revenue, Score, Count) to enable quantitative analysis.",
                importance_score=10.0,
            ))

        # No dimensions — grouping impossible
        if not dimensions:
            insights.append(DataInsight(
                title="No categorical dimensions detected",
                description="The dataset lacks categorical columns for grouping. Comparison and segmentation analyses will be limited.",
                severity=InsightSeverity.HIGH,
                category="schema",
                affected_columns=[],
                recommendation="Add categorical columns (e.g., Region, Category, Status) to enable group-by analysis.",
                importance_score=6.0,
            ))

        # Time coverage
        if time_cols:
            insights.append(DataInsight(
                title=f"Time dimension available for trend analysis",
                description=f"Column '{time_cols[0]}' enables time-series analysis, trend tracking, and period-over-period comparisons.",
                severity=InsightSeverity.POSITIVE,
                category="schema",
                affected_columns=time_cols,
                importance_score=6.5,
            ))

        # Constant columns (usually wasted schema)
        constant_cols = [s.name for s in schemas if s.is_constant]
        if constant_cols:
            insights.append(DataInsight(
                title=f"{len(constant_cols)} column(s) have only one unique value",
                description=f"Column(s) {constant_cols} are constant \u2014 they add no analytical value and can be removed.",
                severity=InsightSeverity.HIGH,
                category="schema",
                affected_columns=constant_cols,
                recommendation="Remove constant columns to clean up the dataset.",
                importance_score=4.5,
            ))

        return insights

    # -----------------------------------------------------------------------
    # Statistical Insights
    # -----------------------------------------------------------------------

    def _statistical_insights(self, schemas: List[ColumnSchema], column_stats: Dict[str, ColumnStats]) -> List[DataInsight]:
        insights = []

        for schema in schemas:
            stats = column_stats.get(schema.name)
            if not stats:
                continue

            # Numeric insights
            if stats.numeric:
                ns = stats.numeric

                # Skewness
                if ns.skewness and abs(ns.skewness) > 1.0:
                    direction = "right" if ns.skewness > 0 else "left"
                    insights.append(DataInsight(
                        title=f"'{schema.name}' is {ns.skewness_label}",
                        description=(
                            f"'{schema.name}' has a skewness of {ns.skewness:.2f}, indicating a {direction}-skewed distribution. "
                            f"The mean ({ns.mean:.2f}) may not accurately represent the typical value. "
                            f"The median ({ns.median:.2f}) is more representative."
                        ),
                        severity=InsightSeverity.MEDIUM,
                        category="statistical",
                        affected_columns=[schema.name],
                        evidence={"skewness": ns.skewness, "mean": ns.mean, "median": ns.median},
                        recommendation=f"Consider using median instead of mean when summarizing '{schema.name}'.",
                        importance_score=4.0,
                    ))

                # High outlier count
                if ns.outlier_pct and ns.outlier_pct > 10:
                    insights.append(DataInsight(
                        title=f"'{schema.name}' has significant outliers ({ns.outlier_pct:.1f}%)",
                        description=(
                            f"'{schema.name}' has {ns.outlier_count} outliers ({ns.outlier_pct:.1f}% of non-null values). "
                            f"These extreme values may distort aggregate calculations and visualizations."
                        ),
                        severity=InsightSeverity.HIGH if ns.outlier_pct > 20 else InsightSeverity.MEDIUM,
                        category="statistical",
                        affected_columns=[schema.name],
                        evidence={"outlier_count": ns.outlier_count, "outlier_pct": ns.outlier_pct, "min": ns.min, "max": ns.max},
                        recommendation=f"Investigate outliers in '{schema.name}' before computing averages.",
                        importance_score=5.0 if ns.outlier_pct > 20 else 3.5,
                    ))

                # Negatives in unexpected columns
                if ns.negative_count and ns.negative_count > 0:
                    financial_keywords = ['revenue', 'price', 'sales', 'quantity', 'count', 'score']
                    if any(kw in schema.name.lower() for kw in financial_keywords):
                        insights.append(DataInsight(
                            title=f"'{schema.name}' contains {ns.negative_count} negative values",
                            description=f"'{schema.name}' has {ns.negative_count} negative value(s), which may indicate data entry errors or legitimate returns/adjustments.",
                            severity=InsightSeverity.MEDIUM,
                            category="statistical",
                            affected_columns=[schema.name],
                            evidence={"negative_count": ns.negative_count, "min": ns.min},
                            recommendation=f"Verify that negative values in '{schema.name}' are intentional.",
                            importance_score=3.0,
                        ))

                # Wide range (max/min ratio)
                if ns.min is not None and ns.max is not None and ns.min > 0:
                    ratio = ns.max / ns.min
                    if ratio > 1000:
                        insights.append(DataInsight(
                            title=f"'{schema.name}' spans a very wide value range",
                            description=f"'{schema.name}' ranges from {ns.min:,.2f} to {ns.max:,.2f} (ratio: {ratio:,.0f}x). Log scaling may improve readability in visualizations.",
                            severity=InsightSeverity.LOW,
                            category="statistical",
                            affected_columns=[schema.name],
                            evidence={"min": ns.min, "max": ns.max, "ratio": ratio},
                            recommendation="Consider log scale for charts involving this column.",
                            importance_score=2.0,
                        ))

            # Categorical insights
            if stats.categorical:
                cs = stats.categorical

                # Dominant category
                if cs.dominant_pct > 80:
                    insights.append(DataInsight(
                        title=f"'{schema.name}' is dominated by one value ({cs.dominant_pct:.0f}%)",
                        description=f"'{cs.dominant_value}' makes up {cs.dominant_pct:.1f}% of '{schema.name}'. This column may not be useful as a grouping dimension.",
                        severity=InsightSeverity.MEDIUM,
                        category="statistical",
                        affected_columns=[schema.name],
                        evidence={"dominant_value": cs.dominant_value, "dominant_pct": cs.dominant_pct},
                        importance_score=2.5,
                    ))

                # Perfect completeness
                if stats.null_pct == 0 and stats.total_count > 100:
                    insights.append(DataInsight(
                        title=f"'{schema.name}' has no missing values",
                        description=f"'{schema.name}' is 100% complete across all {stats.total_count:,} rows.",
                        severity=InsightSeverity.POSITIVE,
                        category="quality",
                        affected_columns=[schema.name],
                        importance_score=1.5,
                    ))

        return insights

    # -----------------------------------------------------------------------
    # Quality Insights
    # -----------------------------------------------------------------------

    def _quality_insights(self, quality: QualityReport) -> List[DataInsight]:
        insights = []

        if quality.overall_score >= 90:
            insights.append(DataInsight(
                title=f"Excellent data quality (score: {quality.overall_score:.0f}/100)",
                description="The dataset is clean, complete, and ready for analysis with minimal preparation needed.",
                severity=InsightSeverity.POSITIVE,
                category="quality",
                affected_columns=[],
                importance_score=6.0,
            ))
        elif quality.overall_score < 60:
            insights.append(DataInsight(
                title=f"Data quality requires attention (score: {quality.overall_score:.0f}/100)",
                description=f"The dataset has {quality.total_missing_pct:.1f}% missing data and {quality.duplicate_row_pct:.1f}% duplicate rows. These issues may impact analysis accuracy.",
                severity=InsightSeverity.HIGH,
                category="quality",
                affected_columns=quality.columns_with_issues,
                recommendation="Address data quality issues before running detailed analysis.",
                importance_score=7.0,
            ))

        if quality.duplicate_row_count > 0:
            insights.append(DataInsight(
                title=f"{quality.duplicate_row_count:,} duplicate rows detected ({quality.duplicate_row_pct:.1f}%)",
                description=f"The dataset contains {quality.duplicate_row_count:,} fully duplicate rows which could inflate aggregate results.",
                severity=InsightSeverity.HIGH if quality.duplicate_row_pct > 5 else InsightSeverity.MEDIUM,
                category="quality",
                affected_columns=[],
                recommendation="Remove duplicates with df.drop_duplicates() before analysis.",
                importance_score=5.0 if quality.duplicate_row_pct > 5 else 3.0,
            ))

        return insights

    # -----------------------------------------------------------------------
    # Relationship Insights
    # -----------------------------------------------------------------------

    def _relationship_insights(self, relationships: RelationshipMap) -> List[DataInsight]:
        insights = []

        # Strong correlations
        strong = [c for c in relationships.correlations if abs(c.pearson_r) >= 0.7]
        if strong:
            top = strong[0]
            insights.append(DataInsight(
                title=f"Strong {top.direction} correlation: '{top.col_a}' and '{top.col_b}'",
                description=f"'{top.col_a}' and '{top.col_b}' have a {top.strength} {top.direction} correlation (r = {top.pearson_r:.3f}). They tend to move together.",
                severity=InsightSeverity.MEDIUM,
                category="relationship",
                affected_columns=[top.col_a, top.col_b],
                evidence={"pearson_r": top.pearson_r, "strength": top.strength},
                importance_score=4.5,
            ))

        # Time-metric pairings
        if relationships.time_metrics:
            pairs = list(relationships.time_metrics.items())
            time_col, metric_cols = pairs[0]
            insights.append(DataInsight(
                title=f"Time-series analysis available: '{time_col}' \u00d7 {len(metric_cols)} metric(s)",
                description=f"'{time_col}' can be used to track trends in {', '.join(metric_cols[:3])}{'...' if len(metric_cols) > 3 else ''} over time.",
                severity=InsightSeverity.POSITIVE,
                category="relationship",
                affected_columns=[time_col] + metric_cols[:3],
                importance_score=5.5,
            ))

        return insights

    # -----------------------------------------------------------------------
    # Capability Insights
    # -----------------------------------------------------------------------

    def _capability_insights(self, capabilities: CapabilitySet, semantics: SemanticMap) -> List[DataInsight]:
        insights = []
        cap_list = capabilities.capabilities
        n_caps = len(cap_list)

        if n_caps >= 6:
            insights.append(DataInsight(
                title=f"High analytical potential: {n_caps} analysis types available",
                description=f"The dataset supports {n_caps} different analysis types including: {', '.join(c.value for c in cap_list[:5])}.",
                severity=InsightSeverity.POSITIVE,
                category="capability",
                affected_columns=[],
                importance_score=6.0,
            ))
        elif n_caps <= 2:
            insights.append(DataInsight(
                title=f"Limited analytical potential: only {n_caps} analysis type(s) supported",
                description="The dataset structure limits the types of analysis that can be performed. Adding numeric and categorical columns would significantly expand analytical capabilities.",
                severity=InsightSeverity.MEDIUM,
                category="capability",
                affected_columns=[],
                recommendation="Enrich the dataset with additional columns to unlock more analysis types.",
                importance_score=4.0,
            ))

        return insights


insight_engine = InsightEngine()
