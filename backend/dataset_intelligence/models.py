"""
Dataset Intelligence Engine — Data Models

This module defines ALL dataclasses used throughout the Dataset Intelligence Engine.
It has zero dependencies on other DIE modules — it is the foundation layer.

Design principles:
  - Every field has a type annotation and a docstring/comment.
  - Every dataclass has a to_dict() method for JSON serialization.
  - Enum classes define all allowed categorical values to prevent magic strings.
  - Models are immutable by default (frozen=False only where mutation is needed).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enumerations — prevents magic strings throughout the codebase
# ---------------------------------------------------------------------------

class ColumnRole(str, Enum):
    """High-level analytical role of a column."""
    METRIC          = "Metric"           # Numeric value to aggregate (Revenue, Score)
    DIMENSION       = "Dimension"        # Categorical grouping column (Region, Category)
    IDENTIFIER      = "Identifier"       # Unique key, not for analysis (Order_ID, UUID)
    TIME            = "Time"             # Temporal column (Date, Month, Year)
    ATTRIBUTE       = "Attribute"        # Descriptive text, not for grouping
    BOOLEAN_FLAG    = "BooleanFlag"      # True/False flag (Is_Active, Has_Discount)
    GEOGRAPHIC      = "Geographic"       # Location data (Country, City, Zip)
    FINANCIAL       = "FinancialMetric"  # Currency/financial metric
    ACADEMIC        = "AcademicMetric"   # Education-specific metric
    HEALTHCARE      = "HealthcareMetric" # Medical metric
    UNKNOWN         = "Unknown"          # Unclassified


class ColumnSemanticType(str, Enum):
    """Detailed semantic type of a column's values."""
    # Numeric subtypes
    CURRENCY        = "currency"         # Contains dollar/currency values
    PERCENTAGE      = "percentage"       # 0–100 or 0.0–1.0 ratios
    SCORE           = "score"            # Scoring/ranking numeric
    COUNT           = "count"            # Integer count values
    RANK            = "rank"             # Ordinal rank (1st, 2nd, ...)
    RATING          = "rating"           # 1–5 or 1–10 scale
    NUMERIC_GENERAL = "numeric_general"  # Generic numeric

    # Categorical subtypes
    CATEGORY        = "category"         # General categorical
    STATUS          = "status"           # Status/state values (Active, Inactive)
    BOOLEAN_TEXT    = "boolean_text"     # Yes/No, True/False stored as text
    GENDER          = "gender"           # Gender values
    GRADE           = "grade"            # A/B/C or Pass/Fail
    GEOGRAPHIC_NAME = "geographic_name"  # Country, City, Region names

    # Identifier subtypes
    UUID            = "uuid"             # UUID format identifiers
    CODE            = "code"             # Codes (SKU, Promo codes)
    ID_INTEGER      = "id_integer"       # Integer IDs
    SEQUENTIAL_ID   = "sequential_id"    # Auto-increment integer IDs

    # Temporal subtypes
    DATE            = "date"
    DATETIME        = "datetime"
    YEAR            = "year"
    MONTH           = "month"
    QUARTER         = "quarter"

    # Text subtypes
    NAME            = "name"             # Person names
    EMAIL           = "email"            # Email addresses
    PHONE           = "phone"            # Phone numbers
    URL             = "url"              # Web URLs
    ADDRESS         = "address"          # Physical addresses
    FREE_TEXT       = "free_text"        # Long-form unstructured text
    DESCRIPTION     = "description"      # Descriptions/notes

    # Unknown
    UNKNOWN         = "unknown"


class DataDomain(str, Enum):
    """Inferred business domain of the dataset."""
    RETAIL_SALES    = "Retail/Sales"
    FINANCE         = "Finance"
    HR              = "HR"
    EDUCATION       = "Education"
    HEALTHCARE      = "Healthcare"
    MARKETING       = "Marketing"
    INVENTORY       = "Inventory"
    MANUFACTURING   = "Manufacturing"
    SPORTS          = "Sports"
    CUSTOMER        = "Customer Analytics"
    ECOMMERCE       = "E-Commerce"
    LOGISTICS       = "Logistics"
    GENERAL         = "General Purpose"


