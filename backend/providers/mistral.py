import time
import requests
import logging
import json
from typing import Optional, Any, Generator

from providers.base import ProviderResponse
from providers.domain.contracts import IProviderAdapter, AIRequest, ProviderCapabilities
from providers.errors import ProviderExecutionError

logger = logging.getLogger(__name__)

class MistralProvider(IProviderAdapter):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.mistral.ai/v1/chat/completions"
        self._name = "mistral"
        
    @property
    def provider_name(self) -> str:
        return self._name
        
    def get_capabilities(self, model_name: str) -> ProviderCapabilities:
        """Return capabilities for the given Mistral model."""
        return ProviderCapabilities(
            vision=False,
            embeddings=False,
            parallel_tool_calling=True,
            structured_output=True,
            temperature_support=True,
            multimodal=False,
            streaming=True,
            json_mode=True,
            reasoning_level="none",
            max_input_tokens=32000,
            max_output_tokens=4096,
            latency_profile="medium",
            cost_profile="medium"
        )

    def _map_exception(self, e: Exception) -> Exception:
        """Map generic exceptions to ProviderExecutionError."""
        return ProviderExecutionError(str(e))

    def generate(self, request: AIRequest) -> ProviderResponse:
        start_time = time.time()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = request.messages.copy() if request.messages else []
        if not messages and request.task:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.task})
        
        model_name = "mistral-large-latest" if request.quality_target == "HIGH_QUALITY" else "open-mistral-nemo"
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
        }
        
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            latency_ms = (time.time() - start_time) * 1000
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            
            return ProviderResponse(
                text=content,
                model=model_name,
                provider=self._name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                success=True,
                raw_response=data
            )
        except Exception as e:
            logger.error(f"Mistral generate error: {e}")
            mapped_error = self._map_exception(e)
            return ProviderResponse(
                text="",
                model=model_name,
                provider=self._name,
                success=False,
                error=str(mapped_error)
            )
            
    def generate_stream(self, request: AIRequest) -> Generator[str, None, None]:
        """Stream text chunks using Mistral API."""
        messages = request.messages.copy() if request.messages else []
        if not messages and request.task:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.task})

        model_name = "mistral-large-latest" if request.quality_target == "HIGH_QUALITY" else "open-mistral-nemo"

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": True,
        }

        try:
            with requests.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                stream=True,
                timeout=60,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
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
                        delta = data["choices"][0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except (KeyError, json.JSONDecodeError):
                        continue
        except Exception as e:
            logger.error(f"Mistral generate_stream error: {e}")
            raise self._map_exception(e)
