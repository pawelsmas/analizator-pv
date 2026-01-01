"""
Artifact Store for job artifacts (v3.5.0).

Provides pluggable storage backends for job artifacts:
- local: Local filesystem storage (single replica only)
- s3: S3/MinIO storage (HA, multi-replica safe)

Configuration via environment variables:
- ARTIFACT_STORE_BACKEND: Backend type - local|s3 (default: local)
- ARTIFACT_STORE_PATH: Local storage path (default: /data/artifacts)
- S3_ENDPOINT: S3/MinIO endpoint URL
- S3_BUCKET: S3 bucket name (default: bess-artifacts)
- S3_ACCESS_KEY: S3 access key
- S3_SECRET_KEY: S3 secret key
- S3_REGION: S3 region (default: us-east-1)
"""

import io
import json
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

ARTIFACT_STORE_BACKEND = os.getenv("ARTIFACT_STORE_BACKEND", "local").lower()
ARTIFACT_STORE_PATH = os.getenv("ARTIFACT_STORE_PATH", "/data/artifacts")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_BUCKET = os.getenv("S3_BUCKET", "bess-artifacts")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")


# -----------------------------------------------------------------------------
# Artifact Metadata
# -----------------------------------------------------------------------------

@dataclass
class ArtifactMetadata:
    """Metadata for a stored artifact."""
    artifact_id: str
    job_id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: str
    checksum: Optional[str] = None


# -----------------------------------------------------------------------------
# Artifact Store Backend Interface
# -----------------------------------------------------------------------------

