"""
Dataset Intelligence Engine Package

Public API:
    DatasetIntelligenceEngine   — Main orchestrator
    DatasetKnowledgeObject      — The unified intelligence output
    dataset_intelligence_engine — Module-level singleton instance
"""

from .dataset_intelligence_engine import DatasetIntelligenceEngine, dataset_intelligence_engine
from .models_v2 import DatasetKnowledgeObject
from .models import (
    AnalysisCapability,
    CapabilitySet,
    ColumnRole,
    ColumnSchema,
    ColumnSemanticType,
    ColumnStats,
    DataDomain,
    DataInsight,
    DatasetPresentation,
    DomainResult,
    InsightSeverity,
    PredictedQuestion,
    QualityReport,
    RelationshipMap,
    SemanticMap,
)
from .dataset_memory_builder import dataset_memory_builder
from .semantic_resolver import SemanticSchemaResolver, semantic_schema_resolver, get_semantic_resolver, SemanticResolutionResult, SemanticRole

__all__ = [
    "DatasetIntelligenceEngine",
    "dataset_intelligence_engine",
    "DatasetKnowledgeObject",
    "SemanticSchemaResolver",
    "semantic_schema_resolver",
    "get_semantic_resolver",
    "SemanticResolutionResult",
    "SemanticRole",
    "ColumnRole",
    "ColumnSchema",
    "ColumnSemanticType",
    "ColumnStats",
    "DataDomain",
    "DomainResult",
    "CapabilitySet",
    "AnalysisCapability",
    "QualityReport",
    "RelationshipMap",
    "SemanticMap",
    "DataInsight",
    "InsightSeverity",
    "PredictedQuestion",
    "DatasetPresentation",
    "dataset_memory_builder",
    "SemanticSchemaResolver",
    "semantic_schema_resolver",
    "SemanticResolutionResult",
    "SemanticRole",
]

