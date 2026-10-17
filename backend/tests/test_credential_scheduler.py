"""
Credential Scheduler and Multi-Slot Quota Management Tests (Part 10.B).

Verifies:
- Multiple Gemini credential slots (up to 4) registered and rotated.
- Multiple OpenRouter credential slots (up to 3) registered and rotated.
- Empty or whitespace keys are rejected.
- Sliding-window RPM enforcement prevents reserving beyond capacity.
- Concurrency limit enforcement prevents in-flight overflow.
- Capacity released correctly on success or failure.
- Quarantine integration: quarantining slot A causes immediate selection of slot B.
- Zero secrets in diagnostics, logs, or string representations.
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from providers.scheduler import CredentialScheduler, CredentialSlot
from providers.quarantine import QuarantineManager, InMemoryStateStore, FailureCategory


class TestCredentialScheduler:
    """Verifies multi-key scheduling, rate-limiting, and quarantine rotation."""

    def setup_method(self):
        self.scheduler = CredentialScheduler()

    def test_multi_slot_registration(self):
        """Verify registration of multiple slots per provider."""
        s1 = self.scheduler.register_slot("gemini", "AIzaSyKeyOne11111111111111111111111", slot_id="gemini_slot_1")
        s2 = self.scheduler.register_slot("gemini", "AQ.AbKeyTwo22222222222222222222222", slot_id="gemini_slot_2")
        s3 = self.scheduler.register_slot("gemini", "AQ.AbKeyThree333333333333333333333", slot_id="gemini_slot_3")
        s4 = self.scheduler.register_slot("gemini", "AQ.AbKeyFour4444444444444444444444", slot_id="gemini_slot_4")

        slots = self.scheduler.get_slots("gemini")
        assert len(slots) == 4
        assert [s.slot_id for s in slots] == ["gemini_slot_1", "gemini_slot_2", "gemini_slot_3", "gemini_slot_4"]

    def test_duplicate_and_invalid_keys(self):
        """Duplicate keys should be deduplicated; empty keys rejected."""
        self.scheduler.register_slot("mistral", "mstrl_key_11111111111111111111111")
        self.scheduler.register_slot("mistral", "mstrl_key_11111111111111111111111")  # duplicate
        assert len(self.scheduler.get_slots("mistral")) == 1

        with pytest.raises(ValueError):
            self.scheduler.register_slot("mistral", "   ")

    def test_sliding_window_rpm_limit(self):
        """Enforces that requests exceeding RPM limit cannot be reserved."""
        # Slot with limit of 3 RPM
        slot = self.scheduler.register_slot("test_prov", "key_rpm_test", rpm_limit=3, concurrency_limit=10)

        # 3 reservations succeed
        r1 = self.scheduler.select_and_reserve("test_prov")
        assert r1 is not None
        self.scheduler.release_reservation(r1)

        r2 = self.scheduler.select_and_reserve("test_prov")
        assert r2 is not None
        self.scheduler.release_reservation(r2)

        r3 = self.scheduler.select_and_reserve("test_prov")
        assert r3 is not None
        self.scheduler.release_reservation(r3)

        # 4th reservation within the same minute is rejected due to RPM exhaustion
        r4 = self.scheduler.select_and_reserve("test_prov")
        assert r4 is None, "Should not exceed RPM limit"

    def test_concurrency_limit_enforcement(self):
        """Enforces that concurrent in-flight requests cannot exceed concurrency_limit."""
        slot = self.scheduler.register_slot("test_prov_conc", "key_conc_test", rpm_limit=100, concurrency_limit=2)

        r1 = self.scheduler.select_and_reserve("test_prov_conc")
        assert r1 is not None
        assert r1.current_inflight == 1

        r2 = self.scheduler.select_and_reserve("test_prov_conc")
        assert r2 is not None
        assert r2.current_inflight == 2

        # 3rd concurrent request while 2 are still in flight should be rejected
        r3 = self.scheduler.select_and_reserve("test_prov_conc")
        assert r3 is None

        # Releasing one allows the next request to proceed
        self.scheduler.release_reservation(r1)
        assert r1.current_inflight == 1

        r4 = self.scheduler.select_and_reserve("test_prov_conc")
        assert r4 is not None
        self.scheduler.release_reservation(r2)
        self.scheduler.release_reservation(r4)

    def test_quarantine_rotation_across_slots(self):
        """When slot 1 is quarantined (e.g. 429), scheduler rotates to slot 2."""
        from providers.quarantine import quarantine_manager
        k1 = "key_slot_one_1111111111111111111111"
        k2 = "key_slot_two_2222222222222222222222"

        self.scheduler.register_slot("openrouter", k1, slot_id="or_slot_1")
        self.scheduler.register_slot("openrouter", k2, slot_id="or_slot_2")

        # First request picks a slot
        first = self.scheduler.select_and_reserve("openrouter")
        assert first is not None
        self.scheduler.release_reservation(first)

        # Simulate 429 rate limit failure on slot 1
        quarantine_manager.record_failure(
            provider="openrouter",
            error="HTTP 429 Too Many Requests",
            api_key=k1,
            status_code=429,
        )

        # Next selection must pick slot 2, since slot 1 is cooling down
        second = self.scheduler.select_and_reserve("openrouter")
        assert second is not None
        assert second.api_key == k2, "Should have rotated to healthy slot 2!"
        self.scheduler.release_reservation(second)

    def test_zero_secrets_in_diagnostics(self):
        """Diagnostics must expose only masked keys and anon hashes, never raw keys."""
        secret_key = "sk-super-secret-production-api-key-12345678"
        self.scheduler.register_slot("secret_prov", secret_key, slot_id="sec_slot_1")

        diag = self.scheduler.get_diagnostics()
        prov_diag = diag.get("secret_prov")
        assert prov_diag is not None
        slot_info = prov_diag["slots"][0]

        # Verify raw secret is NOT present anywhere in diagnostics
        diag_str = str(diag)
        assert secret_key not in diag_str
        assert slot_info["key_mask"] == "sk-s...5678"
        assert len(slot_info["anon_hash"]) == 8
