"""Unit tests for duration sweep helper (v4.5.0 PR6)."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from duration_sweep_helper import compute_duration_sweep, compute_marginal_metrics, build_duration_sweep_response


class TestComputeDurationSweep:
    def test_basic_sweep(self):
        data = {
            1.0: {"npv_pln": 100000, "payback_years": 5.0, "power_kw": 50},
            2.0: {"npv_pln": 120000, "payback_years": 5.5, "power_kw": 50},
            4.0: {"npv_pln": 130000, "payback_years": 6.0, "power_kw": 50},
        }
        sweep = compute_duration_sweep(data)
        assert len(sweep) == 3
        assert sweep[0].duration_h == 1.0
        assert sweep[2].duration_h == 4.0

    def test_empty_returns_empty(self):
        assert compute_duration_sweep({}) == []


class TestComputeMarginalMetrics:
    def test_marginal_from_sweep(self):
        from models import DurationSweepPoint
        sweep = [
            DurationSweepPoint(duration_h=1.0, npv_pln=100000, power_kw=50),
            DurationSweepPoint(duration_h=2.0, npv_pln=120000, power_kw=50),
        ]
        marginal = compute_marginal_metrics(sweep)
        assert marginal is not None
        assert marginal.marginal_npv_pln_per_added_kwh is not None

    def test_single_point_returns_none(self):
        from models import DurationSweepPoint
        sweep = [DurationSweepPoint(duration_h=1.0, npv_pln=100000)]
        assert compute_marginal_metrics(sweep) is None


class TestBuildDurationSweepResponse:
    def test_full_response(self):
        variants = [
            {"duration_h": 1.0, "npv_pln": 100000, "payback_years": 5.0, "power_kw": 50},
            {"duration_h": 2.0, "npv_pln": 120000, "payback_years": 5.5, "power_kw": 50},
        ]
        resp = build_duration_sweep_response(variants)
        assert "duration_sweep" in resp
        assert len(resp["duration_sweep"]) == 2
