import time
import json
import logging
import requests
from typing import Optional, Dict, Any, Generator

from providers.base import ProviderResponse
from providers.domain.contracts import IProviderAdapter, AIRequest, ProviderCapabilities

logger = logging.getLogger(__name__)

class OpenRouterProvider(IProviderAdapter):
    """OpenRouter provider using requests API, behind ACL."""

    def __init__(self, api_key: str):
        """Initialize OpenRouter provider."""
        self._api_key = api_key
        self.endpoint = 'https://openrouter.ai/api/v1/chat/completions'

    @property
    def provider_name(self) -> str:
        return 'openrouter'

    def get_capabilities(self, model_name: str) -> ProviderCapabilities:
        """Return capabilities for the given OpenRouter model."""
        return ProviderCapabilities(
            vision=True,
            embeddings=False,
            parallel_tool_calling=True,
            structured_output=True,
            temperature_support=True,
            multimodal=True,
            streaming=True,
            json_mode=True,
            reasoning_level="advanced" if "claude-3-opus" in model_name or "gpt-4" in model_name else "basic",
            max_input_tokens=128000,
            max_output_tokens=4096,
            latency_profile="medium",
            cost_profile="medium"
        )

    def generate(self, request: AIRequest) -> ProviderResponse:
        """Generate text using OpenRouter, governed by AIRequest."""
        try:
            messages = request.messages.copy() if request.messages else []
            if not messages and request.task:
                if request.system_prompt:
                    messages.append({'role': 'system', 'content': request.system_prompt})
                messages.append({'role': 'user', 'content': request.task})

            headers = {
                'Authorization': f'Bearer {self._api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://plexis.ai',
                'X-Title': 'Plexis'
            }

            model_name = "anthropic/claude-3-5-sonnet" if request.quality_target == "HIGH_QUALITY" else "openai/gpt-4o-mini"

            body = {
                'model': model_name,
                'messages': messages,
                'temperature': request.temperature,
                'max_tokens': request.max_tokens or 4096
            }

            if request.json_mode:
                body['response_format'] = {'type': 'json_object'}

            start_time = time.time()
            response = requests.post(self.endpoint, headers=headers, json=body, timeout=60)
            response.raise_for_status()
            latency_ms = (time.time() - start_time) * 1000
            
            data = response.json()
            text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
            usage = data.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)

            return ProviderResponse(
                text=text,
                model=model_name,
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                success=True,
                raw_response=data
            )
        except Exception as e:
            logger.error(f"OpenRouter generate error: {e}")
            return ProviderResponse(
                text='',
                model="unknown",
                provider=self.provider_name,
                success=False,
                error=str(e)
            )

    def generate_stream(self, request: AIRequest) -> Generator[str, None, None]:
        """Stream text chunks using OpenRouter API."""
        try:
            messages = request.messages.copy() if request.messages else []
            if not messages and request.task:
                if request.system_prompt:
                    messages.append({'role': 'system', 'content': request.system_prompt})
                messages.append({'role': 'user', 'content': request.task})

            headers = {
                'Authorization': f'Bearer {self._api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://plexis.ai',
                'X-Title': 'Plexis'
            }

            model_name = "anthropic/claude-3-5-sonnet" if request.quality_target == "HIGH_QUALITY" else "openai/gpt-4o-mini"

            body = {
                'model': model_name,
                'messages': messages,
                'temperature': request.temperature,
                'max_tokens': request.max_tokens or 4096,
                'stream': True
            }

            with requests.post(self.endpoint, headers=headers, json=body, stream=True, timeout=60) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8")
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[6:].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_str)
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except (KeyError, json.JSONDecodeError):
                        continue
        except Exception as e:
            logger.error(f"OpenRouter generate_stream error: {e}")
            raise e

