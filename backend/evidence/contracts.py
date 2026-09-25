"""
Evidence contracts — EvidenceType, EvidenceReference, EvidenceCollection.

These are the stable, typed evidence models produced by the capability layer
and returned to the frontend via the /api/ask response.

Design rules:
  - EvidenceReference stores a RowLocator, not raw row indices.
  - EvidenceCollection wraps multiple EvidenceReferences for comparative queries.
  - Both implement to_dict() for JSON serialization.
  - LLMs only ever receive evidence.description (language). Never the full model.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceType(str, Enum):
    ROWS        = "rows"
    COLUMNS     = "columns"
    FILTERED    = "filtered"
    DUPLICATES  = "duplicates"
    MISSING     = "missing"
    OUTLIERS    = "outliers"
    SAMPLE      = "sample"
    TOP_N       = "top_n"
    BOTTOM_N    = "bottom_n"
    CORRELATION = "correlation"
    GROUP       = "group"
    AGGREGATE   = "aggregate"


@dataclass
class EvidenceReference:
    """
    A stable, typed reference to one or more records in a dataset.

    Identity is encoded as a RowLocator (not a display index).
    Locator is resolved to current display positions at render time.

    Lifecycle fields:
      dataset_fingerprint — used to detect staleness after re-upload.
      is_stale — set True by the frontend EvidenceRegistry when fingerprint changes.
      superseded_by — id of newer EvidenceReference if this one was updated.
    """
    type: EvidenceType = EvidenceType.ROWS
    dataset_id: str = ""
    description: str = ""              # Human-readable: "Row 42 — highest Price ($999)"
    source_query: str = ""             # The user's original question
    column_names: List[str] = field(default_factory=list)

    # Stable identity
    locator: Optional[Any] = None      # RowLocator — set by LocatorBuilder

    # Inline preview data for EvidenceCard (top 1–3 rows, key columns)
    preview_rows: List[Dict[str, Any]] = field(default_factory=list)

    # Versioning / staleness
    dataset_fingerprint: str = ""
    analysis_version: str = "1.0"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    superseded_by: Optional[str] = None
    is_stale: bool = False

    # General metadata (capability-specific facts for EvidenceCard display)
    metadata: Dict[str, Any] = field(default_factory=dict)

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, EvidenceType) else self.type,
            "dataset_id": self.dataset_id,
            "description": self.description,
            "source_query": self.source_query,
            "column_names": self.column_names,
            "locator": self.locator.to_dict() if self.locator else None,
            "preview_rows": self.preview_rows,
            "dataset_fingerprint": self.dataset_fingerprint,
            "analysis_version": self.analysis_version,
            "created_at": self.created_at,
            "is_stale": self.is_stale,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
        }


@dataclass
class EvidenceCollection:
    """
    A named collection of EvidenceReference objects for comparative or
    multi-faceted queries.

    Stored as a single unit in the frontend EvidenceRegistry.
    The workspace renders all references simultaneously with a color legend.

    Examples:
      - Compare highest/lowest: two EvidenceReferences (top_n, bottom_n)
      - Duplicates + missing:   two EvidenceReferences
    """
    references: List[EvidenceReference] = field(default_factory=list)
    collection_type: str = "comparison"  # "comparison" | "multi_facet" | "sequence"
    summary: str = ""                    # "Highest vs. lowest Revenue rows"
    dataset_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "collection",
            "collection_type": self.collection_type,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "dataset_id": self.dataset_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
