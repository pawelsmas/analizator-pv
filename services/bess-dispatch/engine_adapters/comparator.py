"""
Engine Comparator
=================

Compares results from multiple BESS engines and generates
confidence scores and difference reports.

The comparator analyzes:
- Sizing agreement (power, energy, NPV)
- Dispatch agreement (SOC traces, savings)
- Economic consistency

Confidence levels:
- HIGH: All engines agree within 10%
- MEDIUM: Engines agree within 25%
- LOW: Significant disagreement (>25%)

Version: 1.0.0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import numpy as np

import sys
sys.path.insert(0, '..')

from canonical_input import CanonicalInput, CanonicalBattery
from .base import (
    EngineType,
    EngineSizingResult,
    EngineDispatchResult,
    EngineAdapter,
)

logger = logging.getLogger(__name__)


class ConfidenceLevel(str, Enum):
    """Confidence in results based on engine agreement."""
    HIGH = "high"           # <10% disagreement
    MEDIUM = "medium"       # 10-25% disagreement
    LOW = "low"             # >25% disagreement
    SINGLE_ENGINE = "single"  # Only one engine available


# Thresholds for confidence scoring
SIZING_AGREEMENT_HIGH = 0.10      # 10% difference
SIZING_AGREEMENT_MEDIUM = 0.25   # 25% difference
DISPATCH_SOC_RMSE_HIGH = 0.05    # 5% SOC RMSE
DISPATCH_SOC_RMSE_MEDIUM = 0.10  # 10% SOC RMSE


@dataclass
class SizingComparison:
    """Comparison of sizing results from multiple engines."""
    power_kw: Dict[str, float]     # {engine_type: value}
    energy_kwh: Dict[str, float]
    npv_pln: Dict[str, float]
    annual_savings_pln: Dict[str, float]

    # Relative differences (vs native engine baseline)
    power_diff_pct: Dict[str, float]
    energy_diff_pct: Dict[str, float]
    npv_diff_pct: Dict[str, float]

    # Agreement metrics
    power_spread_pct: float    # (max - min) / mean
    energy_spread_pct: float
    npv_spread_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "power_kw": self.power_kw,
            "energy_kwh": self.energy_kwh,
            "npv_pln": self.npv_pln,
            "annual_savings_pln": self.annual_savings_pln,
            "power_diff_pct": self.power_diff_pct,
            "energy_diff_pct": self.energy_diff_pct,
            "npv_diff_pct": self.npv_diff_pct,
            "power_spread_pct": round(self.power_spread_pct, 1),
            "energy_spread_pct": round(self.energy_spread_pct, 1),
            "npv_spread_pct": round(self.npv_spread_pct, 1),
        }


@dataclass
class DispatchComparison:
    """Comparison of dispatch results from multiple engines."""
    # SOC trace comparison
    soc_rmse: Dict[str, float]       # RMSE vs native engine
    soc_max_diff: Dict[str, float]   # Max absolute difference
    soc_correlation: Dict[str, float]  # Pearson correlation

    # Energy metrics comparison
    total_discharge_diff_pct: Dict[str, float]
    equivalent_cycles_diff_pct: Dict[str, float]

    # Savings comparison
    savings_diff_pct: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "soc_rmse": self.soc_rmse,
            "soc_max_diff": self.soc_max_diff,
            "soc_correlation": self.soc_correlation,
            "total_discharge_diff_pct": self.total_discharge_diff_pct,
            "equivalent_cycles_diff_pct": self.equivalent_cycles_diff_pct,
            "savings_diff_pct": self.savings_diff_pct,
        }


@dataclass
class DiagnosticIssue:
    """A diagnostic issue found during comparison."""
    severity: str           # "error", "warning", "info"
    category: str           # "sizing", "dispatch", "economics"
    engine: str             # Which engine flagged this
    message: str
    metric_name: str
    expected_value: float
    actual_value: float
    difference_pct: float


@dataclass
class ComparisonResult:
    """
    Complete comparison result from multi-engine analysis.

    This is the main output of the comparator.
    """
    # Timestamp
    comparison_timestamp: str

    # Engines used
    engines_used: List[str]
    engines_available: Dict[str, bool]

    # Overall confidence
    confidence_level: ConfidenceLevel
    confidence_score: float  # 0-100

    # Sizing comparison (if sizing was run)
    sizing: Optional[SizingComparison] = None

    # Dispatch comparison (if dispatch was run)
    dispatch: Optional[DispatchComparison] = None

    # Recommended values (consensus or weighted average)
    recommended_power_kw: float = 0
    recommended_energy_kwh: float = 0
    recommended_npv_pln: float = 0

    # Computation times
    computation_times_ms: Dict[str, float] = field(default_factory=dict)

    # Diagnostic issues
    issues: List[DiagnosticIssue] = field(default_factory=list)

    # Raw results (for detailed debugging)
    sizing_results: Dict[str, EngineSizingResult] = field(default_factory=dict)
    dispatch_results: Dict[str, EngineDispatchResult] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON response."""
        return {
            "comparison_timestamp": self.comparison_timestamp,
            "engines_used": self.engines_used,
            "engines_available": self.engines_available,
            "confidence_level": self.confidence_level.value,
            "confidence_score": round(self.confidence_score, 1),
            "sizing": self.sizing.to_dict() if self.sizing else None,
            "dispatch": self.dispatch.to_dict() if self.dispatch else None,
            "recommended": {
                "power_kw": round(self.recommended_power_kw, 1),
                "energy_kwh": round(self.recommended_energy_kwh, 1),
                "npv_pln": round(self.recommended_npv_pln, 0),
            },
            "computation_times_ms": {k: round(v, 1) for k, v in self.computation_times_ms.items()},
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "engine": i.engine,
                    "message": i.message,
                    "metric_name": i.metric_name,
                    "difference_pct": round(i.difference_pct, 1),
                }
                for i in self.issues
            ],
            "n_issues_error": sum(1 for i in self.issues if i.severity == "error"),
            "n_issues_warning": sum(1 for i in self.issues if i.severity == "warning"),
        }


