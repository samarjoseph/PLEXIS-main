"""Add R2 storage metadata and spreadsheet action history tables

Revision ID: 006
Revises: 005
Create Date: 2026-10-26
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── datasets storage metadata ─────────────────────────────────────────────
    op.add_column(
        'datasets',
        sa.Column('storage_account', sa.String(50), server_default='primary', nullable=False)
    )
    op.add_column(
        'datasets',
        sa.Column('storage_key', sa.String(500), nullable=True)
    )
    op.add_column(
        'datasets',
        sa.Column('current_revision', sa.Integer(), server_default='0', nullable=False)
    )

    # ── dataset_versions storage metadata ─────────────────────────────────────
    op.add_column(
        'dataset_versions',
        sa.Column('revision', sa.Integer(), server_default='0', nullable=True)
    )
    op.add_column(
        'dataset_versions',
        sa.Column('storage_account', sa.String(50), server_default='primary', nullable=True)
    )
    op.add_column(
        'dataset_versions',
        sa.Column('storage_key', sa.String(1024), nullable=True)
    )

    # ── spreadsheet_actions ───────────────────────────────────────────────────
    op.create_table(
        'spreadsheet_actions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'dataset_id', UUID(as_uuid=True),
            sa.ForeignKey('datasets.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('session_id', sa.String(100), nullable=True),
        sa.Column('base_revision', sa.Integer(), nullable=False),
        sa.Column('resulting_revision', sa.Integer(), nullable=False),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('operation_payload', JSONB(), nullable=False),
        sa.Column('inverse_payload', JSONB(), nullable=True),
        sa.Column('storage_account', sa.String(50), server_default='primary', nullable=False),
        sa.Column('storage_key', sa.String(1024), nullable=True),
        sa.Column('status', sa.String(20), server_default='committed', nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
    )
    op.create_index(
        'ix_spreadsheet_actions_dataset_id',
        'spreadsheet_actions', ['dataset_id'],
    )
    op.create_index(
        'ix_spreadsheet_actions_user_id',
        'spreadsheet_actions', ['user_id'],
    )
    op.create_index(
        'ix_spreadsheet_actions_dataset_seq',
        'spreadsheet_actions', ['dataset_id', 'sequence_number'],
    )


def downgrade() -> None:
    op.drop_index('ix_spreadsheet_actions_dataset_seq', table_name='spreadsheet_actions')
    op.drop_index('ix_spreadsheet_actions_user_id', table_name='spreadsheet_actions')
    op.drop_index('ix_spreadsheet_actions_dataset_id', table_name='spreadsheet_actions')
    op.drop_table('spreadsheet_actions')

    op.drop_column('dataset_versions', 'storage_key')
    op.drop_column('dataset_versions', 'storage_account')
    op.drop_column('dataset_versions', 'revision')

    op.drop_column('datasets', 'current_revision')
    op.drop_column('datasets', 'storage_key')
    op.drop_column('datasets', 'storage_account')
