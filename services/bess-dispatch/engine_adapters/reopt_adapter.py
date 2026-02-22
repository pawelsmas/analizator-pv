"""
REopt Engine Adapter (Layer 2)
==============================

Adapter for NREL REopt Lite MILP optimizer.

REopt is the "golden reference" for sizing optimization:
- Uses MILP (Mixed Integer Linear Programming) for global optimum
- Developed by NREL (National Renewable Energy Laboratory)
- Free API available at developer.nrel.gov

This adapter can operate in two modes:
1. API Mode: Calls NREL REopt API (requires API key)
2. Local Mode: Uses REopt Julia package (if installed)

Key differences from native engine:
- MILP guarantees global optimum (vs heuristic grid search)
- More comprehensive financial model
- Standard US utility rate structures (less PL-specific)

Version: 1.0.0
"""

import logging
import os
import time
import json
from typing import Optional, Dict, Any, List
import numpy as np

import sys
sys.path.insert(0, '..')

from canonical_input import CanonicalInput, CanonicalBattery
from .base import (
    EngineAdapter,
    EngineType,
    EngineSizingResult,
    EngineDispatchResult,
    SizingRecommendation,
    DispatchTimeseries,
)

logger = logging.getLogger(__name__)


# REopt API settings
REOPT_API_URL = "https://developer.nrel.gov/api/reopt/stable/job"
REOPT_API_KEY_ENV = "NREL_API_KEY"  # Environment variable for API key

# Default constraints for Poland
DEFAULT_POLAND_COORDS = (52.23, 21.01)  # Warsaw
PLN_TO_USD = 0.25  # Approximate conversion for cost comparison


