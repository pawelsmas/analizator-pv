"""
Unit tests for Helm K8s security hardening (v3.6.0 PR3).

Tests verify:
- securityContext is configured for API and Worker
- readOnlyRootFilesystem is enabled by default
- Startup/liveness/readiness probes are configured
- terminationGracePeriodSeconds is set for worker
- Schema includes security context definitions
"""

import pytest
import json
import yaml
from pathlib import Path


# Path to helm chart
CHART_PATH = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal"


class TestSecurityContextDefaults:
    """Tests for default security context values."""

    def test_api_has_pod_security_context(self):
        """API should have podSecurityContext configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "podSecurityContext" in values["api"]
        psc = values["api"]["podSecurityContext"]
        assert psc["runAsNonRoot"] is True
        assert psc["runAsUser"] == 1000
        assert psc["runAsGroup"] == 1000
        assert psc["fsGroup"] == 1000

    def test_api_has_container_security_context(self):
        """API should have container securityContext configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "securityContext" in values["api"]
        sc = values["api"]["securityContext"]
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["readOnlyRootFilesystem"] is True
        assert "ALL" in sc["capabilities"]["drop"]

    def test_worker_has_pod_security_context(self):
        """Worker should have podSecurityContext configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "podSecurityContext" in values["worker"]
        psc = values["worker"]["podSecurityContext"]
        assert psc["runAsNonRoot"] is True
        assert psc["runAsUser"] == 1000

    def test_worker_has_container_security_context(self):
        """Worker should have container securityContext configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "securityContext" in values["worker"]
        sc = values["worker"]["securityContext"]
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["readOnlyRootFilesystem"] is True


class TestProbesConfiguration:
    """Tests for health probe configuration."""

    def test_api_has_startup_probe(self):
        """API should have startup probe configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "startupProbe" in values["api"]
        probe = values["api"]["startupProbe"]
        assert "httpGet" in probe
        assert probe["httpGet"]["path"] == "/health/live"
        assert probe["failureThreshold"] >= 10  # Allow slow startup

    def test_api_has_liveness_probe(self):
        """API should have liveness probe configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "livenessProbe" in values["api"]
        probe = values["api"]["livenessProbe"]
        assert "httpGet" in probe
        assert probe["httpGet"]["path"] == "/health/live"

    def test_api_has_readiness_probe(self):
        """API should have readiness probe configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "readinessProbe" in values["api"]
        probe = values["api"]["readinessProbe"]
        assert "httpGet" in probe
        assert probe["httpGet"]["path"] == "/health/ready"


class TestGracefulShutdown:
    """Tests for graceful shutdown configuration."""

    def test_worker_has_termination_grace_period(self):
        """Worker should have terminationGracePeriodSeconds configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "terminationGracePeriodSeconds" in values["worker"]
        # Should be reasonable (30-120 seconds)
        grace = values["worker"]["terminationGracePeriodSeconds"]
        assert grace >= 30
        assert grace <= 120


class TestDeploymentTemplates:
    """Tests for deployment template security features."""

    def test_api_deployment_has_security_context(self):
        """API deployment template should reference securityContext."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.api.podSecurityContext" in content
        assert ".Values.api.securityContext" in content

    def test_api_deployment_has_startup_probe(self):
        """API deployment template should reference startupProbe."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "startupProbe" in content

    def test_api_deployment_has_emptydir_volumes(self):
        """API deployment should mount emptyDir for readOnlyRootFilesystem."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "emptyDir" in content
        assert "/tmp" in content or "tmp" in content

    def test_worker_deployment_has_security_context(self):
        """Worker deployment template should reference securityContext."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.worker.podSecurityContext" in content
        assert ".Values.worker.securityContext" in content

    def test_worker_deployment_has_termination_grace(self):
        """Worker deployment should have terminationGracePeriodSeconds."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "terminationGracePeriodSeconds" in content
        assert "SHUTDOWN_GRACE_SECONDS" in content


class TestSchemaSecurityDefinitions:
    """Tests for security-related schema definitions."""

    def test_schema_has_pod_security_context_definition(self):
        """Schema should define podSecurityContext."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "podSecurityContext" in schema["definitions"]
        psc = schema["definitions"]["podSecurityContext"]
        assert psc["properties"]["runAsNonRoot"]["type"] == "boolean"
        assert psc["properties"]["runAsUser"]["type"] == "integer"

    def test_schema_has_container_security_context_definition(self):
        """Schema should define containerSecurityContext."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "containerSecurityContext" in schema["definitions"]
        csc = schema["definitions"]["containerSecurityContext"]
        assert "readOnlyRootFilesystem" in csc["properties"]
        assert "allowPrivilegeEscalation" in csc["properties"]
        assert "capabilities" in csc["properties"]

    def test_schema_has_probe_definition(self):
        """Schema should define probe configuration."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "probe" in schema["definitions"]
        probe = schema["definitions"]["probe"]
        assert "httpGet" in probe["properties"]
        assert "initialDelaySeconds" in probe["properties"]
        assert "failureThreshold" in probe["properties"]

    def test_schema_api_has_security_references(self):
        """API schema should reference security context definitions."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        api_props = schema["properties"]["api"]["properties"]
        assert "podSecurityContext" in api_props
        assert "securityContext" in api_props
        assert "startupProbe" in api_props

    def test_schema_worker_has_termination_grace(self):
        """Worker schema should have terminationGracePeriodSeconds."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        worker_props = schema["properties"]["worker"]["properties"]
        assert "terminationGracePeriodSeconds" in worker_props
        tgp = worker_props["terminationGracePeriodSeconds"]
        assert tgp["minimum"] == 0
        assert tgp["maximum"] == 600
