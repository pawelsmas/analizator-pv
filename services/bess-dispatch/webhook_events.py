"""
Webhook events SSoT (Single Source of Truth) for BESS API (v4.1.0).

Defines canonical event types and payload schemas for webhooks.
Each event has a unique event_id for idempotency tracking.

Events:
- job.succeeded: Sizing/validation job completed successfully
- job.failed: Sizing/validation job failed
- report.generated: PDF report was generated
- share.accessed: Shared link was accessed
- quota.exceeded: Usage quota was exceeded
- run.created: New sizing run was created

Usage:
    from webhook_events import WebhookEventEmitter, EventType

    emitter = WebhookEventEmitter(webhook_store)
    emitter.emit_job_succeeded(tenant_id, project_id, job_id, run_id, summary)
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from webhook_store import WebhookStore


class EventType(str, Enum):
    """Supported webhook event types."""
    JOB_SUCCEEDED = "job.succeeded"
    JOB_FAILED = "job.failed"
    REPORT_GENERATED = "report.generated"
    SHARE_ACCESSED = "share.accessed"
    QUOTA_EXCEEDED = "quota.exceeded"
    RUN_CREATED = "run.created"


# -------------------------------------------------------------------------
# Event Payload Models
# -------------------------------------------------------------------------

@dataclass
class BaseEventPayload:
    """Base payload for all events."""
    event_id: str
    event_type: str
    timestamp: str
    tenant_id: str
    project_id: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class JobSucceededPayload(BaseEventPayload):
    """Payload for job.succeeded event."""
    job_id: str
    job_type: str  # "sizing" | "validation" | "sizing-batch"
    run_id: Optional[str]
    duration_ms: int
    summary: Dict[str, Any]  # Subset of results (NPV, CAPEX, etc.)


@dataclass
class JobFailedPayload(BaseEventPayload):
    """Payload for job.failed event."""
    job_id: str
    job_type: str
    run_id: Optional[str]
    error_code: str
    error_message: str
    duration_ms: Optional[int]


@dataclass
class ReportGeneratedPayload(BaseEventPayload):
    """Payload for report.generated event."""
    report_id: str
    run_id: str
    format: str  # "pdf" | "csv" | "xlsx"
    size_bytes: int
    download_url: Optional[str]  # Temporary signed URL if enabled


@dataclass
class ShareAccessedPayload(BaseEventPayload):
    """Payload for share.accessed event."""
    share_id: str
    run_id: str
    accessed_by_ip: Optional[str]  # Anonymized or omitted based on settings
    access_type: str  # "view" | "download"


@dataclass
class QuotaExceededPayload(BaseEventPayload):
    """Payload for quota.exceeded event."""
    quota_name: str  # e.g., "jobs_per_day", "reports_per_day"
    quota_limit: int
    current_usage: int
    period: str  # "daily" | "monthly"
    reset_at: str  # ISO timestamp when quota resets


@dataclass
class RunCreatedPayload(BaseEventPayload):
    """Payload for run.created event."""
    run_id: str
    name: str
    created_by_user_id: Optional[str]
    scenario_count: int


# -------------------------------------------------------------------------
# Event ID Generation
# -------------------------------------------------------------------------

def generate_event_id(
    event_type: str,
    tenant_id: str,
    project_id: Optional[str],
    *args: str,
) -> str:
    """
    Generate unique event ID based on event content.

    Format: evt_{type_prefix}_{timestamp_ms}_{hash_suffix}

    The hash includes all provided args to ensure uniqueness.
    """
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    type_prefix = event_type.split('.')[0][:3]  # e.g., "job" -> "job"

    # Create hash from content
    content = f"{event_type}:{tenant_id}:{project_id or ''}:{':'.join(str(a) for a in args)}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:8]

    return f"evt_{type_prefix}_{timestamp_ms}_{hash_suffix}"


def generate_dedup_key(
    event_type: str,
    tenant_id: str,
    project_id: Optional[str],
    unique_key: str,
) -> str:
    """
    Generate dedup key for events that should be deduplicated.

    Used for quota.exceeded to ensure only one notification per day.
    """
    return f"{event_type}:{unique_key}:{project_id or tenant_id}"


# -------------------------------------------------------------------------
# Event Emitter
# -------------------------------------------------------------------------

class WebhookEventEmitter:
    """
    Emits webhook events to the outbox for delivery.

    This is the SSoT for creating and enqueuing webhook events.
    All event emission should go through this class.
    """

    def __init__(self, webhook_store: WebhookStore):
        self.store = webhook_store

    def _now_iso(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _enqueue_for_webhooks(
        self,
        event_type: str,
        tenant_id: str,
        project_id: Optional[str],
        event_id: str,
        payload: Dict[str, Any],
        dedup_key: Optional[str] = None,
    ) -> int:
        """
        Enqueue event for all matching webhooks.

        Returns number of outbox entries created.
        """
        webhooks = self.store.get_webhooks_for_event(
            tenant_id=tenant_id,
            project_id=project_id,
            event_name=event_type,
        )

        count = 0
        for webhook in webhooks:
            entry = self.store.enqueue_event(
                webhook_id=webhook.id,
                tenant_id=tenant_id,
                project_id=project_id,
                event_name=event_type,
                event_id=event_id,
                payload=payload,
                dedup_key=f"{webhook.id}:{dedup_key}" if dedup_key else None,
            )
            if entry is not None:
                count += 1

        return count

    def emit_job_succeeded(
        self,
        tenant_id: str,
        project_id: Optional[str],
        job_id: str,
        job_type: str,
        run_id: Optional[str],
        duration_ms: int,
        summary: Dict[str, Any],
    ) -> str:
        """
        Emit job.succeeded event.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier (optional)
            job_id: Job identifier
            job_type: Type of job (sizing, validation, sizing-batch)
            run_id: Associated run ID (optional)
            duration_ms: Job duration in milliseconds
            summary: Summary of results (NPV, CAPEX, etc.)

        Returns:
            Event ID
        """
        event_id = generate_event_id(
            EventType.JOB_SUCCEEDED, tenant_id, project_id, job_id
        )

        payload = JobSucceededPayload(
            event_id=event_id,
            event_type=EventType.JOB_SUCCEEDED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job_id,
            job_type=job_type,
            run_id=run_id,
            duration_ms=duration_ms,
            summary=summary,
        )

        self._enqueue_for_webhooks(
            event_type=EventType.JOB_SUCCEEDED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
        )

        return event_id

    def emit_job_failed(
        self,
        tenant_id: str,
        project_id: Optional[str],
        job_id: str,
        job_type: str,
        run_id: Optional[str],
        error_code: str,
        error_message: str,
        duration_ms: Optional[int] = None,
    ) -> str:
        """Emit job.failed event."""
        event_id = generate_event_id(
            EventType.JOB_FAILED, tenant_id, project_id, job_id
        )

        payload = JobFailedPayload(
            event_id=event_id,
            event_type=EventType.JOB_FAILED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job_id,
            job_type=job_type,
            run_id=run_id,
            error_code=error_code,
            error_message=error_message,
            duration_ms=duration_ms,
        )

        self._enqueue_for_webhooks(
            event_type=EventType.JOB_FAILED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
        )

        return event_id

    def emit_report_generated(
        self,
        tenant_id: str,
        project_id: Optional[str],
        report_id: str,
        run_id: str,
        format: str,
        size_bytes: int,
        download_url: Optional[str] = None,
    ) -> str:
        """Emit report.generated event."""
        event_id = generate_event_id(
            EventType.REPORT_GENERATED, tenant_id, project_id, report_id
        )

        payload = ReportGeneratedPayload(
            event_id=event_id,
            event_type=EventType.REPORT_GENERATED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            report_id=report_id,
            run_id=run_id,
            format=format,
            size_bytes=size_bytes,
            download_url=download_url,
        )

        self._enqueue_for_webhooks(
            event_type=EventType.REPORT_GENERATED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
        )

        return event_id

    def emit_share_accessed(
        self,
        tenant_id: str,
        project_id: Optional[str],
        share_id: str,
        run_id: str,
        access_type: str,
        accessed_by_ip: Optional[str] = None,
    ) -> str:
        """Emit share.accessed event."""
        event_id = generate_event_id(
            EventType.SHARE_ACCESSED, tenant_id, project_id, share_id, str(uuid.uuid4())
        )

        payload = ShareAccessedPayload(
            event_id=event_id,
            event_type=EventType.SHARE_ACCESSED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            share_id=share_id,
            run_id=run_id,
            accessed_by_ip=accessed_by_ip,
            access_type=access_type,
        )

        self._enqueue_for_webhooks(
            event_type=EventType.SHARE_ACCESSED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
        )

        return event_id

    def emit_quota_exceeded(
        self,
        tenant_id: str,
        project_id: Optional[str],
        quota_name: str,
        quota_limit: int,
        current_usage: int,
        period: str,
        reset_at: str,
    ) -> Optional[str]:
        """
        Emit quota.exceeded event.

        Uses dedup key to ensure only one notification per quota per day.
        Returns None if deduplicated (already sent today).
        """
        # Dedup key includes date to send once per day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dedup_key = f"{quota_name}:{today}:{project_id or tenant_id}"

        event_id = generate_event_id(
            EventType.QUOTA_EXCEEDED, tenant_id, project_id, quota_name, today
        )

        payload = QuotaExceededPayload(
            event_id=event_id,
            event_type=EventType.QUOTA_EXCEEDED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            quota_name=quota_name,
            quota_limit=quota_limit,
            current_usage=current_usage,
            period=period,
            reset_at=reset_at,
        )

        count = self._enqueue_for_webhooks(
            event_type=EventType.QUOTA_EXCEEDED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
            dedup_key=dedup_key,
        )

        # Return event_id if at least one webhook was queued
        return event_id if count > 0 else None

    def emit_run_created(
        self,
        tenant_id: str,
        project_id: Optional[str],
        run_id: str,
        name: str,
        created_by_user_id: Optional[str],
        scenario_count: int,
    ) -> str:
        """Emit run.created event."""
        event_id = generate_event_id(
            EventType.RUN_CREATED, tenant_id, project_id, run_id
        )

        payload = RunCreatedPayload(
            event_id=event_id,
            event_type=EventType.RUN_CREATED,
            timestamp=self._now_iso(),
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            name=name,
            created_by_user_id=created_by_user_id,
            scenario_count=scenario_count,
        )

        self._enqueue_for_webhooks(
            event_type=EventType.RUN_CREATED,
            tenant_id=tenant_id,
            project_id=project_id,
            event_id=event_id,
            payload=payload.to_dict(),
        )

        return event_id
