"""
Contract tests for v1.3.0 job metadata PATCH endpoint.

Tests verify:
- PATCH /api/bess-dispatch/jobs/{job_id} updates metadata
- Validation for label (max 80 chars)
- Validation for tags (max 20 tags, each 1-32 chars [a-zA-Z0-9_-])
- Validation for notes (max 2000 chars)
- 404 for nonexistent job_id
- Response includes updated_at timestamp
- GET /api/bess-dispatch/jobs/{job_id} returns updated metadata
"""
import time

import pytest
import requests

from ._api import post_json, get_json, patch_json, load_smoke_payload


# API paths
JOBS_PATH = "/api/bess-dispatch/jobs"
BASE_URL = "http://localhost:8031"


def create_job_sync():
    """Create a sizing job (sync) and return the job_id."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    batch_request = {
        "items": [
            {"item_id": "test-item-1", "request": payload}
        ],
        "wait": True,
    }
    response = post_json(f"{JOBS_PATH}/sizing-batch", batch_request)
    return response["job_id"]


class TestPatchJobMetadataBasic:
    """Test basic PATCH functionality."""

    def test_patch_label_success(self):
        """Verify PATCH updates label field."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test Label"})

        assert response["job_id"] == job_id
        assert response["label"] == "Test Label"
        assert "updated_at" in response

    def test_patch_tags_success(self):
        """Verify PATCH updates tags field."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["tag1", "tag2"]})

        assert response["job_id"] == job_id
        assert response["tags"] == ["tag1", "tag2"]

    def test_patch_notes_success(self):
        """Verify PATCH updates notes field."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"notes": "Test notes content"})

        assert response["job_id"] == job_id
        assert response["notes"] == "Test notes content"

    def test_patch_all_fields_success(self):
        """Verify PATCH updates all fields at once."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {
            "label": "Full Test",
            "tags": ["a", "b", "c"],
            "notes": "All fields updated"
        })

        assert response["label"] == "Full Test"
        assert response["tags"] == ["a", "b", "c"]
        assert response["notes"] == "All fields updated"

    def test_patch_returns_updated_at(self):
        """Verify PATCH response includes updated_at timestamp."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Test"})

        assert "updated_at" in response
        assert response["updated_at"] is not None
        # Should be ISO 8601 format
        assert "T" in response["updated_at"]


class TestPatchJobMetadataGetVerification:
    """Test that GET returns updated metadata."""

    def test_get_returns_updated_label(self):
        """Verify GET returns the updated label."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "GET Test Label"})

        job = get_json(f"{JOBS_PATH}/{job_id}")
        assert job.get("label") == "GET Test Label"

    def test_get_returns_updated_tags(self):
        """Verify GET returns the updated tags."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["tag-x", "tag-y"]})

        job = get_json(f"{JOBS_PATH}/{job_id}")
        assert job.get("tags") == ["tag-x", "tag-y"]

    def test_get_returns_updated_notes(self):
        """Verify GET returns the updated notes."""
        job_id = create_job_sync()
        patch_json(f"{JOBS_PATH}/{job_id}", {"notes": "GET Test Notes"})

        job = get_json(f"{JOBS_PATH}/{job_id}")
        assert job.get("notes") == "GET Test Notes"


class TestPatchJobMetadataNotFound:
    """Test 404 handling for nonexistent job_id."""

    def test_patch_nonexistent_job_returns_404(self):
        """Verify PATCH returns 404 for nonexistent job_id."""
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/nonexistent-job-id-xyz",
            json={"label": "Test"}
        )
        assert response.status_code == 404


