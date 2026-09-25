from typing import List, Dict, Set
from autonomous_analysis.contracts import (
    AnalysisType, CandidateCost, ColumnRequirement, CandidatePrerequisites,
    CandidateScore, AnalysisCandidate, AnalysisBudget
)
from dataset_intelligence.models_v2 import DatasetKnowledgeObject
from dataset_intelligence.models import ColumnRole
import logging
logger = logging.getLogger(__name__)


def _make_id(analysis_type: AnalysisType, columns: List[str]) -> str:
    col_slug = "_".join(c.lower()[:12].replace(" ", "_") for c in columns[:2])
    return f"{analysis_type.value}__{col_slug}" if col_slug else analysis_type.value


# Normalize raw DKO dtype_category strings to the canonical set used throughout
# the candidate generator and filter.
#
# The DKO stores raw pandas/schema dtypes like 'float', 'integer', 'int64',
# 'object', 'string', etc. The candidate system expects the canonical strings:
# 'numeric', 'categorical', 'datetime', 'boolean'.
#
_NUMERIC_DTYPES = {
    "numeric", "float", "int", "integer", "float64", "float32",
    "int64", "int32", "int16", "int8", "uint64", "uint32", "number",
    "double", "decimal",
}
_CATEGORICAL_DTYPES = {
    "categorical", "category", "object", "string", "str", "text",
    "varchar", "char", "nvarchar",
}
_DATETIME_DTYPES = {
    "datetime", "date", "time", "timestamp", "datetime64",
    "datetime64[ns]", "datetime64[us]",
}
_BOOLEAN_DTYPES = {"bool", "boolean"}


def _normalize_dtype(dtype_category: str) -> str:
    """
    Map raw dtype_category from the DKO to the canonical candidate-system strings.

    Returns one of: 'numeric', 'categorical', 'datetime', 'boolean', or 'unknown'.
    """
    raw = (dtype_category or "").lower().strip()
    if raw in _NUMERIC_DTYPES:
        return "numeric"
    if raw in _CATEGORICAL_DTYPES:
        return "categorical"
    if raw in _DATETIME_DTYPES:
        return "datetime"
    if raw in _BOOLEAN_DTYPES:
        return "boolean"
    return "unknown"

