"""
Dataset Intelligence Engine — Context Engineering Layer

This module manages the intelligent packaging of the DatasetKnowledgeObject (DKO)
for the Presentation Engine. 

It implements Adaptive Context Budgeting: ensuring that large datasets do not
overwhelm the LLM token limits, while preserving rich statistical profiles for
the most analytically important columns.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .models_v2 import DatasetKnowledgeObject

logger = logging.getLogger(__name__)


class PresentationContextBuilder:
    """
    Context Engineering Layer.
    Extracts, prioritizes, and formats intelligence from the DKO for the Presentation LLM.
    """

    def build_context(self, dko: DatasetKnowledgeObject) -> str:
        """
        Build the JSON payload representing the context.
        """
        logger.info(f"PresentationContextBuilder: Engineering context for '{dko.dataset_name}'")

        # 1. Start with Dataset Identity and Observations
        identity = dko.get_dataset_identity()
        context = {
            "metadata": {
                "dataset_name": dko.dataset_name,
                "row_count": dko.row_count,
                "column_count": dko.column_count,
                "domain": identity.probable_purpose,
                "overall_readiness": identity.overall_readiness
            },
            "dataset_observations": [obs.observation for obs in dko.observations],
            "primary_entities": dko.get_business_entities(),
            "kpis": [k.name for k in dko.get_kpis()],
            "analytical_opportunities": [opp.name for opp in dko.get_analysis_opportunities()]
        }

        # 2. Adaptive Budgeting for Column Profiles
        # We don't use fixed limits, but we adapt based on importance.
        # If dataset is huge, we raise the threshold for deep statistics.
        threshold = 0.1
        if dko.column_count > 50:
            threshold = 0.5
        elif dko.column_count > 200:
            threshold = 0.8

        important_cols = dko.get_most_important_columns(limit=50, threshold=threshold)
        
        column_profiles = []
        for col in important_cols:
            profile = {
                "name": col.name,
                "role": col.role.value,
                "semantic_type": col.semantic_type.value,
                "characteristics": col.characteristics,
                "null_pct": col.null_pct,
                "unique_count": col.unique_count
            }

            if col.numeric_stats:
                profile["numeric_profile"] = {
                    "min": col.numeric_stats.min,
                    "max": col.numeric_stats.max,
                    "mean": col.numeric_stats.mean,
                    "median": col.numeric_stats.median,
                    "skewness": col.numeric_stats.skewness_label,
                    "zero_count": col.numeric_stats.zero_count
                }
            elif col.categorical_stats:
                profile["categorical_profile"] = {
                    "dominant_value": col.categorical_stats.dominant_value,
                    "dominant_pct": col.categorical_stats.dominant_pct,
                    "is_high_cardinality": col.categorical_stats.is_high_cardinality
                }
            elif col.datetime_stats:
                profile["datetime_profile"] = {
                    "min_date": col.datetime_stats.min_date,
                    "max_date": col.datetime_stats.max_date,
                    "granularity": col.datetime_stats.granularity
                }
            
            column_profiles.append(profile)

        context["key_columns"] = column_profiles

        # 3. Relationships and Groupings
        graph = dko.get_relationships()
        context["relationships"] = {
            "top_correlations": [
                {"col_a": c.col_a, "col_b": c.col_b, "strength": c.strength, "direction": c.direction}
                for c in graph.correlations[:5]
            ],
            "grouping_dynamics": [
                {"dimension": g.dimension, "controls_metrics": g.metrics}
                for g in graph.groupings
            ]
        }

        # 4. Top Insights
        top_insights = sorted(dko.insights, key=lambda x: x.importance_score, reverse=True)[:5]
        context["top_insights"] = [
            {"title": i.title, "description": i.description, "severity": i.severity.value}
            for i in top_insights
        ]
        
        # 5. Versioning
        context["versioning"] = {
            "dko_schema_version": dko.versions.dko_schema_version,
            "context_version": "1.0.0"
        }

        return json.dumps(context, indent=2)

presentation_context_builder = PresentationContextBuilder()
