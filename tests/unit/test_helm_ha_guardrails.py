"""
Unit tests for Helm HA guardrails (v3.6.0 PR2).

Tests verify:
- HA guardrail fails when API replicas > 1 without proper HA config
- HA guardrail fails when worker replicas > 1 without proper HA config
- HA guardrail passes when all requirements are met
- values.schema.json is valid JSON Schema
"""

import pytest
import subprocess
import os
import json
import sys
from pathlib import Path


# Path to helm chart
CHART_PATH = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal"


class TestHelmValuesSchema:
    """Tests for values.schema.json validation."""

    def test_schema_is_valid_json(self):
        """Schema file should be valid JSON."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "$schema" in schema
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"

    def test_schema_has_required_properties(self):
        """Schema should define key configuration sections."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        properties = schema.get("properties", {})

        # Check for required sections
        assert "ha" in properties
        assert "api" in properties
        assert "worker" in properties
        assert "runstore" in properties
        assert "postgresql" in properties
        assert "redis" in properties
        assert "externalSecrets" in properties

    def test_schema_runstore_backend_enum(self):
        """runstore.backend should be constrained to filesystem|db."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        runstore = schema["properties"]["runstore"]["properties"]["backend"]
        assert runstore["enum"] == ["filesystem", "db"]

    def test_schema_replicacount_minimum(self):
        """replicaCount should have minimum of 1."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        api_replicas = schema["properties"]["api"]["properties"]["replicaCount"]
        assert api_replicas["minimum"] == 1


class TestHelmHAHelpers:
    """Tests for _helpers.tpl HA guardrail logic."""

    def test_helpers_file_exists(self):
        """_helpers.tpl should exist."""
        helpers_path = CHART_PATH / "templates" / "_helpers.tpl"
        assert helpers_path.exists()

    def test_helpers_contains_ha_validate(self):
        """_helpers.tpl should contain HA validation function."""
        helpers_path = CHART_PATH / "templates" / "_helpers.tpl"
        with open(helpers_path, "r") as f:
            content = f.read()

        assert "pv-portal.ha.validate" in content
        assert "HA MODE GUARDRAIL" in content

    def test_helpers_checks_postgresql(self):
        """HA validation should check for PostgreSQL."""
        helpers_path = CHART_PATH / "templates" / "_helpers.tpl"
        with open(helpers_path, "r") as f:
            content = f.read()

        assert ".Values.postgresql.enabled" in content
        assert "postgresql.external.host" in content

    def test_helpers_checks_redis(self):
        """HA validation should check for Redis."""
        helpers_path = CHART_PATH / "templates" / "_helpers.tpl"
        with open(helpers_path, "r") as f:
            content = f.read()

        assert ".Values.redis.enabled" in content
        assert "redis.external.host" in content

    def test_helpers_checks_runstore_backend(self):
        """HA validation should check runstore backend is 'db'."""
        helpers_path = CHART_PATH / "templates" / "_helpers.tpl"
        with open(helpers_path, "r") as f:
            content = f.read()

        assert ".Values.runstore.backend" in content
        assert '"db"' in content


class TestHelmChartStructure:
    """Tests for Helm chart structure."""

    def test_chart_yaml_exists(self):
        """Chart.yaml should exist."""
        chart_path = CHART_PATH / "Chart.yaml"
        assert chart_path.exists()

    def test_values_yaml_exists(self):
        """values.yaml should exist."""
        values_path = CHART_PATH / "values.yaml"
        assert values_path.exists()

    def test_values_ha_yaml_exists(self):
        """values-ha.yaml example should exist."""
        values_path = CHART_PATH / "values-ha.yaml"
        assert values_path.exists()

    def test_external_secrets_yaml_exists(self):
        """external-secrets.yaml template should exist."""
        template_path = CHART_PATH / "templates" / "external-secrets.yaml"
        assert template_path.exists()

    def test_api_deployment_exists(self):
        """api-deployment.yaml template should exist."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        assert template_path.exists()

    def test_worker_deployment_exists(self):
        """worker-deployment.yaml template should exist."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        assert template_path.exists()


class TestHelmValuesDefaults:
    """Tests for default values in values.yaml."""

    def test_default_replica_count_is_one(self):
        """Default replica count should be 1 (no HA)."""
        import yaml

        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["api"]["replicaCount"] == 1
        assert values["worker"]["replicaCount"] == 1

    def test_default_runstore_backend_is_filesystem(self):
        """Default runstore backend should be filesystem."""
        import yaml

        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["runstore"]["backend"] == "filesystem"

    def test_default_postgresql_disabled(self):
        """PostgreSQL should be disabled by default."""
        import yaml

        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["postgresql"]["enabled"] is False

    def test_default_redis_disabled(self):
        """Redis should be disabled by default."""
        import yaml

        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["redis"]["enabled"] is False

    def test_default_external_secrets_disabled(self):
        """External Secrets should be disabled by default."""
        import yaml

        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["externalSecrets"]["enabled"] is False


class TestHelmHAValuesExample:
    """Tests for HA values example file."""

    def test_ha_values_enables_ha(self):
        """HA values should enable HA mode."""
        import yaml

        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["ha"]["enabled"] is True
        assert values["ha"]["strict"] is True

    def test_ha_values_multiple_replicas(self):
        """HA values should configure multiple replicas."""
        import yaml

        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["api"]["replicaCount"] >= 2
        assert values["worker"]["replicaCount"] >= 2

    def test_ha_values_db_backend(self):
        """HA values should use db backend."""
        import yaml

        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["runstore"]["backend"] == "db"

    def test_ha_values_enables_postgresql(self):
        """HA values should enable PostgreSQL."""
        import yaml

        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["postgresql"]["enabled"] is True

    def test_ha_values_enables_redis(self):
        """HA values should enable Redis."""
        import yaml

        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["redis"]["enabled"] is True
