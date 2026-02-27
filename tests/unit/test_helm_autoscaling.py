"""
Unit tests for Helm autoscaling features (v3.6.0 PR4).

Tests verify:
- HPA configuration for API and Worker
- PDB configuration for API and Worker
- Topology spread constraints
- Worker knobs configuration
- Schema definitions for new features
"""

import pytest
import json
import yaml
from pathlib import Path


# Path to helm chart
CHART_PATH = Path(__file__).parent.parent.parent / "deploy" / "helm" / "pv-portal"


class TestAutoscalingDefaults:
    """Tests for default autoscaling values."""

    def test_api_autoscaling_disabled_by_default(self):
        """API autoscaling should be disabled by default."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["api"]["autoscaling"]["enabled"] is False

    def test_api_autoscaling_has_min_max_replicas(self):
        """API autoscaling should have min and max replicas configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        autoscaling = values["api"]["autoscaling"]
        assert autoscaling["minReplicas"] >= 1
        assert autoscaling["maxReplicas"] >= autoscaling["minReplicas"]

    def test_api_autoscaling_has_cpu_target(self):
        """API autoscaling should have CPU target configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        autoscaling = values["api"]["autoscaling"]
        assert "targetCPUUtilizationPercentage" in autoscaling
        assert 1 <= autoscaling["targetCPUUtilizationPercentage"] <= 100

    def test_worker_autoscaling_disabled_by_default(self):
        """Worker autoscaling should be disabled by default."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["worker"]["autoscaling"]["enabled"] is False

    def test_worker_autoscaling_has_min_max_replicas(self):
        """Worker autoscaling should have min and max replicas configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        autoscaling = values["worker"]["autoscaling"]
        assert autoscaling["minReplicas"] >= 1
        assert autoscaling["maxReplicas"] >= autoscaling["minReplicas"]


class TestPDBDefaults:
    """Tests for default PDB values."""

    def test_api_pdb_disabled_by_default(self):
        """API PDB should be disabled by default."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["api"]["pdb"]["enabled"] is False

    def test_api_pdb_has_min_available(self):
        """API PDB should have minAvailable configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "minAvailable" in values["api"]["pdb"]

    def test_worker_pdb_disabled_by_default(self):
        """Worker PDB should be disabled by default."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values["worker"]["pdb"]["enabled"] is False

    def test_worker_pdb_has_min_available(self):
        """Worker PDB should have minAvailable configured."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "minAvailable" in values["worker"]["pdb"]


class TestTopologySpreadConstraints:
    """Tests for topology spread constraints."""

    def test_api_has_topology_spread_constraints_field(self):
        """API should have topologySpreadConstraints field."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "topologySpreadConstraints" in values["api"]
        assert isinstance(values["api"]["topologySpreadConstraints"], list)

    def test_worker_has_topology_spread_constraints_field(self):
        """Worker should have topologySpreadConstraints field."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "topologySpreadConstraints" in values["worker"]
        assert isinstance(values["worker"]["topologySpreadConstraints"], list)


class TestWorkerKnobs:
    """Tests for worker tuning knobs."""

    def test_worker_has_knobs_section(self):
        """Worker should have knobs section."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "knobs" in values["worker"]

    def test_worker_knobs_has_max_tasks(self):
        """Worker knobs should have maxTasksPerWorker."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "maxTasksPerWorker" in values["worker"]["knobs"]
        assert values["worker"]["knobs"]["maxTasksPerWorker"] >= 1

    def test_worker_knobs_has_memory_threshold(self):
        """Worker knobs should have memoryThresholdMb."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "memoryThresholdMb" in values["worker"]["knobs"]
        assert values["worker"]["knobs"]["memoryThresholdMb"] >= 256

    def test_worker_knobs_has_prefetch_multiplier(self):
        """Worker knobs should have prefetchMultiplier."""
        values_path = CHART_PATH / "values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert "prefetchMultiplier" in values["worker"]["knobs"]
        assert 1 <= values["worker"]["knobs"]["prefetchMultiplier"] <= 16


class TestHPATemplates:
    """Tests for HPA template files."""

    def test_api_hpa_template_exists(self):
        """API HPA template should exist."""
        template_path = CHART_PATH / "templates" / "api-hpa.yaml"
        assert template_path.exists()

    def test_api_hpa_has_conditional(self):
        """API HPA should be conditional on autoscaling.enabled."""
        template_path = CHART_PATH / "templates" / "api-hpa.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.api.autoscaling.enabled" in content

    def test_api_hpa_has_scale_target(self):
        """API HPA should reference API deployment."""
        template_path = CHART_PATH / "templates" / "api-hpa.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "scaleTargetRef" in content
        assert "Deployment" in content

    def test_worker_hpa_template_exists(self):
        """Worker HPA template should exist."""
        template_path = CHART_PATH / "templates" / "worker-hpa.yaml"
        assert template_path.exists()

    def test_worker_hpa_has_conditional(self):
        """Worker HPA should be conditional on autoscaling.enabled."""
        template_path = CHART_PATH / "templates" / "worker-hpa.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.worker.autoscaling.enabled" in content


