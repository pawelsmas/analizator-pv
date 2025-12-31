"""
Regression tests for v1.7.0 validate-pack jobs API.

Tests verify:
- ValidatePackJobResponse structure
- Result contains summary and scenarios
- Scenario pass/fail status
- Pack list response structure

Scenarios:
1. Validate-pack job with wait=true - result returned immediately
2. Result structure with summary and scenarios
3. GET /validation/packs response structure
"""
import pytest


class TestRegressionValidatePackResponse:
    """Regression tests for validate-pack job response."""

    GOLDEN_FILE = "scenario_validate_pack_v170.json"

    def test_job_has_job_id(self, load_golden):
        """Verify validate-pack job response has job_id."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "job_id" in golden
        assert golden["job_id"] is not None
        assert len(golden["job_id"]) > 0

    def test_job_has_type_validate_pack(self, load_golden):
        """Verify job type is validate_pack."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "type" in golden
        assert golden["type"] == "validate_pack"

    def test_job_has_pack_name(self, load_golden):
        """Verify job response has pack name."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "pack" in golden
        assert golden["pack"] is not None
        assert len(golden["pack"]) > 0

    def test_job_has_status(self, load_golden):
        """Verify job response has status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "status" in golden
        assert golden["status"] in ["pending", "running", "done", "failed", "cancelled"]

    def test_sync_job_status_is_done(self, load_golden):
        """Verify sync job (wait=true) returns done status."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["status"] == "done", (
            f"Sync job should return 'done' status, got '{golden['status']}'"
        )

    def test_job_has_items_counts(self, load_golden):
        """Verify job has items_total, items_done, error_count."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "items_total" in golden
        assert "items_done" in golden
        assert "error_count" in golden
        assert golden["items_total"] >= 0
        assert golden["items_done"] >= 0
        assert golden["error_count"] >= 0


class TestRegressionValidatePackResult:
    """Regression tests for validate-pack result structure."""

    GOLDEN_FILE = "scenario_validate_pack_v170.json"

    def test_result_exists_when_done(self, load_golden):
        """Verify result exists when status is done."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done":
            assert "result" in golden
            assert golden["result"] is not None

    def test_result_has_pack_name(self, load_golden):
        """Verify result has pack name."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "pack" in result

    def test_result_has_pass_flag(self, load_golden):
        """Verify result has pass flag."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "pass" in result
            assert isinstance(result["pass"], bool)

    def test_result_has_summary(self, load_golden):
        """Verify result has summary with counts."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "summary" in result
            summary = result["summary"]
            assert "total" in summary
            assert "pass" in summary
            assert "fail" in summary

    def test_result_has_scenarios(self, load_golden):
        """Verify result has scenarios list."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            assert "scenarios" in result
            assert isinstance(result["scenarios"], list)

    def test_scenario_has_required_fields(self, load_golden):
        """Verify each scenario has name and pass."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            for scenario in result.get("scenarios", []):
                assert "name" in scenario
                assert "pass" in scenario
                assert isinstance(scenario["pass"], bool)

    def test_summary_counts_match_scenarios(self, load_golden):
        """Verify summary counts match scenario results."""
        golden = load_golden(self.GOLDEN_FILE)

        if golden["status"] == "done" and golden.get("result"):
            result = golden["result"]
            summary = result.get("summary", {})
            scenarios = result.get("scenarios", [])

            total = summary.get("total", 0)
            passed = summary.get("pass", 0)
            failed = summary.get("fail", 0)

            assert total == len(scenarios), (
                f"Summary total ({total}) should match scenarios count ({len(scenarios)})"
            )

            actual_passed = sum(1 for s in scenarios if s.get("pass", False))
            actual_failed = sum(1 for s in scenarios if not s.get("pass", True))

            assert passed == actual_passed, (
                f"Summary pass ({passed}) should match actual passed ({actual_passed})"
            )


class TestRegressionPacksList:
    """Regression tests for GET /validation/packs response."""

    GOLDEN_FILE = "scenario_packs_list_v170.json"

    def test_packs_list_has_packs_array(self, load_golden):
        """Verify response has packs array."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "packs" in golden
        assert isinstance(golden["packs"], list)

    def test_packs_are_strings(self, load_golden):
        """Verify each pack name is a string."""
        golden = load_golden(self.GOLDEN_FILE)

        for pack in golden.get("packs", []):
            assert isinstance(pack, str)
            assert len(pack) > 0

    def test_baseline_pack_exists(self, load_golden):
        """Verify baseline pack is in the list."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "baseline" in golden.get("packs", []), (
            "baseline pack should exist in packs list"
        )
