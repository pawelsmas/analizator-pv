"""Add run_index and job_index tables

Revision ID: 0002_run_job_index
Revises: 0001_initial_baseline
Create Date: 2024-01-02 00:00:00.000000

v3.3.0 PR4: DB-indexed runs/jobs listing for faster queries.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_run_job_index'
down_revision: Union[str, None] = '0001_initial_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create run_index table
    op.create_table(
        'run_index',
        sa.Column('run_id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, server_default='default'),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('endpoint', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('cache_hit', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('schema_version', sa.String(20), nullable=True),
        sa.Column('assumptions_version', sa.String(64), nullable=True),
        sa.Column('compute_time_ms', sa.Integer, nullable=True),
        # Metadata columns
        sa.Column('label', sa.String(80), nullable=True),
        sa.Column('tags_json', sa.Text, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        # Blob storage
        sa.Column('request_blob', sa.LargeBinary, nullable=True),
        sa.Column('response_blob', sa.LargeBinary, nullable=True),
    )

    # Create indexes for run_index
    op.create_index('idx_run_index_tenant', 'run_index', ['tenant_id'])
    op.create_index('idx_run_index_created_at', 'run_index', ['created_at'])
    op.create_index('idx_run_index_request_hash', 'run_index', ['request_hash'])
    op.create_index('idx_run_index_endpoint', 'run_index', ['endpoint'])
    op.create_index('idx_run_index_status', 'run_index', ['status'])
    op.create_index('idx_run_index_tenant_created', 'run_index', ['tenant_id', 'created_at'])

    # Create job_index table
    op.create_table(
        'job_index',
        sa.Column('job_id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, server_default='default'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('batch_id', sa.String(36), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True),
        sa.Column('items_total', sa.Integer, nullable=False, server_default='0'),
        sa.Column('items_done', sa.Integer, nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('message', sa.Text, nullable=True),
        # Leasing columns
        sa.Column('lease_owner', sa.String(255), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer, nullable=False, server_default='3'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text, nullable=True),
        # Metadata columns
        sa.Column('label', sa.String(80), nullable=True),
        sa.Column('tags_json', sa.Text, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        # Blob storage
        sa.Column('request_blob', sa.LargeBinary, nullable=True),
        sa.Column('result_blob', sa.LargeBinary, nullable=True),
    )

    # Create indexes for job_index
    op.create_index('idx_job_index_tenant', 'job_index', ['tenant_id'])
    op.create_index('idx_job_index_created_at', 'job_index', ['created_at'])
    op.create_index('idx_job_index_status', 'job_index', ['status'])
    op.create_index('idx_job_index_type', 'job_index', ['type'])
    op.create_index('idx_job_index_idempotency_key', 'job_index', ['idempotency_key'])
    op.create_index('idx_job_index_lease_expires', 'job_index', ['lease_expires_at'])
    op.create_index('idx_job_index_tenant_status', 'job_index', ['tenant_id', 'status'])
    # Composite unique for idempotency per tenant
    op.create_index(
        'idx_job_index_idempotency_tenant',
        'job_index',
        ['idempotency_key', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL')
    )


def downgrade() -> None:
    # Drop indexes first
    op.drop_index('idx_job_index_idempotency_tenant', 'job_index')
    op.drop_index('idx_job_index_tenant_status', 'job_index')
    op.drop_index('idx_job_index_lease_expires', 'job_index')
    op.drop_index('idx_job_index_idempotency_key', 'job_index')
    op.drop_index('idx_job_index_type', 'job_index')
    op.drop_index('idx_job_index_status', 'job_index')
    op.drop_index('idx_job_index_created_at', 'job_index')
    op.drop_index('idx_job_index_tenant', 'job_index')
    op.drop_table('job_index')

    op.drop_index('idx_run_index_tenant_created', 'run_index')
    op.drop_index('idx_run_index_status', 'run_index')
    op.drop_index('idx_run_index_endpoint', 'run_index')
    op.drop_index('idx_run_index_request_hash', 'run_index')
    op.drop_index('idx_run_index_created_at', 'run_index')
    op.drop_index('idx_run_index_tenant', 'run_index')
    op.drop_table('run_index')
