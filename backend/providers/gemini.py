"""
Gemini provider implementation using google-genai SDK.

SDK imports are LAZY (inside methods) to ensure provider isolation:
  - A Gemini SDK import failure does NOT crash Groq/Mistral/OpenRouter initialization.
  - Each provider loads its SDK only when actually called.
"""
import time
import json
import logging
from typing import Optional, Any, Generator

from providers.base import ProviderResponse
from providers.domain.contracts import IProviderAdapter, AIRequest, ProviderCapabilities
from providers.errors import ProviderExecutionError, ProviderAuthenticationError, ProviderRateLimitError

logger = logging.getLogger(__name__)


def _get_genai_client(api_key: str):
    """
    Lazily import and construct the google.genai client.
    Raises ImportError if the SDK is not available.
    Raises RuntimeError if client construction fails.
    """
    try:
        from google import genai as _genai
        from google.genai import types as _types  # noqa: F401 — side-effect import validates package
    except ImportError as e:
        raise ImportError(
            f"google-genai SDK not available: {e}. "
            "Install with: pip install google-genai"
        ) from e

    try:
        client = _genai.Client(api_key=api_key)
        return client, _genai
    except Exception as e:
        raise RuntimeError(f"Failed to construct google.genai.Client: {e}") from e


class GeminiProvider(IProviderAdapter):
    """Gemini provider using google-genai SDK, with lazy SDK loading."""

    def __init__(self, api_key: str):
        """Store API key only — SDK imported lazily on first call."""
        self._api_key = api_key
        self._client = None   # initialized on first use

    def _get_client(self):
        """Return (or create) the genai Client."""
        if self._client is None:
            client, _ = _get_genai_client(self._api_key)
            self._client = client
        return self._client

    @property
    def provider_name(self) -> str:
        return 'gemini'

    def get_capabilities(self, model_name: str) -> ProviderCapabilities:
        """Return capabilities for the given Gemini model."""
        if "pro" in model_name.lower():
            return ProviderCapabilities(
                vision=True,
                embeddings=False,
                parallel_tool_calling=True,
                structured_output=True,
                temperature_support=True,
                multimodal=True,
                streaming=True,
                json_mode=True,
                reasoning_level="advanced",
                max_input_tokens=2000000,
                max_output_tokens=8192,
                latency_profile="medium",
                cost_profile="high"
            )
        else:
            return ProviderCapabilities(
                vision=True,
                embeddings=False,
                parallel_tool_calling=True,
                structured_output=True,
                temperature_support=True,
                multimodal=True,
                streaming=True,
                json_mode=True,
                reasoning_level="basic",
                max_input_tokens=1000000,
                max_output_tokens=8192,
                latency_profile="low",
                cost_profile="low"
            )

    def _convert_messages(self, messages: list) -> str:
        """Convert messages list to a prompt string."""
        return "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages])

    def _map_exception(self, e: Exception) -> Exception:
        """Map SDK exception to internal Provider errors."""
        try:
            from google.genai.errors import APIError
            if isinstance(e, APIError):
                if e.code in (401, 403):
                    return ProviderAuthenticationError(f"Gemini Auth Error: {e.message}")
                elif e.code == 429:
                    return ProviderRateLimitError(f"Gemini Rate Limit Exceeded: {e.message}")
                return ProviderExecutionError(f"Gemini API Error: {e.message}")
        except ImportError:
            pass
        return ProviderExecutionError(str(e))

    def _get_model_for_request(self, request: AIRequest) -> str:
        """Select model from model_registry for the given task."""
        try:
            from providers.model_registry import model_registry
            task = (request.task or '').lower()
            gemini_models = model_registry.get_models_for_provider('gemini')
            if gemini_models:
                task_models = [
                    m for m in gemini_models
                    if m.task_affinities.get(task, 0) > 0 and m.health_score > 0.3
                ]
                if task_models:
                    task_models.sort(key=lambda m: (-m.task_affinities.get(task, 0), m.priority))
                    return task_models[0].model_name
                gemini_models.sort(key=lambda m: m.priority)
                return gemini_models[0].model_name
        except Exception as exc:
            logger.warning('[GeminiProvider] model_registry lookup failed: %s', exc)
        # Hard fallback — Gemini is not in the normal routing chain.
        # This path is only reached if gemini provider is called explicitly.
        return 'gemini-2.0-flash'

    def generate(self, request: AIRequest) -> ProviderResponse:
        """Generate text using Gemini, governed by AIRequest."""
        try:
            from google.genai import types as _types

            client = self._get_client()
            prompt = self._convert_messages(request.messages) if request.messages else request.task
            model_name = self._get_model_for_request(request)
            logger.info(
                '[PRESENTATION_MODEL_REQUEST] provider=gemini selected_model=%s outgoing_model=%s',
                model_name, model_name,
            )

            response_mime_type = 'application/json' if request.json_mode else 'text/plain'

            config = _types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                max_output_tokens=request.max_tokens or 8192,
                response_mime_type=response_mime_type
            )

            start_time = time.time()
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            latency_ms = (time.time() - start_time) * 1000

            input_tokens = 0
            output_tokens = 0
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0

            return ProviderResponse(
                text=response.text,
                model=model_name,
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                success=True,
                raw_response={"text": response.text}
            )
        except (ImportError, RuntimeError) as sdk_err:
            logger.error(f"Gemini SDK unavailable: {sdk_err}")
            return ProviderResponse(
                text='', model="unknown", provider=self.provider_name,
                success=False, error=f"Gemini SDK unavailable: {sdk_err}"
            )
        except Exception as e:
            logger.error(f"Gemini generate error: {e}")
            mapped_error = self._map_exception(e)
            return ProviderResponse(
                text='', model="unknown", provider=self.provider_name,
                success=False, error=str(mapped_error)
            )

    def generate_stream(self, request: AIRequest) -> Generator[str, None, None]:
        """Stream text chunks using Gemini's native streaming API."""
        try:
            from google.genai import types as _types

            client = self._get_client()
            prompt = self._convert_messages(request.messages) if request.messages else request.task
            model_name = self._get_model_for_request(request)
            logger.info(
                '[PRESENTATION_MODEL_REQUEST] provider=gemini selected_model=%s outgoing_model=%s',
                model_name, model_name,
            )

            config = _types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                max_output_tokens=request.max_tokens or 8192,
            )

            response_stream = client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config
            )
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text

        except (ImportError, RuntimeError) as sdk_err:
            logger.error(f"Gemini SDK unavailable for streaming: {sdk_err}")
            raise ProviderExecutionError(f"Gemini SDK unavailable: {sdk_err}")
        except Exception as e:
            logger.error(f"Gemini generate_stream error: {e}")
            raise self._map_exception(e)
