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
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Any, List
import uuid

from autonomous_analysis.contracts import InvestigationResult, StructuredFinding
from autonomous_analysis.result_validator import result_validator
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest

logger = logging.getLogger(__name__)

INTERPRETATION_SYSTEM_PROMPT = """You are the Plexis Data Interpreter.
Write structured findings explaining what this analysis result MEANS for the dataset.

RULES:
1. Do NOT repeat specific numbers unnecessarily — the user already sees them in the table/chart above.
2. Do NOT invent statistics, percentages, columns, categories, or values not in the result.
3. Do NOT claim causation unless explicitly supported by the analysis.
4. Do NOT make business recommendations (e.g., "target outreach to...") without explicit domain context.
5. Explain the PATTERN or MEANING, not the raw numbers.
6. Return a valid JSON object matching this schema:
{
  "findings": [
    {
      "prose": "The distribution is approximately symmetric...",
      "columns_referenced": ["column_name"],
      "categories_referenced": ["category1"],
      "numbers_referenced": [12.5, 4]
    }
  ]
}
7. IMPORTANT: Every column name, category name, or number you mention MUST be exactly present in the provided evidence. If you invent a column, your finding will be rejected.
"""

def _build_prompt(result: InvestigationResult, dataset_context: dict) -> str:
    ev_id = result.structured_evidence.evidence_id if result.structured_evidence else "ev_000"
    
    # We provide the structured evidence to the LLM so it knows the exact boundary
    evidence_json = "{}"
    if result.structured_evidence:
        evidence_json = json.dumps({
            "allowed_columns": result.structured_evidence.columns,
            "allowed_categories": result.structured_evidence.categories,
            "allowed_statistics": result.structured_evidence.statistics,
            "allowed_values": result.structured_evidence.values,
        }, indent=2)

    return f"""ANALYSIS TYPE: {result.analysis_type.value}
DATASET: {dataset_context.get('name', 'unknown')} ({dataset_context.get('domain', 'general')})

EVIDENCE ID: {ev_id}
STRUCTURED EVIDENCE (You MUST NOT reference columns or categories outside this list):
{evidence_json}

RESULT DATA:
{json.dumps(result.result_data, indent=2, default=str)}

Generate 1-2 structured findings for this result."""

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
                    temperature=0.0, # Zero temperature to avoid hallucination
                    json_mode=True
                )
            )
            
            if response.success and response.text:
                try:
                    data = json.loads(response.text)
                except Exception:
                    data = {}
                
                valid_prose = []
                for f_data in data.get("findings", []):
                    finding = StructuredFinding(
                        finding_id=f"f_{uuid.uuid4().hex[:8]}",
                        finding_type=result.analysis_type.value,
                        prose=f_data.get("prose", ""),
                        evidence_ids=[result.structured_evidence.evidence_id] if result.structured_evidence else [],
                        columns_referenced=f_data.get("columns_referenced", []),
                        categories_referenced=f_data.get("categories_referenced", []),
                        numbers_referenced=f_data.get("numbers_referenced", []),
                    )
                    
                    is_valid = result_validator.validate_finding(finding, result.structured_evidence, result)
                    if is_valid:
                        result.verified_findings.append(finding)
                        valid_prose.append(finding.prose)
                    else:
                        logger.warning(f"Finding rejected by validator: {finding.prose}")
                
                if not valid_prose:
                    result.interpretation_flagged = True
                    return "No verified insights were generated for this dataset."
                    
                return " ".join(valid_prose)
            else:
                logger.warning(f"[InterpretationEngine] LLM request failed or returned empty: {response.error}")
                return _fallback_interpretation(result)
                
        except Exception as e:
            logger.error(f"[InterpretationEngine] Error during interpretation: {e}")
            return _fallback_interpretation(result)

interpretation_engine = InterpretationEngine()
