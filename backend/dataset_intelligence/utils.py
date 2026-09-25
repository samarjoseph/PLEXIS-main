"""
Dataset Intelligence Engine — Shared Utilities

Pure utility functions used across multiple DIE stages.
Zero dependencies on other DIE modules (except models.py).

These helpers ensure consistent, safe computation across all stages:
  - Safe numeric operations that never raise exceptions on bad data
  - Statistical helpers (entropy, skewness labeling, IQR outlier detection)
  - Column name pattern matchers used by schema and semantic stages
  - Dataset sampling strategy for large datasets
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Sampling Strategy
# ---------------------------------------------------------------------------

LARGE_DATASET_THRESHOLD = 100_000
SAMPLE_SIZE = 50_000


def get_working_sample(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a working sample of the DataFrame for expensive operations.
    For datasets <= LARGE_DATASET_THRESHOLD rows, returns the full DataFrame.
    For larger datasets, returns a stratified random sample of SAMPLE_SIZE rows.

    The schema stage always uses the full DataFrame (it only inspects dtypes).
    Statistical and quality stages use the sampled version.
    """
    if len(df) <= LARGE_DATASET_THRESHOLD:
        return df
    return df.sample(n=SAMPLE_SIZE, random_state=42).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Safe Numeric Operations
# ---------------------------------------------------------------------------

def safe_float(value: Any) -> Optional[float]:
    """Convert a value to float safely, returning None on failure."""
    try:
        v = float(value)
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    except (TypeError, ValueError, OverflowError):
        return None


