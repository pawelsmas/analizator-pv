"""
Excel Export Module for BESS Economics Analysis.

Generates detailed hourly breakdown Excel file with:
- For each hour: energia czynna (per ToU zone), dystrybucja, jakość, OZE, kog, akcyza, mocowa
- Separate columns for baseline (PV only) and project (PV+BESS)
- Full cost calculation per hour
- Summary sheet with totals

IMPORTANT - MVP Implementation:
1. Capacity fee (opłata mocowa) is calculated dynamically via capacity_fee_pl module
   using K-class classification (A=0.17/0.50/0.83/1.00) based on consumption profile.
   WOM in hourly rows is allocated from daily totals proportionally to import in selected hours.

2. OSD_ALL_IN mode: When tariff rates already include distribution (energia + dystrybucja),
   the distribution component should be set to 0 to avoid double counting.

3. All time calculations use CET_FIXED (UTC+1) to match Polish tariff definitions.

Version: 2.0.0
"""

import io
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter

from common.time_utils import CET_FIXED_OFFSET
from common.calendar_pl import get_day_type, DayType, is_polish_holiday
from capacity_fee_pl.models import CapacityFeeConfig, KClass, K_COEFFICIENTS
from capacity_fee_pl.calculator import (
    compute_capacity_fee,
    compute_capacity_fee_savings,
    build_selected_hours_mask,
)


# =============================================================================
# Configuration Models
# =============================================================================

class FixedChargesConfig:
    """
    Fixed charges configuration (PLN/MWh).

    Note on OSD_ALL_IN mode:
    When is_osd_all_in=True, the ToU tariff rates already include distribution,
    so distribution should be set to 0 to avoid double counting.
    """
    def __init__(
        self,
        distribution: float = 200.0,
        quality_fee: float = 10.0,
        oze_fee: float = 7.0,
        cogeneration_fee: float = 10.0,
        excise_tax: float = 5.0,
        capacity_fee_som: float = 0.2194,  # SOM rate PLN/kWh
        is_osd_all_in: bool = False,  # If True, ToU rates include distribution
    ):
        self.quality_fee = quality_fee     # Opłata jakościowa
        self.oze_fee = oze_fee             # Opłata OZE
        self.cogeneration_fee = cogeneration_fee  # Opłata kogeneracyjna
        self.excise_tax = excise_tax       # Akcyza
        self.capacity_fee_som = capacity_fee_som  # SOM rate for capacity fee
        self.is_osd_all_in = is_osd_all_in

        # If OSD_ALL_IN, distribution is already in ToU rates
        if is_osd_all_in:
            self.distribution = 0.0
        else:
            self.distribution = distribution  # Dystrybucja

    @property
    def other_fees_total(self) -> float:
        """Sum of OTHER fees (excluding distribution and capacity fee)."""
        return (
            self.quality_fee +
            self.oze_fee +
            self.cogeneration_fee +
            self.excise_tax
        )

    @property
    def fixed_without_capacity(self) -> float:
        """Sum of fixed charges excluding capacity fee."""
        return self.distribution + self.other_fees_total


class ToUConfig:
    """Time-of-Use tariff configuration."""
    def __init__(
        self,
        tariff_type: str = "two_zone",  # flat, two_zone, three_zone
        flat_rate: float = 750.0,       # PLN/MWh
        day_rate: float = 850.0,        # PLN/MWh (two_zone)
        night_rate: float = 450.0,      # PLN/MWh (two_zone)
        peak_rate: float = 950.0,       # PLN/MWh (three_zone)
        partial_rate: float = 700.0,    # PLN/MWh (three_zone)
        off_peak_rate: float = 400.0,   # PLN/MWh (three_zone)
        weekday_day_start: int = 6,
        weekday_day_end: int = 22,
        weekend_day_start: int = 6,
        weekend_day_end: int = 13,
        peak1_start: int = 7,
        peak1_end: int = 13,
        peak2_start: int = 17,
        peak2_end: int = 21,
    ):
        self.tariff_type = tariff_type
        self.flat_rate = flat_rate
        self.day_rate = day_rate
        self.night_rate = night_rate
        self.peak_rate = peak_rate
        self.partial_rate = partial_rate
        self.off_peak_rate = off_peak_rate
        self.weekday_day_start = weekday_day_start
        self.weekday_day_end = weekday_day_end
        self.weekend_day_start = weekend_day_start
        self.weekend_day_end = weekend_day_end
        self.peak1_start = peak1_start
        self.peak1_end = peak1_end
        self.peak2_start = peak2_start
        self.peak2_end = peak2_end


# =============================================================================
# Time Index Builder (CET_FIXED)
# =============================================================================