class AnalysisCapability(str, Enum):
    """Analysis types the dataset supports."""
    RANKING         = "ranking"
    AGGREGATION     = "aggregation"
    GROUPING        = "grouping"
    COMPARISON      = "comparison"
    TIME_SERIES     = "time_series"
    CORRELATION     = "correlation"
    DISTRIBUTION    = "distribution"
    GEOGRAPHIC      = "geographic"
    TREND           = "trend"
    FORECASTING     = "forecasting"
    COHORT          = "cohort"
    SEGMENTATION    = "segmentation"
    KPI_TRACKING    = "kpi_tracking"


class InsightSeverity(str, Enum):
    """Priority level of a data insight."""
    CRITICAL    = "critical"    # Must be addressed (e.g., 80% null column)
    HIGH        = "high"        # Significant finding (e.g., strong skew)
    MEDIUM      = "medium"      # Noteworthy (e.g., moderate correlation)
    LOW         = "low"         # Informational
    POSITIVE    = "positive"    # Good news (e.g., no missing values)


class QualityIssueType(str, Enum):
    """Types of data quality issues."""
    MISSING_VALUES      = "missing_values"
    DUPLICATE_ROWS      = "duplicate_rows"
    DUPLICATE_COLUMNS   = "duplicate_columns"
    CONSTANT_COLUMN     = "constant_column"
    NEAR_CONSTANT       = "near_constant_column"
    HIGH_CARDINALITY    = "high_cardinality"
    MIXED_TYPES         = "mixed_types"
    WHITESPACE_ISSUES   = "whitespace_issues"
    CASE_INCONSISTENCY  = "case_inconsistency"
    INVALID_DATES       = "invalid_dates"
    OUTLIERS            = "extreme_outliers"
    NEGATIVE_VALUES     = "suspicious_negatives"
    SPARSE_COLUMN       = "sparse_column"
    ENCODING_ISSUES     = "encoding_issues"


# ---------------------------------------------------------------------------
# Schema Models
# ---------------------------------------------------------------------------

@dataclass
class ColumnSchema:
    """
    Complete schema-level understanding of a single column.
    This is Stage 1 output — richer than a plain dtype.
    """
    name: str
    position: int                           # 0-indexed column position
    dtype_raw: str                          # Original pandas dtype string
    dtype_category: str                     # 'numeric', 'categorical', 'datetime', 'boolean', 'text'
    role: ColumnRole = ColumnRole.UNKNOWN
    semantic_type: ColumnSemanticType = ColumnSemanticType.UNKNOWN

    # Nullability
    null_count: int = 0
    null_pct: float = 0.0
    is_nullable: bool = False

    # Cardinality
    unique_count: int = 0
    unique_pct: float = 0.0
    is_constant: bool = False               # All values the same
    is_unique: bool = False                 # All values different (potential identifier)

    # Characteristics
    sample_values: List[str] = field(default_factory=list)
    is_primary_metric: bool = False         # Flagged as most important metric
    is_primary_date: bool = False           # Flagged as the main time column
    concept: Optional[str] = None          # e.g. 'revenue_metric', 'region_dimension'

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['role'] = self.role.value
        d['semantic_type'] = self.semantic_type.value
        return d


# ---------------------------------------------------------------------------
# Statistical Models
# ---------------------------------------------------------------------------

