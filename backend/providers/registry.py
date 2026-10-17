"""
Provider instance registry with multi-credential support.
"""
from typing import Dict, Optional, List, Union
import logging
from providers.base import BaseProvider
from providers.scheduler import credential_scheduler

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry to manage and retrieve provider instances and their credential pools."""
    
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._api_keys: Dict[str, str] = {}
        self._all_api_keys: Dict[str, List[str]] = {}

    def register(self, provider: BaseProvider, api_key: Union[str, List[str]]) -> None:
        """
        Register a provider instance along with one or more API keys.
        Registers all keys in credential_scheduler for multi-slot scheduling.
        """
        pname = provider.provider_name.lower()
        self._providers[pname] = provider

        # Handle list or single key
        if isinstance(api_key, list):
            keys = [k.strip() for k in api_key if k and k.strip()]
        elif isinstance(api_key, str) and api_key.strip():
            keys = [api_key.strip()]
        else:
            keys = []

        self._all_api_keys[pname] = keys
        primary_key = keys[0] if keys else ""
        self._api_keys[pname] = primary_key

        # Register each key into credential_scheduler
        for idx, key in enumerate(keys):
            slot_id = f"{pname}_slot_{idx + 1}"
            account_id = f"{pname}_account_{idx + 1}"
            credential_scheduler.register_slot(
                provider=pname,
                api_key=key,
                slot_id=slot_id,
                account_id=account_id,
            )

        logger.info(
            f"[ProviderRegistry] Registered provider='{pname}' with {len(keys)} credential slot(s)"
        )

    def get(self, provider_name: str) -> Optional[BaseProvider]:
        """Get a provider instance by name."""
        return self._providers.get(provider_name.lower())

    def get_available(self) -> List[str]:
        """Get names of all providers that have at least one configured API key."""
        available = []
        for name in self._providers:
            # Check if has active keys in scheduler or in registry
            slots = credential_scheduler.get_slots(name)
            if slots or self._api_keys.get(name):
                available.append(name)
        return available

    def has_provider(self, provider_name: str) -> bool:
        """Check if a provider is registered."""
        return provider_name.lower() in self._providers

    def get_api_key(self, provider_name: str) -> Optional[str]:
        """Get primary API key for provider."""
        return self._api_keys.get(provider_name.lower())

    def get_all_api_keys(self, provider_name: str) -> List[str]:
        """Get all registered API keys for provider."""
        return list(self._all_api_keys.get(provider_name.lower(), []))


provider_registry = ProviderRegistry()