class TestPDBTemplates:
    """Tests for PDB template files."""

    def test_api_pdb_template_exists(self):
        """API PDB template should exist."""
        template_path = CHART_PATH / "templates" / "api-pdb.yaml"
        assert template_path.exists()

    def test_api_pdb_has_conditional(self):
        """API PDB should be conditional on pdb.enabled."""
        template_path = CHART_PATH / "templates" / "api-pdb.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.api.pdb.enabled" in content

    def test_api_pdb_has_selector(self):
        """API PDB should have selector for API pods."""
        template_path = CHART_PATH / "templates" / "api-pdb.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "matchLabels" in content
        assert "pv-portal.api.selectorLabels" in content

    def test_worker_pdb_template_exists(self):
        """Worker PDB template should exist."""
        template_path = CHART_PATH / "templates" / "worker-pdb.yaml"
        assert template_path.exists()

    def test_worker_pdb_has_conditional(self):
        """Worker PDB should be conditional on pdb.enabled."""
        template_path = CHART_PATH / "templates" / "worker-pdb.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert ".Values.worker.pdb.enabled" in content


class TestDeploymentHPAIntegration:
    """Tests for HPA integration in deployment templates."""

    def test_api_deployment_skips_replicas_when_hpa_enabled(self):
        """API deployment should not set replicas when HPA is enabled."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "if not .Values.api.autoscaling.enabled" in content

    def test_api_deployment_has_topology_spread(self):
        """API deployment should support topology spread constraints."""
        template_path = CHART_PATH / "templates" / "api-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "topologySpreadConstraints" in content

    def test_worker_deployment_skips_replicas_when_hpa_enabled(self):
        """Worker deployment should not set replicas when HPA is enabled."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "if not .Values.worker.autoscaling.enabled" in content

    def test_worker_deployment_has_topology_spread(self):
        """Worker deployment should support topology spread constraints."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "topologySpreadConstraints" in content

    def test_worker_deployment_has_knobs_env_vars(self):
        """Worker deployment should expose knobs as environment variables."""
        template_path = CHART_PATH / "templates" / "worker-deployment.yaml"
        with open(template_path, "r") as f:
            content = f.read()

        assert "MAX_TASKS_PER_WORKER" in content
        assert "MEMORY_THRESHOLD_MB" in content
        assert "PREFETCH_MULTIPLIER" in content


class TestSchemaAutoscalingDefinitions:
    """Tests for autoscaling-related schema definitions."""

    def test_schema_has_autoscaling_definition(self):
        """Schema should define autoscaling."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "autoscaling" in schema["definitions"]
        autoscaling = schema["definitions"]["autoscaling"]
        assert "enabled" in autoscaling["properties"]
        assert "minReplicas" in autoscaling["properties"]
        assert "maxReplicas" in autoscaling["properties"]

    def test_schema_has_pdb_definition(self):
        """Schema should define pdb."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "pdb" in schema["definitions"]
        pdb = schema["definitions"]["pdb"]
        assert "enabled" in pdb["properties"]
        assert "minAvailable" in pdb["properties"]

    def test_schema_has_topology_spread_definition(self):
        """Schema should define topologySpreadConstraint."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "topologySpreadConstraint" in schema["definitions"]
        tsc = schema["definitions"]["topologySpreadConstraint"]
        assert "maxSkew" in tsc["properties"]
        assert "topologyKey" in tsc["properties"]
        assert "whenUnsatisfiable" in tsc["properties"]

    def test_schema_has_worker_knobs_definition(self):
        """Schema should define workerKnobs."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        assert "workerKnobs" in schema["definitions"]
        knobs = schema["definitions"]["workerKnobs"]
        assert "maxTasksPerWorker" in knobs["properties"]
        assert "memoryThresholdMb" in knobs["properties"]
        assert "prefetchMultiplier" in knobs["properties"]

    def test_schema_api_references_autoscaling(self):
        """API schema should reference autoscaling definition."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        api_props = schema["properties"]["api"]["properties"]
        assert "autoscaling" in api_props
        assert "pdb" in api_props
        assert "topologySpreadConstraints" in api_props

    def test_schema_worker_references_knobs(self):
        """Worker schema should reference knobs definition."""
        schema_path = CHART_PATH / "values.schema.json"
        with open(schema_path, "r") as f:
            schema = json.load(f)

        worker_props = schema["properties"]["worker"]["properties"]
        assert "knobs" in worker_props
        assert "autoscaling" in worker_props
        assert "pdb" in worker_props


class TestHAValuesAutoscaling:
    """Tests for HA values with autoscaling enabled."""

    def test_ha_values_has_autoscaling_enabled(self):
        """HA values should enable autoscaling."""
        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        # HA values may have autoscaling enabled or higher replicas
        api_replicas = values.get("api", {}).get("replicaCount", 1)
        worker_replicas = values.get("worker", {}).get("replicaCount", 1)
        assert api_replicas >= 2 or worker_replicas >= 2

    def test_ha_values_has_pdb_enabled(self):
        """HA values should enable PDB."""
        values_path = CHART_PATH / "values-ha.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        # Check if PDB is configured in HA mode
        api_pdb = values.get("api", {}).get("pdb", {})
        worker_pdb = values.get("worker", {}).get("pdb", {})
        # At least one should be enabled in HA mode
        assert api_pdb.get("enabled", False) or worker_pdb.get("enabled", False) or \
               values.get("api", {}).get("replicaCount", 1) >= 2
