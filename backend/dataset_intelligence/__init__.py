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

__all__ = [
    "DatasetIntelligenceEngine",
    "dataset_intelligence_engine",
    "DatasetKnowledgeObject",
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
]
