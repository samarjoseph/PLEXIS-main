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
  - Lightweight LLM call (max 200 tokens)
  - Input: interpretation summaries only (never raw data)
"""
from __future__ import annotations

import json
import logging
from typing import List, Tuple, Dict, Any

from autonomous_analysis.contracts import InvestigationResult, SynthesisInsight
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You are the Plexis Insight Synthesizer.
You are given multiple analysis findings for the same dataset.
Identify relationships BETWEEN the findings.

RULES:
1. Only reference facts from the provided findings.
2. Do NOT compute new statistics.
3. Identify reinforcing, contradicting, or contextual relationships.
4. Keep synthesis under 150 words.
5. Return JSON with 'synthesis_text' and 'insights' array.

Output format:
{
  "synthesis_text": "Brief paragraph connecting the findings",
  "insights": [
    {"related_ids": ["id1", "id2"], "type": "reinforcing|contradicting|contextual", "text": "..."}
  ]
}"""

class InsightSynthesizer:
    def synthesize(self, results: List[InvestigationResult], dataset_context: dict) -> Tuple[str, List[SynthesisInsight]]:
        if len(results) < 3:
            return "", []

        findings_info = []
        for r in results:
            findings_info.append({
                "candidate_id": r.candidate_id,
                "analysis_type": r.analysis_type.value,
                "columns": r.columns,
                "interpretation": r.interpretation
            })

        prompt = f"""DATASET: {dataset_context.get('name', 'unknown')} ({dataset_context.get('domain', 'general')})

FINDINGS:
{json.dumps(findings_info, indent=2)}

Synthesize these findings into relationships."""

        try:
            response = provider_engine.generate(
                AIRequest(
                    task="insight_synthesizer",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                    temperature=0.3,
                    json_mode=True
                )
            )

            if response.success and response.text:
                try:
                    data = json.loads(response.text)
                    synthesis_text = data.get("synthesis_text", "")
                    raw_insights = data.get("insights", [])
                    
                    insights = []
                    for raw in raw_insights:
                        insights.append(SynthesisInsight(
                            related_candidate_ids=raw.get("related_ids", []),
                            relationship_type=raw.get("type", "contextual"),
                            synthesis_text=raw.get("text", "")
                        ))
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
