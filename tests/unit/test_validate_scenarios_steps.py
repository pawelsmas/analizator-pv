"""
Unit tests for step-based scenario validation (v3.4.0 PR5).

Tests the new step-based pack format with submit_job, wait_job, and http actions.
"""

import pytest
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from validate_scenarios import (
    StepContext,
    execute_http_step,
    execute_submit_job_step,
    execute_wait_job_step,
    check_expectations,
    run_step_scenario,
    is_step_based_pack,
)


class TestStepContext:
    """Tests for StepContext class."""

    def test_init_sets_random_suffix(self):
        """Context should initialize with random suffix."""
        ctx = StepContext("http://localhost:8031")
        assert "RANDOM_SUFFIX" in ctx.variables
        assert len(ctx.variables["RANDOM_SUFFIX"]) == 8

    def test_init_loads_env_variables(self):
        """Context should load TEST_ and BESS_ env variables."""
        with patch.dict(os.environ, {"TEST_RUN_ID": "run-123", "BESS_API_URL": "http://test"}):
            ctx = StepContext("http://localhost:8031")
            assert ctx.variables.get("TEST_RUN_ID") == "run-123"
            assert ctx.variables.get("BESS_API_URL") == "http://test"

    def test_resolve_variable_simple(self):
        """Should resolve simple ${var} syntax."""
        ctx = StepContext("http://localhost:8031")
        ctx.variables["job_id"] = "abc-123"
        result = ctx.resolve_variable("/jobs/${job_id}")
        assert result == "/jobs/abc-123"

    def test_resolve_variable_with_default(self):
        """Should resolve ${var:-default} syntax."""
        ctx = StepContext("http://localhost:8031")
        result = ctx.resolve_variable("${MISSING_VAR:-fallback}")
        assert result == "fallback"

    def test_resolve_variable_no_match(self):
        """Should leave unresolved variables as-is."""
        ctx = StepContext("http://localhost:8031")
        result = ctx.resolve_variable("${UNDEFINED_VAR}")
        assert result == "${UNDEFINED_VAR}"

    def test_resolve_variables_in_dict(self):
        """Should recursively resolve variables in dicts."""
        ctx = StepContext("http://localhost:8031")
        ctx.variables["id"] = "123"
        result = ctx.resolve_variables_in_dict({
            "job_id": "${id}",
            "nested": {"value": "${id}"},
        })
        assert result == {"job_id": "123", "nested": {"value": "123"}}

    def test_resolve_variables_in_list(self):
        """Should resolve variables in lists."""
        ctx = StepContext("http://localhost:8031")
        ctx.variables["fmt"] = "pdf"
        result = ctx.resolve_variables_in_dict(["${fmt}", "xlsx"])
        assert result == ["pdf", "xlsx"]

    def test_capture_value_simple(self):
        """Should capture simple JSONPath values."""
        ctx = StepContext("http://localhost:8031")
        data = {"job_id": "abc-123", "status": "queued"}
        assert ctx.capture_value(data, "$.job_id") == "abc-123"

    def test_capture_value_nested(self):
        """Should capture nested JSONPath values."""
        ctx = StepContext("http://localhost:8031")
        data = {"result": {"artifacts": ["report.pdf"]}}
        assert ctx.capture_value(data, "$.result.artifacts") == ["report.pdf"]

    def test_capture_value_array_index(self):
        """Should capture array index values."""
        ctx = StepContext("http://localhost:8031")
        data = {"items": ["a", "b", "c"]}
        assert ctx.capture_value(data, "$.items.0") == "a"


class TestExecuteHttpStep:
    """Tests for execute_http_step function."""

    @patch('validate_scenarios.requests.get')
    def test_get_request_success(self, mock_get):
        """Should execute GET request successfully."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_resp

        ctx = StepContext("http://localhost:8031")
        step = {"method": "GET", "endpoint": "/api/jobs"}

        success, result = execute_http_step(ctx, step)

        assert success is True
        assert result["status_code"] == 200
        assert result["body"] == {"items": []}

    @patch('validate_scenarios.requests.post')
    def test_post_request_success(self, mock_post):
        """Should execute POST request successfully."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"job_id": "abc-123"}
        mock_post.return_value = mock_resp

        ctx = StepContext("http://localhost:8031")
        step = {"method": "POST", "endpoint": "/api/jobs", "body": {"kind": "report_run"}}

        success, result = execute_http_step(ctx, step)

        assert success is True
        assert result["status_code"] == 200
        mock_post.assert_called_once()

    @patch('validate_scenarios.requests.get')
    def test_request_exception(self, mock_get):
        """Should handle request exceptions."""
        import requests as req_module
        mock_get.side_effect = req_module.RequestException("Connection refused")

        ctx = StepContext("http://localhost:8031")
        step = {"method": "GET", "endpoint": "/api/jobs"}

        success, result = execute_http_step(ctx, step)

        assert success is False
        assert "error" in result


