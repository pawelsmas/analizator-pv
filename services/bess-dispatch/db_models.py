"""
SQLAlchemy ORM models (v3.3.0 PR3/PR4, v3.4.0 PR1).

Defines all database tables used by BESS API for PostgreSQL and SQLite backends.

PR3: Auth tables (tenants, users, api_keys, invites, shares, audit_log)
PR4: Run/Job index tables (run_index, job_index) for faster listing
v3.4.0 PR1: JobQueue table for distributed job processing
"""

from datetime import datetime, timezone
from typing import Optional
import json

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Tenant(Base):
    """Tenant model - multi-tenant isolation."""
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")
    invites = relationship("Invite", back_populates="tenant", cascade="all, delete-orphan")
    shares = relationship("Share", back_populates="tenant", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="tenant", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """User model."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    disabled = Column(Boolean, nullable=False, default=False)

    # v3.2.0 lockout columns
    failed_attempts = Column(Integer, nullable=False, default=0)
    lockout_until = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")

    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_tenant", "tenant_id"),
    )

    def to_dict(self, include_hash: bool = False) -> dict:
        result = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "disabled": self.disabled,
        }
        if include_hash:
            result["password_hash"] = self.password_hash
        return result


class APIKey(Base):
    """API key model."""
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    label = Column(String(255), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True)
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # v3.2.0 rotation columns
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    rotated_from = Column(String(36), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_hash", "key_hash"),
        Index("idx_api_keys_tenant", "tenant_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "label": self.label,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "rotated_from": self.rotated_from,
        }


class Invite(Base):
    """Invite model for user registration links."""
    __tablename__ = "invites"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="invites")

    __table_args__ = (
        Index("idx_invites_token_hash", "token_hash"),
        Index("idx_invites_tenant", "tenant_id"),
        Index("idx_invites_email", "email"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_by": self.created_by,
        }


class Share(Base):
    """Share link model for resource sharing."""
    __tablename__ = "shares"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(36), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    label = Column(String(255), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="shares")

    __table_args__ = (
        Index("idx_shares_token_hash", "token_hash"),
        Index("idx_shares_tenant", "tenant_id"),
        Index("idx_shares_resource", "resource_type", "resource_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_by": self.created_by,
            "label": self.label,
        }


class AuditLog(Base):
    """Audit log model for security events."""
    __tablename__ = "audit_log"

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    action = Column(String(100), nullable=False)
    actor_id = Column(String(36), nullable=True)
    actor_email = Column(String(255), nullable=True)
    actor_role = Column(String(50), nullable=True)
    auth_method = Column(String(50), nullable=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(36), nullable=True)
    details_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # v3.2.0 chain integrity columns
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_tenant_id", "tenant_id"),
        Index("idx_audit_created_at", "created_at"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_actor_id", "actor_id"),
    )

    def to_dict(self) -> dict:
        details = None
        if self.details_json:
            try:
                details = json.loads(self.details_json)
            except json.JSONDecodeError:
                details = None

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "action": self.action,
            "actor_id": self.actor_id,
            "actor_email": self.actor_email,
            "actor_role": self.actor_role,
            "auth_method": self.auth_method,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }


# =============================================================================
# Run/Job Index Models (v3.3.0 PR4)
# =============================================================================

class RunIndex(Base):
    """
    Run index model for fast listing (v3.3.0 PR4).

    Stores metadata index for runs. The full request/response blobs
    are stored separately (in run_store.py SQLite files for now).
    This table enables fast Postgres-backed listing with proper indexes.
    """
    __tablename__ = "run_index"

    run_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, default="default")
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    endpoint = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    cache_hit = Column(Boolean, nullable=False, default=False)
    schema_version = Column(String(20), nullable=True)
    assumptions_version = Column(String(64), nullable=True)
    compute_time_ms = Column(Integer, nullable=True)

    # v1.3.0 metadata
    label = Column(String(80), nullable=True)
    tags_json = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    # Blob storage (zlib-compressed JSON)
    request_blob = Column(LargeBinary, nullable=True)
    response_blob = Column(LargeBinary, nullable=True)

    __table_args__ = (
        Index("idx_run_index_tenant", "tenant_id"),
        Index("idx_run_index_created_at", "created_at"),
        Index("idx_run_index_request_hash", "request_hash"),
        Index("idx_run_index_endpoint", "endpoint"),
        Index("idx_run_index_status", "status"),
        Index("idx_run_index_tenant_created", "tenant_id", "created_at"),
    )

    def to_dict(self, include_blobs: bool = False) -> dict:
        import zlib

        tags = None
        if self.tags_json:
            try:
                tags = json.loads(self.tags_json)
            except json.JSONDecodeError:
                tags = None

        result = {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "request_hash": self.request_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "endpoint": self.endpoint,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "schema_version": self.schema_version,
            "assumptions_version": self.assumptions_version,
            "compute_time_ms": self.compute_time_ms,
            "label": self.label,
            "tags": tags,
            "notes": self.notes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_blobs:
            if self.request_blob:
                try:
                    result["request"] = json.loads(zlib.decompress(self.request_blob).decode("utf-8"))
                except Exception:
                    result["request"] = None
            if self.response_blob:
                try:
                    result["response"] = json.loads(zlib.decompress(self.response_blob).decode("utf-8"))
                except Exception:
                    result["response"] = None

        return result


class JobIndex(Base):
    """
    Job index model for fast listing (v3.3.0 PR4).

    Stores metadata index for async jobs. Enables fast Postgres-backed
    listing with proper indexes for status, type, tenant filtering.
    """
    __tablename__ = "job_index"

    job_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), nullable=False, default="default")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    batch_id = Column(String(36), nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    items_total = Column(Integer, nullable=False, default=0)
    items_done = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    request_hash = Column(String(64), nullable=False)
    message = Column(Text, nullable=True)

    # Leasing columns (v1.2.0)
    lease_owner = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # v1.3.0 metadata
    label = Column(String(80), nullable=True)
    tags_json = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Blob storage (zlib-compressed JSON)
    request_blob = Column(LargeBinary, nullable=True)
    result_blob = Column(LargeBinary, nullable=True)

    __table_args__ = (
        Index("idx_job_index_tenant", "tenant_id"),
        Index("idx_job_index_created_at", "created_at"),
        Index("idx_job_index_status", "status"),
        Index("idx_job_index_type", "type"),
        Index("idx_job_index_idempotency_key", "idempotency_key"),
        Index("idx_job_index_lease_expires", "lease_expires_at"),
        Index("idx_job_index_tenant_status", "tenant_id", "status"),
        # Composite unique for idempotency per tenant
        Index("idx_job_index_idempotency_tenant", "idempotency_key", "tenant_id", unique=True),
    )

    def to_dict(self, include_blobs: bool = False) -> dict:
        import zlib

        tags = None
        if self.tags_json:
            try:
                tags = json.loads(self.tags_json)
            except json.JSONDecodeError:
                tags = None

        result = {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "type": self.type,
            "status": self.status,
            "batch_id": self.batch_id,
            "idempotency_key": self.idempotency_key,
            "items_total": self.items_total,
            "items_done": self.items_done,
            "error_count": self.error_count,
            "request_hash": self.request_hash,
            "message": self.message,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_error": self.last_error,
            "label": self.label,
            "tags": tags,
            "notes": self.notes,
        }

        if include_blobs:
            if self.request_blob:
                try:
                    result["request"] = json.loads(zlib.decompress(self.request_blob).decode("utf-8"))
                except Exception:
                    result["request"] = None
            if self.result_blob:
                try:
                    result["result"] = json.loads(zlib.decompress(self.result_blob).decode("utf-8"))
                except Exception:
                    result["result"] = None

        return result


# =============================================================================
# Job Queue Model (v3.4.0 PR1)
# =============================================================================

class JobQueue(Base):
    """
    Job queue model for distributed job processing (v3.4.0 PR1).

    This table enables async job execution by workers. Jobs are claimed using
    database-level locking (FOR UPDATE SKIP LOCKED on Postgres, optimistic
    locking on SQLite).

    Statuses:
    - queued: Ready to be claimed by a worker
    - running: Currently being processed by a worker
    - succeeded: Completed successfully
    - failed: Failed after all retry attempts
    - cancelled: Cancelled by user request

    Kinds:
    - sizing_batch: Batch sizing calculations
    - report_run: Generate report for a single run
    - report_portfolio: Generate portfolio report
    - validate_pack: Run scenario pack validation
    """
    __tablename__ = "job_queue"

    # Primary key (UUID or ULID)
    id = Column(String(36), primary_key=True)

    # Tenant isolation
    tenant_id = Column(String(36), nullable=False, default="default")

    # Job type and payload
    kind = Column(String(50), nullable=False)
    payload_json = Column(Text, nullable=True)

    # Status tracking
    status = Column(String(20), nullable=False, default="queued")

    # Result storage
    result_json = Column(Text, nullable=True)

    # Error handling
    error_code = Column(String(50), nullable=True)
    error_detail = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Retry handling
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)

    # Worker locking
    locked_by = Column(String(255), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # Progress tracking (optional JSON)
    progress_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_job_queue_status", "status"),
        Index("idx_job_queue_tenant", "tenant_id"),
        Index("idx_job_queue_created_at", "created_at"),
        Index("idx_job_queue_kind", "kind"),
        Index("idx_job_queue_tenant_status", "tenant_id", "status"),
        Index("idx_job_queue_locked_until", "locked_until"),
        Index("idx_job_queue_claim", "status", "locked_until"),
    )

    def to_dict(self, include_payload: bool = True, include_result: bool = True) -> dict:
        payload = None
        if include_payload and self.payload_json:
            try:
                payload = json.loads(self.payload_json)
            except json.JSONDecodeError:
                payload = None

        result_data = None
        if include_result and self.result_json:
            try:
                result_data = json.loads(self.result_json)
            except json.JSONDecodeError:
                result_data = None

        progress = None
        if self.progress_json:
            try:
                progress = json.loads(self.progress_json)
            except json.JSONDecodeError:
                progress = None

        result = {
            "job_id": self.id,
            "tenant_id": self.tenant_id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "progress": progress,
        }

        if include_payload:
            result["payload"] = payload

        if include_result:
            result["result"] = result_data

        # Include error info if present
        if self.error_code or self.error_detail:
            result["error"] = {
                "code": self.error_code,
                "detail": self.error_detail,
            }

        return result
