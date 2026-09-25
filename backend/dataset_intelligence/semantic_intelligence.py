"""
Dataset Intelligence Engine — Stage 5: Semantic Intelligence

Maps every column to a high-level analytical concept and role.
This is the layer the Planner and Router will use to understand
what the dataset can actually compute.

Unlike Stage 1 (schema), this stage thinks in terms of business concepts:
  - Not "float64" but "Financial Metric"
  - Not "object" but "Geographic Dimension"
  - Not "int64" but "Identifier"

This stage supersedes the Phase 7 semantic/ package for datasets
processed through the Dataset Intelligence Engine.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .models import ColumnRole, ColumnSchema, SemanticColumn, SemanticMap
from .utils import (
    matches_financial_pattern, matches_geo_pattern, matches_score_pattern
)

logger = logging.getLogger(__name__)


class SemanticIntelligenceStage:
    """
    Stage 5 — Semantic Intelligence

    Takes the schema classifications from Stage 1 and elevates them into
    semantically rich ColumnRole assignments, using a combination of:
      - Stage 1 role assignments (strong signal)
      - Column name concept matching
      - Special-case overrides for domain-specific column types
    """

    def analyze(self, schemas: List[ColumnSchema]) -> SemanticMap:
        """
        Build a SemanticMap from the existing schema intelligence.

        Args:
            schemas: Stage 1 ColumnSchema objects

        Returns:
            A SemanticMap with one SemanticColumn per column.
        """
        logger.info(f"SemanticIntelligenceStage: classifying {len(schemas)} columns")
        semantic_columns: Dict[str, SemanticColumn] = {}

        for schema in schemas:
            # Elevate role to specialized type where possible
            elevated_role = self._elevate_role(schema)
            concept = self._map_concept(schema.name, elevated_role)

            semantic_col = SemanticColumn(
                name=schema.name,
                role=elevated_role,
                concept=concept,
                is_primary_metric=schema.is_primary_metric,
                is_primary_date=schema.is_primary_date,
            )
            semantic_columns[schema.name] = semantic_col

        sem_map = SemanticMap(columns=semantic_columns)
        logger.info(
            f"SemanticIntelligenceStage: {len(sem_map.metrics)} metrics, "
            f"{len(sem_map.dimensions)} dimensions, "
            f"{len(sem_map.time_columns)} time columns, "
            f"{len(sem_map.identifiers)} identifiers"
        )
        return sem_map

    def _elevate_role(self, schema: ColumnSchema) -> ColumnRole:
        """
        Refine the generic role from Stage 1 into a more semantically rich role.
        Stage 1 does general classification; this stage adds domain concept layering.
        """
        role = schema.role

        # Financial metrics: numeric columns that match financial patterns
        if role in (ColumnRole.METRIC, ColumnRole.FINANCIAL):
            if matches_financial_pattern(schema.name):
                return ColumnRole.FINANCIAL

        # Academic metrics: score/grade/attendance-named columns
        if role == ColumnRole.METRIC:
            academic_keywords = ['score', 'grade', 'mark', 'gpa', 'result', 'exam', 'test', 'quiz', 'attendance', 'pass', 'fail']
            if any(kw in schema.name.lower() for kw in academic_keywords):
                return ColumnRole.ACADEMIC

        # Healthcare metrics
        if role == ColumnRole.METRIC:
            health_keywords = ['bmi', 'height', 'weight', 'blood', 'pressure', 'heart', 'pulse', 'dosage', 'cholesterol', 'glucose']
            if any(kw in schema.name.lower() for kw in health_keywords):
                return ColumnRole.HEALTHCARE

        # Geographic dimensions
        if role in (ColumnRole.DIMENSION, ColumnRole.GEOGRAPHIC, ColumnRole.ATTRIBUTE):
            if matches_geo_pattern(schema.name):
                return ColumnRole.GEOGRAPHIC

        return role

    def _map_concept(self, col_name: str, role: ColumnRole) -> Optional[str]:
        """
        Map a column name to a universal concept string.
        The concept is a machine-readable label for the analytical meaning.
        """
        col_lower = col_name.lower()

        concept_map = {
            # Financial
            'revenue': 'revenue_metric', 'sales': 'revenue_metric', 'income': 'revenue_metric',
            'turnover': 'revenue_metric', 'billing': 'revenue_metric',
            'profit': 'profit_metric', 'margin': 'margin_metric',
            'cost': 'cost_metric', 'expense': 'cost_metric', 'spend': 'cost_metric',
            'discount': 'discount_metric', 'price': 'price_metric',
            'amount': 'amount_metric', 'total': 'total_metric', 'value': 'value_metric',
            'tax': 'tax_metric', 'fee': 'fee_metric',

            # Academic
            'score': 'score_metric', 'grade': 'grade_metric', 'mark': 'mark_metric',
            'gpa': 'gpa_metric', 'attendance': 'attendance_metric',

            # HR
            'salary': 'salary_metric', 'bonus': 'bonus_metric',
            'tenure': 'tenure_metric', 'age': 'age_metric',

            # Geographic
            'country': 'country_dimension', 'nation': 'country_dimension',
            'state': 'state_dimension', 'province': 'state_dimension',
            'region': 'region_dimension', 'territory': 'region_dimension', 'zone': 'region_dimension',
            'city': 'city_dimension', 'town': 'city_dimension',
            'zip': 'zip_dimension', 'postal': 'zip_dimension',
            'latitude': 'latitude_geo', 'longitude': 'longitude_geo',

            # Organizational
            'department': 'department_dimension', 'dept': 'department_dimension',
            'team': 'team_dimension', 'division': 'division_dimension',
            'branch': 'branch_dimension', 'store': 'store_dimension',
            'channel': 'channel_dimension', 'segment': 'segment_dimension',

            # Product
            'category': 'category_dimension', 'product': 'product_dimension',
            'brand': 'brand_dimension', 'sku': 'sku_identifier',
            'model': 'model_dimension',

            # Demographic
            'gender': 'gender_dimension', 'sex': 'gender_dimension',
            'age_group': 'age_group_dimension', 'cohort': 'cohort_dimension',

            # Time
            'date': 'date_time', 'datetime': 'date_time', 'timestamp': 'timestamp_time',
            'year': 'year_time', 'month': 'month_time',
            'quarter': 'quarter_time', 'week': 'week_time', 'day': 'day_time',
        }

        for key, concept in concept_map.items():
            if key in col_lower:
                return concept

        return None


semantic_intelligence_stage = SemanticIntelligenceStage()
