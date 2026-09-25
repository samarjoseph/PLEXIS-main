"""
autonomous_analysis/interpretation_engine.py

LLM #2 — Interpretation Engine.

Receives verified result_data + evidence for one investigation.
Generates a grounded explanation of what the results mean.

Rules:
  - Cannot introduce numerical facts not present in verified result_data
  - Display formatting/rounding is allowed (controlled by presentation layer)
  - Max 100 words per interpretation
  - temperature = 0.3 (slightly more natural than planner)
  - If any number in the interpretation is unsupported by result_data, flags it
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Any

from autonomous_analysis.contracts import InvestigationResult
from autonomous_analysis.result_validator import result_validator
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest

logger = logging.getLogger(__name__)

INTERPRETATION_SYSTEM_PROMPT = """You are the Plexis Data Interpreter.
Write 1–2 sentences explaining what this analysis result MEANS for the dataset.

RULES:
1. Do NOT repeat specific numbers — the user already sees them in the table/chart above.
2. Do NOT invent statistics, percentages, or values not in the result.
3. Do NOT claim causation unless explicitly supported by the analysis.
4. Do NOT make business recommendations (e.g., "target outreach to...") without explicit domain context.
5. Explain the PATTERN or MEANING, not the raw numbers.
6. Maximum 2 sentences. Be specific and actionable.
7. Write in plain English, not technical jargon.

GOOD: "The distribution is approximately symmetric, suggesting no systematic bias in the data."
BAD: "The mean is 41.0 and the median is 40.5, which shows a roughly normal distribution."
"""

def _build_prompt(result: InvestigationResult, dataset_context: dict) -> str:
    return f"""ANALYSIS TYPE: {result.analysis_type.value}
COLUMNS: {result.columns}
DATASET: {dataset_context.get('name', 'unknown')} ({dataset_context.get('domain', 'general')})

RESULT DATA:
{json.dumps(result.result_data, indent=2, default=str)}

Evidence: {result.evidence.description if result.evidence else 'N/A'}

Explain what this result means. Only reference the numbers shown above."""

def _fallback_interpretation(result: InvestigationResult) -> str:
    return f"Analysis of {', '.join(result.columns)} ({result.analysis_type.value}) completed successfully."

class InterpretationEngine:
    def interpret(self, result: InvestigationResult, dataset_context: dict) -> str:
        prompt = _build_prompt(result, dataset_context)
        
        try:
            response = provider_engine.generate(
                AIRequest(
                    task="interpreter",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=INTERPRETATION_SYSTEM_PROMPT,
                    temperature=0.3,
                    json_mode=False
                )
            )
            
            if response.success and response.text:
                interpretation = response.text.strip()
                
                # Check for unsupported numbers
                if result.grounding:
                    if not result_validator.check_interpretation(interpretation, result.grounding):
                        result.interpretation_flagged = True
                
                return interpretation
            else:
                logger.warning(f"[InterpretationEngine] LLM request failed or returned empty: {response.error}")
                return _fallback_interpretation(result)
                
        except Exception as e:
            logger.error(f"[InterpretationEngine] Error during interpretation: {e}")
            return _fallback_interpretation(result)

interpretation_engine = InterpretationEngine()
