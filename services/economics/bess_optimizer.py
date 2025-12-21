"""
BESS Peak Shaving Optimizer
============================
Optymalny dobór magazynu energii (BESS) do peak shavingu.

Wykorzystuje PyPSA + HiGHS do rozwiązania problemu LP/MIP:
- Minimalizacja kosztu BESS (CAPEX) przy zapewnieniu peak shavingu
- Uwzględnienie ograniczeń fizycznych baterii (DOD, C-rate, sprawność)
- Analiza cykliczności i żywotności

Biblioteki:
- PyPSA: Python for Power System Analysis - modelowanie systemów energetycznych
- HiGHS: High-performance LP/MIP solver (open source, szybki)

Autor: PV Optimizer
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field
from enum import Enum


class OptimizationMethod(str, Enum):
    """Metoda optymalizacji"""
    HEURISTIC = "heuristic"  # Szybka heurystyka (obecna metoda)
    LP_RELAXED = "lp_relaxed"  # LP bez dyskretyzacji - szybsze
    MIP_FULL = "mip_full"  # Pełna optymalizacja MIP - dokładniejsza


class BESSOptimizationRequest(BaseModel):
    """Dane wejściowe do optymalizacji BESS"""
    # Profil obciążenia (kW) - może być godzinowy (60 min) lub 15-minutowy
    load_profile_kw: List[float] = Field(..., min_length=24, description="Profil obciążenia [kW], min 24 interwały")
    timestamps: Optional[List[str]] = Field(None, description="Timestampy ISO8601 (opcjonalne)")

    # Rozdzielczość czasowa danych
    interval_minutes: int = Field(default=60, ge=15, le=60, description="Interwał danych w minutach (15 lub 60)")

    # Parametry peak shaving
    peak_shaving_threshold_kw: float = Field(..., gt=0, description="Próg peak shaving [kW]")

    # Parametry ekonomiczne BESS
    bess_capex_per_kwh: float = Field(default=1500.0, description="Koszt pojemności [PLN/kWh]")
    bess_capex_per_kw: float = Field(default=300.0, description="Koszt mocy [PLN/kW]")
    bess_opex_pct_per_year: float = Field(default=1.5, description="OPEX [% CAPEX/rok]")

    # Parametry techniczne BESS
    depth_of_discharge: float = Field(default=0.8, ge=0.5, le=1.0, description="DOD (0.5-1.0)")
    round_trip_efficiency: float = Field(default=0.90, ge=0.7, le=1.0, description="Sprawność cyklu")
    max_c_rate: float = Field(default=1.0, ge=0.5, le=4.0, description="Max C-rate (moc/pojemność)")
    min_soc: float = Field(default=0.1, ge=0.0, le=0.5, description="Min SOC")
    max_soc: float = Field(default=0.9, ge=0.5, le=1.0, description="Max SOC")

    # Parametry żywotności
    cycle_life: int = Field(default=6000, ge=1000, description="Żywotność cyklowa")
    calendar_life_years: int = Field(default=15, ge=5, description="Żywotność kalendarzowa")

    # Metoda optymalizacji
    method: OptimizationMethod = Field(default=OptimizationMethod.LP_RELAXED)

    # Margines bezpieczeństwa
    safety_margin: float = Field(default=1.2, ge=1.0, le=2.0, description="Margines bezpieczeństwa")


class BESSBlock(BaseModel):
    """Pojedynczy blok przeciążenia"""
    start_idx: int
    end_idx: int
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_hours: float  # Float for 15-min intervals (0.25, 0.5, 0.75, etc.)
    peak_power_kw: float
    total_energy_kwh: float
    max_excess_kw: float


class BESSOptimizationResult(BaseModel):
    """Wynik optymalizacji BESS"""
    # Optymalny rozmiar
    optimal_capacity_kwh: float = Field(..., description="Optymalna pojemność [kWh]")
    optimal_power_kw: float = Field(..., description="Optymalna moc [kW]")

    # Koszty
    capex_total_pln: float
    capex_per_kwh_effective: float  # Po uwzględnieniu mocy
    annual_opex_pln: float

    # Parametry techniczne
    usable_capacity_kwh: float  # Po DOD
    c_rate_actual: float

    # Analiza bloków
    blocks_analyzed: int
    largest_block: BESSBlock
    total_annual_cycles: float
    expected_lifetime_years: float

    # Szczegóły optymalizacji
    method_used: str
    solver_status: str
    optimization_time_ms: float

    # Rekomendacje
    sizing_rationale: str
    warnings: List[str] = Field(default_factory=list)

    # Dane do wizualizacji
    hourly_soc_profile: Optional[List[float]] = None
    hourly_charge_kw: Optional[List[float]] = None
    hourly_discharge_kw: Optional[List[float]] = None


def group_exceedance_blocks(
    load_profile: np.ndarray,
    threshold: float,
    timestamps: Optional[List[str]] = None,
    interval_minutes: int = 60
) -> List[BESSBlock]:
    """
    Grupuje interwały przekroczenia progu w bloki.

    Args:
        load_profile: Profil obciążenia [kW]
        threshold: Próg peak shaving [kW]
        timestamps: Opcjonalne timestampy
        interval_minutes: Interwał w minutach (15 lub 60)

    Returns:
        Lista bloków przeciążenia
    """
    blocks = []
    current_block = None
    hours_per_interval = interval_minutes / 60.0  # 0.25 for 15-min, 1.0 for hourly

    for i, power in enumerate(load_profile):
        excess = power - threshold

        if excess > 0:
            if current_block is None:
                current_block = {
                    'start_idx': i,
                    'powers': [power],
                    'excesses': [excess]
                }
            else:
                current_block['powers'].append(power)
                current_block['excesses'].append(excess)
        else:
            if current_block is not None:
                # Zamknij blok
                # Energy = sum of (excess_kW * hours_per_interval)
                num_intervals = len(current_block['powers'])
                total_energy = sum(current_block['excesses']) * hours_per_interval
                duration = num_intervals * hours_per_interval

                block = BESSBlock(
                    start_idx=current_block['start_idx'],
                    end_idx=i - 1,
                    start_time=timestamps[current_block['start_idx']] if timestamps else None,
                    end_time=timestamps[i - 1] if timestamps else None,
                    duration_hours=duration,
                    peak_power_kw=max(current_block['powers']),
                    total_energy_kwh=total_energy,
                    max_excess_kw=max(current_block['excesses'])
                )
                blocks.append(block)
                current_block = None

    # Zamknij ostatni blok jeśli istnieje
    if current_block is not None:
        num_intervals = len(current_block['powers'])
        total_energy = sum(current_block['excesses']) * hours_per_interval
        duration = num_intervals * hours_per_interval

        block = BESSBlock(
            start_idx=current_block['start_idx'],
            end_idx=len(load_profile) - 1,
            start_time=timestamps[current_block['start_idx']] if timestamps else None,
            end_time=timestamps[-1] if timestamps else None,
            duration_hours=duration,
            peak_power_kw=max(current_block['powers']),
            total_energy_kwh=total_energy,
            max_excess_kw=max(current_block['excesses'])
        )
        blocks.append(block)

    return blocks


def optimize_bess_heuristic(
    request: BESSOptimizationRequest,
    blocks: List[BESSBlock]
) -> Tuple[float, float, str]:
    """
    Szybka heurystyka doboru BESS.

    Zasada: pojemność = energia największego bloku / DOD * margines
            moc = max deficyt * margines
    """
    if not blocks:
        return 0.0, 0.0, "Brak bloków przekroczenia"

    # Znajdź największy blok
    largest = max(blocks, key=lambda b: b.total_energy_kwh)
    max_excess = max(b.max_excess_kw for b in blocks)

    # Oblicz wymagania
    usable_capacity = largest.total_energy_kwh / request.round_trip_efficiency
    total_capacity = usable_capacity / request.depth_of_discharge * request.safety_margin
    power = max_excess * request.safety_margin

    # Sprawdź C-rate
    if power / total_capacity > request.max_c_rate:
        # Zwiększ pojemność dla zachowania C-rate
        total_capacity = power / request.max_c_rate

    rationale = (
        f"Heurystyka: największy blok {largest.total_energy_kwh:.1f} kWh "
        f"przez {largest.duration_hours}h, max deficyt {max_excess:.1f} kW. "
        f"DOD={request.depth_of_discharge*100:.0f}%, "
        f"sprawność={request.round_trip_efficiency*100:.0f}%, "
        f"margines={request.safety_margin*100:.0f}%"
    )

    return total_capacity, power, rationale


def optimize_bess_pypsa(
    request: BESSOptimizationRequest,
    blocks: List[BESSBlock]
) -> Tuple[float, float, str, Dict[str, Any]]:
    """
    Optymalizacja LP/MIP z użyciem PyPSA + HiGHS.

    Model:
    - Minimalizuj: CAPEX_energy * E + CAPEX_power * P
    - Ograniczenia:
      - SOC(t) = SOC(t-1) + charge(t)*eff - discharge(t)/eff
      - SOC_min <= SOC(t) <= SOC_max
      - charge(t) <= P
      - discharge(t) <= P
      - discharge(t) >= excess(t)  dla każdej godziny przekroczenia

    Returns:
        (capacity_kwh, power_kw, rationale, details)
    """
    import time
    start_time = time.time()

    try:
        import pypsa
    except ImportError:
        # Fallback to heuristic if PyPSA not available
        cap, pwr, rationale = optimize_bess_heuristic(request, blocks)
        return cap, pwr, rationale + " [PyPSA niedostępne - użyto heurystyki]", {"status": "fallback"}

    load_profile = np.array(request.load_profile_kw)
    threshold = request.peak_shaving_threshold_kw
    n_intervals = len(load_profile)
    hours_per_interval = request.interval_minutes / 60.0  # 0.25 for 15-min, 1.0 for hourly

    # Utwórz sieć PyPSA
    network = pypsa.Network()
    network.set_snapshots(range(n_intervals))
    # Set snapshot weightings for proper energy calculations (important for 15-min intervals)
    network.snapshot_weightings.loc[:, "objective"] = hours_per_interval
    network.snapshot_weightings.loc[:, "generators"] = hours_per_interval
    network.snapshot_weightings.loc[:, "stores"] = hours_per_interval

    # Dodaj magistralę
    network.add("Bus", "main_bus")

    # Dodaj obciążenie (tylko nadwyżka ponad próg)
    excess = np.maximum(load_profile - threshold, 0)
    network.add(
        "Load",
        "peak_excess",
        bus="main_bus",
        p_set=excess
    )

    # Dodaj magazyn energii z optymalizowaną pojemnością
    # Używamy Store + Link dla lepszej kontroli
    network.add(
        "Store",
        "bess",
        bus="main_bus",
        e_nom_extendable=True,
        e_nom_min=0,
        e_nom_max=1e6,  # Praktycznie bez limitu
        e_min_pu=request.min_soc,
        e_max_pu=request.max_soc,
        e_cyclic=True,  # SOC na końcu = SOC na początku
        standing_loss=0.0001,  # Minimalne straty postojowe
        capital_cost=request.bess_capex_per_kwh,
        marginal_cost=0.001  # Mały koszt marginalny dla stabilności
    )

    # Generator "sieć" do ładowania baterii (darmowy w tym modelu)
    network.add(
        "Generator",
        "grid_charger",
        bus="main_bus",
        p_nom=1e6,  # Bez limitu mocy
        marginal_cost=0.01  # Niski koszt
    )

    # Rozwiąż optymalizację
    try:
        if request.method == OptimizationMethod.MIP_FULL:
            solver_name = "highs"
            solver_options = {"mip_rel_gap": 0.01}
        else:
            solver_name = "highs"
            solver_options = {}

        status = network.optimize(
            solver_name=solver_name,
            solver_options=solver_options
        )

        solve_time = (time.time() - start_time) * 1000

        if status[0] != "ok":
            # Fallback
            cap, pwr, rationale = optimize_bess_heuristic(request, blocks)
            return cap, pwr, f"{rationale} [Solver: {status[1]}]", {"status": status[0]}

        # Wyciągnij wyniki
        optimal_capacity = network.stores.loc["bess", "e_nom_opt"]

        # Oblicz wymaganą moc z profilu rozładowania
        store_p = network.stores_t.p.get("bess", pd.Series([0]*n_intervals))
        max_discharge = store_p.max() if len(store_p) > 0 else 0
        max_charge = abs(store_p.min()) if len(store_p) > 0 else 0
        optimal_power = max(max_discharge, max_charge)

        # Uwzględnij koszt mocy (PyPSA optymalizował tylko pojemność)
        # Dostosuj pojemność dla wymaganego C-rate
        if optimal_power > 0 and optimal_capacity > 0:
            actual_c_rate = optimal_power / optimal_capacity
            if actual_c_rate > request.max_c_rate:
                optimal_capacity = optimal_power / request.max_c_rate

        # Dodaj margines bezpieczeństwa
        optimal_capacity *= request.safety_margin
        optimal_power *= request.safety_margin

        rationale = (
            f"PyPSA+HiGHS LP: optymalna pojemność {optimal_capacity:.1f} kWh, "
            f"moc {optimal_power:.1f} kW. "
            f"Solver: {solve_time:.0f}ms, status: {status[0]}"
        )

        details = {
            "status": status[0],
            "solve_time_ms": solve_time,
            "soc_profile": network.stores_t.e.get("bess", pd.Series()).tolist(),
            "charge_discharge": store_p.tolist()
        }

        return optimal_capacity, optimal_power, rationale, details

    except Exception as e:
        # Fallback
        cap, pwr, rationale = optimize_bess_heuristic(request, blocks)
        return cap, pwr, f"{rationale} [Błąd PyPSA: {str(e)}]", {"status": "error", "error": str(e)}


def optimize_bess(request: BESSOptimizationRequest) -> BESSOptimizationResult:
    """
    Główna funkcja optymalizacji BESS.

    Wybiera metodę na podstawie request.method i zwraca kompletny wynik.
    """
    import time
    start_time = time.time()

    load_profile = np.array(request.load_profile_kw)
    threshold = request.peak_shaving_threshold_kw
    interval_minutes = request.interval_minutes

    # Grupuj bloki przekroczenia (z uwzględnieniem rozdzielczości czasowej)
    blocks = group_exceedance_blocks(load_profile, threshold, request.timestamps, interval_minutes)

    if not blocks:
        return BESSOptimizationResult(
            optimal_capacity_kwh=0,
            optimal_power_kw=0,
            capex_total_pln=0,
            capex_per_kwh_effective=0,
            annual_opex_pln=0,
            usable_capacity_kwh=0,
            c_rate_actual=0,
            blocks_analyzed=0,
            largest_block=BESSBlock(
                start_idx=0, end_idx=0, duration_hours=0,
                peak_power_kw=0, total_energy_kwh=0, max_excess_kw=0
            ),
            total_annual_cycles=0,
            expected_lifetime_years=request.calendar_life_years,
            method_used=request.method.value,
            solver_status="no_blocks",
            optimization_time_ms=0,
            sizing_rationale="Brak przekroczeń progu - BESS nie jest wymagany",
            warnings=[]
        )

    # Wybierz metodę optymalizacji
    if request.method == OptimizationMethod.HEURISTIC:
        capacity, power, rationale = optimize_bess_heuristic(request, blocks)
        details = {"status": "heuristic"}
    else:
        capacity, power, rationale, details = optimize_bess_pypsa(request, blocks)

    # Oblicz koszty
    capex_total = capacity * request.bess_capex_per_kwh + power * request.bess_capex_per_kw
    capex_per_kwh_eff = capex_total / capacity if capacity > 0 else 0
    annual_opex = capex_total * request.bess_opex_pct_per_year / 100

    # Oblicz cykle roczne
    total_energy_shaved = sum(b.total_energy_kwh for b in blocks)
    usable_capacity = capacity * request.depth_of_discharge
    annual_cycles = total_energy_shaved / usable_capacity if usable_capacity > 0 else 0

    # Oblicz żywotność
    cycle_limited_years = request.cycle_life / annual_cycles if annual_cycles > 0 else float('inf')
    expected_lifetime = min(cycle_limited_years, request.calendar_life_years)

    # Znajdź największy blok
    largest_block = max(blocks, key=lambda b: b.total_energy_kwh)

    # Generuj ostrzeżenia
    warnings = []
    c_rate = power / capacity if capacity > 0 else 0

    if c_rate > request.max_c_rate:
        warnings.append(f"C-rate {c_rate:.2f} przekracza limit {request.max_c_rate}")

    if annual_cycles > request.cycle_life / 10:
        warnings.append(f"Wysoka cykliczność ({annual_cycles:.0f} cykli/rok) - rozważ większą pojemność")

    if expected_lifetime < 10:
        warnings.append(f"Krótka żywotność ({expected_lifetime:.1f} lat) - rozważ baterię o dłuższej żywotności")

    total_time = (time.time() - start_time) * 1000

    return BESSOptimizationResult(
        optimal_capacity_kwh=round(capacity, 1),
        optimal_power_kw=round(power, 1),
        capex_total_pln=round(capex_total, 0),
        capex_per_kwh_effective=round(capex_per_kwh_eff, 0),
        annual_opex_pln=round(annual_opex, 0),
        usable_capacity_kwh=round(usable_capacity, 1),
        c_rate_actual=round(c_rate, 2),
        blocks_analyzed=len(blocks),
        largest_block=largest_block,
        total_annual_cycles=round(annual_cycles, 1),
        expected_lifetime_years=round(expected_lifetime, 1),
        method_used=request.method.value,
        solver_status=details.get("status", "ok"),
        optimization_time_ms=round(total_time, 1),
        sizing_rationale=rationale,
        warnings=warnings,
        hourly_soc_profile=details.get("soc_profile"),
        hourly_charge_kw=details.get("charge_discharge")
    )
