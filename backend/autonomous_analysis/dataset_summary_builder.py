from typing import Dict, Any

from dataset_intelligence.models_v2 import DatasetKnowledgeObject
from dataset_intelligence.models import ColumnSemanticType


class DatasetSummaryBuilder:
    def build(self, dko: DatasetKnowledgeObject) -> Dict[str, Any]:
        pii_types = {
            ColumnSemanticType.EMAIL.value,
            ColumnSemanticType.PHONE.value,
            ColumnSemanticType.NAME.value,
            ColumnSemanticType.UUID.value,
            ColumnSemanticType.ADDRESS.value,
        }

        columns_summary = []
        temporal_summary = None
        has_temporal = False

        for col_name in sorted(dko.columns.keys()):
            col = dko.columns[col_name]
            if col.semantic_type.value in pii_types:
                continue

            col_info = {
                "name": col.name,
                "dtype": col.dtype_category,
                "role": col.role.value,
                "semantic_type": col.semantic_type.value,
                "unique_count": col.unique_count,
                "null_pct": col.null_pct,
                "is_constant": col.is_constant,
            }

            if col.numeric_stats:
                col_info.update({
                    "min": col.numeric_stats.min,
                    "max": col.numeric_stats.max,
                    "mean": col.numeric_stats.mean,
                    "skewness": col.numeric_stats.skewness,
                    "outlier_count": col.numeric_stats.outlier_count
                })
            elif col.categorical_stats:
                col_info.update({
                    "cardinality": col.categorical_stats.cardinality,
                    "top_values": col.categorical_stats.top_values[:5] if col.categorical_stats.top_values else []
                })
            elif col.datetime_stats:
                col_info.update({
                    "min_date": col.datetime_stats.min_date,
                    "max_date": col.datetime_stats.max_date,
                    "granularity": col.datetime_stats.granularity
                })
                if temporal_summary is None:
                    has_temporal = True
                    temporal_summary = {
                        "column": col.name,
                        "min_date": col.datetime_stats.min_date,
                        "max_date": col.datetime_stats.max_date,
                        "range_days": col.datetime_stats.range_days,
                        "granularity": col.datetime_stats.granularity,
                        "has_gaps": col.datetime_stats.has_gaps
                    }

            columns_summary.append(col_info)

        has_relationships = bool(dko.knowledge_graph and dko.knowledge_graph.correlations)

        quality_issues = []
        if dko.quality_report and dko.quality_report.issues:
            sorted_issues = sorted(dko.quality_report.issues, key=lambda i: getattr(i, 'impact_score', 0), reverse=True)
            for issue in sorted_issues[:3]:
                quality_issues.append({
                    "type": issue.issue_type.value if hasattr(issue.issue_type, 'value') else str(issue.issue_type),
                    "severity": issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity),
                    "columns": issue.affected_columns,
                    "description": issue.description
                })

        relationships = []
        if dko.knowledge_graph and dko.knowledge_graph.correlations:
            sorted_correlations = sorted(dko.knowledge_graph.correlations, key=lambda c: abs(c.pearson_r) if hasattr(c, 'pearson_r') else 0, reverse=True)
            for corr in sorted_correlations[:3]:
                relationships.append({
                    "col_a": corr.col_a,
                    "col_b": corr.col_b,
                    "strength": corr.strength
                })

        dataset_dict = {
            "name": dko.dataset_name,
            "rows": dko.row_count,
            "columns_count": dko.column_count,
            "domain": getattr(getattr(dko.domain, 'domain', None), 'value', str(dko.domain)) if dko.domain else None,
            "quality_score": dko.quality_report.overall_score if dko.quality_report else None,
            "readiness": dko.quality_report.analysis_readiness if dko.quality_report else None,
            "has_temporal": has_temporal,
            "has_relationships": has_relationships,
        }

        capabilities = []
        if dko.capabilities:
            if isinstance(dko.capabilities, list):
                capabilities = [c.value if hasattr(c, 'value') else str(c) for c in dko.capabilities]
            else:
                capabilities = [str(dko.capabilities)]

        return {
            "dataset": dataset_dict,
            "columns": columns_summary,
            "quality_issues": quality_issues,
            "relationships": relationships,
            "temporal": temporal_summary,
            "capabilities": capabilities
        }


dataset_summary_builder = DatasetSummaryBuilder()
