from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from evidence.contracts import EvidenceReference, EvidenceType


class AnalysisType(str, Enum):
    """Closed enum of all supported autonomous analysis families."""
    DISTRIBUTION = "distribution"
    OUTLIER_DETECTION = "outlier_detection"
    SUMMARY_STATISTICS = "summary_statistics"
    TEMPORAL_TREND = "temporal_trend"
    TEMPORAL_COVERAGE = "temporal_coverage"
    TEMPORAL_GAPS = "temporal_gaps"
    GROUP_COMPARISON = "group_comparison"
    CONCENTRATION_ANALYSIS = "concentration_analysis"
    CORRELATION = "correlation"
    MISSINGNESS_ANALYSIS = "missingness_analysis"
    DUPLICATE_ANALYSIS = "duplicate_analysis"
    TOP_N_ANALYSIS = "top_n_analysis"
    FREQUENCY_ANALYSIS = "frequency_analysis"
    VOLATILITY = "volatility"
    IDENTIFIER_QUALITY = "identifier_quality"


class SectionType(str, Enum):
    """Closed enum of allowed presentation primitives."""
    METRIC_GROUP = "metric_group"
    TABLE = "table"
    CHART = "chart"
    FINDING = "finding"
    WARNING = "warning"
    RELATIONSHIP = "relationship"
    TEXT = "text"
    COMPARISON = "comparison"
    # Evidence-driven section types
    STATISTICS = "statistics"
    DISTRIBUTION = "distribution"
    MISSINGNESS = "missingness"
    IDENTIFIER = "identifier"
    DATA_QUALITY = "data_quality"
    RANKING = "ranking"
    OUTLIER_LIST = "outlier_list"


class CandidateCost(str, Enum):
    """Execution cost tier for a candidate analysis."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ColumnRequirement:
    dtype_category: str
    min_cardinality: int = 1
    max_cardinality: int = 999999
    min_non_null_pct: float = 0.0
    must_be_ordered: bool = False
    semantic_hints: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidatePrerequisites:
    column_requirements: List[ColumnRequirement]
    min_row_count: int = 10
    dataset_level: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["column_requirements"] = [req.to_dict() for req in self.column_requirements]
        return d


@dataclass
class CandidateScore:
    structural_validity: float = 0.0
    evidence_strength: float = 0.0
    information_value: float = 0.0
    semantic_relevance: float = 0.0
    novelty: float = 0.0
    computational_cost: float = 0.0
    composite: float = 0.0
    diversity_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisCandidate:
    candidate_id: str
    analysis_type: AnalysisType
    columns: List[str]
    prerequisites: CandidatePrerequisites
    score: CandidateScore = field(default_factory=CandidateScore)
    estimated_cost: CandidateCost = CandidateCost.LOW
    estimated_cost_units: int = 1
    evidence_basis: str = ""
    redundancy_group: str = ""
    is_filtered_out: bool = False
    filter_reason: str = ""

    @property
    def column_key(self) -> str:
        return f"{self.analysis_type.value}::{','.join(sorted(self.columns))}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "analysis_type": self.analysis_type.value,
            "columns": self.columns,
            "prerequisites": self.prerequisites.to_dict(),
            "score": self.score.to_dict(),
            "estimated_cost": self.estimated_cost.value,
            "estimated_cost_units": self.estimated_cost_units,
            "evidence_basis": self.evidence_basis,
            "redundancy_group": self.redundancy_group,
            "is_filtered_out": self.is_filtered_out,
            "filter_reason": self.filter_reason,
            "column_key": self.column_key
        }


@dataclass
class PlannedInvestigation:
    candidate_id: str
    priority: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationPlan:
    investigations: List[PlannedInvestigation]
    dataset_fingerprint: str
    plan_version: str = "1.0"
    llm_model: str = ""
    raw_llm_output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["investigations"] = [inv.to_dict() for inv in self.investigations]
        return d


@dataclass
class AnalysisBudget:
    max_investigations: int
    max_cost_units: int
    per_analysis_timeout_s: int = 30
    total_wall_budget_s: int = 120
    complexity_tier: str = "normal"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NumericalGrounding:
    values: List[float] = field(default_factory=list)
    percentages: List[float] = field(default_factory=list)
    tolerance: float = 0.01

    def is_supported(self, claimed_value: float) -> bool:
        """Return True if claimed_value is within tolerance of any grounded value."""
        for val in self.values + self.percentages:
            if abs(val) > 0 and abs(claimed_value - val) / abs(val) <= self.tolerance:
                return True
            if abs(val) == 0 and abs(claimed_value) < 0.001:
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationResult:
    candidate_id: str
    analysis_type: AnalysisType
    status: str
    columns: List[str]
    result_data: Dict[str, Any] = field(default_factory=dict)
    evidence: Optional[EvidenceReference] = None
    grounding: Optional[NumericalGrounding] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    interpretation: str = ""
    interpretation_flagged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["analysis_type"] = self.analysis_type.value
        d["evidence"] = self.evidence.to_dict() if self.evidence else None
        d["grounding"] = self.grounding.to_dict() if self.grounding else None
        return d


@dataclass
class SynthesisInsight:
    related_candidate_ids: List[str]
    relationship_type: str
    synthesis_text: str
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomousSection:
    section_id: str
    section_type: SectionType
    group_title: str
    title: str
    interpretation: str
    evidence_ids: List[str]
    data: Dict[str, Any]
    priority: int = 50
    flagged: bool = False
    source_candidate_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["section_type"] = self.section_type.value
        return d


@dataclass
class SectionGroup:
    group_id: str
    group_title: str
    sections: List[AutonomousSection] = field(default_factory=list)
    synthesis_insight: Optional[SynthesisInsight] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["sections"] = [s.to_dict() for s in self.sections]
        d["synthesis_insight"] = self.synthesis_insight.to_dict() if self.synthesis_insight else None
        return d


@dataclass
class InvestigationReport:
    dataset_id: str
    dataset_fingerprint: str
    dataset_name: str
    status: str
    section_groups: List[SectionGroup] = field(default_factory=list)
    synthesis_text: str = ""
    total_investigations: int = 0
    successful_investigations: int = 0
    failed_investigations: int = 0
    complexity_tier: str = "normal"
    generated_at: str = ""
    llm_planner_model: str = ""

    @classmethod
    def failed_report(cls, dataset_id: str, fingerprint: str, name: str, error: str) -> InvestigationReport:
        return cls(
            dataset_id=dataset_id,
            dataset_fingerprint=fingerprint,
            dataset_name=name,
            status="failed",
            synthesis_text=error
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["section_groups"] = [sg.to_dict() for sg in self.section_groups]
        return d
