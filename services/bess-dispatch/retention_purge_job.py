"""
Retention purge job module (v4.3.0 PR9).

Runs as a Kubernetes CronJob to execute scheduled retention purges.
Supports:
- Multi-tenant purge execution
- Dry-run mode for testing
- Slack notifications
- Prometheus metrics push
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from compliance_store import ComplianceStore
from retention_executor import (
    execute_retention,
    dry_run_retention,
    PurgeResult,
    MAX_DELETIONS_PER_RUN,
)
from retention_policy_helper import ResourceCategory

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("retention_purge_job")


def get_enabled_categories() -> list[ResourceCategory]:
    """Get enabled categories from environment variable."""
    categories_str = os.getenv("ENABLED_CATEGORIES", "")
    if not categories_str:
        return list(ResourceCategory)

    enabled = []
    for cat_name in categories_str.split(","):
        cat_name = cat_name.strip().upper()
        try:
            enabled.append(ResourceCategory[cat_name])
        except KeyError:
            logger.warning(f"Unknown category: {cat_name}")

    return enabled if enabled else list(ResourceCategory)


def send_slack_notification(
    webhook_url: str,
    result: PurgeResult,
    tenant_id: str,
    duration_seconds: float,
) -> bool:
    """Send Slack notification about purge completion."""
    try:
        emoji = ":white_check_mark:" if result.success else ":x:"
        mode = "DRY RUN" if result.mode == "dry_run" else "EXECUTE"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Retention Purge {mode} Complete",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Tenant:*\n{tenant_id}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{'Success' if result.success else 'Failed'}"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{duration_seconds:.1f}s"},
                    {"type": "mrkdwn", "text": f"*Mode:*\n{mode}"},
                ],
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Found:*\n{result.total_found}"},
                    {"type": "mrkdwn", "text": f"*To Delete:*\n{result.total_to_delete}"},
                    {"type": "mrkdwn", "text": f"*Deleted:*\n{result.total_deleted}"},
                    {"type": "mrkdwn", "text": f"*Skipped (held):*\n{result.total_skipped_held}"},
                ],
            },
        ]

        if result.hit_limit:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":warning: Hit deletion limit. More items pending.",
                    }
                ],
            })

        if result.error:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:*\n```{result.error}```",
                },
            })

        payload = json.dumps({"blocks": blocks}).encode("utf-8")

        request = Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=10) as response:
            return response.status == 200

    except (URLError, Exception) as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


def push_metrics_to_pushgateway(
    pushgateway_url: str,
    result: PurgeResult,
    tenant_id: str,
    job_name: str = "retention_purge",
) -> bool:
    """Push metrics to Prometheus Pushgateway."""
    try:
        # Format metrics in Prometheus exposition format
        metrics = [
            f'retention_purge_total_found{{tenant_id="{tenant_id}",mode="{result.mode}"}} {result.total_found}',
            f'retention_purge_total_to_delete{{tenant_id="{tenant_id}",mode="{result.mode}"}} {result.total_to_delete}',
            f'retention_purge_total_deleted{{tenant_id="{tenant_id}",mode="{result.mode}"}} {result.total_deleted}',
            f'retention_purge_total_skipped_held{{tenant_id="{tenant_id}",mode="{result.mode}"}} {result.total_skipped_held}',
            f'retention_purge_total_skipped_error{{tenant_id="{tenant_id}",mode="{result.mode}"}} {result.total_skipped_error}',
            f'retention_purge_success{{tenant_id="{tenant_id}",mode="{result.mode}"}} {1 if result.success else 0}',
            f'retention_purge_hit_limit{{tenant_id="{tenant_id}",mode="{result.mode}"}} {1 if result.hit_limit else 0}',
        ]

        # Add per-category metrics
        for cat_stats in result.categories:
            metrics.extend([
                f'retention_purge_category_found{{tenant_id="{tenant_id}",category="{cat_stats.category}"}} {cat_stats.total_found}',
                f'retention_purge_category_deleted{{tenant_id="{tenant_id}",category="{cat_stats.category}"}} {cat_stats.deleted}',
                f'retention_purge_category_skipped_held{{tenant_id="{tenant_id}",category="{cat_stats.category}"}} {cat_stats.skipped_held}',
            ])

        payload = "\n".join(metrics).encode("utf-8")
        url = f"{pushgateway_url}/metrics/job/{job_name}/tenant_id/{tenant_id}"

        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "text/plain"},
            method="POST",
        )

        with urlopen(request, timeout=10) as response:
            return response.status in (200, 202)

    except (URLError, Exception) as e:
        logger.error(f"Failed to push metrics to Pushgateway: {e}")
        return False


def run_purge_for_tenant(
    store: ComplianceStore,
    tenant_id: str,
    dry_run: bool = False,
    max_deletions: int = MAX_DELETIONS_PER_RUN,
    categories: Optional[list[ResourceCategory]] = None,
) -> PurgeResult:
    """Run retention purge for a single tenant."""
    start_time = datetime.now(timezone.utc)

    try:
        if dry_run:
            logger.info(f"Running dry-run retention for tenant: {tenant_id}")
            result = dry_run_retention(
                store,
                tenant_id=tenant_id,
                categories=categories,
            )
        else:
            logger.info(f"Executing retention purge for tenant: {tenant_id}")
            result = execute_retention(
                store,
                tenant_id=tenant_id,
                max_deletions=max_deletions or MAX_DELETIONS_PER_RUN,
                categories=categories,
            )

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"Purge completed for tenant {tenant_id}: "
            f"found={result.total_found}, deleted={result.total_deleted}, "
            f"skipped_held={result.total_skipped_held}, duration={duration:.1f}s"
        )

        return result

    except Exception as e:
        logger.error(f"Purge failed for tenant {tenant_id}: {e}")
        result = PurgeResult(
            mode="dry_run" if dry_run else "execute",
            tenant_id=tenant_id,
            started_at=start_time.isoformat(),
            success=False,
            error=str(e),
        )
        return result


def main():
    """Main entry point for retention purge job."""
    logger.info("=== Retention Purge Job Started ===")

    # Load configuration from environment
    db_path = os.getenv("DB_PATH", "/data/compliance.db")
    dry_run = os.getenv("DRY_RUN_MODE", "false").lower() == "true"
    max_deletions = int(os.getenv("MAX_DELETIONS_PER_RUN", "10000"))
    notify = os.getenv("NOTIFY_ON_COMPLETION", "false").lower() == "true"
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL", "")
    pushgateway_url = os.getenv("PROMETHEUS_PUSHGATEWAY_URL", "")

    categories = get_enabled_categories()

    logger.info(f"Configuration:")
    logger.info(f"  DB Path: {db_path}")
    logger.info(f"  Dry Run: {dry_run}")
    logger.info(f"  Max Deletions: {max_deletions}")
    logger.info(f"  Categories: {[c.value for c in categories]}")
    logger.info(f"  Notifications: {notify}")

    start_time = datetime.now(timezone.utc)
    total_deleted = 0
    total_found = 0
    failed_tenants = []

    try:
        # Initialize compliance store
        store = ComplianceStore(db_path=db_path)

        # Get all tenants with retention policies
        tenants = store.list_tenants_with_policies()
        logger.info(f"Found {len(tenants)} tenants with retention policies")

        for tenant_id in tenants:
            result = run_purge_for_tenant(
                store,
                tenant_id=tenant_id,
                dry_run=dry_run,
                max_deletions=max_deletions,
                categories=categories,
            )

            total_found += result.total_found
            total_deleted += result.total_deleted

            if not result.success:
                failed_tenants.append(tenant_id)

            # Send notifications
            if notify and slack_webhook:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                send_slack_notification(
                    slack_webhook,
                    result,
                    tenant_id,
                    duration,
                )

            # Push metrics
            if pushgateway_url:
                push_metrics_to_pushgateway(
                    pushgateway_url,
                    result,
                    tenant_id,
                )

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=== Retention Purge Job Completed ===")
        logger.info(f"  Total Tenants: {len(tenants)}")
        logger.info(f"  Total Found: {total_found}")
        logger.info(f"  Total Deleted: {total_deleted}")
        logger.info(f"  Failed Tenants: {len(failed_tenants)}")
        logger.info(f"  Duration: {duration:.1f}s")

        if failed_tenants:
            logger.error(f"Failed tenants: {failed_tenants}")
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Fatal error in retention purge job: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