def build_time_index_cet_fixed(
    start_date: date,
    n_timesteps: int,
    interval_minutes: int = 60
) -> List[datetime]:
    """
    Build a time index using CET_FIXED (UTC+1) for Polish tariff calculations.

    This ensures tariff zones are correctly applied according to Polish regulations
    which define zones in "czas zimowy" (winter time = CET).

    Args:
        start_date: Start date for the index
        n_timesteps: Number of timesteps
        interval_minutes: Interval duration (60 for hourly)

    Returns:
        List of datetime objects in CET_FIXED timezone
    """
    time_index = []
    dt = datetime(
        start_date.year, start_date.month, start_date.day,
        0, 0, 0, tzinfo=CET_FIXED_OFFSET
    )
    delta = timedelta(minutes=interval_minutes)

    for _ in range(n_timesteps):
        time_index.append(dt)
        dt += delta

    return time_index


# =============================================================================
# Zone Detection
# =============================================================================

def get_energia_zone(
    dt: datetime,
    tou_config: ToUConfig,
) -> Tuple[str, float]:
    """
    Determine energia czynna zone and rate for a given datetime.

    Args:
        dt: Datetime in CET-fixed timezone
        tou_config: ToU configuration

    Returns:
        Tuple of (zone_name, rate_pln_mwh)
    """
    hour = dt.hour
    weekday = dt.weekday()  # 0=Monday, 6=Sunday
    is_weekend = weekday >= 5

    if tou_config.tariff_type == "flat":
        return "Jednolita", tou_config.flat_rate

    elif tou_config.tariff_type == "two_zone":
        # Two-zone: day/night
        if is_weekend:
            # Weekend hours
            if tou_config.weekend_day_start <= hour < tou_config.weekend_day_end:
                return "Dzień", tou_config.day_rate
            else:
                return "Noc", tou_config.night_rate
        else:
            # Weekday hours
            if tou_config.weekday_day_start <= hour < tou_config.weekday_day_end:
                return "Dzień", tou_config.day_rate
            else:
                return "Noc", tou_config.night_rate

    elif tou_config.tariff_type == "three_zone":
        # Three-zone: peak/partial/off-peak (weekdays only for peak/partial)
        if is_weekend:
            return "Poza szczyt", tou_config.off_peak_rate
        else:
            # Check peak hours (morning and evening)
            if tou_config.peak1_start <= hour < tou_config.peak1_end:
                return "Szczyt", tou_config.peak_rate
            elif tou_config.peak2_start <= hour < tou_config.peak2_end:
                return "Szczyt", tou_config.peak_rate
            # Check partial hours (between peaks)
            elif tou_config.peak1_end <= hour < tou_config.peak2_start:
                return "Częściowy szczyt", tou_config.partial_rate
            else:
                return "Poza szczyt", tou_config.off_peak_rate

    # Default
    return "Nieznana", tou_config.flat_rate


def is_capacity_fee_hour(dt: datetime) -> bool:
    """
    Check if capacity fee (opłata mocowa) applies at given hour.

    Capacity fee applies:
    - Only on working days (Mon-Fri, excluding Polish holidays)
    - Hours 7:00-21:59 (7-22)

    Args:
        dt: Datetime to check (should have date info)

    Returns:
        True if capacity fee applies
    """
    # Check if weekend
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Check if Polish holiday
    if is_polish_holiday(dt.date()):
        return False

    # Check hours (7:00-21:59)
    if 7 <= dt.hour < 22:
        return True

    return False


# =============================================================================
# Capacity Fee Calculator (Dynamic K-class)
# =============================================================================

