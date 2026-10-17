"""
Provider Observability and Diagnostics Module.

Provides comprehensive diagnostic reporting on:
- Registered providers and initialized status.
- Configured credential slots and quota availability.
- Active models assigned to each role.
- Global quarantine and circuit breaker states.
- Aggregated request success/failure metrics.

NEVER exposes API keys, tokens, or credential-bearing URLs.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from providers.model_registry import model_registry
from providers.registry import provider_registry
from providers.scheduler import credential_scheduler
from providers.quarantine import quarantine_manager

logger = logging.getLogger(__name__)


class ProviderDiagnostics:
    """Safe telemetry and diagnostic reporter for Plexis LLM infrastructure."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_metrics: Dict[str, Dict[str, int]] = collections.defaultdict(
            lambda: {"succeeded": 0, "failed": 0, "fallbacks": 0}
        )

    def record_request(self, role: str, provider: str, success: bool, fallback: bool = False) -> None:
        """Record metric for request outcome."""
        key = f"{role}::{provider}"
        with self._lock:
            stats = self._request_metrics[key]
            if success:
                stats["succeeded"] += 1
            else:
                stats["failed"] += 1
            if fallback:
                stats["fallbacks"] += 1

    def get_diagnostics_report(self) -> Dict[str, Any]:
        """
        Generate full diagnostic report.
        Distinguishes: configured, initialized, eligible, quarantined.
        """
        from providers.engine import provider_engine
        provider_engine._ensure_initialized()

        now = time.time()

        # 1. Role to Model Mapping
        role_mapping = {
            "router": {
                "primary": {"provider": "mistral", "models": [m.model_id for m in model_registry.get_models_for_task("classification") if m.provider == "mistral"]},
                "fallback": {"provider": "nvidia", "models": [m.model_id for m in model_registry.get_models_for_task("classification") if m.provider == "nvidia"]},
            },
            "analysis": {
                "primary": {"provider": "openrouter", "models": [m.model_id for m in model_registry.get_models_for_task("planner") if m.provider == "openrouter" and m.priority == 0]},
                "model_fallback": {"provider": "openrouter", "models": [m.model_id for m in model_registry.get_models_for_task("planner") if m.provider == "openrouter" and m.priority == 1]},
                "secondary": {"provider": "gemini", "models": [m.model_id for m in model_registry.get_models_for_task("planner") if m.provider == "gemini"]},
            },
            "transformation": {
                "dedicated_pool": {"provider": "gemini", "models": [m.model_id for m in model_registry.get_models_for_task("transformation_planning")]},
                "cross_role_fallback_permitted": False,
            },
            "conversation": {
                "primary": {"provider": "openrouter", "models": [m.model_id for m in model_registry.get_models_for_task("conversation") if m.provider == "openrouter" and m.priority == 0]},
                "model_fallback": {"provider": "openrouter", "models": [m.model_id for m in model_registry.get_models_for_task("conversation") if m.provider == "openrouter" and m.priority == 1]},
                "secondary": {"provider": "gemini", "models": [m.model_id for m in model_registry.get_models_for_task("conversation") if m.provider == "gemini"]},
            },
        }

        # 2. Provider and Credential Slot Status
        scheduler_diag = credential_scheduler.get_diagnostics()
        registered_providers = provider_registry.get_available()

        providers_status = {}
        all_provider_names = set(registered_providers) | set(scheduler_diag.keys())

        for p in sorted(all_provider_names):
            p_slots = scheduler_diag.get(p, {}).get("slots", [])
            adapter = provider_registry.get(p)
            initialized = adapter is not None
            healthy = adapter.health_check() if initialized and hasattr(adapter, "health_check") else False

            providers_status[p] = {
                "configured": bool(p_slots) or (p in registered_providers),
                "initialized": initialized,
                "healthy": healthy,
                "slots_count": len(p_slots),
                "eligible_slots": sum(1 for s in p_slots if s.get("eligible")),
                "slots": p_slots,
            }

        # 3. Global Quarantine & Circuit States
        quarantine_info = quarantine_manager.get_status()
        quarantine_states = quarantine_info.get("active_scopes", {})

        # 4. Telemetry Metrics
        with self._lock:
            metrics_copy = {k: dict(v) for k, v in self._request_metrics.items()}

        return {
            "timestamp": now,
            "roles": role_mapping,
            "providers": providers_status,
            "circuits": quarantine_states,
            "quarantine_metrics": dict(quarantine_manager._metrics),
            "request_metrics": metrics_copy,
        }


provider_diagnostics = ProviderDiagnostics()
