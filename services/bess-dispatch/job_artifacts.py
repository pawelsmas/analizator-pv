"""
Job artifacts storage (v3.4.0 PR3).

Stores and retrieves artifacts produced by async jobs:
- PDF reports
- XLSX exports
- JSON data

Artifacts are stored on filesystem with job_id as directory.
"""

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from pydantic import BaseModel


# Artifacts directory from environment or default
ARTIFACTS_DIR = Path(os.getenv("JOB_ARTIFACTS_DIR", "/data/job_artifacts"))


class ArtifactInfo(BaseModel):
    """Information about a stored artifact."""
    name: str
    content_type: str
    size_bytes: int
    created_at: str


def get_job_artifacts_dir(job_id: str) -> Path:
    """Get the artifacts directory for a job."""
    return ARTIFACTS_DIR / job_id


def ensure_artifacts_dir(job_id: str) -> Path:
    """Ensure the artifacts directory exists for a job."""
    path = get_job_artifacts_dir(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_artifact(job_id: str, name: str, content: bytes, content_type: str) -> ArtifactInfo:
    """
    Save an artifact for a job.

    Args:
        job_id: Job ID
        name: Artifact filename (e.g., "report.pdf")
        content: Artifact content as bytes
        content_type: MIME type (e.g., "application/pdf")

    Returns:
        ArtifactInfo with artifact metadata
    """
    artifacts_dir = ensure_artifacts_dir(job_id)
    artifact_path = artifacts_dir / name

    # Write content
    artifact_path.write_bytes(content)

    # Write metadata
    metadata = {
        "name": name,
        "content_type": content_type,
        "size_bytes": len(content),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = artifacts_dir / f"{name}.meta.json"
    metadata_path.write_text(json.dumps(metadata))

    return ArtifactInfo(**metadata)


def get_artifact(job_id: str, name: str) -> Optional[tuple[bytes, str]]:
    """
    Get an artifact for a job.

    Args:
        job_id: Job ID
        name: Artifact filename

    Returns:
        Tuple of (content bytes, content_type) or None if not found
    """
    artifacts_dir = get_job_artifacts_dir(job_id)
    artifact_path = artifacts_dir / name
    metadata_path = artifacts_dir / f"{name}.meta.json"

    if not artifact_path.exists():
        return None

    content = artifact_path.read_bytes()

    # Read metadata for content type
    content_type = "application/octet-stream"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text())
            content_type = metadata.get("content_type", content_type)
        except (json.JSONDecodeError, KeyError):
            pass

    return content, content_type


def list_artifacts(job_id: str) -> List[ArtifactInfo]:
    """
    List all artifacts for a job.

    Args:
        job_id: Job ID

    Returns:
        List of ArtifactInfo objects
    """
    artifacts_dir = get_job_artifacts_dir(job_id)

    if not artifacts_dir.exists():
        return []

    artifacts = []
    for meta_file in artifacts_dir.glob("*.meta.json"):
        try:
            metadata = json.loads(meta_file.read_text())
            artifacts.append(ArtifactInfo(**metadata))
        except (json.JSONDecodeError, KeyError):
            continue

    return artifacts


def delete_artifacts(job_id: str) -> int:
    """
    Delete all artifacts for a job.

    Args:
        job_id: Job ID

    Returns:
        Number of files deleted
    """
    import shutil

    artifacts_dir = get_job_artifacts_dir(job_id)

    if not artifacts_dir.exists():
        return 0

    count = len(list(artifacts_dir.iterdir()))
    shutil.rmtree(artifacts_dir)
    return count