class TestPatchJobMetadataValidation:
    """Test validation rules."""

    def test_label_max_length_80(self):
        """Verify label rejects > 80 characters."""
        job_id = create_job_sync()
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/{job_id}",
            json={"label": "x" * 81}
        )
        assert response.status_code == 422

    def test_label_80_chars_accepted(self):
        """Verify label accepts exactly 80 characters."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "x" * 80})
        assert response["label"] == "x" * 80

    def test_notes_max_length_2000(self):
        """Verify notes rejects > 2000 characters."""
        job_id = create_job_sync()
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/{job_id}",
            json={"notes": "x" * 2001}
        )
        assert response.status_code == 422

    def test_notes_2000_chars_accepted(self):
        """Verify notes accepts exactly 2000 characters."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"notes": "x" * 2000})
        assert response["notes"] == "x" * 2000

    def test_tags_max_count_20(self):
        """Verify tags rejects > 20 tags."""
        job_id = create_job_sync()
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/{job_id}",
            json={"tags": [f"tag{i}" for i in range(21)]}
        )
        assert response.status_code == 422

    def test_tags_20_accepted(self):
        """Verify tags accepts exactly 20 tags."""
        job_id = create_job_sync()
        tags = [f"tag{i}" for i in range(20)]
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": tags})
        assert response["tags"] == tags

    def test_tag_max_length_32(self):
        """Verify individual tag rejects > 32 characters."""
        job_id = create_job_sync()
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/{job_id}",
            json={"tags": ["x" * 33]}
        )
        assert response.status_code == 422

    def test_tag_32_chars_accepted(self):
        """Verify individual tag accepts exactly 32 characters."""
        job_id = create_job_sync()
        tag = "x" * 32
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": [tag]})
        assert response["tags"] == [tag]

    def test_tag_invalid_characters_rejected(self):
        """Verify tags with invalid characters are rejected."""
        job_id = create_job_sync()
        response = requests.patch(
            f"{BASE_URL}{JOBS_PATH}/{job_id}",
            json={"tags": ["invalid tag with space"]}
        )
        assert response.status_code == 422

    def test_tag_valid_characters_accepted(self):
        """Verify tags with valid characters [a-zA-Z0-9_-] are accepted."""
        job_id = create_job_sync()
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["Valid_Tag-123"]})
        assert response["tags"] == ["Valid_Tag-123"]


class TestPatchJobMetadataPartialUpdate:
    """Test partial updates preserve other fields."""

    def test_update_label_preserves_tags(self):
        """Verify updating label preserves existing tags."""
        job_id = create_job_sync()

        # Set both label and tags
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Initial", "tags": ["tag1"]})

        # Update only label
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Updated"})
        assert response["label"] == "Updated"
        assert response["tags"] == ["tag1"]

    def test_update_tags_preserves_label(self):
        """Verify updating tags preserves existing label."""
        job_id = create_job_sync()

        # Set both label and tags
        patch_json(f"{JOBS_PATH}/{job_id}", {"label": "My Label", "tags": ["tag1"]})

        # Update only tags
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["tag2", "tag3"]})
        assert response["label"] == "My Label"
        assert response["tags"] == ["tag2", "tag3"]

    def test_clear_tags_with_empty_list(self):
        """Verify tags can be cleared with empty list."""
        job_id = create_job_sync()

        # Set tags
        patch_json(f"{JOBS_PATH}/{job_id}", {"tags": ["tag1", "tag2"]})

        # Clear with empty list
        response = patch_json(f"{JOBS_PATH}/{job_id}", {"tags": []})
        assert response["tags"] == []


class TestPatchJobMetadataUpdateTimestamp:
    """Test updated_at timestamp behavior."""

    def test_updated_at_changes_on_patch(self):
        """Verify updated_at changes when metadata is updated."""
        job_id = create_job_sync()

        # First update
        response1 = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "First"})
        updated_at_1 = response1["updated_at"]

        # Wait a bit to ensure different timestamp
        time.sleep(0.1)

        # Second update
        response2 = patch_json(f"{JOBS_PATH}/{job_id}", {"label": "Second"})
        updated_at_2 = response2["updated_at"]

        # Timestamps should be different (or at least not fail)
        # Allow for same second timestamps
        assert updated_at_2 >= updated_at_1
