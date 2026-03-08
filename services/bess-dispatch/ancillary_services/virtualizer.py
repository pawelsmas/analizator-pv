"""
Battery Virtualizer — manages virtual slices of a physical battery.

Core responsibilities:
1. Split physical battery into service-specific slices
2. Track SoC per slice independently
3. Resolve conflicts when services compete for capacity
4. Enforce physical constraints (total power, total energy)

The virtualizer sits BETWEEN the dispatch engine and the physical battery,
translating service-level commands into unified charge/discharge actions.

Design inspired by pagra-galileo's battery partitioning approach,
but enhanced with dynamic reallocation and LP co-optimization.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from copy import deepcopy

from .models import (
    AncillaryServiceType,
    BatterySlice,
    BatteryVirtualizationConfig,
    SERVICE_PROPERTIES,
)


class BatteryVirtualizer:
    """
    Manages virtual battery slices for multi-service dispatch.

    Each timestep:
    1. Check which slices are active (time windows)
    2. Compute available capacity per slice
    3. Accept charge/discharge requests per service
    4. Resolve conflicts (priority-based or proportional)
    5. Update SoC per slice and physical SoC
    """

    def __init__(self, config: BatteryVirtualizationConfig):
        self.config = config
        self.slices: Dict[AncillaryServiceType, BatterySlice] = {}
        self._init_slices()

        # Physical state
        self.physical_soc_kwh = sum(s.soc_kwh for s in self.slices.values())
        self.dt_hours = 1.0  # default, set per dispatch

        # Tracking
        self.history: List[Dict] = []

    def _init_slices(self):
        """Initialize slices from config."""
        for s in self.config.slices:
            self.slices[s.service_type] = deepcopy(s)
            # Initialize SoC to middle of range
            if s.soc_kwh == 0:
                mid = s.energy_kwh * (s.soc_min_pct + s.soc_max_pct) / 200.0
                self.slices[s.service_type].soc_kwh = mid

    def reset(self, soc_pct: float = 50.0):
        """Reset all slices to given SoC percentage."""
        for s in self.slices.values():
            s.soc_kwh = s.energy_kwh * soc_pct / 100.0
        self.physical_soc_kwh = sum(s.soc_kwh for s in self.slices.values())
        self.history.clear()

    def get_active_slices(self, hour_of_day: int) -> List[BatterySlice]:
        """Get slices active at given hour."""
        active = []
        for s in self.slices.values():
            if s.active_hours is None or hour_of_day in s.active_hours:
                active.append(s)
        return active

    def get_available_power(
        self,
        direction: str,
        hour_of_day: int,
        exclude_services: Optional[List[AncillaryServiceType]] = None,
    ) -> float:
        """
        Get total available power in a direction.

        Args:
            direction: 'charge' or 'discharge'
            hour_of_day: current hour
            exclude_services: services to exclude from calculation

        Returns:
            Available power [kW]
        """
        exclude = set(exclude_services or [])
        total = 0.0

        for s in self.get_active_slices(hour_of_day):
            if s.service_type in exclude:
                continue

            props = SERVICE_PROPERTIES.get(s.service_type, {})
            svc_dir = props.get("direction", "both")

            if direction == "charge":
                if svc_dir in ("charge", "both", "symmetric"):
                    if s.available_charge_kwh > 0:
                        total += s.power_kw
            elif direction == "discharge":
                if svc_dir in ("discharge", "both", "symmetric"):
                    if s.available_discharge_kwh > 0:
                        total += s.power_kw

        return min(total, self.config.total_power_kw)

    def request_dispatch(
        self,
        service: AncillaryServiceType,
        power_kw: float,
        dt_hours: float,
        hour_of_day: int = 0,
    ) -> Tuple[float, float]:
        """
        Request charge or discharge for a specific service.

        Positive power = discharge, negative = charge.

        Returns:
            (actual_power_kw, energy_kwh): what was actually dispatched
        """
        if service not in self.slices:
            return 0.0, 0.0

        s = self.slices[service]
        eta = self.config.roundtrip_efficiency ** 0.5

        # Check time window
        if s.active_hours is not None and hour_of_day not in s.active_hours:
            return 0.0, 0.0

        if power_kw > 0:
            # Discharge
            max_power = min(power_kw, s.power_kw)
            max_energy = s.available_discharge_kwh / eta  # accounting for losses
            actual_energy = min(max_power * dt_hours, max_energy)
            actual_power = actual_energy / dt_hours if dt_hours > 0 else 0
            soc_delta = actual_energy * eta  # energy leaving battery (before inverter loss)
            # Actually remove from slice
            s.soc_kwh = max(s.energy_kwh * s.soc_min_pct / 100, s.soc_kwh - actual_energy)
        elif power_kw < 0:
            # Charge
            max_power = min(abs(power_kw), s.power_kw)
            max_energy = s.available_charge_kwh
            charge_energy = min(max_power * dt_hours * eta, max_energy)  # after charging losses
            actual_power = -(charge_energy / eta / dt_hours) if dt_hours > 0 else 0
            s.soc_kwh = min(s.energy_kwh * s.soc_max_pct / 100, s.soc_kwh + charge_energy)
            actual_energy = -charge_energy / eta
        else:
            return 0.0, 0.0

        # Update physical SoC
        self.physical_soc_kwh = sum(sl.soc_kwh for sl in self.slices.values())

        return actual_power if power_kw > 0 else actual_power, abs(actual_energy)

    def dispatch_timestep(
        self,
        requests: Dict[AncillaryServiceType, float],
        dt_hours: float,
        hour_of_day: int = 0,
    ) -> Dict[AncillaryServiceType, Tuple[float, float]]:
        """
        Dispatch multiple services in one timestep.

        Resolves conflicts by priority (lower number = higher priority).

        Args:
            requests: {service: power_kw} (positive=discharge, negative=charge)
            dt_hours: timestep duration
            hour_of_day: for time window filtering

        Returns:
            {service: (actual_power, actual_energy)} results per service
        """
        self.dt_hours = dt_hours
        results = {}

        # Sort by priority
        sorted_services = sorted(
            requests.keys(),
            key=lambda st: self.slices.get(st, BatterySlice(
                service_type=st, power_kw=0, energy_kwh=0, priority=99
            )).priority
        )

        # Track physical limits
        remaining_charge_power = self.config.total_power_kw
        remaining_discharge_power = self.config.total_power_kw

        for service in sorted_services:
            power = requests[service]
            if service not in self.slices:
                results[service] = (0.0, 0.0)
                continue

            # Enforce physical power limit
            if power > 0:
                clamped = min(power, remaining_discharge_power)
                actual_p, actual_e = self.request_dispatch(service, clamped, dt_hours, hour_of_day)
                remaining_discharge_power -= abs(actual_p)
            elif power < 0:
                clamped = max(power, -remaining_charge_power)
                actual_p, actual_e = self.request_dispatch(service, clamped, dt_hours, hour_of_day)
                remaining_charge_power -= abs(actual_p)
            else:
                actual_p, actual_e = 0.0, 0.0

            results[service] = (actual_p, actual_e)

        # Record history
        self.history.append({
            "hour_of_day": hour_of_day,
            "requests": dict(requests),
            "results": {k.value: v for k, v in results.items()},
            "soc": {k.value: v.soc_kwh for k, v in self.slices.items()},
            "physical_soc": self.physical_soc_kwh,
        })

        return results

    def get_state_summary(self) -> Dict:
        """Get current state of all slices."""
        return {
            "physical_soc_kwh": self.physical_soc_kwh,
            "physical_soc_pct": (
                self.physical_soc_kwh / self.config.total_energy_kwh * 100
                if self.config.total_energy_kwh > 0 else 0
            ),
            "slices": {
                s.service_type.value: {
                    "soc_kwh": s.soc_kwh,
                    "soc_pct": s.soc_kwh / s.energy_kwh * 100 if s.energy_kwh > 0 else 0,
                    "available_charge_kwh": s.available_charge_kwh,
                    "available_discharge_kwh": s.available_discharge_kwh,
                    "power_kw": s.power_kw,
                    "energy_kwh": s.energy_kwh,
                    "priority": s.priority,
                }
                for s in self.slices.values()
            },
            "allocation_warnings": self.config.validate_allocation(),
        }

    @staticmethod
    def create_default_allocation(
        total_power_kw: float,
        total_energy_kwh: float,
        services: List[AncillaryServiceType],
        roundtrip_efficiency: float = 0.90,
    ) -> BatteryVirtualizationConfig:
        """
        Create a balanced default allocation across services.

        Heuristic allocation strategy:
        - Peak shaving: 20% power, 15% energy (reserve for peaks)
        - aFRR: 40% power, 35% energy (main revenue driver)
        - mFRR: 15% power, 20% energy (secondary)
        - Energy arbitrage: 20% power, 25% energy (spread trading)
        - FCR: 5% power, 5% energy (small symmetric)
        - Capacity market: shares with peak shaving (availability)

        Adjusts proportionally based on which services are requested.
        """
        # Default weights
        weights = {
            AncillaryServiceType.PEAK_SHAVING: {"power": 0.20, "energy": 0.15, "priority": 1},
            AncillaryServiceType.AFRR_UP: {"power": 0.25, "energy": 0.20, "priority": 3},
            AncillaryServiceType.AFRR_DOWN: {"power": 0.15, "energy": 0.15, "priority": 4},
            AncillaryServiceType.MFRR_UP: {"power": 0.10, "energy": 0.15, "priority": 5},
            AncillaryServiceType.MFRR_DOWN: {"power": 0.05, "energy": 0.05, "priority": 6},
            AncillaryServiceType.FCR: {"power": 0.05, "energy": 0.05, "priority": 7},
            AncillaryServiceType.ENERGY_ARBITRAGE: {"power": 0.15, "energy": 0.20, "priority": 8},
            AncillaryServiceType.CAPACITY_MARKET: {"power": 0.05, "energy": 0.05, "priority": 2},
            AncillaryServiceType.PV_SURPLUS: {"power": 0.00, "energy": 0.00, "priority": 9},
        }

        # Filter to requested services
        active_weights = {s: weights.get(s, {"power": 0.1, "energy": 0.1, "priority": 5})
                          for s in services}

        # Normalize
        total_p = sum(w["power"] for w in active_weights.values()) or 1.0
        total_e = sum(w["energy"] for w in active_weights.values()) or 1.0

        slices = []
        for svc, w in active_weights.items():
            p_frac = w["power"] / total_p
            e_frac = w["energy"] / total_e
            slices.append(BatterySlice(
                service_type=svc,
                label=svc.value,
                power_kw=round(total_power_kw * p_frac, 1),
                energy_kwh=round(total_energy_kwh * e_frac, 1),
                soc_min_pct=10.0,
                soc_max_pct=90.0,
                priority=w["priority"],
            ))

        return BatteryVirtualizationConfig(
            total_power_kw=total_power_kw,
            total_energy_kwh=total_energy_kwh,
            roundtrip_efficiency=roundtrip_efficiency,
            slices=slices,
            allow_dynamic_reallocation=True,
        )
