"""
Dataset Intelligence Engine — Stage 10: Knowledge Synthesizer

Merges all deterministic intelligence from Stages 1-9 into a single,
unified DatasetKnowledgeObject (DKO) following the new Knowledge Graph architecture.

This is the assembly stage. It acts as the bridge between legacy deterministic
heuristics and the new presentation-agnostic graph system.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

import pandas as pd

# Import legacy stage outputs
from .models import (
    AnalysisCapability, CapabilitySet, ColumnSchema, ColumnStats,
    DataInsight, DomainResult,
    PredictedQuestion, QualityReport, RelationshipMap, SemanticMap,
    DatasetPresentation
)

# Import new DKO architecture
from .models_v2 import (
    DatasetKnowledgeObject, ColumnIntelligence, DatasetIdentity,
    DatasetObservation, KnowledgeGraph, Dependency, GroupingRelationship,
    AnalyticalGroup, AnalyticalOpportunity, InferenceMetadata,
    IntelligenceStackVersion
)

logger = logging.getLogger(__name__)


class KnowledgeSynthesizer:
    """
    Stage 10 — Knowledge Synthesizer

    Takes all stage outputs and assembles the master DatasetKnowledgeObject.
    Converts legacy ColumnSchema/ColumnStats into rich ColumnIntelligence.
    Builds the Knowledge Graph and Analytical Groups.
    """

    def synthesize(
        self,
        df: pd.DataFrame,
        dataset_name: str,
        fingerprint: str,
        schemas: List[ColumnSchema],
        column_stats: Dict[str, ColumnStats],
        quality: QualityReport,
        relationships: RelationshipMap,
        semantics: SemanticMap,
        domain: DomainResult,
        capabilities: CapabilitySet,
        predicted_questions: List[PredictedQuestion],
        insights: List[DataInsight],
    ) -> DatasetKnowledgeObject:
        logger.info(f"KnowledgeSynthesizer: assembling Graph-Based DatasetKnowledgeObject for '{dataset_name}'")

        memory_bytes = int(df.memory_usage(deep=True).sum())

        # 1. Build ColumnIntelligence
        columns: Dict[str, ColumnIntelligence] = {}
        for schema in schemas:
            col_name = schema.name
            stats = column_stats.get(col_name)
            
            # Determine analytical importance deterministically
            # This is a naive heuristic for demonstration:
            # Metrics and Dimensions get higher importance. Low nulls get higher importance.
            importance = 0.5
            if schema.role.value in ("Metric", "FinancialMetric"):
                importance += 0.3
            elif schema.role.value in ("Dimension", "Time"):
                importance += 0.2
            if schema.null_pct > 50:
                importance -= 0.3
            importance = max(0.1, min(1.0, importance))

            # Store deterministic characteristics based on legacy quality flags
            characteristics = []
            if schema.is_constant: characteristics.append("constant_column")
            if schema.is_unique: characteristics.append("all_unique_values")
            if schema.null_pct > 80: characteristics.append("sparse_column")
            if stats and stats.numeric and stats.numeric.skewness_label != "normal":
                characteristics.append(f"{stats.numeric.skewness_label}_distribution")

            metadata = InferenceMetadata(
                confidence=1.0,
                importance=importance,
                explanation=f"Role inferred as {schema.role.value} based on type {schema.dtype_category}",
                lineage="Schema Intelligence -> Statistical Profiler -> Semantic Engine"
            )

            col_intel = ColumnIntelligence(
                name=col_name,
                position=schema.position,
                dtype_raw=schema.dtype_raw,
                dtype_category=schema.dtype_category,
                role=schema.role,
                semantic_type=schema.semantic_type,
                business_meaning=schema.concept,
                null_count=schema.null_count,
                null_pct=schema.null_pct,
                unique_count=schema.unique_count,
                unique_pct=schema.unique_pct,
                is_nullable=schema.is_nullable,
                is_constant=schema.is_constant,
                is_unique=schema.is_unique,
                numeric_stats=stats.numeric if stats else None,
                categorical_stats=stats.categorical if stats else None,
                datetime_stats=stats.datetime if stats else None,
                characteristics=characteristics,
                metadata=metadata
            )
            columns[col_name] = col_intel

        # 2. Build DatasetIdentity
        identity = DatasetIdentity(
            probable_purpose=domain.domain.value if domain else "Unknown",
            primary_entities=relationships.foreign_key_candidates,
            business_concepts=[],
            overall_readiness=quality.analysis_readiness,
            kpis=relationships.metric_columns,
            strongest_groupings=relationships.grouping_dimensions
        )

        # 3. Build DatasetObservations
        observations = []
        if quality.overall_score > 90:
            observations.append(DatasetObservation(
                observation="Dataset is exceptionally clean and analysis-ready.",
                category="Quality",
                metadata=InferenceMetadata(explanation="Quality score > 90", lineage="Quality Engine")
            ))
        elif quality.overall_score < 50:
            observations.append(DatasetObservation(
                observation="Dataset requires significant cleaning before analysis.",
                category="Quality",
                metadata=InferenceMetadata(explanation="Quality score < 50", lineage="Quality Engine")
            ))

        # 4. Build KnowledgeGraph
        graph = KnowledgeGraph(correlations=relationships.correlations)
        for time_col, metrics in relationships.time_metrics.items():
            graph.groupings.append(GroupingRelationship(
                dimension=time_col,
                metrics=metrics,
                metadata=InferenceMetadata(explanation="Time column controls metrics", lineage="Relationship Engine")
            ))

        # 5. Build AnalyticalGroups
        analytical_groups = []
        financial_metrics = [c for c, v in columns.items() if v.role.value == "FinancialMetric"]
        if financial_metrics:
            analytical_groups.append(AnalyticalGroup(name="Financial Metrics", group_type="Financial", columns=financial_metrics))
        time_dims = [c for c, v in columns.items() if v.role.value == "Time"]
        if time_dims:
            analytical_groups.append(AnalyticalGroup(name="Time Dimensions", group_type="Time", columns=time_dims))

        # 6. Build AnalyticalOpportunities
        opportunities = []
        for cap in capabilities.capabilities:
            opportunities.append(AnalyticalOpportunity(
                name=cap.value,
                description=f"Supports {cap.value} analysis.",
                required_columns=capabilities.supporting_columns.get(cap, []),
                metadata=InferenceMetadata(lineage="Capability Detector")
            ))

        # 7. Assemble the final DKO
        dko = DatasetKnowledgeObject(
            fingerprint=fingerprint,
            dataset_name=dataset_name,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            row_count=len(df),
            column_count=len(df.columns),
            memory_usage_bytes=memory_bytes,
            versions=IntelligenceStackVersion(),
            identity=identity,
            observations=observations,
            columns=columns,
            analytical_groups=analytical_groups,
            knowledge_graph=graph,
            opportunities=opportunities,
            insights=insights,
            predicted_questions=predicted_questions,
            quality_report=quality,
            domain=domain,
            capabilities=capabilities,
            presentation=DatasetPresentation()
        )

        logger.info(f"KnowledgeSynthesizer: New Graph-based DKO assembled successfully.")
        return dko

    def finalize(
        self,
        dko: DatasetKnowledgeObject,
        presentation: DatasetPresentation,
    ) -> DatasetKnowledgeObject:
        """
        Inject the LLM presentation into the legacy field.
        """
        from dataclasses import replace
        return replace(dko, presentation=presentation)


knowledge_synthesizer = KnowledgeSynthesizer()
