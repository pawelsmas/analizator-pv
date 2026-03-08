"""
Ancillary services revenue calculator.

Computes annual revenue from Polish balancing market participation:
- aFRR: capacity payment (PLN/MW/h) + energy activation (PLN/MWh)
- mFRR: capacity payment + energy activation (higher price, fewer hours)
- FCR: capacity payment (symmetric, small allocation)
- Capacity Market: annual payment (PLN/MW/year) with KWD penalty

Revenue formula per service:
  gross = capacity_price * power_MW * availability_hours
        + energy_price * activation_energy_MWh
  net   = gross * (1 - aggregator_margin) - degradation_cost - efficiency_loss

References:
- PSE aFRR avg 2025: 181 PLN/MW/h
- Capacity Market 2026: 264,900 PLN/MW/year (URE)
- KWD: 0.133 (pagra-galileo parameter)
"""

import numpy as np
from typing import Dict, List, Optional

from .models import (
    AncillaryServiceType,
    AncillaryServiceConfig,
    BatterySlice,
    BatteryVirtualizationConfig,
    PolishMarketPreset,
    POLISH_MARKET_PRESETS,
    ServiceRevenueDetail,
    AncillaryRevenueResult,
)


class AncillaryRevenueCalculator:
    """Calculate revenue from ancillary services participation."""

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
        self.year = year

        # Degradation cost estimate (PLN per kWh throughput)
        # Based on CAPEX 1200 PLN/kWh, 6000 FEC lifetime
        self._degradation_cost_per_kwh = 1200.0 / 6000.0 / 2  # ~0.10 PLN/kWh

    def calculate_all(
        self,
        services: Optional[List[AncillaryServiceConfig]] = None,
    ) -> AncillaryRevenueResult:
        """
        Calculate revenue for all configured services.

        If services not provided, auto-generates from battery slices + market preset.
        """
        if services is None:
            services = self._auto_configure_services()

        details = []
        for svc in services:
            if not svc.enabled:
                continue
            detail = self._calculate_service(svc)
            details.append(detail)

        result = AncillaryRevenueResult(
            services=details,
            total_gross_revenue_pln=sum(d.gross_revenue_pln for d in details),
            total_net_revenue_pln=sum(d.net_revenue_pln for d in details),
            total_aggregator_fees_pln=sum(d.aggregator_fee_pln for d in details),
            total_degradation_cost_pln=sum(d.degradation_cost_pln for d in details),
            total_efc=sum(d.efc_contribution for d in details),
            total_throughput_mwh=sum(d.throughput_mwh for d in details),
            market_preset=self.market,
        )
        return result

    def _calculate_service(self, svc: AncillaryServiceConfig) -> ServiceRevenueDetail:
        """Calculate revenue for a single service."""
        power_mw = svc.power_kw / 1000.0
        energy_mwh = svc.energy_kwh / 1000.0

        if svc.service_type == AncillaryServiceType.CAPACITY_MARKET:
            return self._calc_capacity_market(svc, power_mw)
        elif svc.service_type in (AncillaryServiceType.AFRR_UP, AncillaryServiceType.AFRR_DOWN):
            return self._calc_afrr(svc, power_mw, energy_mwh)
        elif svc.service_type in (AncillaryServiceType.MFRR_UP, AncillaryServiceType.MFRR_DOWN):
            return self._calc_mfrr(svc, power_mw, energy_mwh)
        elif svc.service_type == AncillaryServiceType.FCR:
            return self._calc_fcr(svc, power_mw)
        else:
            return ServiceRevenueDetail(
                service_type=svc.service_type,
                power_allocated_kw=svc.power_kw,
                energy_allocated_kwh=svc.energy_kwh,
            )

    def _calc_capacity_market(
        self, svc: AncillaryServiceConfig, power_mw: float
    ) -> ServiceRevenueDetail:
        """
        Capacity Market (Rynek Mocy) revenue.

        Revenue = price_per_MW_year * power_MW * (1 - KWD * unavailability)
        Reduced by test/real call-up costs (energy for activation).
        """
        annual_payment = self.market.capacity_market_pln_mw_year * power_mw

        # Availability factor (assume 95% availability for BESS)
        availability = svc.min_availability_pct / 100.0
        # KWD penalty for unavailability
        penalty_factor = 1.0 - self.market.kwd * (1.0 - availability)
        capacity_revenue = annual_payment * max(penalty_factor, 0)

        # Activation costs (test + real call-ups)
        n_activations = (
            self.market.capacity_market_test_activations
            + self.market.capacity_market_real_activations
        )
        # Each activation: 2h at full power (typical)
        activation_hours = n_activations * 2.0
        activation_energy_mwh = power_mw * activation_hours
        # Energy cost at avg buy price (~400 PLN/MWh)
        energy_cost = activation_energy_mwh * 400.0

        gross = capacity_revenue
        aggregator_fee = gross * svc.aggregator_margin_pct / 100.0
        degradation_cost = activation_energy_mwh * 1000 * self._degradation_cost_per_kwh
        efficiency_loss = activation_energy_mwh * 1000 * (1 - self.battery.roundtrip_efficiency) * 0.4  # PLN/kWh avg price
        net = gross - aggregator_fee - degradation_cost - efficiency_loss - energy_cost

        efc = activation_energy_mwh / (svc.energy_kwh / 1000) if svc.energy_kwh > 0 else 0

        return ServiceRevenueDetail(
            service_type=svc.service_type,
            enabled=True,
            capacity_revenue_pln=capacity_revenue,
            availability_hours=8760 * availability,
            energy_revenue_pln=-energy_cost,  # Cost of activations
            activation_count=n_activations,
            activation_energy_mwh=activation_energy_mwh,
            aggregator_fee_pln=aggregator_fee,
            degradation_cost_pln=degradation_cost,
            efficiency_loss_pln=efficiency_loss,
            gross_revenue_pln=gross,
            net_revenue_pln=net,
            efc_contribution=efc,
            throughput_mwh=activation_energy_mwh * 2,  # charge + discharge
            power_allocated_kw=svc.power_kw,
            energy_allocated_kwh=svc.energy_kwh,
        )

    def _calc_afrr(
        self, svc: AncillaryServiceConfig, power_mw: float, energy_mwh: float
    ) -> ServiceRevenueDetail:
        """
        aFRR revenue: capacity payment + energy activation.

        Capacity: price_PLN_MW_h * power_MW * availability_hours
        Energy: price_PLN_MWh * activated_MWh (on activation events)
        """
        is_up = svc.service_type == AncillaryServiceType.AFRR_UP
        cap_price = (self.market.afrr_up_capacity_pln_mw_h if is_up
                     else self.market.afrr_down_capacity_pln_mw_h)

        if svc.capacity_price_pln_mw_h > 0:
            cap_price = svc.capacity_price_pln_mw_h

        # Availability hours (assume available during active_hours or full year)
        avail_hours = 8760 * (svc.min_availability_pct / 100.0)
        capacity_revenue = cap_price * power_mw * avail_hours

        # Energy activation revenue
        act_hours = (svc.expected_activation_hours_per_year
                     if svc.expected_activation_hours_per_year > 0
                     else self.market.afrr_activation_hours_year)
        energy_price = (svc.energy_price_pln_mwh
                        if svc.energy_price_pln_mwh > 0
                        else self.market.afrr_energy_pln_mwh)
        activation_energy = power_mw * act_hours
        energy_revenue = energy_price * activation_energy

        gross = capacity_revenue + energy_revenue
        aggregator_fee = gross * svc.aggregator_margin_pct / 100.0
        degradation_cost = activation_energy * 1000 * self._degradation_cost_per_kwh
        efficiency_loss = activation_energy * 1000 * (1 - self.battery.roundtrip_efficiency) * 0.35
        net = gross - aggregator_fee - degradation_cost - efficiency_loss

        efc = (activation_energy * 2) / energy_mwh if energy_mwh > 0 else 0

        return ServiceRevenueDetail(
            service_type=svc.service_type,
            enabled=True,
            capacity_revenue_pln=capacity_revenue,
            availability_hours=avail_hours,
            energy_revenue_pln=energy_revenue,
            activation_count=int(act_hours),
            activation_energy_mwh=activation_energy,
            aggregator_fee_pln=aggregator_fee,
            degradation_cost_pln=degradation_cost,
            efficiency_loss_pln=efficiency_loss,
            gross_revenue_pln=gross,
            net_revenue_pln=net,
            efc_contribution=efc,
            throughput_mwh=activation_energy * 2,
            power_allocated_kw=svc.power_kw,
            energy_allocated_kwh=svc.energy_kwh,
        )

    def _calc_mfrr(
        self, svc: AncillaryServiceConfig, power_mw: float, energy_mwh: float
    ) -> ServiceRevenueDetail:
        """
        mFRR revenue: capacity payment + energy activation.

        Similar to aFRR but fewer activation hours, higher energy price.
        """
        is_up = svc.service_type == AncillaryServiceType.MFRR_UP
        cap_price = (self.market.mfrr_up_capacity_pln_mw_h if is_up
                     else self.market.mfrr_down_capacity_pln_mw_h)

        if svc.capacity_price_pln_mw_h > 0:
            cap_price = svc.capacity_price_pln_mw_h

        avail_hours = 8760 * (svc.min_availability_pct / 100.0)
        capacity_revenue = cap_price * power_mw * avail_hours

        # mFRR has fewer activations but higher energy price
        n_activations = (svc.expected_activations_per_year
                         if svc.expected_activations_per_year > 0
                         else self.market.mfrr_activations_year)
        hours_per_activation = 1.0  # avg 1h per activation
        act_hours = n_activations * hours_per_activation
        energy_price = (svc.energy_price_pln_mwh
                        if svc.energy_price_pln_mwh > 0
                        else self.market.mfrr_energy_pln_mwh)
        activation_energy = power_mw * act_hours
        energy_revenue = energy_price * activation_energy

        gross = capacity_revenue + energy_revenue
        aggregator_fee = gross * svc.aggregator_margin_pct / 100.0
        degradation_cost = activation_energy * 1000 * self._degradation_cost_per_kwh
        efficiency_loss = activation_energy * 1000 * (1 - self.battery.roundtrip_efficiency) * 0.35
        net = gross - aggregator_fee - degradation_cost - efficiency_loss

        efc = (activation_energy * 2) / energy_mwh if energy_mwh > 0 else 0

        return ServiceRevenueDetail(
            service_type=svc.service_type,
            enabled=True,
            capacity_revenue_pln=capacity_revenue,
            availability_hours=avail_hours,
            energy_revenue_pln=energy_revenue,
            activation_count=n_activations,
            activation_energy_mwh=activation_energy,
            aggregator_fee_pln=aggregator_fee,
            degradation_cost_pln=degradation_cost,
            efficiency_loss_pln=efficiency_loss,
            gross_revenue_pln=gross,
            net_revenue_pln=net,
            efc_contribution=efc,
            throughput_mwh=activation_energy * 2,
            power_allocated_kw=svc.power_kw,
            energy_allocated_kwh=svc.energy_kwh,
        )

    def _calc_fcr(
        self, svc: AncillaryServiceConfig, power_mw: float
    ) -> ServiceRevenueDetail:
        """
        FCR revenue: symmetric capacity payment only.

        FCR requires fast response (30s) and symmetric up/down.
        Revenue is purely from capacity availability.
        """
        cap_price = (svc.capacity_price_pln_mw_h
                     if svc.capacity_price_pln_mw_h > 0
                     else self.market.fcr_capacity_pln_mw_h)

        avail_hours = 8760 * (svc.min_availability_pct / 100.0)
        capacity_revenue = cap_price * power_mw * avail_hours

        # FCR has minimal energy throughput (regulation signal is ~zero mean)
        activation_energy = power_mw * 50  # ~50 MWh/MW/year typical
        degradation_cost = activation_energy * 1000 * self._degradation_cost_per_kwh * 0.3  # Lower for FCR (shallow cycles)

        gross = capacity_revenue
        aggregator_fee = gross * svc.aggregator_margin_pct / 100.0
        net = gross - aggregator_fee - degradation_cost

        efc = activation_energy / (svc.energy_kwh / 1000) if svc.energy_kwh > 0 else 0

        return ServiceRevenueDetail(
            service_type=svc.service_type,
            enabled=True,
            capacity_revenue_pln=capacity_revenue,
            availability_hours=avail_hours,
            energy_revenue_pln=0.0,
            activation_count=0,
            activation_energy_mwh=activation_energy,
            aggregator_fee_pln=aggregator_fee,
            degradation_cost_pln=degradation_cost,
            efficiency_loss_pln=0.0,
            gross_revenue_pln=gross,
            net_revenue_pln=net,
            efc_contribution=efc,
            throughput_mwh=activation_energy * 2,
            power_allocated_kw=svc.power_kw,
            energy_allocated_kwh=svc.energy_kwh,
        )

    def _auto_configure_services(self) -> List[AncillaryServiceConfig]:
        """
        Auto-generate service configs from battery slices + market preset.

        Creates one AncillaryServiceConfig per BatterySlice that maps
        to an ancillary service type.
        """
        configs = []
        for slice_ in self.battery.slices:
            st = slice_.service_type
            if st in (AncillaryServiceType.PEAK_SHAVING, AncillaryServiceType.PV_SURPLUS,
                      AncillaryServiceType.ENERGY_ARBITRAGE):
                continue  # BTM services handled by dispatch engine

            cfg = AncillaryServiceConfig(
                service_type=st,
                enabled=True,
                power_kw=slice_.power_kw,
                energy_kwh=slice_.energy_kwh,
                aggregator_margin_pct=self.market.aggregator_margin_pct,
                min_availability_pct=95.0,
            )

            # Set prices from market preset
            if st == AncillaryServiceType.AFRR_UP:
                cfg.capacity_price_pln_mw_h = self.market.afrr_up_capacity_pln_mw_h
                cfg.energy_price_pln_mwh = self.market.afrr_energy_pln_mwh
                cfg.expected_activation_hours_per_year = self.market.afrr_activation_hours_year
            elif st == AncillaryServiceType.AFRR_DOWN:
                cfg.capacity_price_pln_mw_h = self.market.afrr_down_capacity_pln_mw_h
                cfg.energy_price_pln_mwh = self.market.afrr_energy_pln_mwh
                cfg.expected_activation_hours_per_year = self.market.afrr_activation_hours_year
            elif st == AncillaryServiceType.MFRR_UP:
                cfg.capacity_price_pln_mw_h = self.market.mfrr_up_capacity_pln_mw_h
                cfg.energy_price_pln_mwh = self.market.mfrr_energy_pln_mwh
                cfg.expected_activations_per_year = self.market.mfrr_activations_year
            elif st == AncillaryServiceType.MFRR_DOWN:
                cfg.capacity_price_pln_mw_h = self.market.mfrr_down_capacity_pln_mw_h
                cfg.energy_price_pln_mwh = self.market.mfrr_energy_pln_mwh
                cfg.expected_activations_per_year = self.market.mfrr_activations_year
            elif st == AncillaryServiceType.FCR:
                cfg.capacity_price_pln_mw_h = self.market.fcr_capacity_pln_mw_h
            elif st == AncillaryServiceType.CAPACITY_MARKET:
                cfg.capacity_price_pln_mw_h = self.market.capacity_market_pln_mw_year / 8760
                cfg.expected_activations_per_year = (
                    self.market.capacity_market_test_activations
                    + self.market.capacity_market_real_activations
                )

            configs.append(cfg)
        return configs
