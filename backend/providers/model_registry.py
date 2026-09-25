"""
Model registry and metadata definitions for LLM providers.

NEW MODEL HIERARCHY (2026-08-25):
  PRIMARY:   groq / openai/gpt-oss-20b         — conversation, planner, all tasks
  FALLBACK:  groq / Qwen/Qwen3.6-27B-A3B-Instruct — conversation fallback, planner fallback
  HIGH-REASONING: groq / openai/gpt-oss-120b   — complex reasoning, high-quality analysis

DEPRECATED (health_score=0.0, will not be selected):
  llama-3.3-70b-versatile  → replaced by openai/gpt-oss-20b
  gemini-1.5-pro           → replaced by openai/gpt-oss-120b
  gemini-2.0-flash         → Gemini removed from normal conversation chain
  mistral-medium-latest    → Qwen/Qwen3.6-27B-A3B-Instruct replaces as fallback
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    model_id: str
    provider: str
    model_name: str
    context_window: int
    max_output_tokens: int
    supports_vision: bool
    supports_json_mode: bool
    supports_tool_calling: bool
    supports_streaming: bool
    supports_reasoning: bool
    task_affinities: Dict[str, float] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    estimated_cost_per_1k: float = 0.0
    reliability_score: float = 1.0
    health_score: float = 1.0
    priority: int = 0


class ModelRegistry:
    """Registry to manage metadata for all available models."""

    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}

    def register(self, model: ModelMetadata) -> None:
        """Register a new model."""
        self._models[model.model_id] = model
        logger.debug("Registered model %s (provider=%s health=%.1f)",
                     model.model_id, model.provider, model.health_score)

    def get(self, model_id: str) -> Optional[ModelMetadata]:
        """Get model metadata by ID."""
        return self._models.get(model_id)

    def get_models_for_provider(self, provider: str) -> List[ModelMetadata]:
        """Get all ACTIVE (health_score > 0.3) models for a specific provider."""
        return [m for m in self._models.values()
                if m.provider == provider and m.health_score > 0.3]

    def get_models_for_task(self, task: str, require_json: bool = False) -> List[ModelMetadata]:
        """
        Get models ranked for a specific task.
        Only returns models with health_score > 0.3.
        Sorted by: priority ASC, task affinity DESC.
        """
        result = []
        for m in self._models.values():
            if m.health_score <= 0.3:
                continue
            if require_json and not m.supports_json_mode:
                continue
            affinity = m.task_affinities.get(task, 0.0)
            if affinity > 0:
                result.append(m)
        result.sort(key=lambda m: (m.priority, -m.task_affinities.get(task, 0.0)))
        return result

    def all_models(self) -> List[ModelMetadata]:
        """Get all registered models (including inactive)."""
        return list(self._models.values())

    def active_models(self) -> List[ModelMetadata]:
        """Get only active models (health_score > 0.3)."""
        return [m for m in self._models.values() if m.health_score > 0.3]

    def update_health(self, model_id: str, score: float) -> None:
        if model_id in self._models:
            self._models[model_id].health_score = max(0.0, min(1.0, score))

    def mark_permanently_failed(self, model_id: str) -> None:
        """Mark a model as permanently unavailable (404 / model not found)."""
        if model_id in self._models:
            self._models[model_id].health_score = 0.0
            logger.warning(
                "[ModelRegistry] Model marked permanently unavailable: %s", model_id
            )

    def update_latency(self, model_id: str, latency_ms: float) -> None:
        if model_id in self._models:
            model = self._models[model_id]
            model.avg_latency_ms = (model.avg_latency_ms * 0.9) + (latency_ms * 0.1)

    def update_reliability(self, model_id: str, success: bool) -> None:
        if model_id in self._models:
            model = self._models[model_id]
            value = 1.0 if success else 0.0
            model.reliability_score = (model.reliability_score * 0.95) + (value * 0.05)


model_registry = ModelRegistry()

# ── NEW GROQ MODELS (primary provider hierarchy) ──────────────────────────────
# All Groq models use the same Groq API; model name determines capability tier.

# PRIMARY: GPT-OSS 20B — conversation, planner, all standard tasks
model_registry.register(ModelMetadata(
    model_id="openai/gpt-oss-20b",
    provider="groq",
    model_name="openai/gpt-oss-20b",
    context_window=128000,
    max_output_tokens=8192,
    supports_vision=False,
    supports_json_mode=True,
    supports_tool_calling=True,
    supports_streaming=True,
    supports_reasoning=False,
    task_affinities={
        "chat": 1.0,
        "conversation": 1.0,
        "planner": 1.0,
        "presentation": 1.0,
        "report": 1.0,
        "classification": 1.0,
        "spreadsheet_interpret": 1.0,
        "router": 1.0,
        "explanation": 1.0,
        "title": 1.0,
        "search": 0.9,
        "stream": 1.0,
        "fallback": 1.0,
        # Investigation engine tasks
        "interpreter": 1.0,
        "insight_synthesizer": 1.0,
        "analysis": 1.0,
    },
    avg_latency_ms=600.0,
    estimated_cost_per_1k=0.0,
    reliability_score=1.0,
    health_score=1.0,
    priority=0,  # Highest priority
))

# DEPRECATED: Qwen 3.6 27B — decommissioned on Groq; health_score=0.0 ensures never selected
model_registry.register(ModelMetadata(
    model_id="Qwen/Qwen3.6-27B-A3B-Instruct",
    provider="groq",
    model_name="Qwen/Qwen3.6-27B-A3B-Instruct",
    context_window=128000,
    max_output_tokens=8192,
    supports_vision=False,
    supports_json_mode=True,
    supports_tool_calling=True,
    supports_streaming=True,
    supports_reasoning=True,
    task_affinities={},
    avg_latency_ms=0.0,
    estimated_cost_per_1k=0.0,
    reliability_score=0.0,
    health_score=0.0,  # PERMANENTLY DISABLED — model decommissioned on Groq
    priority=99,
))

# HIGH-REASONING: GPT-OSS 120B — complex queries, high-reasoning fallback
model_registry.register(ModelMetadata(
    model_id="openai/gpt-oss-120b",
    provider="groq",
    model_name="openai/gpt-oss-120b",
    context_window=128000,
    max_output_tokens=8192,
    supports_vision=False,
    supports_json_mode=True,
    supports_tool_calling=True,
    supports_streaming=True,
    supports_reasoning=True,
    task_affinities={
        "chat": 0.8,
        "conversation": 0.8,
        "planner": 0.8,
        "high_reasoning": 1.0,
        "complex_analysis": 1.0,
        "presentation": 0.8,
        "report": 0.8,
        "classification": 0.8,
        "spreadsheet_interpret": 0.8,
        "explanation": 0.85,
        "fallback": 0.8,
        # Investigation engine tasks
        "interpreter": 0.9,
        "insight_synthesizer": 0.9,
        "analysis": 0.9,
    },
    avg_latency_ms=2000.0,
    estimated_cost_per_1k=0.0,
    reliability_score=1.0,
    health_score=1.0,
    priority=2,  # Third priority — for high-complexity or when others fail
))

# ── OPENROUTER (disabled — credentials unavailable / not configured) ──────────
# These remain for future re-enabling if OpenRouter credentials are provided.
# Set health_score=0.0 so ModelRegistry.get_models_for_task() never returns them.
model_registry.register(ModelMetadata(
    model_id="deepseek/deepseek-chat-v3",
    provider="openrouter",
    model_name="deepseek/deepseek-chat-v3",
    context_window=131072,
    max_output_tokens=8192,
    supports_vision=False,
    supports_json_mode=True,
    supports_tool_calling=True,
    supports_streaming=True,
    supports_reasoning=False,
    task_affinities={
        "chat": 0.6,
        "conversation": 0.6,
        "planner": 0.6,
        "report": 0.7,
        "classification": 0.6,
        "spreadsheet_interpret": 0.7,
        "fallback": 0.7,
    },
    avg_latency_ms=2000.0,
    estimated_cost_per_1k=0.27,
    reliability_score=0.95,
    health_score=0.0,   # DISABLED — OpenRouter not configured; enable by setting health_score=1.0
    priority=99,
))

model_registry.register(ModelMetadata(
    model_id="meta-llama/llama-4-maverick",
    provider="openrouter",
    model_name="meta-llama/llama-4-maverick",
    context_window=1048576,
    max_output_tokens=32768,
    supports_vision=True,
    supports_json_mode=True,
    supports_tool_calling=True,
    supports_streaming=True,
    supports_reasoning=False,
    task_affinities={
        "chat": 0.5,
        "conversation": 0.5,
        "planner": 0.5,
        "spreadsheet_interpret": 0.6,
        "fallback": 0.6,
    },
    avg_latency_ms=1800.0,
    estimated_cost_per_1k=0.20,
    reliability_score=0.90,
    health_score=0.0,   # DISABLED — OpenRouter not configured; enable by setting health_score=1.0
    priority=99,
))

# ── DEPRECATED — health_score=0.0 ensures they are NEVER selected ─────────────
# These remain in the registry for observability/audit only.

model_registry.register(ModelMetadata(
    model_id="llama-3.3-70b-versatile",
    provider="groq",
    model_name="llama-3.3-70b-versatile",
    context_window=32768, max_output_tokens=8192,
    supports_vision=False, supports_json_mode=True, supports_tool_calling=True,
    supports_streaming=True, supports_reasoning=False,
    task_affinities={},
    avg_latency_ms=0.0, estimated_cost_per_1k=0.0,
    reliability_score=0.0,
    health_score=0.0,  # PERMANENTLY DISABLED — 404 on Groq API
    priority=99,
))

model_registry.register(ModelMetadata(
    model_id="gemini-2.0-flash",
    provider="gemini",
    model_name="gemini-2.0-flash",
    context_window=1048576, max_output_tokens=8192,
    supports_vision=True, supports_json_mode=True, supports_tool_calling=True,
    supports_streaming=True, supports_reasoning=False,
    task_affinities={},
    avg_latency_ms=0.0, estimated_cost_per_1k=0.0,
    reliability_score=0.0,
    health_score=0.0,  # DEPRECATED — Gemini removed from normal routing
    priority=99,
))

model_registry.register(ModelMetadata(
    model_id="gemini-1.5-pro",
    provider="gemini",
    model_name="gemini-1.5-pro",
    context_window=2000000, max_output_tokens=8192,
    supports_vision=True, supports_json_mode=True, supports_tool_calling=True,
    supports_streaming=True, supports_reasoning=True,
    task_affinities={},
    avg_latency_ms=0.0, estimated_cost_per_1k=0.0,
    reliability_score=0.0,
    health_score=0.0,  # DEPRECATED — 404 on Gemini API
    priority=99,
))

model_registry.register(ModelMetadata(
    model_id="mistral-medium-latest",
    provider="mistral",
    model_name="mistral-medium-latest",
    context_window=32768, max_output_tokens=8192,
    supports_vision=False, supports_json_mode=True, supports_tool_calling=True,
    supports_streaming=True, supports_reasoning=False,
    task_affinities={},
    avg_latency_ms=0.0, estimated_cost_per_1k=0.0,
    reliability_score=0.0,
    health_score=0.0,  # DEPRECATED — replaced by Qwen as fallback
    priority=99,
))