def calculate_capacity_fee_dynamic(
    import_kw: np.ndarray,
    time_index: List[datetime],
    som_pln_kwh: float,
    interval_minutes: int = 60,
) -> Tuple[float, Dict[str, Any], np.ndarray]:
    """
    Calculate capacity fee using dynamic K-class classification.

    This uses the capacity_fee_pl module to properly calculate WOM with
    A coefficient based on consumption profile (Δs classification).

    Args:
        import_kw: Grid import profile [kW]
        time_index: List of datetime objects (CET_FIXED)
        som_pln_kwh: SOM rate [PLN/kWh]
        interval_minutes: Time resolution

    Returns:
        Tuple of (total_fee_pln, details_dict, hourly_allocation_pln)

    Note:
        hourly_allocation_pln contains the daily WOM allocated to each hour
        proportionally to import in selected hours. Sum of allocations = total WOM.
    """
    dt_hours = interval_minutes / 60.0
    n_timesteps = len(import_kw)

    # Convert kW to kWh
    import_kwh = import_kw * dt_hours

    # Build capacity fee config
    cap_config = CapacityFeeConfig(
        year=time_index[0].year if time_index else 2025,
        som_pln_per_kwh=som_pln_kwh,
    )

    # Calculate using capacity_fee_pl module
    result = compute_capacity_fee(
        grid_import_kwh=import_kwh,
        time_index=time_index,
        config=cap_config,
    )

    # Build selected hours mask for allocation
    selected_mask = build_selected_hours_mask(time_index, cap_config)

    # Allocate daily WOM to hourly values proportionally to import in selected hours
    hourly_allocation = np.zeros(n_timesteps)

    # Group by day
    daily_data: Dict[date, Dict] = {}
    for i, dt in enumerate(time_index):
        day = dt.date()
        if day not in daily_data:
            daily_data[day] = {'indices': [], 'selected_indices': []}
        daily_data[day]['indices'].append(i)
        if selected_mask[i]:
            daily_data[day]['selected_indices'].append(i)

    # Find daily fees from result
    daily_fees = {r.date: r.fee_pln for r in result.top_10_days}

    # For days not in top_10, we need to check monthly results
    # Actually, the result contains full daily breakdown through monthly_results
    # but individual day fees are in result.top_10_days only
    # Let's recalculate daily fees properly

    for day, day_info in daily_data.items():
        selected_indices = day_info['selected_indices']

        if not selected_indices:
            continue  # Non-workday or no selected hours

        # Get import in selected hours for this day
        selected_import_kwh = import_kwh[selected_indices]
        total_selected_kwh = float(np.sum(selected_import_kwh))

        if total_selected_kwh <= 0:
            continue

        # Calculate day's fee using K-class
        # We need to get the A coefficient for this specific day
        day_indices = day_info['indices']
        day_energy = import_kwh[day_indices]
        day_mask = selected_mask[day_indices]

        # Calculate Δs for this day
        zs = float(np.sum(day_energy[day_mask]))  # Energy in selected hours
        zps = float(np.sum(day_energy[~day_mask]))  # Energy outside selected hours
        n_selected = int(np.sum(day_mask))
        n_outside = int(np.sum(~day_mask))

        # Classify
        if zps == 0 or n_outside == 0:
            a_coeff = 1.0  # K4
        elif n_selected == 0:
            a_coeff = 1.0  # K4
        else:
            avg_s = zs / n_selected
            avg_ps = zps / n_outside
            if avg_ps == 0:
                a_coeff = 1.0
            else:
                delta_s = (avg_s / avg_ps - 1) * 100
                if delta_s < 5:
                    a_coeff = 0.17  # K1
                elif delta_s < 10:
                    a_coeff = 0.50  # K2
                elif delta_s < 15:
                    a_coeff = 0.83  # K3
                else:
                    a_coeff = 1.00  # K4

        # Calculate day fee
        day_fee = a_coeff * som_pln_kwh * zs

        # Allocate proportionally to import in selected hours
        for idx in selected_indices:
            if total_selected_kwh > 0:
                proportion = import_kwh[idx] / total_selected_kwh
                hourly_allocation[idx] = day_fee * proportion

    details = {
        'total_fee_pln': result.total_fee_pln,
        'total_zs_kwh': result.total_zs_kwh,
        'k_histogram': result.k_histogram,
        'avg_delta_s': result.avg_delta_s,
        'workdays_count': result.workdays_count,
        'monthly_results': [
            {
                'month': m.month,
                'fee_pln': m.total_fee_pln,
                'zs_kwh': m.total_zs_kwh,
                'k_histogram': m.k_histogram,
            }
            for m in result.monthly_results
        ],
    }

    return result.total_fee_pln, details, hourly_allocation


# =============================================================================
# Hourly Cost Calculator
# =============================================================================