class ArtifactStoreBackend(ABC):
    """Abstract base class for artifact storage backends."""

    @abstractmethod
    def store(
        self,
        job_id: str,
        filename: str,
        data: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> ArtifactMetadata:
        """
        Store an artifact.

        Args:
            job_id: Job identifier
            filename: Original filename
            data: Binary data stream
            content_type: MIME type

        Returns:
            ArtifactMetadata with artifact ID and metadata
        """
        pass

    @abstractmethod
    def get(self, artifact_id: str) -> Optional[BinaryIO]:
        """
        Retrieve an artifact by ID.

        Args:
            artifact_id: Artifact identifier

        Returns:
            Binary data stream or None if not found
        """
        pass

    @abstractmethod
    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """
        Get artifact metadata by ID.

        Args:
            artifact_id: Artifact identifier

        Returns:
            ArtifactMetadata or None if not found
        """
        pass

    @abstractmethod
    def list_by_job(self, job_id: str) -> List[ArtifactMetadata]:
        """
        List all artifacts for a job.

        Args:
            job_id: Job identifier

        Returns:
            List of ArtifactMetadata
        """
        pass

    @abstractmethod
    def delete(self, artifact_id: str) -> bool:
        """
        Delete an artifact by ID.

        Args:
            artifact_id: Artifact identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def delete_by_job(self, job_id: str) -> int:
        """
        Delete all artifacts for a job.

        Args:
            job_id: Job identifier

        Returns:
            Number of artifacts deleted
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


# -----------------------------------------------------------------------------
# Local Filesystem Backend
# -----------------------------------------------------------------------------

class LocalArtifactStore(ArtifactStoreBackend):
    """
    Local filesystem artifact storage.

    Directory structure:
    {base_path}/
      {job_id}/
        {artifact_id}.data - artifact data
        {artifact_id}.meta - JSON metadata
    """

    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or ARTIFACT_STORE_PATH)
        self._ensure_base_path()

    def _ensure_base_path(self):
        """Create base path if it doesn't exist."""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        """Get path for job artifacts."""
        return self.base_path / job_id

    def _artifact_data_path(self, job_id: str, artifact_id: str) -> Path:
        """Get path for artifact data file."""
        return self._job_path(job_id) / f"{artifact_id}.data"

    def _artifact_meta_path(self, job_id: str, artifact_id: str) -> Path:
        """Get path for artifact metadata file."""
        return self._job_path(job_id) / f"{artifact_id}.meta"

    def _compute_checksum(self, data: bytes) -> str:
        """Compute SHA-256 checksum of data."""
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def store(
        self,
        job_id: str,
        filename: str,
        data: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> ArtifactMetadata:
        """Store artifact to local filesystem."""
        # Generate artifact ID
        artifact_id = str(uuid.uuid4())

        # Ensure job directory exists
        job_path = self._job_path(job_id)
        job_path.mkdir(parents=True, exist_ok=True)

        # Read data and compute size/checksum
        content = data.read()
        size_bytes = len(content)
        checksum = self._compute_checksum(content)

        # Write data file
        data_path = self._artifact_data_path(job_id, artifact_id)
        with open(data_path, "wb") as f:
            f.write(content)

        # Create metadata
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            job_id=job_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=datetime.now(timezone.utc).isoformat(),
            checksum=checksum,
        )

        # Write metadata file
        meta_path = self._artifact_meta_path(job_id, artifact_id)
        with open(meta_path, "w") as f:
            json.dump({
                "artifact_id": metadata.artifact_id,
                "job_id": metadata.job_id,
                "filename": metadata.filename,
                "content_type": metadata.content_type,
                "size_bytes": metadata.size_bytes,
                "created_at": metadata.created_at,
                "checksum": metadata.checksum,
            }, f)

        return metadata

    def get(self, artifact_id: str) -> Optional[BinaryIO]:
        """Retrieve artifact from local filesystem."""
        # Find the artifact by searching job directories
        for job_dir in self.base_path.iterdir():
            if job_dir.is_dir():
                data_path = job_dir / f"{artifact_id}.data"
                if data_path.exists():
                    return io.BytesIO(data_path.read_bytes())
        return None

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata from local filesystem."""
        for job_dir in self.base_path.iterdir():
            if job_dir.is_dir():
                meta_path = job_dir / f"{artifact_id}.meta"
                if meta_path.exists():
                    with open(meta_path, "r") as f:
                        data = json.load(f)
                        return ArtifactMetadata(**data)
        return None

    def list_by_job(self, job_id: str) -> List[ArtifactMetadata]:
        """List all artifacts for a job."""
        job_path = self._job_path(job_id)
        if not job_path.exists():
            return []

        artifacts = []
        for meta_file in job_path.glob("*.meta"):
            with open(meta_file, "r") as f:
                data = json.load(f)
                artifacts.append(ArtifactMetadata(**data))

        return artifacts

    def delete(self, artifact_id: str) -> bool:
        """Delete artifact from local filesystem."""
        for job_dir in self.base_path.iterdir():
            if job_dir.is_dir():
                data_path = job_dir / f"{artifact_id}.data"
                meta_path = job_dir / f"{artifact_id}.meta"
                if data_path.exists():
                    data_path.unlink()
                    if meta_path.exists():
                        meta_path.unlink()
                    return True
        return False

    def delete_by_job(self, job_id: str) -> int:
        """Delete all artifacts for a job."""
        job_path = self._job_path(job_id)
        if not job_path.exists():
            return 0

        count = len(list(job_path.glob("*.data")))
        shutil.rmtree(job_path)
        return count

    def is_available(self) -> bool:
        """Check if local storage is available."""
        try:
            self._ensure_base_path()
            # Try to write a test file
            test_file = self.base_path / ".healthcheck"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# S3/MinIO Backend
# -----------------------------------------------------------------------------

class S3ArtifactStore(ArtifactStoreBackend):
    """
    S3/MinIO artifact storage.

    Object structure:
    {bucket}/
      {job_id}/{artifact_id}/data - artifact data
      {job_id}/{artifact_id}/meta.json - JSON metadata
    """

    def __init__(
        self,
        endpoint: str = None,
        bucket: str = None,
        access_key: str = None,
        secret_key: str = None,
        region: str = None,
    ):
        self.endpoint = endpoint or S3_ENDPOINT
        self.bucket = bucket or S3_BUCKET
        self.access_key = access_key or S3_ACCESS_KEY
        self.secret_key = secret_key or S3_SECRET_KEY
        self.region = region or S3_REGION
        self._client = None

    def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config

                config = Config(
                    connect_timeout=5,
                    read_timeout=10,
                    retries={'max_attempts': 2}
                )

                client_kwargs = {
                    'config': config,
                    'aws_access_key_id': self.access_key,
                    'aws_secret_access_key': self.secret_key,
                    'region_name': self.region,
                }

                if self.endpoint:
                    client_kwargs['endpoint_url'] = self.endpoint

                self._client = boto3.client('s3', **client_kwargs)
            except ImportError:
                raise RuntimeError("boto3 package not installed")
        return self._client

    def _data_key(self, job_id: str, artifact_id: str) -> str:
        """Get S3 key for artifact data."""
        return f"{job_id}/{artifact_id}/data"

    def _meta_key(self, job_id: str, artifact_id: str) -> str:
        """Get S3 key for artifact metadata."""
        return f"{job_id}/{artifact_id}/meta.json"

    def _compute_checksum(self, data: bytes) -> str:
        """Compute SHA-256 checksum of data."""
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def store(
        self,
        job_id: str,
        filename: str,
        data: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> ArtifactMetadata:
        """Store artifact to S3."""
        client = self._get_client()
        artifact_id = str(uuid.uuid4())

        # Read data and compute size/checksum
        content = data.read()
        size_bytes = len(content)
        checksum = self._compute_checksum(content)

        # Upload data
        data_key = self._data_key(job_id, artifact_id)
        client.put_object(
            Bucket=self.bucket,
            Key=data_key,
            Body=content,
            ContentType=content_type,
        )

        # Create metadata
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            job_id=job_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=datetime.now(timezone.utc).isoformat(),
            checksum=checksum,
        )

        # Upload metadata
        meta_key = self._meta_key(job_id, artifact_id)
        meta_json = json.dumps({
            "artifact_id": metadata.artifact_id,
            "job_id": metadata.job_id,
            "filename": metadata.filename,
            "content_type": metadata.content_type,
            "size_bytes": metadata.size_bytes,
            "created_at": metadata.created_at,
            "checksum": metadata.checksum,
        })
        client.put_object(
            Bucket=self.bucket,
            Key=meta_key,
            Body=meta_json.encode(),
            ContentType="application/json",
        )

        return metadata

    def get(self, artifact_id: str) -> Optional[BinaryIO]:
        """Retrieve artifact from S3."""
        client = self._get_client()

        # Search for the artifact
        try:
            # List objects with prefix to find job_id
            paginator = client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket):
                for obj in page.get('Contents', []):
                    if f"/{artifact_id}/data" in obj['Key']:
                        response = client.get_object(Bucket=self.bucket, Key=obj['Key'])
                        return io.BytesIO(response['Body'].read())
        except Exception:
            pass
        return None

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata from S3."""
        client = self._get_client()

        try:
            # Search for metadata file
            paginator = client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket):
                for obj in page.get('Contents', []):
                    if f"/{artifact_id}/meta.json" in obj['Key']:
                        response = client.get_object(Bucket=self.bucket, Key=obj['Key'])
                        data = json.loads(response['Body'].read().decode())
                        return ArtifactMetadata(**data)
        except Exception:
            pass
        return None

    def list_by_job(self, job_id: str) -> List[ArtifactMetadata]:
        """List all artifacts for a job from S3."""
        client = self._get_client()
        artifacts = []

        try:
            paginator = client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{job_id}/"):
                for obj in page.get('Contents', []):
                    if obj['Key'].endswith('/meta.json'):
                        response = client.get_object(Bucket=self.bucket, Key=obj['Key'])
                        data = json.loads(response['Body'].read().decode())
                        artifacts.append(ArtifactMetadata(**data))
        except Exception:
            pass

        return artifacts

    def delete(self, artifact_id: str) -> bool:
        """Delete artifact from S3."""
        client = self._get_client()

        try:
            # Find and delete both data and metadata
            paginator = client.get_paginator('list_objects_v2')
            keys_to_delete = []
            for page in paginator.paginate(Bucket=self.bucket):
                for obj in page.get('Contents', []):
                    if f"/{artifact_id}/" in obj['Key']:
                        keys_to_delete.append({'Key': obj['Key']})

            if keys_to_delete:
                client.delete_objects(
                    Bucket=self.bucket,
                    Delete={'Objects': keys_to_delete}
                )
                return True
        except Exception:
            pass
        return False

    def delete_by_job(self, job_id: str) -> int:
        """Delete all artifacts for a job from S3."""
        client = self._get_client()
        count = 0

        try:
            paginator = client.get_paginator('list_objects_v2')
            keys_to_delete = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{job_id}/"):
                for obj in page.get('Contents', []):
                    keys_to_delete.append({'Key': obj['Key']})
                    if obj['Key'].endswith('/data'):
                        count += 1

            if keys_to_delete:
                # Delete in batches of 1000 (S3 limit)
                for i in range(0, len(keys_to_delete), 1000):
                    batch = keys_to_delete[i:i+1000]
                    client.delete_objects(
                        Bucket=self.bucket,
                        Delete={'Objects': batch}
                    )
        except Exception:
            pass

        return count

    def is_available(self) -> bool:
        """Check if S3 is available."""
        if not self.endpoint and not self.bucket:
            return False

        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# Backend Factory
