"""
Retry engine with exponential backoff for LLM provider calls.
"""
from typing import Callable, Any
import time
import logging
from providers.base import ProviderResponse
from providers.circuit_breaker import circuit_breaker
from providers.health import health_monitor

logger = logging.getLogger(__name__)

class RetryEngine:
    """Engine to retry failing operations with exponential backoff."""
    
    def retry(self, fn: Callable[..., ProviderResponse], max_retries: int = 2, base_delay: float = 1.0, provider_name: str = '') -> ProviderResponse:
        """
        Execute a function with retries and circuit breaking.
        
        Args:
            fn: Callable that returns a ProviderResponse
            max_retries: Maximum number of retries before giving up
            base_delay: Initial delay between retries
            provider_name: Name of the provider for metrics and circuit breaking
        """
        attempt = 0
        last_exception = None
        
        while attempt <= max_retries:
            if provider_name and not circuit_breaker.can_call(provider_name):
                raise RuntimeError(f"Circuit breaker is OPEN for provider: {provider_name}")
                
            try:
                response = fn()
                if provider_name:
                    circuit_breaker.record_success(provider_name)
                    health_monitor.record_success(provider_name)
                return response
            except Exception as e:
                last_exception = e
                if provider_name:
                    circuit_breaker.record_failure(provider_name)
                    health_monitor.record_failure(provider_name)
                    
                logger.error(f"Attempt {attempt + 1} failed for {provider_name or 'unnamed provider'}: {str(e)}")
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                attempt += 1
                
        raise last_exception or Exception("Max retries exceeded")

retry_engine = RetryEngine()
