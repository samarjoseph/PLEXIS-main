import concurrent.futures
import time
import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np

from autonomous_analysis.contracts import (
    AnalysisType, AnalysisCandidate, InvestigationPlan, PlannedInvestigation,
    InvestigationResult, NumericalGrounding, AnalysisBudget, CandidateCost
)
from evidence.contracts import EvidenceReference, EvidenceType
from dataset_intelligence.models_v2 import DatasetKnowledgeObject

logger = logging.getLogger(__name__)

class AutonomousExecutor:
    def execute_plan(
        self,
        plan: InvestigationPlan,
        candidates_dict: Dict[str, AnalysisCandidate],
        df: pd.DataFrame,
        dko: DatasetKnowledgeObject,
        budget: AnalysisBudget
    ) -> List[InvestigationResult]:
        
        investigations = sorted(plan.investigations, key=lambda x: x.priority)
        
        low_med = []
        high = []
        
        for inv in investigations:
            cand = candidates_dict.get(inv.candidate_id)
            if not cand:
                continue
            if cand.estimated_cost == CandidateCost.HIGH:
                high.append(cand)
            else:
                low_med.append(cand)
                
        results = []
        start_time = time.time()
        
        # Parallel for LOW/MEDIUM cost
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._execute_one, cand, df, dko, budget.per_analysis_timeout_s): cand
                for cand in low_med
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                
        # Sequential for HIGH cost
        for cand in high:
            elapsed = time.time() - start_time
            if elapsed >= budget.total_wall_budget_s:
                break
            res = self._execute_one(cand, df, dko, budget.per_analysis_timeout_s)
            results.append(res)
            
        return results

    def _execute_one(self, candidate: AnalysisCandidate, df: pd.DataFrame, dko: DatasetKnowledgeObject, timeout_s: int) -> InvestigationResult:
        start_time = time.time()
        result_data = {}
        status = "success"
        error = None
        evidence = None
        
        try:
            op = candidate.analysis_type
            cols = candidate.columns
            
            if op == "summary_statistics":
                result_data = self._summary_statistics(cols, df)
            elif op == "distribution":
                result_data = self._distribution(cols, df)
            elif op == "outlier_detection":
                result_data = self._outlier_detection(cols, df)
            elif op == "temporal_trend":
                result_data = self._temporal_trend(cols, df)
            elif op == "temporal_coverage":
                result_data = self._temporal_coverage(cols, df)
            elif op == "temporal_gaps":
                result_data = self._temporal_gaps(cols, df)
            elif op == "group_comparison":
                result_data = self._group_comparison(cols, df)
            elif op == "concentration_analysis":
                result_data = self._concentration_analysis(cols, df)
            elif op == "correlation":
                result_data = self._correlation(cols, df)
            elif op == "missingness_analysis":
                result_data = self._missingness_analysis(cols, df)
            elif op == "duplicate_analysis":
                result_data = self._duplicate_analysis(cols, df)
            elif op == "top_n_analysis":
                result_data = self._top_n_analysis(cols, df)
            elif op == "frequency_analysis":
                result_data = self._frequency_analysis(cols, df)
            elif op == "volatility":
                result_data = self._volatility(cols, df)
            elif op == "identifier_quality":
                result_data = self._identifier_quality(cols, df)
            else:
                raise ValueError(f"Unknown analysis_type {op}")
            
            evidence = self._build_evidence(candidate, result_data, dko)
                
        except Exception as e:
            status = "failed"
            error = str(e)
            logger.error(f"[AutonomousExecutor] {candidate.candidate_id} failed: {e}", exc_info=True)
            
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        return InvestigationResult(
            candidate_id=candidate.candidate_id,
            analysis_type=candidate.analysis_type,
            status=status,
            columns=candidate.columns,
            result_data=result_data,
            evidence=evidence,
            grounding=None,
            error=error,
            execution_time_ms=execution_time_ms,
            interpretation="",
            interpretation_flagged=False
        )

    # -------------------------------------------------------------------------
    # Safe Pandas Implementations
    # -------------------------------------------------------------------------

    def _summary_statistics(self, cols, df):
        col = cols[0]
        series = pd.to_numeric(df[col], errors='coerce')
        valid = series.dropna()
        total = len(df)
        valid_count = int(len(valid))
        missing_count = total - valid_count
        result = {
            "column": col,
            "valid_count": valid_count,
            "missing_count": missing_count,
            "missing_pct": round(float(missing_count / total * 100), 2) if total else 0.0,
        }
        if valid_count > 0:
            result.update({
                "mean": round(float(valid.mean()), 4),
                "median": round(float(valid.median()), 4),
                "std": round(float(valid.std()), 4),
                "min": float(valid.min()),
                "q1": float(valid.quantile(0.25)),
                "q3": float(valid.quantile(0.75)),
                "max": float(valid.max()),
                "skewness": round(float(valid.skew()), 4),
                "kurtosis": round(float(valid.kurtosis()), 4),
                "range_min": float(valid.min()),
                "range_max": float(valid.max()),
            })
        return result

    def _distribution(self, cols, df):
        col = cols[0]
        series = pd.to_numeric(df[col], errors='coerce')
        valid = series.dropna()
        total = len(df)
        valid_count = int(len(valid))
        missing_count = total - valid_count
        counts, bins = np.histogram(valid, bins=10)
        counts_list = [int(c) for c in counts]
        bins_list = [float(b) for b in bins]
        # Find the modal (largest) bin
        modal_idx = int(np.argmax(counts))
        modal_bin_label = f"{bins_list[modal_idx]:.1f}-{bins_list[modal_idx + 1]:.1f}"
        modal_bin_count = counts_list[modal_idx]
        return {
            "column": col,
            "counts": counts_list,
            "bins": bins_list,
            "skewness": round(float(valid.skew()), 4) if valid_count > 1 else 0.0,
            "kurtosis": round(float(valid.kurtosis()), 4) if valid_count > 3 else 0.0,
            "modal_bin_label": modal_bin_label,
            "modal_bin_count": modal_bin_count,
            # Inline stats for compact display
            "valid_count": valid_count,
            "missing_count": missing_count,
            "mean": round(float(valid.mean()), 2) if valid_count > 0 else None,
            "median": round(float(valid.median()), 2) if valid_count > 0 else None,
            "std": round(float(valid.std()), 2) if valid_count > 1 else None,
            "min": float(valid.min()) if valid_count > 0 else None,
            "max": float(valid.max()) if valid_count > 0 else None,
        }
        
    def _outlier_detection(self, cols, df):
        col = cols[0]
        series = pd.to_numeric(df[col], errors='coerce').dropna()
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = series[(series < lower) | (series > upper)]
        return {
            "outlier_count": int(len(outliers)),
            "outlier_pct": float(len(outliers) / len(df) * 100) if len(df) else 0.0,
            "fences": {"lower": float(lower), "upper": float(upper)},
            "extremes": [float(x) for x in outliers.head(10).tolist()]
        }
        
    def _temporal_trend(self, cols, df):
        if len(cols) < 2:
            return {}
        date_col = cols[0]
        val_col = cols[1]
        temp_df = df[[date_col, val_col]].dropna().copy()
        temp_df[date_col] = pd.to_datetime(temp_df[date_col], errors='coerce')
        temp_df = temp_df.dropna().set_index(date_col)
        temp_df[val_col] = pd.to_numeric(temp_df[val_col], errors='coerce')
        resampled = temp_df[val_col].resample('M').mean().dropna()
        
        if len(resampled) < 2:
            return {}
        
        first = resampled.iloc[0]
        last = resampled.iloc[-1]
        change_pct = float((last - first) / (first if first else 1) * 100)
        
        return {
            "direction": "up" if change_pct > 0 else "down",
            "change_pct": change_pct,
            "periods": [str(x) for x in resampled.index]
        }

    def _temporal_coverage(self, cols, df):
        col = cols[0]
        series = pd.to_datetime(df[col], errors='coerce')
        min_date = series.min()
        max_date = series.max()
        return {
            "min_date": str(min_date) if pd.notnull(min_date) else None,
            "max_date": str(max_date) if pd.notnull(max_date) else None,
            "range_days": int((max_date - min_date).days) if pd.notnull(max_date) and pd.notnull(min_date) else 0,
            "null_count": int(series.isna().sum())
        }

    def _temporal_gaps(self, cols, df):
        col = cols[0]
        series = pd.to_datetime(df[col], errors='coerce').dropna().sort_values()
        diffs = series.diff().dt.days.dropna()
        if len(diffs) == 0:
            return {}
        median_diff = diffs.median()
        gaps = diffs[diffs > median_diff * 3]
        return {
            "gap_count": int(len(gaps)),
            "max_gap_days": float(gaps.max()) if len(gaps) else 0.0
        }

    def _group_comparison(self, cols, df):
        if len(cols) < 2:
            return {}
        group_col = cols[0]
        val_col = cols[1]
        temp_df = df.copy()
        temp_df[val_col] = pd.to_numeric(temp_df[val_col], errors='coerce')
        res = temp_df.groupby(group_col)[val_col].agg(['mean', 'median', 'count', 'sum']).dropna().sort_values('mean', ascending=False)
        return res.to_dict(orient='index')

    def _concentration_analysis(self, cols, df):
        col = cols[0]
        vc = df[col].value_counts(normalize=True).head(10)
        return {
            "top_values": vc.index.tolist(),
            "top_pcts": (vc * 100).tolist()
        }

    def _correlation(self, cols, df):
        if len(cols) < 2:
            return {}
        c1, c2 = cols[0], cols[1]
        s1 = pd.to_numeric(df[c1], errors='coerce')
        s2 = pd.to_numeric(df[c2], errors='coerce')
        mask = s1.notna() & s2.notna()
        
        corr = float(s1[mask].corr(s2[mask]))
        if pd.isna(corr):
            corr = 0.0
            
        strength = "strong" if abs(corr) > 0.7 else "moderate" if abs(corr) > 0.3 else "weak"
        return {
            "pearson": corr,
            "strength": strength,
            "scatter_sample": [{"x": float(x), "y": float(y)} for x, y in zip(s1[mask].head(20), s2[mask].head(20))]
        }

    def _missingness_analysis(self, cols, df):
        total = len(df)
        column_missing_summary = []
        # Collect missing row indices per column (1-indexed for frontend display)
        all_missing_indices = []
        for c in cols:
            mask = df[c].isna()
            count = int(mask.sum())
            valid_count = total - count
            missing_pct = round(float(count / total * 100), 2) if total else 0.0
            # Get row indices (0-based) where this column is missing, capped at 50
            row_indices = [int(i) for i in mask[mask].index.tolist()[:50]]
            column_missing_summary.append({
                "column": c,
                "missing_count": count,
                "valid_count": valid_count,
                "missing_pct": missing_pct,
            })
            all_missing_indices.extend(row_indices)
        # De-duplicate and sort
        unique_indices = sorted(set(all_missing_indices))[:50]
        return {
            "column_missing_summary": column_missing_summary,
            "missing_row_indices": unique_indices,
            "total_missing_cells": sum(r["missing_count"] for r in column_missing_summary),
        }

    def _duplicate_analysis(self, cols, df):
        subset = [c for c in cols if c in df.columns]
        if not subset:
            subset = df.columns
        dup_count = int(df.duplicated(subset=subset).sum())
        return {
            "duplicate_count": dup_count,
            "duplicate_pct": float(dup_count / len(df) * 100) if len(df) else 0.0
        }

    def _top_n_analysis(self, cols, df):
        col = cols[0]
        temp = df.copy()
        temp[col] = pd.to_numeric(temp[col], errors='coerce')
        top = temp.nlargest(10, col)
        
        # Format preview rows safely
        preview = []
        for _, row in top.iterrows():
            preview_row = {}
            for k, v in row.items():
                if pd.isna(v):
                    preview_row[k] = None
                else:
                    preview_row[k] = v
            preview.append(preview_row)

        return {
            "top_values": [float(x) for x in top[col]],
            "preview_rows": preview
        }

    def _frequency_analysis(self, cols, df):
        col = cols[0]
        vc = df[col].value_counts().head(20)
        return {
            "values": vc.index.tolist(),
            "counts": [int(x) for x in vc.values]
        }
        
    def _volatility(self, cols, df):
        if len(cols) < 2:
            return {}
        date_col = cols[0]
        val_col = cols[1]
        temp_df = df[[date_col, val_col]].dropna().copy()
        temp_df[date_col] = pd.to_datetime(temp_df[date_col], errors='coerce')
        temp_df[val_col] = pd.to_numeric(temp_df[val_col], errors='coerce')
        temp_df = temp_df.dropna().sort_values(date_col).set_index(date_col)
        series = temp_df[val_col]
        
        if len(series) < 3:
            return {}
            
        rolling_std = series.rolling(window=3).std().dropna()
        mean_val = series.mean()
        cv = float(series.std() / mean_val) if mean_val else 0.0
        max_vol_period = str(rolling_std.idxmax()) if not rolling_std.empty else None
        
        return {
            "cv": cv,
            "max_volatility_period": max_vol_period,
            "max_rolling_std": float(rolling_std.max()) if not rolling_std.empty else 0.0
        }

    def _identifier_quality(self, cols, df):
        col = cols[0]
        series = df[col]
        total = len(series)
        missing_count = int(series.isna().sum())
        non_null = series.dropna()
        unique_count = int(non_null.nunique())
        duplicate_count = int(len(non_null) - unique_count)
        uniqueness_pct = round(float(unique_count / (total - missing_count) * 100), 2) if (total - missing_count) > 0 else 0.0
        is_clean = duplicate_count == 0 and missing_count == 0

        if is_clean:
            finding_text = f"All {total} identifiers are unique and non-missing."
        else:
            issues = []
            if duplicate_count > 0:
                issues.append(f"{duplicate_count} duplicate{'s' if duplicate_count != 1 else ''}")
            if missing_count > 0:
                issues.append(f"{missing_count} missing")
            finding_text = f"Identifier column '{col}' has {', '.join(issues)}."

        return {
            "column": col,
            "row_count": total,
            "unique_count": unique_count,
            "duplicate_count": duplicate_count,
            "missing_count": missing_count,
            "uniqueness_pct": uniqueness_pct,
            "is_clean": is_clean,
            "finding_text": finding_text,
        }

    def _build_evidence(self, candidate: AnalysisCandidate, result_data: dict, dko: DatasetKnowledgeObject) -> EvidenceReference:
        op = candidate.analysis_type
        
        type_mapping = {
            "outlier_detection": EvidenceType.OUTLIERS,
            "missingness_analysis": EvidenceType.MISSING,
            "duplicate_analysis": EvidenceType.DUPLICATES,
            "top_n_analysis": EvidenceType.TOP_N,
            "correlation": EvidenceType.CORRELATION,
            "group_comparison": EvidenceType.GROUP,
        }
        
        ev_type = type_mapping.get(op, EvidenceType.ROWS)
        
        return EvidenceReference(
            type=ev_type,
            dataset_id=dko.fingerprint,
            dataset_fingerprint=dko.fingerprint,
            description=f"Autonomous Analysis: {op}",
            column_names=candidate.columns,
        )

autonomous_executor = AutonomousExecutor()
