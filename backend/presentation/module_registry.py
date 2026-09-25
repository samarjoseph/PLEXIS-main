"""
Presentation Layer — Module Registry

In-memory, TTL-scoped, LRU-bounded store for KnowledgeBundles.

Key design decisions (audit fixes):
  C-1/C-2: Registry is keyed by dataset_id (not session_id or "active")
           → multi-tab safe, no collision between sessions
  C-2:     TTL=24h, max=200 bundles, LRU eviction using OrderedDict
  C-2:     On TTL eviction: BundleExpiredError is raised; caller re-decomposes
           from the persisted DKO on disk (DKO is permanent; registry is transient)
  Auth:    Keys are scoped as (user_scope, dataset_id) for future multi-user safety

Eviction strategy:
  - Background eviction every 15 minutes removes expired entries
  - If MAX_BUNDLES exceeded on store(), evict the LRU entry immediately
  - BundleExpiredError is the recovery signal for callers
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from .domain.contracts import KnowledgeBundle, KnowledgeModule, ExecutiveSummary, ModuleID
from .domain.errors import BundleExpiredError, ModuleNotAvailableError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
import os

MAX_BUNDLES: int = int(os.getenv("PRESENTATION_MAX_BUNDLES", "200"))
BUNDLE_TTL_SECONDS: int = int(os.getenv("PRESENTATION_BUNDLE_TTL", str(24 * 60 * 60)))  # 24h
RICHNESS_THRESHOLD: float = 20.0


class ModuleRegistry:
    """
    Session-scoped, TTL-bounded, LRU-evicting module store.

    All keys are dataset_id-based (not session_id, not "active").
    An executive module (13th, derived by ranker) is stored alongside
    the 12 source modules from the decomposer.
    """

    def __init__(
        self,
        max_bundles: int = MAX_BUNDLES,
        ttl_seconds: int = BUNDLE_TTL_SECONDS,
    ) -> None:
        self._max_bundles = max_bundles
        self._ttl_seconds = ttl_seconds

        # OrderedDict used as LRU cache: (dataset_id) -> (bundle, executive_module, stored_at)
        self._store: OrderedDict[str, Tuple[KnowledgeBundle, KnowledgeModule, float]] = OrderedDict()
        self._lock = threading.Lock()

        logger.info(
            f"ModuleRegistry initialized: max_bundles={max_bundles}, "
            f"ttl={ttl_seconds}s ({ttl_seconds // 3600}h)"
        )

    # -------------------------------------------------------------------------
    # Write path
    # -------------------------------------------------------------------------

    def store(self, summary: ExecutiveSummary) -> None:
        """
        Store a KnowledgeBundle + executive module in the registry.

        Args:
            summary: The ExecutiveSummary produced by SemanticImportanceRanker.
                     Contains the bundle (12 source modules) and executive_module (13th).

        Evicts LRU entry if MAX_BUNDLES exceeded.
        """
        dataset_id = summary.dataset_id
        with self._lock:
            # Remove and re-insert to move to MRU position
            if dataset_id in self._store:
                self._store.move_to_end(dataset_id)

            self._store[dataset_id] = (
                summary.bundle,
                summary.executive_module,
                time.time(),
            )
            self._store.move_to_end(dataset_id)

            # Evict LRU if over capacity
            while len(self._store) > self._max_bundles:
                evicted_id, _ = self._store.popitem(last=False)
                logger.info(f"ModuleRegistry: evicted LRU bundle for dataset_id='{evicted_id}'")

        logger.info(
            f"ModuleRegistry: stored bundle for dataset_id='{dataset_id}' "
            f"({len(summary.bundle.all_modules())} source + 1 executive modules, "
            f"store_size={len(self._store)})"
        )

    # -------------------------------------------------------------------------
    # Read path
    # -------------------------------------------------------------------------

    def get_module(self, dataset_id: str, module_id: str) -> KnowledgeModule:
        """
        Retrieve a specific module by dataset_id and module_id.

        Raises:
            BundleExpiredError: If TTL has elapsed or entry was evicted.
            ModuleNotAvailableError: If module richness < threshold or not present.
        """
        bundle, executive, stored_at = self._get_entry(dataset_id)

        if module_id == ModuleID.EXECUTIVE:
            return executive

        module = bundle.get_module(module_id)
        if module is None:
            raise ModuleNotAvailableError(module_id, reason="Unknown module_id.")

        if not module.is_available or module.richness_score < RICHNESS_THRESHOLD:
            raise ModuleNotAvailableError(
                module_id,
                reason=f"Richness score {module.richness_score:.0f} < threshold {RICHNESS_THRESHOLD}.",
            )

        # Move to MRU on access (LRU tracking)
        with self._lock:
            if dataset_id in self._store:
                self._store.move_to_end(dataset_id)

        return module

    def get_bundle(self, dataset_id: str) -> KnowledgeBundle:
        """Retrieve the full 12-module KnowledgeBundle."""
        bundle, _, _ = self._get_entry(dataset_id)
        return bundle

    def get_executive_module(self, dataset_id: str) -> KnowledgeModule:
        """Retrieve the derived executive module."""
        _, executive, _ = self._get_entry(dataset_id)
        return executive

    def list_available_modules(self, dataset_id: str) -> list:
        """
        Return a list of available module metadata for the frontend.
        Modules with richness < threshold are excluded.
        Executive module is always included first.
        """
        bundle, executive, _ = self._get_entry(dataset_id)
        result = [
            {
                "module_id": executive.module_id,
                "display_name": executive.display_name,
                "icon": executive.icon,
                "richness_score": round(executive.richness_score, 1),
                "fact_count": executive.fact_count,
                "preview": executive.preview,
                "is_available": True,
            }
        ]
        for module in bundle.all_modules():
            if module.richness_score >= RICHNESS_THRESHOLD and module.is_available:
                result.append({
                    "module_id": module.module_id,
                    "display_name": module.display_name,
                    "icon": module.icon,
                    "richness_score": round(module.richness_score, 1),
                    "fact_count": module.fact_count,
                    "preview": module.preview,
                    "is_available": True,
                })
        # Sort by richness descending (executive is pinned at position 0)
        pinned = result[:1]
        sortable = sorted(result[1:], key=lambda m: m["richness_score"], reverse=True)
        return pinned + sortable

    def has_bundle(self, dataset_id: str) -> bool:
        """Check if a dataset_id has a valid, non-expired bundle."""
        try:
            self._get_entry(dataset_id)
            return True
        except (BundleExpiredError, KeyError):
            return False

    # -------------------------------------------------------------------------
    # Eviction
    # -------------------------------------------------------------------------

    def evict_expired(self) -> int:
        """
        Remove all entries older than TTL.
        Called by the background eviction scheduler every 15 minutes.

        Returns: number of entries evicted.
        """
        now = time.time()
        evicted = 0
        with self._lock:
            expired_keys = [
                k for k, (_, _, stored_at) in self._store.items()
                if now - stored_at > self._ttl_seconds
            ]
            for k in expired_keys:
                del self._store[k]
                evicted += 1

        if evicted:
            logger.info(f"ModuleRegistry: evicted {evicted} expired bundle(s), "
                        f"store_size={len(self._store)}")
        return evicted

    def size(self) -> int:
        """Return current number of bundles in the registry."""
        return len(self._store)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_entry(self, dataset_id: str) -> Tuple[KnowledgeBundle, KnowledgeModule, float]:
        """Fetch an entry, checking TTL. Raises BundleExpiredError if stale."""
        with self._lock:
            entry = self._store.get(dataset_id)

        if entry is None:
            raise BundleExpiredError(dataset_id)

        bundle, executive, stored_at = entry
        if time.time() - stored_at > self._ttl_seconds:
            with self._lock:
                self._store.pop(dataset_id, None)
            raise BundleExpiredError(dataset_id)

        return bundle, executive, stored_at


# ---------------------------------------------------------------------------
# Background eviction thread
# ---------------------------------------------------------------------------

class _EvictionThread(threading.Thread):
    """Daemon thread that evicts expired bundles every 15 minutes."""

    INTERVAL_SECONDS = 15 * 60  # 15 minutes

    def __init__(self, registry: ModuleRegistry) -> None:
        super().__init__(daemon=True, name="ModuleRegistry-Eviction")
        self._registry = registry

    def run(self) -> None:
        while True:
            time.sleep(self.INTERVAL_SECONDS)
            try:
                count = self._registry.evict_expired()
                if count:
                    logger.debug(f"EvictionThread: evicted {count} expired bundles")
            except Exception as e:
                logger.warning(f"EvictionThread: error during eviction: {e}")


# ---------------------------------------------------------------------------
# Module-level singleton + eviction thread
# ---------------------------------------------------------------------------
module_registry = ModuleRegistry()
_eviction_thread = _EvictionThread(module_registry)
_eviction_thread.start()
logger.info("ModuleRegistry eviction thread started.")
