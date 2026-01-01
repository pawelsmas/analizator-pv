"""
Unit tests for artifact_store module (v3.5.0 PR4).

Tests verify:
- LocalArtifactStore operations
- S3ArtifactStore with mocks
- Backend factory and fallback
- ArtifactMetadata structure
"""

import pytest
import sys
import os
import io
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestArtifactMetadata:
    """Tests for ArtifactMetadata dataclass."""

    def test_metadata_structure(self):
        """ArtifactMetadata should have correct structure."""
        from artifact_store import ArtifactMetadata

        metadata = ArtifactMetadata(
            artifact_id="test-id",
            job_id="job-123",
            filename="result.json",
            content_type="application/json",
            size_bytes=1024,
            created_at="2024-01-01T00:00:00Z",
            checksum="abc123",
        )

        assert metadata.artifact_id == "test-id"
        assert metadata.job_id == "job-123"
        assert metadata.filename == "result.json"
        assert metadata.content_type == "application/json"
        assert metadata.size_bytes == 1024
        assert metadata.checksum == "abc123"

    def test_metadata_optional_checksum(self):
        """ArtifactMetadata should allow None checksum."""
        from artifact_store import ArtifactMetadata

        metadata = ArtifactMetadata(
            artifact_id="test-id",
            job_id="job-123",
            filename="result.json",
            content_type="application/json",
            size_bytes=1024,
            created_at="2024-01-01T00:00:00Z",
        )

        assert metadata.checksum is None


class TestLocalArtifactStore:
    """Tests for local filesystem artifact store."""

    def test_store_and_get(self):
        """Should store and retrieve artifact."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            # Store artifact
            data = io.BytesIO(b"test content")
            metadata = store.store(
                job_id="job-1",
                filename="test.txt",
                data=data,
                content_type="text/plain",
            )

            assert metadata.artifact_id is not None
            assert metadata.job_id == "job-1"
            assert metadata.filename == "test.txt"
            assert metadata.size_bytes == 12

            # Retrieve artifact
            retrieved = store.get(metadata.artifact_id)
            assert retrieved is not None
            assert retrieved.read() == b"test content"

    def test_get_metadata(self):
        """Should retrieve artifact metadata."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            data = io.BytesIO(b"test content")
            stored = store.store("job-1", "test.txt", data)

            metadata = store.get_metadata(stored.artifact_id)
            assert metadata is not None
            assert metadata.artifact_id == stored.artifact_id
            assert metadata.filename == "test.txt"

    def test_list_by_job(self):
        """Should list all artifacts for a job."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            # Store multiple artifacts
            store.store("job-1", "file1.txt", io.BytesIO(b"content1"))
            store.store("job-1", "file2.txt", io.BytesIO(b"content2"))
            store.store("job-2", "file3.txt", io.BytesIO(b"content3"))

            # List for job-1
            artifacts = store.list_by_job("job-1")
            assert len(artifacts) == 2
            filenames = {a.filename for a in artifacts}
            assert filenames == {"file1.txt", "file2.txt"}

    def test_delete_artifact(self):
        """Should delete artifact by ID."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            data = io.BytesIO(b"test content")
            stored = store.store("job-1", "test.txt", data)

            # Delete
            result = store.delete(stored.artifact_id)
            assert result is True

            # Verify deleted
            assert store.get(stored.artifact_id) is None

    def test_delete_by_job(self):
        """Should delete all artifacts for a job."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            # Store multiple artifacts
            store.store("job-1", "file1.txt", io.BytesIO(b"content1"))
            store.store("job-1", "file2.txt", io.BytesIO(b"content2"))
            store.store("job-2", "file3.txt", io.BytesIO(b"content3"))

            # Delete all for job-1
            count = store.delete_by_job("job-1")
            assert count == 2

            # Verify job-1 artifacts deleted
            assert len(store.list_by_job("job-1")) == 0

            # Verify job-2 artifacts still exist
            assert len(store.list_by_job("job-2")) == 1

    def test_is_available(self):
        """Local store should always be available."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)
            assert store.is_available() is True

    def test_checksum_computed(self):
        """Should compute SHA-256 checksum."""
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)

            data = io.BytesIO(b"test content")
            metadata = store.store("job-1", "test.txt", data)

            assert metadata.checksum is not None
            assert len(metadata.checksum) == 64  # SHA-256 hex length


