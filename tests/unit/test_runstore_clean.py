"""
Unit tests for RunStore clean normalization (v2.8.0 PR4).

Tests verify:
- Responses are normalized to clean format before storage
- Deprecated fields are removed during save
- Stored responses can be retrieved without deprecated fields
"""

import pytest
import sys
import tempfile
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestNormalizeResponseToClean:
    """Tests for _normalize_response_to_clean function."""

    def test_removes_export_revenue_pln(self):
        """Should remove export_revenue_pln from response."""
        from run_store import _normalize_response_to_clean

        response = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 1000,  # Deprecated
            "npv_pln": 50000,
        }

        result = _normalize_response_to_clean(response)

        assert "export_savings_pln" in result
        assert "export_revenue_pln" not in result
        assert result["npv_pln"] == 50000

    def test_removes_nested_deprecated(self):
        """Should remove deprecated fields from nested structures."""
        from run_store import _normalize_response_to_clean

        response = {
            "variants": [
                {
                    "export_savings_pln": 500,
                    "export_revenue_pln": 500,  # Deprecated
                    "name": "S",
                }
            ]
        }

        result = _normalize_response_to_clean(response)

        assert "export_revenue_pln" not in result["variants"][0]
        assert result["variants"][0]["export_savings_pln"] == 500

    def test_preserves_non_deprecated(self):
        """Should preserve non-deprecated fields."""
        from run_store import _normalize_response_to_clean

        response = {
            "npv_pln": 50000,
            "capex_pln": 100000,
            "variants": [{"name": "S"}, {"name": "M"}],
        }

        result = _normalize_response_to_clean(response)

        assert result["npv_pln"] == 50000
        assert result["capex_pln"] == 100000
        assert len(result["variants"]) == 2


class TestRunStoreSaveNormalization:
    """Tests for RunStore.save normalization."""

    def test_save_normalizes_response(self):
        """save() should normalize response to clean before storing."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)

        # Save with deprecated fields
        response_with_legacy = {
            "export_savings_pln": 1000,
            "export_revenue_pln": 1000,  # Deprecated
            "npv_pln": 50000,
        }

        store.save(
            run_id="test-run-001",
            request_hash="abc123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0",
            assumptions_version="1.0",
            compute_time_ms=100,
            request={"load_kw": [100]},
            response=response_with_legacy,
        )

        # Retrieve and verify deprecated field is gone
        result = store.get("test-run-001")
        assert result is not None
        assert "export_revenue_pln" not in result["response"]
        assert result["response"]["export_savings_pln"] == 1000

    def test_save_preserves_original_fields(self):
        """save() should preserve non-deprecated fields."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)

        response = {
            "npv_pln": 50000,
            "capex_pln": 100000,
            "recommended": {"energy_kwh": 100},
        }

        store.save(
            run_id="test-run-002",
            request_hash="abc123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0",
            assumptions_version="1.0",
            compute_time_ms=100,
            request={"load_kw": [100]},
            response=response,
        )

        result = store.get("test-run-002")
        assert result["response"]["npv_pln"] == 50000
        assert result["response"]["capex_pln"] == 100000
        assert result["response"]["recommended"]["energy_kwh"] == 100


class TestRunStoreGetClean:
    """Tests for RunStore.get returning clean responses."""

    def test_get_returns_clean_response(self):
        """get() should return clean response without deprecated fields."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)

        # Save with deprecated fields
        store.save(
            run_id="test-run-003",
            request_hash="abc123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0",
            assumptions_version="1.0",
            compute_time_ms=100,
            request={"load_kw": [100]},
            response={
                "variants": [
                    {
                        "export_savings_pln": 500,
                        "export_revenue_pln": 500,  # Deprecated
                    }
                ]
            },
        )

        result = store.get("test-run-003")
        assert "export_revenue_pln" not in result["response"]["variants"][0]


class TestGlobalFunctions:
    """Tests for global run_store functions."""

    def test_save_run_normalizes(self):
        """save_run() should normalize response."""
        import os
        import tempfile
        from run_store import save_run, get_run, _run_store

        # Use temp file for testing
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            temp_db = f.name

        # Temporarily override settings
        import run_store
        original_path = run_store.RUN_STORE_PATH
        original_enabled = run_store.RUN_STORE_ENABLED
        run_store.RUN_STORE_PATH = temp_db
        run_store.RUN_STORE_ENABLED = True
        run_store._run_store = None  # Reset global instance

        try:
            save_run(
                run_id="global-test-001",
                request_hash="xyz789",
                endpoint="sizing",
                status="ok",
                cache_hit=False,
                schema_version="1.0",
                assumptions_version="1.0",
                compute_time_ms=50,
                request={"load_kw": [100]},
                response={
                    "export_savings_pln": 2000,
                    "export_revenue_pln": 2000,  # Deprecated
                },
            )

            result = get_run("global-test-001")
            assert result is not None
            assert "export_revenue_pln" not in result["response"]
            assert result["response"]["export_savings_pln"] == 2000
        finally:
            # Restore original settings
            run_store.RUN_STORE_PATH = original_path
            run_store.RUN_STORE_ENABLED = original_enabled
            run_store._run_store = None


class TestCompatibilityWithExistingRuns:
    """Tests for compatibility with existing stored runs."""

    def test_existing_runs_remain_accessible(self):
        """Existing runs should remain accessible after upgrade."""
        from run_store import RunStore, _compress_json
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)

        # Simulate old run with deprecated fields (bypass normalization)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            old_response = {
                "export_savings_pln": 1500,
                "export_revenue_pln": 1500,  # Would be removed by new code
                "npv_pln": 75000,
            }
            cursor.execute("""
                INSERT INTO runs (
                    run_id, request_hash, created_at, endpoint, status,
                    cache_hit, schema_version, assumptions_version,
                    compute_time_ms, request_blob, response_blob
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "old-run-001", "old123", "2025-01-01T00:00:00Z", "sizing", "ok",
                0, "1.0", "1.0", 100,
                _compress_json({"load_kw": [100]}),
                _compress_json(old_response),  # Old format with deprecated
            ))
            conn.commit()
        finally:
            conn.close()

        # New code should still be able to read old runs
        result = store.get("old-run-001")
        assert result is not None
        # Old runs may still have deprecated fields (not retroactively cleaned)
        assert result["response"]["export_savings_pln"] == 1500
        # The deprecated field is still there in old data
        assert result["response"]["export_revenue_pln"] == 1500
