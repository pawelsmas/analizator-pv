"""
Optimization Profiles Helper (v4.5.0).

Maps profile names to objective + policy configurations.
"""

from typing import Dict, Any, Optional
from models import OptimizationProfile, RecommendationPolicy, OptimizationObjective


PROFILE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "objective": OptimizationObjective.NPV,
        "policy": RecommendationPolicy(
            near_optimal_tolerance_pct=5.0,
            tie_breakers=["self_consumption_rate", "payback_years", "duration_h"],
        ),
        "description": "NPV optimization with self-consumption tie-breaker",
    },
    "pv_self_consumption": {
        "objective": OptimizationObjective.SELF_CONSUMPTION,
        "policy": RecommendationPolicy(
            near_optimal_tolerance_pct=10.0,
            tie_breakers=["npv_pln", "duration_h"],
            min_npv_pln=0.0,
        ),
        "description": "Maximize PV self-consumption, require positive NPV",
    },
    "commercial_peak_shaving": {
        "objective": OptimizationObjective.PEAK_REDUCTION,
        "policy": RecommendationPolicy(
            near_optimal_tolerance_pct=5.0,
            tie_breakers=["npv_pln", "capex_pln"],
        ),
        "description": "Maximize peak reduction for demand charge savings",
    },
    "arbitrage": {
        "objective": OptimizationObjective.NPV,
        "policy": RecommendationPolicy(
            near_optimal_tolerance_pct=3.0,
            tie_breakers=["irr_pct", "payback_years"],
        ),
        "description": "NPV optimization for arbitrage with grid charging",
    },
    "resilience_backup": {
        "objective": OptimizationObjective.RESILIENCE,
        "policy": RecommendationPolicy(
            near_optimal_tolerance_pct=15.0,
            tie_breakers=["duration_h", "npv_pln"],
        ),
        "description": "Maximize backup capability, prefer longer duration",
    },
}


def get_profile_config(profile: str) -> Optional[Dict[str, Any]]:
    """Get configuration for a profile name."""
    return PROFILE_CONFIGS.get(profile)


def get_objective_for_profile(profile: str) -> OptimizationObjective:
    """Get primary objective for profile."""
    config = PROFILE_CONFIGS.get(profile, PROFILE_CONFIGS["balanced"])
    return config["objective"]


def get_policy_for_profile(profile: str) -> RecommendationPolicy:
    """Get recommendation policy for profile."""
    config = PROFILE_CONFIGS.get(profile, PROFILE_CONFIGS["balanced"])
    return config["policy"]


def list_available_profiles() -> Dict[str, str]:
    """List all profiles with descriptions."""
    return {name: cfg["description"] for name, cfg in PROFILE_CONFIGS.items()}
