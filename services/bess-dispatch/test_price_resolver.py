"""
Golden master tests for price_resolver.py (Faza 2 refaktoring).

Verifies that the unified PriceResolver produces results consistent
with the old price resolution in:
- lp_dispatch.py: resolve_price_arrays(), resolve_buy_sell_for_dispatch()
- sizing_runner.py: get_price_bundle_for_sizing() [paths 1 & 3 only — OSD needs Docker]

Run: python -m pytest test_price_resolver.py -v
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

from price_resolver import (
    PriceResolver,
    ResolvedPrices,
    resolve_prices,
    _mwh_to_kwh,
    _fit_to_length,
    _build_metadata,
)

# Import old functions for comparison
from lp_dispatch import resolve_price_arrays, resolve_buy_sell_for_dispatch
from models import PriceConfig, ArbitrageConfig


# ============================================================
# Test data — representative scenarios
# ============================================================

# Flat pricing (default PriceConfig)
FLAT_BUY_MWH = 800.0
FLAT_SELL_MWH = 0.0

# Custom flat pricing
CUSTOM_BUY_MWH = 650.0
CUSTOM_SELL_MWH = 350.0

# RDN hourly prices (synthetic — 24h pattern repeated)
RDN_24H = [300, 280, 260, 250, 240, 250, 280, 350,
           450, 500, 520, 530, 540, 520, 480, 460,
           500, 550, 600, 580, 520, 450, 380, 320]
RDN_YEAR = RDN_24H * 365  # 8760 hours

# Export prices (raw RDN, lower than all-in)
EXPORT_24H = [250, 230, 210, 200, 190, 200, 230, 300,
              400, 450, 470, 480, 490, 470, 430, 410,
              450, 500, 550, 530, 470, 400, 330, 270]
EXPORT_YEAR = EXPORT_24H * 365


# ============================================================
# Helper function tests
# ============================================================

class TestHelpers:
    """Pure utility function tests — no external dependencies."""

    def test_mwh_to_kwh_conversion(self):
        arr = np.array([500.0, 800.0, 1000.0])
        result = _mwh_to_kwh(arr)
        np.testing.assert_allclose(result, [0.5, 0.8, 1.0])

    def test_mwh_to_kwh_zero(self):
        arr = np.array([0.0])
        result = _mwh_to_kwh(arr)
        assert result[0] == 0.0

    def test_fit_to_length_truncate(self):
        arr = np.array([1, 2, 3, 4, 5])
        result = _fit_to_length(arr, 3)
        np.testing.assert_array_equal(result, [1, 2, 3])

    def test_fit_to_length_tile(self):
        arr = np.array([1, 2, 3])
        result = _fit_to_length(arr, 7)
        np.testing.assert_array_equal(result, [1, 2, 3, 1, 2, 3, 1])

    def test_fit_to_length_pad(self):
        arr = np.array([1, 2, 3])
        result = _fit_to_length(arr, 5, pad_value=99)
        np.testing.assert_array_equal(result, [1, 2, 3, 99, 99])

    def test_fit_to_length_exact(self):
        arr = np.array([1, 2, 3])
        result = _fit_to_length(arr, 3)
        np.testing.assert_array_equal(result, [1, 2, 3])

    def test_build_metadata(self):
        buy = np.full(100, 0.65)   # PLN/kWh → 650 PLN/MWh
        sell = np.full(100, 0.35)  # PLN/kWh → 350 PLN/MWh
        meta = _build_metadata(buy, sell)
        assert meta['avg_import_mwh'] == 650.0
        assert meta['avg_export_mwh'] == 350.0
        assert meta['spread_mwh'] == 300.0


# ============================================================
# Golden Master: Flat pricing consistency
# ============================================================

class TestFlatPricingConsistency:
    """
    PriceResolver PATH 3 (flat) must match old resolve_price_arrays().
    """

    def test_default_priceconfig(self):
        """Default PriceConfig → same arrays from old and new."""
        prices = PriceConfig()
        n = 8760

        old_buy, old_sell = resolve_price_arrays(prices, n)
        new = PriceResolver().resolve(n_hours=n, prices=prices)

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        # Sell: old clamps to 1e-6, new does too
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)
        assert new.path == "flat"
        assert new.n_hours == n

    def test_custom_priceconfig(self):
        """Custom import/export prices → same arrays."""
        prices = PriceConfig(
            import_price_pln_mwh=CUSTOM_BUY_MWH,
            export_price_pln_mwh=CUSTOM_SELL_MWH,
        )
        n = 100

        old_buy, old_sell = resolve_price_arrays(prices, n)
        new = PriceResolver().resolve(n_hours=n, prices=prices)

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)
        assert new.path == "flat"

    def test_zero_export_clamped(self):
        """Export=0 → clamped to 1e-6 (LP stability)."""
        prices = PriceConfig(import_price_pln_mwh=800.0, export_price_pln_mwh=0.0)
        n = 24

        old_buy, old_sell = resolve_price_arrays(prices, n)
        new = PriceResolver().resolve(n_hours=n, prices=prices)

        assert np.all(old_sell >= 1e-6)
        assert np.all(new.export_kwh >= 1e-6)
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)

    def test_none_priceconfig_uses_defaults(self):
        """prices=None → default PriceConfig (800/0 PLN/MWh)."""
        n = 48
        old_buy, old_sell = resolve_price_arrays(None, n)
        new = PriceResolver().resolve(n_hours=n, prices=None)

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)

    def test_flat_metadata(self):
        """Metadata (avg, spread) correct for flat pricing."""
        prices = PriceConfig(
            import_price_pln_mwh=650.0,
            export_price_pln_mwh=350.0,
        )
        new = PriceResolver().resolve(n_hours=100, prices=prices)

        assert new.avg_import_mwh == 650.0
        assert new.avg_export_mwh == 350.0
        assert new.spread_mwh == 300.0


# ============================================================
# Golden Master: RDN direct pricing consistency
# ============================================================

class TestRdnDirectConsistency:
    """
    PriceResolver PATH 1 (RDN direct) must match old
    resolve_buy_sell_for_dispatch() with import_prices.
    """

    def _make_arb_config(self, hourly_prices, export_prices=None):
        """Create ArbitrageConfig with RDN hourly prices."""
        config = ArbitrageConfig(
            enabled=True,
            hourly_prices_pln_mwh=hourly_prices,
        )
        if export_prices is not None:
            config.hourly_export_prices_pln_mwh = export_prices
        return config

    def test_rdn_direct_buy_prices(self):
        """RDN hourly → import_kwh matches old resolve_buy_sell_for_dispatch."""
        n = 8760
        arb = self._make_arb_config(RDN_YEAR)
        prices = PriceConfig(import_price_pln_mwh=800.0, export_price_pln_mwh=0.0)

        # Old path: convert manually then pass to resolve_buy_sell_for_dispatch
        import_arr = np.array(RDN_YEAR[:n], dtype=float) / 1000.0
        old_buy, old_sell = resolve_buy_sell_for_dispatch(
            prices=prices, n_steps=n,
            import_prices=import_arr,
            arbitrage_config=arb,
        )

        # New path: PriceResolver does conversion internally
        new = PriceResolver().resolve(
            n_hours=n, prices=prices, arbitrage_config=arb,
        )

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        assert new.path == "rdn_direct"

    def test_rdn_with_explicit_export(self):
        """RDN hourly with explicit export prices."""
        n = 8760
        arb = self._make_arb_config(RDN_YEAR, EXPORT_YEAR)
        prices = PriceConfig(import_price_pln_mwh=800.0, export_price_pln_mwh=0.0)

        # Old path
        import_arr = np.array(RDN_YEAR[:n], dtype=float) / 1000.0
        export_arr = np.array(EXPORT_YEAR[:n], dtype=float) / 1000.0
        old_buy, old_sell = resolve_buy_sell_for_dispatch(
            prices=prices, n_steps=n,
            import_prices=import_arr,
            export_prices=export_arr,
            arbitrage_config=arb,
        )

        # New path
        new = PriceResolver().resolve(
            n_hours=n, prices=prices, arbitrage_config=arb,
        )

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)

    def test_rdn_fallback_sell_095(self):
        """No export prices + export_price=0 → sell = buy × 0.95."""
        n = 8760
        arb = self._make_arb_config(RDN_YEAR)
        prices = PriceConfig(import_price_pln_mwh=800.0, export_price_pln_mwh=0.0)

        # Old path: buy*0.95 fallback
        import_arr = np.array(RDN_YEAR[:n], dtype=float) / 1000.0
        old_buy, old_sell = resolve_buy_sell_for_dispatch(
            prices=prices, n_steps=n,
            import_prices=import_arr,
            arbitrage_config=arb,
        )

        # New path
        new = PriceResolver().resolve(
            n_hours=n, prices=prices, arbitrage_config=arb,
        )

        np.testing.assert_allclose(new.import_kwh, old_buy, atol=1e-10)
        np.testing.assert_allclose(new.export_kwh, old_sell, atol=1e-10)

    def test_rdn_short_array_tiled(self):
        """RDN array shorter than n_hours → tiled to match."""
        n = 100
        short_rdn = RDN_24H  # 24 elements
        arb = self._make_arb_config(short_rdn * 5)  # 120 > 100
        prices = PriceConfig(import_price_pln_mwh=800.0, export_price_pln_mwh=0.0)

        new = PriceResolver().resolve(
            n_hours=n, prices=prices, arbitrage_config=arb,
        )

        assert len(new.import_kwh) == n
        assert new.path == "rdn_direct"

    def test_rdn_metadata(self):
        """RDN metadata (avg, spread) correct."""
        n = 8760
        arb = self._make_arb_config(RDN_YEAR, EXPORT_YEAR)
        prices = PriceConfig()

        new = PriceResolver().resolve(
            n_hours=n, prices=prices, arbitrage_config=arb,
        )

        expected_avg_import = np.mean(np.array(RDN_YEAR[:n]))
        expected_avg_export = np.mean(np.array(EXPORT_YEAR[:n]))
        assert abs(new.avg_import_mwh - expected_avg_import) < 0.5
        assert abs(new.avg_export_mwh - expected_avg_export) < 0.5
        assert new.spread_mwh > 0


# ============================================================
# Path selection tests
# ============================================================

class TestPathSelection:
    """PriceResolver chooses the correct path based on input data."""

    def test_no_arbitrage_uses_flat(self):
        """No ArbitrageConfig → flat path."""
        new = PriceResolver().resolve(n_hours=100)
        assert new.path == "flat"

    def test_arbitrage_disabled_uses_flat(self):
        """ArbitrageConfig.enabled=False → flat path."""
        arb = ArbitrageConfig(enabled=False, hourly_prices_pln_mwh=RDN_YEAR)
        new = PriceResolver().resolve(n_hours=100, arbitrage_config=arb)
        assert new.path == "flat"

    def test_rdn_hourly_uses_rdn_direct(self):
        """RDN hourly with >100 elements → rdn_direct path."""
        arb = ArbitrageConfig(enabled=True, hourly_prices_pln_mwh=RDN_YEAR)
        new = PriceResolver().resolve(n_hours=8760, arbitrage_config=arb)
        assert new.path == "rdn_direct"

    def test_short_hourly_falls_to_flat(self):
        """RDN hourly with <100 elements → not rdn_direct."""
        arb = ArbitrageConfig(enabled=True, hourly_prices_pln_mwh=RDN_24H)
        new = PriceResolver().resolve(n_hours=24, arbitrage_config=arb)
        # Should NOT be rdn_direct (too few elements)
        assert new.path != "rdn_direct"

    def test_tariff_without_start_date_skips_osd(self):
        """Tariff ID but no start_date → should not crash, falls to flat."""
        arb = ArbitrageConfig(enabled=True, tariff_id="pge_c12a_2025")
        new = PriceResolver().resolve(n_hours=100, arbitrage_config=arb)
        # Without start_date, OSD can't resolve → flat
        assert new.path == "flat"


# ============================================================
# ResolvedPrices contract tests
# ============================================================

class TestResolvedPricesContract:
    """ResolvedPrices always satisfies these invariants."""

    def test_arrays_correct_length(self):
        for n in [24, 100, 8760]:
            result = PriceResolver().resolve(n_hours=n)
            assert len(result.import_kwh) == n
            assert len(result.export_kwh) == n
            assert result.n_hours == n

    def test_import_positive(self):
        result = PriceResolver().resolve(n_hours=100)
        assert np.all(result.import_kwh > 0)

    def test_export_non_negative(self):
        result = PriceResolver().resolve(n_hours=100)
        assert np.all(result.export_kwh >= 0)

    def test_path_is_valid(self):
        result = PriceResolver().resolve(n_hours=100)
        assert result.path in ("rdn_direct", "osd_tariff", "hybrid", "flat")

    def test_spread_is_buy_minus_sell(self):
        prices = PriceConfig(
            import_price_pln_mwh=700.0,
            export_price_pln_mwh=400.0,
        )
        result = PriceResolver().resolve(n_hours=100, prices=prices)
        expected_spread = result.avg_import_mwh - result.avg_export_mwh
        assert abs(result.spread_mwh - expected_spread) < 0.1

    def test_rdn_spread_positive(self):
        """With RDN + export prices, spread should be positive (OSD fees)."""
        arb = ArbitrageConfig(
            enabled=True,
            hourly_prices_pln_mwh=RDN_YEAR,
            hourly_export_prices_pln_mwh=EXPORT_YEAR,
        )
        result = PriceResolver().resolve(n_hours=8760, arbitrage_config=arb)
        assert result.spread_mwh > 0


# ============================================================
# Convenience function test
# ============================================================

class TestConvenienceFunction:
    """resolve_prices() module-level function works correctly."""

    def test_resolve_prices_matches_class(self):
        prices = PriceConfig(import_price_pln_mwh=650.0, export_price_pln_mwh=300.0)
        n = 100

        from_class = PriceResolver().resolve(n_hours=n, prices=prices)
        from_func = resolve_prices(n_hours=n, prices=prices)

        np.testing.assert_allclose(from_class.import_kwh, from_func.import_kwh)
        np.testing.assert_allclose(from_class.export_kwh, from_func.export_kwh)
        assert from_class.path == from_func.path


# ============================================================
# Edge cases
# ============================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_hour(self):
        result = PriceResolver().resolve(n_hours=1)
        assert len(result.import_kwh) == 1
        assert len(result.export_kwh) == 1

    def test_large_n_hours(self):
        """35040 = 4 years × 8760."""
        result = PriceResolver().resolve(n_hours=35040)
        assert len(result.import_kwh) == 35040

    def test_rdn_with_flat_export_override(self):
        """RDN import + flat export_price > 0 → uses flat export, not buy*0.95."""
        arb = ArbitrageConfig(
            enabled=True,
            hourly_prices_pln_mwh=RDN_YEAR,
        )
        prices = PriceConfig(
            import_price_pln_mwh=800.0,
            export_price_pln_mwh=400.0,  # Meaningful flat export
        )
        result = PriceResolver().resolve(n_hours=8760, prices=prices, arbitrage_config=arb)

        # Should use flat export (400 PLN/MWh = 0.4 PLN/kWh), not buy*0.95
        assert result.path == "rdn_direct"
        assert abs(np.mean(result.export_kwh) - 0.4) < 0.01
