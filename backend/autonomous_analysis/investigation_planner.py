import json
import logging
import re
from typing import List, Optional

from autonomous_analysis.contracts import (
    AnalysisCandidate, InvestigationPlan, PlannedInvestigation, AnalysisBudget
)
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Plexis Autonomous Investigation Planner.
You are given a Dataset Summary and a list of Analysis Candidates.
You must select candidates to investigate.
Rules:
1. ONLY select from the provided candidate_ids. Do not invent your own.
2. Return ONLY a valid JSON object. No markdown. No prose.
3. The output JSON must match the InvestigationPlan schema, containing an 'investigations' list with 'candidate_id', 'priority', and 'reason'.
"""

class InvestigationPlanner:
    def plan(
        self,
        dataset_summary: dict,
        candidates: List[AnalysisCandidate],
        budget: AnalysisBudget,
        dataset_fingerprint: str
    ) -> Optional[InvestigationPlan]:
        
        candidate_ids = {c.candidate_id for c in candidates}
        last_error = None
        
        for attempt in range(2):
            prompt = self._build_prompt(dataset_summary, candidates, last_error)
            
            raw_plan = self._call_llm(prompt)
            if not raw_plan:
                last_error = "LLM returned invalid JSON"
                continue
                
            try:
                investigations = []
                for inv in raw_plan.get("investigations", []):
                    cid = inv["candidate_id"]
                    if cid not in candidate_ids:
                        raise ValueError(f"Unknown candidate_id: {cid}")
                    investigations.append(PlannedInvestigation(**inv))
                    
                return InvestigationPlan(
                    investigations=investigations,
                    dataset_fingerprint=dataset_fingerprint,
                    plan_version="1.0",
                    llm_model="default",
                    raw_llm_output=json.dumps(raw_plan)
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Validation failed: {e}")
                
        return self._deterministic_fallback(candidates, budget, dataset_fingerprint)

    def _build_prompt(self, dataset_summary: dict, candidates: List[AnalysisCandidate], repair_error: Optional[str]) -> str:
        prompt = f"Dataset Summary:\n{json.dumps(dataset_summary)}\n\nCandidates:\n"
        for c in candidates:
            prompt += f"- ID: {c.candidate_id} | Type: {c.analysis_type} | Columns: {c.columns} | Cost: {c.estimated_cost_units}\n"
        if repair_error:
            prompt += f"\n\nPREVIOUS ERROR: {repair_error}. Fix your output to avoid this."
        return prompt

    def _call_llm(self, prompt: str) -> Optional[dict]:
        response = provider_engine.generate(AIRequest(
            task="planner",
            messages=[{"role": "user", "content": prompt}],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.0,
            json_mode=True
        ))
        if not response.success:
            return None
        return self._parse_json(response.text or "")

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        return None

    def _deterministic_fallback(self, candidates: List[AnalysisCandidate], budget: AnalysisBudget, fingerprint: str) -> InvestigationPlan:
        # Default 0 for composite score if not present
        sorted_cands = sorted(
            candidates, 
            key=lambda c: c.score.composite if (hasattr(c, 'score') and hasattr(c.score, 'composite')) else 0, 
            reverse=True
        )
        
        # Determine max based on budget limit
        max_inv = budget.max_investigations if hasattr(budget, 'max_investigations') else 5
        top_n = sorted_cands[:max_inv]
        
        investigations = [
            PlannedInvestigation(
                candidate_id=c.candidate_id,
                priority=i,
                reason="Fallback deterministic selection"
            ) for i, c in enumerate(top_n)
        ]
        
        return InvestigationPlan(
            investigations=investigations,
            dataset_fingerprint=fingerprint,
            plan_version="1.0-fallback",
            llm_model="deterministic",
            raw_llm_output=""
        )

investigation_planner = InvestigationPlanner()
