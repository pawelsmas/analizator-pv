/**
 * CENTRALIZED PRICE CONFIGURATION - Single Source of Truth
 *
 * All modules (BESS, Economics, Reports) MUST use this for price data.
 * DO NOT read price settings directly from systemSettings or localStorage.
 *
 * Usage:
 *   const pc = window.buildPriceConfig(settings);
 *   pc.arbitrageConfig        // ready for backend API
 *   pc.totalEnergyPricePlnMwh // flat rate sum
 *   pc.rdnPrices.available    // true if RDN hourly data loaded
 *   pc.getHourlyImportRate(hour, isWeekend) // PLN/kWh for given hour
 *   pc.warnings               // validation issues
 *
 * @version 1.0.0
 */
(function () {
  'use strict';

  // =========================================================================
  // HELPER
  // =========================================================================
  function pf(value, fallback) {
    if (value === null || value === undefined || value === '') return fallback;
    const p = parseFloat(value);
    return isNaN(p) ? fallback : p;
  }

  // =========================================================================
  // CALENDAR HELPERS (for per-hour fee calculation)
  // =========================================================================

  function _getEasterDate(year) {
    const a = year % 19, b = Math.floor(year / 100), c = year % 100;
    const d = Math.floor(b / 4), e = b % 4;
    const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4), k = c % 4;
    const l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451);
    const month = Math.floor((h + l - 7 * m + 114) / 31);
    const day = ((h + l - 7 * m + 114) % 31) + 1;
    return new Date(year, month - 1, day);
  }

  const _holidayCache = {};
  function _getPolishHolidays(year) {
    if (_holidayCache[year]) return _holidayCache[year];
    const easter = _getEasterDate(year);
    const easterMs = easter.getTime();
    const oneDay = 86400000;
    const dates = [
      new Date(year, 0, 1), new Date(year, 0, 6),
      easter, new Date(easterMs + oneDay),
      new Date(year, 4, 1), new Date(year, 4, 3),
      new Date(easterMs + 49 * oneDay), new Date(easterMs + 60 * oneDay),
      new Date(year, 7, 15), new Date(year, 10, 1), new Date(year, 10, 11),
      new Date(year, 11, 25), new Date(year, 11, 26),
    ];
    if (year >= 2025) dates.push(new Date(year, 11, 24)); // Wigilia
    const set = new Set(dates.map(d => {
      return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    }));
    _holidayCache[year] = set;
    return set;
  }

  function _isPolishWorkday(date) {
    const dow = date.getDay();
    if (dow === 0 || dow === 6) return false;
    const y = date.getFullYear();
    const key = `${y}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    return !_getPolishHolidays(y).has(key);
  }

  // =========================================================================
  // MAIN BUILDER
  // =========================================================================

  /**
   * Build a complete, immutable price configuration from settings.
   *
   * @param {Object} settings - systemSettings (from pv_system_settings)
   * @param {Object} [opts] - optional overrides
   * @param {Array<number>} [opts.rdnHourlyPrices] - RDN prices to use instead of localStorage
   * @param {Object} [opts.rdnScenarioInfo] - RDN scenario metadata
   * @returns {PriceConfig}
   */
  function buildPriceConfig(settings, opts) {
    settings = settings || {};
    opts = opts || {};
    const warnings = [];

    // -----------------------------------------------------------------
    // 1. COMPONENT BREAKDOWN (PLN/MWh)
    // -----------------------------------------------------------------
    // OSD zone rates from BESS arbitrage settings (PLN/kWh → PLN/MWh)
    // These reflect the actual C-class distribution tariff per zone.
    // Used as fallback when explicit distributionPeak/Day/Night are not set.
    const _osdPeakMwh = pf(settings.bessOsdPeakRate, 0.75) * 1000;    // e.g. 750 PLN/MWh
    const _osdOffMwh  = pf(settings.bessOsdOffPeakRate, 0.45) * 1000; // e.g. 450 PLN/MWh
    const _osdNightMwh = _osdOffMwh * 0.65;  // night ≈ 65% of off-peak (typical C12a)

    const components = {
      distributionPeak: pf(settings.distributionPeak, _osdPeakMwh),
      distributionDay:  pf(settings.distributionDay,  _osdOffMwh),
      distributionNight: pf(settings.distributionNight, _osdNightMwh),
      distributionValley: pf(settings.distributionValley, 13.5),
      qualityFee: pf(settings.qualityFee, 33.1),
      ozeFee: pf(settings.ozeFee, 7.3),
      cogenerationFee: pf(settings.cogenerationFee, 3),
      capacityFee: pf(settings.capacityFee, 219.4),
      exciseTax: pf(settings.exciseTax, 5),
    };
    // Weighted average distribution (simplified: equal weight day/night)
    components.distribution = pf(settings.distribution,
      (components.distributionPeak + components.distributionNight) / 2);

    const totalFixedCharges =
      components.distribution + components.qualityFee + components.ozeFee +
      components.cogenerationFee + components.capacityFee + components.exciseTax;

    // -----------------------------------------------------------------
    // 2. ToU TARIFF CONFIG
    // -----------------------------------------------------------------
    const tariffType = settings.tariffConfig?.type || settings.tariffType || 'two_zone';
    const tariffConfig = {
      type: tariffType,
      name: settings.tariffConfig?.name || settings.tariffName || 'C12a',
      flatRate: pf(settings.tariffConfig?.flatRate || settings.tariffFlatRate, 750),
      twoZone: {
        dayRate: pf(settings.tariffConfig?.twoZone?.dayRate || settings.tariffDayRate, 850),
        nightRate: pf(settings.tariffConfig?.twoZone?.nightRate || settings.tariffNightRate, 450),
        weekday: {
          start: parseInt(settings.tariffConfig?.twoZone?.weekday?.start || settings.tariffDayStartWeekday, 10) || 6,
          end: parseInt(settings.tariffConfig?.twoZone?.weekday?.end || settings.tariffDayEndWeekday, 10) || 22,
        },
        weekend: {
          start: parseInt(settings.tariffConfig?.twoZone?.weekend?.start || settings.tariffDayStartWeekend, 10) || 6,
          end: parseInt(settings.tariffConfig?.twoZone?.weekend?.end || settings.tariffDayEndWeekend, 10) || 13,
        },
      },
      threeZone: {
        peakRate: pf(settings.tariffConfig?.threeZone?.peakRate || settings.tariffPeakRate, 950),
        partialRate: pf(settings.tariffConfig?.threeZone?.partialRate || settings.tariffPartialRate, 700),
        offPeakRate: pf(settings.tariffConfig?.threeZone?.offPeakRate || settings.tariffOffPeakRate, 400),
        peak1: {
          start: parseInt(settings.tariffConfig?.threeZone?.peak1?.start || settings.tariffPeakStart, 10) || 7,
          end: parseInt(settings.tariffConfig?.threeZone?.peak1?.end || settings.tariffPeakEnd, 10) || 13,
        },
        peak2: {
          start: parseInt(settings.tariffConfig?.threeZone?.peak2?.start || settings.tariffPeakStart2, 10) || 17,
          end: parseInt(settings.tariffConfig?.threeZone?.peak2?.end || settings.tariffPeakEnd2, 10) || 21,
        },
        partial: {
          start: parseInt(settings.tariffConfig?.threeZone?.partial?.start || settings.tariffPartialStart, 10) || 13,
          end: parseInt(settings.tariffConfig?.threeZone?.partial?.end || settings.tariffPartialEnd, 10) || 17,
        },
      },
      fourZone: {
        peakRate: pf(settings.tariffConfig?.fourZone?.peakRate || settings.tariffFourPeakRate, 950),
        dayRate: pf(settings.tariffConfig?.fourZone?.dayRate || settings.tariffFourDayRate, 700),
        offPeakRate: pf(settings.tariffConfig?.fourZone?.offPeakRate || settings.tariffFourOffPeakRate, 400),
        valleyRate: pf(settings.tariffConfig?.fourZone?.valleyRate || settings.tariffFourValleyRate, 200),
      },
    };

    // Compute weighted ToU average (PLN/MWh) for flat calculations
    let energyActiveAvg;
    switch (tariffType) {
      case 'flat':
        energyActiveAvg = tariffConfig.flatRate;
        break;
      case 'three_zone':
        energyActiveAvg = (tariffConfig.threeZone.peakRate * 0.35 +
          tariffConfig.threeZone.partialRate * 0.25 +
          tariffConfig.threeZone.offPeakRate * 0.40);
        break;
      case 'four_zone':
        energyActiveAvg = (tariffConfig.fourZone.peakRate * 0.25 +
          tariffConfig.fourZone.dayRate * 0.30 +
          tariffConfig.fourZone.offPeakRate * 0.30 +
          tariffConfig.fourZone.valleyRate * 0.15);
        break;
      default: // two_zone
        energyActiveAvg = (tariffConfig.twoZone.dayRate * 0.58 +
          tariffConfig.twoZone.nightRate * 0.42);
        break;
    }

    const totalEnergyPricePlnMwh = pf(settings.totalEnergyPrice, energyActiveAvg + totalFixedCharges);

    // -----------------------------------------------------------------
    // 3. RDN HOURLY PRICES (from opts, sharedData, or localStorage)
    // -----------------------------------------------------------------
    let rdnHourlyPrices = null;
    let rdnScenarioInfo = null;

    // Priority 1: explicitly passed (from postMessage broadcast)
    if (opts.rdnHourlyPrices && opts.rdnHourlyPrices.length > 100) {
      rdnHourlyPrices = opts.rdnHourlyPrices;
      rdnScenarioInfo = opts.rdnScenarioInfo || null;
    }

    // Priority 2: localStorage fallback
    if (!rdnHourlyPrices) {
      try {
        const cached = localStorage.getItem('rdn_hourly_prices');
        const info = localStorage.getItem('rdn_scenario_info');
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 100) {
            rdnHourlyPrices = parsed;
          }
        }
        if (info) rdnScenarioInfo = JSON.parse(info);
      } catch (e) { /* ignore parse errors */ }
    }

    // Pre-compute RDN percentiles
    let rdnPercentiles = null;
    if (rdnHourlyPrices && rdnHourlyPrices.length > 0) {
      const sorted = rdnHourlyPrices.filter(p => p != null && !isNaN(p)).sort((a, b) => a - b);
      if (sorted.length > 0) {
        rdnPercentiles = {
          p10: sorted[Math.floor(sorted.length * 0.10)] || 0,
          p25: sorted[Math.floor(sorted.length * 0.25)] || 0,
          p50: sorted[Math.floor(sorted.length * 0.50)] || 0,
          p75: sorted[Math.floor(sorted.length * 0.75)] || 0,
          p90: sorted[Math.floor(sorted.length * 0.90)] || 0,
          min: sorted[0],
          max: sorted[sorted.length - 1],
          avg: sorted.reduce((a, b) => a + b, 0) / sorted.length,
        };
      }
    }

    const rdnPrices = {
      available: !!(rdnHourlyPrices && rdnHourlyPrices.length >= 8000),
      hourlyPricesPlnMwh: rdnHourlyPrices,
      scenarioInfo: rdnScenarioInfo,
      percentiles: rdnPercentiles,
      dataPoints: rdnHourlyPrices ? rdnHourlyPrices.length : 0,
    };

    // -----------------------------------------------------------------
    // 4. OSD ARBITRAGE FLAGS
    // -----------------------------------------------------------------
    const osdEnabled = settings.bessOsdArbitrageEnabled === true;
    const rdnEnabled = settings.bessPriceArbitrageEnabled === true;

    // -----------------------------------------------------------------
    // 5. PRICING MODE & HYBRID MONTHLY
    // -----------------------------------------------------------------
    const pricingMode = settings.pricingMode || 'single';
    let monthlyPriceSources = null;
    if (pricingMode === 'hybrid_monthly' && settings.monthlyPriceSources) {
      // Normalize keys to int
      monthlyPriceSources = {};
      for (const [k, v] of Object.entries(settings.monthlyPriceSources)) {
        monthlyPriceSources[parseInt(k, 10)] = v;
      }
    }

    // -----------------------------------------------------------------
    // 6. BUILD ARBITRAGE CONFIG (for backend API)
    // -----------------------------------------------------------------
    let arbitrageConfig = null;

    if (osdEnabled || rdnEnabled) {
      const year = new Date().getFullYear();
      const operatorMap = { pge: 'pge', tauron: 'tauron', energa: 'energa', enea: 'enea', innogy: 'stoen' };
      const operator = settings.bessOsdOperator || 'pge';
      const group = settings.bessOsdTariffGroup || 'C12a';

      // OSD tariff_id for backend preset lookup
      const osdTariffId = `${operatorMap[operator] || operator}_${group.toLowerCase()}_${year}`;

      arbitrageConfig = {
        enabled: true,
        charge_below_percentile: 25,
        discharge_above_percentile: 75,
        arbitrage_soc_min: pf(settings.bessArbitrageSocMin, 0.20),
        degradation_cost_pln_kwh: pf(settings.bessArbitrageDegradationCost, 0.05),
      };

      // --- OSD tariff arbitrage ---
      if (osdEnabled) {
        arbitrageConfig.tariff_id = osdTariffId;
        arbitrageConfig.strategy = 'zone_based';
        arbitrageConfig.osd_operator = operator;
        arbitrageConfig.osd_tariff_group = group;
        arbitrageConfig.peak_rate_pln_kwh = pf(settings.bessOsdPeakRate, 0.75);
        arbitrageConfig.offpeak_rate_pln_kwh = pf(settings.bessOsdOffPeakRate, 0.45);
        arbitrageConfig.min_spread_pln_kwh = pf(settings.bessOsdMinSpread, 0.15);
        arbitrageConfig.start_date = `${year}-01-01`;
      }

      // --- RDN price arbitrage ---
      if (rdnEnabled) {
        arbitrageConfig.price_arbitrage_enabled = true;
        arbitrageConfig.price_source = settings.bessPriceArbitrageSource || 'rdn_widget';

        if (rdnPrices.available) {
          // =================================================================
          // BUILD ALL-IN PRICES: RDN + dystrybucja(h) + flat fees + mocowa(h)
          // =================================================================
          // Distribution zone config from settings
          const distCfg = settings.distributionConfig || {};
          const distType = distCfg.type || 'three_zone';
          const distPeak = components.distributionPeak;   // PLN/MWh
          const distDay = components.distributionDay;     // PLN/MWh
          const distNight = components.distributionNight;  // PLN/MWh
          const distValley = components.distributionValley; // PLN/MWh

          // Distribution zone time windows
          const dist3z = distCfg.threeZone || { peak1: {start:7,end:13}, peak2: {start:16,end:21}, weekendOffPeak: true };
          const dist4z = distCfg.fourZone || { peak1: {start:7,end:13}, peak2: {start:16,end:21}, valley: {start:1,end:5} };
          const dist2z = distCfg.twoZone || { weekday: {start:6,end:22}, weekend: {start:6,end:22} };

          function _getDistRate(hour, isWeekend) {
            // Returns distribution rate in PLN/MWh for given hour/day type
            switch (distType) {
              case 'flat':
                return components.distribution;
              case 'two_zone': {
                const bounds = isWeekend ? dist2z.weekend : dist2z.weekday;
                const isDayZone = hour >= (bounds.start || 6) && hour < (bounds.end || 22);
                return isDayZone ? distDay : distNight;
              }
              case 'four_zone': {
                if (isWeekend) return distNight;
                if ((hour >= dist4z.peak1.start && hour < dist4z.peak1.end) ||
                    (hour >= dist4z.peak2.start && hour < dist4z.peak2.end)) return distPeak;
                if (hour >= (dist4z.valley?.start || 1) && hour < (dist4z.valley?.end || 5)) return distValley;
                return distDay;
              }
              default: { // three_zone
                if (isWeekend && dist3z.weekendOffPeak !== false) return distNight;
                if ((hour >= dist3z.peak1.start && hour < dist3z.peak1.end) ||
                    (hour >= dist3z.peak2.start && hour < dist3z.peak2.end)) return isWeekend ? distNight : distPeak;
                return isWeekend ? distNight : distDay;
              }
            }
          }

          // Capacity fee config
          const capCfg = settings.capacityFeeConfig || {};
          const somRate = pf(capCfg.somRate || settings.capacitySomRate, 0.2194); // PLN/kWh
          const somRatePlnMwh = somRate * 1000; // PLN/MWh
          const capHours = capCfg.selectedHours || { Q1:{start:7,end:22}, Q2:{start:7,end:22}, Q3:{start:7,end:22}, Q4:{start:7,end:22} };

          function _getQuarter(month) {
            if (month <= 2) return 'Q1';
            if (month <= 5) return 'Q2';
            if (month <= 8) return 'Q3';
            return 'Q4';
          }

          // Flat fees that apply every hour (PLN/MWh)
          const flatFeesPlnMwh = components.qualityFee + components.ozeFee +
            components.cogenerationFee + components.exciseTax;

          // Build all-in price array
          const startYear = rdnScenarioInfo?.year || year;
          const startDate = new Date(startYear, 0, 1);
          const n = rdnHourlyPrices.length;
          const rdnAllInPrices = new Array(n);
          let allInSum = 0;

          for (let i = 0; i < n; i++) {
            const date = new Date(startDate.getTime() + i * 3600000);
            const hour = date.getHours();
            const dow = date.getDay();
            const month = date.getMonth(); // 0-based
            const isWeekend = (dow === 0 || dow === 6);
            const isWorkday = _isPolishWorkday(date);

            // Base: RDN energy price (PLN/MWh)
            let allIn = rdnHourlyPrices[i] || 0;

            // + Distribution variable (per zone, PLN/MWh)
            allIn += _getDistRate(hour, isWeekend);

            // + Flat fees: jakosciowa + OZE + kogeneracja + akcyza (PLN/MWh)
            allIn += flatFeesPlnMwh;

            // + Capacity fee (only workday qualifying hours, PLN/MWh)
            if (isWorkday) {
              const q = _getQuarter(month);
              const sh = capHours[q] || { start: 7, end: 22 };
              if (hour >= sh.start && hour < sh.end) {
                allIn += somRatePlnMwh;
              }
            }

            rdnAllInPrices[i] = allIn;
            allInSum += allIn;
          }

          const allInAvg = n > 0 ? allInSum / n : 0;
          console.log(`[PriceConfig] RDN all-in prices built: ${n} hours, ` +
            `raw_avg=${rdnPercentiles?.avg?.toFixed(0)} PLN/MWh, ` +
            `all_in_avg=${allInAvg.toFixed(0)} PLN/MWh, ` +
            `markup=${(allInAvg - (rdnPercentiles?.avg || 0)).toFixed(0)} PLN/MWh`);

          // Send all-in prices as buy_price (import cost from grid)
          arbitrageConfig.hourly_prices_pln_mwh = rdnAllInPrices;
          // Send raw RDN as sell_price (prosumer export price = RDN without OSD fees)
          arbitrageConfig.hourly_export_prices_pln_mwh = rdnHourlyPrices;
          // Diagnostics
          arbitrageConfig.raw_rdn_avg_pln_mwh = rdnPercentiles?.avg || 0;
          arbitrageConfig.all_in_avg_pln_mwh = Math.round(allInAvg);
          // Use actual percentiles from data
          arbitrageConfig.buy_threshold_pln_mwh = rdnPercentiles ? rdnPercentiles.p25 : 300;
          arbitrageConfig.sell_threshold_pln_mwh = rdnPercentiles ? rdnPercentiles.p75 : 600;
          arbitrageConfig.min_spread_pln_mwh = rdnPercentiles
            ? Math.max(50, (rdnPercentiles.p75 - rdnPercentiles.p25) * 0.3)
            : 100;
          console.log('[PriceConfig] RDN prices attached:', rdnPrices.dataPoints, 'points, avg=',
            rdnPercentiles?.avg?.toFixed(0), 'PLN/MWh');
        } else {
          // RDN enabled but no data - use manual thresholds from settings
          arbitrageConfig.buy_threshold_pln_mwh = pf(settings.bessPriceArbitrageBuyThreshold, 300);
          arbitrageConfig.sell_threshold_pln_mwh = pf(settings.bessPriceArbitrageSellThreshold, 600);
          arbitrageConfig.min_spread_pln_mwh = pf(settings.bessPriceArbitrageSpread, 100);
          warnings.push('Arbitraz RDN wlaczony, ale brak danych cenowych - zaladuj ceny w widgecie Ceny RDN');
        }

        // If only RDN (no OSD), use percentile strategy
        if (!osdEnabled) {
          arbitrageConfig.strategy = 'percentile';
          arbitrageConfig.tariff_id = 'rdn_spot_' + (rdnScenarioInfo?.year || year);
          arbitrageConfig.start_date = `${rdnScenarioInfo?.year || year}-01-01`;
        }
      }

      // --- Hybrid monthly ---
      if (pricingMode === 'hybrid_monthly' && monthlyPriceSources && osdEnabled && rdnEnabled) {
        arbitrageConfig.pricing_mode = 'hybrid_monthly';
        arbitrageConfig.monthly_price_sources = monthlyPriceSources;
        arbitrageConfig.osd_enabled = true;
        arbitrageConfig.rdn_enabled = true;

        if (!rdnPrices.available) {
          warnings.push('Tryb hybrydowy wymaga danych RDN - zaladuj ceny godzinowe');
        }
      }

      // Flag both sources for UI display
      arbitrageConfig.osd_enabled = osdEnabled;
      arbitrageConfig.rdn_enabled = rdnEnabled;
    }

    // -----------------------------------------------------------------
    // 7. CAPACITY FEE CONFIG
    // -----------------------------------------------------------------
    const capacityFeeConfig = {
      somRate: pf(settings.capacityFeeConfig?.somRate || settings.capacitySomRate, 0.2194),
      qualificationPeriod: settings.capacityFeeConfig?.qualificationPeriod ||
        settings.capacityQualificationPeriod || 'daily',
    };

    // -----------------------------------------------------------------
    // 8. FIXED MONTHLY FEES
    // -----------------------------------------------------------------
    const fixedMonthlyFees = {
      contractedPowerKw: pf(settings.contractedPowerKw, 50),
      distFixedRatePerKwMonth: pf(settings.distFixedRatePerKwMonth, 9.14),
      osdSubscriptionFeeMonth: pf(settings.osdSubscriptionFeeMonth, 5.54),
      transitionFeeMonth: pf(settings.transitionFeeMonth, 0),
      supplierTradeFeeMonth: pf(settings.supplierTradeFeeMonth, 0),
      demandChargePerKwMonth: pf(settings.bessPowerChargePlnPerKwMonth, 50),
    };

    // -----------------------------------------------------------------
    // 9. HOURLY RATE HELPER (for tight loops in economics)
    // -----------------------------------------------------------------

    /**
     * Get energy-only rate for a given hour (PLN/kWh).
     * Does NOT include distribution/fees - just the active energy component.
     *
     * @param {number} hour - Hour of day (0-23)
     * @param {boolean} isWeekend - Is it Saturday or Sunday?
     * @returns {number} PLN/kWh
     */
    function getEnergyRate(hour, isWeekend) {
      switch (tariffType) {
        case 'flat':
          return tariffConfig.flatRate / 1000;
        case 'two_zone': {
          const wd = tariffConfig.twoZone.weekday;
          const we = tariffConfig.twoZone.weekend;
          const bounds = isWeekend ? we : wd;
          const isDay = hour >= bounds.start && hour < bounds.end;
          return (isDay ? tariffConfig.twoZone.dayRate : tariffConfig.twoZone.nightRate) / 1000;
        }
        case 'three_zone': {
          const tz = tariffConfig.threeZone;
          if ((hour >= tz.peak1.start && hour < tz.peak1.end) ||
              (hour >= tz.peak2.start && hour < tz.peak2.end)) {
            return isWeekend ? tz.offPeakRate / 1000 : tz.peakRate / 1000;
          }
          if (hour >= tz.partial.start && hour < tz.partial.end) {
            return isWeekend ? tz.offPeakRate / 1000 : tz.partialRate / 1000;
          }
          return tz.offPeakRate / 1000;
        }
        case 'four_zone': {
          const fz = tariffConfig.fourZone;
          if (hour >= 7 && hour < 13) return isWeekend ? fz.offPeakRate / 1000 : fz.peakRate / 1000;
          if (hour >= 13 && hour < 17) return isWeekend ? fz.offPeakRate / 1000 : fz.dayRate / 1000;
          if (hour >= 17 && hour < 22) return isWeekend ? fz.offPeakRate / 1000 : fz.peakRate / 1000;
          if (hour >= 22 || hour < 6) return fz.valleyRate / 1000;
          return fz.offPeakRate / 1000;
        }
        default:
          return energyActiveAvg / 1000;
      }
    }

    /**
     * Get full import rate including all fees (PLN/kWh).
     * Optionally uses RDN hourly price for the given timestep index.
     *
     * @param {number} hour - Hour of day (0-23)
     * @param {boolean} isWeekend - Is it Saturday/Sunday?
     * @param {number} [timestepIdx] - Index into rdnHourlyPrices (for RDN mode)
     * @param {number} [month] - Month 1-12 (for hybrid mode)
     * @returns {number} PLN/kWh
     */
    function getHourlyImportRate(hour, isWeekend, timestepIdx, month) {
      const feesPerKwh = totalFixedCharges / 1000;

      // Hybrid monthly: check source for this month
      if (pricingMode === 'hybrid_monthly' && monthlyPriceSources && month) {
        const src = monthlyPriceSources[month] || 'osd';
        if (src === 'rdn' && rdnHourlyPrices && timestepIdx != null && timestepIdx < rdnHourlyPrices.length) {
          return rdnHourlyPrices[timestepIdx] / 1000 + feesPerKwh;
        }
        // OSD month: use ToU
        return getEnergyRate(hour, isWeekend) + feesPerKwh;
      }

      // Pure RDN mode
      if (rdnEnabled && rdnPrices.available && timestepIdx != null && timestepIdx < rdnHourlyPrices.length) {
        return rdnHourlyPrices[timestepIdx] / 1000 + feesPerKwh;
      }

      // Default: ToU + fees
      return getEnergyRate(hour, isWeekend) + feesPerKwh;
    }

    // -----------------------------------------------------------------
    // 10. VALIDATION
    // -----------------------------------------------------------------
    if (osdEnabled && !arbitrageConfig?.tariff_id) {
      warnings.push('OSD arbitraz wlaczony, ale brak tariff_id');
    }
    if (pricingMode === 'hybrid_monthly' && (!osdEnabled || !rdnEnabled)) {
      warnings.push('Tryb hybrydowy wymaga zarowno OSD jak i RDN');
    }
    if (totalEnergyPricePlnMwh > 2000) {
      warnings.push('Cena energii > 2000 PLN/MWh - sprawdz poprawnosc');
    }
    if (totalEnergyPricePlnMwh < 200) {
      warnings.push('Cena energii < 200 PLN/MWh - sprawdz poprawnosc');
    }

    if (warnings.length > 0) {
      console.warn('[PriceConfig] Warnings:', warnings);
    }

    // -----------------------------------------------------------------
    // 11. RETURN IMMUTABLE CONFIG
    // -----------------------------------------------------------------
    const config = {
      // Flat rate
      totalEnergyPricePlnMwh,
      energyActiveAvgPlnMwh: energyActiveAvg,
      totalFixedChargesPlnMwh: totalFixedCharges,

      // Component breakdown
      components,

      // Tariff
      tariffConfig,
      tariffType,

      // RDN
      rdnPrices,

      // Arbitrage (ready for backend API)
      arbitrageConfig,

      // Pricing mode
      pricingMode,
      monthlyPriceSources,

      // Flags
      osdEnabled,
      rdnEnabled,

      // Capacity fee
      capacityFeeConfig,

      // Fixed monthly fees
      fixedMonthlyFees,

      // Helpers (for tight loops)
      getEnergyRate,
      getHourlyImportRate,

      // Validation
      warnings,

      // Metadata
      _version: '1.0.0',
      _builtAt: new Date().toISOString(),
    };

    console.log('[PriceConfig] Built:', {
      totalEnergyPricePlnMwh,
      energyActiveAvgPlnMwh: energyActiveAvg,
      tariffType,
      osdEnabled,
      rdnEnabled,
      rdnAvailable: rdnPrices.available,
      rdnPoints: rdnPrices.dataPoints,
      pricingMode,
      arbitrageType: arbitrageConfig?.strategy || 'none',
      warnings: warnings.length,
    });

    return config;
  }

  // =========================================================================
  // EXPORT
  // =========================================================================
  window.buildPriceConfig = buildPriceConfig;

  console.log('[PriceConfig] Centralized price config loaded (v1.0.0)');

})();
