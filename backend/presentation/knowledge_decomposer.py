"""
Presentation Layer — Knowledge Decomposer

Transforms a DatasetKnowledgeObject (DKO) into a KnowledgeBundle containing
12 typed, named Knowledge Modules.

Single Responsibility: DKO → KnowledgeBundle (12 source modules)
LLM calls: NONE — 100% deterministic
Rules:
  - Never modifies the DKO
  - Never throws (all errors caught, module marked as unavailable)
  - No overlapping data between modules (clear delineation per RFC-002 §9.1)
  - Statistics module owns: central tendency and spread
  - Distribution module owns: shape (skewness, kurtosis, distribution_type)
  - Column module owns: schema-level facts only (no embedded stats objects)

Pattern detection criteria (RFC-002 §9.3 audit fix):
  bimodal:         kurtosis < 2.0 AND std > 0.5 * mean AND unique_count > 10
  long_tail:       skewness > 2.0 OR (p95 > 10 * median AND median > 0)
  concentration:   categorical dominant_pct > 50%
  periodicity:     datetime column with repeating month_distribution peak
  gap:             datetime column with has_gaps = True
  anomaly_cluster: numeric column with outlier_pct > 5.0
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from dataset_intelligence.models_v2 import DatasetKnowledgeObject, ColumnIntelligence
from dataset_intelligence.models import (
    ColumnRole, ColumnSemanticType, InsightSeverity, NumericStats,
    CategoricalStats, DatetimeStats
)
from .domain.contracts import (
    KnowledgeBundle, KnowledgeModule, ModuleID, PII_SEMANTIC_TYPES
)

logger = logging.getLogger(__name__)

# Richness threshold — modules below this are not rendered in the UI
RICHNESS_THRESHOLD = 20.0

# Prompt versions for each module (increment when system prompt changes)
MODULE_PROMPT_VERSIONS: Dict[str, int] = {
    ModuleID.QUALITY:        1,
    ModuleID.STATISTICS:     1,
    ModuleID.COLUMNS:        1,
    ModuleID.RELATIONSHIPS:  1,
    ModuleID.PATTERNS:       1,
    ModuleID.RARE:           1,
    ModuleID.DISTRIBUTION:   1,
    ModuleID.INSIGHTS:       1,
    ModuleID.VIZ:            1,
    ModuleID.SEMANTIC:       1,
    ModuleID.QUESTIONS:      1,
}


class KnowledgeDecomposer:
    """
    Decomposes a DatasetKnowledgeObject into 12 typed Knowledge Modules.

    Each module builder is isolated — a failure in one module does not
    affect the others. Failed modules are marked is_available=False.

    The executive module (13th) is NOT built here — it is the responsibility
    of SemanticImportanceRanker.
    """

    def decompose(self, dko: DatasetKnowledgeObject, dataset_id: str) -> KnowledgeBundle:
        """
        Main entry point. Builds all 12 source modules from the DKO.

        Args:
            dko: The immutable DatasetKnowledgeObject from the DIE.
            dataset_id: The UUID assigned to this upload (for registry keying).

        Returns:
            KnowledgeBundle with all 12 source modules populated.
        """
        logger.info(
            f"KnowledgeDecomposer: decomposing '{dko.dataset_name}' "
            f"({dko.row_count} rows, {dko.column_count} cols)"
        )

        return KnowledgeBundle(
            dataset_id=dataset_id,
            fingerprint=dko.fingerprint,
            dataset_name=dko.dataset_name,
            quality=self._build_quality_module(dko),
            statistics=self._build_statistics_module(dko),
            columns=self._build_columns_module(dko),
            relationships=self._build_relationships_module(dko),
            patterns=self._build_patterns_module(dko),
            rare=self._build_rare_module(dko),
            distribution=self._build_distribution_module(dko),
            insights=self._build_insights_module(dko),
            viz=self._build_viz_module(dko),
            semantic=self._build_semantic_module(dko),
            questions=self._build_questions_module(dko),
        )

    # -------------------------------------------------------------------------
    # Module Builders — 12 source modules
    # -------------------------------------------------------------------------

    def _build_quality_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Data Quality Report — owns quality scores and issue list."""
        try:
            qr = dko.quality_report
            if not qr:
                return self._unavailable(ModuleID.QUALITY, "Data Quality", "shield-check",
                                        "No quality report available.")

            column_health = {}
            for col_name, col in dko.columns.items():
                has_issues = col.null_pct > 0 or col.is_constant
                issue_types = []
                if col.null_pct > 0:
                    issue_types.append("missing_values")
                if col.is_constant:
                    issue_types.append("constant_column")
                column_health[col_name] = {
                    "null_pct": round(col.null_pct, 2),
                    "has_issues": has_issues,
                    "issue_types": issue_types,
                }

            issues_data = []
            for issue in qr.issues:
                issues_data.append({
                    "type": issue.issue_type.value if hasattr(issue.issue_type, 'value') else str(issue.issue_type),
                    "severity": issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity),
                    "affected_columns": issue.affected_columns,
                    "description": issue.description,
                    "recommendation": issue.recommendation,
                    "impact_score": round(issue.impact_score, 2),
                })

            readiness_label = qr.analysis_readiness
            fact_count = 4 + len(issues_data) + len(column_health)
            richness = min(100.0, 30.0 + qr.overall_score * 0.5 + len(issues_data) * 5.0)

            critical_count = sum(1 for i in qr.issues if hasattr(i.severity, 'value') and i.severity.value == "critical")

            if qr.overall_score >= 90:
                preview = f"Score {qr.overall_score:.0f}/100 — excellent quality, ready for analysis."
            elif qr.overall_score >= 70:
                preview = f"Score {qr.overall_score:.0f}/100 — {len(issues_data)} issues detected, review recommended."
            else:
                preview = f"Score {qr.overall_score:.0f}/100 — {critical_count} critical issues require attention."

            data = {
                "module_id": ModuleID.QUALITY,
                "overall_score": round(qr.overall_score, 1),
                "completeness_score": round(qr.completeness_score, 1),
                "consistency_score": round(qr.consistency_score, 1),
                "uniqueness_score": round(qr.uniqueness_score, 1),
                "readiness": readiness_label,
                "summary": preview,
                "duplicate_rows": {
                    "count": qr.duplicate_row_count,
                    "pct": round(qr.duplicate_row_pct, 2),
                },
                "missing_cells": {
                    "count": qr.total_missing_cells,
                    "pct": round(qr.total_missing_pct, 2),
                },
                "issues": issues_data,
                "column_health": column_health,
            }

            return KnowledgeModule(
                module_id=ModuleID.QUALITY,
                display_name="Data Quality Report",
                icon="shield-check",
                richness_score=richness,
                fact_count=fact_count,
                is_available=True,
                data=data,
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.QUALITY],
            )

        except Exception as e:
            logger.warning(f"Failed to build quality module: {e}")
            return self._unavailable(ModuleID.QUALITY, "Data Quality", "shield-check", str(e))

    def _build_statistics_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """
        Module: Statistical Details — owns central tendency and spread.
        (NOT skewness/kurtosis — those belong to distribution module)
        """
        try:
            numeric_cols = [
                col for col in dko.columns.values()
                if col.numeric_stats is not None
            ]

            if not numeric_cols:
                return self._unavailable(ModuleID.STATISTICS, "Statistical Details", "chart-bar",
                                        "No numeric columns in dataset.")

            rows = []
            for col in numeric_cols:
                ns = col.numeric_stats
                rows.append({
                    "name": col.name,
                    "min": self._safe_round(ns.min),
                    "max": self._safe_round(ns.max),
                    "mean": self._safe_round(ns.mean),
                    "median": self._safe_round(ns.median),
                    "mode": self._safe_round(ns.mode),
                    "std": self._safe_round(ns.std),
                    "variance": self._safe_round(ns.variance),
                    "q1": self._safe_round(ns.q1),
                    "q3": self._safe_round(ns.q3),
                    "iqr": self._safe_round(ns.iqr),
                    "p5": self._safe_round(ns.p5),
                    "p95": self._safe_round(ns.p95),
                    "range": self._safe_round(ns.range),
                    "zero_count": ns.zero_count,
                    "negative_count": ns.negative_count,
                    "outlier_count": ns.outlier_count,
                    "outlier_pct": round(ns.outlier_pct, 2),
                    # Shape reference only — full shape data is in distribution module
                    "shape": ns.skewness_label,
                    "distribution_ref": ModuleID.DISTRIBUTION,
                    "is_primary_metric": col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL),
                })

            richness = min(100.0, 40.0 + len(rows) * 3.0)
            preview = f"{len(rows)} numeric column(s) profiled — click to view full statistics table."

            return KnowledgeModule(
                module_id=ModuleID.STATISTICS,
                display_name="Statistical Details",
                icon="chart-bar",
                richness_score=richness,
                fact_count=len(rows) * 10,
                is_available=True,
                data={"module_id": ModuleID.STATISTICS, "numeric_columns": rows},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.STATISTICS],
            )

        except Exception as e:
            logger.warning(f"Failed to build statistics module: {e}")
            return self._unavailable(ModuleID.STATISTICS, "Statistical Details", "chart-bar", str(e))

    def _build_columns_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """
        Module: Column Intelligence — owns schema-level facts only.
        Does NOT embed stats objects inline (audit fix for payload size).
        References statistics and distribution modules for numeric data.
        """
        try:
            if not dko.columns:
                return self._unavailable(ModuleID.COLUMNS, "Column Intelligence", "table-cells",
                                        "No columns found.")

            cols_data = []
            for col in dko.columns.values():
                cols_data.append({
                    "name": col.name,
                    "position": col.position,
                    "role": col.role.value if hasattr(col.role, 'value') else str(col.role),
                    "semantic_type": col.semantic_type.value if hasattr(col.semantic_type, 'value') else str(col.semantic_type),
                    "importance_score": round(col.metadata.importance, 3) if col.metadata else 0.0,
                    "null_pct": round(col.null_pct, 2),
                    "unique_count": col.unique_count,
                    "unique_pct": round(col.unique_pct, 2) if hasattr(col, 'unique_pct') else 0.0,
                    "is_constant": col.is_constant,
                    "is_unique": col.is_unique,
                    "is_nullable": col.is_nullable,
                    "is_primary_metric": col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL),
                    "is_primary_date": col.role == ColumnRole.TIME,
                    # Schema reference — do not embed full stats here
                    "stats_available": col.numeric_stats is not None or col.categorical_stats is not None or col.datetime_stats is not None,
                    "stats_module_ref": ModuleID.STATISTICS if col.numeric_stats else None,
                    "distribution_module_ref": ModuleID.DISTRIBUTION if col.numeric_stats else None,
                    "characteristics": col.characteristics[:5] if col.characteristics else [],
                })

            richness = min(100.0, 50.0 + len(cols_data) * 2.0)
            preview = f"{len(cols_data)} columns — roles, semantic types, and completeness profiled."

            return KnowledgeModule(
                module_id=ModuleID.COLUMNS,
                display_name="Column Intelligence",
                icon="table-cells",
                richness_score=richness,
                fact_count=len(cols_data) * 5,
                is_available=True,
                data={"module_id": ModuleID.COLUMNS, "columns": cols_data},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.COLUMNS],
            )

        except Exception as e:
            logger.warning(f"Failed to build columns module: {e}")
            return self._unavailable(ModuleID.COLUMNS, "Column Intelligence", "table-cells", str(e))

    def _build_relationships_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Relationships — correlations, groupings, FK candidates."""
        try:
            kg = dko.knowledge_graph
            correlations = []
            for corr in kg.correlations:
                correlations.append({
                    "col_a": corr.col_a,
                    "col_b": corr.col_b,
                    "pearson_r": round(corr.pearson_r, 4),
                    "strength": corr.strength,
                    "direction": corr.direction,
                    "interpretation": self._correlation_interpretation(corr.pearson_r, corr.col_a, corr.col_b),
                })

            groupings = []
            for g in kg.groupings:
                groupings.append({
                    "column": g.dimension,
                    "controls_metrics": g.metrics,
                    "grouping_power": round(g.metadata.importance, 3) if g.metadata else 0.5,
                })

            # FK candidates from quality report or inference
            fk_candidates = []
            for col_name, col in dko.columns.items():
                if col.role == ColumnRole.IDENTIFIER and col.is_unique:
                    fk_candidates.append(col_name)

            # Target candidates (high-importance metrics)
            target_candidates = [
                col.name for col in dko.columns.values()
                if col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL)
                and col.metadata.importance > 0.5
            ]

            # Time-metric pairs
            time_cols = [c.name for c in dko.columns.values() if c.role == ColumnRole.TIME]
            metric_cols = [c.name for c in dko.columns.values() if c.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL)]
            time_metric_pairs = [
                {"time_col": tc, "metric_cols": metric_cols}
                for tc in time_cols
            ] if time_cols and metric_cols else []

            total_relations = len(correlations) + len(groupings)
            if total_relations == 0:
                return self._unavailable(
                    ModuleID.RELATIONSHIPS, "Relationships", "share-nodes",
                    "No significant relationships detected."
                )

            richness = min(100.0, 20.0 + len(correlations) * 15.0 + len(groupings) * 10.0)
            preview = (
                f"{len(correlations)} correlation(s) found — "
                f"{'strong signal detected' if any(abs(c['pearson_r']) > 0.7 for c in correlations) else 'moderate relationships'}."
            )

            return KnowledgeModule(
                module_id=ModuleID.RELATIONSHIPS,
                display_name="Relationships",
                icon="share-nodes",
                richness_score=richness,
                fact_count=total_relations,
                is_available=True,
                data={
                    "module_id": ModuleID.RELATIONSHIPS,
                    "correlations": correlations,
                    "grouping_dimensions": groupings,
                    "foreign_key_candidates": fk_candidates,
                    "target_candidates": target_candidates[:5],
                    "time_metric_pairs": time_metric_pairs,
                },
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.RELATIONSHIPS],
            )

        except Exception as e:
            logger.warning(f"Failed to build relationships module: {e}")
            return self._unavailable(ModuleID.RELATIONSHIPS, "Relationships", "share-nodes", str(e))

    def _build_patterns_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """
        Module: Hidden Patterns — detected distribution patterns.

        Pattern detection criteria (RFC-002 audit §9.3 — deterministic):
          bimodal:         kurtosis < 2.0 AND std > 0.5 * mean AND unique_count > 10
          long_tail:       skewness > 2.0 OR (p95 > 10 * median AND median > 0)
          concentration:   categorical dominant_pct > 50%
          periodicity:     datetime with repeating month_distribution peak
          gap:             datetime with has_gaps = True
          anomaly_cluster: numeric outlier_pct > 5.0
        """
        try:
            patterns = []
            importance_score = 0.0

            for col in dko.columns.values():
                ns = col.numeric_stats
                if ns:
                    # bimodal detection
                    if (ns.kurtosis is not None and ns.kurtosis < 2.0
                            and ns.std is not None and ns.mean is not None
                            and ns.mean != 0 and ns.std > 0.5 * abs(ns.mean)
                            and col.unique_count > 10):
                        patterns.append({
                            "type": "bimodal",
                            "column": col.name,
                            "description": f"'{col.name}' may have a bimodal distribution (kurtosis={ns.kurtosis:.2f}), suggesting two distinct population groups.",
                            "evidence": {"kurtosis": ns.kurtosis, "std": ns.std, "mean": ns.mean},
                            "severity": "medium",
                            "importance_score": 70.0,
                        })
                        importance_score = max(importance_score, 70.0)

                    # long_tail detection
                    if ns.skewness is not None and ns.skewness > 2.0:
                        patterns.append({
                            "type": "long_tail",
                            "column": col.name,
                            "description": f"'{col.name}' has a heavy right tail (skewness={ns.skewness:.2f}), indicating a small number of extremely high values drive the distribution.",
                            "evidence": {"skewness": ns.skewness, "p95": ns.p95, "median": ns.median},
                            "severity": "medium",
                            "importance_score": 65.0,
                        })
                        importance_score = max(importance_score, 65.0)
                    elif (ns.p95 is not None and ns.median is not None
                          and ns.median > 0 and ns.p95 > 10 * ns.median):
                        patterns.append({
                            "type": "long_tail",
                            "column": col.name,
                            "description": f"'{col.name}' shows extreme concentration — P95 ({ns.p95:.1f}) is over 10x the median ({ns.median:.1f}).",
                            "evidence": {"p95": ns.p95, "median": ns.median},
                            "severity": "high",
                            "importance_score": 75.0,
                        })
                        importance_score = max(importance_score, 75.0)

                    # anomaly_cluster
                    if ns.outlier_pct > 5.0:
                        patterns.append({
                            "type": "anomaly_cluster",
                            "column": col.name,
                            "description": f"'{col.name}' has an unusually high outlier rate ({ns.outlier_pct:.1f}%) — likely contains systematic anomalies, not random noise.",
                            "evidence": {"outlier_pct": ns.outlier_pct, "outlier_count": ns.outlier_count},
                            "severity": "high",
                            "importance_score": 80.0,
                        })
                        importance_score = max(importance_score, 80.0)

                cs = col.categorical_stats
                if cs:
                    # concentration
                    if cs.dominant_pct > 50.0:
                        patterns.append({
                            "type": "concentration",
                            "column": col.name,
                            "description": f"'{col.name}' is heavily concentrated — '{cs.dominant_value}' accounts for {cs.dominant_pct:.1f}% of all values.",
                            "evidence": {"dominant_value": cs.dominant_value, "dominant_pct": cs.dominant_pct},
                            "severity": "medium",
                            "importance_score": 60.0,
                        })
                        importance_score = max(importance_score, 60.0)

                ds = col.datetime_stats
                if ds:
                    # gap
                    if ds.has_gaps:
                        patterns.append({
                            "type": "gap",
                            "column": col.name,
                            "description": f"'{col.name}' contains temporal gaps — missing time periods that could affect time-series analysis.",
                            "evidence": {"has_gaps": True, "granularity": ds.granularity},
                            "severity": "medium",
                            "importance_score": 65.0,
                        })
                        importance_score = max(importance_score, 65.0)

                    # periodicity
                    if ds.month_distribution:
                        vals = list(ds.month_distribution.values())
                        if len(vals) > 2 and vals:
                            max_month = max(vals)
                            avg_month = sum(vals) / len(vals)
                            if avg_month > 0 and max_month > 2.0 * avg_month:
                                patterns.append({
                                    "type": "periodicity",
                                    "column": col.name,
                                    "description": f"'{col.name}' shows seasonal concentration — one month accounts for {max_month / sum(vals) * 100:.0f}% of all records.",
                                    "evidence": {"month_distribution": ds.month_distribution},
                                    "severity": "low",
                                    "importance_score": 55.0,
                                })
                                importance_score = max(importance_score, 55.0)

            if not patterns:
                return self._unavailable(
                    ModuleID.PATTERNS, "Hidden Patterns", "magnifying-glass",
                    "No significant distribution patterns detected."
                )

            # Sort by importance descending
            patterns.sort(key=lambda p: p["importance_score"], reverse=True)
            richness = min(100.0, 20.0 + len(patterns) * 20.0)
            preview = f"{len(patterns)} pattern(s) detected — {patterns[0]['type']} in '{patterns[0]['column']}'."

            return KnowledgeModule(
                module_id=ModuleID.PATTERNS,
                display_name="Hidden Patterns",
                icon="magnifying-glass",
                richness_score=richness,
                fact_count=len(patterns),
                is_available=True,
                data={"module_id": ModuleID.PATTERNS, "patterns": patterns},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.PATTERNS],
            )

        except Exception as e:
            logger.warning(f"Failed to build patterns module: {e}")
            return self._unavailable(ModuleID.PATTERNS, "Hidden Patterns", "magnifying-glass", str(e))

    def _build_rare_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """
        Module: Rare Observations — unusual values, singletons, extreme outliers.
        PII-sensitive columns have their values REDACTED (audit fix C-5).
        """
        try:
            observations = []

            for col in dko.columns.values():
                is_pii = (
                    hasattr(col.semantic_type, 'value')
                    and col.semantic_type.value in PII_SEMANTIC_TYPES
                )

                cs = col.categorical_stats
                if cs and cs.rare_values:
                    for rv in cs.rare_values[:5]:
                        display_value = "[REDACTED]" if is_pii else rv
                        observations.append({
                            "type": "rare_value",
                            "column": col.name,
                            "value": display_value,
                            "frequency": 1,
                            "frequency_pct": round(1.0 / max(col.unique_count, 1) * 100, 4),
                            "description": f"Rare category in '{col.name}'" + (" (PII redacted)" if is_pii else f": '{display_value}'"),
                            "importance_score": 40.0,
                        })

                ns = col.numeric_stats
                if ns and ns.outlier_pct > 0:
                    observations.append({
                        "type": "extreme_outlier",
                        "column": col.name,
                        "value": f"~{ns.outlier_count} values beyond IQR fences",
                        "frequency": ns.outlier_count,
                        "frequency_pct": round(ns.outlier_pct, 2),
                        "description": f"'{col.name}' has {ns.outlier_pct:.1f}% outliers (IQR method). Range: {ns.min:.2f}–{ns.max:.2f}.",
                        "importance_score": min(90.0, 40.0 + ns.outlier_pct * 5),
                    })

                # Singletons from high-cardinality categoricals
                if cs and cs.is_high_cardinality and not is_pii:
                    # Top values that appear very rarely
                    for val, count in cs.top_values[-3:]:
                        if count == 1:
                            observations.append({
                                "type": "singleton",
                                "column": col.name,
                                "value": str(val),
                                "frequency": 1,
                                "frequency_pct": round(1.0 / max(col.unique_count, 1) * 100, 4),
                                "description": f"Singleton value '{val}' in '{col.name}' appears exactly once.",
                                "importance_score": 35.0,
                            })

            if not observations:
                return self._unavailable(
                    ModuleID.RARE, "Rare Observations", "eye",
                    "No rare values or outliers detected."
                )

            observations.sort(key=lambda o: o["importance_score"], reverse=True)
            richness = min(100.0, 15.0 + len(observations) * 10.0)
            preview = f"{len(observations)} rare value(s) or outlier cluster(s) found."

            return KnowledgeModule(
                module_id=ModuleID.RARE,
                display_name="Rare Observations",
                icon="eye",
                richness_score=richness,
                fact_count=len(observations),
                is_available=True,
                data={"module_id": ModuleID.RARE, "observations": observations},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.RARE],
            )

        except Exception as e:
            logger.warning(f"Failed to build rare module: {e}")
            return self._unavailable(ModuleID.RARE, "Rare Observations", "eye", str(e))

    def _build_distribution_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """
        Module: Distribution Intelligence — owns shape metrics.
        (skewness, kurtosis, distribution_type, tail analysis, histogram summary)
        Statistics module owns central tendency; this module owns shape.
        """
        try:
            numeric_cols = [
                col for col in dko.columns.values()
                if col.numeric_stats is not None
            ]

            if not numeric_cols:
                return self._unavailable(ModuleID.DISTRIBUTION, "Distribution Intelligence", "chart-pie",
                                        "No numeric columns in dataset.")

            distributions = []
            for col in numeric_cols:
                ns = col.numeric_stats
                distribution_type = self._classify_distribution(ns)

                distributions.append({
                    "column": col.name,
                    "distribution_type": distribution_type,
                    "skewness": self._safe_round(ns.skewness),
                    "skewness_label": ns.skewness_label,
                    "kurtosis": self._safe_round(ns.kurtosis),
                    "range": self._safe_round(ns.range),
                    "spread": self._classify_spread(ns),
                    "quartiles": {
                        "q1": self._safe_round(ns.q1),
                        "q3": self._safe_round(ns.q3),
                        "iqr": self._safe_round(ns.iqr),
                    },
                    "tail_analysis": {
                        "left_tail_pct": round(ns.outlier_pct / 2, 2) if ns.outlier_pct else 0.0,
                        "right_tail_pct": round(ns.outlier_pct / 2, 2) if ns.outlier_pct else 0.0,
                    },
                    # Central tendency ref — do not duplicate, points to statistics module
                    "central_tendency_ref": ModuleID.STATISTICS,
                })

            richness = min(100.0, 30.0 + len(distributions) * 5.0)
            skewed_count = sum(1 for d in distributions if d["distribution_type"] not in ("normal", "unknown"))
            preview = (
                f"{skewed_count}/{len(distributions)} columns have non-normal distributions — click to explore shapes."
                if skewed_count else
                f"{len(distributions)} numeric column(s) — distribution shapes profiled."
            )

            return KnowledgeModule(
                module_id=ModuleID.DISTRIBUTION,
                display_name="Distribution Intelligence",
                icon="chart-pie",
                richness_score=richness,
                fact_count=len(distributions) * 4,
                is_available=True,
                data={"module_id": ModuleID.DISTRIBUTION, "distributions": distributions},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.DISTRIBUTION],
            )

        except Exception as e:
            logger.warning(f"Failed to build distribution module: {e}")
            return self._unavailable(ModuleID.DISTRIBUTION, "Distribution Intelligence", "chart-pie", str(e))

    def _build_insights_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Interesting Facts — the DIE's pre-scored DataInsights."""
        try:
            insights = sorted(dko.insights, key=lambda i: i.importance_score, reverse=True)

            if not insights:
                return self._unavailable(ModuleID.INSIGHTS, "Interesting Facts", "light-bulb",
                                        "No insights generated.")

            insights_data = []
            for ins in insights:
                insights_data.append({
                    "title": ins.title,
                    "description": ins.description,
                    "severity": ins.severity.value if hasattr(ins.severity, 'value') else str(ins.severity),
                    "category": ins.category,
                    "affected_columns": ins.affected_columns,
                    "importance_score": round(ins.importance_score, 2),
                    "recommendation": ins.recommendation,
                })

            richness = min(100.0, 30.0 + len(insights) * 10.0)
            top = insights_data[0] if insights_data else None
            preview = f"{top['title']}" if top else f"{len(insights)} insight(s) discovered."

            return KnowledgeModule(
                module_id=ModuleID.INSIGHTS,
                display_name="Interesting Facts",
                icon="light-bulb",
                richness_score=richness,
                fact_count=len(insights),
                is_available=True,
                data={"module_id": ModuleID.INSIGHTS, "insights": insights_data},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.INSIGHTS],
            )

        except Exception as e:
            logger.warning(f"Failed to build insights module: {e}")
            return self._unavailable(ModuleID.INSIGHTS, "Interesting Facts", "light-bulb", str(e))

    def _build_viz_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Visualization Suggestions — chart recommendations from capabilities."""
        try:
            suggestions = []
            priority = 1

            for opp in dko.opportunities:
                chart_type = self._capability_to_chart(opp.name)
                if not chart_type:
                    continue

                x_axis, y_axis, group_by = self._infer_axes(opp, dko)
                suggestions.append({
                    "chart_type": chart_type,
                    "title": opp.description or opp.name,
                    "x_axis": x_axis,
                    "y_axis": y_axis,
                    "group_by": group_by,
                    "reason": f"Dataset supports {opp.name} analysis.",
                    "priority": priority,
                    "capability": opp.name,
                })
                priority += 1

            if not suggestions:
                return self._unavailable(ModuleID.VIZ, "Visualization Suggestions", "chart-bar-square",
                                        "No visualization capabilities detected.")

            richness = min(100.0, 40.0 + len(suggestions) * 8.0)
            preview = f"{len(suggestions)} chart recommendation(s) — {suggestions[0]['chart_type']} is the top suggestion."

            return KnowledgeModule(
                module_id=ModuleID.VIZ,
                display_name="Visualization Suggestions",
                icon="chart-bar-square",
                richness_score=richness,
                fact_count=len(suggestions),
                is_available=True,
                data={"module_id": ModuleID.VIZ, "suggestions": suggestions},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.VIZ],
            )

        except Exception as e:
            logger.warning(f"Failed to build viz module: {e}")
            return self._unavailable(ModuleID.VIZ, "Visualization Suggestions", "chart-bar-square", str(e))

    def _build_semantic_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Semantic Summary — domain classification and business context."""
        try:
            identity = dko.get_dataset_identity()
            domain_result = dko.domain

            metrics = [c.name for c in dko.get_primary_metrics()]
            dimensions = [c.name for c in dko.get_grouping_dimensions()]
            time_cols = [c.name for c in dko.get_time_dimensions()]
            identifiers = [c.name for c in dko.columns.values() if c.role == ColumnRole.IDENTIFIER]

            data = {
                "module_id": ModuleID.SEMANTIC,
                "domain": domain_result.domain.value if domain_result and hasattr(domain_result.domain, 'value') else str(domain_result.domain) if domain_result else "General Purpose",
                "domain_confidence": round(domain_result.confidence, 3) if domain_result else 0.0,
                "domain_evidence": domain_result.evidence[:3] if domain_result else [],
                "probable_purpose": identity.probable_purpose,
                "primary_entities": identity.primary_entities[:5],
                "business_concepts": identity.business_concepts[:5],
                "kpis": identity.kpis[:5],
                "column_roles": {
                    "metrics": metrics,
                    "dimensions": dimensions,
                    "time_columns": time_cols,
                    "identifiers": identifiers,
                },
                "strongest_groupings": identity.strongest_groupings[:5],
            }

            richness = 60.0  # semantic module is always rich if domain is detected
            if domain_result and domain_result.confidence > 0.5:
                richness = 80.0

            preview = (
                f"{data['domain']} domain detected ({domain_result.confidence:.0%} confidence) — "
                f"{len(metrics)} metric(s), {len(dimensions)} dimension(s)."
                if domain_result else
                f"General purpose dataset — {len(metrics)} metric(s), {len(dimensions)} dimension(s)."
            )

            return KnowledgeModule(
                module_id=ModuleID.SEMANTIC,
                display_name="Semantic Summary",
                icon="brain-circuit",
                richness_score=richness,
                fact_count=len(metrics) + len(dimensions) + len(time_cols),
                is_available=True,
                data=data,
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.SEMANTIC],
            )

        except Exception as e:
            logger.warning(f"Failed to build semantic module: {e}")
            return self._unavailable(ModuleID.SEMANTIC, "Semantic Summary", "brain-circuit", str(e))

    def _build_questions_module(self, dko: DatasetKnowledgeObject) -> KnowledgeModule:
        """Module: Predicted Questions — the most likely user questions."""
        try:
            questions = dko.predicted_questions

            if not questions:
                return self._unavailable(ModuleID.QUESTIONS, "Predicted Questions", "chat-bubble",
                                        "No predicted questions generated.")

            questions_data = []
            for q in questions:
                questions_data.append({
                    "question": q.question,
                    "category": q.category,
                    "confidence": round(q.confidence, 3),
                    "relevant_columns": q.relevant_columns,
                    "suggested_chart": q.suggested_chart,
                })

            richness = min(100.0, 40.0 + len(questions_data) * 8.0)
            preview = f"{len(questions_data)} predicted question(s) — click any to start analysis."

            return KnowledgeModule(
                module_id=ModuleID.QUESTIONS,
                display_name="Predicted Questions",
                icon="chat-bubble",
                richness_score=richness,
                fact_count=len(questions_data),
                is_available=True,
                data={"module_id": ModuleID.QUESTIONS, "questions": questions_data},
                preview=preview,
                prompt_version=MODULE_PROMPT_VERSIONS[ModuleID.QUESTIONS],
            )

        except Exception as e:
            logger.warning(f"Failed to build questions module: {e}")
            return self._unavailable(ModuleID.QUESTIONS, "Predicted Questions", "chat-bubble", str(e))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _unavailable(
        self, module_id: str, display_name: str, icon: str, reason: str
    ) -> KnowledgeModule:
        """Create a stub KnowledgeModule marked as unavailable."""
        return KnowledgeModule(
            module_id=module_id,
            display_name=display_name,
            icon=icon,
            richness_score=0.0,
            fact_count=0,
            is_available=False,
            data={"module_id": module_id, "unavailable_reason": reason},
            preview=f"Not available: {reason}",
            prompt_version=MODULE_PROMPT_VERSIONS.get(module_id, 1),
        )

    def _safe_round(self, value: Optional[float], decimals: int = 4) -> Optional[float]:
        if value is None:
            return None
        try:
            return round(float(value), decimals)
        except (TypeError, ValueError):
            return None

    def _classify_distribution(self, ns: NumericStats) -> str:
        if ns.skewness is None:
            return "unknown"
        if ns.skewness > 1.0:
            return "right_skewed"
        elif ns.skewness < -1.0:
            return "left_skewed"
        elif ns.kurtosis is not None and ns.kurtosis < 2.0 and ns.std and ns.mean and ns.std > 0.5 * abs(ns.mean):
            return "bimodal"
        elif abs(ns.skewness) <= 0.5:
            return "normal"
        else:
            return "uniform"

    def _classify_spread(self, ns: NumericStats) -> str:
        if ns.std is None or ns.mean is None or ns.mean == 0:
            return "unknown"
        cv = abs(ns.std / ns.mean)
        if cv < 0.2:
            return "tight"
        elif cv < 0.75:
            return "moderate"
        else:
            return "wide"

    def _correlation_interpretation(self, r: float, col_a: str, col_b: str) -> str:
        strength = abs(r)
        direction = "positively" if r > 0 else "negatively"
        if strength > 0.8:
            return f"As '{col_a}' increases, '{col_b}' {direction} follows very strongly."
        elif strength > 0.6:
            return f"'{col_a}' and '{col_b}' are strongly {direction} correlated."
        elif strength > 0.4:
            return f"Moderate {direction} relationship between '{col_a}' and '{col_b}'."
        else:
            return f"Weak {direction} relationship between '{col_a}' and '{col_b}'."

    def _capability_to_chart(self, capability: str) -> Optional[str]:
        mapping = {
            "ranking":      "bar",
            "aggregation":  "bar",
            "grouping":     "bar",
            "comparison":   "bar",
            "time_series":  "line",
            "trend":        "line",
            "forecasting":  "line",
            "correlation":  "scatter",
            "distribution": "histogram",
            "geographic":   "treemap",
            "cohort":       "heatmap",
            "segmentation": "scatter",
            "kpi_tracking": "bar",
        }
        return mapping.get(capability.lower())

    def _infer_axes(self, opportunity, dko: DatasetKnowledgeObject):
        """Infer chart axes from opportunity and DKO semantics."""
        metrics = [c.name for c in dko.get_primary_metrics()]
        dims = [c.name for c in dko.get_grouping_dimensions()]
        times = [c.name for c in dko.get_time_dimensions()]

        x_axis = dims[0] if dims else (times[0] if times else None)
        y_axis = metrics[0] if metrics else None
        group_by = dims[1] if len(dims) > 1 else None

        if opportunity.required_columns:
            cols = opportunity.required_columns
            if len(cols) >= 2:
                x_axis = cols[0]
                y_axis = cols[1]

        return x_axis, y_axis, group_by


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
knowledge_decomposer = KnowledgeDecomposer()
