"""
Capacity Fee Calculator for Polish Capacity Market (Opłata Mocowa)

Implements the calculation according to:
- Ustawa z dnia 8 grudnia 2017 r. o rynku mocy
- Informacja Prezesa URE nr 58/2025

Key formulas:
- WOM = A × SOM × ZS
- Δs = (avg_selected / avg_outside - 1) × 100%

K-class classification:
- K1: Δs < 5%     → A = 0.17
- K2: Δs ∈ [5%, 10%) → A = 0.50
- K3: Δs ∈ [10%, 15%) → A = 0.83
- K4: Δs ≥ 15% OR ZPS=0 → A = 1.00

IMPORTANT: Input must be grid_import_kwh (energy from grid), not load!
"""

import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Tuple, Dict, Optional
import logging

from .models import (
    KClass,
    K_COEFFICIENTS,
    QualificationPeriod,
    CapacityFeeConfig,
    DailyClassification,
    MonthlyResult,
    CapacityFeeResult,
    CapacityFeeSavings,
)
from .calendar_pl import (
    is_workday,
    get_day_type,
    DayType,
    get_workdays_in_month,
)

logger = logging.getLogger(__name__)


def build_selected_hours_mask(
    time_index: List[datetime],
    config: CapacityFeeConfig
) -> np.ndarray:
    """
    Build a boolean mask for "selected hours" (godziny wybrane).

    Selected hours are the hours when capacity fee applies:
    - Only on workdays (Mon-Fri, excluding Polish holidays)
    - Within the selected window (default: 7:00-22:00)

    Args:
        time_index: List of datetime objects (hourly or 15-min resolution)
        config: Capacity fee configuration

    Returns:
        np.ndarray of bool - True for hours within selected window on workdays
    """
    mask = np.zeros(len(time_index), dtype=bool)

    for i, dt in enumerate(time_index):
        # Only workdays qualify
        if get_day_type(dt) != DayType.WORKDAY:
            continue

        # Get window for this month's quarter
        window = config.get_window_for_month(dt.month)
        start_hour, end_hour = window

        # Check if hour is within window
        # Use minute_of_day for 15-min resolution compatibility
        minute_of_day = dt.hour * 60 + dt.minute
        start_minute = start_hour * 60
        end_minute = end_hour * 60  # exclusive

        if start_minute <= minute_of_day < end_minute:
            mask[i] = True

    return mask


def classify_period_K(
    energy_kwh: np.ndarray,
    selected_mask: np.ndarray
) -> Tuple[KClass, float, float, float]:
    """
    Classify a period (day/decade/month) into K-class based on Δs.

    Δs = (avg_selected / avg_outside - 1) × 100%

    Args:
        energy_kwh: Energy values for the period [kWh]
        selected_mask: Boolean mask for selected hours

    Returns:
        Tuple of (k_class, delta_s_percent, zs_kwh, zps_kwh)
    """
    # Calculate energy sums
    zs = float(np.sum(energy_kwh[selected_mask]))    # Energy in selected hours
    zps = float(np.sum(energy_kwh[~selected_mask]))  # Energy outside selected hours

    # Count hours
    n_selected = int(np.sum(selected_mask))
    n_outside = int(np.sum(~selected_mask))

    # Special case: no consumption outside selected hours → K4
    if zps == 0 or n_outside == 0:
        return KClass.K4, float('inf'), zs, zps

    # Special case: no selected hours (non-workday period)
    if n_selected == 0:
        return KClass.K4, 0.0, 0.0, zps

    # Calculate averages
    avg_s = zs / n_selected
    avg_ps = zps / n_outside

    # Edge case: no consumption outside
    if avg_ps == 0:
        return KClass.K4, float('inf'), zs, zps

    # Calculate Δs
    delta_s = (avg_s / avg_ps - 1) * 100

    # Classify based on thresholds
    if delta_s < 5:
        k_class = KClass.K1
    elif delta_s < 10:
        k_class = KClass.K2
    elif delta_s < 15:
        k_class = KClass.K3
    else:
        k_class = KClass.K4

    return k_class, delta_s, zs, zps