@dataclass
class NumericStats:
    """Full statistical profile of a numeric column."""
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    mode: Optional[float] = None
    variance: Optional[float] = None
    std: Optional[float] = None
    q1: Optional[float] = None             # 25th percentile
    q3: Optional[float] = None             # 75th percentile
    iqr: Optional[float] = None            # Interquartile range
    p5: Optional[float] = None             # 5th percentile
    p95: Optional[float] = None            # 95th percentile
    range: Optional[float] = None
    skewness: Optional[float] = None
    kurtosis: Optional[float] = None
    skewness_label: str = "normal"         # 'left-skewed', 'normal', 'right-skewed'
    zero_count: int = 0
    negative_count: int = 0
    positive_count: int = 0
    outlier_count: int = 0
    outlier_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CategoricalStats:
    """Full statistical profile of a categorical column."""
    cardinality: int = 0                   # Number of unique values
    top_values: List[Tuple[str, int]] = field(default_factory=list)   # (value, count)
    rare_values: List[str] = field(default_factory=list)              # Values appearing < 1%
    dominant_value: Optional[str] = None   # Most frequent value
    dominant_pct: float = 0.0             # Percentage of dominant value
    entropy: float = 0.0                   # Shannon entropy (diversity measure)
    is_high_cardinality: bool = False      # More unique values than typical for dimension

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatetimeStats:
    """Full statistical profile of a datetime column."""
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    range_days: Optional[int] = None
    range_years: Optional[float] = None
    granularity: str = "unknown"           # 'daily', 'monthly', 'yearly', 'hourly'
    coverage_pct: float = 0.0             # Non-null percentage
    year_distribution: Dict[str, int] = field(default_factory=dict)
    month_distribution: Dict[str, int] = field(default_factory=dict)
    has_gaps: bool = False                 # Whether there are missing time periods

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ColumnStats:
    """
    Unified statistical container for a column.
    Exactly one of numeric/categorical/datetime will be populated.
    """
    column_name: str
    column_type: str                       # 'numeric', 'categorical', 'datetime', 'boolean'
    null_count: int = 0
    null_pct: float = 0.0
    total_count: int = 0
    distinct_count: int = 0
    duplicate_count: int = 0

    numeric: Optional[NumericStats] = None
    categorical: Optional[CategoricalStats] = None
    datetime: Optional[DatetimeStats] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_name": self.column_name,
            "column_type": self.column_type,
            "null_count": self.null_count,
            "null_pct": self.null_pct,
            "total_count": self.total_count,
            "distinct_count": self.distinct_count,
            "duplicate_count": self.duplicate_count,
            "numeric": self.numeric.to_dict() if self.numeric else None,
            "categorical": self.categorical.to_dict() if self.categorical else None,
            "datetime": self.datetime.to_dict() if self.datetime else None,
        }


# ---------------------------------------------------------------------------
# Quality Models
# ---------------------------------------------------------------------------

@dataclass
class QualityIssue:
    """A single data quality problem found in the dataset."""
    issue_type: QualityIssueType
    severity: InsightSeverity
    affected_columns: List[str]
    description: str
    recommendation: str
    impact_score: float = 0.0             # 0–10 impact on analysis quality

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['issue_type'] = self.issue_type.value
        d['severity'] = self.severity.value
        return d


@dataclass
class QualityReport:
    """Complete data quality assessment of the dataset."""
    overall_score: float                   # 0–100 composite quality score
    completeness_score: float              # Based on missing values
    consistency_score: float              # Based on type/format consistency
    uniqueness_score: float               # Based on duplicate detection
    issues: List[QualityIssue] = field(default_factory=list)
    duplicate_row_count: int = 0
    duplicate_row_pct: float = 0.0
    total_missing_cells: int = 0
    total_missing_pct: float = 0.0
    columns_with_issues: List[str] = field(default_factory=list)
    analysis_readiness: str = "good"       # 'excellent', 'good', 'fair', 'poor'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "completeness_score": self.completeness_score,
            "consistency_score": self.consistency_score,
            "uniqueness_score": self.uniqueness_score,
            "issues": [i.to_dict() for i in self.issues],
            "duplicate_row_count": self.duplicate_row_count,
            "duplicate_row_pct": self.duplicate_row_pct,
            "total_missing_cells": self.total_missing_cells,
            "total_missing_pct": self.total_missing_pct,
            "columns_with_issues": self.columns_with_issues,
            "analysis_readiness": self.analysis_readiness,
        }


# ---------------------------------------------------------------------------
# Relationship Models
# ---------------------------------------------------------------------------

@dataclass
class ColumnCorrelation:
    """Correlation between two numeric columns."""
    col_a: str
    col_b: str
    pearson_r: float
    strength: str                         # 'very_strong', 'strong', 'moderate', 'weak', 'negligible'
    direction: str                        # 'positive', 'negative'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RelationshipMap:
    """All discovered inter-column relationships."""
    correlations: List[ColumnCorrelation] = field(default_factory=list)
    grouping_dimensions: List[str] = field(default_factory=list)  # Best columns for GROUP BY
    metric_columns: List[str] = field(default_factory=list)       # Columns suitable as KPIs
    foreign_key_candidates: List[str] = field(default_factory=list)
    target_candidates: List[str] = field(default_factory=list)    # ML target variable candidates
    time_metrics: Dict[str, List[str]] = field(default_factory=dict)  # {time_col: [metric_cols]}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlations": [c.to_dict() for c in self.correlations],
            "grouping_dimensions": self.grouping_dimensions,
            "metric_columns": self.metric_columns,
            "foreign_key_candidates": self.foreign_key_candidates,
            "target_candidates": self.target_candidates,
            "time_metrics": self.time_metrics,
        }


