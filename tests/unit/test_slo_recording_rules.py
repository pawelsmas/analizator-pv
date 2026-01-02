"""
Unit tests for SLO recording rules structure (v3.9.0 PR1).

Tests that slo_recording_rules.yml has correct structure and expected rules.
Actual PromQL validation is done by promtool in CI.
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestSLORecordingRulesStructure:
    """Tests for SLO recording rules YAML structure."""

    @pytest.fixture
    def rules_content(self):
        """Load the recording rules file."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_rules_file_exists(self):
        """Verify recording rules file exists."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        assert rules_path.exists(), f"Recording rules file not found: {rules_path}"

    def test_has_groups_key(self, rules_content):
        """Verify rules have 'groups' key."""
        assert "groups" in rules_content
        assert isinstance(rules_content["groups"], list)
        assert len(rules_content["groups"]) > 0

    def test_availability_group_exists(self, rules_content):
        """Verify bess_sli_availability group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_sli_availability" in group_names

    def test_latency_group_exists(self, rules_content):
        """Verify bess_sli_latency group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_sli_latency" in group_names

    def test_compliance_group_exists(self, rules_content):
        """Verify bess_slo_compliance group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_slo_compliance" in group_names

    def test_error_budget_group_exists(self, rules_content):
        """Verify bess_error_budget group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_error_budget" in group_names

    def test_endpoint_availability_group_exists(self, rules_content):
        """Verify bess_endpoint_availability group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_endpoint_availability" in group_names

    def test_critical_endpoints_group_exists(self, rules_content):
        """Verify bess_critical_endpoints group exists."""
        group_names = [g["name"] for g in rules_content["groups"]]
        assert "bess_critical_endpoints" in group_names


class TestAvailabilityRules:
    """Tests for availability SLI rules."""

    @pytest.fixture
    def availability_rules(self):
        """Get rules from availability group."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        for group in content["groups"]:
            if group["name"] == "bess_sli_availability":
                return group["rules"]
        return []

    def test_ratio5m_rule_exists(self, availability_rules):
        """Verify 5-minute availability ratio rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:availability:ratio5m" in rule_names

    def test_ratio1h_rule_exists(self, availability_rules):
        """Verify 1-hour availability ratio rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:availability:ratio1h" in rule_names

    def test_ratio6h_rule_exists(self, availability_rules):
        """Verify 6-hour availability ratio rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:availability:ratio6h" in rule_names

    def test_ratio24h_rule_exists(self, availability_rules):
        """Verify 24-hour availability ratio rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:availability:ratio24h" in rule_names

    def test_ratio30d_rule_exists(self, availability_rules):
        """Verify 30-day availability ratio rule exists (SLO window)."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:availability:ratio30d" in rule_names

    def test_requests_total_rule_exists(self, availability_rules):
        """Verify total requests rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:requests:total5m" in rule_names

    def test_errors_total_rule_exists(self, availability_rules):
        """Verify errors total rule exists."""
        rule_names = [r["record"] for r in availability_rules]
        assert "bess:sli:errors:total5m" in rule_names


class TestLatencyRules:
    """Tests for latency SLI rules."""

    @pytest.fixture
    def latency_rules(self):
        """Get rules from latency group."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        for group in content["groups"]:
            if group["name"] == "bess_sli_latency":
                return group["rules"]
        return []

    def test_p50_5m_rule_exists(self, latency_rules):
        """Verify p50 latency rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p50_5m" in rule_names

    def test_p95_5m_rule_exists(self, latency_rules):
        """Verify p95 latency rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p95_5m" in rule_names

    def test_p99_5m_rule_exists(self, latency_rules):
        """Verify p99 latency rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p99_5m" in rule_names

    def test_p95_1h_rule_exists(self, latency_rules):
        """Verify p95 1h latency rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p95_1h" in rule_names

    def test_p95_24h_rule_exists(self, latency_rules):
        """Verify p95 24h latency rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p95_24h" in rule_names

    def test_p95_30d_rule_exists(self, latency_rules):
        """Verify p95 30d latency rule exists (SLO window)."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:p95_30d" in rule_names

    def test_within_target_rule_exists(self, latency_rules):
        """Verify latency within target rule exists."""
        rule_names = [r["record"] for r in latency_rules]
        assert "bess:sli:latency:within_target_5m" in rule_names


