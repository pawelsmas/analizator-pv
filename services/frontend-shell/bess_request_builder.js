/**
 * PLIK: bess_request_builder.js
 * ROLA: SSoT budowania BESS API request — jedyne miejsce tworzenia requestów do /dispatch i /sizing.
 * WEJŚCIE: settings (z window.PVSettings), load_kw[], pv_generation_kw[], overrides
 * WYJŚCIE: JSON request body zgodny z SizingRequest/DispatchRequest (backend app.py)
 * NIE ROBI: Nie wyświetla UI (to robi bess.js), nie liczy ekonomiki (to robi economics.js),
 *           nie definiuje scenariuszy (SSoT: BESS_SCENARIOS w settings.js)
 *
 * All modules MUST use this builder to ensure consistent parameters.
 * DO NOT build BESS requests manually - always use buildBessRequest().
 *
 * This file is loaded by shell/index.html BEFORE all modules.
 *
 * @version 1.0.0
 * @author ANALIZATOR PV Team
 */

(function() {
  'use strict';

  /**
   * Build tariff preset ID from group name and OSD operator.
   *
   * Maps settings.tariffGroup (e.g. "B23") + settings.osdOperator (e.g. "pge")
   * to a preset ID (e.g. "pge_b23_2026") matching keys in ALL_PRESETS.
   *
   * @param {string} group - Tariff group (e.g. "B23", "C12a", "C22a")
   * @param {string} operator - OSD operator (e.g. "pge", "tauron", "energa")
   * @param {number} [year] - Tariff year (default: from analyticalPeriod or 2026)
   * @returns {string|null} Preset ID or null if no group provided
   */
  function buildTariffPresetId(group, operator, year) {
    if (!group) return null;
    // Only OSD ToU groups have presets (C11, C12a, C12b, G12).
    // Groups B21-B24, A23-A24 are flat/three-zone — no OSD preset exists.
    const touGroups = ['c11', 'c12a', 'c12b', 'g12'];
    const g = group.toLowerCase().replace('-', '_');
    if (!touGroups.includes(g)) return null;

    const op = (operator || 'pge').toLowerCase();
    const y = year || new Date().getFullYear();
    return `${op}_${g}_${y}`;
  }

  /**
   * Try to recover analyticalPeriod from localStorage or load_kw length.
   * Fallback for BESS-only flows where user hasn't run full KONFIGURACJA analysis.
   */
  function tryRecoverAnalyticalPeriod(options) {
    // Try localStorage first (set by config-v2.js or consumption module)
    try {
      const stored = localStorage.getItem('consumptionData');
      if (stored) {
        const cd = JSON.parse(stored);
        if (cd.analyticalPeriod) {
          return cd.analyticalPeriod;
        }
        // Reconstruct from stored year + data length
        if (cd.year && cd.dataPoints) {
          const nPoints = cd.dataPoints > 8760 ? 8760 : cd.dataPoints;
          return {
            start_datetime: `${cd.year}-01-01T00:00:00`,
            interval_minutes: 60,
            n_points: nPoints,
            timezone: 'Europe/Warsaw',
            clock_mode: 'CET_FIXED'
          };
        }
      }
    } catch (e) {
      console.warn('⚠️ Failed to recover analyticalPeriod from localStorage:', e);
    }

    // Try pv_data_info from localStorage
    try {
      const dataInfo = localStorage.getItem('pv_data_info');
      if (dataInfo) {
        const info = JSON.parse(dataInfo);
        if (info.year) {
          return {
            start_datetime: `${info.year}-01-01T00:00:00`,
            interval_minutes: 60,
            n_points: info.points || 8760,
            timezone: 'Europe/Warsaw',
            clock_mode: 'CET_FIXED'
          };
        }
      }
    } catch (e) {
      console.warn('⚠️ Failed to recover analyticalPeriod from pv_data_info:', e);
    }

    // Last resort: if load_kw is provided, assume current year
    if (options?.load_kw?.length > 0) {
      const nPoints = Math.min(options.load_kw.length, 8760);
      const year = new Date().getFullYear();
      console.warn(`⚠️ Creating emergency analyticalPeriod from load_kw (${nPoints} points, year=${year})`);
      return {
        start_datetime: `${year}-01-01T00:00:00`,
        interval_minutes: 60,
        n_points: nPoints,
        timezone: 'Europe/Warsaw',
        clock_mode: 'CET_FIXED'
      };
    }

    return null;
  }

  /**
   * Build BESS sizing/dispatch request with consistent parameters.
   *
   * Uses sharedData.analyticalPeriod as the SINGLE SOURCE OF TRUTH for time axis.
   * Uses sharedData.settings (systemSettings) for all configuration.
   *
   * @param {Object} options - Request options
   * @param {Array<number>} options.load_kw - Load profile [kW] (required)
   * @param {Array<number>} [options.pv_generation_kw] - PV profile [kW] (optional)
   * @param {Object} [options.overrides] - Parameter overrides for what-if scenarios
   * @returns {Object} Request body for /sizing or /dispatch API
   * @throws {Error} If analyticalPeriod is not set
   */
  function buildBessRequest(options = {}) {
    // Get sharedData from shell (or parent window if in iframe)
    const sharedData = window.sharedData || (window.parent !== window ? window.parent.sharedData : null);

    if (!sharedData) {
      throw new Error(
        'sharedData not available. Ensure this script runs after shell.js loads. ' +
        'buildBessRequest() requires sharedData to access analyticalPeriod and settings.'
      );
    }

    let analyticalPeriod = sharedData.analyticalPeriod;
    const settings = sharedData.settings || {};

    // Fallback: try to reconstruct analyticalPeriod from localStorage or load_kw data
    if (!analyticalPeriod) {
      analyticalPeriod = tryRecoverAnalyticalPeriod(options);
      if (analyticalPeriod) {
        // Persist recovered analyticalPeriod back to sharedData
        sharedData.analyticalPeriod = analyticalPeriod;
        console.log('📅 AnalyticalPeriod recovered from fallback:', analyticalPeriod);
      }
    }

    // Validate: analyticalPeriod is required
    if (!analyticalPeriod) {
      throw new Error(
        'AnalyticalPeriod not set. Wgraj dane zużycia w KONFIGURACJI (plik CSV/Excel). ' +
        'Dla scenariuszy BESS-only wystarczy sam profil obciążenia — PV nie jest wymagane.'
      );
    }

    // Determine topology and mode from settings
    const topology = determineTopology(settings, options);
    const mode = determineDispatchMode(settings, options, topology);

    // Calculate peak_limit_kw from settings or data
    const peakLimitKw = determinePeakLimit(settings, options);

    // Base request with all required fields
    const request = {
      // ===== TIME AXIS (from analyticalPeriod - SINGLE SOURCE OF TRUTH) =====
      analytical_period: {
        start_datetime: analyticalPeriod.start_datetime,
        interval_minutes: analyticalPeriod.interval_minutes,
        n_points: analyticalPeriod.n_points,
        timezone: analyticalPeriod.timezone || 'Europe/Warsaw',
        clock_mode: analyticalPeriod.clock_mode || 'CET_FIXED'
      },

      // DEPRECATED but kept for backward compatibility with older backends
      start_date: analyticalPeriod.start_datetime.split('T')[0],
      interval_minutes: analyticalPeriod.interval_minutes,

      // ===== TOPOLOGY & MODE =====
      topology: topology,
      mode: mode,

      // ===== PEAK SHAVING =====
      peak_limit_kw: peakLimitKw,
      reserve_fraction: parseFloatSafe(settings.bessReserveFraction, 0.30),

      // ===== SIZING CONSTRAINTS =====
      min_power_kw: parseFloatSafe(settings.bessProMinPowerKw, 20),
      max_power_kw: parseFloatSafe(settings.bessProMaxPowerKw, 10000),
      power_steps: 20,
      durations_h: parseDurations(settings.bessDurations) || [1.0, 2.0, 4.0],

      // ===== BATTERY PARAMS =====
      roundtrip_efficiency: parseFloatSafe(settings.bessRoundtripEfficiency, 0.90),
      soc_min: parseFloatSafe(settings.bessSocMin, 0.10),
      soc_max: parseFloatSafe(settings.bessSocMax, 0.90),

      // ===== EOL SIZING =====
      eol_capacity_factor: parseFloatSafe(settings.bessEolCapacityFactor, 0.70),
      annual_degradation_pct: parseFloatSafe(settings.bessAnnualDegradationPct, 2.0),

      // ===== CAPEX =====
      capex_per_kwh: parseFloatSafe(settings.bessCapexPerKwh, 1500),
      capex_per_kw: parseFloatSafe(settings.bessCapexPerKw, 300),
      opex_pct_per_year: parseFloatSafe(settings.bessOpexPctPerYear, 1.5) / 100,

      // ===== ANALYSIS =====
      discount_rate: parseFloatSafe(settings.discountRate) / 100,
      analysis_years: parseInt(settings.analysisYears || settings.bessLifetimeYears || settings.analysisPeriod, 10),

      // ===== DEGRADATION BUDGET =====
      max_efc_per_year: settings.bessMaxEfcPerYear || null,
      max_throughput_mwh_per_year: settings.bessMaxThroughputMwhPerYear || null,

      // ===== PRICING =====
      prices: buildPricesConfig(settings, analyticalPeriod),

      // ===== DEMAND CHARGE =====
      demand_charge_pln_kw_month: parseFloatSafe(settings.bessPowerChargePlnPerKwMonth, 50),

      // ===== SOLVER (v7.0.0: LP only) =====
      solver: 'lp',

      // ===== MARGINAL CYCLING COST (Wariant B — dispatch friction) =====
      // Without MCC, LP cycles 1500-1800 times/year (5x/day) — physically impossible.
      // For arbitrage (priceArbitrageEnabled), force auto-MCC regardless of user setting.
      // MCC = CAPEX / (2 × cycles_to_eol) ≈ 650/(2×3000) = 108 PLN/MWh.
      // LP only cycles when spread > 2×MCC → realistic EFC 150-400/year.
      marginal_cycle_cost_per_kwh: (() => {
        const mode = settings.bessMarginalCycleCostMode || 'auto';
        // Force auto MCC for any arbitrage scenario (bess_only topology or price arb enabled)
        // MCC=0 causes LP to over-cycle (1800+ EFC/yr). auto = CAPEX/(2×cycles_to_eol) ≈ 108 PLN/MWh.
        const priceArb = settings.bessPriceArbitrageEnabled === true || settings.bessPriceArbitrageEnabled === 'true';
        const arbTopology = settings.bessTopology === 'bess_only' || settings.bessTopology === 'load_only';
        if (mode === 'off' && !priceArb && !arbTopology) return 0.0;
        if (mode === 'manual') return parseFloatSafe(settings.bessMarginalCycleCostManual, 0.125);
        // Auto (default + forced for arbitrage): -1 → backend calculates CAPEX/(2×cycles_to_eol)
        return -1.0;
      })(),
    };

    // ===== OPTIMIZATION OBJECTIVE (from Settings SSoT) =====
    const objective = options.overrides?.objective
      || settings.bessProObjective
      || 'npv';
    const optConfig = { objective: objective, constraints: [] };

    // Max payback constraint
    const maxPayback = parseFloat(settings.bessMaxPaybackYears);
    if (maxPayback > 0) {
      optConfig.constraints.push({
        constraint_type: 'max_payback',
        value: maxPayback,
        hard: false
      });
    }

    request.optimization = optConfig;
    console.log(`🎯 Optimization: objective=${objective}, constraints=${optConfig.constraints.length}`);

    // LP params (v7.0.0)
    request.lp_params = {
      forecast_hours: parseInt(settings.bessLpForecastHours, 10) || 34,
      keep_hours: parseInt(settings.bessLpKeepHours, 10) || 24,
      time_limit_seconds: parseFloatSafe(settings.bessLpTimeLimit, 30.0)
    };

    // Add data arrays
    if (options.load_kw) {
      request.load_kw = options.load_kw;
    }
    if (options.pv_generation_kw) {
      request.pv_generation_kw = options.pv_generation_kw;
    } else if (topology === 'load_only') {
      request.pv_generation_kw = [];  // Empty for load_only
    }

    // Add arbitrage config if either OSD or Price arbitrage is enabled
    const osdArbitrageEnabled = settings.bessOsdArbitrageEnabled === true;
    const priceArbitrageEnabled = settings.bessPriceArbitrageEnabled === true;

    if (osdArbitrageEnabled || priceArbitrageEnabled) {
      request.arbitrage_config = buildArbitrageConfig(settings, osdArbitrageEnabled, priceArbitrageEnabled);
      console.log('💹 Arbitrage config added:', request.arbitrage_config);
    }

    // Apply overrides (for what-if scenarios)
    if (options.overrides) {
      applyOverrides(request, options.overrides);
      console.log('🔬 Request built with overrides (what-if mode):', options.overrides);
    }

    // Log for debugging
    console.log('📋 Built BESS request:', {
      analytical_period: request.analytical_period,
      mode: request.mode,
      topology: request.topology,
      solver: request.solver,
      lp_params: request.lp_params || null,
      peak_limit_kw: request.peak_limit_kw,
      demand_charge: request.demand_charge_pln_kw_month,
      eol_capacity_factor: request.eol_capacity_factor,
      load_points: request.load_kw?.length,
      pv_points: request.pv_generation_kw?.length,
      arbitrage_config: request.arbitrage_config || null
    });

    return request;
  }

  /**
   * Determine topology from settings.
   */
  function determineTopology(settings, options) {
    if (options.topology) return options.topology;

    const settingTopology = settings.bessTopology || settings.topology;

    if (settingTopology === 'bess_only' || settingTopology === 'load_only') {
      return 'load_only';
    }
    return 'pv_load';  // Default: PV + Load + BESS
  }

  /**
   * Determine dispatch mode from settings and topology.
   */
  function determineDispatchMode(settings, options, topology) {
    // Check overrides first (options.overrides.mode from what-if/scenario flows)
    if (options.overrides?.mode) return options.overrides.mode;
    if (options.mode) return options.mode;

    // load_only topology forces load_only mode
    if (topology === 'load_only') {
      return 'load_only';
    }

    // Read baseMode from scenario declaration (SSoT in settings.js)
    const scenarioId = parseInt(settings.bessScenarioId || '0', 10);
    const scenario = window.BESS_SCENARIOS?.[scenarioId];
    if (scenario?.baseMode) {
      return scenario.baseMode;
    }

    // Fallback: check if stacked mode is enabled (peak shaving or arbitrage)
    if (settings.bessStackedMode || settings.bessPeakShavingEnabled ||
        settings.bessOsdArbitrageEnabled || settings.bessPriceArbitrageEnabled) {
      return 'stacked';
    }

    return settings.bessDispatchMode || 'pv_surplus';
  }

  /**
   * Determine peak_limit_kw from settings or calculate from data.
   */
  function determinePeakLimit(settings, options) {
    if (options.overrides?.peak_limit_kw !== undefined) {
      return options.overrides.peak_limit_kw;
    }

    if (settings.bessPeakShavingEnabled && settings.bessPeakShavingTargetKw) {
      return parseFloatSafe(settings.bessPeakShavingTargetKw, null);
    }

    // null means: backend will auto-calculate from data (e.g., P95)
    return null;
  }

  /**
   * Build prices configuration.
   */
  function buildPricesConfig(settings, analyticalPeriod) {
    const analysisYear = parseInt(analyticalPeriod.start_datetime.substring(0, 4), 10);

    return {
      // Tariff: explicit BESS override → mapped from consumption tariff → fallback
      tariff_id: settings.bessOsdTariffGroup ||
                 buildTariffPresetId(settings.tariffGroup, settings.osdOperator,
                   parseInt(analyticalPeriod.start_datetime.substring(0, 4), 10)) ||
                 'pge_c12a_2026',
      pricing_stack_mode: 'OSD_ALL_IN',

      // Energy prices
      import_price_pln_mwh: parseFloatSafe(settings.totalEnergyPrice),
      export_price_pln_mwh: 0,  // ZERO_EXPORT policy

      // Fixed charges
      other_fees_pln_mwh: parseFloatSafe(settings.otherFeesPln, 50),  // OZE + kog + quality + akcyza

      // Demand charge
      annual_demand_charge_pln_kw: parseFloatSafe(settings.bessPowerChargePlnPerKwMonth, 50) * 12,

      // Capacity fee
      capacity_fee_method: 'polish_som',

      // Analysis year (from analytical period, not from settings!)
      analysis_year: analysisYear,

      // ToU enabled flag
      is_tou_enabled: settings.bessOsdTariffGroup ? true : false
    };
  }

  /**
   * Build arbitrage configuration from settings flags.
   *
   * Supports two arbitrage modes:
   * 1. OSD Tariff Arbitrage (ToU) - based on time zones (C12a, C22a, etc.)
   * 2. RDN Price Arbitrage (Spot) - based on price thresholds
   *
   * @param {Object} settings - System settings
   * @param {boolean} osdEnabled - OSD tariff arbitrage enabled
   * @param {boolean} priceEnabled - RDN price arbitrage enabled
   * @returns {Object} ArbitrageConfig for sizing request
   */
  function buildArbitrageConfig(settings, osdEnabled, priceEnabled) {
    const config = {
      enabled: true
    };

    // OSD Tariff Arbitrage (ToU zones)
    if (osdEnabled) {
      config.tariff_id = settings.bessOsdTariffGroup ||
        buildTariffPresetId(settings.tariffGroup, settings.osdOperator) ||
        'pge_c12a_2026';
      config.strategy = 'zone_based';  // Use OSD zone hours
      config.osd_operator = settings.bessOsdOperator || 'pge';
      config.peak_rate_pln_kwh = parseFloatSafe(settings.bessOsdPeakRate, 0.75);
      config.offpeak_rate_pln_kwh = parseFloatSafe(settings.bessOsdOffPeakRate, 0.45);
      config.min_spread_pln_kwh = parseFloatSafe(settings.bessOsdMinSpread, 0.15);
    }

    // RDN Price Arbitrage (Spot market)
    if (priceEnabled) {
      config.price_arbitrage_enabled = true;
      config.price_source = settings.bessPriceArbitrageSource || 'manual';
      config.buy_threshold_pln_mwh = parseFloatSafe(settings.bessPriceArbitrageBuyThreshold, 300);
      config.sell_threshold_pln_mwh = parseFloatSafe(settings.bessPriceArbitrageSellThreshold, 600);
      config.min_spread_pln_mwh = parseFloatSafe(settings.bessPriceArbitrageSpread, 100);

      // RDN hourly prices for LP:
      // SOURCE 1 (preferred): price_config.js all-in array from sharedData (already computed: RDN + distribution + fees)
      // SOURCE 2 (fallback): raw RDN from localStorage (both buy=sell → spread=0, time-shift only)
      // Zero-export (LOAD_ONLY/bess_only): sell = buy (time-shift semantics: saving = avoided purchase)
      // Export-enabled: sell = raw RDN, buy = all-in → spread = distribution + fees
      try {
        const topology = settings.bessTopology || 'pv_bess';
        const isZeroExport = (topology === 'bess_only' || topology === 'load_only');

        // SOURCE 1: price_config.js already computed all-in prices (avg≈676 PLN/MWh)
        const pcArb = (typeof window !== 'undefined' ? window : {})?.sharedData?.priceConfig?.arbitrageConfig;
        const allInFromPriceConfig = pcArb?.hourly_prices_pln_mwh;
        const rawFromPriceConfig = pcArb?.hourly_export_prices_pln_mwh;

        if (Array.isArray(allInFromPriceConfig) && allInFromPriceConfig.length >= 8760) {
          const buyPrices = allInFromPriceConfig.slice(0, 8760);
          const sellPrices = isZeroExport
            ? buyPrices                                                   // time-shift: sell = buy
            : (Array.isArray(rawFromPriceConfig) && rawFromPriceConfig.length >= 8760
                ? rawFromPriceConfig.slice(0, 8760)
                : buyPrices);
          config.hourly_prices_pln_mwh = buyPrices;
          config.hourly_export_prices_pln_mwh = sellPrices;
          const buyAvg = (buyPrices.reduce((s, v) => s + v, 0) / 8760).toFixed(0);
          const sellAvg = (sellPrices.reduce((s, v) => s + v, 0) / 8760).toFixed(0);
          console.log(`💹 RDN prices (from price_config): buy avg=${buyAvg} PLN/MWh, sell avg=${sellAvg} PLN/MWh (${isZeroExport ? 'time-shift' : 'export-enabled'})`);
        } else {
          // SOURCE 2: fallback — raw RDN from localStorage, buy=sell=raw (spread=0)
          const raw = localStorage.getItem('rdn_hourly_prices');
          if (raw) {
            const arr = JSON.parse(raw);
            if (Array.isArray(arr) && arr.length >= 8760) {
              const rdnSlice = arr.slice(0, 8760);
              config.hourly_prices_pln_mwh = rdnSlice;
              config.hourly_export_prices_pln_mwh = rdnSlice;
              const rdnAvg = (rdnSlice.reduce((s, v) => s + v, 0) / 8760).toFixed(0);
              console.warn(`⚠️ RDN prices fallback (no price_config): buy=sell=raw RDN avg=${rdnAvg} PLN/MWh, spread=0`);
            }
          } else {
            console.warn('⚠️ RDN arbitrage enabled but no price data available');
          }
        }
      } catch (e) {
        console.warn('⚠️ Failed to attach RDN prices:', e);
      }

      // If both enabled, prefer percentile strategy with RDN prices
      if (!osdEnabled) {
        config.strategy = 'percentile';
        config.charge_below_percentile = 25;  // Buy cheap (bottom 25%)
        config.discharge_above_percentile = 75;  // Sell expensive (top 25%)
      }
    }

    // Common arbitrage parameters
    config.arbitrage_soc_min = parseFloatSafe(settings.bessArbitrageSocMin, 0.20);
    config.degradation_cost_pln_kwh = parseFloatSafe(settings.bessArbitrageDegradationCost, 0.05);

    // Grid charging control: read from scenario declaration (SSoT in settings.js)
    const scenarioId = parseInt(settings.bessScenarioId || '0', 10);
    const scenario = window.BESS_SCENARIOS?.[scenarioId];
    config.allow_grid_charging = scenario?.gridCharging !== false;  // default: true

    return config;
  }

  /**
   * Apply overrides to request (deep merge).
   */
  function applyOverrides(request, overrides) {
    for (const [key, value] of Object.entries(overrides)) {
      if (key === 'prices' && typeof value === 'object') {
        request.prices = { ...request.prices, ...value };
      } else if (key === 'analytical_period' && typeof value === 'object') {
        request.analytical_period = { ...request.analytical_period, ...value };
      } else if (key === 'arbitrage_config' && typeof value === 'object') {
        request.arbitrage_config = { ...(request.arbitrage_config || {}), ...value };
      } else {
        request[key] = value;
      }
    }
  }

  /**
   * Validate request before sending.
   * @param {Object} request - Built request object
   * @returns {Object} { valid: boolean, errors: string[], warnings: string[] }
   */
  function validateBessRequest(request) {
    const errors = [];
    const warnings = [];

    // Required fields
    if (!request.analytical_period?.start_datetime) {
      errors.push('Missing analytical_period.start_datetime');
    }
    if (!request.load_kw || request.load_kw.length === 0) {
      errors.push('Missing or empty load_kw array');
    }

    // Consistency checks
    if (request.load_kw && request.analytical_period) {
      if (request.load_kw.length !== request.analytical_period.n_points) {
        warnings.push(
          `load_kw length (${request.load_kw.length}) != analytical_period.n_points (${request.analytical_period.n_points})`
        );
      }
    }

    // PV data consistency
    if (request.pv_generation_kw && request.pv_generation_kw.length > 0) {
      if (request.topology === 'load_only') {
        warnings.push('pv_generation_kw provided but topology is load_only - PV data will be ignored');
      }
      if (request.pv_generation_kw.length !== request.load_kw?.length) {
        warnings.push(
          `pv_generation_kw length (${request.pv_generation_kw.length}) != load_kw length (${request.load_kw?.length})`
        );
      }
    }

    // Mode-specific checks
    if (request.mode === 'stacked' && !request.peak_limit_kw) {
      warnings.push('STACKED mode without peak_limit_kw - backend will auto-calculate from P95');
    }

    // Economic sanity checks
    if (request.capex_per_kwh > 3000) {
      warnings.push(`High CAPEX: ${request.capex_per_kwh} PLN/kWh - verify this is correct`);
    }
    if (request.discount_rate > 0.20) {
      warnings.push(`High discount rate: ${(request.discount_rate * 100).toFixed(1)}% - verify this is correct`);
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings
    };
  }

  // ===== HELPER FUNCTIONS =====

  /**
   * Parse float with fallback.
   */
  function parseFloatSafe(value, fallback) {
    if (value === null || value === undefined || value === '') {
      return fallback;
    }
    const parsed = parseFloat(value);
    return isNaN(parsed) ? fallback : parsed;
  }

  /**
   * Parse durations from settings (string "1,2,4" or array).
   */
  function parseDurations(value) {
    if (!value) return null;
    if (Array.isArray(value)) return value;
    if (typeof value === 'string') {
      return value.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    }
    return null;
  }

  // ===== DRIVER/PROFILE SUPPORT (v4.5.0) =====

  /**
   * Available optimization profiles (v4.5.0).
   */
  const OPTIMIZATION_PROFILES = {
    balanced: {
      objective: 'npv',
      description: 'NPV optimization with self-consumption tie-breaker',
      policy: { near_optimal_tolerance_pct: 5.0, tie_breakers: ['self_consumption_rate', 'duration_h'] }
    },
    pv_self_consumption: {
      objective: 'self_consumption',
      description: 'Maximize PV self-consumption',
      policy: { near_optimal_tolerance_pct: 10.0, tie_breakers: ['npv_pln', 'duration_h'] }
    },
    commercial_peak_shaving: {
      objective: 'peak_reduction',
      description: 'Maximize peak reduction for demand charge savings',
      policy: { near_optimal_tolerance_pct: 5.0, tie_breakers: ['npv_pln', 'capex_pln'] }
    },
    arbitrage: {
      objective: 'npv',
      description: 'NPV optimization for arbitrage',
      policy: { near_optimal_tolerance_pct: 3.0, tie_breakers: ['irr_pct', 'payback_years'] }
    },
    resilience_backup: {
      objective: 'resilience',
      description: 'Maximize backup capability',
      policy: { near_optimal_tolerance_pct: 15.0, tie_breakers: ['duration_h', 'npv_pln'] }
    }
  };

  /**
   * Available optimization objectives (v4.5.0).
   */
  const OPTIMIZATION_OBJECTIVES = [
    { value: 'npv', label: 'NPV (Net Present Value)', direction: 'maximize' },
    { value: 'irr', label: 'IRR (Internal Rate of Return)', direction: 'maximize' },
    { value: 'payback', label: 'Payback Period', direction: 'minimize' },
    { value: 'self_consumption', label: 'Self-Consumption Rate', direction: 'maximize' },
    { value: 'peak_reduction', label: 'Peak Reduction', direction: 'maximize' },
    { value: 'lcos', label: 'LCOS (Levelized Cost of Storage)', direction: 'minimize' },
    { value: 'resilience', label: 'Resilience (Backup)', direction: 'maximize' }
  ];

  /**
   * Add driver/profile configuration to request (v4.5.0).
   *
   * @param {Object} request - Base request object
   * @param {Object} options - Driver options
   * @param {string} [options.profile] - Profile name (balanced, pv_self_consumption, etc.)
   * @param {string} [options.objective] - Override objective (npv, lcos, etc.)
   * @param {Object} [options.recommendation_policy] - Custom recommendation policy
   * @param {Object} [options.variant_space] - Custom variant space
   * @returns {Object} Request with driver configuration
   */
  function addDriverConfig(request, options = {}) {
    const driverConfig = {};

    // Profile-based configuration
    if (options.profile && OPTIMIZATION_PROFILES[options.profile]) {
      const profile = OPTIMIZATION_PROFILES[options.profile];
      driverConfig.optimization = { objective: profile.objective };
      driverConfig.recommendation_policy = profile.policy;
      console.log(`🎯 Applied profile: ${options.profile} (objective: ${profile.objective})`);
    }

    // Objective override (from options, then settings, then localStorage)
    const objectiveSource = options.objective
      || options.overrides?.objective
      || settings.bessProObjective
      || localStorage.getItem('bessObjective')
      || null;
    if (objectiveSource) {
      driverConfig.optimization = { objective: objectiveSource, constraints: [] };
      console.log(`🎯 Objective: ${objectiveSource}`);
    }

    // Max payback constraint from settings
    const maxPayback = parseFloat(settings.bessMaxPaybackYears);
    if (maxPayback > 0) {
      if (!driverConfig.optimization) {
        driverConfig.optimization = { objective: 'npv', constraints: [] };
      }
      if (!driverConfig.optimization.constraints) {
        driverConfig.optimization.constraints = [];
      }
      driverConfig.optimization.constraints.push({
        constraint_type: 'max_payback',
        value: maxPayback,
        hard: false
      });
      console.log(`🎯 Max payback constraint: ${maxPayback} lat`);
    }

    // Custom policy override
    if (options.recommendation_policy) {
      driverConfig.recommendation_policy = {
        ...(driverConfig.recommendation_policy || {}),
        ...options.recommendation_policy
      };
    }

    // Variant space configuration
    if (options.variant_space) {
      driverConfig.variant_space = options.variant_space;
    }

    // Include duration sweep flag
    if (options.include_duration_sweep !== undefined) {
      driverConfig.include_duration_sweep = options.include_duration_sweep;
    }

    return { ...request, ...driverConfig };
  }

  /**
   * Get available profiles.
   */
  function getAvailableProfiles() {
    return Object.entries(OPTIMIZATION_PROFILES).map(([key, val]) => ({
      value: key,
      label: val.description,
      objective: val.objective
    }));
  }

  /**
   * Get available objectives.
   */
  function getAvailableObjectives() {
    return OPTIMIZATION_OBJECTIVES;
  }

  // ===== EXPORT TO WINDOW =====

  window.buildBessRequest = buildBessRequest;
  window.buildTariffPresetId = buildTariffPresetId;
  window.validateBessRequest = validateBessRequest;
  window.addDriverConfig = addDriverConfig;
  window.getAvailableProfiles = getAvailableProfiles;
  window.getAvailableObjectives = getAvailableObjectives;
  window.OPTIMIZATION_PROFILES = OPTIMIZATION_PROFILES;
  window.OPTIMIZATION_OBJECTIVES = OPTIMIZATION_OBJECTIVES;

  console.log('✅ BESS Request Builder loaded (v1.1.0 - drivers support)');

})();
