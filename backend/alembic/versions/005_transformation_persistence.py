"""Add transformation_plans and dataset_versions tables

Revision ID: 005
Revises: 004_early_access_submissions
Create Date: 2026-09-27
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004_early_access_submissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── transformation_plans ──────────────────────────────────────────────────
    op.create_table(
        'transformation_plans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'dataset_id', UUID(as_uuid=True),
            sa.ForeignKey('datasets.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('chat_id', UUID(as_uuid=True), nullable=True),
        sa.Column('operation_type', sa.String(100), nullable=False),
        sa.Column('operation_payload', JSONB(), nullable=False),
        sa.Column('operation_code', sa.Text(), nullable=False),
        sa.Column('affected_rows_count', sa.Integer(), nullable=False),
        sa.Column('affected_cells_count', sa.Integer(), nullable=False),
        sa.Column('before_sample_json', JSONB(), nullable=True),
        sa.Column('dataset_fingerprint', sa.String(64), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_transformation_plans_dataset_id',
        'transformation_plans', ['dataset_id'],
    )
    op.create_index(
        'ix_transformation_plans_status',
        'transformation_plans', ['status'],
    )

    # ── dataset_versions ──────────────────────────────────────────────────────
    op.create_table(
        'dataset_versions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'original_dataset_id', UUID(as_uuid=True),
            sa.ForeignKey('datasets.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'version_dataset_id', UUID(as_uuid=True),
            sa.ForeignKey('datasets.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'parent_version_id', UUID(as_uuid=True),
            sa.ForeignKey('dataset_versions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'plan_id', UUID(as_uuid=True),
            sa.ForeignKey('transformation_plans.id', ondelete='RESTRICT'),
            nullable=True,
        ),
        sa.Column('operation_label', sa.String(500), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('changed_cells_count', sa.Integer(), nullable=False),
        sa.Column('metadata_json', JSONB(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
    )
    op.create_index(
        'ix_dataset_versions_original_dataset_id',
        'dataset_versions', ['original_dataset_id'],
    )
    op.create_index(
        'ix_dataset_versions_plan_id',
        'dataset_versions', ['plan_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_dataset_versions_plan_id', table_name='dataset_versions')
    op.drop_index('ix_dataset_versions_original_dataset_id', table_name='dataset_versions')
    op.drop_table('dataset_versions')
    op.drop_index('ix_transformation_plans_status', table_name='transformation_plans')
    op.drop_index('ix_transformation_plans_dataset_id', table_name='transformation_plans')
    op.drop_table('transformation_plans')
