"""
Regression test fixtures.
"""
import pytest
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture
def golden_dir():
    """Path to golden master directory."""
    return GOLDEN_DIR


@pytest.fixture
def load_golden():
    """Load a golden master JSON file."""
    def _load(filename: str) -> dict:
        filepath = GOLDEN_DIR / filename
        with open(filepath) as f:
            return json.load(f)
    return _load
