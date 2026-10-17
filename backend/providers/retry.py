"""
Retry engine with exponential backoff for LLM provider calls.
Uses centralized QuarantineManager for eligibility checks and failure recording.
"""
from typing import Callable, Any
import time
import logging
from providers.base import ProviderResponse
from providers.quarantine import quarantine_manager

logger = logging.getLogger(__name__)


class RetryEngine:
    """Engine to retry failing operations with exponential backoff and quarantine checks."""

    def retry(
        self,
        fn: Callable[..., ProviderResponse],
        max_retries: int = 1,
        base_delay: float = 0.5,
        provider_name: str = '',
        model_id: str = '',
    ) -> ProviderResponse:
        """
        Execute a function with retries and circuit breaking.
        """
        attempt = 0
        last_exception = None
        from providers.registry import provider_registry
        api_key = provider_registry._api_keys.get(provider_name) if provider_name else None

        while attempt <= max_retries:
            if provider_name and not quarantine_manager.is_eligible(provider_name, api_key=api_key, model_id=model_id):
                raise RuntimeError(f"Quarantine active / circuit OPEN for provider: {provider_name}")

            try:
                response = fn()
                if response.success:
                    if provider_name:
                        quarantine_manager.record_success(provider_name, api_key=api_key, model_id=model_id)
                    return response
                
                # Response returned with success=False
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"[RetryEngine] Attempt {attempt + 1} unsuccessful for {provider_name}. Retrying in {delay}s...")
                    time.sleep(delay)
                    attempt += 1
                    continue
                return response
            except Exception as e:
                last_exception = e
                logger.error(f"[RetryEngine] Attempt {attempt + 1} failed for {provider_name or 'unnamed'}: {str(e)}")
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                attempt += 1

        if last_exception:
            if provider_name:
                quarantine_manager.record_failure(provider_name, error=last_exception, api_key=api_key, model_id=model_id)
            raise last_exception
        raise Exception("Max retries exceeded")


retry_engine = RetryEngine()
