from typing import List
from autonomous_analysis.contracts import (
    AnalysisCandidate, AnalysisBudget, CandidateCost, AnalysisType
)
from dataset_intelligence.models_v2 import DatasetKnowledgeObject
from dataset_intelligence.models import ColumnRole
from autonomous_analysis.candidate_generator import _normalize_dtype

class CandidateFilter:
    def _hard_filter(self, candidates: List[AnalysisCandidate], dko: DatasetKnowledgeObject) -> List[AnalysisCandidate]:
        valid = []
        dko_cols = dko.columns
        for cand in candidates:
            if cand.prerequisites.min_row_count and dko.row_count < cand.prerequisites.min_row_count:
                cand.is_filtered_out = True
                cand.filter_reason = "Row count < min_row_count"
                continue
            
            if cand.analysis_type == AnalysisType.VOLATILITY:
                dt_col_name = cand.columns[0] if cand.columns else None
                if dt_col_name and dt_col_name in dko_cols:
                    col_intel = dko_cols[dt_col_name]
                    if not col_intel.datetime_stats or not col_intel.datetime_stats.range_days or col_intel.datetime_stats.range_days <= 6:
                        cand.is_filtered_out = True
                        cand.filter_reason = "Volatility needs datetime with range_days > 6"
                        continue
            
            passed_reqs = True
            for i, req in enumerate(cand.prerequisites.column_requirements):
                if i >= len(cand.columns):
                    break
                col_name = cand.columns[i]
                if col_name not in dko_cols:
                    cand.is_filtered_out = True
                    cand.filter_reason = f"Required column {col_name} not found"
                    passed_reqs = False
                    break
                
                col_intel = dko_cols[col_name]
                col_norm_dtype = _normalize_dtype(col_intel.dtype_category)
                
                if req.dtype_category and req.dtype_category != "any" and col_norm_dtype != req.dtype_category:
                    if req.dtype_category == "datetime" and (col_norm_dtype == "datetime" or col_intel.role == ColumnRole.TIME):
                        pass  # TIME role columns can satisfy datetime requirement
                    else:
                        cand.is_filtered_out = True
                        cand.filter_reason = f"Column {col_name} dtype mismatch: {col_intel.dtype_category} (normalized={col_norm_dtype}) != {req.dtype_category}"
                        passed_reqs = False
                        break
                
                if req.min_cardinality and col_intel.unique_count < req.min_cardinality:
                    cand.is_filtered_out = True
                    cand.filter_reason = f"Column {col_name} cardinality {col_intel.unique_count} < min {req.min_cardinality}"
                    passed_reqs = False
                    break
                    
                if req.max_cardinality < 999999 and col_intel.unique_count > req.max_cardinality:
                    cand.is_filtered_out = True
                    cand.filter_reason = f"Column {col_name} cardinality {col_intel.unique_count} > max {req.max_cardinality}"
                    passed_reqs = False
                    break
                    
                if req.min_non_null_pct:
                    non_null_pct = 1.0 - col_intel.null_pct
                    if non_null_pct < req.min_non_null_pct:
                        cand.is_filtered_out = True
                        cand.filter_reason = f"Column {col_name} non-null pct {non_null_pct:.2f} < min {req.min_non_null_pct}"
                        passed_reqs = False
                        break
                        
                if col_intel.is_constant and req.min_cardinality > 1:
                    cand.is_filtered_out = True
                    cand.filter_reason = f"Column {col_name} is constant but analysis needs variation"
                    passed_reqs = False
                    break
                    
            if passed_reqs:
                valid.append(cand)
                
        return valid

    def _score_candidates(self, candidates: List[AnalysisCandidate], dko: DatasetKnowledgeObject) -> List[AnalysisCandidate]:
        for cand in candidates:
            if cand.is_filtered_out:
                continue
                
            ident_count = sum(1 for c in cand.columns if c in dko.columns and dko.columns[c].role == ColumnRole.IDENTIFIER)
            cand.score.structural_validity = max(0.0, 1.0 - (0.2 * ident_count))
            
            evidence = 1.0
            if cand.columns:
                target_col = dko.columns.get(cand.columns[0])
                if target_col:
                    if target_col.is_constant:
                        evidence *= 0.1
                    evidence *= max(0.0, 1.0 - target_col.null_pct)
            cand.score.evidence_strength = evidence
            
            iv = 0.5
            if cand.columns:
                target_col = dko.columns.get(cand.columns[0])
                if target_col:
                    _norm = _normalize_dtype(target_col.dtype_category)
                    if _norm == "numeric" and target_col.numeric_stats:
                        iv = min(1.0, 0.5 + (target_col.numeric_stats.variance or 0.0) / 1000.0)
                    elif _norm == "categorical" and target_col.categorical_stats:
                        iv = min(1.0, target_col.categorical_stats.entropy / 10.0)
            cand.score.information_value = iv

            
            sr = 0.5
            if cand.columns:
                target_col = dko.columns.get(cand.columns[0])
                if target_col and target_col.role in (ColumnRole.METRIC, ColumnRole.FINANCIAL, ColumnRole.DIMENSION, ColumnRole.TIME):
                    sr = 1.0
            cand.score.semantic_relevance = sr
            
            cand.score.novelty = 0.5
            
            cost_map = {CandidateCost.LOW: 1.0, CandidateCost.MEDIUM: 0.6, CandidateCost.HIGH: 0.3}
            cand.score.computational_cost = cost_map.get(cand.estimated_cost, 0.5)
            
            w = [0.20, 0.25, 0.25, 0.15, 0.05, 0.10]
            cand.score.composite = (
                w[0] * cand.score.structural_validity +
                w[1] * cand.score.evidence_strength +
                w[2] * cand.score.information_value +
                w[3] * cand.score.semantic_relevance +
                w[4] * cand.score.novelty +
                w[5] * cand.score.computational_cost
            )
        return candidates

    def _mmr_select(self, candidates: List[AnalysisCandidate], lambda_param: float = 0.6, max_k: int = 30) -> List[AnalysisCandidate]:
        valid_cands = [c for c in candidates if not c.is_filtered_out]
        if not valid_cands:
            return []
            
        valid_cands.sort(key=lambda c: c.score.composite, reverse=True)
        selected = []
        remaining = valid_cands.copy()
        
        while remaining and len(selected) < max_k:
            if not selected:
                best = remaining.pop(0)
                selected.append(best)
                continue
                
            best_idx = -1
            best_mmr = -float('inf')
            
            for i, cand in enumerate(remaining):
                max_sim = 0.0
                for s in selected:
                    sim = 0.0
                    if cand.redundancy_group and s.redundancy_group and cand.redundancy_group == s.redundancy_group:
                        sim = 1.0
                    elif cand.analysis_type == s.analysis_type:
                        sim = 0.7
                    elif set(cand.columns) & set(s.columns):
                        sim = 0.3
                    max_sim = max(max_sim, sim)
                
                mmr = lambda_param * cand.score.composite - (1 - lambda_param) * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
                    
            selected.append(remaining.pop(best_idx))
            
        return selected

    def compute_budget(self, dko: DatasetKnowledgeObject) -> AnalysisBudget:
        rows = dko.row_count
        cols = len(dko.columns)
        semantic_dims = len(set(c.role for c in dko.columns.values()))

        if rows < 5000 and cols < 8 and semantic_dims <= 3:
            tier, max_inv, max_cost = "simple", 6, 15
        elif rows >= 100000 or cols >= 20 or semantic_dims >= 6:
            tier, max_inv, max_cost = "complex", 14, 40
        else:
            tier, max_inv, max_cost = "normal", 10, 25

        max_inv = min(max_inv, 14)
        total_wall = max(60, min(180, rows // 1000 * 10))
        
        return AnalysisBudget(
            max_investigations=max_inv,
            max_cost_units=max_cost,
            per_analysis_timeout_s=30,
            total_wall_budget_s=total_wall,
            complexity_tier=tier
        )

    def filter_and_rank(self, candidates: List[AnalysisCandidate], dko: DatasetKnowledgeObject, budget: AnalysisBudget) -> List[AnalysisCandidate]:
        cands = self._hard_filter(candidates, dko)
        cands = self._score_candidates(cands, dko)
        selected = self._mmr_select(cands, max_k=30)
        
        final_list = []
        cost_sum = 0
        for c in selected:
            if cost_sum + c.estimated_cost_units <= budget.max_cost_units and len(final_list) < budget.max_investigations:
                final_list.append(c)
                cost_sum += c.estimated_cost_units
                
        return final_list

candidate_filter = CandidateFilter()
