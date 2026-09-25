"""
Dataset Intelligence Engine — Dataset Memory Builder

Serializes a DatasetKnowledgeObject for storage in session memory.

The Dataset Memory stores a compact, context-efficient representation
of the DKO that is injected into the conversation context when a user
asks about a dataset they have already uploaded.

This allows the Conversation Engine and Planner to have instant dataset
knowledge without re-running the intelligence pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

# Use models_v2
from .models_v2 import DatasetKnowledgeObject

logger = logging.getLogger(__name__)


class DatasetMemoryBuilder:
    """
    Builds a compact memory representation of the DatasetKnowledgeObject
    for injection into conversation context.
    """

    def build_context_summary(self, dko: DatasetKnowledgeObject) -> str:
        """
        Build a compact, LLM-ready context summary of the dataset.
        This uses the Knowledge Access API exclusively.
        """
        lines = []
        identity = dko.get_dataset_identity()

        lines.append(f"## Active Dataset: {dko.dataset_name}")
        lines.append(f"- **Rows:** {dko.row_count:,} | **Columns:** {dko.column_count}")
        lines.append(f"- **Domain:** {identity.probable_purpose}")
        
        # We rely on observations directly
        if dko.observations:
            for obs in dko.observations:
                lines.append(f"- **Observation:** {obs.observation}")

        lines.append("")

        # Schema summary using API
        metrics = [m.name for m in dko.get_primary_metrics()]
        dimensions = [d.name for d in dko.get_grouping_dimensions()]
        time_cols = [t.name for t in dko.get_time_dimensions()]
        identifiers = [i.name for i in dko.columns.values() if i.role.value == "Identifier"]

        if metrics:
            lines.append(f"**Metrics (can be aggregated/ranked):** {', '.join(metrics)}")
        if dimensions:
            lines.append(f"**Dimensions (can be grouped by):** {', '.join(dimensions)}")
        if time_cols:
            lines.append(f"**Time Columns:** {', '.join(time_cols)}")
        if identifiers:
            lines.append(f"**Identifiers (unique keys):** {', '.join(identifiers)}")
        lines.append("")

        # Capabilities using API
        opportunities = dko.get_analysis_opportunities()
        if opportunities:
            lines.append(f"**Supported Analyses:** {', '.join(o.name for o in opportunities)}")
            lines.append("")

        # Top insights (if available)
        top_insights = sorted(dko.insights, key=lambda x: x.importance_score, reverse=True)[:4]
        if top_insights:
            lines.append("**Key Findings:**")
            for insight in top_insights:
                lines.append(f"- {insight.title}")
            lines.append("")

        # Presentation
        if dko.presentation and dko.presentation.presentation:
            lines.append("")
            lines.append(f"**Dataset Overview:** {dko.presentation.presentation[:500]}...")

        return "\n".join(lines)

    def build_planner_context(self, dko: DatasetKnowledgeObject) -> Dict[str, Any]:
        """
        Build a structured context dict for the Planner using Knowledge Access API.
        """
        metrics = [m.name for m in dko.get_primary_metrics()]
        dimensions = [d.name for d in dko.get_grouping_dimensions()]
        time_cols = [t.name for t in dko.get_time_dimensions()]
        identifiers = [i.name for i in dko.columns.values() if i.role.value == "Identifier"]
        opportunities = [o.name for o in dko.get_analysis_opportunities()]
        
        correlations = []
        if dko.knowledge_graph:
            correlations = [
                {"col_a": c.col_a, "col_b": c.col_b, "r": c.pearson_r, "strength": c.strength}
                for c in dko.knowledge_graph.correlations[:5]
            ]

        # Use identity for primary entities or KPIs
        kpis = [k.name for k in dko.get_kpis()]

        return {
            "dataset_name": dko.dataset_name,
            "row_count": dko.row_count,
            "column_count": dko.column_count,
            "domain": dko.get_dataset_identity().probable_purpose,
            "metrics": metrics,
            "dimensions": dimensions,
            "time_columns": time_cols,
            "identifiers": identifiers,
            "capabilities": opportunities,
            "kpis": kpis,
            "predicted_questions": [q.question for q in dko.predicted_questions[:5]],
            "correlations": correlations,
        }

    def build_frontend_payload(self, dko: DatasetKnowledgeObject) -> Dict[str, Any]:
        """
        Build the complete frontend payload for the Intelligence Dashboard.
        Uses DKO.to_frontend_dict() as the base, adding any additional formatting.
        """
        payload = dko.to_frontend_dict()

        # Add column-level details for the schema explorer
        payload["column_details"] = [
            {
                "name": col.name,
                "role": col.role.value,
                "semantic_type": col.semantic_type.value,
                "null_pct": col.null_pct,
                "unique_count": col.unique_count,
                "is_primary_metric": col.name in [k.name for k in dko.get_kpis()],
                "is_primary_date": False, # Simplified for now
                "concept": col.business_meaning,
            }
            for col in dko.columns.values()
        ]

        return payload


dataset_memory_builder = DatasetMemoryBuilder()