def calculate_hourly_costs(
    import_kw: np.ndarray,
    tou_config: ToUConfig,
    fixed_config: FixedChargesConfig,
    start_date: date,
    interval_minutes: int = 60,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Calculate detailed hourly costs with full breakdown.

    Uses capacity_fee_pl for dynamic K-class WOM calculation.

    Args:
        import_kw: Grid import power profile [kW]
        tou_config: Time-of-use configuration
        fixed_config: Fixed charges configuration
        start_date: Start date for analysis
        interval_minutes: Time resolution (60 for hourly)

    Returns:
        Tuple of (DataFrame with hourly breakdown, capacity_fee_details dict)
    """
    n_timesteps = len(import_kw)
    dt_hours = interval_minutes / 60

    # Build CET_FIXED time index
    time_index = build_time_index_cet_fixed(start_date, n_timesteps, interval_minutes)

    # Calculate capacity fee dynamically
    total_capacity_fee, cap_fee_details, hourly_cap_fee_allocation = calculate_capacity_fee_dynamic(
        import_kw=import_kw,
        time_index=time_index,
        som_pln_kwh=fixed_config.capacity_fee_som,
        interval_minutes=interval_minutes,
    )

    # Build hourly records
    records = []

    for i, dt in enumerate(time_index):
        import_kwh = import_kw[i] * dt_hours
        import_mwh = import_kwh / 1000.0

        # Get energia czynna zone and rate
        zone_name, energia_rate = get_energia_zone(dt, tou_config)
        energia_pln = import_mwh * energia_rate

        # Fixed charges (distribution may be 0 if OSD_ALL_IN)
        dystrybucja_pln = import_mwh * fixed_config.distribution
        jakosc_pln = import_mwh * fixed_config.quality_fee
        oze_pln = import_mwh * fixed_config.oze_fee
        kog_pln = import_mwh * fixed_config.cogeneration_fee
        akcyza_pln = import_mwh * fixed_config.excise_tax

        # Capacity fee from allocation (already calculated with K-class)
        mocowa_pln = hourly_cap_fee_allocation[i]

        # Calculate effective hourly rate for display (if applicable)
        is_selected_hour = is_capacity_fee_hour(dt)
        if is_selected_hour and import_kwh > 0:
            mocowa_rate_effective = mocowa_pln / import_mwh if import_mwh > 0 else 0
        else:
            mocowa_rate_effective = 0.0

        # Total
        total_pln = (
            energia_pln + dystrybucja_pln + jakosc_pln +
            oze_pln + kog_pln + akcyza_pln + mocowa_pln
        )

        # Effective rate (total cost / import)
        if import_mwh > 0:
            effective_rate = total_pln / import_mwh
        else:
            effective_rate = energia_rate + fixed_config.fixed_without_capacity

        records.append({
            'datetime': dt.replace(tzinfo=None),  # Excel doesn't support timezone
            'date': dt.date(),
            'hour': dt.hour,
            'weekday': dt.strftime('%A'),
            'weekday_pl': ['Pon', 'Wt', 'Śr', 'Czw', 'Pt', 'Sob', 'Nd'][dt.weekday()],
            'is_holiday': is_polish_holiday(dt.date()),
            'is_capacity_hour': is_selected_hour,
            'zone': zone_name,
            'import_kwh': round(import_kwh, 3),
            'import_mwh': round(import_mwh, 6),
            # Rates (PLN/MWh)
            'energia_rate': energia_rate,
            'dystrybucja_rate': fixed_config.distribution,
            'jakosc_rate': fixed_config.quality_fee,
            'oze_rate': fixed_config.oze_fee,
            'kog_rate': fixed_config.cogeneration_fee,
            'akcyza_rate': fixed_config.excise_tax,
            'mocowa_rate': round(mocowa_rate_effective, 2),  # Effective rate for this hour
            'effective_rate': round(effective_rate, 2),
            # Costs (PLN)
            'energia_pln': round(energia_pln, 4),
            'dystrybucja_pln': round(dystrybucja_pln, 4),
            'jakosc_pln': round(jakosc_pln, 4),
            'oze_pln': round(oze_pln, 4),
            'kog_pln': round(kog_pln, 4),
            'akcyza_pln': round(akcyza_pln, 4),
            'mocowa_pln': round(mocowa_pln, 4),  # This is ALLOCATED from daily WOM
            'total_pln': round(total_pln, 4),
        })

    return pd.DataFrame(records), cap_fee_details


# =============================================================================
# Excel Generator
# =============================================================================

def generate_economics_excel(
    baseline_import_kw: np.ndarray,
    project_import_kw: np.ndarray,
    tou_config: ToUConfig,
    fixed_config: FixedChargesConfig,
    start_date: date,
    bess_power_kw: float,
    bess_energy_kwh: float,
    interval_minutes: int = 60,
    project_name: str = "Analiza BESS",
) -> bytes:
    """
    Generate comprehensive Excel file with hourly economics breakdown.

    Uses dynamic K-class classification for capacity fee calculation.

    Args:
        baseline_import_kw: Grid import without BESS [kW]
        project_import_kw: Grid import with BESS [kW]
        tou_config: Time-of-use configuration
        fixed_config: Fixed charges configuration
        start_date: Start date for analysis
        bess_power_kw: BESS power rating
        bess_energy_kwh: BESS energy capacity
        interval_minutes: Time resolution
        project_name: Name for the report

    Returns:
        Excel file as bytes
    """
    # Calculate hourly costs for both scenarios
    baseline_df, baseline_cap_details = calculate_hourly_costs(
        baseline_import_kw, tou_config, fixed_config, start_date, interval_minutes
    )
    baseline_df = baseline_df.add_prefix('baseline_')
    baseline_df = baseline_df.rename(columns={
        'baseline_datetime': 'datetime',
        'baseline_date': 'date',
        'baseline_hour': 'hour',
        'baseline_weekday': 'weekday',
        'baseline_weekday_pl': 'weekday_pl',
        'baseline_is_holiday': 'is_holiday',
        'baseline_is_capacity_hour': 'is_capacity_hour',
        'baseline_zone': 'zone',
    })

    project_df, project_cap_details = calculate_hourly_costs(
        project_import_kw, tou_config, fixed_config, start_date, interval_minutes
    )
    project_df = project_df.add_prefix('project_')

    # Merge on common columns
    merged_df = pd.concat([
        baseline_df[['datetime', 'date', 'hour', 'weekday_pl', 'is_holiday', 'is_capacity_hour', 'zone']],
        baseline_df[[c for c in baseline_df.columns if c.startswith('baseline_')]],
        project_df[[c for c in project_df.columns if c.startswith('project_')]],
    ], axis=1)

    # Calculate savings
    merged_df['savings_energia_pln'] = merged_df['baseline_energia_pln'] - merged_df['project_energia_pln']
    merged_df['savings_dystrybucja_pln'] = merged_df['baseline_dystrybucja_pln'] - merged_df['project_dystrybucja_pln']
    merged_df['savings_jakosc_pln'] = merged_df['baseline_jakosc_pln'] - merged_df['project_jakosc_pln']
    merged_df['savings_oze_pln'] = merged_df['baseline_oze_pln'] - merged_df['project_oze_pln']
    merged_df['savings_kog_pln'] = merged_df['baseline_kog_pln'] - merged_df['project_kog_pln']
    merged_df['savings_akcyza_pln'] = merged_df['baseline_akcyza_pln'] - merged_df['project_akcyza_pln']
    merged_df['savings_mocowa_pln'] = merged_df['baseline_mocowa_pln'] - merged_df['project_mocowa_pln']
    merged_df['savings_total_pln'] = merged_df['baseline_total_pln'] - merged_df['project_total_pln']
    merged_df['savings_import_kwh'] = merged_df['baseline_import_kwh'] - merged_df['project_import_kwh']

    # Create Excel workbook
    wb = Workbook()

    # =========================================================================
    # Sheet 1: Summary
    # =========================================================================
    ws_summary = wb.active
    ws_summary.title = "Podsumowanie"

    # Styles
    header_fill = PatternFill(start_color="1565C0", end_color="1565C0", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    section_fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
    section_font = Font(bold=True, color="1565C0")
    warning_fill = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")
    number_format = '#,##0.00'

    # Title
    ws_summary['A1'] = f"📊 {project_name}"
    ws_summary['A1'].font = Font(bold=True, size=16)
    ws_summary.merge_cells('A1:D1')

    ws_summary['A2'] = f"Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    # Calculate actual analysis end date from data length
    n_timesteps = len(baseline_import_kw)
    period_hours = n_timesteps * (interval_minutes / 60)
    period_days = int(np.ceil(period_hours / 24))
    end_date = start_date + timedelta(days=period_days - 1)
    ws_summary['A3'] = f"Okres analizy: {start_date} - {end_date} ({period_days} dni)"

    # BESS Configuration
    ws_summary['A5'] = "⚡ Konfiguracja BESS"
    ws_summary['A5'].font = section_font
    ws_summary['A5'].fill = section_fill
    ws_summary.merge_cells('A5:D5')

    ws_summary['A6'] = "Moc BESS [kW]"
    ws_summary['B6'] = bess_power_kw
    ws_summary['A7'] = "Pojemność BESS [kWh]"
    ws_summary['B7'] = bess_energy_kwh

    # Tariff Configuration
    ws_summary['A9'] = "💰 Konfiguracja Taryfowa"
    ws_summary['A9'].font = section_font
    ws_summary['A9'].fill = section_fill
    ws_summary.merge_cells('A9:D9')

    ws_summary['A10'] = "Typ taryfy"
    ws_summary['B10'] = tou_config.tariff_type

    # OSD_ALL_IN warning
    if fixed_config.is_osd_all_in:
        ws_summary['C10'] = "⚠️ OSD_ALL_IN: stawki zawierają dystrybucję"
        ws_summary['C10'].fill = warning_fill

    if tou_config.tariff_type == "two_zone":
        ws_summary['A11'] = "Stawka dzienna [PLN/MWh]"
        ws_summary['B11'] = tou_config.day_rate
        ws_summary['A12'] = "Stawka nocna [PLN/MWh]"
        ws_summary['B12'] = tou_config.night_rate
    elif tou_config.tariff_type == "three_zone":
        ws_summary['A11'] = "Stawka szczyt [PLN/MWh]"
        ws_summary['B11'] = tou_config.peak_rate
        ws_summary['A12'] = "Stawka częściowy [PLN/MWh]"
        ws_summary['B12'] = tou_config.partial_rate
        ws_summary['A13'] = "Stawka poza szczyt [PLN/MWh]"
        ws_summary['B13'] = tou_config.off_peak_rate

    # Fixed Charges
    row = 15
    ws_summary[f'A{row}'] = "📋 Opłaty Stałe [PLN/MWh]"
    ws_summary[f'A{row}'].font = section_font
    ws_summary[f'A{row}'].fill = section_fill
    ws_summary.merge_cells(f'A{row}:D{row}')

    row += 1
    ws_summary[f'A{row}'] = "Dystrybucja"
    ws_summary[f'B{row}'] = fixed_config.distribution
    if fixed_config.is_osd_all_in:
        ws_summary[f'C{row}'] = "(=0, zawarta w stawce ToU)"

    row += 1
    ws_summary[f'A{row}'] = "Opłata jakościowa"
    ws_summary[f'B{row}'] = fixed_config.quality_fee
    row += 1
    ws_summary[f'A{row}'] = "Opłata OZE"
    ws_summary[f'B{row}'] = fixed_config.oze_fee
    row += 1
    ws_summary[f'A{row}'] = "Opłata kogeneracyjna"
    ws_summary[f'B{row}'] = fixed_config.cogeneration_fee
    row += 1
    ws_summary[f'A{row}'] = "Akcyza"
    ws_summary[f'B{row}'] = fixed_config.excise_tax
    row += 1
    ws_summary[f'A{row}'] = "Opłata mocowa SOM [PLN/kWh]"
    ws_summary[f'B{row}'] = fixed_config.capacity_fee_som
    ws_summary[f'C{row}'] = "(dynamiczna klasyfikacja K)"

    # Capacity Fee K-class Summary
    row += 2
    ws_summary[f'A{row}'] = "⚡ Opłata Mocowa - Klasyfikacja K"
    ws_summary[f'A{row}'].font = section_font
    ws_summary[f'A{row}'].fill = section_fill
    ws_summary.merge_cells(f'A{row}:D{row}')

    row += 1
    ws_summary[f'A{row}'] = ""
    ws_summary[f'B{row}'] = "Baseline"
    ws_summary[f'C{row}'] = "PV+BESS"
    ws_summary[f'D{row}'] = "Oszczędności"
    for col in ['B', 'C', 'D']:
        ws_summary[f'{col}{row}'].font = header_font
        ws_summary[f'{col}{row}'].fill = header_fill

    row += 1
    ws_summary[f'A{row}'] = "WOM [PLN]"
    ws_summary[f'B{row}'] = round(baseline_cap_details['total_fee_pln'], 2)
    ws_summary[f'C{row}'] = round(project_cap_details['total_fee_pln'], 2)
    ws_summary[f'D{row}'] = round(baseline_cap_details['total_fee_pln'] - project_cap_details['total_fee_pln'], 2)

    row += 1
    ws_summary[f'A{row}'] = "Średnia Δs [%]"
    ws_summary[f'B{row}'] = round(baseline_cap_details['avg_delta_s'], 1)
    ws_summary[f'C{row}'] = round(project_cap_details['avg_delta_s'], 1)

    row += 1
    ws_summary[f'A{row}'] = "Dni K1 (A=0.17)"
    ws_summary[f'B{row}'] = baseline_cap_details['k_histogram'].get('K1', 0)
    ws_summary[f'C{row}'] = project_cap_details['k_histogram'].get('K1', 0)

    row += 1
    ws_summary[f'A{row}'] = "Dni K2 (A=0.50)"
    ws_summary[f'B{row}'] = baseline_cap_details['k_histogram'].get('K2', 0)
    ws_summary[f'C{row}'] = project_cap_details['k_histogram'].get('K2', 0)

    row += 1
    ws_summary[f'A{row}'] = "Dni K3 (A=0.83)"
    ws_summary[f'B{row}'] = baseline_cap_details['k_histogram'].get('K3', 0)
    ws_summary[f'C{row}'] = project_cap_details['k_histogram'].get('K3', 0)

    row += 1
    ws_summary[f'A{row}'] = "Dni K4 (A=1.00)"
    ws_summary[f'B{row}'] = baseline_cap_details['k_histogram'].get('K4', 0)
    ws_summary[f'C{row}'] = project_cap_details['k_histogram'].get('K4', 0)

    # Annual Summary
    row += 2
    ws_summary[f'A{row}'] = "📈 Podsumowanie Roczne"
    ws_summary[f'A{row}'].font = section_font
    ws_summary[f'A{row}'].fill = section_fill
    ws_summary.merge_cells(f'A{row}:D{row}')

    row += 1
    summary_data = [
        ("", "Baseline (PV)", "Projekt (PV+BESS)", "Oszczędności"),
        ("Import energii [MWh]",
         merged_df['baseline_import_kwh'].sum() / 1000,
         merged_df['project_import_kwh'].sum() / 1000,
         merged_df['savings_import_kwh'].sum() / 1000),
        ("Energia czynna [PLN]",
         merged_df['baseline_energia_pln'].sum(),
         merged_df['project_energia_pln'].sum(),
         merged_df['savings_energia_pln'].sum()),
        ("Dystrybucja [PLN]",
         merged_df['baseline_dystrybucja_pln'].sum(),
         merged_df['project_dystrybucja_pln'].sum(),
         merged_df['savings_dystrybucja_pln'].sum()),
        ("Opłata jakościowa [PLN]",
         merged_df['baseline_jakosc_pln'].sum(),
         merged_df['project_jakosc_pln'].sum(),
         merged_df['savings_jakosc_pln'].sum()),
        ("Opłata OZE [PLN]",
         merged_df['baseline_oze_pln'].sum(),
         merged_df['project_oze_pln'].sum(),
         merged_df['savings_oze_pln'].sum()),
        ("Opłata kogeneracyjna [PLN]",
         merged_df['baseline_kog_pln'].sum(),
         merged_df['project_kog_pln'].sum(),
         merged_df['savings_kog_pln'].sum()),
        ("Akcyza [PLN]",
         merged_df['baseline_akcyza_pln'].sum(),
         merged_df['project_akcyza_pln'].sum(),
         merged_df['savings_akcyza_pln'].sum()),
        ("Opłata mocowa [PLN] (dyn. K)",
         baseline_cap_details['total_fee_pln'],
         project_cap_details['total_fee_pln'],
         baseline_cap_details['total_fee_pln'] - project_cap_details['total_fee_pln']),
        ("RAZEM [PLN]",
         merged_df['baseline_total_pln'].sum(),
         merged_df['project_total_pln'].sum(),
         merged_df['savings_total_pln'].sum()),
    ]

    for i, data_row in enumerate(summary_data):
        for j, val in enumerate(data_row):
            cell = ws_summary.cell(row=row + i, column=1 + j)
            cell.value = val
            if i == 0:  # Header row
                cell.fill = header_fill
                cell.font = header_font
            elif i == len(summary_data) - 1:  # Total row
                cell.font = Font(bold=True)
            if j > 0 and i > 0:
                cell.number_format = number_format

    # Adjust column widths
    ws_summary.column_dimensions['A'].width = 35
    ws_summary.column_dimensions['B'].width = 20
    ws_summary.column_dimensions['C'].width = 20
    ws_summary.column_dimensions['D'].width = 20

    # =========================================================================
    # Sheet 2: Hourly Details
    # =========================================================================
    ws_hourly = wb.create_sheet("Rozliczenie Godzinowe")

    # Add note about capacity fee allocation
    ws_hourly['A1'] = "⚠️ UWAGA: Opłata mocowa (Mocowa) to alokacja dziennego WOM do godzin wybranych proporcjonalnie do importu. Suma alokacji = dzienny WOM."
    ws_hourly['A1'].font = Font(italic=True, color="666666")
    ws_hourly.merge_cells('A1:V1')

    # Select columns for hourly sheet
    hourly_columns = [
        'datetime', 'weekday_pl', 'is_capacity_hour', 'zone',
        'baseline_import_kwh', 'baseline_energia_rate', 'baseline_energia_pln',
        'baseline_dystrybucja_pln', 'baseline_jakosc_pln', 'baseline_oze_pln',
        'baseline_kog_pln', 'baseline_akcyza_pln', 'baseline_mocowa_pln', 'baseline_total_pln',
        'project_import_kwh', 'project_energia_pln',
        'project_dystrybucja_pln', 'project_jakosc_pln', 'project_oze_pln',
        'project_kog_pln', 'project_akcyza_pln', 'project_mocowa_pln', 'project_total_pln',
        'savings_total_pln',
    ]

    hourly_df = merged_df[hourly_columns].copy()

    # Rename columns for Polish headers
    column_names = {
        'datetime': 'Data i godzina',
        'weekday_pl': 'Dzień',
        'is_capacity_hour': 'Godz. wybrana',
        'zone': 'Strefa',
        'baseline_import_kwh': 'BL Import [kWh]',
        'baseline_energia_rate': 'BL Stawka [PLN/MWh]',
        'baseline_energia_pln': 'BL Energia [PLN]',
        'baseline_dystrybucja_pln': 'BL Dystrybucja [PLN]',
        'baseline_jakosc_pln': 'BL Jakość [PLN]',
        'baseline_oze_pln': 'BL OZE [PLN]',
        'baseline_kog_pln': 'BL Kog [PLN]',
        'baseline_akcyza_pln': 'BL Akcyza [PLN]',
        'baseline_mocowa_pln': 'BL Mocowa (alok.) [PLN]',
        'baseline_total_pln': 'BL RAZEM [PLN]',
        'project_import_kwh': 'BESS Import [kWh]',
        'project_energia_pln': 'BESS Energia [PLN]',
        'project_dystrybucja_pln': 'BESS Dystrybucja [PLN]',
        'project_jakosc_pln': 'BESS Jakość [PLN]',
        'project_oze_pln': 'BESS OZE [PLN]',
        'project_kog_pln': 'BESS Kog [PLN]',
        'project_akcyza_pln': 'BESS Akcyza [PLN]',
        'project_mocowa_pln': 'BESS Mocowa (alok.) [PLN]',
        'project_total_pln': 'BESS RAZEM [PLN]',
        'savings_total_pln': 'Oszczędności [PLN]',
    }
    hourly_df = hourly_df.rename(columns=column_names)

    # Write DataFrame to sheet (starting at row 3 to leave room for note)
    for r_idx, row in enumerate(dataframe_to_rows(hourly_df, index=False, header=True), 3):
        for c_idx, value in enumerate(row, 1):
            cell = ws_hourly.cell(row=r_idx, column=c_idx, value=value)
            if r_idx == 3:  # Header row
                cell.fill = header_fill
                cell.font = header_font
            elif isinstance(value, float):
                cell.number_format = '#,##0.0000'

    # Adjust column widths
    for i, col in enumerate(hourly_df.columns, 1):
        ws_hourly.column_dimensions[get_column_letter(i)].width = max(12, len(col) + 2)

    # Freeze header row
    ws_hourly.freeze_panes = 'A4'

    # =========================================================================
    # Sheet 3: Daily Summary
    # =========================================================================
    ws_daily = wb.create_sheet("Podsumowanie Dzienne")

    # Group by date
    daily_df = merged_df.groupby('date').agg({
        'baseline_import_kwh': 'sum',
        'baseline_total_pln': 'sum',
        'project_import_kwh': 'sum',
        'project_total_pln': 'sum',
        'savings_total_pln': 'sum',
        'baseline_mocowa_pln': 'sum',
        'project_mocowa_pln': 'sum',
        'savings_mocowa_pln': 'sum',
    }).reset_index()

    daily_df.columns = [
        'Data', 'BL Import [kWh]', 'BL Koszt [PLN]',
        'BESS Import [kWh]', 'BESS Koszt [PLN]', 'Oszczędności [PLN]',
        'BL Mocowa [PLN]', 'BESS Mocowa [PLN]', 'Oszcz. Mocowa [PLN]'
    ]

    for r_idx, row in enumerate(dataframe_to_rows(daily_df, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws_daily.cell(row=r_idx, column=c_idx, value=value)
            if r_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
            elif isinstance(value, float):
                cell.number_format = '#,##0.00'

    for i, col in enumerate(daily_df.columns, 1):
        ws_daily.column_dimensions[get_column_letter(i)].width = max(15, len(col) + 2)

    ws_daily.freeze_panes = 'A2'

    # =========================================================================
    # Sheet 4: Monthly Summary
    # =========================================================================
    ws_monthly = wb.create_sheet("Podsumowanie Miesięczne")

    # Add month column
    merged_df['month'] = pd.to_datetime(merged_df['date']).dt.to_period('M')

    monthly_df = merged_df.groupby('month').agg({
        'baseline_import_kwh': 'sum',
        'baseline_energia_pln': 'sum',
        'baseline_dystrybucja_pln': 'sum',
        'baseline_mocowa_pln': 'sum',
        'baseline_total_pln': 'sum',
        'project_import_kwh': 'sum',
        'project_energia_pln': 'sum',
        'project_dystrybucja_pln': 'sum',
        'project_mocowa_pln': 'sum',
        'project_total_pln': 'sum',
        'savings_energia_pln': 'sum',
        'savings_mocowa_pln': 'sum',
        'savings_total_pln': 'sum',
    }).reset_index()

    monthly_df['month'] = monthly_df['month'].astype(str)
    monthly_df.columns = [
        'Miesiąc',
        'BL Import [kWh]', 'BL Energia [PLN]', 'BL Dystrybucja [PLN]', 'BL Mocowa [PLN]', 'BL Razem [PLN]',
        'BESS Import [kWh]', 'BESS Energia [PLN]', 'BESS Dystrybucja [PLN]', 'BESS Mocowa [PLN]', 'BESS Razem [PLN]',
        'Oszcz. Energia [PLN]', 'Oszcz. Mocowa [PLN]', 'Oszcz. Razem [PLN]'
    ]

    for r_idx, row in enumerate(dataframe_to_rows(monthly_df, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws_monthly.cell(row=r_idx, column=c_idx, value=value)
            if r_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
            elif isinstance(value, float):
                cell.number_format = '#,##0.00'

    for i, col in enumerate(monthly_df.columns, 1):
        ws_monthly.column_dimensions[get_column_letter(i)].width = max(15, len(col) + 2)

    ws_monthly.freeze_panes = 'A2'

    # =========================================================================
    # Save to bytes
    # =========================================================================
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return output.getvalue()
