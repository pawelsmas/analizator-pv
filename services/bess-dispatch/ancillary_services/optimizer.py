"""
Stacked Service Optimizer — LP co-optimization of all battery services.

Uses scipy.linprog (HiGHS) to jointly optimize:
- Behind-the-meter: peak shaving, PV surplus, energy arbitrage
- Ancillary services: aFRR, mFRR, FCR capacity reservation

The optimizer decides, for each timestep:
1. How much capacity to allocate to each service
2. Charge/discharge schedule per service
3. Revenue-optimal split considering:
   - Service prices (capacity + energy)
   - Battery degradation cost per cycle
   - Physical constraints (power, energy, SoC)
   - Service constraints (availability windows, activation requirements)

This is the key differentiator vs pagra-galileo:
- pagra-galileo uses fixed allocation per service
- We use dynamic LP that reallocates every timestep based on prices
"""

import numpy as np
from scipy.optimize import linprog
from typing import Dict, List, Optional, Tuple

from .models import (
    AncillaryServiceType,
    AncillaryServiceConfig,
    BatteryVirtualizationConfig,
    PolishMarketPreset,
    POLISH_MARKET_PRESETS,
    StackedRevenueResult,
    AncillaryRevenueResult,
    ServiceRevenueDetail,
)
from .virtualizer import BatteryVirtualizer
from .revenue import AncillaryRevenueCalculator


