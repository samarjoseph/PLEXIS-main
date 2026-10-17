"""
Global Provider Quarantine and Circuit Breakers for Plexis.

Provides centralized, thread-safe, cross-subsystem provider health tracking,
circuit breaking, and quota-aware quarantine with configurable cooldowns,
Retry-After header parsing, half-open probing, and safe degradation.
"""
from __future__ import annotations

import enum
import hashlib
import json
import logging
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Failure Categories ─────────────────────────────────────────────────────────

class FailureCategory(str, enum.Enum):
    RATE_LIMIT = "rate_limit"           # 429, Too Many Requests
    QUOTA_EXHAUSTED = "quota_exhausted" # 402, 429 quota exhaustion, out of credits
    SERVER_ERROR = "server_error"       # 500, 502, 503, 504
    TIMEOUT = "timeout"                 # Connection or read timeout
    CONNECTION_ERROR = "connection"     # Network connection error / DNS
    AUTH_FAILURE = "auth_failure"       # 401, 403 invalid key / forbidden
    CONFIG_ERROR = "config_error"       # 404, 422 model not found / bad config
    CLIENT_ERROR = "client_error"       # 400 bad request (prompt issue)
    UNKNOWN = "unknown"

    @property
    def is_quarantinable(self) -> bool:
        """Whether this failure category should trigger quarantine/cooldown."""
        return self in (
            FailureCategory.RATE_LIMIT,
            FailureCategory.QUOTA_EXHAUSTED,
            FailureCategory.SERVER_ERROR,
            FailureCategory.TIMEOUT,
            FailureCategory.CONNECTION_ERROR,
            FailureCategory.AUTH_FAILURE,
            FailureCategory.CONFIG_ERROR,
        )

    @property
    def is_account_scoped(self) -> bool:
        """Whether failure affects all models under the same account/API key."""
        return self in (
            FailureCategory.RATE_LIMIT,
            FailureCategory.QUOTA_EXHAUSTED,
            FailureCategory.AUTH_FAILURE,
            FailureCategory.SERVER_ERROR,
            FailureCategory.CONNECTION_ERROR,
        )


# ── Circuit States ─────────────────────────────────────────────────────────────

class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"        # Healthy, accepting all traffic
    OPEN = "OPEN"            # Quarantined, rejecting all normal traffic
    HALF_OPEN = "HALF_OPEN"  # Cooldown expired, allowing 1 bounded probe


# ── Scope Key ──────────────────────────────────────────────────────────────────

def hash_secret(secret: Optional[str]) -> str:
    """Generate a safe 8-char hash of a secret for scope keying and logging."""
    if not secret:
        return "default"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class ScopeKey:
    """
    Hierarchical quarantine scope key.
    
    Scopes:
      - Provider scope: (provider, account_hash, None) -> affects all models on this account
      - Model scope:    (provider, account_hash, model_id) -> affects only this model
    """
    provider: str
    account: str = "default"
    model: Optional[str] = None

    @classmethod
    def from_provider_and_key(cls, provider: str, api_key: Optional[str] = None, model: Optional[str] = None) -> ScopeKey:
        return cls(
            provider=provider.lower().strip(),
            account=hash_secret(api_key),
            model=model.lower().strip() if model else None
        )

    @property
    def account_scope(self) -> ScopeKey:
        """Return the account-level scope (no model)."""
        return ScopeKey(provider=self.provider, account=self.account, model=None)

    @property
    def is_account_level(self) -> bool:
        return self.model is None

    def as_str(self) -> str:
        if self.model:
            return f"{self.provider}:{self.account}:{self.model}"
        return f"{self.provider}:{self.account}"


# ── Cooldown Policy ────────────────────────────────────────────────────────────

@dataclass
class CooldownPolicy:
    """Defines cooldown behavior for failure categories."""
    base_seconds: float
    max_seconds: float
    factor: float = 2.0
    jitter: bool = True
    failure_threshold: int = 1  # Consecutive failures before opening circuit

    def calculate_cooldown(self, consecutive_failures: int, retry_after: Optional[float] = None) -> float:
        """Calculate cooldown in seconds."""
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self.max_seconds)
        
        # Exponential backoff based on consecutive failures
        exponent = max(0, consecutive_failures - 1)
        raw_cd = self.base_seconds * (self.factor ** exponent)
        capped_cd = min(raw_cd, self.max_seconds)

        if self.jitter:
            # Add up to 10% jitter
            jitter_amount = random.uniform(0, 0.1 * capped_cd)
            capped_cd += jitter_amount

        return capped_cd


