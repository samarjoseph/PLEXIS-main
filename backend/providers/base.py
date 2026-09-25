"""
Abstract base class and models for LLM providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Generator, Optional, Any

@dataclass
class ProviderResponse:
    """Standardized response from any LLM provider."""
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    raw_response: Optional[Any] = None

class BaseProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> ProviderResponse:
        ...

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        model_name: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> ProviderResponse:
        ...

    def generate_stream(
        self,
        prompt: str,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Stream text chunks from the provider.

        Override in providers that natively support streaming.
        Default fallback: calls generate() and yields the full text as a
        single chunk so providers without streaming still work correctly.
        """
        response = self.generate(
            prompt=prompt,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        if response.success and response.text:
            yield response.text

    @abstractmethod
    def health_check(self) -> bool:
        ...
