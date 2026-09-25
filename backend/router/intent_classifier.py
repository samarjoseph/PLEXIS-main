"""
IntentClassifier — LEGACY / FAST-PATH ONLY

STATUS: Demoted. No longer the primary semantic authority.

In the 80/20 architecture, the MasterRouter uses LLM semantic interpretation
as the primary authority. This module is retained only for:
  1. Backward compatibility imports
  2. Any legacy code that hasn't been migrated yet

The fast-path patterns (greetings, title generation) have been moved into
MasterRouter._fast_path() using regex directly — they do not use this class.

WHAT HAS BEEN REMOVED:
  - ANALYSIS_KEYWORDS as the primary analytical intent signal
  - HELP_PATTERNS as the authority on what is "help"
  - Keyword-based analysis scoring as a routing decision
  - LLM escalation based on confidence threshold

If you need to add a new capability or analytical intent:
  - Add a capability class in capabilities/
  - Register it in engines/analysis.py
  - The LLM interpreter (prompts/interpreter.py) handles semantic matching

This file now exports only the get_analysis_score utility used by legacy code.
"""
import logging
import re
from core.context import ExecutionContext

logger = logging.getLogger(__name__)

# Kept only for backward compatibility — NOT used for routing decisions
ANALYSIS_KEYWORDS = [
    'average', 'mean', 'median', 'sum', 'total', 'count',
    'minimum', 'maximum', 'min', 'max', 'std', 'deviation',
    'correlation', 'distribution', 'top', 'bottom', 'highest', 'lowest',
    'outlier', 'missing', 'null', 'filter', 'sort', 'rank',
    'analyze', 'analyse', 'analysis', 'find', 'calculate', 'compute',
]


class IntentClassifier:
    """
    LEGACY: Retained for backward compatibility only.

    The MasterRouter no longer calls this class for primary intent classification.
    The 80/20 LLM-first architecture in master_router.py handles all classification.

    This class now only provides the get_analysis_score() utility for telemetry
    and any legacy callers.
    """

    def classify(self, context: ExecutionContext) -> dict:
        """
        DEPRECATED: No longer called by MasterRouter.

        The MasterRouter now uses LLM-first interpretation via master_router._llm_interpret().
        This method is retained for any legacy code that imports it directly.

        If called, returns a low-confidence result so the LLM always gets a chance to interpret.
        """
        logger.debug("[IntentClassifier.classify] DEPRECATED — should not be called in 80/20 arch")
        # Return low confidence → LLM will handle it
        return {
            "intent": "conversation",
            "confidence": 0.0,
            "execution_type": "synchronous",
            "requires_dataset": bool(getattr(context, 'dataset_id', None)),
            "requires_llm": True,
            "requires_planner": False,
            "requires_context": False,
            "requires_memory": False,
            "estimated_cost": "low",
            "estimated_latency": "low",
            "reasoning": "Legacy classifier — routing deferred to LLM interpreter",
        }

    def get_analysis_score(self, context: ExecutionContext) -> float:
        """
        Compute a keyword-based analysis score for telemetry and observability.

        NOT used for routing decisions in the 80/20 architecture.
        May be used for logging/monitoring to compare with LLM decisions.
        """
        message = (
            getattr(context, 'normalized_query', '') or
            context.message.lower()
        )
        return self._score_analysis(message)

    def _score_analysis(self, message: str) -> float:
        """Keyword-based analysis score (telemetry only, not a routing decision)."""
        matches = sum(1 for kw in ANALYSIS_KEYWORDS if kw in message.lower())
        if matches == 0:
            return 0.0
        score = min(0.5 + (matches * 0.15), 0.95)
        if '?' in message:
            score = min(score + 0.1, 0.95)
        return score


intent_classifier = IntentClassifier()
