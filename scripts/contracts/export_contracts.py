#!/usr/bin/env python3
"""
Contract Schema Export Tool (v2.6.0 PR1).

Exports JSON Schema for key API models to docs/contracts/latest/.
Supports deterministic export and drift checking for CI.

Usage:
    python scripts/contracts/export_contracts.py          # Export schemas
    python scripts/contracts/export_contracts.py --check  # Check for drift
    python scripts/contracts/export_contracts.py --version v2.6.0  # Snapshot to history

Features:
- Deterministic output (sorted keys, stable order)
- Hash verification for drift detection
- Version snapshots for release history
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add service to path
SERVICE_PATH = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(SERVICE_PATH))


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

CONTRACTS_DIR = Path(__file__).parent.parent.parent / "docs" / "contracts"
LATEST_DIR = CONTRACTS_DIR / "latest"
HISTORY_DIR = CONTRACTS_DIR / "history"

# Models to export with their categories
MODELS_TO_EXPORT = [
    # Core API models
    ("SizingRequest", "sizing"),
    ("SizingResult", "sizing"),
    ("DispatchRequest", "dispatch"),
    ("DispatchResult", "dispatch"),
    # Batch API models
    ("BatchSizingRequest", "batch"),
    ("BatchSizingResponse", "batch"),
    ("BatchItemResult", "batch"),
    # Portfolio models
    ("PortfolioSummary", "portfolio"),
    ("PortfolioVariantRanking", "portfolio"),
    # Validation models
    ("KpiSnapshot", "validation"),
    ("KpiDiff", "validation"),
    # Report models
    ("ReportOptions", "report"),
    # Job models
    ("JobStatus", "jobs"),
]


# -----------------------------------------------------------------------------
# Schema Generation
# -----------------------------------------------------------------------------

def get_model_class(model_name: str):
    """Import and return a model class by name."""
    try:
        # Try models.py first
        from models import (
            SizingRequest, SizingResult,
            DispatchRequest, DispatchResult,
            BatchSizingRequest, BatchSizingResponse, BatchItemResult,
            PortfolioSummary, PortfolioVariantRanking,
        )
        model_map = {
            "SizingRequest": SizingRequest,
            "SizingResult": SizingResult,
            "DispatchRequest": DispatchRequest,
            "DispatchResult": DispatchResult,
            "BatchSizingRequest": BatchSizingRequest,
            "BatchSizingResponse": BatchSizingResponse,
            "BatchItemResult": BatchItemResult,
            "PortfolioSummary": PortfolioSummary,
            "PortfolioVariantRanking": PortfolioVariantRanking,
        }
        if model_name in model_map:
            return model_map[model_name]
    except ImportError:
        pass

    try:
        # Try validation_kpis.py
        from validation_kpis import KpiSnapshot, KpiDiff
        model_map = {
            "KpiSnapshot": KpiSnapshot,
            "KpiDiff": KpiDiff,
        }
        if model_name in model_map:
            return model_map[model_name]
    except ImportError:
        pass

    try:
        # Try report_models.py
        from report_models import ReportOptions
        model_map = {
            "ReportOptions": ReportOptions,
        }
        if model_name in model_map:
            return model_map[model_name]
    except ImportError:
        pass

    try:
        # Try job_store.py
        from job_store import JobStatus
        model_map = {
            "JobStatus": JobStatus,
        }
        if model_name in model_map:
            return model_map[model_name]
    except ImportError:
        pass

    return None


def generate_schema(model_name: str) -> Dict[str, Any]:
    """Generate JSON Schema for a model."""
    model_class = get_model_class(model_name)
    if model_class is None:
        return {"error": f"Model {model_name} not found"}

    try:
        # Pydantic v2 uses model_json_schema()
        if hasattr(model_class, "model_json_schema"):
            schema = model_class.model_json_schema()
        else:
            # Pydantic v1 fallback
            schema = model_class.schema()
        return schema
    except Exception as e:
        return {"error": str(e)}


def serialize_schema(schema: Dict[str, Any]) -> str:
    """Serialize schema to deterministic JSON string."""
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False)


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# -----------------------------------------------------------------------------
# Export Functions
# -----------------------------------------------------------------------------

def export_schemas(output_dir: Path) -> List[Tuple[str, str, str]]:
    """
    Export all schemas to output directory.

    Returns:
        List of (model_name, filename, hash) tuples
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for model_name, category in MODELS_TO_EXPORT:
        schema = generate_schema(model_name)
        content = serialize_schema(schema)
        content_hash = compute_hash(content)

        filename = f"{category}_{model_name}.json"
        filepath = output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")  # Trailing newline

        results.append((model_name, filename, content_hash))

    # Write manifest
    manifest = {
        "version": "2.6.0",
        "schemas": [
            {"model": name, "file": fname, "hash": h}
            for name, fname, h in results
        ]
    }
    manifest_content = json.dumps(manifest, sort_keys=True, indent=2)
    with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
        f.write(manifest_content)
        f.write("\n")

    return results