class CandidateGenerator:
    def generate(self, dko: DatasetKnowledgeObject) -> List[AnalysisCandidate]:
        candidates = []

        # ── Diagnostic logging ───────────────────────────────────────────────
        # Use normalized dtypes for accurate field classification
        _diag_numeric = [c.name for c in dko.columns.values() if _normalize_dtype(c.dtype_category) == "numeric"]
        _diag_categorical = [c.name for c in dko.columns.values() if _normalize_dtype(c.dtype_category) == "categorical" and c.unique_count > 1]
        _diag_datetime = [c.name for c in dko.columns.values() if _normalize_dtype(c.dtype_category) == "datetime" or c.role == ColumnRole.TIME]
        _diag_missing_cells = sum(c.null_count for c in dko.columns.values())
        _diag_semantic = [(c.name, c.role.value, c.dtype_category, _normalize_dtype(c.dtype_category)) for c in dko.columns.values()]
        logger.info(
            "[InvestigationCandidateGenerator] dataset_id=%s rows=%d columns=%d "
            "numeric_fields=%s categorical_fields=%s datetime_fields=%s "
            "missing_cells=%d semantic_fields(name,role,raw_dtype,normalized)=%s",
            getattr(dko, 'fingerprint', 'unknown'),
            dko.row_count, dko.column_count,
            _diag_numeric, _diag_categorical, _diag_datetime,
            _diag_missing_cells, _diag_semantic,
        )

        prereqs = {
            AnalysisType.TEMPORAL_TREND: CandidatePrerequisites(
                column_requirements=[
                    ColumnRequirement(dtype_category="datetime"),
                    ColumnRequirement(dtype_category="numeric", min_non_null_pct=0.5)
                ]
            ),
            AnalysisType.VOLATILITY: CandidatePrerequisites(
                column_requirements=[
                    ColumnRequirement(dtype_category="datetime", must_be_ordered=True),
                    ColumnRequirement(dtype_category="numeric", min_non_null_pct=0.5)
                ]
            ),
            AnalysisType.GROUP_COMPARISON: CandidatePrerequisites(
                column_requirements=[
                    ColumnRequirement(dtype_category="categorical", min_cardinality=2, max_cardinality=50),
                    ColumnRequirement(dtype_category="numeric")
                ]
            ),
            AnalysisType.CORRELATION: CandidatePrerequisites(
                column_requirements=[
                    ColumnRequirement(dtype_category="numeric"),
                    ColumnRequirement(dtype_category="numeric")
                ]
            ),
            AnalysisType.DISTRIBUTION: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="numeric")]
            ),
            AnalysisType.OUTLIER_DETECTION: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="numeric")]
            ),
            AnalysisType.SUMMARY_STATISTICS: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="numeric")]
            ),
            AnalysisType.CONCENTRATION_ANALYSIS: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="categorical", min_cardinality=2)]
            ),
            AnalysisType.TOP_N_ANALYSIS: CandidatePrerequisites(
                column_requirements=[
                    ColumnRequirement(dtype_category="numeric"),
                    ColumnRequirement(dtype_category="categorical")
                ]
            ),
            AnalysisType.TEMPORAL_COVERAGE: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="datetime")]
            ),
            AnalysisType.TEMPORAL_GAPS: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="datetime")]
            ),
            AnalysisType.MISSINGNESS_ANALYSIS: CandidatePrerequisites(
                column_requirements=[],
                dataset_level=["missing_values"]
            ),
            AnalysisType.DUPLICATE_ANALYSIS: CandidatePrerequisites(
                column_requirements=[],
                dataset_level=["duplicate_rows"]
            ),
            AnalysisType.FREQUENCY_ANALYSIS: CandidatePrerequisites(
                column_requirements=[ColumnRequirement(dtype_category="categorical", min_cardinality=2, max_cardinality=100)]
            ),
            AnalysisType.IDENTIFIER_QUALITY: CandidatePrerequisites(
                column_requirements=[],  # any column type
            ),
        }

        cost_map = {
            AnalysisType.DISTRIBUTION: (CandidateCost.LOW, 1),
            AnalysisType.SUMMARY_STATISTICS: (CandidateCost.LOW, 1),
            AnalysisType.FREQUENCY_ANALYSIS: (CandidateCost.LOW, 1),
            AnalysisType.CONCENTRATION_ANALYSIS: (CandidateCost.LOW, 1),
            AnalysisType.TEMPORAL_COVERAGE: (CandidateCost.LOW, 1),
            AnalysisType.MISSINGNESS_ANALYSIS: (CandidateCost.LOW, 1),
            AnalysisType.DUPLICATE_ANALYSIS: (CandidateCost.LOW, 1),
            AnalysisType.IDENTIFIER_QUALITY: (CandidateCost.LOW, 1),
            
            AnalysisType.GROUP_COMPARISON: (CandidateCost.MEDIUM, 3),
            AnalysisType.TOP_N_ANALYSIS: (CandidateCost.MEDIUM, 3),
            AnalysisType.OUTLIER_DETECTION: (CandidateCost.MEDIUM, 3),
            AnalysisType.TEMPORAL_GAPS: (CandidateCost.MEDIUM, 3),
            AnalysisType.CORRELATION: (CandidateCost.MEDIUM, 3),
            
            AnalysisType.TEMPORAL_TREND: (CandidateCost.HIGH, 8),
            AnalysisType.VOLATILITY: (CandidateCost.HIGH, 8),
        }

        def add_candidate(atype: AnalysisType, cols: List[str], r_group: str = ""):
            cost_enum, cost_units = cost_map[atype]
            candidates.append(AnalysisCandidate(
                candidate_id=_make_id(atype, cols),
                analysis_type=atype,
                columns=cols,
                prerequisites=prereqs[atype],
                estimated_cost=cost_enum,
                estimated_cost_units=cost_units,
                redundancy_group=r_group or atype.value
            ))

        numeric_cols = []
        categorical_cols = []
        datetime_cols = []
        metric_cols = []

        for col in dko.columns.values():
            _norm = _normalize_dtype(col.dtype_category)
            if _norm == "numeric":
                numeric_cols.append(col)
                if col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.ACADEMIC, ColumnRole.HEALTHCARE):
                    metric_cols.append(col)
            elif _norm == "categorical" and col.unique_count > 1:
                categorical_cols.append(col)

            if _norm == "datetime" or col.role == ColumnRole.TIME:
                datetime_cols.append(col)

        # Also include GEOGRAPHIC / DIMENSION / ATTRIBUTE-role columns that were
        # tagged with dtype_category='unknown' (e.g., city, country, category) as
        # effective categorical columns for GROUP_COMPARISON and FREQUENCY_ANALYSIS.
        _CATEGORICAL_ROLES = {r for r in [
            getattr(ColumnRole, 'DIMENSION', None),
            getattr(ColumnRole, 'GEOGRAPHIC', None),
            getattr(ColumnRole, 'ATTRIBUTE', None),
        ] if r is not None}

        for col in dko.columns.values():
            _norm = _normalize_dtype(col.dtype_category)
            if _norm not in ("numeric", "categorical", "datetime", "boolean") and col.unique_count > 1:
                # dtype is 'unknown' — use role as secondary signal
                if col.role in _CATEGORICAL_ROLES:
                    if col not in categorical_cols:
                        categorical_cols.append(col)

        best_cat_col = max(categorical_cols, key=lambda c: c.unique_count) if categorical_cols else None


        # ── Identifier columns → IDENTIFIER_QUALITY (not distribution/stats) ──
        _IDENTIFIER_ROLES = {r for r in [
            getattr(ColumnRole, 'IDENTIFIER', None),
            getattr(ColumnRole, 'UUID', None),
        ] if r is not None}

        for col in numeric_cols:
            is_identifier = col.role in _IDENTIFIER_ROLES or getattr(col, 'is_unique', False)

            if is_identifier:
                # Identifiers get quality analysis, NOT distribution/summary
                add_candidate(AnalysisType.IDENTIFIER_QUALITY, [col.name], f"idqual_{col.name}")
                continue

            add_candidate(AnalysisType.DISTRIBUTION, [col.name], f"dist_{col.name}")
            
            if col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.ACADEMIC, ColumnRole.HEALTHCARE):
                add_candidate(AnalysisType.SUMMARY_STATISTICS, [col.name], f"summ_{col.name}")
                
            if col.numeric_stats and col.numeric_stats.outlier_pct > 0:
                add_candidate(AnalysisType.OUTLIER_DETECTION, [col.name], f"outlier_{col.name}")
                
            if best_cat_col and col in metric_cols:
                add_candidate(AnalysisType.TOP_N_ANALYSIS, [col.name, best_cat_col.name], f"topn_{col.name}_{best_cat_col.name}")

        for col in categorical_cols:
            add_candidate(AnalysisType.FREQUENCY_ANALYSIS, [col.name], f"freq_{col.name}")
            if col.categorical_stats and col.categorical_stats.dominant_pct > 30:
                add_candidate(AnalysisType.CONCENTRATION_ANALYSIS, [col.name], f"conc_{col.name}")

        for dt_col in datetime_cols:
            add_candidate(AnalysisType.TEMPORAL_COVERAGE, [dt_col.name], f"temp_cov_{dt_col.name}")
            
            if dt_col.datetime_stats and dt_col.datetime_stats.has_gaps:
                add_candidate(AnalysisType.TEMPORAL_GAPS, [dt_col.name], f"temp_gaps_{dt_col.name}")
                
            for m_col in metric_cols:
                add_candidate(AnalysisType.TEMPORAL_TREND, [dt_col.name, m_col.name], f"trend_{dt_col.name}_{m_col.name}")
                
                if dt_col.datetime_stats and dt_col.datetime_stats.range_days is not None and dt_col.datetime_stats.range_days > 6 and dt_col.datetime_stats.granularity != "unknown":
                    add_candidate(AnalysisType.VOLATILITY, [dt_col.name, m_col.name], f"vol_{dt_col.name}_{m_col.name}")

        corr_pairs = 0
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                if corr_pairs >= 6:
                    break
                c1, c2 = numeric_cols[i], numeric_cols[j]
                if c1.role == ColumnRole.IDENTIFIER or c1.is_constant or c2.role == ColumnRole.IDENTIFIER or c2.is_constant:
                    continue
                add_candidate(AnalysisType.CORRELATION, [c1.name, c2.name], f"corr_{c1.name}_{c2.name}")
                corr_pairs += 1

        for cat_col in categorical_cols:
            if 2 <= cat_col.unique_count <= 50:
                for m_col in metric_cols:
                    add_candidate(AnalysisType.GROUP_COMPARISON, [cat_col.name, m_col.name], f"group_{cat_col.name}_{m_col.name}")

        if dko.quality_report:
            issues = [issue.issue_type.value for issue in dko.quality_report.issues]
            if "missing_values" in issues:
                add_candidate(AnalysisType.MISSINGNESS_ANALYSIS, [], "quality_missing")
            if "duplicate_rows" in issues:
                add_candidate(AnalysisType.DUPLICATE_ANALYSIS, [], "quality_dupes")

        # Fallback: check missing values directly from column null counts
        # in case quality_report doesn't explicitly flag "missing_values"
        if not any(c.redundancy_group == "quality_missing" for c in candidates):
            _total_missing = sum(c.null_count for c in dko.columns.values())
            if _total_missing > 0:
                logger.debug(
                    "[InvestigationCandidateGenerator] Adding MISSINGNESS via direct scan: %d missing cells",
                    _total_missing
                )
                add_candidate(AnalysisType.MISSINGNESS_ANALYSIS, [], "quality_missing")

        logger.info(
            "[InvestigationCandidateGenerator] TOTAL candidates=%d fingerprint=%s",
            len(candidates), getattr(dko, 'fingerprint', 'unknown')
        )
        return candidates

candidate_generator = CandidateGenerator()
