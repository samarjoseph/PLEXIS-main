"""
Context Enrichment — General, dataset-agnostic extraction and composition
of grounding context from verified analytical results and source-row provenance.

Design principles:
  1. Grounded & Deterministic: values belong strictly to the records that produced the result.
  2. Dataset Agnostic: works across airlines, telco, sales, healthcare, or any schema.
  3. No Fabrication: never invent flight numbers, names, or units.
  4. Honest Representation: accurately surface ties, unknown units, and missing context.
  5. Exact Provenance: distinguish true source-row number, dataframe index, and result rank.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# Internal/system columns that must never be presented as domain context
_SYSTEM_COLUMNS = frozenset({
    "_row_number", "dataframe_index", "source_row_number", "result_rank",
    "index", "level_0", "unnamed: 0", "_index", "_id",
})

# High-priority semantic hints for categorical, entity, and descriptor columns
_ENTITY_HINTS = (
    "name", "airline", "carrier", "customer", "product", "category",
    "type", "status", "city", "state", "country", "region",
    "origin", "destination", "dest", "model", "make", "brand",
    "department", "employee", "title", "company", "segment",
    "contract", "service", "class", "genre", "species", "location",
)

# Secondary identifier and code hints
_IDENTIFIER_HINTS = (
    "id", "code", "number", "num", "key", "sku", "flight",
)

# Temporal hints
_TEMPORAL_HINTS = (
    "date", "time", "year", "month", "day", "quarter", "timestamp",
)


def _is_empty_or_nan(val: Any) -> bool:
    """Check if a value is null, NaN, or whitespace-only string."""
    if val is None:
        return True
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return True
    val_str = str(val).strip().lower()
    return val_str in ("", "nan", "none", "null", "<na>", "nat")


def _score_column(col_name: str, val: Any) -> int:
    """Heuristic relevance score for candidate contextual columns."""
    c_lower = col_name.lower().replace(" ", "_")
    score = 0

    # 1. Entity / Descriptor hints (+100)
    if any(hint in c_lower for hint in _ENTITY_HINTS):
        score += 100

    # 2. Specific domain identifiers (+95) vs general identifiers (+85)
    if any(hint in c_lower for hint in ("flight_number", "flight_no", "order_id", "customer_id", "product_id", "transaction_id", "patient_id")):
        score += 95
    elif any(hint in c_lower for hint in _IDENTIFIER_HINTS):
        score += 85

    # 3. Temporal hints (+75)
    if any(hint in c_lower for hint in _TEMPORAL_HINTS):
        score += 75

    # String values that are not pure numbers get higher weight
    if isinstance(val, str) and not val.strip().isdigit():
        score += 20
    elif isinstance(val, (int, float)):
        score += 5

    return score


def extract_relevant_context(
    row: Optional[Dict[str, Any]],
    target_col: Optional[str] = None,
    max_fields: int = 8,
) -> Dict[str, Any]:
    """
    Extract grounded, semantically relevant contextual key-value pairs from a matching record.

    Excludes:
      - System columns (_row_number, dataframe_index, source_row_number, result_rank, etc.)
      - The target metric column itself (which is already displayed as the main value)
      - Null, NaN, or empty values

    Composes:
      - Hour + Minute columns into a unified time string (e.g. Scheduled Departure Time: 21:01).

    Ranks remaining columns by semantic relevance and returns up to max_fields items.
    """
    if not row or not isinstance(row, dict):
        return {}

    target_norm = (target_col or "").strip().lower()
    suppressed_keys = set()
    composed_candidates = []

    # Detect composite hour + minute patterns (e.g. Scheduled_Departure_Hour & Scheduled_Departure_Minute)
    hour_key = None
    min_key = None
    for k in row.keys():
        kl = str(k).lower().replace(" ", "_")
        if "delay" in kl:
            continue
        if "hour" in kl and any(prefix in kl for prefix in ("sched", "dep", "arr")):
            hour_key = k
        elif "minute" in kl and any(prefix in kl for prefix in ("sched", "dep", "arr")):
            min_key = k

    if hour_key and min_key and not _is_empty_or_nan(row.get(hour_key)) and not _is_empty_or_nan(row.get(min_key)):
        try:
            h_val = int(float(row[hour_key]))
            m_val = int(float(row[min_key]))
            h_lower = str(hour_key).lower()
            if "sched" in h_lower and "dep" in h_lower:
                time_label = "Scheduled Departure Time"
            elif "dep" in h_lower:
                time_label = "Departure Time"
            elif "arr" in h_lower:
                time_label = "Arrival Time"
            else:
                time_label = "Scheduled Time"

            time_str = f"{h_val:02d}:{m_val:02d}"
            # Composite time gets high priority (+105)
            composed_candidates.append((105, -1, time_label, time_str))
            suppressed_keys.add(hour_key)
            suppressed_keys.add(min_key)
        except (ValueError, TypeError):
            pass

    candidates = list(composed_candidates)

    for idx, (k, v) in enumerate(row.items()):
        k_str = str(k).strip()
        k_norm = k_str.lower()

        # Filter suppressed composite keys
        if k in suppressed_keys:
            continue

        # Filter internal / system keys
        if k_norm in _SYSTEM_COLUMNS or k_str.startswith("_"):
            continue

        # Filter the target metric column
        if target_norm and k_norm == target_norm:
            continue

        # Filter missing/empty values
        if _is_empty_or_nan(v):
            continue

        score = _score_column(k_str, v)
        # We sort by (-score, idx) to prioritize higher score, preserving original order as tie-breaker
        candidates.append((score, idx, k_str, v))

    if not candidates:
        return {}

    # Sort candidates by score descending, then by original column order
    candidates.sort(key=lambda c: (-c[0], c[1]))

    selected = {}
    for _, _, k_str, v in candidates[:max_fields]:
        # Clean float representations if whole numbers
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        selected[k_str] = v

    return selected


def format_col_name(col: str) -> str:
    """Format column key into a clean title-cased label."""
    if not col:
        return ""
    if " " in col and "_" not in col:
        return col
    return col.replace("_", " ").strip().title()


def format_context_summary(context_fields: Dict[str, Any]) -> str:
    """Format context fields into a clean inline narrative string."""
    if not context_fields:
        return ""
    return ", ".join(f"{format_col_name(k)}: {v}" for k, v in context_fields.items())


def enrich_extremum_narrative(
    op: str,
    col: str,
    val: Any,
    matching_rows: List[Dict[str, Any]],
    dataset_name: str = "the dataset",
    details: Optional[Dict[str, Any]] = None,
    unit: Optional[str] = None,
) -> str:
    """
    Compose an operation-aware, context-enriched narrative for extreme-value questions
    (maximum, minimum, longest, shortest, highest, lowest).
    """
    details = details or {}
    label = "highest" if op in ("max", "idxmax", "longest", "highest") else "lowest"

    # Only include unit if grounded in trusted metadata
    val_str = f"{val} {unit}" if unit else str(val)

    # Unit status note if unknown
    unit_status = details.get("unit_status")
    unit_label = details.get("unit_label")
    unit_clause = ""
    if unit_status == "unknown" or (not unit and unit_label):
        unit_clause = f" [{unit_label or 'Unit not specified in dataset metadata'}]"

    # Determine tie status
    total_matching = details.get("matching_count")
    if total_matching is None:
        total_matching = len(matching_rows) if matching_rows else 1

    if not matching_rows:
        return f"In **{dataset_name}**, the {label} **{col}** is **{val_str}**{unit_clause}."

    if total_matching > 1:
        # Multiple records tie for extremum
        samples = []
        for r in matching_rows[:2]:
            ctx = extract_relevant_context(r, target_col=col, max_fields=3)
            r_num = r.get("source_row_number") or r.get("_row_number")
            ctx_summary = format_context_summary(ctx)
            if r_num and ctx_summary:
                samples.append(f"Row {r_num}: {ctx_summary}")
            elif ctx_summary:
                samples.append(ctx_summary)
            elif r_num:
                samples.append(f"Row {r_num}")

        if samples:
            samples_str = "; ".join(samples)
            return (
                f"In **{dataset_name}**, the {label} **{col}** is **{val_str}**{unit_clause}, "
                f"tied across **{total_matching} records** (including {samples_str})."
            )
        return (
            f"In **{dataset_name}**, the {label} **{col}** is **{val_str}**{unit_clause}, "
            f"tied across **{total_matching} records**."
        )

    # Single matching record
    top_row = matching_rows[0]
    ctx = extract_relevant_context(top_row, target_col=col, max_fields=8)
    src_row = top_row.get("source_row_number") or top_row.get("_row_number")

    prov_items = []
    if ctx:
        prov_items.append(format_context_summary(ctx))
    if src_row is not None:
        prov_items.append(f"Source row: {src_row}")

    if prov_items:
        ctx_str = " · ".join(prov_items)
        return f"In **{dataset_name}**, the {label} **{col}** is **{val_str}**{unit_clause} ({ctx_str})."

    return f"In **{dataset_name}**, the {label} **{col}** is **{val_str}**{unit_clause}."
