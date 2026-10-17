"""Transformation system contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class AffectedCell:
    row_index: int          # 0-based dataframe index
    source_row_number: int  # 1-based display row number
    column: str
    before: Any
    after: Any


@dataclass
class TransformationPlan:
    plan_id: str                    # UUID string
    dataset_id: str                 # UUID string
    operation_type: str             # FILL_MISSING | DROP_DUPLICATES | RENAME_COLUMN | DROP_COLUMN | FILTER_ROWS | CAST_DTYPE | REPLACE_VALUES | SORT_ROWS
    operation_label: str            # Human-readable: "Fill missing values with 0"
    operation_code: str             # Code string: "df.fillna(0)"
    operation_payload: Dict[str, Any]  # Raw LLM params
    affected_rows_count: int
    affected_cells_count: int
    affected_columns: List[str]
    before_sample: List[AffectedCell]  # Up to 20 cells
    dataset_fingerprint: str        # SHA-256 of dataset bytes at plan creation time
    warnings: List[str] = field(default_factory=list)
    created_at: Optional[str] = None  # ISO timestamp
    intelligence_provenance: Optional[Dict[str, Any]] = None  # Provenance for intelligence suggestions


@dataclass
class TransformationResult:
    success: bool
    plan_id: str
    version_id: Optional[str]
    version_number: Optional[int]
    changed_cells: int
    operation_label: str
    error: Optional[str] = None
    intelligence_provenance: Optional[Dict[str, Any]] = None


@dataclass
class VersionInfo:
    version_id: str
    version_number: int
    operation_label: str
    changed_cells: int
    created_at: str
    plan_id: Optional[str]
    parent_version_id: Optional[str]
