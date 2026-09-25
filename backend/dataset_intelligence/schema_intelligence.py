"""
Dataset Intelligence Engine — Stage 1: Schema Intelligence

Classifies every column in the dataset into a rich semantic schema,
going far beyond raw pandas dtypes.

This stage answers:
  - What is this column's data type category?
  - What semantic type does this column represent?
  - Is it nullable? Is it constant? Is it unique?
  - What is its likely analytical role?

This stage uses ONLY deterministic Python — no LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from .models import (
    ColumnRole, ColumnSchema, ColumnSemanticType
)
from .utils import (
    matches_date_pattern, matches_dimension_pattern, matches_email_pattern,
    matches_financial_pattern, matches_geo_pattern, matches_id_pattern,
    matches_name_pattern, matches_percentage_pattern, matches_phone_pattern,
    matches_score_pattern, sample_value_type
)

logger = logging.getLogger(__name__)


class SchemaIntelligenceStage:
    """
    Stage 1 — Schema Intelligence

    Builds a rich ColumnSchema for every column.
    Uses heuristics applied to:
      - Column name patterns
      - Raw pandas dtypes
      - Cardinality / uniqueness ratios
      - Sampled value patterns (for text columns)
    """

    # Cardinality thresholds for classifying dimensions vs. identifiers
    HIGH_CARDINALITY_THRESHOLD = 0.85   # unique_pct above this → likely identifier
    LOW_CARDINALITY_THRESHOLD = 0.05    # unique_pct below this → likely dimension

    # A column with only 1 unique value is constant
    CONSTANT_THRESHOLD = 1

    def analyze(self, df: pd.DataFrame) -> List[ColumnSchema]:
        """
        Analyze the full DataFrame schema.
        Always uses the full DataFrame (not a sample) since dtypes and
        unique counts are schema-level properties.

        Returns:
            A list of ColumnSchema objects, one per column.
        """
        logger.info(f"SchemaIntelligenceStage: analyzing {len(df.columns)} columns")
        schemas = []
        total_rows = len(df)

        for position, col_name in enumerate(df.columns):
            try:
                schema = self._analyze_column(df, col_name, position, total_rows)
                schemas.append(schema)
            except Exception as e:
                logger.warning(f"Failed to analyze column '{col_name}': {e}")
                # Fallback: create a minimal schema entry
                schemas.append(ColumnSchema(
                    name=str(col_name),
                    position=position,
                    dtype_raw=str(df[col_name].dtype),
                    dtype_category="unknown",
                    role=ColumnRole.UNKNOWN,
                    semantic_type=ColumnSemanticType.UNKNOWN,
                ))

        # Post-process: mark primary metric and primary date
        self._mark_primaries(schemas)
        return schemas

    def _analyze_column(self, df: pd.DataFrame, col_name: str, position: int, total_rows: int) -> ColumnSchema:
        """Build a ColumnSchema for a single column."""
        series = df[col_name]
        dtype_raw = str(series.dtype)
        dtype_category = self._classify_dtype(series)

        # Null analysis
        null_count = int(series.isna().sum())
        null_pct = round((null_count / total_rows) * 100, 2) if total_rows > 0 else 0.0
        is_nullable = null_pct > 0

        # Cardinality analysis
        unique_count = int(series.nunique(dropna=True))
        non_null_count = total_rows - null_count
        unique_pct = round((unique_count / non_null_count) * 100, 2) if non_null_count > 0 else 0.0
        is_constant = unique_count <= self.CONSTANT_THRESHOLD
        is_unique = unique_pct >= 99.0 and non_null_count > 10  # 99% threshold for "identifier"

        # Sample values (up to 5 non-null)
        sample_values = [str(v) for v in series.dropna().head(5).tolist()]

        # Determine semantic type and role
        semantic_type = self._classify_semantic_type(col_name, series, dtype_category, unique_count, unique_pct, non_null_count)
        role = self._classify_role(col_name, series, dtype_category, semantic_type, unique_pct, is_unique, is_constant)

        # Concept label for known column name patterns
        concept = self._derive_concept(col_name, role)

        return ColumnSchema(
            name=str(col_name),
            position=position,
            dtype_raw=dtype_raw,
            dtype_category=dtype_category,
            role=role,
            semantic_type=semantic_type,
            null_count=null_count,
            null_pct=null_pct,
            is_nullable=is_nullable,
            unique_count=unique_count,
            unique_pct=unique_pct,
            is_constant=is_constant,
            is_unique=is_unique,
            sample_values=sample_values,
            concept=concept,
        )

    def _classify_dtype(self, series: pd.Series) -> str:
        """Classify a pandas dtype into a broad category."""
        dtype_str = str(series.dtype)
        if pd.api.types.is_bool_dtype(series):
            return "boolean"
        elif pd.api.types.is_integer_dtype(series):
            return "integer"
        elif pd.api.types.is_float_dtype(series):
            return "float"
        elif pd.api.types.is_datetime64_any_dtype(series):
            return "datetime"
        elif pd.api.types.is_categorical_dtype(series):
            return "categorical"
        elif dtype_str == "object":
            return "text"
        else:
            return "unknown"

    def _classify_semantic_type(self, col: str, series: pd.Series, dtype_category: str, unique_count: int, unique_pct: float, non_null_count: int) -> ColumnSemanticType:
        """Determine the semantic type of a column from name + data patterns."""

        if dtype_category == "datetime":
            col_lower = col.lower()
            if "year" in col_lower:
                return ColumnSemanticType.YEAR
            elif "month" in col_lower:
                return ColumnSemanticType.MONTH
            elif "quarter" in col_lower:
                return ColumnSemanticType.QUARTER
            elif "timestamp" in col_lower or "time" in col_lower:
                return ColumnSemanticType.DATETIME
            return ColumnSemanticType.DATE

        if dtype_category == "boolean":
            return ColumnSemanticType.BOOLEAN_TEXT

        if dtype_category in ("integer", "float"):
            # Year stored as integer
            col_lower = col.lower()
            if "year" in col_lower and unique_count < 100:
                return ColumnSemanticType.YEAR
            # Integer IDs
            if matches_id_pattern(col) and unique_pct > 80:
                return ColumnSemanticType.ID_INTEGER
            # Percentage columns
            if matches_percentage_pattern(col):
                return ColumnSemanticType.PERCENTAGE
            # Score/rating columns
            if matches_score_pattern(col):
                return ColumnSemanticType.SCORE
            # Financial columns
            if matches_financial_pattern(col):
                return ColumnSemanticType.CURRENCY
            # Binary flag (only 0 and 1)
            try:
                values = series.dropna().unique()
                if set(values).issubset({0, 1, 0.0, 1.0}):
                    return ColumnSemanticType.BOOLEAN_TEXT
            except Exception:
                pass
            return ColumnSemanticType.NUMERIC_GENERAL

        if dtype_category in ("text", "categorical"):
            if matches_email_pattern(col):
                return ColumnSemanticType.EMAIL
            if matches_phone_pattern(col):
                return ColumnSemanticType.PHONE
            if matches_geo_pattern(col):
                return ColumnSemanticType.GEOGRAPHIC_NAME
            if matches_name_pattern(col) and unique_pct > 30:
                return ColumnSemanticType.NAME
            if matches_score_pattern(col):
                return ColumnSemanticType.GRADE
            if matches_dimension_pattern(col):
                return ColumnSemanticType.CATEGORY

            # Inspect actual values for deeper classification
            detected_value_type = sample_value_type(series)
            if detected_value_type == "email":
                return ColumnSemanticType.EMAIL
            elif detected_value_type == "url":
                return ColumnSemanticType.URL
            elif detected_value_type == "uuid":
                return ColumnSemanticType.UUID
            elif detected_value_type == "phone":
                return ColumnSemanticType.PHONE

            # Free text: high unique count with long average string length
            try:
                avg_len = series.dropna().astype(str).str.len().mean()
                if avg_len > 40 and unique_pct > 50:
                    return ColumnSemanticType.FREE_TEXT
                elif avg_len > 20 and unique_pct > 30:
                    return ColumnSemanticType.DESCRIPTION
            except Exception:
                pass

            return ColumnSemanticType.CATEGORY

        return ColumnSemanticType.UNKNOWN

    def _classify_role(self, col: str, series: pd.Series, dtype_category: str, semantic_type: ColumnSemanticType, unique_pct: float, is_unique: bool, is_constant: bool) -> ColumnRole:
        """Assign the high-level analytical role to a column."""

        if is_constant:
            return ColumnRole.ATTRIBUTE  # Constant columns are not analytically useful

        # Boolean flags
        if dtype_category == "boolean" or semantic_type == ColumnSemanticType.BOOLEAN_TEXT:
            return ColumnRole.BOOLEAN_FLAG

        # Datetime → Time role
        if dtype_category == "datetime" or semantic_type in (
            ColumnSemanticType.DATE, ColumnSemanticType.DATETIME,
            ColumnSemanticType.YEAR, ColumnSemanticType.MONTH, ColumnSemanticType.QUARTER
        ):
            return ColumnRole.TIME

        # Identifiers: unique text or numeric IDs
        if semantic_type in (ColumnSemanticType.UUID, ColumnSemanticType.ID_INTEGER, ColumnSemanticType.EMAIL, ColumnSemanticType.PHONE, ColumnSemanticType.URL):
            return ColumnRole.IDENTIFIER
        if matches_id_pattern(col) and unique_pct > 70:
            return ColumnRole.IDENTIFIER
        if is_unique and dtype_category in ("integer", "text"):
            return ColumnRole.IDENTIFIER

        # Geographic
        if semantic_type == ColumnSemanticType.GEOGRAPHIC_NAME or matches_geo_pattern(col):
            return ColumnRole.GEOGRAPHIC

        # Numeric roles
        if dtype_category in ("integer", "float"):
            if semantic_type == ColumnSemanticType.CURRENCY or matches_financial_pattern(col):
                return ColumnRole.FINANCIAL
            if semantic_type in (ColumnSemanticType.SCORE, ColumnSemanticType.PERCENTAGE):
                return ColumnRole.METRIC
            if semantic_type == ColumnSemanticType.NUMERIC_GENERAL:
                return ColumnRole.METRIC

        # Text/categorical roles
        if dtype_category in ("text", "categorical"):
            if semantic_type in (ColumnSemanticType.FREE_TEXT, ColumnSemanticType.DESCRIPTION, ColumnSemanticType.NAME):
                return ColumnRole.ATTRIBUTE
            # High cardinality text with identifier-like name -> identifier
            if is_unique:
                return ColumnRole.IDENTIFIER
            # Low-to-moderate cardinality text -> dimension
            if unique_pct < 50:
                return ColumnRole.DIMENSION
            return ColumnRole.ATTRIBUTE

        # Final catch-all (unknown dtype, boolean without flag match, etc.)
        return ColumnRole.ATTRIBUTE

    def _derive_concept(self, col: str, role: ColumnRole) -> Optional[str]:
        """Derive a universal concept label for known column name patterns."""
        col_lower = col.lower()
        concept_map = {
            'revenue': 'revenue_metric', 'sales': 'revenue_metric', 'income': 'revenue_metric',
            'profit': 'profit_metric', 'margin': 'margin_metric',
            'cost': 'cost_metric', 'expense': 'cost_metric',
            'discount': 'discount_metric', 'price': 'price_metric', 'amount': 'amount_metric',
            'score': 'score_metric', 'gpa': 'gpa_metric', 'grade': 'grade_metric',
            'salary': 'salary_metric', 'bonus': 'bonus_metric',
            'country': 'country_dimension', 'state': 'state_dimension',
            'region': 'region_dimension', 'city': 'city_dimension',
            'department': 'department_dimension', 'category': 'category_dimension',
            'product': 'product_dimension', 'gender': 'gender_dimension',
            'date': 'date_time', 'year': 'year_time', 'month': 'month_time',
        }
        for key, concept in concept_map.items():
            if key in col_lower:
                return concept
        return None

    def _mark_primaries(self, schemas: List[ColumnSchema]) -> None:
        """Mark the most likely primary metric and primary date column."""
        # Primary date: prefer columns named 'date', then first Time column
        time_cols = [s for s in schemas if s.role == ColumnRole.TIME]
        if time_cols:
            priority_date = next((s for s in time_cols if 'date' in s.name.lower()), time_cols[0])
            priority_date.is_primary_date = True

        # Primary metric: prefer financial > score > generic metric
        financial = [s for s in schemas if s.role == ColumnRole.FINANCIAL]
        metrics = [s for s in schemas if s.role == ColumnRole.METRIC]
        priority_keywords = ['revenue', 'sales', 'profit', 'total', 'amount', 'score']

        candidates = financial + metrics
        if candidates:
            primary = None
            for kw in priority_keywords:
                match = next((s for s in candidates if kw in s.name.lower()), None)
                if match:
                    primary = match
                    break
            if not primary:
                primary = candidates[0]
            primary.is_primary_metric = True


schema_intelligence_stage = SchemaIntelligenceStage()
