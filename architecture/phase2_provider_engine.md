# Phase 2 — Provider Engine & Model Registry

> Feature implementation plan for the LLM Provider abstraction layer.
> Master plan reference: `implementation_plan.md` → Phase 2, Enhancement 3, Enhancement 4

---

## Objective

Build a provider-independent LLM abstraction layer so no component outside `providers/` ever imports a specific LLM SDK directly. Every LLM call flows through:

```
Component → ProviderEngine.generate(task, prompt) → Model Selector → Retry → Fallback → Circuit Breaker → Provider Call
```

---

## Files to Create

```
backend/providers/
├── __init__.py          # Public API: provider_engine singleton
├── base.py              # BaseProvider abstract class
├── registry.py          # ProviderRegistry — manages provider instances
├── model_registry.py    # ModelRegistry — model metadata + selection
├── selector.py          # ModelSelector — picks best model for task
├── health.py            # HealthMonitor — tracks provider health
├── retry.py             # RetryEngine — exponential backoff
├── fallback.py          # FallbackEngine — tries next provider on failure
├── circuit_breaker.py   # CircuitBreaker — stops calling broken providers
├── engine.py            # ProviderEngine — main orchestrator
├── gemini.py            # Gemini provider implementation
└── openrouter.py        # OpenRouter provider implementation
└── groq.py              # groq provider implementation
```

---

## Key Interfaces

### BaseProvider (base.py)
```python
class BaseProvider(ABC):
    provider_name: str
    
    async generate(prompt, model_name, temperature, max_tokens) → ProviderResponse
    async generate_json(prompt, model_name, temperature, max_tokens) → dict
    async health_check() → bool
```

### ProviderResponse
```python
@dataclass
class ProviderResponse:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    success: bool
```

### ProviderEngine (engine.py)
```python
class ProviderEngine:
    generate(task, prompt, temperature, max_tokens, require_json) → ProviderResponse
    generate_json(task, prompt, temperature, max_tokens) → dict
```
This is the ONLY public interface. All other classes are internal.

---

## Model Selection Algorithm

1. Filter by required capabilities (e.g., `supports_json_mode` for planner tasks)
2. Filter by health (score > 0.3)
3. Rank by: `task_affinity × reliability_score × (1 / normalized_cost)`, adjusted by priority
4. Select top-ranked model
5. On failure → fallback to next-ranked model

---

## Implementation Progress

- [ ] `base.py` — BaseProvider ABC + ProviderResponse dataclass
- [ ] `model_registry.py` — ModelMetadata dataclass + ModelRegistry with pre-registered models
- [ ] `registry.py` — ProviderRegistry managing provider instances
- [ ] `health.py` — HealthMonitor with rolling failure tracking
- [ ] `circuit_breaker.py` — CircuitBreaker per provider
- [ ] `retry.py` — RetryEngine with exponential backoff
- [ ] `selector.py` — ModelSelector implementing the ranking algorithm
- [ ] `fallback.py` — FallbackEngine trying alternatives on failure
- [ ] `gemini.py` — Gemini provider using google-generativeai SDK
- [ ] `openrouter.py` — OpenRouter provider using requests
- [ ] `engine.py` — ProviderEngine orchestrator (main public API)
- [ ] `__init__.py` — Exports provider_engine singleton
- [ ] Integration with config.py for API keys
- [ ] Event bus integration (provider_called, provider_failed, provider_switched)
