"""
PLIK: economics_engine.py
ROLA: Jedyne źródło prawdy (SSoT) dla obliczeń NPV, IRR, payback w module BESS.
WEJŚCIE: annual_savings (float), capex (float), NpvConfig (parametry obliczeniowe)
WYJŚCIE: NpvResult (npv, irr, payback, cashflows, effective_years, battery_lifetime)

ZALEŻNOŚCI: brak (standalone — nie importuje żadnych modułów projektu)

NIE ROBI:
  - Nie rozstrzyga cen (to robi PriceResolver / price_engine)
  - Nie liczy savings breakdown (to robi lp_dispatch / dispatch_engine)
  - Nie decyduje o mode (to przychodzi z requestu)

UŻYCIE:
  from economics_engine import NpvConfig, NpvResult, calculate_npv, calculate_simple_payback

  config = NpvConfig(discount_rate=0.07, analysis_years=15)
  result = calculate_npv(annual_savings=50000, capex=300000, config=config)
  print(result.npv_pln, result.irr_pct, result.payback_years)

  # Z degradacją (lifecycle):
  config = NpvConfig(
      discount_rate=0.07, analysis_years=15,
      include_degradation=True,
      efc_per_year=500, energy_kwh=1000, cycles_to_eol=6000,
      savings_escalation_rate=0.025,
  )
  result = calculate_npv(annual_savings=50000, capex=300000, config=config)

Version: 1.0.0 — Faza 1 refaktoringu BESS
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class NpvConfig:
    """
    Konfiguracja obliczeń NPV — jeden obiekt, wiele trybów.

    Tryb prosty (default):
        NpvConfig(discount_rate=0.07, analysis_years=15)
        → stałe cashflows przez analysis_years

    Tryb lifecycle (include_degradation=True):
        → savings skalowane przez SoH(year)
        → horizon skrócony do battery EOL jeśli include_replacement=False
        → z replacement: dodaje koszt wymiany w roku EOL, kontynuuje

    Tryb z eskalacją:
        savings_escalation_rate=0.025 → savings rosną 2.5%/rok (inflacja)
        opex_escalation_rate=0.025 → opex rośnie 2.5%/rok
    """
    # --- Wymagane ---
    discount_rate: float = 0.07
    analysis_years: int = 15
    opex_pct: float = 0.015

    # --- Degradacja (opcjonalne) ---
    include_degradation: bool = False
    efc_per_year: float = 0.0
    energy_kwh: float = 0.0
    cycles_to_eol: float = 6000.0
    eol_soh_pct: float = 70.0
    calendar_deg_year1_pct: float = 2.0   # LFP realistic (was 5.0)
    calendar_deg_annual_pct: float = 1.0  # LFP realistic (was 2.0)
    degradation_curve: str = "linear"     # "linear" or "sqrt"

    # --- Eskalacja (opcjonalne) ---
    savings_escalation_rate: float = 0.0
    opex_escalation_rate: float = 0.0

    # --- Wymiana baterii (opcjonalne) ---
    include_replacement: bool = False
    replacement_cost_factor: float = 0.6  # 60% of original CAPEX

    # --- Koszty dodatkowe ---
    annual_auxiliary_cost_pln: float = 0.0  # HVAC, BMS, PCS standby


@dataclass
class NpvResult:
    """
    Wynik obliczeń NPV — kompletny pakiet ekonomiczny.

    Wszystkie pola wypełnione niezależnie od trybu (prosty/lifecycle).
    """
    npv_pln: float
    irr_pct: Optional[float]
    payback_years: float
    effective_years: int          # Ile lat trwa analiza (= analysis_years lub battery EOL)
    battery_lifetime_years: int   # Kiedy SoH < EOL (= analysis_years jeśli brak degradacji)
    yearly_cashflows: List[float] = field(default_factory=list)  # [CF_0, CF_1, ..., CF_n]


# ---------------------------------------------------------------------------
# SoH model (calendar + cycle aging)
# ---------------------------------------------------------------------------

def combined_soh(
    year: int,
    efc_per_year: float,
    energy_kwh: float,
    cycles_to_eol: float,
    eol_soh_pct: float,
    calendar_deg_year1_pct: float,
    calendar_deg_annual_pct: float,
    degradation_curve: str = "linear",
) -> float:
    """
    SoH w roku `year` = 1 - calendar_loss - cycle_loss.

    Calendar aging: rok 1 wyższy (formacja), potem liniowy.
    Cycle aging: throughput-based (linear lub sqrt).
    Floor: 10% (bateria nie schodzi do 0).
    """
    if year <= 0:
        return 1.0

    eol_factor = eol_soh_pct / 100.0

    # Calendar aging
    cal_year1_loss = calendar_deg_year1_pct / 100.0
    cal_annual_loss = calendar_deg_annual_pct / 100.0
    if year == 1:
        calendar_loss = cal_year1_loss
    else:
        calendar_loss = cal_year1_loss + cal_annual_loss * (year - 1)

    # Cycle aging
    cycle_loss = 0.0
    if efc_per_year > 0 and energy_kwh > 0 and cycles_to_eol > 0:
        cumulative_fec = efc_per_year * year
        progress = min(cumulative_fec / cycles_to_eol, 2.0)
        degradation_range = 1.0 - eol_factor
        if degradation_curve == "sqrt":
            cycle_loss = degradation_range * (progress ** 0.5)
        else:
            cycle_loss = degradation_range * progress

    soh = 1.0 - calendar_loss - cycle_loss
    return max(soh, 0.1)


def battery_lifetime_years(
    efc_per_year: float,
    energy_kwh: float,
    config: NpvConfig,
    max_years: int = 30,
) -> int:
    """Rok w którym SoH spada poniżej eol_soh_pct. Max = max_years."""
    eol_factor = config.eol_soh_pct / 100.0
    for year in range(1, max_years + 1):
        soh = combined_soh(
            year, efc_per_year, energy_kwh,
            config.cycles_to_eol, config.eol_soh_pct,
            config.calendar_deg_year1_pct, config.calendar_deg_annual_pct,
            config.degradation_curve,
        )
        if soh <= eol_factor:
            return year
    return max_years


# ---------------------------------------------------------------------------
# IRR (bisection)
# ---------------------------------------------------------------------------

def calculate_irr_from_cashflows(
    cashflows: List[float],
    lo: float = -0.9,
    hi: float = 3.0,
    max_iterations: int = 80,
    tolerance: float = 1e-6,
) -> Optional[float]:
    """
    IRR z tablicy cashflows metodą bisekcji.
    Zwraca procent (np. 15.0 = 15%) lub None.
    """
    if len(cashflows) < 2:
        return None
    if all(cf <= 0 for cf in cashflows[1:]):
        return None

    def npv_at_rate(rate: float) -> float:
        return sum(float(cf) / ((1.0 + rate) ** t) for t, cf in enumerate(cashflows))

    f_lo = npv_at_rate(lo)
    f_hi = npv_at_rate(hi)

    if abs(f_lo) < tolerance:
        return lo * 100.0
    if abs(f_hi) < tolerance:
        return hi * 100.0
    if f_lo * f_hi > 0:
        return None

    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        f_mid = npv_at_rate(mid)
        if abs(f_mid) < tolerance:
            return mid * 100.0
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    return ((lo + hi) / 2.0) * 100.0


# ---------------------------------------------------------------------------
# Payback
# ---------------------------------------------------------------------------

def calculate_simple_payback(annual_savings: float, capex: float) -> float:
    """Prosty payback w latach. Zwraca 999.0 gdy savings <= 0 (JSON-compatible)."""
    if annual_savings <= 0:
        return 999.0
    return capex / annual_savings


# ---------------------------------------------------------------------------
# GŁÓWNA FUNKCJA: calculate_npv
# ---------------------------------------------------------------------------

def calculate_npv(
    annual_savings: float,
    capex: float,
    config: Optional[NpvConfig] = None,
) -> NpvResult:
    """
    JEDYNA funkcja NPV w systemie BESS.

    Zachowanie zależy od config:
    - config=None lub default → prosty NPV (stałe cashflows)
    - include_degradation=True → lifecycle z SoH curve
    - include_replacement=True → dodaje koszt wymiany w roku EOL
    - savings_escalation_rate > 0 → inflacja na savings
    - opex_escalation_rate > 0 → inflacja na opex

    Zwraca NpvResult z: npv, irr, payback, cashflows, effective_years.
    """
    if config is None:
        config = NpvConfig()

    annual_opex_base = capex * config.opex_pct

    # --- Determine battery lifetime and analysis horizon ---
    if config.include_degradation and config.efc_per_year > 0:
        bat_life = battery_lifetime_years(
            config.efc_per_year, config.energy_kwh, config, config.analysis_years,
        )
    else:
        bat_life = config.analysis_years

    # Effective horizon: analysis_years (always — even if battery dies earlier)
    # If battery dies, replacement or zero savings for remaining years
    horizon = config.analysis_years

    # --- Build yearly cashflows ---
    cashflows = [-capex]  # Year 0
    replacement_applied = False

    for t in range(1, horizon + 1):
        # SoH scaling (1.0 if no degradation)
        if config.include_degradation and config.efc_per_year > 0:
            soh = combined_soh(
                t, config.efc_per_year, config.energy_kwh,
                config.cycles_to_eol, config.eol_soh_pct,
                config.calendar_deg_year1_pct, config.calendar_deg_annual_pct,
                config.degradation_curve,
            )
            eol_factor = config.eol_soh_pct / 100.0
            battery_alive = soh > eol_factor
        else:
            soh = 1.0
            battery_alive = True

        # Savings: escalated × SoH
        if battery_alive:
            esc_factor = (1 + config.savings_escalation_rate) ** t
            year_savings = annual_savings * esc_factor * soh
        elif config.include_replacement and not replacement_applied:
            # Battery died this year → pay replacement, restart SoH
            replacement_applied = True
            replacement_cost = capex * config.replacement_cost_factor
            # After replacement: full SoH, escalated savings
            esc_factor = (1 + config.savings_escalation_rate) ** t
            year_savings = annual_savings * esc_factor * 1.0 - replacement_cost
        elif replacement_applied:
            # Post-replacement: battery alive again with full SoH (simplified)
            esc_factor = (1 + config.savings_escalation_rate) ** t
            years_since_replacement = t - bat_life
            if years_since_replacement > 0 and config.include_degradation:
                soh2 = combined_soh(
                    years_since_replacement, config.efc_per_year, config.energy_kwh,
                    config.cycles_to_eol, config.eol_soh_pct,
                    config.calendar_deg_year1_pct, config.calendar_deg_annual_pct,
                    config.degradation_curve,
                )
                year_savings = annual_savings * esc_factor * soh2
            else:
                year_savings = annual_savings * esc_factor
        else:
            # Battery dead, no replacement → zero savings
            year_savings = 0.0

        # OpEx: escalated
        year_opex = annual_opex_base * ((1 + config.opex_escalation_rate) ** t)

        # Auxiliary cost: escalated with savings rate
        year_aux = config.annual_auxiliary_cost_pln * (
            (1 + config.savings_escalation_rate) ** t
        )

        net_cf = year_savings - year_opex - year_aux
        cashflows.append(net_cf)

    # --- NPV from cashflows ---
    npv = 0.0
    for t, cf in enumerate(cashflows):
        npv += cf / ((1 + config.discount_rate) ** t)

    # --- IRR ---
    irr = calculate_irr_from_cashflows(cashflows)

    # --- Payback ---
    payback = calculate_simple_payback(annual_savings, capex)

    # --- Effective years (how many years have positive cashflow) ---
    effective = horizon
    if config.include_degradation and not config.include_replacement:
        effective = min(bat_life, horizon)

    return NpvResult(
        npv_pln=npv,
        irr_pct=irr,
        payback_years=payback,
        effective_years=effective,
        battery_lifetime_years=bat_life,
        yearly_cashflows=cashflows,
    )
