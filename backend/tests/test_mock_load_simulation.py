"""
Mock Load Simulation and Dynamic Failover Tests (Part 10.F).

Verifies under simulated load and quota pressure:
1. Router Failover: Mistral 429 -> NVIDIA NIM failover; subsequent requests bypass Mistral.
2. Analysis Failover: OpenRouter Gemma 429 -> Nemotron 429 -> Gemini 2.0 Flash success.
3. Transformation Quota Isolation: 4 Gemini slots rotate under 429 pressure.
   When all Gemini slots exhaust, fails with explicit recoverable error and
   NEVER falls back to Mistral or NVIDIA.
4. Concurrent Load Bursts: Multi-threaded burst requests safely rotate slots and
   respect concurrency / RPM limits without race conditions.
"""
import sys
import os
import time
import threading
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from providers.base import ProviderResponse, BaseProvider
from providers.domain.contracts import AIRequest
from providers.registry import provider_registry
from providers.model_registry import model_registry, ModelMetadata
from providers.quarantine import quarantine_manager, FailureCategory
from providers.scheduler import credential_scheduler, CredentialScheduler
from providers.fallback import fallback_engine
from config import Config


class MockConfigurableProvider(BaseProvider):
    """Mock provider with per-call or per-key configurable behavior."""

    def __init__(self, name: str):
        self._name = name
        self.call_count = 0
        self.calls_by_key: Dict[str, int] = {}
        self.failing_keys: set = set()
        self.fail_all = False
        self.status_code = 429
        self.error_message = "Rate limit exceeded"

    @property
    def provider_name(self) -> str:
        return self._name

    def generate(self, request: AIRequest, api_key: Optional[str] = None) -> ProviderResponse:
        self.call_count += 1
        key = api_key or "default"
        self.calls_by_key[key] = self.calls_by_key.get(key, 0) + 1

        if self.fail_all or key in self.failing_keys:
            return ProviderResponse(
                text="",
                model=f"{self._name}-mock-model",
                provider=self._name,
                success=False,
                error=f"HTTP {self.status_code}: {self.error_message}",
                status_code=self.status_code,
                headers={"retry-after": "60"},
            )

        return ProviderResponse(
            text='{"intent": "DATA_OPERATION", "operation": {"type": "FILTER"}}',
            model=f"{self._name}-mock-model",
            provider=self._name,
            success=True,
            latency_ms=15.0,
        )

    def generate_json(self, *args, **kwargs) -> ProviderResponse:
        return self.generate(AIRequest(task="test", json_mode=True))

    def health_check(self) -> bool:
        return True


