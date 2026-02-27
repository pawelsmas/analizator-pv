"""
Webhook hooks for emitting events at key points in the application (v4.1.0).

This module provides hook functions that should be called when significant
events occur. Each hook emits the appropriate webhook event if webhooks
are configured.

Usage:
    from webhook_hooks import WebhookHooks

    # Initialize once (e.g., in app startup)
    hooks = WebhookHooks()

    # Call when job completes
    hooks.on_job_completed(job)

    # Call when report is generated
    hooks.on_report_generated(report, run_id)
"""

import logging
from typing import Any, Dict, Optional

from webhook_events import WebhookEventEmitter
from webhook_store import WebhookStore


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Global singleton
# -------------------------------------------------------------------------

_hooks_instance: Optional["WebhookHooks"] = None


def get_webhook_hooks() -> "WebhookHooks":
    """Get or create the global WebhookHooks instance."""
    global _hooks_instance
    if _hooks_instance is None:
        _hooks_instance = WebhookHooks()
    return _hooks_instance


def set_webhook_hooks(hooks: "WebhookHooks"):
    """Set the global WebhookHooks instance (for testing)."""
    global _hooks_instance
    _hooks_instance = hooks


# -------------------------------------------------------------------------
# WebhookHooks class
# -------------------------------------------------------------------------

