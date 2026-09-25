"""Initial schema — all Plexis tables.

Revision ID: 001
Revises:
Create Date: 2026-08-19

Tables created:
    users
    chats
    datasets
    dataset_files
    messages
    analysis_sessions
    analysis_operations
    evidence_references
    user_memories
    chat_memories
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # users
    # -------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"], unique=True)

    # -------------------------------------------------------------------------
    # datasets (belongs to User, not to Chat/Session)
    # -------------------------------------------------------------------------
    op.create_table(
        "datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_filename", sa.String(500), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("schema_json", JSONB(), nullable=True),
        sa.Column("profile_json", JSONB(), nullable=True),
        sa.Column("dko_json", JSONB(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "file_hash", name="uq_user_file_hash"),
    )
    op.create_index("ix_datasets_user_id", "datasets", ["user_id"])
    op.create_index("ix_datasets_file_hash", "datasets", ["file_hash"])

    # -------------------------------------------------------------------------
    # dataset_files (BYTEA content, 1:1 with datasets)
    # -------------------------------------------------------------------------
    op.create_table(
        "dataset_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("compression", sa.String(20), server_default="gzip"),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # -------------------------------------------------------------------------
    # chats (current_dataset_id = currently active dataset, can change)
    # -------------------------------------------------------------------------
    op.create_table(
        "chats",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False, server_default="New Chat"),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chats_user_id", "chats", ["user_id"])
    op.create_index("ix_chats_slug", "chats", ["slug"], unique=True)

    # -------------------------------------------------------------------------
    # messages (UNIQUE(chat_id, sequence_number) for deterministic ordering)
    # -------------------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_type", sa.String(50), server_default="conversation"),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.UniqueConstraint("chat_id", "sequence_number", name="uq_chat_sequence"),
    )
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])

    # -------------------------------------------------------------------------
    # analysis_sessions (references both chat and dataset)
    # -------------------------------------------------------------------------
    op.create_table(
        "analysis_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("current_state_json", JSONB(), nullable=True),
        sa.Column("analysis_context_json", JSONB(), nullable=True),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_analysis_sessions_chat_id", "analysis_sessions", ["chat_id"])
    op.create_index("ix_analysis_sessions_dataset_id", "analysis_sessions", ["dataset_id"])

    # -------------------------------------------------------------------------
    # analysis_operations (with before/after state for Undo/Redo)
    # -------------------------------------------------------------------------
    op.create_table(
        "analysis_operations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_session_id", UUID(as_uuid=True), sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_type", sa.String(100), nullable=False),
        sa.Column("column_name", sa.String(255), nullable=True),
        sa.Column("parameters_json", JSONB(), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("before_state_json", JSONB(), nullable=True),
        sa.Column("after_state_json", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_analysis_operations_session_id", "analysis_operations", ["analysis_session_id"])
    op.create_index("ix_analysis_operations_dataset_id", "analysis_operations", ["dataset_id"])

    # -------------------------------------------------------------------------
    # evidence_references
    # -------------------------------------------------------------------------
    op.create_table(
        "evidence_references",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", UUID(as_uuid=True), sa.ForeignKey("analysis_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("row_locator_json", JSONB(), nullable=True),
        sa.Column("column_names", ARRAY(sa.String()), nullable=True),
        sa.Column("operation_type", sa.String(100), nullable=True),
        sa.Column("result_value", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("preview_rows_json", JSONB(), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evidence_references_operation_id", "evidence_references", ["operation_id"])
    op.create_index("ix_evidence_references_dataset_id", "evidence_references", ["dataset_id"])

    # -------------------------------------------------------------------------
    # user_memories
    # -------------------------------------------------------------------------
    op.create_table(
        "user_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.String(50), server_default="preference"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "key", name="uq_user_memory_key"),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])

    # -------------------------------------------------------------------------
    # chat_memories
    # -------------------------------------------------------------------------
    op.create_table(
        "chat_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(255), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "chat_id", "key", name="uq_chat_memory_key"),
    )
    op.create_index("ix_chat_memories_user_id", "chat_memories", ["user_id"])
    op.create_index("ix_chat_memories_chat_id", "chat_memories", ["chat_id"])


def downgrade() -> None:
    op.drop_table("chat_memories")
    op.drop_table("user_memories")
    op.drop_table("evidence_references")
    op.drop_table("analysis_operations")
    op.drop_table("analysis_sessions")
    op.drop_table("messages")
    op.drop_table("chats")
    op.drop_table("dataset_files")
    op.drop_table("datasets")
    op.drop_table("users")
