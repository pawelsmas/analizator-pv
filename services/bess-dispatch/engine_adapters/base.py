"""
Base Engine Adapter
===================

Abstract base class and result types for all BESS engine adapters.

All adapters must implement the same interface to enable
transparent switching and comparison between engines.

Version: 1.0.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
import numpy as np

import sys
sys.path.insert(0, '..')
from canonical_input import CanonicalInput, CanonicalBattery


class EngineType(str, Enum):
    """Engine type identifier."""
    NATIVE = "native"           # Layer 1: Fast Polish heuristics
    REOPT = "reopt"             # Layer 2: NREL MILP reference
    PYSAM = "pysam"             # Layer 3: NREL dispatch diagnostics


@dataclass
class SizingRecommendation:
    """Single sizing recommendation from an engine."""
    power_kw: float
    energy_kwh: float
    duration_h: float
    annual_savings_pln: float
    npv_pln: float
    irr_pct: Optional[float]
    payback_years: float
    capex_pln: float
    variant_name: str = "M"  # S, M, L or custom


@dataclass
class EngineSizingResult:
    """
    Standardized sizing result from any engine.

    All engines must produce results in this format for comparison.
    """
    # Engine metadata
    engine_type: EngineType
    engine_version: str
    computation_time_ms: float

    # Recommended sizing
    recommended: SizingRecommendation

    # All variants (S, M, L or custom)
    variants: List[SizingRecommendation]

    # Annual metrics
    annual_savings_pln: float
    annual_cycles: float
    self_consumption_pct: float

    # Economics
    npv_pln: float
    irr_pct: Optional[float]
    payback_years: float

    # Confidence and quality
    solver_status: str = "optimal"  # optimal, feasible, infeasible
    solver_gap: float = 0.0         # MIP gap (for MILP solvers)

    # Raw engine output (for debugging)
    raw_output: Optional[Dict[str, Any]] = None

    # Warnings/notes
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "engine_type": self.engine_type.value,
            "engine_version": self.engine_version,
            "computation_time_ms": round(self.computation_time_ms, 1),
            "recommended": {
                "power_kw": self.recommended.power_kw,
                "energy_kwh": self.recommended.energy_kwh,
                "duration_h": self.recommended.duration_h,
                "annual_savings_pln": round(self.recommended.annual_savings_pln, 2),
                "npv_pln": round(self.recommended.npv_pln, 2),
                "irr_pct": round(self.recommended.irr_pct, 2) if self.recommended.irr_pct else None,
                "payback_years": round(self.recommended.payback_years, 2),
                "capex_pln": round(self.recommended.capex_pln, 2),
                "variant_name": self.recommended.variant_name,
            },
            "variants": [
                {
                    "power_kw": v.power_kw,
                    "energy_kwh": v.energy_kwh,
                    "duration_h": v.duration_h,
                    "annual_savings_pln": round(v.annual_savings_pln, 2),
                    "npv_pln": round(v.npv_pln, 2),
                    "variant_name": v.variant_name,
                }
                for v in self.variants
            ],
            "annual_savings_pln": round(self.annual_savings_pln, 2),
            "annual_cycles": round(self.annual_cycles, 1),
            "self_consumption_pct": round(self.self_consumption_pct, 1),
            "npv_pln": round(self.npv_pln, 2),
            "irr_pct": round(self.irr_pct, 2) if self.irr_pct else None,
            "payback_years": round(self.payback_years, 2),
            "solver_status": self.solver_status,
            "solver_gap": round(self.solver_gap, 4),
            "warnings": self.warnings,
        }


@dataclass
class DispatchTimeseries:
    """Hourly dispatch timeseries."""
    soc: np.ndarray              # SOC [0-1] per timestep
    charge_kw: np.ndarray        # Charge power (positive = charging)
    discharge_kw: np.ndarray     # Discharge power (positive = discharging)
    grid_import_kw: np.ndarray   # Grid import
    grid_export_kw: np.ndarray   # Grid export


@dataclass
class EngineDispatchResult:
    """
    Standardized dispatch result from any engine.

    Includes full timeseries for diagnostic comparison.
    """
    # Engine metadata
    engine_type: EngineType
    engine_version: str
    computation_time_ms: float

    # Battery used
    battery: CanonicalBattery

    # Summary metrics
    total_charge_kwh: float
    total_discharge_kwh: float
    equivalent_cycles: float
    self_consumption_pct: float
    peak_reduction_kw: float

    # Economics
    annual_savings_pln: float
    savings_breakdown: Dict[str, float]  # {pv_surplus, peak_shaving, arbitrage, capacity_fee}

    # Timeseries (for comparison)
    timeseries: Optional[DispatchTimeseries] = None

    # Final SOC
    final_soc: float = 0.5

    # Quality metrics
    soc_violations: int = 0     # Number of SOC bound violations
    power_violations: int = 0   # Number of power limit violations

    # Raw output
    raw_output: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (without timeseries arrays)."""
        return {
            "engine_type": self.engine_type.value,
            "engine_version": self.engine_version,
            "computation_time_ms": round(self.computation_time_ms, 1),
            "battery": self.battery.to_dict(),
            "total_charge_kwh": round(self.total_charge_kwh, 1),
            "total_discharge_kwh": round(self.total_discharge_kwh, 1),
            "equivalent_cycles": round(self.equivalent_cycles, 2),
            "self_consumption_pct": round(self.self_consumption_pct, 1),
            "peak_reduction_kw": round(self.peak_reduction_kw, 1),
            "annual_savings_pln": round(self.annual_savings_pln, 2),
            "savings_breakdown": {k: round(v, 2) for k, v in self.savings_breakdown.items()},
            "final_soc": round(self.final_soc, 3),
            "soc_violations": self.soc_violations,
            "power_violations": self.power_violations,
            "warnings": self.warnings,
            "has_timeseries": self.timeseries is not None,
        }


class EngineAdapter(ABC):
    """
    Abstract base class for BESS engine adapters.

    All engines must implement:
    - run_sizing(): Optimize battery size for given load/PV
    - run_dispatch(): Simulate battery operation for given size

    Engines may also implement:
    - is_available(): Check if engine dependencies are installed
    - get_info(): Return engine metadata
    """

    @property
    @abstractmethod
    def engine_type(self) -> EngineType:
        """Return the engine type identifier."""
        pass

    @property
    @abstractmethod
    def engine_version(self) -> str:
        """Return the engine version string."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this engine is available (dependencies installed).

        Returns True if engine can be used, False otherwise.
        """
        pass

    @abstractmethod
    def run_sizing(
        self,
        inp: CanonicalInput,
        power_range_kw: Optional[tuple] = None,
        energy_range_kwh: Optional[tuple] = None,
    ) -> EngineSizingResult:
        """
        Run sizing optimization.

        Args:
            inp: Canonical input with load, PV, prices, policies
            power_range_kw: Optional (min, max) power constraint
            energy_range_kwh: Optional (min, max) energy constraint

        Returns:
            EngineSizingResult with recommended sizing and variants
        """
        pass

    @abstractmethod
    def run_dispatch(
        self,
        inp: CanonicalInput,
        battery: CanonicalBattery,
    ) -> EngineDispatchResult:
        """
        Run dispatch simulation for given battery size.

        Args:
            inp: Canonical input with load, PV, prices, policies
            battery: Battery parameters to simulate

        Returns:
            EngineDispatchResult with timeseries and metrics
        """
        pass

    def get_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "engine_type": self.engine_type.value,
            "engine_version": self.engine_version,
            "is_available": self.is_available(),
        }