def compute_capacity_fee(
    grid_import_kwh: np.ndarray,
    time_index: List[datetime],
    config: Optional[CapacityFeeConfig] = None
) -> CapacityFeeResult:
    """
    Compute Polish capacity market fee (opłata mocowa).

    IMPORTANT: Input must be grid_import_kwh (energy imported from grid),
    not load! After PV/BESS dispatch, grid import may be different from load.

    Formula: WOM = A × SOM × ZS
    where:
    - A = coefficient based on K-class (0.17/0.50/0.83/1.00)
    - SOM = capacity fee rate [PLN/kWh]
    - ZS = energy in selected hours [kWh]

    Args:
        grid_import_kwh: Grid import profile [kWh] - hourly or 15-min resolution
        time_index: List of datetime objects matching grid_import_kwh
        config: Capacity fee configuration (defaults to 2026)

    Returns:
        CapacityFeeResult with detailed breakdown
    """
    if config is None:
        config = CapacityFeeConfig()

    if len(grid_import_kwh) != len(time_index):
        raise ValueError(
            f"grid_import_kwh length ({len(grid_import_kwh)}) must match "
            f"time_index length ({len(time_index)})"
        )

    # Build selected hours mask
    selected_mask = build_selected_hours_mask(time_index, config)

    # Determine qualification period
    qual_period = config.get_qualification_period_for_year(config.year)

    # Group data by day
    daily_data: Dict[date, Dict] = {}

    for i, dt in enumerate(time_index):
        day = dt.date()

        if day not in daily_data:
            daily_data[day] = {
                'indices': [],
                'day_type': get_day_type(dt),
            }

        daily_data[day]['indices'].append(i)

    # Process each workday
    daily_results: List[DailyClassification] = []
    total_fee = 0.0
    total_zs = 0.0
    k_histogram = {k.value: 0 for k in KClass}

    for day, day_info in sorted(daily_data.items()):
        # Skip non-workdays
        if day_info['day_type'] != DayType.WORKDAY:
            continue

        indices = day_info['indices']
        day_energy = grid_import_kwh[indices]
        day_mask = selected_mask[indices]

        # Classify the day
        k_class, delta_s, zs, zps = classify_period_K(day_energy, day_mask)
        a_coeff = K_COEFFICIENTS[k_class]

        # Calculate fee for this day
        day_fee = a_coeff * config.som_pln_per_kwh * zs

        # Create result
        result = DailyClassification(
            date=day,
            k_class=k_class,
            a_coefficient=a_coeff,
            delta_s_percent=delta_s if delta_s != float('inf') else 999.99,
            zs_kwh=zs,
            zps_kwh=zps,
            fee_pln=day_fee,
            n_selected_hours=int(np.sum(day_mask)),
            n_outside_hours=int(np.sum(~day_mask)),
        )

        daily_results.append(result)
        total_fee += day_fee
        total_zs += zs
        k_histogram[k_class.value] += 1

    # Aggregate by month
    monthly_results: List[MonthlyResult] = []

    for month in range(1, 13):
        month_days = [r for r in daily_results if r.date.month == month]

        if not month_days:
            monthly_results.append(MonthlyResult(
                month=month,
                total_fee_pln=0.0,
                total_zs_kwh=0.0,
                workdays_count=0,
                k_histogram={k.value: 0 for k in KClass},
                avg_delta_s=0.0,
            ))
            continue

        month_fee = sum(r.fee_pln for r in month_days)
        month_zs = sum(r.zs_kwh for r in month_days)
        month_k_hist = {k.value: 0 for k in KClass}
        for r in month_days:
            month_k_hist[r.k_class.value] += 1

        valid_deltas = [r.delta_s_percent for r in month_days if r.delta_s_percent < 999]
        avg_delta = sum(valid_deltas) / len(valid_deltas) if valid_deltas else 0.0

        monthly_results.append(MonthlyResult(
            month=month,
            total_fee_pln=month_fee,
            total_zs_kwh=month_zs,
            workdays_count=len(month_days),
            k_histogram=month_k_hist,
            avg_delta_s=avg_delta,
        ))

    # Get top 10 days by fee
    top_10 = sorted(daily_results, key=lambda x: x.fee_pln, reverse=True)[:10]

    # Calculate overall average Δs
    valid_deltas = [r.delta_s_percent for r in daily_results if r.delta_s_percent < 999]
    avg_delta_s = sum(valid_deltas) / len(valid_deltas) if valid_deltas else 0.0

    return CapacityFeeResult(
        total_fee_pln=total_fee,
        total_zs_kwh=total_zs,
        monthly_results=monthly_results,
        k_histogram=k_histogram,
        top_10_days=top_10,
        config=config,
        workdays_count=len(daily_results),
        avg_delta_s=avg_delta_s,
    )