class EngineComparator:
    """
    Compares BESS sizing/dispatch results across multiple engines.

    Usage:
        comparator = EngineComparator()
        comparator.add_engine(native_adapter)
        comparator.add_engine(reopt_adapter)
        comparator.add_engine(pysam_adapter)

        result = comparator.run_comparison(canonical_input)
    """

    def __init__(self):
        """Initialize comparator."""
        self.engines: Dict[EngineType, EngineAdapter] = {}

    def add_engine(self, adapter: EngineAdapter):
        """Add an engine adapter to the comparator."""
        self.engines[adapter.engine_type] = adapter

    def get_available_engines(self) -> Dict[str, bool]:
        """Check which engines are available."""
        return {
            engine.engine_type.value: engine.is_available()
            for engine in self.engines.values()
        }

    def run_sizing_comparison(
        self,
        inp: CanonicalInput,
        use_engines: Optional[List[EngineType]] = None,
    ) -> ComparisonResult:
        """
        Run sizing on all available engines and compare results.

        Args:
            inp: Canonical input for sizing
            use_engines: Optional list of engines to use (default: all available)

        Returns:
            ComparisonResult with sizing comparison
        """
        start_time = datetime.now()
        engines_available = self.get_available_engines()
        sizing_results: Dict[str, EngineSizingResult] = {}
        issues: List[DiagnosticIssue] = []
        computation_times: Dict[str, float] = {}

        # Determine which engines to use
        if use_engines:
            engines_to_use = [e for e in use_engines if e in self.engines]
        else:
            engines_to_use = list(self.engines.keys())

        # Run sizing on each engine
        engines_used = []
        for engine_type in engines_to_use:
            adapter = self.engines[engine_type]

            if not adapter.is_available():
                logger.info(f"Skipping {engine_type.value} - not available")
                continue

            try:
                result = adapter.run_sizing(inp)
                sizing_results[engine_type.value] = result
                computation_times[engine_type.value] = result.computation_time_ms
                engines_used.append(engine_type.value)

                # Check for engine-specific issues
                for warning in result.warnings:
                    issues.append(DiagnosticIssue(
                        severity="warning",
                        category="sizing",
                        engine=engine_type.value,
                        message=warning,
                        metric_name="general",
                        expected_value=0,
                        actual_value=0,
                        difference_pct=0,
                    ))

            except Exception as e:
                logger.exception(f"Engine {engine_type.value} failed: {e}")
                issues.append(DiagnosticIssue(
                    severity="error",
                    category="sizing",
                    engine=engine_type.value,
                    message=f"Engine failed: {str(e)}",
                    metric_name="execution",
                    expected_value=0,
                    actual_value=0,
                    difference_pct=0,
                ))

        # If no results, return empty comparison
        if not sizing_results:
            return ComparisonResult(
                comparison_timestamp=start_time.isoformat(),
                engines_used=[],
                engines_available=engines_available,
                confidence_level=ConfidenceLevel.LOW,
                confidence_score=0,
                issues=issues,
            )

        # Compare sizing results
        sizing_comparison = self._compare_sizing_results(sizing_results)

        # Add comparison-based issues
        issues.extend(self._generate_sizing_issues(sizing_comparison, sizing_results))

        # Calculate confidence
        confidence_level, confidence_score = self._calculate_sizing_confidence(sizing_comparison)

        # Calculate recommended values (weighted average by confidence)
        recommended = self._calculate_consensus_sizing(sizing_results)

        return ComparisonResult(
            comparison_timestamp=start_time.isoformat(),
            engines_used=engines_used,
            engines_available=engines_available,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            sizing=sizing_comparison,
            recommended_power_kw=recommended["power_kw"],
            recommended_energy_kwh=recommended["energy_kwh"],
            recommended_npv_pln=recommended["npv_pln"],
            computation_times_ms=computation_times,
            issues=issues,
            sizing_results=sizing_results,
        )

    def run_dispatch_comparison(
        self,
        inp: CanonicalInput,
        battery: CanonicalBattery,
        use_engines: Optional[List[EngineType]] = None,
    ) -> ComparisonResult:
        """
        Run dispatch on all available engines and compare results.

        Args:
            inp: Canonical input
            battery: Battery parameters for dispatch
            use_engines: Optional list of engines to use

        Returns:
            ComparisonResult with dispatch comparison
        """
        start_time = datetime.now()
        engines_available = self.get_available_engines()
        dispatch_results: Dict[str, EngineDispatchResult] = {}
        issues: List[DiagnosticIssue] = []
        computation_times: Dict[str, float] = {}

        # Determine which engines to use
        if use_engines:
            engines_to_use = [e for e in use_engines if e in self.engines]
        else:
            engines_to_use = list(self.engines.keys())

        # Run dispatch on each engine
        engines_used = []
        for engine_type in engines_to_use:
            adapter = self.engines[engine_type]

            if not adapter.is_available():
                continue

            try:
                result = adapter.run_dispatch(inp, battery)
                dispatch_results[engine_type.value] = result
                computation_times[engine_type.value] = result.computation_time_ms
                engines_used.append(engine_type.value)

                for warning in result.warnings:
                    issues.append(DiagnosticIssue(
                        severity="warning",
                        category="dispatch",
                        engine=engine_type.value,
                        message=warning,
                        metric_name="general",
                        expected_value=0,
                        actual_value=0,
                        difference_pct=0,
                    ))

            except Exception as e:
                logger.exception(f"Engine {engine_type.value} dispatch failed: {e}")
                issues.append(DiagnosticIssue(
                    severity="error",
                    category="dispatch",
                    engine=engine_type.value,
                    message=f"Dispatch failed: {str(e)}",
                    metric_name="execution",
                    expected_value=0,
                    actual_value=0,
                    difference_pct=0,
                ))

        if not dispatch_results:
            return ComparisonResult(
                comparison_timestamp=start_time.isoformat(),
                engines_used=[],
                engines_available=engines_available,
                confidence_level=ConfidenceLevel.LOW,
                confidence_score=0,
                issues=issues,
            )

        # Compare dispatch results
        dispatch_comparison = self._compare_dispatch_results(dispatch_results)

        # Add comparison-based issues
        issues.extend(self._generate_dispatch_issues(dispatch_comparison, dispatch_results))

        # Calculate confidence
        confidence_level, confidence_score = self._calculate_dispatch_confidence(dispatch_comparison)

        return ComparisonResult(
            comparison_timestamp=start_time.isoformat(),
            engines_used=engines_used,
            engines_available=engines_available,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            dispatch=dispatch_comparison,
            computation_times_ms=computation_times,
            issues=issues,
            dispatch_results=dispatch_results,
        )

    def run_full_comparison(
        self,
        inp: CanonicalInput,
        use_engines: Optional[List[EngineType]] = None,
    ) -> ComparisonResult:
        """
        Run full comparison: sizing + dispatch.

        Uses sizing from first engine, then runs dispatch comparison
        on recommended battery size.
        """
        # First run sizing comparison
        sizing_result = self.run_sizing_comparison(inp, use_engines)

        if sizing_result.recommended_power_kw == 0:
            return sizing_result  # No valid sizing found

        # Create battery from recommended sizing
        battery = CanonicalBattery(
            power_kw=sizing_result.recommended_power_kw,
            energy_kwh=sizing_result.recommended_energy_kwh,
        )

        # Run dispatch comparison
        dispatch_result = self.run_dispatch_comparison(inp, battery, use_engines)

        # Merge results
        combined_issues = sizing_result.issues + dispatch_result.issues

        # Combined confidence (min of both)
        if sizing_result.confidence_score < dispatch_result.confidence_score:
            confidence_level = sizing_result.confidence_level
            confidence_score = sizing_result.confidence_score
        else:
            confidence_level = dispatch_result.confidence_level
            confidence_score = dispatch_result.confidence_score

        return ComparisonResult(
            comparison_timestamp=datetime.now().isoformat(),
            engines_used=list(set(sizing_result.engines_used + dispatch_result.engines_used)),
            engines_available=sizing_result.engines_available,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            sizing=sizing_result.sizing,
            dispatch=dispatch_result.dispatch,
            recommended_power_kw=sizing_result.recommended_power_kw,
            recommended_energy_kwh=sizing_result.recommended_energy_kwh,
            recommended_npv_pln=sizing_result.recommended_npv_pln,
            computation_times_ms={
                **sizing_result.computation_times_ms,
                **{f"{k}_dispatch": v for k, v in dispatch_result.computation_times_ms.items()},
            },
            issues=combined_issues,
            sizing_results=sizing_result.sizing_results,
            dispatch_results=dispatch_result.dispatch_results,
        )

    def _compare_sizing_results(
        self,
        results: Dict[str, EngineSizingResult],
    ) -> SizingComparison:
        """Compare sizing results from multiple engines."""
        power_kw = {}
        energy_kwh = {}
        npv_pln = {}
        annual_savings = {}

        for engine, result in results.items():
            power_kw[engine] = result.recommended.power_kw
            energy_kwh[engine] = result.recommended.energy_kwh
            npv_pln[engine] = result.recommended.npv_pln
            annual_savings[engine] = result.recommended.annual_savings_pln

        # Calculate differences vs native (baseline)
        baseline_power = power_kw.get("native", list(power_kw.values())[0])
        baseline_energy = energy_kwh.get("native", list(energy_kwh.values())[0])
        baseline_npv = npv_pln.get("native", list(npv_pln.values())[0])

        power_diff = {}
        energy_diff = {}
        npv_diff = {}

        for engine in results:
            power_diff[engine] = self._pct_diff(power_kw[engine], baseline_power)
            energy_diff[engine] = self._pct_diff(energy_kwh[engine], baseline_energy)
            npv_diff[engine] = self._pct_diff(npv_pln[engine], baseline_npv)

        # Calculate spread (agreement metric)
        power_spread = self._spread(list(power_kw.values()))
        energy_spread = self._spread(list(energy_kwh.values()))
        npv_spread = self._spread(list(npv_pln.values()))

        return SizingComparison(
            power_kw=power_kw,
            energy_kwh=energy_kwh,
            npv_pln=npv_pln,
            annual_savings_pln=annual_savings,
            power_diff_pct=power_diff,
            energy_diff_pct=energy_diff,
            npv_diff_pct=npv_diff,
            power_spread_pct=power_spread,
            energy_spread_pct=energy_spread,
            npv_spread_pct=npv_spread,
        )

    def _compare_dispatch_results(
        self,
        results: Dict[str, EngineDispatchResult],
    ) -> DispatchComparison:
        """Compare dispatch results from multiple engines."""
        # Get native result as baseline
        native_result = results.get("native")
        if native_result is None:
            native_result = list(results.values())[0]

        baseline_soc = native_result.timeseries.soc if native_result.timeseries else np.array([])

        soc_rmse = {}
        soc_max_diff = {}
        soc_correlation = {}
        discharge_diff = {}
        cycles_diff = {}
        savings_diff = {}

        for engine, result in results.items():
            if result.timeseries is not None and len(baseline_soc) > 0:
                soc = result.timeseries.soc
                if len(soc) == len(baseline_soc):
                    soc_rmse[engine] = float(np.sqrt(np.mean((soc - baseline_soc) ** 2)))
                    soc_max_diff[engine] = float(np.max(np.abs(soc - baseline_soc)))
                    if np.std(soc) > 0 and np.std(baseline_soc) > 0:
                        soc_correlation[engine] = float(np.corrcoef(soc, baseline_soc)[0, 1])
                    else:
                        soc_correlation[engine] = 1.0
                else:
                    soc_rmse[engine] = 0
                    soc_max_diff[engine] = 0
                    soc_correlation[engine] = 0
            else:
                soc_rmse[engine] = 0
                soc_max_diff[engine] = 0
                soc_correlation[engine] = 0

            discharge_diff[engine] = self._pct_diff(
                result.total_discharge_kwh,
                native_result.total_discharge_kwh
            )
            cycles_diff[engine] = self._pct_diff(
                result.equivalent_cycles,
                native_result.equivalent_cycles
            )
            savings_diff[engine] = self._pct_diff(
                result.annual_savings_pln,
                native_result.annual_savings_pln
            )

        return DispatchComparison(
            soc_rmse=soc_rmse,
            soc_max_diff=soc_max_diff,
            soc_correlation=soc_correlation,
            total_discharge_diff_pct=discharge_diff,
            equivalent_cycles_diff_pct=cycles_diff,
            savings_diff_pct=savings_diff,
        )

    def _calculate_sizing_confidence(
        self,
        comparison: SizingComparison,
    ) -> Tuple[ConfidenceLevel, float]:
        """Calculate confidence level from sizing comparison."""
        # Use max spread as primary metric
        max_spread = max(
            comparison.power_spread_pct,
            comparison.energy_spread_pct,
            comparison.npv_spread_pct,
        )

        if max_spread < SIZING_AGREEMENT_HIGH * 100:
            level = ConfidenceLevel.HIGH
            score = 90 + (SIZING_AGREEMENT_HIGH * 100 - max_spread)
        elif max_spread < SIZING_AGREEMENT_MEDIUM * 100:
            level = ConfidenceLevel.MEDIUM
            score = 60 + (SIZING_AGREEMENT_MEDIUM * 100 - max_spread)
        else:
            level = ConfidenceLevel.LOW
            score = max(0, 40 - (max_spread - SIZING_AGREEMENT_MEDIUM * 100))

        return level, min(100, max(0, score))

    def _calculate_dispatch_confidence(
        self,
        comparison: DispatchComparison,
    ) -> Tuple[ConfidenceLevel, float]:
        """Calculate confidence level from dispatch comparison."""
        # Use max SOC RMSE as primary metric
        if comparison.soc_rmse:
            max_rmse = max(comparison.soc_rmse.values())
        else:
            max_rmse = 0

        if max_rmse < DISPATCH_SOC_RMSE_HIGH:
            level = ConfidenceLevel.HIGH
            score = 90 + (DISPATCH_SOC_RMSE_HIGH - max_rmse) * 100
        elif max_rmse < DISPATCH_SOC_RMSE_MEDIUM:
            level = ConfidenceLevel.MEDIUM
            score = 60 + (DISPATCH_SOC_RMSE_MEDIUM - max_rmse) * 100
        else:
            level = ConfidenceLevel.LOW
            score = max(0, 40 - (max_rmse - DISPATCH_SOC_RMSE_MEDIUM) * 100)

        return level, min(100, max(0, score))

    def _calculate_consensus_sizing(
        self,
        results: Dict[str, EngineSizingResult],
    ) -> Dict[str, float]:
        """Calculate consensus sizing from multiple engines."""
        # Weight by solver quality: MILP > heuristic > error
        weights = {
            "native": 1.0,
            "reopt": 1.5,  # MILP gets higher weight
            "pysam": 0.8,
        }

        total_weight = 0
        weighted_power = 0
        weighted_energy = 0
        weighted_npv = 0

        for engine, result in results.items():
            if result.solver_status == "error":
                continue

            w = weights.get(engine, 1.0)
            total_weight += w
            weighted_power += result.recommended.power_kw * w
            weighted_energy += result.recommended.energy_kwh * w
            weighted_npv += result.recommended.npv_pln * w

        if total_weight == 0:
            return {"power_kw": 0, "energy_kwh": 0, "npv_pln": 0}

        return {
            "power_kw": weighted_power / total_weight,
            "energy_kwh": weighted_energy / total_weight,
            "npv_pln": weighted_npv / total_weight,
        }

    def _generate_sizing_issues(
        self,
        comparison: SizingComparison,
        results: Dict[str, EngineSizingResult],
    ) -> List[DiagnosticIssue]:
        """Generate diagnostic issues from sizing comparison."""
        issues = []

        # Check power spread
        if comparison.power_spread_pct > SIZING_AGREEMENT_MEDIUM * 100:
            issues.append(DiagnosticIssue(
                severity="warning",
                category="sizing",
                engine="comparator",
                message=f"Power sizing spread is {comparison.power_spread_pct:.1f}% - engines disagree",
                metric_name="power_kw",
                expected_value=0,
                actual_value=comparison.power_spread_pct,
                difference_pct=comparison.power_spread_pct,
            ))

        # Check NPV spread
        if comparison.npv_spread_pct > SIZING_AGREEMENT_MEDIUM * 100:
            issues.append(DiagnosticIssue(
                severity="warning",
                category="sizing",
                engine="comparator",
                message=f"NPV spread is {comparison.npv_spread_pct:.1f}% - verify economic assumptions",
                metric_name="npv_pln",
                expected_value=0,
                actual_value=comparison.npv_spread_pct,
                difference_pct=comparison.npv_spread_pct,
            ))

        # Check for REopt vs Native discrepancy (MILP vs heuristic)
        if "reopt" in comparison.power_diff_pct and "native" in comparison.power_diff_pct:
            diff = abs(comparison.power_diff_pct["reopt"])
            if diff > 15:
                issues.append(DiagnosticIssue(
                    severity="info",
                    category="sizing",
                    engine="comparator",
                    message=f"REopt (MILP) differs from native by {diff:.1f}% - REopt may be more accurate",
                    metric_name="power_kw",
                    expected_value=comparison.power_kw.get("native", 0),
                    actual_value=comparison.power_kw.get("reopt", 0),
                    difference_pct=diff,
                ))

        return issues

    def _generate_dispatch_issues(
        self,
        comparison: DispatchComparison,
        results: Dict[str, EngineDispatchResult],
    ) -> List[DiagnosticIssue]:
        """Generate diagnostic issues from dispatch comparison."""
        issues = []

        # Check SOC RMSE
        for engine, rmse in comparison.soc_rmse.items():
            if engine == "native":
                continue
            if rmse > DISPATCH_SOC_RMSE_MEDIUM:
                issues.append(DiagnosticIssue(
                    severity="warning",
                    category="dispatch",
                    engine=engine,
                    message=f"SOC trace RMSE is {rmse:.3f} - significant dispatch difference",
                    metric_name="soc_rmse",
                    expected_value=0,
                    actual_value=rmse,
                    difference_pct=rmse * 100,
                ))

        return issues

    @staticmethod
    def _pct_diff(value: float, baseline: float) -> float:
        """Calculate percentage difference."""
        if baseline == 0:
            return 0 if value == 0 else 100
        return ((value - baseline) / abs(baseline)) * 100

    @staticmethod
    def _spread(values: List[float]) -> float:
        """Calculate spread as percentage of mean."""
        if not values or len(values) < 2:
            return 0
        mean = np.mean(values)
        if mean == 0:
            return 0
        return ((max(values) - min(values)) / abs(mean)) * 100
