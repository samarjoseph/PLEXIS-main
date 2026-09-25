"""
Stable Row Locators — encode a record's identity independent of display order.

Resolution priority (most to least stable):
  1. PRIMARY_KEY   — explicit PK column + value(s)
  2. COMPOSITE_KEY — multi-column natural key
  3. ROW_HASH      — SHA-256 of all cell values (always available)
  4. FILTER_EXPR   — deterministic filter expression (e.g. "Price == max(Price)")
  5. POSITION      — raw index fallback (unstable — marked explicitly)

The workspace resolves a RowLocator to current display positions at render time,
not at evidence creation time. This means evidence survives sort/filter changes.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LocatorStrategy(str, Enum):
    PRIMARY_KEY   = "primary_key"
    ROW_HASH      = "row_hash"
    COMPOSITE_KEY = "composite_key"
    FILTER_EXPR   = "filter_expr"
    POSITION      = "position"


@dataclass
class RowLocator:
    """
    Stable logical identity for one or more dataset records.

    Stability guarantee per operation:
      Sort            → primary_key ✓  row_hash ✓  filter_expr ✓  position ✗
      Filter (subset) → primary_key ✓  row_hash ✓  filter_expr ✓  position ✗
      Dataset re-upload → primary_key ✓ (same PK)  row_hash ✓ (same row)  others vary
      Pagination      → primary_key ✓  row_hash ✓  filter_expr ✓  position ✗

    is_stable is surfaced in the UI. Unstable evidence shows a subtle warning:
      "This reference may be affected by reordering."
    """
    strategy: LocatorStrategy = LocatorStrategy.ROW_HASH

    # PRIMARY_KEY / COMPOSITE_KEY: column→value mapping
    primary_key: Optional[Dict[str, Any]] = None    # e.g. {"product_id": 4821}
    composite_key: Optional[Dict[str, Any]] = None  # e.g. {"name": "X", "date": "2024-01"}

    # ROW_HASH: SHA-256 hex digests of all row values
    row_hashes: List[str] = field(default_factory=list)

    # FILTER_EXPR: re-apply this filter to current data
    filter_expr: Optional[str] = None  # e.g. "Price == 999 AND Category == 'Appliances'"

    # POSITION: raw index fallback (unstable)
    fallback_indices: List[int] = field(default_factory=list)

    # Stability flag — False only when strategy == POSITION with no other locator
    is_stable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "primary_key": self.primary_key,
            "composite_key": self.composite_key,
            "row_hashes": self.row_hashes,
            "filter_expr": self.filter_expr,
            "fallback_indices": self.fallback_indices,
            "is_stable": self.is_stable,
        }
