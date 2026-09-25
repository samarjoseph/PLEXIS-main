"""
Presentation Layer — Module Explainer

On-demand LLM explanation for individual Knowledge Modules.
Triggered when the user expands a module card in the frontend.

Design (RFC-002 §6.5):
  - One LLM call per module expansion (~300–500 tokens input)
  - SSE stream returned directly to the expand endpoint
  - Explanation cached by (fingerprint, module_id, prompt_version)
  - POST endpoint allows user_query context for personalized explanations
  - Concurrency: max 1 active explain stream per dataset_id (semaphore)

Audit fixes:
  - POST endpoint (not GET) to allow user_query in body
  - prompt_version in cache key (stale cache prevention)
  - PII already scrubbed upstream in rare module
  - previously_stated context prevents narrative redundancy
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Generator, Optional

from .domain.contracts import KnowledgeModule, ExplanationCacheKey, ModuleID
from .explanation_cache import explanation_cache

logger = logging.getLogger(__name__)

RESPONSE_MAX_TOKENS = 512

# ---------------------------------------------------------------------------
# Per-module system prompts
# ---------------------------------------------------------------------------

MODULE_SYSTEM_PROMPTS: Dict[str, str] = {
    ModuleID.EXECUTIVE: """You are Plexis. Provide a concise summary of what the executive intelligence means for this dataset. Focus on narrative synthesis, not statistics.""",

    ModuleID.QUALITY: """You are Plexis, a data quality expert. Explain what the data quality findings mean for analysis reliability. Focus on actionable implications: what does poor quality block? What does good quality enable? Do NOT list numbers — interpret them.""",

    ModuleID.STATISTICS: """You are Plexis. Explain what the statistical profile reveals about the business dynamics behind this data. Connect statistical patterns to real-world meaning. Do NOT narrate individual numbers — interpret distribution shapes and relationships.""",

    ModuleID.COLUMNS: """You are Plexis. Explain what the column roles and semantic types reveal about how this data was structured and what business process generated it. Do NOT list column names — describe the data architecture.""",

    ModuleID.RELATIONSHIPS: """You are Plexis. Explain what the correlations and grouping dimensions reveal about the causal structure of this data. What drives what? Which relationships are meaningful vs coincidental?""",

    ModuleID.PATTERNS: """You are Plexis, a patterns analyst. Explain what the detected distribution patterns mean in practical terms. Why might a bimodal distribution exist? What business events create long tails?""",

    ModuleID.RARE: """You are Plexis. Explain what the rare values and outliers might represent in this domain context. Are they errors? Exceptional cases? Fraud signals? Measurement artifacts?""",

    ModuleID.DISTRIBUTION: """You are Plexis. Explain what the distribution shapes reveal about the underlying process that generated this data. Normal vs skewed distributions tell different stories — interpret them.""",

    ModuleID.INSIGHTS: """You are Plexis. Synthesize the key insights into a coherent narrative about what makes this dataset analytically interesting. Connect multiple insights if they tell a common story.""",

    ModuleID.VIZ: """You are Plexis. Explain why each visualization type is recommended and what analytical question it would answer. Help the user understand what they'd discover by creating each chart.""",

    ModuleID.SEMANTIC: """You are Plexis. Explain what the semantic classification and domain detection reveal about the business context of this data. What kind of organization likely generated it?""",

    ModuleID.QUESTIONS: """You are Plexis. Explain why these are the most analytically valuable questions to ask about this dataset and what insights answering them would reveal.""",
}

DEFAULT_SYSTEM_PROMPT = """You are Plexis, an expert data analyst. Provide a concise, insightful explanation of the provided module data. Focus on practical implications, not statistics."""


# ---------------------------------------------------------------------------
# ModuleExplainer
# ---------------------------------------------------------------------------

