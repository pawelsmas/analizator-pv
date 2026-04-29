"""
PLIK: price_resolver.py
ROLA: Jedyne źródło prawdy (SSoT) dla rozstrzygania cen import/export w module BESS.
WEJŚCIE: SizingRequest lub DispatchRequest (arbitrage_config, prices, start_date)
WYJŚCIE: ResolvedPrices (import/export arrays PLN/kWh + metadata)

ZALEŻNOŚCI:
  - price_engine.py → ToUPriceProvider (OSD tariff lookup)
  - osd_tariffs/presets/templates.py → ALL_PRESETS, TARIFF_ALIASES
  - models.py → PriceConfig, ArbitrageConfig

NIE ROBI:
  - Nie oblicza savings (to robi dispatch_engine / lp_dispatch)
  - Nie oblicza NPV (to robi economics_engine)
  - Nie decyduje o mode (to przychodzi z requestu)

UŻYCIE:
  from price_resolver import PriceResolver, ResolvedPrices

  resolver = PriceResolver()
  prices = resolver.resolve(
      n_hours=8760,
      prices=request.prices,
      arbitrage_config=request.arbitrage_config,
      start_date=request.start_date,
      interval_minutes=request.interval_minutes,
  )
  # prices.import_kwh → np.ndarray [PLN/kWh]
  # prices.export_kwh → np.ndarray [PLN/kWh]
  # prices.path → "rdn_direct" | "osd_tariff" | "hybrid" | "flat"

ŚCIEŻKI ROZSTRZYGANIA (priorytet):
  Path 0 (hybrid):    monthly_price_sources + hourly RDN → mix OSD/RDN per month
  Path 1 (rdn_direct): hourly_prices_pln_mwh → PLN/MWh ÷ 1000 = PLN/kWh
  Path 2 (osd_tariff): tariff_id → OSD preset → ToUPriceProvider → hourly PLN/kWh
  Path 3 (flat):       import_price_pln_mwh / export_price_pln_mwh → constant arrays

EXPORT PRICES (sell):
  - Explicit: hourly_export_prices_pln_mwh (raw RDN, no OSD fees)
  - Fallback: buy_price × 0.95 (opportunity-cost proxy)
  - Flat: export_price_pln_mwh from PriceConfig

Version: 1.0.0 — Faza 2 refaktoringu BESS
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Any, Dict

import numpy as np

logger = logging.getLogger(__name__)


def _getfield(obj, name, default=None):
    """Get field from dict or object attribute."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPrices:
    """
    Wynik rozstrzygania cen — kompletny pakiet do przekazania do dispatch/sizing.

    Jednostki: PLN/kWh (standard wewnętrzny dispatch engine).
    Frontend wysyła PLN/MWh → PriceResolver konwertuje ÷ 1000.
    """
    import_kwh: np.ndarray        # PLN/kWh, buy price (all-in: RDN + OSD + fees)
    export_kwh: np.ndarray        # PLN/kWh, sell price (raw RDN or flat export)
    path: str                     # "rdn_direct", "osd_tariff", "hybrid", "flat"
    tariff_id: Optional[str]      # Resolved tariff identifier (if OSD used)
    avg_import_mwh: float         # Average import price PLN/MWh (for logging)
    avg_export_mwh: float         # Average export price PLN/MWh (for logging)
    spread_mwh: float             # Average buy-sell spread PLN/MWh
    n_hours: int                  # Length of price arrays


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mwh_to_kwh(arr_mwh: np.ndarray) -> np.ndarray:
    """PLN/MWh → PLN/kWh."""
    return arr_mwh / 1000.0


def _fit_to_length(arr: np.ndarray, n: int, pad_value: float = None) -> np.ndarray:
    """Truncate or tile/pad array to exactly n elements."""
    if len(arr) >= n:
        return arr[:n]
    if pad_value is not None:
        return np.pad(arr, (0, n - len(arr)), 'constant', constant_values=pad_value)
    # Tile to cover
    repeats = (n + len(arr) - 1) // len(arr)
    return np.tile(arr, repeats)[:n]


