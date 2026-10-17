"""
Circuit breaker for protecting against failing LLM providers.
Delegates to the centralized QuarantineManager to ensure single-source-of-truth
health state across all Plexis subsystems.
"""
from __future__ import annotations

import logging
from typing import Optional, Any
from dataclasses import dataclass

from providers.quarantine import quarantine_manager, CircuitState

logger = logging.getLogger(__name__)


@dataclass
class BreakerState:
    """Represents the state of a circuit breaker for a provider."""
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    failures: int = 0
    opened_at: float = 0.0


class CircuitBreaker:
    """
    Prevents calls to failing providers and allows them time to recover.
    Acts as a bridge to QuarantineManager for full backward compatibility.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

    def can_call(self, provider_name: str) -> bool:
        """Check if calls to the provider are currently allowed."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        return quarantine_manager.is_eligible(provider_name, api_key=api_key)

    def record_success(self, provider_name: str) -> None:
        """Record a successful call, resetting the breaker if needed."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        quarantine_manager.record_success(provider_name, api_key=api_key)

    def record_failure(self, provider_name: str, error: Any = None) -> None:
        """Record a failure, potentially tripping the circuit breaker."""
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name)
        quarantine_manager.record_failure(
            provider=provider_name,
            error=error or "failure",
            api_key=api_key
        )


circuit_breaker = CircuitBreaker()