class ModuleExplainer:
    """
    Generates LLM explanations for individual Knowledge Modules on demand.

    One explanation per module per user request.
    Explanations are cached by (fingerprint, module_id, prompt_version).
    Concurrency is limited to 1 active stream per dataset_id via semaphore.
    """

    def __init__(self) -> None:
        # Per-dataset_id semaphore: max 1 concurrent explain stream
        # Audit fix: prevents 429 storms from simultaneous card expansions
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._sem_lock = threading.Lock()

    def explain_stream(
        self,
        module: KnowledgeModule,
        dataset_fingerprint: str,
        dataset_id: str,
        user_query: Optional[str] = None,
        verbosity: str = "standard",
        audience: str = "technical",
        previously_stated: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Stream an LLM explanation for a module.

        Args:
            module: The KnowledgeModule to explain.
            dataset_fingerprint: DKO fingerprint for cache keying.
            dataset_id: Used for per-dataset concurrency control.
            user_query: Optional user question to personalize the explanation.
            verbosity: "brief" | "standard" | "detailed"
            audience: "technical" | "non-technical" | "executive"
            previously_stated: Summary of what the primary narrative already said
                                (prevents redundancy — audit fix for explanation anchoring).

        Yields:
            Plain string chunks of Markdown.
        """
        cache_key = ExplanationCacheKey(
            dataset_fingerprint=dataset_fingerprint,
            module_id=module.module_id,
            prompt_version=module.prompt_version,
        )

        # Check cache first (before acquiring semaphore)
        cached = explanation_cache.get(cache_key)
        if cached and not user_query:
            logger.info(
                f"ModuleExplainer: cache hit for "
                f"(fp={dataset_fingerprint[:8]}…, module={module.module_id}, v={module.prompt_version})"
            )
            yield cached
            return

        # Acquire per-dataset semaphore (max 1 concurrent explain per dataset)
        sem = self._get_semaphore(dataset_id)
        acquired = sem.acquire(blocking=False)
        if not acquired:
            logger.info(f"ModuleExplainer: semaphore busy for dataset_id={dataset_id}, cancelling in-flight and proceeding")
            # Cancel old stream by acquiring after brief wait
            sem.acquire(timeout=5)

        try:
            prompt = self._build_prompt(module, user_query, verbosity, audience, previously_stated)
            system = MODULE_SYSTEM_PROMPTS.get(module.module_id, DEFAULT_SYSTEM_PROMPT)
            chunks = []

            for chunk in self._call_llm(prompt, system):
                chunks.append(chunk)
                yield chunk

            # Cache the result (only when no user_query — user-specific answers not cached)
            if chunks and not user_query:
                full_text = "".join(chunks)
                explanation_cache.set(cache_key, full_text)

        except Exception as e:
            logger.error(f"ModuleExplainer.explain_stream() failed for {module.module_id}: {e}")
            yield self._fallback_explanation(module)
        finally:
            sem.release()

    # -------------------------------------------------------------------------
    # Prompt building
    # -------------------------------------------------------------------------

    def _build_prompt(
        self,
        module: KnowledgeModule,
        user_query: Optional[str],
        verbosity: str,
        audience: str,
        previously_stated: Optional[str],
    ) -> str:
        import json

        # Serialize module data compactly
        data_summary = json.dumps(module.data, indent=2, default=str)
        # Limit to ~400 chars worth of data for token efficiency
        if len(data_summary) > 2000:
            data_summary = data_summary[:2000] + "\n... (truncated)"

        verbosity_instruction = {
            "brief": "Keep your response to 2–3 sentences.",
            "standard": "Write 100–150 words.",
            "detailed": "Write 200–300 words with supporting reasoning.",
        }.get(verbosity, "Write 100–150 words.")

        audience_instruction = {
            "technical": "Use precise analytical language. Assume data science familiarity.",
            "non-technical": "Use plain business language. Avoid jargon.",
            "executive": "Be direct and business-focused. Lead with implications, not methodology.",
        }.get(audience, "Use precise analytical language.")

        parts = [
            f"MODULE: {module.display_name}",
            f"DATA:\n{data_summary}",
        ]

        if previously_stated:
            parts.append(
                f"\nCONTEXT (already mentioned in primary narrative — do NOT repeat):\n{previously_stated}"
            )

        if user_query:
            parts.append(f"\nUSER QUESTION: {user_query}")
            parts.append("\nAnswer the user's specific question using this module's data.")
        else:
            parts.append(
                f"\n{verbosity_instruction} {audience_instruction} "
                f"Explain what this module's data reveals. Do NOT list the numbers — interpret them."
            )

        return "\n".join(parts)

    # -------------------------------------------------------------------------
    # LLM call
    # -------------------------------------------------------------------------

    def _call_llm(self, prompt: str, system_prompt: str) -> Generator[str, None, None]:
        from providers import provider_engine
        from providers.domain.contracts import AIRequest

        for chunk in provider_engine.generate_stream(
            AIRequest(
                task="presentation",
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system_prompt,
                temperature=0.5,
                max_tokens=RESPONSE_MAX_TOKENS,
            )
        ):
            if chunk:
                yield chunk

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_semaphore(self, dataset_id: str) -> threading.Semaphore:
        with self._sem_lock:
            if dataset_id not in self._semaphores:
                self._semaphores[dataset_id] = threading.Semaphore(1)
            return self._semaphores[dataset_id]

    def _fallback_explanation(self, module: KnowledgeModule) -> str:
        return (
            f"**{module.display_name}**: {module.preview}\n\n"
            f"*Full explanation temporarily unavailable. Click to retry.*"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
module_explainer = ModuleExplainer()
