"""
Native Engine Adapter (Layer 1)
================================

Wraps the existing bess-dispatch sizing and dispatch engines
in the standard adapter interface.

This is the "fast" engine optimized for Polish market:
- Grid search over power/energy combinations
- OSD tariff support (ToU zones, capacity fees)
- 15-min and hourly resolution
- Heuristic dispatch (not MILP)

Version: 1.0.0
"""

import logging
import time
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


class NativeAdapter(EngineAdapter):
    """
    Adapter for the native bess-dispatch engine.

    Wraps existing sizing_runner and dispatch_engine modules.
    """

    @property
    def engine_type(self) -> EngineType:
        return EngineType.NATIVE

    @property
    def engine_version(self) -> str:
        return "1.3.0"  # Match models.py ENGINE_VERSION

    def is_available(self) -> bool:
        """Native engine is always available."""
        return True

    def run_sizing(
        self,
        inp: CanonicalInput,
        power_range_kw: Optional[tuple] = None,
        energy_range_kwh: Optional[tuple] = None,
    ) -> EngineSizingResult:
        """
        Run native sizing using existing grid search.

        This wraps the sizing_runner.run_sizing_variants() function.
        """
        start_time = time.time()
        warnings = []

        try:
            # Import native modules
            from sizing_runner import run_sizing_variants
            from models import (
                SizingRequest,
                BatteryParams,
                PriceConfig,
                DispatchMode,
                StackedModeParams,
                ArbitrageConfig,
                ArbitrageStrategy,
                OptimizationConfig,
                OptimizationObjective,
                AnalyticalPeriodConfig,
                FinanceConfig,
            )

            # Build SizingRequest from CanonicalInput
            # Map dispatch mode
            mode_map = {
                "pv_surplus": DispatchMode.PV_SURPLUS,
                "peak_shaving": DispatchMode.PEAK_SHAVING,
                "stacked": DispatchMode.STACKED,
                "arbitrage": DispatchMode.ARBITRAGE,
                "load_only": DispatchMode.LOAD_ONLY,
            }
            mode = mode_map.get(inp.mode.value, DispatchMode.PV_SURPLUS)

            # Build price config
            price_config = PriceConfig(
                buy_rate_pln_kwh=inp.pricing.avg_price_import,
                sell_rate_pln_kwh=inp.pricing.avg_price_export,
            )

            # Build analytical period
            period_config = AnalyticalPeriodConfig(
                start_datetime=inp.time_axis.start_datetime.isoformat(),
                interval_minutes=inp.time_axis.interval_minutes,
                n_points=inp.time_axis.n_points,
                timezone=inp.time_axis.timezone,
            )

            # Stacked params if applicable
            stacked_params = None
            if inp.policies.peak_limit_kw:
                stacked_params = StackedModeParams(
                    peak_limit_kw=inp.policies.peak_limit_kw,
                    reserve_fraction=inp.policies.reserve_fraction,
                )

            # Arbitrage config if enabled
            arb_config = None
            if inp.policies.arbitrage_enabled:
                strategy_map = {
                    "percentile": ArbitrageStrategy.PERCENTILE_THRESHOLD,
                    "zone_based": ArbitrageStrategy.ZONE_BASED,
                    "spread": ArbitrageStrategy.SPREAD_THRESHOLD,
                }
                arb_config = ArbitrageConfig(
                    strategy=strategy_map.get(
                        inp.policies.arbitrage_strategy,
                        ArbitrageStrategy.ZONE_BASED
                    ),
                    allow_grid_charging=inp.policies.allow_grid_charging,
                )

            # Finance config
            finance_config = FinanceConfig(
                capex_per_kwh=inp.economics.capex_per_kwh,
                capex_per_kw=inp.economics.capex_per_kw,
                opex_pct=inp.economics.opex_pct_per_year,
                discount_rate=inp.economics.discount_rate,
                analysis_years=inp.economics.analysis_years,
            )

            # Build sizing request
            sizing_request = SizingRequest(
                pv_kw=inp.pv_kw.tolist(),
                load_kw=inp.load_kw.tolist(),
                mode=mode,
                durations_h=[1.0, 2.0, 4.0],  # Standard S/M/L
                prices=price_config,
                analytical_period=period_config,
                stacked_params=stacked_params,
                arbitrage_config=arb_config,
                finance=finance_config,
            )

            # Run native sizing
            result = run_sizing_variants(sizing_request)

            # Extract computation time
            computation_time_ms = (time.time() - start_time) * 1000

            # Convert to standard format
            variants = []
            for var in result.variants:
                variants.append(SizingRecommendation(
                    power_kw=var.power_kw,
                    energy_kwh=var.energy_kwh,
                    duration_h=var.duration_h,
                    annual_savings_pln=var.annual_savings_pln,
                    npv_pln=var.npv,
                    irr_pct=var.irr,
                    payback_years=var.payback_years,
                    capex_pln=var.capex,
                    variant_name=var.variant,
                ))

            # Find recommended (highest NPV)
            if result.recommended:
                recommended = SizingRecommendation(
                    power_kw=result.recommended.power_kw,
                    energy_kwh=result.recommended.energy_kwh,
                    duration_h=result.recommended.duration_h,
                    annual_savings_pln=result.recommended.annual_savings_pln,
                    npv_pln=result.recommended.npv,
                    irr_pct=result.recommended.irr,
                    payback_years=result.recommended.payback_years,
                    capex_pln=result.recommended.capex,
                    variant_name=result.recommended.variant,
                )
            elif variants:
                recommended = variants[0]
            else:
                # No valid results - return minimal
                recommended = SizingRecommendation(
                    power_kw=0,
                    energy_kwh=0,
                    duration_h=0,
                    annual_savings_pln=0,
                    npv_pln=0,
                    irr_pct=None,
                    payback_years=999,
                    capex_pln=0,
                    variant_name="none",
                )
                warnings.append("No feasible sizing found")

            return EngineSizingResult(
                engine_type=self.engine_type,
                engine_version=self.engine_version,
                computation_time_ms=computation_time_ms,
                recommended=recommended,
                variants=variants,
                annual_savings_pln=recommended.annual_savings_pln,
                annual_cycles=result.recommended.degradation.efc if result.recommended and result.recommended.degradation else 0,
                self_consumption_pct=result.recommended.self_consumption_pct if result.recommended else 0,
                npv_pln=recommended.npv_pln,
                irr_pct=recommended.irr_pct,
                payback_years=recommended.payback_years,
                solver_status="optimal",
                solver_gap=0.0,
                raw_output=None,  # Could store full result if needed
                warnings=warnings,
            )

        except Exception as e:
            logger.exception(f"Native sizing failed: {e}")
            computation_time_ms = (time.time() - start_time) * 1000

            # Return error result
            return EngineSizingResult(
                engine_type=self.engine_type,
                engine_version=self.engine_version,
                computation_time_ms=computation_time_ms,
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
                solver_gap=0.0,
                raw_output=None,
                warnings=[f"Native sizing error: {str(e)}"],
            )

    def run_dispatch(
        self,
        inp: CanonicalInput,
        battery: CanonicalBattery,
    ) -> EngineDispatchResult:
        """
        Run native dispatch simulation.

        Uses existing dispatch_engine module.
        """
        start_time = time.time()
        warnings = []

        try:
            # Import native dispatch
            from dispatch_engine import (
                dispatch_pv_surplus,
                dispatch_peak_shaving,
                dispatch_stacked,
                dispatch_load_only,
            )
            from models import BatteryParams, StackedModeParams

            # Build battery params
            battery_params = BatteryParams(
                power_kw=battery.power_kw,
                energy_kwh=battery.energy_kwh,
                eta_charge=battery.eta_charge,
                eta_discharge=battery.eta_discharge,
                soc_min=battery.soc_min,
                soc_max=battery.soc_max,
                soc_initial=battery.soc_initial,
            )

            # Select dispatch function based on mode
            pv = inp.pv_kw
            load = inp.load_kw
            dt = inp.time_axis.dt_hours

            if inp.mode.value == "pv_surplus":
                result = dispatch_pv_surplus(pv, load, battery_params, dt)
            elif inp.mode.value == "peak_shaving":
                peak_limit = inp.policies.peak_limit_kw or np.percentile(load, 95)
                result = dispatch_peak_shaving(pv, load, battery_params, peak_limit, dt)
            elif inp.mode.value == "stacked":
                peak_limit = inp.policies.peak_limit_kw or np.percentile(load, 95)
                stacked_params = StackedModeParams(
                    peak_limit_kw=peak_limit,
                    reserve_fraction=inp.policies.reserve_fraction,
                )
                result = dispatch_stacked(pv, load, battery_params, stacked_params, dt)
            elif inp.mode.value == "load_only":
                peak_limit = inp.policies.peak_limit_kw or np.percentile(load, 95)
                result = dispatch_load_only(load, battery_params, peak_limit, dt)
            else:
                # Default to PV surplus
                result = dispatch_pv_surplus(pv, load, battery_params, dt)

            computation_time_ms = (time.time() - start_time) * 1000

            # Extract timeseries
            timeseries = DispatchTimeseries(
                soc=np.array(result.soc_trace),
                charge_kw=np.array(result.charge_kw) if hasattr(result, 'charge_kw') else np.zeros(len(pv)),
                discharge_kw=np.array(result.discharge_kw) if hasattr(result, 'discharge_kw') else np.zeros(len(pv)),
                grid_import_kw=np.array(result.grid_import_kw) if hasattr(result, 'grid_import_kw') else np.zeros(len(pv)),
                grid_export_kw=np.array(result.grid_export_kw) if hasattr(result, 'grid_export_kw') else np.zeros(len(pv)),
            )

            # Calculate metrics
            total_charge = float(np.sum(np.maximum(0, result.bess_kw)) * dt)
            total_discharge = float(np.sum(np.maximum(0, -result.bess_kw)) * dt)
            eq_cycles = total_discharge / battery.energy_kwh if battery.energy_kwh > 0 else 0

            # Self-consumption
            pv_used = float(np.sum(np.minimum(pv, load + np.maximum(0, result.bess_kw))) * dt)
            pv_total = float(np.sum(pv) * dt)
            self_consumption_pct = (pv_used / pv_total * 100) if pv_total > 0 else 0

            # Peak reduction
            original_peak = float(np.max(np.maximum(0, load - pv)))
            with_bess_peak = float(np.max(result.grid_import_kw)) if hasattr(result, 'grid_import_kw') else original_peak
            peak_reduction = original_peak - with_bess_peak

            # Savings breakdown (simplified)
            savings_breakdown = {
                "pv_surplus": result.savings_pln if hasattr(result, 'savings_pln') else 0,
                "peak_shaving": 0,
                "arbitrage": 0,
                "capacity_fee": 0,
            }

            return EngineDispatchResult(
                engine_type=self.engine_type,
                engine_version=self.engine_version,
                computation_time_ms=computation_time_ms,
                battery=battery,
                total_charge_kwh=total_charge,
                total_discharge_kwh=total_discharge,
                equivalent_cycles=eq_cycles,
                self_consumption_pct=self_consumption_pct,
                peak_reduction_kw=peak_reduction,
                annual_savings_pln=result.savings_pln if hasattr(result, 'savings_pln') else 0,
                savings_breakdown=savings_breakdown,
                timeseries=timeseries,
                final_soc=float(result.soc_trace[-1]) if result.soc_trace else 0.5,
                soc_violations=0,
                power_violations=0,
                raw_output=None,
                warnings=warnings,
            )

        except Exception as e:
            logger.exception(f"Native dispatch failed: {e}")
            computation_time_ms = (time.time() - start_time) * 1000

            return EngineDispatchResult(
                engine_type=self.engine_type,
                engine_version=self.engine_version,
                computation_time_ms=computation_time_ms,
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
                warnings=[f"Native dispatch error: {str(e)}"],
            )
