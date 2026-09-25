"""
Dataset Intelligence Engine — Data Models v2

This module defines the new consumer-agnostic Analytical Knowledge System.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    ColumnRole, ColumnSemanticType, DataDomain, AnalysisCapability,
    InsightSeverity, QualityIssueType, QualityIssue, QualityReport,
    NumericStats, CategoricalStats, DatetimeStats, ColumnCorrelation,
    PredictedQuestion, DataInsight, DatasetPresentation
)

# ---------------------------------------------------------------------------
# Inference Metadata & Lineage
# ---------------------------------------------------------------------------

@dataclass
class InferenceMetadata:
    confidence: float = 1.0
    importance: float = 0.0
    explanation: str = ""
    lineage: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# Column Intelligence
# ---------------------------------------------------------------------------

@dataclass
class ColumnIntelligence:
    name: str
    position: int
    dtype_raw: str
    dtype_category: str
    role: ColumnRole = ColumnRole.UNKNOWN
    semantic_type: ColumnSemanticType = ColumnSemanticType.UNKNOWN
    business_meaning: Optional[str] = None

    # Nullability & Cardinality
    null_count: int = 0
    null_pct: float = 0.0
    unique_count: int = 0
    unique_pct: float = 0.0
    is_nullable: bool = False
    is_constant: bool = False
    is_unique: bool = False
    
    # Nested stats
    numeric_stats: Optional[NumericStats] = None
    categorical_stats: Optional[CategoricalStats] = None
    datetime_stats: Optional[DatetimeStats] = None
    
    # Knowledge
    characteristics: List[str] = field(default_factory=list)
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "dtype_raw": self.dtype_raw,
            "dtype_category": self.dtype_category,
            "role": self.role.value,
            "semantic_type": self.semantic_type.value,
            "business_meaning": self.business_meaning,
            "null_count": self.null_count,
            "null_pct": self.null_pct,
            "unique_count": self.unique_count,
            "unique_pct": self.unique_pct,
            "is_nullable": self.is_nullable,
            "is_constant": self.is_constant,
            "is_unique": self.is_unique,
            "numeric_stats": self.numeric_stats.to_dict() if self.numeric_stats else None,
            "categorical_stats": self.categorical_stats.to_dict() if self.categorical_stats else None,
            "datetime_stats": self.datetime_stats.to_dict() if self.datetime_stats else None,
            "characteristics": self.characteristics,
            "metadata": self.metadata.to_dict()
        }

# ---------------------------------------------------------------------------
# Knowledge Graph Layer
# ---------------------------------------------------------------------------

@dataclass
class Dependency:
    source: str
    target: str
    relationship_type: str
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class GroupingRelationship:
    dimension: str
    metrics: List[str]
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class KnowledgeGraph:
    hierarchies: List[Dependency] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    groupings: List[GroupingRelationship] = field(default_factory=list)
    correlations: List[ColumnCorrelation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hierarchies": [h.to_dict() for h in self.hierarchies],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "groupings": [g.to_dict() for g in self.groupings],
            "correlations": [c.to_dict() for c in self.correlations]
        }

# ---------------------------------------------------------------------------
# Analytical Groups & Opportunities
# ---------------------------------------------------------------------------

@dataclass
class AnalyticalGroup:
    name: str
    group_type: str
    columns: List[str]
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class AnalyticalOpportunity:
    name: str
    description: str
    required_columns: List[str] = field(default_factory=list)
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# Dataset Identity & Observations
# ---------------------------------------------------------------------------

@dataclass
class DatasetIdentity:
    probable_purpose: str = ""
    primary_entities: List[str] = field(default_factory=list)
    business_concepts: List[str] = field(default_factory=list)
    overall_readiness: str = "unknown"
    kpis: List[str] = field(default_factory=list)
    strongest_groupings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class DatasetObservation:
    observation: str
    category: str
    metadata: InferenceMetadata = field(default_factory=InferenceMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# Versioning Stack
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceStackVersion:
    engine_version: str = "1.0.0"
    dko_schema_version: str = "2.0.0"
    knowledge_graph_version: str = "1.0.0"
    semantic_model_version: str = "1.0.0"
    observation_engine_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# The Dataset Knowledge Object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetKnowledgeObject:
    fingerprint: str
    dataset_name: str
    analyzed_at: str
    row_count: int
    column_count: int
    memory_usage_bytes: int

    versions: IntelligenceStackVersion = field(default_factory=IntelligenceStackVersion)
    
    identity: DatasetIdentity = field(default_factory=DatasetIdentity)
    observations: List[DatasetObservation] = field(default_factory=list)
    
    columns: Dict[str, ColumnIntelligence] = field(default_factory=dict)
    analytical_groups: List[AnalyticalGroup] = field(default_factory=list)
    
    knowledge_graph: KnowledgeGraph = field(default_factory=KnowledgeGraph)
    
    opportunities: List[AnalyticalOpportunity] = field(default_factory=list)
    insights: List[DataInsight] = field(default_factory=list)
    predicted_questions: List[PredictedQuestion] = field(default_factory=list)

    # Note: These legacy objects are kept temporarily during migration
    quality_report: Optional[QualityReport] = None
    domain: Optional[DomainResult] = None
    capabilities: Optional[Any] = None # Will be deprecated in favor of opportunities
    presentation: Optional[DatasetPresentation] = None # Still needed for backwards compat UI

    # -------------------------------------------------------------------------
    # Knowledge Access API
    # -------------------------------------------------------------------------

    def get_primary_metrics(self) -> List[ColumnIntelligence]:
        return [c for c in self.columns.values() if c.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL)]

    def get_grouping_dimensions(self) -> List[ColumnIntelligence]:
        return [c for c in self.columns.values() if c.role in (ColumnRole.DIMENSION, ColumnRole.GEOGRAPHIC)]

    def get_dataset_identity(self) -> DatasetIdentity:
        return self.identity

    def get_kpis(self) -> List[ColumnIntelligence]:
        return [self.columns[kpi] for kpi in self.identity.kpis if kpi in self.columns]

    def get_relationships(self) -> KnowledgeGraph:
        return self.knowledge_graph

    def get_business_entities(self) -> List[str]:
        return self.identity.primary_entities

    def get_analysis_opportunities(self) -> List[AnalyticalOpportunity]:
        return self.opportunities

    def get_time_dimensions(self) -> List[ColumnIntelligence]:
        return [c for c in self.columns.values() if c.role == ColumnRole.TIME]

    def get_most_important_columns(self, limit: int = 10, threshold: float = 0.5) -> List[ColumnIntelligence]:
        cols = [c for c in self.columns.values() if c.metadata.importance >= threshold]
        return sorted(cols, key=lambda c: c.metadata.importance, reverse=True)[:limit]

    def get_column_profile(self, column_name: str) -> Optional[ColumnIntelligence]:
        return self.columns.get(column_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "dataset_name": self.dataset_name,
            "analyzed_at": self.analyzed_at,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "memory_usage_bytes": self.memory_usage_bytes,
            "versions": self.versions.to_dict(),
            "identity": self.identity.to_dict(),
            "observations": [o.to_dict() for o in self.observations],
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "analytical_groups": [g.to_dict() for g in self.analytical_groups],
            "knowledge_graph": self.knowledge_graph.to_dict(),
            "opportunities": [o.to_dict() for o in self.opportunities],
            "insights": [i.to_dict() for i in self.insights],
            "predicted_questions": [q.to_dict() for q in self.predicted_questions],
            "quality_report": self.quality_report.to_dict() if self.quality_report else None,
            "domain": self.domain.to_dict() if self.domain else None,
            "presentation": self.presentation.to_dict() if self.presentation else None
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def to_frontend_dict(self) -> Dict[str, Any]:
        top_insights = sorted(self.insights, key=lambda x: x.importance_score, reverse=True)[:8]
        return {
            "dataset_name": self.dataset_name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "domain": self.domain.to_dict() if self.domain else None,
            "analysis_readiness_score": self.quality_report.overall_score if self.quality_report else 0.0,
            "data_quality_score": self.quality_report.overall_score if self.quality_report else 0.0,
            "quality_label": self.quality_report.analysis_readiness if self.quality_report else "unknown",
            "metrics": [c.name for c in self.get_primary_metrics()],
            "dimensions": [c.name for c in self.get_grouping_dimensions()],
            "time_columns": [c.name for c in self.get_time_dimensions()],
            "identifiers": [c.name for c in self.columns.values() if c.role == ColumnRole.IDENTIFIER],
            "capabilities": [o.name for o in self.opportunities],
            "top_insights": [i.to_dict() for i in top_insights],
            "predicted_questions": [q.to_dict() for q in self.predicted_questions[:8]],
            "presentation": self.presentation.to_dict() if self.presentation else None,
        }