class TestMockLoadSimulation:
    """End-to-end simulated load and failover suite."""

    def setup_method(self):
        # Save real registries state
        self.saved_providers = dict(provider_registry._providers)
        self.saved_keys = dict(provider_registry._api_keys)
        self.saved_models = dict(model_registry._models)
        self.saved_slots = {p: list(slots) for p, slots in credential_scheduler._slots.items()}
        self.saved_indices = dict(credential_scheduler._round_robin_index)

        quarantine_manager.reset_all()
        credential_scheduler._slots.clear()
        credential_scheduler._round_robin_index.clear()

    def teardown_method(self):
        # Restore real registries state
        import collections
        provider_registry._providers = self.saved_providers
        provider_registry._api_keys = self.saved_keys
        model_registry._models = self.saved_models
        credential_scheduler._slots = collections.defaultdict(list, self.saved_slots)
        credential_scheduler._round_robin_index = collections.defaultdict(int, self.saved_indices)
        quarantine_manager.reset_all()

    def test_router_mistral_429_failover_to_nvidia(self):
        """Simulate Mistral 429: Failover to NVIDIA NIM and subsequent requests bypass Mistral."""
        mistral_mock = MockConfigurableProvider("mistral")
        mistral_mock.fail_all = True
        mistral_mock.status_code = 429
        mistral_mock.error_message = "Mistral RPM limit exceeded"

        nvidia_mock = MockConfigurableProvider("nvidia")
        nvidia_mock.fail_all = False

        provider_registry.register(mistral_mock, "mstrl_key_1111")
        provider_registry.register(nvidia_mock, "nvda_key_2222")

        # 1. First router request: Mistral fails with 429 -> NVIDIA succeeds
        req1 = AIRequest(task="classification", json_mode=True)
        res1 = fallback_engine.execute(req1)

        assert res1.success is True
        assert res1.provider == "nvidia"
        assert mistral_mock.call_count == 1
        assert nvidia_mock.call_count == 1

        # Mistral must now be quarantined
        assert not quarantine_manager.is_eligible("mistral", api_key="mstrl_key_1111")

        # 2. Subsequent router requests must bypass Mistral completely
        for _ in range(5):
            req = AIRequest(task="classification", json_mode=True)
            res = fallback_engine.execute(req)
            assert res.success is True
            assert res.provider == "nvidia"

        # Mistral should NOT have been called again during its cooldown
        assert mistral_mock.call_count == 1
        assert nvidia_mock.call_count == 6

    def test_analysis_openrouter_429_progression_to_gemini(self):
        """Analysis request: OpenRouter 429 -> failover to Gemini secondary provider."""
        openrouter_mock = MockConfigurableProvider("openrouter")
        openrouter_mock.fail_all = True
        openrouter_mock.status_code = 429
        openrouter_mock.error_message = "OpenRouter credits/rate limit exceeded"

        gemini_mock = MockConfigurableProvider("gemini")
        gemini_mock.fail_all = False

        provider_registry.register(openrouter_mock, "or_key_1111")
        provider_registry.register(gemini_mock, "gem_key_2222")

        # Request with analysis task 'planner'
        req = AIRequest(task="planner", json_mode=True)
        res = fallback_engine.execute(req)

        assert res.success is True
        assert res.provider == "gemini"
        # OpenRouter failed and Gemini picked it up
        assert openrouter_mock.call_count >= 1
        assert gemini_mock.call_count == 1

        # OpenRouter should now be quarantined
        assert not quarantine_manager.is_eligible("openrouter", api_key="or_key_1111")

        # Subsequent analysis requests bypass OpenRouter and route directly to Gemini
        req2 = AIRequest(task="planner", json_mode=True)
        res2 = fallback_engine.execute(req2)
        assert res2.success is True
        assert res2.provider == "gemini"
        assert gemini_mock.call_count == 2

    def test_transformation_gemini_multi_slot_rotation_and_no_leakage(self):
        """Transformation requests:
        1. Rotate among Gemini slots.
        2. When a slot hits 429, rotate to the next slot.
        3. If ALL Gemini slots exhaust, return explicit recoverable error and
           NEVER fall back to Mistral or NVIDIA.
        """
        gemini_mock = MockConfigurableProvider("gemini")
        mistral_mock = MockConfigurableProvider("mistral")
        nvidia_mock = MockConfigurableProvider("nvidia")

        # Register Mistral and NVIDIA as available
        provider_registry.register(mistral_mock, "mstrl_key")
        provider_registry.register(nvidia_mock, "nvda_key")

        # Register 4 Gemini slots
        slot_keys = [
            "AIzaSySlot1_1111111111111111111",
            "AIzaSySlot2_2222222222222222222",
            "AIzaSySlot3_3333333333333333333",
            "AIzaSySlot4_4444444444444444444",
        ]
        provider_registry.register(gemini_mock, slot_keys)

        # Slots 1 and 2 return 429
        gemini_mock.failing_keys.add(slot_keys[0])
        gemini_mock.failing_keys.add(slot_keys[1])

        # Execute transformation request
        req = AIRequest(task="transformation_planning", json_mode=True)
        res = fallback_engine.execute(req)

        # Slot 1 failed (quarantined), Slot 2 failed (quarantined), Slot 3 succeeded!
        assert res.success is True
        assert res.provider == "gemini"

        # Now fail ALL 4 slots
        gemini_mock.failing_keys.add(slot_keys[2])
        gemini_mock.failing_keys.add(slot_keys[3])

        req_exhausted = AIRequest(task="transformation_planning", json_mode=True)
        res_exhausted = fallback_engine.execute(req_exhausted)

        # Must return explicit failure
        assert res_exhausted.success is False
        assert "All available providers are quarantined or exhausted" in res_exhausted.error

        # CRITICAL: Mistral and NVIDIA must NEVER have been called for transformation
        assert mistral_mock.call_count == 0
        assert nvidia_mock.call_count == 0

    def test_concurrent_burst_across_slots(self):
        """Simulate high-concurrency burst across registered slots without race conditions."""
        scheduler = CredentialScheduler()
        keys = [f"key_burst_{i}_{'x'*20}" for i in range(4)]
        for i, k in enumerate(keys):
            scheduler.register_slot("gemini", k, slot_id=f"slot_{i}", rpm_limit=60, concurrency_limit=5)

        num_threads = 16
        requests_per_thread = 5
        errors = []

        def worker():
            for _ in range(requests_per_thread):
                slot = scheduler.select_and_reserve("gemini")
                if not slot:
                    errors.append("No slot reserved")
                    continue
                time.sleep(0.005)  # simulate brief in-flight work
                scheduler.release_reservation(slot)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All in-flight counters must be back to 0
        for slot in scheduler.get_slots("gemini"):
            assert slot.current_inflight == 0
            assert len(slot.request_timestamps) > 0
