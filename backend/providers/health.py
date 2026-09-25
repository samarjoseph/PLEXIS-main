"""
Health monitoring for LLM providers.
"""
from typing import Dict
import logging
from providers.model_registry import model_registry

logger = logging.getLogger(__name__)

class HealthMonitor:
    """Tracks and updates the health status of providers and models."""
    
    def __init__(self):
        self._failures: Dict[str, int] = {}
        self._health: Dict[str, float] = {}

    def record_success(self, provider_name: str) -> None:
        """Record a successful call to a provider."""
        self._failures[provider_name] = 0
        self._health[provider_name] = 1.0
        
        for model in model_registry.get_models_for_provider(provider_name):
            model_registry.update_health(model.model_id, 1.0)
            model_registry.update_reliability(model.model_id, True)

    def record_failure(self, provider_name: str) -> None:
        """Record a failed call to a provider and degrade its health score."""
        current_failures = self._failures.get(provider_name, 0) + 1
        self._failures[provider_name] = current_failures
        
        # Degrade health score
        health = max(0.0, 1.0 - (current_failures * 0.2))
        self._health[provider_name] = health
        
        for model in model_registry.get_models_for_provider(provider_name):
            model_registry.update_health(model.model_id, health)
            model_registry.update_reliability(model.model_id, False)
            
        logger.warning(f"Recorded failure for provider {provider_name}. Consecutive failures: {current_failures}. Health: {health}")

    def get_health(self, provider_name: str) -> float:
        """Get the current health score for a provider (0.0 to 1.0)."""
        return self._health.get(provider_name, 1.0)

    def is_healthy(self, provider_name: str) -> bool:
        """Check if a provider is considered healthy."""
        return self.get_health(provider_name) > 0.3

health_monitor = HealthMonitor()
