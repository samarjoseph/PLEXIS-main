"""
PlannerContext — builds the context dict passed to the AnalyticalPlanner.

This bundles together:
  - Real dataset schema (column names + types) — AUTHORITATIVE: from Pandas DataFrame
  - Dataset profile
  - Recent chat history
  - Previous analytical operations (for follow-up questions)
  - Dataset fingerprint

SCHEMA AUTHORITY ORDER:
  1. Live Pandas DataFrame (from DatasetRegistry L1 cache) — most authoritative
  2. schema_profile from DatasetEntry (fallback if DF not available)
  3. DKO columns (last resort)

Column types are ALWAYS in canonical vocabulary:
  integer | float | string | categorical | boolean | datetime | unknown

The AnalyticalPlanner ONLY sees what PlannerContext gives it.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Canonical dtype vocabulary ────────────────────────────────────────────────
# Maps pandas dtype strings → canonical labels used by:
#   PlannerContext, PlanValidator, PandasExecutor, prompt_builder
#
# Covers:
#   - All standard pandas dtypes (int8/int64/float64/object/bool/category/datetime)
#   - Pandas 3.x native string dtype: "str" / "string[python]" / "string"
#   - Pandas nullable integer types: Int8/Int16/Int32/Int64/UInt8...
#   - Pandas nullable float types: Float32/Float64
#   - PyArrow backend types: large_string, string_view, double, etc.
#   - Profiler-generated friendly types: decimal, text, date, boolean, integer
_DTYPE_MAP: Dict[str, str] = {
    # ── Standard pandas integer dtypes ────────────────────────────────────────
    "int8":     "integer",
    "int16":    "integer",
    "int32":    "integer",
    "int64":    "integer",
    "uint8":    "integer",
    "uint16":   "integer",
    "uint32":   "integer",
    "uint64":   "integer",
    # Nullable integer extension types (pandas 1.x+ / 2.x+)
    "int8":     "integer",   # already above
    "Int8":     "integer",
    "Int16":    "integer",
    "Int32":    "integer",
    "Int64":    "integer",
    "UInt8":    "integer",
    "UInt16":   "integer",
    "UInt32":   "integer",
    "UInt64":   "integer",
    # ── Standard pandas float dtypes ──────────────────────────────────────────
    "float16":  "float",
    "float32":  "float",
    "float64":  "float",
    "Float32":  "float",
    "Float64":  "float",
    # ── Boolean ───────────────────────────────────────────────────────────────
    "bool":     "boolean",
    "boolean":  "boolean",   # nullable BooleanDtype
    # ── String dtypes ─────────────────────────────────────────────────────────
    "object":   "string",   # classic pandas string dtype
    "string":   "string",   # pd.StringDtype()
    "str":      "string",   # pandas 3.x native string dtype
    "large_string": "string",  # PyArrow
    "string_view":  "string",  # PyArrow
    "utf8":     "string",   # PyArrow
    "large_utf8": "string", # PyArrow
    # Profiler-generated friendly names
    "text":     "string",
    # ── Numeric friendly aliases (from profiler / legacy code) ────────────────
    "integer":  "integer",  # profiler may store canonical directly
    "float":    "float",    # profiler may store canonical directly
    "decimal":  "float",    # profiler maps float64 → "decimal"
    "number":   "float",
    "numeric":  "float",
    "double":   "float",
    # ── Category ──────────────────────────────────────────────────────────────
    "category":     "categorical",
    "categorical":  "categorical",
    # ── Datetime dtypes ───────────────────────────────────────────────────────
    "datetime64[ns]": "datetime",
    "datetime64[us]": "datetime",
    "datetime64[ms]": "datetime",
    "datetime64[s]":  "datetime",
    "date":           "datetime",    # profiler maps datetime → "date"
    "timestamp[ns][pyarrow]": "datetime",
    "timestamp[us][pyarrow]": "datetime",
    # ── Timedelta / other ─────────────────────────────────────────────────────
    "timedelta64[ns]": "timedelta",
}

# Sets for fast membership tests
_NUMERIC_CANONICAL = frozenset({"integer", "float", "numeric"})
_STRING_CANONICAL  = frozenset({"string", "categorical"})
_DATE_CANONICAL    = frozenset({"datetime"})


def _map_dtype(pandas_dtype: str) -> str:
    """
    Convert a pandas dtype string → canonical vocabulary.

    Falls back to 'unknown' only for truly unrecognised dtypes.
    'unknown' is treated as non-numeric by the validator.
    """
    raw  = str(pandas_dtype)
    base = raw.lower().split("[")[0].strip()

    # Exact match (primary — fastest path)
    if base in _DTYPE_MAP:
        return _DTYPE_MAP[base]

    # Also try with the raw (preserves case-sensitive keys like "Int64")
    raw_lower = raw.lower().split("[")[0].strip()
    if raw_lower in _DTYPE_MAP:
        return _DTYPE_MAP[raw_lower]

    # ── Substring fallback (handles Arrow/extension types) ────────────────────
    # Datetime must come before "int" to prevent "timedelta" matching "int"
    if "datetime" in base or "timestamp" in base:
        return "datetime"
    if "timedelta" in base or "duration" in base:
        return "timedelta"

    # Integer detection (careful: must not match "string" which contains no "int")
    if base.startswith("int") or base.startswith("uint"):
        return "integer"

    # Float / decimal detection
    if "float" in base or "double" in base or "decimal" in base:
        return "float"

    # String detection — covers: str, string, text, utf8, large_string, etc.
    if any(s in base for s in ("str", "utf", "text", "char", "unicode", "large_string", "string_view")):
        return "string"

    # Boolean
    if "bool" in base:
        return "boolean"

    # Category
    if "categ" in base:
        return "categorical"

    return "unknown"



def _classify_column(series: pd.Series) -> Dict[str, Any]:
    """
    Derive authoritative metadata for a single DataFrame column.

    Returns a dict with canonical_type, is_numeric, min/max, etc.
    """
    dtype_str  = str(series.dtype)
    canonical  = _map_dtype(dtype_str)
    is_numeric = canonical in _NUMERIC_CANONICAL
    is_str     = canonical in _STRING_CANONICAL
    is_date    = canonical in _DATE_CANONICAL

    null_count = int(series.isna().sum())
    total      = len(series)

    meta: Dict[str, Any] = {
        "pandas_dtype":   dtype_str,
        "canonical_type": canonical,
        "is_numeric":     is_numeric,
        "is_string":      is_str,
        "is_datetime":    is_date,
        "nullable":       null_count > 0,
        "null_count":     null_count,
    }

    # Cardinality (flag low-cardinality string cols as categorical)
    if total > 0:
        n_unique = series.nunique(dropna=True)
        if n_unique / total < 0.05 and canonical == "string":
            meta["cardinality"] = n_unique
            # Reclassify low-cardinality string as categorical for prompt building
            meta["canonical_type"] = "categorical"

    # Min/max for numeric columns (useful for prompt context)
    if is_numeric:
        try:
            meta["min"] = float(series.dropna().min())
            meta["max"] = float(series.dropna().max())
        except Exception:
            pass

    # Sample values (5 non-null, for prompt context — NO raw PII rows)
    try:
        sample = series.dropna().head(5).tolist()
        meta["sample_values"] = [
            round(v, 4) if isinstance(v, float) else v for v in sample
        ]
    except Exception:
        meta["sample_values"] = []

    return meta


def _schema_from_df(df: pd.DataFrame) -> tuple[list, dict, dict]:
    """
    Build authoritative columns, column_types, and column_meta from a DataFrame.

    Returns:
        (columns: list, column_types: dict, column_meta: dict)
    """
    columns: list = list(df.columns)
    column_types: Dict[str, str] = {}
    column_meta:  Dict[str, dict] = {}

    for col in df.columns:
        meta = _classify_column(df[col])
        column_meta[col]  = meta
        column_types[col] = meta["canonical_type"]

    return columns, column_types, column_meta


class PlannerContext:
    """
    Builds the context dict required by AnalyticalPlanner.plan().

    All schema data is real — never invented, never hallucinated.
    """

    def build(
        self,
        execution_context,  # core.context.ExecutionContext
        db=None,
        chat_history: Optional[list] = None,
        previous_ops: Optional[list] = None,
        df: Optional[pd.DataFrame] = None,   # Pass DataFrame for authoritative types
    ) -> Dict[str, Any]:
        """
        Build the planner context from an ExecutionContext.

        Args:
            execution_context: The resolved ExecutionContext from the pipeline.
            db:                SQLAlchemy session (for loading previous ops from DB).
            chat_history:      Recent messages in this chat.
            previous_ops:      Recent AnalyticalResult summaries for context.
            df:                Live DataFrame — if provided, schema is derived from it.
                               If not provided, will be looked up from DatasetRegistry.

        Returns:
            dict with keys: columns, column_types, column_meta, dataset_name,
                            dataset_fingerprint, profile, chat_history, previous_ops,
                            dataset_id, row_count
        """
        ctx = execution_context

        # ── Step 1: Get the live DataFrame ────────────────────────────────────
        # Try caller-supplied DF first, then DatasetRegistry, then schema_profile fallback
        live_df = df
        if live_df is None:
            live_df = self._get_df_from_registry(ctx)

        # ── Step 2: Build schema from live DataFrame (authoritative) ──────────
        if live_df is not None and not live_df.empty:
            columns, column_types, column_meta = _schema_from_df(live_df)
            row_count = len(live_df)
            logger.debug(
                "[PlannerContext] Schema from DataFrame: %s",
                {c: column_types[c] for c in list(columns)[:8]},
            )
        else:
            # Fallback: schema_profile (less reliable — may have "unknown" types)
            columns, column_types = self._extract_schema_from_profile(ctx)
            column_meta = {}
            row_count = 0
            logger.warning(
                "[PlannerContext] DataFrame not available — using schema_profile fallback. "
                "column_types=%s",
                {c: column_types.get(c, "?") for c in columns[:8]},
            )

        # ── Step 3: Dataset fingerprint ───────────────────────────────────────
        dataset_fingerprint = getattr(ctx, "dataset_fingerprint", None) or ""
        if not dataset_fingerprint and live_df is not None:
            try:
                shape_str = f"{live_df.shape[0]}x{live_df.shape[1]}"
                cols_str  = ",".join(str(c) for c in live_df.columns)
                dataset_fingerprint = hashlib.sha256(
                    f"{shape_str}|{cols_str}".encode()
                ).hexdigest()[:16]
            except Exception:
                pass

        # ── Step 4: Dataset metadata ──────────────────────────────────────────
        dataset_name = getattr(ctx, "dataset_filename", None) or "the dataset"
        dataset_id   = getattr(ctx, "dataset_id", None)
        profile      = self._extract_profile(ctx)

        # ── Step 5: Chat history ──────────────────────────────────────────────
        if chat_history is None:
            chat_history = getattr(ctx, "conversation_history", None) or []
        chat_history = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:200]}
            for m in (chat_history or [])[-6:]
        ]

        # ── Step 6: Previous analytical ops ───────────────────────────────────
        if previous_ops is None and db is not None and dataset_id:
            previous_ops = self._load_previous_ops(db, ctx)
        previous_ops = previous_ops or []

        context_dict = {
            "columns":           columns,
            "column_types":      column_types,    # col → canonical_type
            "column_meta":       column_meta,     # col → full metadata dict
            "dataset_name":      dataset_name,
            "dataset_id":        str(dataset_id) if dataset_id else None,
            "dataset_fingerprint": dataset_fingerprint,
            "row_count":         row_count,
            "profile":           profile,
            "chat_history":      chat_history,
            "previous_ops":      previous_ops,
        }

        logger.debug(
            "[PlannerContext] Built context: dataset=%s columns=%d prev_ops=%d",
            dataset_name, len(columns), len(previous_ops),
        )
        logger.info(
            "[PlannerContext] Column types: %s",
            {c: column_types[c] for c in list(columns)[:10]},
        )

        return context_dict

    # ─────────────────────────── private helpers ──────────────────────────────

    @staticmethod
    def _get_df_from_registry(ctx) -> Optional[pd.DataFrame]:
        """
        Look up the live DataFrame from DatasetRegistry L1 cache.
        Falls back to L2 (PostgreSQL restore) if L1 is cold.
        Returns None if no dataset is loaded.
        """
        dataset_id = getattr(ctx, "dataset_id", None)
        if not dataset_id:
            return None
        try:
            from datasets.registry import dataset_registry
            entry = dataset_registry.get(str(dataset_id))
            if entry is not None:
                df = getattr(entry, "dataframe", None)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            logger.warning("[PlannerContext] DatasetRegistry lookup failed: %s", e)
        return None

    @staticmethod
    def _extract_schema_from_profile(ctx) -> tuple[list, dict]:
        """
        Extract column names and types from schema_profile (fallback only).
        Returns raw strings from schema_profile — may be "unknown".
        """
        columns: list = []
        column_types: dict = {}

        schema_profile = getattr(ctx, "schema_profile", None)
        if schema_profile and isinstance(schema_profile, list):
            for col_info in schema_profile:
                if isinstance(col_info, dict):
                    name  = col_info.get("name") or ""
                    dtype = col_info.get("dtype") or col_info.get("type") or "unknown"
                    if name:
                        columns.append(name)
                        # Attempt canonical normalization
                        column_types[name] = _map_dtype(str(dtype))
            if columns:
                return columns, column_types

        # DKO fallback
        dko = getattr(ctx, "dko", None)
        if dko and hasattr(dko, "columns"):
            try:
                for col_name, col_info in dko.columns.items():
                    columns.append(col_name)
                    dtype = getattr(col_info, "dtype", "unknown")
                    column_types[col_name] = _map_dtype(str(dtype))
            except Exception as e:
                logger.warning("[PlannerContext] DKO column extraction failed: %s", e)

        return columns, column_types

    @staticmethod
    def _extract_profile(ctx) -> dict:
        """Extract a compact dataset profile for the planner."""
        profile: dict = {}
        dko = getattr(ctx, "dko", None)
        if dko:
            try:
                if hasattr(dko, "profile"):
                    profile = dko.profile or {}
                elif hasattr(dko, "to_dict"):
                    full = dko.to_dict()
                    profile = {
                        k: full.get(k)
                        for k in ("row_count", "column_count", "quality_score", "summary")
                        if full.get(k) is not None
                    }
            except Exception as e:
                logger.warning("[PlannerContext] Profile extraction failed: %s", e)
        return profile

    def _load_previous_ops(self, db, ctx) -> list:
        """Load recent AnalysisOperations for this chat as context."""
        try:
            chat_id    = getattr(ctx, "chat_id", None)
            dataset_id = getattr(ctx, "dataset_id", None)
            if not chat_id or not dataset_id:
                return []

            from db.repositories.analysis_session_repository import analysis_session_repository
            from db.repositories.operation_repository import operation_repository

            session = analysis_session_repository.get_latest_for_chat_dataset(
                db, chat_id, dataset_id
            )
            if not session:
                return []

            ops = operation_repository.get_recent_for_session(db, session.id, last_n=5)
            summaries = []
            for op in reversed(ops):   # oldest first
                result = op.result_json or {}
                summaries.append({
                    "operation": op.operation_type,
                    "column":    op.column_name,
                    "value":     result.get("value"),
                    "intent":    result.get("normalized_intent"),
                    "query":     result.get("query"),
                })
            return summaries
        except Exception as e:
            logger.warning("[PlannerContext] Could not load previous ops: %s", e)
            return []


planner_context_builder = PlannerContext()