class TestS3ArtifactStore:
    """Tests for S3/MinIO artifact store."""

    def test_not_available_when_no_config(self):
        """S3 store should be unavailable with no config."""
        from artifact_store import S3ArtifactStore

        store = S3ArtifactStore(endpoint="", bucket="")
        assert store.is_available() is False

    def test_store_with_mock(self):
        """Should store artifact via mock S3 client."""
        from artifact_store import S3ArtifactStore

        store = S3ArtifactStore(
            endpoint="http://localhost:9000",
            bucket="test-bucket",
            access_key="test",
            secret_key="test",
        )

        # Mock the S3 client
        mock_client = MagicMock()
        store._client = mock_client

        data = io.BytesIO(b"test content")
        metadata = store.store("job-1", "test.txt", data)

        assert metadata.artifact_id is not None
        assert metadata.job_id == "job-1"
        assert mock_client.put_object.call_count == 2  # data + meta

    def test_get_with_mock(self):
        """Should retrieve artifact via mock S3 client."""
        from artifact_store import S3ArtifactStore

        store = S3ArtifactStore(
            endpoint="http://localhost:9000",
            bucket="test-bucket",
            access_key="test",
            secret_key="test",
        )

        # Mock the S3 client
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {'Contents': [{'Key': 'job-1/test-id/data'}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.get_object.return_value = {
            'Body': io.BytesIO(b"test content")
        }
        store._client = mock_client

        result = store.get("test-id")
        assert result is not None


class TestBackendFactory:
    """Tests for artifact store backend factory."""

    def test_factory_returns_local_by_default(self):
        """Factory should return local backend by default."""
        from artifact_store import get_artifact_store, reset_store, LocalArtifactStore

        reset_store()

        with patch.dict(os.environ, {"ARTIFACT_STORE_BACKEND": "local"}):
            import artifact_store
            import importlib
            importlib.reload(artifact_store)

            store = artifact_store.get_artifact_store()
            assert isinstance(store, artifact_store.LocalArtifactStore)

        importlib.reload(artifact_store)

    def test_factory_caches_store(self):
        """Factory should return same store instance."""
        from artifact_store import get_artifact_store, reset_store

        reset_store()

        store1 = get_artifact_store()
        store2 = get_artifact_store()

        assert store1 is store2


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_store_artifact(self):
        """store_artifact should work."""
        from artifact_store import store_artifact, reset_store, LocalArtifactStore

        reset_store()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ARTIFACT_STORE_PATH": tmpdir}):
                import artifact_store
                import importlib
                importlib.reload(artifact_store)

                data = io.BytesIO(b"test content")
                metadata = artifact_store.store_artifact(
                    "job-1", "test.txt", data, "text/plain"
                )

                assert metadata.job_id == "job-1"
                assert metadata.filename == "test.txt"

            importlib.reload(artifact_store)

    def test_get_artifact(self):
        """get_artifact should work."""
        from artifact_store import reset_store

        reset_store()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ARTIFACT_STORE_PATH": tmpdir}):
                import artifact_store
                import importlib
                importlib.reload(artifact_store)

                data = io.BytesIO(b"test content")
                stored = artifact_store.store_artifact("job-1", "test.txt", data)

                retrieved = artifact_store.get_artifact(stored.artifact_id)
                assert retrieved is not None
                assert retrieved.read() == b"test content"

            importlib.reload(artifact_store)

    def test_list_job_artifacts(self):
        """list_job_artifacts should work."""
        from artifact_store import reset_store

        reset_store()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ARTIFACT_STORE_PATH": tmpdir}):
                import artifact_store
                import importlib
                importlib.reload(artifact_store)

                artifact_store.store_artifact("job-1", "f1.txt", io.BytesIO(b"c1"))
                artifact_store.store_artifact("job-1", "f2.txt", io.BytesIO(b"c2"))

                artifacts = artifact_store.list_job_artifacts("job-1")
                assert len(artifacts) == 2

            importlib.reload(artifact_store)

    def test_delete_artifact(self):
        """delete_artifact should work."""
        from artifact_store import reset_store

        reset_store()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ARTIFACT_STORE_PATH": tmpdir}):
                import artifact_store
                import importlib
                importlib.reload(artifact_store)

                stored = artifact_store.store_artifact(
                    "job-1", "test.txt", io.BytesIO(b"content")
                )

                result = artifact_store.delete_artifact(stored.artifact_id)
                assert result is True

                assert artifact_store.get_artifact(stored.artifact_id) is None

            importlib.reload(artifact_store)