class WebhookHooks:
    """
    Webhook hooks for emitting events.

    This class wraps WebhookEventEmitter and provides convenient methods
    for emitting events from different parts of the application.
    """

    def __init__(self, webhook_store: Optional[WebhookStore] = None):
        """
        Initialize WebhookHooks.

        Args:
            webhook_store: Optional WebhookStore instance. If not provided,
                          creates a new one.
        """
        self._store = webhook_store or WebhookStore()
        self._emitter = WebhookEventEmitter(self._store)
        self._enabled = True

    def disable(self):
        """Disable webhook emission (for testing)."""
        self._enabled = False

    def enable(self):
        """Enable webhook emission."""
        self._enabled = True

    # -------------------------------------------------------------------------
    # Job Events
    # -------------------------------------------------------------------------

    def on_job_completed(
        self,
        job: Dict[str, Any],
        duration_ms: Optional[int] = None,
    ) -> Optional[str]:
        """
        Emit event when a job completes (succeeded or failed).

        Args:
            job: Job dictionary with keys: job_id, tenant_id, project_id,
                 job_type, run_id, status, result, message
            duration_ms: Optional duration override

        Returns:
            Event ID if emitted, None otherwise
        """
        if not self._enabled:
            return None

        try:
            tenant_id = job.get("tenant_id", "default")
            project_id = job.get("project_id")
            job_id = job.get("job_id", "")
            job_type = job.get("job_type", "sizing")
            run_id = job.get("run_id")
            status = job.get("status", "")

            # Calculate duration if not provided
            if duration_ms is None:
                created_at = job.get("created_at")
                updated_at = job.get("updated_at")
                if created_at and updated_at:
                    from datetime import datetime
                    try:
                        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        end = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        duration_ms = int((end - start).total_seconds() * 1000)
                    except (ValueError, TypeError):
                        duration_ms = 0
                else:
                    duration_ms = 0

            if status == "done":
                # Extract summary from result
                result = job.get("result", {})
                summary = self._extract_job_summary(result, job_type)

                return self._emitter.emit_job_succeeded(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    job_id=job_id,
                    job_type=job_type,
                    run_id=run_id,
                    duration_ms=duration_ms,
                    summary=summary,
                )

            elif status == "failed":
                message = job.get("message", "Unknown error")
                error_code = self._extract_error_code(message)

                return self._emitter.emit_job_failed(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    job_id=job_id,
                    job_type=job_type,
                    run_id=run_id,
                    error_code=error_code,
                    error_message=message,
                    duration_ms=duration_ms,
                )

        except Exception as e:
            logger.warning(f"Failed to emit job webhook: {e}")
            return None

        return None

    def _extract_job_summary(
        self, result: Dict[str, Any], job_type: str
    ) -> Dict[str, Any]:
        """Extract summary fields from job result."""
        summary = {}

        if job_type in ("sizing", "validation"):
            # Extract key KPIs
            kpis = result.get("recommended_variant", {})
            if "npv_pln" in kpis:
                summary["npv_pln"] = kpis["npv_pln"]
            if "capex_pln" in kpis:
                summary["capex_pln"] = kpis["capex_pln"]
            if "payback_years" in kpis:
                summary["payback_years"] = kpis["payback_years"]
            if "variant_name" in kpis:
                summary["variant_name"] = kpis["variant_name"]

            # Count variants
            variants = result.get("variants", [])
            summary["variant_count"] = len(variants)

        elif job_type == "sizing-batch":
            # Batch job summary
            items = result.get("items", [])
            summary["total_items"] = len(items)
            summary["succeeded"] = sum(1 for i in items if i.get("status") == "OK")
            summary["failed"] = sum(1 for i in items if i.get("status") == "FAILED")

            # Portfolio summary if present
            portfolio = result.get("portfolio_summary", {})
            if portfolio:
                summary["total_npv_pln"] = portfolio.get("total_npv_pln")
                summary["total_capex_pln"] = portfolio.get("total_capex_pln")

        elif job_type == "validate-pack":
            # Pack validation summary
            summary["pack_name"] = result.get("pack", "")
            summary["passed"] = result.get("passed_count", 0)
            summary["failed"] = result.get("failed_count", 0)
            summary["total"] = result.get("total_count", 0)

        return summary

    def _extract_error_code(self, message: str) -> str:
        """Extract error code from error message."""
        # Common error patterns
        if "timeout" in message.lower():
            return "TIMEOUT"
        if "solver" in message.lower():
            return "SOLVER_ERROR"
        if "validation" in message.lower():
            return "VALIDATION_ERROR"
        if "not found" in message.lower():
            return "NOT_FOUND"
        if "permission" in message.lower() or "forbidden" in message.lower():
            return "FORBIDDEN"
        return "INTERNAL_ERROR"

    # -------------------------------------------------------------------------
    # Report Events
    # -------------------------------------------------------------------------

    def on_report_generated(
        self,
        tenant_id: str,
        project_id: Optional[str],
        report_id: str,
        run_id: str,
        format: str,
        size_bytes: int,
        download_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Emit event when a report is generated.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier (optional)
            report_id: Report identifier
            run_id: Associated run ID
            format: Report format (pdf, csv, xlsx)
            size_bytes: File size in bytes
            download_url: Optional download URL

        Returns:
            Event ID if emitted, None otherwise
        """
        if not self._enabled:
            return None

        try:
            return self._emitter.emit_report_generated(
                tenant_id=tenant_id,
                project_id=project_id,
                report_id=report_id,
                run_id=run_id,
                format=format,
                size_bytes=size_bytes,
                download_url=download_url,
            )
        except Exception as e:
            logger.warning(f"Failed to emit report webhook: {e}")
            return None

    # -------------------------------------------------------------------------
    # Share Events
    # -------------------------------------------------------------------------

    def on_share_accessed(
        self,
        tenant_id: str,
        project_id: Optional[str],
        share_id: str,
        run_id: str,
        access_type: str,
        accessed_by_ip: Optional[str] = None,
    ) -> Optional[str]:
        """
        Emit event when a share is accessed.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier (optional)
            share_id: Share identifier
            run_id: Associated run ID
            access_type: Type of access (view, download)
            accessed_by_ip: IP address (anonymized or omitted)

        Returns:
            Event ID if emitted, None otherwise
        """
        if not self._enabled:
            return None

        try:
            return self._emitter.emit_share_accessed(
                tenant_id=tenant_id,
                project_id=project_id,
                share_id=share_id,
                run_id=run_id,
                access_type=access_type,
                accessed_by_ip=accessed_by_ip,
            )
        except Exception as e:
            logger.warning(f"Failed to emit share webhook: {e}")
            return None

    # -------------------------------------------------------------------------
    # Quota Events
    # -------------------------------------------------------------------------

    def on_quota_exceeded(
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
        Emit event when a quota is exceeded.

        Note: This event is deduplicated to send once per day per quota.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier (optional)
            quota_name: Quota name (e.g., jobs_per_day)
            quota_limit: Maximum allowed
            current_usage: Current usage value
            period: Period type (daily, monthly)
            reset_at: ISO timestamp when quota resets

        Returns:
            Event ID if emitted, None if deduplicated or failed
        """
        if not self._enabled:
            return None

        try:
            return self._emitter.emit_quota_exceeded(
                tenant_id=tenant_id,
                project_id=project_id,
                quota_name=quota_name,
                quota_limit=quota_limit,
                current_usage=current_usage,
                period=period,
                reset_at=reset_at,
            )
        except Exception as e:
            logger.warning(f"Failed to emit quota webhook: {e}")
            return None

    # -------------------------------------------------------------------------
    # Run Events
    # -------------------------------------------------------------------------

    def on_run_created(
        self,
        tenant_id: str,
        project_id: Optional[str],
        run_id: str,
        name: str,
        created_by_user_id: Optional[str],
        scenario_count: int,
    ) -> Optional[str]:
        """
        Emit event when a run is created.

        Args:
            tenant_id: Tenant identifier
            project_id: Project identifier (optional)
            run_id: Run identifier
            name: Run name
            created_by_user_id: Creator's user ID
            scenario_count: Number of scenarios

        Returns:
            Event ID if emitted, None otherwise
        """
        if not self._enabled:
            return None

        try:
            return self._emitter.emit_run_created(
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
                name=name,
                created_by_user_id=created_by_user_id,
                scenario_count=scenario_count,
            )
        except Exception as e:
            logger.warning(f"Failed to emit run webhook: {e}")
            return None
