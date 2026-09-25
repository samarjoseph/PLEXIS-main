"""
Dataset Intelligence Engine — Stage 7: Capability Detector

Determines which analytical operations the dataset can support.
This output is consumed by the Planner, Chart Engine, and Report Generator
to know what questions are answerable.

All capability detection is deterministic — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from .models import AnalysisCapability, CapabilitySet, ColumnRole, SemanticMap

logger = logging.getLogger(__name__)


class CapabilityDetector:
    """
    Stage 7 — Capability Detector

    For each AnalysisCapability, checks whether the dataset has the required
    column structure to support it, and records which columns enable it.

    Example:
      TIME_SERIES requires: at least one Time column + at least one Metric column
      GEOGRAPHIC requires: at least one Geographic column
      COMPARISON requires: at least one Dimension + at least one Metric
    """

    def detect(self, semantics: SemanticMap) -> CapabilitySet:
        """
        Detect which analysis types the dataset supports.

        Args:
            semantics: Stage 5 SemanticMap

        Returns:
            A CapabilitySet with enabled capabilities and their supporting columns.
        """
        metrics = semantics.metrics
        dimensions = semantics.dimensions
        time_cols = semantics.time_columns
        identifiers = semantics.identifiers
        geo_cols = [n for n, c in semantics.columns.items() if c.role == ColumnRole.GEOGRAPHIC]

        capabilities: List[AnalysisCapability] = []
        supporting: Dict[str, List[str]] = {}

        # AGGREGATION: Need at least one metric
        if metrics:
            capabilities.append(AnalysisCapability.AGGREGATION)
            supporting[AnalysisCapability.AGGREGATION.value] = metrics

        # RANKING: Need at least one metric (rank by value)
        if metrics:
            capabilities.append(AnalysisCapability.RANKING)
            supporting[AnalysisCapability.RANKING.value] = metrics

        # GROUPING: Need at least one dimension and one metric
        if dimensions and metrics:
            capabilities.append(AnalysisCapability.GROUPING)
            supporting[AnalysisCapability.GROUPING.value] = dimensions + metrics

        # COMPARISON: Same requirements as grouping
        if dimensions and metrics:
            capabilities.append(AnalysisCapability.COMPARISON)
            supporting[AnalysisCapability.COMPARISON.value] = dimensions + metrics

        # TIME SERIES: Need a time column and a metric
        if time_cols and metrics:
            capabilities.append(AnalysisCapability.TIME_SERIES)
            supporting[AnalysisCapability.TIME_SERIES.value] = time_cols + metrics

        # TREND: Same as time series
        if time_cols and metrics:
            capabilities.append(AnalysisCapability.TREND)
            supporting[AnalysisCapability.TREND.value] = time_cols + metrics

        # FORECASTING: Need a time column and a metric (same prerequisite as time series,
        # but is a more advanced capability — we flag it if we have good time coverage)
        if time_cols and metrics:
            capabilities.append(AnalysisCapability.FORECASTING)
            supporting[AnalysisCapability.FORECASTING.value] = time_cols + metrics

        # DISTRIBUTION: Need at least one metric
        if metrics:
            capabilities.append(AnalysisCapability.DISTRIBUTION)
            supporting[AnalysisCapability.DISTRIBUTION.value] = metrics

        # CORRELATION: Need at least two metrics
        if len(metrics) >= 2:
            capabilities.append(AnalysisCapability.CORRELATION)
            supporting[AnalysisCapability.CORRELATION.value] = metrics

        # GEOGRAPHIC: Need a geographic column
        if geo_cols and metrics:
            capabilities.append(AnalysisCapability.GEOGRAPHIC)
            supporting[AnalysisCapability.GEOGRAPHIC.value] = geo_cols + metrics

        # SEGMENTATION: Need at least two dimensions
        if len(dimensions) >= 2 and metrics:
            capabilities.append(AnalysisCapability.SEGMENTATION)
            supporting[AnalysisCapability.SEGMENTATION.value] = dimensions

        # COHORT: Need a time column and a grouping dimension
        if time_cols and dimensions:
            capabilities.append(AnalysisCapability.COHORT)
            supporting[AnalysisCapability.COHORT.value] = time_cols + dimensions

        # KPI TRACKING: Need at least one metric and one time or dimension
        if metrics and (time_cols or dimensions):
            capabilities.append(AnalysisCapability.KPI_TRACKING)
            supporting[AnalysisCapability.KPI_TRACKING.value] = metrics

        logger.info(f"CapabilityDetector: detected {len(capabilities)} capabilities")
        return CapabilitySet(capabilities=capabilities, supporting_columns=supporting)


capability_detector = CapabilityDetector()
