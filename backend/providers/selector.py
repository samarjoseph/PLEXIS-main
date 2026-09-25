"""Model Selection Engine.

Provides two selection modes:
  1. select() / select_fallback() — excludes by PROVIDER name (legacy, used by generate_stream)
  2. select_by_model_fallback()  — excludes by MODEL ID (used by FallbackEngine)
     This enables within-Groq model fallback:
       openai/gpt-oss-20b → Qwen/Qwen3.6-27B-A3B-Instruct → openai/gpt-oss-120b
"""
import logging
from typing import Optional, List

from providers.model_registry import model_registry, ModelMetadata
from providers.circuit_breaker import circuit_breaker

logger = logging.getLogger(__name__)


class ModelSelector:
    """Selects the best available model for a task."""

    def select(
        self,
        task: str,
        require_json: bool = False,
        exclude_providers: Optional[List[str]] = None,
    ) -> Optional[ModelMetadata]:
        """Select best model for task, excluding given providers (legacy API)."""
        exclude_providers = exclude_providers or []
        models = model_registry.get_models_for_task(task, require_json)

        valid_models = []
        for model in models:
            if model.provider in exclude_providers:
                continue
            if not circuit_breaker.can_call(model.provider):
                continue
            valid_models.append(model)

        if not valid_models:
            logger.warning("No valid models found for task: %s", task)
            return None

        return self._score_and_pick(valid_models, task)

    def select_fallback(
        self,
        task: str,
        require_json: bool,
        failed_providers: List[str],
    ) -> Optional[ModelMetadata]:
        """Select a fallback model excluding failed providers (legacy API)."""
        return self.select(task, require_json, failed_providers)

    def select_by_model_fallback(
        self,
        task: str,
        require_json: bool,
        failed_model_ids: List[str],
    ) -> Optional[ModelMetadata]:
        """
        Select the best model for a task, excluding specific model IDs.

        This is the correct API for the FallbackEngine — it excludes
        individual models (not whole providers), enabling within-Groq
        model-level fallback:

          openai/gpt-oss-20b     (fails)
              → Qwen/Qwen3.6-27B-A3B-Instruct  (same groq provider)
              → openai/gpt-oss-120b              (same groq provider)
              → deepseek/deepseek-chat-v3         (openrouter)
        """
        models = model_registry.get_models_for_task(task, require_json)

        valid_models = []
        for model in models:
            if model.model_id in failed_model_ids:
                continue
            if model.model_name in failed_model_ids:
                continue
            # Circuit breaker: if the provider has been circuit-broken,
            # skip it UNLESS we have another model on the same provider
            # that wasn't individually failed (circuit break is per-provider).
            if not circuit_breaker.can_call(model.provider):
                logger.debug(
                    "[ModelSelector] Circuit OPEN for provider=%s — skipping model=%s",
                    model.provider, model.model_id
                )
                continue
            valid_models.append(model)

        if not valid_models:
            logger.warning(
                "[ModelSelector] No valid models for task=%s after excluding %s",
                task, failed_model_ids
            )
            return None

        selected = self._score_and_pick(valid_models, task)
        if selected:
            logger.info(
                "[ModelSelector] Selected: model=%s provider=%s priority=%d task=%s",
                selected.model_id, selected.provider, selected.priority, task
            )
        return selected

    @staticmethod
    def _score_and_pick(models: List[ModelMetadata], task: str) -> Optional[ModelMetadata]:
        """Score models by: priority (lower is better), task affinity, reliability, cost."""
        if not models:
            return None

        scored = []
        for model in models:
            affinity = model.task_affinities.get(task, 0.5)
            cost_factor = 1.0 / (1.0 + getattr(model, 'estimated_cost_per_1k', 0.0))
            priority = getattr(model, 'priority', 5)
            reliability = getattr(model, 'reliability_score', 1.0)

            # Priority is primary sort key (lower = better → negate for max sort)
            # Affinity is secondary
            score = (10 - priority) * affinity * reliability * cost_factor
            scored.append((score, model))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


model_selector = ModelSelector()