# ---------------------------------------------------------------------------
# Semantic Models
# ---------------------------------------------------------------------------

@dataclass
class SemanticColumn:
    """Semantic classification of a column."""
    name: str
    role: ColumnRole
    concept: Optional[str] = None         # Universal concept label
    is_primary_metric: bool = False
    is_primary_date: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['role'] = self.role.value
        return d


@dataclass
class SemanticMap:
    """Complete semantic understanding of the dataset columns."""
    columns: Dict[str, SemanticColumn] = field(default_factory=dict)

    @property
    def metrics(self) -> List[str]:
        return [n for n, c in self.columns.items() if c.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.ACADEMIC, ColumnRole.HEALTHCARE)]

    @property
    def dimensions(self) -> List[str]:
        # Geographic columns are also usable as grouping dimensions
        return [n for n, c in self.columns.items() if c.role in (ColumnRole.DIMENSION, ColumnRole.GEOGRAPHIC)]

    @property
    def identifiers(self) -> List[str]:
        return [n for n, c in self.columns.items() if c.role == ColumnRole.IDENTIFIER]

    @property
    def time_columns(self) -> List[str]:
        return [n for n, c in self.columns.items() if c.role == ColumnRole.TIME]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "metrics": self.metrics,
            "dimensions": self.dimensions,
            "identifiers": self.identifiers,
            "time_columns": self.time_columns,
        }


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------

@dataclass
class DomainResult:
    """Inferred business domain with supporting evidence."""
    domain: DataDomain
    confidence: float                     # 0.0–1.0
    evidence: List[str] = field(default_factory=list)  # Human-readable reasons
    secondary_domain: Optional[DataDomain] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "secondary_domain": self.secondary_domain.value if self.secondary_domain else None,
        }


# ---------------------------------------------------------------------------
# Capability Models
# ---------------------------------------------------------------------------

@dataclass
class CapabilitySet:
    """Analysis capabilities the dataset supports."""
    capabilities: List[AnalysisCapability] = field(default_factory=list)
    supporting_columns: Dict[str, List[str]] = field(default_factory=dict)  # {capability: [cols]}

    def supports(self, capability: AnalysisCapability) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capabilities": [c.value for c in self.capabilities],
            "supporting_columns": {k.value if isinstance(k, AnalysisCapability) else k: v
                                   for k, v in self.supporting_columns.items()},
        }


# ---------------------------------------------------------------------------
# Prediction Models
# ---------------------------------------------------------------------------

@dataclass
class PredictedQuestion:
    """A question the user is likely to ask about this dataset."""
    question: str
    category: str                         # 'ranking', 'aggregation', 'comparison', 'trend', etc.
    confidence: float                     # 0.0–1.0
    relevant_columns: List[str] = field(default_factory=list)
    suggested_chart: Optional[str] = None  # 'bar', 'line', 'pie', 'scatter', etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Insight Models
# ---------------------------------------------------------------------------

@dataclass
class DataInsight:
    """
    A single, prioritized, human-interpretable insight about the dataset.
    Not just a statistic — an interpretation of what the statistic means.
    """
    title: str                            # Short headline
    description: str                      # Full explanation
    severity: InsightSeverity
    category: str                         # 'quality', 'statistical', 'relationship', 'schema'
    affected_columns: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)   # Supporting numbers
    recommendation: Optional[str] = None  # Suggested action
    importance_score: float = 0.0        # 0–10 for sorting

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['severity'] = self.severity.value
        return d


# ---------------------------------------------------------------------------
# Presentation Model
# ---------------------------------------------------------------------------

