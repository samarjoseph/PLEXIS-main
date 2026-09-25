"""Provider Engine public API."""
import json
import logging
from typing import Generator, Optional, Dict, Any

from providers.base import ProviderResponse
from providers.domain.contracts import AIRequest
from providers.registry import provider_registry
from providers.health import health_monitor
from providers.circuit_breaker import circuit_breaker
from providers.model_registry import model_registry
from providers.fallback import fallback_engine

logger = logging.getLogger(__name__)


class ProviderEngine:
    """Main entrypoint for LLM provider orchestration."""

    def __init__(self) -> None:
        """Initialize engine (providers registered lazily on first call)."""
        self._initialized: bool = False

    def _ensure_initialized(self) -> None:
        """Lazily initialize providers on first use."""
        if self._initialized:
            return
        self._initialized = True

        from config import Config

        # Each provider is initialized independently.
        # A failure in one (e.g., SDK import error or missing API key) must NOT
        # prevent the others from loading. This is the provider isolation guarantee.

        if Config.GEMINI_API_KEY:
            try:
                from providers.gemini import GeminiProvider
                gemini_provider = GeminiProvider(Config.GEMINI_API_KEY)
                provider_registry.register(gemini_provider, Config.GEMINI_API_KEY)
                logger.info("ProviderEngine: registered provider=gemini")
            except Exception as e:
                logger.warning(
                    f"ProviderEngine: skipping gemini provider — failed to register: {e}"
                )

        if Config.OPENROUTER_API_KEY:
            try:
                from providers.openrouter import OpenRouterProvider
                openrouter_provider = OpenRouterProvider(Config.OPENROUTER_API_KEY)
                provider_registry.register(openrouter_provider, Config.OPENROUTER_API_KEY)
                logger.info("ProviderEngine: registered provider=openrouter")
            except Exception as e:
                logger.warning(
                    f"ProviderEngine: skipping openrouter provider — failed to register: {e}"
                )

        if Config.GROQ_API_KEY:
            try:
                from providers.groq import GroqProvider
                groq_provider = GroqProvider(Config.GROQ_API_KEY)
                provider_registry.register(groq_provider, Config.GROQ_API_KEY)
                logger.info("ProviderEngine: registered provider=groq")
            except Exception as e:
                logger.warning(
                    f"ProviderEngine: skipping groq provider — failed to register: {e}"
                )

        if Config.MISTRAL_API_KEY:
            try:
                from providers.mistral import MistralProvider
                mistral_provider = MistralProvider(Config.MISTRAL_API_KEY)
                provider_registry.register(mistral_provider, Config.MISTRAL_API_KEY)
                logger.info("ProviderEngine: registered provider=mistral")
            except Exception as e:
                logger.warning(
                    f"ProviderEngine: skipping mistral provider — failed to register: {e}"
                )

        available = provider_registry.get_available()
        logger.info(f"ProviderEngine: initialization complete. Available providers: {available}")

    def generate(self, request: AIRequest) -> ProviderResponse:
        """Generate text utilizing provider fallbacks and circuit breakers."""
        self._ensure_initialized()

        response = fallback_engine.execute(request)

        if response.success:
            health_monitor.record_success(response.provider)
            circuit_breaker.record_success(response.provider)
            model_registry.update_latency(response.model, response.latency_ms)
            model_registry.update_reliability(response.model, True)
            from core.events import event_bus, ProviderCalledEvent
            event_bus.publish(ProviderCalledEvent(
                provider=response.provider,
                model=response.model,
                latency_ms=response.latency_ms,
            ))
        else:
            if response.model != 'unknown':
                model_registry.update_reliability(response.model, False)

        return response

    def generate_stream(self, request: AIRequest) -> Generator[str, None, None]:
        """
        Stream text chunks from the best available provider.

        Uses the same provider selection and fallback logic as generate(),
        but calls generate_stream() on the selected provider to yield
        tokens progressively. If streaming fails on the primary provider,
        falls back to the base-class default (yields full text as one chunk).

        Callers are responsible for SSE formatting — this yields plain strings.
        """
        self._ensure_initialized()

        # Reuse the fallback engine's provider selection logic
        from providers.selector import model_selector
        model_meta = model_selector.select_fallback(
            task=request.task or "stream",
            require_json=request.json_mode,
            failed_providers=[]
        )
        if not model_meta:
            logger.error("generate_stream: no available providers")
            return

        provider_instance = provider_registry.get(model_meta.provider)
        if not provider_instance:
            logger.error(f"generate_stream: provider '{model_meta.provider}' not found in registry")
            return

        logger.info(
            f"generate_stream: using provider='{model_meta.provider}' "
            f"model='{model_meta.model_name}'"
        )

        try:
            yield from provider_instance.generate_stream(request)
        except Exception as e:
            logger.error(f"generate_stream: provider '{model_meta.provider}' raised {e}")
            # Final fallback — non-streaming generate
            response = provider_instance.generate(request)
            if response.success and response.text:
                yield response.text

    def generate_json(self, request: AIRequest) -> Dict[str, Any]:
        """Generate structured JSON utilizing provider fallbacks."""
        request.json_mode = True
        response = self.generate(request)

        if not response.success:
            return {'error': response.error or 'Failed to generate JSON', 'raw': None}

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"ProviderEngine failed to parse JSON: {e}")
            return {'error': 'Failed to parse JSON', 'raw': response.text}


# Module-level singleton — safe to import without triggering API calls
provider_engine = ProviderEngine()
