"""
Unit tests for kind HA configuration (v3.6.0 PR6).

Tests verify:
- kind cluster config exists and is valid YAML
- HA test values exist and are valid
- Cluster has multiple worker nodes
- Zone labels are configured
- GitHub workflow exists
"""

import pytest
import yaml
from pathlib import Path


# Paths
DEPLOY_PATH = Path(__file__).parent.parent.parent / "deploy"
WORKFLOWS_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows"


class TestKindClusterConfig:
    """Tests for kind cluster configuration."""

    def test_kind_config_exists(self):
        """Kind cluster config should exist."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        assert config_path.exists()

    def test_kind_config_is_valid_yaml(self):
        """Kind cluster config should be valid YAML."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        assert config is not None
        assert "kind" in config
        assert config["kind"] == "Cluster"

    def test_kind_config_has_control_plane(self):
        """Kind config should have a control plane node."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        nodes = config.get("nodes", [])
        control_planes = [n for n in nodes if n.get("role") == "control-plane"]
        assert len(control_planes) >= 1

    def test_kind_config_has_multiple_workers(self):
        """Kind config should have multiple worker nodes."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        nodes = config.get("nodes", [])
        workers = [n for n in nodes if n.get("role") == "worker"]
        assert len(workers) >= 2, "Need at least 2 workers for HA testing"

    def test_kind_config_has_zone_labels(self):
        """Worker nodes should have zone labels."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        nodes = config.get("nodes", [])
        workers = [n for n in nodes if n.get("role") == "worker"]

        zones = set()
        for worker in workers:
            labels = worker.get("labels", {})
            zone = labels.get("topology.kubernetes.io/zone")
            if zone:
                zones.add(zone)

        assert len(zones) >= 2, "Workers should span multiple zones"

    def test_kind_config_has_ingress_port_mapping(self):
        """Control plane should have ingress port mappings."""
        config_path = DEPLOY_PATH / "kind" / "kind-ha-config.yaml"
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        nodes = config.get("nodes", [])
        control_planes = [n for n in nodes if n.get("role") == "control-plane"]

        for cp in control_planes:
            port_mappings = cp.get("extraPortMappings", [])
            ports = [pm.get("hostPort") for pm in port_mappings]
            assert 80 in ports or 443 in ports, "Need ingress port mapping"


class TestHATestValues:
    """Tests for HA test values configuration."""

    def test_ha_test_values_exists(self):
        """HA test values should exist."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        assert values_path.exists()

    def test_ha_test_values_is_valid_yaml(self):
        """HA test values should be valid YAML."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values is not None

    def test_ha_test_values_enables_ha(self):
        """HA test values should enable HA mode."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("ha", {}).get("enabled") is True
        assert values.get("ha", {}).get("strict") is True

    def test_ha_test_values_has_multiple_api_replicas(self):
        """HA test values should have 2+ API replicas."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("api", {}).get("replicaCount", 1) >= 2

    def test_ha_test_values_has_multiple_worker_replicas(self):
        """HA test values should have 2+ Worker replicas."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("worker", {}).get("replicaCount", 1) >= 2

    def test_ha_test_values_has_pdb_enabled(self):
        """HA test values should enable PDB."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("api", {}).get("pdb", {}).get("enabled") is True
        assert values.get("worker", {}).get("pdb", {}).get("enabled") is True

    def test_ha_test_values_uses_db_backend(self):
        """HA test values should use db backend."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("runstore", {}).get("backend") == "db"

    def test_ha_test_values_enables_postgresql(self):
        """HA test values should enable PostgreSQL."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("postgresql", {}).get("enabled") is True

    def test_ha_test_values_enables_redis(self):
        """HA test values should enable Redis."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        assert values.get("redis", {}).get("enabled") is True

    def test_ha_test_values_has_topology_spread(self):
        """HA test values should have topology spread constraints."""
        values_path = DEPLOY_PATH / "kind" / "ha-test-values.yaml"
        with open(values_path, "r") as f:
            values = yaml.safe_load(f)

        api_constraints = values.get("api", {}).get("topologySpreadConstraints", [])
        worker_constraints = values.get("worker", {}).get("topologySpreadConstraints", [])

        assert len(api_constraints) > 0, "API should have topology constraints"
        assert len(worker_constraints) > 0, "Worker should have topology constraints"


class TestHAE2EWorkflow:
    """Tests for HA E2E GitHub workflow."""

    def test_workflow_exists(self):
        """HA E2E workflow should exist."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        assert workflow_path.exists()

    def test_workflow_is_valid_yaml(self):
        """HA E2E workflow should be valid YAML."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            workflow = yaml.safe_load(f)

        assert workflow is not None
        assert "name" in workflow
        assert "jobs" in workflow

    def test_workflow_uses_kind(self):
        """Workflow should use kind action."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "helm/kind-action" in content
        assert "kind-ha-config.yaml" in content

    def test_workflow_verifies_replicas(self):
        """Workflow should verify replica counts."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "API_REPLICAS" in content
        assert "WORKER_REPLICAS" in content
        assert "readyReplicas" in content

    def test_workflow_verifies_pdb(self):
        """Workflow should verify PDB status."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "pdb" in content.lower()
        assert "currentHealthy" in content

    def test_workflow_tests_failover(self):
        """Workflow should test HA failover."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "failover" in content.lower()
        assert "delete pod" in content.lower()

    def test_workflow_tests_health_endpoints(self):
        """Workflow should test health endpoints."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "/health/live" in content
        assert "/health/ready" in content

    def test_workflow_collects_logs_on_failure(self):
        """Workflow should collect logs on failure."""
        workflow_path = WORKFLOWS_PATH / "ha-e2e.yml"
        with open(workflow_path, "r") as f:
            content = f.read()

        assert "if: failure()" in content
        assert "kubectl logs" in content
