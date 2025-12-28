"""
Capacity Fee PL (Opłata Mocowa) - Polish Capacity Market Fee Calculator

This module implements the Polish capacity market fee calculation according to:
- Ustawa z dnia 8 grudnia 2017 r. o rynku mocy (Dz.U. 2018 poz. 9)
- Informacja Prezesa URE nr 58/2025 (stawka SOM na 2026)

Key concepts:
- SOM (Stawka Opłaty Mocowej): Fee rate in PLN/kWh, set by URE annually
- Selected hours: 15 consecutive hours on workdays (7:00-22:00 for 2026)
- K-classes (K1-K4): Classification based on consumption profile ratio (Δs)
- A coefficient: Discount factor based on K-class (0.17/0.50/0.83/1.00)

Formula: WOM = A × SOM × ZS
where:
- A = coefficient based on K-class
- SOM = capacity fee rate [PLN/kWh]
- ZS = energy consumed in selected hours [kWh]

Important notes:
- Fee is calculated on grid_import_kwh (energy from grid), not load
- Classification period: daily (2025+), decadal (2023-2024), monthly (≤2022)
- Holidays are treated as non-workdays (no fee calculation)
"""

from .models import (
    KClass,
    K_COEFFICIENTS,
    QualificationPeriod,
    CapacityFeeConfig,
    DailyClassification,
    MonthlyResult,
    CapacityFeeResult,
    CapacityFeeSavings,
    get_preset_for_year,
)
from .calendar_pl import (
    get_polish_holidays,
    is_polish_holiday,
    is_workday,
    get_day_type,
    DayType,
)
from .calculator import (
    build_selected_hours_mask,
    classify_period_K,
    compute_capacity_fee,
    compute_capacity_fee_savings,
)

__all__ = [
    # Models
    "KClass",
    "K_COEFFICIENTS",
    "QualificationPeriod",
    "CapacityFeeConfig",
    "DailyClassification",
    "MonthlyResult",
    "CapacityFeeResult",
    "CapacityFeeSavings",
    "get_preset_for_year",
    # Calendar
    "get_polish_holidays",
    "is_polish_holiday",
    "is_workday",
    "get_day_type",
    "DayType",
    # Calculator
    "build_selected_hours_mask",
    "classify_period_K",
    "compute_capacity_fee",
    "compute_capacity_fee_savings",
]

__version__ = "1.0.0"