def compute_capacity_fee_savings(
    grid_import_before_kwh: np.ndarray,
    grid_import_after_kwh: np.ndarray,
    time_index: List[datetime],
    config: Optional[CapacityFeeConfig] = None
) -> CapacityFeeSavings:
    """
    Compare capacity fee before and after BESS installation.

    This shows the potential savings from BESS by:
    1. Reducing energy consumption in selected hours (ZS reduction)
    2. Shifting to better K-class (lower A coefficient)

    Args:
        grid_import_before_kwh: Grid import before BESS [kWh]
        grid_import_after_kwh: Grid import after BESS [kWh]
        time_index: List of datetime objects
        config: Capacity fee configuration

    Returns:
        CapacityFeeSavings with detailed comparison
    """
    if config is None:
        config = CapacityFeeConfig()

    # Calculate fees for both scenarios
    result_before = compute_capacity_fee(grid_import_before_kwh, time_index, config)
    result_after = compute_capacity_fee(grid_import_after_kwh, time_index, config)

    # Calculate savings
    savings_pln = result_before.total_fee_pln - result_after.total_fee_pln
    savings_pct = (
        (savings_pln / result_before.total_fee_pln * 100)
        if result_before.total_fee_pln > 0 else 0.0
    )

    # Monthly comparison
    monthly_comparison = []
    for i in range(12):
        before_month = result_before.monthly_results[i]
        after_month = result_after.monthly_results[i]

        monthly_comparison.append({
            'month': i + 1,
            'fee_before_pln': before_month.total_fee_pln,
            'fee_after_pln': after_month.total_fee_pln,
            'savings_pln': before_month.total_fee_pln - after_month.total_fee_pln,
            'zs_before_kwh': before_month.total_zs_kwh,
            'zs_after_kwh': after_month.total_zs_kwh,
            'zs_reduction_kwh': before_month.total_zs_kwh - after_month.total_zs_kwh,
        })

    # Calculate K-class shifts
    # This requires day-by-day comparison
    k_shifts = {
        'K4_to_K3': 0, 'K4_to_K2': 0, 'K4_to_K1': 0,
        'K3_to_K2': 0, 'K3_to_K1': 0,
        'K2_to_K1': 0,
    }

    # Build lookup for after results
    after_by_date = {r.date: r for r in result_after.top_10_days}

    # Compare top days (simplified - full comparison would need all days)
    for before_day in result_before.top_10_days:
        if before_day.date in after_by_date:
            after_day = after_by_date[before_day.date]
            before_k = before_day.k_class
            after_k = after_day.k_class

            if before_k == KClass.K4:
                if after_k == KClass.K3:
                    k_shifts['K4_to_K3'] += 1
                elif after_k == KClass.K2:
                    k_shifts['K4_to_K2'] += 1
                elif after_k == KClass.K1:
                    k_shifts['K4_to_K1'] += 1
            elif before_k == KClass.K3:
                if after_k == KClass.K2:
                    k_shifts['K3_to_K2'] += 1
                elif after_k == KClass.K1:
                    k_shifts['K3_to_K1'] += 1
            elif before_k == KClass.K2:
                if after_k == KClass.K1:
                    k_shifts['K2_to_K1'] += 1

    return CapacityFeeSavings(
        fee_before_pln=result_before.total_fee_pln,
        k_histogram_before=result_before.k_histogram,
        avg_delta_s_before=result_before.avg_delta_s,
        fee_after_pln=result_after.total_fee_pln,
        k_histogram_after=result_after.k_histogram,
        avg_delta_s_after=result_after.avg_delta_s,
        savings_pln=savings_pln,
        savings_percent=savings_pct,
        monthly_comparison=monthly_comparison,
        k_class_shifts=k_shifts,
    )


