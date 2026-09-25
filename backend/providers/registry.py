"""
Provider instance registry.
"""
from typing import Dict, Optional, List
import logging
from providers.base import BaseProvider

logger = logging.getLogger(__name__)

class ProviderRegistry:
    """Registry to manage and retrieve provider instances."""
    
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._api_keys: Dict[str, str] = {}

    def register(self, provider: BaseProvider, api_key: str) -> None:
        """Register a provider instance along with its API key."""
        self._providers[provider.provider_name] = provider
        self._api_keys[provider.provider_name] = api_key
        logger.info(f"Registered provider {provider.provider_name}")

    def get(self, provider_name: str) -> Optional[BaseProvider]:
        """Get a provider instance by name."""
        return self._providers.get(provider_name)

    def get_available(self) -> List[str]:
        """Get names of all providers that have a configured API key."""
        return [name for name, key in self._api_keys.items() if key]

    def has_provider(self, provider_name: str) -> bool:
        """Check if a provider is registered."""
        return provider_name in self._providers

provider_registry = ProviderRegistry()
