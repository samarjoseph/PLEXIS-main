"""Safe typed JSON encoding for persisted transformation snapshots.

CSV is a user-facing interchange format, but it cannot round-trip mixed
columns reliably (for example, numeric 0 alongside string "0"). Version
snapshots use tagged JSON scalars instead; no pickle or code execution is used.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

FORMAT_MARKER = "plexis.typed-dataframe.v1"


def _encode_scalar(value: Any) -> dict:
    if value is None or value is pd.NA or value is pd.NaT:
        return {"type": "null"}
    if isinstance(value, (bool, np.bool_)):
        return {"type": "boolean", "value": bool(value)}
    if isinstance(value, (int, np.integer)):
        return {"type": "integer", "value": int(value)}
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return {"type": "null"}
        if math.isinf(number):
            return {"type": "float_special", "value": "inf" if number > 0 else "-inf"}
        return {"type": "float", "value": number}
    if isinstance(value, pd.Timestamp):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, np.generic):
        return _encode_scalar(value.item())
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return {"type": "null"}
    except (TypeError, ValueError):
        pass
    raise TypeError(f"Unsupported dataset snapshot scalar: {type(value).__name__}")


def _decode_scalar(value: dict):
    kind = value.get("type")
    raw = value.get("value")
    if kind == "null":
        return None
    if kind == "boolean":
        return bool(raw)
    if kind == "integer":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "float_special":
        return float("inf") if raw == "inf" else float("-inf")
    if kind == "string":
        return str(raw)
    if kind == "decimal":
        return Decimal(raw)
    if kind == "datetime":
        return pd.Timestamp(raw)
    if kind == "date":
        return date.fromisoformat(raw)
    raise ValueError(f"Unsupported typed dataset scalar: {kind!r}")


def serialize_dataframe(df: pd.DataFrame) -> bytes:
    payload = {
        "format": FORMAT_MARKER,
        "columns": [str(column) for column in df.columns],
        "dtypes": [str(dtype) for dtype in df.dtypes],
        "rows": [[_encode_scalar(value) for value in row] for row in df.itertuples(index=False, name=None)],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def deserialize_dataframe(raw_bytes: bytes) -> pd.DataFrame:
    payload = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_MARKER:
        raise ValueError("Not a Plexis typed dataframe snapshot")
    columns = payload.get("columns")
    dtypes = payload.get("dtypes")
    rows = payload.get("rows")
    if not isinstance(columns, list) or not isinstance(dtypes, list) or not isinstance(rows, list):
        raise ValueError("Malformed Plexis typed dataframe snapshot")
    decoded = [[_decode_scalar(cell) for cell in row] for row in rows]
    df = pd.DataFrame(decoded, columns=columns)
    if len(dtypes) != len(columns):
        raise ValueError("Snapshot dtype metadata does not match its columns")
    for column, dtype in zip(columns, dtypes):
        # Restore physical dtypes when the original dtype can be represented
        # losslessly. Object columns keep their tagged Python scalar types.
        if dtype == "object":
            continue
        try:
            df[column] = df[column].astype(dtype)
        except (TypeError, ValueError, OverflowError):
            pass
    return df