class StackedServiceOptimizer:
    """
    Joint optimization of all battery services.

    For each optimization window (typically 24h):
    1. Collect price signals for all services
    2. Build LP: maximize total revenue across all services
    3. Subject to: physical battery constraints + service requirements
    4. Return optimal schedule + revenue breakdown
    """

    def __init__(
        self,
        battery_config: BatteryVirtualizationConfig,
        market_preset: Optional[PolishMarketPreset] = None,
        year: int = 2026,
    ):
        self.battery = battery_config
        self.market = market_preset or POLISH_MARKET_PRESETS.get(
            year, PolishMarketPreset(year=year)
        )
        self.virtualizer = BatteryVirtualizer(battery_config)
        self.revenue_calc = AncillaryRevenueCalculator(battery_config, self.market, year)

    def optimize_day(
        self,
        buy_prices: np.ndarray,
        sell_prices: np.ndarray,
        load_kw: np.ndarray,
        pv_kw: np.ndarray,
        peak_limit_kw: float,
        dt_hours: float = 1.0,
        ancillary_prices: Optional[Dict[str, np.ndarray]] = None,
    ) -> Dict:
        """
        Optimize battery dispatch for one day (24 timesteps).

        Uses simplified LP that maximizes:
          Revenue = sum_t (
            energy_arbitrage_revenue[t]
            + afrr_capacity_revenue[t]
            + mfrr_capacity_revenue[t]
            + peak_shaving_value[t]
            - degradation_cost[t]
          )

        Returns schedule + revenue breakdown per service.
        """
        n = len(load_kw)
        eta = self.battery.roundtrip_efficiency ** 0.5
        total_p = self.battery.total_power_kw
        total_e = self.battery.total_energy_kwh
        soc_min = total_e * 0.10
        soc_max = total_e * 0.90

        # Net load (load - PV)
        net_load = load_kw - pv_kw
        pv_surplus = np.maximum(-net_load, 0)  # PV > load
        load_deficit = np.maximum(net_load, 0)  # load > PV

        # Peak shaving value: how much we save per kW reduced
        # Simplified: value of shaving = buy_price * kW_shaved * dt
        peak_excess = np.maximum(load_deficit - peak_limit_kw, 0)

        # Ancillary service prices (PLN/MW/h for capacity)
        afrr_up_price = np.full(n, self.market.afrr_up_capacity_pln_mw_h / 1000)  # PLN/kW/h
        afrr_down_price = np.full(n, self.market.afrr_down_capacity_pln_mw_h / 1000)
        mfrr_up_price = np.full(n, self.market.mfrr_up_capacity_pln_mw_h / 1000)

        if ancillary_prices:
            if "afrr_up" in ancillary_prices:
                afrr_up_price = ancillary_prices["afrr_up"] / 1000
            if "afrr_down" in ancillary_prices:
                afrr_down_price = ancillary_prices["afrr_down"] / 1000
            if "mfrr_up" in ancillary_prices:
                mfrr_up_price = ancillary_prices["mfrr_up"] / 1000

        # Degradation cost per kWh throughput
        deg_cost = 0.10  # PLN/kWh

        # ── Build LP ──
        # Decision variables per timestep:
        #   charge_arb[t]    - charge for arbitrage [kW]
        #   discharge_arb[t] - discharge for arbitrage [kW]
        #   charge_pv[t]     - charge from PV surplus [kW]
        #   discharge_peak[t]- discharge for peak shaving [kW]
        #   cap_afrr_up[t]   - capacity reserved for aFRR up [kW]
        #   cap_afrr_down[t] - capacity reserved for aFRR down [kW]
        #   cap_mfrr_up[t]   - capacity reserved for mFRR up [kW]

        n_vars_per_t = 7
        n_total = n * n_vars_per_t

        # Variable indices
        def idx(var, t):
            offsets = {
                "charge_arb": 0, "discharge_arb": 1,
                "charge_pv": 2, "discharge_peak": 3,
                "cap_afrr_up": 4, "cap_afrr_down": 5,
                "cap_mfrr_up": 6,
            }
            return t * n_vars_per_t + offsets[var]

        # Objective: MAXIMIZE revenue = MINIMIZE negative revenue
        c = np.zeros(n_total)
        for t in range(n):
            # Arbitrage: revenue = sell_price * discharge - buy_price * charge
            c[idx("discharge_arb", t)] = -(sell_prices[t] - deg_cost / 1000) * dt_hours
            c[idx("charge_arb", t)] = (buy_prices[t] + deg_cost / 1000) * dt_hours

            # PV surplus: free charge (value = avoided export at sell_price)
            c[idx("charge_pv", t)] = -sell_prices[t] * dt_hours * 0.5  # Small incentive to charge

            # Peak shaving: value = buy_price * peak_excess avoided
            if peak_excess[t] > 0:
                c[idx("discharge_peak", t)] = -buy_prices[t] * dt_hours

            # Ancillary capacity: revenue per kW reserved
            c[idx("cap_afrr_up", t)] = -afrr_up_price[t] * dt_hours
            c[idx("cap_afrr_down", t)] = -afrr_down_price[t] * dt_hours
            c[idx("cap_mfrr_up", t)] = -mfrr_up_price[t] * dt_hours

        # Bounds
        bounds = []
        for t in range(n):
            bounds.append((0, total_p))          # charge_arb
            bounds.append((0, total_p))          # discharge_arb
            bounds.append((0, min(pv_surplus[t], total_p)))  # charge_pv
            bounds.append((0, min(peak_excess[t], total_p))) # discharge_peak
            bounds.append((0, total_p))          # cap_afrr_up
            bounds.append((0, total_p))          # cap_afrr_down
            bounds.append((0, total_p))          # cap_mfrr_up

        # Constraints
        A_ub = []
        b_ub = []

        # 1. Total power constraint per timestep
        #    charge_arb + charge_pv <= total_power (charging)
        #    discharge_arb + discharge_peak <= total_power (discharging)
        for t in range(n):
            # Charge power limit
            row = np.zeros(n_total)
            row[idx("charge_arb", t)] = 1
            row[idx("charge_pv", t)] = 1
            A_ub.append(row)
            b_ub.append(total_p)

            # Discharge power limit
            row = np.zeros(n_total)
            row[idx("discharge_arb", t)] = 1
            row[idx("discharge_peak", t)] = 1
            A_ub.append(row)
            b_ub.append(total_p)

            # Capacity reservation + active dispatch <= total power
            # aFRR/mFRR reserved capacity reduces available dispatch power
            row = np.zeros(n_total)
            row[idx("discharge_arb", t)] = 1
            row[idx("discharge_peak", t)] = 1
            row[idx("cap_afrr_up", t)] = 1
            row[idx("cap_mfrr_up", t)] = 1
            A_ub.append(row)
            b_ub.append(total_p)

            row = np.zeros(n_total)
            row[idx("charge_arb", t)] = 1
            row[idx("charge_pv", t)] = 1
            row[idx("cap_afrr_down", t)] = 1
            A_ub.append(row)
            b_ub.append(total_p)

        # 2. SoC constraints (rolling)
        # SoC[t+1] = SoC[t] + (charge * eta - discharge / eta) * dt
        # SoC_min <= SoC[t] <= SoC_max
        for t in range(n):
            # SoC upper bound: initial + sum of net charge <= soc_max
            row_upper = np.zeros(n_total)
            row_lower = np.zeros(n_total)
            for tt in range(t + 1):
                row_upper[idx("charge_arb", tt)] = eta * dt_hours
                row_upper[idx("charge_pv", tt)] = eta * dt_hours
                row_upper[idx("discharge_arb", tt)] = -dt_hours / eta
                row_upper[idx("discharge_peak", tt)] = -dt_hours / eta

                row_lower[idx("charge_arb", tt)] = -eta * dt_hours
                row_lower[idx("charge_pv", tt)] = -eta * dt_hours
                row_lower[idx("discharge_arb", tt)] = dt_hours / eta
                row_lower[idx("discharge_peak", tt)] = dt_hours / eta

            soc_init = total_e * 0.5  # Start at 50%
            A_ub.append(row_upper)
            b_ub.append(soc_max - soc_init)

            A_ub.append(row_lower)
            b_ub.append(soc_init - soc_min)

        A_ub = np.array(A_ub) if A_ub else np.zeros((0, n_total))
        b_ub = np.array(b_ub) if b_ub else np.zeros(0)

        # Solve
        try:
            result = linprog(
                c, A_ub=A_ub, b_ub=b_ub, bounds=bounds,
                method="highs",
                options={"time_limit": 30, "presolve": True},
            )
        except Exception as e:
            return {"error": str(e), "status": "failed"}

        if not result.success:
            return {"error": result.message, "status": result.status}

        # Extract results
        x = result.x
        schedule = {
            "charge_arb_kw": np.array([x[idx("charge_arb", t)] for t in range(n)]),
            "discharge_arb_kw": np.array([x[idx("discharge_arb", t)] for t in range(n)]),
            "charge_pv_kw": np.array([x[idx("charge_pv", t)] for t in range(n)]),
            "discharge_peak_kw": np.array([x[idx("discharge_peak", t)] for t in range(n)]),
            "cap_afrr_up_kw": np.array([x[idx("cap_afrr_up", t)] for t in range(n)]),
            "cap_afrr_down_kw": np.array([x[idx("cap_afrr_down", t)] for t in range(n)]),
            "cap_mfrr_up_kw": np.array([x[idx("cap_mfrr_up", t)] for t in range(n)]),
        }

        # Compute SoC trace
        soc = np.zeros(n + 1)
        soc[0] = total_e * 0.5
        for t in range(n):
            net_charge = (
                (schedule["charge_arb_kw"][t] + schedule["charge_pv_kw"][t]) * eta
                - (schedule["discharge_arb_kw"][t] + schedule["discharge_peak_kw"][t]) / eta
            ) * dt_hours
            soc[t + 1] = soc[t] + net_charge

        schedule["soc_kwh"] = soc

        # Revenue breakdown
        arb_revenue = float(np.sum(
            schedule["discharge_arb_kw"] * sell_prices * dt_hours
            - schedule["charge_arb_kw"] * buy_prices * dt_hours
        ))
        peak_value = float(np.sum(
            schedule["discharge_peak_kw"] * buy_prices * dt_hours
        ))
        afrr_up_rev = float(np.sum(schedule["cap_afrr_up_kw"] * afrr_up_price * dt_hours))
        afrr_down_rev = float(np.sum(schedule["cap_afrr_down_kw"] * afrr_down_price * dt_hours))
        mfrr_up_rev = float(np.sum(schedule["cap_mfrr_up_kw"] * mfrr_up_price * dt_hours))

        total_charge = float(np.sum(
            (schedule["charge_arb_kw"] + schedule["charge_pv_kw"]) * dt_hours
        ))
        total_discharge = float(np.sum(
            (schedule["discharge_arb_kw"] + schedule["discharge_peak_kw"]) * dt_hours
        ))
        throughput_mwh = (total_charge + total_discharge) / 1000
        efc = throughput_mwh / 2 / (total_e / 1000) if total_e > 0 else 0

        degradation_cost = throughput_mwh * 1000 * 0.10  # PLN

        return {
            "status": "optimal",
            "objective_value": float(-result.fun),
            "schedule": schedule,
            "revenue": {
                "energy_arbitrage_pln": arb_revenue,
                "peak_shaving_value_pln": peak_value,
                "afrr_up_capacity_pln": afrr_up_rev,
                "afrr_down_capacity_pln": afrr_down_rev,
                "mfrr_up_capacity_pln": mfrr_up_rev,
                "total_ancillary_pln": afrr_up_rev + afrr_down_rev + mfrr_up_rev,
                "total_btm_pln": arb_revenue + peak_value,
                "degradation_cost_pln": degradation_cost,
                "net_total_pln": (arb_revenue + peak_value + afrr_up_rev
                                  + afrr_down_rev + mfrr_up_rev - degradation_cost),
            },
            "metrics": {
                "total_charge_kwh": total_charge,
                "total_discharge_kwh": total_discharge,
                "throughput_mwh": throughput_mwh,
                "efc": efc,
                "avg_afrr_up_reserved_kw": float(np.mean(schedule["cap_afrr_up_kw"])),
                "avg_afrr_down_reserved_kw": float(np.mean(schedule["cap_afrr_down_kw"])),
                "avg_mfrr_up_reserved_kw": float(np.mean(schedule["cap_mfrr_up_kw"])),
            },
        }

    def optimize_year(
        self,
        buy_prices: np.ndarray,
        sell_prices: np.ndarray,
        load_kw: np.ndarray,
        pv_kw: np.ndarray,
        peak_limit_kw: float,
        dt_hours: float = 1.0,
    ) -> StackedRevenueResult:
        """
        Optimize full year by rolling daily windows.

        Returns aggregated StackedRevenueResult.
        """
        n_steps = len(load_kw)
        steps_per_day = int(24 / dt_hours)
        n_days = n_steps // steps_per_day

        total_arb = 0.0
        total_peak = 0.0
        total_afrr_up = 0.0
        total_afrr_down = 0.0
        total_mfrr = 0.0
        total_deg = 0.0
        total_efc = 0.0
        total_throughput = 0.0
        warnings = []

        for day in range(n_days):
            start = day * steps_per_day
            end = start + steps_per_day
            if end > n_steps:
                break

            result = self.optimize_day(
                buy_prices=buy_prices[start:end],
                sell_prices=sell_prices[start:end],
                load_kw=load_kw[start:end],
                pv_kw=pv_kw[start:end],
                peak_limit_kw=peak_limit_kw,
                dt_hours=dt_hours,
            )

            if result.get("status") != "optimal":
                warnings.append(f"Day {day}: {result.get('error', 'LP failed')}")
                continue

            rev = result["revenue"]
            met = result["metrics"]
            total_arb += rev["energy_arbitrage_pln"]
            total_peak += rev["peak_shaving_value_pln"]
            total_afrr_up += rev["afrr_up_capacity_pln"]
            total_afrr_down += rev["afrr_down_capacity_pln"]
            total_mfrr += rev["mfrr_up_capacity_pln"]
            total_deg += rev["degradation_cost_pln"]
            total_efc += met["efc"]
            total_throughput += met["throughput_mwh"]

        btm_total = total_arb + total_peak
        ancillary_total = total_afrr_up + total_afrr_down + total_mfrr

        # Build ancillary revenue result
        ancillary_result = AncillaryRevenueResult(
            services=[
                ServiceRevenueDetail(
                    service_type=AncillaryServiceType.AFRR_UP,
                    capacity_revenue_pln=total_afrr_up,
                    net_revenue_pln=total_afrr_up * 0.8,  # After aggregator
                    gross_revenue_pln=total_afrr_up,
                    aggregator_fee_pln=total_afrr_up * 0.2,
                ),
                ServiceRevenueDetail(
                    service_type=AncillaryServiceType.AFRR_DOWN,
                    capacity_revenue_pln=total_afrr_down,
                    net_revenue_pln=total_afrr_down * 0.8,
                    gross_revenue_pln=total_afrr_down,
                    aggregator_fee_pln=total_afrr_down * 0.2,
                ),
                ServiceRevenueDetail(
                    service_type=AncillaryServiceType.MFRR_UP,
                    capacity_revenue_pln=total_mfrr,
                    net_revenue_pln=total_mfrr * 0.8,
                    gross_revenue_pln=total_mfrr,
                    aggregator_fee_pln=total_mfrr * 0.2,
                ),
            ],
            total_gross_revenue_pln=ancillary_total,
            total_net_revenue_pln=ancillary_total * 0.8,
            total_aggregator_fees_pln=ancillary_total * 0.2,
            total_degradation_cost_pln=total_deg * 0.3,  # Ancillary share
            total_efc=total_efc * 0.3,
            total_throughput_mwh=total_throughput * 0.3,
            market_preset=self.market,
        )

        return StackedRevenueResult(
            btm_savings_pln=btm_total,
            btm_efc=total_efc * 0.7,
            ancillary_revenue=ancillary_result,
            total_annual_revenue_pln=btm_total + ancillary_total * 0.8 - total_deg,
            total_efc=total_efc,
            allocation_summary={
                "energy_arbitrage": {
                    "revenue_pln": total_arb,
                    "share_pct": total_arb / max(btm_total + ancillary_total, 1) * 100,
                },
                "peak_shaving": {
                    "revenue_pln": total_peak,
                    "share_pct": total_peak / max(btm_total + ancillary_total, 1) * 100,
                },
                "aFRR": {
                    "revenue_pln": total_afrr_up + total_afrr_down,
                    "share_pct": (total_afrr_up + total_afrr_down) / max(btm_total + ancillary_total, 1) * 100,
                },
                "mFRR": {
                    "revenue_pln": total_mfrr,
                    "share_pct": total_mfrr / max(btm_total + ancillary_total, 1) * 100,
                },
            },
            warnings=warnings[:10],
        )