DEFAULT_POLICIES: Dict[FailureCategory, CooldownPolicy] = {
    FailureCategory.RATE_LIMIT: CooldownPolicy(
        base_seconds=30.0,
        max_seconds=300.0,
        factor=2.0,
        failure_threshold=1,
    ),
    FailureCategory.QUOTA_EXHAUSTED: CooldownPolicy(
        base_seconds=3600.0,
        max_seconds=86400.0,
        factor=1.0,  # Wait for full reset window
        jitter=False,
        failure_threshold=1,
    ),
    FailureCategory.SERVER_ERROR: CooldownPolicy(
        base_seconds=15.0,
        max_seconds=120.0,
        factor=2.0,
        failure_threshold=2,  # Tolerates 1 blip before trip
    ),
    FailureCategory.TIMEOUT: CooldownPolicy(
        base_seconds=10.0,
        max_seconds=60.0,
        factor=1.5,
        failure_threshold=2,
    ),
    FailureCategory.CONNECTION_ERROR: CooldownPolicy(
        base_seconds=10.0,
        max_seconds=60.0,
        factor=1.5,
        failure_threshold=2,
    ),
    FailureCategory.AUTH_FAILURE: CooldownPolicy(
        base_seconds=86400.0,
        max_seconds=86400.0 * 7,
        factor=1.0,
        jitter=False,
        failure_threshold=1,
    ),
    FailureCategory.CONFIG_ERROR: CooldownPolicy(
        base_seconds=86400.0 * 30,  # Effectively permanent until config reload
        max_seconds=86400.0 * 30,
        factor=1.0,
        jitter=False,
        failure_threshold=1,
    ),
    FailureCategory.UNKNOWN: CooldownPolicy(
        base_seconds=15.0,
        max_seconds=60.0,
        factor=2.0,
        failure_threshold=3,
    ),
}


# ── Scope Health Record ────────────────────────────────────────────────────────

@dataclass
class HealthRecord:
    scope: ScopeKey
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    failure_category: Optional[FailureCategory] = None
    opened_at: float = 0.0
    cooldown_until: float = 0.0
    retry_after: Optional[float] = None
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    last_error_message: Optional[str] = None
    # Concurrency-safe half-open probe tracking
    probe_in_flight: bool = False
    probe_started_at: float = 0.0


# ── Storage Backend ────────────────────────────────────────────────────────────