class TestExecuteSubmitJobStep:
    """Tests for execute_submit_job_step function."""

    @patch('validate_scenarios.requests.post')
    def test_submit_job_success(self, mock_post):
        """Should submit job successfully."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"job_id": "abc-123", "status": "queued"}
        mock_post.return_value = mock_resp

        ctx = StepContext("http://localhost:8031")
        step = {
            "endpoint": "/api/bess-dispatch/jobs",
            "payload": {"kind": "report_run", "payload": {"run_id": "run-1"}},
        }

        success, result = execute_submit_job_step(ctx, step)

        assert success is True
        assert result["status_code"] == 200
        assert result["body"]["job_id"] == "abc-123"

    @patch('validate_scenarios.requests.post')
    def test_submit_job_resolves_variables(self, mock_post):
        """Should resolve variables in payload."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"job_id": "abc-123"}
        mock_post.return_value = mock_resp

        ctx = StepContext("http://localhost:8031")
        ctx.variables["TEST_RUN_ID"] = "my-run-id"
        step = {
            "payload": {"kind": "report_run", "payload": {"run_id": "${TEST_RUN_ID}"}},
        }

        success, result = execute_submit_job_step(ctx, step)

        assert success is True
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["payload"]["run_id"] == "my-run-id"


class TestExecuteWaitJobStep:
    """Tests for execute_wait_job_step function."""

    @patch('validate_scenarios.requests.get')
    @patch('validate_scenarios.time.sleep')
    def test_wait_job_success(self, mock_sleep, mock_get):
        """Should poll until job succeeds."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = [
            {"status": "running"},
            {"status": "running"},
            {"status": "succeeded", "result": {"artifacts": ["report.pdf"]}},
        ]
        mock_get.return_value = mock_resp

        ctx = StepContext("http://localhost:8031", poll_interval=1, timeout=60)
        ctx.variables["job_id"] = "abc-123"
        step = {"job_id": "${job_id}", "timeout_seconds": 60}

        success, result = execute_wait_job_step(ctx, step)

        assert success is True
        assert result["status"] == "succeeded"

    @patch('validate_scenarios.requests.get')
    @patch('validate_scenarios.time.sleep')
    def test_wait_job_failed(self, mock_sleep, mock_get):
        """Should detect failed job."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "failed", "error": {"code": "ERROR"}}
        mock_get.return_value = mock_resp

        ctx = StepContext("http://localhost:8031")
        step = {"job_id": "abc-123"}

        success, result = execute_wait_job_step(ctx, step)

        assert success is True
        assert result["status"] == "failed"

    @patch('validate_scenarios.requests.get')
    @patch('validate_scenarios.time.time')
    def test_wait_job_timeout(self, mock_time, mock_get):
        """Should timeout if job doesn't complete."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "running"}
        mock_get.return_value = mock_resp

        # Simulate timeout
        mock_time.side_effect = [0, 5, 10, 120]

        ctx = StepContext("http://localhost:8031")
        step = {"job_id": "abc-123", "timeout_seconds": 10}

        success, result = execute_wait_job_step(ctx, step)

        assert success is False
        assert "Timeout" in result["error"]

    def test_wait_job_missing_job_id(self):
        """Should fail if job_id is missing."""
        ctx = StepContext("http://localhost:8031")
        step = {}

        success, result = execute_wait_job_step(ctx, step)

        assert success is False
        assert "job_id is required" in result["error"]


class TestCheckExpectations:
    """Tests for check_expectations function."""

    def test_check_status_code_pass(self):
        """Should pass when status code matches."""
        result = {"status_code": 200}
        expect = {"status_code": 200}
        passed, errors = check_expectations(result, expect)
        assert passed is True
        assert errors == []

    def test_check_status_code_fail(self):
        """Should fail when status code doesn't match."""
        result = {"status_code": 404}
        expect = {"status_code": 200}
        passed, errors = check_expectations(result, expect)
        assert passed is False
        assert "Expected status_code 200" in errors[0]

    def test_check_status_pass(self):
        """Should pass when status matches."""
        result = {"status": "succeeded"}
        expect = {"status": "succeeded"}
        passed, errors = check_expectations(result, expect)
        assert passed is True

    def test_check_body_field_pass(self):
        """Should pass when body field matches."""
        result = {"body": {"job_id": "abc-123", "status": "queued"}}
        expect = {"body": {"status": "queued"}}
        passed, errors = check_expectations(result, expect)
        assert passed is True

    def test_check_body_field_fail(self):
        """Should fail when body field doesn't match."""
        result = {"body": {"status": "failed"}}
        expect = {"body": {"status": "succeeded"}}
        passed, errors = check_expectations(result, expect)
        assert passed is False

    def test_check_array_field(self):
        """Should check that array field is an array."""
        result = {"body": {"items": []}}
        expect = {"body": {"items": []}}
        passed, errors = check_expectations(result, expect)
        assert passed is True

    def test_check_header_case_insensitive(self):
        """Should check headers case-insensitively."""
        result = {"headers": {"Content-Type": "application/json"}}
        expect = {"headers": {"content-type": "json"}}
        passed, errors = check_expectations(result, expect)
        assert passed is True