def safe_int(value: Any) -> Optional[int]:
    """Convert a value to int safely, returning None on failure."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def safe_round(value: Optional[float], decimals: int = 4) -> Optional[float]:
    """Round a float safely."""
    if value is None:
        return None
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Statistical Helpers
# ---------------------------------------------------------------------------

def compute_entropy(series: pd.Series) -> float:
    """
    Compute Shannon entropy of a categorical series.
    Higher entropy = more diverse values.
    Returns 0.0 for empty or constant series.
    """
    try:
        counts = series.value_counts(normalize=True, dropna=True)
        if counts.empty:
            return 0.0
        entropy = -float(np.sum(counts.values * np.log2(counts.values + 1e-10)))
        return round(entropy, 4)
    except Exception:
        return 0.0


def label_skewness(skew: Optional[float]) -> str:
    """
    Convert a numeric skewness value to a human-readable label.
    Standard thresholds: |skew| < 0.5 = normal, 0.5-1 = moderate, >1 = strong.
    """
    if skew is None:
        return "unknown"
    if skew > 1.5:
        return "strongly right-skewed"
    elif skew > 0.5:
        return "moderately right-skewed"
    elif skew < -1.5:
        return "strongly left-skewed"
    elif skew < -0.5:
        return "moderately left-skewed"
    else:
        return "approximately normal"


def detect_outliers_iqr(series: pd.Series) -> Tuple[int, float]:
    """
    Detect outliers using the IQR (Tukey) method.
    An outlier is any value below Q1 - 1.5*IQR or above Q3 + 1.5*IQR.

    Returns:
        (outlier_count, outlier_pct)
    """
    try:
        clean = series.dropna()
        if len(clean) < 4:
            return 0, 0.0
        q1 = float(clean.quantile(0.25))
        q3 = float(clean.quantile(0.75))
        iqr = q3 - q1
        if iqr == 0:
            return 0, 0.0
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_mask = (clean < lower) | (clean > upper)
        count = int(outlier_mask.sum())
        pct = round((count / len(clean)) * 100, 2) if len(clean) > 0 else 0.0
        return count, pct
    except Exception:
        return 0, 0.0


def correlation_strength(r: float) -> Tuple[str, str]:
    """
    Convert a Pearson correlation coefficient to (strength, direction) labels.
    Standard Evans (1996) thresholds.
    """
    abs_r = abs(r)
    direction = "positive" if r >= 0 else "negative"
    if abs_r >= 0.8:
        strength = "very_strong"
    elif abs_r >= 0.6:
        strength = "strong"
    elif abs_r >= 0.4:
        strength = "moderate"
    elif abs_r >= 0.2:
        strength = "weak"
    else:
        strength = "negligible"
    return strength, direction


def infer_datetime_granularity(series: pd.Series) -> str:
    """
    Infer the temporal granularity of a datetime column.
    Checks whether the series varies at hour/day/month/year level.
    """
    try:
        clean = series.dropna()
        if len(clean) < 2:
            return "unknown"

        # Check if hours vary
        if hasattr(clean.dt, 'hour') and clean.dt.hour.nunique() > 1:
            return "hourly"

        # Check if days vary within months
        if clean.dt.day.nunique() > 1:
            return "daily"

        # Check if months vary within years
        if clean.dt.month.nunique() > 1:
            return "monthly"

        # Only years vary
        if clean.dt.year.nunique() > 1:
            return "yearly"

        return "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Column Name Pattern Matchers
# ---------------------------------------------------------------------------

# Patterns for identifier-like column names
_ID_PATTERNS = re.compile(
    r'\b(id|uuid|guid|key|code|number|num|no|ref|serial|sequence|token|hash)\b',
    re.IGNORECASE
)

# Patterns for financial metric column names
_FINANCIAL_PATTERNS = re.compile(
    r'\b(revenue|sales|profit|income|cost|expense|price|amount|total|value|'
    r'margin|discount|tax|fee|payment|charge|invoice|budget|spend|earning|'
    r'salary|wage|bonus|commission|turnover|gross|net)\b',
    re.IGNORECASE
)

# Patterns for date/time column names
_DATE_PATTERNS = re.compile(
    r'\b(date|time|timestamp|created|updated|modified|at|on|when|'
    r'year|month|day|quarter|week|hour|minute)\b',
    re.IGNORECASE
)

# Patterns for geographic column names
_GEO_PATTERNS = re.compile(
    r'\b(country|city|state|region|province|territory|district|zip|postal|'
    r'latitude|longitude|lat|lng|address|location|place|area|zone|market)\b',
    re.IGNORECASE
)

# Patterns for person/name columns
_NAME_PATTERNS = re.compile(
    r'\b(name|first|last|full|person|customer|employee|student|user|member|'
    r'owner|manager|agent|contact|client|vendor|supplier)\b',
    re.IGNORECASE
)

# Patterns for email columns
_EMAIL_PATTERNS = re.compile(r'\b(email|e[-_]?mail|mail)\b', re.IGNORECASE)

# Patterns for phone columns
_PHONE_PATTERNS = re.compile(r'\b(phone|mobile|cell|tel|contact|fax)\b', re.IGNORECASE)

# Patterns for categorical/dimension columns
_DIMENSION_PATTERNS = re.compile(
    r'\b(type|category|class|group|segment|status|gender|sex|grade|level|'
    r'tier|rank|division|department|team|branch|channel|source|medium|'
    r'industry|sector|role|position|title|product|brand|model|sku|'
    r'ethnicity|race|age_group|cohort)\b',
    re.IGNORECASE
)

# Patterns for score/rating columns
_SCORE_PATTERNS = re.compile(
    r'\b(score|rating|grade|mark|point|index|rank|performance|'
    r'satisfaction|nps|csat|gpa|result|outcome)\b',
    re.IGNORECASE
)

# Patterns for percentage columns
_PERCENTAGE_PATTERNS = re.compile(
    r'\b(pct|percent|percentage|ratio|rate|proportion|share|fraction)\b',
    re.IGNORECASE
)


def matches_id_pattern(col: str) -> bool:
    return bool(_ID_PATTERNS.search(col))

def matches_financial_pattern(col: str) -> bool:
    return bool(_FINANCIAL_PATTERNS.search(col))

def matches_date_pattern(col: str) -> bool:
    return bool(_DATE_PATTERNS.search(col))

def matches_geo_pattern(col: str) -> bool:
    return bool(_GEO_PATTERNS.search(col))

def matches_name_pattern(col: str) -> bool:
    return bool(_NAME_PATTERNS.search(col))

def matches_email_pattern(col: str) -> bool:
    return bool(_EMAIL_PATTERNS.search(col))

def matches_phone_pattern(col: str) -> bool:
    return bool(_PHONE_PATTERNS.search(col))

def matches_dimension_pattern(col: str) -> bool:
    return bool(_DIMENSION_PATTERNS.search(col))

def matches_score_pattern(col: str) -> bool:
    return bool(_SCORE_PATTERNS.search(col))

def matches_percentage_pattern(col: str) -> bool:
    return bool(_PERCENTAGE_PATTERNS.search(col))


# ---------------------------------------------------------------------------
# Value Pattern Detectors (for actual cell contents)
# ---------------------------------------------------------------------------

_EMAIL_VALUE_PATTERN = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_URL_VALUE_PATTERN   = re.compile(r'^https?://')
_UUID_VALUE_PATTERN  = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
_PHONE_VALUE_PATTERN = re.compile(r'^[\+\d][\d\s\-\(\)\.]{7,}$')


def sample_value_type(series: pd.Series, n: int = 50) -> str:
    """
    Sample up to n non-null values from a series and detect the predominant
    value format. Returns: 'email', 'url', 'uuid', 'phone', or 'text'.
    """
    try:
        sample = series.dropna().astype(str).head(n)
        if sample.empty:
            return 'text'

        counts: Dict[str, int] = {"email": 0, "url": 0, "uuid": 0, "phone": 0}
        for val in sample:
            if _EMAIL_VALUE_PATTERN.match(val):
                counts["email"] += 1
            elif _URL_VALUE_PATTERN.match(val):
                counts["url"] += 1
            elif _UUID_VALUE_PATTERN.match(val):
                counts["uuid"] += 1
            elif _PHONE_VALUE_PATTERN.match(val):
                counts["phone"] += 1

        threshold = len(sample) * 0.7  # 70% must match
        for kind, count in counts.items():
            if count >= threshold:
                return kind
        return 'text'
    except Exception:
        return 'text'


# ---------------------------------------------------------------------------
# Dataset Fingerprinting
# ---------------------------------------------------------------------------

def compute_schema_fingerprint(df: pd.DataFrame) -> str:
    """
    Compute a deterministic fingerprint of the dataset schema.
    Used as the cache key for the DKO.

    The fingerprint is based on:
    - Sorted column names
    - Their corresponding dtypes
    - Row count (different row counts = different data, even with same schema)
    """
    col_info = sorted(zip(df.columns.tolist(), [str(dt) for dt in df.dtypes]))
    fingerprint_str = f"{len(df)}|{'|'.join(f'{c}:{d}' for c, d in col_info)}"
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Scoring Helpers
# ---------------------------------------------------------------------------

def clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Clamp a float value to [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def score_to_label(score: float) -> str:
    """Convert a 0–100 score to a human-readable label."""
    if score >= 90:
        return "excellent"
    elif score >= 75:
        return "good"
    elif score >= 55:
        return "fair"
    else:
        return "poor"
