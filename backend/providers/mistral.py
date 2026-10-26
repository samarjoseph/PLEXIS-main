import time
import requests
import logging
import json
from typing import Optional, Any, Generator, Dict

from config import Config
from providers.base import ProviderResponse
from providers.domain.contracts import IProviderAdapter, AIRequest, ProviderCapabilities
from providers.errors import ProviderExecutionError, ProviderAuthenticationError, ProviderRateLimitError

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

    def _resolve_model(self, request: AIRequest) -> str:
        """Resolve model from request or configuration."""
        if hasattr(request, "model_id") and request.model_id:
            return request.model_id
        # Use configured Router Mistral model (Mistral Small 4)
        return Config.ROUTER_MISTRAL_MODEL or "mistral-small-latest"

    def generate(self, request: AIRequest, api_key: Optional[str] = None) -> ProviderResponse:
        start_time = time.time()
        effective_key = api_key or self.api_key
        headers = {
            "Authorization": f"Bearer {effective_key}",
            "Content-Type": "application/json"
        }
        
        messages = request.messages.copy() if request.messages else []
        if not messages and request.task:
            messages.append({"role": "user", "content": request.task})

        if request.system_prompt and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": request.system_prompt})
        
        model_name = self._resolve_model(request)
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
        }
        
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        status_code = None
        resp_headers: Dict[str, Any] = {}
        retry_after = None

        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=(3.0, 10.0))
            status_code = response.status_code
            resp_headers = dict(response.headers)
            if "retry-after" in resp_headers:
                try:
                    retry_after = float(resp_headers["retry-after"])
                except (ValueError, TypeError):
                    pass

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
                status_code=status_code,
                headers=resp_headers,
                retry_after=retry_after,
                raw_response=data
            )
        except requests.exceptions.HTTPError as he:
            err_resp = he.response
            sc = err_resp.status_code if err_resp is not None else 500
            h = dict(err_resp.headers) if err_resp is not None else {}
            ra = None
            if "retry-after" in h:
                try:
                    ra = float(h["retry-after"])
                except (ValueError, TypeError):
                    pass
            err_text = ""
            try:
                err_text = err_resp.text if err_resp is not None else str(he)
            except Exception:
                err_text = str(he)

            logger.error(f"Mistral HTTP {sc} error: {err_text}")
            return ProviderResponse(
                text="",
                model=model_name,
                provider=self._name,
                success=False,
                error=f"HTTP {sc}: {err_text}",
                status_code=sc,
                headers=h,
                retry_after=ra,
                raw_response={"error": err_text, "status_code": sc}
            )
        except Exception as e:
            logger.error(f"Mistral generate error: {e}")
            return ProviderResponse(
                text="",
                model=model_name,
                provider=self._name,
                success=False,
                error=str(e),
                status_code=status_code,
                headers=resp_headers,
                retry_after=retry_after
            )
            
    def generate_stream(self, request: AIRequest, api_key: Optional[str] = None) -> Generator[str, None, None]:
        """Stream text chunks using Mistral API."""
        effective_key = api_key or self.api_key
        messages = request.messages.copy() if request.messages else []
        if not messages and request.task:
            messages.append({"role": "user", "content": request.task})

        if request.system_prompt and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": request.system_prompt})

        model_name = self._resolve_model(request)

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
                headers={"Authorization": f"Bearer {effective_key}", "Content-Type": "application/json"},
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
            raise ProviderExecutionError(str(e))

    def health_check(self) -> bool:
        """Health check verifying network and credential readiness."""
        return bool(self.api_key)
