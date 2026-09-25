"""
Circuit breaker for protecting against failing LLM providers.
"""
from dataclasses import dataclass
from typing import Dict
import time
import logging

logger = logging.getLogger(__name__)

@dataclass
class BreakerState:
    """Represents the state of a circuit breaker for a provider."""
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    failures: int = 0
    opened_at: float = 0.0

class CircuitBreaker:
    """Prevents calls to failing providers and allows them time to recover."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._breakers: Dict[str, BreakerState] = {}

    def _get_breaker(self, provider_name: str) -> BreakerState:
        if provider_name not in self._breakers:
            self._breakers[provider_name] = BreakerState()
        return self._breakers[provider_name]

    def can_call(self, provider_name: str) -> bool:
        """Check if calls to the provider are currently allowed."""
        breaker = self._get_breaker(provider_name)
        if breaker.state == "CLOSED":
            return True
        if breaker.state == "OPEN":
            if time.time() - breaker.opened_at >= self.recovery_timeout:
                breaker.state = "HALF_OPEN"
                logger.info(f"Circuit breaker for {provider_name} entering HALF_OPEN state.")
                return True
            return False
        if breaker.state == "HALF_OPEN":
            # Only allow one test call when in HALF_OPEN
            return True
        return False

    def record_success(self, provider_name: str) -> None:
        """Record a successful call, resetting the breaker if needed."""
        breaker = self._get_breaker(provider_name)
        if breaker.state != "CLOSED":
            logger.info(f"Circuit breaker for {provider_name} entering CLOSED state.")
        breaker.state = "CLOSED"
        breaker.failures = 0

    def record_failure(self, provider_name: str) -> None:
        """Record a failure, potentially tripping the circuit breaker."""
        breaker = self._get_breaker(provider_name)
        if breaker.state == "HALF_OPEN":
            breaker.state = "OPEN"
            breaker.opened_at = time.time()
            logger.warning(f"Circuit breaker for {provider_name} reopening.")
        elif breaker.state == "CLOSED":
            breaker.failures += 1
            if breaker.failures >= self.failure_threshold:
                breaker.state = "OPEN"
                breaker.opened_at = time.time()
                logger.warning(f"Circuit breaker for {provider_name} tripped to OPEN state.")

circuit_breaker = CircuitBreaker()
