"""
autonomous_analysis/presentation_builder.py

Presentation Builder — composes N investigation results into M grouped sections.

Rules:
  - 1 InvestigationResult != necessarily 1 section
  - Groups related results by thematic area (column overlap, analysis type)
  - Selects section_type primitives based on result characteristics
  - NO fixed template (no Overview/Statistics/Insights/Recommendations)
  - Dynamic composition based on available evidence
  - All data in sections comes from verified result_data (never invented)
"""
from __future__ import annotations

import uuid
from typing import List, Dict

from autonomous_analysis.contracts import (
    InvestigationResult, SynthesisInsight, SectionGroup, 
    AutonomousSection, AnalysisType, SectionType
)

SECTION_TYPE_MAP = {
    AnalysisType.SUMMARY_STATISTICS: SectionType.STATISTICS,
    AnalysisType.DISTRIBUTION: SectionType.DISTRIBUTION,
    AnalysisType.OUTLIER_DETECTION: SectionType.OUTLIER_LIST,
    AnalysisType.TEMPORAL_TREND: SectionType.CHART,
    AnalysisType.TEMPORAL_COVERAGE: SectionType.METRIC_GROUP,
    AnalysisType.TEMPORAL_GAPS: SectionType.WARNING,
    AnalysisType.GROUP_COMPARISON: SectionType.TABLE,
    AnalysisType.CONCENTRATION_ANALYSIS: SectionType.FINDING,
    AnalysisType.CORRELATION: SectionType.RELATIONSHIP,
    AnalysisType.MISSINGNESS_ANALYSIS: SectionType.MISSINGNESS,
    AnalysisType.DUPLICATE_ANALYSIS: SectionType.DATA_QUALITY,
    AnalysisType.TOP_N_ANALYSIS: SectionType.RANKING,
    AnalysisType.FREQUENCY_ANALYSIS: SectionType.CHART,
    AnalysisType.VOLATILITY: SectionType.CHART,
    AnalysisType.IDENTIFIER_QUALITY: SectionType.IDENTIFIER,
}

def _group_title(results: List[InvestigationResult], group_key: str) -> str:
    if group_key == "Data Quality":
        return "Data Quality"
    elif group_key == "Temporal Analysis":
        return "Temporal Analysis"
    elif group_key == "Relationships":
        return "Relationships"
    elif group_key:
        return f"{group_key} Analysis"
    else:
        return "General Findings"

def _priority(result: InvestigationResult) -> int:
    # Lower = shown first
    base = {
        'identifier_quality': 5, 'summary_statistics': 10, 'temporal_trend': 15,
        'group_comparison': 20, 'correlation': 25, 'distribution': 30,
        'top_n_analysis': 35, 'outlier_detection': 40, 'concentration_analysis': 45,
        'frequency_analysis': 50, 'temporal_coverage': 55,
        'volatility': 60, 'temporal_gaps': 65,
        'missingness_analysis': 70, 'duplicate_analysis': 75,
    }
    return base.get(result.analysis_type.value, 50)

def _section_title(result: InvestigationResult) -> str:
    type_titles = {
        'summary_statistics': f"{result.columns[0]} Statistics" if result.columns else "Summary Statistics",
        'distribution': f"{result.columns[0]} Distribution" if result.columns else "Distribution",
        'outlier_detection': f"Outliers in {result.columns[0]}" if result.columns else "Outlier Detection",
        'temporal_trend': f"{result.columns[1]} Over Time" if len(result.columns) > 1 else "Temporal Trend",
        'group_comparison': f"{result.columns[1]} by {result.columns[0]}" if len(result.columns) > 1 else "Group Comparison",
        'correlation': f"{result.columns[0]} vs {result.columns[1]}" if len(result.columns) > 1 else "Correlation",
        'missingness_analysis': "Missing Data",
        'duplicate_analysis': "Duplicate Rows",
        'concentration_analysis': f"{result.columns[0]} Concentration" if result.columns else "Concentration",
        'frequency_analysis': f"{result.columns[0]} Frequency" if result.columns else "Frequency",
        'top_n_analysis': f"Top {result.columns[0]}" if result.columns else "Top Values",
        'temporal_coverage': "Date Coverage",
        'temporal_gaps': "Temporal Gaps",
        'volatility': f"{result.columns[1]} Volatility" if len(result.columns) > 1 else "Volatility",
        'identifier_quality': f"Identifier Quality — {result.columns[0]}" if result.columns else "Identifier Quality",
    }
    return type_titles.get(result.analysis_type.value, result.analysis_type.value.replace('_', ' ').title())


class PresentationBuilder:
    def _group_results(self, results: List[InvestigationResult]) -> Dict[str, List[InvestigationResult]]:
        groups = {}
        for r in results:
            if r.analysis_type in [AnalysisType.MISSINGNESS_ANALYSIS, AnalysisType.DUPLICATE_ANALYSIS]:
                groups.setdefault("Data Quality", []).append(r)
            elif r.analysis_type in [AnalysisType.TEMPORAL_TREND, AnalysisType.TEMPORAL_COVERAGE, AnalysisType.TEMPORAL_GAPS, AnalysisType.VOLATILITY]:
                groups.setdefault("Temporal Analysis", []).append(r)
            elif r.analysis_type in [AnalysisType.CORRELATION]:
                groups.setdefault("Relationships", []).append(r)
            elif r.columns:
                primary_col = r.columns[0]
                groups.setdefault(primary_col, []).append(r)
            else:
                groups.setdefault("General", []).append(r)
        return groups

    def build(self, results: List[InvestigationResult], synthesis_insights: List[SynthesisInsight], dataset_context: dict) -> List[SectionGroup]:
        successful_results = [r for r in results if r.status != "failed"]
        grouped_results = self._group_results(successful_results)
        
        section_groups = []
        for key, group_res in grouped_results.items():
            g_title = _group_title(group_res, key)
            sections = []
            
            for result in group_res:
                section = AutonomousSection(
                    section_id=str(uuid.uuid4()),
                    section_type=SECTION_TYPE_MAP.get(result.analysis_type, SectionType.FINDING),
                    group_title=g_title,
                    title=_section_title(result),
                    interpretation=result.interpretation,
                    evidence_ids=[result.evidence.id] if result.evidence else [],
                    data=result.result_data,
                    priority=_priority(result),
                    flagged=result.interpretation_flagged,
                    source_candidate_ids=[result.candidate_id]
                )
                sections.append(section)
            
            sections.sort(key=lambda s: s.priority)
            
            group_candidate_ids = set(r.candidate_id for r in group_res)
            matched_insight = None
            for insight in synthesis_insights:
                if any(c_id in group_candidate_ids for c_id in insight.related_candidate_ids):
                    matched_insight = insight
                    break
            
            sg = SectionGroup(
                group_id=str(uuid.uuid4()),
                group_title=g_title,
                sections=sections,
                synthesis_insight=matched_insight
            )
            section_groups.append(sg)
            
        # Sort groups by the minimum priority of their sections
        section_groups.sort(key=lambda sg: min((s.priority for s in sg.sections), default=999))
        
        return section_groups

presentation_builder = PresentationBuilder()
