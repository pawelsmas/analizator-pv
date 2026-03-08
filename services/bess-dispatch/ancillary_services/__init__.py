"""
Ancillary Services & Battery Virtualization Module
===================================================

Provides revenue stacking for BESS through multi-service optimization:

Services supported:
- Peak Shaving (demand charge reduction)
- PV Surplus Shifting (self-consumption)
- Energy Arbitrage (ToU / RDN price spreads)
- aFRR (automatic Frequency Restoration Reserve)
- mFRR (manual Frequency Restoration Reserve)
- FCR (Frequency Containment Reserve)
- Capacity Market (Rynek Mocy)

Architecture:
- BatteryVirtualizer: splits physical battery into virtual slices per service
- AncillaryRevenueCalculator: computes revenue from UB market participation
- StackedOptimizer: joint LP that co-optimizes all services simultaneously

Polish market specifics:
- aFRR: ~181 PLN/MW/h avg (2025), PICASSO platform
- mFRR: MARI platform, 15-min activation
- Capacity Market: 264,900 PLN/MW/rok, KWD=0.133
"""

from .models import (
    AncillaryServiceType,
    AncillaryServiceConfig,
    BatterySlice,
    BatteryVirtualizationConfig,
    AncillaryRevenueResult,
    StackedRevenueResult,
)

from .virtualizer import BatteryVirtualizer
from .revenue import AncillaryRevenueCalculator
from .optimizer import StackedServiceOptimizer

__all__ = [
    "AncillaryServiceType",
    "AncillaryServiceConfig",
    "BatterySlice",
    "BatteryVirtualizationConfig",
    "AncillaryRevenueResult",
    "StackedRevenueResult",
    "BatteryVirtualizer",
    "AncillaryRevenueCalculator",
    "StackedServiceOptimizer",
]