def check_drift(reference_dir: Path) -> Tuple[bool, List[str]]:
    """
    Check if current schemas match reference.

    Returns:
        (passed, list_of_differences)
    """
    if not reference_dir.exists():
        return False, ["Reference directory does not exist"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        export_schemas(tmp_path)

        differences = []

        # Compare manifest
        ref_manifest = reference_dir / "manifest.json"
        tmp_manifest = tmp_path / "manifest.json"

        if not ref_manifest.exists():
            differences.append("manifest.json missing from reference")
        else:
            with open(ref_manifest, encoding="utf-8") as f:
                ref_content = f.read()
            with open(tmp_manifest, encoding="utf-8") as f:
                tmp_content = f.read()

            if ref_content.strip() != tmp_content.strip():
                differences.append("manifest.json differs")

        # Compare each schema file
        for model_name, category in MODELS_TO_EXPORT:
            filename = f"{category}_{model_name}.json"
            ref_file = reference_dir / filename
            tmp_file = tmp_path / filename

            if not ref_file.exists():
                differences.append(f"{filename} missing from reference")
                continue

            with open(ref_file, encoding="utf-8") as f:
                ref_content = f.read()
            with open(tmp_file, encoding="utf-8") as f:
                tmp_content = f.read()

            if ref_content.strip() != tmp_content.strip():
                differences.append(f"{filename} differs")

        return len(differences) == 0, differences


def snapshot_to_history(version: str) -> None:
    """Copy latest schemas to history/{version}/."""
    if not LATEST_DIR.exists():
        print("Error: latest/ directory does not exist. Run export first.")
        sys.exit(1)

    history_version_dir = HISTORY_DIR / version
    if history_version_dir.exists():
        print(f"Warning: {history_version_dir} already exists, overwriting...")
        shutil.rmtree(history_version_dir)

    shutil.copytree(LATEST_DIR, history_version_dir)
    print(f"Copied schemas to {history_version_dir}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Contract Schema Export Tool")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check for drift against latest/ (exit 1 if drift detected)",
    )
    parser.add_argument(
        "--version",
        type=str,
        help="Snapshot current schemas to history/{version}/",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Override output directory (default: docs/contracts/latest/)",
    )

    args = parser.parse_args()

    if args.check:
        print("Checking for contract drift...")
        passed, differences = check_drift(LATEST_DIR)
        if passed:
            print("[OK] No contract drift detected")
            sys.exit(0)
        else:
            print("[FAIL] Contract drift detected:")
            for diff in differences:
                print(f"  - {diff}")
            print("\nRun 'python scripts/contracts/export_contracts.py' to update schemas")
            sys.exit(1)

    # Export schemas
    output_dir = Path(args.output) if args.output else LATEST_DIR
    print(f"Exporting schemas to {output_dir}...")

    results = export_schemas(output_dir)
    print(f"Exported {len(results)} schemas:")
    for model_name, filename, content_hash in results:
        print(f"  {filename} ({content_hash[:16]}...)")

    # Snapshot if version specified
    if args.version:
        snapshot_to_history(args.version)

    print("Done!")


if __name__ == "__main__":
    main()
