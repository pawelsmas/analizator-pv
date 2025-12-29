"""
Contract tests for v0.9.0 batch sizing endpoint.

Tests verify:
- POST /sizing:batch endpoint structure
- Per-item isolation (ok/error)
- fail_fast behavior
- Batch ID handling
- Summary statistics

Run with: pytest tests/contract/test_batch_sizing_endpoint.py -v
"""
import pytest
from ._api import post_json


BATCH_PATH = "/sizing:batch"


# Minimal valid sizing request for testing
MINIMAL_SIZING_REQUEST = {
    "load_kw": [100, 120, 110, 90],
    "pv_generation_kw": [50, 70, 80, 60],
    "energy_price_pln_kwh": 0.8,
}


class TestBatchEndpointPresence:
    """Tests for batch endpoint existence and basic structure."""

    def test_batch_endpoint_returns_200(self):
        """Verify POST /sizing:batch returns 200 OK."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        assert "batch_id" in resp
        assert "results" in resp
        assert "summary" in resp

    def test_batch_id_generated_when_not_provided(self):
        """Verify batch_id is generated if not in request."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        assert resp["batch_id"] is not None
        assert len(resp["batch_id"]) > 0

    def test_batch_id_echoed_when_provided(self):
        """Verify batch_id is echoed from request."""
        payload = {
            "batch_id": "my-custom-batch-123",
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        assert resp["batch_id"] == "my-custom-batch-123"


class TestBatchResponseStructure:
    """Tests for batch response structure."""

    def test_response_has_required_fields(self):
        """Verify response has all required fields."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert "batch_id" in resp
        assert "schema_version" in resp
        assert "assumptions_version" in resp
        assert "results" in resp
        assert "summary" in resp

    def test_summary_has_required_fields(self):
        """Verify summary has all required fields."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST},
                {"item_id": "site-2", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        summary = resp["summary"]

        assert "total_items" in summary
        assert "ok_count" in summary
        assert "error_count" in summary
        assert "processing_time_ms" in summary

    def test_results_count_matches_items(self):
        """Verify results count matches input items count."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST},
                {"item_id": "site-2", "request": MINIMAL_SIZING_REQUEST},
                {"item_id": "site-3", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert len(resp["results"]) == 3
        assert resp["summary"]["total_items"] == 3


class TestBatchItemResult:
    """Tests for individual batch item results."""

    def test_item_result_has_required_fields(self):
        """Verify each item result has required fields."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        result = resp["results"][0]

        assert "item_id" in result
        assert "status" in result

    def test_successful_item_has_response(self):
        """Verify successful item has response, not error."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        result = resp["results"][0]

        assert result["status"] == "ok"
        assert result["response"] is not None
        assert result["error"] is None

    def test_successful_item_response_has_sizing_fields(self):
        """Verify successful item response has sizing result fields."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        sizing_result = resp["results"][0]["response"]

        # Check for key SizingResult fields
        assert "mode" in sizing_result
        assert "variants" in sizing_result
        assert "recommended_variant" in sizing_result

    def test_item_id_preserved_in_result(self):
        """Verify item_id is preserved in result."""
        payload = {
            "items": [
                {"item_id": "my-unique-id-123", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        result = resp["results"][0]

        assert result["item_id"] == "my-unique-id-123"


class TestBatchErrorHandling:
    """Tests for error handling in batch processing."""

    def test_invalid_item_returns_error_status(self):
        """Verify invalid item has error status."""
        payload = {
            "items": [
                {
                    "item_id": "invalid-item",
                    "request": {
                        "load_kw": [],  # Invalid: empty load
                        "pv_generation_kw": [50, 70, 80, 60],
                    }
                }
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        result = resp["results"][0]

        assert result["status"] == "error"
        assert result["error"] is not None
        assert result["response"] is None

    def test_error_count_matches_failed_items(self):
        """Verify error_count matches number of failed items."""
        payload = {
            "items": [
                {"item_id": "valid", "request": MINIMAL_SIZING_REQUEST},
                {
                    "item_id": "invalid",
                    "request": {
                        "load_kw": [],  # Invalid
                        "pv_generation_kw": [50, 70, 80, 60],
                    }
                },
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert resp["summary"]["ok_count"] == 1
        assert resp["summary"]["error_count"] == 1

    def test_valid_items_processed_despite_errors(self):
        """Verify valid items are still processed when other items fail."""
        payload = {
            "fail_fast": False,  # Process all items
            "items": [
                {"item_id": "valid-1", "request": MINIMAL_SIZING_REQUEST},
                {
                    "item_id": "invalid",
                    "request": {
                        "load_kw": [],  # Invalid
                        "pv_generation_kw": [50, 70, 80, 60],
                    }
                },
                {"item_id": "valid-2", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert len(resp["results"]) == 3
        assert resp["results"][0]["status"] == "ok"
        assert resp["results"][1]["status"] == "error"
        assert resp["results"][2]["status"] == "ok"


class TestBatchFailFast:
    """Tests for fail_fast behavior."""

    def test_fail_fast_false_processes_all_items(self):
        """Verify fail_fast=False processes all items even after error."""
        payload = {
            "fail_fast": False,
            "items": [
                {
                    "item_id": "invalid",
                    "request": {
                        "load_kw": [],  # Invalid - will fail
                        "pv_generation_kw": [],
                    }
                },
                {"item_id": "valid", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        # Both items should be processed
        assert len(resp["results"]) == 2
        assert resp["results"][0]["status"] == "error"
        assert resp["results"][1]["status"] == "ok"

    def test_fail_fast_true_stops_on_error(self):
        """Verify fail_fast=True stops processing on first error."""
        payload = {
            "fail_fast": True,
            "items": [
                {"item_id": "valid-first", "request": MINIMAL_SIZING_REQUEST},
                {
                    "item_id": "invalid",
                    "request": {
                        "load_kw": [],  # Invalid - will fail
                        "pv_generation_kw": [],
                    }
                },
                {"item_id": "valid-last", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        # Only first two items should be processed
        assert len(resp["results"]) == 2
        assert resp["results"][0]["status"] == "ok"
        assert resp["results"][1]["status"] == "error"
        # Third item should not be in results
        item_ids = [r["item_id"] for r in resp["results"]]
        assert "valid-last" not in item_ids


class TestBatchSummary:
    """Tests for batch summary statistics."""

    def test_processing_time_is_positive(self):
        """Verify processing_time_ms is positive."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert resp["summary"]["processing_time_ms"] > 0

    def test_ok_count_plus_error_count_equals_results_count(self):
        """Verify ok_count + error_count equals results count."""
        payload = {
            "fail_fast": False,
            "items": [
                {"item_id": "valid-1", "request": MINIMAL_SIZING_REQUEST},
                {
                    "item_id": "invalid",
                    "request": {
                        "load_kw": [],
                        "pv_generation_kw": [],
                    }
                },
                {"item_id": "valid-2", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)
        summary = resp["summary"]

        assert summary["ok_count"] + summary["error_count"] == len(resp["results"])


class TestBatchVersioning:
    """Tests for API versioning in batch response."""

    def test_schema_version_present(self):
        """Verify schema_version is present in response."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert "schema_version" in resp
        assert resp["schema_version"] is not None

    def test_assumptions_version_present(self):
        """Verify assumptions_version is present in response."""
        payload = {
            "items": [
                {"item_id": "site-1", "request": MINIMAL_SIZING_REQUEST}
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert "assumptions_version" in resp
        assert resp["assumptions_version"] is not None


class TestBatchMultipleItems:
    """Tests for processing multiple items."""

    def test_multiple_valid_items_all_succeed(self):
        """Verify multiple valid items all succeed."""
        payload = {
            "items": [
                {"item_id": f"site-{i}", "request": MINIMAL_SIZING_REQUEST}
                for i in range(5)
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert resp["summary"]["total_items"] == 5
        assert resp["summary"]["ok_count"] == 5
        assert resp["summary"]["error_count"] == 0
        assert all(r["status"] == "ok" for r in resp["results"])

    def test_items_processed_in_order(self):
        """Verify items are processed and returned in order."""
        payload = {
            "items": [
                {"item_id": "first", "request": MINIMAL_SIZING_REQUEST},
                {"item_id": "second", "request": MINIMAL_SIZING_REQUEST},
                {"item_id": "third", "request": MINIMAL_SIZING_REQUEST},
            ]
        }
        resp = post_json(BATCH_PATH, payload)

        assert resp["results"][0]["item_id"] == "first"
        assert resp["results"][1]["item_id"] == "second"
        assert resp["results"][2]["item_id"] == "third"
