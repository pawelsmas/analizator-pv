"""Add job_queue table for distributed job processing

Revision ID: 0003_job_queue
Revises: 0002_run_job_index
Create Date: 2024-01-03 00:00:00.000000

v3.4.0 PR1: Distributed Jobs - DB-backed job queue with worker claim/lock.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_job_queue'
down_revision: Union[str, None] = '0002_run_job_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create job_queue table
    op.create_table(
        'job_queue',
        # Primary key
        sa.Column('id', sa.String(36), primary_key=True),
        # Tenant isolation
        sa.Column('tenant_id', sa.String(36), nullable=False, server_default='default'),
        # Job type and payload
        sa.Column('kind', sa.String(50), nullable=False),
        sa.Column('payload_json', sa.Text, nullable=True),
        # Status tracking
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        # Result storage
        sa.Column('result_json', sa.Text, nullable=True),
        # Error handling
        sa.Column('error_code', sa.String(50), nullable=True),
        sa.Column('error_detail', sa.Text, nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        # Retry handling
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer, nullable=False, server_default='3'),
        # Worker locking
        sa.Column('locked_by', sa.String(255), nullable=True),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        # Progress tracking (optional JSON)
        sa.Column('progress_json', sa.Text, nullable=True),
    )

    # Create indexes for efficient querying
    # Index for claim query: status + locked_until
    op.create_index('idx_job_queue_status', 'job_queue', ['status'])
    op.create_index('idx_job_queue_tenant', 'job_queue', ['tenant_id'])
    op.create_index('idx_job_queue_created_at', 'job_queue', ['created_at'])
    op.create_index('idx_job_queue_kind', 'job_queue', ['kind'])
    # Composite index for claim query
    op.create_index('idx_job_queue_tenant_status', 'job_queue', ['tenant_id', 'status'])
    op.create_index('idx_job_queue_locked_until', 'job_queue', ['locked_until'])
    # Composite for worker claim: status=queued AND locked_until < now
    op.create_index('idx_job_queue_claim', 'job_queue', ['status', 'locked_until'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_job_queue_claim', 'job_queue')
    op.drop_index('idx_job_queue_locked_until', 'job_queue')
    op.drop_index('idx_job_queue_tenant_status', 'job_queue')
    op.drop_index('idx_job_queue_kind', 'job_queue')
    op.drop_index('idx_job_queue_created_at', 'job_queue')
    op.drop_index('idx_job_queue_tenant', 'job_queue')
    op.drop_index('idx_job_queue_status', 'job_queue')
    # Drop table
    op.drop_table('job_queue')