class HealthStateStore:
    """Abstract interface for storing and retrieving provider health state."""
    def get(self, key_str: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def set(self, key_str: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        raise NotImplementedError


class InMemoryStateStore(HealthStateStore):
    """Thread-safe in-memory health state store."""
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key_str: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            val = self._data.get(key_str)
            return dict(val) if val else None

    def set(self, key_str: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._data[key_str] = dict(data)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}


# ── Error Classifier ───────────────────────────────────────────────────────────

def parse_retry_after(header_val: Optional[Any], now_ts: Optional[float] = None) -> Optional[float]:
    """
    Parse a Retry-After header or reset time value.
    Can be integer seconds or HTTP-date format.
    """
    if header_val is None:
        return None

    s = str(header_val).strip()
    if not s:
        return None

    # 1. Direct integer/float seconds
    try:
        val = float(s)
        if val >= 0:
            return val
    except ValueError:
        pass

    # 2. Check for human duration in error strings (e.g. "Retry in 7h17m45s" or "in 30s")
    match_duration = re.search(r'(?:retry|try again|wait)\s+(?:in\s+)?(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?', s, re.IGNORECASE)
    if match_duration and any(match_duration.groups()):
        hours = float(match_duration.group(1) or 0)
        minutes = float(match_duration.group(2) or 0)
        seconds = float(match_duration.group(3) or 0)
        total = (hours * 3600) + (minutes * 60) + seconds
        if total > 0:
            return total

    # 3. HTTP Date (RFC 7231 / RFC 1123)
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(s)
        now = now_ts or time.time()
        diff = dt.timestamp() - now
        return max(0.0, diff)
    except Exception:
        pass

    return None


def classify_error(
    error_str: str,
    status_code: Optional[int] = None,
    headers: Optional[Dict[str, Any]] = None,
    raw_response: Optional[Any] = None,
) -> Tuple[FailureCategory, Optional[float]]:
    """
    Classify a provider error and extract any Retry-After duration.
    
    Returns:
        (FailureCategory, retry_after_seconds)
    """
    err = str(error_str or "").lower()
    headers = headers or {}
    
    # Extract retry-after from headers if present
    retry_header = (
        headers.get("retry-after")
        or headers.get("Retry-After")
        or headers.get("x-ratelimit-reset-requests")
        or headers.get("x-ratelimit-reset")
    )
    retry_after = parse_retry_after(retry_header)

    # If retry-after wasn't in headers, look inside the error text
    if retry_after is None:
        retry_after = parse_retry_after(err)

    # 1. Quota Exhaustion (Distinguished from short rate limits)
    is_quota = (
        "quota exceeded" in err
        or "resource_exhausted" in err
        or ("resource" in err and "exhaust" in err)
        or "insufficient_quota" in err
        or "check quota" in err
        or ("quota" in err and "exceeded" in err)
        or "out of credits" in err
        or "credit balance" in err
        or status_code == 402
    )
    if is_quota:
        return FailureCategory.QUOTA_EXHAUSTED, retry_after

    # 2. Rate Limits (429)
    if status_code == 429 or "429" in err or "too many requests" in err or "rate limit" in err or "ratelimit" in err:
        return FailureCategory.RATE_LIMIT, retry_after

    # 3. Authentication & Authorization (401, 403)
    if status_code in (401, 403) or "401" in err or "403" in err or "unauthorized" in err or "forbidden" in err or "invalid api key" in err:
        return FailureCategory.AUTH_FAILURE, None

    # 4. Configuration & Model Not Found (404, 422)
    if (
        status_code in (404, 422)
        or "404" in err
        or "422" in err
        or "model not found" in err
        or "model_not_found" in err
        or "does not exist" in err
        or "not available on" in err
    ):
        return FailureCategory.CONFIG_ERROR, None

    # 5. Timeouts
    if "timeout" in err or "timed out" in err or status_code in (408, 504):
        return FailureCategory.TIMEOUT, None

    # 6. Connection / Network errors
    if (
        "connection refused" in err
        or "connection reset" in err
        or "connection error" in err
        or "failed to establish a new connection" in err
        or "remotely closed" in err
    ):
        return FailureCategory.CONNECTION_ERROR, None

    # 7. Server Errors (5xx)
    if (status_code and 500 <= status_code <= 599) or "500" in err or "502" in err or "503" in err or "bad gateway" in err:
        return FailureCategory.SERVER_ERROR, None

    # 8. Client errors (400)
    if status_code == 400 or "bad request" in err:
        return FailureCategory.CLIENT_ERROR, None

    return FailureCategory.UNKNOWN, None


# ── Global Quarantine Manager ──────────────────────────────────────────────────

class QuarantineManager:
    """
    Centralized health manager providing:
    - Quota-aware scoped circuit breakers (Account-level & Model-level).
    - Provider quarantine with category-specific cooldowns.
    - Thread-safe half-open probe synchronization.
    - Secret-safe observability & metrics.
    - Safe degradation if state store fails.
    """

    def __init__(
        self,
        store: Optional[HealthStateStore] = None,
        clock: Callable[[], float] = time.time,
        policies: Optional[Dict[FailureCategory, CooldownPolicy]] = None,
    ):
        self._store = store or InMemoryStateStore()
        self._clock = clock
        self._policies = policies or DEFAULT_POLICIES
        self._lock = threading.RLock()
        
        # Local cache for safe degradation if store fails
        self._local_cache: Dict[str, HealthRecord] = {}

        # Secret-safe metrics
        self._metrics = {
            "transitions_to_open": 0,
            "transitions_to_closed": 0,
            "transitions_to_half_open": 0,
            "probes_attempted": 0,
            "probes_succeeded": 0,
            "probes_failed": 0,
            "probes_rejected_concurrent": 0,
            "calls_blocked_by_circuit": 0,
            "all_providers_unavailable": 0,
            "rate_limits_recorded": 0,
            "quotas_exhausted_recorded": 0,
        }

    def _now(self) -> float:
        return self._clock()

    # ── State persistence helpers with safe degradation ────────────────────────

    def _get_record(self, scope: ScopeKey) -> HealthRecord:
        """Fetch record with fallback to local cache on store failure."""
        key_str = scope.as_str()
        try:
            raw = self._store.get(key_str)
            if raw:
                rec = HealthRecord(
                    scope=scope,
                    state=CircuitState(raw.get("state", CircuitState.CLOSED.value)),
                    consecutive_failures=raw.get("consecutive_failures", 0),
                    failure_category=FailureCategory(raw["failure_category"]) if raw.get("failure_category") else None,
                    opened_at=raw.get("opened_at", 0.0),
                    cooldown_until=raw.get("cooldown_until", 0.0),
                    retry_after=raw.get("retry_after"),
                    last_failure_at=raw.get("last_failure_at", 0.0),
                    last_success_at=raw.get("last_success_at", 0.0),
                    last_error_message=raw.get("last_error_message"),
                    probe_in_flight=raw.get("probe_in_flight", False),
                    probe_started_at=raw.get("probe_started_at", 0.0),
                )
                self._local_cache[key_str] = rec
                return rec
        except Exception as e:
            logger.warning(f"[Quarantine] State store read failed ({e}) — degrading to local cache.")

        # Fallback to local cache or new record
        if key_str in self._local_cache:
            return self._local_cache[key_str]

        new_rec = HealthRecord(scope=scope)
        self._local_cache[key_str] = new_rec
        return new_rec

    def _save_record(self, record: HealthRecord) -> None:
        """Save record with fallback to local cache on store failure."""
        key_str = record.scope.as_str()
        self._local_cache[key_str] = record
        try:
            payload = {
                "state": record.state.value,
                "consecutive_failures": record.consecutive_failures,
                "failure_category": record.failure_category.value if record.failure_category else None,
                "opened_at": record.opened_at,
                "cooldown_until": record.cooldown_until,
                "retry_after": record.retry_after,
                "last_failure_at": record.last_failure_at,
                "last_success_at": record.last_success_at,
                "last_error_message": record.last_error_message,
                "probe_in_flight": record.probe_in_flight,
                "probe_started_at": record.probe_started_at,
            }
            self._store.set(key_str, payload)
        except Exception as e:
            logger.warning(f"[Quarantine] State store write failed ({e}) — safely persisting locally.")

    # ── Core Eligibility Check ─────────────────────────────────────────────────

    def is_eligible(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        """
        Check if a provider/model is eligible for new requests.
        Respects hierarchical scopes:
          1. Provider/Account scope (shared quota, e.g. all Nvidia models)
          2. Model scope (specific model issues)
        """
        account_scope = ScopeKey.from_provider_and_key(provider, api_key, model=None)
        model_scope = ScopeKey.from_provider_and_key(provider, api_key, model=model_id) if model_id else None

        with self._lock:
            # 1. Check account-level scope
            if not self._check_scope_eligibility(account_scope):
                self._metrics["calls_blocked_by_circuit"] += 1
                return False

            # 2. Check model-level scope if provided
            if model_scope and not self._check_scope_eligibility(model_scope):
                self._metrics["calls_blocked_by_circuit"] += 1
                return False

            return True

    def _check_scope_eligibility(self, scope: ScopeKey) -> bool:
        """Inspect and transition scope state based on current time."""
        rec = self._get_record(scope)
        now = self._now()

        if rec.state == CircuitState.CLOSED:
            return True

        if rec.state == CircuitState.OPEN:
            # Check if cooldown has expired
            if now >= rec.cooldown_until:
                rec.state = CircuitState.HALF_OPEN
                rec.probe_in_flight = False
                self._metrics["transitions_to_half_open"] += 1
                logger.info(
                    f"[Quarantine] Circuit entering HALF_OPEN for scope={scope.as_str()} "
                    f"(cooldown elapsed, awaiting probe)."
                )
                self._save_record(rec)
                # In HALF_OPEN, only eligible if probe can be acquired via acquire_probe()
                return True
            return False

        if rec.state == CircuitState.HALF_OPEN:
            # If probe is already in flight, other requests cannot use this provider
            if rec.probe_in_flight:
                # Expire probe lock if probe hung for > 60 seconds
                if now - rec.probe_started_at > 60.0:
                    logger.warning(
                        f"[Quarantine] Stale probe detected for scope={scope.as_str()} "
                        f"— releasing probe lock."
                    )
                    rec.probe_in_flight = False
                    self._save_record(rec)
                    return True
                return False
            return True

        return True

    # ── Concurrency-Safe Half-Open Probe Lock ───────────────────────────────────

    def acquire_probe_slot(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        """
        Atomically acquire the single probe request slot for a HALF_OPEN circuit.
        Returns True if this request is authorized to be the recovery probe.
        """
        account_scope = ScopeKey.from_provider_and_key(provider, api_key, model=None)
        model_scope = ScopeKey.from_provider_and_key(provider, api_key, model=model_id) if model_id else None

        with self._lock:
            now = self._now()

            def _check_and_acquire(scope: ScopeKey) -> Optional[bool]:
                rec = self._get_record(scope)
                if rec.state == CircuitState.CLOSED:
                    return None  # No probe required

                if rec.state == CircuitState.OPEN:
                    if now >= rec.cooldown_until:
                        rec.state = CircuitState.HALF_OPEN
                        rec.probe_in_flight = False
                        self._metrics["transitions_to_half_open"] += 1
                        self._save_record(rec)
                    else:
                        return False  # Still in OPEN cooldown

                if rec.state == CircuitState.HALF_OPEN:
                    if rec.probe_in_flight:
                        # Stale probe check (60s timeout)
                        if now - rec.probe_started_at > 60.0:
                            rec.probe_in_flight = True
                            rec.probe_started_at = now
                            self._save_record(rec)
                            return True
                        self._metrics["probes_rejected_concurrent"] += 1
                        return False
                    rec.probe_in_flight = True
                    rec.probe_started_at = now
                    self._metrics["probes_attempted"] += 1
                    self._save_record(rec)
                    return True

                return None

            acct_res = _check_and_acquire(account_scope)
            if acct_res is False:
                return False

            if model_scope:
                mod_res = _check_and_acquire(model_scope)
                if mod_res is False:
                    return False

            return True

    # ── Recording Outcomes ─────────────────────────────────────────────────────

    def record_success(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> None:
        """Record a successful call to a provider/model, resetting circuits."""
        account_scope = ScopeKey.from_provider_and_key(provider, api_key, model=None)
        model_scope = ScopeKey.from_provider_and_key(provider, api_key, model=model_id) if model_id else None

        with self._lock:
            now = self._now()
            for scope in [account_scope, model_scope]:
                if not scope:
                    continue
                rec = self._get_record(scope)
                was_quarantined = rec.state in (CircuitState.OPEN, CircuitState.HALF_OPEN)
                
                if rec.state == CircuitState.HALF_OPEN:
                    self._metrics["probes_succeeded"] += 1

                rec.state = CircuitState.CLOSED
                rec.consecutive_failures = 0
                rec.failure_category = None
                rec.cooldown_until = 0.0
                rec.retry_after = None
                rec.probe_in_flight = False
                rec.last_success_at = now
                self._save_record(rec)

                if was_quarantined:
                    self._metrics["transitions_to_closed"] += 1
                    logger.info(f"[Quarantine] Provider RECOVERED. Circuit CLOSED for scope={scope.as_str()}.")

    def record_failure(
        self,
        provider: str,
        error: Any,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        status_code: Optional[int] = None,
        headers: Optional[Dict[str, Any]] = None,
        raw_response: Optional[Any] = None,
    ) -> Tuple[CircuitState, float]:
        """
        Record a provider failure, classify it, update quarantine status,
        and calculate cooldown.
        
        Returns:
            (circuit_state, cooldown_until_timestamp)
        """
        category, retry_after = classify_error(
            error_str=str(error),
            status_code=status_code,
            headers=headers,
            raw_response=raw_response,
        )

        with self._lock:
            now = self._now()

            # Record metrics
            if category == FailureCategory.RATE_LIMIT:
                self._metrics["rate_limits_recorded"] += 1
            elif category == FailureCategory.QUOTA_EXHAUSTED:
                self._metrics["quotas_exhausted_recorded"] += 1

            # Determine appropriate scope:
            # If account-scoped failure (quota, 429, auth, server outage), quarantine entire account.
            # If model-scoped (e.g. 404 model not found), quarantine only that model.
            target_scope = ScopeKey.from_provider_and_key(
                provider=provider,
                api_key=api_key,
                model=None if category.is_account_scoped else model_id
            )

            rec = self._get_record(target_scope)
            policy = self._policies.get(category, self._policies[FailureCategory.UNKNOWN])

            rec.consecutive_failures += 1
            rec.failure_category = category
            rec.last_failure_at = now
            rec.last_error_message = str(error)[:200]

            # If failed during HALF_OPEN probe, immediately reopen with penalty
            if rec.state == CircuitState.HALF_OPEN or rec.probe_in_flight:
                self._metrics["probes_failed"] += 1
                rec.probe_in_flight = False
                cooldown_dur = policy.calculate_cooldown(rec.consecutive_failures, retry_after)
                rec.cooldown_until = now + cooldown_dur
                rec.state = CircuitState.OPEN
                rec.opened_at = now
                self._metrics["transitions_to_open"] += 1
                self._save_record(rec)
                logger.warning(
                    f"[Quarantine] Probe FAILED for scope={target_scope.as_str()}. "
                    f"Reopening circuit. Cooldown={cooldown_dur:.1f}s until={rec.cooldown_until:.0f}."
                )
                return rec.state, rec.cooldown_until

            # If closed, check if threshold is reached
            if rec.consecutive_failures >= policy.failure_threshold:
                cooldown_dur = policy.calculate_cooldown(rec.consecutive_failures, retry_after)
                rec.cooldown_until = now + cooldown_dur
                rec.state = CircuitState.OPEN
                rec.opened_at = now
                rec.retry_after = retry_after
                rec.probe_in_flight = False
                self._metrics["transitions_to_open"] += 1
                self._save_record(rec)
                logger.warning(
                    f"[Quarantine] Provider QUARANTINED! Circuit OPEN for scope={target_scope.as_str()}. "
                    f"Category={category.value} ConsecutiveFailures={rec.consecutive_failures} "
                    f"Cooldown={cooldown_dur:.1f}s (Until {rec.cooldown_until:.0f}). "
                    f"Reason='{rec.last_error_message}'"
                )
                return rec.state, rec.cooldown_until

            self._save_record(rec)
            return rec.state, rec.cooldown_until

    # ── Observability & Metrics ─────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """Return secret-safe performance and circuit metrics."""
        with self._lock:
            return dict(self._metrics)

    def get_status(self) -> Dict[str, Any]:
        """Return current status of all tracked provider scopes without secret leakage."""
        with self._lock:
            all_records = self._store.get_all()
            now = self._now()
            scopes = {}
            for k, v in all_records.items():
                cd_left = max(0.0, v.get("cooldown_until", 0.0) - now)
                scopes[k] = {
                    "state": v.get("state"),
                    "category": v.get("failure_category"),
                    "consecutive_failures": v.get("consecutive_failures"),
                    "cooldown_remaining_seconds": round(cd_left, 1),
                    "last_error": v.get("last_error_message"),
                }
            return {
                "active_scopes": scopes,
                "metrics": dict(self._metrics),
            }

    def reset_all(self) -> None:
        """Clear all quarantine records (primarily for testing)."""
        with self._lock:
            self._local_cache.clear()
            self._store = InMemoryStateStore()
            for k in self._metrics:
                self._metrics[k] = 0


# Module-level singleton shared across the entire backend
quarantine_manager = QuarantineManager()
