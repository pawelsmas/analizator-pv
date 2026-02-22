"""
Engine Adapters Package
=======================

Multi-engine BESS sizing and dispatch adapters.

Available adapters:
- NativeAdapter: Fast, Polish-market-specific heuristic engine (Layer 1)
- REoptAdapter: NREL REopt MILP optimizer for sizing validation (Layer 2)
- PySAMAdapter: NREL SAM for hourly dispatch diagnostics (Layer 3)

Version: 1.0.0
"""

from .base import EngineAdapter, EngineSizingResult, EngineDispatchResult
from .native_adapter import NativeAdapter
from .reopt_adapter import REoptAdapter
from .pysam_adapter import PySAMAdapter
from .comparator import EngineComparator, ComparisonResult, ConfidenceLevel

__all__ = [
    "EngineAdapter",
    "EngineSizingResult",
    "EngineDispatchResult",
    "NativeAdapter",
    "REoptAdapter",
    "PySAMAdapter",
    "EngineComparator",
    "ComparisonResult",
    "ConfidenceLevel",
]
