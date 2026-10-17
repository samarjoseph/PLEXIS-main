"""
Health monitoring for LLM providers.
Delegates to QuarantineManager as the central source of truth.
"""
from typing import Dict, Any
import logging
from providers.model_registry import model_registry
from providers.quarantine import quarantine_manager

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Tracks and updates the health status of providers and models."""

    def record_success(self, provider_name: str) -> None:
        """Record a successful call to a provider."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        quarantine_manager.record_success(provider_name, api_key=api_key)

        for model in model_registry.get_models_for_provider(provider_name):
            model_registry.update_health(model.model_id, 1.0)
            model_registry.update_reliability(model.model_id, True)

    def record_failure(self, provider_name: str, error: Any = None) -> None:
        """Record a failed call to a provider and degrade its health score."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        state, cd = quarantine_manager.record_failure(
            provider=provider_name,
            error=error or "failure",
            api_key=api_key,
        )

        health = 0.0 if not quarantine_manager.is_eligible(provider_name, api_key=api_key) else 0.5
        for model in model_registry.get_models_for_provider(provider_name):
            model_registry.update_health(model.model_id, health)
            model_registry.update_reliability(model.model_id, False)

    def get_health(self, provider_name: str) -> float:
        """Get the current health score for a provider (0.0 to 1.0)."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        return 1.0 if quarantine_manager.is_eligible(provider_name, api_key=api_key) else 0.0

    def is_healthy(self, provider_name: str) -> bool:
        """Check if a provider is considered healthy."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        return quarantine_manager.is_eligible(provider_name, api_key=api_key)


health_monitor = HealthMonitor()
