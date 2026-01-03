"""Unit tests for profiles helper (v4.5.0 PR7)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from profiles_helper import get_profile_config, get_objective_for_profile, get_policy_for_profile, list_available_profiles
from models import OptimizationObjective


class TestProfilesHelper:
    def test_balanced_profile(self):
        config = get_profile_config("balanced")
        assert config["objective"] == OptimizationObjective.NPV

    def test_self_consumption_profile(self):
        obj = get_objective_for_profile("pv_self_consumption")
        assert obj == OptimizationObjective.SELF_CONSUMPTION

    def test_resilience_profile(self):
        policy = get_policy_for_profile("resilience_backup")
        assert policy.near_optimal_tolerance_pct == 15.0
        assert "duration_h" in policy.tie_breakers

    def test_unknown_profile_returns_balanced(self):
        obj = get_objective_for_profile("unknown")
        assert obj == OptimizationObjective.NPV

    def test_list_profiles(self):
        profiles = list_available_profiles()
        assert "balanced" in profiles
        assert "pv_self_consumption" in profiles
        assert len(profiles) == 5