@dataclass
class DatasetPresentation:
    """
    The Dataset Presentation Engine's output.

    Free-form Markdown generated by the LLM after receiving structured
    intelligence from Python. The LLM owns communication — Python owns facts.

    Fields:
        presentation:  Full Markdown string ready for rendering in the frontend.
        version:       Prompt/architecture version (for cache invalidation, debugging).
        model_used:    Which LLM model generated this presentation.
        generated_at:  ISO-8601 timestamp of when this was generated.
        generated_by:  'llm' when AI-generated, 'fallback' for deterministic fallback.
    """
    presentation: str = ""          # Full Markdown — the only user-facing field
    version: str = "1.0"            # Increment when the prompt changes significantly
    model_used: str = ""            # e.g. 'gemini-1.5-flash', 'llama-3.1-8b-instant'
    generated_at: str = ""          # ISO-8601 timestamp
    generated_by: str = "llm"       # 'llm' | 'fallback'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "presentation": self.presentation,
            "version": self.version,
            "model_used": self.model_used,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
        }


# ---------------------------------------------------------------------------
# Master Object: Dataset Knowledge Object (DKO)
# ---------------------------------------------------------------------------

@dataclass
class DatasetKnowledgeObject:
    """
    The single, unified intelligence object produced by the Dataset Intelligence Engine.

    This is the authoritative source of truth about a dataset.
    Every downstream subsystem consumes this object — never re-analyzing the raw data.
    """

    # Identity
    fingerprint: str
    dataset_name: str
    analyzed_at: str

    # Dimensions
    row_count: int
    column_count: int
    memory_usage_bytes: int

    # Stage outputs
    columns: List[ColumnSchema]
    column_stats: Dict[str, ColumnStats]
    quality: QualityReport
    relationships: RelationshipMap
    semantics: SemanticMap
    domain: DomainResult
    capabilities: CapabilitySet
    predicted_questions: List[PredictedQuestion]
    insights: List[DataInsight]
    presentation: DatasetPresentation

    # Convenience properties (derived from semantics)
    @property
    def metrics(self) -> List[str]:
        return self.semantics.metrics

    @property
    def dimensions(self) -> List[str]:
        return self.semantics.dimensions

    @property
    def time_columns(self) -> List[str]:
        return self.semantics.time_columns

    @property
    def identifiers(self) -> List[str]:
        return self.semantics.identifiers

    @property
    def analysis_readiness_score(self) -> float:
        """Composite readiness score: weighted average of quality + capability count."""
        quality_weight = 0.6
        capability_weight = 0.4
        max_capabilities = len(AnalysisCapability)
        capability_score = (len(self.capabilities.capabilities) / max_capabilities) * 100
        return round(quality_weight * self.quality.overall_score + capability_weight * capability_score, 1)

    @property
    def data_quality_score(self) -> float:
        return self.quality.overall_score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "dataset_name": self.dataset_name,
            "analyzed_at": self.analyzed_at,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "memory_usage_bytes": self.memory_usage_bytes,
            "columns": [c.to_dict() for c in self.columns],
            "column_stats": {k: v.to_dict() for k, v in self.column_stats.items()},
            "quality": self.quality.to_dict(),
            "relationships": self.relationships.to_dict(),
            "semantics": self.semantics.to_dict(),
            "domain": self.domain.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "predicted_questions": [q.to_dict() for q in self.predicted_questions],
            "insights": [i.to_dict() for i in self.insights],
            "presentation": self.presentation.to_dict(),
            "derived": {
                "metrics": self.metrics,
                "dimensions": self.dimensions,
                "time_columns": self.time_columns,
                "identifiers": self.identifiers,
                "analysis_readiness_score": self.analysis_readiness_score,
                "data_quality_score": self.data_quality_score,
            },
        }

    def to_frontend_dict(self) -> Dict[str, Any]:
        """
        A slim, frontend-optimized representation for the Intelligence Dashboard.
        Does not include the full column_stats payload (too large for API response).
        """
        top_insights = sorted(self.insights, key=lambda x: x.importance_score, reverse=True)[:8]
        return {
            "dataset_name": self.dataset_name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "domain": self.domain.to_dict(),
            "analysis_readiness_score": self.analysis_readiness_score,
            "data_quality_score": self.quality.overall_score,
            "quality_label": self.quality.analysis_readiness,
            "metrics": self.metrics,
            "dimensions": self.dimensions,
            "time_columns": self.time_columns,
            "identifiers": self.identifiers,
            "capabilities": [c.value for c in self.capabilities.capabilities],
            "top_insights": [i.to_dict() for i in top_insights],
            "predicted_questions": [q.to_dict() for q in self.predicted_questions[:8]],
            "presentation": self.presentation.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