# -----------------------------------------------------------------------------

_store_instance: Optional[ArtifactStoreBackend] = None


def get_artifact_store() -> ArtifactStoreBackend:
    """
    Get or create artifact store based on configuration.

    Falls back to local storage if S3 is unavailable.
    """
    global _store_instance

    if _store_instance is not None:
        return _store_instance

    if ARTIFACT_STORE_BACKEND == "s3":
        s3_store = S3ArtifactStore()
        if s3_store.is_available():
            _store_instance = s3_store
        else:
            # Fallback to local if S3 unavailable
            import logging
            logging.getLogger("artifact_store").warning(
                "S3 unavailable, falling back to local artifact storage"
            )
            _store_instance = LocalArtifactStore()
    else:
        _store_instance = LocalArtifactStore()

    return _store_instance


def reset_store():
    """Reset store instance (for testing)."""
    global _store_instance
    _store_instance = None


# -----------------------------------------------------------------------------
# Convenience Functions
# -----------------------------------------------------------------------------

def store_artifact(
    job_id: str,
    filename: str,
    data: BinaryIO,
    content_type: str = "application/octet-stream",
) -> ArtifactMetadata:
    """Store an artifact for a job."""
    return get_artifact_store().store(job_id, filename, data, content_type)


def get_artifact(artifact_id: str) -> Optional[BinaryIO]:
    """Retrieve an artifact by ID."""
    return get_artifact_store().get(artifact_id)


def get_artifact_metadata(artifact_id: str) -> Optional[ArtifactMetadata]:
    """Get artifact metadata by ID."""
    return get_artifact_store().get_metadata(artifact_id)


def list_job_artifacts(job_id: str) -> List[ArtifactMetadata]:
    """List all artifacts for a job."""
    return get_artifact_store().list_by_job(job_id)


def delete_artifact(artifact_id: str) -> bool:
    """Delete an artifact by ID."""
    return get_artifact_store().delete(artifact_id)


def delete_job_artifacts(job_id: str) -> int:
    """Delete all artifacts for a job."""
    return get_artifact_store().delete_by_job(job_id)