def _resolve_osd_tariff(tariff_id: str):
    """Lookup OSD tariff from presets. Returns (tariff, resolved_id) or (None, None)."""
    from osd_tariffs.presets.templates import ALL_PRESETS, TARIFF_ALIASES

    resolved_id = TARIFF_ALIASES.get(tariff_id, tariff_id)
    tariff = ALL_PRESETS.get(resolved_id) or ALL_PRESETS.get(tariff_id)
    if tariff is None:
        for t in ALL_PRESETS.values():
            if t.id == tariff_id or t.id == resolved_id:
                return t, resolved_id
    return tariff, resolved_id


def _build_metadata(import_kwh: np.ndarray, export_kwh: np.ndarray) -> dict:
    """Compute summary statistics for logging."""
    avg_import = float(np.mean(import_kwh) * 1000)
    avg_export = float(np.mean(export_kwh) * 1000)
    return dict(
        avg_import_mwh=round(avg_import, 1),
        avg_export_mwh=round(avg_export, 1),
        spread_mwh=round(avg_import - avg_export, 1),
    )


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

class PriceResolver:
    """
    Centralna rozdzielczość cen import/export.

    Wywołana RAZ per request (sizing lub dispatch).
    Wynik (ResolvedPrices) przekazywany do dispatch/sizing bez dalszych transformacji.
    """

    def resolve(
        self,
        n_hours: int,
        prices: Optional[Any] = None,          # PriceConfig
        arbitrage_config: Optional[Any] = None, # ArbitrageConfig
        start_date: Optional[str] = None,       # "YYYY-MM-DD"
        interval_minutes: int = 60,
    ) -> ResolvedPrices:
        """
        Rozstrzyga ceny import/export na podstawie dostępnych danych.

        Priorytet ścieżek:
        0. Hybrid monthly (OSD + RDN per month) — jeśli monthly_price_sources
        1. RDN direct — jeśli hourly_prices_pln_mwh (>100 elementów)
        2. OSD tariff — jeśli tariff_id
        3. Flat — z PriceConfig.import_price_pln_mwh / export_price_pln_mwh
        """
        arb = arbitrage_config
        arb_enabled = arb and _getfield(arb, 'enabled', False)

        # --- Try Path 0: Hybrid monthly ---
        if arb_enabled and self._has_hybrid_sources(arb):
            result = self._resolve_hybrid(arb, n_hours, start_date, interval_minutes)
            if result is not None:
                import_kwh = result
                export_kwh = self._resolve_export(arb, import_kwh, prices, n_hours)
                return self._build_result(import_kwh, export_kwh, "hybrid",
                                          _getfield(arb, 'tariff_id', None), n_hours)

        # --- Try Path 1: RDN direct ---
        if arb_enabled and self._has_rdn_hourly(arb):
            result = self._resolve_rdn_direct(arb, n_hours)
            if result is not None:
                import_kwh = result
                export_kwh = self._resolve_export(arb, import_kwh, prices, n_hours)
                return self._build_result(import_kwh, export_kwh, "rdn_direct",
                                          "rdn_spot", n_hours)

        # --- Try Path 2: OSD tariff ---
        if arb_enabled and self._has_tariff(arb) and start_date:
            result = self._resolve_osd(arb, n_hours, start_date, interval_minutes)
            if result is not None:
                import_kwh = result
                export_kwh = self._resolve_export(arb, import_kwh, prices, n_hours)
                return self._build_result(import_kwh, export_kwh, "osd_tariff",
                                          _getfield(arb, 'tariff_id', None), n_hours)

        # --- Path 3: Flat fallback ---
        import_kwh, export_kwh = self._resolve_flat(prices, n_hours)
        return self._build_result(import_kwh, export_kwh, "flat",
                                  _getfield(prices, 'tariff_id', None) if prices else None,
                                  n_hours)

    # -----------------------------------------------------------------------
    # Path checks
    # -----------------------------------------------------------------------

    @staticmethod
    def _has_hybrid_sources(arb) -> bool:
        hp = _getfield(arb, 'hourly_prices_pln_mwh', None)
        return (_getfield(arb, 'monthly_price_sources', None) is not None and
                hp is not None and len(hp) > 100)

    @staticmethod
    def _has_rdn_hourly(arb) -> bool:
        hp = _getfield(arb, 'hourly_prices_pln_mwh', None)
        return hp is not None and len(hp) > 100

    @staticmethod
    def _has_tariff(arb) -> bool:
        return bool(_getfield(arb, 'tariff_id', None))

    # -----------------------------------------------------------------------
    # Path 0: Hybrid monthly
    # -----------------------------------------------------------------------

    def _resolve_hybrid(self, arb, n_hours: int, start_date: str,
                        interval_minutes: int) -> Optional[np.ndarray]:
        try:
            from price_engine import ToUPriceProvider, ToUPriceConfig, HybridMonthlyPriceProvider

            rdn_kwh = _mwh_to_kwh(np.array(arb.hourly_prices_pln_mwh, dtype=float))
            rdn_kwh = _fit_to_length(rdn_kwh, n_hours)

            tariff, resolved_id = _resolve_osd_tariff(arb.tariff_id)
            if tariff is None:
                logger.warning(f"PRICE_RESOLVE: Hybrid - tariff not found: {arb.tariff_id}")
                return None

            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            n_days = (n_hours + 23) // 24
            ed = sd + timedelta(days=n_days - 1)

            config = ToUPriceConfig(
                osd_tariff=tariff,
                capacity_fee_pln_kwh=0.0,
                other_components_pln_kwh=_getfield(arb, 'other_components_pln_kwh', 0.0),
            )
            tou_provider = ToUPriceProvider(config)

            monthly_sources = {int(k): v for k, v in arb.monthly_price_sources.items()}
            hybrid = HybridMonthlyPriceProvider(
                tou_provider=tou_provider,
                rdn_prices_pln_kwh=rdn_kwh,
                monthly_sources=monthly_sources,
                start_date=sd,
            )
            bundle = hybrid.get_series(sd, ed, interval_minutes)
            import_kwh = np.array(bundle.import_total[:n_hours])

            rdn_months = [m for m, s in monthly_sources.items() if s == 'rdn']
            osd_months = [m for m, s in monthly_sources.items() if s != 'rdn']
            logger.warning(
                f"PRICE_RESOLVE: PATH 0 (Hybrid) OK: RDN months={rdn_months}, "
                f"OSD months={osd_months}, avg={np.mean(import_kwh)*1000:.0f} PLN/MWh"
            )
            return import_kwh

        except Exception as e:
            logger.error(f"PRICE_RESOLVE: PATH 0 (Hybrid) FAILED: {e}")
            return None

    # -----------------------------------------------------------------------
    # Path 1: RDN direct
    # -----------------------------------------------------------------------

    def _resolve_rdn_direct(self, arb, n_hours: int) -> Optional[np.ndarray]:
        try:
            raw_kwh = _mwh_to_kwh(np.array(arb.hourly_prices_pln_mwh, dtype=float))
            import_kwh = _fit_to_length(raw_kwh, n_hours)

            logger.warning(
                f"PRICE_RESOLVE: PATH 1 (RDN direct) OK: {len(import_kwh)} hours, "
                f"avg={np.mean(import_kwh)*1000:.0f} PLN/MWh, "
                f"min={np.min(import_kwh)*1000:.0f}, max={np.max(import_kwh)*1000:.0f}"
            )
            return import_kwh

        except Exception as e:
            logger.error(f"PRICE_RESOLVE: PATH 1 (RDN direct) FAILED: {e}")
            return None

    # -----------------------------------------------------------------------
    # Path 2: OSD tariff
    # -----------------------------------------------------------------------

    def _resolve_osd(self, arb, n_hours: int, start_date: str,
                     interval_minutes: int) -> Optional[np.ndarray]:
        try:
            from price_engine import ToUPriceProvider, ToUPriceConfig

            tariff, resolved_id = _resolve_osd_tariff(arb.tariff_id)
            if tariff is None:
                logger.warning(
                    f"PRICE_RESOLVE: PATH 2 - tariff not found: {arb.tariff_id}"
                )
                return None

            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            n_days = (n_hours + 23) // 24
            ed = sd + timedelta(days=n_days - 1)

            config = ToUPriceConfig(
                osd_tariff=tariff,
                capacity_fee_pln_kwh=0.0,
                other_components_pln_kwh=_getfield(arb, 'other_components_pln_kwh', 0.0),
            )
            provider = ToUPriceProvider(config)
            bundle = provider.get_series(sd, ed, interval_minutes)

            import_kwh = np.array(bundle.import_total[:n_hours])
            if len(import_kwh) < n_hours:
                pad_val = import_kwh[-1] if len(import_kwh) > 0 else 0.65
                import_kwh = _fit_to_length(import_kwh, n_hours, pad_value=pad_val)

            logger.warning(
                f"PRICE_RESOLVE: PATH 2 (OSD tariff) OK: tariff={arb.tariff_id}, "
                f"resolved={resolved_id}, {len(import_kwh)} hours, "
                f"avg={np.mean(import_kwh)*1000:.0f} PLN/MWh"
            )
            return import_kwh

        except Exception as e:
            logger.error(f"PRICE_RESOLVE: PATH 2 (OSD tariff) FAILED: {e}")
            return None

    # -----------------------------------------------------------------------
    # Path 3: Flat fallback
    # -----------------------------------------------------------------------

    @staticmethod
    def _resolve_flat(prices, n_hours: int):
        if prices is None:
            from models import PriceConfig
            prices = PriceConfig()

        _import = _getfield(prices, 'import_price_pln_mwh', 800.0)
        _export = _getfield(prices, 'export_price_pln_mwh', 0.0)
        buy = np.full(n_hours, _import / 1000.0)
        sell = np.full(n_hours, _export / 1000.0)
        sell = np.maximum(sell, 1e-6)  # LP stability

        logger.warning(
            f"PRICE_RESOLVE: PATH 3 (Flat) OK: buy={_import:.0f}, "
            f"sell={_export:.0f} PLN/MWh"
        )
        return buy, sell

    # -----------------------------------------------------------------------
    # Export price resolution (shared across paths 0-2)
    # -----------------------------------------------------------------------

    @staticmethod
    def _resolve_export(arb, import_kwh: np.ndarray, prices, n_hours: int) -> np.ndarray:
        """
        Rozstrzyga cenę eksportu (sell/prosumer):
        1. Explicit: hourly_export_prices_pln_mwh (raw RDN)
        2. Fallback: buy_price × 0.95
        3. Flat: export_price_pln_mwh from PriceConfig
        """
        exp_raw = _getfield(arb, 'hourly_export_prices_pln_mwh', None)
        if exp_raw is not None and len(exp_raw) > 100:
            export_kwh = _mwh_to_kwh(np.array(exp_raw, dtype=float))
            export_kwh = _fit_to_length(export_kwh, n_hours)
            logger.warning(
                f"PRICE_RESOLVE: Export prices (raw RDN): "
                f"avg={np.mean(export_kwh)*1000:.0f} PLN/MWh, "
                f"spread buy-sell={np.mean(import_kwh - export_kwh)*1000:.0f} PLN/MWh"
            )
            return export_kwh

        # Fallback: check if flat export is meaningful
        _exp = _getfield(prices, 'export_price_pln_mwh', 0)
        if prices and _exp > 0.01:
            export_kwh = np.full(n_hours, _exp / 1000.0)
            logger.warning(
                f"PRICE_RESOLVE: No export prices -> flat export={_exp:.0f} PLN/MWh"
            )
            return np.maximum(export_kwh, 1e-6)

        # BESS-only (no PV export): sell_price = buy_price
        # Battery doesn't export to grid — it time-shifts load.
        # LP uses spread between cheap hours (charge) and expensive hours (discharge).
        # Setting sell = buy means LP profit = buy_expensive - buy_cheap - RT_losses.
        logger.warning("PRICE_RESOLVE: No export prices → sell=buy (BESS time-shift mode)")
        return import_kwh.copy()

    # -----------------------------------------------------------------------
    # Build result
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_result(import_kwh, export_kwh, path, tariff_id, n_hours) -> ResolvedPrices:
        meta = _build_metadata(import_kwh, export_kwh)
        return ResolvedPrices(
            import_kwh=import_kwh,
            export_kwh=export_kwh,
            path=path,
            tariff_id=tariff_id,
            avg_import_mwh=meta['avg_import_mwh'],
            avg_export_mwh=meta['avg_export_mwh'],
            spread_mwh=meta['spread_mwh'],
            n_hours=n_hours,
        )


# ---------------------------------------------------------------------------
# Module-level singleton (optional convenience)
# ---------------------------------------------------------------------------

_default_resolver = PriceResolver()


def resolve_prices(
    n_hours: int,
    prices=None,
    arbitrage_config=None,
    start_date=None,
    interval_minutes=60,
) -> ResolvedPrices:
    """Convenience function using default resolver."""
    return _default_resolver.resolve(
        n_hours=n_hours,
        prices=prices,
        arbitrage_config=arbitrage_config,
        start_date=start_date,
        interval_minutes=interval_minutes,
    )
