"""
autonomous_analysis/investigation_cache.py

Cache for autonomous investigation results.

L1: In-memory dict (per-process, cleared on restart)
L2: JSON files in backend/data/investigation_cache/ (persistent)

Cache key: SHA-256(dataset_fingerprint + analysis_type + sorted(columns))
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "investigation_cache"


class InvestigationCache:
    """Two-level cache for investigation reports."""

    def __init__(self):
        self._l1: Dict[str, dict] = {}
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_report(self, dataset_fingerprint: str) -> Optional[dict]:
        """Get cached report by dataset fingerprint."""
        key = self._report_key(dataset_fingerprint)

        # L1
        if key in self._l1:
            logger.debug("[InvestigationCache] L1 hit for %s", key[:12])
            return self._l1[key]

        # L2
        path = _CACHE_DIR / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._l1[key] = data
                logger.debug("[InvestigationCache] L2 hit for %s", key[:12])
                return data
            except Exception as e:
                logger.warning("[InvestigationCache] L2 read error: %s", e)

        return None

    def save_report(self, dataset_fingerprint: str, report_dict: dict) -> None:
        """Save report to both L1 and L2."""
        key = self._report_key(dataset_fingerprint)

        # L1
        self._l1[key] = report_dict

        # L2
        try:
            path = _CACHE_DIR / f"{key}.json"
            path.write_text(
                json.dumps(report_dict, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug("[InvestigationCache] saved report %s", key[:12])
        except Exception as e:
            logger.warning("[InvestigationCache] L2 write error: %s", e)

    def get_result(self, fingerprint: str, analysis_type: str, columns: list) -> Optional[dict]:
        """Get cached individual analysis result."""
        key = self._result_key(fingerprint, analysis_type, columns)
        if key in self._l1:
            return self._l1[key]
        path = _CACHE_DIR / f"result_{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._l1[key] = data
                return data
            except Exception:
                pass
        return None

    def save_result(self, fingerprint: str, analysis_type: str, columns: list, result_dict: dict) -> None:
        """Save individual analysis result."""
        key = self._result_key(fingerprint, analysis_type, columns)
        self._l1[key] = result_dict
        try:
            path = _CACHE_DIR / f"result_{key}.json"
            path.write_text(json.dumps(result_dict, default=str), encoding="utf-8")
        except Exception:
            pass

    def invalidate(self, dataset_fingerprint: str) -> None:
        """Remove cached report for a fingerprint."""
        key = self._report_key(dataset_fingerprint)
        self._l1.pop(key, None)
        path = _CACHE_DIR / f"{key}.json"
        if path.exists():
            path.unlink(missing_ok=True)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _report_key(fingerprint: str) -> str:
        return hashlib.sha256(f"report::{fingerprint}".encode()).hexdigest()[:32]

    @staticmethod
    def _result_key(fingerprint: str, analysis_type: str, columns: list) -> str:
        raw = f"{fingerprint}::{analysis_type}::{'::'.join(sorted(columns))}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# Singleton
investigation_cache = InvestigationCache()
