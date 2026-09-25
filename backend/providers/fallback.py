"""Fallback and Execution Engine.

Model-level fallback:
  Tracks FAILED MODEL IDs (not provider names) so that within-Groq fallback works:
    openai/gpt-oss-20b (fails)
        -> Qwen/Qwen3.6-27B-A3B-Instruct (same groq provider, different model)
        -> openai/gpt-oss-120b (same groq provider, high-reasoning)
        -> openrouter (different provider, last resort)

Provider circuit breakers are still used for health monitoring (transient errors).
"""
import logging
from typing import List, Optional

from providers.base import ProviderResponse
from providers.domain.contracts import AIRequest
from providers.selector import model_selector
from providers.registry import provider_registry
from providers.health import health_monitor
from providers.circuit_breaker import circuit_breaker
from providers.retry import retry_engine
from core.events import event_bus, ProviderFailedEvent, ProviderSwitchedEvent

logger = logging.getLogger(__name__)


class FallbackEngine:
    """Engine to orchestrate model-level execution with fallbacks."""

    def execute(self, request: AIRequest) -> ProviderResponse:
        """Execute prompt with model-level fallbacks."""
        failed_model_ids: List[str] = []   # Track model IDs, not provider names
        attempts = 0
        max_attempts = 5  # Enough to cover all 3 Groq tiers + 2 OpenRouter

        while attempts < max_attempts:
            model_meta = model_selector.select_by_model_fallback(
                task=request.task or "fallback",
                require_json=request.json_mode,
                failed_model_ids=failed_model_ids,
            )
            if not model_meta:
                return ProviderResponse(
                    text='',
                    model='unknown',
                    provider='unknown',
                    success=False,
                    error='No available models or providers.'
                )

            provider_name = model_meta.provider
            model_id = model_meta.model_id
            provider_instance = provider_registry.get(provider_name)

            if not provider_instance:
                logger.warning(
                    "[FallbackEngine] Provider '%s' not registered — skipping model %s",
                    provider_name, model_id
                )
                failed_model_ids.append(model_id)
                continue

            attempts += 1

            logger.info(
                "[FallbackEngine] Attempt %d: model=%s provider=%s",
                attempts, model_id, provider_name
            )

            # Use circuit breaker only for transient failure history
            if not circuit_breaker.can_call(provider_name):
                logger.warning(
                    "[FallbackEngine] Circuit breaker OPEN for provider=%s — "
                    "skipping model %s", provider_name, model_id
                )
                failed_model_ids.append(model_id)
                continue

            def call_provider():
                return provider_instance.generate(request)

            try:
                response = retry_engine.retry(
                    call_provider,
                    max_retries=1,    # Only 1 retry for transient errors; permanent = 0
                    base_delay=0.5,
                    provider_name=provider_name,
                )
            except Exception as exc:
                logger.error(
                    "[FallbackEngine] Provider '%s' raised exception: %s",
                    provider_name, exc
                )
                failed_model_ids.append(model_id)
                health_monitor.record_failure(provider_name)
                circuit_breaker.record_failure(provider_name)
                continue

            if response.success:
                health_monitor.record_success(provider_name)
                circuit_breaker.record_success(provider_name)
                logger.info(
                    "[FallbackEngine] Success: model=%s provider=%s",
                    response.model, response.provider
                )
                return response

            # ── Permanent error fast-fail ───────────────────────────────────────
            # 404/422 = model not found; 401/403 = auth failure (never retry).
            # These are configuration failures, not transient outages.
            error_str = str(response.error or "").lower()
            is_permanent = (
                "http 404" in error_str
                or "http 422" in error_str
                or "http 401" in error_str
                or "http 403" in error_str
                or "unauthorized" in error_str
                or "forbidden" in error_str
                or "model not available" in error_str
                or "does not exist" in error_str
                or "model_not_found" in error_str
                or "not available on groq" in error_str
            )
            if is_permanent:
                logger.warning(
                    "[FallbackEngine] PERMANENT error for model=%s — "
                    "skipping to next model. error=%s",
                    model_id, response.error
                )
                failed_model_ids.append(model_id)
                event_bus.publish(ProviderFailedEvent(
                    provider=provider_name,
                    error=f"[PERMANENT] {response.error}"
                ))
                continue

            # ── Transient error (429, 5xx, timeout) ───────────────────────────────
            logger.warning(
                "[FallbackEngine] Transient error for model=%s provider=%s: %s",
                model_id, provider_name, response.error
            )
            health_monitor.record_failure(provider_name)
            circuit_breaker.record_failure(provider_name)
            event_bus.publish(ProviderFailedEvent(
                provider=provider_name,
                error=str(response.error)
            ))
            failed_model_ids.append(model_id)

            # Emit provider-switched event
            next_model = model_selector.select_by_model_fallback(
                task=request.task or "fallback",
                require_json=request.json_mode,
                failed_model_ids=failed_model_ids,
            )
            if next_model:
                event_bus.publish(ProviderSwitchedEvent(
                    from_provider=provider_name,
                    to_provider=next_model.provider
                ))

        return ProviderResponse(
            text='',
            model='unknown',
            provider='unknown',
            success=False,
            error='All fallback attempts exhausted.',
            raw_response={'error_type': 'provider_exhausted', 'retryable': True},
        )


fallback_engine = FallbackEngine()
