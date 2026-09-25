"""
Dataset Intelligence Engine — Stage 3: Quality Intelligence

Produces a comprehensive data quality assessment of the dataset,
including a 0-100 DataQualityScore with supporting evidence.

All detection is deterministic Python — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from .models import (
    ColumnSchema, ColumnStats, InsightSeverity, QualityIssue, QualityIssueType, QualityReport
)
from .utils import clamp, score_to_label, get_working_sample

logger = logging.getLogger(__name__)


class QualityIntelligenceStage:
    """
    Stage 3 — Quality Intelligence

    Detects: missing values, duplicates, constant columns, high cardinality,
    mixed types, whitespace issues, outliers, and more.

    Computes a composite DataQualityScore from:
      - Completeness (missing values)
      - Uniqueness (duplicate rows)
      - Consistency (type/format issues)
    """

    def analyze(self, df: pd.DataFrame, schemas: List[ColumnSchema], column_stats: Dict[str, ColumnStats]) -> QualityReport:
        """
        Run all quality checks and return a QualityReport.

        Args:
            df: The full DataFrame
            schemas: Stage 1 outputs
            column_stats: Stage 2 outputs

        Returns:
            A populated QualityReport.
        """
        sample = get_working_sample(df)
        total = len(sample)
        num_columns = len(df.columns)
        logger.info(f"QualityIntelligenceStage: running quality checks on {total:,} rows x {num_columns} cols")

        issues: List[QualityIssue] = []
        columns_with_issues: List[str] = []

        # --- 1. Missing Values ---
        total_cells = total * num_columns
        total_missing = int(sample.isna().sum().sum())
        missing_pct = round((total_missing / total_cells) * 100, 2) if total_cells > 0 else 0.0
        completeness_score = clamp(100.0 - missing_pct * 2)

        for schema in schemas:
            col_stat = column_stats.get(schema.name)
            if col_stat and col_stat.null_pct > 0:
                columns_with_issues.append(schema.name)
                if col_stat.null_pct > 50:
                    issues.append(QualityIssue(
                        issue_type=QualityIssueType.MISSING_VALUES,
                        severity=InsightSeverity.CRITICAL,
                        affected_columns=[schema.name],
                        description=f"'{schema.name}' is {col_stat.null_pct:.1f}% missing — this column may not be usable for analysis.",
                        recommendation=f"Consider removing '{schema.name}' or imputing values before analysis.",
                        impact_score=8.0,
                    ))
                elif col_stat.null_pct > 20:
                    issues.append(QualityIssue(
                        issue_type=QualityIssueType.MISSING_VALUES,
                        severity=InsightSeverity.HIGH,
                        affected_columns=[schema.name],
                        description=f"'{schema.name}' has {col_stat.null_pct:.1f}% missing values.",
                        recommendation=f"Review missing values in '{schema.name}' — they may affect aggregation results.",
                        impact_score=5.0,
                    ))
                elif col_stat.null_pct > 5:
                    issues.append(QualityIssue(
                        issue_type=QualityIssueType.MISSING_VALUES,
                        severity=InsightSeverity.MEDIUM,
                        affected_columns=[schema.name],
                        description=f"'{schema.name}' has {col_stat.null_pct:.1f}% missing values.",
                        recommendation=f"Missing values in '{schema.name}' may affect some analyses.",
                        impact_score=2.0,
                    ))

        # --- 2. Duplicate Rows ---
        duplicate_rows = int(sample.duplicated().sum())
        duplicate_row_pct = round((duplicate_rows / total) * 100, 2) if total > 0 else 0.0
        uniqueness_score = clamp(100.0 - duplicate_row_pct * 5)

        if duplicate_rows > 0:
            severity = InsightSeverity.HIGH if duplicate_row_pct > 10 else InsightSeverity.MEDIUM
            issues.append(QualityIssue(
                issue_type=QualityIssueType.DUPLICATE_ROWS,
                severity=severity,
                affected_columns=[],
                description=f"Dataset contains {duplicate_rows:,} duplicate rows ({duplicate_row_pct:.1f}%).",
                recommendation="Remove or investigate duplicate rows before running aggregations.",
                impact_score=6.0 if duplicate_row_pct > 10 else 3.0,
            ))

        # --- 3. Constant Columns ---
        constant_cols = [s.name for s in schemas if s.is_constant]
        if constant_cols:
            for col in constant_cols:
                if col not in columns_with_issues:
                    columns_with_issues.append(col)
                issues.append(QualityIssue(
                    issue_type=QualityIssueType.CONSTANT_COLUMN,
                    severity=InsightSeverity.HIGH,
                    affected_columns=[col],
                    description=f"'{col}' has only one unique value and provides no analytical information.",
                    recommendation=f"Remove '{col}' — it adds no value to analysis.",
                    impact_score=4.0,
                ))

        # --- 4. Near-Constant Columns ---
        for schema in schemas:
            col_stat = column_stats.get(schema.name)
            if col_stat and col_stat.categorical:
                dominant_pct = col_stat.categorical.dominant_pct
                if dominant_pct > 95 and not schema.is_constant:
                    if schema.name not in columns_with_issues:
                        columns_with_issues.append(schema.name)
                    issues.append(QualityIssue(
                        issue_type=QualityIssueType.NEAR_CONSTANT,
                        severity=InsightSeverity.MEDIUM,
                        affected_columns=[schema.name],
                        description=f"'{schema.name}' is {dominant_pct:.1f}% dominated by one value — low analytical variation.",
                        recommendation=f"'{schema.name}' may not be useful as a grouping dimension.",
                        impact_score=2.0,
                    ))

        # --- 5. High Cardinality Dimensions ---
        for schema in schemas:
            col_stat = column_stats.get(schema.name)
            if col_stat and col_stat.categorical and col_stat.categorical.is_high_cardinality:
                if schema.name not in columns_with_issues:
                    columns_with_issues.append(schema.name)
                issues.append(QualityIssue(
                    issue_type=QualityIssueType.HIGH_CARDINALITY,
                    severity=InsightSeverity.LOW,
                    affected_columns=[schema.name],
                    description=f"'{schema.name}' has very high cardinality ({col_stat.distinct_count} unique values) — may not be suitable as a grouping dimension.",
                    recommendation=f"Consider bucketing '{schema.name}' into fewer categories for aggregation.",
                    impact_score=1.5,
                ))

        # --- 6. Whitespace / Encoding Issues ---
        for schema in schemas:
            if schema.dtype_category in ("text", "categorical"):
                try:
                    col_series = sample[schema.name].dropna().astype(str)
                    has_leading_trailing = (col_series != col_series.str.strip()).any()
                    if has_leading_trailing:
                        if schema.name not in columns_with_issues:
                            columns_with_issues.append(schema.name)
                        issues.append(QualityIssue(
                            issue_type=QualityIssueType.WHITESPACE_ISSUES,
                            severity=InsightSeverity.LOW,
                            affected_columns=[schema.name],
                            description=f"'{schema.name}' has values with leading or trailing whitespace.",
                            recommendation=f"Apply str.strip() to '{schema.name}' before analysis to avoid grouping inconsistencies.",
                            impact_score=1.0,
                        ))
                except Exception:
                    pass

        # --- 7. Outliers in Numeric Columns ---
        for schema in schemas:
            col_stat = column_stats.get(schema.name)
            if col_stat and col_stat.numeric and col_stat.numeric.outlier_pct > 5:
                if schema.name not in columns_with_issues:
                    columns_with_issues.append(schema.name)
                issues.append(QualityIssue(
                    issue_type=QualityIssueType.OUTLIERS,
                    severity=InsightSeverity.MEDIUM,
                    affected_columns=[schema.name],
                    description=f"'{schema.name}' has {col_stat.numeric.outlier_count} outliers ({col_stat.numeric.outlier_pct:.1f}%) — they may distort mean calculations.",
                    recommendation=f"Review outliers in '{schema.name}'. Consider using median instead of mean.",
                    impact_score=3.0,
                ))

        # --- 8. Suspicious Negative Values ---
        non_negative_keywords = ['revenue', 'price', 'quantity', 'count', 'age', 'score', 'amount', 'sales']
        for schema in schemas:
            col_stat = column_stats.get(schema.name)
            if col_stat and col_stat.numeric and col_stat.numeric.negative_count > 0:
                col_lower = schema.name.lower()
                if any(kw in col_lower for kw in non_negative_keywords):
                    if schema.name not in columns_with_issues:
                        columns_with_issues.append(schema.name)
                    issues.append(QualityIssue(
                        issue_type=QualityIssueType.NEGATIVE_VALUES,
                        severity=InsightSeverity.MEDIUM,
                        affected_columns=[schema.name],
                        description=f"'{schema.name}' contains {col_stat.numeric.negative_count} negative values, which may be unexpected for this type of column.",
                        recommendation=f"Verify that negative values in '{schema.name}' are intentional (e.g., returns, corrections).",
                        impact_score=2.5,
                    ))

        # --- Compute Consistency Score ---
        type_issues = [i for i in issues if i.issue_type in (
            QualityIssueType.WHITESPACE_ISSUES, QualityIssueType.MIXED_TYPES,
            QualityIssueType.ENCODING_ISSUES, QualityIssueType.CASE_INCONSISTENCY
        )]
        consistency_score = clamp(100.0 - len(type_issues) * 5)

        # --- Composite Quality Score ---
        overall_score = clamp(
            (completeness_score * 0.5) +
            (uniqueness_score * 0.3) +
            (consistency_score * 0.2)
        )
        overall_score = round(overall_score, 1)

        return QualityReport(
            overall_score=overall_score,
            completeness_score=round(completeness_score, 1),
            consistency_score=round(consistency_score, 1),
            uniqueness_score=round(uniqueness_score, 1),
            issues=sorted(issues, key=lambda x: x.impact_score, reverse=True),
            duplicate_row_count=duplicate_rows,
            duplicate_row_pct=duplicate_row_pct,
            total_missing_cells=total_missing,
            total_missing_pct=missing_pct,
            columns_with_issues=list(set(columns_with_issues)),
            analysis_readiness=score_to_label(overall_score),
        )


quality_intelligence_stage = QualityIntelligenceStage()
