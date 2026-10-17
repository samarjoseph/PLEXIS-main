"""
autonomous_analysis/insight_synthesizer.py

Insight Synthesizer — identifies relationships between verified findings.

Runs AFTER all interpretations are complete.
Operates only on verified InvestigationResult objects.

Rules:
  - Does NOT compute new statistics
  - Does NOT introduce unsupported numbers
  - Does NOT modify verified result values
  - Identifies shared dimensions, direction agreements/conflicts
  - Output structured findings with proper evidence links.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import List, Tuple

from autonomous_analysis.contracts import InvestigationResult, SynthesisInsight, StructuredFinding, StructuredEvidence
from autonomous_analysis.result_validator import result_validator
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You are the Plexis Insight Synthesizer.
You are given multiple analysis findings for the same dataset.
Identify relationships BETWEEN the findings.

RULES:
1. Only reference facts from the provided findings and their evidence.
2. Do NOT compute new statistics.
3. Identify reinforcing, contradicting, or contextual relationships.
4. Keep synthesis under 150 words.
5. Return JSON with 'synthesis_text' and a 'findings' array matching this schema:
{
  "synthesis_text": "Brief paragraph connecting the findings",
  "findings": [
    {
      "prose": "Combined insight text...",
      "evidence_ids": ["ev_001", "ev_002"],
      "columns_referenced": ["col1"],
      "categories_referenced": ["cat1"],
      "numbers_referenced": [12.5]
    }
  ]
}
6. IMPORTANT: Every column, category, or number you mention MUST be present in the allowed lists of the evidence_ids you cite.
"""

class InsightSynthesizer:
    def synthesize(self, results: List[InvestigationResult], dataset_context: dict) -> Tuple[str, List[SynthesisInsight]]:
        if len(results) < 3:
            return "", []

        findings_info = []
        for r in results:
            ev_id = r.structured_evidence.evidence_id if r.structured_evidence else "N/A"
            findings_info.append({
                "candidate_id": r.candidate_id,
                "evidence_id": ev_id,
                "analysis_type": r.analysis_type.value,
                "columns": r.columns,
                "interpretation": r.interpretation
            })
            
        allowed_ev = {}
        for r in results:
            if r.structured_evidence:
                allowed_ev[r.structured_evidence.evidence_id] = {
                    "columns": r.structured_evidence.columns,
                    "categories": r.structured_evidence.categories,
                    "statistics": r.structured_evidence.statistics,
                    "values": r.structured_evidence.values,
                }

        prompt = f"""DATASET: {dataset_context.get('name', 'unknown')} ({dataset_context.get('domain', 'general')})

FINDINGS:
{json.dumps(findings_info, indent=2)}

ALLOWED EVIDENCE DETAILS:
{json.dumps(allowed_ev, indent=2)}

Synthesize these findings into relationships."""

        try:
            response = provider_engine.generate(
                AIRequest(
                    task="insight_synthesizer",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                    temperature=0.0,
                    json_mode=True
                )
            )

            if response.success and response.text:
                try:
                    data = json.loads(response.text)
                    synthesis_text = data.get("synthesis_text", "")
                    raw_findings = data.get("findings", [])
                    
                    insights = []
                    # Create a combined pseudo-evidence that has all allowed fields from referenced evidence
                    for raw in raw_findings:
                        ev_ids = raw.get("evidence_ids", [])
                        combined_ev = StructuredEvidence(
                            evidence_id="synthesized",
                            dataset_id=results[0].structured_evidence.dataset_id if results[0].structured_evidence else "",
                            dataset_fingerprint=results[0].structured_evidence.dataset_fingerprint if results[0].structured_evidence else "",
                            evidence_type="synthesis"
                        )
                        for r in results:
                            if r.structured_evidence and r.structured_evidence.evidence_id in ev_ids:
                                combined_ev.columns.extend(r.structured_evidence.columns)
                                combined_ev.categories.extend(r.structured_evidence.categories)
                                combined_ev.statistics.update(r.structured_evidence.statistics)
                                combined_ev.values.extend(r.structured_evidence.values)
                                
                        finding = StructuredFinding(
                            finding_id=f"f_{uuid.uuid4().hex[:8]}",
                            finding_type="synthesis",
                            prose=raw.get("prose", ""),
                            evidence_ids=ev_ids,
                            columns_referenced=raw.get("columns_referenced", []),
                            categories_referenced=raw.get("categories_referenced", []),
                            numbers_referenced=raw.get("numbers_referenced", [])
                        )
                        
                        # Validate the finding against the combined evidence
                        # We temporarily mock a result with this combined evidence
                        mock_result = InvestigationResult(
                            candidate_id="synth",
                            analysis_type=results[0].analysis_type,
                            status="success",
                            columns=[],
                            evidence=results[0].evidence,
                            structured_evidence=combined_ev
                        )
                        # Patch finding evidence_ids for validation since it checks if ev_id == evidence.evidence_id
                        original_ev_ids = finding.evidence_ids
                        finding.evidence_ids = [combined_ev.evidence_id]
                        is_valid = result_validator.validate_finding(finding, combined_ev, mock_result)
                        finding.evidence_ids = original_ev_ids
                        
                        if is_valid:
                            insights.append(SynthesisInsight(
                                related_candidate_ids=[r.candidate_id for r in results if r.structured_evidence and r.structured_evidence.evidence_id in ev_ids],
                                relationship_type="contextual",
                                synthesis_text=finding.prose
                            ))
                        else:
                            logger.warning(f"Synthesis finding rejected by validator: {finding.prose}")

                    return synthesis_text, insights
                except Exception as e:
                    logger.warning(f"[InsightSynthesizer] Failed to parse JSON response: {e}")
                    return "", []
            else:
                logger.warning(f"[InsightSynthesizer] LLM request failed: {response.error}")
                return "", []

        except Exception as e:
            logger.error(f"[InsightSynthesizer] Error during synthesis: {e}")
            return "", []

insight_synthesizer = InsightSynthesizer()
