"""
AnalyticalPlanner — the ONLY LLM-based analytical planning component in Plexis.

Rules:
  - temperature = 0.0 always
  - Receives the full PlannerContext (schema, profile, chat history, previous ops)
  - Returns a validated AnalyticalPlan (from schema.py)
  - Runs a repair loop (max 3 attempts) if output is invalid
  - Does NOT execute anything
  - Does NOT compute numbers
  - Does NOT invent column names
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from planner.schema import AnalyticalPlan
from planner.prompt_builder import build_planner_prompt

logger = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 3


class AnalyticalPlanner:
    """
    The canonical LLM-based analytical planner.

    Input:  user query + PlannerContext dict
    Output: AnalyticalPlan | None

    If the LLM produces invalid JSON or an invalid plan:
      - Attempt up to MAX_REPAIR_ATTEMPTS times with a repair prompt
      - Return None on final failure (caller must handle gracefully)
    """

    def plan(
        self,
        query: str,
        context: dict,
    ) -> Optional[AnalyticalPlan]:
        """
        Produce a validated AnalyticalPlan for the given query.

        Args:
            query:   Raw user query (e.g. "who is the oldest person?")
            context: PlannerContext dict with keys:
                     columns, column_types, dataset_name, dataset_fingerprint,
                     profile, chat_history, previous_ops, dataset_id

        Returns:
            AnalyticalPlan on success, None on failure.
        """
        columns = context.get("columns", [])
        if not columns:
            logger.warning("[Planner] No columns in context — cannot plan without schema.")
            return None

        last_error: Optional[str] = None
        raw_plan: Optional[dict] = None

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
            prompt = build_planner_prompt(query, context, repair_error=last_error)
            raw_plan = self._call_llm(prompt, attempt)

            if raw_plan is None:
                last_error = "LLM returned no JSON"
                logger.warning("[Planner] Attempt %d/%d: LLM returned no parseable JSON",
                               attempt, MAX_REPAIR_ATTEMPTS)
                continue

            plan = AnalyticalPlan.from_dict(raw_plan)
            error = plan.validation_error(context)

            if error is None:
                logger.info(
                    "[Planner] Attempt %d/%d: Valid plan — intent=%s op=%s column=%s",
                    attempt, MAX_REPAIR_ATTEMPTS,
                    plan.intent, plan.operation, plan.target_column,
                )
                return plan

            last_error = error
            logger.warning(
                "[Planner] Attempt %d/%d: Invalid plan — %s", attempt, MAX_REPAIR_ATTEMPTS, error
            )

        logger.error(
            "[Planner] All %d attempts failed. Last error: %s", MAX_REPAIR_ATTEMPTS, last_error
        )
        return None

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _call_llm(self, prompt: str, attempt: int) -> Optional[dict]:
        """Call the LLM provider and parse JSON response."""
        try:
            from providers.engine import provider_engine
            from providers.domain.contracts import AIRequest

            response = provider_engine.generate(
                AIRequest(
                    task="planner",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=(
                        "You are the Plexis Analytical Planner. "
                        "Return ONLY a valid JSON object. No markdown. No prose. No code blocks."
                    ),
                    temperature=0.0,
                    json_mode=True,
                )
            )
            if not response.success:
                logger.warning("[Planner] LLM attempt %d failed: %s", attempt, response.error)
                return None
            return self._parse_json(response.text or "")
        except Exception as e:
            logger.error("[Planner] LLM call exception on attempt %d: %s", attempt, e, exc_info=True)
            return None

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Strip markdown fences and parse JSON."""
        text = text.strip()
        # Strip ```json ... ``` or ``` ... ```
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Last-resort: grab the first {...} block
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        return None


# Singleton
analytical_planner = AnalyticalPlanner()

# Legacy aliases — keep old names working so existing imports don't break
planner_engine = analytical_planner
AnalyticalPlanner = AnalyticalPlanner  # noqa: F811
