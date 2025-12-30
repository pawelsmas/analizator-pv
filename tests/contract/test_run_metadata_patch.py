"""
Contract tests for v1.3.0 run metadata PATCH endpoint.

Tests verify:
- PATCH /runs/{run_id} updates label, tags, notes
- Validation rules are enforced (tag format, lengths, counts)
- Error responses for invalid input
- 404 for nonexistent runs
"""
import uuid

import pytest

from ._api import post_json, get_json, patch_json, load_smoke_payload


# API paths
SIZING_PATH = "/sizing"
RUNS_PATH = "/runs"


def create_sizing_run():
    """Create a sizing run and return the run_id."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    response = post_json(SIZING_PATH, payload)
    return response["cache_info"]["run_id"]


class TestPatchRunLabelOnly:
    """Test PATCH with label only."""

    def test_patch_run_label_only(self):
        """Verify PATCH with label updates label field."""
        run_id = create_sizing_run()

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Test Label"})

        assert result["run_id"] == run_id
        assert result["label"] == "Test Label"

    def test_patch_run_label_persisted(self):
        """Verify label is persisted in storage."""
        run_id = create_sizing_run()

        patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Persisted Label"})

        # Fetch and verify
        stored = get_json(f"{RUNS_PATH}/{run_id}")
        assert stored["label"] == "Persisted Label"


class TestPatchRunTags:
    """Test PATCH with tags."""

    def test_patch_run_tags(self):
        """Verify PATCH with tags updates tags field."""
        run_id = create_sizing_run()

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["tag1", "tag2", "test-tag"]})

        assert result["run_id"] == run_id
        assert result["tags"] == ["tag1", "tag2", "test-tag"]

    def test_patch_run_tags_persisted(self):
        """Verify tags are persisted in storage."""
        run_id = create_sizing_run()

        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["persisted", "tags"]})

        stored = get_json(f"{RUNS_PATH}/{run_id}")
        assert stored["tags"] == ["persisted", "tags"]

    def test_patch_run_tags_with_underscores_and_dashes(self):
        """Verify tags can contain underscores and dashes."""
        run_id = create_sizing_run()

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["my_tag", "my-tag", "tag_with-both"]})

        assert result["tags"] == ["my_tag", "my-tag", "tag_with-both"]


class TestPatchRunNotes:
    """Test PATCH with notes."""

    def test_patch_run_notes(self):
        """Verify PATCH with notes updates notes field."""
        run_id = create_sizing_run()

        notes_text = "This is a test note for the sizing run."
        result = patch_json(f"{RUNS_PATH}/{run_id}", {"notes": notes_text})

        assert result["run_id"] == run_id
        assert result["notes"] == notes_text

    def test_patch_run_notes_persisted(self):
        """Verify notes are persisted in storage."""
        run_id = create_sizing_run()

        notes_text = "Persisted notes content."
        patch_json(f"{RUNS_PATH}/{run_id}", {"notes": notes_text})

        stored = get_json(f"{RUNS_PATH}/{run_id}")
        assert stored["notes"] == notes_text

    def test_patch_run_notes_multiline(self):
        """Verify notes can contain multiple lines."""
        run_id = create_sizing_run()

        notes_text = "Line 1\nLine 2\nLine 3"
        result = patch_json(f"{RUNS_PATH}/{run_id}", {"notes": notes_text})

        assert result["notes"] == notes_text


class TestPatchRunAllFields:
    """Test PATCH with all fields."""

    def test_patch_run_all_fields(self):
        """Verify PATCH with all fields updates all."""
        run_id = create_sizing_run()

        result = patch_json(f"{RUNS_PATH}/{run_id}", {
            "label": "Full Update",
            "tags": ["complete", "test"],
            "notes": "All fields updated."
        })

        assert result["run_id"] == run_id
        assert result["label"] == "Full Update"
        assert result["tags"] == ["complete", "test"]
        assert result["notes"] == "All fields updated."

    def test_patch_run_updated_at_is_iso(self):
        """Verify updated_at is ISO format timestamp."""
        run_id = create_sizing_run()

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"label": "ISO Test"})

        assert "updated_at" in result
        # ISO format: YYYY-MM-DDTHH:MM:SS...
        assert "T" in result["updated_at"]
        assert len(result["updated_at"]) >= 19  # At least YYYY-MM-DDTHH:MM:SS


class TestPatchRunClearTags:
    """Test clearing tags."""

    def test_patch_run_clear_tags(self):
        """Verify sending tags=[] clears tags."""
        run_id = create_sizing_run()

        # First set some tags
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["initial", "tags"]})

        # Then clear them
        result = patch_json(f"{RUNS_PATH}/{run_id}", {"tags": []})

        # Empty list should result in null/empty tags
        assert result["tags"] is None or result["tags"] == []

    def test_patch_run_clear_tags_persisted(self):
        """Verify cleared tags are persisted."""
        run_id = create_sizing_run()

        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["to", "clear"]})
        patch_json(f"{RUNS_PATH}/{run_id}", {"tags": []})

        stored = get_json(f"{RUNS_PATH}/{run_id}")
        assert stored["tags"] is None or stored["tags"] == []


class TestPatchRunInvalidTagChars:
    """Test validation of tag characters."""

    def test_patch_run_invalid_tag_chars_space(self):
        """Verify tags with spaces are rejected."""
        run_id = create_sizing_run()

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["invalid tag"]})

        assert "422" in str(exc_info.value)

    def test_patch_run_invalid_tag_chars_special(self):
        """Verify tags with special characters are rejected."""
        run_id = create_sizing_run()

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["invalid@tag"]})

        assert "422" in str(exc_info.value)

    def test_patch_run_invalid_tag_chars_unicode(self):
        """Verify tags with unicode are rejected."""
        run_id = create_sizing_run()

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"tags": ["täg"]})

        assert "422" in str(exc_info.value)


class TestPatchRunTagTooLong:
    """Test validation of tag length."""

    def test_patch_run_tag_too_long(self):
        """Verify tag over 32 chars is rejected."""
        run_id = create_sizing_run()

        long_tag = "a" * 40  # 40 chars, max is 32

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"tags": [long_tag]})

        assert "422" in str(exc_info.value)

    def test_patch_run_tag_at_limit(self):
        """Verify tag at exactly 32 chars is accepted."""
        run_id = create_sizing_run()

        tag_at_limit = "a" * 32

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"tags": [tag_at_limit]})

        assert tag_at_limit in result["tags"]


class TestPatchRunTooManyTags:
    """Test validation of tag count."""

    def test_patch_run_too_many_tags(self):
        """Verify more than 20 tags is rejected."""
        run_id = create_sizing_run()

        too_many_tags = [f"tag{i}" for i in range(25)]  # 25 tags, max is 20

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"tags": too_many_tags})

        assert "422" in str(exc_info.value)

    def test_patch_run_tags_at_limit(self):
        """Verify exactly 20 tags is accepted."""
        run_id = create_sizing_run()

        tags_at_limit = [f"tag{i}" for i in range(20)]

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"tags": tags_at_limit})

        assert len(result["tags"]) == 20


class TestPatchRunNotFound:
    """Test 404 for nonexistent runs."""

    def test_patch_run_not_found(self):
        """Verify PATCH on nonexistent run returns 404."""
        random_uuid = str(uuid.uuid4())

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{random_uuid}", {"label": "Not Found"})

        assert "404" in str(exc_info.value)


class TestPatchRunLabelValidation:
    """Test label validation."""

    def test_patch_run_label_too_long(self):
        """Verify label over 80 chars is rejected."""
        run_id = create_sizing_run()

        long_label = "a" * 100  # 100 chars, max is 80

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"label": long_label})

        assert "422" in str(exc_info.value)

    def test_patch_run_label_at_limit(self):
        """Verify label at exactly 80 chars is accepted."""
        run_id = create_sizing_run()

        label_at_limit = "a" * 80

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"label": label_at_limit})

        assert result["label"] == label_at_limit


class TestPatchRunNotesValidation:
    """Test notes validation."""

    def test_patch_run_notes_too_long(self):
        """Verify notes over 2000 chars is rejected."""
        run_id = create_sizing_run()

        long_notes = "a" * 2500  # 2500 chars, max is 2000

        with pytest.raises(AssertionError) as exc_info:
            patch_json(f"{RUNS_PATH}/{run_id}", {"notes": long_notes})

        assert "422" in str(exc_info.value)

    def test_patch_run_notes_at_limit(self):
        """Verify notes at exactly 2000 chars is accepted."""
        run_id = create_sizing_run()

        notes_at_limit = "a" * 2000

        result = patch_json(f"{RUNS_PATH}/{run_id}", {"notes": notes_at_limit})

        assert result["notes"] == notes_at_limit


class TestPatchRunPartialUpdate:
    """Test partial updates preserve other fields."""

    def test_patch_run_preserves_other_fields(self):
        """Verify updating one field preserves others."""
        run_id = create_sizing_run()

        # Set all fields
        patch_json(f"{RUNS_PATH}/{run_id}", {
            "label": "Initial Label",
            "tags": ["initial"],
            "notes": "Initial notes."
        })

        # Update only label
        result = patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Updated Label"})

        assert result["label"] == "Updated Label"
        assert result["tags"] == ["initial"]
        assert result["notes"] == "Initial notes."

    def test_patch_run_empty_request_noop(self):
        """Verify empty PATCH request is a no-op."""
        run_id = create_sizing_run()

        # Set initial values
        patch_json(f"{RUNS_PATH}/{run_id}", {"label": "Keep Me"})

        # Send empty update
        result = patch_json(f"{RUNS_PATH}/{run_id}", {})

        # Label should be preserved
        assert result["label"] == "Keep Me"
