"""Extend analysis_operations for full analytical brain persistence.

Revision ID: 002
Revises: 001
Create Date: 2026-08-23

Adds to analysis_operations:
    value_json           — computed scalar/collection value (JSONB)
    row_indices_json     — list of matched DataFrame row indices (JSONB)
    matching_rows_json   — preview rows up to 10 (JSONB)
    dataset_fingerprint  — SHA-256 of dataset at computation time (VARCHAR 64)
    verified             — True if ResultVerifier confirmed the value (BOOLEAN)
    verification_details — verifier output (JSONB)
    plan_json            — full AnalyticalPlanner output (JSONB)
    normalized_intent    — e.g. "highest_age" (VARCHAR 100)
    query_text           — original user query for this operation (TEXT)
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All columns are nullable so existing rows are unaffected.
    op.add_column("analysis_operations", sa.Column("value_json", JSONB, nullable=True))
    op.add_column("analysis_operations", sa.Column("row_indices_json", JSONB, nullable=True))
    op.add_column("analysis_operations", sa.Column("matching_rows_json", JSONB, nullable=True))
    op.add_column(
        "analysis_operations",
        sa.Column("dataset_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "analysis_operations",
        sa.Column("verified", sa.Boolean, nullable=True, server_default=sa.text("false")),
    )
    op.add_column(
        "analysis_operations",
        sa.Column("verification_details", JSONB, nullable=True),
    )
    op.add_column("analysis_operations", sa.Column("plan_json", JSONB, nullable=True))
    op.add_column(
        "analysis_operations",
        sa.Column("normalized_intent", sa.String(100), nullable=True),
    )
    op.add_column(
        "analysis_operations",
        sa.Column("query_text", sa.Text, nullable=True),
    )
    # Index fingerprint for stale-result checks
    op.create_index(
        "ix_analysis_operations_fingerprint",
        "analysis_operations",
        ["dataset_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_operations_fingerprint", table_name="analysis_operations")
    for col in [
        "query_text",
        "normalized_intent",
        "plan_json",
        "verification_details",
        "verified",
        "dataset_fingerprint",
        "matching_rows_json",
        "row_indices_json",
        "value_json",
    ]:
        op.drop_column("analysis_operations", col)