class TestComplianceRules:
    """Tests for SLO compliance rules."""

    @pytest.fixture
    def compliance_rules(self):
        """Get rules from compliance group."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        for group in content["groups"]:
            if group["name"] == "bess_slo_compliance":
                return group["rules"]
        return []

    def test_availability_target_rule_exists(self, compliance_rules):
        """Verify availability target rule exists."""
        rule_names = [r["record"] for r in compliance_rules]
        assert "bess:slo:availability:target" in rule_names

    def test_latency_target_rule_exists(self, compliance_rules):
        """Verify latency target rule exists."""
        rule_names = [r["record"] for r in compliance_rules]
        assert "bess:slo:latency:target_seconds" in rule_names

    def test_availability_compliant_rule_exists(self, compliance_rules):
        """Verify availability compliant rule exists."""
        rule_names = [r["record"] for r in compliance_rules]
        assert "bess:slo:availability:compliant" in rule_names

    def test_latency_compliant_rule_exists(self, compliance_rules):
        """Verify latency compliant rule exists."""
        rule_names = [r["record"] for r in compliance_rules]
        assert "bess:slo:latency:compliant" in rule_names

    def test_overall_compliant_rule_exists(self, compliance_rules):
        """Verify overall compliant rule exists."""
        rule_names = [r["record"] for r in compliance_rules]
        assert "bess:slo:overall:compliant" in rule_names

    def test_availability_target_is_995(self, compliance_rules):
        """Verify availability target is 99.5%."""
        for rule in compliance_rules:
            if rule["record"] == "bess:slo:availability:target":
                # YAML may parse as float directly
                expr = rule["expr"]
                if isinstance(expr, (int, float)):
                    assert expr == 0.995
                else:
                    assert expr.strip() == "0.995"
                return
        pytest.fail("Availability target rule not found")

    def test_latency_target_is_2_seconds(self, compliance_rules):
        """Verify latency target is 2 seconds."""
        for rule in compliance_rules:
            if rule["record"] == "bess:slo:latency:target_seconds":
                # YAML may parse as int directly
                expr = rule["expr"]
                if isinstance(expr, (int, float)):
                    assert expr == 2
                else:
                    assert expr.strip() == "2"
                return
        pytest.fail("Latency target rule not found")


class TestErrorBudgetRules:
    """Tests for error budget rules."""

    @pytest.fixture
    def budget_rules(self):
        """Get rules from error budget group."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        for group in content["groups"]:
            if group["name"] == "bess_error_budget":
                return group["rules"]
        return []

    def test_total_budget_rule_exists(self, budget_rules):
        """Verify total budget rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:total" in rule_names

    def test_consumed_ratio_rule_exists(self, budget_rules):
        """Verify consumed ratio rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:consumed_ratio" in rule_names

    def test_remaining_ratio_rule_exists(self, budget_rules):
        """Verify remaining ratio rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:remaining_ratio" in rule_names

    def test_remaining_pct_rule_exists(self, budget_rules):
        """Verify remaining percentage rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:remaining_pct" in rule_names

    def test_burn_rate_1h_rule_exists(self, budget_rules):
        """Verify 1h burn rate rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:burn_rate_1h" in rule_names

    def test_burn_rate_6h_rule_exists(self, budget_rules):
        """Verify 6h burn rate rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:burn_rate_6h" in rule_names

    def test_burn_rate_24h_rule_exists(self, budget_rules):
        """Verify 24h burn rate rule exists."""
        rule_names = [r["record"] for r in budget_rules]
        assert "bess:error_budget:burn_rate_24h" in rule_names

    def test_error_budget_is_005(self, budget_rules):
        """Verify error budget is 0.5%."""
        for rule in budget_rules:
            if rule["record"] == "bess:error_budget:total":
                # YAML may parse as float directly
                expr = rule["expr"]
                if isinstance(expr, (int, float)):
                    assert expr == 0.005
                else:
                    assert expr.strip() == "0.005"
                return
        pytest.fail("Error budget total rule not found")


class TestCriticalEndpointRules:
    """Tests for critical endpoint rules."""

    @pytest.fixture
    def critical_rules(self):
        """Get rules from critical endpoints group."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        for group in content["groups"]:
            if group["name"] == "bess_critical_endpoints":
                return group["rules"]
        return []

    def test_sizing_availability_rule_exists(self, critical_rules):
        """Verify sizing endpoint availability rule exists."""
        rule_names = [r["record"] for r in critical_rules]
        assert "bess:sizing:availability:ratio5m" in rule_names

    def test_sizing_latency_rule_exists(self, critical_rules):
        """Verify sizing endpoint latency rule exists."""
        rule_names = [r["record"] for r in critical_rules]
        assert "bess:sizing:latency:p95_5m" in rule_names

    def test_validation_availability_rule_exists(self, critical_rules):
        """Verify validation endpoint availability rule exists."""
        rule_names = [r["record"] for r in critical_rules]
        assert "bess:validation:availability:ratio5m" in rule_names

    def test_jobs_availability_rule_exists(self, critical_rules):
        """Verify jobs endpoint availability rule exists."""
        rule_names = [r["record"] for r in critical_rules]
        assert "bess:jobs:availability:ratio5m" in rule_names


class TestRuleIntervals:
    """Tests for rule evaluation intervals."""

    @pytest.fixture
    def rules_content(self):
        """Load the recording rules file."""
        rules_path = PROJECT_ROOT / "monitoring" / "prometheus" / "slo_recording_rules.yml"
        with open(rules_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_availability_group_interval(self, rules_content):
        """Verify availability group has 1m interval."""
        for group in rules_content["groups"]:
            if group["name"] == "bess_sli_availability":
                assert group.get("interval") == "1m"
                return
        pytest.fail("Availability group not found")

    def test_latency_group_interval(self, rules_content):
        """Verify latency group has 1m interval."""
        for group in rules_content["groups"]:
            if group["name"] == "bess_sli_latency":
                assert group.get("interval") == "1m"
                return
        pytest.fail("Latency group not found")

    def test_compliance_group_interval(self, rules_content):
        """Verify compliance group has 1m interval."""
        for group in rules_content["groups"]:
            if group["name"] == "bess_slo_compliance":
                assert group.get("interval") == "1m"
                return
        pytest.fail("Compliance group not found")

    def test_endpoint_group_interval(self, rules_content):
        """Verify endpoint availability group has 5m interval."""
        for group in rules_content["groups"]:
            if group["name"] == "bess_endpoint_availability":
                assert group.get("interval") == "5m"
                return
        pytest.fail("Endpoint availability group not found")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
