"""
Credential Registry and Quota-Aware Scheduler for Plexis LLM Providers.

Manages multi-key credential pools per provider (Gemini 4 slots, OpenRouter 3 slots,
Mistral 1 slot, NVIDIA 1 slot), enforces true quota scopes, tracks in-flight concurrency,
provides sliding-window RPM rate-limiting, and coordinates with QuarantineManager.
"""
from __future__ import annotations

import collections
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from providers.quarantine import quarantine_manager

logger = logging.getLogger(__name__)


# ── Documented default RPM and concurrency limits per provider ─────────────────
# Configurable per slot; sensible defaults for free tiers
DEFAULT_PROVIDER_LIMITS = {
    "gemini": {"rpm": 15, "concurrency": 3},        # Gemini free tier default 15 RPM
    "openrouter": {"rpm": 20, "concurrency": 4},    # OpenRouter free tier default 20 RPM
    "mistral": {"rpm": 30, "concurrency": 5},       # Mistral Small tier
    "nvidia": {"rpm": 40, "concurrency": 5},        # NVIDIA NIM default 40 RPM
    "groq": {"rpm": 30, "concurrency": 5},          # Groq default 30 RPM
    "mock": {"rpm": 10000, "concurrency": 100},
}


@dataclass
class CredentialSlot:
    """Represents a single registered API credential slot."""
    slot_id: str
    provider: str
    api_key: str
    account_id: str
    rpm_limit: int = 60
    concurrency_limit: int = 5
    current_inflight: int = 0
    request_timestamps: collections.deque = field(default_factory=lambda: collections.deque(maxlen=1000))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def anon_id(self) -> str:
        """Anonymized 8-character hash of the API key for logging and quarantine keys."""
        return hashlib.sha256(self.api_key.encode()).hexdigest()[:8]

    @property
    def masked_key(self) -> str:
        """Safe masked representation (e.g. 'mstr...syn') without leaking secrets."""
        if not self.api_key:
            return "[EMPTY]"
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"

    def can_reserve(self, now: Optional[float] = None) -> bool:
        """Check if this slot has capacity (RPM and concurrency)."""
        now = now or time.time()
        with self._lock:
            # Check concurrency
            if self.current_inflight >= self.concurrency_limit:
                return False
            # Clean expired timestamps older than 60 seconds
            while self.request_timestamps and now - self.request_timestamps[0] > 60.0:
                self.request_timestamps.popleft()
            # Check RPM
            if len(self.request_timestamps) >= self.rpm_limit:
                return False
            return True

    def reserve(self, now: Optional[float] = None) -> bool:
        """Atomically reserve capacity on this slot."""
        now = now or time.time()
        with self._lock:
            if self.current_inflight >= self.concurrency_limit:
                return False
            while self.request_timestamps and now - self.request_timestamps[0] > 60.0:
                self.request_timestamps.popleft()
            if len(self.request_timestamps) >= self.rpm_limit:
                return False
            self.current_inflight += 1
            self.request_timestamps.append(now)
            return True

    def release(self) -> None:
        """Release in-flight concurrency count."""
        with self._lock:
            self.current_inflight = max(0, self.current_inflight - 1)


