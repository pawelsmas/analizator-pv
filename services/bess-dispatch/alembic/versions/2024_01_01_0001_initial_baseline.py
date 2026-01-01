"""Initial baseline - auth/audit/invites/shares/api_keys tables

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

This migration creates the baseline schema for BESS Dispatch auth/audit system.
Tables included:
- tenants
- users
- api_keys (with v3.2.0 last_used_at, rotated_from)
- invites
- shares
- audit_log (with v3.2.0 prev_hash, entry_hash)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tenants table
    op.create_table(
        'tenants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
    )

    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('disabled', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.create_index('idx_users_email', 'users', ['email'])
    op.create_index('idx_users_tenant', 'users', ['tenant_id'])

    # API keys table (with v3.2.0 columns)
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('revoked_at', sa.String(32), nullable=True),
        sa.Column('last_used_at', sa.String(32), nullable=True),  # v3.2.0
        sa.Column('rotated_from', sa.String(36), nullable=True),  # v3.2.0
    )
    op.create_index('idx_api_keys_hash', 'api_keys', ['key_hash'])
    op.create_index('idx_api_keys_tenant', 'api_keys', ['tenant_id'])

    # Invites table
    op.create_table(
        'invites',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('expires_at', sa.String(32), nullable=False),
        sa.Column('accepted_at', sa.String(32), nullable=True),
        sa.Column('revoked_at', sa.String(32), nullable=True),
        sa.Column('created_by', sa.String(36), nullable=True),
    )
    op.create_index('idx_invites_token_hash', 'invites', ['token_hash'])
    op.create_index('idx_invites_tenant', 'invites', ['tenant_id'])

    # Shares table
    op.create_table(
        'shares',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('resource_type', sa.String(32), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('expires_at', sa.String(32), nullable=True),
        sa.Column('revoked_at', sa.String(32), nullable=True),
        sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('label', sa.String(255), nullable=True),
    )
    op.create_index('idx_shares_token_hash', 'shares', ['token_hash'])
    op.create_index('idx_shares_tenant', 'shares', ['tenant_id'])

    # Audit log table (with v3.2.0 hash chain columns)
    op.create_table(
        'audit_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=True),
        sa.Column('actor_email', sa.String(255), nullable=True),
        sa.Column('actor_role', sa.String(32), nullable=True),
        sa.Column('auth_method', sa.String(32), nullable=True),
        sa.Column('resource_type', sa.String(32), nullable=True),
        sa.Column('resource_id', sa.String(36), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
        sa.Column('prev_hash', sa.String(64), nullable=True),  # v3.2.0
        sa.Column('entry_hash', sa.String(64), nullable=True),  # v3.2.0
    )
    op.create_index('idx_audit_tenant_id', 'audit_log', ['tenant_id'])
    op.create_index('idx_audit_created_at', 'audit_log', ['created_at'])
    op.create_index('idx_audit_action', 'audit_log', ['action'])
    op.create_index('idx_audit_actor_id', 'audit_log', ['actor_id'])


def downgrade() -> None:
    op.drop_table('audit_log')
    op.drop_table('shares')
    op.drop_table('invites')
    op.drop_table('api_keys')
    op.drop_table('users')
    op.drop_table('tenants')
