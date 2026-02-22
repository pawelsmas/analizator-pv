"""
Data models for Polish Capacity Market Fee (Opłata Mocowa)

Based on:
- Ustawa z dnia 8 grudnia 2017 r. o rynku mocy
- Informacja Prezesa URE nr 58/2025
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import date


class KClass(str, Enum):
    """
    K-class classification based on consumption profile ratio (Δs).

    Δs = (avg_consumption_in_selected_hours / avg_consumption_outside - 1) × 100%

    Thresholds (Dz.U. 2023 poz. 503):
    - K1: Δs < -10%    → A = 0.17 (83% discount)
    - K2: Δs ∈ [-10%, 10%) → A = 0.50 (50% discount)
    - K3: Δs ∈ [10%, 30%) → A = 0.83 (17% discount)
    - K4: Δs ≥ 30% OR ZPS=0 → A = 1.00 (no discount)
    """
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"
    K4 = "K4"


# K-class to A coefficient mapping
K_COEFFICIENTS: Dict[KClass, float] = {
    KClass.K1: 0.17,
    KClass.K2: 0.50,
    KClass.K3: 0.83,
    KClass.K4: 1.00,
}

# K-class Δs thresholds (percent)
K_THRESHOLDS: Dict[KClass, Tuple[float, float]] = {
    KClass.K1: (float('-inf'), 5.0),
    KClass.K2: (5.0, 10.0),
    KClass.K3: (10.0, 15.0),
    KClass.K4: (15.0, float('inf')),
}


class QualificationPeriod(str, Enum):
    """
    Period for K-class qualification.

    Changed over time:
    - 2025+: DAILY (per workday)
    - 2023-2024: DECADAL (1-10, 11-20, 21-end of month)
    - ≤2022: MONTHLY

    Reference: Tauron Dystrybucja - przejście na dobowy od 1.01.2025
    """
    DAILY = "daily"
    DECADAL = "decadal"
    MONTHLY = "monthly"


class CapacityFeeConfig(BaseModel):
    """
    Configuration for capacity fee calculation.

    SOM rate and selected hours are published by URE annually.
    Reference: Informacja Prezesa URE nr 58/2025
    """
    year: int = Field(default=2026, description="Year for calculation")

    # SOM rate (Stawka Opłaty Mocowej) - PLN/kWh netto
    # 2026: 0.2194 PLN/kWh (URE 58/2025)
    som_pln_per_kwh: float = Field(
        default=0.2194,
        description="SOM rate in PLN/kWh (netto)",
        ge=0
    )

    # Qualification period depends on year
    qualification_period: QualificationPeriod = Field(
        default=QualificationPeriod.DAILY,
        description="Period for K-class qualification"
    )

    # Selected hours window per quarter
    # URE publishes these separately (Informacja 57/2025 for 2026)
    # Default: 7:00-22:00 (15 consecutive hours) for all quarters
    selected_windows_by_quarter: Dict[str, Tuple[int, int]] = Field(
        default={
            "Q1": (7, 22),
            "Q2": (7, 22),
            "Q3": (7, 22),
            "Q4": (7, 22),
        },
        description="Selected hours window (start_hour, end_hour) per quarter"
    )

    def get_window_for_month(self, month: int) -> Tuple[int, int]:
        """Get selected hours window for given month."""
        if month <= 3:
            return self.selected_windows_by_quarter.get("Q1", (7, 22))
        elif month <= 6:
            return self.selected_windows_by_quarter.get("Q2", (7, 22))
        elif month <= 9:
            return self.selected_windows_by_quarter.get("Q3", (7, 22))
        else:
            return self.selected_windows_by_quarter.get("Q4", (7, 22))

    def get_qualification_period_for_year(self, year: int) -> QualificationPeriod:
        """Get qualification period based on year."""
        if year >= 2025:
            return QualificationPeriod.DAILY
        elif year >= 2023:
            return QualificationPeriod.DECADAL
        else:
            return QualificationPeriod.MONTHLY


class DailyClassification(BaseModel):
    """Result of K-class classification for a single day/period."""
    date: date
    k_class: KClass
    a_coefficient: float
    delta_s_percent: float = Field(description="Δs value in percent")
    zs_kwh: float = Field(description="Energy in selected hours [kWh]")
    zps_kwh: float = Field(description="Energy outside selected hours [kWh]")
    fee_pln: float = Field(description="Capacity fee for this day [PLN]")
    n_selected_hours: int = Field(description="Number of selected hours")
    n_outside_hours: int = Field(description="Number of hours outside selected")


class MonthlyResult(BaseModel):
    """Monthly aggregation of capacity fee."""
    month: int
    total_fee_pln: float
    total_zs_kwh: float
    workdays_count: int
    k_histogram: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of days per K-class"
    )
    avg_delta_s: float = Field(default=0.0, description="Average Δs for the month")


class CapacityFeeResult(BaseModel):
    """Complete result of capacity fee calculation."""
    # Totals
    total_fee_pln: float = Field(description="Total annual capacity fee [PLN]")
    total_zs_kwh: float = Field(description="Total energy in selected hours [kWh]")

    # Monthly breakdown
    monthly_results: List[MonthlyResult] = Field(default_factory=list)

    # K-class statistics
    k_histogram: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of periods per K-class"
    )

    # Top cost days for analysis
    top_10_days: List[DailyClassification] = Field(
        default_factory=list,
        description="Top 10 days by fee amount"
    )

    # Configuration used
    config: CapacityFeeConfig

    # Metadata
    workdays_count: int = Field(description="Total workdays in year")
    avg_delta_s: float = Field(description="Average Δs across all periods")


class CapacityFeeSavings(BaseModel):
    """Comparison of capacity fee before/after BESS."""
    # Before BESS
    fee_before_pln: float
    k_histogram_before: Dict[str, int]
    avg_delta_s_before: float

    # After BESS
    fee_after_pln: float
    k_histogram_after: Dict[str, int]
    avg_delta_s_after: float

    # Savings
    savings_pln: float
    savings_percent: float

    # Monthly comparison
    monthly_comparison: List[Dict] = Field(default_factory=list)

    # K-class shifts (e.g., "K4_to_K2": 15 days shifted)
    k_class_shifts: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of periods that shifted between K-classes"
    )


# Presets for different years
CAPACITY_FEE_PRESETS: Dict[int, CapacityFeeConfig] = {
    2024: CapacityFeeConfig(
        year=2024,
        som_pln_per_kwh=0.1783,  # Example - check URE for actual
        qualification_period=QualificationPeriod.DECADAL,
    ),
    2025: CapacityFeeConfig(
        year=2025,
        som_pln_per_kwh=0.2050,  # Example - check URE for actual
        qualification_period=QualificationPeriod.DAILY,
    ),
    2026: CapacityFeeConfig(
        year=2026,
        som_pln_per_kwh=0.2194,  # URE 58/2025
        qualification_period=QualificationPeriod.DAILY,
    ),
}


def get_preset_for_year(year: int) -> CapacityFeeConfig:
    """Get capacity fee configuration preset for given year."""
    if year in CAPACITY_FEE_PRESETS:
        return CAPACITY_FEE_PRESETS[year]

    # Default to 2026 config for future years
    config = CapacityFeeConfig(year=year)
    if year >= 2025:
        config.qualification_period = QualificationPeriod.DAILY
    elif year >= 2023:
        config.qualification_period = QualificationPeriod.DECADAL
    else:
        config.qualification_period = QualificationPeriod.MONTHLY

    return config
