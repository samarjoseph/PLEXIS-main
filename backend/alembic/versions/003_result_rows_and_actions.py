"""
New tables + AnalysisOperation extension for analytical persistence UX.

Revision ID: 003
Revises: 002
Create Date: 2026-08-25

Creates:
    analysis_result_rows  — Per-row source references (source_row_number, record data)
    analysis_actions      — User interaction log (explain/locate/retry)

Extends analysis_operations:
    retry_of_operation_id — Links a retry to the original operation
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── analysis_result_rows ─────────────────────────────────────────────────
    op.create_table(
        "analysis_result_rows",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operation_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("analysis_operations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("source_row_number", sa.Integer, nullable=False),   # 1-based spreadsheet row
        sa.Column("dataframe_index", sa.Integer, nullable=True),       # 0-based df positional index
        sa.Column("record_data_json", JSONB, nullable=True),           # full row values
        sa.Column("column_value", JSONB, nullable=True),               # specific analytical value
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_analysis_result_rows_operation_id",
        "analysis_result_rows", ["operation_id"],
    )
    op.create_index(
        "ix_analysis_result_rows_source_row",
        "analysis_result_rows", ["source_row_number"],
    )
    op.create_index(
        "ix_analysis_result_rows_op_row",
        "analysis_result_rows", ["operation_id", "source_row_number"],
    )

    # ── analysis_actions ─────────────────────────────────────────────────────
    op.create_table(
        "analysis_actions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("operation_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("analysis_operations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("chat_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chats.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("dataset_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("action_type", sa.String(30), nullable=False),  # explain/locate/locate_selection/retry
        sa.Column("action_metadata_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_analysis_actions_operation_id", "analysis_actions", ["operation_id"])
    op.create_index("ix_analysis_actions_user_id",      "analysis_actions", ["user_id"])
    op.create_index("ix_analysis_actions_chat_id",      "analysis_actions", ["chat_id"])
    op.create_index("ix_analysis_actions_action_type",  "analysis_actions", ["action_type"])

    # ── analysis_operations: add retry_of_operation_id ───────────────────────
    op.add_column(
        "analysis_operations",
        sa.Column(
            "retry_of_operation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_operations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_operations", "retry_of_operation_id")
    op.drop_index("ix_analysis_actions_action_type",  table_name="analysis_actions")
    op.drop_index("ix_analysis_actions_chat_id",      table_name="analysis_actions")
    op.drop_index("ix_analysis_actions_user_id",      table_name="analysis_actions")
    op.drop_index("ix_analysis_actions_operation_id", table_name="analysis_actions")
    op.drop_table("analysis_actions")
    op.drop_index("ix_analysis_result_rows_op_row",       table_name="analysis_result_rows")
    op.drop_index("ix_analysis_result_rows_source_row",   table_name="analysis_result_rows")
    op.drop_index("ix_analysis_result_rows_operation_id", table_name="analysis_result_rows")
    op.drop_table("analysis_result_rows")