class REoptAdapter(EngineAdapter):
    """
    Adapter for NREL REopt optimizer.

    Uses REopt API or local Julia package for MILP-based sizing.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: int = 300,
        use_api: bool = True,
    ):
        """
        Initialize REopt adapter.

        Args:
            api_key: NREL API key (or set NREL_API_KEY env var)
            timeout_seconds: API timeout
            use_api: If True, use NREL API; if False, try local Julia
        """
        self.api_key = api_key or os.environ.get(REOPT_API_KEY_ENV)
        self.timeout = timeout_seconds
        self.use_api = use_api
        self._reopt_version = "3.4.0"  # REopt stable version

    @property
    def engine_type(self) -> EngineType:
        return EngineType.REOPT

    @property
    def engine_version(self) -> str:
        return self._reopt_version

    def is_available(self) -> bool:
        """Check if REopt is available."""
        if self.use_api:
            return self.api_key is not None
        else:
            # Check for local Julia installation
            try:
                import julia
                return True
            except ImportError:
                return False

    def run_sizing(
        self,
        inp: CanonicalInput,
        power_range_kw: Optional[tuple] = None,
        energy_range_kwh: Optional[tuple] = None,
    ) -> EngineSizingResult:
        """
        Run REopt sizing optimization.

        Converts CanonicalInput to REopt format and calls API.
        """
        start_time = time.time()
        warnings = []

        if not self.is_available():
            return self._error_result(
                "REopt not available - set NREL_API_KEY environment variable",
                start_time
            )

        try:
            # Build REopt request
            reopt_request = self._build_reopt_request(
                inp, power_range_kw, energy_range_kwh
            )

            if self.use_api:
                # Call NREL API
                result = self._call_reopt_api(reopt_request)
            else:
                # Use local Julia
                result = self._call_reopt_local(reopt_request)

            computation_time_ms = (time.time() - start_time) * 1000

            # Parse REopt result
            return self._parse_reopt_result(result, inp, computation_time_ms)

        except Exception as e:
            logger.exception(f"REopt sizing failed: {e}")
            return self._error_result(str(e), start_time)

    def run_dispatch(
        self,
        inp: CanonicalInput,
        battery: CanonicalBattery,
    ) -> EngineDispatchResult:
        """
        Run REopt dispatch simulation.

        REopt is primarily a sizing tool, but we can fix the battery
        size and get dispatch timeseries from the solution.
        """
        start_time = time.time()
        warnings = []

        if not self.is_available():
            return self._dispatch_error_result(
                battery, "REopt not available", start_time
            )

        try:
            # Build REopt request with fixed battery size
            reopt_request = self._build_reopt_request(
                inp,
                power_range_kw=(battery.power_kw, battery.power_kw),
                energy_range_kwh=(battery.energy_kwh, battery.energy_kwh),
            )

            if self.use_api:
                result = self._call_reopt_api(reopt_request)
            else:
                result = self._call_reopt_local(reopt_request)

            computation_time_ms = (time.time() - start_time) * 1000

            # Extract dispatch timeseries from REopt result
            return self._parse_reopt_dispatch(
                result, inp, battery, computation_time_ms
            )

        except Exception as e:
            logger.exception(f"REopt dispatch failed: {e}")
            return self._dispatch_error_result(battery, str(e), start_time)

    def _build_reopt_request(
        self,
        inp: CanonicalInput,
        power_range_kw: Optional[tuple] = None,
        energy_range_kwh: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        """
        Build REopt API request from CanonicalInput.

        REopt uses specific JSON schema for input.
        """
        # Determine size constraints
        if power_range_kw:
            min_kw, max_kw = power_range_kw
        else:
            min_kw, max_kw = 0, inp.peak_load_kw * 2

        if energy_range_kwh:
            min_kwh, max_kwh = energy_range_kwh
        else:
            min_kwh, max_kwh = 0, inp.peak_load_kw * 4 * 2  # Up to 4h duration

        # Convert prices to USD (REopt uses USD)
        price_usd = inp.pricing.avg_price_import * PLN_TO_USD

        # Build REopt request structure
        request = {
            "Settings": {
                "timeout_seconds": self.timeout,
                "optimality_tolerance": 0.01,  # 1% MIP gap
            },
            "Site": {
                "latitude": DEFAULT_POLAND_COORDS[0],
                "longitude": DEFAULT_POLAND_COORDS[1],
            },
            "ElectricLoad": {
                "loads_kw": inp.load_kw.tolist(),
                "year": inp.time_axis.start_datetime.year,
            },
            "ElectricTariff": {
                "blended_annual_energy_rate": price_usd,
                "blended_annual_demand_rate": inp.pricing.demand_charge_pln_per_kw * PLN_TO_USD,
            },
            "ElectricStorage": {
                "min_kw": min_kw,
                "max_kw": max_kw,
                "min_kwh": min_kwh,
                "max_kwh": max_kwh,
                "installed_cost_per_kw": inp.economics.capex_per_kw * PLN_TO_USD,
                "installed_cost_per_kwh": inp.economics.capex_per_kwh * PLN_TO_USD,
                "replace_cost_per_kw": inp.economics.capex_per_kw * PLN_TO_USD * inp.economics.replacement_cost_factor,
                "replace_cost_per_kwh": inp.economics.capex_per_kwh * PLN_TO_USD * inp.economics.replacement_cost_factor,
                "inverter_replacement_year": inp.economics.battery_lifetime_years,
                "battery_replacement_year": inp.economics.battery_lifetime_years,
                "macrs_option_years": 0,  # No US tax credits
                "total_rebate_per_kw": 0,
                "soc_min_fraction": 0.1,
                "soc_init_fraction": 0.5,
                "can_grid_charge": inp.policies.allow_grid_charging,
            },
            "Financial": {
                "analysis_years": inp.economics.analysis_years,
                "offtaker_discount_rate": inp.economics.discount_rate,
                "owner_discount_rate": inp.economics.discount_rate,
                "escalation_rate": inp.economics.inflation_rate,
                "om_cost_escalation_rate": inp.economics.inflation_rate,
            },
        }

        # Add PV if present
        if np.sum(inp.pv_kw) > 0:
            # REopt expects production factor (normalized to 1)
            max_pv = float(np.max(inp.pv_kw))
            if max_pv > 0:
                production_factor = (inp.pv_kw / max_pv).tolist()
                request["PV"] = {
                    "existing_kw": max_pv,  # Treat as existing PV
                    "production_factor_series": production_factor,
                    "min_kw": 0,
                    "max_kw": 0,  # Don't size additional PV
                }

        return request

    def _call_reopt_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call NREL REopt API.

        This submits a job and polls for results.
        """
        import requests

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
        }

        # Submit job
        response = requests.post(
            REOPT_API_URL,
            json=request,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        job_data = response.json()
        job_id = job_data.get("run_uuid")

        if not job_id:
            raise ValueError(f"No job ID in REopt response: {job_data}")

        logger.info(f"REopt job submitted: {job_id}")

        # Poll for results
        results_url = f"{REOPT_API_URL}/{job_id}/results"
        poll_interval = 5  # seconds
        max_polls = self.timeout // poll_interval

        for i in range(max_polls):
            time.sleep(poll_interval)

            response = requests.get(
                results_url,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            result = response.json()
            status = result.get("status", "")

            if status == "optimal":
                logger.info(f"REopt job {job_id} completed: optimal")
                return result
            elif status in ["infeasible", "error", "timeout"]:
                raise ValueError(f"REopt job failed with status: {status}")

            logger.debug(f"REopt job {job_id} status: {status}")

        raise TimeoutError(f"REopt job {job_id} timed out after {self.timeout}s")

    def _call_reopt_local(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call local REopt Julia package.

        Requires Julia and REopt.jl installed.
        """
        try:
            from julia import Main
            Main.eval('using REopt')

            # Convert request to Julia-compatible format
            json_str = json.dumps(request)
            Main.eval(f'input = JSON.parse("""{json_str}""")')
            Main.eval('results = REopt.run_reopt(input)')

            # Get results back
            results_json = Main.eval('JSON.json(results)')
            return json.loads(results_json)

        except Exception as e:
            raise RuntimeError(f"Local REopt failed: {e}")

    def _parse_reopt_result(
        self,
        result: Dict[str, Any],
        inp: CanonicalInput,
        computation_time_ms: float,
    ) -> EngineSizingResult:
        """
        Parse REopt API result into EngineSizingResult.
        """
        warnings = []

        # Extract outputs
        outputs = result.get("outputs", {})
        storage = outputs.get("ElectricStorage", {})
        financial = outputs.get("Financial", {})

        # Battery sizing
        power_kw = storage.get("size_kw", 0)
        energy_kwh = storage.get("size_kwh", 0)
        duration_h = energy_kwh / power_kw if power_kw > 0 else 0

        # Convert USD to PLN
        npv_usd = financial.get("npv", 0)
        npv_pln = npv_usd / PLN_TO_USD

        # Annual metrics
        annual_cycles = storage.get("annual_storage_dispatch_kwh", 0) / energy_kwh if energy_kwh > 0 else 0

        # Solver info
        solver_status = result.get("status", "unknown")
        solver_gap = result.get("mip_gap", 0)

        # Calculate savings (difference vs baseline)
        baseline_cost_usd = outputs.get("ElectricTariff", {}).get("lifecycle_energy_cost_after_tax_bau", 0)
        with_bess_cost_usd = outputs.get("ElectricTariff", {}).get("lifecycle_energy_cost_after_tax", 0)
        annual_savings_usd = (baseline_cost_usd - with_bess_cost_usd) / inp.economics.analysis_years
        annual_savings_pln = annual_savings_usd / PLN_TO_USD

        # CAPEX
        capex_usd = storage.get("storage_capital_cost", 0)
        capex_pln = capex_usd / PLN_TO_USD

        # IRR and payback
        irr_pct = financial.get("internal_rate_of_return", None)
        payback_years = financial.get("simple_payback_years", 999)

        # Create recommendation
        recommended = SizingRecommendation(
            power_kw=power_kw,
            energy_kwh=energy_kwh,
            duration_h=duration_h,
            annual_savings_pln=annual_savings_pln,
            npv_pln=npv_pln,
            irr_pct=irr_pct,
            payback_years=payback_years,
            capex_pln=capex_pln,
            variant_name="REopt-optimal",
        )

        # REopt gives one optimal solution, not S/M/L variants
        # Create synthetic variants around optimal for comparison
        variants = [recommended]

        if power_kw > 0:
            # Add smaller variant
            smaller = SizingRecommendation(
                power_kw=power_kw * 0.5,
                energy_kwh=energy_kwh * 0.5,
                duration_h=duration_h,
                annual_savings_pln=annual_savings_pln * 0.6,  # Rough estimate
                npv_pln=npv_pln * 0.7,
                irr_pct=irr_pct,
                payback_years=payback_years,
                capex_pln=capex_pln * 0.5,
                variant_name="REopt-small",
            )
            variants.insert(0, smaller)

            # Add larger variant
            larger = SizingRecommendation(
                power_kw=power_kw * 1.5,
                energy_kwh=energy_kwh * 1.5,
                duration_h=duration_h,
                annual_savings_pln=annual_savings_pln * 1.3,
                npv_pln=npv_pln * 0.9,  # Larger system may have lower NPV
                irr_pct=irr_pct,
                payback_years=payback_years * 1.2,
                capex_pln=capex_pln * 1.5,
                variant_name="REopt-large",
            )
            variants.append(larger)

        return EngineSizingResult(
            engine_type=self.engine_type,
            engine_version=self.engine_version,
            computation_time_ms=computation_time_ms,
            recommended=recommended,
            variants=variants,
            annual_savings_pln=annual_savings_pln,
            annual_cycles=annual_cycles,
            self_consumption_pct=0,  # REopt doesn't report this directly
            npv_pln=npv_pln,
            irr_pct=irr_pct,
            payback_years=payback_years,
            solver_status=solver_status,
            solver_gap=solver_gap,
            raw_output=result,
            warnings=warnings,
        )

    def _parse_reopt_dispatch(
        self,
        result: Dict[str, Any],
        inp: CanonicalInput,
        battery: CanonicalBattery,
        computation_time_ms: float,
    ) -> EngineDispatchResult:
        """
        Parse REopt dispatch timeseries from result.
        """
        warnings = []

        outputs = result.get("outputs", {})
        storage = outputs.get("ElectricStorage", {})

        # Extract timeseries
        soc_series = storage.get("soc_series_fraction", [])
        charge_series = storage.get("storage_to_load_series_kw", [])
        discharge_series = storage.get("storage_to_grid_series_kw", [])

        # Convert to numpy
        n = len(inp.load_kw)
        if len(soc_series) == n:
            soc = np.array(soc_series)
        else:
            soc = np.zeros(n)
            warnings.append("SOC series length mismatch")

        timeseries = DispatchTimeseries(
            soc=soc,
            charge_kw=np.array(charge_series) if len(charge_series) == n else np.zeros(n),
            discharge_kw=np.array(discharge_series) if len(discharge_series) == n else np.zeros(n),
            grid_import_kw=np.zeros(n),  # TODO: extract from REopt
            grid_export_kw=np.zeros(n),
        )

        # Calculate metrics
        dt = inp.time_axis.dt_hours
        total_charge = float(np.sum(timeseries.charge_kw) * dt)
        total_discharge = float(np.sum(timeseries.discharge_kw) * dt)
        eq_cycles = total_discharge / battery.energy_kwh if battery.energy_kwh > 0 else 0

        return EngineDispatchResult(
            engine_type=self.engine_type,
            engine_version=self.engine_version,
            computation_time_ms=computation_time_ms,
            battery=battery,
            total_charge_kwh=total_charge,
            total_discharge_kwh=total_discharge,
            equivalent_cycles=eq_cycles,
            self_consumption_pct=0,
            peak_reduction_kw=0,
            annual_savings_pln=0,  # TODO: calculate
            savings_breakdown={},
            timeseries=timeseries,
            final_soc=float(soc[-1]) if len(soc) > 0 else 0.5,
            soc_violations=0,
            power_violations=0,
            raw_output=result,
            warnings=warnings,
        )

    def _error_result(
        self,
        error_msg: str,
        start_time: float,
    ) -> EngineSizingResult:
        """Create error sizing result."""
        return EngineSizingResult(
            engine_type=self.engine_type,
            engine_version=self.engine_version,
            computation_time_ms=(time.time() - start_time) * 1000,
            recommended=SizingRecommendation(
                power_kw=0,
                energy_kwh=0,
                duration_h=0,
                annual_savings_pln=0,
                npv_pln=0,
                irr_pct=None,
                payback_years=999,
                capex_pln=0,
                variant_name="error",
            ),
            variants=[],
            annual_savings_pln=0,
            annual_cycles=0,
            self_consumption_pct=0,
            npv_pln=0,
            irr_pct=None,
            payback_years=999,
            solver_status="error",
            solver_gap=0,
            raw_output=None,
            warnings=[error_msg],
        )

    def _dispatch_error_result(
        self,
        battery: CanonicalBattery,
        error_msg: str,
        start_time: float,
    ) -> EngineDispatchResult:
        """Create error dispatch result."""
        return EngineDispatchResult(
            engine_type=self.engine_type,
            engine_version=self.engine_version,
            computation_time_ms=(time.time() - start_time) * 1000,
            battery=battery,
            total_charge_kwh=0,
            total_discharge_kwh=0,
            equivalent_cycles=0,
            self_consumption_pct=0,
            peak_reduction_kw=0,
            annual_savings_pln=0,
            savings_breakdown={},
            timeseries=None,
            final_soc=battery.soc_initial,
            soc_violations=0,
            power_violations=0,
            raw_output=None,
            warnings=[error_msg],
        )
