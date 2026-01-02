"""
Unit tests for quota documentation.

Tests verify:
- Documentation files exist
- Key sections are present
- Examples are included
"""

import os
import pytest


DOCS_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'docs'
)


class TestQuotasDoc:
    """Tests for QUOTAS.md documentation."""

    def test_file_exists(self):
        """QUOTAS.md should exist."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        assert os.path.exists(path)

    def test_has_overview_section(self):
        """Should have Overview section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Overview' in content

    def test_has_plans_section(self):
        """Should have Plans section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Plans' in content

    def test_has_api_endpoints_section(self):
        """Should have API Endpoints section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## API Endpoints' in content

    def test_has_quota_enforcement_section(self):
        """Should have Quota Enforcement section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Quota Enforcement' in content

    def test_has_429_response_example(self):
        """Should have 429 response example."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'QUOTA_EXCEEDED' in content
        assert '429' in content

    def test_has_project_overrides_section(self):
        """Should have Project Overrides section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Project Overrides' in content

    def test_has_usage_tracking_section(self):
        """Should have Usage Tracking section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Usage Tracking' in content

    def test_has_ui_components_section(self):
        """Should have UI Components section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## UI Components' in content

    def test_has_prometheus_metrics_section(self):
        """Should have Prometheus Metrics section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Prometheus Metrics' in content

    def test_has_migration_section(self):
        """Should have Migration section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Migration' in content

    def test_has_runbook_section(self):
        """Should have Runbook section."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Runbook' in content

    def test_documents_plan_table(self):
        """Should document plan limits table."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'free' in content
        assert 'pro' in content
        assert 'enterprise' in content
        assert 'jobs_per_day' in content

    def test_documents_zero_means_unlimited(self):
        """Should document that 0 means unlimited."""
        path = os.path.join(DOCS_PATH, 'QUOTAS.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'unlimited' in content.lower()
        assert '0' in content


class TestRunbookDoc:
    """Tests for QUOTA_RUNBOOK.md documentation."""

    def test_file_exists(self):
        """QUOTA_RUNBOOK.md should exist."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        assert os.path.exists(path)

    def test_has_quick_reference(self):
        """Should have Quick Reference section."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Quick Reference' in content

    def test_has_procedures_section(self):
        """Should have Procedures section."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Procedures' in content

    def test_has_investigate_exceeded_procedure(self):
        """Should have investigation procedure."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Investigate Quota Exceeded' in content

    def test_has_add_override_procedure(self):
        """Should have add override procedure."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Add Project Override' in content

    def test_has_change_plan_procedure(self):
        """Should have change plan procedure."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Change Tenant Plan' in content

    def test_has_emergency_procedure(self):
        """Should have emergency disable procedure."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Emergency' in content
        assert 'Disable Quota Enforcement' in content

    def test_has_promql_examples(self):
        """Should have PromQL examples."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'promql' in content.lower() or 'bess_quota' in content

    def test_has_api_curl_examples(self):
        """Should have curl API examples."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'curl' in content

    def test_has_monitoring_dashboard(self):
        """Should have Monitoring Dashboard section."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Monitoring Dashboard' in content

    def test_has_escalation_section(self):
        """Should have Escalation section."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Escalation' in content

    def test_has_related_documentation(self):
        """Should have Related Documentation section."""
        path = os.path.join(DOCS_PATH, 'runbooks', 'QUOTA_RUNBOOK.md')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '## Related Documentation' in content
        assert 'QUOTAS.md' in content