class TestRunStepScenario:
    """Tests for run_step_scenario function."""

    @patch('validate_scenarios.execute_http_step')
    def test_run_scenario_all_pass(self, mock_http):
        """Should run all steps when they pass."""
        mock_http.return_value = (True, {"status_code": 200, "body": {"ok": True}})

        ctx = StepContext("http://localhost:8031")
        scenario = {
            "id": "test_scenario",
            "steps": [
                {"action": "http", "method": "GET", "endpoint": "/health"},
                {"action": "http", "method": "GET", "endpoint": "/version"},
            ],
        }

        passed, result = run_step_scenario(scenario, ctx)

        assert passed is True
        assert result["scenario_id"] == "test_scenario"
        assert len(result["steps"]) == 2

    @patch('validate_scenarios.execute_http_step')
    def test_run_scenario_stop_on_failure(self, mock_http):
        """Should stop on first failure."""
        mock_http.side_effect = [
            (True, {"status_code": 200, "body": {}}),
            (False, {"error": "Connection failed"}),
        ]

        ctx = StepContext("http://localhost:8031")
        scenario = {
            "id": "test_scenario",
            "steps": [
                {"action": "http", "method": "GET", "endpoint": "/health"},
                {"action": "http", "method": "GET", "endpoint": "/fail"},
                {"action": "http", "method": "GET", "endpoint": "/never"},
            ],
        }

        passed, result = run_step_scenario(scenario, ctx)

        assert passed is False
        assert len(result["steps"]) == 2

    @patch('validate_scenarios.execute_submit_job_step')
    def test_run_scenario_captures_variables(self, mock_submit):
        """Should capture variables for use in later steps."""
        mock_submit.return_value = (True, {"status_code": 200, "body": {"job_id": "captured-id"}})

        ctx = StepContext("http://localhost:8031")
        scenario = {
            "id": "test_capture",
            "steps": [
                {
                    "action": "submit_job",
                    "payload": {"kind": "report_run"},
                    "capture": {"my_job_id": "$.job_id"},
                },
            ],
        }

        passed, result = run_step_scenario(scenario, ctx)

        assert passed is True
        assert ctx.variables["my_job_id"] == "captured-id"


class TestIsStepBasedPack:
    """Tests for is_step_based_pack function."""

    def test_step_based_pack_true(self):
        """Should detect step-based pack."""
        pack_data = {
            "name": "test",
            "scenarios": [
                {"id": "test", "steps": [{"action": "http"}]},
            ],
        }
        assert is_step_based_pack(pack_data) is True

    def test_legacy_pack_false(self):
        """Should detect legacy pack."""
        pack_data = {
            "name": "test",
            "scenarios": ["scenario_1", "scenario_2"],
        }
        assert is_step_based_pack(pack_data) is False

    def test_empty_scenarios_false(self):
        """Should return False for empty scenarios."""
        pack_data = {"name": "test", "scenarios": []}
        assert is_step_based_pack(pack_data) is False


class TestPackFileExists:
    """Tests for jobs_async_auth.yml pack file."""

    def test_pack_file_exists(self):
        """Pack file should exist."""
        pack_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "jobs_async_auth.yml"
        assert pack_path.exists(), f"Pack file not found: {pack_path}"

    def test_pack_file_valid_yaml(self):
        """Pack file should be valid YAML."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        pack_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "jobs_async_auth.yml"
        with open(pack_path) as f:
            data = yaml.safe_load(f)

        assert "name" in data
        assert "scenarios" in data
        assert isinstance(data["scenarios"], list)
        assert len(data["scenarios"]) > 0

    def test_pack_has_required_fields(self):
        """Pack should have required config and scenarios."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        pack_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "jobs_async_auth.yml"
        with open(pack_path) as f:
            data = yaml.safe_load(f)

        assert data["name"] == "jobs_async_auth"
        assert "config" in data
        assert "poll_interval_seconds" in data["config"]
        assert "timeout_seconds" in data["config"]

    def test_pack_scenarios_have_steps(self):
        """Each scenario should have steps."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        pack_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "jobs_async_auth.yml"
        with open(pack_path) as f:
            data = yaml.safe_load(f)

        for scenario in data["scenarios"]:
            assert "id" in scenario, f"Scenario missing 'id': {scenario}"
            assert "steps" in scenario, f"Scenario {scenario.get('id')} missing 'steps'"
            assert len(scenario["steps"]) > 0, f"Scenario {scenario['id']} has no steps"

    def test_pack_step_actions_valid(self):
        """All step actions should be valid."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        valid_actions = {"http", "submit_job", "wait_job"}
        pack_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "jobs_async_auth.yml"
        with open(pack_path) as f:
            data = yaml.safe_load(f)

        for scenario in data["scenarios"]:
            for step in scenario["steps"]:
                action = step.get("action", "http")
                assert action in valid_actions, f"Invalid action '{action}' in {scenario['id']}"