def estimate_bess_savings_potential(
    grid_import_kwh: np.ndarray,
    time_index: List[datetime],
    bess_capacity_kwh: float,
    bess_power_kw: float,
    config: Optional[CapacityFeeConfig] = None
) -> Dict:
    """
    Estimate potential capacity fee savings from BESS.

    This is a simplified estimate that shows the maximum theoretical savings
    if BESS could perfectly shift consumption from selected to non-selected hours.

    Args:
        grid_import_kwh: Current grid import profile [kWh]
        time_index: List of datetime objects
        bess_capacity_kwh: BESS energy capacity [kWh]
        bess_power_kw: BESS power rating [kW]
        config: Capacity fee configuration

    Returns:
        Dict with savings estimates and recommendations
    """
    if config is None:
        config = CapacityFeeConfig()

    # Calculate current fee
    current_result = compute_capacity_fee(grid_import_kwh, time_index, config)

    # Detect resolution (hourly or 15-min)
    if len(time_index) >= 2:
        delta = (time_index[1] - time_index[0]).total_seconds() / 3600
    else:
        delta = 1.0  # Default to hourly

    # Estimate maximum shiftable energy per day
    max_daily_shift_kwh = min(
        bess_capacity_kwh,  # Limited by capacity
        bess_power_kw * 15 * delta  # Limited by power × selected hours
    )

    # Theoretical maximum savings (100% shift)
    theoretical_max_savings = (
        current_result.total_fee_pln *
        (1 - K_COEFFICIENTS[KClass.K1] / K_COEFFICIENTS[KClass.K4])
    )

    # Realistic estimate (30-50% of maximum based on profile)
    realistic_savings_low = theoretical_max_savings * 0.30
    realistic_savings_high = theoretical_max_savings * 0.50

    return {
        'current_fee_pln': current_result.total_fee_pln,
        'current_k_histogram': current_result.k_histogram,
        'current_avg_delta_s': current_result.avg_delta_s,
        'theoretical_max_savings_pln': theoretical_max_savings,
        'realistic_savings_range_pln': (realistic_savings_low, realistic_savings_high),
        'bess_daily_shift_capacity_kwh': max_daily_shift_kwh,
        'recommendations': _generate_recommendations(current_result, bess_capacity_kwh),
    }


def _generate_recommendations(
    result: CapacityFeeResult,
    bess_capacity_kwh: float
) -> List[str]:
    """Generate recommendations based on capacity fee analysis."""
    recommendations = []

    # Check K-class distribution
    k4_pct = result.k_histogram.get('K4', 0) / max(result.workdays_count, 1) * 100

    if k4_pct > 80:
        recommendations.append(
            f"Wysoki udział K4 ({k4_pct:.0f}%) - duży potencjał optymalizacji. "
            "BESS może znacząco obniżyć opłatę mocową przez shift zużycia."
        )
    elif k4_pct > 50:
        recommendations.append(
            f"Umiarkowany udział K4 ({k4_pct:.0f}%) - dobry potencjał optymalizacji."
        )
    else:
        recommendations.append(
            f"Niski udział K4 ({k4_pct:.0f}%) - profil już dość płaski."
        )

    # Check if BESS capacity is sufficient
    if result.top_10_days:
        avg_top_zs = sum(d.zs_kwh for d in result.top_10_days) / len(result.top_10_days)
        if bess_capacity_kwh < avg_top_zs * 0.3:
            recommendations.append(
                f"Pojemność BESS ({bess_capacity_kwh:.0f} kWh) może być niewystarczająca "
                f"dla pełnej optymalizacji (średnie ZS top dni: {avg_top_zs:.0f} kWh)."
            )

    # Check avg_delta_s
    if result.avg_delta_s > 20:
        recommendations.append(
            f"Wysoka średnia Δs ({result.avg_delta_s:.1f}%) - profil mocno szczytowy. "
            "BESS do peak shaving będzie bardzo efektywny."
        )

    return recommendations
