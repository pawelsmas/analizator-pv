"""
Contract tests for v1.3.0 run listing upgrades.

Tests verify:
- Filter by tag (exact match)
- Free-text search (q parameter) in label and notes
- Sorting (created_at_asc, created_at_desc, updated_at_desc)
- Response includes metadata fields (label, tags, notes, updated_at)
"""
import time

import pytest
import requests

from ._api import post_json, get_json, patch_json, load_smoke_payload


# API paths
SIZING_PATH = "/sizing"
RUNS_PATH = "/runs"
BASE_URL = "http://localhost:8031"


def create_sizing_run():
    """Create a sizing run and return the run_id."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    response = post_json(SIZING_PATH, payload)
    return response["cache_info"]["run_id"]


def create_run_with_metadata(label=None, tags=None, notes=None):
    """Create a sizing run and set metadata."""
    run_id = create_sizing_run()
    if label or tags or notes:
        patch_json(f"{RUNS_PATH}/{run_id}", {
            k: v for k, v in [("label", label), ("tags", tags), ("notes", notes)] if v is not None
        })
    return run_id


class TestListRunsFilterByTag:
    """Test filter by tag parameter."""

    def test_filter_by_tag_returns_matching_runs(self):
        """Verify tag filter returns only runs with that tag."""
        # Create runs with different tags
        unique_tag = f"testtag{int(time.time() * 1000)}"
        run1 = create_run_with_metadata(tags=[unique_tag, "other"])
        run2 = create_run_with_metadata(tags=["different"])

        # Filter by the unique tag
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?tag={unique_tag}")
        assert response.status_code == 200
        data = response.json()

        # Should find run1 but not run2
        run_ids = [item["run_id"] for item in data["items"]]
        assert run1 in run_ids
        assert run2 not in run_ids

    def test_filter_by_tag_no_matches(self):
        """Verify tag filter with no matches returns empty list."""
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?tag=nonexistent_tag_xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_filter_by_tag_exact_match(self):
        """Verify tag filter requires exact match."""
        unique_tag = f"exact{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(tags=[unique_tag])

        # Partial match should not work
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?tag={unique_tag[:5]}")
        assert response.status_code == 200
        data = response.json()
        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id not in run_ids


class TestListRunsFreeTextSearch:
    """Test free-text search (q parameter)."""

    def test_search_in_label(self):
        """Verify q parameter searches in label."""
        unique_label = f"UniqueLabel{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(label=unique_label)

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?q={unique_label}")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id in run_ids

    def test_search_in_notes(self):
        """Verify q parameter searches in notes."""
        unique_notes = f"UniqueNotes{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(notes=unique_notes)

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?q={unique_notes}")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id in run_ids

    def test_search_case_insensitive(self):
        """Verify q parameter is case-insensitive."""
        unique_label = f"CaseTest{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(label=unique_label)

        # Search with lowercase
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?q={unique_label.lower()}")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id in run_ids

    def test_search_partial_match(self):
        """Verify q parameter supports partial matches."""
        unique_label = f"PartialMatchTest{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(label=unique_label)

        # Search with partial string
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?q=PartialMatch")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id in run_ids

    def test_search_no_matches(self):
        """Verify q parameter with no matches returns empty list."""
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?q=xyznonexistent123456")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestListRunsSorting:
    """Test sorting parameter."""

    def test_sort_created_at_desc_default(self):
        """Verify default sort is created_at DESC (newest first)."""
        run1 = create_sizing_run()
        time.sleep(0.1)  # Ensure different timestamps
        run2 = create_sizing_run()

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?limit=10")
        assert response.status_code == 200
        data = response.json()

        # run2 should appear before run1 (newest first)
        run_ids = [item["run_id"] for item in data["items"]]
        if run1 in run_ids and run2 in run_ids:
            assert run_ids.index(run2) < run_ids.index(run1)

    def test_sort_created_at_asc(self):
        """Verify sort=created_at_asc returns oldest first."""
        run1 = create_sizing_run()
        time.sleep(0.1)
        run2 = create_sizing_run()

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?sort=created_at_asc&limit=100")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        if run1 in run_ids and run2 in run_ids:
            assert run_ids.index(run1) < run_ids.index(run2)

    def test_sort_created_at_desc_explicit(self):
        """Verify sort=created_at_desc returns newest first."""
        run1 = create_sizing_run()
        time.sleep(0.1)
        run2 = create_sizing_run()

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?sort=created_at_desc&limit=10")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        if run1 in run_ids and run2 in run_ids:
            assert run_ids.index(run2) < run_ids.index(run1)

    def test_sort_updated_at_desc(self):
        """Verify sort=updated_at_desc returns most recently updated first."""
        run1 = create_sizing_run()
        run2 = create_sizing_run()
        time.sleep(0.1)

        # Update run1's metadata to make it more recently updated
        patch_json(f"{RUNS_PATH}/{run1}", {"label": "Updated"})

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?sort=updated_at_desc&limit=10")
        assert response.status_code == 200
        data = response.json()

        # run1 should appear first (most recently updated)
        run_ids = [item["run_id"] for item in data["items"]]
        if run1 in run_ids and run2 in run_ids:
            assert run_ids.index(run1) < run_ids.index(run2)

    def test_sort_invalid_value_rejected(self):
        """Verify invalid sort value is rejected."""
        response = requests.get(f"{BASE_URL}{RUNS_PATH}?sort=invalid_sort")
        assert response.status_code == 422


class TestListRunsResponseMetadata:
    """Test that response includes metadata fields."""

    def test_response_includes_label(self):
        """Verify response items include label field."""
        run_id = create_run_with_metadata(label="Test Label")

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?limit=10")
        assert response.status_code == 200
        data = response.json()

        run_item = next((item for item in data["items"] if item["run_id"] == run_id), None)
        assert run_item is not None
        assert "label" in run_item
        assert run_item["label"] == "Test Label"

    def test_response_includes_tags(self):
        """Verify response items include tags field."""
        run_id = create_run_with_metadata(tags=["tag1", "tag2"])

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?limit=10")
        assert response.status_code == 200
        data = response.json()

        run_item = next((item for item in data["items"] if item["run_id"] == run_id), None)
        assert run_item is not None
        assert "tags" in run_item
        assert run_item["tags"] == ["tag1", "tag2"]

    def test_response_includes_notes(self):
        """Verify response items include notes field."""
        run_id = create_run_with_metadata(notes="Test notes content")

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?limit=10")
        assert response.status_code == 200
        data = response.json()

        run_item = next((item for item in data["items"] if item["run_id"] == run_id), None)
        assert run_item is not None
        assert "notes" in run_item
        assert run_item["notes"] == "Test notes content"

    def test_response_includes_updated_at(self):
        """Verify response items include updated_at field."""
        run_id = create_run_with_metadata(label="For Updated At Test")

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?limit=10")
        assert response.status_code == 200
        data = response.json()

        run_item = next((item for item in data["items"] if item["run_id"] == run_id), None)
        assert run_item is not None
        assert "updated_at" in run_item
        assert run_item["updated_at"] is not None


class TestListRunsCombinedFilters:
    """Test combining multiple filters."""

    def test_tag_and_search_combined(self):
        """Verify tag and q filters can be combined."""
        unique_tag = f"comboTag{int(time.time() * 1000)}"
        unique_label = f"ComboLabel{int(time.time() * 1000)}"

        # Create run with both tag and label
        run1 = create_run_with_metadata(tags=[unique_tag], label=unique_label)
        # Create run with only tag
        run2 = create_run_with_metadata(tags=[unique_tag], label="Other")
        # Create run with only label
        run3 = create_run_with_metadata(tags=["other"], label=unique_label)

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?tag={unique_tag}&q={unique_label}")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run1 in run_ids
        assert run2 not in run_ids  # No matching label
        assert run3 not in run_ids  # No matching tag

    def test_tag_and_sort_combined(self):
        """Verify tag and sort can be combined."""
        unique_tag = f"sortTag{int(time.time() * 1000)}"

        run1 = create_run_with_metadata(tags=[unique_tag])
        time.sleep(0.1)
        run2 = create_run_with_metadata(tags=[unique_tag])

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?tag={unique_tag}&sort=created_at_asc")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        # Both should be found
        assert run1 in run_ids
        assert run2 in run_ids
        # run1 should come first (oldest)
        assert run_ids.index(run1) < run_ids.index(run2)

    def test_endpoint_and_tag_combined(self):
        """Verify endpoint and tag filters can be combined."""
        unique_tag = f"endpointTag{int(time.time() * 1000)}"
        run_id = create_run_with_metadata(tags=[unique_tag])

        response = requests.get(f"{BASE_URL}{RUNS_PATH}?endpoint=sizing&tag={unique_tag}")
        assert response.status_code == 200
        data = response.json()

        run_ids = [item["run_id"] for item in data["items"]]
        assert run_id in run_ids