class CredentialScheduler:
    """
    Central scheduler coordinating credential slots across all providers.

    Features:
    - Thread-safe slot selection and reservations.
    - Health & Quarantine check via QuarantineManager before selection.
    - Capacity-aware round-robin / least-busy selection.
    - Graceful fallback when slots are exhausted.
    - Comprehensive diagnostics without leaking API keys.
    """

    def __init__(self) -> None:
        self._slots: Dict[str, List[CredentialSlot]] = collections.defaultdict(list)
        self._lock = threading.Lock()
        self._round_robin_index: Dict[str, int] = collections.defaultdict(int)

    def register_slot(
        self,
        provider: str,
        api_key: str,
        slot_id: Optional[str] = None,
        account_id: Optional[str] = None,
        rpm_limit: Optional[int] = None,
        concurrency_limit: Optional[int] = None,
    ) -> CredentialSlot:
        """Register a new credential slot for a provider."""
        if not api_key or not api_key.strip():
            raise ValueError("api_key cannot be empty")
        api_key = api_key.strip()
        provider = provider.lower().strip()

        limits = DEFAULT_PROVIDER_LIMITS.get(provider, {"rpm": 60, "concurrency": 5})
        rpm = rpm_limit or limits["rpm"]
        conc = concurrency_limit or limits["concurrency"]

        with self._lock:
            existing = self._slots.setdefault(provider, [])
            # Check if key already registered
            for slot in existing:
                if slot.api_key == api_key:
                    return slot

            slot_idx = len(existing) + 1
            actual_slot_id = slot_id or f"{provider}_slot_{slot_idx}"
            actual_account_id = account_id or f"{provider}_account_{slot_idx}"

            slot = CredentialSlot(
                slot_id=actual_slot_id,
                provider=provider,
                api_key=api_key,
                account_id=actual_account_id,
                rpm_limit=rpm,
                concurrency_limit=conc,
            )
            existing.append(slot)
            logger.info(
                f"[CredentialScheduler] Registered slot={actual_slot_id} "
                f"provider={provider} key={slot.masked_key} rpm={rpm} conc={conc}"
            )
            return slot

    def get_slots(self, provider: str) -> List[CredentialSlot]:
        """Return all registered slots for a provider."""
        with self._lock:
            return list(self._slots.get(provider.lower().strip(), []))

    def select_and_reserve(
        self,
        provider: str,
        model_id: Optional[str] = None,
    ) -> Optional[CredentialSlot]:
        """
        Find an eligible, healthy slot for the provider with available capacity,
        and atomically reserve a capacity token.
        """
        provider = provider.lower().strip()
        now = time.time()

        with self._lock:
            slots = self._slots.get(provider, [])
            if not slots:
                return None

            # Filter slots by QuarantineManager eligibility
            eligible_slots: List[CredentialSlot] = []
            for slot in slots:
                if quarantine_manager.is_eligible(
                    provider=provider,
                    api_key=slot.api_key,
                    model_id=model_id,
                ):
                    eligible_slots.append(slot)
                else:
                    logger.debug(
                        f"[CredentialScheduler] Slot {slot.slot_id} quarantined for "
                        f"provider={provider} model={model_id}"
                    )

            if not eligible_slots:
                logger.warning(
                    f"[CredentialScheduler] All {len(slots)} slots for provider={provider} "
                    f"are currently quarantined or cooling down."
                )
                return None

            # Find slot with available capacity (prefer least busy / least recently used)
            # Try round-robin from last selected index
            start_idx = self._round_robin_index[provider] % len(eligible_slots)
            ordered_slots = eligible_slots[start_idx:] + eligible_slots[:start_idx]

            # Filter for capacity
            available_slots = [s for s in ordered_slots if s.can_reserve(now)]
            if not available_slots:
                logger.warning(
                    f"[CredentialScheduler] All eligible slots for provider={provider} "
                    f"have reached capacity (RPM or concurrency limit)."
                )
                return None

            # Pick slot with lowest current in-flight requests
            available_slots.sort(key=lambda s: s.current_inflight)
            chosen = available_slots[0]

            if chosen.reserve(now):
                self._round_robin_index[provider] = (
                    eligible_slots.index(chosen) + 1
                ) % len(eligible_slots)
                logger.debug(
                    f"[CredentialScheduler] Reserved slot={chosen.slot_id} "
                    f"provider={provider} inflight={chosen.current_inflight}"
                )
                return chosen

            return None

    def release_reservation(self, slot: CredentialSlot) -> None:
        """Release the reserved capacity slot upon completion or failure."""
        slot.release()
        logger.debug(
            f"[CredentialScheduler] Released slot={slot.slot_id} "
            f"provider={slot.provider} inflight={slot.current_inflight}"
        )

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return safe, non-sensitive diagnostic telemetry for all registered slots."""
        with self._lock:
            now = time.time()
            diag: Dict[str, Any] = {}
            for provider, slots in self._slots.items():
                slot_info = []
                for s in slots:
                    # Clean expired
                    valid_times = [t for t in s.request_timestamps if now - t <= 60.0]
                    eligible = quarantine_manager.is_eligible(
                        provider=provider,
                        api_key=s.api_key,
                    )
                    slot_info.append({
                        "slot_id": s.slot_id,
                        "account_id": s.account_id,
                        "key_mask": s.masked_key,
                        "anon_hash": s.anon_id,
                        "rpm_limit": s.rpm_limit,
                        "rpm_current": len(valid_times),
                        "concurrency_limit": s.concurrency_limit,
                        "inflight": s.current_inflight,
                        "eligible": eligible,
                    })
                diag[provider] = {
                    "total_slots": len(slots),
                    "active_slots": sum(1 for s in slot_info if s["eligible"]),
                    "slots": slot_info,
                }
            return diag

    def clear(self) -> None:
        """Clear all registered slots (used in tests)."""
        with self._lock:
            self._slots.clear()
            self._round_robin_index.clear()


# Module-level singleton
credential_scheduler = CredentialScheduler()
