console.log('🚀 economics.js LOADED v=20260314-PLNTOTYPLN - timestamp:', new Date().toISOString());

// DEBUG flag - set to true for verbose logging (or via URL ?debug_economics=1)
const DEBUG_ECONOMICS = window.location?.search?.includes('debug_economics=1') || false;

// ============================================================================
// UNIT CONVERSION HELPERS — użyj zamiast ręcznego /1000, *1000
// ============================================================================
const kwhToMwh = kwh => kwh / 1000;
const mwhToKwh = mwh => mwh * 1000;
const plnToTysPln = pln => pln / 1000;
const plnToMlnPln = pln => pln / 1000000;
const pctToDecimal = pct => pct / 100;
const decimalToPct = dec => dec * 100;

// Production mode - use nginx reverse proxy routes
const USE_PROXY = true;

// Backend API URLs
const API_URLS = USE_PROXY ? {
  dataAnalysis: '/api/data',
  economics: '/api/economics'
} : {
  dataAnalysis: 'http://localhost:8001',
  economics: 'http://localhost:8003'
};

// ============================================
// NUMBER FORMATTING - European format (global)
// ============================================

/**
 * Format number in European style
 * - Decimal separator: comma (,)
 * - Thousands separator: non-breaking space (\u00A0)
 * @param {number} value - Number to format
 * @param {number} decimals - Number of decimal places (default: 2)
 * @returns {string} Formatted number string
 */
function formatNumberEU(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }

  // Round to specified decimals
  const fixed = Number(value).toFixed(decimals);

  // Split into integer and decimal parts
  const parts = fixed.split('.');
  let integerPart = parts[0];
  const decimalPart = parts[1];

  // Add thousands separator (non-breaking space)
  integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00A0');

  // Join with comma as decimal separator
  if (decimals > 0 && decimalPart) {
    return integerPart + ',' + decimalPart;
  }
  return integerPart;
}

/**
 * Format number with unit
 * @param {number} value - Number to format
 * @param {string} unit - Unit string
 * @param {number} decimals - Number of decimal places
 * @returns {string} Formatted number with unit
 */
function formatWithUnitEU(value, unit, decimals = 2) {
  return `${formatNumberEU(value, decimals)} ${unit}`;
}

// Expose globally
window.formatNumberEU = formatNumberEU;
window.formatWithUnitEU = formatWithUnitEU;

// Chart.js instances
let capexChart, opexChart, cashFlowChart, revenueChart, sensitivityChart;
let sensitivityEnergyChart, sensitivityDiscountChart;
let variantScanChart = null;
// PULS DNIA charts
let pulsDniaProductionChart = null;
let pulsDniaGridChart = null;
let pulsDniaBessChart = null;
let pulsDniaCostsChart = null;

// Data storage
let economicData = null;
let pvConfig = null;
let analysisResults = null;
let variants = {};
let currentVariant = 'A'; // Default variant
let consumptionData = null;
let productionData = null; // Hourly PV production data from backend
let systemSettings = null; // Settings from Settings module
let hourlyData = null; // Hourly consumption/production data
// BESS data now comes exclusively from analysisResults (pv-calculation)
// to enforce a Single Source of Truth.
let currentBessSource = 'pv-calculation'; // SSoT: always use pv-calculation
let profileAnalysisBessData = null; // Legacy - kept for compatibility but not used in SSoT mode
let bessSizingData = null; // BESS sizing data from shell/bess-dispatch
let breakevenMode = 'npv'; // 'npv' (Max NPV) or 'payback' (Min Payback) - for variant scan table

// CENTRALIZED FINANCIAL METRICS STORAGE
// This is the SINGLE SOURCE OF TRUTH for all NPV calculations
// All UI sections should read from this object
let centralizedMetrics = {};
let centralizedMetricsRdn = {};

// PRECISE ANNUAL SAVINGS from backend (hourly K-class methodology, same as Excel)
// Populated by fetchPreciseAnnualSavings(), consumed by calculateCentralizedFinancialMetrics()
let preciseAnnualSavings = null; // { year1_savings, baseline, project, energy, effective_price_pln_mwh, monthly }
let preciseAnnualSavingsCache = {}; // Per-variant cache: { 'A': data, 'B': data, ... }
window.preciseAnnualSavings = preciseAnnualSavings;
// Expose to window for cross-file access (capex-export.js)
window.centralizedMetricsRdn = centralizedMetricsRdn;

// EaaS yearly data for Bankability calculations
let eaasYearlyData = [];

// Export key variables to window for cross-module access (e.g., bankability.js)
// These are updated throughout the module lifecycle
window.variants = variants;
window.centralizedMetrics = centralizedMetrics;
window.currentVariant = currentVariant;
window.eaasYearlyData = eaasYearlyData;

// Initialize window.economicsSettings — values are null until real settings arrive via SHARED_DATA_RESPONSE.
// Any calculation reading null means settings haven't loaded yet (bug in call order, not a fallback case).
window.economicsSettings = {
  discountRate: null,
  insuranceRate: null,
  inflationRate: null,
  eaasIndexation: null,
  useInflation: false,
  irrMode: null,

  // === P0-1: BESS Replacement Parameters ===
  bessLifetimeYears: 15,
  bessReplacementEnabled: true, // Enable/disable BESS replacement
  bessReplacementMode: 'percent_of_initial', // 'percent_of_initial' | 'per_kwh'
  bessReplacementCostValue: 0.7, // 70% of initial CAPEX or PLN/kWh depending on mode
  bessReplacementFraction: 1.0, // Fraction of original capacity to replace (1.0 = 100%)

  // === P0-1: Inverter Replacement Parameters (optional) ===
  inverterLifetimeYears: 12,
  inverterReplacementEnabled: false, // Disabled by default
  inverterReplacementCostPercent: 0.15, // 15% of PV CAPEX

  // === P0-2: Residual Value Parameters ===
  residualValueMode: 'zero', // 'contractual' | 'fmv' | 'zero'
  residualValueFmvPercent: 0.20, // 20% of CAPEX for FMV mode
  residualValueContractualPerKwp: 1, // PLN per kWp for contractual (token buyout)
  residualValueYearMode: 'end_of_analysis', // 'end_of_analysis' | 'end_of_contract'

  // === P0-3: Nominal vs Real Rate Mode ===
  rateMode: 'nominal' // 'nominal' | 'real' - determines how discount_rate is interpreted
};

// Production scenario selector for P50/P75/P90
window.currentProductionScenario = 'P50';
window.currentScenarioFactor = 1.0;

// P-factor values — initialized from settings in applySettingsToUI()
window.productionFactors = {
  P50: 1.00,
  P75: 0.97,
  P90: 0.94
};

// ============================================
// P0-1: BESS REPLACEMENT CALCULATION
// ============================================

/**
 * Calculate BESS replacement schedule for the analysis period.
 * Returns array of { year, cost } objects for each replacement event.
 *
 * @param {number} initialBessCapex - Initial BESS CAPEX in PLN
 * @param {number} bessEnergyKwh - BESS energy capacity in kWh
 * @param {number} analysisPeriod - Analysis period in years
 * @param {Object} settings - economicsSettings object
 * @returns {Array<{year: number, cost: number}>} - Replacement schedule
 */
function calculateBessReplacementSchedule(initialBessCapex, bessEnergyKwh, analysisPeriod, settings = {}) {
  const bessLifetime = settings.bessLifetimeYears ?? window.economicsSettings?.bessLifetimeYears;
  const replacementMode = settings.bessReplacementMode ?? window.economicsSettings?.bessReplacementMode ?? 'percent_of_initial';
  const replacementCostValue = settings.bessReplacementCostValue ?? window.economicsSettings?.bessReplacementCostValue ?? 0.7;
  const replacementFraction = settings.bessReplacementFraction ?? window.economicsSettings?.bessReplacementFraction ?? 1.0;

  const schedule = [];

  if (initialBessCapex <= 0 || bessLifetime <= 0) {
    return schedule;
  }

  // Calculate replacement years
  let year = bessLifetime;
  while (year < analysisPeriod) {
    let replacementCost = 0;

    if (replacementMode === 'percent_of_initial') {
      // Cost as percentage of initial CAPEX (e.g., 0.7 = 70%)
      replacementCost = initialBessCapex * replacementCostValue * replacementFraction;
    } else if (replacementMode === 'per_kwh') {
      // Cost as PLN per kWh
      replacementCost = bessEnergyKwh * replacementCostValue * replacementFraction;
    }

    if (replacementCost > 0) {
      schedule.push({
        year: year,
        cost: replacementCost,
        description: `BESS Replacement #${schedule.length + 1}`
      });
    }

    year += bessLifetime;
  }

  if (DEBUG_ECONOMICS && schedule.length > 0) {
    console.log('🔋 BESS Replacement Schedule:', schedule);
  }

  return schedule;
}

/**
 * Calculate inverter replacement schedule for the analysis period.
 * Inverter typically lasts 10-15 years and costs ~10-15% of PV CAPEX to replace.
 *
 * @param {number} pvCapex - Initial PV CAPEX in PLN
 * @param {number} analysisPeriod - Analysis period in years
 * @param {Object} settings - economicsSettings object
 * @returns {Array<{year: number, cost: number, description: string}>} - Replacement schedule
 */
function calculateInverterReplacementSchedule(pvCapex, analysisPeriod, settings = {}) {
  const enabled = settings.inverterReplacementEnabled ?? window.economicsSettings?.inverterReplacementEnabled ?? false;
  const inverterLifetime = settings.inverterLifetimeYears ?? window.economicsSettings?.inverterLifetimeYears ?? 12;
  const replacementCostPercent = settings.inverterReplacementCostPercent ?? window.economicsSettings?.inverterReplacementCostPercent ?? 0.15;

  const schedule = [];

  if (!enabled || pvCapex <= 0 || inverterLifetime <= 0) {
    return schedule;
  }

  // Calculate replacement years
  let year = inverterLifetime;
  while (year < analysisPeriod) {
    const replacementCost = pvCapex * replacementCostPercent;

    if (replacementCost > 0) {
      schedule.push({
        year: year,
        cost: replacementCost,
        description: `Inverter Replacement #${schedule.length + 1}`
      });
    }

    year += inverterLifetime;
  }

  if (DEBUG_ECONOMICS && schedule.length > 0) {
    console.log('⚡ Inverter Replacement Schedule:', schedule);
  }

  return schedule;
}

/**
 * Calculate combined reinvestment schedule (BESS + Inverter).
 * Returns year -> total reinvestment cost mapping for easy lookup.
 *
 * @param {number} bessCapex - Initial BESS CAPEX
 * @param {number} bessEnergyKwh - BESS energy capacity
 * @param {number} pvCapex - Initial PV CAPEX
 * @param {number} analysisPeriod - Analysis period in years
 * @param {Object} settings - economicsSettings object
 * @returns {{schedule: Object, bessSchedule: Array, inverterSchedule: Array, totalCost: number}}
 */
function calculateReinvestmentSchedule(bessCapex, bessEnergyKwh, pvCapex, analysisPeriod, settings = {}) {
  const bessEnabled = settings.bessReplacementEnabled ?? window.economicsSettings?.bessReplacementEnabled ?? true;

  // BESS replacement schedule
  const bessSchedule = bessEnabled && bessCapex > 0
    ? calculateBessReplacementSchedule(bessCapex, bessEnergyKwh, analysisPeriod, settings)
    : [];

  // Inverter replacement schedule
  const inverterSchedule = calculateInverterReplacementSchedule(pvCapex, analysisPeriod, settings);

  // Combine into year -> cost dictionary
  const schedule = {};
  let totalCost = 0;

  bessSchedule.forEach(item => {
    schedule[item.year] = (schedule[item.year] || 0) + item.cost;
    totalCost += item.cost;
  });

  inverterSchedule.forEach(item => {
    schedule[item.year] = (schedule[item.year] || 0) + item.cost;
    totalCost += item.cost;
  });

  return {
    schedule,           // { year: totalCost } for quick lookup
    bessSchedule,       // Array of BESS replacements
    inverterSchedule,   // Array of inverter replacements
    totalCost           // Sum of all reinvestment costs
  };
}

// ============================================
// P0-2: RESIDUAL VALUE CALCULATION
// ============================================

/**
 * Calculate residual/terminal value at end of analysis period or contract.
 *
 * Modes:
 * - 'zero': No residual value
 * - 'contractual': Token buyout (e.g., 1 PLN/kWp) - for EaaS
 * - 'fmv': Fair Market Value as % of CAPEX
 *
 * YearMode:
 * - 'end_of_analysis': Apply residual value in last year of analysis period
 * - 'end_of_contract': Apply residual value at end of EaaS contract (eaasDuration)
 *
 * @param {number} totalCapex - Total initial CAPEX (PV + BESS)
 * @param {number} capacityKwp - PV capacity in kWp
 * @param {number} analysisPeriod - Analysis period in years
 * @param {Object} settings - economicsSettings object
 * @param {number} [eaasDuration] - EaaS contract duration (for end_of_contract mode)
 * @returns {{year: number, value: number, mode: string, yearMode: string, description: string}}
 */
function calculateResidualValue(totalCapex, capacityKwp, analysisPeriod, settings = {}, eaasDuration = null) {
  const mode = settings.residualValueMode ?? window.economicsSettings?.residualValueMode ?? 'zero';
  const fmvPercent = settings.residualValueFmvPercent ?? window.economicsSettings?.residualValueFmvPercent ?? 0.20;
  const contractualPerKwp = settings.residualValueContractualPerKwp ?? window.economicsSettings?.residualValueContractualPerKwp ?? 1;
  const yearMode = settings.residualValueYearMode ?? window.economicsSettings?.residualValueYearMode ?? 'end_of_analysis';

  // Determine residual year based on yearMode
  let residualYear = analysisPeriod;
  if (yearMode === 'end_of_contract' && eaasDuration && eaasDuration > 0) {
    residualYear = Math.min(eaasDuration, analysisPeriod);
  }

  let value = 0;
  let description = '';

  switch (mode) {
    case 'zero':
      value = 0;
      description = 'No residual value';
      break;

    case 'contractual':
      // Token buyout - typically used in EaaS/PPA
      value = capacityKwp * contractualPerKwp;
      description = `Contractual buyout: ${contractualPerKwp} PLN/kWp`;
      break;

    case 'fmv':
      // Fair Market Value as percentage of initial CAPEX
      // Note: Could be adjusted for depreciation, but simplified here
      value = totalCapex * fmvPercent;
      description = `FMV: ${decimalToPct(fmvPercent).toFixed(0)}% of initial CAPEX`;
      break;

    default:
      value = 0;
      description = 'Unknown mode - defaulting to zero';
  }

  if (DEBUG_ECONOMICS && value > 0) {
    console.log(`📈 Residual Value (${mode}, ${yearMode}): ${formatNumberEU(value, 0)} PLN in year ${residualYear}`);
  }

  return {
    year: residualYear,
    value: value,
    mode: mode,
    yearMode: yearMode,
    description: description
  };
}

// ============================================
// P0-3: NOMINAL VS REAL RATE CONVERSION
// ============================================

/**
 * Get effective discount rate based on rate mode.
 *
 * If rateMode='real' and inflation is specified, convert to nominal:
 *   r_nominal = (1 + r_real) * (1 + inflation) - 1
 *
 * If rateMode='nominal', use discount rate directly.
 *
 * P0-3 GUARDRAILS:
 * - If rate_mode='real' and inflation_rate is NaN/undefined → fallback to nominal with warning
 * - Validates inputs are numeric
 *
 * @param {Object} settings - economicsSettings object
 * @returns {{effectiveRate: number, mode: string, isConverted: boolean, inflationRate: number, warning: string|null, inputRate: number}}
 */
function getEffectiveDiscountRate(settings = {}) {
  const rateMode = settings.rateMode ?? window.economicsSettings?.rateMode ?? 'nominal';
  let discountRate = settings.discountRate ?? window.economicsSettings?.discountRate;
  let inflationRate = settings.inflationRate ?? window.economicsSettings?.inflationRate;
  const useInflation = settings.useInflation ?? window.economicsSettings?.useInflation ?? false;

  // P0-3 GUARDRAIL: Ensure numeric values
  discountRate = parseFloat(discountRate);
  inflationRate = parseFloat(inflationRate);

  if (isNaN(discountRate)) {
    console.error('❌ getEffectiveDiscountRate: discountRate is NaN — settings not loaded?');
    return { effectiveRate: NaN, mode: 'error', isConverted: false, inflationRate: NaN, warning: 'discountRate is NaN', inputRate: NaN };
  }

  let effectiveRate = discountRate;
  let isConverted = false;
  let warning = null;

  // P0-3 GUARDRAIL: Handle real mode with missing/invalid inflation
  if (rateMode === 'real') {
    if (isNaN(inflationRate) || inflationRate === null || inflationRate === undefined) {
      // Fallback to nominal mode with warning
      warning = 'Rate mode is "real" but inflation_rate is missing/NaN. Using nominal rate as fallback.';
      console.warn('⚠️', warning);
      // Keep effectiveRate = discountRate (nominal fallback)
    } else if (inflationRate > 0) {
      // Convert real rate to nominal: r_nom = (1+r_real)*(1+infl) - 1
      effectiveRate = (1 + discountRate) * (1 + inflationRate) - 1;
      isConverted = true;

      if (DEBUG_ECONOMICS) {
        console.log(`📊 Rate conversion: ${decimalToPct(discountRate).toFixed(2)}% real → ${decimalToPct(effectiveRate).toFixed(2)}% nominal (inflation: ${decimalToPct(inflationRate).toFixed(1)}%)`);
      }
    }
    // If inflation = 0, real = nominal, no conversion needed
  }

  // Additional warning detection
  if (useInflation && rateMode === 'real' && !warning) {
    // User has inflation enabled but is using real rate - might be inconsistent
    warning = 'Cash flows include inflation but discount rate is in real terms. Results may be inconsistent.';
  }

  // P0-3 GUARDRAIL: Final NaN check
  if (isNaN(effectiveRate) || !isFinite(effectiveRate)) {
    console.warn('⚠️ getEffectiveDiscountRate: effectiveRate is NaN/Infinity, using default 0.10');
    effectiveRate = 0.10;
    warning = (warning || '') + ' effectiveRate computed as NaN, using fallback.';
  }

  return {
    effectiveRate: effectiveRate,
    mode: rateMode,
    isConverted: isConverted,
    inflationRate: inflationRate,
    warning: warning,
    inputRate: discountRate  // Original input rate for reference
  };
}

/**
 * Convert nominal rate to real rate (inverse of above)
 * r_real = (1 + r_nominal) / (1 + inflation) - 1
 *
 * @param {number} nominalRate - Nominal discount rate
 * @param {number} inflationRate - Inflation rate
 * @returns {number} - Real discount rate
 */
function nominalToRealRate(nominalRate, inflationRate) {
  if (inflationRate <= -1) return nominalRate; // Guard against invalid inflation
  return (1 + nominalRate) / (1 + inflationRate) - 1;
}

/**
 * Convert real rate to nominal rate
 * r_nominal = (1 + r_real) * (1 + inflation) - 1
 *
 * @param {number} realRate - Real discount rate
 * @param {number} inflationRate - Inflation rate
 * @returns {number} - Nominal discount rate
 */
function realToNominalRate(realRate, inflationRate) {
  return (1 + realRate) * (1 + inflationRate) - 1;
}

// ============================================
// BESS SOURCE MANAGEMENT FUNCTIONS
// ============================================

/**
 * Update BESS source selector UI (no-op in SSoT mode - selector removed)
 * Kept for backward compatibility with message handlers.
 */
function updateBessSourceSelector() {
  // SSoT: Selector UI has been removed. BESS data comes only from pv-calculation.
  // This function is a no-op but kept for backward compatibility.
  console.log('📊 updateBessSourceSelector: SSoT mode - selector disabled');
}

/**
 * Apply BESS source data to current variant
 * Copies dispatch_metadata, savings_breakdown, and prices_summary from bessSizingData to variant.
 */
function applyBessSourceToVariant() {
  const variant = variants[currentVariant];
  if (!variant) {
    console.log('⚠️ applyBessSourceToVariant: No current variant to update');
    return;
  }

  if (!bessSizingData) {
    console.log('⚠️ applyBessSourceToVariant: No bessSizingData available');
    return;
  }

  console.log('🔋 Applying BESS source data to variant:', currentVariant);

  // Copy savings_breakdown if available
  if (bessSizingData.savings_breakdown) {
    variant.savings_breakdown = bessSizingData.savings_breakdown;
    console.log('  ✓ Copied savings_breakdown:', variant.savings_breakdown);
  }

  // Copy dispatch_metadata if available
  if (bessSizingData.dispatch_metadata) {
    variant.dispatch_metadata = bessSizingData.dispatch_metadata;
    console.log('  ✓ Copied dispatch_metadata:', variant.dispatch_metadata);
  }

  // Build prices_summary from bessSizingData or systemSettings
  if (bessSizingData.prices_summary) {
    variant.prices_summary = bessSizingData.prices_summary;
  } else {
    // Build from available data
    const settings = systemSettings || {};
    variant.prices_summary = {
      import_price_pln_mwh: window.economicsSettings?.totalEnergyPrice || settings.totalEnergyPrice || settings.energyPrice,
      demand_charge_pln_kw_month: settings.bessPowerChargePlnPerKwMonth || 50,
      tariff_id: settings.tariffGroup || settings.bessOsdTariffGroup || 'C12a'
    };
  }
  console.log('  ✓ Set prices_summary:', variant.prices_summary);

  // Update BESS power/energy on variant if not already set
  if (bessSizingData.bess_power_kw && !variant.bess_power_kw) {
    variant.bess_power_kw = bessSizingData.bess_power_kw;
    variant.bess_energy_kwh = bessSizingData.bess_energy_kwh;
    console.log('  ✓ Set BESS power/energy:', variant.bess_power_kw, 'kW /', variant.bess_energy_kwh, 'kWh');
  }
}

/**
 * Generate local savings_breakdown when BESS data is present but savings_breakdown is missing.
 * This is needed when BESS source is 'pv-calculation' and no BESS dispatch API was called.
 *
 * The estimation is based on:
 * - Energy savings: BESS self-consumed energy × energy price
 * - Peak shaving: Estimated from BESS power capacity (simplified)
 * - Arbitrage: Estimated ToU premium (if applicable)
 *
 * @param {object} variant - Current variant with BESS data
 * @returns {object|null} - Generated savings_breakdown or null if no BESS
 */
function generateLocalSavingsBreakdown(variant) {
  if (!variant) return null;

  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  if (!hasBess) {
    console.log('📊 generateLocalSavingsBreakdown: No BESS configured');
    return null;
  }

  console.log('📊 Generating LOCAL savings_breakdown for BESS:', variant.bess_power_kw, 'kW /', variant.bess_energy_kwh, 'kWh');

  const settings = systemSettings || {};

  // Get energy price [PLN/MWh]
  const energyPricePLNperMWh = window.economicsSettings?.totalEnergyPrice || settings.totalEnergyPrice || settings.energyPrice;

  // Get BESS energy discharged/self-consumed [kWh/year]
  // Priority: bess_self_consumed_from_bess_kwh > bess_discharged_kwh > estimate from cycles
  let bessDischargedKwh = variant.bess_self_consumed_from_bess_kwh || variant.bess_discharged_kwh || 0;

  // If no discharge data, estimate from cycles and capacity
  if (bessDischargedKwh === 0) {
    // Typical 250-300 cycles/year for commercial BESS, use 250 as conservative estimate
    const estimatedCycles = variant.bess_cycles_equivalent || 250;
    // Discharge = cycles × capacity × DoD (assume 90% DoD)
    bessDischargedKwh = estimatedCycles * variant.bess_energy_kwh * 0.9;
    console.log('  ⚠️ Estimated BESS discharge:', bessDischargedKwh.toFixed(0), 'kWh/year (from cycles)');
  } else {
    console.log('  ✓ BESS discharge from variant:', bessDischargedKwh.toFixed(0), 'kWh/year');
  }

  // ========== ENERGY SAVINGS ==========
  // Savings from BESS storing excess PV and discharging to reduce grid import
  // This is the main value proposition: energy stored = energy not bought from grid
  const bessDischargedMwh = kwhToMwh(bessDischargedKwh);
  const energySavingsPLN = bessDischargedMwh * energyPricePLNperMWh;
  console.log('  💰 Energy savings:', energySavingsPLN.toFixed(0), 'PLN/year');

  // ========== PEAK SHAVING / DEMAND CHARGE SAVINGS ==========
  // Estimate savings from reducing peak demand (capacity fee reduction)
  // Conservative estimate: BESS can reduce peak by 50-70% of its power rating
  // Demand charge typically 30-60 PLN/kW/month depending on tariff
  const demandChargePLNperKwMonth = settings.bessPowerChargePlnPerKwMonth || 40;
  const peakReductionFactor = 0.5; // Conservative: 50% of BESS power can reduce peak
  const peakReductionKw = variant.bess_power_kw * peakReductionFactor;
  const demandChargeSavingsPLN = peakReductionKw * demandChargePLNperKwMonth * 12;
  console.log('  💰 Demand charge savings:', demandChargeSavingsPLN.toFixed(0), 'PLN/year (peak reduction:', peakReductionKw.toFixed(0), 'kW)');

  // ========== CAPACITY FEE SAVINGS (SOM) ==========
  // Capacity fee (opłata mocowa) savings from reducing contracted capacity
  // Typically 50-80 PLN/kW/month for industrial customers
  const capacityFeePLNperKwMonth = settings.bessCapacityFeePlnPerKwMonth || 0; // Default 0 - not all customers have this
  const capacityFeeSavingsPLN = peakReductionKw * capacityFeePLNperKwMonth * 12;
  console.log('  💰 Capacity fee savings:', capacityFeeSavingsPLN.toFixed(0), 'PLN/year');

  // ========== ARBITRAGE SAVINGS (ToU PREMIUM) ==========
  // Time-of-Use arbitrage: charge at low price, discharge at high price
  // This is ADDITIONAL to flat rate savings (premium for ToU vs flat)
  // Estimate: 10-20% premium for ToU tariffs, applied to portion of BESS discharge
  const touPremiumFactor = settings.bessTouPremiumFactor || 0.10; // 10% default
  const arbitrageEligibleKwh = bessDischargedKwh * 0.7; // Assume 70% of discharge can capture ToU spread
  const arbitrageSavingsPLN = kwhToMwh(arbitrageEligibleKwh) * energyPricePLNperMWh * touPremiumFactor;
  console.log('  💰 Arbitrage savings:', arbitrageSavingsPLN.toFixed(0), 'PLN/year (ToU premium)');

  // ========== DEGRADATION COST ==========
  // Cost of battery degradation from cycling
  // Typical: 0.05-0.10 PLN/kWh throughput
  const degradationCostPLNperKwh = settings.bessDegradationCostPlnPerKwh || 0.10;
  const annualThroughputKwh = bessDischargedKwh * 2; // Charge + discharge
  const degradationCostPLN = annualThroughputKwh * degradationCostPLNperKwh;
  console.log('  💸 Degradation cost:', degradationCostPLN.toFixed(0), 'PLN/year');

  // ========== NET SAVINGS ==========
  const netSavingsPLN = energySavingsPLN + demandChargeSavingsPLN + capacityFeeSavingsPLN + arbitrageSavingsPLN - degradationCostPLN;
  console.log('  ✅ NET savings:', netSavingsPLN.toFixed(0), 'PLN/year');

  return {
    source: 'local-estimate',
    energy_savings_pln: Math.round(energySavingsPLN),
    demand_charge_savings_pln: Math.round(demandChargeSavingsPLN),
    capacity_fee_savings_pln: Math.round(capacityFeeSavingsPLN),
    arbitrage_savings_pln: Math.round(arbitrageSavingsPLN),
    degradation_cost_pln: Math.round(degradationCostPLN),
    net_savings_pln: Math.round(netSavingsPLN),
    // Additional metadata
    bess_discharged_kwh: Math.round(bessDischargedKwh),
    energy_price_pln_mwh: energyPricePLNperMWh,
    peak_reduction_kw: Math.round(peakReductionKw)
  };
}

/**
 * Ensure variant has savings_breakdown - either from API or generated locally.
 * Call this before displaying BESS economics widgets.
 *
 * @param {object} variant - Current variant
 */
function ensureSavingsBreakdown(variant) {
  if (!variant) return;

  // If savings_breakdown already exists, keep it
  if (variant.savings_breakdown) {
    console.log('📊 ensureSavingsBreakdown: Using existing savings_breakdown (source:', variant.savings_breakdown.source || 'api', ')');
    return;
  }

  // Generate locally if BESS is configured
  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  if (hasBess) {
    console.log('📊 ensureSavingsBreakdown: No existing savings_breakdown, generating locally...');
    variant.savings_breakdown = generateLocalSavingsBreakdown(variant);
  }
}

/**
 * Helper function to get annual consumption in kWh
 * This is the TOTAL ENERGY CONSUMPTION of the facility (from uploaded consumption file)
 * NOT to be confused with autoconsumption (self_consumed) which is energy from PV used on-site
 *
 * Uses multiple sources with fallbacks
 */
let _cachedAnnualConsumptionKwh = null;

function invalidateConsumptionCache() {
  _cachedAnnualConsumptionKwh = null;
}

function getAnnualConsumptionKwh() {
  if (_cachedAnnualConsumptionKwh !== null) return _cachedAnnualConsumptionKwh;

  const result = _resolveAnnualConsumptionKwh();
  _cachedAnnualConsumptionKwh = result;
  return result;
}

function _resolveAnnualConsumptionKwh() {
  // Priority 1: consumptionData.annual_consumption_kwh (sent from config module)
  if (consumptionData?.annual_consumption_kwh && consumptionData.annual_consumption_kwh > 0) {
    console.log('📊 [P1] Using annual_consumption_kwh from consumptionData:',
      kwhToMwh(consumptionData.annual_consumption_kwh).toFixed(1), 'MWh');
    return consumptionData.annual_consumption_kwh;
  }

  // Priority 2: consumptionData.total_consumption_gwh (convert GWh to kWh)
  if (consumptionData?.total_consumption_gwh && consumptionData.total_consumption_gwh > 0) {
    const kwh = consumptionData.total_consumption_gwh * 1000000;
    console.log('📊 [P2] Using total_consumption_gwh from consumptionData:',
      consumptionData.total_consumption_gwh, 'GWh =', kwhToMwh(kwh).toFixed(1), 'MWh');
    return kwh;
  }

  // Priority 3: Calculate from hourlyData array (sum of all values)
  if (hourlyData && Array.isArray(hourlyData) && hourlyData.length > 0) {
    let sum = 0;
    for (const h of hourlyData) {
      if (typeof h === 'number') {
        sum += h;
      } else if (h && typeof h.consumption === 'number') {
        sum += h.consumption;
      } else if (h && typeof h.consumption_kwh === 'number') {
        sum += h.consumption_kwh;
      }
    }
    if (sum > 0) {
      console.log('📊 [P3] Calculated annual consumption from hourlyData:', kwhToMwh(sum).toFixed(1), 'MWh');
      return sum;
    }
  }

  // Priority 4: Get from analysisResults (data sent back from pv-calculation)
  if (analysisResults?.consumption_stats?.total_consumption_gwh) {
    const kwh = analysisResults.consumption_stats.total_consumption_gwh * 1000000;
    console.log('📊 [P4] Using total_consumption_gwh from analysisResults:', kwhToMwh(kwh).toFixed(1), 'MWh');
    return kwh;
  }

  // FALLBACK WARNING: The values below are NOT the total consumption!
  console.warn('⚠️ WARNING: consumptionData not available! Using fallback values.');

  // Priority 5: Get from current variant (grid_import + self_consumed = approximate total consumption)
  const variant = variants[currentVariant];
  if (variant) {
    const selfConsumed = variant.self_consumed || 0;
    const gridImport = variant.bess_grid_import_kwh || 0;

    if (selfConsumed > 0 && gridImport > 0) {
      const totalConsumption = selfConsumed + gridImport;
      console.warn('📊 [P5 FALLBACK] Estimated from variant: self_consumed + grid_import =',
        kwhToMwh(totalConsumption).toFixed(1), 'MWh (INACCURATE!)');
      return totalConsumption;
    }
  }

  // Priority 6: Last resort fallback
  console.error('❌ No consumption data found! Using default 5000 MWh');
  return 5000000;
}

/**
 * Global scenario setter - updates ALL economic calculations
 * Called from the global scenario selector in the header
 * @param {string} scenario - P50, P75, or P90
 * @param {boolean} broadcastToShell - whether to notify shell (default: true)
 */
function setGlobalScenario(scenario, broadcastToShell = true) {
  console.log(`🌐 Setting global scenario: ${scenario}`);
  window.currentProductionScenario = scenario;

  // Update global button styles
  const btnConfig = {
    P50: { borderColor: '#27ae60', activeBackground: '#27ae60', textColor: '#27ae60' },
    P75: { borderColor: '#3498db', activeBackground: '#3498db', textColor: '#3498db' },
    P90: { borderColor: '#e74c3c', activeBackground: '#e74c3c', textColor: '#e74c3c' }
  };

  ['P50', 'P75', 'P90'].forEach(s => {
    const btn = document.getElementById(`globalBtn${s}`);
    if (btn) {
      const isActive = s === scenario;
      const cfg = btnConfig[s];
      btn.style.borderColor = cfg.borderColor;
      btn.style.background = isActive ? cfg.activeBackground : 'white';
      btn.style.color = isActive ? 'white' : cfg.textColor;
    }
  });

  // Update scenario labels
  const eaasLabel = document.getElementById('eaasCurrentScenario');
  if (eaasLabel) eaasLabel.textContent = scenario;

  const scenarioLabelEl = document.getElementById('eaasScenarioLabel');
  if (scenarioLabelEl) scenarioLabelEl.textContent = scenario;

  // Update EaaS metrics if scenarios are loaded
  selectProductionScenario(scenario);

  // Recalculate CAPEX section with new scenario factor
  recalculateCapexWithScenario(scenario);

  // Notify shell to sync other modules (only if triggered locally)
  if (broadcastToShell) {
    window.parent.postMessage({
      type: 'PRODUCTION_SCENARIO_CHANGED',
      data: {
        scenario: scenario,
        source: 'economics'
      }
    }, '*');
    console.log(`📡 Broadcasted scenario change to shell: ${scenario}`);
  }

  console.log(`✅ Global scenario set to ${scenario}`);
}

/**
 * Recalculate CAPEX section economics with production scenario factor
 */
async function recalculateCapexWithScenario(scenario) {
  const factor = window.productionFactors[scenario] || 1.0;
  console.log(`📊 Recalculating CAPEX economics with factor: ${factor} (${scenario})`);

  // Store factor for use in calculations
  window.currentScenarioFactor = factor;

  // Clear cached centralized metrics so they get recalculated with new scenario
  // This ensures optimization tables use the new scenario values
  centralizedMetrics = {};
  preciseAnnualSavingsCache = {};
  preciseAnnualSavings = null;
  window.preciseAnnualSavings = null;
  console.log('🔄 Cleared centralizedMetrics + preciseAnnualSavings cache for scenario recalculation');

  // If we have analysis results, recalculate and update displays
  if (analysisResults && variants && Object.keys(variants).length > 0) {
    // Regenerate all charts, tables, and centralizedMetrics with new scenario
    await regenerateAllChartsAndTables();

    // Update key metrics UI from centralizedMetrics (SSoT)
    updateKeyMetricsFromCentralized();
  }
}

/**
 * Regenerate all charts and tables after scenario change
 */
async function regenerateAllChartsAndTables() {
  console.log('🔄 Regenerating all charts and tables for new scenario...');

  const variant = variants[currentVariant];
  if (!variant) return;

  const params = getEconomicParameters();
  const factor = window.currentScenarioFactor || 1.0;

  // Recalculate economic data with scenario factor
  const scenarioAdjustedData = calculateScenarioAdjustedEconomicData(variant, params, factor);

  // Store in economicData for other functions
  economicData = {
    ...economicData,
    ...scenarioAdjustedData,
    scenario: window.currentProductionScenario,
    scenarioFactor: factor
  };
  window._lastEconomicData = economicData;

  // Update charts
  if (typeof generateCashFlowChart === 'function' && scenarioAdjustedData) {
    generateCashFlowChart(scenarioAdjustedData);
  }

  if (typeof generateRevenueChart === 'function') {
    generateRevenueChart();
  }

  // PRECISE MODE: re-fetch for current variant with new scenario
  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  if (!hasBess) {
    await fetchPreciseAnnualSavings(variant);
  }

  // Recalculate EaaS (populates centralizedMetrics + generates EaaS yearly table)
  try {
    await calculateEaaS();
  } catch (e) {
    console.warn('EaaS recalculation skipped:', e.message);
  }

  // Update payback table (reads from centralizedMetrics)
  if (typeof generatePaybackTable === 'function' && scenarioAdjustedData) {
    generatePaybackTable(scenarioAdjustedData, variant.capacity, params);
  }

  // Update revenue table
  if (typeof generateRevenueTable === 'function' && scenarioAdjustedData) {
    generateRevenueTable(scenarioAdjustedData);
  }

  // Update optimization tables (async — fetches PRECISE for all variants)
  if (typeof calculateOptimization === 'function') {
    try {
      await calculateOptimization();
    } catch (e) {
      console.log('Optimization update skipped:', e.message);
    }
  }

  // Update sensitivity charts if visible
  if (typeof generateSensitivityAnalysisCharts === 'function') {
    try {
      generateSensitivityAnalysisCharts();
    } catch (e) {
      console.log('Sensitivity charts update skipped:', e.message);
    }
  }

  // Update data info
  if (typeof updateDataInfo === 'function') {
    updateDataInfo();
  }

  // Update ESG Dashboard with new scenario
  if (typeof updateESGDashboard === 'function') {
    updateESGDashboard();
  }

  // Update Variant Scan chart and table
  if (typeof generateVariantScanSection === 'function') {
    try {
      generateVariantScanSection();
    } catch (e) {
      console.log('Variant scan update skipped:', e.message);
    }
  }

  // Update PULS DNIA chart (async - fetches real data)
  if (typeof generatePulsDniaChart === 'function') {
    generatePulsDniaChart().catch(e => {
      console.log('PULS DNIA update skipped:', e.message);
    });
  }

  console.log('✅ Charts and tables regenerated for scenario');
}

/**
 * Calculate scenario-adjusted economic data
 * Returns data in format expected by generateCashFlowChart, generatePaybackTable, etc.
 */
function calculateScenarioAdjustedEconomicData(variant, params, factor) {
  const capacityKwp = variant.capacity || 0;
  const baseProductionKwh = variant.production || 0;
  const baseSelfConsumedKwh = variant.self_consumed || 0;

  // Apply scenario factor
  const adjustedProductionKwh = baseProductionKwh * factor;
  const adjustedSelfConsumedKwh = baseSelfConsumedKwh * factor;
  const adjustedProductionMwh = kwhToMwh(adjustedProductionKwh);
  const adjustedSelfConsumedMwh = kwhToMwh(adjustedSelfConsumedKwh);

  // Energy prices - calculateTotalEnergyPrice() zawiera wszystkie składniki ceny energii z sieci
  // (energia czynna, dystrybucja, opłaty OZE/kogeneracja/jakościowa/mocowa, akcyza)
  const totalPricePerMwh = calculateTotalEnergyPrice(params);

  // CAPEX
  const capexPerKwp = getCapexForCapacity(capacityKwp);
  const totalCapex = capacityKwp * capexPerKwp;

  // OPEX
  const opexPerKwp = params.opex_per_kwp || 15;
  const annualOpex = capacityKwp * opexPerKwp;

  // Annual savings
  const annualSavings = adjustedSelfConsumedMwh * totalPricePerMwh;
  const netAnnualSavings = annualSavings - annualOpex;

  // Analysis parameters
  const analysisPeriod = params.analysis_period || 25;
  const degradationRate = params.degradation_rate || window.economicsSettings?.degradationRate;
  const discountRate = params.discount_rate || window.economicsSettings?.discountRate;
  const inflationRate = window.economicsSettings?.useInflation ? (params.inflation_rate || window.economicsSettings?.inflationRate) : 0;

  // Generate cash flows in format expected by charts/tables
  const cash_flows = [];
  let cumulativeCashFlow = -totalCapex;
  let npv = -totalCapex;

  for (let year = 1; year <= analysisPeriod; year++) {
    const degradationFactor = Math.pow(1 - degradationRate, year - 1);
    const inflationFactor = Math.pow(1 + inflationRate, year - 1);

    // Production and self-consumption both degrade over time
    const yearProductionMwh = adjustedProductionMwh * degradationFactor;
    const yearSelfConsumedMwh = adjustedSelfConsumedMwh * degradationFactor;

    // Savings come from self-consumed energy
    const yearSavings = yearSelfConsumedMwh * totalPricePerMwh;
    const yearOpex = annualOpex * inflationFactor;
    const yearCashFlow = yearSavings - yearOpex;

    cumulativeCashFlow += yearCashFlow;
    npv += yearCashFlow / Math.pow(1 + discountRate, year);

    // Format expected by generatePaybackTable and generateCashFlowChart
    cash_flows.push({
      year: year,
      production: yearProductionMwh,                     // MWh - total production
      selfConsumed: yearSelfConsumedMwh,                 // MWh - self-consumed (with degradation)
      savings: yearSavings,                              // PLN
      opex: yearOpex,                                    // PLN
      net_cash_flow: yearCashFlow,                       // PLN
      cumulative_cash_flow: cumulativeCashFlow,          // PLN
      npv: npv,                                          // PLN
      unit: 'MWh'                                        // Mark unit explicitly
    });
  }

  return {
    investment: totalCapex,
    annual_savings: annualSavings,
    annual_opex: annualOpex,
    net_annual_savings: netAnnualSavings,
    npv: npv,
    payback_period: netAnnualSavings > 0 ? totalCapex / netAnnualSavings : null,
    cash_flows: cash_flows,                              // Used by generateCashFlowChart
    centralized_cash_flows: cash_flows,                  // Used by generatePaybackTable
    scenario: window.currentProductionScenario,
    factor: factor,
    capacity_kwp: capacityKwp,
    production_mwh: adjustedProductionMwh,
    self_consumed_mwh: adjustedSelfConsumedMwh,
    energy_price: totalPricePerMwh
  };
}

/**
 * Update key metric UI elements from centralizedMetrics (SSoT).
 * Called after centralizedMetrics has been (re)populated.
 */
function updateKeyMetricsFromCentralized() {
  const cm = centralizedMetrics[currentVariant];
  if (!cm || !cm.common) {
    console.warn('⚠️ centralizedMetrics not available for updateKeyMetricsFromCentralized');
    return;
  }

  const c = cm.common;
  const capex = cm.capex;

  // Key metrics — read from SSoT
  const paybackEl = document.getElementById('paybackPeriod');
  if (paybackEl) paybackEl.textContent = c.simplePayback ? formatNumberEU(c.simplePayback, 1) : '–';

  const npvEl = document.getElementById('npv');
  if (npvEl) npvEl.textContent = formatNumberEU(plnToMlnPln(c.capexNpv), 2);

  const irrEl = document.getElementById('irr');
  if (irrEl) irrEl.textContent = c.capexIrr ? formatNumberEU(decimalToPct(c.capexIrr), 1) : '–';

  // Scenario factor display
  const factorDisplayEl = document.getElementById('scenarioFactorDisplay');
  if (factorDisplayEl) factorDisplayEl.textContent = `${formatNumberEU(decimalToPct(c.scenarioFactor), 0)}%`;

  // Store scenario-adjusted data for use by other functions
  window.scenarioAdjustedData = {
    factor: c.scenarioFactor,
    scenario: c.scenarioName,
    production: c.selfConsumedKwh,
    annualSavings: c.selfConsumedMwh * c.totalEnergyPrice,
    npv: c.capexNpv,
    irr: c.capexIrr,
    paybackYears: c.simplePayback,
    capex: c.totalCapex,
    capacityKwp: c.capacityKwp
  };

  // "Szczegółowe Wskaźniki Finansowe" section
  const annualSavings = c.selfConsumedMwh * c.totalEnergyPrice;
  const annualOpex = c.capacityKwp * c.opexPerKwp;
  const netAnnualSavings = annualSavings - annualOpex;

  const savingsAnnualEl = document.getElementById('savingsAnnual');
  if (savingsAnnualEl) savingsAnnualEl.textContent = `${formatNumberEU(plnToTysPln(netAnnualSavings), 0)} tys. PLN`;

  const revenueAnnualEl = document.getElementById('revenueAnnual');
  if (revenueAnnualEl) revenueAnnualEl.textContent = `${formatNumberEU(plnToTysPln(annualSavings), 0)} tys. PLN`;

  const opexAnnualEl = document.getElementById('opexAnnual');
  if (opexAnnualEl) opexAnnualEl.textContent = `${formatNumberEU(plnToTysPln(annualOpex), 0)} tys. PLN`;

  const roiEl = document.getElementById('roi');
  if (roiEl && c.totalCapex > 0) roiEl.textContent = `${formatNumberEU((c.capexNpv / c.totalCapex) * 100, 1)}%`;

  const unitCapexEl = document.getElementById('unitCapex');
  if (unitCapexEl && c.capacityKwp > 0) unitCapexEl.textContent = `${formatNumberEU(c.capexPerKwp, 0)} PLN/kWp`;

  console.log(`📈 Key metrics updated from centralizedMetrics: Payback=${c.simplePayback?.toFixed(1)}y, NPV=${plnToMlnPln(c.capexNpv).toFixed(2)}M, IRR=${c.capexIrr ? (c.capexIrr*100).toFixed(1) : 'N/A'}%`);
}

function selectProductionScenario(scenario) {
  console.log(`🎯 selectProductionScenario called with: ${scenario}`);
  window.currentProductionScenario = scenario;

  const scenarios = window.eaasScenarios;
  const gridPricePLN = window.eaasGridPrice;
  const annualSubscriptionPLN = window.eaasSubscription;
  const baseMetrics = window.eaasBaseMetrics;

  // Button styling configuration (for old buttons if they exist)
  const btnConfig = {
    P50: { borderColor: '#27ae60', activeBackground: '#27ae60', textColor: '#27ae60' },
    P75: { borderColor: '#3498db', activeBackground: '#3498db', textColor: '#3498db' },
    P90: { borderColor: '#e74c3c', activeBackground: '#e74c3c', textColor: '#e74c3c' }
  };

  // Update old button styles (backwards compatibility)
  ['P50', 'P75', 'P90'].forEach(s => {
    const btn = document.getElementById(`btnScenario${s}`);
    if (btn) {
      const isActive = s === scenario;
      const cfg = btnConfig[s];
      btn.style.borderColor = cfg.borderColor;
      btn.style.background = isActive ? cfg.activeBackground : 'white';
      btn.style.color = isActive ? 'white' : cfg.textColor;
      btn.style.fontWeight = isActive ? '700' : '600';
    }
  });

  // If scenarios not loaded yet, just update buttons
  if (!scenarios || !scenarios[scenario]) {
    console.warn('⚠️ Scenarios not loaded yet - only updating button styles');
    return;
  }

  const cs = scenarios[scenario];
  console.log(`📊 Scenario ${scenario} data:`, cs);

  // Update all metric cards with scenario-adjusted values - European format
  // Efektywna cena EaaS = Abonament / Produkcja_scenariusz
  const effectivePriceEl = document.getElementById('eaasVal_effectivePrice');
  if (effectivePriceEl) {
    effectivePriceEl.textContent = formatNumberEU(cs.pricePLN, 2);
  }

  // Różnica cen = Cena sieci - Efektywna cena EaaS
  const priceDiffEl = document.getElementById('eaasVal_priceDiff');
  if (priceDiffEl) {
    priceDiffEl.textContent = formatNumberEU(cs.savingsPerMWh, 2);
    priceDiffEl.style.color = cs.savingsPerMWh >= 0 ? '#27ae60' : '#e74c3c';
  }

  // Roczne oszczędności = Produkcja * Różnica cen
  const annualSavingsEl = document.getElementById('eaasVal_annualSavings');
  if (annualSavingsEl) {
    annualSavingsEl.textContent = formatNumberEU(plnToTysPln(cs.annualSavings), 1);
    annualSavingsEl.style.color = cs.annualSavings >= 0 ? '#27ae60' : '#e74c3c';
  }

  // Savings percent
  const savingsPercentEl = document.getElementById('eaasVal_savingsPercent');
  if (savingsPercentEl) {
    savingsPercentEl.textContent = `tys. PLN (${formatNumberEU(cs.savingsPercent, 1)}% kosztu energii)`;
  }

  // Równoważny okres zwrotu = CAPEX / Roczne oszczędności
  const paybackEl = document.getElementById('eaasVal_payback');
  if (paybackEl && baseMetrics) {
    if (cs.annualSavings > 0) {
      const payback = baseMetrics.capex / cs.annualSavings;
      paybackEl.textContent = formatNumberEU(payback, 1);
      paybackEl.style.color = '#27ae60';
    } else {
      paybackEl.textContent = '–';
      paybackEl.style.color = '#e74c3c';
    }
  }

  // Równoważny ROI = (Roczne oszczędności / CAPEX) * 100
  const roiEl = document.getElementById('eaasVal_roi');
  if (roiEl && baseMetrics && baseMetrics.capex > 0) {
    if (cs.annualSavings > 0) {
      const roi = (cs.annualSavings / baseMetrics.capex) * 100;
      roiEl.textContent = formatNumberEU(roi, 1);
      roiEl.style.color = '#27ae60';
    } else {
      roiEl.textContent = '–';
      roiEl.style.color = '#e74c3c';
    }
  }

  // Produkcja roczna (scenario row)
  const productionEl = document.getElementById('eaasVal_production');
  if (productionEl) {
    productionEl.textContent = formatNumberEU(cs.energyMWh, 0);
  }

  // Scenario label
  const scenarioLabelEl = document.getElementById('eaasScenarioLabel');
  if (scenarioLabelEl) {
    scenarioLabelEl.textContent = scenario;
  }

  // Also update the old label if exists (for backwards compatibility)
  const oldLabelEl = document.getElementById('selectedScenarioLabel');
  if (oldLabelEl) {
    oldLabelEl.textContent = scenario;
  }

  // ESCO IRR stays fixed
  const escoIrrEl = document.getElementById('eaasVal_escoIrr');
  if (escoIrrEl && window.eaasEscoIrr) {
    escoIrrEl.textContent = formatNumberEU(window.eaasEscoIrr * 100, 1);
  }

  console.log(`✅ Selected production scenario: ${scenario}`, cs);

  // Recalculate EaaS table and detailed metrics with new scenario
  recalculateEaaSWithScenario(scenario);
}

/**
 * Recalculate EaaS section (table, detailed metrics) with new production scenario
 */
function recalculateEaaSWithScenario(scenario) {
  console.log(`🔄 Recalculating EaaS section for scenario: ${scenario}`);

  const variant = variants[currentVariant];
  if (!variant) {
    console.warn('⚠️ No variant data for EaaS recalculation');
    return;
  }

  const factor = window.productionFactors[scenario] || 1.0;
  const params = getEconomicParameters();

  // Clear cached centralized metrics to force recalculation
  if (centralizedMetrics[currentVariant]) {
    delete centralizedMetrics[currentVariant];
  }
  if (centralizedMetricsRdn[currentVariant]) {
    delete centralizedMetricsRdn[currentVariant];
  }

  // Recalculate EaaS subscription with adjusted production
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value) || 24;
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || 10;

  // Use FULL MODEL subscription (stored from calculateEaasFullModel) for consistency
  // with "Efektywna cena EaaS" which also uses the full model.
  // Fallback to simple model only if full model result not available.
  const fullModelSubPLN = window.eaasSubscription; // PLN, from calculateEaasFullModel
  const eaasCurrency = (systemSettings || {}).eaasCurrency || 'PLN';
  const fxRate = (systemSettings || {}).fxPlnEur || 4.5;

  let subscriptionContractCurrency, subscriptionPLN;
  if (fullModelSubPLN && fullModelSubPLN > 0) {
    subscriptionPLN = fullModelSubPLN;
    subscriptionContractCurrency = eaasCurrency === 'EUR' ? fullModelSubPLN / fxRate : fullModelSubPLN;
    console.log(`📊 Using FULL MODEL subscription: ${subscriptionPLN.toFixed(0)} PLN/yr = ${subscriptionContractCurrency.toFixed(0)} ${eaasCurrency}/yr`);
  } else {
    // Fallback: simple model
    const subscriptionData = calculateEaasSubscription(
      variant.capacity,
      systemSettings || {},
      params,
      variant
    );
    subscriptionContractCurrency = subscriptionData.annualSubscription;
    subscriptionPLN = subscriptionData.annualSubscriptionPLN;
    console.warn(`⚠️ Full model subscription not available, using simple model: ${subscriptionPLN.toFixed(0)} PLN/yr`);
  }

  // Recalculate centralized metrics with scenario factor (expects PLN, consistent with initial calc)
  centralizedMetrics[currentVariant] = calculateCentralizedFinancialMetrics(variant, params, {
    subscription: subscriptionPLN,
    duration: eaasDuration,
    omPerKwp: eaasOM
  });

  // Recalculate RDN year-by-year if TCSL data available
  if (tcslMetrics[currentVariant]?.rdn_tcsl_annual_pln != null) {
    try { calculateRdnYearByYear(); } catch (e) { console.error('RDN YbY recalc error:', e); }
  }

  // Regenerate EaaS yearly table
  const eaasParams = {
    annualConsumptionKWh: getAnnualConsumptionKwh(),
    annualPVProductionKWh: variant.production * factor,
    selfConsumptionRatio: variant.self_consumed / variant.production,
    pvPowerKWp: variant.capacity,
    pvCapexPLN: variant.capacity * getCapexForCapacity(variant.capacity),
    eaasSubscriptionPLNperYear: subscriptionPLN,
    omCostPerKWp: eaasOM,
    tariffComponents: {
      energyActive: params.energy_active,
      distribution: params.distribution,
      quality: params.quality_fee,
      oze: params.oze_fee,
      cogeneration: params.cogeneration_fee,
      capacity: params.capacity_fee,
      excise: params.excise_tax
    }
  };

  // Generate the EaaS yearly table
  if (typeof generateEaaSYearlyTable === 'function') {
    generateEaaSYearlyTable(eaasParams, { scenario: scenario, factor: factor });
  }

  // Update "Cena EaaS" (price per MWh) using SAME subscription as "Efektywna cena EaaS"
  // This ensures: Cena EaaS [EUR/MWh] × FX = Efektywna cena [PLN/MWh]
  const annualEnergyMWh = kwhToMwh(variant.self_consumed || variant.production || 0) * factor;
  if (annualEnergyMWh > 0) {
    const updatedPricePerMWh = subscriptionContractCurrency / annualEnergyMWh;
    const priceEl = document.getElementById('eaasPricePerMWh');
    if (priceEl) {
      priceEl.textContent = updatedPricePerMWh.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
    }
  }

  // Update detailed metrics section
  updateEaaSDetailedMetrics(scenario, factor);

  console.log(`✅ EaaS section recalculated for ${scenario}`);
}

/**
 * Update EaaS detailed financial metrics
 */
function updateEaaSDetailedMetrics(scenario, factor) {
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc) return;

  // Update Szczegółowe Wskaźniki Finansowe section
  // These IDs might be different - need to check actual HTML
  const detailedElements = {
    'eaasDetailedNPV': centralizedCalc.eaas?.npv,
    'eaasDetailedIRR': centralizedCalc.eaas?.irr ? centralizedCalc.eaas.irr * 100 : null,
    'capexDetailedNPV': centralizedCalc.capex?.npv,
    'capexDetailedIRR': centralizedCalc.capex?.irr ? centralizedCalc.capex.irr * 100 : null
  };

  for (const [id, value] of Object.entries(detailedElements)) {
    const el = document.getElementById(id);
    if (el && value !== null && value !== undefined) {
      if (id.includes('NPV')) {
        el.textContent = formatNumberEU(plnToMlnPln(value), 2);
      } else if (id.includes('IRR')) {
        el.textContent = formatNumberEU(value, 1);
      }
    }
  }

  console.log(`📊 Updated EaaS detailed metrics for ${scenario}`);
}

function getInsuranceRate(settings) {
  const raw = settings?.insuranceRate;
  if (raw === undefined || raw === null) {
    return window.economicsSettings?.insuranceRate || 0.005;
  }
  // If user provided percentage (>1), convert to decimal fraction
  return raw > 1 ? raw / 100 : raw;
}

// Default CAPEX per type (fallback when systemSettings doesn't have capexPerType)
const DEFAULT_CAPEX_PER_TYPE = {
  ground_s: [
    { cost: 2800, margin: 23, sale: 3444 },  // 50-150 kWp
    { cost: 2400, margin: 20, sale: 2880 },  // 150-300 kWp
    { cost: 2000, margin: 18, sale: 2360 },  // 300-1000 kWp
    { cost: 1700, margin: 16, sale: 1972 },  // 1000-3000 kWp
    { cost: 1500, margin: 15, sale: 1725 },  // 3000-10000 kWp
    { cost: 1400, margin: 13, sale: 1582 }   // 10000+ kWp
  ],
  ground_ew: [
    { cost: 2744, margin: 23, sale: 3375 },
    { cost: 2352, margin: 20, sale: 2822 },
    { cost: 1960, margin: 18, sale: 2313 },
    { cost: 1666, margin: 16, sale: 1933 },
    { cost: 1470, margin: 15, sale: 1691 },
    { cost: 1372, margin: 13, sale: 1550 }
  ],
  roof_ew: [
    { cost: 3100, margin: 23, sale: 3813 },  // 50-150 kWp
    { cost: 2700, margin: 20, sale: 3240 },  // 150-300 kWp
    { cost: 2300, margin: 18, sale: 2714 },  // 300-1000 kWp
    { cost: 1950, margin: 16, sale: 2262 },  // 1000-3000 kWp
    { cost: 1650, margin: 15, sale: 1898 },  // 3000-10000 kWp
    null  // No installations above 10 MWp for roof
  ],
  carport: [
    { cost: 3500, margin: 23, sale: 4305 },
    { cost: 3200, margin: 20, sale: 3840 },
    { cost: 2800, margin: 18, sale: 3304 },
    { cost: 2500, margin: 16, sale: 2900 },
    { cost: 2200, margin: 15, sale: 2530 },
    { cost: 2000, margin: 13, sale: 2260 }
  ]
};

const DEFAULT_CAPEX_RANGES = [
  { min: 50, max: 150 },
  { min: 150, max: 300 },
  { min: 300, max: 1000 },
  { min: 1000, max: 3000 },
  { min: 3000, max: 10000 },
  { min: 10000, max: Infinity }
];

// Get CAPEX per kWp based on capacity using tiered pricing (memoized)
const _capexCache = new Map();

function invalidateCapexCache() {
  _capexCache.clear();
}

function getCapexForCapacity(capacityKwp) {
  const pvType = pvConfig?.pvType || pvConfig?.pv_type || 'ground_s';
  const cacheKey = `${capacityKwp}_${pvType}`;
  if (_capexCache.has(cacheKey)) return _capexCache.get(cacheKey);

  const result = _resolveCapexForCapacity(capacityKwp);
  _capexCache.set(cacheKey, result);
  return result;
}

function _resolveCapexForCapacity(capacityKwp) {
  const currentPvType = pvConfig?.pvType || pvConfig?.pv_type || 'ground_s';

  // SSoT: delegate to settings.js via window.PVSettings (loaded first)
  if (window.PVSettings?.getCapexForCapacity) {
    return window.PVSettings.getCapexForCapacity(capacityKwp, currentPvType);
  }

  // Fallback when settings.js not yet loaded — use local data
  const capexPerType = systemSettings?.capexPerType || DEFAULT_CAPEX_PER_TYPE;
  const capexRanges = systemSettings?.capexRanges || DEFAULT_CAPEX_RANGES;
  const typeTiers = capexPerType[currentPvType] || capexPerType.ground_s;

  if (typeTiers && capexRanges) {
    for (let i = 0; i < capexRanges.length; i++) {
      const range = capexRanges[i];
      const tier = typeTiers[i];
      if (!tier || !range) continue;
      const maxVal = (range.max == null || range.max === Infinity || range.max >= 999999) ? Infinity : range.max;
      if (capacityKwp >= (range.min || 0) && capacityKwp <= maxVal) {
        return tier.sale || tier.cost || 3500;
      }
    }
    // Last valid tier for large installations
    for (let i = typeTiers.length - 1; i >= 0; i--) {
      if (typeTiers[i] !== null) {
        return typeTiers[i].sale || typeTiers[i].cost || 3500;
      }
    }
  }

  return 3500;
}

// Get economic parameters from inputs or systemSettings
function getEconomicParameters() {
  // Get ToU average energy rate from tariffConfig
  const touAverageRate = calculateTouAverageRate();

  // Use systemSettings if available, otherwise fall back to input values
  return {
    // Energia czynna - średnia stawka z ToU (trzystrefowa/dwustrefowa/jednolita)
    energy_active: touAverageRate,
    // Opłaty stałe (z sekcji USTAWIENIA -> Opłaty Stałe)
    distribution: systemSettings?.distribution || parseFloat(document.getElementById('distribution')?.value || 200),
    distribution_peak: systemSettings?.distributionPeak || parseFloat(document.getElementById('distributionPeak')?.value || 200),
    distribution_day: systemSettings?.distributionDay || parseFloat(document.getElementById('distributionDay')?.value || 200),
    distribution_night: systemSettings?.distributionNight || parseFloat(document.getElementById('distributionNight')?.value || 200),
    distribution_valley: systemSettings?.distributionValley || parseFloat(document.getElementById('distributionValley')?.value || 13.5),
    quality_fee: systemSettings?.qualityFee || parseFloat(document.getElementById('qualityFee')?.value || 10),
    oze_fee: systemSettings?.ozeFee || parseFloat(document.getElementById('ozeFee')?.value || 7),
    cogeneration_fee: systemSettings?.cogenerationFee || parseFloat(document.getElementById('cogenerationFee')?.value || 10),
    capacity_fee: systemSettings?.capacityFee || parseFloat(document.getElementById('capacityFee')?.value || 219),
    excise_tax: systemSettings?.exciseTax || parseFloat(document.getElementById('exciseTax')?.value || 5),
    investment_cost: parseFloat(document.getElementById('investmentCost')?.value || 3500), // This is display only
    opex_per_kwp: systemSettings?.opexPerKwp || parseFloat(document.getElementById('opexPerKwp')?.value || 15),
    degradation_rate: window.economicsSettings?.degradationRate || pctToDecimal(systemSettings?.degradationRate || parseFloat(document.getElementById('degradationRate')?.value || 0.5)),
    analysis_period: systemSettings?.analysisPeriod || parseInt(document.getElementById('analysisPeriod')?.value || 25)
  };
}

// Calculate average ToU rate from tariffConfig
function calculateTouAverageRate() {
  const tc = systemSettings?.tariffConfig;
  if (!tc) {
    // Fallback to default if no tariffConfig
    console.log('⚠️ No tariffConfig - using default 510 PLN/MWh');
    return 510;
  }

  const type = tc.type || 'two_zone';
  let avgRate = 510; // Default

  if (type === 'flat') {
    avgRate = tc.flatRate || 750;
  } else if (type === 'two_zone' && tc.twoZone) {
    const dayRate = tc.twoZone.dayRate || 850;
    const nightRate = tc.twoZone.nightRate || 450;
    // Assuming 60% day / 40% night consumption profile
    avgRate = dayRate * 0.6 + nightRate * 0.4;
  } else if (type === 'three_zone' && tc.threeZone) {
    const peakRate = tc.threeZone.peakRate || 550;
    const partialRate = tc.threeZone.partialRate || 550;
    const offPeakRate = tc.threeZone.offPeakRate || 450;
    // Assuming ~35% peak / ~25% partial / ~40% off-peak for industrial profile
    avgRate = peakRate * 0.35 + partialRate * 0.25 + offPeakRate * 0.40;
  }

  console.log(`💰 ToU Average Rate (${type}): ${avgRate.toFixed(0)} PLN/MWh`);
  return avgRate;
}

/**
 * Compute weighted average energy price (PLN/MWh) based on actual self-consumption profile.
 * For hybrid_monthly: weights OSD and RDN prices by real hourly self-consumption.
 * Returns { weightedEnergyActive, weightedTotalNoCapacity, weightedTotal } in PLN/MWh
 * or null if hourly data not available.
 */
function computeWeightedEnergyPrice(params) {
  const settings = systemSettings || {};
  const pricingMode = settings.pricingMode || 'single';

  // Only compute for hybrid_monthly or full RDN
  if (pricingMode !== 'hybrid_monthly') return null;

  const monthlyPriceSources = settings.monthlyPriceSources || {};

  // Get hourly profiles (same source as PULS DNIA)
  const sd = window.sharedData || window.parent?.sharedData || {};
  const pvHourly = cachedHourlyProduction?.values || sd.pvData || sd.analysisResults?.hourly_production || [];
  const loadHourly = cachedHourlyConsumption?.values || sd.loadData || sd.consumptionData?.values || [];

  if (pvHourly.length < 720 || loadHourly.length < 720) {
    console.warn('⚠️ computeWeightedEnergyPrice: insufficient hourly data, pvH=', pvHourly.length, 'loadH=', loadHourly.length);
    return null;
  }

  // Get RDN hourly prices from centralized PriceConfig
  const rdnPrices = _getRdnHourlyPrices();

  const n = Math.min(pvHourly.length, loadHourly.length);
  const startDate = new Date(cachedHourlyConsumption?.timestamps?.[0] ||
                             sd.analyticalPeriod?.start_datetime || '2025-01-01');

  // Other fixed fees (excluding distribution — distribution is zonal)
  const otherFeesPerMwh = (params.quality_fee || 0) + (params.oze_fee || 0) +
                          (params.cogeneration_fee || 0) + (params.excise_tax || 0);

  let totalSelfConsumedKwh = 0;
  let weightedEnergyActiveSumPln = 0; // sum of (selfConsumed_kWh * energyActiveRate_PLN/kWh)
  let weightedDistributionSumPln = 0; // sum of (selfConsumed_kWh * distRate_PLN/kWh)

  for (let i = 0; i < n; i++) {
    const load = loadHourly[i] || 0;
    const pv = pvHourly[i] || 0;
    const selfConsumed = Math.min(pv, load); // kWh (1h intervals)
    if (selfConsumed <= 0) continue;

    // Determine hour's date
    const hourDate = new Date(startDate.getTime() + i * 3600000);
    const month = hourDate.getMonth() + 1; // 1-12
    const h = hourDate.getHours();
    const dayOfWeek = hourDate.getDay(); // 0=Sun
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const dayOfMonth = hourDate.getDate();

    // Get energy active rate for this hour (PLN/kWh)
    const source = monthlyPriceSources[month] || 'osd';
    let energiaRatePerKwh;

    if (source === 'rdn' && rdnPrices && i < rdnPrices.length) {
      energiaRatePerKwh = rdnPrices[i] / 1000; // PLN/MWh -> PLN/kWh
    } else {
      // OSD ToU rate
      energiaRatePerKwh = getHourlyEnergyRate(h, month, dayOfMonth, isWeekend); // PLN/kWh
    }

    // Distribution rate for this hour (zonal)
    const distRatePerKwh = getHourlyDistributionRate(h, month, dayOfMonth, isWeekend, params);

    totalSelfConsumedKwh += selfConsumed;
    weightedEnergyActiveSumPln += selfConsumed * energiaRatePerKwh;
    weightedDistributionSumPln += selfConsumed * distRatePerKwh;
  }

  if (totalSelfConsumedKwh <= 0) return null;

  // Weighted average rates in PLN/MWh
  const weightedEnergyActive = (weightedEnergyActiveSumPln / totalSelfConsumedKwh) * 1000;
  const weightedDistribution = (weightedDistributionSumPln / totalSelfConsumedKwh) * 1000;
  const weightedTotalNoCapacity = weightedEnergyActive + weightedDistribution + otherFeesPerMwh;
  const weightedTotal = weightedTotalNoCapacity + (params.capacity_fee || 0);

  console.log(`💰 Weighted Energy Price (hybrid_monthly): energyActive=${weightedEnergyActive.toFixed(1)}, noCapacity=${weightedTotalNoCapacity.toFixed(1)}, total=${weightedTotal.toFixed(1)} PLN/MWh`);
  console.log(`   Based on ${totalSelfConsumedKwh.toFixed(0)} kWh self-consumed across ${n} hours`);

  return { weightedEnergyActive, weightedTotalNoCapacity, weightedTotal };
}

/**
 * Fetch precise annual savings from backend (hourly K-class methodology, same as Excel).
 * Calls backend per-variant with variant-specific PV profile.
 * Caches results in preciseAnnualSavingsCache[variantKey].
 * Sets global `preciseAnnualSavings` to the result for backward compat.
 * Returns the data or null on failure.
 */

/**
 * Resolve PV hourly profile for a variant — SINGLE SOURCE OF TRUTH.
 * Used by fetchPreciseAnnualSavings() and exportPvYearlyExcel().
 * Steps: 1) variant-specific, 2) scale from base, 3) localStorage, 4) scenarioFactor, 5) LID
 * @returns {{ pvProfile: number[]|null, pvProfileSource: string }}
 */
function resolvePvProfile(variant, variantKey) {
  const sd = window.sharedData || window.parent?.sharedData || {};
  const ar = sd.analysisResults || analysisResults || {};

  let pvProfile = null;
  let pvProfileSource = '';

  // 1. Best: variant-specific hourly_production from key_variants
  const variantData = ar.key_variants?.[variantKey];
  if (variantData?.hourly_production?.length >= 720) {
    pvProfile = [...variantData.hourly_production];
    pvProfileSource = `key_variants[${variantKey}].hourly_production`;
  }

  // 2. Fallback: scale cached/base PV profile by capacity ratio
  if (!pvProfile || pvProfile.length < 720) {
    const basePvProfile = cachedHourlyProduction?.values || sd.pvData || ar.hourly_production || [];
    if (basePvProfile.length >= 720) {
      const baseVariantKey = currentVariant || 'B';
      const baseCapacity = ar.key_variants?.[baseVariantKey]?.capacity || variants[baseVariantKey]?.capacity || variant.capacity;
      const targetCapacity = variant.capacity || baseCapacity;
      if (baseCapacity > 0 && targetCapacity !== baseCapacity) {
        const scale = targetCapacity / baseCapacity;
        pvProfile = basePvProfile.map(v => v * scale);
        pvProfileSource = `scaled from ${baseVariantKey} (${baseCapacity}→${targetCapacity} kWp, x${scale.toFixed(3)})`;
      } else {
        pvProfile = [...basePvProfile];
        pvProfileSource = 'cached (same capacity)';
      }
    }
  }

  // 3. Last resort: localStorage
  if (!pvProfile || pvProfile.length < 720) {
    try {
      const storedVariants = JSON.parse(localStorage.getItem('pv_variants') || '{}');
      const sv = storedVariants[variantKey];
      if (sv?.hourly_production?.length >= 720) {
        pvProfile = [...sv.hourly_production];
        pvProfileSource = 'localStorage';
      }
    } catch (e) { /* ignore */ }
  }

  if (!pvProfile || pvProfile.length < 720) {
    return { pvProfile: null, pvProfileSource: 'NOT FOUND' };
  }

  // 4. Apply scenario factor (P50/P75/P90) — productionFactors priorytet
  const scenarioName = window.currentProductionScenario || 'P50';
  const scenarioFactor = (window.productionFactors && window.productionFactors[scenarioName] !== undefined)
    ? window.productionFactors[scenarioName]
    : (window.currentScenarioFactor || 1.0);
  if (scenarioFactor !== 1.0) {
    pvProfile = pvProfile.map(v => v * scenarioFactor);
    pvProfileSource += ` × ${scenarioFactor} (${scenarioName})`;
  }

  // 5. Apply Year 1 LID degradation
  const lidPct = window.economicsSettings?.pvDegradationYear1 || 0;
  if (lidPct > 0) {
    pvProfile = pvProfile.map(v => v * (1 - lidPct));
    pvProfileSource += ` × ${(1 - lidPct).toFixed(3)} (LID ${(lidPct*100).toFixed(1)}%)`;
  }

  return { pvProfile, pvProfileSource };
}

async function fetchPreciseAnnualSavings(variant) {
  if (!variant) return null;

  const variantKey = variant.variant || currentVariant || 'B';
  const scenarioKey = window.currentProductionScenario || 'P50';
  const cacheKey = `${variantKey}_${scenarioKey}`;

  // Return cached result if available for this variant+scenario combination
  if (preciseAnnualSavingsCache[cacheKey]) {
    const cached = preciseAnnualSavingsCache[cacheKey];
    preciseAnnualSavings = cached;
    window.preciseAnnualSavings = cached;
    // Also store under plain variantKey for backward compatibility
    preciseAnnualSavingsCache[variantKey] = cached;
    console.log(`📊 fetchPreciseAnnualSavings: using CACHED result for ${cacheKey} (${cached.energy?.self_consumed_mwh?.toFixed(1)} MWh)`);
    return cached;
  }

  const settings = systemSettings || {};
  const tariffConfig = settings.tariffConfig || {};

  // Ensure hourly data is loaded (with proper waiting for concurrent loads)
  if (!cachedHourlyConsumption || !cachedHourlyProduction) {
    try { await fetchRealHourlyData(); } catch (e) { console.warn('fetchRealHourlyData error:', e); }
  }

  // === PV PROFILE: resolve via shared function (scenarioFactor + LID already applied) ===
  const { pvProfile: resolvedPv, pvProfileSource } = resolvePvProfile(variant, variantKey);
  let pvProfile = resolvedPv;
  if (!pvProfile) {
    console.warn(`⚠️ fetchPreciseAnnualSavings: no PV profile for variant ${variantKey}`);
    return null;
  }

  // === LOAD PROFILE (same for all variants) ===
  let loadProfile = cachedHourlyConsumption?.values || sd.loadData || sd.consumptionData?.values || [];
  if (loadProfile.length < 720) {
    try {
      const stored = JSON.parse(localStorage.getItem('hourly_consumption') || 'null');
      if (stored?.values?.length >= 720) loadProfile = stored.values;
    } catch (e) { /* ignore */ }
  }

  // Convert 15-min to hourly if needed
  if (loadProfile.length > 10000) {
    const hourlyLoad = [];
    for (let h = 0; h < Math.floor(loadProfile.length / 4); h++) {
      const s = h * 4;
      hourlyLoad.push(((loadProfile[s] || 0) + (loadProfile[s+1] || 0) + (loadProfile[s+2] || 0) + (loadProfile[s+3] || 0)) / 4);
    }
    loadProfile = hourlyLoad;
  }

  // scenarioFactor + LID already applied by resolvePvProfile()

  const pvSum = pvProfile.reduce((a, b) => a + b, 0);
  const loadSum = loadProfile.reduce((a, b) => a + b, 0);
  const selfConsumedSum = pvProfile.reduce((acc, pv, i) => acc + Math.min(pv, loadProfile[i] || 0), 0);
  console.log(`📊 fetchPreciseAnnualSavings[${variantKey}]: pvSource=${pvProfileSource}, pv=${(pvSum/1000).toFixed(1)} MWh, load=${(loadSum/1000).toFixed(1)} MWh, selfConsumed=${(selfConsumedSum/1000).toFixed(1)} MWh`);

  if (loadProfile.length < 720) {
    console.warn('⚠️ fetchPreciseAnnualSavings: insufficient load data, loadH=', loadProfile.length);
    return null;
  }

  const n = Math.min(pvProfile.length, loadProfile.length);
  const payload = {
    load_kw: loadProfile.slice(0, n),
    pv_kw: pvProfile.slice(0, n),
    start_date: cachedHourlyConsumption?.timestamps?.[0]?.slice(0, 10) ||
                sd.analyticalPeriod?.start_datetime?.slice(0, 10) || '2025-01-01',
    interval_minutes: 60,
    tariff_type: tariffConfig.type || 'two_zone',
    flat_rate: tariffConfig.flatRate || 750,
    day_rate: tariffConfig.twoZone?.dayRate || 850,
    night_rate: tariffConfig.twoZone?.nightRate || 450,
    peak_rate: tariffConfig.threeZone?.peakRate || 950,
    partial_rate: tariffConfig.threeZone?.partialRate || 700,
    off_peak_rate: tariffConfig.threeZone?.offPeakRate || 400,
    weekday_day_start: tariffConfig.twoZone?.weekday?.start || 6,
    weekday_day_end: tariffConfig.twoZone?.weekday?.end || 22,
    weekend_day_start: tariffConfig.twoZone?.weekend?.start || 6,
    weekend_day_end: tariffConfig.twoZone?.weekend?.end || 13,
    peak1_start: tariffConfig.threeZone?.peak1?.start || 7,
    peak1_end: tariffConfig.threeZone?.peak1?.end || 13,
    peak2_start: tariffConfig.threeZone?.peak2?.start || 17,
    peak2_end: tariffConfig.threeZone?.peak2?.end || 21,
    distribution: settings.distribution || 200,
    distribution_peak: settings.distributionPeak || settings.distribution || 200,
    distribution_day: settings.distributionDay || settings.distribution || 200,
    distribution_night: settings.distributionNight || settings.distribution || 200,
    distribution_valley: settings.distributionValley || settings.distributionNight || 13.5,
    quality_fee: settings.qualityFee || 10,
    oze_fee: settings.ozeFee || 7,
    cogeneration_fee: settings.cogenerationFee || 10,
    excise_tax: settings.exciseTax || 5,
    capacity_fee_som: settings.capacityFeeConfig?.somRate || 0.2194,
    is_osd_all_in: settings.isOsdAllIn || false,
    // Distribution time windows (OSD zones)
    ...getDistConfigPayload(settings),
    project_name: `PV ${variant.capacity} kWp`,
    pv_capacity_kwp: variant.capacity || 0,
  };

  // Hybrid monthly pricing
  const pricingMode = settings.pricingMode || 'single';
  if (pricingMode === 'hybrid_monthly' && settings.monthlyPriceSources) {
    const sources = {};
    for (const [k, v] of Object.entries(settings.monthlyPriceSources)) {
      sources[parseInt(k)] = v;
    }
    payload.monthly_price_sources = sources;
  }

  // RDN hourly prices (from centralized PriceConfig)
  const rdnPricesForPayload = _getRdnHourlyPrices();
  if (rdnPricesForPayload && rdnPricesForPayload.length >= 720) {
    payload.hourly_prices_pln_mwh = rdnPricesForPayload;
  }

  try {
    console.log(`📊 fetchPreciseAnnualSavings[${variantKey}]: calling /pv-annual-summary (${variant.capacity} kWp)...`);
    const resp = await fetch('/api/bess-dispatch/pv-annual-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    // Cache per variant+scenario AND set global for backward compat
    preciseAnnualSavingsCache[cacheKey] = data;
    preciseAnnualSavingsCache[variantKey] = data;
    preciseAnnualSavings = data;
    window.preciseAnnualSavings = data;
    console.log(`✅ Precise annual savings[${variantKey}] loaded:`, {
      total: data.year1_savings?.total_pln,
      energia: data.year1_savings?.energia_pln,
      mocowa: data.year1_savings?.mocowa_pln,
      effectivePrice: data.effective_price_pln_mwh,
      selfConsumedMwh: data.energy?.self_consumed_mwh,
    });
    return data;
  } catch (err) {
    console.error(`❌ fetchPreciseAnnualSavings[${variantKey}] failed:`, err);
    return null;
  }
}

// Calculate total energy price (PLN/MWh) - PEŁNA cena zakupu energii z sieci
// Zawiera wszystkie składniki: energia czynna, dystrybucja, opłaty, akcyza
function calculateTotalEnergyPrice(params) {
  // Pełna suma wszystkich składowych ceny energii z sieci:
  // - energy_active: cena energii czynnej (hurtowa + marża sprzedawcy)
  // - distribution: opłata dystrybucyjna (sieciowa)
  // - quality_fee: opłata jakościowa
  // - oze_fee: opłata OZE
  // - cogeneration_fee: opłata kogeneracyjna
  // - capacity_fee: opłata mocowa (rynkowa)
  // - excise_tax: akcyza
  const total = (params.energy_active || 510) +
                (params.distribution || 200) +
                (params.quality_fee || 10) +
                (params.oze_fee || 7) +
                (params.cogeneration_fee || 10) +
                (params.capacity_fee || 219) +
                (params.excise_tax || 5);
  return isNaN(total) ? 961 : total; // Default 961 PLN/MWh if calculation fails
}

// Calculate capacity fee - returns capacity fee to add to base energy price
function calculateCapacityFeeForConsumption(consumptionData, params) {
  // Pełna opłata mocowa - dodawana do bazowej ceny energii
  return params.capacity_fee;
}

// Recalculate button handler
function recalculateEconomics() {
  console.log('🔄 Recalculating economics with new parameters...');

  // Update window.economicsSettings.totalEnergyPrice from current UI values
  const params = getEconomicParameters();
  window.economicsSettings.totalEnergyPrice = calculateTotalEnergyPrice(params);
  console.log('💰 Updated total energy price:', window.economicsSettings.totalEnergyPrice, 'PLN/MWh');

  performEconomicAnalysis();
}

// Reset to defaults button handler
function resetToDefaults() {
  document.getElementById('energyActive').value = 550;
  document.getElementById('distribution').value = 200;
  document.getElementById('qualityFee').value = 10;
  document.getElementById('ozeFee').value = 7;
  document.getElementById('cogenerationFee').value = 10;
  document.getElementById('capacityFee').value = 219;
  document.getElementById('exciseTax').value = 5;
  document.getElementById('investmentCost').value = 3500;
  document.getElementById('opexPerKwp').value = 15;
  document.getElementById('degradationRate').value = 0.5;
  document.getElementById('analysisPeriod').value = 25;
  recalculateEconomics();
}

// IRR is now provided exclusively by backend economics service (no local solver)
// Compatibility helper: returns last backend IRR when synchronous IRR is requested
function calculateIRR() {
  const backendIrr = economicData?.irr ?? centralizedMetrics?.[currentVariant]?.capex?.irr;
  if (backendIrr === undefined || backendIrr === null) {
    console.warn('IRR unavailable locally - backend is the source of truth');
    return 0;
  }
  return backendIrr;
}

async function fetchBackendIRR(variant, params) {
  // Build payload for economics service /analyze endpoint
  const variantData = {
    capacity: variant.capacity,
    production: variant.production,
    self_consumed: variant.self_consumed,
    exported: variant.exported,
    auto_consumption_pct: variant.auto_consumption_pct,
    coverage_pct: variant.coverage_pct
  };

  // Add BESS fields if present
  if (variant.bess_power_kw !== undefined && variant.bess_power_kw !== null) {
    variantData.bess_power_kw = variant.bess_power_kw;
    variantData.bess_energy_kwh = variant.bess_energy_kwh;
    variantData.bess_charged_kwh = variant.bess_charged_kwh;
    variantData.bess_discharged_kwh = variant.bess_discharged_kwh;
    variantData.bess_curtailed_kwh = variant.bess_curtailed_kwh;
    variantData.bess_grid_import_kwh = variant.bess_grid_import_kwh;
    variantData.bess_self_consumed_direct_kwh = variant.bess_self_consumed_direct_kwh;
    variantData.bess_self_consumed_from_bess_kwh = variant.bess_self_consumed_from_bess_kwh;
    variantData.bess_cycles_equivalent = variant.bess_cycles_equivalent;
  }

  const parametersData = {
    energy_price: params.energy_price,           // PLN/MWh
    feed_in_tariff: params.feed_in_tariff || 0,  // PLN/MWh
    investment_cost: params.investment_cost,     // PLN/kWp
    export_mode: params.export_mode || 'zero',
    discount_rate: params.discount_rate,
    degradation_rate: params.degradation_rate,
    opex_per_kwp: params.opex_per_kwp,
    analysis_period: params.analysis_period,
    use_inflation: params.use_inflation || false,
    irr_mode: params.irr_mode || (params.use_inflation ? 'nominal' : 'real'),
    inflation_rate: params.inflation_rate || 0
  };

  // Add BESS economic parameters from system settings
  const settings = systemSettings;
  if (settings?.bessEnabled) {
    parametersData.bess_capex_per_kwh = settings.bessCapexPerKwh || 1500;
    parametersData.bess_capex_per_kw = settings.bessCapexPerKw || 300;
    parametersData.bess_opex_pct_per_year = settings.bessOpexPctPerYear || 1.5;
    parametersData.bess_lifetime_years = settings.bessLifetimeYears;
    parametersData.bess_degradation_year1 = settings.bessDegradationYear1 || 3.0;
    parametersData.bess_degradation_pct_per_year = settings.bessDegradationPctPerYear || 2.0;
  }

  const payload = {
    variant: variantData,
    parameters: parametersData
  };

  const response = await fetch(`${API_URLS.economics}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Economics backend error: ${response.status} ${text}`);
  }

  return response.json();
}

// Fetch monthly EaaS calculation with detailed log (backend)
async function fetchEaasMonthlyLog(variant, settings, params) {
  const payload = {
    capacity_kw: variant.capacity,
    capex_per_kwp: getCapexForCapacity(variant.capacity),
    opex_per_kwp: params.opex_per_kwp,
    insurance_rate: getInsuranceRate(settings),
    land_lease_per_kwp: settings?.landLeasePerKwp ?? 0,
    duration_years: settings?.eaasDuration ?? 10,
    target_irr: pctToDecimal(settings?.eaasTargetIrrPln ?? 12.0),
    indexation: settings?.eaasIndexation ?? 'fixed',
    cpi: window.economicsSettings?.inflationRate,
    currency: settings?.eaasCurrency ?? 'PLN'
  };

  const response = await fetch(`${API_URLS.economics}/eaas-monthly`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`EaaS backend error: ${response.status} ${text}`);
  }

  return response.json();
}

/**
 * Calculate full EaaS investment model with monthly cash flows
 *
 * This is the complete investor model including:
 * - Monthly cash flows
 * - CIT tax with depreciation shield
 * - Debt financing (optional)
 * - CPI indexation with floor/cap
 * - Project IRR and Equity IRR
 * - Residual value
 *
 * @param {number} capacityKw - Installation capacity in kW
 * @param {number} annualEnergyMWh - Annual energy delivered to client [MWh]
 * @param {object} settings - System settings with all EaaS parameters
 * @param {object} economicParams - Economic parameters
 * @param {object} bessData - BESS data (power_kw, energy_kwh) or null if no BESS
 * @returns {object} - Full model results
 */
function calculateEaasFullModel(capacityKw, annualEnergyMWh, settings, economicParams, bessData = null) {
  console.log(`\n📊 ========== PEŁNY MODEL EaaS ==========`);
  console.log(`   Moc PV: ${capacityKw} kW, Energia roczna: ${annualEnergyMWh?.toFixed(0) || 'N/A'} MWh`);
  if (bessData && bessData.bess_energy_kwh > 0) {
    console.log(`   BESS: ${bessData.bess_power_kw?.toFixed(0) || 0} kW / ${bessData.bess_energy_kwh?.toFixed(0) || 0} kWh`);
  }

  // ========== PARAMETERS ==========
  const currency = settings.eaasCurrency || 'PLN';
  const irrDriver = settings.irrDriver || 'PLN';
  const N_contract = settings.eaasDuration || 10;
  const N_project = settings.projectLifetime || 25;
  const indexationType = settings.eaasIndexation || 'fixed';

  // Target IRR
  const targetIrr = irrDriver === 'PLN'
    ? pctToDecimal(settings.eaasTargetIrrPln || 12.0)
    : pctToDecimal(settings.eaasTargetIrrEur || 10.0);

  // CPI
  const cpi = irrDriver === 'PLN'
    ? pctToDecimal(settings.cpiPln || 2.5)
    : pctToDecimal(settings.cpiEur || 2.0);
  const cpiFloor = pctToDecimal(settings.cpiFloor || 0);
  const cpiCapAnnual = pctToDecimal(settings.cpiCapAnnual || 5.0);
  const cpiCapTotal = pctToDecimal(settings.cpiCapTotal || 50.0);

  // Tax & Depreciation
  const citRate = pctToDecimal(settings.citRate || 19.0);
  const depPeriod = settings.depreciationPeriod || 20;

  // Financing
  const leverageRatio = pctToDecimal(settings.leverageRatio || 0);
  const costOfDebt = pctToDecimal(settings.costOfDebt || 7.0);
  const debtTenor = settings.debtTenor || 8;
  const debtGracePeriod = settings.debtGracePeriod || 0;
  const debtAmortization = settings.debtAmortization || 'annuity';

  // Technical
  const availability = pctToDecimal(settings.availabilityFactor || 98.0);
  const degradationRate = window.economicsSettings?.degradationRate || pctToDecimal(settings.degradationRate || 0.5);
  const expectedLossRate = pctToDecimal(settings.expectedLossRate || 0);

  // FX
  const fxPlnEur = settings.fxPlnEur || 4.5;

  // ========== PV CAPEX ==========
  const capexPerKwp = getCapexForCapacity(capacityKw);
  const pvCapex = capacityKw * capexPerKwp;

  // ========== BESS CAPEX ==========
  let bessCapex = 0;
  let bessPowerKw = 0;
  let bessEnergyKwh = 0;
  if (bessData && bessData.bess_energy_kwh > 0) {
    bessPowerKw = bessData.bess_power_kw || 0;
    bessEnergyKwh = bessData.bess_energy_kwh || 0;
    // BESS cost: PLN per kWh capacity + PLN per kW power
    const bessCapexPerKwh = settings.bessCapexPerKwh || economicParams?.bess_capex_per_kwh || 750;
    const bessCapexPerKw = settings.bessCapexPerKw || economicParams?.bess_capex_per_kw || 100;
    bessCapex = bessEnergyKwh * bessCapexPerKwh + bessPowerKw * bessCapexPerKw;
  }

  // ========== TOTAL CAPEX ==========
  const totalCapex = pvCapex + bessCapex;

  // ========== PV OPEX (annual) ==========
  const opexPerKwp = economicParams?.opex_per_kwp || settings.opexPerKwp || 15;
  const insuranceRate = getInsuranceRate(settings);
  const landLeasePerKwp = settings.landLeasePerKwp || 0;

  const annualOM = capacityKw * opexPerKwp;
  const annualInsurance = pvCapex * insuranceRate;  // Insurance on PV only
  const annualLandLease = capacityKw * landLeasePerKwp;
  const pvOpex = annualOM + annualInsurance + annualLandLease;

  // ========== BESS OPEX (annual) ==========
  let bessOpex = 0;
  if (bessCapex > 0) {
    // BESS O&M: typically 1-2% of BESS CAPEX per year
    const bessOpexRate = settings.bessOpexRate || economicParams?.bess_opex_rate || 0.015; // 1.5% default
    bessOpex = bessCapex * bessOpexRate;
  }

  // ========== TOTAL OPEX ==========
  const baseOpex = pvOpex + bessOpex;

  // ========== DEPRECIATION ==========
  const annualDepreciation = totalCapex / depPeriod;

  // ========== DEBT ==========
  const debtAmount = totalCapex * leverageRatio;
  const equityAmount = totalCapex - debtAmount;

  console.log(`\n📋 PARAMETRY WEJŚCIOWE:`);
  console.log(`   PV CAPEX: ${(pvCapex/1e6).toFixed(2)} mln PLN (${capexPerKwp} PLN/kWp × ${capacityKw} kW)`);
  if (bessCapex > 0) {
    console.log(`   BESS CAPEX: ${(bessCapex/1e6).toFixed(2)} mln PLN (${bessPowerKw.toFixed(0)} kW / ${bessEnergyKwh.toFixed(0)} kWh)`);
  }
  console.log(`   TOTAL CAPEX: ${(totalCapex/1e6).toFixed(2)} mln PLN`);
  console.log(`   OPEX bazowy: ${(baseOpex/1e3).toFixed(0)} tys. PLN/rok (PV: ${(pvOpex/1e3).toFixed(0)}, BESS: ${(bessOpex/1e3).toFixed(0)})`);
  console.log(`   Amortyzacja: ${(annualDepreciation/1e3).toFixed(0)} tys. PLN/rok (${depPeriod} lat)`);
  console.log(`   Leverage: ${(leverageRatio*100).toFixed(0)}% → Dług: ${(debtAmount/1e6).toFixed(2)} mln, Equity: ${(equityAmount/1e6).toFixed(2)} mln`);
  console.log(`   Target IRR: ${(targetIrr*100).toFixed(1)}% (${irrDriver})`);
  console.log(`   Okres kontraktu: ${N_contract} lat, Życie projektu: ${N_project} lat`);

  // ========== SOLVER: Find subscription that achieves target IRR ==========

  // Binary search for annual subscription
  // Upper bound: annuity payment that would return CAPEX + target profit over contract period
  // A_high = CAPEX * annuity_factor where annuity_factor = r*(1+r)^N / ((1+r)^N - 1)
  const annuityFactor = targetIrr > 0
    ? (targetIrr * Math.pow(1 + targetIrr, N_contract)) / (Math.pow(1 + targetIrr, N_contract) - 1)
    : 1 / N_contract;
  let A_low = baseOpex; // At minimum, cover OPEX
  let A_high = totalCapex * annuityFactor * 1.5 + baseOpex; // CAPEX annuity + OPEX + 50% margin
  const tolerance = 100; // PLN tolerance
  let iterations = 0;
  const maxIterations = 100;

  function buildCashFlows(annualSubscriptionYear1) {
    const monthlyFlows = [];
    let cumulativeCpi = 1;
    let debtBalance = debtAmount;
    let remainingDepreciation = totalCapex;

    // Month 0: Initial investment
    monthlyFlows.push({
      month: 0,
      capex: -totalCapex,
      debtDraw: debtAmount,
      cfProject: -totalCapex,
      cfEquity: -equityAmount
    });

    // Calculate debt payment (if leverage > 0)
    let monthlyDebtPayment = 0;
    let principalPayment = 0;
    if (debtAmount > 0 && debtTenor > 0) {
      const monthlyRate = costOfDebt / 12;
      const debtMonths = debtTenor * 12;
      if (debtAmortization === 'annuity') {
        monthlyDebtPayment = debtAmount * (monthlyRate * Math.pow(1 + monthlyRate, debtMonths)) / (Math.pow(1 + monthlyRate, debtMonths) - 1);
      } else {
        // Linear
        principalPayment = debtAmount / debtMonths;
      }
    }

    // EaaS model: cash flows only during contract period (ESCO perspective)
    // After contract ends, asset is transferred to client or sold (residual value)
    const modelDuration = N_contract; // Use contract duration, not project lifetime

    // Months 1 to N_contract * 12
    for (let m = 1; m <= modelDuration * 12; m++) {
      const yearIndex = Math.floor((m - 1) / 12); // 0-indexed year
      const monthInYear = (m - 1) % 12;

      // CPI factor (apply at start of each year after year 1)
      if (monthInYear === 0 && yearIndex > 0 && indexationType === 'cpi') {
        const effectiveCpi = Math.min(Math.max(cpi, cpiFloor), cpiCapAnnual);
        const newCumulativeCpi = cumulativeCpi * (1 + effectiveCpi);
        // Apply total cap
        cumulativeCpi = Math.min(newCumulativeCpi, 1 + cpiCapTotal);
      }

      // Revenue from subscription
      let subscription = (annualSubscriptionYear1 / 12) * cumulativeCpi;
      // Apply expected loss
      subscription *= (1 - expectedLossRate);

      // OPEX (grows with CPI)
      const monthlyOpex = (baseOpex / 12) * cumulativeCpi;

      // Energy with degradation (for reporting)
      const energyFactor = Math.pow(1 - degradationRate, yearIndex) * availability;

      // EBITDA
      const ebitda = subscription - monthlyOpex;

      // Depreciation (monthly) - only if within depreciation period
      const monthlyDep = yearIndex < depPeriod ? annualDepreciation / 12 : 0;
      remainingDepreciation = Math.max(0, remainingDepreciation - monthlyDep);

      // EBIT
      const ebit = ebitda - monthlyDep;

      // Interest and principal
      let interest = 0;
      let principal = 0;
      if (debtBalance > 0) {
        interest = debtBalance * (costOfDebt / 12);

        if (m > debtGracePeriod * 12 && m <= debtTenor * 12) {
          if (debtAmortization === 'annuity') {
            principal = Math.min(monthlyDebtPayment - interest, debtBalance);
          } else {
            principal = Math.min(principalPayment, debtBalance);
          }
          debtBalance -= principal;
        }
      }

      // Tax base (EBIT - interest, but floored at 0)
      const taxBase = Math.max(0, ebit - interest);
      const tax = taxBase * citRate;

      // Cash flows
      const cfProject = ebitda - tax;
      const cfEquity = ebitda - tax - interest - principal;

      monthlyFlows.push({
        month: m,
        year: yearIndex + 1,
        subscription,
        opex: monthlyOpex,
        ebitda,
        depreciation: monthlyDep,
        ebit,
        interest,
        principal,
        tax,
        cfProject,
        cfEquity,
        debtBalance,
        cumulativeCpi,
        energyFactor
      });
    }

    // Add residual value at end of contract
    // Per contract terms: client can buy installation for 1 PLN/kWp after contract ends
    // This is symbolic value - no significant residual value for ESCO
    const residualValuePerKwp = 1; // PLN/kWp - contractual buyout price
    const residualValue = capacityKw * residualValuePerKwp;

    if (monthlyFlows.length > 0) {
      const lastMonth = monthlyFlows[monthlyFlows.length - 1];
      lastMonth.residualValue = residualValue;
      lastMonth.residualNote = `Wykup przez klienta: ${residualValuePerKwp} PLN/kWp`;
      lastMonth.cfProject += residualValue;
      lastMonth.cfEquity += residualValue;
    }

    return monthlyFlows;
  }

  function calculateXIRR(flows, cfType = 'cfEquity') {
    // Simplified IRR calculation using Newton-Raphson on monthly cash flows
    const cfs = flows.map(f => f[cfType] || 0);

    // Convert to annual for simpler calculation
    // Number of years = number of flows / 12 (month 0 is year 0, months 1-12 is year 1, etc.)
    const numYears = Math.ceil((cfs.length - 1) / 12);
    const annualCfs = [];

    for (let y = 0; y <= numYears; y++) {
      let yearCf = 0;
      if (y === 0) {
        yearCf = cfs[0] || 0;
      } else {
        const startMonth = (y - 1) * 12 + 1;
        const endMonth = y * 12;
        for (let m = startMonth; m <= Math.min(endMonth, cfs.length - 1); m++) {
          yearCf += cfs[m] || 0;
        }
      }
      annualCfs.push(yearCf);
    }

    // Newton-Raphson IRR
    let irr = targetIrr; // Start with target IRR as initial guess
    for (let iter = 0; iter < 200; iter++) {
      let npv = 0;
      let dnpv = 0;
      for (let t = 0; t < annualCfs.length; t++) {
        const factor = Math.pow(1 + irr, t);
        npv += annualCfs[t] / factor;
        if (t > 0) dnpv -= t * annualCfs[t] / Math.pow(1 + irr, t + 1);
      }
      if (Math.abs(npv) < 1) break;
      if (Math.abs(dnpv) < 0.0001) break;
      irr = irr - npv / dnpv;
      if (irr < -0.99) irr = -0.99;
      if (irr > 2) irr = 2;
    }
    return irr;
  }

  // Binary search for target IRR
  while (A_high - A_low > tolerance && iterations < maxIterations) {
    const A_mid = (A_low + A_high) / 2;
    const flows = buildCashFlows(A_mid);
    const irr = calculateXIRR(flows, leverageRatio > 0 ? 'cfEquity' : 'cfProject');

    if (irr < targetIrr) {
      A_low = A_mid;
    } else {
      A_high = A_mid;
    }
    iterations++;
  }

  const optimalSubscription = (A_low + A_high) / 2;
  const finalFlows = buildCashFlows(optimalSubscription);
  const projectIrr = calculateXIRR(finalFlows, 'cfProject');
  const equityIrr = leverageRatio > 0 ? calculateXIRR(finalFlows, 'cfEquity') : projectIrr;

  // ========== RESULTS ==========
  const monthlySubscription = optimalSubscription / 12;
  const pricePerMWh = annualEnergyMWh > 0 ? optimalSubscription / annualEnergyMWh : 0;

  // Sum up contract period revenues and costs
  let totalRevenue = 0;
  let totalOpex = 0;
  let totalTax = 0;
  let totalInterest = 0;
  for (let m = 1; m <= N_contract * 12; m++) {
    const f = finalFlows[m];
    if (f) {
      totalRevenue += f.subscription || 0;
      totalOpex += f.opex || 0;
      totalTax += f.tax || 0;
      totalInterest += f.interest || 0;
    }
  }

  // Convert to contract currency if EUR
  const currencyMultiplier = currency === 'EUR' ? 1 / fxPlnEur : 1;
  const currencyDisplay = currency;

  console.log(`\n✅ WYNIKI SOLVERA (${iterations} iteracji):`);
  console.log(`   Abonament roczny (rok 1): ${plnToTysPln(optimalSubscription * currencyMultiplier).toFixed(0)} tys. ${currencyDisplay}`);
  console.log(`   Abonament miesięczny: ${plnToTysPln(monthlySubscription * currencyMultiplier).toFixed(1)} tys. ${currencyDisplay}`);
  console.log(`   Cena EaaS: ${(pricePerMWh * currencyMultiplier).toFixed(0)} ${currencyDisplay}/MWh`);
  console.log(`   Project IRR: ${decimalToPct(projectIrr).toFixed(2)}%`);
  console.log(`   Equity IRR: ${decimalToPct(equityIrr).toFixed(2)}%`);
  console.log(`   Przychód kontraktowy: ${(totalRevenue * currencyMultiplier / 1e6).toFixed(2)} mln ${currencyDisplay}`);

  return {
    // Subscription
    annualSubscription: optimalSubscription * currencyMultiplier,
    annualSubscriptionPLN: optimalSubscription,
    monthlySubscription: monthlySubscription * currencyMultiplier,
    pricePerMWh: pricePerMWh * currencyMultiplier,

    // IRR
    projectIrr,
    equityIrr,
    targetIrr,

    // Financials
    totalCapex: totalCapex * currencyMultiplier,
    totalCapexPLN: totalCapex,
    debtAmount: debtAmount * currencyMultiplier,
    equityAmount: equityAmount * currencyMultiplier,
    totalRevenue: totalRevenue * currencyMultiplier,
    totalOpex: totalOpex * currencyMultiplier,
    totalTax: totalTax * currencyMultiplier,
    totalInterest: totalInterest * currencyMultiplier,

    // Parameters
    currency: currencyDisplay,
    irrDriver,
    contractDuration: N_contract,
    projectLifetime: N_project,
    indexationType,
    leverageRatio: leverageRatio * 100,
    citRate: citRate * 100,
    expectedLossRate: expectedLossRate * 100,
    degradationRate: degradationRate * 100,

    // Residual value
    residualValue: capacityKw * 1, // 1 PLN/kWp buyout
    residualValueNote: 'Opcja wykupu przez klienta: 1 PLN/kWp',

    // Monthly flows (for detailed analysis)
    monthlyFlows: finalFlows,

    // Solver info
    solverIterations: iterations
  };
}

/**
 * Calculate EaaS annual subscription to achieve target IRR (LEGACY - simplified model)
 *
 * Implements financial model with proper annuity formula:
 * - FIXED mode: A = O + I₀ · [r(1+r)^N] / [(1+r)^N - 1]
 * - CPI mode: A_real = O_real + I₀ · [r_real(1+r_real)^N] / [(1+r_real)^N - 1]
 *              where r_real = (1+r)/(1+g) - 1
 *
 * @param {number} capacityKw - Installation capacity in kW
 * @param {object} settings - System settings with EaaS parameters
 * @param {object} economicParams - Economic parameters (OPEX, degradation, etc.)
 * @param {object} variant - Optional variant data with BESS info
 * @returns {object} - { annualSubscription, monthlySubscription, totalRevenue, irr, pricePerMWh }
 */
function calculateEaasSubscription(capacityKw, settings, economicParams, variant = null) {
  console.log(`\n📊 Calculating EaaS subscription for ${capacityKw} kW installation`);

  // ========== INPUTS ==========
  const currency = settings.eaasCurrency || 'PLN';
  const N = settings.eaasDuration || 10; // Contract duration [years]
  const indexationType = settings.eaasIndexation || 'fixed'; // 'fixed' or 'cpi'

  // Target IRR (nominal)
  const r = currency === 'PLN'
    ? pctToDecimal(settings.eaasTargetIrrPln || 12.0)
    : pctToDecimal(settings.eaasTargetIrrEur || 10.0);

  // CPI inflation rates - use unified inflationRate from financial parameters
  const systemInflationRate = window.economicsSettings?.inflationRate;
  const g_PLN = systemInflationRate; // Use system-wide inflation rate for PLN
  const g_EUR = pctToDecimal(settings.cpiEur || 2.0); // Keep separate EUR inflation if needed
  const g = currency === 'PLN' ? g_PLN : g_EUR;

  // FX rate
  const FX_PLN_EUR = settings.fxPlnEur || 4.5;

  // ========== CAPEX (in PLN - base currency) ==========
  // PV CAPEX
  const capexPerKwp = getCapexForCapacity(capacityKw);
  const capexPV_PLN = capacityKw * capexPerKwp;

  // BESS CAPEX (if present in variant)
  let capexBESS_PLN = 0;
  let opexBESS_PLN = 0;
  const hasBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  if (hasBess) {
    const bessCapexPerKwh = settings.bessCapexPerKwh || 1500;
    const bessCapexPerKw = settings.bessCapexPerKw || 300;
    const bessOpexPctPerYear = settings.bessOpexPctPerYear || 1.5;
    capexBESS_PLN = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);
    opexBESS_PLN = capexBESS_PLN * pctToDecimal(bessOpexPctPerYear);
  }

  // Total CAPEX = PV + BESS
  const I0_PLN = capexPV_PLN + capexBESS_PLN;

  // ========== OPEX (in PLN - base currency) ==========
  const opexPerKwp = economicParams.opex_per_kwp || settings.opexPerKwp || 15;
  const insuranceRate = getInsuranceRate(settings); // normalized decimal (e.g., 0.005 = 0.5%)
  const landLeasePerKwp = settings.landLeasePerKwp || 0; // Land lease cost per kWp [PLN/kWp/year]

  const annualOM_PLN = capacityKw * opexPerKwp; // O&M
  const annualInsurance_PLN = I0_PLN * insuranceRate; // Insurance (on total CAPEX including BESS)
  const annualLandLease_PLN = capacityKw * landLeasePerKwp; // Land lease
  const O_PLN = annualOM_PLN + annualInsurance_PLN + annualLandLease_PLN + opexBESS_PLN; // Total annual OPEX including BESS

  console.log(`  📋 INPUTS:`);
  console.log(`     Waluta: ${currency}`);
  console.log(`     Okres umowy: ${N} lat`);
  console.log(`     Typ opłaty: ${indexationType}`);
  console.log(`     Target IRR: ${decimalToPct(r).toFixed(1)}%`);
  console.log(`     Inflacja (CPI ${currency}): ${decimalToPct(g).toFixed(1)}%`);
  console.log(`  `);
  console.log(`  💰 PARAMETRY (waluta bazowa PLN):`);
  console.log(`     CAPEX (I₀): ${plnToMlnPln(I0_PLN).toFixed(2)} mln PLN (${capexPerKwp} PLN/kWp)`);
  if (hasBess) {
    console.log(`       - PV CAPEX: ${plnToMlnPln(capexPV_PLN).toFixed(2)} mln PLN`);
    console.log(`       - BESS CAPEX: ${plnToMlnPln(capexBESS_PLN).toFixed(2)} mln PLN`);
  }
  console.log(`     OPEX (O): ${O_PLN.toFixed(0)} PLN/rok`);
  console.log(`       - O&M: ${annualOM_PLN.toFixed(0)} PLN/rok`);
  console.log(`       - Ubezpieczenie: ${annualInsurance_PLN.toFixed(0)} PLN/rok`);
  if (annualLandLease_PLN > 0) {
    console.log(`       - Najem powierzchni: ${annualLandLease_PLN.toFixed(0)} PLN/rok`);
  }
  if (opexBESS_PLN > 0) {
    console.log(`       - BESS OPEX: ${opexBESS_PLN.toFixed(0)} PLN/rok`);
  }
  console.log(`  `);

  let A_PLN; // Annual subscription in PLN (base currency)
  let calculationMode = '';

  // ========== CALCULATION ==========
  if (indexationType === 'fixed') {
    // ========== FIXED MODE ==========
    // Formula: A = O + I₀ · [r(1+r)^N] / [(1+r)^N - 1]
    calculationMode = 'FIXED (stała kwota nominalna)';

    const factor = Math.pow(1 + r, N);
    const annuity_factor = (r * factor) / (factor - 1);

    A_PLN = O_PLN + I0_PLN * annuity_factor;

    console.log(`  🔢 LOGIKA FIXED:`);
    console.log(`     A = O + I₀ · [r(1+r)^N] / [(1+r)^N - 1]`);
    console.log(`     A = ${O_PLN.toFixed(0)} + ${I0_PLN.toFixed(0)} · ${annuity_factor.toFixed(6)}`);
    console.log(`     A = ${A_PLN.toFixed(0)} PLN/rok`);

  } else {
    // ========== CPI MODE ==========
    // Real rate: r_real = (1+r)/(1+g) - 1
    // Formula: A_real = O_real + I₀ · [r_real(1+r_real)^N] / [(1+r_real)^N - 1]
    // Nominal subscription in year 1: A₁ = A_real
    calculationMode = 'CPI (indeksacja inflacją)';

    const r_real = (1 + r) / (1 + g) - 1;

    // Assume O_real ≈ current OPEX (real terms)
    const O_real_PLN = O_PLN;

    const factor_real = Math.pow(1 + r_real, N);
    const annuity_factor_real = (r_real * factor_real) / (factor_real - 1);

    const A_real_PLN = O_real_PLN + I0_PLN * annuity_factor_real;

    // Nominal subscription in year 1 (same as real in year 1)
    A_PLN = A_real_PLN;

    console.log(`  🔢 LOGIKA CPI:`);
    console.log(`     r_real = (1+r)/(1+g) - 1 = ${decimalToPct(r_real).toFixed(3)}%`);
    console.log(`     A_real = O_real + I₀ · [r_real(1+r_real)^N] / [(1+r_real)^N - 1]`);
    console.log(`     A_real = ${O_real_PLN.toFixed(0)} + ${I0_PLN.toFixed(0)} · ${annuity_factor_real.toFixed(6)}`);
    console.log(`     A₁ (nominal, rok 1) = ${A_PLN.toFixed(0)} PLN/rok`);
    console.log(`     (W kolejnych latach: A₂ = A₁·(1+g), A₃ = A₁·(1+g)², ...)`);
  }

  console.log(`  `);

  // ========== CURRENCY CONVERSION ==========
  let A_contract, A_monthly_contract, currency_display;

  if (currency === 'EUR') {
    A_contract = A_PLN / FX_PLN_EUR;
    A_monthly_contract = A_contract / 12;
    currency_display = 'EUR';

    console.log(`  💱 KONWERSJA WALUTY:`);
    console.log(`     Abonament roczny (PLN): ${A_PLN.toFixed(0)} PLN/rok`);
    console.log(`     Kurs FX: ${FX_PLN_EUR}`);
    console.log(`     Abonament roczny (EUR): ${A_contract.toFixed(0)} EUR/rok`);
    console.log(`     Abonament miesięczny: ${A_monthly_contract.toFixed(0)} EUR/mies`);
  } else {
    A_contract = A_PLN;
    A_monthly_contract = A_PLN / 12;
    currency_display = 'PLN';

    console.log(`  💵 WYNIK (PLN):`);
    console.log(`     Abonament roczny: ${A_contract.toFixed(0)} PLN/rok`);
    console.log(`     Abonament miesięczny: ${A_monthly_contract.toFixed(0)} PLN/mies`);
  }

  // ========== TOTAL REVENUE & VERIFICATION ==========
  let totalRevenue_contract = 0;
  const cashFlows = [-I0_PLN]; // Year 0: Investment

  for (let year = 1; year <= N; year++) {
    let yearlySubscription_PLN;

    if (indexationType === 'cpi') {
      // CPI-indexed: grows with inflation
      yearlySubscription_PLN = A_PLN * Math.pow(1 + g, year - 1);
    } else {
      // Fixed: constant nominal
      yearlySubscription_PLN = A_PLN;
    }

    const yearlyOpex_PLN = O_PLN * Math.pow(1 + g, year - 1); // OPEX grows with inflation
    const netCashFlow = yearlySubscription_PLN - yearlyOpex_PLN;
    cashFlows.push(netCashFlow);

    const yearlySubscription_contract = currency === 'EUR'
      ? yearlySubscription_PLN / FX_PLN_EUR
      : yearlySubscription_PLN;
    totalRevenue_contract += yearlySubscription_contract;
  }

  // Verify IRR
  // Note: This calculates ESCO's IRR over contract period only (conservative approach)
  // In reality, ESCO may have residual value considerations, but this ensures subscription covers costs
  const achievedIRR = calculateIRR(
    cashFlows.slice(1).map((cf, idx) => ({ year: idx + 1, net_cash_flow: cf })),
    I0_PLN
  );

  console.log(`  `);
  console.log(`  ✅ PODSUMOWANIE:`);
  console.log(`     Abonament roczny (rok 1): ${A_contract.toLocaleString('pl-PL', {maximumFractionDigits: 0})} ${currency_display}/rok`);
  console.log(`     Abonament miesięczny: ${A_monthly_contract.toLocaleString('pl-PL', {maximumFractionDigits: 0})} ${currency_display}/mies`);
  console.log(`     Całkowity przychód (${N} lat): ${plnToMlnPln(totalRevenue_contract).toFixed(2)} mln ${currency_display}`);
  console.log(`     Osiągnięte IRR: ${decimalToPct(achievedIRR).toFixed(2)}% (target: ${decimalToPct(r).toFixed(1)}%)`);
  console.log(`     Tryb: ${calculationMode}`);

  return {
    annualSubscription: A_contract,
    annualSubscriptionPLN: A_PLN,  // ALWAYS in PLN for internal calculations
    monthlySubscription: A_monthly_contract,
    totalRevenue: totalRevenue_contract,
    irr: achievedIRR,
    capex: currency === 'EUR' ? I0_PLN / FX_PLN_EUR : I0_PLN,
    duration: N,
    currency: currency_display,
    indexation: indexationType,
    mode: calculationMode,
    fxRate: FX_PLN_EUR  // Include FX rate for reference
  };
}

// Check for data on load
document.addEventListener('DOMContentLoaded', () => {
  console.log('📱 DOMContentLoaded event fired in economics.js');

  // Run LCOE validation tests (only logs to console)
  // Validates that LCOE calculations are mathematically correct
  try {
    validateLCOECalculations();
  } catch (e) {
    console.error('❌ LCOE Validation failed:', e);
  }

  // Show loading state first
  showLoadingState();

  // Request shared data and settings from parent shell FIRST
  // Data from shell has priority over localStorage
  requestSharedData();
  requestSettingsFromShell();

  // CRITICAL: Fetch consumption statistics from backend directly
  // This ensures we have annual_consumption_kwh even if CONFIG didn't send it
  fetchConsumptionStatistics();

  // Fallback: try to load from localStorage after a short delay
  // (in case shell doesn't respond)
  setTimeout(() => {
    if (!analysisResults || Object.keys(variants).length === 0) {
      console.log('⏳ No data from shell yet, trying localStorage...');
      loadAllData();
    }
  }, 500);
});

// Fetch consumption statistics directly from data-analysis backend
async function fetchConsumptionStatistics() {
  try {
    const response = await fetch('/api/data/statistics');
    if (!response.ok) {
      console.log('📊 No consumption statistics available from backend');
      return;
    }
    const stats = await response.json();
    console.log('📊 Fetched consumption statistics from backend:', stats);

    // Store in consumptionData if not already set or missing annual_consumption_kwh
    if (!consumptionData) {
      consumptionData = {};
    }
    if (!consumptionData.annual_consumption_kwh && stats.total_consumption_gwh) {
      consumptionData.annual_consumption_kwh = stats.total_consumption_gwh * 1000000; // GWh -> kWh
      consumptionData.total_consumption_gwh = stats.total_consumption_gwh;
      console.log('📊 Set annual_consumption_kwh from backend:', consumptionData.annual_consumption_kwh, 'kWh');
    }
  } catch (error) {
    console.log('📊 Could not fetch consumption statistics:', error.message);
  }
}

// Show loading state
function showLoadingState() {
  const noDataDiv = document.getElementById('noData');
  const contentDiv = document.getElementById('economicsContent');

  if (noDataDiv) {
    noDataDiv.innerHTML = `
      <div style="text-align:center;padding:40px">
        <div style="font-size:24px;margin-bottom:10px">⏳</div>
        <h3>Ładowanie danych...</h3>
        <p style="color:#888">Pobieranie wyników analizy</p>
      </div>
    `;
    noDataDiv.style.display = 'block';
  }
  if (contentDiv) {
    contentDiv.style.display = 'none';
  }
}

// Request shared data from shell
function requestSharedData() {
  if (window.parent !== window) {
    console.log('📤 Requesting shared data from shell...');
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  }
}

// Request settings from shell
function requestSettingsFromShell() {
  if (window.parent !== window) {
    console.log('📤 Requesting settings from shell...');
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  }
}

// Apply settings from Settings module to UI
function applySettingsToUI(settings) {
  if (!settings) return;

  // Invalidate caches — settings changed
  invalidateConsumptionCache();
  invalidateCapexCache();

  // Energy tariff components
  const energyActive = document.getElementById('energyActive');
  if (energyActive) energyActive.value = settings.energyActive || 550;

  const distribution = document.getElementById('distribution');
  if (distribution) distribution.value = settings.distribution || 200;

  const qualityFee = document.getElementById('qualityFee');
  if (qualityFee) qualityFee.value = settings.qualityFee || 10;

  const ozeFee = document.getElementById('ozeFee');
  if (ozeFee) ozeFee.value = settings.ozeFee || 7;

  const cogenerationFee = document.getElementById('cogenerationFee');
  if (cogenerationFee) cogenerationFee.value = settings.cogenerationFee || 10;

  const capacityFee = document.getElementById('capacityFee');
  if (capacityFee) capacityFee.value = settings.capacityFee || 219;

  const exciseTax = document.getElementById('exciseTax');
  if (exciseTax) exciseTax.value = settings.exciseTax || 5;

  // OPEX and financial params
  const opexPerKwp = document.getElementById('opexPerKwp');
  if (opexPerKwp) opexPerKwp.value = settings.opexPerKwp || 15;

  const degradationRate = document.getElementById('degradationRate');
  if (degradationRate) degradationRate.value = settings.degradationRate || 0.5;

  const analysisPeriod = document.getElementById('analysisPeriod');
  if (analysisPeriod) analysisPeriod.value = settings.analysisPeriod || 25;

  // EaaS parameters
  const eaasSubscription = document.getElementById('eaasSubscription');
  if (eaasSubscription) eaasSubscription.value = settings.eaasSubscription || 800000;

  const eaasOM = document.getElementById('eaasOM');
  if (eaasOM) eaasOM.value = settings.eaasOM || 24;

  const eaasDuration = document.getElementById('eaasDuration');
  if (eaasDuration) eaasDuration.value = settings.eaasDuration || 10;

  // Store discount rate and other financial params for calculations
  if (typeof window.economicsSettings === 'undefined') {
    window.economicsSettings = {};
  }
  window.economicsSettings.discountRate = pctToDecimal(settings.discountRate);
  window.economicsSettings.insuranceRate = getInsuranceRate(settings);
  window.economicsSettings.inflationRate = pctToDecimal(settings.inflationRate);
  window.economicsSettings.degradationRate = pctToDecimal(settings.degradationRate);       // PV annual years 2+ [decimal]
  window.economicsSettings.pvDegradationYear1 = pctToDecimal(settings.pvDegradationYear1); // LID [decimal]
  window.economicsSettings.opexPerKwp = settings.opexPerKwp;   // PLN/kWp/year
  window.economicsSettings.analysisPeriod = settings.analysisPeriod; // years
  window.economicsSettings.eaasIndexation = settings.eaasIndexation || 'fixed';
  // IRR calculation mode
  window.economicsSettings.useInflation = settings.useInflation || false;
  window.economicsSettings.irrMode = settings.irrMode || (settings.useInflation ? 'nominal' : 'real');
  window.economicsSettings.bessLifetimeYears = settings.bessLifetimeYears;

  // Production scenario factors — from USTAWIENIA (SSoT)
  window.productionFactors = {
    P50: settings.productionFactorP50 ?? 1.00,
    P75: settings.productionFactorP75 ?? 0.97,
    P90: settings.productionFactorP90 ?? 0.94
  };

  // Calculate and store total energy price (all components including capacity fee)
  // Used by LCOE chart for grid price reference line
  // Energia czynna teraz pochodzi ze średniej stawki ToU (trzystrefowa/dwustrefowa/jednolita)
  const params = getEconomicParameters();
  window.economicsSettings.totalEnergyPrice = calculateTotalEnergyPrice(params);

  // Store tariffConfig for reference
  window.economicsSettings.tariffConfig = settings.tariffConfig;

  console.log('📊 Applied settings to Economics UI:', {
    totalEnergyPrice: window.economicsSettings.totalEnergyPrice,
    discountRate: window.economicsSettings.discountRate,
    eaasSubscription: settings.eaasSubscription,
    eaasOM: settings.eaasOM,
    eaasIndexation: window.economicsSettings.eaasIndexation,
    useInflation: window.economicsSettings.useInflation,
    irrMode: window.economicsSettings.irrMode
  });
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  console.log('📩 economics.js received message:', event.data.type);

  switch (event.data.type) {
    case 'SHARED_DATA_RESPONSE':
      console.log('📨 SHARED_DATA_RESPONSE received:', event.data.data);
      console.log('  - Full data structure:', JSON.stringify(Object.keys(event.data.data || {})));

      if (event.data.data.analysisResults) {
        analysisResults = event.data.data.analysisResults;
        console.log('  - analysisResults loaded:', !!analysisResults);
        console.log('  - analysisResults keys:', Object.keys(analysisResults));
      }

      if (event.data.data.analysisResults?.key_variants) {
        variants = event.data.data.analysisResults.key_variants;
        console.log('  - variants loaded:', Object.keys(variants));
      } else {
        console.warn('  ⚠️ No key_variants found in analysisResults');
      }

      if (event.data.data.pvConfig) {
        // Take pvType from sharedData.pvConfig - this is updated by PV_TYPE_CHANGED in shell
        // The shell maintains the most recent pvType selection from Configuration module
        const shellPvType = event.data.data.pvConfig.pvType || event.data.data.pvConfig.pv_type;
        pvConfig = event.data.data.pvConfig;
        // Ensure both fields are set
        if (shellPvType) {
          pvConfig.pvType = shellPvType;
          pvConfig.pv_type = shellPvType;
        }
        console.log('  - pvConfig loaded:', !!pvConfig, 'pvType:', pvConfig?.pvType || pvConfig?.pv_type);
      }

      // Load hourlyData from sharedData (same field shell stores after ANALYSIS_COMPLETE)
      if (!hourlyData && event.data.data.hourlyData) {
        hourlyData = event.data.data.hourlyData;
        console.log('  - hourlyData loaded from SHARED_DATA_RESPONSE:', hourlyData?.values?.length || 'no values');
      }

      // Load consumptionData - CRITICAL for correct energy consumption values
      if (event.data.data.consumptionData) {
        consumptionData = event.data.data.consumptionData;
        invalidateConsumptionCache();
        // Calculate annual_consumption_kwh from total_consumption_gwh if not present
        if (!consumptionData.annual_consumption_kwh && consumptionData.total_consumption_gwh) {
          consumptionData.annual_consumption_kwh = consumptionData.total_consumption_gwh * 1000000;
        }
        console.log('  - consumptionData loaded:', {
          dataPoints: consumptionData.dataPoints,
          annual_consumption_kwh: consumptionData.annual_consumption_kwh,
          total_consumption_gwh: consumptionData.total_consumption_gwh
        });
      } else {
        console.warn('  ⚠️ No consumptionData in SHARED_DATA_RESPONSE!');
      }

      if (event.data.data.masterVariant) {
        // masterVariant może być stringiem ('A') lub obiektem {variant: 'A', ...}
        if (typeof event.data.data.masterVariant === 'string') {
          currentVariant = event.data.data.masterVariant;
        } else if (event.data.data.masterVariant.variant) {
          currentVariant = event.data.data.masterVariant.variant;
        }
        console.log('  - currentVariant set to:', currentVariant);
      }

      // Load settings from shared data
      if (event.data.data.settings) {
        systemSettings = event.data.data.settings;
        applySettingsToUI(systemSettings);
        console.log('  - settings loaded from sharedData:', systemSettings.totalEnergyPrice);
      }

      // Restore production scenario (P50/P75/P90) from shared data
      if (event.data.data.currentScenario && ['P50', 'P75', 'P90'].includes(event.data.data.currentScenario)) {
        const savedScenario = event.data.data.currentScenario;
        console.log(`  - restoring scenario from sharedData: ${savedScenario}`);
        window.currentProductionScenario = savedScenario;
        window.currentScenarioFactor = (window.productionFactors && window.productionFactors[savedScenario]) || 1.0;
        // Update button styles and labels
        ['P50', 'P75', 'P90'].forEach(s => {
          const btn = document.getElementById(`globalBtn${s}`);
          if (btn) {
            const isActive = s === savedScenario;
            const colors = { P50: '#27ae60', P75: '#3498db', P90: '#e74c3c' };
            btn.style.background = isActive ? colors[s] : 'white';
            btn.style.color = isActive ? 'white' : colors[s];
          }
        });
        // Update scenario labels
        const eaasLabel = document.getElementById('eaasCurrentScenario');
        if (eaasLabel) eaasLabel.textContent = savedScenario;
        const scenarioLabel = document.getElementById('eaasScenarioLabel');
        if (scenarioLabel) scenarioLabel.textContent = savedScenario;
        const factorDisplay = document.getElementById('scenarioFactorDisplay');
        if (factorDisplay) factorDisplay.textContent = `${Math.round(decimalToPct(window.currentScenarioFactor))}%`;
      }

      console.log('🚀 Calling performEconomicAnalysis() from SHARED_DATA_RESPONSE (debounced)');
      performEconomicAnalysisDebounced();
      break;

    case 'MASTER_VARIANT_CHANGED':
      console.log('🔄 Master variant changed to:', event.data.data);
      // data może być stringiem ('A') lub obiektem {variant: 'A', ...}
      if (typeof event.data.data === 'string') {
        currentVariant = event.data.data;
      } else if (event.data.data.variant) {
        currentVariant = event.data.data.variant;
      }
      console.log('  - currentVariant updated to:', currentVariant);
      // Clear PULS DNIA production cache so it reloads for new variant
      cachedHourlyProduction = null;
      console.log('  - PULS DNIA production cache cleared');
      performEconomicAnalysisDebounced();
      break;

    case 'ANALYSIS_RESULTS':
      // Received directly from shell after ANALYSIS_COMPLETE
      console.log('📊 ANALYSIS_RESULTS received from shell');
      if (event.data.data) {
        // Load analysis results
        if (event.data.data.fullResults) {
          analysisResults = event.data.data.fullResults;
          if (analysisResults.key_variants) {
            variants = analysisResults.key_variants;
          }
          console.log('  - analysisResults loaded:', Object.keys(analysisResults));
        }
        // Load PV config - use pvType from shell's sharedData
        if (event.data.data.pvConfig) {
          const shellPvType = event.data.data.pvConfig.pvType || event.data.data.pvConfig.pv_type;
          pvConfig = event.data.data.pvConfig;
          if (shellPvType) {
            pvConfig.pvType = shellPvType;
            pvConfig.pv_type = shellPvType;
          }
          console.log('  - pvConfig loaded, pvType:', pvConfig?.pvType || pvConfig?.pv_type);
        }
        // Load hourly data
        if (event.data.data.hourlyData) {
          hourlyData = event.data.data.hourlyData;
          console.log('  - hourlyData loaded');
        }
        // Load shared data (includes settings, consumptionData, profileAnalysis, etc.)
        if (event.data.data.sharedData) {
          if (event.data.data.sharedData.settings) {
            systemSettings = event.data.data.sharedData.settings;
            applySettingsToUI(systemSettings);
          }
          if (event.data.data.sharedData.consumptionData) {
            consumptionData = event.data.data.sharedData.consumptionData;
            invalidateConsumptionCache();
            // Calculate annual_consumption_kwh from total_consumption_gwh if not present
            if (!consumptionData.annual_consumption_kwh && consumptionData.total_consumption_gwh) {
              consumptionData.annual_consumption_kwh = consumptionData.total_consumption_gwh * 1000000;
            }
            console.log('  - consumptionData loaded from sharedData:', {
              annual_consumption_kwh: consumptionData.annual_consumption_kwh,
              total_consumption_gwh: consumptionData.total_consumption_gwh,
              dataPoints: consumptionData.dataPoints
            });
          }
          // Load profile analysis BESS data if available
          if (event.data.data.sharedData.profileAnalysis?.bessData) {
            profileAnalysisBessData = event.data.data.sharedData.profileAnalysis.bessData;
            console.log('  - profileAnalysisBessData loaded:', profileAnalysisBessData.bess_energy_kwh, 'kWh');
          }
        }
        console.log('🚀 Calling performEconomicAnalysis() from ANALYSIS_RESULTS (debounced)');
        performEconomicAnalysisDebounced();
      }
      break;

    case 'ECONOMIC_DATA_UPDATED':
    case 'PV_CONFIG_UPDATED':
    case 'DATA_AVAILABLE':
      console.log('🔄 Data updated, reloading...');
      loadAllData();
      break;

    case 'VARIANT_ADDED':
    case 'VARIANT_UPDATED':
      console.log('🔄 Variant change notification, reloading...');
      loadAllData();
      break;

    case 'DATA_CLEARED':
      clearAnalysis();
      clearEconomicsData();
      break;
    case 'SETTINGS_UPDATED':
      console.log('📊 Settings received from shell');
      systemSettings = event.data.data;
      // Cache priceConfig if included
      if (event.data.priceConfig) {
        window._cachedPriceConfig = event.data.priceConfig;
      }
      applySettingsToUI(systemSettings);
      // Recalculate if we have analysis data
      if (analysisResults) {
        performEconomicAnalysisDebounced();
      }
      break;
    case 'PRICE_CONFIG_UPDATED':
      console.log('📊 PriceConfig received from shell');
      if (event.data.priceConfig) {
        window._cachedPriceConfig = event.data.priceConfig;
      }
      break;

    case 'PROFILE_ANALYSIS_UPDATED':
      // Received BESS analysis results from Profile Analysis module
      console.log('📊 Profile analysis received from shell:', event.data.data);
      if (event.data.data?.bessData) {
        profileAnalysisBessData = event.data.data.bessData;

        // Log v2 payload if available
        const isV2 = profileAnalysisBessData.schema_version === 'bess_economics_v2';
        console.log('🔋 BESS data from profile analysis' + (isV2 ? ' (v2)' : '') + ':', {
          power_kw: profileAnalysisBessData.bess_power_kw,
          energy_kwh: profileAnalysisBessData.bess_energy_kwh,
          annual_cycles: profileAnalysisBessData.annual_cycles,
          annual_discharge_mwh: profileAnalysisBessData.annual_discharge_mwh,
          strategy: profileAnalysisBessData.strategy,
          ...(isV2 && {
            dispatch_mode: profileAnalysisBessData.dispatch_metadata?.dispatch_mode,
            savings_source: profileAnalysisBessData.savings_breakdown?.source,
            energy_savings: profileAnalysisBessData.savings_breakdown?.energy_savings_pln,
            demand_charge_savings: profileAnalysisBessData.savings_breakdown?.demand_charge_savings_pln,
          })
        });

        // Store config BESS data before potentially overwriting
        const variant = variants[currentVariant];
        if (variant && variant.bess_power_kw > 0 && !configBessData) {
          configBessData = {
            bess_power_kw: variant.bess_power_kw,
            bess_energy_kwh: variant.bess_energy_kwh,
            bess_cycles_equivalent: variant.bess_cycles_equivalent,
            // Store original BESS energy data for table calculations
            bess_self_consumed_from_bess_kwh: variant.bess_self_consumed_from_bess_kwh || 0,
            bess_discharged_kwh: variant.bess_discharged_kwh || 0
          };
        }

        // IMPORTANT: Update BESS source selector and auto-select profile-analysis
        // This MUST be called after profileAnalysisBessData is set!
        updateBessSourceSelector();

        // Display savings breakdown if v2 data available
        displayBessSavingsBreakdown();

        // Recalculate economics with new BESS data available
        if (analysisResults) {
          performEconomicAnalysisDebounced();
        }
      }
      break;

    case 'BESS_RESULT_UPDATED':
      // NEW: Receive BESS result from shell (Single Source of Truth)
      // This is the authoritative source from bess-dispatch via config module
      console.log('🔋 BESS result from shell (Single Source of Truth):', event.data.data);
      if (event.data.data) {
        const bessResult = event.data.data;

        // Store as primary source
        bessSizingData = {
          bess_power_kw: bessResult.recommended_power_kw,
          bess_energy_kwh: bessResult.recommended_energy_kwh,
          variants: bessResult.variants,
          period_info: bessResult.period_info,
          topology: bessResult.topology,
          timestamp: bessResult.timestamp
        };

        // If variants have detailed data, use first variant's breakdown
        if (bessResult.variants && bessResult.variants.length > 0) {
          const v = bessResult.variants[0];
          bessSizingData.bess_cycles_equivalent = v.degradation?.efc_total || v.annual_cycles || 0;
          bessSizingData.annual_discharge_mwh = kwhToMwh(v.dispatch_summary?.total_discharge_kwh || 0);
          bessSizingData.annual_savings_pln = v.annual_savings_pln;
          bessSizingData.savings_breakdown = v.savings_breakdown;
          bessSizingData.dispatch_metadata = v.dispatch_summary;
          bessSizingData.schema_version = 'bess_economics_v2';
        }

        // Set as authoritative source
        currentBessSource = 'bess-sizing';
        console.log('✅ BESS result stored as AUTHORITATIVE source (from config)');

        // Update UI
        updateBessSourceSelector();
        displayBessSavingsBreakdown();

        // Apply to variant and recalculate
        applyBessSourceToVariant();
        if (analysisResults) {
          performEconomicAnalysisDebounced();
        }
      }
      break;

    case 'BESS_SIZING_UPDATED':
      // LEGACY: B1: Received BESS sizing results from BESS PRO module (v2 payload)
      // This is kept for backward compatibility
      console.log('📊 BESS sizing received from shell:', event.data.data);
      if (event.data.data?.bessData) {
        const bessProData = event.data.data.bessData;

        // Log v2 payload
        const isV2 = bessProData.schema_version === 'bess_economics_v2';
        console.log('🔋 BESS PRO data (AUTHORITATIVE)' + (isV2 ? ' (v2)' : '') + ':', {
          power_kw: bessProData.bess_power_kw,
          energy_kwh: bessProData.bess_energy_kwh,
          annual_savings_pln: bessProData.annual_savings_pln,
          net_savings_pln: bessProData.savings_breakdown?.net_savings_pln,
          savings_source: bessProData.savings_breakdown?.source,
          dispatch_mode: bessProData.dispatch_metadata?.dispatch_mode,
        });

        // B1: Store in bessSizingData (separate from estimated configBessData)
        bessSizingData = {
          bess_power_kw: bessProData.bess_power_kw,
          bess_energy_kwh: bessProData.bess_energy_kwh,
          bess_cycles_equivalent: bessProData.annual_cycles,
          bess_self_consumed_from_bess_kwh: (bessProData.annual_discharge_mwh || 0) * 1000,
          annual_discharge_mwh: bessProData.annual_discharge_mwh,
          annual_savings_pln: bessProData.annual_savings_pln,
          // v2 fields
          schema_version: bessProData.schema_version,
          savings_breakdown: bessProData.savings_breakdown,
          prices_summary: bessProData.prices_summary,
          dispatch_metadata: bessProData.dispatch_metadata,
        };

        // B1: Auto-select bess-sizing as primary source (it's authoritative)
        currentBessSource = 'bess-sizing';
        console.log('✅ BESS sizing data stored as AUTHORITATIVE source');

        // Update UI
        updateBessSourceSelector();
        displayBessSavingsBreakdown();

        // Apply to variant and recalculate
        applyBessSourceToVariant();
        if (analysisResults) {
          performEconomicAnalysisDebounced();
        }
      }
      break;

    case 'PV_TYPE_UPDATED':
      // PV type changed in Configuration module - update local pvConfig and recalculate
      console.log('📋 PV type updated from config:', event.data.data);
      if (event.data.data) {
        const newPvType = event.data.data.pvType || event.data.data.pv_type;
        // Update local pvConfig
        if (!pvConfig) {
          pvConfig = {};
        }
        pvConfig.pvType = newPvType;
        pvConfig.pv_type = newPvType;

        // If we have full pvConfig from message, use it
        if (event.data.data.pvConfig) {
          pvConfig = { ...pvConfig, ...event.data.data.pvConfig };
        }

        console.log('📋 Updated pvConfig.pvType to:', pvConfig.pvType);

        // Recalculate CAPEX if we have analysis data
        if (analysisResults) {
          console.log('🔄 Recalculating economics with new PV type:', newPvType);
          performEconomicAnalysisDebounced();
        }
      }
      break;
    case 'SCENARIO_CHANGED':
      // Received from shell - scenario was changed in another module (e.g., Production)
      console.log('📊 Scenario changed from another module:', event.data.data);
      if (event.data.data && event.data.data.scenario) {
        const newScenario = event.data.data.scenario;
        const source = event.data.data.source || 'unknown';

        // Only update if scenario is different and not from economics itself
        if (window.currentProductionScenario !== newScenario && source !== 'economics') {
          console.log(`🔄 Syncing scenario from ${source}: ${newScenario}`);
          // Pass false to prevent re-broadcasting back to shell
          setGlobalScenario(newScenario, false);
        }
      }
      break;
    case 'PROJECT_LOADED':
      // Project was loaded - request shared data to refresh
      console.log('📂 Economics: Project loaded, requesting shared data');
      if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
      }
      break;

    case 'REQUEST_ECONOMICS_DATA':
      // Shell is requesting current economics data (for saving to database)
      console.log('📤 Shell requested economics data - sending current data...');
      console.log('📤 DEBUG: currentVariant =', currentVariant);
      console.log('📤 DEBUG: systemSettings =', systemSettings);
      console.log('📤 DEBUG: centralizedMetrics keys =', Object.keys(centralizedMetrics));

      // Get current centralized metrics for the current variant
      const currentCalc = centralizedMetrics[currentVariant];
      console.log('📤 DEBUG: currentCalc =', currentCalc ? 'exists' : 'null');

      if (currentCalc && variants[currentVariant]) {
        const variant = variants[currentVariant];
        console.log('📤 DEBUG: variant.capacity =', variant.capacity, 'variant.production =', variant.production);

        const eaasDuration = systemSettings?.eaasDuration || 10;
        const analysisPeriod = systemSettings?.analysisPeriod || 25;
        const discountRate = window.economicsSettings?.discountRate;
        console.log('📤 DEBUG: eaasDuration =', eaasDuration, 'analysisPeriod =', analysisPeriod);

        // Calculate Full Investor Model on-demand to ensure fresh data
        let fullInvestorModelData = null;
        try {
          const annualEnergyMWh = kwhToMwh(variant.production || 0);
          const bessDataForModel = (variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0) ? variant : null;
          const economicParams = {
            gridPrice: systemSettings?.gridPrice || 0.8,
            opexPerKwp: window.economicsSettings?.opexPerKwp,
            insuranceRate: window.economicsSettings?.insuranceRate,
            degradationRate: window.economicsSettings?.degradationRate
          };
          console.log('📤 DEBUG: Calling calculateEaasFullModel with capacity =', variant.capacity, 'annualEnergyMWh =', annualEnergyMWh);

          const freshFullModel = calculateEaasFullModel(
            variant.capacity,
            annualEnergyMWh,
            systemSettings || {},
            economicParams,
            bessDataForModel
          );
          console.log('📤 DEBUG: freshFullModel result =', freshFullModel);

          if (freshFullModel) {
            fullInvestorModelData = {
              // EaaS Client (abonament)
              subscriptionAnnual: freshFullModel.annualSubscriptionPLN || null,
              subscriptionMonthly: freshFullModel.annualSubscriptionPLN ? freshFullModel.annualSubscriptionPLN / 12 : null,
              pricePerMwh: freshFullModel.pricePerMWh || null,
              // IRR metrics
              targetIrr: freshFullModel.targetIrr || null,
              projectIrr: freshFullModel.projectIrr || null,
              equityIrr: freshFullModel.equityIrr || null,
              irrDriver: freshFullModel.irrDriver || null,
              // Capital structure
              capexPln: freshFullModel.totalCapexPLN || null,
              debtPln: freshFullModel.debtAmount || null,
              equityPln: freshFullModel.equityAmount || null,
              leveragePct: freshFullModel.leverageRatio || null,
              // Contract financials
              contractRevenuePln: freshFullModel.totalRevenue || null,
              contractOpexPln: freshFullModel.totalOpex || null,
              contractTaxPln: freshFullModel.totalTax || null,
              contractInterestPln: freshFullModel.totalInterest || null,
              // Model parameters
              citRatePct: freshFullModel.citRate || null,
              depreciationYears: 15, // Standard depreciation period
              indexationType: freshFullModel.indexationType || null,
              projectLifeYears: freshFullModel.projectLifetime || null,
              // Residual value
              residualValuePln: freshFullModel.residualValue || null,
              residualPerKwp: 1 // 1 PLN/kWp standard buyout
            };
            console.log('✅ Calculated fresh fullInvestorModel for save:', JSON.stringify(fullInvestorModelData, null, 2));
          } else {
            console.log('⚠️ freshFullModel is null/undefined!');
          }
        } catch (err) {
          console.error('⚠️ Error calculating fullInvestorModel:', err);
          console.error('⚠️ Error stack:', err.stack);
        }

        // Build economics data similar to what generateEaaSYearlyTable sends
        const economicsDataForSave = {
          variantKey: currentVariant,
          eaasDuration: eaasDuration,
          analysisPeriod: analysisPeriod,
          eaasPhaseSavings: currentCalc.eaas?.phaseSavings || 0,
          ownershipPhaseSavings: currentCalc.eaas?.ownershipPhaseSavings || 0,
          totalSavings: (currentCalc.eaas?.phaseSavings || 0) + (currentCalc.eaas?.ownershipPhaseSavings || 0),
          cumulativeNPV: currentCalc.eaas?.npv || 0,
          discountRate: discountRate,
          cashFlows: currentCalc.eaas?.cashFlows || [],
          // CAPEX Client yearly cashflows (for database save)
          capexCashFlows: currentCalc.capex?.cashFlows || [],
          // CAPEX data
          capexInvestment: currentCalc.capex?.investment || 0,
          capexNPV: currentCalc.capex?.npv || 0,
          capexIRR: currentCalc.capex?.irr || 0,
          capexPayback: currentCalc.capex?.simplePayback || 0,
          irrMode: systemSettings?.irrMode || 'real',
          // Common parameters
          totalEnergyPrice: currentCalc.common?.totalEnergyPrice || 0,
          inflationRate: currentCalc.common?.inflationRate || 0,
          // BESS info
          bessIncluded: variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0,
          bessPowerKw: variant.bess_power_kw || 0,
          bessEnergyKwh: variant.bess_energy_kwh || 0,
          // Full Investor Model (perspektywa inwestora) - calculated fresh
          fullInvestorModel: fullInvestorModelData
        };

        console.log('📤 Sending ECONOMICS_DATA_RESPONSE:', economicsDataForSave.variantKey, economicsDataForSave.fullInvestorModel ? '(with investor model)' : '(no investor model)');
        window.parent.postMessage({
          type: 'ECONOMICS_DATA_RESPONSE',
          data: economicsDataForSave
        }, '*');
      } else {
        console.log('⚠️ No economics data available to send');
        window.parent.postMessage({
          type: 'ECONOMICS_DATA_RESPONSE',
          data: null
        }, '*');
      }
      break;
  }
});

// Load all data from localStorage or backend
async function loadAllData() {
  // Try localStorage first
  const storedEconomic = localStorage.getItem('economicData');
  const storedConfig = localStorage.getItem('pvConfig');
  const storedProduction = localStorage.getItem('pvProductionData');
  const storedAnalysisResults = localStorage.getItem('analysisResults') || localStorage.getItem('pv_analysis_results');

  // Preserve current pvType if already set (e.g., from PV_TYPE_UPDATED message)
  const currentPvType = pvConfig?.pvType || pvConfig?.pv_type;

  if (storedEconomic || storedConfig) {
    try {
      if (storedEconomic) economicData = JSON.parse(storedEconomic);
      if (storedConfig) {
        const loadedConfig = JSON.parse(storedConfig);
        // Preserve pvType from shell if it was set more recently
        if (currentPvType) {
          loadedConfig.pvType = currentPvType;
          loadedConfig.pv_type = currentPvType;
        }
        pvConfig = loadedConfig;
      }
      if (storedProduction) productionData = JSON.parse(storedProduction);

      // Load variants from analysis results
      if (storedAnalysisResults) {
        const results = JSON.parse(storedAnalysisResults);
        if (results.key_variants) {
          variants = results.key_variants;
          console.log('✅ Loaded variants from localStorage:', Object.keys(variants));
        }
        if (results) {
          analysisResults = results;
        }
      }

      performAnalysis();
      return;
    } catch (error) {
      console.error('Błąd ładowania danych z localStorage:', error);
    }
  }

  // Fallback: try to load from backend
  try {
    // Try to fetch from economics service first
    let economicsDataFetched = false;
    try {
      const economicsResponse = await fetch(`${API_URLS.economics}/`);
      if (economicsResponse.ok) {
        const economicsInfo = await economicsResponse.json();
        // Economics service is running, could fetch data here if available
        economicsDataFetched = true;
      }
    } catch (e) {
      console.log('Economics service not available, using generated data');
    }

    // Check if data service has data
    const healthResponse = await fetch(`${API_URLS.dataAnalysis}/health`);
    if (!healthResponse.ok) {
      showNoData();
      return;
    }

    const health = await healthResponse.json();
    if (!health.data_loaded) {
      showNoData();
      return;
    }

    // If no economic data from service, generate sample data
    if (!economicsDataFetched && !storedConfig) {
      // Try to get basic config from default values
      const capacity = 1000; // Default 1 MWp
      pvConfig = {
        installedCapacity: capacity,
        name: 'Domyślna konfiguracja',
        pvType: currentPvType || 'ground_s',
        pv_type: currentPvType || 'ground_s'
      };
    } else if (storedConfig) {
      try {
        const loadedConfig = JSON.parse(storedConfig);
        // Preserve pvType from shell if it was set more recently
        if (currentPvType) {
          loadedConfig.pvType = currentPvType;
          loadedConfig.pv_type = currentPvType;
        }
        pvConfig = loadedConfig;
      } catch (e) {
        console.error('Błąd parsowania konfiguracji:', e);
      }
    }

    // Generate economic data if not available
    if (!storedEconomic && pvConfig) {
      economicData = generateSampleEconomicData(pvConfig);
      localStorage.setItem('economicData', JSON.stringify(economicData));
    }

    // Try to get production data and variants from backend
    if (!storedProduction || !storedAnalysisResults) {
      try {
        const analysisResultsStr = localStorage.getItem('pv_analysis_results') || localStorage.getItem('analysisResults');
        if (analysisResultsStr) {
          const results = JSON.parse(analysisResultsStr);

          // Load variants if not already loaded
          if (results.key_variants && !variants) {
            variants = results.key_variants;
            analysisResults = results;
            console.log('✅ Loaded variants from fallback path:', Object.keys(variants));
          }

          // Load production data if not already loaded
          if (results.hourly_production && !productionData) {
            productionData = {
              filename: 'Dane z backendu',
              hourlyProduction: results.hourly_production,
              dataPoints: results.hourly_production.length
            };
            localStorage.setItem('pvProductionData', JSON.stringify(productionData));
          }
        }
      } catch (e) {
        console.error('Błąd pobierania danych produkcji:', e);
      }
    }

    // Save config to localStorage
    if (pvConfig) {
      localStorage.setItem('pvConfig', JSON.stringify(pvConfig));
    }

    performAnalysis();
  } catch (error) {
    console.error('Błąd ładowania danych z backendu:', error);
    showNoData();
  }
}

// Show "no data" message
function showNoData() {
  document.querySelector('.content-grid').classList.add('hidden');
  document.getElementById('noDataMessage').classList.add('active');
  document.getElementById('dataInfo').textContent = 'Brak danych';
}

// Hide "no data" message
function hideNoData() {
  document.querySelector('.content-grid').classList.remove('hidden');
  document.getElementById('noDataMessage').classList.remove('active');
}

/**
 * CENTRALIZED FINANCIAL CALCULATIONS
 *
 * This function is the SINGLE SOURCE OF TRUTH for all NPV and financial metric calculations.
 * All UI sections should display values from this function to ensure consistency.
 *
 * @param {object} variant - Variant data (capacity, production, self_consumed)
 * @param {object} params - Economic parameters (prices, OPEX, degradation, etc.)
 * @param {object} eaasParams - EaaS-specific parameters (subscription, duration, etc.)
 * @returns {object} - Complete financial metrics for both CAPEX and EaaS models
 */
function calculateCentralizedFinancialMetrics(variant, params, eaasParams = null, options = {}) {
  // Auto-detect hybrid_monthly from settings if not explicitly set
  const settingsPricingMode = (systemSettings || {}).pricingMode;
  const pricingMode = options.pricingMode || (settingsPricingMode === 'hybrid_monthly' ? 'hybrid_monthly' : 'tariff');
  const rdnBaseline = options.rdnBaseline || null;
  console.log('💰 CENTRALIZED CALCULATION for variant:', variant.capacity, 'kWp', '| pricingMode:', pricingMode);

  // Apply production scenario factor — productionFactors (per-scenario) ma priorytet nad currentScenarioFactor (global cache)
  const scenarioName = window.currentProductionScenario || 'P50';
  const scenarioFactor = (window.productionFactors && window.productionFactors[scenarioName] !== undefined)
    ? window.productionFactors[scenarioName]
    : (window.currentScenarioFactor || 1.0);
  console.log(`  📊 Using scenario: ${scenarioName} (factor: ${scenarioFactor})`);

  // Common parameters - convert to MWh for consistent calculations with PLN/MWh prices
  const capacityKwp = variant.capacity;
  const productionMwh = kwhToMwh(variant.production * scenarioFactor);
  // Use PRECISE hourly self-consumed from backend when available (consistent with Excel)
  const selfConsumedMwh = (preciseAnnualSavings?.energy?.self_consumed_mwh)
    ? preciseAnnualSavings.energy.self_consumed_mwh
    : kwhToMwh(variant.self_consumed * scenarioFactor); // fallback: simple scaling

  // BESS autoconsumption breakdown (for table display)
  const bessSelfConsumedMwh = kwhToMwh((variant.bess_self_consumed_from_bess_kwh || 0) * scenarioFactor);

  // PV direct autoconsumption - CRITICAL: use profile-analysis data when available!
  // The variant.self_consumed was calculated with CONFIG BESS, not recommended BESS,
  // so we MUST use direct_consumption_mwh from profile-analysis for consistency with Excel.
  let pvDirectSelfConsumedMwh;
  console.log(`  📊 DEBUG: currentBessSource=${currentBessSource}, profileAnalysisBessData?.direct_consumption_mwh=${profileAnalysisBessData?.direct_consumption_mwh}`);
  if (currentBessSource === 'profile-analysis' && profileAnalysisBessData?.direct_consumption_mwh) {
    // Use REAL direct consumption from profile-analysis (PV direct, without BESS)
    pvDirectSelfConsumedMwh = profileAnalysisBessData.direct_consumption_mwh * scenarioFactor;
    console.log(`  ✅ Using profile-analysis direct_consumption: ${pvDirectSelfConsumedMwh.toFixed(1)} MWh (from backend)`);
  } else {
    // Fallback: calculate from total self_consumed minus BESS
    pvDirectSelfConsumedMwh = selfConsumedMwh - bessSelfConsumedMwh;
    console.log(`  ⚠️ FALLBACK: pvDirectSelfConsumedMwh = ${selfConsumedMwh.toFixed(1)} - ${bessSelfConsumedMwh.toFixed(1)} = ${pvDirectSelfConsumedMwh.toFixed(1)} MWh`);
  }

  // Recalculate total self-consumed as PV direct + BESS (ensures consistency)
  const actualSelfConsumedMwh = pvDirectSelfConsumedMwh + bessSelfConsumedMwh;

  console.log(`  🔋 Autoconsumption breakdown: PV=${pvDirectSelfConsumedMwh.toFixed(1)} MWh + BESS=${bessSelfConsumedMwh.toFixed(1)} MWh = ${actualSelfConsumedMwh.toFixed(1)} MWh total`);


  // PV CAPEX
  const capexPerKwp = getCapexForCapacity(capacityKwp);
  const capexPV = capacityKwp * capexPerKwp;

  // BESS CAPEX (if present)
  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  let capexBESS = 0;
  let opexBESS = 0;
  let bessDegradationYear1 = 0;
  let bessDegradationPctPerYear = 0;
  if (hasBess) {
    const settings = systemSettings || {};
    const bessCapexPerKwh = settings.bessCapexPerKwh || 1500;
    const bessCapexPerKw = settings.bessCapexPerKw || 300;
    const bessOpexPctPerYear = settings.bessOpexPctPerYear || 1.5;
    // BESS degradation from settings (user configurable in Settings → Parametry techniczne BESS)
    const rawDegYear1 = settings.bessDegradationYear1;
    const rawDegPerYear = settings.bessDegradationPctPerYear;
    bessDegradationYear1 = pctToDecimal(rawDegYear1 !== undefined ? rawDegYear1 : 3.0);
    bessDegradationPctPerYear = pctToDecimal(rawDegPerYear !== undefined ? rawDegPerYear : 2.0);
    capexBESS = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);
    opexBESS = capexBESS * pctToDecimal(bessOpexPctPerYear);
    console.log(`  🔋 BESS CAPEX: ${plnToMlnPln(capexBESS).toFixed(2)} mln PLN`);
    console.log(`  🔋 BESS OPEX: ${plnToTysPln(opexBESS).toFixed(0)} tys. PLN/rok`);
    console.log(`  🔋 BESS Degradation from settings: Year1=${(bessDegradationYear1*100).toFixed(1)}% (raw: ${rawDegYear1}), Years2+=${(bessDegradationPctPerYear*100).toFixed(1)}%/yr (raw: ${rawDegPerYear})`);
  }

  // Total CAPEX = PV + BESS
  const capex = capexPV + capexBESS;

  const discountRate = window.economicsSettings?.discountRate;
  const inflationRate = window.economicsSettings?.inflationRate;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';
  // =========================================================================
  // DATA CONTRACT: Client analysis horizon = 30 years
  // Must match: shell.js CLIENT_ANALYSIS_PERIOD, app.py CLIENT_ANALYSIS_PERIOD
  // =========================================================================
  const CLIENT_ANALYSIS_PERIOD = 30;
  const analysisPeriod = CLIENT_ANALYSIS_PERIOD; // Fixed for client models (CAPEX_CLIENT, EAAS_CLIENT)
  const degradationRate = params.degradation_rate; // PV degradation for years 2+ [fraction]

  // PV degradation Year 1 (LID)
  // When preciseAnnualSavings available: LID already applied to PV profile before backend call,
  // so self_consumed_mwh already includes it → pvDegradationYear1Calc = 0 to avoid double-counting.
  // pvDegradationYear1Display always reflects actual setting (for tables/Excel).
  const settings = systemSettings || {};
  const rawPvDegYear1 = settings.pvDegradationYear1;
  const hasPreciseBase = !!(preciseAnnualSavings?.energy?.self_consumed_mwh);
  const pvDegradationYear1Display = pctToDecimal(rawPvDegYear1 !== undefined ? rawPvDegYear1 : 1.0);
  const pvDegradationYear1 = hasPreciseBase
    ? 0  // LID already in profile → in self_consumed_mwh
    : pvDegradationYear1Display;

  // IRR calculation mode - determines if we apply inflation to cash flows
  const useInflation = window.economicsSettings?.useInflation || false;
  const irrMode = useInflation ? 'nominal' : 'real';

  // ========== CENA ENERGII [PLN/MWh] ==========
  // energyPriceWithoutCapacity — cena energii BEZ opłaty mocowej (capacity_fee).
  //   Składniki: energia czynna (ToU average) + dystrybucja + jakościowa + OZE + kogeneracja + akcyza
  //   Użycie: obliczanie oszczędności per-MWh z autokonsumpcji (bo capacity_fee zależy od K-class, nie od MWh)
  //
  // totalEnergyPrice — pełna cena = energyPriceWithoutCapacity + capacity_fee
  //   Użycie: LCOE reference, display, backward compat
  //
  // Gdy dostępne preciseAnnualSavings: obie wartości zastępowane przez effective_price z backendu
  let energyPriceWithoutCapacity = params.energy_active + params.distribution + params.quality_fee +
                                      params.oze_fee + params.cogeneration_fee +
                                      params.excise_tax;
  let totalEnergyPrice = energyPriceWithoutCapacity + params.capacity_fee;

  // PRECISE BACKEND SAVINGS: if available, use hourly K-class calculations (same as Excel)
  const hasPreciseSavings = preciseAnnualSavings && preciseAnnualSavings.year1_savings;
  let preciseYear1TotalSavings = 0;
  let preciseYear1EnergySavings = 0;
  let preciseYear1CapacitySavings = 0;
  if (hasPreciseSavings) {
    preciseYear1TotalSavings = preciseAnnualSavings.year1_savings.total_pln;
    preciseYear1EnergySavings = preciseAnnualSavings.year1_savings.energia_pln +
                                 preciseAnnualSavings.year1_savings.dystrybucja_pln +
                                 preciseAnnualSavings.year1_savings.other_pln;
    preciseYear1CapacitySavings = preciseAnnualSavings.year1_savings.mocowa_pln;
    totalEnergyPrice = preciseAnnualSavings.effective_price_pln_mwh || totalEnergyPrice;
    energyPriceWithoutCapacity = totalEnergyPrice - (params.capacity_fee || 0);
    console.log(`  ✅ PRECISE SAVINGS from backend: total=${preciseYear1TotalSavings.toFixed(0)} PLN (energia=${preciseYear1EnergySavings.toFixed(0)}, mocowa=${preciseYear1CapacitySavings.toFixed(0)})`);
    console.log(`     Effective price: ${totalEnergyPrice.toFixed(1)} PLN/MWh`);
  } else {
    // Fallback: HYBRID MONTHLY weighted average or flat rate
    const weightedPrice = (pricingMode === 'hybrid_monthly') ? computeWeightedEnergyPrice(params) : null;
    if (weightedPrice) {
      console.log(`  🔀 HYBRID MONTHLY fallback: flat ${energyPriceWithoutCapacity.toFixed(0)} → weighted ${weightedPrice.weightedTotalNoCapacity.toFixed(0)} PLN/MWh`);
      energyPriceWithoutCapacity = weightedPrice.weightedTotalNoCapacity;
      totalEnergyPrice = weightedPrice.weightedTotal;
    }
  }

  // K-class capacity fee data from pv-calculation (v3.0)
  const hasKClassData = variant.capacity_fee_baseline_pln != null && variant.capacity_fee_baseline_pln !== undefined;
  const capacityFeeSavingsPV = variant.capacity_fee_savings_pv_pln || 0;       // S0 - S1
  const capacityFeeSavingsBESS = variant.capacity_fee_savings_bess_pln || 0;   // S1 - S2
  const capacityFeeSavingsTotal = variant.capacity_fee_savings_total_pln || 0; // S0 - S2

  // BESS additional savings from bess-dispatch (arbitrage, peak shaving)
  const bessArbitrageSavingsYear1 = variant.savings_breakdown?.arbitrage_savings_pln || 0;
  const bessPeakShavingSavingsYear1 = variant.savings_breakdown?.demand_charge_savings_pln || 0;
  // Note: energy_savings from bess-dispatch is already captured in bessSelfConsumedMwh × energyPrice
  // So we do NOT add it here to avoid double-counting

  // ========== CAPEX MODEL CALCULATION ==========
  console.log('🔢 CENTRALIZED CAPEX NPV Calculation:');
  console.log('  📅 Analysis period:', analysisPeriod, 'years');
  console.log('  📊 Discount rate:', decimalToPct(discountRate).toFixed(1), '%');
  console.log('  📈 Inflation rate:', decimalToPct(inflationRate).toFixed(1), '%');
  console.log(`  📉 PV Degradation from settings: Year1=${(pvDegradationYear1*100).toFixed(1)}% (raw: ${rawPvDegYear1}), Years2+=${(degradationRate*100).toFixed(2)}%/yr`);
  console.log('  💰 Initial CAPEX:', plnToMlnPln(-capex).toFixed(2), 'mln PLN');
  console.log('  📊 IRR Mode:', irrMode, useInflation ? '(inflation-indexed cash flows)' : '(constant prices)');
  console.log(`  📊 K-class data: ${hasKClassData ? 'YES' : 'NO (fallback to flat rate)'}`);
  if (hasKClassData) {
    console.log(`     K-class: ${variant.k_class_baseline} -> ${variant.k_class_with_pv} -> ${variant.k_class_with_pv_bess || 'N/A'}`);
    console.log(`     Capacity fee savings: PV=${capacityFeeSavingsPV.toFixed(0)}, BESS=${capacityFeeSavingsBESS.toFixed(0)}, Total=${capacityFeeSavingsTotal.toFixed(0)} PLN`);
    console.log(`     BESS extra: arbitrage=${bessArbitrageSavingsYear1.toFixed(0)}, peak_shaving=${bessPeakShavingSavingsYear1.toFixed(0)} PLN`);
  }

  let capexNPV = -capex;
  let capexCashFlows = [];

  for (let year = 1; year <= analysisPeriod; year++) {
    // PV degradation: Year 1 = pvDegradationYear1, Years 2+ = degradationRate
    // Year 1: (1 - pvDegradationYear1)
    // Year 2: (1 - pvDegradationYear1) * (1 - degradationRate)
    // Year N: (1 - pvDegradationYear1) * (1 - degradationRate)^(N-1)
    const pvDegradation = (1 - pvDegradationYear1) * Math.pow(1 - degradationRate, Math.max(0, year - 1));

    // BESS degradation: Year 1 = bessDegradationYear1, Years 2+ = bessDegradationPctPerYear
    // Year 1: (1 - bessDegradationYear1)
    // Year 2: (1 - bessDegradationYear1) * (1 - bessDegradationPctPerYear)
    // Year N: (1 - bessDegradationYear1) * (1 - bessDegradationPctPerYear)^(N-1)
    let bessDegradation = 1;
    if (hasBess && year >= 1) {
      bessDegradation = (1 - bessDegradationYear1) * Math.pow(1 - bessDegradationPctPerYear, Math.max(0, year - 1));
    }

    // --- Inflation factors (audit-grade, matching Excel formulas) ---
    // Savings CPI escalation: (1+CPI)^(year-1) — year 1 at base prices, year 2+ escalated
    // Used for tariff-mode energy price and RDN savings
    const savingsCpiEscalation = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;
    // OPEX CPI escalation: ALWAYS (1+CPI)^year — costs always grow with inflation
    // Excel formula: =$F$14*POWER(1+$F$5,year) — unconditional, exponent = year (not year-1)
    const opexCpiEscalation = Math.pow(1 + inflationRate, year);

    // Breakdown: PV direct uses PV degradation, BESS uses BESS degradation
    const yearPvDirectMwh = pvDirectSelfConsumedMwh * pvDegradation;
    const yearBessMwh = bessSelfConsumedMwh * bessDegradation;
    const yearSelfConsumedMwh = yearPvDirectMwh + yearBessMwh;

    // OPEX = PV OPEX + BESS OPEX — ALWAYS inflated (operational costs grow with CPI)
    const adjustedOpexPV = capacityKwp * params.opex_per_kwp * opexCpiEscalation;
    const adjustedOpexBESS = opexBESS * opexCpiEscalation;
    const adjustedOpex = adjustedOpexPV + adjustedOpexBESS;

    // --- Savings calculation: per-component streams ---
    let yearSavings, yearEnergyFeesSavings = 0, yearCapacitySavings = 0;
    let yearBessArbitrage = 0, yearBessPeakShaving = 0;
    if (hasPreciseSavings && !hasBess) {
      // PRECISE MODE: backend hourly K-class calculations (same as Excel).
      // Backend computed savings for full production (no degradation applied there).
      // We scale by pvDegradation relative to year-1 degradation factor.
      const year1PvDeg = (1 - pvDegradationYear1); // Year 1 = 0.98
      const relDeg = pvDegradation / year1PvDeg; // relative to year 1 (1.0 for year 1)
      const cpiEscalation = savingsCpiEscalation;
      // Energy savings scale with PV degradation + CPI
      yearEnergyFeesSavings = preciseYear1EnergySavings * relDeg * cpiEscalation;
      // Capacity fee savings scale with PV degradation + CPI
      yearCapacitySavings = preciseYear1CapacitySavings * relDeg * cpiEscalation;
      // BESS streams
      yearBessArbitrage = bessArbitrageSavingsYear1 * bessDegradation * cpiEscalation;
      yearBessPeakShaving = bessPeakShavingSavingsYear1 * bessDegradation * cpiEscalation;
      yearSavings = yearEnergyFeesSavings + yearCapacitySavings + yearBessArbitrage + yearBessPeakShaving;
    } else if (pricingMode === 'rdn' && rdnBaseline) {
      // RDN mode: two separate savings streams from TCSL year-1 data
      const cpiEscalation = Math.pow(1 + inflationRate, year - 1);
      yearEnergyFeesSavings = rdnBaseline.energyFeesSavingsYear1 * pvDegradation * cpiEscalation;
      yearCapacitySavings = rdnBaseline.capacitySavingsYear1 * cpiEscalation;
      yearSavings = yearEnergyFeesSavings + yearCapacitySavings;
    } else if (hasKClassData) {
      // ===== NEW: Per-component savings with real K-class data =====
      // Stream 1: Energy savings (autokonsumpcja × cena BEZ opłaty mocowej)
      const adjustedEnergyPriceNoCapacity = energyPriceWithoutCapacity * savingsCpiEscalation;
      yearEnergyFeesSavings = yearSelfConsumedMwh * adjustedEnergyPriceNoCapacity;

      // Stream 2: K-class capacity fee savings (PV component) — degrades with PV
      yearCapacitySavings = capacityFeeSavingsPV * pvDegradation * savingsCpiEscalation;

      // Stream 3: K-class capacity fee savings (BESS component) — degrades with BESS
      const yearBessCapacitySavings = capacityFeeSavingsBESS * bessDegradation * savingsCpiEscalation;

      // Stream 4: BESS arbitrage savings — degrades with BESS SoH
      yearBessArbitrage = bessArbitrageSavingsYear1 * bessDegradation * savingsCpiEscalation;

      // Stream 5: BESS peak shaving savings — degrades with BESS SoH
      yearBessPeakShaving = bessPeakShavingSavingsYear1 * bessDegradation * savingsCpiEscalation;

      yearSavings = yearEnergyFeesSavings + yearCapacitySavings + yearBessCapacitySavings
                  + yearBessArbitrage + yearBessPeakShaving;
    } else {
      // Fallback: flat rate (old behavior — capacity_fee included in energy price)
      const adjustedEnergyPrice = totalEnergyPrice * savingsCpiEscalation;
      yearSavings = yearSelfConsumedMwh * adjustedEnergyPrice; // MWh * PLN/MWh = PLN
    }

    const yearCashFlow = yearSavings - adjustedOpex;
    const discountedCF = yearCashFlow / Math.pow(1 + discountRate, year);
    capexNPV += discountedCF;

    capexCashFlows.push({
      year: year,
      savings: yearSavings,
      energyFeesSavings: yearEnergyFeesSavings,
      capacitySavings: yearCapacitySavings,
      bessArbitrage: yearBessArbitrage,
      bessPeakShaving: yearBessPeakShaving,
      opex: adjustedOpex,
      net_cash_flow: yearCashFlow,
      production: productionMwh * pvDegradation * 1000,
      selfConsumed: yearSelfConsumedMwh * 1000,
      selfConsumedPvDirect: yearPvDirectMwh * 1000,
      selfConsumedBess: yearBessMwh * 1000,
      energyPrice: (hasKClassData ? energyPriceWithoutCapacity : totalEnergyPrice) * savingsCpiEscalation,
      pvDegradationPct: ((1 - pvDegradationYear1Display) * Math.pow(1 - degradationRate, Math.max(0, year - 1))) * 100,
      bessDegradationPct: bessDegradation * 100,
      pricingMode: pricingMode,
      hasKClassData: hasKClassData
    });

    // Log sample years
    if (year <= 2 || year === analysisPeriod) {
      console.log(`  Year ${year}: NetCF=${plnToTysPln(yearCashFlow).toFixed(0)}k PLN, Discounted=${plnToTysPln(discountedCF).toFixed(0)}k PLN, RunningNPV=${plnToMlnPln(capexNPV).toFixed(2)}M PLN`);
    }
  }

  console.log('  ✅ Final CAPEX NPV:', plnToMlnPln(capexNPV).toFixed(2), 'mln PLN');

  // Calculate CAPEX IRR using local Newton-Raphson method
  // NOTE: This is for display purposes; backend IRR (when available) should be preferred
  const irrCashFlows = capexCashFlows.map((cf, i) => ({
    year: i + 1,
    net_cash_flow: cf.net_cash_flow
  }));
  console.log('  📊 IRR Input - Initial investment:', plnToMlnPln(capex).toFixed(2), 'mln PLN');
  console.log('  📊 IRR Input - Cash flows count:', irrCashFlows.length);
  console.log('  📊 IRR Input - First 3 cash flows:', irrCashFlows.slice(0, 3).map(cf => `Year ${cf.year}: ${plnToTysPln(cf.net_cash_flow).toFixed(0)}k PLN`));
  const capexIRR = calculateIRR()
  console.log('  📊 IRR Result:', capexIRR, '(', decimalToPct(capexIRR).toFixed(2), '%) - Mode:', irrMode);

  // ========== EaaS MODEL CALCULATION ==========
  let eaasNPV = 0;
  let eaasCashFlows = [];
  let eaasMetrics = null;

  if (eaasParams) {
    const eaasDuration = eaasParams.duration || 10;
    const baseSubscriptionCost = eaasParams.subscription;
    const baseOmCost = capacityKwp * (eaasParams.omPerKwp || 24);
    const baseInsuranceCost = capex * (window.economicsSettings?.insuranceRate || 0.005);
    const baseLandLeaseCost = capacityKwp * (window.economicsSettings?.landLeasePerKwp || 0);

    console.log('🔢 CENTRALIZED EaaS NPV Calculation:');
    console.log('  📅 Analysis period:', analysisPeriod, 'years');
    console.log('  📅 EaaS contract duration:', eaasDuration, 'years');
    console.log('  📊 Discount rate:', decimalToPct(discountRate).toFixed(1), '%');
    console.log('  📈 Inflation rate:', decimalToPct(inflationRate).toFixed(1), '%');
    console.log('  📋 EaaS indexation:', eaasIndexation);
    console.log('  💰 Base subscription:', plnToTysPln(baseSubscriptionCost).toFixed(0), 'k PLN/year');
    console.log('  💰 Base O&M:', plnToTysPln(baseOmCost).toFixed(0), 'k PLN/year');
    console.log('  💰 Base insurance:', plnToTysPln(baseInsuranceCost).toFixed(0), 'k PLN/year');
    if (baseLandLeaseCost > 0) {
      console.log('  💰 Base land lease:', plnToTysPln(baseLandLeaseCost).toFixed(0), 'k PLN/year');
    }

    for (let year = 1; year <= analysisPeriod; year++) {
      // PV degradation: Year 1 = pvDegradationYear1, Years 2+ = degradationRate
      const pvDegradation = (1 - pvDegradationYear1) * Math.pow(1 - degradationRate, Math.max(0, year - 1));

      // BESS degradation: Year 1 = bessDegradationYear1, Years 2+ = bessDegradationPctPerYear
      let bessDegradation = 1;
      if (hasBess && year >= 1) {
        bessDegradation = (1 - bessDegradationYear1) * Math.pow(1 - bessDegradationPctPerYear, Math.max(0, year - 1));
      }

      const inflationFactor = Math.pow(1 + inflationRate, year - 1);

      // Breakdown: PV direct uses PV degradation, BESS uses BESS degradation
      const yearPvDirectMwh = pvDirectSelfConsumedMwh * pvDegradation;
      const yearBessMwh = bessSelfConsumedMwh * bessDegradation;
      const yearSelfConsumedMwh = yearPvDirectMwh + yearBessMwh;

      const adjustedGridPrice = totalEnergyPrice * inflationFactor; // PLN/MWh

      // EaaS subscription: apply inflation only if indexation is 'cpi'
      const eaasInflationFactor = eaasIndexation === 'cpi' ? inflationFactor : 1;
      const adjustedSubscriptionCost = baseSubscriptionCost * eaasInflationFactor;

      // OPEX costs after EaaS contract: ALWAYS apply inflation (real-world costs grow with inflation)
      const adjustedOmCost = baseOmCost * inflationFactor;
      const adjustedInsuranceCost = baseInsuranceCost * inflationFactor;
      const adjustedLandLeaseCost = baseLandLeaseCost * inflationFactor;
      const adjustedBessOpex = opexBESS * inflationFactor; // BESS OPEX after EaaS contract

      // --- GridCost / savings calculation: precise > RDN > tariff ---
      let gridCost, eaasEnergyFeesSavings = 0, eaasCapacitySavings = 0;
      if (hasPreciseSavings && !hasBess) {
        // PRECISE MODE: use backend hourly K-class (same as Excel)
        const year1PvDeg = (1 - pvDegradationYear1);
        const relDeg = pvDegradation / year1PvDeg;
        const cpiEscalation = inflationFactor;
        eaasEnergyFeesSavings = preciseYear1EnergySavings * relDeg * cpiEscalation;
        eaasCapacitySavings = preciseYear1CapacitySavings * relDeg * cpiEscalation;
        gridCost = eaasEnergyFeesSavings + eaasCapacitySavings;
      } else if (pricingMode === 'rdn' && rdnBaseline) {
        const cpiEscalation = Math.pow(1 + inflationRate, year - 1);
        eaasEnergyFeesSavings = rdnBaseline.energyFeesSavingsYear1 * pvDegradation * cpiEscalation;
        eaasCapacitySavings = rdnBaseline.capacitySavingsYear1 * cpiEscalation;
        gridCost = eaasEnergyFeesSavings + eaasCapacitySavings;
      } else {
        gridCost = yearSelfConsumedMwh * adjustedGridPrice;
      }

      let eaasCost;
      if (year <= eaasDuration) {
        eaasCost = adjustedSubscriptionCost;
      } else {
        eaasCost = adjustedOmCost + adjustedInsuranceCost + adjustedLandLeaseCost + adjustedBessOpex;
      }

      const savings = gridCost - eaasCost;
      const discountedCF = savings / Math.pow(1 + discountRate, year);
      eaasNPV += discountedCF;

      eaasCashFlows.push({
        year: year,
        selfConsumed: yearSelfConsumedMwh * 1000,
        selfConsumedPvDirect: yearPvDirectMwh * 1000,
        selfConsumedBess: yearBessMwh * 1000,
        gridCost: gridCost,
        eaasCost: eaasCost,
        savings: savings,
        energyFeesSavings: eaasEnergyFeesSavings,
        capacitySavings: eaasCapacitySavings,
        discountedCF: discountedCF,
        phase: year <= eaasDuration ? 'eaas' : 'ownership',
        energyPrice: adjustedGridPrice,
        pvDegradationPct: ((1 - pvDegradationYear1Display) * Math.pow(1 - degradationRate, Math.max(0, year - 1))) * 100,
        bessDegradationPct: bessDegradation * 100,
        pricingMode: pricingMode
      });

      // Log sample years
      if (year <= 2 || year === eaasDuration || year === eaasDuration + 1 || year === analysisPeriod) {
        console.log(`  Year ${year} (${year <= eaasDuration ? 'EaaS' : 'Own'}): GridCost=${plnToTysPln(gridCost).toFixed(0)}k, EaasCost=${plnToTysPln(eaasCost).toFixed(0)}k, Savings=${plnToTysPln(savings).toFixed(0)}k, Discounted=${plnToTysPln(discountedCF).toFixed(0)}k, RunningNPV=${plnToMlnPln(eaasNPV).toFixed(2)}M`);
      }
    }

    console.log('  ✅ Final EaaS NPV:', plnToMlnPln(eaasNPV).toFixed(2), 'mln PLN');

    eaasMetrics = {
      npv: eaasNPV,
      duration: eaasDuration,
      baseSubscription: baseSubscriptionCost,
      baseOmCost: baseOmCost,
      baseInsuranceCost: baseInsuranceCost,
      cashFlows: eaasCashFlows
    };
  }


  // Calculate Simple Payback
  let simplePayback = analysisPeriod;
  let cumulativeSavings = 0;
  for (let i = 0; i < capexCashFlows.length; i++) {
    cumulativeSavings += capexCashFlows[i].net_cash_flow;
    if (cumulativeSavings >= capex) {
      const prevCumulative = cumulativeSavings - capexCashFlows[i].net_cash_flow;
      const remaining = capex - prevCumulative;
      simplePayback = (i + 1) + (remaining / capexCashFlows[i].net_cash_flow);
      break;
    }
  }

  // Calculate Discounted Payback Period (DPP) - year when cumulative NPV >= 0
  let discountedPayback = null;
  let runningNPV = -capex;
  for (let i = 0; i < capexCashFlows.length; i++) {
    const year = i + 1;
    const discCF = capexCashFlows[i].net_cash_flow / Math.pow(1 + discountRate, year);
    const prevNPV = runningNPV;
    runningNPV += discCF;
    if (runningNPV >= 0 && prevNPV < 0) {
      // Interpolate within the year for fractional DPP
      discountedPayback = year - 1 + (-prevNPV / discCF);
      break;
    }
  }
  console.log('  DPP:', discountedPayback ? discountedPayback.toFixed(1) + ' lat' : 'Powyzej okresu analizy');

  // LCOE — EXACT replica of reference Excel formula:
  // =($F$10*1000+SUMPRODUCT(K18:K47/POWER(1+$F$4,B18:B47)))/SUMPRODUCT(I18:I47/POWER(1+$F$4,B18:B47))
  // F10 = CAPEX [tys PLN], K = OPEX [tys PLN], I = AutoTotal [MWh]
  // capex variable is in PLN = F10*1000
  let lcoeNumerator = capex; // = F10*1000 [PLN]
  let lcoeDenominator = 0;
  for (let yr = 1; yr <= analysisPeriod; yr++) {
    const pvDeg = yr === 1 ? (1 - pvDegradationYear1) : (1 - pvDegradationYear1) * Math.pow(1 - degradationRate, yr - 1);
    let bessDeg = 1;
    if (hasBess && yr >= 1) {
      bessDeg = (1 - bessDegradationYear1) * Math.pow(1 - bessDegradationPctPerYear, Math.max(0, yr - 1));
    }
    // K column = OPEX [tys PLN] = =$F$14*POWER(1+$F$5,yr)
    const yrOpexTys = plnToTysPln((capacityKwp * params.opex_per_kwp + opexBESS) * Math.pow(1 + inflationRate, yr));
    lcoeNumerator += yrOpexTys / Math.pow(1 + discountRate, yr);
    // I column = AutoPV + AutoBESS [MWh]
    const yrAutocons = pvDirectSelfConsumedMwh * pvDeg + bessSelfConsumedMwh * bessDeg;
    lcoeDenominator += yrAutocons / Math.pow(1 + discountRate, yr);
  }
  const lcoe = lcoeDenominator > 0 ? lcoeNumerator / lcoeDenominator : 0; // PLN/MWh

  return {
    capex: {
      npv: capexNPV,
      irr: capexIRR,
      irrMode: irrMode,
      irrStatus: 'converged',
      cashFlows: capexCashFlows,
      investment: capex,
      capexPerKwp: capexPerKwp,
      simplePayback: simplePayback,
      discountedPayback: discountedPayback,
      lcoe: lcoe,
      pricingMode: pricingMode,
      rdnBaseline: rdnBaseline
    },
    eaas: eaasMetrics ? { ...eaasMetrics, pricingMode, rdnBaseline } : null,
    common: {
      // === Dane wariantu ===
      capacityKwp: capacityKwp,
      productionMwh: productionMwh,
      selfConsumedMwh: selfConsumedMwh,
      productionKwh: productionMwh * 1000,
      selfConsumedKwh: selfConsumedMwh * 1000,
      pvDirectSelfConsumedMwh: pvDirectSelfConsumedMwh,
      bessSelfConsumedMwh: bessSelfConsumedMwh,
      // === Scenariusz produkcji ===
      scenarioFactor: scenarioFactor,                     // decimal (np. 0.85 dla P75)
      scenarioName: scenarioName,                         // string ('P50'/'P75'/'P90')
      // === Ceny energii [PLN/MWh] ===
      totalEnergyPrice: totalEnergyPrice,
      energyPriceWithoutCapacity: energyPriceWithoutCapacity,
      // === Parametry finansowe [decimal] ===
      discountRate: discountRate,
      inflationRate: inflationRate,
      analysisPeriod: analysisPeriod,
      useInflation: useInflation,
      // === Degradacja [decimal] ===
      degradationRate: degradationRate,                   // PV roczna years 2+ (np. 0.005)
      pvDegradationYear1: pvDegradationYear1,             // LID (np. 0.01 lub 0 gdy precise)
      bessDegradationYear1: bessDegradationYear1,         // BESS year 1 (np. 0.03)
      bessDegradationPctPerYear: bessDegradationPctPerYear, // BESS annual (np. 0.02)
      // === Koszty [PLN] ===
      capexPerKwp: capexPerKwp,
      totalCapex: capex,
      opexPerKwp: params.opex_per_kwp,
      // === Wyniki obliczeń — SSoT, NIE liczyć ponownie! ===
      // Aby uzyskać NPV/IRR/payback/LCOE, czytaj z tych pól lub z capex.*/eaas.*
      capexNpv: capexNPV,                                 // [PLN] NPV modelu CAPEX
      capexIrr: capexIRR,                                 // [decimal] IRR modelu CAPEX
      simplePayback: simplePayback,                       // [lata] prosty okres zwrotu
      discountedPayback: discountedPayback,               // [lata] zdyskontowany okres zwrotu (DPP)
      lcoe: lcoe,                                         // [PLN/MWh] LCOE
      eaasNpv: eaasMetrics?.npv || null,                  // [PLN] NPV modelu EaaS
      // === Tryb wyceny ===
      pricingMode: pricingMode,
      // === K-class / opłata mocowa ===
      hasKClassData: hasKClassData,
      kClassBaseline: variant.k_class_baseline || null,
      kClassWithPV: variant.k_class_with_pv || null,
      kClassWithPVBess: variant.k_class_with_pv_bess || null,
      capacityFeeSavingsPV: capacityFeeSavingsPV,
      capacityFeeSavingsBESS: capacityFeeSavingsBESS,
      capacityFeeSavingsTotal: capacityFeeSavingsTotal,
      hasPreciseSavings: hasPreciseSavings && !hasBess
    }
  };
}

// Perform economic analysis
// Debounce guard — multiple SHARED_DATA_RESPONSE messages can trigger this 4× on init
let _peaDebounceTimer = null;
let _peaRunning = false;

function performEconomicAnalysisDebounced(delayMs = 300) {
  if (_peaDebounceTimer) clearTimeout(_peaDebounceTimer);
  _peaDebounceTimer = setTimeout(() => {
    _peaDebounceTimer = null;
    performEconomicAnalysis();
  }, delayMs);
}

// Perform economic analysis using backend API
async function performEconomicAnalysis() {
  if (_peaRunning) {
    console.log('💰 performEconomicAnalysis() already running, skipping');
    return;
  }
  _peaRunning = true;
  console.log('💰 performEconomicAnalysis() called');
  console.log('  - currentVariant:', currentVariant);
  console.log('  - variants object:', variants);
  console.log('  - variants keys:', Object.keys(variants || {}));

  // CRITICAL: Ensure we have consumption data BEFORE calculations
  // This fetches from data-analysis backend if not already loaded
  if (!consumptionData?.annual_consumption_kwh && !consumptionData?.total_consumption_gwh) {
    console.log('📊 Fetching consumption statistics before analysis...');
    await fetchConsumptionStatistics();
  }

  hideNoData();

  if (!variants || Object.keys(variants).length === 0) {
    console.log('ℹ️ No variants in localStorage, waiting for data via postMessage...');
    showNoData();
    return;
  }

  // Try to get masterVariant from localStorage if currentVariant is invalid
  const storedMasterVariant = localStorage.getItem('masterVariant');
  if (storedMasterVariant && variants[storedMasterVariant]) {
    currentVariant = storedMasterVariant;
    console.log('  - Using masterVariant from localStorage:', currentVariant);
  }

  // Fallback: use first available variant if currentVariant not found
  if (!variants[currentVariant]) {
    const availableKeys = Object.keys(variants);
    currentVariant = availableKeys[0];
    console.log('  - Fallback to first available variant:', currentVariant);
  }

  const variant = variants[currentVariant];
  console.log('  - Looking for variant[' + currentVariant + ']:', variant);

  if (!variant) {
    console.error('❌ Variant not found for key:', currentVariant);
    console.error('Available variants:', Object.keys(variants));
    showNoData();
    return;
  }

  console.log('✅ Found variant:', currentVariant, variant);

  // SSoT Refactor: Display savings breakdown directly from the authoritative variant data.
  displayBessSavingsBreakdown();

  // K-class analysis is now in ZUŻYCIE module (frontend-consumption)
  // initKClassAnalysisFromData();

  try {
    // Get parameters from sidebar inputs
    const params = getEconomicParameters();
    console.log('📊 Using economic parameters:', params);

    // Calculate total energy cost (PLN/MWh) - już zawiera wszystkie składniki włącznie z opłatą mocową
    const totalEnergyPrice = calculateTotalEnergyPrice(params);

    console.log('💰 Total energy price (with capacity fee):', totalEnergyPrice, 'PLN/MWh');

    // Podstawowe dane z wariantu — z uwzględnieniem scenarioFactor (P50/P75/P90)
    const scenarioFactor = window.currentScenarioFactor || 1.0;
    const capacity_kwp = variant.capacity; // Already in kWp from backend
    const production_annual = kwhToMwh(variant.production * scenarioFactor);

    // Autokonsumpcja: preciseAnnualSavings jako źródło (spójne z Excel), fallback: skalowanie
    let self_consumed_annual = (preciseAnnualSavings?.energy?.self_consumed_mwh)
      ? preciseAnnualSavings.energy.self_consumed_mwh
      : kwhToMwh(variant.self_consumed * scenarioFactor);

    // BESS dodatkowa autokonsumpcja (energia rozładowana z baterii do zużycia)
    const bess_self_consumed_from_bess = kwhToMwh(variant.bess_self_consumed_from_bess_kwh || 0);

    console.log('📊 Variant data:', {
      capacity_kwp,
      production_annual_MWh: production_annual,
      self_consumed_annual_MWh: self_consumed_annual,
      bess_self_consumed_from_bess_MWh: bess_self_consumed_from_bess
    });

    // === PROSTY MODEL CAPEX ===

    // 1. Nakłady inwestycyjne PV (CAPEX) - using tiered pricing based on capacity
    const capexPerKwp = getCapexForCapacity(capacity_kwp);
    const capexPV = capacity_kwp * capexPerKwp; // PLN
    console.log(`💰 PV CAPEX: ${capacity_kwp} kWp × ${capexPerKwp} PLN/kWp = ${plnToMlnPln(capexPV).toFixed(2)} mln PLN`);

    // 1b. Nakłady inwestycyjne BESS (jeśli włączony)
    let capexBESS = 0;
    const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
    if (hasBess) {
      const settings = systemSettings || {};
      const bessCapexPerKwh = settings.bessCapexPerKwh || 1500;
      const bessCapexPerKw = settings.bessCapexPerKw || 300;
      capexBESS = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);
      console.log(`🔋 BESS CAPEX: ${variant.bess_energy_kwh} kWh × ${bessCapexPerKwh} + ${variant.bess_power_kw} kW × ${bessCapexPerKw} = ${plnToMlnPln(capexBESS).toFixed(2)} mln PLN`);
    }

    // 1c. Całkowity CAPEX = PV + BESS
    const capex = capexPV + capexBESS;
    console.log(`💰 TOTAL CAPEX: ${plnToMlnPln(capexPV).toFixed(2)} + ${plnToMlnPln(capexBESS).toFixed(2)} = ${plnToMlnPln(capex).toFixed(2)} mln PLN`);

    // Update investmentCost field to show the calculated tiered CAPEX
    const investmentCostField = document.getElementById('investmentCost');
    if (investmentCostField) {
      investmentCostField.value = capexPerKwp;
      console.log(`📝 Updated investmentCost field to: ${capexPerKwp} PLN/kWp`);
    }

    // 2. Roczne koszty operacyjne (OPEX)
    // 2a. PV OPEX
    const opex_pv_annual = capacity_kwp * params.opex_per_kwp; // PLN/rok

    // 2b. BESS OPEX (jeśli jest BESS)
    let opex_bess_annual = 0;
    if (hasBess) {
      const settings = systemSettings || {};
      const bessOpexPctPerYear = settings.bessOpexPctPerYear || 1.5; // % CAPEX per year
      opex_bess_annual = capexBESS * pctToDecimal(bessOpexPctPerYear);
      console.log(`🔋 BESS OPEX: ${capexBESS.toFixed(0)} × ${bessOpexPctPerYear}% = ${opex_bess_annual.toFixed(0)} PLN/rok`);
    }

    // 2c. Całkowity OPEX = PV + BESS
    const opex_annual = opex_pv_annual + opex_bess_annual;
    console.log(`💰 TOTAL OPEX: ${opex_pv_annual.toFixed(0)} + ${opex_bess_annual.toFixed(0)} = ${opex_annual.toFixed(0)} PLN/rok`);

    // 3. Roczne oszczędności = autoconsumption * cena energii
    // self_consumed_annual już zawiera energię z BESS (backend liczy to razem)
    const savings_year1 = self_consumed_annual * totalEnergyPrice; // PLN
    console.log(`💰 Savings Year 1: ${self_consumed_annual.toFixed(1)} MWh × ${totalEnergyPrice.toFixed(0)} PLN/MWh = ${plnToTysPln(savings_year1).toFixed(0)} tys. PLN`);

    // 4. Prosty okres zwrotu (bez zdyskontowania, bez degradacji)
    const simple_payback = capex / (savings_year1 - opex_annual); // lata

    // 5. Przepływy pieniężne z uwzględnieniem degradacji
    let cash_flows = [];
    let cumulative_cash_flow = -capex; // Start with negative CAPEX

    // Check if inflation should be applied (nominal IRR mode)
    const useInflation = window.economicsSettings?.useInflation || false;
    const inflationRate = useInflation ? window.economicsSettings?.inflationRate : 0;

    // === P0-1: Combined Reinvestment Schedule (BESS + Inverter) ===
    const reinvestmentResult = calculateReinvestmentSchedule(
      capexBESS,
      variant.bess_energy_kwh || 0,
      capexPV,
      params.analysis_period,
      window.economicsSettings || {}
    );
    const reinvestmentSchedule = reinvestmentResult.schedule; // year -> totalCost
    const bessReplacementScheduleArray = reinvestmentResult.bessSchedule;
    const inverterReplacementScheduleArray = reinvestmentResult.inverterSchedule;
    const totalReinvestmentCost = reinvestmentResult.totalCost;

    if (DEBUG_ECONOMICS && (bessReplacementScheduleArray.length > 0 || inverterReplacementScheduleArray.length > 0)) {
      console.log('🔋 BESS Replacement Schedule:', bessReplacementScheduleArray);
      console.log('⚡ Inverter Replacement Schedule:', inverterReplacementScheduleArray);
      console.log('💰 Total Reinvestment Cost:', totalReinvestmentCost.toFixed(0), 'PLN');
    }

    // === P0-2: Residual Value (calculated once, applied in final year) ===
    // Returns object {year, value, mode, description}
    const residualValueResult = calculateResidualValue(
      capex,
      capacity_kwp,
      params.analysis_period,
      window.economicsSettings || {}
    );
    const residualValue = residualValueResult.value; // Extract numeric value
    if (DEBUG_ECONOMICS) {
      console.log('💰 Residual Value:', residualValue.toFixed(0), 'PLN', `(${residualValueResult.mode})`);
    }

    for (let year = 1; year <= params.analysis_period; year++) {
      // Degradacja produkcji
      const degradation_factor = Math.pow(1 - params.degradation_rate, year - 1);
      const production_year = production_annual * degradation_factor;
      const self_consumed_year = self_consumed_annual * degradation_factor;

      // Inflation factor (applied only in nominal IRR mode)
      const inflation_factor = Math.pow(1 + inflationRate, year - 1);

      // Oszczędności w danym roku (z inflacją cen energii jeśli włączona)
      const adjustedEnergyPrice = totalEnergyPrice * inflation_factor;
      const savings_year = self_consumed_year * adjustedEnergyPrice;

      // OPEX z inflacją jeśli włączona
      const opex_year = opex_annual * inflation_factor;

      // === P0-1: Reinvestment Cost (BESS + Inverter replacement in specific years) ===
      const reinvestmentCapex = reinvestmentSchedule[year] || 0;

      // === P0-2: Residual Value (positive cash flow in residual value year) ===
      const residualValueYear = (year === residualValueResult.year) ? residualValue : 0;

      // Przepływ netto = oszczędności - OPEX - reinvestment + residual value
      const net_cash_flow = savings_year - opex_year - reinvestmentCapex + residualValueYear;
      cumulative_cash_flow += net_cash_flow;

      cash_flows.push({
        year: year,
        savings: savings_year,
        opex: opex_year,
        reinvestmentCapex: reinvestmentCapex,      // P0-1: Combined BESS + Inverter replacement
        bessReplacementCost: reinvestmentCapex,    // P0-1: Alias for backward compatibility
        residualValue: residualValueYear,          // P0-2: Track residual value
        net_cash_flow: net_cash_flow,
        cumulative_cash_flow: cumulative_cash_flow,
        production: production_year,        // MWh - for display
        selfConsumed: self_consumed_year,   // MWh - for display (use selfConsumed for consistency)
        unit: 'MWh'                         // Mark unit explicitly
      });
    }

    // 6. NPV i IRR - uproszczone
    // NPV = suma zdyskontowanych przepływów - CAPEX
    // P0-3 FIX: Use getEffectiveDiscountRate() for nominal/real consistency
    const discountRateResult = getEffectiveDiscountRate(window.economicsSettings || {});
    const discount_rate = discountRateResult.effectiveRate; // Extract numeric value
    if (DEBUG_ECONOMICS) {
      console.log(`📊 NPV Calculation using ${discountRateResult.mode} discount_rate:`, decimalToPct(discount_rate).toFixed(2), '%');
      if (discountRateResult.isConverted) {
        console.log(`   (converted from real rate, inflation: ${decimalToPct(discountRateResult.inflationRate).toFixed(1)}%)`);
      }
    }
    let npv = -capex;
    for (let cf of cash_flows) {
      npv += cf.net_cash_flow / Math.pow(1 + discount_rate, cf.year);
    }

    // IRR - przybliżone (metoda Newton-Raphson)
    let irr = calculateIRR()

    // 7. LCOE - Levelized Cost of Energy
    // LCOE = (CAPEX + suma zdyskontowanych OPEX + reinvestment) / suma zdyskontowanej produkcji
    // P0-1: Include reinvestment costs (BESS + Inverter) in LCOE calculation
    let discounted_costs = capex;
    let discounted_production = 0;
    for (let cf of cash_flows) {
      discounted_costs += cf.opex / Math.pow(1 + discount_rate, cf.year);
      // P0-1: Add reinvestment costs (BESS + Inverter) to total discounted costs
      discounted_costs += (cf.reinvestmentCapex || 0) / Math.pow(1 + discount_rate, cf.year);
      discounted_production += cf.production / Math.pow(1 + discount_rate, cf.year);
    }
    const lcoe = discounted_costs / discounted_production; // PLN/MWh

    // Backend economics parameters (single source of truth for IRR/NPV)
    // P0-3: Use effective discount rate for nominal/real consistency
    const backendParams = {
      energy_price: totalEnergyPrice, // PLN/MWh
      feed_in_tariff: params.feed_in_tariff || 0,
      investment_cost: capexPerKwp, // PLN/kWp (tiered)
      export_mode: params.export_mode || 'zero',
      discount_rate: discount_rate, // P0-3: Use calculated effective rate
      degradation_rate: params.degradation_rate,
      opex_per_kwp: params.opex_per_kwp,
      analysis_period: params.analysis_period,
      use_inflation: window.economicsSettings?.useInflation || false,
      irr_mode: window.economicsSettings?.irrMode || ((window.economicsSettings?.useInflation) ? 'nominal' : 'real'),
      inflation_rate: window.economicsSettings?.inflationRate ?? 0.0,
      // P0-3: Rate mode for backend reference
      rate_mode: window.economicsSettings?.rateMode || 'nominal',
      // P0-1: BESS replacement parameters
      bess_replacement_schedule: reinvestmentSchedule,
      // P0-2: Residual value
      residual_value: residualValue
    };

    // Pull IRR/NPV from backend economics service
    let backendEconomics = null;
    try {
      backendEconomics = await fetchBackendIRR(variant, backendParams);
      console.log('? Backend economics result received');
    } catch (err) {
      console.error('? Backend economics call failed, IRR unavailable:', err);
    }

    const irrValue = backendEconomics?.irr ?? null;
    const irrMode = backendEconomics?.irr_details?.mode || backendParams.irr_mode;
    const irrStatus = backendEconomics?.irr_details?.status || (irrValue !== null ? 'converged' : 'failed');

    economicData = {
      investment: capex,
      simple_payback: simple_payback,
      npv: backendEconomics?.npv ?? npv,
      irr: irrValue,
      irrMode: irrMode,
      irrStatus: irrStatus,
      irrDetails: backendEconomics?.irr_details || null,
      lcoe: lcoe / 1000, // MWh -> kWh
      annual_savings: savings_year1,
      annual_total_revenue: savings_year1,
      annual_export_revenue: 0,
      cash_flows: cash_flows,
      centralized_cash_flows: backendEconomics?.cash_flows || cash_flows,
      // P0-1: Reinvestment info (BESS + Inverter)
      reinvestmentSchedule: reinvestmentSchedule,            // { year: cost } for lookup
      bessReplacementSchedule: reinvestmentSchedule,         // Alias for backward compatibility
      bessReplacementScheduleArray: bessReplacementScheduleArray,
      inverterReplacementScheduleArray: inverterReplacementScheduleArray,
      totalReinvestmentCost: totalReinvestmentCost,
      totalBessReplacementCost: totalReinvestmentCost,       // Alias for backward compat
      // P0-2: Residual value info
      residualValue: residualValue,                    // Numeric value
      residualValueResult: residualValueResult,        // Full object with mode/yearMode/description
      residualValueMode: residualValueResult.mode,
      residualValueYearMode: residualValueResult.yearMode,
      metrics: {
        annual_opex: opex_annual,
        capacity_kwp: capacity_kwp,
        total_energy_price: totalEnergyPrice
      },
      parameters: {
        ...params,
        energy_price: totalEnergyPrice,
        investment_cost: capexPerKwp,
        use_inflation: backendParams.use_inflation,
        irr_mode: irrMode,
        inflation_rate: backendParams.inflation_rate,
        // P0-3: Rate mode info
        rate_mode: backendParams.rate_mode,
        effective_discount_rate: discount_rate,
        discount_rate_input: discountRateResult.inputRate,
        discount_rate_converted: discountRateResult.isConverted
      },
      backendEconomics
    };

    console.log('? Calculated economic analysis (using backend NPV/IRR):', economicData);

    // Update UI
    updateMetrics(economicData);
    updateDataInfo();

    // Generate charts (don't need centralizedMetrics)
    generateCashFlowChart(economicData);
    generateRevenueChart(economicData);

    // PRECISE MODE: fetch backend-computed hourly savings (same methodology as Excel)
    // This populates preciseAnnualSavings which is then used by calculateCentralizedFinancialMetrics()
    if (!hasBess) {
      console.log('📊 Fetching precise annual savings from backend (Excel-consistent)...');
      await fetchPreciseAnnualSavings(variant);
    }

    // CRITICAL: calculateEaaS() MUST run FIRST - it populates centralizedMetrics[currentVariant]
    // ALL tables below depend on centralizedMetrics being set!
    console.log('🎯 About to call calculateEaaS()...');
    await calculateEaaS();
    console.log('🎯 calculateEaaS() completed - centralizedMetrics should now be set');

    // Store for later re-rendering (e.g., after optimization recalculates with PRECISE)
    window._lastEconomicData = economicData;

    // Generate tables - ALL require centralizedMetrics to be set
    generateRevenueTable(economicData);
    generatePaybackTable(economicData, capacity_kwp, params);

    // Generate sensitivity analysis charts (CAPEX vs EaaS)
    console.log('📊 About to call generateSensitivityAnalysisCharts()...');
    generateSensitivityAnalysisCharts();
    console.log('📊 generateSensitivityAnalysisCharts() completed');

    // Update ESG Dashboard
    console.log('🌱 About to call updateESGDashboard()...');
    updateESGDashboard();
    console.log('🌱 updateESGDashboard() completed');

    // Update BESS Economics Section
    console.log('🔋 About to call updateBessEconomicsSection()...');
    updateBessEconomicsSection();
    console.log('🔋 updateBessEconomicsSection() completed');

    // Generate Variant Scan section (chart + table)
    console.log('📊 About to call generateVariantScanSection()...');
    generateVariantScanSection();
    console.log('📊 generateVariantScanSection() completed');

    // Generate PULS DNIA chart (async - fetches real data from API)
    console.log('📈 About to call generatePulsDniaChart()...');
    // Ensure calendar is initialized before generating chart
    if (typeof initializePulsDniaCalendar === 'function') {
      initializePulsDniaCalendar();
    }
    // Note: async function, but we don't await to avoid blocking
    generatePulsDniaChart().then(() => {
      console.log('📈 generatePulsDniaChart() completed');
    }).catch(err => {
      console.warn('📈 generatePulsDniaChart() error:', err.message);
    });

    // TCSL Unified Cost comparison (async, non-blocking)
    console.log('⚡ TCSL: About to call calculateTcslComparison');
    calculateTcslComparison(variant).then(() => {
      console.log('⚡ TCSL comparison completed');
    }).catch(err => {
      console.warn('⚡ TCSL comparison error:', err.message);
    });

  } catch (error) {
    console.error('❌ Error performing economic analysis:', error);
    showNoData();
  } finally {
    _peaRunning = false;
  }
}

// Legacy function for backward compatibility
function performAnalysis() {
  performEconomicAnalysis();
}

// Generate sample economic data — reads from settings, no hardcoded financial params
function generateSampleEconomicData(config) {
  const capacity = config.installedCapacity || 1000; // kWp
  const unitCost = getCapexForCapacity(capacity) || 3500; // PLN/kWp

  return {
    capex: capacity * unitCost,
    opexAnnual: capacity * (systemSettings?.opexPerKwp || 24), // PLN/year
    energyPrice: (window.economicsSettings?.totalEnergyPrice || 961) / 1000, // PLN/kWh
    discountRate: window.economicsSettings?.discountRate,
    analysisHorizon: systemSettings?.analysisPeriod || 25,
    inflationRate: window.economicsSettings?.inflationRate,
    taxRate: 0.19,
    subsidies: 0
  };
}

// Calculate financial metrics — reads from centralizedMetrics (SSoT)
function calculateFinancialMetrics() {
  const cm = centralizedMetrics[currentVariant];
  if (!cm || !cm.common) {
    console.warn('⚠️ calculateFinancialMetrics: centralizedMetrics not available, returning empty');
    return null;
  }

  const c = cm.common;
  const annualSavings = c.selfConsumedMwh * c.totalEnergyPrice;
  const annualOpex = c.capacityKwp * c.opexPerKwp;
  const netAnnualSavings = annualSavings - annualOpex;
  const roi = c.totalCapex > 0 ? (c.capexNpv / c.totalCapex) * 100 : 0;

  return {
    capex: formatNumberEU(plnToMlnPln(c.totalCapex), 2),
    paybackPeriod: formatNumberEU(c.simplePayback, 1),
    npv: formatNumberEU(plnToMlnPln(c.capexNpv), 2),
    irr: c.capexIrr != null ? formatNumberEU(decimalToPct(c.capexIrr), 1) : 'N/A',
    unitCapex: `${formatNumberEU(c.capexPerKwp, 0)} PLN/kWp`,
    lcoe: `${formatNumberEU(c.lcoe / 1000, 2)} PLN/kWh`,
    opexAnnual: `${formatNumberEU(plnToTysPln(annualOpex), 0)} tys. PLN`,
    revenueAnnual: `${formatNumberEU(plnToTysPln(annualSavings), 0)} tys. PLN`,
    savingsAnnual: `${formatNumberEU(plnToTysPln(netAnnualSavings), 0)} tys. PLN`,
    roi: `${formatNumberEU(roi, 1)}%`,
    discountRate: `${formatNumberEU(decimalToPct(c.discountRate), 1)}%`,
    analysisHorizon: `${c.analysisPeriod} lat`,
    energyPrice: `${formatNumberEU(c.totalEnergyPrice / 1000, 2)} PLN/kWh`,
    subsidies: `${formatNumberEU(plnToTysPln(economicData?.subsidies || 0), 0)} tys. PLN`,
    taxRate: `${formatNumberEU((economicData?.taxRate || 0.19) * 100, 0)}%`,
    inflationRate: `${formatNumberEU(decimalToPct(c.inflationRate), 1)}%`
  };
}

// Update metrics display
function updateMetrics(data) {
  // Main metrics from backend API - European format
  document.getElementById('capex').textContent = formatNumberEU(plnToMlnPln(data.investment), 2); // PLN → mln PLN
  document.getElementById('paybackPeriod').textContent = formatNumberEU(data.simple_payback, 1);
  document.getElementById('npv').textContent = formatNumberEU(plnToMlnPln(data.npv), 2); // PLN → mln PLN

  // Update CAPEX breakdown (PV + BESS)
  updateCapexBreakdown(data);

  // IRR with mode indicator
  const irrValue = data.irr;
  const irrMode = data.irrMode || centralizedMetrics[currentVariant]?.capex?.irrMode || 'real';
  const irrStatus = data.irrStatus || 'converged';

  const irrElement = document.getElementById('irr');
  if (irrElement) {
    if (irrValue === null || irrValue === undefined || irrStatus === 'no_root' || irrStatus === 'failed') {
      irrElement.textContent = 'N/A';
      irrElement.title = data.irrMessage || 'IRR niedostępne';
    } else {
      irrElement.textContent = formatNumberEU(decimalToPct(irrValue), 1); // decimal → %
      irrElement.title = `IRR ${irrMode === 'nominal' ? 'nominalny' : 'realny'}`;
    }
  }

  // Add IRR mode indicator if not already present
  const irrModeIndicator = document.getElementById('irrModeIndicator');
  if (!irrModeIndicator) {
    const irrContainer = irrElement?.parentElement;
    if (irrContainer) {
      const modeSpan = document.createElement('span');
      modeSpan.id = 'irrModeIndicator';
      modeSpan.style.cssText = 'font-size:10px;color:#666;margin-left:4px;';
      modeSpan.textContent = irrMode === 'nominal' ? '(nom.)' : '(real)';
      irrContainer.appendChild(modeSpan);
    }
  } else {
    irrModeIndicator.textContent = irrMode === 'nominal' ? '(nom.)' : '(real)';
  }

  // Detailed metrics - European format
  const variant = variants[currentVariant];
  const capacity_kwp = variant.capacity; // Already in kWp

  document.getElementById('unitCapex').textContent = `${formatNumberEU(data.investment / capacity_kwp, 0)} PLN/kWp`;
  document.getElementById('lcoe').textContent = `${formatNumberEU(data.lcoe * 1000, 2)} PLN/kWh`; // /kWh → /kWh
  document.getElementById('opexAnnual').textContent = `${formatNumberEU(plnToTysPln(data.metrics.annual_opex), 0)} tys. PLN`;
  document.getElementById('revenueAnnual').textContent = `${formatNumberEU(plnToTysPln(data.annual_total_revenue), 0)} tys. PLN`;
  document.getElementById('savingsAnnual').textContent = `${formatNumberEU(plnToTysPln(data.annual_savings), 0)} tys. PLN`;
  document.getElementById('roi').textContent = `${formatNumberEU((data.npv / data.investment) * 100, 1)}%`;

  // Display parameters from sidebar inputs - European format
  const params = data.parameters;
  const discountRateValue = window.economicsSettings?.discountRate;
  document.getElementById('discountRate').textContent = `${formatNumberEU(discountRateValue * 100, 1)}%`;
  document.getElementById('analysisHorizon').textContent = `${params.analysis_period} lat`;
  document.getElementById('energyPrice').textContent = `${formatNumberEU(data.metrics.total_energy_price, 0)} PLN/MWh`;
  document.getElementById('subsidies').textContent = '0 PLN'; // Not implemented yet
  document.getElementById('taxRate').textContent = '0%'; // Not implemented yet
  document.getElementById('inflationRate').textContent = `${formatNumberEU(params.degradation_rate * 100, 1)}%`; // Show degradation rate
}

// Update data info
function updateDataInfo() {
  if (!variants || !currentVariant) return;

  const variant = variants[currentVariant];
  const capacity = formatNumberEU(kwhToMwh(variant.capacity), 1); // kWp → MWp
  const params = getEconomicParameters();
  const irrMode = economicData?.irrMode || centralizedMetrics[currentVariant]?.capex?.irrMode || 'real';
  const irrValue = economicData?.irr;
  const irrDisplay = irrValue !== null && irrValue !== undefined
    ? `${formatNumberEU(decimalToPct(irrValue), 1)}% (${irrMode === 'nominal' ? 'nom.' : 'real'})`
    : 'N/A';
  const info = `Wariant ${currentVariant}: ${capacity} MWp • Analiza ${params.analysis_period}-letnia • IRR: ${irrDisplay}`;
  document.getElementById('dataInfo').textContent = info;

  // Update BESS info line if BESS is enabled
  updateBessInfoLine(variant);
}

// Update BESS info line in header
function updateBessInfoLine(variant) {
  const bessInfoLine = document.getElementById('bessInfoLine');
  const bessInfoText = document.getElementById('bessInfoText');

  if (!bessInfoLine || !bessInfoText) return;

  const hasBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;

  if (hasBess) {
    const powerKw = variant.bess_power_kw;
    const energyKwh = variant.bess_energy_kwh;
    const duration = powerKw > 0 ? (energyKwh / powerKw).toFixed(1) : 0;

    bessInfoText.textContent = `BESS: ${formatNumberEU(powerKw, 0)} kW / ${formatNumberEU(energyKwh, 0)} kWh (${duration}h)`;
    bessInfoLine.style.display = 'block';
  } else {
    bessInfoLine.style.display = 'none';
  }
}

// Update CAPEX breakdown showing PV and BESS costs separately
function updateCapexBreakdown(data) {
  const variant = variants[currentVariant];
  const capexBreakdown = document.getElementById('capexBreakdown');
  const capexPVEl = document.getElementById('capexPV');
  const capexBESSEl = document.getElementById('capexBESS');

  if (!capexBreakdown || !capexPVEl || !capexBESSEl) return;

  const hasBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;

  if (hasBess) {
    // Get BESS economic parameters from settings
    const bessSettings = systemSettings || {};
    const bessCapexPerKwh = bessSettings.bessCapexPerKwh || 1500;
    const bessCapexPerKw = bessSettings.bessCapexPerKw || 300;

    // Calculate BESS CAPEX
    const bessCapexEnergy = variant.bess_energy_kwh * bessCapexPerKwh;
    const bessCapexPower = variant.bess_power_kw * bessCapexPerKw;
    const bessCapexTotal = bessCapexEnergy + bessCapexPower;

    // Calculate PV CAPEX directly from capacity and tier price
    const pvCapexPerKwp = getCapexForCapacity(variant.capacity);
    const pvCapex = variant.capacity * pvCapexPerKwp;

    // Total should match what's displayed
    const totalCapex = pvCapex + bessCapexTotal;

    console.log('💰 CAPEX Breakdown (updateCapexBreakdown):', {
      pvCapex: pvCapex,
      bessCapex: bessCapexTotal,
      calculatedTotal: totalCapex,
      displayedTotal: data.investment
    });

    // Update display
    capexPVEl.textContent = formatNumberEU(plnToMlnPln(pvCapex), 2);
    capexBESSEl.textContent = formatNumberEU(plnToMlnPln(bessCapexTotal), 2);
    capexBreakdown.style.display = 'block';
  } else {
    capexBreakdown.style.display = 'none';
  }
}

// Generate CAPEX structure chart
function generateCapexChart() {
  const ctx = document.getElementById('capexStructure').getContext('2d');

  if (capexChart) capexChart.destroy();

  const capacity = pvConfig?.installedCapacity || 1000;
  const totalCapex = economicData?.capex || capacity * getCapexForCapacity(capacity);

  const data = {
    modules: (totalCapex * 0.40).toFixed(0),
    inverters: (totalCapex * 0.15).toFixed(0),
    construction: (totalCapex * 0.25).toFixed(0),
    electrical: (totalCapex * 0.10).toFixed(0),
    other: (totalCapex * 0.10).toFixed(0)
  };

  capexChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Moduły PV', 'Inwertery', 'Konstrukcja', 'Instalacja Elektryczna', 'Inne'],
      datasets: [{
        data: Object.values(data),
        backgroundColor: [
          '#27ae60',
          '#2ecc71',
          '#3498db',
          '#9b59b6',
          '#95a5a6'
        ],
        borderWidth: 2,
        borderColor: '#fff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          display: true,
          position: 'bottom'
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return context.label + ': ' + plnToTysPln(context.parsed).toFixed(0) + ' tys. PLN';
            }
          }
        }
      }
    }
  });
}

// Generate OPEX structure chart
function generateOpexChart() {
  const ctx = document.getElementById('opexStructure').getContext('2d');

  if (opexChart) opexChart.destroy();

  const opexAnnual = economicData?.opexAnnual || (pvConfig?.installedCapacity || 1000) * 50;

  const data = {
    maintenance: (opexAnnual * 0.40).toFixed(0),
    insurance: (opexAnnual * 0.25).toFixed(0),
    monitoring: (opexAnnual * 0.15).toFixed(0),
    cleaning: (opexAnnual * 0.10).toFixed(0),
    administration: (opexAnnual * 0.10).toFixed(0)
  };

  opexChart = new Chart(ctx, {
    type: 'pie',
    data: {
      labels: ['Konserwacja', 'Ubezpieczenie', 'Monitoring', 'Czyszczenie', 'Administracja'],
      datasets: [{
        data: Object.values(data),
        backgroundColor: [
          '#e74c3c',
          '#e67e22',
          '#f39c12',
          '#f1c40f',
          '#95a5a6'
        ],
        borderWidth: 2,
        borderColor: '#fff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          display: true,
          position: 'bottom'
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return context.label + ': ' + plnToTysPln(context.parsed).toFixed(1) + ' tys. PLN/rok';
            }
          }
        }
      }
    }
  });
}

// Generate cash flow chart
function generateCashFlowChart(data) {
  if (!data || !data.cash_flows) return;

  const ctx = document.getElementById('cashFlow').getContext('2d');
  if (cashFlowChart) cashFlowChart.destroy();

  const years = data.cash_flows.map(cf => cf.year);
  const cumulativeCashFlow = data.cash_flows.map(cf => plnToMlnPln(cf.cumulative_cash_flow).toFixed(2)); // PLN → mln PLN

  cashFlowChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: years,
      datasets: [{
        label: 'Skumulowane CF [mln PLN]',
        data: cumulativeCashFlow,
        borderColor: '#27ae60',
        backgroundColor: 'rgba(39, 174, 96, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          title: { display: true, text: 'Wartość [mln PLN]' }
        },
        x: {
          title: { display: true, text: 'Rok' }
        }
      }
    }
  });
}

// Generate revenue vs costs chart
function generateRevenueChart() {
  const ctx = document.getElementById('revenueVsCosts').getContext('2d');

  if (revenueChart) revenueChart.destroy();

  const capacity = pvConfig?.installedCapacity || 1000;
  const opexAnnual = economicData?.opexAnnual || capacity * 50;
  const energyPrice = economicData?.energyPrice || 0.65;
  const annualProduction = capacity * 1000;
  const horizon = Math.min(economicData?.analysisHorizon || 25, 10); // Show first 10 years

  const years = [];
  const revenues = [];
  const costs = [];

  for (let year = 1; year <= horizon; year++) {
    years.push(`Rok ${year}`);
    revenues.push(plnToTysPln(annualProduction * energyPrice).toFixed(0));
    costs.push(plnToTysPln(opexAnnual).toFixed(0));
  }

  revenueChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: years,
      datasets: [
        {
          label: 'Przychody [tys. PLN]',
          data: revenues,
          backgroundColor: 'rgba(39, 174, 96, 0.7)',
          borderColor: '#27ae60',
          borderWidth: 2
        },
        {
          label: 'Koszty OPEX [tys. PLN]',
          data: costs,
          backgroundColor: 'rgba(231, 76, 60, 0.7)',
          borderColor: '#e74c3c',
          borderWidth: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Wartość [tys. PLN]' }
        }
      }
    }
  });
}

// ============================================
// PULS DNIA - 24h Energy Profile Visualization
// ============================================

// Cache for real hourly data from API
let cachedHourlyConsumption = null; // {timestamps: [], values: []}
let cachedHourlyProduction = null;  // {timestamps: [], values: []}
let pulsDniaDataLoading = false;

/**
 * Fetch real hourly data from data-analysis API
 * Returns data for the entire year, which we then filter by selected day
 */
async function fetchRealHourlyData() {
  // Return cached data if available
  if (cachedHourlyConsumption) {
    console.log('📊 Using cached hourly consumption data');
    return { consumption: cachedHourlyConsumption, production: cachedHourlyProduction };
  }

  if (pulsDniaDataLoading) {
    console.log('📊 Data already loading, waiting for completion...');
    // Poll until loading finishes (up to 10 seconds)
    for (let i = 0; i < 20; i++) {
      await new Promise(resolve => setTimeout(resolve, 500));
      if (cachedHourlyConsumption) {
        console.log('📊 Data loaded after waiting', (i + 1) * 500, 'ms');
        return { consumption: cachedHourlyConsumption, production: cachedHourlyProduction };
      }
    }
    console.warn('📊 Timed out waiting for hourly data load');
    return { consumption: cachedHourlyConsumption, production: cachedHourlyProduction };
  }

  pulsDniaDataLoading = true;

  // Determine API base URL - handle iframe context
  const apiBaseUrl = window.location.origin;
  const apiUrl = `${apiBaseUrl}/api/data/hourly-data`;
  console.log('📊 PULS DNIA: ============================================');
  console.log('📊 PULS DNIA: FETCHING REAL HOURLY DATA');
  console.log('📊 PULS DNIA: API URL:', apiUrl);
  console.log('📊 PULS DNIA: window.location.origin:', window.location.origin);
  console.log('📊 PULS DNIA: ============================================');

  try {
    // Fetch consumption data from data-analysis API
    const consResponse = await fetch(apiUrl);
    console.log('📊 PULS DNIA: API response status:', consResponse.status);

    if (consResponse.ok) {
      cachedHourlyConsumption = await consResponse.json();
      const rawLen = cachedHourlyConsumption.values?.length || 0;
      console.log(`📊 PULS DNIA: Loaded ${rawLen} consumption points`);
      console.log(`📊 PULS DNIA: Sample timestamps:`, cachedHourlyConsumption.timestamps?.slice(0, 3));

      // Convert 15-min data to hourly by averaging (power kW → kWh per hour)
      // This ensures all downstream code (export, K-class, LDC) gets consistent hourly data
      if (rawLen > 10000 && cachedHourlyConsumption.values) {
        console.log(`📊 PULS DNIA: Converting ${rawLen} 15-min points to hourly`);
        const vals = cachedHourlyConsumption.values;
        const hourlyVals = [];
        const hourlyTs = [];
        for (let h = 0; h < Math.floor(rawLen / 4); h++) {
          const s = h * 4;
          hourlyVals.push(((vals[s] || 0) + (vals[s+1] || 0) + (vals[s+2] || 0) + (vals[s+3] || 0)) / 4);
          if (cachedHourlyConsumption.timestamps) {
            hourlyTs.push(cachedHourlyConsumption.timestamps[s]);
          }
        }
        cachedHourlyConsumption.values = hourlyVals;
        if (hourlyTs.length > 0) cachedHourlyConsumption.timestamps = hourlyTs;
        console.log(`📊 PULS DNIA: Converted to ${hourlyVals.length} hourly points`);
      }
    } else {
      console.warn('📊 PULS DNIA: Could not fetch consumption data:', consResponse.status);
      pulsDniaDataLoading = false;
      return null;
    }

    // Try to get production data from various sources
    // Priority: 1) key_variants PVGIS data, 2) productionData, 3) analysisResults.hourly_production
    const variantKey = window.currentVariant || 'B';
    const variantData = analysisResults?.key_variants?.[variantKey];

    if (variantData?.hourly_production && variantData.hourly_production.length > 0) {
      // BEST SOURCE: PVGIS hourly production from key_variants (real meteorological data)
      cachedHourlyProduction = {
        timestamps: cachedHourlyConsumption?.timestamps || [],
        values: variantData.hourly_production
      };
      console.log(`📊 PULS DNIA: Using key_variants[${variantKey}].hourly_production (PVGIS data, ${cachedHourlyProduction.values?.length || 0} points)`);
    } else if (productionData?.hourlyProduction && productionData.hourlyProduction.length > 0) {
      cachedHourlyProduction = {
        timestamps: cachedHourlyConsumption?.timestamps || [],
        values: productionData.hourlyProduction
      };
      console.log(`📊 PULS DNIA: Using productionData.hourlyProduction (${cachedHourlyProduction.values?.length || 0} points)`);
    } else if (analysisResults?.hourly_production && analysisResults.hourly_production.length > 0) {
      cachedHourlyProduction = {
        timestamps: cachedHourlyConsumption?.timestamps || [],
        values: analysisResults.hourly_production
      };
      console.log(`📊 PULS DNIA: Using analysisResults.hourly_production (${cachedHourlyProduction.values?.length || 0} points)`);
    } else {
      console.log('📊 PULS DNIA: No hourly production data available - will use synthetic profile');
      console.log(`   Checked: key_variants[${variantKey}].hourly_production, productionData.hourlyProduction, analysisResults.hourly_production`);
      // Production will be calculated synthetically in generateTypicalDayProfiles
      cachedHourlyProduction = null;
    }

    pulsDniaDataLoading = false;
    return { consumption: cachedHourlyConsumption, production: cachedHourlyProduction };
  } catch (error) {
    console.error('📊 PULS DNIA: Error fetching hourly data:', error);
    pulsDniaDataLoading = false;
    return null;
  }
}

/**
 * Get real hourly data for a specific day
 * Returns 24 data points for the selected date
 *
 * IMPORTANT: Production data (PVGIS) uses the same index mapping as consumption
 * because both arrays represent the same analytical year period (8760 hours).
 */
function getRealDayData(month, day, consumption, production) {
  if (!consumption?.timestamps || !consumption?.values) {
    console.log('📊 No consumption data available');
    return null;
  }

  // DEBUG: Log input data structure
  console.log('📊 getRealDayData DEBUG:');
  console.log('  - consumption.timestamps length:', consumption.timestamps?.length);
  console.log('  - consumption.values length:', consumption.values?.length);
  console.log('  - production.values length:', production?.values?.length || 0);
  console.log('  - First 3 timestamps:', consumption.timestamps?.slice(0, 3));
  console.log('  - First 3 consumption values:', consumption.values?.slice(0, 3));
  if (production?.values) {
    console.log('  - First 3 production values:', production.values.slice(0, 3).map(v => v?.toFixed(2)));
    console.log('  - Max production value:', Math.max(...production.values).toFixed(2));
  }

  // Build target date string (assuming data is from current or recent year)
  // We'll match by month and day regardless of year
  const targetMonth = String(month).padStart(2, '0');
  const targetDay = String(day).padStart(2, '0');

  const dayData = [];
  const hourlyAggregation = {}; // Aggregate multiple measurements per hour

  // Check if production data is available and has the same length as consumption
  const hasProductionData = production?.values && production.values.length === consumption.values.length;
  if (hasProductionData) {
    console.log(`📊 Production data available (${production.values.length} points, same as consumption)`);
  } else if (production?.values) {
    console.log(`📊 Production data length mismatch: prod=${production.values.length}, cons=${consumption.values.length}`);
  }

  for (let i = 0; i < consumption.timestamps.length; i++) {
    const ts = consumption.timestamps[i];
    const date = new Date(ts);
    const tsMonth = String(date.getMonth() + 1).padStart(2, '0');
    const tsDay = String(date.getDate()).padStart(2, '0');

    if (tsMonth === targetMonth && tsDay === targetDay) {
      const hour = date.getHours();
      const consValue = consumption.values[i] || 0;
      // Use same index for production - both arrays are aligned by analytical year
      const prodValue = hasProductionData ? (production.values[i] || 0) : 0;

      // Aggregate by hour (in case of 15-min or sub-hourly data)
      if (!hourlyAggregation[hour]) {
        hourlyAggregation[hour] = { consumption: 0, production: 0, count: 0 };
      }
      hourlyAggregation[hour].consumption += consValue;
      hourlyAggregation[hour].production += prodValue;
      hourlyAggregation[hour].count += 1;
    }
  }

  // Convert aggregated data to array, averaging if multiple points per hour
  for (const hour of Object.keys(hourlyAggregation).map(Number).sort((a, b) => a - b)) {
    const agg = hourlyAggregation[hour];
    dayData.push({
      hour: hour,
      timestamp: `${targetMonth}-${targetDay} ${hour}:00`,
      consumption: agg.consumption / agg.count, // Average if multiple points
      production: agg.production / agg.count
    });
  }

  console.log(`📊 Found ${dayData.length} data points for ${day}/${month}`);
  if (dayData.length > 0) {
    console.log('📊 Sample data points:');
    dayData.slice(0, 3).forEach(d => {
      console.log(`  Hour ${d.hour}: consumption=${d.consumption.toFixed(2)} kW, production=${d.production.toFixed(2)} kW`);
    });
    const totalDayCons = dayData.reduce((sum, d) => sum + d.consumption, 0);
    const totalDayProd = dayData.reduce((sum, d) => sum + d.production, 0);
    console.log(`📊 Total day: consumption=${totalDayCons.toFixed(2)} kWh, production=${totalDayProd.toFixed(2)} kWh`);
  }
  return dayData.length > 0 ? dayData : null;
}

/**
 * Update calendar day selector based on selected month
 */
function updatePulsDniaCalendar() {
  const monthSelect = document.getElementById('pulsDniaMonth');
  const daySelect = document.getElementById('pulsDniaDay');
  if (!monthSelect || !daySelect) return;

  const month = parseInt(monthSelect.value);
  const daysInMonth = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const numDays = daysInMonth[month - 1];

  // Remember current selection if valid
  const currentDay = parseInt(daySelect.value) || 15;

  // Populate days
  daySelect.innerHTML = '';
  for (let d = 1; d <= numDays; d++) {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = d;
    if (d === Math.min(currentDay, numDays)) opt.selected = true;
    daySelect.appendChild(opt);
  }

  // Regenerate chart (async)
  generatePulsDniaChart().catch(err => console.warn('📈 Chart error:', err.message));
}

/**
 * Get solar parameters for a specific day of year
 * Returns dayLength, production factor, consumption factor
 */
function getSolarParametersForDay(month, day) {
  // Day of year calculation (approximate)
  const daysInMonth = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  const dayOfYear = daysInMonth[month - 1] + day;

  // Day length calculation based on latitude ~52°N (Poland)
  // Varies from ~8h (Dec 21) to ~16.5h (Jun 21)
  const summerSolstice = 172; // June 21
  const dayAngle = 2 * Math.PI * (dayOfYear - summerSolstice) / 365;
  const dayLength = 12.25 + 4.25 * Math.cos(dayAngle); // 8h to 16.5h

  // Production factor - solar irradiance varies through year
  // Peak in June, minimum in December
  const productionFactor = 0.5 + 0.5 * Math.cos(dayAngle); // 0 (winter) to 1 (summer)

  // Consumption factor - slightly higher in winter (heating, lighting)
  const consumptionFactor = 1.0 + 0.15 * Math.cos(dayAngle + Math.PI); // Higher in winter

  return { dayLength, productionFactor, consumptionFactor, dayOfYear };
}

/**
 * Get RDN hourly prices from centralized PriceConfig or localStorage fallback.
 * @returns {Array<number>|null} Array of PLN/MWh values (8760 hours) or null
 */
function _getRdnHourlyPrices() {
  const pc = _getPriceConfig();
  if (pc?.rdnPrices?.available) return pc.rdnPrices.hourlyPricesPlnMwh;
  // Fallback to localStorage
  try {
    const cached = localStorage.getItem('rdn_hourly_prices');
    if (cached) {
      const arr = JSON.parse(cached);
      if (Array.isArray(arr) && arr.length > 100) return arr;
    }
  } catch (e) { /* ignore */ }
  return null;
}

/**
 * Get centralized PriceConfig from shell or cached.
 * @returns {Object|null}
 */
function _getPriceConfig() {
  // 1. Cached from message handler
  if (window._cachedPriceConfig) return window._cachedPriceConfig;
  // 2. From shell sharedData
  const parentWindow = window.parent !== window ? window.parent : window;
  if (parentWindow.sharedData?.priceConfig) return parentWindow.sharedData.priceConfig;
  // 3. Build locally if buildPriceConfig available
  if (parentWindow.buildPriceConfig) {
    const pc = parentWindow.buildPriceConfig(systemSettings || {});
    window._cachedPriceConfig = pc;
    return pc;
  }
  return null;
}

/**
 * Get the correct energy rate for a specific hour based on pricing mode.
 * Returns rate in PLN/kWh (energia czynna only, without fixed fees).
 *
 * v4.0: Delegates to centralized PriceConfig when available.
 */
function getHourlyEnergyRate(h, month, dayOfMonth, isWeekend) {
  // Try centralized PriceConfig first (from shell)
  const pc = _getPriceConfig();
  if (pc && pc.getEnergyRate) {
    // For RDN mode: need timestep index
    const pricingMode = pc.pricingMode || 'single';
    const useRdn = (pricingMode === 'hybrid_monthly' && pc.monthlyPriceSources?.[month] === 'rdn') ||
                   (pc.rdnEnabled && !pc.osdEnabled);

    if (useRdn && pc.rdnPrices?.available) {
      const dayOfYear = getDayOfYear(month, dayOfMonth);
      const hourIndex = (dayOfYear - 1) * 24 + h;
      const rdnArr = pc.rdnPrices.hourlyPricesPlnMwh;
      if (rdnArr && hourIndex < rdnArr.length) {
        return rdnArr[hourIndex] / 1000; // PLN/MWh -> PLN/kWh
      }
    }
    // OSD/ToU path via centralized config
    return pc.getEnergyRate(h, isWeekend);
  }

  // Fallback: direct settings read (legacy path)
  const settings = systemSettings || {};
  const tc = settings.tariffConfig;
  if (!tc) return 0.51;
  const type = tc.type || 'two_zone';
  if (type === 'flat') return (tc.flatRate || 750) / 1000;
  if (type === 'two_zone') {
    const dayStart = isWeekend ? (tc.twoZone?.weekend?.start || 6) : (tc.twoZone?.weekday?.start || 6);
    const dayEnd = isWeekend ? (tc.twoZone?.weekend?.end || 13) : (tc.twoZone?.weekday?.end || 22);
    return (h >= dayStart && h < dayEnd) ? (tc.twoZone?.dayRate || 850) / 1000 : (tc.twoZone?.nightRate || 450) / 1000;
  }
  if (type === 'three_zone') {
    const p1s = tc.threeZone?.peak1?.start || 7, p1e = tc.threeZone?.peak1?.end || 13;
    const p2s = tc.threeZone?.peak2?.start || 17, p2e = tc.threeZone?.peak2?.end || 21;
    if ((h >= p1s && h < p1e) || (h >= p2s && h < p2e)) return isWeekend ? (tc.threeZone?.offPeakRate || 400) / 1000 : (tc.threeZone?.peakRate || 950) / 1000;
    if (h < 6 || h >= 22) return (tc.threeZone?.offPeakRate || 400) / 1000;
    return (tc.threeZone?.partialRate || 700) / 1000;
  }
  return 0.51;
}

/**
 * Build distribution config payload for backend API from settings.
 */
function getDistConfigPayload(settings) {
  const dc = settings?.distributionConfig || {};
  const type = dc.type || 'three_zone';
  const payload = {
    dist_zone_type: type,
    dist_two_zone_weekday_start: dc.twoZone?.weekday?.start ?? 6,
    dist_two_zone_weekday_end: dc.twoZone?.weekday?.end ?? 22,
    dist_two_zone_weekend_start: dc.twoZone?.weekend?.start ?? 6,
    dist_two_zone_weekend_end: dc.twoZone?.weekend?.end ?? 22,
    dist_peak1_start: dc.threeZone?.peak1?.start ?? 7,
    dist_peak1_end: dc.threeZone?.peak1?.end ?? 13,
    dist_peak2_start: dc.threeZone?.peak2?.start ?? 16,
    dist_peak2_end: dc.threeZone?.peak2?.end ?? 21,
    dist_weekend_off_peak: dc.threeZone?.weekendOffPeak !== false,
    distribution_valley: settings?.distributionValley ?? 13.5,
    dist_valley_start: dc.fourZone?.valley?.start ?? 1,
    dist_valley_end: dc.fourZone?.valley?.end ?? 5,
  };
  // For four_zone, use fourZone peak boundaries instead of threeZone
  if (type === 'four_zone') {
    payload.dist_peak1_start = dc.fourZone?.peak1?.start ?? 7;
    payload.dist_peak1_end = dc.fourZone?.peak1?.end ?? 13;
    payload.dist_peak2_start = dc.fourZone?.peak2?.start ?? 16;
    payload.dist_peak2_end = dc.fourZone?.peak2?.end ?? 21;
  }
  return payload;
}

/**
 * Get hourly distribution rate based on OSD distribution time windows.
 * Uses distributionConfig (separate from energy tariffConfig).
 * Returns PLN/kWh (distribution zone rate / 1000).
 */
function getHourlyDistributionRate(h, month, dayOfMonth, isWeekend, params) {
  const settings = systemSettings || {};
  const dc = settings.distributionConfig;
  const distPeak = (params?.distribution_peak || 200);
  const distDay = (params?.distribution_day || 200);
  const distNight = (params?.distribution_night || 200);
  const distValley = (params?.distribution_valley || distNight);

  if (!dc) return distNight / 1000; // fallback flat

  const type = dc.type || 'flat';

  if (type === 'flat') {
    return distNight / 1000; // all zones same for flat
  } else if (type === 'two_zone') {
    const dayStart = isWeekend ? (dc.twoZone?.weekend?.start || 6) : (dc.twoZone?.weekday?.start || 6);
    const dayEnd = isWeekend ? (dc.twoZone?.weekend?.end || 22) : (dc.twoZone?.weekday?.end || 22);
    const isDayZone = h >= dayStart && h < dayEnd;
    return isDayZone ? distDay / 1000 : distNight / 1000;
  } else if (type === 'three_zone') {
    const weekendOffPeak = dc.threeZone?.weekendOffPeak !== false;
    if (isWeekend && weekendOffPeak) return distNight / 1000;
    const p1s = dc.threeZone?.peak1?.start || 7;
    const p1e = dc.threeZone?.peak1?.end || 13;
    const p2s = dc.threeZone?.peak2?.start || 16;
    const p2e = dc.threeZone?.peak2?.end || 21;
    const isPeak = (h >= p1s && h < p1e) || (h >= p2s && h < p2e);
    if (isPeak) return distPeak / 1000;
    const isNight = h < p1s || h >= p2e;
    if (isNight) return distNight / 1000;
    return distDay / 1000; // partial/day zone (between peaks)
  } else if (type === 'four_zone') {
    // Weekend = full valley (Strefa 4)
    if (isWeekend) return distValley / 1000;
    // Weekday: valley = deep night only (e.g. 1:00-4:59)
    const vStart = dc.fourZone?.valley?.start ?? 1;
    const vEnd = dc.fourZone?.valley?.end ?? 5;
    if (h >= vStart && h < vEnd) return distValley / 1000;
    // Peak zones (Strefa 1+2)
    const p1s = dc.fourZone?.peak1?.start || 7;
    const p1e = dc.fourZone?.peak1?.end || 13;
    const p2s = dc.fourZone?.peak2?.start || 16;
    const p2e = dc.fourZone?.peak2?.end || 21;
    if ((h >= p1s && h < p1e) || (h >= p2s && h < p2e)) return distPeak / 1000;
    // Remaining hours = Strefa 3 (13-16, 21-1, 5-7) — fall through
    return distDay / 1000;
  }
  return distNight / 1000;
}

function getDayOfYear(month, day) {
  const daysInMonth = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  let doy = day;
  for (let m = 0; m < month - 1; m++) doy += daysInMonth[m];
  return doy;
}

/**
 * Generate daily profiles using REAL data from API
 * If real data is not available, falls back to synthetic profiles
 *
 * @param {number|string} monthOrDayType - Month (1-12) or legacy dayType string
 * @param {number} day - Day of month (1-31)
 * @param {object} realDayData - Optional pre-fetched real day data
 * @returns {object} Day profile data with hourlyData and summary
 */
function generateTypicalDayProfiles(monthOrDayType = 6, day = 15, realDayData = null) {
  const variant = variants[currentVariant];
  if (!variant) return null;

  // Handle legacy dayType strings for backward compatibility
  let month = monthOrDayType;
  if (typeof monthOrDayType === 'string') {
    const legacyMap = { summer: 6, winter: 12, spring: 4 };
    month = legacyMap[monthOrDayType] || 6;
    day = 15;
  }

  // BESS parameters
  const bessEnergyKwh = bessSizingData?.energy_kwh || variant.bess_energy_kwh || 0;
  const bessPowerKw = bessSizingData?.power_kw || variant.bess_power_kw || 0;
  const hasBess = bessEnergyKwh > 0 && bessPowerKw > 0;

  // Get economic parameters
  const params = getEconomicParameters();
  // Legacy flat rate (kept for backward compat, real hourly rates used in loop below)
  const totalPricePerMwh = calculateTotalEnergyPrice(params); // PLN/MWh
  const energyPricePerKwh = totalPricePerMwh / 1000; // PLN/kWh — NOTE: overridden per-hour below

  // ============================================
  // USE REAL DATA IF AVAILABLE
  // ============================================
  let useRealData = false;
  let hourlyConsumptionKw = new Array(24).fill(0);
  let hourlyProductionKw = new Array(24).fill(0);

  if (realDayData && realDayData.length > 0) {
    useRealData = true;
    console.log(`📊 PULS DNIA: Using REAL consumption data for ${day}/${month} (${realDayData.length} points)`);

    // Fill consumption array with real data
    let hasRealProduction = false;
    for (const point of realDayData) {
      const h = point.hour;
      if (h >= 0 && h < 24) {
        hourlyConsumptionKw[h] = point.consumption || 0; // kW
        if (point.production > 0) {
          hourlyProductionKw[h] = point.production;
          hasRealProduction = true;
        }
      }
    }

    // DEBUG: Log filled arrays
    console.log('📊 PULS DNIA DEBUG - hourlyConsumptionKw after filling:');
    console.log('  - Non-zero values:', hourlyConsumptionKw.filter(v => v > 0).length);
    console.log('  - Max consumption:', Math.max(...hourlyConsumptionKw).toFixed(2), 'kW');
    console.log('  - Sum (daily total):', hourlyConsumptionKw.reduce((a,b) => a+b, 0).toFixed(2), 'kWh');
    console.log('  - First 6 hours:', hourlyConsumptionKw.slice(0, 6).map(v => v.toFixed(1)).join(', '));

    // If no real production data, generate synthetic production based on variant
    if (!hasRealProduction) {
      console.log(`📊 PULS DNIA: No real production data - generating synthetic PV profile for ${day}/${month}`);
      const annualProductionKwh = variant.production || 0;
      const solar = getSolarParametersForDay(month, day);
      const dailyProductionKwh = (annualProductionKwh / 365) * (1 + solar.productionFactor) / 1.5;

      // Generate PV bell curve
      const pvProfile = [];
      const sunriseHour = 12 - solar.dayLength / 2;
      const sunsetHour = 12 + solar.dayLength / 2;
      for (let h = 0; h < 24; h++) {
        if (h >= sunriseHour && h <= sunsetHour) {
          const sigma = solar.dayLength / 4;
          pvProfile.push(Math.exp(-Math.pow(h - 12, 2) / (2 * sigma * sigma)));
        } else {
          pvProfile.push(0);
        }
      }
      const pvSum = pvProfile.reduce((a, b) => a + b, 0) || 1;
      for (let h = 0; h < 24; h++) {
        hourlyProductionKw[h] = dailyProductionKwh * pvProfile[h] / pvSum;
      }
    }
  } else {
    // ============================================
    // FALLBACK: SYNTHETIC DATA
    // ============================================
    console.log(`📊 PULS DNIA: No real data for ${day}/${month}, using synthetic profile`);

    // Get annual values for synthetic calculation
    const annualProductionKwh = variant.production || 0;
    const annualConsumptionKwh = getAnnualConsumptionKwh();

    // Get solar parameters for selected day
    const solar = getSolarParametersForDay(month, day);

    // Calculate daily totals
    const dailyProductionKwh = (annualProductionKwh / 365) * (1 + solar.productionFactor) / 1.5;
    const dailyConsumptionKwh = (annualConsumptionKwh / 365) * solar.consumptionFactor;

    // PV production profile (bell curve centered at noon)
    const pvProfile = [];
    const sunriseHour = 12 - solar.dayLength / 2;
    const sunsetHour = 12 + solar.dayLength / 2;

    for (let h = 0; h < 24; h++) {
      if (h >= sunriseHour && h <= sunsetHour) {
        const midday = 12;
        const sigma = solar.dayLength / 4;
        const pvFactor = Math.exp(-Math.pow(h - midday, 2) / (2 * sigma * sigma));
        pvProfile.push(pvFactor);
      } else {
        pvProfile.push(0);
      }
    }
    const pvSum = pvProfile.reduce((a, b) => a + b, 0) || 1;
    const normalizedPv = pvProfile.map(v => v / pvSum);

    // Consumption profile (typical industrial/commercial)
    const consumptionProfile = [
      0.02, 0.02, 0.02, 0.02, 0.03, 0.04, // 0-5: Night
      0.05, 0.06, 0.07, 0.07, 0.07, 0.06, // 6-11: Morning
      0.05, 0.06, 0.07, 0.07, 0.07, 0.06, // 12-17: Afternoon
      0.05, 0.04, 0.04, 0.03, 0.02, 0.02  // 18-23: Evening
    ];
    const consSum = consumptionProfile.reduce((a, b) => a + b, 0);
    const normalizedCons = consumptionProfile.map(v => v / consSum);

    // Generate hourly values in kWh (for 1 hour, kWh = kW average)
    for (let h = 0; h < 24; h++) {
      hourlyProductionKw[h] = dailyProductionKwh * normalizedPv[h];
      hourlyConsumptionKw[h] = dailyConsumptionKwh * normalizedCons[h];
    }
  }

  // ============================================
  // GENERATE HOURLY DATA WITH ENERGY BALANCE
  // ============================================
  const hourlyData = [];
  let bessSOC = hasBess ? bessEnergyKwh * 0.2 : 0; // Start at 20% SOC
  const bessMinSOC = bessEnergyKwh * 0.1; // 10% minimum
  const bessMaxSOC = bessEnergyKwh * 0.9; // 90% maximum
  const bessEfficiency = 0.92;

  let totalSelfConsumed = 0;
  let totalGridImport = 0;
  let totalGridExport = 0;
  let totalSavings = 0;
  let totalCost = 0;
  let totalBessCharge = 0;
  let totalBessDischarge = 0;

  for (let h = 0; h < 24; h++) {
    // Use hourly arrays (from real or synthetic data)
    const production = hourlyProductionKw[h];  // kWh (for 1h interval)
    const consumption = hourlyConsumptionKw[h]; // kWh (for 1h interval)

    let selfConsumed = 0;
    let gridImport = 0;
    let gridExport = 0;
    let bessCharge = 0;
    let bessDischarge = 0;
    let newSOC = bessSOC;

    // Energy balance
    const netEnergy = production - consumption;

    if (netEnergy >= 0) {
      // Production >= Consumption: self-consume all consumption
      selfConsumed = consumption;
      const surplus = netEnergy;

      if (hasBess && surplus > 0) {
        // Try to charge battery with surplus
        const maxCharge = Math.min(surplus, bessPowerKw, (bessMaxSOC - bessSOC) / bessEfficiency);
        bessCharge = maxCharge;
        newSOC = bessSOC + bessCharge * bessEfficiency;
        gridExport = surplus - bessCharge;
      } else {
        gridExport = surplus;
      }
    } else {
      // Consumption > Production: need to import
      selfConsumed = production;
      let deficit = -netEnergy;

      if (hasBess && deficit > 0 && bessSOC > bessMinSOC) {
        // Try to discharge battery
        const maxDischarge = Math.min(deficit, bessPowerKw, (bessSOC - bessMinSOC));
        bessDischarge = maxDischarge * bessEfficiency;
        newSOC = bessSOC - maxDischarge;
        deficit = deficit - bessDischarge;
      }

      gridImport = deficit;
    }

    bessSOC = newSOC;

    // Cost/savings calculation with real ToU/RDN rates
    const isPeakHour = h >= 7 && h < 21;
    const isWeekend = false; // Typical day = weekday
    const energiaRate = getHourlyEnergyRate(h, month, day, isWeekend); // PLN/kWh (energia czynna)

    // Fixed fees per kWh (zonal distribution + quality + OZE + cogeneration + excise)
    const distRatePerKwh = getHourlyDistributionRate(h, month, day, isWeekend, params);
    const fixedFeesPerKwh = distRatePerKwh + ((params.quality_fee || 0) +
                             (params.oze_fee || 0) + (params.cogeneration_fee || 0) +
                             (params.excise_tax || 0)) / 1000; // PLN/MWh -> PLN/kWh

    // Capacity fee only during selected hours (7-22 weekdays)
    const capacityFeePerKwh = isPeakHour ? ((params.capacity_fee || 0) / 1000) : 0;

    // Total hourly rate = energia czynna + opłaty stałe + opłata mocowa
    const hourlyRate = energiaRate + fixedFeesPerKwh + capacityFeePerKwh;

    const hourlySavings = selfConsumed * hourlyRate + (bessDischarge * hourlyRate);
    const hourlyCost = gridImport * hourlyRate;

    hourlyData.push({
      hour: h,
      production: production,
      consumption: consumption,
      selfConsumed: selfConsumed,
      gridImport: gridImport,
      gridExport: gridExport,
      bessCharge: bessCharge,
      bessDischarge: bessDischarge,
      bessSOC: bessSOC,
      bessSOCPercent: hasBess ? (bessSOC / bessEnergyKwh) * 100 : 0,
      savings: hourlySavings,
      cost: hourlyCost,
      isPeakHour: isPeakHour,
      energyRate: energiaRate * 1000, // PLN/MWh for display
      totalRate: hourlyRate * 1000,    // PLN/MWh for display
    });

    totalSelfConsumed += selfConsumed;
    totalGridImport += gridImport;
    totalGridExport += gridExport;
    totalSavings += hourlySavings;
    totalCost += hourlyCost;
    totalBessCharge += bessCharge;
    totalBessDischarge += bessDischarge;
  }

  // Calculate daily totals from hourly arrays
  const dailyProductionTotal = hourlyProductionKw.reduce((a, b) => a + b, 0);
  const dailyConsumptionTotal = hourlyConsumptionKw.reduce((a, b) => a + b, 0);

  // Get solar parameters for metadata (even when using real data)
  const solar = getSolarParametersForDay(month, day);

  // Determine data source type for UI display
  let dataSourceType = 'synthetic'; // Default: all synthetic
  if (useRealData) {
    // Check if we have real production data (sum > 0 and came from API)
    const hasRealProd = hourlyProductionKw.some(v => v > 0) &&
                        realDayData?.some(p => p.production > 0);
    dataSourceType = hasRealProd ? 'real_full' : 'real_consumption';
  }

  return {
    month,
    day,
    dayOfYear: solar.dayOfYear,
    dayLength: solar.dayLength,
    useRealData, // Flag indicating if real consumption data was used
    dataSourceType, // 'real_full', 'real_consumption', or 'synthetic'
    hourlyData,
    summary: {
      dailyProduction: dailyProductionTotal,
      dailyConsumption: dailyConsumptionTotal,
      dailySelfConsumed: totalSelfConsumed,
      dailyGridImport: totalGridImport,
      dailyGridExport: totalGridExport,
      dailySavings: totalSavings,
      dailyCost: totalCost,
      dailyBessCharge: totalBessCharge,
      dailyBessDischarge: totalBessDischarge,
      hasBess,
      bessEnergyKwh,
      bessPowerKw
    }
  };
}

/**
 * Generate PULS DNIA - Premium Canvas Visualization
 * Dark theme with smooth curves like the reference image
 * Now fetches REAL data from API for accurate daily profiles!
 */
async function generatePulsDniaChart() {
  console.log('📈 ============================================');
  console.log('📈 generatePulsDniaChart() STARTED');
  console.log('📈 ============================================');

  const variant = variants[currentVariant];
  const noDataEl = document.getElementById('pulsDniaNoData');
  const contentEl = document.getElementById('pulsDniaContent');

  if (!variant || !contentEl) {
    console.log('📈 PULS DNIA - No variant, showing placeholder');
    if (noDataEl) noDataEl.style.display = 'flex';
    if (contentEl) contentEl.style.display = 'none';
    return;
  }

  // Get selected month and day from calendar
  const monthSelect = document.getElementById('pulsDniaMonth');
  const daySelect = document.getElementById('pulsDniaDay');

  // Initialize day selector if empty
  if (daySelect && daySelect.options.length === 0) {
    updatePulsDniaCalendar();
    return; // Will be called again after calendar is populated
  }

  const month = monthSelect ? parseInt(monthSelect.value) : 6;
  const day = daySelect ? parseInt(daySelect.value) || 15 : 15;

  console.log(`📈 PULS DNIA - Generating for ${day}/${month}`);

  // ============================================
  // FETCH REAL DATA FROM API
  // ============================================
  let realDayData = null;
  try {
    const apiData = await fetchRealHourlyData();
    if (apiData) {
      realDayData = getRealDayData(month, day, apiData.consumption, apiData.production);
    }
  } catch (err) {
    console.warn('📈 Could not fetch real data:', err.message);
  }

  // Generate data for selected date (using real data if available)
  const dayData = generateTypicalDayProfiles(month, day, realDayData);
  if (!dayData) {
    console.log('📈 PULS DNIA - No data generated');
    if (noDataEl) noDataEl.style.display = 'flex';
    if (contentEl) contentEl.style.display = 'none';
    return;
  }

  console.log(`📈 PULS DNIA - Data: prod=${dayData.summary.dailyProduction.toFixed(0)}kWh, cons=${dayData.summary.dailyConsumption.toFixed(0)}kWh`);

  // Show canvas
  if (noDataEl) noDataEl.style.display = 'none';
  contentEl.style.display = 'block';

  const canvas = document.getElementById('pulsDniaCanvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  // Clear canvas before redrawing
  ctx.setTransform(1, 0, 0, 1, 0, 0); // Reset transform
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Set canvas size - fits on one screen
  const containerWidth = canvas.parentElement.offsetWidth || 900;
  const hasBess = dayData.summary.hasBess;
  // Fixed height for one-screen view (reduced by ~12%)
  const canvasHeight = hasBess ? 750 : 570;

  canvas.width = containerWidth * dpr;
  canvas.height = canvasHeight * dpr;
  canvas.style.width = containerWidth + 'px';
  canvas.style.height = canvasHeight + 'px';
  ctx.scale(dpr, dpr);

  const W = containerWidth;
  const H = canvasHeight;

  // Colors
  const colors = {
    bg1: '#0a1628',
    bg2: '#1a2744',
    text: '#ffffff',
    textMuted: '#8899aa',
    yellow: '#ffc107',
    yellowGlow: 'rgba(255, 193, 7, 0.3)',
    green: '#4caf50',
    greenGlow: 'rgba(76, 175, 80, 0.2)',
    red: '#ef5350',
    redGlow: 'rgba(239, 83, 80, 0.5)',
    blue: '#42a5f5',
    orange: '#ff9800',
    purple: '#ab47bc',
    gridLine: 'rgba(255,255,255,0.1)',
    accent: '#4a9eff'
  };

  // Background gradient
  const bgGrad = ctx.createLinearGradient(0, 0, 0, H);
  bgGrad.addColorStop(0, colors.bg1);
  bgGrad.addColorStop(1, colors.bg2);
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // Layout - generous space for panels
  const margin = { top: 85, right: 70, bottom: 100, left: 75 };
  const chartW = W - margin.left - margin.right;
  const panelGap = 25;
  const numPanels = hasBess ? 4 : 3;
  const panelH = (H - margin.top - margin.bottom - (numPanels - 1) * panelGap) / numPanels;

  // Data
  const hourlyData = dayData.hourlyData;

  // Better max calculations with minimum values to avoid flat charts
  const maxProd = Math.max(10, Math.max(...hourlyData.map(d => Math.max(d.production || 0, d.consumption || 0)))) * 1.2;
  const maxGrid = Math.max(5, Math.max(...hourlyData.map(d => Math.max(d.gridImport || 0, d.gridExport || 0)))) * 1.2;
  const maxBessCharge = Math.max(5, Math.max(...hourlyData.map(d => Math.max(d.bessCharge || 0, d.bessDischarge || 0)))) * 1.2;
  const maxCost = Math.max(0.5, Math.max(...hourlyData.map(d => Math.max(d.cost || 0, d.savings || 0)))) * 1.2;

  // Helper: x position for hour
  const xForHour = (h) => margin.left + (h / 23) * chartW;
  const barW = Math.max(12, Math.min(25, chartW / 26)); // Better bar width

  // Helper: Draw smooth curve
  function drawSmoothCurve(points, color, lineWidth = 2) {
    if (points.length < 2) return;
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);

    for (let i = 1; i < points.length - 1; i++) {
      const xc = (points[i].x + points[i + 1].x) / 2;
      const yc = (points[i].y + points[i + 1].y) / 2;
      ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
    }
    ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);

    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
  }

  // Helper: Draw filled area under curve
  function drawFilledCurve(points, baseY, gradientColors) {
    if (points.length < 2) return;
    ctx.beginPath();
    ctx.moveTo(points[0].x, baseY);
    ctx.lineTo(points[0].x, points[0].y);

    for (let i = 1; i < points.length - 1; i++) {
      const xc = (points[i].x + points[i + 1].x) / 2;
      const yc = (points[i].y + points[i + 1].y) / 2;
      ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
    }
    ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
    ctx.lineTo(points[points.length - 1].x, baseY);
    ctx.closePath();

    const minY = Math.min(...points.map(p => p.y));
    const grad = ctx.createLinearGradient(0, minY, 0, baseY);
    grad.addColorStop(0, gradientColors[0]);
    grad.addColorStop(1, gradientColors[1]);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Helper: Draw Y axis labels for a panel
  function drawYAxis(panelTop, panelBottom, maxVal, unit, steps = 4) {
    ctx.fillStyle = colors.textMuted;
    ctx.font = '10px Arial';
    ctx.textAlign = 'right';

    for (let i = 0; i <= steps; i++) {
      const val = (maxVal * i / steps);
      const y = panelBottom - (i / steps) * (panelBottom - panelTop - 25);
      const label = val >= 100 ? val.toFixed(0) : val.toFixed(1);
      ctx.fillText(`${label}${unit}`, margin.left - 8, y + 3);

      // Grid line
      if (i > 0 && i < steps) {
        ctx.strokeStyle = colors.gridLine;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(margin.left, y);
        ctx.lineTo(W - margin.right, y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
  }

  // === TITLE ===
  ctx.fillStyle = colors.text;
  ctx.font = 'bold 24px Arial';
  ctx.textAlign = 'center';
  ctx.fillText('PULS DNIA', W / 2, 38);

  // Data source indicator - show what type of data is being used
  ctx.font = '11px Arial';
  const sourceType = dayData.dataSourceType || 'synthetic';
  if (sourceType === 'real_full') {
    ctx.fillStyle = '#4ade80'; // Green for fully real data
    ctx.fillText('📊 DANE RZECZYWISTE (Zużycie + Produkcja)', W / 2, 54);
  } else if (sourceType === 'real_consumption') {
    ctx.fillStyle = '#60a5fa'; // Blue for real consumption + synthetic production
    ctx.fillText('📊 ZUŻYCIE RZECZYWISTE | ☀️ PRODUKCJA MODELOWANA', W / 2, 54);
  } else {
    ctx.fillStyle = '#fbbf24'; // Yellow/orange for synthetic
    ctx.fillText('⚠️ PROFIL SYNTETYCZNY (brak danych)', W / 2, 54);
  }

  // Decorative lines
  ctx.strokeStyle = colors.accent;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(W/2 - 140, 62);
  ctx.lineTo(W/2 - 70, 62);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(W/2 + 70, 62);
  ctx.lineTo(W/2 + 140, 62);
  ctx.stroke();

  // === TIME AXIS (top) ===
  ctx.fillStyle = colors.textMuted;
  ctx.font = '10px Arial';
  ctx.textAlign = 'center';
  // Fewer time labels to avoid overlap (every 6 hours)
  for (let h = 0; h <= 24; h += 6) {
    const x = h === 24 ? xForHour(23) + 10 : xForHour(h);
    ctx.fillText(h === 24 ? '24h' : `${h}:00`, x, margin.top - 8);
  }

  // Time axis line
  ctx.strokeStyle = colors.gridLine;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(margin.left, margin.top - 2);
  ctx.lineTo(W - margin.right, margin.top - 2);
  ctx.stroke();

  // ============ PANEL 1: PV Production vs Consumption ============
  let panelY = margin.top;
  const chartAreaH = panelH - 35; // Usable chart height per panel

  // Panel background (subtle)
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(margin.left, panelY, chartW, panelH);

  // Panel label
  ctx.fillStyle = colors.yellow;
  ctx.font = 'bold 13px Arial';
  ctx.textAlign = 'left';
  ctx.fillText('▶ PRODUKCJA PV', margin.left + 5, panelY + 20);
  ctx.fillStyle = colors.green;
  ctx.fillText('    / ZAPOTRZEBOWANIE', margin.left + 120, panelY + 20);

  // Y axis
  const panel1BaseY = panelY + panelH - 12;
  drawYAxis(panelY + 25, panel1BaseY, maxProd, ' kWh');

  // Build curve points with better scaling
  const prodPoints = hourlyData.map((d, i) => ({
    x: xForHour(i),
    y: panel1BaseY - ((d.production || 0) / maxProd) * chartAreaH
  }));
  const consPoints = hourlyData.map((d, i) => ({
    x: xForHour(i),
    y: panel1BaseY - ((d.consumption || 0) / maxProd) * chartAreaH
  }));

  // Fill under consumption curve first (so production overlays it)
  drawFilledCurve(consPoints, panel1BaseY, ['rgba(76, 175, 80, 0.5)', 'rgba(76, 175, 80, 0.05)']);

  // Fill under production curve (yellow glow)
  drawFilledCurve(prodPoints, panel1BaseY, ['rgba(255, 193, 7, 0.6)', 'rgba(255, 193, 7, 0.05)']);

  // Consumption curve (green solid, thicker) - drawn first so production is on top
  drawSmoothCurve(consPoints, colors.green, 3);

  // Production curve (yellow)
  drawSmoothCurve(prodPoints, colors.yellow, 3);

  // Legend for panel 1 - positioned inside right margin with proper spacing
  const legendX = W - margin.right + 5;
  ctx.fillStyle = colors.yellow;
  ctx.fillRect(legendX, panelY + 8, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.font = '9px Arial';
  ctx.textAlign = 'left';
  ctx.fillText('PV', legendX + 12, panelY + 16);
  ctx.fillStyle = colors.green;
  ctx.fillRect(legendX, panelY + 24, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.fillText('Zużycie', legendX + 12, panelY + 32);

  // ============ PANEL 2: Grid Import ============
  panelY += panelH + panelGap;
  const panel2BaseY = panelY + panelH - 12;

  // Panel background
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(margin.left, panelY, chartW, panelH);

  ctx.fillStyle = colors.blue;
  ctx.font = 'bold 13px Arial';
  ctx.textAlign = 'left';
  ctx.fillText('▶ IMPORT Z SIECI / EKSPORT DO SIECI', margin.left + 5, panelY + 20);

  // Y axis
  drawYAxis(panelY + 25, panel2BaseY, maxGrid, ' kWh');

  // Legend - positioned inside right margin with proper spacing
  const legend2X = W - margin.right + 5;
  ctx.fillStyle = '#6a9aca';
  ctx.fillRect(legend2X, panelY + 8, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.font = '9px Arial';
  ctx.fillText('Import', legend2X + 12, panelY + 16);
  ctx.fillStyle = '#90caf9';
  ctx.fillRect(legend2X, panelY + 24, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.fillText('Eksport', legend2X + 12, panelY + 32);

  // Grid import/export bars
  hourlyData.forEach((d, i) => {
    const x = xForHour(i);
    const importVal = d.gridImport || 0;
    const exportVal = d.gridExport || 0;
    const importH = (importVal / maxGrid) * chartAreaH;
    const exportH = (exportVal / maxGrid) * chartAreaH;

    if (importVal > 0) {
      const barGrad = ctx.createLinearGradient(x, panel2BaseY, x, panel2BaseY - importH);
      barGrad.addColorStop(0, '#3a5a8a');
      barGrad.addColorStop(1, '#6a9aca');
      ctx.fillStyle = barGrad;
      ctx.fillRect(x - barW/2, panel2BaseY - importH, barW, importH);
    }

    if (exportVal > 0) {
      const barGrad = ctx.createLinearGradient(x, panel2BaseY, x, panel2BaseY - exportH);
      barGrad.addColorStop(0, '#5080b0');
      barGrad.addColorStop(1, '#90caf9');
      ctx.fillStyle = barGrad;
      ctx.fillRect(x - barW/2, panel2BaseY - exportH, barW, exportH);
    }
  });

  // ============ PANEL 3: BESS (if available) ============
  if (hasBess) {
    panelY += panelH + panelGap;
    const panel3BaseY = panelY + panelH - 12;

    // Panel background
    ctx.fillStyle = 'rgba(255,255,255,0.02)';
    ctx.fillRect(margin.left, panelY, chartW, panelH);

    ctx.fillStyle = colors.purple;
    ctx.font = 'bold 13px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('▶ MAGAZYN ENERGII (BESS)', margin.left + 5, panelY + 20);

    // Y axis for BESS charge/discharge
    drawYAxis(panelY + 25, panel3BaseY, maxBessCharge, ' kWh');

    // Legend - positioned inside right margin with proper spacing
    const legend3X = W - margin.right + 5;
    ctx.fillStyle = colors.green;
    ctx.fillRect(legend3X, panelY + 8, 8, 8);
    ctx.fillStyle = colors.textMuted;
    ctx.font = '9px Arial';
    ctx.fillText('Ładow.', legend3X + 12, panelY + 16);
    ctx.fillStyle = colors.orange;
    ctx.fillRect(legend3X, panelY + 24, 8, 8);
    ctx.fillStyle = colors.textMuted;
    ctx.fillText('Rozład.', legend3X + 12, panelY + 32);

    // BESS bars
    hourlyData.forEach((d, i) => {
      const x = xForHour(i);
      const chargeVal = d.bessCharge || 0;
      const dischargeVal = d.bessDischarge || 0;
      const chargeH = (chargeVal / maxBessCharge) * chartAreaH;
      const dischargeH = (dischargeVal / maxBessCharge) * chartAreaH;

      if (chargeVal > 0) {
        const grad = ctx.createLinearGradient(x, panel3BaseY, x, panel3BaseY - chargeH);
        grad.addColorStop(0, '#1b5e20');
        grad.addColorStop(1, '#66bb6a');
        ctx.fillStyle = grad;
        ctx.fillRect(x - barW/2 - 3, panel3BaseY - chargeH, barW, chargeH);
      }

      if (dischargeVal > 0) {
        const grad = ctx.createLinearGradient(x, panel3BaseY, x, panel3BaseY - dischargeH);
        grad.addColorStop(0, '#e65100');
        grad.addColorStop(1, '#ffb74d');
        ctx.fillStyle = grad;
        ctx.fillRect(x - barW/2 + 3, panel3BaseY - dischargeH, barW, dischargeH);
      }
    });

    // SOC line overlay
    const socAreaTop = panelY + 30;
    const socAreaBottom = panel3BaseY;
    const socPoints = hourlyData.map((d, i) => ({
      x: xForHour(i),
      y: socAreaBottom - ((d.bessSOCPercent || 0) / 100) * (socAreaBottom - socAreaTop)
    }));

    // SOC filled area
    ctx.beginPath();
    ctx.moveTo(socPoints[0].x, socAreaBottom);
    socPoints.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(socPoints[socPoints.length - 1].x, socAreaBottom);
    ctx.closePath();
    ctx.fillStyle = 'rgba(156, 39, 176, 0.15)';
    ctx.fill();

    // SOC line
    ctx.setLineDash([5, 3]);
    drawSmoothCurve(socPoints, 'rgba(206, 147, 216, 0.8)', 2);
    ctx.setLineDash([]);

    // SOC % labels on right
    ctx.fillStyle = colors.textMuted;
    ctx.font = '9px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('100%', W - margin.right + 5, socAreaTop + 3);
    ctx.fillText('0%', W - margin.right + 5, socAreaBottom + 3);
  }

  // ============ PANEL 4: Costs / Savings ============
  panelY += panelH + panelGap;
  const panel4BaseY = panelY + panelH - 12;

  // Panel background
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(margin.left, panelY, chartW, panelH);

  // Title
  ctx.fillStyle = colors.yellow;
  ctx.font = 'bold 13px Arial';
  ctx.textAlign = 'left';
  ctx.fillText('▶ KOSZTY / OSZCZĘDNOŚCI', margin.left + 5, panelY + 20);

  // Y axis
  drawYAxis(panelY + 25, panel4BaseY, maxCost, ' PLN');

  // Legend - positioned inside right margin with proper spacing
  const legend4X = W - margin.right + 5;
  ctx.fillStyle = colors.green;
  ctx.fillRect(legend4X, panelY + 8, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.font = '9px Arial';
  ctx.fillText('Oszczędn.', legend4X + 12, panelY + 16);
  ctx.fillStyle = colors.red;
  ctx.fillRect(legend4X, panelY + 24, 8, 8);
  ctx.fillStyle = colors.textMuted;
  ctx.fillText('Koszty', legend4X + 12, panelY + 32);

  // Cost/savings bars - draw taller bar first (behind), then shorter bar (front) with transparency
  hourlyData.forEach((d, i) => {
    const x = xForHour(i);
    const costVal = d.cost || 0;
    const savVal = d.savings || 0;
    const costH = (costVal / maxCost) * chartAreaH;
    const savH = (savVal / maxCost) * chartAreaH;

    // Determine which bar is taller (draw it first, behind)
    const savTaller = savH >= costH;

    // First pass: draw the TALLER bar (background)
    if (savTaller && savVal > 0) {
      // Savings is taller - draw it first (solid)
      const grad = ctx.createLinearGradient(x, panel4BaseY, x, panel4BaseY - savH);
      grad.addColorStop(0, '#1b5e20');
      grad.addColorStop(1, '#4caf50');
      ctx.fillStyle = grad;
      ctx.fillRect(x - barW/2, panel4BaseY - savH, barW, savH);
    } else if (!savTaller && costVal > 0) {
      // Cost is taller - draw it first (solid)
      const grad = ctx.createLinearGradient(x, panel4BaseY, x, panel4BaseY - costH);
      grad.addColorStop(0, '#b71c1c');
      grad.addColorStop(1, '#ef5350');
      ctx.fillStyle = grad;
      ctx.fillRect(x - barW/2, panel4BaseY - costH, barW, costH);
    }

    // Second pass: draw the SHORTER bar (foreground with semi-transparency)
    ctx.globalAlpha = 0.85;
    if (!savTaller && savVal > 0) {
      // Savings is shorter - draw in front
      const grad = ctx.createLinearGradient(x, panel4BaseY, x, panel4BaseY - savH);
      grad.addColorStop(0, '#2e7d32');
      grad.addColorStop(1, '#81c784');
      ctx.fillStyle = grad;
      ctx.fillRect(x - barW/2, panel4BaseY - savH, barW, savH);
    } else if (savTaller && costVal > 0) {
      // Cost is shorter - draw in front
      const grad = ctx.createLinearGradient(x, panel4BaseY, x, panel4BaseY - costH);
      grad.addColorStop(0, '#c62828');
      grad.addColorStop(1, '#ff8a80');
      ctx.fillStyle = grad;
      ctx.fillRect(x - barW/2, panel4BaseY - costH, barW, costH);
    }
    ctx.globalAlpha = 1.0;
  });

  // ============ SUMMARY STATS (bottom) ============
  const statsY = H - 35;
  const monthNames = ['', 'STY', 'LUT', 'MAR', 'KWI', 'MAJ', 'CZE', 'LIP', 'SIE', 'WRZ', 'PAŹ', 'LIS', 'GRU'];
  const dateLabel = `${dayData.day} ${monthNames[dayData.month]}`;

  // Safe number formatting helper
  const safeNum = (val) => (val && !isNaN(val)) ? val.toFixed(0) : '0';
  const safeNum1 = (val) => (val && !isNaN(val)) ? val.toFixed(1) : '0.0';

  // Calculate daily savings properly (avoid NaN)
  const dailySavings = dayData.summary.dailySavings || 0;
  const dailyCost = dayData.summary.dailyCost || 0;
  const netSavings = dailySavings - dailyCost;

  // Stats background
  ctx.fillStyle = 'rgba(0,0,0,0.3)';
  ctx.fillRect(20, statsY - 30, W - 40, 55);

  const stats = [
    { label: 'DZIEŃ', value: dateLabel, unit: '', color: colors.accent },
    { label: 'PRODUKCJA', value: safeNum(dayData.summary.dailyProduction), unit: 'kWh', color: colors.yellow },
    { label: 'KONSUMPCJA', value: safeNum(dayData.summary.dailyConsumption), unit: 'kWh', color: colors.text },
    { label: 'AUTOKONS.', value: safeNum(dayData.summary.dailySelfConsumed), unit: 'kWh', color: colors.green },
    { label: 'Z SIECI', value: safeNum1(dayData.summary.dailyGridImport), unit: 'kWh', color: colors.blue },
    { label: 'BILANS', value: (netSavings >= 0 ? '+' : '') + safeNum1(netSavings), unit: 'PLN', color: netSavings >= 0 ? colors.green : colors.red }
  ];

  const statWidth = (W - 60) / stats.length;
  stats.forEach((s, i) => {
    const x = 30 + i * statWidth + statWidth / 2;
    ctx.fillStyle = colors.textMuted;
    ctx.font = '10px Arial';
    ctx.textAlign = 'center';
    ctx.fillText(s.label, x, statsY - 12);
    ctx.fillStyle = s.color;
    ctx.font = 'bold 16px Arial';
    ctx.fillText(`${s.value} ${s.unit}`, x, statsY + 10);
  });

  console.log('📈 PULS DNIA premium chart rendered:', `${day}/${month}`, dayData.summary);
}

/**
 * Export PULS DNIA data to Excel
 */
function exportPulsDniaToExcel() {
  const monthSelect = document.getElementById('pulsDniaMonth');
  const daySelect = document.getElementById('pulsDniaDay');
  const month = monthSelect ? parseInt(monthSelect.value) : 6;
  const day = daySelect ? parseInt(daySelect.value) : 15;
  const dayData = generateTypicalDayProfiles(month, day);

  if (!dayData) {
    alert('Brak danych do eksportu');
    return;
  }

  const monthNames = ['', 'Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec', 'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];
  const variant = variants[currentVariant];

  // Build CSV with Polish formatting
  const lines = [];
  lines.push('PULS DNIA - Profil Energetyczny 24h');
  lines.push(`Data: ${day} ${monthNames[month]}`);
  lines.push(`Wariant: ${currentVariant} - ${(variant?.capacity || 0).toFixed(0)} kWp`);
  lines.push(`Data eksportu: ${new Date().toLocaleDateString('pl-PL')}`);
  lines.push('');
  lines.push('PODSUMOWANIE DNIA');
  lines.push(`Produkcja PV [kWh];${dayData.summary.dailyProduction.toFixed(1).replace('.', ',')}`);
  lines.push(`Konsumpcja [kWh];${dayData.summary.dailyConsumption.toFixed(1).replace('.', ',')}`);
  lines.push(`Autokonsumpcja [kWh];${dayData.summary.dailySelfConsumed.toFixed(1).replace('.', ',')}`);
  lines.push(`Pobor z sieci [kWh];${dayData.summary.dailyGridImport.toFixed(1).replace('.', ',')}`);
  lines.push(`Nadwyzka do sieci [kWh];${dayData.summary.dailyGridExport.toFixed(1).replace('.', ',')}`);
  lines.push(`Oszczednosc [PLN];${dayData.summary.dailySavings.toFixed(2).replace('.', ',')}`);
  if (dayData.summary.hasBess) {
    lines.push(`BESS Ladowanie [kWh];${dayData.summary.dailyBessCharge.toFixed(1).replace('.', ',')}`);
    lines.push(`BESS Rozladowanie [kWh];${dayData.summary.dailyBessDischarge.toFixed(1).replace('.', ',')}`);
  }
  lines.push('');
  lines.push('DANE GODZINOWE');

  // Header
  let header = 'Godzina;Produkcja PV [kWh];Konsumpcja [kWh];Autokonsumpcja [kWh];Pobor z sieci [kWh];Nadwyzka [kWh];Cena energii [PLN/MWh];Cena calkowita [PLN/MWh];Oszczednosc [PLN];Koszt [PLN]';
  if (dayData.summary.hasBess) {
    header += ';BESS Ladowanie [kWh];BESS Rozladowanie [kWh];BESS SOC [%]';
  }
  lines.push(header);

  // Data rows
  for (const h of dayData.hourlyData) {
    let row = [
      `${h.hour}:00`,
      h.production.toFixed(2).replace('.', ','),
      h.consumption.toFixed(2).replace('.', ','),
      h.selfConsumed.toFixed(2).replace('.', ','),
      h.gridImport.toFixed(2).replace('.', ','),
      h.gridExport.toFixed(2).replace('.', ','),
      (h.energyRate || 0).toFixed(1).replace('.', ','),
      (h.totalRate || 0).toFixed(1).replace('.', ','),
      h.savings.toFixed(2).replace('.', ','),
      h.cost.toFixed(2).replace('.', ',')
    ];
    if (dayData.summary.hasBess) {
      row.push(
        h.bessCharge.toFixed(2).replace('.', ','),
        h.bessDischarge.toFixed(2).replace('.', ','),
        h.bessSOCPercent.toFixed(1).replace('.', ',')
      );
    }
    lines.push(row.join(';'));
  }

  // Download
  const csv = lines.join('\n');
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `PULS_DNIA_${month}-${day}_${currentVariant}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);

  console.log('📥 PULS DNIA exported to CSV');
}

/**
 * Export full-year (8760h) PV economics to Excel via bess-dispatch /pv-export-excel endpoint.
 * Uses real ToU/RDN hourly pricing based on current pricing mode settings.
 */
async function exportPvYearlyExcel() {
  const variant = variants[currentVariant];
  if (!variant) {
    alert('Brak wybranego wariantu PV. Najpierw wybierz wariant.');
    return;
  }

  const settings = systemSettings || {};
  const tariffConfig = settings.tariffConfig || {};

  // Ensure hourly data is loaded (same cache as PULS DNIA uses)
  if (!cachedHourlyConsumption || !cachedHourlyProduction) {
    try {
      await fetchRealHourlyData();
    } catch (e) {
      console.warn('⚠️ fetchRealHourlyData failed:', e);
    }
  }

  // Get full-year profiles via shared resolvePvProfile() — SSoT for PV profile resolution
  const variantKey = currentVariant || 'B';
  const { pvProfile: resolvedPv, pvProfileSource } = resolvePvProfile(variant, variantKey);
  let pvProfile = resolvedPv || [];
  console.log(`📊 PV Export: pvSource=${pvProfileSource}, pvSum=${pvProfile.length > 0 ? (pvProfile.reduce((a,b)=>a+b,0)/1000).toFixed(1) : 0} MWh`);

  const sd = window.sharedData || window.parent?.sharedData || {};
  let loadProfile = cachedHourlyConsumption?.values ||
                      sd.loadData ||
                      sd.consumptionData?.values || [];

  // Safety: if loadProfile is still 15-min data (>10000 points), convert to hourly
  // (cachedHourlyConsumption should already be converted in fetchRealHourlyData,
  //  but sd.consumptionData might still be raw 15-min)
  if (loadProfile.length > 10000) {
    console.log(`📊 PV Export: Converting ${loadProfile.length} 15-min load points to hourly`);
    const hourlyLoad = [];
    for (let h = 0; h < Math.floor(loadProfile.length / 4); h++) {
      const s = h * 4;
      const avg = ((loadProfile[s] || 0) + (loadProfile[s+1] || 0) + (loadProfile[s+2] || 0) + (loadProfile[s+3] || 0)) / 4;
      hourlyLoad.push(avg);
    }
    loadProfile = hourlyLoad;
  }

  if (pvProfile.length < 720 || loadProfile.length < 720) {
    alert('Brak danych profili godzinowych (PV i/lub konsumpcja). Upewnij się, że dane zostały załadowane i wyświetlono PULS DNIA.');
    return;
  }

  const n = Math.min(pvProfile.length, loadProfile.length);

  // Build payload matching PvExcelExportRequest schema
  const payload = {
    load_kw: loadProfile.slice(0, n),
    pv_kw: pvProfile.slice(0, n),
    start_date: cachedHourlyConsumption?.timestamps?.[0]?.slice(0, 10) ||
                window.sharedData?.analyticalPeriod?.start_datetime?.slice(0, 10) || '2025-01-01',
    interval_minutes: 60,
    tariff_type: tariffConfig.type || 'two_zone',
    flat_rate: tariffConfig.flatRate || 750,
    day_rate: tariffConfig.twoZone?.dayRate || 850,
    night_rate: tariffConfig.twoZone?.nightRate || 450,
    peak_rate: tariffConfig.threeZone?.peakRate || 950,
    partial_rate: tariffConfig.threeZone?.partialRate || 700,
    off_peak_rate: tariffConfig.threeZone?.offPeakRate || 400,
    weekday_day_start: tariffConfig.twoZone?.weekday?.start || 6,
    weekday_day_end: tariffConfig.twoZone?.weekday?.end || 22,
    weekend_day_start: tariffConfig.twoZone?.weekend?.start || 6,
    weekend_day_end: tariffConfig.twoZone?.weekend?.end || 13,
    peak1_start: tariffConfig.threeZone?.peak1?.start || 7,
    peak1_end: tariffConfig.threeZone?.peak1?.end || 13,
    peak2_start: tariffConfig.threeZone?.peak2?.start || 17,
    peak2_end: tariffConfig.threeZone?.peak2?.end || 21,
    distribution: settings.distribution || 200,
    distribution_peak: settings.distributionPeak || settings.distribution || 200,
    distribution_day: settings.distributionDay || settings.distribution || 200,
    distribution_night: settings.distributionNight || settings.distribution || 200,
    distribution_valley: settings.distributionValley || settings.distributionNight || 13.5,
    quality_fee: settings.qualityFee || 10,
    oze_fee: settings.ozeFee || 7,
    cogeneration_fee: settings.cogenerationFee || 10,
    excise_tax: settings.exciseTax || 5,
    capacity_fee_som: settings.capacityFeeConfig?.somRate || 0.2194,
    is_osd_all_in: settings.isOsdAllIn || false,
    // Distribution time windows (OSD zones)
    ...getDistConfigPayload(settings),
    project_name: `PV ${variant.capacity} kWp - Analiza Roczna`,
    pv_capacity_kwp: variant.capacity || 0,
  };

  // Hybrid monthly pricing
  const pricingMode = settings.pricingMode || 'single';
  if (pricingMode === 'hybrid_monthly' && settings.monthlyPriceSources) {
    const sources = {};
    for (const [k, v] of Object.entries(settings.monthlyPriceSources)) {
      sources[parseInt(k)] = v;
    }
    payload.monthly_price_sources = sources;
  }

  // RDN hourly prices (from centralized PriceConfig)
  const rdnForExport = _getRdnHourlyPrices();
  if (rdnForExport && rdnForExport.length >= 720) {
    payload.hourly_prices_pln_mwh = rdnForExport;
  }

  console.log('📊 PV Yearly Excel export: sending request...', {
    pvPoints: pvProfile.length,
    loadPoints: loadProfile.length,
    pricingMode,
    capacity: variant.capacity,
  });

  try {
    const resp = await fetch('/api/bess-dispatch/pv-export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${errText}`);
    }

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const cd = resp.headers.get('Content-Disposition');
    const fnMatch = cd && cd.match(/filename="?([^"]+)"?/);
    a.download = fnMatch ? fnMatch[1] : `PV_Economics_${variant.capacity}kWp.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    console.log('📥 PV Yearly Excel downloaded successfully');
  } catch (err) {
    console.error('❌ PV Excel export error:', err);
    alert(`Błąd eksportu Excel: ${err.message}`);
  }
}

// Expose PULS DNIA functions globally
window.generatePulsDniaChart = generatePulsDniaChart;
window.exportPulsDniaToExcel = exportPulsDniaToExcel;
window.exportPvYearlyExcel = exportPvYearlyExcel;
window.updatePulsDniaCalendar = updatePulsDniaCalendar;

// Initialize PULS DNIA calendar and event listeners
let pulsDniaCalendarInitialized = false;

function initializePulsDniaCalendar() {
  if (pulsDniaCalendarInitialized) {
    console.log('📅 PULS DNIA calendar already initialized');
    return;
  }

  console.log('📅 Initializing PULS DNIA calendar...');

  const monthSelect = document.getElementById('pulsDniaMonth');
  const daySelect = document.getElementById('pulsDniaDay');

  if (!monthSelect || !daySelect) {
    console.log('📅 PULS DNIA calendar elements not found, retrying in 500ms...');
    setTimeout(initializePulsDniaCalendar, 500);
    return;
  }

  console.log('📅 PULS DNIA calendar elements found, attaching event listeners');

  // Mark as initialized to prevent duplicate event listeners
  pulsDniaCalendarInitialized = true;

  // Remove inline handlers and add proper event listeners
  monthSelect.removeAttribute('onchange');
  daySelect.removeAttribute('onchange');

  // Find export button
  const exportBtn = document.querySelector('#pulsDniaContent button');
  if (exportBtn) {
    exportBtn.removeAttribute('onclick');
    exportBtn.addEventListener('click', function() {
      console.log('📥 Export button clicked');
      exportPulsDniaToExcel();
    });
  }

  monthSelect.addEventListener('change', function() {
    console.log('📅 Month changed to:', this.value);
    updatePulsDniaCalendar();
  });

  daySelect.addEventListener('change', function() {
    console.log('📅 Day changed to:', this.value);
    generatePulsDniaChart().catch(err => console.warn('📈 Chart error:', err.message));
  });

  // Initialize day options if empty
  if (daySelect.options.length === 0) {
    console.log('📅 Populating day options...');
    updatePulsDniaCalendar();
  }

  console.log('📅 PULS DNIA calendar initialized successfully');
}

// Expose initialization function globally (after definition)
window.initializePulsDniaCalendar = initializePulsDniaCalendar;

// Call initialization when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializePulsDniaCalendar);
} else {
  // DOM already loaded, initialize after short delay to ensure elements exist
  setTimeout(initializePulsDniaCalendar, 100);
}

// ============================================
// INDEPENDENT PULS DNIA TRIGGER
// This ensures the chart renders even if performEconomicAnalysis has errors
// ============================================
(function initPulsDniaIndependent() {
  console.log('📈 PULS DNIA Independent Trigger: Setting up...');

  // Wait for DOM and data to be ready
  const checkAndRender = () => {
    const canvas = document.getElementById('pulsDniaCanvas');
    const monthSelect = document.getElementById('pulsDniaMonth');

    if (!canvas || !monthSelect) {
      console.log('📈 PULS DNIA: Elements not ready, retrying in 1s...');
      setTimeout(checkAndRender, 1000);
      return;
    }

    // Check if we have variant data
    if (!variants || Object.keys(variants).length === 0) {
      console.log('📈 PULS DNIA: No variants yet, retrying in 2s...');
      setTimeout(checkAndRender, 2000);
      return;
    }

    console.log('📈 PULS DNIA Independent Trigger: Rendering chart...');
    generatePulsDniaChart()
      .then(() => console.log('📈 PULS DNIA Independent: Chart rendered successfully'))
      .catch(err => console.error('📈 PULS DNIA Independent: Error:', err));
  };

  // Start checking after page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(checkAndRender, 2000));
  } else {
    setTimeout(checkAndRender, 2000);
  }
})();

// Generate sensitivity analysis chart - recalculates NPV properly for each scenario
function generateSensitivityChart() {
  const ctx = document.getElementById('sensitivityAnalysis')?.getContext('2d');
  if (!ctx) return;

  if (sensitivityChart) sensitivityChart.destroy();

  const variant = variants[currentVariant];
  if (!variant) return;

  const params = getEconomicParameters();
  const totalEnergyPrice = calculateTotalEnergyPrice(params);
  const capacity_kwp = variant.capacity;
  const self_consumed = variant.self_consumed;
  const capex_per_kwp = getCapexForCapacity(capacity_kwp);
  const base_discount_rate = window.economicsSettings?.discountRate;
  const inflation_rate = window.economicsSettings?.inflationRate;

  // Base NPV parameters for recalculation
  const baseParams = {
    capacity_kwp,
    self_consumed_annual_kwh: self_consumed,
    total_energy_price_per_kwh: totalEnergyPrice / 1000,
    capex_per_kwp,
    opex_per_kwp: params.opex_per_kwp,
    degradation_rate: params.degradation_rate,
    discount_rate: base_discount_rate,
    analysis_period: params.analysis_period,
    inflation_rate
  };

  const baseNPV = plnToMlnPln(calculateCapexNPV(baseParams));

  // Recalculate NPV for each variation of each parameter
  const variations = [-20, -10, 0, 10, 20];
  const paramDefs = [
    { label: 'Cena energii', color: '#27ae60', modify: (v) => ({...baseParams, total_energy_price_per_kwh: totalEnergyPrice / 1000 * (1 + v/100)}) },
    { label: 'CAPEX', color: '#3498db', modify: (v) => ({...baseParams, capex_per_kwp: capex_per_kwp * (1 + v/100)}) },
    { label: 'OPEX', color: '#e74c3c', modify: (v) => ({...baseParams, opex_per_kwp: params.opex_per_kwp * (1 + v/100)}) },
    { label: 'Produkcja', color: '#f39c12', modify: (v) => ({...baseParams, self_consumed_annual_kwh: self_consumed * (1 + v/100)}) },
    { label: 'Stopa dyskontowa', color: '#9b59b6', modify: (v) => ({...baseParams, discount_rate: Math.max(0.01, base_discount_rate + v/100 * base_discount_rate)}) }
  ];

  const datasets = paramDefs.map(paramDef => {
    const npvValues = variations.map(variation => {
      const modifiedParams = paramDef.modify(variation);
      return plnToMlnPln(calculateCapexNPV(modifiedParams)).toFixed(2);
    });

    return {
      label: paramDef.label,
      data: npvValues,
      borderColor: paramDef.color,
      backgroundColor: `${paramDef.color}33`,
      borderWidth: 2,
      fill: false,
      tension: 0.4
    };
  });

  sensitivityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: variations.map(v => `${v > 0 ? '+' : ''}${v}%`),
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          title: { display: true, text: 'NPV [mln PLN]' }
        },
        x: {
          title: { display: true, text: 'Zmiana parametru' }
        }
      }
    }
  });
}

// ============================================================
// SENSITIVITY ANALYSIS: CAPEX vs EaaS
// ============================================================

/**
 * Calculate NPV for CAPEX model with given parameters
 */
function calculateCapexNPV(params) {
  const {
    capacity_kwp,
    self_consumed_annual_kwh,
    total_energy_price_per_kwh,
    capex_per_kwp,
    opex_per_kwp,
    degradation_rate,
    discount_rate,
    analysis_period,
    inflation_rate = 0 // Default 0 if not provided
  } = params;

  const capex = capacity_kwp * capex_per_kwp;
  const base_opex_annual = capacity_kwp * opex_per_kwp;
  const self_consumed_annual_mwh = kwhToMwh(self_consumed_annual_kwh);

  let npv = -capex;
  for (let year = 1; year <= analysis_period; year++) {
    const degradation_factor = Math.pow(1 - degradation_rate, year - 1);
    // Apply inflation to energy price and O&M costs
    const inflation_factor = Math.pow(1 + inflation_rate, year - 1);
    const adjusted_energy_price = total_energy_price_per_kwh * inflation_factor;
    const adjusted_opex = base_opex_annual * inflation_factor;

    const savings = self_consumed_annual_mwh * degradation_factor * adjusted_energy_price * 1000;
    const cash_flow = savings - adjusted_opex;
    npv += cash_flow / Math.pow(1 + discount_rate, year);
  }

  return npv;
}

/**
 * Calculate NPV for EaaS model with given parameters
 */
function calculateEaaSNPV(params) {
  const {
    capacity_kwp,
    self_consumed_annual_kwh,
    total_energy_price_per_kwh,
    eaas_subscription,
    eaas_om_per_kwp,
    insurance_rate,
    capex_per_kwp,
    degradation_rate,
    discount_rate,
    eaas_duration,
    analysis_period,
    inflation_rate = 0, // Default 0 if not provided
    eaas_indexation = 'fixed' // 'fixed' or 'cpi'
  } = params;

  const capex = capacity_kwp * capex_per_kwp;
  // During contract: subscription INCLUDES O&M + insurance (no double-counting!)
  const base_subscription_cost = eaas_subscription;
  // Post-contract costs: O&M + insurance (client takes over installation)
  const base_om_cost = capacity_kwp * eaas_om_per_kwp;
  const base_insurance_cost = capex * insurance_rate;
  const self_consumed_annual_mwh = kwhToMwh(self_consumed_annual_kwh);

  let npv = 0;
  for (let year = 1; year <= analysis_period; year++) {
    const degradation_factor = Math.pow(1 - degradation_rate, year - 1);
    // Apply inflation to energy price (always)
    const inflation_factor = Math.pow(1 + inflation_rate, year - 1);
    const adjusted_energy_price = total_energy_price_per_kwh * inflation_factor;

    const savings = self_consumed_annual_mwh * degradation_factor * adjusted_energy_price * 1000;

    // EaaS costs: subscription during contract, O&M+insurance after
    let costs;
    if (year <= eaas_duration) {
      // During contract: ONLY subscription (already includes O&M + insurance)
      const eaas_inflation_factor = eaas_indexation === 'cpi' ? inflation_factor : 1;
      costs = base_subscription_cost * eaas_inflation_factor;
    } else {
      // After contract: client pays O&M + insurance, always inflation-adjusted
      costs = (base_om_cost + base_insurance_cost) * inflation_factor;
    }
    const cash_flow = savings - costs;
    npv += cash_flow / Math.pow(1 + discount_rate, year);
  }

  return npv;
}

/**
 * Generate sensitivity analysis charts for CAPEX vs EaaS
 */
function generateSensitivityAnalysisCharts() {
  console.log('📊 Generating sensitivity analysis charts...');

  const variant = variants[currentVariant];
  if (!variant) {
    console.error('❌ No variant data for sensitivity analysis');
    return;
  }

  const params = getEconomicParameters();
  // calculateTotalEnergyPrice() już zawiera wszystkie składniki włącznie z opłatą mocową
  const totalEnergyPrice = calculateTotalEnergyPrice(params);

  // Get EaaS parameters from fullModelResult (stored globally)
  const eaasSubscription = window.eaasSubscription || 800000;
  const eaasOM = params.opex_per_kwp || (systemSettings?.opexPerKwp || 15);
  const eaasDuration = systemSettings?.eaasDuration || 10;
  const insuranceRate = systemSettings?.insuranceRate || 0.005;

  // Base parameters
  const capacity_kwp = variant.capacity;
  const self_consumed = variant.self_consumed;
  const capex_per_kwp = getCapexForCapacity(capacity_kwp);
  const base_discount_rate = window.economicsSettings?.discountRate;
  const inflation_rate = window.economicsSettings?.inflationRate;
  const eaas_indexation = window.economicsSettings?.eaasIndexation || 'fixed';

  // === 1. Energy Price Sensitivity Chart ===
  const energyPriceVariations = [-30, -20, -10, 0, 10, 20, 30, 40, 50];
  const capexNPVsByEnergy = [];
  const eaasNPVsByEnergy = [];
  const energyPriceLabels = [];

  energyPriceVariations.forEach(variation => {
    const factor = 1 + (variation / 100);
    const adjustedPrice = totalEnergyPrice * factor;
    energyPriceLabels.push(`${variation > 0 ? '+' : ''}${variation}%`);

    const capexNPV = calculateCapexNPV({
      capacity_kwp,
      self_consumed_annual_kwh: self_consumed,
      total_energy_price_per_kwh: adjustedPrice / 1000,
      capex_per_kwp,
      opex_per_kwp: params.opex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: base_discount_rate,
      analysis_period: params.analysis_period,
      inflation_rate
    });

    const eaasNPV = calculateEaaSNPV({
      capacity_kwp,
      self_consumed_annual_kwh: self_consumed,
      total_energy_price_per_kwh: adjustedPrice / 1000,
      eaas_subscription: eaasSubscription,
      eaas_om_per_kwp: eaasOM,
      insurance_rate: insuranceRate,
      capex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: base_discount_rate,
      eaas_duration: eaasDuration,
      analysis_period: params.analysis_period,
      inflation_rate,
      eaas_indexation
    });

    capexNPVsByEnergy.push(plnToMlnPln(capexNPV).toFixed(2));
    eaasNPVsByEnergy.push(plnToMlnPln(eaasNPV).toFixed(2));
  });

  // Create energy price sensitivity chart
  const ctxEnergy = document.getElementById('sensitivityEnergyPrice')?.getContext('2d');
  if (ctxEnergy) {
    if (sensitivityEnergyChart) sensitivityEnergyChart.destroy();

    sensitivityEnergyChart = new Chart(ctxEnergy, {
      type: 'line',
      data: {
        labels: energyPriceLabels,
        datasets: [
          {
            label: 'NPV CAPEX',
            data: capexNPVsByEnergy,
            borderColor: '#2196f3',
            backgroundColor: '#2196f333',
            borderWidth: 2,
            fill: false,
            tension: 0.4
          },
          {
            label: 'NPV EaaS',
            data: eaasNPVsByEnergy,
            borderColor: '#ff9800',
            backgroundColor: '#ff980033',
            borderWidth: 2,
            fill: false,
            tension: 0.4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: true, position: 'top' }
        },
        scales: {
          y: {
            title: { display: true, text: 'NPV [mln PLN]' }
          },
          x: {
            title: { display: true, text: 'Zmiana ceny energii' }
          }
        }
      }
    });
  }

  // === 2. Discount Rate Sensitivity Chart ===
  const discountRateVariations = [3, 4, 5, 6, 7, 8, 9, 10, 12];
  const capexNPVsByDiscount = [];
  const eaasNPVsByDiscount = [];
  const discountRateLabels = [];

  discountRateVariations.forEach(rate => {
    const discountRate = rate / 100;
    discountRateLabels.push(`${rate}%`);

    const capexNPV = calculateCapexNPV({
      capacity_kwp,
      self_consumed_annual_kwh: self_consumed,
      total_energy_price_per_kwh: totalEnergyPrice / 1000,
      capex_per_kwp,
      opex_per_kwp: params.opex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: discountRate,
      analysis_period: params.analysis_period,
      inflation_rate
    });

    const eaasNPV = calculateEaaSNPV({
      capacity_kwp,
      self_consumed_annual_kwh: self_consumed,
      total_energy_price_per_kwh: totalEnergyPrice / 1000,
      eaas_subscription: eaasSubscription,
      eaas_om_per_kwp: eaasOM,
      insurance_rate: insuranceRate,
      capex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: discountRate,
      eaas_duration: eaasDuration,
      analysis_period: params.analysis_period,
      inflation_rate,
      eaas_indexation
    });

    capexNPVsByDiscount.push(plnToMlnPln(capexNPV).toFixed(2));
    eaasNPVsByDiscount.push(plnToMlnPln(eaasNPV).toFixed(2));
  });

  // Create discount rate sensitivity chart
  const ctxDiscount = document.getElementById('sensitivityDiscountRate')?.getContext('2d');
  if (ctxDiscount) {
    if (sensitivityDiscountChart) sensitivityDiscountChart.destroy();

    sensitivityDiscountChart = new Chart(ctxDiscount, {
      type: 'line',
      data: {
        labels: discountRateLabels,
        datasets: [
          {
            label: 'NPV CAPEX',
            data: capexNPVsByDiscount,
            borderColor: '#2196f3',
            backgroundColor: '#2196f333',
            borderWidth: 2,
            fill: false,
            tension: 0.4
          },
          {
            label: 'NPV EaaS',
            data: eaasNPVsByDiscount,
            borderColor: '#ff9800',
            backgroundColor: '#ff980033',
            borderWidth: 2,
            fill: false,
            tension: 0.4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: true, position: 'top' }
        },
        scales: {
          y: {
            title: { display: true, text: 'NPV [mln PLN]' }
          },
          x: {
            title: { display: true, text: 'Stopa dyskontowa' }
          }
        }
      }
    });
  }

  // === 3. Generate break-even table ===
  generateSensitivityBreakevenTable({
    baseEnergyPrice: totalEnergyPrice,
    baseDiscountRate: base_discount_rate,
    baseCapexNPV: parseFloat(capexNPVsByEnergy[energyPriceVariations.indexOf(0)]),
    baseEaasNPV: parseFloat(eaasNPVsByEnergy[energyPriceVariations.indexOf(0)]),
    capacity_kwp,
    self_consumed,
    capex_per_kwp,
    opex_per_kwp: params.opex_per_kwp,
    degradation_rate: params.degradation_rate,
    analysis_period: params.analysis_period,
    eaas_subscription: eaasSubscription,
    eaas_om_per_kwp: eaasOM,
    insurance_rate: insuranceRate,
    eaas_duration: eaasDuration,
    inflation_rate,
    eaas_indexation
  });

  console.log('✅ Sensitivity analysis charts generated');
}

/**
 * Generate break-even table for sensitivity analysis
 */
function generateSensitivityBreakevenTable(params) {
  const tableBody = document.getElementById('sensitivityBreakevenBody');
  if (!tableBody) return;

  tableBody.innerHTML = '';

  // Determine which model is better at base values
  const betterModel = params.baseCapexNPV > params.baseEaasNPV ? 'CAPEX' : 'EaaS';
  const npvDifference = params.baseCapexNPV - params.baseEaasNPV;

  // Find break-even for energy price
  let energyBreakeven = 'Brak';
  for (let variation = -50; variation <= 100; variation += 1) {
    const factor = 1 + (variation / 100);
    const adjustedPrice = params.baseEnergyPrice * factor;

    const capexNPV = calculateCapexNPV({
      capacity_kwp: params.capacity_kwp,
      self_consumed_annual_kwh: params.self_consumed,
      total_energy_price_per_kwh: adjustedPrice / 1000,
      capex_per_kwp: params.capex_per_kwp,
      opex_per_kwp: params.opex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: params.baseDiscountRate,
      analysis_period: params.analysis_period,
      inflation_rate: params.inflation_rate || 0
    });

    const eaasNPV = calculateEaaSNPV({
      capacity_kwp: params.capacity_kwp,
      self_consumed_annual_kwh: params.self_consumed,
      total_energy_price_per_kwh: adjustedPrice / 1000,
      eaas_subscription: params.eaas_subscription,
      eaas_om_per_kwp: params.eaas_om_per_kwp,
      insurance_rate: params.insurance_rate,
      capex_per_kwp: params.capex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: params.baseDiscountRate,
      eaas_duration: params.eaas_duration,
      analysis_period: params.analysis_period,
      inflation_rate: params.inflation_rate || 0,
      eaas_indexation: params.eaas_indexation || 'fixed'
    });

    // Check if sign changes (crossed break-even)
    if (Math.abs(capexNPV - eaasNPV) < 50000) { // Within 50k PLN
      energyBreakeven = `${variation > 0 ? '+' : ''}${variation}%`;
      break;
    }
  }

  // Find break-even for discount rate
  let discountBreakeven = 'Brak';
  for (let rate = 1; rate <= 20; rate += 0.5) {
    const discountRate = rate / 100;

    const capexNPV = calculateCapexNPV({
      capacity_kwp: params.capacity_kwp,
      self_consumed_annual_kwh: params.self_consumed,
      total_energy_price_per_kwh: params.baseEnergyPrice / 1000,
      capex_per_kwp: params.capex_per_kwp,
      opex_per_kwp: params.opex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: discountRate,
      analysis_period: params.analysis_period,
      inflation_rate: params.inflation_rate || 0
    });

    const eaasNPV = calculateEaaSNPV({
      capacity_kwp: params.capacity_kwp,
      self_consumed_annual_kwh: params.self_consumed,
      total_energy_price_per_kwh: params.baseEnergyPrice / 1000,
      eaas_subscription: params.eaas_subscription,
      eaas_om_per_kwp: params.eaas_om_per_kwp,
      insurance_rate: params.insurance_rate,
      capex_per_kwp: params.capex_per_kwp,
      degradation_rate: params.degradation_rate,
      discount_rate: discountRate,
      eaas_duration: params.eaas_duration,
      analysis_period: params.analysis_period,
      inflation_rate: params.inflation_rate || 0,
      eaas_indexation: params.eaas_indexation || 'fixed'
    });

    if (Math.abs(capexNPV - eaasNPV) < 50000) {
      discountBreakeven = `${rate.toFixed(1)}%`;
      break;
    }
  }

  // Row 1: Energy price
  const row1 = document.createElement('tr');
  row1.innerHTML = `
    <td>Cena energii</td>
    <td>${formatNumberEU(params.baseEnergyPrice, 0)} PLN/MWh</td>
    <td>${energyBreakeven}</td>
    <td><span style="color:${betterModel === 'CAPEX' ? '#2196f3' : '#ff9800'};font-weight:600">${betterModel}</span></td>
    <td class="${npvDifference >= 0 ? 'positive' : 'negative'}">${formatNumberEU(npvDifference, 2)}</td>
  `;
  tableBody.appendChild(row1);

  // Row 2: Discount rate
  const row2 = document.createElement('tr');
  row2.innerHTML = `
    <td>Stopa dyskontowa</td>
    <td>${formatNumberEU(params.baseDiscountRate * 100, 0)}%</td>
    <td>${discountBreakeven}</td>
    <td><span style="color:${betterModel === 'CAPEX' ? '#2196f3' : '#ff9800'};font-weight:600">${betterModel}</span></td>
    <td class="${npvDifference >= 0 ? 'positive' : 'negative'}">${formatNumberEU(npvDifference, 2)}</td>
  `;
  tableBody.appendChild(row2);
}

// Export economics analysis
function exportEconomics() {
  if (!economicData && !pvConfig) {
    alert('Brak danych do eksportu');
    return;
  }

  const metrics = calculateFinancialMetrics();

  const report = {
    exportedAt: new Date().toISOString(),
    metrics: metrics,
    economicData: economicData,
    pvConfig: pvConfig
  };

  const dataStr = JSON.stringify(report, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(dataBlob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `analiza-ekonomiczna-${new Date().toISOString().split('T')[0]}.json`;
  link.click();

  URL.revokeObjectURL(url);
}

// Update parameters
function updateParameters() {
  alert('Funkcja aktualizacji parametrów dostępna w module Configuration');
  window.parent.postMessage({ type: 'NAVIGATE_TO', module: 'config' }, '*');
}

// Refresh data
function refreshData() {
  loadAllData();
}

// Generate CAPEX payback table (similar structure to EaaS table)
function generatePaybackTable(data, capacity_kwp, params) {
  const tableBody = document.getElementById('paybackTableBody');
  if (!tableBody) return;

  tableBody.innerHTML = '';

  // ========== USE CENTRALIZED CALCULATIONS - SINGLE SOURCE OF TRUTH ==========
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc || !centralizedCalc.capex) {
    console.warn('⚠️ No centralized CAPEX metrics available for payback table');
    return;
  }

  const cashFlows = centralizedCalc.capex.cashFlows;
  const investment = centralizedCalc.capex.investment;
  const discountRate = centralizedCalc.common.discountRate;
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice;
  const inflationRate = centralizedCalc.common.inflationRate;

  // Get annual consumption using helper function
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = kwhToMwh(annualConsumptionKwh);

  console.log('📊 CAPEX TABLE - Using centralizedMetrics:', {
    variant: currentVariant,
    investment: investment,
    cashFlowsCount: cashFlows.length,
    discountRate: discountRate,
    annualConsumptionMwh: annualConsumptionMwh
  });

  // Year 0 - Initial investment (12 columns now with degradation)
  const row0 = document.createElement('tr');
  row0.className = 'year-0';
  row0.style.background = '#ffebee';
  row0.innerHTML = `
    <td>0</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td class="negative">-${formatNumberEU(plnToTysPln(investment), 0)}</td>
    <td class="negative">-${formatNumberEU(plnToMlnPln(investment), 2)}</td>
  `;
  tableBody.appendChild(row0);

  // Calculate cumulative NPV
  let cumulativeNPV = -investment;
  let breakEvenYear = null;
  let totalSavings = 0;

  // Years 1-N - all data from centralizedMetrics.capex.cashFlows
  cashFlows.forEach((cf) => {
    const row = document.createElement('tr');
    const year = cf.year;

    // Inflation factor for this year
    const inflationFactor = Math.pow(1 + inflationRate, year - 1);

    // A. Energia z Sieci OSD = całkowite zużycie zakładu (stałe)
    const gridEnergyMwh = annualConsumptionMwh;

    // B. Koszt Sieci OSD = całe zużycie × cena z inflacją
    const yearGridCostFull = gridEnergyMwh * totalEnergyPrice * inflationFactor;

    // C. Autokonsumpcja - breakdown PV/BESS (z degradacją) - dane w kWh, konwersja do MWh
    const selfConsumedMwh = kwhToMwh(cf.selfConsumed || 0);
    const pvDirectMwh = kwhToMwh(cf.selfConsumedPvDirect || 0);
    const bessMwh = kwhToMwh(cf.selfConsumedBess || 0);

    // D. Równoważny Koszt OSD = autokonsumpcja × cena sieci z inflacją
    const equivalentGridCost = cf.savings || 0; // savings = selfConsumed × price

    // E. OPEX
    const opex = cf.opex || 0;

    // F. Oszczędności = Równoważny Koszt OSD - OPEX = net_cash_flow
    const savings = cf.net_cash_flow || 0;
    totalSavings += savings;

    // G. CF Zdyskontowany
    const discountedCF = savings / Math.pow(1 + discountRate, year);

    // H. Skumulowany NPV
    cumulativeNPV += discountedCF;

    // Check if this is the break-even year
    const prevNPV = cumulativeNPV - discountedCF;
    if (prevNPV < 0 && cumulativeNPV >= 0 && !breakEvenYear) {
      breakEvenYear = year;
      row.className = 'breakeven';
      row.style.background = '#e8f5e9';
      row.style.borderTop = '3px solid #4caf50';
      row.style.borderBottom = '3px solid #4caf50';
    }

    const savingsClass = savings >= 0 ? 'positive' : 'negative';
    const npvClass = cumulativeNPV >= 0 ? 'positive' : 'negative';

    // Degradation percentages (from cashFlows)
    const pvDegPct = cf.pvDegradationPct || 100;
    const bessDegPct = cf.bessDegradationPct || 100;

    // Kolumny (12 total with degradation):
    // 1. Rok
    // 2. Deg PV %
    // 3. Deg BESS %
    // 4. Zużycie MWh
    // 5. Koszt OSD tys. PLN
    // 6. Auto PV MWh
    // 7. Auto BESS MWh
    // 8. Suma Auto MWh
    // 9. Równow. OSD tys. PLN
    // 10. OPEX tys. PLN
    // 11. Oszczędn. tys. PLN
    // 12. NPV mln PLN
    row.innerHTML = `
      <td>${year}</td>
      <td>${formatNumberEU(pvDegPct, 1)}</td>
      <td>${formatNumberEU(bessDegPct, 1)}</td>
      <td>${formatNumberEU(gridEnergyMwh, 1)}</td>
      <td>${formatNumberEU(plnToTysPln(yearGridCostFull), 0)}</td>
      <td>${formatNumberEU(pvDirectMwh, 1)}</td>
      <td>${formatNumberEU(bessMwh, 1)}</td>
      <td>${formatNumberEU(selfConsumedMwh, 1)}</td>
      <td>${formatNumberEU(plnToTysPln(equivalentGridCost), 0)}</td>
      <td>${formatNumberEU(plnToTysPln(opex), 0)}</td>
      <td class="${savingsClass}">${formatNumberEU(plnToTysPln(savings), 0)}</td>
      <td class="${npvClass}">${formatNumberEU(plnToMlnPln(cumulativeNPV), 2)}</td>
    `;

    tableBody.appendChild(row);
  });

  // Add summary row
  const summaryRow = document.createElement('tr');
  summaryRow.style.background = '#f5f5f5';
  summaryRow.style.fontWeight = '700';
  summaryRow.style.borderTop = '3px solid #27ae60';

  const npvClass = cumulativeNPV >= 0 ? 'positive' : 'negative';

  summaryRow.innerHTML = `
    <td colspan="10" style="text-align:right">💰 SUMA CAŁKOWITA (${cashFlows.length} lat) / NPV (${formatNumberEU(decimalToPct(discountRate), 0)}%):</td>
    <td class="positive">${formatNumberEU(plnToTysPln(totalSavings), 0)}</td>
    <td class="${npvClass}">${formatNumberEU(plnToMlnPln(cumulativeNPV), 2)}</td>
  `;
  tableBody.appendChild(summaryRow);

  console.log('✅ CAPEX table generated. Break-even year:', breakEvenYear || 'Beyond analysis period', ', Final NPV:', plnToMlnPln(cumulativeNPV).toFixed(2), 'mln PLN');
}

// Generate revenue and costs table
function generateRevenueTable(data) {
  const tableBody = document.getElementById('revenueTableBody');
  if (!tableBody) return;

  tableBody.innerHTML = '';

  // ========== USE CENTRALIZED CALCULATIONS - SINGLE SOURCE OF TRUTH ==========
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc || !centralizedCalc.capex) {
    console.warn('⚠️ No centralized CAPEX metrics available for revenue table');
    return;
  }

  const cashFlows = centralizedCalc.capex.cashFlows;

  console.log('📊 REVENUE TABLE - Using centralizedMetrics:', {
    variant: currentVariant,
    cashFlowsCount: cashFlows.length
  });

  // Show first 10 years
  const yearsToShow = Math.min(10, cashFlows.length);
  let totalSavings = 0;
  let totalOpex = 0;
  let totalProfit = 0;

  for (let i = 0; i < yearsToShow; i++) {
    const cf = cashFlows[i];
    const row = document.createElement('tr');

    // Data from centralizedMetrics.capex.cashFlows
    const savings = cf.savings || 0;
    const opex = cf.opex || 0;
    const profit = cf.net_cash_flow || 0;
    const margin = savings > 0 ? decimalToPct(profit / savings) : 0;

    totalSavings += savings;
    totalOpex += opex;
    totalProfit += profit;

    const profitClass = profit >= 0 ? 'positive' : 'negative';
    const marginClass = margin >= 0 ? 'positive' : 'negative';

    row.innerHTML = `
      <td>${cf.year}</td>
      <td>${formatNumberEU(plnToTysPln(savings), 0)}</td>
      <td>${formatNumberEU(plnToTysPln(opex), 0)}</td>
      <td class="${profitClass}">${formatNumberEU(plnToTysPln(profit), 0)}</td>
      <td class="${marginClass}">${formatNumberEU(margin, 1)}%</td>
    `;

    tableBody.appendChild(row);
  }

  // Add summary row
  const summaryRow = document.createElement('tr');
  summaryRow.style.background = '#f8f9fa';
  summaryRow.style.fontWeight = '600';
  summaryRow.style.borderTop = '2px solid #27ae60';

  const avgMargin = totalSavings > 0 ? decimalToPct(totalProfit / totalSavings) : 0;
  const avgMarginClass = avgMargin >= 0 ? 'positive' : 'negative';

  summaryRow.innerHTML = `
    <td>SUMA</td>
    <td>${formatNumberEU(plnToTysPln(totalSavings), 0)}</td>
    <td>${formatNumberEU(plnToTysPln(totalOpex), 0)}</td>
    <td class="positive">${formatNumberEU(plnToTysPln(totalProfit), 0)}</td>
    <td class="${avgMarginClass}">${formatNumberEU(avgMargin, 1)}%</td>
  `;

  tableBody.appendChild(summaryRow);

  console.log('✅ Revenue table generated from centralizedMetrics for first', yearsToShow, 'years');
}

// Export revenue table to Excel (all 25 years)
// P0-1/P0-2: Updated to include BESS Replacement and Residual Value columns
function exportRevenueToExcel() {
  if (!economicData || !economicData.cash_flows) {
    alert('Brak danych do eksportu. Wykonaj najpierw analizę.');
    return;
  }

  console.log('📥 Exporting revenue table to Excel...');

  // Prepare data for Excel
  const excelData = [];

  // P0-1/P0-2: Extended header row with BESS Replacement and Residual Value
  excelData.push([
    'Rok',
    'Oszczędności [tys. PLN]',
    'OPEX [tys. PLN]',
    'BESS Replacement [tys. PLN]',  // P0-1
    'Residual Value [tys. PLN]',    // P0-2
    'Zysk netto [tys. PLN]',
    'Marża [%]'
  ]);

  // Data rows
  let totalSavings = 0;
  let totalOpex = 0;
  let totalBessReplacement = 0;
  let totalResidualValue = 0;
  let totalProfit = 0;

  economicData.cash_flows.forEach((cf) => {
    const savings = plnToTysPln(cf.savings); // PLN → tys. PLN
    const opex = plnToTysPln(cf.opex);
    const bessReplacement = plnToTysPln(cf.bessReplacementCost || 0);  // P0-1
    const residualVal = plnToTysPln(cf.residualValue || 0);            // P0-2
    const profit = plnToTysPln(cf.net_cash_flow);
    const margin = savings > 0 ? decimalToPct(profit / savings) : 0;

    totalSavings += savings;
    totalOpex += opex;
    totalBessReplacement += bessReplacement;
    totalResidualValue += residualVal;
    totalProfit += profit;

    excelData.push([
      cf.year,
      parseFloat(savings.toFixed(2)),
      parseFloat(opex.toFixed(2)),
      parseFloat(bessReplacement.toFixed(2)),   // P0-1
      parseFloat(residualVal.toFixed(2)),       // P0-2
      parseFloat(profit.toFixed(2)),
      parseFloat(margin.toFixed(2))
    ]);
  });

  // Summary row - P0-1/P0-2: Include BESS Replacement and Residual Value totals
  const avgMargin = totalSavings > 0 ? decimalToPct(totalProfit / totalSavings) : 0;
  excelData.push([
    'SUMA',
    parseFloat(totalSavings.toFixed(2)),
    parseFloat(totalOpex.toFixed(2)),
    parseFloat(totalBessReplacement.toFixed(2)),  // P0-1
    parseFloat(totalResidualValue.toFixed(2)),    // P0-2
    parseFloat(totalProfit.toFixed(2)),
    parseFloat(avgMargin.toFixed(2))
  ]);

  // Create workbook and worksheet
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(excelData);

  // Set column widths - P0-1/P0-2: Added columns for BESS Replacement and Residual Value
  ws['!cols'] = [
    { wch: 10 },  // Rok
    { wch: 22 },  // Oszczędności
    { wch: 18 },  // OPEX
    { wch: 22 },  // BESS Replacement (P0-1)
    { wch: 22 },  // Residual Value (P0-2)
    { wch: 20 },  // Zysk netto
    { wch: 12 }   // Marża
  ];

  // Add worksheet to workbook
  XLSX.utils.book_append_sheet(wb, ws, 'Przychody i Koszty');

  // Generate filename with date
  const variant = variants[currentVariant];
  const capacity = kwhToMwh(variant.capacity).toFixed(1);
  const date = new Date().toISOString().split('T')[0];
  const filename = `Analiza_Ekonomiczna_${capacity}MWp_${date}.xlsx`;

  // Download file
  XLSX.writeFile(wb, filename);

  console.log('✅ Excel file exported:', filename);
}

// Clear analysis
function clearAnalysis() {
  economicData = null;
  pvConfig = null;
  productionData = null;

  if (capexChart) capexChart.destroy();
  if (opexChart) opexChart.destroy();
  if (cashFlowChart) cashFlowChart.destroy();
  if (revenueChart) revenueChart.destroy();
  if (sensitivityChart) sensitivityChart.destroy();

  showNoData();
}

// ============================================================================
// === EAAS MODULE START ===
// ============================================================================

const EAAS_CONFIG = {
  INSURANCE_RATE: 0.003  // 0.3% of CAPEX annually
};

/**
 * Calculate total grid energy cost per kWh
 */
function calculateGridEnergyPrice(tariffComponents) {
  const {
    energyActive = 550,
    distribution = 200,
    quality = 10,
    oze = 7,
    cogeneration = 10,
    capacity = 219,
    excise = 5
  } = tariffComponents;

  const totalGridCostPLNperMWh =
    energyActive + distribution + quality + oze +
    cogeneration + capacity + excise;

  return totalGridCostPLNperMWh / 1000.0;  // Convert to PLN/kWh
}

/**
 * Calculate effective EaaS price per kWh
 * UPDATED: Now uses profile-analysis data when available for accurate self-consumption
 */
function calculateEaaSEffectivePrice(params) {
  const {
    annualPVProductionKWh,
    selfConsumptionRatio,
    pvPowerKWp,
    pvCapexPLN,
    eaasSubscriptionPLNperYear,
    omCostPerKWp
  } = params;

  // SSoT Refactor: self-consumption comes from the single trusted variant data
  const pvSelfConsumedKWh = annualPVProductionKWh * selfConsumptionRatio;
  console.log(`📊 EaaS Effective Price using SSoT: ${(pvSelfConsumedKWh/1000).toFixed(1)} MWh`);

  if (pvSelfConsumedKWh <= 0) {
    return {
      error: 'Brak autokonsumpcji',
      eaasPricePLNperKWh: null,
      breakdown: null
    };
  }

  const omCostPLNperYear = omCostPerKWp * pvPowerKWp;
  const insuranceCostPLNperYear = EAAS_CONFIG.INSURANCE_RATE * pvCapexPLN;

  // IMPORTANT: eaasSubscriptionPLNperYear already includes OPEX and insurance
  // (calculated in calculateEaasSubscription() function)
  // We should NOT add them again here - that would be double-counting!
  const eaasTotalAnnualCostPLN = eaasSubscriptionPLNperYear;

  const eaasPricePLNperKWh = eaasTotalAnnualCostPLN / pvSelfConsumedKWh;

  console.log(`📊 calculateEaaSEffectivePrice RESULT: ${(eaasPricePLNperKWh * 1000).toFixed(2)} PLN/MWh (subscription=${plnToTysPln(eaasTotalAnnualCostPLN).toFixed(0)}k / energy=${kwhToMwh(pvSelfConsumedKWh).toFixed(1)} MWh)`);

  return {
    error: null,
    eaasPricePLNperKWh: eaasPricePLNperKWh,
    breakdown: {
      pvSelfConsumedKWh: pvSelfConsumedKWh,
      subscriptionCost: eaasSubscriptionPLNperYear,
      omCost: omCostPLNperYear,
      insuranceCost: insuranceCostPLNperYear,
      totalAnnualCost: eaasTotalAnnualCostPLN
    }
  };
}

/**
 * Calculate EaaS financial metrics and ROI
 */
function calculateEaaSFinancialMetrics(params) {
  const {
    annualConsumptionKWh,
    annualPVProductionKWh,
    selfConsumptionRatio,
    pvPowerKWp,
    pvCapexPLN,
    eaasSubscriptionPLNperYear,
    tariffComponents,
    omCostPerKWp
  } = params;

  let gridPricePLNperKWh = calculateGridEnergyPrice(tariffComponents);

  // Override with weighted price for hybrid monthly pricing
  const econParams = getEconomicParameters();
  const hybridWeighted = computeWeightedEnergyPrice(econParams);
  if (hybridWeighted) {
    gridPricePLNperKWh = hybridWeighted.weightedTotal / 1000; // PLN/MWh -> PLN/kWh
    console.log(`💰 EaaS grid price overridden with hybrid weighted: ${(gridPricePLNperKWh * 1000).toFixed(1)} PLN/MWh`);
  }

  const eaasResult = calculateEaaSEffectivePrice({
    annualPVProductionKWh,
    selfConsumptionRatio,
    pvPowerKWp,
    pvCapexPLN,
    eaasSubscriptionPLNperYear,
    omCostPerKWp
  });

  if (eaasResult.error) {
    return { error: eaasResult.error, metrics: null };
  }

  const eaasPricePLNperKWh = eaasResult.eaasPricePLNperKWh;
  const pvSelfConsumedKWh = eaasResult.breakdown.pvSelfConsumedKWh;

  const annualSavingsPLN = pvSelfConsumedKWh * (gridPricePLNperKWh - eaasPricePLNperKWh);
  const baselineEnergyCostPLN = annualConsumptionKWh * gridPricePLNperKWh;
  const savingsPercentageVsBaseline = (annualSavingsPLN / baselineEnergyCostPLN) * 100;

  let eaasEquivalentPaybackYears = null;
  let eaasEquivalentROI = null;

  if (annualSavingsPLN > 0) {
    eaasEquivalentPaybackYears = pvCapexPLN / annualSavingsPLN;
    eaasEquivalentROI = (annualSavingsPLN / pvCapexPLN) * 100;
  }

  return {
    error: null,
    metrics: {
      gridPricePLNperKWh: gridPricePLNperKWh,
      eaasPricePLNperKWh: eaasPricePLNperKWh,
      priceDifferencePLNperKWh: gridPricePLNperKWh - eaasPricePLNperKWh,
      annualSavingsPLN: annualSavingsPLN,
      savingsPercentageVsBaseline: savingsPercentageVsBaseline,
      eaasEquivalentPaybackYears: eaasEquivalentPaybackYears,
      eaasEquivalentROI: eaasEquivalentROI,
      baselineEnergyCostPLN: baselineEnergyCostPLN,
      breakdown: eaasResult.breakdown,
      pvCapexPLN: pvCapexPLN  // Added CAPEX for payback/ROI calculations
    }
  };
}

/**
 * Calculate EaaS metrics with BESS savings (arbitrage, peak-shaving, capacity fee)
 *
 * This function extends the basic EaaS calculation by incorporating BESS benefits:
 * - Net subscription after BESS savings
 * - Net effective EaaS price (accounting for BESS revenues)
 * - BESS discount percentage
 * - BESS-specific payback period
 *
 * @param {object} params - Input parameters
 * @param {number} params.eaasSubscriptionPLNperYear - Annual EaaS subscription [PLN]
 * @param {number} params.pvSelfConsumedKWh - Annual PV self-consumption [kWh]
 * @param {number} params.gridPricePLNperMWh - Grid energy price [PLN/MWh]
 * @param {object} params.savingsBreakdown - BESS savings breakdown from pv-calculation
 * @param {number} params.bessCapexPLN - BESS CAPEX [PLN]
 * @returns {object} Extended EaaS metrics with BESS
 */
function calculateEaaSWithBessSavings(params) {
  const {
    eaasSubscriptionPLNperYear,
    pvSelfConsumedKWh,
    gridPricePLNperMWh,
    savingsBreakdown,
    bessCapexPLN
  } = params;

  // Base metrics (without BESS savings)
  const baseEaasPricePLNperMWh = pvSelfConsumedKWh > 0
    ? (eaasSubscriptionPLNperYear / pvSelfConsumedKWh) * 1000
    : null;

  // No BESS savings available - return base metrics only
  if (!savingsBreakdown || !savingsBreakdown.net_savings_pln) {
    return {
      hasBessSavings: false,
      baseSubscriptionPLN: eaasSubscriptionPLNperYear,
      baseEaasPricePLNperMWh: baseEaasPricePLNperMWh,
      netSubscriptionPLN: null,
      netEaasPricePLNperMWh: null,
      bessDiscountPct: null,
      bessAnnualSavingsPLN: null,
      premiumVsGridPct: null,
      bessPaybackYears: null,
      savingsBreakdownDetail: null
    };
  }

  // Extract BESS savings components
  const energySavings = savingsBreakdown.energy_savings_pln || 0;
  const arbitrageSavings = savingsBreakdown.arbitrage_savings_pln || 0;
  const capacityFeeSavings = savingsBreakdown.capacity_fee_savings_pln || 0;
  const demandChargeSavings = savingsBreakdown.demand_charge_savings_pln || 0;
  const degradationCost = savingsBreakdown.degradation_cost_pln || 0;
  const netSavings = savingsBreakdown.net_savings_pln || 0;

  // Net subscription = Subscription - BESS savings (client's effective cost)
  const netSubscriptionPLN = eaasSubscriptionPLNperYear - netSavings;

  // Net effective EaaS price (what client actually pays per kWh)
  const netEaasPricePLNperMWh = pvSelfConsumedKWh > 0
    ? (netSubscriptionPLN / pvSelfConsumedKWh) * 1000
    : null;

  // BESS discount = how much of subscription is "returned" via BESS savings
  const bessDiscountPct = eaasSubscriptionPLNperYear > 0
    ? (netSavings / eaasSubscriptionPLNperYear) * 100
    : null;

  // Premium vs grid = how much cheaper than grid after BESS savings
  const premiumVsGridPct = gridPricePLNperMWh > 0 && netEaasPricePLNperMWh !== null
    ? ((gridPricePLNperMWh - netEaasPricePLNperMWh) / gridPricePLNperMWh) * 100
    : null;

  // BESS-only payback (how fast BESS pays for itself via savings)
  const bessPaybackYears = (bessCapexPLN > 0 && netSavings > 0)
    ? bessCapexPLN / netSavings
    : null;

  console.log(`📊 calculateEaaSWithBessSavings:`, {
    baseSubscription: eaasSubscriptionPLNperYear,
    netSavings: netSavings,
    netSubscription: netSubscriptionPLN,
    basePrice: baseEaasPricePLNperMWh?.toFixed(2),
    netPrice: netEaasPricePLNperMWh?.toFixed(2),
    bessDiscount: bessDiscountPct?.toFixed(1) + '%',
    premiumVsGrid: premiumVsGridPct?.toFixed(1) + '%',
    bessPayback: bessPaybackYears?.toFixed(1) + ' lat'
  });

  return {
    hasBessSavings: true,
    // Base metrics (without BESS savings)
    baseSubscriptionPLN: eaasSubscriptionPLNperYear,
    baseEaasPricePLNperMWh: baseEaasPricePLNperMWh,
    // Net metrics (with BESS savings applied)
    netSubscriptionPLN: netSubscriptionPLN,
    netEaasPricePLNperMWh: netEaasPricePLNperMWh,
    // BESS-specific metrics
    bessDiscountPct: bessDiscountPct,
    bessAnnualSavingsPLN: netSavings,
    premiumVsGridPct: premiumVsGridPct,
    bessPaybackYears: bessPaybackYears,
    // Detailed breakdown
    savingsBreakdownDetail: {
      energySavings: energySavings,
      arbitrageSavings: arbitrageSavings,
      capacityFeeSavings: capacityFeeSavings,
      demandChargeSavings: demandChargeSavings,
      degradationCost: degradationCost,
      netSavings: netSavings
    }
  };
}

/**
 * Display EaaS + BESS Synergy section
 *
 * Shows extended EaaS metrics incorporating BESS savings:
 * - Net subscription and price after BESS savings
 * - BESS discount percentage
 * - Premium vs grid price
 * - Detailed BESS economics (arbitrage, peak-shaving)
 *
 * @param {object} variant - Current variant data with BESS info
 * @param {number} eaasSubscriptionPLN - Annual EaaS subscription [PLN]
 * @param {number} annualEnergyMWh - Annual self-consumed energy [MWh]
 * @param {object} params - Economic parameters
 */
function displayEaasBessSynergy(variant, eaasSubscriptionPLN, annualEnergyMWh, params) {
  const section = document.getElementById('eaasBessSynergySection');
  if (!section) {
    console.warn('EaaS BESS Synergy section not found in DOM');
    return;
  }

  // Check if we have BESS data
  const hasBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  const hasSavingsBreakdown = variant?.savings_breakdown;

  console.log('📊 EaaS BESS Synergy check:', {
    hasBess: hasBess,
    bess_power_kw: variant?.bess_power_kw,
    bess_energy_kwh: variant?.bess_energy_kwh,
    hasSavingsBreakdown: !!hasSavingsBreakdown,
    savings_breakdown: hasSavingsBreakdown
  });

  if (!hasBess || !hasSavingsBreakdown) {
    section.style.display = 'none';
    console.log('📊 EaaS BESS Synergy: HIDDEN (no BESS or no savings_breakdown)');
    return;
  }

  // Show section
  section.style.display = 'block';
  console.log(`📊 EaaS BESS Synergy: SHOWING for BESS ${variant.bess_power_kw} kW / ${variant.bess_energy_kwh} kWh`);

  // Get grid price [PLN/MWh]
  const gridPricePLNperMWh = calculateTotalEnergyPrice(params);

  // Calculate BESS CAPEX
  const settings = systemSettings || {};
  const bessCapexPerKwh = settings.bessCapexPerKwh || 1500;
  const bessCapexPerKw = settings.bessCapexPerKw || 300;
  const bessCapexPLN = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);

  // Calculate extended EaaS metrics with BESS savings
  const bessSynergyMetrics = calculateEaaSWithBessSavings({
    eaasSubscriptionPLNperYear: eaasSubscriptionPLN,
    pvSelfConsumedKWh: annualEnergyMWh * 1000, // MWh -> kWh
    gridPricePLNperMWh: gridPricePLNperMWh,
    savingsBreakdown: variant.savings_breakdown,
    bessCapexPLN: bessCapexPLN
  });

  console.log('📊 EaaS BESS Synergy metrics:', bessSynergyMetrics);

  // Helper for formatting
  const fmt = (val, decimals = 1) => {
    if (val === null || val === undefined || isNaN(val)) return '–';
    return val.toLocaleString('pl-PL', { maximumFractionDigits: decimals });
  };

  // ========== UPDATE DISPLAY ==========

  // Row 1: Price comparison
  const gridPriceEl = document.getElementById('eaasBessGridPrice');
  if (gridPriceEl) gridPriceEl.textContent = fmt(gridPricePLNperMWh, 0);

  const basePriceEl = document.getElementById('eaasBessBasePrice');
  if (basePriceEl) basePriceEl.textContent = fmt(bessSynergyMetrics.baseEaasPricePLNperMWh, 2);

  const netPriceEl = document.getElementById('eaasBessNetPrice');
  if (netPriceEl) {
    netPriceEl.textContent = fmt(bessSynergyMetrics.netEaasPricePLNperMWh, 2);
    // Color based on value vs grid
    if (bessSynergyMetrics.netEaasPricePLNperMWh < gridPricePLNperMWh * 0.7) {
      netPriceEl.style.color = '#1b5e20'; // Dark green for excellent
    } else if (bessSynergyMetrics.netEaasPricePLNperMWh < gridPricePLNperMWh) {
      netPriceEl.style.color = '#2e7d32'; // Green for good
    } else {
      netPriceEl.style.color = '#e65100'; // Orange if higher than grid
    }
  }

  const premiumEl = document.getElementById('eaasBessPremium');
  if (premiumEl) {
    const premiumVal = bessSynergyMetrics.premiumVsGridPct;
    premiumEl.textContent = premiumVal !== null ? fmt(premiumVal, 1) : '–';
    // Color based on premium
    if (premiumVal > 30) {
      premiumEl.style.color = '#1b5e20'; // Dark green for excellent
    } else if (premiumVal > 15) {
      premiumEl.style.color = '#2e7d32'; // Green for good
    } else if (premiumVal > 0) {
      premiumEl.style.color = '#f57c00'; // Orange for moderate
    } else {
      premiumEl.style.color = '#c62828'; // Red if negative
    }
  }

  // Row 2: Subscription and BESS metrics
  const baseSubEl = document.getElementById('eaasBessBaseSub');
  if (baseSubEl) baseSubEl.textContent = fmt(plnToTysPln(bessSynergyMetrics.baseSubscriptionPLN), 1);

  const savingsEl = document.getElementById('eaasBessSavings');
  if (savingsEl) savingsEl.textContent = fmt(plnToTysPln(bessSynergyMetrics.bessAnnualSavingsPLN), 1);

  const netSubEl = document.getElementById('eaasBessNetSub');
  if (netSubEl) netSubEl.textContent = fmt(plnToTysPln(bessSynergyMetrics.netSubscriptionPLN), 1);

  const discountEl = document.getElementById('eaasBessDiscount');
  if (discountEl) {
    discountEl.textContent = fmt(bessSynergyMetrics.bessDiscountPct, 1);
    // Color based on discount
    if (bessSynergyMetrics.bessDiscountPct > 20) {
      discountEl.style.color = '#1b5e20';
    } else if (bessSynergyMetrics.bessDiscountPct > 10) {
      discountEl.style.color = '#00897b';
    } else {
      discountEl.style.color = '#666';
    }
  }

  // Row 3: BESS economics
  const capexEl = document.getElementById('eaasBessCapex');
  if (capexEl) capexEl.textContent = fmt(plnToTysPln(bessCapexPLN), 0);

  const paybackEl = document.getElementById('eaasBessPayback');
  if (paybackEl) {
    paybackEl.textContent = fmt(bessSynergyMetrics.bessPaybackYears, 1);
    // Color based on payback
    if (bessSynergyMetrics.bessPaybackYears && bessSynergyMetrics.bessPaybackYears < 5) {
      paybackEl.style.color = '#1b5e20';
    } else if (bessSynergyMetrics.bessPaybackYears && bessSynergyMetrics.bessPaybackYears < 8) {
      paybackEl.style.color = '#0288d1';
    } else if (bessSynergyMetrics.bessPaybackYears && bessSynergyMetrics.bessPaybackYears < 12) {
      paybackEl.style.color = '#f57c00';
    } else {
      paybackEl.style.color = '#c62828';
    }
  }

  // Detailed breakdown
  const detail = bessSynergyMetrics.savingsBreakdownDetail;
  const arbitrageEl = document.getElementById('eaasBessArbitrage');
  if (arbitrageEl) arbitrageEl.textContent = fmt(plnToTysPln(detail?.arbitrageSavings || 0), 1);

  // Peak shaving = demand charge + capacity fee savings combined
  const peakShavingTotal = (detail?.demandChargeSavings || 0) + (detail?.capacityFeeSavings || 0);
  const peakShavingEl = document.getElementById('eaasBessPeakShaving');
  if (peakShavingEl) peakShavingEl.textContent = fmt(plnToTysPln(peakShavingTotal), 1);

  // Store for potential export
  window.eaasBessSynergyMetrics = bessSynergyMetrics;

  console.log('📊 EaaS BESS Synergy section UPDATED:', {
    gridPrice: gridPricePLNperMWh,
    basePrice: bessSynergyMetrics.baseEaasPricePLNperMWh,
    netPrice: bessSynergyMetrics.netEaasPricePLNperMWh,
    premium: bessSynergyMetrics.premiumVsGridPct,
    bessPayback: bessSynergyMetrics.bessPaybackYears
  });
}

/**
 * Format EaaS results for display
 * Cards with ID prefixes "eaasCard_" are updated by selectProductionScenario()
 */
function formatEaaSResults(result) {
  if (result.error) {
    return `<div style="color:#e74c3c;padding:12px;background:#fff5f5;border-radius:8px;border:1px solid #e74c3c">
      <strong>⚠️ Błąd obliczeń EaaS:</strong> ${result.error}
    </div>`;
  }

  const m = result.metrics;

  // Store base metrics for scenario calculations
  window.eaasBaseMetrics = {
    gridPricePLNperMWh: m.gridPricePLNperKWh * 1000,
    eaasPricePLNperMWh: m.eaasPricePLNperKWh * 1000,
    annualSavingsPLN: m.annualSavingsPLN,
    savingsPercent: m.savingsPercentageVsBaseline,
    paybackYears: m.eaasEquivalentPaybackYears,
    roi: m.eaasEquivalentROI,
    capex: m.pvCapexPLN || 0,  // Use pvCapexPLN from metrics (was previously missing)
    annualCost: m.breakdown?.totalAnnualCost || 0,
    pvSelfConsumedMWh: kwhToMwh(m.breakdown?.pvSelfConsumedKWh || 0)
  };
  console.log('📊 eaasBaseMetrics set with CAPEX:', window.eaasBaseMetrics.capex);

  return `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">
      <div style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Cena energii z sieci</div>
        <div style="color:#2c3e50;font-size:24px;font-weight:600">${(m.gridPricePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>

      <div id="eaasCard_effectivePrice" style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Efektywna cena EaaS</div>
        <div id="eaasVal_effectivePrice" style="color:#27ae60;font-size:24px;font-weight:600">${(m.eaasPricePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>

      <div id="eaasCard_priceDiff" style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Różnica cen</div>
        <div id="eaasVal_priceDiff" style="color:#27ae60;font-size:24px;font-weight:600">${(m.priceDifferencePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">
      <div id="eaasCard_annualSavings" style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Roczne oszczędności</div>
        <div id="eaasVal_annualSavings" style="color:#27ae60;font-size:24px;font-weight:600">${plnToTysPln(m.annualSavingsPLN).toFixed(1)}</div>
        <div id="eaasVal_savingsPercent" style="color:#7f8c8d;font-size:11px">tys. PLN (${m.savingsPercentageVsBaseline.toFixed(1)}% kosztu energii)</div>
      </div>

      <div id="eaasCard_payback" style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Równoważny okres zwrotu</div>
        <div id="eaasVal_payback" style="color:#27ae60;font-size:24px;font-weight:600">${m.eaasEquivalentPaybackYears !== null ? m.eaasEquivalentPaybackYears.toFixed(1) : '–'}</div>
        <div style="color:#7f8c8d;font-size:11px">lat (względem CAPEX)</div>
      </div>

      <div id="eaasCard_roi" style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Równoważny ROI</div>
        <div id="eaasVal_roi" style="color:#27ae60;font-size:24px;font-weight:600">${m.eaasEquivalentROI !== null ? m.eaasEquivalentROI.toFixed(1) : '–'}</div>
        <div style="color:#7f8c8d;font-size:11px">% rocznie</div>
      </div>
    </div>

    <!-- Scenario metrics row - updated by P50/P75/P90 buttons -->
    <div id="eaasScenarioRow" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px">
      <div id="eaasCard_production" style="background:#e8eaf6;padding:16px;border-radius:8px;border-left:4px solid #3f51b5">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Produkcja roczna (<span id="eaasScenarioLabel">P50</span>)</div>
        <div id="eaasVal_production" style="color:#3f51b5;font-size:24px;font-weight:600">${kwhToMwh(m.breakdown?.pvSelfConsumedKWh || 0).toFixed(0)}</div>
        <div style="color:#7f8c8d;font-size:11px">MWh/rok</div>
      </div>

      <div id="eaasCard_subscription" style="background:#e8eaf6;padding:16px;border-radius:8px;border-left:4px solid #3f51b5">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Abonament EaaS</div>
        <div id="eaasVal_subscription" style="color:#3f51b5;font-size:24px;font-weight:600">${plnToTysPln(m.breakdown?.subscriptionCost || 0).toFixed(0)}</div>
        <div style="color:#7f8c8d;font-size:11px">tys. PLN/rok</div>
      </div>

      <div id="eaasCard_escoIrr" style="background:#e8eaf6;padding:16px;border-radius:8px;border-left:4px solid #3f51b5">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">ESCO IRR (fixed)</div>
        <div id="eaasVal_escoIrr" style="color:#3f51b5;font-size:24px;font-weight:600">${decimalToPct(window.eaasEscoIrr || 0).toFixed(1)}</div>
        <div style="color:#7f8c8d;font-size:11px">% (stała subskrypcja)</div>
      </div>
    </div>

    <div style="padding:12px;background:#f8f9fa;border-radius:8px;border:1px solid #e0e0e0;font-size:12px">
      <div style="color:#7f8c8d;font-weight:600;margin-bottom:6px">Rozbicie kosztów EaaS (rocznych):</div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:4px;color:#2c3e50">
        <span>• Abonament: <strong>${plnToTysPln(m.breakdown.subscriptionCost).toFixed(1)}</strong> tys. PLN</span>
        <span>• O&M: <strong>${plnToTysPln(m.breakdown.omCost).toFixed(1)}</strong> tys. PLN</span>
        <span>• Ubezpieczenie: <strong>${plnToTysPln(m.breakdown.insuranceCost).toFixed(1)}</strong> tys. PLN</span>
        <span>• Suma: <strong>${plnToTysPln(m.breakdown.totalAnnualCost).toFixed(1)}</strong> tys. PLN/rok</span>
      </div>
    </div>
  `;
}

/**
 * Calculate and display EaaS analysis
 */
async function calculateEaaS() {
  console.log('Calculating EaaS analysis...');
  console.log('  - variants:', variants);
  console.log('  - currentVariant:', currentVariant);
  console.log('  - systemSettings:', systemSettings);

  const variant = variants[currentVariant];
  if (!variant) {
    console.error('No variant data available for EaaS');
    const resultsDiv = document.getElementById('eaasResults');
    if (resultsDiv) {
      resultsDiv.innerHTML = '<div style="color:#7f8c8d;padding:20px;text-align:center">Load analysis data to see EaaS</div>';
    }
    return;
  }

  if (!systemSettings) {
    console.warn('No system settings available, using defaults');
  }

  const params = getEconomicParameters();

  // ========== FULL MODEL CALCULATION ==========
  // Calculate annual energy delivered to client (MWh)
  //
  // CRITICAL: We need to use the CORRECT self-consumption value:
  // 1. variant.self_consumed = PV direct autoconsumption (calculated in CONFIG with CONFIG BESS)
  // 2. profileAnalysisBessData.annual_discharge_mwh = energy from RECOMMENDED BESS (from profile-analysis)
  // 3. profileAnalysisBessData.direct_consumption_mwh = PV direct autoconsumption (from profile-analysis)
  //
  // When profile-analysis is available, we should use:
  // - direct_consumption_mwh (PV direct) + annual_discharge_mwh (BESS discharge)
  // This gives us the TOTAL energy delivered to client with RECOMMENDED BESS sizing

  let annualEnergyMWh;

  // SSoT Refactor: Always use variant.self_consumed from pv-calculation.
  annualEnergyMWh = kwhToMwh(variant.self_consumed); // kWh -> MWh
  console.log(`📊 EaaS using SSoT variant.self_consumed: ${annualEnergyMWh.toFixed(2)} MWh`);

  // SSoT Refactor: Get BESS data directly from the variant
  const bessDataForEaaS = (variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0) ? variant : null;
  console.log(`📊 EaaS BESS data (from SSoT):`, bessDataForEaaS ?
    `${bessDataForEaaS.bess_power_kw?.toFixed(0) || 0} kW / ${bessDataForEaaS.bess_energy_kwh?.toFixed(0) || 0} kWh` : 'none');

  // Run full investor model with all parameters from Settings (including BESS data)
  const fullModelResult = calculateEaasFullModel(
    variant.capacity,
    annualEnergyMWh,
    systemSettings || {},
    params,
    bessDataForEaaS  // Pass BESS data for CAPEX/OPEX calculation
  );

  console.log('Full EaaS Model Result:', fullModelResult);

  // ========== UPDATE BASIC DISPLAY ==========
  const currency = fullModelResult.currency || 'PLN';

  // Basic subscription display
  document.getElementById('eaasAnnualSub').textContent =
    fullModelResult.annualSubscription.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  document.getElementById('eaasAnnualSubUnit').textContent = `${currency}/rok`;
  document.getElementById('eaasMonthlySub').textContent =
    fullModelResult.monthlySubscription.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  document.getElementById('eaasMonthlySubUnit').textContent = `${currency}/mies`;
  document.getElementById('eaasDurationDisplay').textContent = fullModelResult.contractDuration;

  // Price per MWh
  const pricePerMWhEl = document.getElementById('eaasPricePerMWh');
  if (pricePerMWhEl) {
    pricePerMWhEl.textContent = fullModelResult.pricePerMWh.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  }
  const pricePerMWhUnitEl = document.getElementById('eaasPricePerMWhUnit');
  if (pricePerMWhUnitEl) {
    pricePerMWhUnitEl.textContent = `${currency}/MWh`;
  }

  // ========== UPDATE FULL MODEL DISPLAY ==========
  const fullModelDisplay = document.getElementById('eaasFullModelDisplay');
  if (fullModelDisplay) {
    fullModelDisplay.style.display = 'block';

    // IRR Metrics - European format
    const targetIrrEl = document.getElementById('eaasTargetIRR');
    if (targetIrrEl) targetIrrEl.textContent = formatNumberEU(fullModelResult.targetIrr * 100, 1);

    const projectIrrEl = document.getElementById('eaasProjectIRR');
    if (projectIrrEl) projectIrrEl.textContent = formatNumberEU(fullModelResult.projectIrr * 100, 2);

    const equityIrrEl = document.getElementById('eaasEquityIRR');
    if (equityIrrEl) equityIrrEl.textContent = formatNumberEU(fullModelResult.equityIrr * 100, 2);

    const irrDriverEl = document.getElementById('eaasIrrDriver');
    if (irrDriverEl) irrDriverEl.textContent = fullModelResult.irrDriver;

    // Financing Structure (in millions PLN) - European format
    const totalCapexEl = document.getElementById('eaasTotalCapex');
    if (totalCapexEl) totalCapexEl.textContent = formatNumberEU(fullModelResult.totalCapexPLN / 1e6, 2);

    const debtAmountEl = document.getElementById('eaasDebtAmount');
    if (debtAmountEl) {
      const debtPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.debtAmount * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.debtAmount;
      debtAmountEl.textContent = formatNumberEU(debtPLN / 1e6, 2);
    }

    const equityAmountEl = document.getElementById('eaasEquityAmount');
    if (equityAmountEl) {
      const equityPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.equityAmount * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.equityAmount;
      equityAmountEl.textContent = formatNumberEU(equityPLN / 1e6, 2);
    }

    const leverageEl = document.getElementById('eaasLeverageRatio');
    if (leverageEl) leverageEl.textContent = formatNumberEU(fullModelResult.leverageRatio, 0);

    // Contract Period Summary (in millions PLN) - European format
    const totalRevenueEl = document.getElementById('eaasTotalRevenue');
    if (totalRevenueEl) {
      const revPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.totalRevenue * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.totalRevenue;
      totalRevenueEl.textContent = formatNumberEU(revPLN / 1e6, 2);
    }

    const totalOpexEl = document.getElementById('eaasTotalOpex');
    if (totalOpexEl) {
      const opexPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.totalOpex * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.totalOpex;
      totalOpexEl.textContent = formatNumberEU(opexPLN / 1e6, 2);
    }

    const totalTaxEl = document.getElementById('eaasTotalTax');
    if (totalTaxEl) {
      const taxPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.totalTax * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.totalTax;
      totalTaxEl.textContent = formatNumberEU(taxPLN / 1e6, 2);
    }

    const totalInterestEl = document.getElementById('eaasTotalInterest');
    if (totalInterestEl) {
      const intPLN = fullModelResult.currency === 'EUR'
        ? fullModelResult.totalInterest * (systemSettings?.fxPlnEur || 4.5)
        : fullModelResult.totalInterest;
      totalInterestEl.textContent = formatNumberEU(intPLN / 1e6, 2);
    }

    // Model Parameters Info - European format
    const modelParamsEl = document.getElementById('eaasModelParams');
    if (modelParamsEl) {
      const indexationLabel = fullModelResult.indexationType === 'cpi' ? 'CPI' : 'Stała';
      modelParamsEl.textContent =
        `CIT: ${formatNumberEU(fullModelResult.citRate, 0)}% | ` +
        `Amortyzacja: ${systemSettings?.depreciationPeriod || 20} lat | ` +
        `Indeksacja: ${indexationLabel} | ` +
        `Życie projektu: ${fullModelResult.projectLifetime} lat`;
    }

    // ========== P50/P75/P90 SCENARIOS - CLIENT PERSPECTIVE ==========
    // In FIXED subscription model: ESCO IRR is constant (fixed revenue)
    // But CLIENT sees different value depending on actual production:
    // - Lower production = higher effective price per MWh
    // - Lower production = lower savings vs grid

    const p50Factor = systemSettings?.productionP50Factor || 1.00;
    const p75Factor = systemSettings?.productionP75Factor || 0.97;
    const p90Factor = systemSettings?.productionP90Factor || 0.94;

    // Update global production factors from settings
    window.productionFactors = {
      P50: p50Factor,
      P75: p75Factor,
      P90: p90Factor
    };

    // Update P-factor display in global selector buttons
    const btnP50 = document.getElementById('globalBtnP50');
    const btnP75 = document.getElementById('globalBtnP75');
    const btnP90 = document.getElementById('globalBtnP90');
    if (btnP50) btnP50.innerHTML = `P50 <span style="font-size:10px;opacity:0.9">(${decimalToPct(p50Factor).toFixed(0)}%)</span>`;
    if (btnP75) btnP75.innerHTML = `P75 <span style="font-size:10px;opacity:0.9">(${decimalToPct(p75Factor).toFixed(0)}%)</span>`;
    if (btnP90) btnP90.innerHTML = `P90 <span style="font-size:10px;opacity:0.9">(${decimalToPct(p90Factor).toFixed(0)}%)</span>`;

    // Annual subscription (fixed for all scenarios)
    const annualSubscriptionPLN = fullModelResult.annualSubscriptionPLN || fullModelResult.annualSubscription;

    // Grid price for comparison (PLN/MWh) - use weighted price for hybrid monthly
    let gridPricePLN = calculateTotalEnergyPrice(params);
    const hybridGridPrice = computeWeightedEnergyPrice(params);
    if (hybridGridPrice) gridPricePLN = hybridGridPrice.weightedTotal;

    // Calculate metrics for each scenario
    const scenarios = {
      P50: {
        factor: p50Factor,
        energyMWh: annualEnergyMWh * p50Factor,
        pricePLN: annualEnergyMWh * p50Factor > 0 ? annualSubscriptionPLN / (annualEnergyMWh * p50Factor) : 0,
      },
      P75: {
        factor: p75Factor,
        energyMWh: annualEnergyMWh * p75Factor,
        pricePLN: annualEnergyMWh * p75Factor > 0 ? annualSubscriptionPLN / (annualEnergyMWh * p75Factor) : 0,
      },
      P90: {
        factor: p90Factor,
        energyMWh: annualEnergyMWh * p90Factor,
        pricePLN: annualEnergyMWh * p90Factor > 0 ? annualSubscriptionPLN / (annualEnergyMWh * p90Factor) : 0,
      }
    };

    // Add derived metrics
    Object.keys(scenarios).forEach(key => {
      const s = scenarios[key];
      s.savingsPerMWh = gridPricePLN - s.pricePLN;           // PLN/MWh saved vs grid
      s.annualSavings = s.energyMWh * s.savingsPerMWh;       // PLN/year total savings
      s.savingsPercent = gridPricePLN > 0 ? decimalToPct(s.savingsPerMWh / gridPricePLN) : 0;
    });

    console.log('Production scenarios (client perspective):', {
      gridPricePLN,
      annualSubscriptionPLN,
      scenarios
    });

    // Store scenarios globally for button handlers
    window.eaasScenarios = scenarios;
    window.eaasGridPrice = gridPricePLN;
    window.eaasSubscription = annualSubscriptionPLN;
    window.currentProductionScenario = window.currentProductionScenario || 'P50';

    // Update production scenarios display (buttons are in HTML, only update metrics here)
    // Trigger selectProductionScenario to update the metrics display with current scenario
    const currentScenario = window.currentProductionScenario || 'P50';

    // Store ESCO IRR for display
    window.eaasEscoIrr = fullModelResult.projectIrr;

    // Store full investor model for database save
    window.lastFullModelResult = fullModelResult;

    // NOTE: selectProductionScenario is called AFTER formatEaaSResults below,
    // because formatEaaSResults creates eaasVal_* elements via innerHTML
    console.log('📊 Production scenarios initialized - current:', currentScenario);

    // Add residual value info
    const residualEl = document.getElementById('eaasResidualValue');
    if (residualEl) {
      residualEl.innerHTML = `
        <div style="font-size:12px;color:#666">
          <span style="font-weight:600">Wartość rezydualna:</span>
          ${(fullModelResult.residualValue || variant.capacity).toLocaleString('pl-PL')} PLN
          <span style="color:#888">(1 PLN/kWp - wykup przez klienta)</span>
        </div>
      `;
    }
  }

  // ========== USE FULL MODEL RESULTS FOR CONSISTENCY ==========
  // Always use fullModelResult for subscription to ensure consistency between
  // displayed "Roczny abonament" and table "Koszt EaaS"
  // Backend solver uses different methodology (simplified, no energy revenue),
  // which caused discrepancies (e.g., 490k vs 687k)
  const subscriptionData = {
    annualSubscription: fullModelResult.annualSubscriptionPLN,
    annualSubscriptionPLN: fullModelResult.annualSubscriptionPLN,
    monthlySubscription: fullModelResult.annualSubscriptionPLN / 12,
    irr: fullModelResult.projectIrr,
    duration: fullModelResult.contractDuration,
    currency: fullModelResult.currency,
  };

  console.log('📊 Using fullModelResult for subscriptionData:', {
    annualSubscriptionPLN: subscriptionData.annualSubscriptionPLN,
    duration: subscriptionData.duration,
    irr: subscriptionData.irr
  });

  // Optionally fetch backend log for detailed CSV export (but don't use its subscription value)
  try {
    const backendEaas = await fetchEaasMonthlyLog(variant, systemSettings || {}, params);
    const dl = document.getElementById('eaasLogDownload');
    if (dl && backendEaas.log_csv) {
      const blob = new Blob([backendEaas.log_csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      dl.href = url;
      dl.download = `eaas_log_${currentVariant}.csv`;
      dl.style.display = 'inline-block';
    }
    // Log discrepancy if any (for debugging)
    if (Math.abs(backendEaas.subscription_annual_year1 - fullModelResult.annualSubscriptionPLN) > 1000) {
      console.warn('⚠️ Backend subscription differs from fullModel:', {
        backend: backendEaas.subscription_annual_year1,
        fullModel: fullModelResult.annualSubscriptionPLN,
        diff: backendEaas.subscription_annual_year1 - fullModelResult.annualSubscriptionPLN
      });
    }
  } catch (err) {
    console.log('Backend EaaS log not available (optional):', err.message);
  }

  const eaasSubscriptionPLN = subscriptionData.annualSubscriptionPLN;
  const eaasOM = params.opex_per_kwp || (systemSettings?.opexPerKwp || 15);
  const eaasDuration = fullModelResult.contractDuration;

  const centralizedCalc = calculateCentralizedFinancialMetrics(variant, params, {
    subscription: eaasSubscriptionPLN,
    duration: eaasDuration,
    omPerKwp: eaasOM,
  });

  centralizedMetrics[currentVariant] = centralizedCalc;

  console.log('CENTRALIZED METRICS stored:', centralizedCalc);
  console.log('  - CAPEX NPV:', plnToMlnPln(centralizedCalc.capex.npv).toFixed(2), 'mln PLN');
  console.log('  - EaaS NPV:', plnToMlnPln(centralizedCalc.eaas?.npv || 0).toFixed(2), 'mln PLN');

  // K-class warning banner
  const kclassBanner = document.getElementById('kclassWarningBanner');
  if (kclassBanner) {
    if (centralizedCalc.common.hasKClassData) {
      const kBase = centralizedCalc.common.kClassBaseline || '?';
      const kPV = centralizedCalc.common.kClassWithPV || '?';
      const kBESS = centralizedCalc.common.kClassWithPVBess;
      const savPV = Math.round(centralizedCalc.common.capacityFeeSavingsPV || 0).toLocaleString('pl-PL');
      const savBESS = Math.round(centralizedCalc.common.capacityFeeSavingsBESS || 0).toLocaleString('pl-PL');
      kclassBanner.style.display = 'block';
      kclassBanner.style.background = '#1a3a1a';
      kclassBanner.style.borderColor = '#4caf50';
      kclassBanner.innerHTML = `<b>K-class:</b> ${kBase} &rarr; ${kPV}${kBESS ? ' &rarr; ' + kBESS : ''} | Oszcz. opl. mocowa: PV: ${savPV} PLN${kBESS ? ', BESS: ' + savBESS + ' PLN' : ''}`;
    } else {
      kclassBanner.style.display = 'block';
      kclassBanner.style.background = '#3a2a0a';
      kclassBanner.style.borderColor = '#ff9800';
      kclassBanner.innerHTML = 'Brak danych K-class — obliczenia z ryczaltowa oplata mocowa (' + (params.capacity_fee || 219) + ' PLN/MWh). Uruchom analiz\u0119 PV dla dokladnych oblicze\u0144.';
    }
  }

  const annualConsumption = getAnnualConsumptionKwh();
  const currentScenario = window.currentProductionScenario || 'P50';
  const eaasScenarioFactor = (window.productionFactors && window.productionFactors[currentScenario] !== undefined)
    ? window.productionFactors[currentScenario]
    : (window.currentScenarioFactor || 1.0);
  const eaasParams = {
    annualConsumptionKWh: annualConsumption,
    annualPVProductionKWh: variant.production * eaasScenarioFactor,
    selfConsumptionRatio: variant.self_consumed / variant.production,
    pvPowerKWp: variant.capacity,
    pvCapexPLN: variant.capacity * getCapexForCapacity(variant.capacity),
    eaasSubscriptionPLNperYear: eaasSubscriptionPLN,
    omCostPerKWp: eaasOM,
    tariffComponents: {
      energyActive: params.energy_active,
      distribution: params.distribution,
      quality: params.quality_fee,
      oze: params.oze_fee,
      cogeneration: params.cogeneration_fee,
      capacity: params.capacity_fee,
      excise: params.excise_tax,
    },
  };

  const result = calculateEaaSFinancialMetrics(eaasParams);

  const resultsDiv = document.getElementById('eaasResults');
  if (resultsDiv) {
    resultsDiv.innerHTML = formatEaaSResults(result);
  }

  // Re-apply scenario after formatEaaSResults (innerHTML destroys and recreates eaasVal_* elements)
  selectProductionScenario(currentScenario);

  generateEaaSYearlyTable(eaasParams, result);

  const eaasSection = document.getElementById('eaasSection');
  if (eaasSection) {
    eaasSection.style.display = 'block';
  }

  console.log('EaaS analysis completed:', result);

  // ========== NEW: EaaS + BESS SYNERGY SECTION ==========
  // Ensure savings_breakdown exists (generate locally if needed for pv-calculation source)
  ensureSavingsBreakdown(variant);
  // Calculate and display extended metrics with BESS savings (arbitrage, peak-shaving, capacity fee)
  displayEaasBessSynergy(variant, eaasSubscriptionPLN, annualEnergyMWh, params);

  // Initialize Bankability metrics after EaaS calculation
  if (typeof initializeBankability === 'function') {
    setTimeout(() => {
      initializeBankability();
    }, 100);
  }

  await calculateOptimization();
}
async function calculateOptimization() {
  console.log('🎯 Calculating optimization analysis...');

  // Use actual variant keys from variants object instead of hardcoded A, B, C, D
  const variantKeys = Object.keys(variants);
  console.log('  - Available variant keys:', variantKeys);

  if (variantKeys.length === 0) {
    console.log('❌ No variants available for optimization');
    const capexPanel = document.getElementById('capexOptimizationResults');
    const eaasPanel = document.getElementById('eaasOptimizationResults');
    if (capexPanel) capexPanel.innerHTML = '<p style="color:#666;font-size:13px">Brak wariantów do analizy</p>';
    if (eaasPanel) eaasPanel.innerHTML = '<p style="color:#666;font-size:13px">Brak wariantów do analizy</p>';
    return;
  }

  const params = getEconomicParameters();
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value) || 24;
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || 10;

  const results = [];

  // ========== FETCH PRECISE SAVINGS FOR ALL VARIANTS (parallel) ==========
  // Each variant needs its own backend call with variant-specific PV profile
  const hasBessAny = Object.values(variants).some(v => v?.bess_power_kw > 0 && v?.bess_energy_kwh > 0);
  if (!hasBessAny) {
    const fetchPromises = variantKeys.map(key => {
      const v = variants[key];
      if (!v) return Promise.resolve(null);
      // Ensure variant has its key for cache lookup
      const variantWithKey = { ...v, variant: key };
      return fetchPreciseAnnualSavings(variantWithKey);
    });
    await Promise.all(fetchPromises);
    console.log(`📊 Precise savings fetched for all variants: ${Object.keys(preciseAnnualSavingsCache).join(', ')}`);
  }

  // ========== CALCULATE CENTRALIZED METRICS FOR ALL VARIANTS ==========
  // This ensures we have consistent calculations for all variants
  for (const key of variantKeys) {
    const variant = variants[key];
    if (!variant) continue;

    // Set preciseAnnualSavings to this variant's cached data before calculating
    const hasFreshPrecise = !!preciseAnnualSavingsCache[key];
    if (hasFreshPrecise) {
      preciseAnnualSavings = preciseAnnualSavingsCache[key];
      window.preciseAnnualSavings = preciseAnnualSavings;
    }

    // Recalculate if: (a) not yet computed, or (b) PRECISE data freshly available but existing calc lacks it
    const existingCalcHasPrecise = centralizedMetrics[key]?.common?.hasPreciseSavings;
    const needsRecalc = !centralizedMetrics[key] || (hasFreshPrecise && !existingCalcHasPrecise);
    if (needsRecalc) {
      console.log(`📊 Calculating centralized metrics for variant ${key}...`);

      // For the CURRENT variant, use FULL MODEL subscription (from window.eaasSubscription)
      // to stay consistent with the portal display. For other variants, use simple model.
      let subscriptionPLN;
      if (key === currentVariant && window.eaasSubscription > 0) {
        subscriptionPLN = window.eaasSubscription; // Full model, always PLN
        console.log(`  → Using FULL MODEL subscription for current variant ${key}: ${subscriptionPLN.toFixed(0)} PLN/yr`);
      } else {
        const subscriptionData = calculateEaasSubscription(
          variant.capacity,
          systemSettings || {},
          params,
          variant  // Include variant for BESS data
        );
        // FIX: Always use PLN value (annualSubscription is in contract currency = EUR)
        subscriptionPLN = subscriptionData.annualSubscriptionPLN;
        console.log(`  → Using simple model subscription for variant ${key}: ${subscriptionPLN.toFixed(0)} PLN/yr`);
      }

      // Calculate and store centralized metrics
      centralizedMetrics[key] = calculateCentralizedFinancialMetrics(variant, params, {
        subscription: subscriptionPLN,
        duration: eaasDuration,
        omPerKwp: eaasOM
      });
    }
  }

  // ========== BUILD RESULTS FROM CENTRALIZED METRICS ==========
  for (const key of variantKeys) {
    const variant = variants[key];
    if (!variant || !centralizedMetrics[key]) continue;

    const centralizedCalc = centralizedMetrics[key];
    const autoconsumptionRatio = variant.self_consumed / variant.production;

    // ========== READ FROM CENTRALIZED METRICS (SINGLE SOURCE OF TRUTH) ==========
    const capexNPV = centralizedCalc.capex.npv;
    const capexIRR = centralizedCalc.capex.irr;
    const eaasNPV = centralizedCalc.eaas ? centralizedCalc.eaas.npv : 0;

    console.log(`📊 OPTIMIZATION - Variant ${key}:`);
    console.log(`   CAPEX NPV = ${plnToMlnPln(capexNPV).toFixed(2)} mln PLN`);
    console.log(`   EaaS NPV = ${plnToMlnPln(eaasNPV).toFixed(2)} mln PLN`);

    results.push({
      key: key,
      capacity: centralizedCalc.common.capacityKwp,
      autoconsumptionRatio: autoconsumptionRatio * 100,
      capexNPV: capexNPV,
      capexIRR: capexIRR,
      eaasNPV: eaasNPV,
      // Composite score: normalized NPV * autoconsumption ratio
      capexScore: plnToMlnPln(capexNPV) * autoconsumptionRatio,
      eaasScore: plnToMlnPln(eaasNPV) * autoconsumptionRatio
    });
  }

  // ========== SAVE KPI DATA FOR SCORING MODULE ==========
  // Store full economic KPIs for all variants so scoring module can access them
  const scoringKpiData = {};
  for (const key of variantKeys) {
    const variant = variants[key];
    const calc = centralizedMetrics[key];
    if (!variant || !calc) continue;

    scoringKpiData[key] = {
      // Basic info
      capacity_kwp: calc.common.capacityKwp,
      // Economic KPIs (from centralized calculation)
      npv_pln: calc.capex?.npv || 0,
      payback_years: calc.capex?.simplePayback || 25,
      irr_pct: calc.capex?.irr ? calc.capex.irr * 100 : null,
      lcoe_pln_mwh: calc.capex?.lcoe ? calc.capex.lcoe * 1000 : null, // kWh -> MWh
      // Production/consumption metrics
      annual_production_kwh: variant.production || 0,
      self_consumed_kwh: variant.self_consumed || 0,
      exported_kwh: variant.exported || 0,
      annual_consumption_kwh: calc.common?.annualConsumptionKwh || getAnnualConsumptionKwh(),
      // Auto-calculated ratios
      auto_consumption_pct: variant.production > 0 ? (variant.self_consumed / variant.production) : 0,
      coverage_pct: calc.common?.annualConsumptionKwh > 0 ? (variant.self_consumed / calc.common.annualConsumptionKwh) : 0,
      // ESG
      co2_reduction_tons: variant.self_consumed ? (variant.self_consumed * 0.7) / 1000 : 0
    };
  }
  try {
    localStorage.setItem('scoringKpiData', JSON.stringify(scoringKpiData));
    console.log('📊 Scoring KPI data saved for', Object.keys(scoringKpiData).length, 'variants');
  } catch (e) {
    console.warn('⚠️ Could not save scoring KPI data:', e.message);
  }

  if (results.length === 0) {
    console.log('❌ No variants available for optimization');
    return;
  }

  // Find best variants
  const bestCapexNPV = results.reduce((a, b) => a.capexNPV > b.capexNPV ? a : b);
  const bestEaasNPV = results.reduce((a, b) => a.eaasNPV > b.eaasNPV ? a : b);
  const bestAutoconsumption = results.reduce((a, b) => a.autoconsumptionRatio > b.autoconsumptionRatio ? a : b);
  const bestCapexScore = results.reduce((a, b) => a.capexScore > b.capexScore ? a : b);
  const bestEaasScore = results.reduce((a, b) => a.eaasScore > b.eaasScore ? a : b);

  // Check if we have single variant (NPV strategy)
  const isSingleVariant = results.length === 1;

  // Update CAPEX optimization panel
  const capexPanel = document.getElementById('capexOptimizationResults');
  if (capexPanel) {
    if (isSingleVariant) {
      const r = results[0];
      capexPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>📈 Optymalna instalacja:</strong> ${r.capacity} kWp</div>
          <div style="margin-left:20px;color:#1565c0">NPV: ${plnToMlnPln(r.capexNPV).toFixed(2)} mln PLN</div>
          <div style="margin-left:20px;color:#1565c0">IRR: ${decimalToPct(r.capexIRR).toFixed(1)}%</div>
          <div style="margin-left:20px;color:#1565c0">Autokonsumpcja: ${r.autoconsumptionRatio.toFixed(1)}%</div>
        </div>
      `;
    } else {
      capexPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>🏆 Najlepszy NPV:</strong> Wariant ${bestCapexNPV.key} (${bestCapexNPV.capacity} kWp)</div>
          <div style="margin-left:20px;color:#1565c0">NPV: ${plnToMlnPln(bestCapexNPV.capexNPV).toFixed(2)} mln PLN, IRR: ${decimalToPct(bestCapexNPV.capexIRR).toFixed(1)}%</div>
          <div style="margin-top:8px"><strong>⚡ Najlepsza autokons.:</strong> Wariant ${bestAutoconsumption.key} (${bestAutoconsumption.capacity} kWp)</div>
          <div style="margin-left:20px;color:#1565c0">Autokonsumpcja: ${bestAutoconsumption.autoconsumptionRatio.toFixed(1)}%</div>
          <div style="margin-top:8px"><strong>🎯 Kompromis:</strong> Wariant ${bestCapexScore.key} (${bestCapexScore.capacity} kWp)</div>
          <div style="margin-left:20px;color:#1565c0">Score: ${bestCapexScore.capexScore.toFixed(2)}</div>
        </div>
      `;
    }
  }

  // Update EaaS optimization panel
  const eaasPanel = document.getElementById('eaasOptimizationResults');
  if (eaasPanel) {
    if (isSingleVariant) {
      const r = results[0];
      eaasPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>📈 Optymalna instalacja:</strong> ${r.capacity} kWp</div>
          <div style="margin-left:20px;color:#e65100">NPV: ${plnToMlnPln(r.eaasNPV).toFixed(2)} mln PLN</div>
          <div style="margin-left:20px;color:#e65100">Autokonsumpcja: ${r.autoconsumptionRatio.toFixed(1)}%</div>
        </div>
      `;
    } else {
      eaasPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>🏆 Najlepszy NPV:</strong> Wariant ${bestEaasNPV.key} (${bestEaasNPV.capacity} kWp)</div>
          <div style="margin-left:20px;color:#e65100">NPV: ${plnToMlnPln(bestEaasNPV.eaasNPV).toFixed(2)} mln PLN</div>
          <div style="margin-top:8px"><strong>⚡ Najlepsza autokons.:</strong> Wariant ${bestAutoconsumption.key} (${bestAutoconsumption.capacity} kWp)</div>
          <div style="margin-left:20px;color:#e65100">Autokonsumpcja: ${bestAutoconsumption.autoconsumptionRatio.toFixed(1)}%</div>
          <div style="margin-top:8px"><strong>🎯 Kompromis:</strong> Wariant ${bestEaasScore.key} (${bestEaasScore.capacity} kWp)</div>
          <div style="margin-left:20px;color:#e65100">Score: ${bestEaasScore.eaasScore.toFixed(2)}</div>
        </div>
      `;
    }
  }

  // Update comparison table
  const tableBody = document.getElementById('optimizationTableBody');
  if (tableBody) {
    tableBody.innerHTML = '';

    for (const r of results) {
      const row = document.createElement('tr');

      // Determine badges
      let badges = [];
      if (r.key === bestCapexNPV.key || r.key === bestEaasNPV.key) badges.push('🏆');
      if (r.key === bestAutoconsumption.key) badges.push('⚡');
      if (r.key === bestCapexScore.key || r.key === bestEaasScore.key) badges.push('🎯');

      // Determine better model
      const betterModel = r.capexNPV > r.eaasNPV ? 'CAPEX' : 'EaaS';
      const modelColor = betterModel === 'CAPEX' ? '#1565c0' : '#e65100';

      row.innerHTML = `
        <td style="text-align:center">${r.key} ${badges.join('')}</td>
        <td>${formatNumberEU(r.capacity, 0)}</td>
        <td>${formatNumberEU(r.autoconsumptionRatio, 1)}</td>
        <td class="${r.capexNPV >= 0 ? 'positive' : 'negative'}">${formatNumberEU(plnToMlnPln(r.capexNPV), 2)}</td>
        <td>${formatNumberEU(r.capexIRR * 100, 1)}</td>
        <td class="${r.eaasNPV >= 0 ? 'positive' : 'negative'}">${formatNumberEU(plnToMlnPln(r.eaasNPV), 2)}</td>
        <td style="color:${modelColor};font-weight:600">${betterModel}</td>
      `;

      tableBody.appendChild(row);
    }
  }

  // If current variant was recalculated with fresh PRECISE data, re-render tables
  if (preciseAnnualSavingsCache[currentVariant] && centralizedMetrics[currentVariant]?.common?.hasPreciseSavings) {
    console.log('🔄 Re-rendering EaaS/CAPEX tables with PRECISE data for variant', currentVariant);
    // Re-render EaaS yearly table
    const variant = variants[currentVariant];
    if (variant) {
      const p = getEconomicParameters();
      const r = calculateEaaSFinancialMetrics({
        annualConsumptionKWh: getAnnualConsumptionKwh(),
        annualPVProductionKWh: variant.production * (window.currentScenarioFactor || 1.0),
        selfConsumptionRatio: variant.self_consumed / variant.production,
        pvPowerKWp: variant.capacity,
        pvCapexPLN: variant.capacity * getCapexForCapacity(variant.capacity),
        eaasSubscriptionPLNperYear: window.eaasSubscription || 800000,
        omCostPerKWp: p.opex_per_kwp || (systemSettings?.opexPerKwp || 15),
        tariffComponents: { energyActive: p.energy_active, distribution: p.distribution, quality: p.quality_fee, oze: p.oze_fee, cogeneration: p.cogeneration_fee, capacity: p.capacity_fee, excise: p.excise_tax }
      });
      if (!r.error) generateEaaSYearlyTable(p, r);
      // Re-render CAPEX payback table
      const economicData = window._lastEconomicData;
      if (economicData) {
        generatePaybackTable(economicData, variant.capacity, p);
      }
    }
  }

  console.log('✅ Optimization analysis completed');
}

/**
 * Simple IRR calculation using Newton-Raphson method
 * NOTE: This is a duplicate function definition - the first one at line ~106 is used primarily
 */


/**
 * Generate EaaS year-by-year table with NPV calculation
 * Two phases: EaaS contract period and ownership period
 *
 * UPDATED: Now uses CENTRALIZED CALCULATIONS from centralizedMetrics
 */
function generateEaaSYearlyTable(params, result) {
  const tableBody = document.getElementById('eaasYearlyTableBody');
  if (!tableBody || result.error) return;

  tableBody.innerHTML = '';

  // ========== USE CENTRALIZED CALCULATIONS ==========
  // Read from the SINGLE SOURCE OF TRUTH
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc || !centralizedCalc.eaas) {
    console.warn('⚠️ No centralized EaaS metrics available for table generation');
    return;
  }

  const eaasCashFlows = centralizedCalc.eaas.cashFlows;
  const discountRate = centralizedCalc.common.discountRate;
  const eaasDuration = centralizedCalc.eaas.duration;
  const analysisPeriod = centralizedCalc.common.analysisPeriod;

  let cumulativeNPV = 0;
  let eaasPhaseSavings = 0;
  let ownershipPhaseSavings = 0;

  // Get total energy price and annual consumption for calculations
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice;
  const inflationRate = centralizedCalc.common.inflationRate;

  // A. Energia z sieci = całkowite zużycie zakładu (bez PV musiałby pobrać całość z sieci)
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = kwhToMwh(annualConsumptionKwh);

  // ========== POPULATE eaasYearlyData for Bankability ==========
  // This data is used by initializeBankability() for DSCR/CCR calculations
  eaasYearlyData = eaasCashFlows.map(yearData => ({
    rok: yearData.year,
    year: yearData.year,
    // Revenue = grid cost equivalent (what client saves by using PV)
    savings: yearData.gridCost || 0,
    oszczednosc: yearData.gridCost || 0,
    revenue: yearData.gridCost || 0,
    // OPEX = EaaS cost (subscription) or O&M in ownership phase
    koszt: yearData.eaasCost || 0,
    oAndM: yearData.eaasCost || 0,
    opex: yearData.eaasCost || 0,
    // Additional fields for Bankability
    phase: yearData.phase,
    selfConsumedMwh: kwhToMwh(yearData.selfConsumed || 0),
    gridCost: yearData.gridCost || 0,
    eaasCost: yearData.eaasCost || 0,
    netSavings: yearData.savings || 0
  }));
  console.log('📊 eaasYearlyData populated with', eaasYearlyData.length, 'years for Bankability');

  for (const yearData of eaasCashFlows) {
    const year = yearData.year;
    // Use selfConsumed directly from cashFlows (already includes degradation) - in kWh
    const autoconsumptionKwh = yearData.selfConsumed || 0;
    const autoconsumptionMwh = kwhToMwh(autoconsumptionKwh);
    const gridCost = yearData.gridCost;
    const eaasCost = yearData.eaasCost;
    const savings = yearData.savings;
    const discountedCF = yearData.discountedCF;
    const phase = yearData.phase;

    // Calculate grid energy for this year (total consumption - stays constant, no degradation on demand side)
    const gridEnergyMwh = annualConsumptionMwh;

    // Calculate grid cost (full consumption at grid price with inflation)
    const inflationFactor = Math.pow(1 + inflationRate, year - 1);
    const yearGridCostFull = gridEnergyMwh * totalEnergyPrice * inflationFactor;

    cumulativeNPV += discountedCF;

    // Track phase savings
    if (phase === 'eaas') {
      eaasPhaseSavings += savings;
    } else {
      ownershipPhaseSavings += savings;
    }

    const row = document.createElement('tr');

    // Color coding based on phase
    if (phase === 'eaas') {
      row.style.background = '#fff8e1'; // Light yellow for EaaS phase
    } else {
      row.style.background = '#e8f5e9'; // Light green for ownership phase
    }

    // Special styling for transition year
    if (year === eaasDuration) {
      row.style.borderBottom = '3px solid #f57c00';
    }
    if (year === eaasDuration + 1) {
      row.style.borderTop = '3px solid #4caf50';
    }

    const savingsClass = savings >= 0 ? 'positive' : 'negative';
    const npvClass = cumulativeNPV >= 0 ? 'positive' : 'negative';

    // Phase indicator
    const phaseLabel = phase === 'eaas' ? '📋' : '🏠';

    // Kolumny:
    // A. Zużycie (MWh) - całkowite zużycie zakładu
    // B. Koszt BEZ PV (tys. PLN) - koszt całego zużycia z sieci (gdyby nie było PV)
    // C. Auto PV (MWh) - bezpośrednia autokonsumpcja z PV
    // D. Auto BESS (MWh) - autokonsumpcja z baterii
    // E. Suma Auto (MWh) - całkowita autokonsumpcja
    // F. Koszt Z PV (tys. PLN) - faktyczny koszt importu z sieci po odjęciu autokonsumpcji
    // G. Oszczędn. PV (tys. PLN) - wartość autokonsumpcji w cenach sieci
    // H. Koszt EaaS (tys. PLN) - koszt abonamentu EaaS
    // I. Oszczędn. (tys. PLN) - Oszczędności PV minus Koszt EaaS
    // J. NPV (mln PLN) - skumulowany NPV

    // Breakdown autokonsumpcji
    const pvDirectMwh = kwhToMwh(yearData.selfConsumedPvDirect || 0); // kWh → MWh
    const bessMwh = kwhToMwh(yearData.selfConsumedBess || 0); // kWh → MWh

    // Degradation percentages (from cashFlows)
    const pvDegPct = yearData.pvDegradationPct || 100;
    const bessDegPct = yearData.bessDegradationPct || 100;

    // Oszczędność PV = autokonsumpcja × cena sieci (to jest gridCost z cash flows)
    const pvSavings = gridCost; // yearData.gridCost already = autoconsumption × price with inflation
    // Koszt Z PV = koszt BEZ PV minus oszczędności PV (faktyczny koszt importu z sieci)
    const gridCostWithPv = yearGridCostFull - pvSavings;

    row.innerHTML = `
      <td>${phaseLabel} ${year}</td>
      <td>${formatNumberEU(pvDegPct, 1)}</td>
      <td>${formatNumberEU(bessDegPct, 1)}</td>
      <td>${formatNumberEU(gridEnergyMwh, 1)}</td>
      <td>${formatNumberEU(plnToTysPln(yearGridCostFull), 0)}</td>
      <td>${formatNumberEU(pvDirectMwh, 1)}</td>
      <td>${formatNumberEU(bessMwh, 1)}</td>
      <td>${formatNumberEU(autoconsumptionMwh, 1)}</td>
      <td>${formatNumberEU(plnToTysPln(gridCostWithPv), 0)}</td>
      <td>${formatNumberEU(plnToTysPln(pvSavings), 0)}</td>
      <td>${formatNumberEU(plnToTysPln(eaasCost), 0)}</td>
      <td class="${savingsClass}">${formatNumberEU(plnToTysPln(savings), 0)}</td>
      <td class="${npvClass}">${formatNumberEU(plnToMlnPln(cumulativeNPV), 2)}</td>
    `;

    tableBody.appendChild(row);
  }

  // Add EaaS phase summary row
  const eaasSummaryRow = document.createElement('tr');
  eaasSummaryRow.style.background = '#fff3e0';
  eaasSummaryRow.style.fontWeight = '600';
  eaasSummaryRow.style.borderTop = '2px solid #f57c00';

  eaasSummaryRow.innerHTML = `
    <td colspan="10" style="text-align:right;color:#f57c00">📋 Suma oszczędności w fazie EaaS (lata 1-${eaasDuration}):</td>
    <td class="positive" style="color:#f57c00">${formatNumberEU(plnToTysPln(eaasPhaseSavings), 0)}</td>
    <td style="text-align:left;font-size:11px;color:#666">&nbsp;tys. PLN</td>
  `;
  tableBody.appendChild(eaasSummaryRow);

  // Add ownership phase summary row
  const ownershipSummaryRow = document.createElement('tr');
  ownershipSummaryRow.style.background = '#e8f5e9';
  ownershipSummaryRow.style.fontWeight = '600';

  ownershipSummaryRow.innerHTML = `
    <td colspan="10" style="text-align:right;color:#4caf50">🏠 Suma oszczędności w fazie własności (lata ${eaasDuration + 1}-${analysisPeriod}):</td>
    <td class="positive" style="color:#4caf50">${formatNumberEU(plnToTysPln(ownershipPhaseSavings), 0)}</td>
    <td style="text-align:left;font-size:11px;color:#666">&nbsp;tys. PLN</td>
  `;
  tableBody.appendChild(ownershipSummaryRow);

  // Add total summary row
  const totalSummaryRow = document.createElement('tr');
  totalSummaryRow.style.background = '#f5f5f5';
  totalSummaryRow.style.fontWeight = '700';
  totalSummaryRow.style.borderTop = '3px solid #27ae60';

  const npvClass = cumulativeNPV >= 0 ? 'positive' : 'negative';
  const totalSavings = eaasPhaseSavings + ownershipPhaseSavings;

  totalSummaryRow.innerHTML = `
    <td colspan="10" style="text-align:right">💰 SUMA CAŁKOWITA (25 lat) / NPV (${formatNumberEU(decimalToPct(discountRate), 0)}%):</td>
    <td class="positive">${formatNumberEU(plnToTysPln(totalSavings), 0)}</td>
    <td class="${npvClass}">${formatNumberEU(plnToMlnPln(cumulativeNPV), 2)}</td>
  `;
  tableBody.appendChild(totalSummaryRow);

  console.log('✅ EaaS yearly table generated. EaaS phase:', plnToTysPln(eaasPhaseSavings).toFixed(0), 'tys. PLN, Ownership phase:', plnToTysPln(ownershipPhaseSavings).toFixed(0), 'tys. PLN, NPV:', plnToMlnPln(cumulativeNPV).toFixed(2), 'mln PLN');

  // Send economics data to shell for Reports module
  // Use JSON.parse/stringify to ensure clean data without DOM references

  // Build fullInvestorModel data from lastFullModelResult if available
  let fullInvestorModelData = null;
  if (window.lastFullModelResult) {
    const fm = window.lastFullModelResult;
    fullInvestorModelData = {
      // EaaS Client (abonament)
      subscriptionAnnual: fm.annualSubscriptionPLN || null,
      subscriptionMonthly: fm.annualSubscriptionPLN ? fm.annualSubscriptionPLN / 12 : null,
      pricePerMwh: fm.pricePerMWh || null,
      // IRR metrics
      targetIrr: fm.targetIrr || null,
      projectIrr: fm.projectIrr || null,
      equityIrr: fm.equityIrr || null,
      irrDriver: fm.irrDriver || null,
      // Capital structure
      capexPln: fm.totalCapexPLN || null,
      debtPln: fm.debtAmount || null,
      equityPln: fm.equityAmount || null,
      leveragePct: fm.leverageRatio || null,
      // Contract financials
      contractRevenuePln: fm.totalRevenue || null,
      contractOpexPln: fm.totalOpex || null,
      contractTaxPln: fm.totalTax || null,
      contractInterestPln: fm.totalInterest || null,
      // Model parameters
      citRatePct: fm.citRate || null,
      depreciationYears: 15,
      indexationType: fm.indexationType || null,
      projectLifeYears: fm.projectLifetime || null,
      // Residual value
      residualValuePln: fm.residualValue || null,
      residualPerKwp: 1
    };
    console.log('📊 Adding fullInvestorModel to ECONOMICS_CALCULATED:', {
      projectIrr: fullInvestorModelData.projectIrr,
      subscriptionAnnual: fullInvestorModelData.subscriptionAnnual
    });
  }

  const economicsData = {
    variantKey: currentVariant,
    eaasDuration: eaasDuration,
    analysisPeriod: analysisPeriod,
    eaasPhaseSavings: eaasPhaseSavings,
    ownershipPhaseSavings: ownershipPhaseSavings,
    totalSavings: totalSavings,
    cumulativeNPV: cumulativeNPV,
    discountRate: discountRate,
    cashFlows: JSON.parse(JSON.stringify(eaasCashFlows)),
    // CAPEX data from centralizedMetrics
    capexInvestment: centralizedCalc.capex?.investment || 0,
    capexCashFlows: centralizedCalc.capex?.cashFlows || [],
    capexNPV: centralizedCalc.capex?.npv || 0,
    capexIRR: centralizedCalc.capex?.irr || 0,
    capexPayback: centralizedCalc.capex?.simplePayback || 0,
    irrMode: systemSettings?.irrMode || 'real',
    // Common parameters
    totalEnergyPrice: centralizedCalc.common?.totalEnergyPrice || 0,
    inflationRate: centralizedCalc.common?.inflationRate || 0,
    // Full Investor Model (for database persistence)
    fullInvestorModel: fullInvestorModelData
  };

  try {
    window.parent.postMessage({
      type: 'ECONOMICS_CALCULATED',
      data: JSON.parse(JSON.stringify(economicsData))
    }, '*');
  } catch (e) {
    console.warn('⚠️ Could not send economics data to shell:', e.message);
  }
  console.log('📤 Economics data sent to shell:', economicsData);
}

/**
 * Get current BESS data from the active variant
 * @returns {object|null} BESS data with bess_power_kw and bess_energy_kwh, or null if no BESS
 */
function getCurrentBessData() {
  const variant = variants[currentVariant];
  if (!variant) return null;

  if (variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0) {
    return {
      bess_power_kw: variant.bess_power_kw,
      bess_energy_kwh: variant.bess_energy_kwh
    };
  }
  return null;
}

/**
 * Round number to specified decimal places (keeps as number for Excel)
 * @param {number} value - Number to round
 * @param {number} decimals - Number of decimal places
 * @returns {number} Rounded number
 */
function roundNum(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) return 0;
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

/**
 * Export EaaS analysis to Excel
 */
async function exportEaaSToExcel(withFormulas = false) {
  console.log('📥 exportEaaSToExcel() CALLED', { withFormulas, currentVariant, hasCentralizedMetrics: !!centralizedMetrics?.[currentVariant] });
  try {
  // Apply production scenario factor (P50/P75/P90) — productionFactors priorytet
  const scenarioName = window.currentProductionScenario || 'P50';
  const scenarioFactor = (window.productionFactors && window.productionFactors[scenarioName] !== undefined)
    ? window.productionFactors[scenarioName]
    : (window.currentScenarioFactor || 1.0);
  console.log(`📥 Exporting EaaS analysis to Excel (${scenarioName}, factor=${scenarioFactor})...`, withFormulas ? '(WITH FORMULAS)' : '(values only)');

  // Get variant data (same as calculateEaaS)
  const variant = variants[currentVariant];
  if (!variant) {
    alert('Brak danych EaaS do eksportu. Najpierw wykonaj analizę.');
    return;
  }

  // Get economic parameters
  const params = getEconomicParameters();

  // Get parameters
  const tariffComponents = {
    energyActive: params.energy_active,
    distribution: params.distribution,
    quality: params.quality_fee,
    oze: params.oze_fee,
    cogeneration: params.cogeneration_fee,
    capacity: params.capacity_fee,
    excise: params.excise_tax
  };

  // Use stored subscription from fullModelResult (set in window.eaasSubscription)
  const eaasSubscription = window.eaasSubscription || 800000;
  const eaasOM = params.opex_per_kwp || (systemSettings?.opexPerKwp || 15);
  const degradationRate = params.degradation_rate; // Already as fraction (e.g., 0.005 for 0.5%)
  const analysisPeriod = params.analysis_period;

  const capacityKwp = variant.capacity;
  const capex = capacityKwp * getCapexForCapacity(capacityKwp);
  const annualConsumption = getAnnualConsumptionKwh();

  // USE centralizedMetrics as single source of truth for autoconsumption
  // (consistent with portal display — includes scenario factor from analysis time)
  const autoconsumptionMwh = centralizedMetrics[currentVariant]?.common?.selfConsumedMwh ||
                              kwhToMwh(variant.self_consumed * scenarioFactor);

  // Calculate EaaS metrics (for Sheet 1 summary only - year-by-year uses centralizedMetrics)
  const eaasParams = {
    annualConsumptionKWh: annualConsumption,
    annualPVProductionKWh: variant.production * scenarioFactor,
    selfConsumptionRatio: variant.self_consumed / variant.production,
    pvPowerKWp: capacityKwp,
    pvCapexPLN: capex,
    eaasSubscriptionPLNperYear: eaasSubscription,
    omCostPerKWp: eaasOM,
    tariffComponents: tariffComponents
  };

  const result = calculateEaaSFinancialMetrics(eaasParams);

  if (result.error) {
    alert('Błąd podczas obliczania danych EaaS: ' + result.error);
    return;
  }

  // Grid price for year-by-year calculations (PLN/kWh)
  const gridPrice = result.metrics.gridPricePLNperKWh;

  // Create workbook
  const wb = XLSX.utils.book_new();

  // Get currency settings (needed for both sheets)
  const currency = systemSettings?.eaasCurrency || 'PLN';
  const fxPlnEur = systemSettings?.fxPlnEur || 4.5;

  // Get total annual consumption from uploaded file
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = kwhToMwh(annualConsumptionKwh);

  // Sheet 1: Summary (client-facing - no sensitive ESCO data)
  // Rows 1-3: Header area (logo + title merged A1:B3)
  // Currency conversion multiplier (1 for PLN, 1/fx for EUR)
  const currencyMultiplier = currency === 'EUR' ? 1 / fxPlnEur : 1;
  const currencyLabel = currency;
  // Currency info for display - separate label and value
  const currencyInfoLabel = currency === 'EUR' ? 'Waluta EUR:' : 'Waluta:';
  const currencyInfoValue = currency === 'EUR'
    ? `${fxPlnEur.toFixed(2).replace('.', ',')} PLN/EUR`
    : 'PLN';

  // Convert values to contract currency
  const eaasSubscriptionDisplay = eaasSubscription * currencyMultiplier;
  const gridPriceDisplay = result.metrics.gridPricePLNperKWh * 1000 * currencyMultiplier;
  const eaasPriceDisplay = result.metrics.eaasPricePLNperKWh * 1000 * currencyMultiplier;
  const priceDiffDisplay = result.metrics.priceDifferencePLNperKWh * 1000 * currencyMultiplier;
  const annualSavingsDisplay = plnToTysPln(result.metrics.annualSavingsPLN * currencyMultiplier);

  const summaryData = [
    [''],  // Row 1 - logo area
    [''],  // Row 2 - logo area
    [`ANALIZA EaaS${window._rdnExportMode ? ' (ceny RDN)' : ''} (Energy-as-a-Service) - Scenariusz ${scenarioName}`],  // Row 3 - title at bottom of merged area
    [''],
    ['DANE INSTALACJI'],
    ['Moc instalacji [kWp]:', roundNum(capacityKwp, 0)],
    ['Zużycie roczne zakładu [MWh]:', roundNum(annualConsumptionMwh, 1)],
    ['Autokonsumpcja PV [MWh]:', roundNum(autoconsumptionMwh, 1)],
    ['Pokrycie zużycia [%]:', roundNum((autoconsumptionMwh / annualConsumptionMwh) * 100, 1)],
    [''],
    ['PARAMETRY UMOWY EaaS'],
    [`Abonament EaaS [${currencyLabel}/rok]:`, roundNum(eaasSubscriptionDisplay, 0)],
    ['Okres analizy [lat]:', analysisPeriod],
    [currencyInfoLabel, currencyInfoValue],  // Currency info row with value in column C
    [''],
    ['SKŁADNIKI TARYFY [PLN/MWh]'],  // Tariff always in PLN (base costs)
    ['Energia czynna:', roundNum(tariffComponents.energyActive, 0)],
    ['Dystrybucja:', roundNum(tariffComponents.distribution, 0)],
    ['Opłata jakościowa:', roundNum(tariffComponents.quality, 0)],
    ['Opłata OZE:', roundNum(tariffComponents.oze, 0)],
    ['Opłata kogeneracyjna:', roundNum(tariffComponents.cogeneration, 0)],
    ['Opłata mocowa:', roundNum(tariffComponents.capacity, 0)],
    ['Akcyza:', roundNum(tariffComponents.excise, 0)],
    [''],
    ['KORZYŚCI DLA KLIENTA'],
    [`Cena energii z sieci [${currencyLabel}/MWh]:`, roundNum(gridPriceDisplay, 2)],
    [`Efektywna cena EaaS [${currencyLabel}/MWh]:`, roundNum(eaasPriceDisplay, 2)],
    [`Różnica cen [${currencyLabel}/MWh]:`, roundNum(priceDiffDisplay, 2)],
    ['Procent oszczędności [%]:', roundNum((result.metrics.priceDifferencePLNperKWh / result.metrics.gridPricePLNperKWh) * 100, 1)],
    [''],
    [`Roczne oszczędności [tys. ${currencyLabel}]:`, roundNum(annualSavingsDisplay, 1)]
  ];

  const ws1 = XLSX.utils.aoa_to_sheet(summaryData);

  // Set column widths
  ws1['!cols'] = [
    { wch: 35 },
    { wch: 20 }
  ];

  XLSX.utils.book_append_sheet(wb, ws1, 'Podsumowanie EaaS');

  // ========== SHEET 2: Year-by-year with EXCEL FORMULAS (auditable) ==========
  // Use centralizedMetrics for correct base values, but generate Excel formulas for full auditability
  const centralizedCalc = centralizedMetrics[currentVariant];
  if (!centralizedCalc || !centralizedCalc.eaas) {
    console.warn('⚠️ No centralized EaaS metrics for Excel export');
    alert('Brak danych EaaS. Najpierw wykonaj analizę.');
    return;
  }

  const eaasCashFlows = centralizedCalc.eaas.cashFlows;
  // Use eaasDuration from centralizedMetrics (same source as UI calculations)
  const eaasDuration = centralizedCalc.eaas.duration || parseInt(document.getElementById('eaasDuration')?.value) || 15;
  const discountRate = centralizedCalc.common.discountRate;
  const inflationRate = centralizedCalc.common.inflationRate;
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice; // PLN/MWh
  // In RDN mode: compute effective price from actual TCSL annual cost
  const isRdnExport = !!window._rdnExportMode;
  const rdnBLEaas = isRdnExport ? (centralizedCalc.eaas?.rdnBaseline || null) : null;
  const rdnGridCostYear1TysEaas = rdnBLEaas ? plnToTysPln(rdnBLEaas.nopvRdnTcslAnnual) : 0;
  const rdnEffPriceEaas = (rdnBLEaas && annualConsumptionMwh > 0)
    ? rdnBLEaas.nopvRdnTcslAnnual / annualConsumptionMwh : totalEnergyPrice;
  const effectiveEnergyPriceEaas = isRdnExport ? rdnEffPriceEaas : totalEnergyPrice;
  // baseSubscription is always in PLN (from calculateCentralizedFinancialMetrics)
  // Safety: if centralizedCalc value looks too low (e.g. EUR value leaked), prefer window.eaasSubscription
  let baseSubscriptionCost = centralizedCalc.eaas.baseSubscription || (window.eaasSubscription || 166760);
  if (window.eaasSubscription > 0 && baseSubscriptionCost < window.eaasSubscription * 0.5) {
    console.warn(`⚠️ baseSubscription ${baseSubscriptionCost.toFixed(0)} looks too low vs fullModel ${window.eaasSubscription.toFixed(0)} PLN — using fullModel value`);
    baseSubscriptionCost = window.eaasSubscription;
  }
  const baseOmCost = centralizedCalc.eaas.baseOmCost || 0;
  const baseInsuranceCost = centralizedCalc.eaas.baseInsuranceCost || 0;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';

  // currency and fxPlnEur already defined above (for Sheet 1)

  // Get degradation rates — always show actual setting for display/Excel
  const pvDegradationYear1 = pctToDecimal(systemSettings?.pvDegradationYear1 !== undefined ? systemSettings.pvDegradationYear1 : 1.0);
  const pvDegradationYears2Plus = params.degradation_rate; // for years 2+

  // Base autoconsumption (LID already included when precise data available)
  // NOTE: autoconsumptionMwh already includes scenarioFactor (P50/P75/P90)
  const baseAutoconsumptionMwh = autoconsumptionMwh;

  console.log(`📥 Export EaaS with FORMULAS - scenario: ${scenarioName} (×${scenarioFactor}), baseAutoconsumption:`, baseAutoconsumptionMwh, 'MWh');
  console.log('📥 Degradation: Year1:', decimalToPct(pvDegradationYear1).toFixed(1) + '%, Years2+:', decimalToPct(pvDegradationYears2Plus).toFixed(2) + '%/yr');

  // Convert values to contract currency for Sheet 2
  const baseSubscriptionDisplay = plnToTysPln(baseSubscriptionCost * currencyMultiplier); // tys. w walucie kontraktu
  const totalEnergyPriceDisplay = totalEnergyPrice * currencyMultiplier; // w walucie kontraktu

  // Create worksheet manually to set formulas
  // PARAMETRY: labels in columns B-D (merged), values in column E
  const ws2 = XLSX.utils.aoa_to_sheet([
    ['', `ANALIZA EaaS${window._rdnExportMode ? ' (ceny RDN)' : ''} ROK PO ROKU Z NPV - Scenariusz ${scenarioName}`],
    [''],
    ['', 'PARAMETRY:'],
    ['', 'Stopa dyskontowa:', '', '', roundNum(discountRate, 4)],                                // B4, E4 (0.10 = 10%)
    ['', 'Inflacja:', '', '', roundNum(inflationRate, 4)],                                       // B5, E5 (0.025 = 2.5%)
    ['', 'Degradacja PV Rok 1:', '', '', roundNum(pvDegradationYear1, 4)],                       // B6, E6 (0.02 = 2%)
    ['', 'Degradacja PV Lata 2+:', '', '', roundNum(pvDegradationYears2Plus, 4)],                // B7, E7 (0.004 = 0.4%)
    ['', 'Okres umowy EaaS [lat]:', '', '', eaasDuration],                                       // B8, E8
    ['', 'Okres analizy [lat]:', '', '', analysisPeriod],                                        // B9, E9
    ['', 'Autokonsumpcja bazowa [MWh]:', '', '', roundNum(baseAutoconsumptionMwh, 2)],           // B10, E10
    ['', isRdnExport ? `Oszcz. RDN brutto rok 1 [tys. ${currencyLabel}]:` : `Cena sieci bazowa [${currencyLabel}/MWh]:`, '', '', isRdnExport ? roundNum(plnToTysPln((rdnBLEaas ? rdnBLEaas.totalSavingsYear1 : 0) * currencyMultiplier), 2) : roundNum(totalEnergyPriceDisplay, 2)],    // B11, E11
    ['', `Abonament EaaS [tys. ${currencyLabel}/rok]:`, '', '', roundNum(baseSubscriptionDisplay, 2)],  // B12, E12
    ['', `O&M + Ubezp. (rok 1 własności) [tys. ${currencyLabel}/rok]:`, '', '', null], // B13, E13 - formula set below
    ['', 'Indeksacja EaaS:', '', '', eaasIndexation === 'cpi' ? 'Rata indeksowana inflacją' : 'Rata stała'],  // B14, E14
    ['', `Zużycie roczne [MWh]:`, '', '', roundNum(annualConsumptionMwh, 2)],  // B15, E15
    ['', currencyInfoLabel, '', '', currencyInfoValue],  // B16, E16 - Currency info (Waluta EUR: / 4,25 PLN/EUR)
    [''],  // Row 17 - empty row before header
    // Header row (row 18)
    ['Rok', 'Faza', `Zużycie [MWh]`, `Koszt BEZ PV [tys. ${currencyLabel}]`, 'Autokonsumpcja [MWh]', `Koszt Z PV [tys. ${currencyLabel}]`, isRdnExport ? `Oszcz. RDN brutto [tys. ${currencyLabel}]` : `Oszczędność PV [tys. ${currencyLabel}]`, `Koszt EaaS/Własność [tys. ${currencyLabel}]`, `Oszczędności [tys. ${currencyLabel}]`, `CF Zdyskontowany [tys. ${currencyLabel}]`, `Skumulowany NPV [mln ${currencyLabel}]`]
  ]);

  // Format cells E4:E7 as percentages (Excel percentage format)
  const percentCells = ['E4', 'E5', 'E6', 'E7'];
  for (const cellRef of percentCells) {
    if (ws2[cellRef]) {
      ws2[cellRef].z = '0.00%';  // Excel percentage format
    }
  }

  // E13: O&M + Ubezp. (rok 1 własności) - tylko wartość (bez formuły dla ochrony danych)
  // Wartość już zindeksowana na moment przejścia na własność, w walucie kontraktu
  const baseOmTotalThousands = plnToTysPln((baseOmCost + baseInsuranceCost) * currencyMultiplier); // tys. w walucie kontraktu
  const omAtOwnershipYear1 = baseOmTotalThousands * Math.pow(1 + inflationRate, eaasDuration);
  ws2['E13'] = {
    t: 'n',
    v: roundNum(omAtOwnershipYear1, 2)  // Tylko wartość, bez formuły
  };

  // Helper to set cell with formula and pre-calculated value
  function setCell(ws, col, row, formula, value) {
    const cellRef = XLSX.utils.encode_cell({ c: col, r: row - 1 });
    ws[cellRef] = { t: 'n', f: formula, v: value };
  }
  function setCellText(ws, col, row, formula, value) {
    const cellRef = XLSX.utils.encode_cell({ c: col, r: row - 1 });
    ws[cellRef] = { t: 's', f: formula, v: value };
  }
  function setCellNumber(ws, col, row, value) {
    const cellRef = XLSX.utils.encode_cell({ c: col, r: row - 1 });
    ws[cellRef] = { t: 'n', v: value };
  }

  const dataStartRow = 19; // Row 19 is first data row (header is row 18, added Zużycie roczne param row)
  let cumulativeNPV = 0;
  let eaasPhaseSavings = 0;
  let ownershipPhaseSavings = 0;

  for (let year = 1; year <= analysisPeriod; year++) {
    const row = dataStartRow + year - 1;
    const prevRow = row - 1;
    const yearData = eaasCashFlows[year - 1]; // Get pre-calculated values from centralizedMetrics

    // Get values from centralizedMetrics (these are the correct values in PLN)
    const autoconsumptionKwh = yearData?.selfConsumed || 0;
    const autoconsumptionYearMwh = kwhToMwh(autoconsumptionKwh);
    // Convert to contract currency
    const gridCost = (yearData?.gridCost || 0) * currencyMultiplier;
    const eaasCost = (yearData?.eaasCost || 0) * currencyMultiplier;
    const savings = (yearData?.savings || 0) * currencyMultiplier;
    const discountedCF = (yearData?.discountedCF || 0) * currencyMultiplier;
    const phase = yearData?.phase || (year <= eaasDuration ? 'eaas' : 'ownership');

    cumulativeNPV += discountedCF;
    if (phase === 'eaas') {
      eaasPhaseSavings += savings;
    } else {
      ownershipPhaseSavings += savings;
    }

    // Column A: Rok
    setCellNumber(ws2, 0, row, year);

    // Column B: Faza - formula (E8 = okres EaaS)
    const phaseFormula = `IF(A${row}<=$E$8,"EaaS","Własność")`;
    setCellText(ws2, 1, row, phaseFormula, phase === 'eaas' ? 'EaaS' : 'Własność');

    // Column C: Zużycie [MWh] - stałe roczne zużycie zakładu (nie degraduje się)
    // E15 = zużycie roczne [MWh]
    const consumptionFormula = `$E$15`;
    const consumptionMwh = annualConsumptionMwh;
    setCell(ws2, 2, row, consumptionFormula, roundNum(consumptionMwh, 2));

    // Column D: Koszt BEZ PV [tys. PLN] = zużycie × cena sieci × inflacja
    // E15=zużycie, E11=cena sieci bazowa, E5=inflacja
    const noPvCostFormula = `C${row}*$E$11/1000*POWER(1+$E$5,A${row}-1)`;
    const noPvCostValue = consumptionMwh * totalEnergyPrice * Math.pow(1 + inflationRate, year - 1) * currencyMultiplier;
    setCell(ws2, 3, row, noPvCostFormula, roundNum(plnToTysPln(noPvCostValue), 2));

    // Column E: Autokonsumpcja [MWh] - formula with Year1 and Years2+ degradation
    // E10=autokonsumpcja bazowa, E6=degradacja rok 1, E7=degradacja lata 2+
    const autoFormula = `$E$10*(1-$E$6)*POWER(1-$E$7,A${row}-1)`;
    setCell(ws2, 4, row, autoFormula, roundNum(autoconsumptionYearMwh, 2));

    // Column F: Koszt Z PV [tys. PLN] = Koszt BEZ PV - Oszczędność PV
    // = (zużycie - autokonsumpcja) × cena × inflacja
    const withPvCostFormula = `D${row}-G${row}`;
    const pvSavingsValue = gridCost; // autokonsumpcja × cena (from cashflows)
    const withPvCostValue = noPvCostValue - pvSavingsValue;
    setCell(ws2, 5, row, withPvCostFormula, roundNum(plnToTysPln(withPvCostValue), 2));

    // Column G: Oszczędność PV [tys. PLN] = autokonsumpcja × cena sieci × inflacja
    // Tariff: Autokonsumpcja * cena [PLN/MWh] / 1000 * CPI
    // RDN: gridCost from cashflows = totalSavings (energy+capacity)
    const pvSavingsFormula = isRdnExport
      ? `$E$11*POWER(1+$E$5,A${row}-1)`
      : `E${row}*$E$11/1000*POWER(1+$E$5,A${row}-1)`;
    setCell(ws2, 6, row, pvSavingsFormula, roundNum(plnToTysPln(pvSavingsValue), 2));

    // Column H: Koszt EaaS/Własność [tys. PLN]
    // W fazie EaaS: abonament (z lub bez indeksacji inflacją)
    // W fazie Własność: E13 (O&M zindeksowane) × inflacja
    const eaasCostFormula = `IF(A${row}<=$E$8,IF($E$14="Rata indeksowana inflacją",$E$12*POWER(1+$E$5,A${row}-1),$E$12),$E$13*POWER(1+$E$5,A${row}-$E$8-1))`;
    setCell(ws2, 7, row, eaasCostFormula, roundNum(plnToTysPln(eaasCost), 2));

    // Column I: Oszczędności [tys. PLN] = Oszczędność PV - Koszt EaaS
    const savingsFormula = `G${row}-H${row}`;
    setCell(ws2, 8, row, savingsFormula, roundNum(plnToTysPln(savings), 2));

    // Column J: CF Zdyskontowany [tys. PLN]
    const discountedFormula = `I${row}/POWER(1+$E$4,A${row})`;
    setCell(ws2, 9, row, discountedFormula, roundNum(plnToTysPln(discountedCF), 2));

    // Column K: Skumulowany NPV [mln PLN]
    const npvFormula = year === 1 ? `J${row}/1000` : `K${prevRow}+J${row}/1000`;
    setCell(ws2, 10, row, npvFormula, roundNum(plnToMlnPln(cumulativeNPV), 2));
  }

  // Summary rows
  const lastDataRow = dataStartRow + analysisPeriod - 1;
  const summaryRow1 = lastDataRow + 2;
  const summaryRow2 = summaryRow1 + 1;
  const summaryRow3 = summaryRow2 + 1;

  // Extend sheet range (columns A-K = 0-10)
  ws2['!ref'] = XLSX.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: 10, r: summaryRow3 - 1 } });

  // Suma faza EaaS (label in col H=7, value in col I=8 = Oszczędności)
  ws2[XLSX.utils.encode_cell({ c: 7, r: summaryRow1 - 1 })] = { t: 's', v: `Suma faza EaaS (1-${eaasDuration}):` };
  ws2[XLSX.utils.encode_cell({ c: 8, r: summaryRow1 - 1 })] = {
    t: 'n',
    f: `SUMIF(B${dataStartRow}:B${lastDataRow},"EaaS",I${dataStartRow}:I${lastDataRow})`,
    v: roundNum(plnToTysPln(eaasPhaseSavings), 0)
  };

  // Suma faza Własność
  ws2[XLSX.utils.encode_cell({ c: 7, r: summaryRow2 - 1 })] = { t: 's', v: `Suma faza Własność (${eaasDuration + 1}-${analysisPeriod}):` };
  ws2[XLSX.utils.encode_cell({ c: 8, r: summaryRow2 - 1 })] = {
    t: 'n',
    f: `SUMIF(B${dataStartRow}:B${lastDataRow},"Własność",I${dataStartRow}:I${lastDataRow})`,
    v: roundNum(plnToTysPln(ownershipPhaseSavings), 0)
  };

  // Suma całkowita
  ws2[XLSX.utils.encode_cell({ c: 7, r: summaryRow3 - 1 })] = { t: 's', v: 'SUMA CAŁKOWITA:' };
  ws2[XLSX.utils.encode_cell({ c: 8, r: summaryRow3 - 1 })] = {
    t: 'n',
    f: `SUM(I${dataStartRow}:I${lastDataRow})`,
    v: roundNum(plnToTysPln(eaasPhaseSavings + ownershipPhaseSavings), 0)
  };
  ws2[XLSX.utils.encode_cell({ c: 9, r: summaryRow3 - 1 })] = { t: 's', v: `NPV [mln ${currency}]:` };
  ws2[XLSX.utils.encode_cell({ c: 10, r: summaryRow3 - 1 })] = {
    t: 'n',
    f: `K${lastDataRow}`,
    v: roundNum(plnToMlnPln(cumulativeNPV), 2)
  };

  // Set column widths (A-K = 11 columns)
  ws2['!cols'] = [
    { wch: 6 },   // A: Rok
    { wch: 12 },  // B: Faza
    { wch: 14 },  // C: Zużycie [MWh]
    { wch: 18 },  // D: Koszt BEZ PV
    { wch: 20 },  // E: Autokonsumpcja
    { wch: 18 },  // F: Koszt Z PV
    { wch: 20 },  // G: Oszczędność PV
    { wch: 28 },  // H: Koszt EaaS/Własność
    { wch: 18 },  // I: Oszczędności
    { wch: 22 },  // J: CF Zdyskontowany
    { wch: 22 }   // K: Skumulowany NPV
  ];

  XLSX.utils.book_append_sheet(wb, ws2, 'EaaS Rok po Roku');

  // NOTE: Sheet 3 (CF Miesięczny) removed - contains sensitive ESCO profitability data

  // ========== USE EXCELJS FOR CONDITIONAL FORMATTING ==========
  // Convert XLSX workbook to ExcelJS for conditional formatting support
  console.log('📥 Converting to ExcelJS for conditional formatting...');

  const excelWorkbook = new ExcelJS.Workbook();

  // Load logo image as base64
  let logoImageId = null;
  try {
    const logoResponse = await fetch('/logo.png?v=' + Date.now());  // Cache bust
    const logoBlob = await logoResponse.blob();
    const logoBase64 = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result.split(',')[1]);
      reader.readAsDataURL(logoBlob);
    });
    console.log('📥 Logo loaded successfully');

    logoImageId = excelWorkbook.addImage({
      base64: logoBase64,
      extension: 'png'
    });
  } catch (err) {
    console.warn('⚠️ Could not load logo:', err);
  }

  // Sheet 1: Podsumowanie EaaS (with enhanced styling)
  const excelSheet1 = excelWorkbook.addWorksheet('Podsumowanie EaaS');
  excelSheet1.columns = [
    { width: 3 },   // A: margin column (empty)
    { width: 38 },  // B: labels
    { width: 22 }   // C: values
  ];

  // Hide gridlines and headers for cleaner look
  excelSheet1.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Copy summary data with styling (shifted to column B)
  summaryData.forEach((row, idx) => {
    const excelRow = excelSheet1.getRow(idx + 1);
    row.forEach((cell, colIdx) => {
      excelRow.getCell(colIdx + 2).value = cell;  // Start from column B (index 2)
    });
  });

  // Style Sheet 1: Podsumowanie EaaS
  // Merge B1:C3 for header area (logo + title)
  excelSheet1.mergeCells('B1:C3');

  // Set row heights for header area
  excelSheet1.getRow(1).height = 20;
  excelSheet1.getRow(2).height = 20;
  excelSheet1.getRow(3).height = 24;

  // Style the merged header cell - title at bottom, centered
  const headerCell = excelSheet1.getCell('B1');
  headerCell.value = `ANALIZA EaaS${window._rdnExportMode ? ' (ceny RDN)' : ''} (Energy-as-a-Service) - Scenariusz ${scenarioName}`;
  headerCell.font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  headerCell.alignment = { horizontal: 'center', vertical: 'bottom' };

  // Add logo to merged header area (centered above title)
  if (logoImageId !== null) {
    excelSheet1.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },  // Top-left position (shifted for margin)
      ext: { width: 200, height: 50 }  // Size in pixels
    });
  }

  // Section headers styling (cells shifted to B and C)
  // Row mapping: DANE INSTALACJI=5, PARAMETRY UMOWY=11, SKŁADNIKI TARYFY=16, KORZYŚCI=25
  const sectionHeaders1 = [5, 11, 16, 25];
  sectionHeaders1.forEach(rowNum => {
    const row = excelSheet1.getRow(rowNum);
    row.getCell(2).font = { bold: true, size: 11, color: { argb: 'FF2E7D32' } };
    row.getCell(2).fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FFE8F5E9' }
    };
    row.getCell(3).fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FFE8F5E9' }
    };
  });

  // Add borders to data cells in Sheet 1 (shifted +1, cells in B and C)
  for (let r = 6; r <= 9; r++) {
    const row = excelSheet1.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }
  for (let r = 12; r <= 14; r++) {  // PARAMETRY UMOWY: Abonament, Okres analizy, Currency info
    const row = excelSheet1.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }
  for (let r = 17; r <= 23; r++) {  // SKŁADNIKI TARYFY (7 pozycji)
    const row = excelSheet1.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }

  // Highlight key results (savings rows - cells in B and C)
  // Row mapping: Procent oszczędności=29, Roczne oszczędności=31
  const savingsRows1 = [29, 31];
  savingsRows1.forEach(rowNum => {
    const row = excelSheet1.getRow(rowNum);
    if (row.getCell(2).value) {
      row.getCell(2).font = { bold: true, color: { argb: 'FF2E7D32' } };
      row.getCell(3).font = { bold: true, color: { argb: 'FF2E7D32' } };
      row.getCell(3).alignment = { horizontal: 'right' };
    }
  });

  // Update views: frozen rows + hide gridlines and headers
  excelSheet1.views = [{ state: 'frozen', ySplit: 3, showGridLines: false, showRowColHeaders: false }];

  // Sheet 2: EaaS Rok po Roku with conditional formatting
  const excelSheet2 = excelWorkbook.addWorksheet('EaaS Rok po Roku');
  excelSheet2.columns = [
    { width: 3 },   // A: margin column (empty)
    { width: 5 },   // B: Rok
    { width: 36 },  // C: Faza / PARAMETRY labels (wider for long text)
    { width: 14 },  // D: Zużycie [MWh]
    { width: 16 },  // E: Koszt BEZ PV
    { width: 18 },  // F: Autokonsumpcja / Parameter values
    { width: 16 },  // G: Koszt Z PV
    { width: 18 },  // H: Oszczędność PV
    { width: 22 },  // I: Koszt EaaS/Własność
    { width: 16 },  // J: Oszczędności
    { width: 18 },  // K: CF Zdyskontowany
    { width: 18 }   // L: Skumulowany NPV / NPV [mln PLN]:
  ];

  // Hide gridlines and headers for cleaner look (will be updated with freeze later)
  excelSheet2.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Copy data from XLSX worksheet to ExcelJS (shifted +1 column for margin)
  const range = XLSX.utils.decode_range(ws2['!ref']);
  for (let R = range.s.r; R <= range.e.r; R++) {
    const excelRow = excelSheet2.getRow(R + 1);
    for (let C = range.s.c; C <= range.e.c; C++) {
      const cellRef = XLSX.utils.encode_cell({ c: C, r: R });
      const cell = ws2[cellRef];
      if (cell) {
        const excelCell = excelRow.getCell(C + 2);  // Shifted +1 for margin column
        if (cell.f) {
          // Cell has formula - shift column references by 1
          // Use temporary tokens to avoid cascading replacements
          let shiftedFormula = cell.f
            // First pass: replace with temporary tokens (absolute refs) - from K down to A
            .replace(/\$K/g, '§K§')
            .replace(/\$J/g, '§J§')
            .replace(/\$I/g, '§I§')
            .replace(/\$H/g, '§H§')
            .replace(/\$G/g, '§G§')
            .replace(/\$F/g, '§F§')
            .replace(/\$E/g, '§E§')
            .replace(/\$D/g, '§D§')
            .replace(/\$C/g, '§C§')
            .replace(/\$B/g, '§B§')
            .replace(/\$A/g, '§A§')
            // Second pass: replace tokens with shifted columns (A→B, B→C, ..., K→L)
            .replace(/§A§/g, '$B')
            .replace(/§B§/g, '$C')
            .replace(/§C§/g, '$D')
            .replace(/§D§/g, '$E')
            .replace(/§E§/g, '$F')
            .replace(/§F§/g, '$G')
            .replace(/§G§/g, '$H')
            .replace(/§H§/g, '$I')
            .replace(/§I§/g, '$J')
            .replace(/§J§/g, '$K')
            .replace(/§K§/g, '$L');
          // Also handle non-absolute references with tokens - from K down to A
          shiftedFormula = shiftedFormula
            .replace(/(^|[^$§])K(\d+)/g, '$1«K»$2')
            .replace(/(^|[^$§])J(\d+)/g, '$1«J»$2')
            .replace(/(^|[^$§])I(\d+)/g, '$1«I»$2')
            .replace(/(^|[^$§])H(\d+)/g, '$1«H»$2')
            .replace(/(^|[^$§])G(\d+)/g, '$1«G»$2')
            .replace(/(^|[^$§])F(\d+)/g, '$1«F»$2')
            .replace(/(^|[^$§])E(\d+)/g, '$1«E»$2')
            .replace(/(^|[^$§])D(\d+)/g, '$1«D»$2')
            .replace(/(^|[^$§])C(\d+)/g, '$1«C»$2')
            .replace(/(^|[^$§])B(\d+)/g, '$1«B»$2')
            .replace(/(^|[^$§])A(\d+)/g, '$1«A»$2')
            .replace(/«A»/g, 'B')
            .replace(/«B»/g, 'C')
            .replace(/«C»/g, 'D')
            .replace(/«D»/g, 'E')
            .replace(/«E»/g, 'F')
            .replace(/«F»/g, 'G')
            .replace(/«G»/g, 'H')
            .replace(/«H»/g, 'I')
            .replace(/«I»/g, 'J')
            .replace(/«J»/g, 'K')
            .replace(/«K»/g, 'L');
          excelCell.value = { formula: shiftedFormula, result: cell.v };
        } else {
          excelCell.value = cell.v;
        }
        // Apply percentage format for cells F4:F7 (was E4:E7, column F = index 5 after shift)
        if (C === 4 && R >= 3 && R <= 6) {
          excelCell.numFmt = '0.00%';
        }
        // Apply number format with thousand separator for data rows (row 19+, columns C-K)
        // Row 18 is header (R=17), data starts at R=18 (row 19)
        if (R >= 18 && C >= 2 && C <= 10 && typeof cell.v === 'number') {
          excelCell.numFmt = '#,##0.00';  // Format: 1 000,00
        }
      }
    }
  }

  // RDN cross-sheet formulas: overwrite parameter F11 and column H (Oszczędność PV) with audit references
  // Note: ExcelJS columns are +1 from XLSX (margin column A), so XLSX E11 → ExcelJS F11, XLSX G → ExcelJS H
  if (isRdnExport) {
    const AUDIT = "'Dane bazowe TCSL (Rok 1)'!";
    // F11: total savings year 1 = reference to audit sheet F31 (TCSL RAZEM savings) / 1000
    const f11val = excelSheet2.getCell('F11').value;
    const f11result = typeof f11val === 'object' ? f11val.result : f11val;
    excelSheet2.getCell('F11').value = { formula: `${AUDIT}F31/1000`, result: f11result };
    excelSheet2.getCell('F11').numFmt = '#,##0.00';
    // Column H (Oszcz. RDN brutto / Oszczędność PV): cross-sheet formula separating energy (degrades) and capacity (no degrade)
    // H = (audit!F18 * pvDeg * CPI + audit!F21 * CPI) / 1000
    for (let yr = 1; yr <= analysisPeriod; yr++) {
      const dRow = dataStartRow + yr - 1;
      const pvDeg = `(1-$F$6)*POWER(1-$F$7,B${dRow}-1)`;
      const cpi = `POWER(1+$F$5,B${dRow}-1)`;
      const rdnFormula = `(${AUDIT}F18*${pvDeg}*${cpi}+${AUDIT}F21*${cpi})/1000`;
      const prevResult = excelSheet2.getCell(`H${dRow}`).value;
      const prevNum = typeof prevResult === 'object' ? prevResult.result : prevResult;
      excelSheet2.getCell(`H${dRow}`).value = { formula: rdnFormula, result: prevNum || 0 };
      excelSheet2.getCell(`H${dRow}`).numFmt = '#,##0.00';
    }
    console.log('✅ EaaS RDN: cross-sheet formulas applied to F11 and column H');
  }

  // Style title row (row 1) - shifted +1 column for margin
  const titleRow2 = excelSheet2.getRow(1);
  titleRow2.getCell(3).font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  titleRow2.height = 22;

  // Style PARAMETRY section header (row 3) - merge C3:E3 and align right with trailing space
  excelSheet2.mergeCells('C3:E3');
  const paramHeader = excelSheet2.getRow(3);
  paramHeader.getCell(3).value = 'PARAMETRY: ';  // Add trailing space
  paramHeader.getCell(3).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  paramHeader.getCell(3).alignment = { horizontal: 'right', vertical: 'middle' };

  // Merge cells C:E for parameter labels (rows 4-16, including zużycie + currency info) and style them - shifted +1
  for (let r = 4; r <= 16; r++) {
    // Merge C:E for the label (was B:D)
    excelSheet2.mergeCells(`C${r}:E${r}`);

    const row = excelSheet2.getRow(r);
    // Add trailing space to label text and align right
    const currentValue = row.getCell(3).value;
    if (currentValue && typeof currentValue === 'string') {
      row.getCell(3).value = currentValue + ' ';  // Add trailing space
    }
    row.getCell(3).font = { color: { argb: 'FF616161' } };
    row.getCell(3).alignment = { horizontal: 'right', vertical: 'middle' };

    // Style the value in column F (was E) - align left with leading space
    const valueCell = row.getCell(6);
    if (valueCell.value !== null && valueCell.value !== undefined) {
      // Add leading space for separation
      if (typeof valueCell.value === 'string') {
        valueCell.value = ' ' + valueCell.value;
      }
    }
    valueCell.font = { bold: true, color: { argb: 'FF1976D2' } };
    valueCell.alignment = { horizontal: 'left', vertical: 'middle' };

    // Add subtle border
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
    row.getCell(6).border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
  }

  // Style header row (row 18) - enhanced with text wrapping, taller for visibility
  const headerRow = excelSheet2.getRow(18);
  headerRow.height = 40;  // Taller for wrapped text (increased from 30)
  headerRow.eachCell((cell, colNum) => {
    if (colNum === 1) return;  // Skip margin column
    cell.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF37474F' }  // Dark blue-grey
    };
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 9 };  // White text, smaller font
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };  // Text wrapping
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  // Column header notes (Sheet 2 PL) — explain formulas in each column (row 18 = header)
  if (withFormulas) {
    excelSheet2.getCell('D18').note = `-- Zużycie roczne zakładu [MWh] (stałe)`;
    excelSheet2.getCell('E18').note = `-- Zużycie × cena_sieci / 1000 × (1+inflacja)^(rok-1)`;
    excelSheet2.getCell('F18').note = `-- Bazowa × (1-degY1) × (1-degY2+)^(rok-1)`;
    excelSheet2.getCell('G18').note = `-- Koszt BEZ PV - Oszczędność PV`;
    excelSheet2.getCell('H18').note = `-- Autokonsumpcja × cena_sieci / 1000 × (1+inflacja)^(rok-1)`;
    excelSheet2.getCell('I18').note = `-- Faza EaaS: abonament\n-- Faza Własność: O&M + ubezpieczenie`;
    excelSheet2.getCell('J18').note = `-- Oszczędność PV - Koszt EaaS`;
    excelSheet2.getCell('K18').note = `-- Oszczędności / (1+r)^rok`;
    excelSheet2.getCell('L18').note = `-- Suma bieżąca CF / 1000 [mln PLN]`;
  }

  // Add logo to Sheet 2 (top right corner) - shifted +1
  if (logoImageId !== null) {
    excelSheet2.addImage(logoImageId, {
      tl: { col: 10, row: 0.2 },  // Top-left position (column K, row 1)
      ext: { width: 180, height: 45 }  // Size in pixels
    });
  }

  // Freeze header row and parameters (header is now row 18)
  excelSheet2.views = [{ state: 'frozen', ySplit: 18, xSplit: 0, showGridLines: false, showRowColHeaders: false }];

  // Add alternating row shading will be handled by conditional formatting
  // Add borders to data cells - shifted +1 column
  for (let r = dataStartRow; r <= lastDataRow; r++) {
    const row = excelSheet2.getRow(r);
    for (let c = 2; c <= 12; c++) {  // Start from 2 (skip margin), end at 12 (col L)
      const cell = row.getCell(c);
      cell.border = {
        bottom: { style: 'hair', color: { argb: 'FFE0E0E0' } }
      };
      // Center align year and phase columns (now B and C = indices 2 and 3)
      if (c <= 3) {
        cell.alignment = { horizontal: 'center' };
      } else {
        cell.alignment = { horizontal: 'right' };
      }
    }
  }

  // Add CONDITIONAL FORMATTING for data rows - shifted +1 column for margin
  // Colors matching HTML table: EaaS = #fff8e1 (light yellow), Ownership = #e8f5e9 (light green)
  const dataRange = `B${dataStartRow}:L${lastDataRow}`;  // B-L (all data columns)

  console.log('📥 Adding conditional formatting for range:', dataRange);

  // Rule 1: EaaS phase - light yellow (#fff8e1) when year <= eaasDuration (cell F8, was E8)
  // Rule 2: Ownership phase - light green (#e8f5e9) when year > eaasDuration
  excelSheet2.addConditionalFormatting({
    ref: dataRange,
    rules: [
      {
        type: 'expression',
        formulae: [`$B${dataStartRow}<=$F$8`],  // B is Rok, F is okres EaaS
        style: {
          fill: {
            type: 'pattern',
            pattern: 'solid',
            bgColor: { argb: 'FFFFF8E1' }  // #fff8e1 - light yellow (EaaS phase)
          }
        },
        priority: 1
      },
      {
        type: 'expression',
        formulae: [`$B${dataStartRow}>$F$8`],  // B is Rok, F is okres EaaS
        style: {
          fill: {
            type: 'pattern',
            pattern: 'solid',
            bgColor: { argb: 'FFE8F5E9' }  // #e8f5e9 - light green (Ownership phase)
          }
        },
        priority: 2
      }
    ]
  });

  // NPV conditional formatting on cumulative NPV column L (matching CAPEX style)
  excelSheet2.addConditionalFormatting({
    ref: `L${dataStartRow}:L${lastDataRow}`,
    rules: [
      {
        type: 'cellIs',
        operator: 'greaterThanOrEqual',
        formulae: [0],
        style: { font: { color: { argb: 'FF2E7D32' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFE8F5E9' } } },
        priority: 3
      },
      {
        type: 'cellIs',
        operator: 'lessThan',
        formulae: [0],
        style: { font: { color: { argb: 'FFC62828' } }, fill: { type: 'pattern', pattern: 'solid', bgColor: { argb: 'FFFFEBEE' } } },
        priority: 4
      }
    ]
  });

  // DPP Row Highlighting - DYNAMIC conditional formatting (matching CAPEX style)
  // Condition: this row's cumulative NPV >= 0 AND previous row's cumulative NPV < 0
  // Only amber border frame (no fill/font change)
  excelSheet2.addConditionalFormatting({
    ref: `B${dataStartRow}:L${lastDataRow}`,
    rules: [{
      type: 'expression',
      formulae: [`AND($L${dataStartRow}>=0,$L${dataStartRow - 1}<0)`],
      style: {
        border: {
          top: { style: 'medium', color: { argb: 'FFFFC107' } },
          bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
        }
      },
      priority: 5
    }]
  });

  // Add summary rows with styling matching HTML table exactly (like the image)
  // All columns shifted +1 for margin
  const summaryStartRow = lastDataRow + 2;

  // Row 1: Suma oszczędności w fazie EaaS - orange background
  const eaasSummaryRow = excelSheet2.getRow(summaryStartRow);
  eaasSummaryRow.height = 22;
  excelSheet2.mergeCells(summaryStartRow, 2, summaryStartRow, 9); // Merge B-I for label
  eaasSummaryRow.getCell(2).value = `📋  Suma oszczędności w fazie EaaS (lata 1-${eaasDuration}):`;
  eaasSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  eaasSummaryRow.getCell(10).value = { formula: `SUMIF(C${dataStartRow}:C${lastDataRow},"EaaS",J${dataStartRow}:J${lastDataRow})`, result: roundNum(plnToTysPln(eaasPhaseSavings), 2) };
  eaasSummaryRow.getCell(10).numFmt = '#,##0.00';
  eaasSummaryRow.getCell(10).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: light orange background #fff3e0, orange text #f57c00
  for (let col = 2; col <= 12; col++) {
    eaasSummaryRow.getCell(col).fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FFFFF3E0' }
    };
    eaasSummaryRow.getCell(col).font = { color: { argb: 'FFF57C00' }, bold: true };
    eaasSummaryRow.getCell(col).border = {
      top: { style: 'thin', color: { argb: 'FFFFCC80' } },
      bottom: { style: 'thin', color: { argb: 'FFFFCC80' } }
    };
  }

  // Row 2: Suma oszczędności w fazie własności - green background
  const ownershipSummaryRow = excelSheet2.getRow(summaryStartRow + 1);
  ownershipSummaryRow.height = 22;
  excelSheet2.mergeCells(summaryStartRow + 1, 2, summaryStartRow + 1, 9); // Merge B-I for label
  ownershipSummaryRow.getCell(2).value = `🏠  Suma oszczędności w fazie własności (${eaasDuration + 1}-${analysisPeriod}):`;
  ownershipSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  ownershipSummaryRow.getCell(10).value = { formula: `SUMIF(C${dataStartRow}:C${lastDataRow},"Własność",J${dataStartRow}:J${lastDataRow})`, result: roundNum(plnToTysPln(ownershipPhaseSavings), 2) };
  ownershipSummaryRow.getCell(10).numFmt = '#,##0.00';
  ownershipSummaryRow.getCell(10).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: light green background #e8f5e9, green text #4caf50
  for (let col = 2; col <= 12; col++) {
    ownershipSummaryRow.getCell(col).fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FFE8F5E9' }
    };
    ownershipSummaryRow.getCell(col).font = { color: { argb: 'FF4CAF50' }, bold: true };
    ownershipSummaryRow.getCell(col).border = {
      top: { style: 'thin', color: { argb: 'FFA5D6A7' } },
      bottom: { style: 'thin', color: { argb: 'FFA5D6A7' } }
    };
  }

  // Row 3: SUMA CAŁKOWITA + NPV - highlighted
  const totalSummaryRow = excelSheet2.getRow(summaryStartRow + 2);
  totalSummaryRow.height = 26;
  excelSheet2.mergeCells(summaryStartRow + 2, 2, summaryStartRow + 2, 9); // Merge B-I for label
  totalSummaryRow.getCell(2).value = '💰  SUMA CAŁKOWITA:';
  totalSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(10).value = { formula: `SUM(J${dataStartRow}:J${lastDataRow})`, result: roundNum(plnToTysPln(eaasPhaseSavings + ownershipPhaseSavings), 2) };
  totalSummaryRow.getCell(10).numFmt = '#,##0.00';
  totalSummaryRow.getCell(10).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(11).value = `NPV [mln ${currency}]:`;
  totalSummaryRow.getCell(11).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(12).value = { formula: `L${lastDataRow}`, result: roundNum(plnToMlnPln(cumulativeNPV), 2) };
  totalSummaryRow.getCell(12).numFmt = '#,##0.00';
  totalSummaryRow.getCell(12).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: gradient-like effect with bold
  for (let col = 2; col <= 12; col++) {
    totalSummaryRow.getCell(col).fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF37474F' }  // Dark background
    };
    totalSummaryRow.getCell(col).font = { bold: true, size: 11, color: { argb: 'FFFFFFFF' } };  // White text
    totalSummaryRow.getCell(col).border = {
      top: { style: 'medium', color: { argb: 'FF263238' } },
      bottom: { style: 'medium', color: { argb: 'FF263238' } }
    };
  }

  // Row 4: DPP (Discounted Payback Period) - matching CAPEX style
  const dppRow = excelSheet2.getRow(summaryStartRow + 4);
  dppRow.height = 22;
  excelSheet2.mergeCells(summaryStartRow + 4, 2, summaryStartRow + 4, 9);
  dppRow.getCell(2).value = `⏱️  Zdyskontowany zwrot (DPP):`;
  dppRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  dppRow.getCell(2).font = { bold: true, color: { argb: 'FF1565C0' } };

  // DPP interpolating formula: IF no negative years → 0, else interpolate
  // For EaaS, range is data-only (no Year 0), so INDEX offsets differ from CAPEX
  const _nEaaS = `SUMPRODUCT((L${dataStartRow}:L${lastDataRow}<0)*1)`;
  const _iRangeEaaS = `L${dataStartRow}:L${lastDataRow}`;
  const dppFormulaEaaS = `IF(${_nEaaS}=0,0,${_nEaaS}+(-INDEX(${_iRangeEaaS},${_nEaaS}))/(INDEX(${_iRangeEaaS},${_nEaaS}+1)-INDEX(${_iRangeEaaS},${_nEaaS})))`;

  // Calculate DPP value for formula result
  let eaasDpp = null;
  let runningNpvEaaS = 0;
  for (let i = 0; i < eaasCashFlows.length; i++) {
    const yr = i + 1;
    const prevNpv = runningNpvEaaS;
    const discCF = eaasCashFlows[i].net_cash_flow / Math.pow(1 + discountRate, yr);
    runningNpvEaaS += discCF;
    if (runningNpvEaaS >= 0 && prevNpv < 0) {
      eaasDpp = yr - 1 + (-prevNpv / discCF);
      break;
    }
  }
  if (eaasDpp === null && runningNpvEaaS >= 0) eaasDpp = 0;

  if (withFormulas) {
    dppRow.getCell(10).value = { formula: dppFormulaEaaS, result: eaasDpp || 0 };
  } else {
    dppRow.getCell(10).value = (eaasDpp !== null && eaasDpp !== undefined) ? roundNum(eaasDpp, 1) : '-';
  }
  dppRow.getCell(10).numFmt = '0.0';
  dppRow.getCell(10).font = { bold: true, color: { argb: 'FF1565C0' } };
  dppRow.getCell(10).alignment = { horizontal: 'right', vertical: 'middle' };
  dppRow.getCell(11).value = 'lat';
  dppRow.getCell(11).font = { italic: true, color: { argb: 'FF757575' } };
  dppRow.getCell(11).alignment = { horizontal: 'left', vertical: 'middle' };
  // Style: subtle blue border
  for (let col = 2; col <= 12; col++) {
    dppRow.getCell(col).border = {
      top: { style: 'thin', color: { argb: 'FF90CAF9' } },
      bottom: { style: 'thin', color: { argb: 'FF90CAF9' } }
    };
  }

  // Set print area and page setup
  excelSheet2.pageSetup.printArea = `A1:L${summaryStartRow + 4}`;
  excelSheet2.pageSetup.fitToPage = true;
  excelSheet2.pageSetup.fitToWidth = 1;
  excelSheet2.pageSetup.orientation = 'landscape';

  // Store row references for Sheet 3 formulas (when withFormulas=true)
  // Sheet 2 has: column J = Oszczędności [tys. PLN], column L = Skumulowany NPV [mln PLN]
  const sheet2Refs = {
    eaasSumRow: summaryStartRow,        // Row with EaaS phase sum (column J)
    ownershipSumRow: summaryStartRow + 1, // Row with Ownership phase sum (column J)
    totalSumRow: summaryStartRow + 2,    // Row with SUMA CAŁKOWITA (column J)
    npvFinalRow: lastDataRow,            // Row with final NPV (column L)
    // Excel cell references for cross-sheet formulas
    eaasSum: `'EaaS Rok po Roku'!J${summaryStartRow}`,
    ownershipSum: `'EaaS Rok po Roku'!J${summaryStartRow + 1}`,
    totalSum: `'EaaS Rok po Roku'!J${summaryStartRow + 2}`,
    npvFinal: `'EaaS Rok po Roku'!L${lastDataRow}`
  };
  console.log('📊 Sheet 2 references for formulas:', sheet2Refs);

  // ========== SHEET 3: Analiza CFO - Wrażliwość i ESG ==========
  const excelSheet3 = excelWorkbook.addWorksheet('Analiza CFO');
  excelSheet3.columns = [
    { width: 3 },   // A: margin
    { width: 30 },  // B: labels
    { width: 16 },  // C: values
    { width: 14 },  // D: values
    { width: 14 },  // E: values
    { width: 14 },  // F: values
    { width: 14 },  // G: values
    { width: 14 },  // H: values
    { width: 14 }   // I: values
  ];
  excelSheet3.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Use analysisPeriod (30 years) for full analysis, eaasDuration (15 years) for EaaS phase
  const cfoPeriod = analysisPeriod; // Full analysis period (e.g., 30 years)
  const eaasPhaseYears = eaasDuration; // EaaS contract phase (e.g., 15 years)
  const ownershipPhaseYears = cfoPeriod - eaasPhaseYears; // Ownership phase (e.g., 15 years)
  console.log('📊 CFO Sheet - eaasDuration:', eaasDuration, 'analysisPeriod:', analysisPeriod, 'autoconsumptionMwh:', autoconsumptionMwh, 'gridPrice:', gridPriceDisplay, 'eaasPrice:', eaasPriceDisplay);

  // --- HEADER ---
  excelSheet3.mergeCells('B1:I1');
  excelSheet3.getCell('B1').value = `ANALIZA CFO - Model EaaS - Scenariusz ${scenarioName}`;
  excelSheet3.getCell('B1').font = { bold: true, size: 16, color: { argb: 'FF1976D2' } };
  excelSheet3.getCell('B1').alignment = { horizontal: 'center', vertical: 'middle' };

  excelSheet3.mergeCells('B2:I2');
  excelSheet3.getCell('B2').value = `Faza EaaS: lata 1-${eaasPhaseYears} (abonament) → Faza własności: lata ${eaasPhaseYears + 1}-${cfoPeriod} (bez opłat)`;
  excelSheet3.getCell('B2').font = { italic: true, size: 11, color: { argb: 'FF616161' } };
  excelSheet3.getCell('B2').alignment = { horizontal: 'center', vertical: 'middle' };

  // Add logo if available
  if (logoImageId !== null) {
    excelSheet3.addImage(logoImageId, {
      tl: { col: 7, row: 0.1 },
      ext: { width: 160, height: 40 }
    });
  }

  // --- SECTION 0: PARAMETRY (row 4) - for formulas reference ---
  let cfoRow = 4;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'PARAMETRY MODELU';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEBE9' } };

  cfoRow++;
  // Row 5: Parameters in cells for formula references
  excelSheet3.getCell(`B${cfoRow}`).value = 'Okres analizy [lat]';
  excelSheet3.getCell(`C${cfoRow}`).value = cfoPeriod;  // C5 = period (30 lat)
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = 'Faza EaaS [lat]';
  excelSheet3.getCell(`E${cfoRow}`).value = eaasPhaseYears;  // E5 = EaaS duration (15 lat)
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`F${cfoRow}`).value = 'Faza własności [lat]';
  excelSheet3.getCell(`G${cfoRow}`).value = ownershipPhaseYears;  // G5 = ownership phase (15 lat)
  excelSheet3.getCell(`G${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };

  cfoRow++;
  const autoParamRow = cfoRow; // Store row for ESG formulas
  // Row 6: More parameters - formulas referencing year-by-year sheet
  excelSheet3.getCell(`B${cfoRow}`).value = 'Autokonsumpcja [MWh/rok]';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `'EaaS Rok po Roku'!F10`, result: autoconsumptionMwh };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = autoconsumptionMwh;
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0.0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = 'Degradacja PV [%/rok]';
  if (withFormulas) {
    excelSheet3.getCell(`E${cfoRow}`).value = { formula: `'EaaS Rok po Roku'!F7`, result: pvDegradationYears2Plus };
  } else {
    excelSheet3.getCell(`E${cfoRow}`).value = pvDegradationYears2Plus;
  }
  excelSheet3.getCell(`E${cfoRow}`).numFmt = '0.00%';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };

  cfoRow++;
  const co2ParamRow = cfoRow; // Store row for ESG formulas (G7 = CO2 factor)
  // Row 7: More parameters
  excelSheet3.getCell(`B${cfoRow}`).value = `Cena sieci [${currencyLabel}/MWh]`;
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `'EaaS Rok po Roku'!F11`, result: gridPriceDisplay };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = gridPriceDisplay;
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = `Cena EaaS [${currencyLabel}/MWh]`;
  excelSheet3.getCell(`E${cfoRow}`).value = eaasPriceDisplay;  // E7 = EaaS price (not from RpR)
  excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`F${cfoRow}`).value = 'Emisja CO₂ [t/MWh]';
  excelSheet3.getCell(`G${cfoRow}`).value = 0.7;  // G7 = CO2 factor (t/MWh = kg/kWh)
  excelSheet3.getCell(`G${cfoRow}`).numFmt = '0.0';
  excelSheet3.getCell(`G${cfoRow}`).font = { bold: true };
  const gridPriceParamRow = cfoRow; // Store row number for matrix formulas

  cfoRow++;
  // Row 8: Calculated degradation factor for formulas
  excelSheet3.getCell(`B${cfoRow}`).value = 'Wskaźnik degradacji śr.';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `1-E${autoParamRow}*${cfoPeriod}/2`, result: 1 - pvDegradationYears2Plus * cfoPeriod / 2 };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = 1 - pvDegradationYears2Plus * cfoPeriod / 2;
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0.000';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = '= 1 - degradacja × okres / 2';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };
  const degradFactorParamRow = cfoRow;

  // === EaaS NPV base parameters (consistent with CAPEX calculateCapexNPV pattern) ===
  // Defined early so KPI helper rows can reference baseEaaSNpvTys
  const eaasNpvBaseForMatrix = {
    capacity_kwp: capacityKwp,
    self_consumed_annual_kwh: autoconsumptionMwh * 1000,  // MWh → kWh
    total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000,   // PLN/MWh → PLN/kWh (RDN-aware)
    eaas_subscription: baseSubscriptionCost,
    eaas_om_per_kwp: eaasOM,
    insurance_rate: window.economicsSettings?.insuranceRate || 0.005,
    capex_per_kwp: capex / capacityKwp,
    degradation_rate: pvDegradationYears2Plus || 0.004,
    discount_rate: discountRate,
    eaas_duration: eaasDuration,
    analysis_period: analysisPeriod || 30,
    inflation_rate: inflationRate,
    eaas_indexation: eaasIndexation || 'fixed'
  };

  // Base EaaS NPV (for tornado base, sensitivity thresholds, and KPI rows)
  let baseEaaSNpvPLN = 0;
  try {
    baseEaaSNpvPLN = calculateEaaSNPV(eaasNpvBaseForMatrix);
  } catch (npvErr) {
    console.error('⚠️ calculateEaaSNPV failed, using fallback:', npvErr);
    // Fallback: simple savings estimate
    baseEaaSNpvPLN = (autoconsumptionMwh * totalEnergyPrice - baseSubscriptionCost) * (analysisPeriod || 30) * 0.6;
  }
  const baseEaaSNpvTys = plnToTysPln(baseEaaSNpvPLN) * currencyMultiplier;
  const baseEaaSNpvMln = baseEaaSNpvTys / 1000;
  console.log('📊 EaaS NPV base:', { baseEaaSNpvPLN: roundNum(baseEaaSNpvPLN, 0), baseEaaSNpvTys: roundNum(baseEaaSNpvTys, 0), baseEaaSNpvMln: roundNum(baseEaaSNpvMln, 2), isRdnExport, effectivePrice: roundNum(effectiveEnergyPriceEaas, 2), tariffPrice: roundNum(totalEnergyPrice, 2) });

  // --- SECTION 1: KLUCZOWE KPI z podziałem na fazy ---
  cfoRow += 2;
  const kpiSectionRow = cfoRow;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `KLUCZOWE KPI DLA ZARZĄDU (analiza ${cfoPeriod} lat)`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRow++;
  // KPI with formulas - Zero CAPEX
  excelSheet3.getCell(`B${cfoRow}`).value = 'Zero CAPEX';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = 0;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0 "${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Brak wydatków inwestycyjnych';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Oszczędność roczna (rok 1)';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  // Formula using C6 (autoconsumption), C7 (grid price), E7 (EaaS price)
  excelSheet3.getCell(`C${cfoRow}`).value = { formula: `C6*(C7-E7)/1000` };
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0 "tys. ${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = '= Autokons. × (Cena_sieci - Cena_EaaS)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Use the same values as Sheet 2 (EaaS Rok po Roku) - already calculated with inflation and degradation
  // eaasPhaseSavings and ownershipPhaseSavings are calculated in the Sheet 2 loop above
  // They are in PLN and already include inflation + degradation year by year
  const totalSavingsEaaS = eaasPhaseSavings; // in PLN
  const totalSavingsOwnership = ownershipPhaseSavings; // in PLN
  const baseTotalSavings = plnToTysPln(totalSavingsEaaS + totalSavingsOwnership); // Convert from PLN to tys. PLN
  console.log('📊 KPI SUMA CAŁKOWITA (from Sheet 2):', {
    totalSavingsEaaS: totalSavingsEaaS,
    totalSavingsOwnership: totalSavingsOwnership,
    totalPLN: totalSavingsEaaS + totalSavingsOwnership,
    baseTotalSavings_tys: baseTotalSavings
  });

  // Faza EaaS
  cfoRow++;
  const kpiEaaSRow = cfoRow;  // Store row number for formula references
  excelSheet3.getCell(`B${cfoRow}`).value = `📋 Faza EaaS (lata 1-${eaasPhaseYears})`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  // Use formula or value depending on withFormulas flag
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `${sheet2Refs.eaasSum}/1000`, result: roundNum(plnToTysPln(totalSavingsEaaS), 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(plnToTysPln(totalSavingsEaaS), 2);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0.00 "mln ${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = withFormulas ? `= ${sheet2Refs.eaasSum} / 1000` : 'Oszczędności przy abonamencie EaaS';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Faza własności
  cfoRow++;
  const kpiOwnRow = cfoRow;  // Store row number for formula references
  excelSheet3.getCell(`B${cfoRow}`).value = `📋 Faza własności (lata ${eaasPhaseYears + 1}-${cfoPeriod})`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  // Use formula or value depending on withFormulas flag
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `${sheet2Refs.ownershipSum}/1000`, result: roundNum(plnToTysPln(totalSavingsOwnership), 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(plnToTysPln(totalSavingsOwnership), 2);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0.00 "mln ${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = withFormulas ? `= ${sheet2Refs.ownershipSum} / 1000` : 'Energia za darmo (tylko O&M)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // SUMA całkowita
  cfoRow++;
  const kpiTotalRow = cfoRow;  // Store row number for formula references
  excelSheet3.getCell(`B${cfoRow}`).value = `💰 SUMA CAŁKOWITA (${cfoPeriod} lat)`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  // Use formula or value depending on withFormulas flag
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `C${kpiEaaSRow}+C${kpiOwnRow}`, result: roundNum(plnToTysPln(totalSavingsEaaS + totalSavingsOwnership), 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(plnToTysPln(totalSavingsEaaS + totalSavingsOwnership), 2);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0.00 "mln ${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' }, size: 12 };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = withFormulas ? `= C${kpiEaaSRow} + C${kpiOwnRow}` : 'Skumulowana z uwzgl. degradacji PV';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // NPV (matching CAPEX CFO style)
  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '📊 NPV (wartość bieżąca netto)';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  const npvMln = plnToMlnPln(cumulativeNPV);
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `${sheet2Refs.npvFinal}`, result: roundNum(npvMln, 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(npvMln, 2);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '# ##0.00';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: npvMln > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: npvMln > 0 ? 'FFE8F5E9' : 'FFFFEBEE' } };
  excelSheet3.getCell(`D${cfoRow}`).value = `mln ${currencyLabel}`;
  excelSheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`E${cfoRow}`).value = npvMln > 0 ? 'Model opłacalny (NPV > 0)' : 'Model nieopłacalny (NPV < 0)';
  excelSheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // DPP - Zdyskontowany zwrot (matching CAPEX CFO style)
  cfoRow++;
  const hasDppEaaS = eaasDpp !== null && eaasDpp !== undefined;
  excelSheet3.getCell(`B${cfoRow}`).value = '⏱️ Zdyskontowany zwrot (DPP)';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  if (withFormulas) {
    const s2 = "'EaaS Rok po Roku'!";
    const _nCfoEaaS = `SUMPRODUCT((${s2}I${dataStartRow}:${s2}I${lastDataRow}<0)*1)`;
    const _iCfoRange = `${s2}I${dataStartRow}:${s2}I${lastDataRow}`;
    const kpiDppFormulaEaaS = `IF(${_nCfoEaaS}=0,0,${_nCfoEaaS}+(-INDEX(${_iCfoRange},${_nCfoEaaS}))/(INDEX(${_iCfoRange},${_nCfoEaaS}+1)-INDEX(${_iCfoRange},${_nCfoEaaS})))`;
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: kpiDppFormulaEaaS, result: hasDppEaaS ? roundNum(eaasDpp, 1) : 0 };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = hasDppEaaS ? roundNum(eaasDpp, 1) : (eaasDpp === 0 ? 0 : 'Natychmiast');
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = hasDppEaaS && eaasDpp > 0 ? '0.0' : '@';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`D${cfoRow}`).value = hasDppEaaS && eaasDpp > 0 ? 'lat' : '';
  excelSheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`E${cfoRow}`).value = eaasDpp === 0 ? 'NPV > 0 od roku 1 (brak CAPEX)' : 'Rok gdy skumulowane NPV >= 0';
  excelSheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Helper row for formulas: SUMA w tys. PLN (for scenario calculations)
  cfoRow++;
  const kpiTotalTysRow = cfoRow;  // Store row number for scenario formulas
  excelSheet3.getCell(`B${cfoRow}`).value = '(w tys. PLN)';
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `C${kpiTotalRow}*1000`, result: roundNum(baseTotalSavings, 0) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(baseTotalSavings, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { color: { argb: 'FF9E9E9E' } };

  // Helper row for NPV in tys. PLN - formula referencing year-by-year sheet (I column = mln PLN * 1000)
  cfoRow++;
  const kpiNpvTysRow = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = '(NPV w tys. PLN)';
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `'EaaS Rok po Roku'!I${lastDataRow}*1000`, result: roundNum(baseEaaSNpvTys, 0) };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- NPV z arkusza Rok po Roku\n-- I${lastDataRow} = skumulowany NPV [mln] × 1000`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(baseEaaSNpvTys, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { color: { argb: 'FF9E9E9E' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Rabat vs sieć (faza EaaS)';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = (gridPriceDisplay - eaasPriceDisplay) / gridPriceDisplay;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0%';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = `Gwarantowany przez ${eaasPhaseYears} lat umowy`;
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Bilans';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = 'Off-balance';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Nie obciąża bilansu firmy';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Ryzyko techniczne';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = 'Dostawca EaaS';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Gwarancja produkcji po stronie dostawcy';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Add borders to KPI section
  for (let r = kpiSectionRow + 1; r <= cfoRow; r++) {
    excelSheet3.getRow(r).getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    excelSheet3.getRow(r).getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // --- SECTION 2: TORNADO CHART - NPV EaaS ---
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'ANALIZA WRAŻLIWOŚCI - TORNADO CHART';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `Wpływ na NPV EaaS (${cfoPeriod} lat) przy zmianie parametru:`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Yield PV = produkcja energii z instalacji fotowoltaicznej [kWh/kWp/rok]';
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);

  // Calculate base 30-year savings - use baseTotalSavings from Sheet 2 (with inflation + degradation)
  const degradationFactor30 = 1 - degradationRate * cfoPeriod / 2; // Average over period (for other calculations)
  // tornadoBaseSavings30 now uses the same value as SUMA CAŁKOWITA (from Sheet 2)
  const tornadoBaseSavings30 = baseTotalSavings; // Already in tys. PLN, includes inflation + degradation year by year

  // === TORNADO CHART — Full NPV recalculation (consistent with CAPEX) ===
  const npvGridPess = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * 0.80})) * currencyMultiplier;
  const npvGridOpt  = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * 1.20})) * currencyMultiplier;
  const npvSubsPess = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, eaas_subscription: baseSubscriptionCost * 1.20})) * currencyMultiplier;
  const npvSubsOpt  = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, eaas_subscription: baseSubscriptionCost * 0.80})) * currencyMultiplier;
  const npvYieldPess = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, self_consumed_annual_kwh: autoconsumptionMwh * 1000 * 0.85})) * currencyMultiplier;
  const npvYieldOpt  = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, self_consumed_annual_kwh: autoconsumptionMwh * 1000 * 1.15})) * currencyMultiplier;
  const npvDiscPess  = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, discount_rate: discountRate + 0.02})) * currencyMultiplier;
  const npvDiscOpt   = plnToTysPln(calculateEaaSNPV({...eaasNpvBaseForMatrix, discount_rate: Math.max(0.01, discountRate - 0.02)})) * currencyMultiplier;

  console.log('📊 EaaS Tornado (recalculated):', {
    grid: [roundNum(npvGridPess, 0), roundNum(baseEaaSNpvTys, 0), roundNum(npvGridOpt, 0)],
    subs: [roundNum(npvSubsPess, 0), roundNum(baseEaaSNpvTys, 0), roundNum(npvSubsOpt, 0)],
    yield: [roundNum(npvYieldPess, 0), roundNum(baseEaaSNpvTys, 0), roundNum(npvYieldOpt, 0)],
    disc: [roundNum(npvDiscPess, 0), roundNum(baseEaaSNpvTys, 0), roundNum(npvDiscOpt, 0)]
  });

  // SUMPRODUCT formula building blocks for tornado
  const _s2e = "'EaaS Rok po Roku'!";
  const _eR = `${_s2e}$E$${dataStartRow}:$E$${lastDataRow}`;
  const _fR = `${_s2e}$F$${dataStartRow}:$F$${lastDataRow}`;
  const _bR = `${_s2e}$B$${dataStartRow}:$B$${lastDataRow}`;
  const _dR = `${_s2e}$F$4`;

  const tornadoData = [
    {
      param: 'Cena energii z sieci',
      variation: '±20%',
      pessimisticSavings: npvGridPess,
      optimisticSavings: npvGridOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eR} * 0.8\n   - ${_fR}),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      optFormula: `SUMPRODUCT(\n  (${_eR} * 1.2\n   - ${_fR}),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      pessNote: `-- NPV EaaS: cena sieci -20%\n-- E = Koszt Energii Sieci, F = Koszt EaaS\n-- B = Rok, F4 = stopa dyskontowa`,
      optNote: `-- NPV EaaS: cena sieci +20%\n-- E = Koszt Energii Sieci, F = Koszt EaaS`
    },
    {
      param: 'Stopa dyskontowa',
      variation: '±2pp',
      pessimisticSavings: npvDiscPess,
      optimisticSavings: npvDiscOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eR} - ${_fR}),\n  1 / POWER(\n    1 + ${_dR} + 0.02,\n    ${_bR}))`,
      optFormula: `SUMPRODUCT(\n  (${_eR} - ${_fR}),\n  1 / POWER(\n    1 + ${_dR} - 0.02,\n    ${_bR}))`,
      pessNote: `-- NPV EaaS: stopa dyskontowa +2pp`,
      optNote: `-- NPV EaaS: stopa dyskontowa -2pp`
    },
    {
      param: 'Yield PV (produkcja)',
      variation: '±15%',
      pessimisticSavings: npvYieldPess,
      optimisticSavings: npvYieldOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eR} * 0.85\n   - ${_fR}),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      optFormula: `SUMPRODUCT(\n  (${_eR} * 1.15\n   - ${_fR}),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      pessNote: `-- NPV EaaS: yield PV -15%`,
      optNote: `-- NPV EaaS: yield PV +15%`
    },
    {
      param: 'Cena abonamentu EaaS',
      variation: '±20%',
      pessimisticSavings: npvSubsPess,
      optimisticSavings: npvSubsOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eR}\n   - ${_fR} * 1.2),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      optFormula: `SUMPRODUCT(\n  (${_eR}\n   - ${_fR} * 0.8),\n  1 / POWER(\n    1 + ${_dR},\n    ${_bR}))`,
      pessNote: `-- NPV EaaS: abonament +20%`,
      optNote: `-- NPV EaaS: abonament -20%`
    }
  ];

  // Calculate range and sort by impact (biggest first)
  tornadoData.forEach(t => {
    t.range = Math.abs(t.optimisticSavings - t.pessimisticSavings);
  });
  tornadoData.sort((a, b) => b.range - a.range);

  // Tornado table header
  cfoRow += 2;
  const tornadoHeaderRow = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Parametr';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = 'Zmiana';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`D${cfoRow}`).value = `Pesymistyczny [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`D${cfoRow}`).font = { bold: true, color: { argb: 'FFC62828' } };
  excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`E${cfoRow}`).value = 'Bazowy';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`F${cfoRow}`).value = `Optymistyczny [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`F${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`G${cfoRow}`).value = `Rozpiętość [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`G${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };

  // Set column widths for Tornado
  excelSheet3.getColumn('D').width = 22;
  excelSheet3.getColumn('E').width = 14;
  excelSheet3.getColumn('F').width = 22;
  excelSheet3.getColumn('G').width = 20;

  // Tornado data rows with VALUES not percentages
  // When withFormulas=true, use Excel formulas referencing base NPV cell (C${kpiNpvTysRow})
  const tornadoDataStartRow = cfoRow + 1;
  tornadoData.forEach((t, idx) => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = t.param;
    excelSheet3.getCell(`C${cfoRow}`).value = t.variation;
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    // Pessimistic NPV value (tys. PLN) - SUMPRODUCT formula
    if (withFormulas) {
      excelSheet3.getCell(`D${cfoRow}`).value = {
        formula: t.pessFormula,
        result: roundNum(t.pessimisticSavings, 0)
      };
      if (t.pessNote) excelSheet3.getCell(`D${cfoRow}`).note = t.pessNote;
    } else {
      excelSheet3.getCell(`D${cfoRow}`).value = roundNum(t.pessimisticSavings, 0);
    }
    excelSheet3.getCell(`D${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FFC62828' } };
    excelSheet3.getCell(`D${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

    // Base NPV value (tys. PLN)
    if (withFormulas) {
      excelSheet3.getCell(`E${cfoRow}`).value = { formula: `$C$${kpiNpvTysRow}`, result: roundNum(baseEaaSNpvTys, 0) };
    } else {
      excelSheet3.getCell(`E${cfoRow}`).value = roundNum(baseEaaSNpvTys, 0);
    }
    excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
    excelSheet3.getCell(`E${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    // Optimistic NPV value (tys. PLN) - SUMPRODUCT formula
    if (withFormulas) {
      excelSheet3.getCell(`F${cfoRow}`).value = {
        formula: t.optFormula,
        result: roundNum(t.optimisticSavings, 0)
      };
      if (t.optNote) excelSheet3.getCell(`F${cfoRow}`).note = t.optNote;
    } else {
      excelSheet3.getCell(`F${cfoRow}`).value = roundNum(t.optimisticSavings, 0);
    }
    excelSheet3.getCell(`F${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`F${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
    excelSheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

    // Range (tys. PLN) - formula: optimistic - pessimistic
    if (withFormulas) {
      excelSheet3.getCell(`G${cfoRow}`).value = {
        formula: `F${cfoRow}-D${cfoRow}`,
        result: roundNum(t.range, 0)
      };
    } else {
      excelSheet3.getCell(`G${cfoRow}`).value = roundNum(t.range, 0);
    }
    excelSheet3.getCell(`G${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`G${cfoRow}`).font = { bold: true };

    // Borders
    for (let c = 2; c <= 7; c++) {
      excelSheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const tornadoDataEndRow = cfoRow;


  // Horizontal bar chart visualization using Unicode bars
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `📊 WYKRES TORNADO - NPV EaaS [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };

  cfoRow++;
  // Max range = first sorted item (row tornadoDataStartRow) = F - D
  const maxRangeRef = `(F${tornadoDataStartRow}-D${tornadoDataStartRow})`;
  tornadoData.forEach((t, idx) => {
    cfoRow++;
    const dataRow = tornadoDataStartRow + idx;
    // Parameter name
    excelSheet3.getCell(`B${cfoRow}`).value = t.param;
    excelSheet3.getCell(`B${cfoRow}`).font = { size: 10 };

    // Calculate bar lengths relative to max range
    const maxRange = tornadoData[0].range;
    const pessimisticDelta = t.pessimisticSavings - baseEaaSNpvTys;
    const optimisticDelta = t.optimisticSavings - baseEaaSNpvTys;

    // Red bar (pessimistic - left side)
    const redBarLen = Math.round(Math.abs(pessimisticDelta) / maxRange * 15);
    const redBar = '█'.repeat(Math.max(1, redBarLen));
    if (withFormulas) {
      excelSheet3.getCell(`C${cfoRow}`).value = {
        formula: `REPT("█",\n  MAX(1, ROUND(\n    ABS(D${dataRow} - E${dataRow})\n    / ${maxRangeRef} * 15, 0)))`,
        result: redBar
      };
    } else {
      excelSheet3.getCell(`C${cfoRow}`).value = redBar;
    }
    excelSheet3.getCell(`C${cfoRow}`).font = { color: { argb: 'FFC62828' }, size: 10 };
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'right' };

    // Values
    if (withFormulas) {
      excelSheet3.getCell(`D${cfoRow}`).value = {
        formula: `TEXT(D${dataRow},"# ##0")\n& " | " & TEXT(E${dataRow},"# ##0")\n& " | " & TEXT(F${dataRow},"# ##0")`,
        result: `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(baseEaaSNpvTys, 0)} | ${roundNum(t.optimisticSavings, 0)}`
      };
    } else {
      excelSheet3.getCell(`D${cfoRow}`).value = `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(baseEaaSNpvTys, 0)} | ${roundNum(t.optimisticSavings, 0)}`;
    }
    excelSheet3.getCell(`D${cfoRow}`).font = { size: 9 };
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // Green bar (optimistic - right side)
    const greenBarLen = Math.round(Math.abs(optimisticDelta) / maxRange * 15);
    const greenBar = '█'.repeat(Math.max(1, greenBarLen));
    if (withFormulas) {
      excelSheet3.getCell(`E${cfoRow}`).value = {
        formula: `REPT("█",\n  MAX(1, ROUND(\n    ABS(F${dataRow} - E${dataRow})\n    / ${maxRangeRef} * 15, 0)))`,
        result: greenBar
      };
    } else {
      excelSheet3.getCell(`E${cfoRow}`).value = greenBar;
    }
    excelSheet3.getCell(`E${cfoRow}`).font = { color: { argb: 'FF2E7D32' }, size: 10 };
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'left' };
  });

  // Legend
  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = '🔴 Pesymistyczny';
  excelSheet3.getCell(`B${cfoRow}`).font = { size: 9, color: { argb: 'FFC62828' } };
  excelSheet3.getCell(`C${cfoRow}`).value = '⚪ Bazowy';
  excelSheet3.getCell(`C${cfoRow}`).font = { size: 9 };
  excelSheet3.getCell(`D${cfoRow}`).value = '🟢 Optymistyczny';
  excelSheet3.getCell(`D${cfoRow}`).font = { size: 9, color: { argb: 'FF2E7D32' } };

  // --- SECTION 3: SENSITIVITY MATRIX - NPV EaaS (consistent with CAPEX) ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `MACIERZ WRAŻLIWOŚCI - NPV EaaS vs Cena Sieci${isRdnExport ? ' (RDN)' : ''} vs Yield`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  cfoRow += 2;
  const yieldVariations = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const gridPriceVariations = [-0.20, -0.10, 0, 0.10, 0.20];

  // Header
  excelSheet3.getCell(`B${cfoRow}`).value = `NPV [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  excelSheet3.mergeCells(`C${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`C${cfoRow}`).value = '← Yield PV →';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, size: 10 };
  excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  const matrixHeaderRowEaaS = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Cena sieci ↓';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    excelSheet3.getCell(cfoRow, 3 + i).value = yv;
    excelSheet3.getCell(cfoRow, 3 + i).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(cfoRow, 3 + i).font = { bold: true, size: 9 };
    excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    excelSheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data - 30-year savings — FULL RECALCULATION with non-linear self-consumption
  // Pre-compute self-consumption for each yield variation using hourly profiles
  const eaasSelfConsumptionByYield = {};
  try {
    yieldVariations.forEach(yv => {
      const sc = (typeof _computeSelfConsumptionForYield === 'function')
        ? _computeSelfConsumptionForYield(1 + yv)
        : null;
      eaasSelfConsumptionByYield[yv] = sc !== null ? kwhToMwh(sc) : autoconsumptionMwh * (1 + yv); // MWh
    });
  } catch (scErr) {
    console.warn('⚠️ EaaS self-consumption pre-compute failed, using linear fallback:', scErr);
    yieldVariations.forEach(yv => {
      eaasSelfConsumptionByYield[yv] = autoconsumptionMwh * (1 + yv);
    });
  }

  const _col = (n) => String.fromCharCode(64 + n); // 1=A, 2=B, 3=C, ...

  // Compute K_eaas (PV of all EaaS costs) — used by scenario analysis formulas
  let _K_eaas = 0;
  for (let _y = 1; _y <= (analysisPeriod || 30); _y++) {
    const _inflFactor = Math.pow(1 + inflationRate, _y - 1);
    const _eaasInflFactor = eaasIndexation === 'cpi' ? _inflFactor : 1;
    if (_y <= eaasDuration) {
      _K_eaas += baseSubscriptionCost * _eaasInflFactor / Math.pow(1 + discountRate, _y);
    } else {
      const _omCost = capacityKwp * eaasOM;
      const _insCost = capex * (window.economicsSettings?.insuranceRate || 0.005);
      _K_eaas += (_omCost + _insCost) * _inflFactor / Math.pow(1 + discountRate, _y);
    }
  }
  const _K_eaas_disp = _K_eaas * currencyMultiplier;

  gridPriceVariations.forEach(gpv => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = gpv;
    excelSheet3.getCell(`B${cfoRow}`).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
    excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
    excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      // Full NPV recalculation per cell (consistent with CAPEX calculateCapexNPV pattern)
      let adjNpv;
      try {
        adjNpv = plnToTysPln(calculateEaaSNPV({
          ...eaasNpvBaseForMatrix,
          self_consumed_annual_kwh: eaasSelfConsumptionByYield[yv] * 1000, // MWh → kWh
          total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * (1 + gpv)  // PLN/MWh → PLN/kWh with variation (RDN-aware)
        })) * currencyMultiplier; // → tys. in display currency
      } catch (npvErr) {
        console.warn('⚠️ EaaS NPV calc failed, fallback to 0:', npvErr);
        adjNpv = 0;
      }
      if (!isFinite(adjNpv)) adjNpv = 0;

      const cell = excelSheet3.getCell(cfoRow, 3 + i);
      if (withFormulas) {
        const s2e = "'EaaS Rok po Roku'!";
        const colLetter = _col(3 + i);
        const yieldRef = `${colLetter}$${matrixHeaderRowEaaS}`;
        const priceRef = `$B${cfoRow}`;
        const bRange = `${s2e}$B$${dataStartRow}:$B$${lastDataRow}`;
        const eRange = `${s2e}$E$${dataStartRow}:$E$${lastDataRow}`;
        const fCostRange = `${s2e}$F$${dataStartRow}:$F$${lastDataRow}`;
        let formula;
        if (isRdnExport) {
          const A = "'Dane bazowe TCSL (Rok 1)'!";
          const degRange = `(1-${s2e}$F$6)*POWER(1-${s2e}$F$7,${bRange}-1)`;
          const cpiRange = `POWER(1+${s2e}$F$5,${bRange}-1)`;
          formula = `SUMPRODUCT((${A}$F$18*${degRange}*(1+${yieldRef})*(1+${priceRef})*${cpiRange}+${A}$F$21*(1+${yieldRef})*${cpiRange})/1000-${fCostRange},1/POWER(1+${s2e}$F$4,${bRange}))`;
        } else {
          formula = `SUMPRODUCT((${eRange}*(1+${yieldRef})*(1+${priceRef})-${fCostRange}),1/POWER(1+${s2e}$F$4,${bRange}))`;
        }
        cell.value = { formula, result: roundNum(adjNpv, 0) };
      } else {
        cell.value = roundNum(adjNpv, 0);
      }
      cell.numFmt = '#,##0';
      cell.alignment = { horizontal: 'center' };

      // Color coding based on base EaaS NPV
      if (adjNpv > baseEaaSNpvTys * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (adjNpv > baseEaaSNpvTys * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (adjNpv > 0) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
      } else {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFCDD2' } };
        cell.font = { color: { argb: 'FFC62828' }, bold: true };
      }

      cell.border = {
        top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        right: { style: 'thin', color: { argb: 'FFE0E0E0' } }
      };
    });
  });

  // --- SECTION 4: ESG - DIRECT VALUES (no formulas to avoid cell reference issues) ---
  const co2FactorKgPerKwh = 0.7; // Polish grid average
  const annualCO2Tons = autoconsumptionMwh * co2FactorKgPerKwh; // MWh * 0.7 kg/kWh = tons
  const totalCO2Tons = annualCO2Tons * cfoPeriod * (1 - pvDegradationYears2Plus * cfoPeriod / 2);

  cfoRow += 3;
  const esgSectionRow = cfoRow;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `ESG - WPŁYW ŚRODOWISKOWY (${cfoPeriod} lat)`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF00695C' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F2F1' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Autokonsumpcja PV [MWh/rok]';
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(autoconsumptionMwh, 1);
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0.0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Energia zielona zamiast z sieci';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Współczynnik emisji sieci [t CO₂/MWh]';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `$G$${co2ParamRow}`, result: co2FactorKgPerKwh };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- Wsp. emisji z parametrów (G${co2ParamRow})`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = co2FactorKgPerKwh;
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0.0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Średnia dla Polski (2024)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow += 2;
  const annualCO2Row = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = '🌍 Redukcja CO₂ rocznie [tony]';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    // CO2 annual = Autokonsumpcja (C_autoParamRow) × CO2 factor (G_co2ParamRow)
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND(\n  $C$${autoParamRow} * $G$${co2ParamRow},\n  0)`, result: roundNum(annualCO2Tons, 0) };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- Autokonsumpcja × emisyjność\n-- C${autoParamRow} = MWh/rok, G${co2ParamRow} = t CO₂/MWh`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = `= Autokonsumpcja × ${co2FactorKgPerKwh} t/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRow++;
  const totalCO2Row = cfoRow;  // Store for decision summary formulas
  excelSheet3.getCell(`B${cfoRow}`).value = `🌍 Redukcja CO₂ (${cfoPeriod} lat) [tony]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    // Total CO2 = annual × period × avg degradation factor
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND(\n  $C$${annualCO2Row} * ${cfoPeriod}\n  * $C$${degradFactorParamRow},\n  0)`, result: roundNum(totalCO2Tons, 0) };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- CO₂ roczne × lata × śr. degradacja\n-- C${annualCO2Row} = tony/rok, C${degradFactorParamRow} = wsp. degradacji`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(totalCO2Tons, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Całkowity wpływ projektu (z degradacją)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = '🚗 Ekwiwalent samochodów';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND($C$${annualCO2Row}/4.6,0)`, result: roundNum(annualCO2Tons / 4.6, 0) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 4.6, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Roczna emisja tylu aut osobowych';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '🌳 Ekwiwalent drzew';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND($C$${annualCO2Row}/0.022,0)`, result: roundNum(annualCO2Tons / 0.022, 0) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 0.022, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Drzew potrzebnych do pochłonięcia CO₂';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '✈️ Ekwiwalent lotów WAW-LON';
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `ROUND($C$${annualCO2Row}/0.255,0)`, result: roundNum(annualCO2Tons / 0.255, 0) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 0.255, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Lotów w klasie ekonomicznej';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Add borders to ESG section
  for (let r = esgSectionRow + 1; r <= cfoRow; r++) {
    excelSheet3.getRow(r).getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    excelSheet3.getRow(r).getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // --- SECTION 5: BREAK-EVEN ANALYSIS - Full 30-year NPV-based ---
  // Break-even = grid price where NPV = 0 over full analysis period
  // NPV = SUMPRODUCT(E_savings - F_costs, discount_factors) = 0
  // breakEvenPrice = gridPrice × PV(costs) / PV(savings)
  let pvSavings = 0, pvCosts = 0;
  for (let yr = 1; yr <= (analysisPeriod || 30); yr++) {
    const deg = Math.pow(1 - pvDegradationYears2Plus, yr - 1);
    const cpi = Math.pow(1 + inflationRate, yr - 1);
    const disc = Math.pow(1 + discountRate, yr);
    pvSavings += plnToTysPln(autoconsumptionMwh * gridPriceDisplay) * deg * cpi / disc;
    let cost;
    if (yr <= eaasDuration) {
      const eaasInfl = eaasIndexation === 'cpi' ? cpi : 1;
      cost = plnToTysPln(baseSubscriptionCost) * eaasInfl;
    } else {
      cost = plnToTysPln(capacityKwp * eaasOM + capex * (window.economicsSettings?.insuranceRate || 0.005)) * cpi;
    }
    pvCosts += cost / disc;
  }
  const breakEvenGridPrice = pvSavings > 0 ? gridPriceDisplay * pvCosts / pvSavings : eaasPriceDisplay;
  const safetyMarginPct = (gridPriceDisplay - breakEvenGridPrice) / gridPriceDisplay;

  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'ANALIZA BREAK-EVEN';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FFE65100' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Przy jakiej cenie energii z sieci EaaS przestaje się opłacać?';
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet3.mergeCells(`B${cfoRow}:G${cfoRow}`);

  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Obecna cena energii z sieci';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = gridPriceDisplay;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`D${cfoRow}`).value = `${currencyLabel}/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Cena EaaS (abonament)';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = eaasPriceDisplay;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`D${cfoRow}`).value = `${currencyLabel}/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF757575' } };

  cfoRow++;
  const breakEvenRow = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = `⚠️ BREAK-EVEN: Cena sieci (${cfoPeriod} lat)`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    // Break-even = gridPrice × PV(costs) / PV(savings) = C_gridPriceRow × SUMPRODUCT(F/disc) / SUMPRODUCT(E/disc)
    const _s2be = "'EaaS Rok po Roku'!";
    const beFormula = `$C$${gridPriceParamRow}\n* SUMPRODUCT(\n    ${_s2be}$F$${dataStartRow}:$F$${lastDataRow}\n    / POWER(1 + ${_s2be}$F$4,\n            ${_s2be}$B$${dataStartRow}:$B$${lastDataRow}))\n/ SUMPRODUCT(\n    ${_s2be}$E$${dataStartRow}:$E$${lastDataRow}\n    / POWER(1 + ${_s2be}$F$4,\n            ${_s2be}$B$${dataStartRow}:$B$${lastDataRow}))`;
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: beFormula, result: roundNum(breakEvenGridPrice, 0) };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- Cena sieci przy NPV=0 (${cfoPeriod} lat)\n-- cena × PV(koszty_EaaS) / PV(koszty_sieci)`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(breakEvenGridPrice, 0);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  excelSheet3.getCell(`D${cfoRow}`).value = `${currencyLabel}/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF757575' } };
  excelSheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`E${cfoRow}`).value = `Cena sieci przy NPV=0 (pełne ${cfoPeriod} lat z własnością)`;
  excelSheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '🛡️ Margines bezpieczeństwa';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `($C$${gridPriceParamRow} - C${breakEvenRow})\n/ $C$${gridPriceParamRow}`, result: safetyMarginPct };
    excelSheet3.getCell(`C${cfoRow}`).note = `-- (cena_sieci - break_even) / cena_sieci`;
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = safetyMarginPct;
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0.0%';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' }, size: 12 };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.mergeCells(`D${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Ile musi spaść cena sieci, żeby EaaS przestało się opłacać';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- SECTION 6: SCENARIO ANALYSIS ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'ANALIZA SCENARIUSZY';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `Projekcja NPV ${cfoPeriod} lat przy różnych założeniach:`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet3.mergeCells(`B${cfoRow}:G${cfoRow}`);

  // Scenario headers
  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Scenariusz';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).value = 'Cena sieci';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`D${cfoRow}`).value = 'Yield PV';
  excelSheet3.getCell(`D${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`E${cfoRow}`).value = `NPV [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`F${cfoRow}`).value = 'Prawdop.';
  excelSheet3.getCell(`F${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`G${cfoRow}`).value = 'Ważona wart.';
  excelSheet3.getCell(`G${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };

  // Scenario data
  const scenarios = [
    { name: '😟 Pesymistyczny', gridMult: 0.85, yieldMult: 0.90, prob: 0.15, color: 'FFC62828', bgColor: 'FFFFEBEE' },
    { name: '📊 Bazowy', gridMult: 1.0, yieldMult: 1.0, prob: 0.50, color: 'FF1565C0', bgColor: 'FFE3F2FD' },
    { name: '🚀 Optymistyczny', gridMult: 1.15, yieldMult: 1.05, prob: 0.25, color: 'FF2E7D32', bgColor: 'FFE8F5E9' },
    { name: '🔥 Boom energetyczny', gridMult: 1.30, yieldMult: 1.0, prob: 0.10, color: 'FFE65100', bgColor: 'FFFFF3E0' }
  ];

  const scenarioStartRow = cfoRow + 1;
  // K_eaas in display currency (thousands) — for corrected scenario formula
  const _K_eaas_tys = plnToTysPln(_K_eaas_disp);
  console.log('📊 Scenarios - baseEaaSNpvTys:', roundNum(baseEaaSNpvTys, 0), 'K_eaas_tys:', roundNum(_K_eaas_tys, 0));

  // Pre-compute non-linear self-consumption for each scenario yield level (hourly profile-based)
  const scenarioSCbyYield = {};
  scenarios.forEach(s => {
    if (s.yieldMult === 1.0) {
      scenarioSCbyYield[s.yieldMult] = autoconsumptionMwh * 1000; // kWh
    } else {
      const sc = (typeof _computeSelfConsumptionForYield === 'function')
        ? _computeSelfConsumptionForYield(s.yieldMult) : null;
      scenarioSCbyYield[s.yieldMult] = sc !== null ? sc : autoconsumptionMwh * 1000 * s.yieldMult;
    }
  });
  console.log('📊 Scenario SC (non-linear):', Object.fromEntries(Object.entries(scenarioSCbyYield).map(([k,v]) => [k, roundNum(v, 0)])));

  scenarios.forEach((s, idx) => {
    cfoRow++;
    // Full NPV recalculation per scenario with non-linear self-consumption
    let scenarioSavings;
    if (s.gridMult === 1.0 && s.yieldMult === 1.0) {
      scenarioSavings = baseEaaSNpvTys;
    } else {
      try {
        scenarioSavings = plnToTysPln(calculateEaaSNPV({
          ...eaasNpvBaseForMatrix,
          self_consumed_annual_kwh: scenarioSCbyYield[s.yieldMult] || autoconsumptionMwh * 1000 * s.yieldMult,
          total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * s.gridMult  // RDN-aware
        })) * currencyMultiplier;
      } catch (e) {
        scenarioSavings = baseEaaSNpvTys * s.yieldMult * s.gridMult;
      }
    }
    const weightedValue = scenarioSavings * s.prob;
    console.log(`📊 Scenario ${s.name}:`, { gridMult: s.gridMult, yieldMult: s.yieldMult, sc_kwh: roundNum(scenarioSCbyYield[s.yieldMult], 0), scenarioNpv: roundNum(scenarioSavings, 0) });

    excelSheet3.getCell(`B${cfoRow}`).value = s.name;
    excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, color: { argb: s.color } };

    excelSheet3.getCell(`C${cfoRow}`).value = s.gridMult - 1;
    excelSheet3.getCell(`C${cfoRow}`).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    excelSheet3.getCell(`D${cfoRow}`).value = s.yieldMult - 1;
    excelSheet3.getCell(`D${cfoRow}`).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // Oszczędności - use formula or value
    // K_eaas = PV of all EaaS/ownership costs = SUMPRODUCT(F_range/POWER(1+disc,B_range))
    if (withFormulas) {
      const _s2sc = "'EaaS Rok po Roku'!";
      const kEaasFormula = `SUMPRODUCT(\n    ${_s2sc}$F$${dataStartRow}:$F$${lastDataRow}\n    / POWER(1 + ${_s2sc}$F$4,\n            ${_s2sc}$B$${dataStartRow}:$B$${lastDataRow}))`;
      excelSheet3.getCell(`E${cfoRow}`).value = { formula: `ROUND(\n  ($C$${kpiNpvTysRow} + ${kEaasFormula})\n  * (1 + C${cfoRow}) * (1 + D${cfoRow})\n  - ${kEaasFormula},\n  0)`, result: roundNum(scenarioSavings, 0) };
      excelSheet3.getCell(`E${cfoRow}`).note = `-- NPV przy zmianach yield/cena\n-- K_eaas = PV kosztów EaaS\n-- (NPV+K)×mnożniki - K`;
    } else {
      excelSheet3.getCell(`E${cfoRow}`).value = roundNum(scenarioSavings, 0);
    }
    excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: s.color } };
    excelSheet3.getCell(`E${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: s.bgColor } };

    excelSheet3.getCell(`F${cfoRow}`).value = s.prob;
    excelSheet3.getCell(`F${cfoRow}`).numFmt = '0%';
    excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };

    // Ważona wartość - use formula or value
    if (withFormulas) {
      excelSheet3.getCell(`G${cfoRow}`).value = { formula: `ROUND(E${cfoRow}*F${cfoRow},0)`, result: roundNum(weightedValue, 0) };
    } else {
      excelSheet3.getCell(`G${cfoRow}`).value = roundNum(weightedValue, 0);
    }
    excelSheet3.getCell(`G${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`G${cfoRow}`).alignment = { horizontal: 'center' };

    for (let c = 2; c <= 7; c++) {
      excelSheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const scenarioEndRow = cfoRow;

  // Expected value (weighted average)
  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '📈 WARTOŚĆ OCZEKIWANA';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  excelSheet3.mergeCells(`C${cfoRow}:D${cfoRow}`);
  excelSheet3.getCell(`C${cfoRow}`).value = 'Suma ważona scenariuszy';
  excelSheet3.getCell(`C${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`E${cfoRow}`).value = { formula: `SUM(G${scenarioStartRow}:G${scenarioEndRow})` };
  excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  excelSheet3.getCell(`E${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };
  excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`F${cfoRow}`).value = { formula: `SUM(F${scenarioStartRow}:F${scenarioEndRow})` };
  excelSheet3.getCell(`F${cfoRow}`).numFmt = '0%';
  excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`F${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`G${cfoRow}`).value = `tys. ${currencyLabel}`;
  excelSheet3.getCell(`G${cfoRow}`).font = { color: { argb: 'FF757575' } };

  // --- SECTION 7: INFLATION SENSITIVITY (full NPV recalculation) ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'WRAŻLIWOŚĆ NA INFLACJĘ CEN ENERGII';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `Jak zmienia się NPV EaaS ${cfoPeriod} lat przy różnej inflacji cen energii:`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);

  // Inflation scenarios — include base inflation in array
  const baseInflation = inflationRate; // from centralizedCalc.common.inflationRate
  const inflationRates = [0, 0.02, 0.025, 0.03, 0.05, 0.07, 0.10];
  // Find base inflation index (exact match after including it)
  const baseInflIdx = inflationRates.findIndex(r => Math.abs(r - baseInflation) < 0.002);

  cfoRow += 2;
  const inflHeaderRow = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Roczna inflacja cen energii';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  inflationRates.forEach((inf, i) => {
    excelSheet3.getCell(cfoRow, 3 + i).value = inf;
    excelSheet3.getCell(cfoRow, 3 + i).numFmt = '0.0%';
    excelSheet3.getCell(cfoRow, 3 + i).font = { bold: true };
    excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    excelSheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRow++;
  const inflValuesRow = cfoRow;
  excelSheet3.getCell(`B${cfoRow}`).value = `NPV [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };

  // Pre-compute NPV for each inflation rate (for result values)
  const inflNpvValues = [];
  inflationRates.forEach((inf) => {
    const npvPLN = calculateEaaSNPV({
      ...eaasNpvBaseForMatrix,
      inflation_rate: inf
    });
    inflNpvValues.push(plnToTysPln(npvPLN) * currencyMultiplier);
  });

  cfoRow++;
  const inflValuesRowActual = cfoRow;

  // SUMPRODUCT formula building blocks for inflation sensitivity
  const _s2inf = "'EaaS Rok po Roku'!";
  const _eInf = `${_s2inf}$E$${dataStartRow}:$E$${lastDataRow}`;
  const _fInf = `${_s2inf}$F$${dataStartRow}:$F$${lastDataRow}`;
  const _bInf = `${_s2inf}$B$${dataStartRow}:$B$${lastDataRow}`;
  const _discInf = `${_s2inf}$F$4`;
  const _baseInflRef = `${_s2inf}$F$5`;

  inflationRates.forEach((inf, i) => {
    const inflNpv = inflNpvValues[i];
    const cell = excelSheet3.getCell(cfoRow, 3 + i);
    const colLetter = _col(3 + i);

    if (withFormulas) {
      // SUMPRODUCT: adjust savings E by inflation ratio (1+inf_new)/(1+inf_base) per year, keep costs F unchanged
      const formula = `SUMPRODUCT(\n  (${_eInf}\n   * POWER(\n       (1 + ${colLetter}$${inflHeaderRow}) / (1 + ${_baseInflRef}),\n       ${_bInf} - 1)\n   - ${_fInf}),\n  1 / POWER(1 + ${_discInf}, ${_bInf}))`;
      cell.value = { formula, result: roundNum(inflNpv, 0) };
      cell.note = `-- NPV przy inflacji ${colLetter}$${inflHeaderRow}\n-- E×(1+infl)^rok / dyskonto - F`;
    } else {
      cell.value = roundNum(inflNpv, 0);
    }
    cell.numFmt = '#,##0';
    cell.alignment = { horizontal: 'center' };
    cell.font = { bold: true };

    // Color coding
    const isBase = Math.abs(inf - baseInflation) < 0.002;
    if (isBase) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      cell.font = { bold: true, color: { argb: 'FF1565C0' } };
    } else if (inf === 0) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
    } else if (inf <= 0.03) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      cell.font = { bold: true, color: { argb: 'FF2E7D32' } };
    } else {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
      cell.font = { bold: true, color: { argb: 'FF1B5E20' } };
    }
  });

  console.log('📊 Inflation sensitivity (full NPV):', inflationRates.map((r, i) => `${(r*100).toFixed(1)}%: ${roundNum(inflNpvValues[i], 0)}`).join(', '));

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `vs bazowa inflacja ${decimalToPct(baseInflation).toFixed(1)}%`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };

  // Percentage change vs base inflation NPV
  const baseInflNpv = baseInflIdx >= 0 ? inflNpvValues[baseInflIdx] : baseEaaSNpvTys;
  const baseInflColLetter = baseInflIdx >= 0 ? _col(3 + baseInflIdx) : null;
  inflationRates.forEach((inf, i) => {
    const isBase = Math.abs(inf - baseInflation) < 0.002;
    if (isBase) {
      excelSheet3.getCell(cfoRow, 3 + i).value = '-';
      excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    } else {
      const pctChange = baseInflNpv !== 0 ? (inflNpvValues[i] - baseInflNpv) / Math.abs(baseInflNpv) : 0;
      const colLetter = _col(3 + i);
      if (withFormulas && baseInflColLetter) {
        excelSheet3.getCell(cfoRow, 3 + i).value = {
          formula: `(${colLetter}${inflValuesRowActual}-${baseInflColLetter}${inflValuesRowActual})/${baseInflColLetter}${inflValuesRowActual}`,
          result: pctChange
        };
      } else {
        excelSheet3.getCell(cfoRow, 3 + i).value = pctChange;
      }
      excelSheet3.getCell(cfoRow, 3 + i).numFmt = '+0%;-0%';
      excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
      excelSheet3.getCell(cfoRow, 3 + i).font = { color: { argb: pctChange >= 0 ? 'FF2E7D32' : 'FFC62828' } };
    }
  });

  // --- SECTION 8: DECISION SUMMARY ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'PODSUMOWANIE DECYZJI - EaaS vs STATUS QUO';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF283593' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8EAF6' } };

  cfoRow += 2;
  // Header
  excelSheet3.getCell(`B${cfoRow}`).value = 'Kryterium';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = 'EaaS';
  excelSheet3.getCell(`D${cfoRow}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`E${cfoRow}`).value = 'Status Quo';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
  excelSheet3.getCell(`F${cfoRow}`).value = 'Wygrywa';
  excelSheet3.getCell(`F${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };

  // Decision criteria
  // CO2 factor: 0.7 t CO₂/MWh (Polish grid average)
  const co2FactorTonPerMwh = 0.7;
  const totalCO2Reduction = roundNum(autoconsumptionMwh * co2FactorTonPerMwh * cfoPeriod * degradationFactor30, 0);

  // Decision rows with formulas for dynamic rows
  const decisions = [
    { criterion: 'Nakład inwestycyjny (CAPEX)', eaas: '0 PLN', statusQuo: '0 PLN', winner: 'Remis', winColor: 'FF757575', useFormula: false },
    { criterion: `Koszt energii ${cfoPeriod} lat`, eaas: `${roundNum(plnToTysPln(autoconsumptionMwh * eaasPriceDisplay * cfoPeriod * degradationFactor30), 0)} tys.`, statusQuo: `${roundNum(plnToTysPln(autoconsumptionMwh * gridPriceDisplay * cfoPeriod * degradationFactor30), 0)} tys.`, winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'energyCost' },
    { criterion: `Oszczędności ${cfoPeriod} lat`, eaas: `${roundNum(tornadoBaseSavings30, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'savings' },
    { criterion: 'Ryzyko techniczne', eaas: 'Dostawca', statusQuo: 'Brak instalacji', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Ryzyko cenowe', eaas: 'Częściowe zabezp.', statusQuo: '100% ekspozycji', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Wpływ na bilans', eaas: 'Off-balance', statusQuo: 'Brak', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Zielona energia', eaas: 'TAK', statusQuo: 'NIE', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Redukcja CO₂', eaas: `${totalCO2Reduction} ton`, statusQuo: '0 ton', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'co2' }
  ];

  const _s2dec = "'EaaS Rok po Roku'!";
  const decisionFirstRow = cfoRow + 1;
  decisions.forEach(d => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = d.criterion;
    excelSheet3.mergeCells(`B${cfoRow}:C${cfoRow}`);

    // D column (EaaS value) — formulas matching reference ROUND pattern
    if (withFormulas && d.useFormula) {
      if (d.formulaType === 'savings') {
        excelSheet3.getCell(`D${cfoRow}`).value = { formula: `ROUND($C$${kpiTotalTysRow},0)\n&" tys. PLN"`, result: d.eaas };
      } else if (d.formulaType === 'energyCost') {
        excelSheet3.getCell(`D${cfoRow}`).value = {
          formula: `ROUND(\n  SUM(${_s2dec}F${dataStartRow}:${_s2dec}F${lastDataRow}),\n  0)\n&" tys."`,
          result: d.eaas
        };
      } else if (d.formulaType === 'co2') {
        excelSheet3.getCell(`D${cfoRow}`).value = { formula: `ROUND($C$${totalCO2Row},0)\n&" ton"`, result: d.eaas };
      }
    } else {
      excelSheet3.getCell(`D${cfoRow}`).value = d.eaas;
    }
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };

    // E column (Status Quo value) — formulas when applicable
    if (withFormulas && d.useFormula && d.formulaType === 'energyCost') {
      excelSheet3.getCell(`E${cfoRow}`).value = {
        formula: `ROUND(\n  SUM(${_s2dec}E${dataStartRow}:${_s2dec}E${lastDataRow}),\n  0)\n&" tys."`,
        result: d.statusQuo
      };
    } else {
      excelSheet3.getCell(`E${cfoRow}`).value = d.statusQuo;
    }
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`E${cfoRow}`).font = { color: { argb: 'FF757575' } };

    // F column (Winner) — formulas when applicable
    if (withFormulas && d.useFormula) {
      if (d.formulaType === 'savings') {
        excelSheet3.getCell(`F${cfoRow}`).value = { formula: `IF($C$${kpiTotalTysRow}>0,\n  "EaaS","Status Quo")`, result: d.winner };
      } else if (d.formulaType === 'energyCost') {
        excelSheet3.getCell(`F${cfoRow}`).value = {
          formula: `IF(\n  SUM(${_s2dec}F${dataStartRow}:${_s2dec}F${lastDataRow})\n  < SUM(${_s2dec}E${dataStartRow}:${_s2dec}E${lastDataRow}),\n  "EaaS","Status Quo")`,
          result: d.winner
        };
      } else if (d.formulaType === 'co2') {
        excelSheet3.getCell(`F${cfoRow}`).value = { formula: `IF($C$${totalCO2Row}>0,\n  "EaaS","Status Quo")`, result: d.winner };
      }
    } else {
      excelSheet3.getCell(`F${cfoRow}`).value = d.winner;
    }
    excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`F${cfoRow}`).font = { bold: true, color: { argb: d.winColor } };

    if (d.winner === 'EaaS') {
      excelSheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    }

    for (let c = 2; c <= 6; c++) {
      excelSheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const decisionLastRow = cfoRow;
  const eaasWinCount = decisions.filter(d => d.winner === 'EaaS').length;

  // Final verdict — dynamic COUNTIF formula
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);
  if (withFormulas) {
    const fRange = `F${decisionFirstRow}:F${decisionLastRow}`;
    const nCriteria = decisions.length;
    excelSheet3.getCell(`B${cfoRow}`).value = {
      formula: `IF(\n  COUNTIF(${fRange},"EaaS")\n  > COUNTIF(${fRange},"Status Quo"),\n  "✅ REKOMENDACJA: Model EaaS - wygrywa w "\n  & COUNTIF(${fRange},"EaaS")\n  & " z ${nCriteria} kryteriów",\n  "⛔ REKOMENDACJA: Status Quo - wygrywa w "\n  & COUNTIF(${fRange},"Status Quo")\n  & " z ${nCriteria} kryteriów")`,
      result: `✅ REKOMENDACJA: Model EaaS - wygrywa w ${eaasWinCount} z ${nCriteria} kryteriów`
    };
  } else {
    excelSheet3.getCell(`B${cfoRow}`).value = `✅ REKOMENDACJA: Model EaaS - wygrywa w ${eaasWinCount} z ${decisions.length} kryteriów`;
  }
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
  excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);
  // Use formula for final summary when withFormulas=true
  if (withFormulas) {
    excelSheet3.getCell(`B${cfoRow}`).value = { formula: `"Oczekiwana oszczędność: "\n&ROUND($C$${kpiTotalTysRow},0)\n&" tys. ${currencyLabel} przez ${cfoPeriod} lat bez nakładów CAPEX"` };
  } else {
    excelSheet3.getCell(`B${cfoRow}`).value = `Oczekiwana oszczędność: ${roundNum(tornadoBaseSavings30, 0)} tys. ${currencyLabel} przez ${cfoPeriod} lat bez nakładów CAPEX`;
  }
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  // --- FOOTER ---
  cfoRow += 3;
  excelSheet3.getCell(`B${cfoRow}`).value = `Wygenerowano: ${new Date().toLocaleDateString('pl-PL')} | Pagra Energy Studio`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);

  console.log(`✅ Sheet 3: Analiza CFO created (${cfoPeriod} years, formulas, tornado chart)`);

  // ============================================================================
  // === ENGLISH VERSIONS OF ALL SHEETS ===
  // ============================================================================

  // --- SHEET 4: EaaS Summary (English) ---
  const excelSheet4 = excelWorkbook.addWorksheet('EaaS Summary');
  excelSheet4.columns = [
    { width: 3 },   // A: margin column (empty)
    { width: 38 },  // B: labels
    { width: 22 }   // C: values
  ];
  excelSheet4.views = [{ showGridLines: false, showRowColHeaders: false }];

  // English summary data
  const summaryDataEN = [
    [''],  // Row 1 - logo area
    [''],  // Row 2 - logo area
    ['EaaS ANALYSIS (Energy-as-a-Service)'],  // Row 3 - title
    [''],
    ['INSTALLATION DATA'],
    ['System capacity [kWp]:', roundNum(capacityKwp, 0)],
    ['Annual facility consumption [MWh]:', roundNum(annualConsumptionMwh, 1)],
    ['PV self-consumption [MWh]:', roundNum(autoconsumptionMwh, 1)],
    ['Consumption coverage [%]:', roundNum((autoconsumptionMwh / annualConsumptionMwh) * 100, 1)],
    [''],
    ['EaaS CONTRACT PARAMETERS'],
    [`EaaS subscription [${currencyLabel}/year]:`, roundNum(eaasSubscriptionDisplay, 0)],
    ['Analysis period [years]:', analysisPeriod],
    [currencyInfoLabel === 'Waluta:' ? 'Currency:' : 'Currency EUR:', currencyInfoValue === 'PLN (krajowy)' ? 'PLN (domestic)' : currencyInfoValue],
    [''],
    ['TARIFF COMPONENTS [PLN/MWh]'],
    ['Active energy:', roundNum(tariffComponents.energyActive, 0)],
    ['Distribution:', roundNum(tariffComponents.distribution, 0)],
    ['Quality fee:', roundNum(tariffComponents.quality, 0)],
    ['RES fee:', roundNum(tariffComponents.oze, 0)],
    ['Cogeneration fee:', roundNum(tariffComponents.cogeneration, 0)],
    ['Capacity fee:', roundNum(tariffComponents.capacity, 0)],
    ['Excise duty:', roundNum(tariffComponents.excise, 0)],
    [''],
    ['CUSTOMER BENEFITS'],
    [`Grid energy price [${currencyLabel}/MWh]:`, roundNum(gridPriceDisplay, 2)],
    [`Effective EaaS price [${currencyLabel}/MWh]:`, roundNum(eaasPriceDisplay, 2)],
    [`Price difference [${currencyLabel}/MWh]:`, roundNum(priceDiffDisplay, 2)],
    ['Savings percentage [%]:', roundNum((result.metrics.priceDifferencePLNperKWh / result.metrics.gridPricePLNperKWh) * 100, 1)],
    [''],
    [`Annual savings [k${currencyLabel}]:`, roundNum(annualSavingsDisplay, 1)]
  ];

  summaryDataEN.forEach((row, idx) => {
    const excelRow = excelSheet4.getRow(idx + 1);
    row.forEach((cell, colIdx) => {
      excelRow.getCell(colIdx + 2).value = cell;
    });
  });

  // Style Sheet 4 (same as Sheet 1)
  excelSheet4.mergeCells('B1:C3');
  excelSheet4.getRow(1).height = 20;
  excelSheet4.getRow(2).height = 20;
  excelSheet4.getRow(3).height = 24;
  const headerCell4 = excelSheet4.getCell('B1');
  headerCell4.value = `EaaS ANALYSIS${window._rdnExportMode ? ' (RDN prices)' : ''} (Energy-as-a-Service) - Scenario ${scenarioName}`;
  headerCell4.font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  headerCell4.alignment = { horizontal: 'center', vertical: 'bottom' };
  if (logoImageId !== null) {
    excelSheet4.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }
  const sectionHeaders4 = [5, 11, 16, 25];
  sectionHeaders4.forEach(rowNum => {
    const row = excelSheet4.getRow(rowNum);
    row.getCell(2).font = { bold: true, size: 11, color: { argb: 'FF2E7D32' } };
    row.getCell(2).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    row.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  });
  for (let r = 6; r <= 9; r++) {
    const row = excelSheet4.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }
  for (let r = 12; r <= 14; r++) {
    const row = excelSheet4.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }
  for (let r = 17; r <= 23; r++) {
    const row = excelSheet4.getRow(r);
    row.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    row.getCell(3).alignment = { horizontal: 'right' };
  }
  const savingsRows4 = [29, 31];
  savingsRows4.forEach(rowNum => {
    const row = excelSheet4.getRow(rowNum);
    if (row.getCell(2).value) {
      row.getCell(2).font = { bold: true, color: { argb: 'FF2E7D32' } };
      row.getCell(3).font = { bold: true, color: { argb: 'FF2E7D32' } };
      row.getCell(3).alignment = { horizontal: 'right' };
    }
  });
  excelSheet4.views = [{ state: 'frozen', ySplit: 3, showGridLines: false, showRowColHeaders: false }];
  console.log('✅ Sheet 4: EaaS Summary (EN) created');

  // --- SHEET 5: EaaS Year by Year (English) ---
  const excelSheet5 = excelWorkbook.addWorksheet('EaaS Year by Year');
  excelSheet5.columns = [
    { width: 3 },   // A: margin
    { width: 5 },   // B: Year
    { width: 36 },  // C: Phase / PARAMETERS
    { width: 14 },  // D: Self-consumption
    { width: 12 },  // E: Grid Cost
    { width: 14 },  // F: EaaS/Ownership Cost
    { width: 13 },  // G: Savings
    { width: 15 },  // H: Discounted CF
    { width: 18 }   // I: Cumulative NPV
  ];
  excelSheet5.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Copy structure from Sheet 2 with English labels
  // Row 1: Title
  excelSheet5.getRow(1).getCell(3).value = `EaaS${window._rdnExportMode ? ' (RDN prices)' : ''} YEAR BY YEAR ANALYSIS WITH NPV - Scenario ${scenarioName}`;
  excelSheet5.getRow(1).getCell(3).font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  excelSheet5.getRow(1).height = 22;

  // Row 3: PARAMETERS header
  excelSheet5.mergeCells('C3:E3');
  excelSheet5.getRow(3).getCell(3).value = 'PARAMETERS: ';
  excelSheet5.getRow(3).getCell(3).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  excelSheet5.getRow(3).getCell(3).alignment = { horizontal: 'right', vertical: 'middle' };

  // Parameters rows 4-15 (English)
  const paramsEN = [
    ['Discount rate:', roundNum(discountRate, 4)],
    ['Inflation:', roundNum(inflationRate, 4)],
    ['PV degradation Year 1:', roundNum(pvDegradationYear1, 4)],
    ['PV degradation Years 2+:', roundNum(pvDegradationYears2Plus, 4)],
    ['EaaS contract period [years]:', eaasDuration],
    ['Analysis period [years]:', analysisPeriod],
    ['Base self-consumption [MWh]:', roundNum(baseAutoconsumptionMwh, 2)],
    [isRdnExport ? `RDN gross savings Yr1 [k${currencyLabel}]:` : `Base grid price [${currencyLabel}/MWh]:`, isRdnExport ? roundNum(plnToTysPln((rdnBLEaas ? rdnBLEaas.totalSavingsYear1 : 0) * currencyMultiplier), 2) : roundNum(totalEnergyPriceDisplay, 2)],
    [`EaaS subscription [k${currencyLabel}/year]:`, roundNum(baseSubscriptionDisplay, 2)],
    [`O&M + Insurance (ownership year 1) [k${currencyLabel}/year]:`, roundNum(omAtOwnershipYear1, 2)],
    ['EaaS indexation:', eaasIndexation === 'cpi' ? 'CPI indexed' : 'Fixed rate'],
    [currencyInfoLabel === 'Waluta:' ? 'Currency:' : 'Currency EUR:', currencyInfoValue === 'PLN (krajowy)' ? 'PLN (domestic)' : currencyInfoValue]
  ];

  paramsEN.forEach((param, idx) => {
    const r = 4 + idx;
    excelSheet5.mergeCells(`C${r}:E${r}`);
    const row = excelSheet5.getRow(r);
    row.getCell(3).value = param[0] + ' ';
    row.getCell(3).font = { color: { argb: 'FF616161' } };
    row.getCell(3).alignment = { horizontal: 'right', vertical: 'middle' };
    row.getCell(6).value = param[1];
    row.getCell(6).font = { bold: true, color: { argb: 'FF1976D2' } };
    row.getCell(6).alignment = { horizontal: 'left', vertical: 'middle' };
    if (idx < 4) {
      row.getCell(6).numFmt = '0.00%';
    }
    row.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
    row.getCell(6).border = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };
  });

  // RDN cross-sheet formulas for English sheet F11
  if (isRdnExport) {
    const AUDIT_EN = "'Dane bazowe TCSL (Rok 1)'!";
    excelSheet5.getCell('F11').value = { formula: `${AUDIT_EN}F31/1000`, result: excelSheet5.getCell('F11').value };
    excelSheet5.getCell('F11').numFmt = '#,##0.00';
  }

  // Row 17: Header row (English)
  const headerRowEN = excelSheet5.getRow(17);
  headerRowEN.height = 40;
  const headersEN = ['', 'Year', 'Phase', `Self-consumption [MWh]`, isRdnExport ? `RDN Gross Savings [k${currencyLabel}]` : `Grid Energy Cost [k${currencyLabel}]`, `EaaS/Ownership Cost [k${currencyLabel}]`, `Savings [k${currencyLabel}]`, `Discounted CF [k${currencyLabel}]`, `Cumulative NPV [M${currencyLabel}]`];
  headersEN.forEach((h, i) => {
    if (i === 0) return;
    const cell = headerRowEN.getCell(i + 1);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF37474F' } };
    cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 9 };
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  // Column header notes (Sheet 5 EN) — explain formulas in each column
  if (withFormulas) {
    excelSheet5.getCell('D17').note = `-- Base × (1-degY1) × (1-degY2+)^(year-1)`;
    excelSheet5.getCell('E17').note = `-- Self-consumption × grid_price / 1000\n-- × (1+inflation)^(year-1)`;
    excelSheet5.getCell('F17').note = `-- EaaS phase: subscription\n-- Ownership phase: O&M + insurance`;
    excelSheet5.getCell('G17').note = `-- Grid_Cost - EaaS_Cost`;
    excelSheet5.getCell('H17').note = `-- Savings / (1+r)^year`;
    excelSheet5.getCell('I17').note = `-- Running total of CF / 1000 [M PLN]`;
  }

  // Copy data rows from Sheet 2 (rows 18 onwards)
  const dataStartRowEN = 18;
  for (let year = 1; year <= analysisPeriod; year++) {
    const srcRow = excelSheet2.getRow(dataStartRow + year - 1);
    const destRow = excelSheet5.getRow(dataStartRowEN + year - 1);
    const yearData = eaasCashFlows[year - 1];
    const phase = yearData?.phase || (year <= eaasDuration ? 'eaas' : 'ownership');

    // Copy values from Sheet 2 but translate phase
    const destRowNum = dataStartRowEN + year - 1;
    destRow.getCell(2).value = year;
    destRow.getCell(3).value = { formula: `IF(B${destRowNum}<=$F$8,"EaaS","Ownership")`, result: phase === 'eaas' ? 'EaaS' : 'Ownership' };
    destRow.getCell(3).font = { color: { argb: phase === 'eaas' ? 'FF1565C0' : 'FF2E7D32' } };

    // Copy numeric values from source row (Sheet 2 has 11 data cols, EN has 6)
    // Map: EN dest col → Sheet 2 source col (ExcelJS cell indices)
    const colMap = [[4, 6], [5, 8], [6, 9], [7, 10], [8, 11], [9, 12]];
    // dest 4=Self-consumption←src 6=Autokonsumpcja, dest 5=GridCost←src 8=Oszczędność PV,
    // dest 6=EaaS←src 9, dest 7=Savings←src 10, dest 8=DiscCF←src 11, dest 9=NPV←src 12
    for (const [destC, srcC] of colMap) {
      const srcCell = srcRow.getCell(srcC);
      const destCell = destRow.getCell(destC);
      destCell.value = srcCell.value;
      destCell.numFmt = srcCell.numFmt || '#,##0.00';
      destCell.alignment = { horizontal: 'right' };
    }

    // Styling based on phase (columns B-H), NPV column I gets separate styling
    const bgColor = phase === 'eaas' ? 'FFE3F2FD' : 'FFE8F5E9';
    for (let c = 2; c <= 8; c++) {
      destRow.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } };
      destRow.getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
    // NPV column I: green/red based on value (matching CAPEX style)
    const npvVal = destRow.getCell(9).value;
    const npvNum = typeof npvVal === 'object' ? npvVal.result : npvVal;
    const npvPositive = (typeof npvNum === 'number') ? npvNum >= 0 : true;
    destRow.getCell(9).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: npvPositive ? 'FFE8F5E9' : 'FFFFEBEE' } };
    destRow.getCell(9).font = { color: { argb: npvPositive ? 'FF2E7D32' : 'FFC62828' } };
    destRow.getCell(9).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // Summary rows
  const lastDataRowEN = dataStartRowEN + analysisPeriod - 1;
  const summaryStartRowEN = lastDataRowEN + 2;
  excelSheet5.getRow(summaryStartRowEN).getCell(3).value = 'TOTAL EaaS Phase:';
  excelSheet5.getRow(summaryStartRowEN).getCell(3).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet5.getRow(summaryStartRowEN).getCell(7).value = { formula: `SUMIF(C${dataStartRowEN}:C${lastDataRowEN},"EaaS",G${dataStartRowEN}:G${lastDataRowEN})`, result: roundNum(plnToTysPln(eaasPhaseSavings), 2) };
  excelSheet5.getRow(summaryStartRowEN).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN).getCell(7).font = { bold: true, color: { argb: 'FF1565C0' } };

  excelSheet5.getRow(summaryStartRowEN + 1).getCell(3).value = 'TOTAL Ownership Phase:';
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(3).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).value = { formula: `SUMIF(C${dataStartRowEN}:C${lastDataRowEN},"Ownership",G${dataStartRowEN}:G${lastDataRowEN})`, result: roundNum(plnToTysPln(ownershipPhaseSavings), 2) };
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).font = { bold: true, color: { argb: 'FF2E7D32' } };

  excelSheet5.getRow(summaryStartRowEN + 2).getCell(3).value = 'GRAND TOTAL:';
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(3).font = { bold: true, size: 11 };
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).value = { formula: `SUM(G${dataStartRowEN}:G${lastDataRowEN})`, result: roundNum(plnToTysPln(eaasPhaseSavings + ownershipPhaseSavings), 2) };
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).font = { bold: true, size: 11 };

  // NPV row
  const npvRowEN = summaryStartRowEN + 4;
  excelSheet5.getRow(npvRowEN).getCell(3).value = `NPV [M${currencyLabel}]:`;
  excelSheet5.getRow(npvRowEN).getCell(3).font = { bold: true, size: 12, color: { argb: 'FF1976D2' } };
  excelSheet5.getRow(npvRowEN).getCell(9).value = { formula: `I${lastDataRowEN}`, result: roundNum(plnToMlnPln(cumulativeNPV), 2) };
  excelSheet5.getRow(npvRowEN).getCell(9).numFmt = '#,##0.00';
  excelSheet5.getRow(npvRowEN).getCell(9).font = { bold: true, size: 12, color: { argb: 'FF1976D2' } };

  // DPP row (English) - matching CAPEX style
  const dppRowEN = excelSheet5.getRow(npvRowEN + 1);
  dppRowEN.height = 22;
  dppRowEN.getCell(3).value = 'Discounted Payback (DPP):';
  dppRowEN.getCell(3).font = { bold: true, color: { argb: 'FF1565C0' } };
  dppRowEN.getCell(9).value = (eaasDpp !== null && eaasDpp !== undefined) ? roundNum(eaasDpp, 1) : '-';
  dppRowEN.getCell(9).numFmt = '0.0';
  dppRowEN.getCell(9).font = { bold: true, color: { argb: 'FF1565C0' } };
  dppRowEN.getCell(9).alignment = { horizontal: 'right' };

  // DPP amber border on crossover row (English sheet - static)
  // Find the row where cumulative NPV crosses from negative to positive
  for (let year = 2; year <= analysisPeriod; year++) {
    const currNpvCell = excelSheet5.getRow(dataStartRowEN + year - 1).getCell(9).value;
    const prevNpvCell = excelSheet5.getRow(dataStartRowEN + year - 2).getCell(9).value;
    const currNpv = typeof currNpvCell === 'object' ? currNpvCell.result : currNpvCell;
    const prevNpv = typeof prevNpvCell === 'object' ? prevNpvCell.result : prevNpvCell;
    if (typeof currNpv === 'number' && typeof prevNpv === 'number' && currNpv >= 0 && prevNpv < 0) {
      const dppRowIdx = dataStartRowEN + year - 1;
      for (let col = 2; col <= 9; col++) {
        excelSheet5.getRow(dppRowIdx).getCell(col).border = {
          top: { style: 'medium', color: { argb: 'FFFFC107' } },
          bottom: { style: 'medium', color: { argb: 'FFFFC107' } }
        };
      }
      break;
    }
  }

  if (logoImageId !== null) {
    excelSheet5.addImage(logoImageId, {
      tl: { col: 7, row: 0.2 },
      ext: { width: 180, height: 45 }
    });
  }
  excelSheet5.views = [{ state: 'frozen', ySplit: 17, showGridLines: false, showRowColHeaders: false }];
  console.log('✅ Sheet 5: EaaS Year by Year (EN) created');

  // EN cross-sheet references (EN sheet has its own row numbers)
  const sheet5Refs = {
    eaasSum: `'EaaS Year by Year'!G${summaryStartRowEN}`,
    ownershipSum: `'EaaS Year by Year'!G${summaryStartRowEN + 1}`,
    totalSum: `'EaaS Year by Year'!G${summaryStartRowEN + 2}`,
    npvFinal: `'EaaS Year by Year'!I${lastDataRowEN}`
  };

  // --- SHEET 6: CFO Analysis (English) ---
  const excelSheet6 = excelWorkbook.addWorksheet('CFO Analysis');
  excelSheet6.columns = [
    { width: 3 },   // A: margin
    { width: 32 },  // B: labels
    { width: 18 },  // C: values
    { width: 32 },  // D: descriptions
    { width: 14 },  // E
    { width: 14 },  // F
    { width: 16 },  // G
    { width: 28 },  // H: formula explanations
    { width: 14 }   // I
  ];
  excelSheet6.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Title
  excelSheet6.mergeCells('B2:I2');
  excelSheet6.getCell('B2').value = `CFO ANALYSIS - EaaS (${cfoPeriod} years) - Scenario ${scenarioName}`;
  excelSheet6.getCell('B2').font = { bold: true, size: 16, color: { argb: 'FF1976D2' } };
  excelSheet6.getCell('B2').alignment = { horizontal: 'center', vertical: 'middle' };

  if (logoImageId !== null) {
    excelSheet6.addImage(logoImageId, {
      tl: { col: 7, row: 0.1 },
      ext: { width: 160, height: 40 }
    });
  }

  // Model Parameters section
  let cfoRowEN = 4;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'MODEL PARAMETERS';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11, color: { argb: 'FF5D4037' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEFEBE9' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Analysis period [years]';
  excelSheet6.getCell(`C${cfoRowEN}`).value = cfoPeriod;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'EaaS phase [years]';
  excelSheet6.getCell(`E${cfoRowEN}`).value = eaasPhaseYears;
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`F${cfoRowEN}`).value = 'Ownership phase [years]';
  excelSheet6.getCell(`G${cfoRowEN}`).value = ownershipPhaseYears;
  excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };

  cfoRowEN++;
  const autoParamRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Self-consumption [MWh/year]';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `'EaaS Year by Year'!F10`, result: autoconsumptionMwh };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = autoconsumptionMwh;
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0.0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'PV degradation [%/year]';
  if (withFormulas) {
    excelSheet6.getCell(`E${cfoRowEN}`).value = { formula: `'EaaS Year by Year'!F7`, result: pvDegradationYears2Plus };
  } else {
    excelSheet6.getCell(`E${cfoRowEN}`).value = pvDegradationYears2Plus;
  }
  excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '0.00%';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };

  cfoRowEN++;
  const gridPriceParamRowEN = cfoRowEN;
  const co2ParamRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Grid price [${currencyLabel}/MWh]`;
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `'EaaS Year by Year'!F11`, result: gridPriceDisplay };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = gridPriceDisplay;
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `EaaS price [${currencyLabel}/MWh]`;
  excelSheet6.getCell(`E${cfoRowEN}`).value = eaasPriceDisplay;
  excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`F${cfoRowEN}`).value = 'CO2 emission [t/MWh]';
  excelSheet6.getCell(`G${cfoRowEN}`).value = 0.7;
  excelSheet6.getCell(`G${cfoRowEN}`).numFmt = '0.0';
  excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true };

  cfoRowEN++;
  const degradFactorParamRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Avg. degradation factor';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `1-E${autoParamRowEN}*${cfoPeriod}/2`, result: 1 - pvDegradationYears2Plus * cfoPeriod / 2 };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = 1 - pvDegradationYears2Plus * cfoPeriod / 2;
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '0.000';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = '= 1 - degradation × period / 2';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };

  // --- SECTION 1: KEY KPIs FOR MANAGEMENT (matching Polish version) ---
  cfoRowEN += 2;
  const kpiSectionRowEN = cfoRowEN;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = `KEY KPIs FOR MANAGEMENT (${cfoPeriod}-year analysis)`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRowEN++;
  // KPI with formulas - Zero CAPEX
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Zero CAPEX';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = 0;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0 "${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'No investment expenditure';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Annual savings (Year 1)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  // Formula using C6 (autoconsumption), C7 (grid price), E7 (EaaS price)
  excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `C6*(C7-E7)/1000` };
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0 "k${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = '= Self-cons. × (Grid_price - EaaS_price)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // EaaS Phase savings (with formulas like Polish version)
  cfoRowEN++;
  const kpiEaaSRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `EaaS Phase (years 1-${eaasPhaseYears})`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `${sheet5Refs.eaasSum}/1000`, result: roundNum(plnToTysPln(totalSavingsEaaS), 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(plnToTysPln(totalSavingsEaaS), 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= ${sheet5Refs.eaasSum} / 1000` : 'Savings with EaaS subscription';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Ownership Phase savings
  cfoRowEN++;
  const kpiOwnRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Ownership Phase (years ${eaasPhaseYears + 1}-${cfoPeriod})`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `${sheet5Refs.ownershipSum}/1000`, result: roundNum(plnToTysPln(totalSavingsOwnership), 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(plnToTysPln(totalSavingsOwnership), 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= ${sheet5Refs.ownershipSum} / 1000` : 'Free energy (O&M only)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // TOTAL SAVINGS
  cfoRowEN++;
  const kpiTotalRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `TOTAL SAVINGS (${cfoPeriod} years)`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `C${kpiEaaSRowEN}+C${kpiOwnRowEN}`, result: roundNum(plnToTysPln(totalSavingsEaaS + totalSavingsOwnership), 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(plnToTysPln(totalSavingsEaaS + totalSavingsOwnership), 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' }, size: 12 };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= C${kpiEaaSRowEN} + C${kpiOwnRowEN}` : 'Cumulative incl. PV degradation';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // NPV (matching CAPEX CFO style)
  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'NPV (Net Present Value)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `${sheet5Refs.npvFinal}`, result: roundNum(npvMln, 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(npvMln, 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '# ##0.00';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: npvMln > 0 ? { argb: 'FF2E7D32' } : { argb: 'FFC62828' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: npvMln > 0 ? 'FFE8F5E9' : 'FFFFEBEE' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `M${currencyLabel}`;
  excelSheet6.mergeCells(`E${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`E${cfoRowEN}`).value = npvMln > 0 ? 'Model profitable (NPV > 0)' : 'Model unprofitable (NPV < 0)';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // DPP - Discounted Payback (matching CAPEX CFO style)
  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Discounted Payback (DPP)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  if (withFormulas) {
    const s2enDpp = "'EaaS Year by Year'!";
    const _nCfoEN = `SUMPRODUCT((${s2enDpp}I${dataStartRow}:${s2enDpp}I${lastDataRow}<0)*1)`;
    const _iCfoRangeEN = `${s2enDpp}I${dataStartRow}:${s2enDpp}I${lastDataRow}`;
    const kpiDppFormulaEN = `IF(${_nCfoEN}=0,0,${_nCfoEN}+(-INDEX(${_iCfoRangeEN},${_nCfoEN}))/(INDEX(${_iCfoRangeEN},${_nCfoEN}+1)-INDEX(${_iCfoRangeEN},${_nCfoEN})))`;
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: kpiDppFormulaEN, result: hasDppEaaS ? roundNum(eaasDpp, 1) : 0 };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = hasDppEaaS ? roundNum(eaasDpp, 1) : (eaasDpp === 0 ? 0 : 'Immediate');
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = hasDppEaaS && eaasDpp > 0 ? '0.0' : '@';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = hasDppEaaS && eaasDpp > 0 ? 'years' : '';
  excelSheet6.mergeCells(`E${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`E${cfoRowEN}`).value = eaasDpp === 0 ? 'NPV > 0 from year 1 (no CAPEX)' : 'Year when cumulative NPV >= 0';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Helper row for formulas: Total in thousands (for scenario calculations)
  cfoRowEN++;
  const kpiTotalTysRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '(in thousands)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `C${kpiTotalRowEN}*1000`, result: roundNum(baseTotalSavings, 0) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(baseTotalSavings, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { color: { argb: 'FF9E9E9E' } };

  // Helper row for NPV in thousands - formula referencing year-by-year sheet
  cfoRowEN++;
  const kpiNpvTysRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '(NPV in thousands)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `'EaaS Year by Year'!I${lastDataRow}*1000`, result: roundNum(baseEaaSNpvTys, 0) };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- NPV from Year by Year sheet\n-- I${lastDataRow} = cumulative NPV [M] × 1000`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(baseEaaSNpvTys, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { color: { argb: 'FF9E9E9E' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Discount vs grid (EaaS phase)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = (gridPriceDisplay - eaasPriceDisplay) / gridPriceDisplay;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '0%';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = `Guaranteed for ${eaasPhaseYears} years of contract`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Balance sheet';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = 'Off-balance';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Does not burden company balance';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Technical risk';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = 'EaaS Provider';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Production guarantee on provider side';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Add borders to KPI section
  for (let r = kpiSectionRowEN + 1; r <= cfoRowEN; r++) {
    excelSheet6.getRow(r).getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    excelSheet6.getRow(r).getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  }

  // Tornado Chart section (English)
  cfoRowEN += 2;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'SENSITIVITY ANALYSIS - TORNADO CHART';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Impact on EaaS NPV (${cfoPeriod} years) when changing parameter:`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:H${cfoRowEN}`);

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Yield PV = energy production from PV installation [kWh/kWp/year]';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);

  cfoRowEN += 2;
  const tornadoHeaderRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Parameter';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = 'Change';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `Pessimistic [k${currencyLabel}]`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { bold: true, color: { argb: 'FFC62828' } };
  excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`E${cfoRowEN}`).value = 'Base';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`F${cfoRowEN}`).value = `Optimistic [k${currencyLabel}]`;
  excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`G${cfoRowEN}`).value = `Range [k${currencyLabel}]`;
  excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`G${cfoRowEN}`).alignment = { horizontal: 'center' };
  // Tornado data (English) - SUMPRODUCT formulas referencing EaaS Year by Year sheet
  const _s2en = "'EaaS Year by Year'!";
  const _eRen = `${_s2en}$E$${dataStartRow}:$E$${lastDataRow}`;
  const _fRen = `${_s2en}$F$${dataStartRow}:$F$${lastDataRow}`;
  const _bRen = `${_s2en}$B$${dataStartRow}:$B$${lastDataRow}`;
  const _dRen = `${_s2en}$F$4`;

  const tornadoDataEN = [
    { param: 'Grid energy price', variation: '±20%', pessimisticSavings: npvGridPess, optimisticSavings: npvGridOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eRen} * 0.8\n   - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      optFormula: `SUMPRODUCT(\n  (${_eRen} * 1.2\n   - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      pessNote: `-- NPV EaaS: grid price -20%\n-- E = Grid Energy Cost, F = EaaS Cost`,
      optNote: `-- NPV EaaS: grid price +20%\n-- E = Grid Energy Cost, F = EaaS Cost` },
    { param: 'EaaS subscription price', variation: '±20%', pessimisticSavings: npvSubsPess, optimisticSavings: npvSubsOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eRen}\n   - ${_fRen} * 1.2),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      optFormula: `SUMPRODUCT(\n  (${_eRen}\n   - ${_fRen} * 0.8),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      pessNote: `-- NPV EaaS: subscription +20%`,
      optNote: `-- NPV EaaS: subscription -20%` },
    { param: 'PV yield (production)', variation: '±15%', pessimisticSavings: npvYieldPess, optimisticSavings: npvYieldOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eRen} * 0.85\n   - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      optFormula: `SUMPRODUCT(\n  (${_eRen} * 1.15\n   - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen},\n    ${_bRen}))`,
      pessNote: `-- NPV EaaS: PV yield -15%`,
      optNote: `-- NPV EaaS: PV yield +15%` },
    { param: 'Discount rate', variation: '±2pp', pessimisticSavings: npvDiscPess, optimisticSavings: npvDiscOpt,
      pessFormula: `SUMPRODUCT(\n  (${_eRen} - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen} + 0.02,\n    ${_bRen}))`,
      optFormula: `SUMPRODUCT(\n  (${_eRen} - ${_fRen}),\n  1 / POWER(\n    1 + ${_dRen} - 0.02,\n    ${_bRen}))`,
      pessNote: `-- NPV EaaS: discount rate +2pp`,
      optNote: `-- NPV EaaS: discount rate -2pp` }
  ];

  // Calculate range and sort by impact
  tornadoDataEN.forEach(t => {
    t.range = Math.abs(t.optimisticSavings - t.pessimisticSavings);
  });
  tornadoDataEN.sort((a, b) => b.range - a.range);

  const tornadoDataStartRowEN = cfoRowEN + 1;
  tornadoDataEN.forEach((t, idx) => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = t.param;
    excelSheet6.getCell(`C${cfoRowEN}`).value = t.variation;
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };

    // NPV values - SUMPRODUCT formulas when withFormulas=true
    if (withFormulas) {
      excelSheet6.getCell(`D${cfoRowEN}`).value = { formula: t.pessFormula, result: roundNum(t.pessimisticSavings, 0) };
      if (t.pessNote) excelSheet6.getCell(`D${cfoRowEN}`).note = t.pessNote;
      excelSheet6.getCell(`E${cfoRowEN}`).value = { formula: `$C$${kpiNpvTysRowEN}`, result: roundNum(baseEaaSNpvTys, 0) };
      excelSheet6.getCell(`F${cfoRowEN}`).value = { formula: t.optFormula, result: roundNum(t.optimisticSavings, 0) };
      if (t.optNote) excelSheet6.getCell(`F${cfoRowEN}`).note = t.optNote;
      excelSheet6.getCell(`G${cfoRowEN}`).value = { formula: `F${cfoRowEN}-D${cfoRowEN}`, result: roundNum(t.range, 0) };
    } else {
      excelSheet6.getCell(`D${cfoRowEN}`).value = roundNum(t.pessimisticSavings, 0);
      excelSheet6.getCell(`E${cfoRowEN}`).value = roundNum(baseEaaSNpvTys, 0);
      excelSheet6.getCell(`F${cfoRowEN}`).value = roundNum(t.optimisticSavings, 0);
      excelSheet6.getCell(`G${cfoRowEN}`).value = roundNum(t.range, 0);
    }

    excelSheet6.getCell(`D${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FFC62828' } };
    excelSheet6.getCell(`D${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

    excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };
    excelSheet6.getCell(`E${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    excelSheet6.getCell(`F${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`F${cfoRowEN}`).font = { color: { argb: 'FF2E7D32' } };
    excelSheet6.getCell(`F${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

    excelSheet6.getCell(`G${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`G${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true };

    for (let c = 2; c <= 7; c++) {
      excelSheet6.getRow(cfoRowEN).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Tornado Chart visualization (Unicode bars) - English
  cfoRowEN += 2;
  excelSheet6.mergeCells(`B${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = `📊 TORNADO CHART - EaaS NPV [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };

  cfoRowEN++;
  const maxRangeRefEN = `(F${tornadoDataStartRowEN}-D${tornadoDataStartRowEN})`;
  tornadoDataEN.forEach((t, idx) => {
    cfoRowEN++;
    const dataRowEN = tornadoDataStartRowEN + idx;
    excelSheet6.getCell(`B${cfoRowEN}`).value = t.param;
    excelSheet6.getCell(`B${cfoRowEN}`).font = { size: 10 };

    const maxRange = tornadoDataEN[0].range;
    const pessimisticDelta = t.pessimisticSavings - baseEaaSNpvTys;
    const optimisticDelta = t.optimisticSavings - baseEaaSNpvTys;

    const redBarLen = Math.round(Math.abs(pessimisticDelta) / maxRange * 15);
    const redBar = '█'.repeat(Math.max(1, redBarLen));
    if (withFormulas) {
      excelSheet6.getCell(`C${cfoRowEN}`).value = {
        formula: `REPT("█",\n  MAX(1, ROUND(\n    ABS(D${dataRowEN} - E${dataRowEN})\n    / ${maxRangeRefEN} * 15, 0)))`,
        result: redBar
      };
    } else {
      excelSheet6.getCell(`C${cfoRowEN}`).value = redBar;
    }
    excelSheet6.getCell(`C${cfoRowEN}`).font = { color: { argb: 'FFC62828' }, size: 10 };
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'right' };

    if (withFormulas) {
      excelSheet6.getCell(`D${cfoRowEN}`).value = {
        formula: `TEXT(D${dataRowEN},"# ##0")\n& " | " & TEXT(E${dataRowEN},"# ##0")\n& " | " & TEXT(F${dataRowEN},"# ##0")`,
        result: `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(baseEaaSNpvTys, 0)} | ${roundNum(t.optimisticSavings, 0)}`
      };
    } else {
      excelSheet6.getCell(`D${cfoRowEN}`).value = `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(baseEaaSNpvTys, 0)} | ${roundNum(t.optimisticSavings, 0)}`;
    }
    excelSheet6.getCell(`D${cfoRowEN}`).font = { size: 9 };
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };

    const greenBarLen = Math.round(Math.abs(optimisticDelta) / maxRange * 15);
    const greenBar = '█'.repeat(Math.max(1, greenBarLen));
    if (withFormulas) {
      excelSheet6.getCell(`E${cfoRowEN}`).value = {
        formula: `REPT("█",\n  MAX(1, ROUND(\n    ABS(F${dataRowEN} - E${dataRowEN})\n    / ${maxRangeRefEN} * 15, 0)))`,
        result: greenBar
      };
    } else {
      excelSheet6.getCell(`E${cfoRowEN}`).value = greenBar;
    }
    excelSheet6.getCell(`E${cfoRowEN}`).font = { color: { argb: 'FF2E7D32' }, size: 10 };
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'left' };
  });

  // Legend
  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🔴 Pessimistic';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { size: 9, color: { argb: 'FFC62828' } };
  excelSheet6.getCell(`C${cfoRowEN}`).value = '⚪ Base';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { size: 9 };
  excelSheet6.getCell(`D${cfoRowEN}`).value = '🟢 Optimistic';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { size: 9, color: { argb: 'FF2E7D32' } };

  // --- SENSITIVITY MATRIX (English) - NPV EaaS (consistent with CAPEX) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = `SENSITIVITY MATRIX - EaaS NPV vs Grid Price${isRdnExport ? ' (RDN)' : ''} vs Yield`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `NPV [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
  excelSheet6.mergeCells(`C${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`C${cfoRowEN}`).value = '← PV Yield →';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, size: 10 };
  excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };

  cfoRowEN++;
  const matrixHeaderRowEaaSEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Grid price ↓';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
  excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    excelSheet6.getCell(cfoRowEN, 3 + i).value = yv;
    excelSheet6.getCell(cfoRowEN, 3 + i).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(cfoRowEN, 3 + i).font = { bold: true, size: 9 };
    excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    excelSheet6.getCell(cfoRowEN, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  gridPriceVariations.forEach(gpv => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = gpv;
    excelSheet6.getCell(`B${cfoRowEN}`).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
    excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'right' };
    excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      // Full NPV recalculation per cell (consistent with CAPEX)
      let adjNpv;
      try {
        adjNpv = plnToTysPln(calculateEaaSNPV({
          ...eaasNpvBaseForMatrix,
          self_consumed_annual_kwh: eaasSelfConsumptionByYield[yv] * 1000,
          total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * (1 + gpv)  // RDN-aware
        })) * currencyMultiplier;
      } catch (npvErr) {
        console.warn('⚠️ EaaS NPV calc failed (EN), fallback:', npvErr);
        adjNpv = 0;
      }
      if (!isFinite(adjNpv)) adjNpv = 0;

      const cell = excelSheet6.getCell(cfoRowEN, 3 + i);
      if (withFormulas) {
        const s2e = "'EaaS Year by Year'!";
        const colLetter = _col(3 + i);
        const yieldRef = `${colLetter}$${matrixHeaderRowEaaSEN}`;
        const priceRef = `$B${cfoRowEN}`;
        const bRange = `${s2e}$B$${dataStartRow}:$B$${lastDataRow}`;
        const eRange = `${s2e}$E$${dataStartRow}:$E$${lastDataRow}`;
        const fCostRange = `${s2e}$F$${dataStartRow}:$F$${lastDataRow}`;
        let formula;
        if (isRdnExport) {
          const A = "'Dane bazowe TCSL (Rok 1)'!";
          const degRange = `(1-${s2e}$F$6)*POWER(1-${s2e}$F$7,${bRange}-1)`;
          const cpiRange = `POWER(1+${s2e}$F$5,${bRange}-1)`;
          formula = `SUMPRODUCT((${A}$F$18*${degRange}*(1+${yieldRef})*(1+${priceRef})*${cpiRange}+${A}$F$21*(1+${yieldRef})*${cpiRange})/1000-${fCostRange},1/POWER(1+${s2e}$F$4,${bRange}))`;
        } else {
          formula = `SUMPRODUCT((${eRange}*(1+${yieldRef})*(1+${priceRef})-${fCostRange}),1/POWER(1+${s2e}$F$4,${bRange}))`;
        }
        cell.value = { formula, result: roundNum(adjNpv, 0) };
      } else {
        cell.value = roundNum(adjNpv, 0);
      }
      cell.numFmt = '#,##0';
      cell.alignment = { horizontal: 'center' };

      if (adjNpv > baseEaaSNpvTys * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (adjNpv > baseEaaSNpvTys * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (adjNpv > 0) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
      } else {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFCDD2' } };
        cell.font = { color: { argb: 'FFC62828' }, bold: true };
      }
      cell.border = {
        top: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        left: { style: 'thin', color: { argb: 'FFE0E0E0' } },
        right: { style: 'thin', color: { argb: 'FFE0E0E0' } }
      };
    });
  });

  // --- ESG SECTION (English) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = `ESG - ENVIRONMENTAL IMPACT (${cfoPeriod} years)`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF00695C' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F2F1' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'PV self-consumption [MWh/year]';
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(autoconsumptionMwh, 1);
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0.0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Green energy instead of grid';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Grid emission factor [t CO2/MWh]';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `$G$${co2ParamRowEN}`, result: co2FactorKgPerKwh };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- Emission factor from params (G${co2ParamRowEN})`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = co2FactorKgPerKwh;
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '0.0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Poland average (2024)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN += 2;
  const annualCO2RowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🌍 Annual CO2 reduction [tons]';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `ROUND(\n  $C$${autoParamRowEN} * $G$${co2ParamRowEN},\n  0)`, result: roundNum(annualCO2Tons, 0) };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- Self-consumption × emission factor\n-- C${autoParamRowEN} = MWh/yr, G${co2ParamRowEN} = t CO2/MWh`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2Tons, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = `= Autoconsumption × ${co2FactorKgPerKwh} t/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRowEN++;
  const totalCO2RowEN = cfoRowEN;  // Store for decision summary formulas
  excelSheet6.getCell(`B${cfoRowEN}`).value = `🌍 Total CO2 reduction (${cfoPeriod} years) [tons]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `ROUND(\n  $C$${annualCO2RowEN} * ${cfoPeriod}\n  * $C$${degradFactorParamRowEN},\n  0)`, result: roundNum(totalCO2Tons, 0) };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- Annual CO2 × years × avg degradation\n-- C${annualCO2RowEN} = tons/yr, C${degradFactorParamRowEN} = degrad. factor`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(totalCO2Tons, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Total project impact (with degradation)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🚗 Equivalent cars/year';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `ROUND($C$${annualCO2RowEN}/4.6,0)`, result: roundNum(annualCO2Tons / 4.6, 0) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2Tons / 4.6, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Annual emission of this many cars';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🌳 Equivalent trees';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `ROUND($C$${annualCO2RowEN}/0.022,0)`, result: roundNum(annualCO2Tons / 0.022, 0) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2Tons / 0.022, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Trees needed to absorb CO2';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '✈️ Equivalent flights WAW-LON';
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `ROUND($C$${annualCO2RowEN}/0.255,0)`, result: roundNum(annualCO2Tons / 0.255, 0) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2Tons / 0.255, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Economy class flights';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- BREAK-EVEN ANALYSIS (English) - Full 30-year NPV-based ---
  const breakEvenGridPriceEN = breakEvenGridPrice; // reuse PL calculation
  const safetyMarginPctEN = safetyMarginPct;

  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'BREAK-EVEN ANALYSIS';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FFE65100' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'At what grid price does EaaS stop being profitable?';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:G${cfoRowEN}`);

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Current grid energy price';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = gridPriceDisplay;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `${currencyLabel}/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'EaaS price (subscription)';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = eaasPriceDisplay;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `${currencyLabel}/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF757575' } };

  cfoRowEN++;
  const breakEvenRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `⚠️ BREAK-EVEN: Grid price (${cfoPeriod} years)`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    const _s2beEN = "'EaaS Year by Year'!";
    const beFormulaEN = `$C$${gridPriceParamRowEN}\n* SUMPRODUCT(\n    ${_s2beEN}$F$${dataStartRow}:$F$${lastDataRow}\n    / POWER(1 + ${_s2beEN}$F$4,\n            ${_s2beEN}$B$${dataStartRow}:$B$${lastDataRow}))\n/ SUMPRODUCT(\n    ${_s2beEN}$E$${dataStartRow}:$E$${lastDataRow}\n    / POWER(1 + ${_s2beEN}$F$4,\n            ${_s2beEN}$B$${dataStartRow}:$B$${lastDataRow}))`;
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: beFormulaEN, result: roundNum(breakEvenGridPriceEN, 0) };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- Grid price at NPV=0 (${cfoPeriod} years)\n-- price × PV(EaaS_costs) / PV(grid_costs)`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(breakEvenGridPriceEN, 0);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `${currencyLabel}/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF757575' } };
  excelSheet6.mergeCells(`E${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`E${cfoRowEN}`).value = `Grid price at NPV=0 (full ${cfoPeriod} years incl. ownership)`;
  excelSheet6.getCell(`E${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🛡️ Safety margin';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `($C$${gridPriceParamRowEN} - C${breakEvenRowEN})\n/ $C$${gridPriceParamRowEN}`, result: safetyMarginPctEN };
    excelSheet6.getCell(`C${cfoRowEN}`).note = `-- (grid_price - break_even) / grid_price`;
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = safetyMarginPctEN;
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '0.0%';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' }, size: 12 };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'How much grid price must drop for EaaS to stop being profitable';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- SCENARIO ANALYSIS (English) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'SCENARIO ANALYSIS';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `${cfoPeriod}-year EaaS NPV projection under different assumptions:`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:G${cfoRowEN}`);

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Scenario';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).value = 'Grid price';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'PV Yield';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`E${cfoRowEN}`).value = `NPV [k${currencyLabel}]`;
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`F${cfoRowEN}`).value = 'Probability';
  excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`G${cfoRowEN}`).value = 'Weighted val.';
  excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`G${cfoRowEN}`).alignment = { horizontal: 'center' };

  const scenariosEN = [
    { name: '😟 Pessimistic', gridMult: 0.85, yieldMult: 0.90, prob: 0.15, color: 'FFC62828', bgColor: 'FFFFEBEE' },
    { name: '📊 Base', gridMult: 1.0, yieldMult: 1.0, prob: 0.50, color: 'FF1565C0', bgColor: 'FFE3F2FD' },
    { name: '🚀 Optimistic', gridMult: 1.15, yieldMult: 1.05, prob: 0.25, color: 'FF2E7D32', bgColor: 'FFE8F5E9' },
    { name: '🔥 Energy boom', gridMult: 1.30, yieldMult: 1.0, prob: 0.10, color: 'FFE65100', bgColor: 'FFFFF3E0' }
  ];

  const scenarioStartRowEN = cfoRowEN + 1;
  scenariosEN.forEach((s, idx) => {
    cfoRowEN++;
    // Full NPV recalculation with non-linear self-consumption (reuse PL pre-computed SC)
    let scenarioSavingsEN;
    if (s.gridMult === 1.0 && s.yieldMult === 1.0) {
      scenarioSavingsEN = baseEaaSNpvTys;
    } else {
      try {
        scenarioSavingsEN = plnToTysPln(calculateEaaSNPV({
          ...eaasNpvBaseForMatrix,
          self_consumed_annual_kwh: scenarioSCbyYield[s.yieldMult] || autoconsumptionMwh * 1000 * s.yieldMult,
          total_energy_price_per_kwh: effectiveEnergyPriceEaas / 1000 * s.gridMult  // RDN-aware
        })) * currencyMultiplier;
      } catch (e) {
        scenarioSavingsEN = baseEaaSNpvTys * s.yieldMult * s.gridMult;
      }
    }
    const weightedValue = scenarioSavingsEN * s.prob;

    excelSheet6.getCell(`B${cfoRowEN}`).value = s.name;
    excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, color: { argb: s.color } };
    excelSheet6.getCell(`C${cfoRowEN}`).value = s.gridMult - 1;
    excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`D${cfoRowEN}`).value = s.yieldMult - 1;
    excelSheet6.getCell(`D${cfoRowEN}`).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
    // NPV value - K_eaas as SUMPRODUCT formula
    if (withFormulas) {
      const _s2scEN = "'EaaS Year by Year'!";
      const kEaasFormulaEN = `SUMPRODUCT(\n    ${_s2scEN}$F$${dataStartRow}:$F$${lastDataRow}\n    / POWER(1 + ${_s2scEN}$F$4,\n            ${_s2scEN}$B$${dataStartRow}:$B$${lastDataRow}))`;
      excelSheet6.getCell(`E${cfoRowEN}`).value = { formula: `ROUND(\n  ($C$${kpiNpvTysRowEN} + ${kEaasFormulaEN})\n  * (1 + C${cfoRowEN}) * (1 + D${cfoRowEN})\n  - ${kEaasFormulaEN},\n  0)`, result: roundNum(scenarioSavingsEN, 0) };
      excelSheet6.getCell(`E${cfoRowEN}`).note = `-- NPV with yield/price changes\n-- K_eaas = PV of EaaS costs\n-- (NPV+K)×multipliers - K`;
    } else {
      excelSheet6.getCell(`E${cfoRowEN}`).value = roundNum(scenarioSavingsEN, 0);
    }
    excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true, color: { argb: s.color } };
    excelSheet6.getCell(`E${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: s.bgColor } };
    excelSheet6.getCell(`F${cfoRowEN}`).value = s.prob;
    excelSheet6.getCell(`F${cfoRowEN}`).numFmt = '0%';
    excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
    // Weighted value - use formula or value
    if (withFormulas) {
      excelSheet6.getCell(`G${cfoRowEN}`).value = { formula: `ROUND(E${cfoRowEN}*F${cfoRowEN},0)`, result: roundNum(weightedValue, 0) };
    } else {
      excelSheet6.getCell(`G${cfoRowEN}`).value = roundNum(weightedValue, 0);
    }
    excelSheet6.getCell(`G${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`G${cfoRowEN}`).alignment = { horizontal: 'center' };

    for (let c = 2; c <= 7; c++) {
      excelSheet6.getRow(cfoRowEN).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const scenarioEndRowEN = cfoRowEN;

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '📈 EXPECTED VALUE';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  excelSheet6.mergeCells(`C${cfoRowEN}:D${cfoRowEN}`);
  excelSheet6.getCell(`C${cfoRowEN}`).value = 'Weighted sum of scenarios';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`E${cfoRowEN}`).value = { formula: `SUM(G${scenarioStartRowEN}:G${scenarioEndRowEN})` };
  excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF5E35B1' } };
  excelSheet6.getCell(`E${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFEDE7F6' } };
  excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`F${cfoRowEN}`).value = { formula: `SUM(F${scenarioStartRowEN}:F${scenarioEndRowEN})` };
  excelSheet6.getCell(`F${cfoRowEN}`).numFmt = '0%';
  excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`G${cfoRowEN}`).value = `k${currencyLabel}`;
  excelSheet6.getCell(`G${cfoRowEN}`).font = { color: { argb: 'FF757575' } };

  // --- INFLATION SENSITIVITY (English — full NPV recalculation) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'ENERGY PRICE INFLATION SENSITIVITY';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `How EaaS NPV changes over ${cfoPeriod} years with different energy price inflation:`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:H${cfoRowEN}`);

  // Same inflation rates as PL (with base included)
  const inflationRatesEN = inflationRates;

  cfoRowEN += 2;
  const inflHeaderRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Annual energy price inflation';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  inflationRatesEN.forEach((inf, i) => {
    excelSheet6.getCell(cfoRowEN, 3 + i).value = inf;
    excelSheet6.getCell(cfoRowEN, 3 + i).numFmt = '0.0%';
    excelSheet6.getCell(cfoRowEN, 3 + i).font = { bold: true };
    excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    excelSheet6.getCell(cfoRowEN, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRowEN++;
  const inflValuesRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `NPV [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };

  cfoRowEN++;
  const inflValuesRowActualEN = cfoRowEN;

  // SUMPRODUCT formula building blocks for inflation sensitivity (English)
  const _s2infEN = "'EaaS Year by Year'!";
  const _eInfEN = `${_s2infEN}$E$${dataStartRow}:$E$${lastDataRow}`;
  const _fInfEN = `${_s2infEN}$F$${dataStartRow}:$F$${lastDataRow}`;
  const _bInfEN = `${_s2infEN}$B$${dataStartRow}:$B$${lastDataRow}`;
  const _discInfEN = `${_s2infEN}$F$4`;
  const _baseInflRefEN = `${_s2infEN}$F$5`;

  inflationRatesEN.forEach((inf, i) => {
    const cell = excelSheet6.getCell(cfoRowEN, 3 + i);
    const colLetter = _col(3 + i);

    if (withFormulas) {
      const formula = `SUMPRODUCT(\n  (${_eInfEN}\n   * POWER(\n       (1 + ${colLetter}$${inflHeaderRowEN}) / (1 + ${_baseInflRefEN}),\n       ${_bInfEN} - 1)\n   - ${_fInfEN}),\n  1 / POWER(1 + ${_discInfEN}, ${_bInfEN}))`;
      cell.value = { formula, result: roundNum(inflNpvValues[i], 0) };
      cell.note = `-- NPV at inflation ${colLetter}$${inflHeaderRowEN}\n-- E×(1+infl)^year / discount - F`;
    } else {
      cell.value = roundNum(inflNpvValues[i], 0);
    }
    cell.numFmt = '#,##0';
    cell.alignment = { horizontal: 'center' };
    cell.font = { bold: true };

    const isBase = Math.abs(inf - baseInflation) < 0.002;
    if (isBase) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      cell.font = { bold: true, color: { argb: 'FF1565C0' } };
    } else if (inf === 0) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
    } else if (inf <= 0.03) {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
      cell.font = { bold: true, color: { argb: 'FF2E7D32' } };
    } else {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
      cell.font = { bold: true, color: { argb: 'FF1B5E20' } };
    }
  });

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `vs base inflation ${decimalToPct(baseInflation).toFixed(1)}%`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };

  const baseInflColLetterEN = baseInflIdx >= 0 ? _col(3 + baseInflIdx) : null;
  inflationRatesEN.forEach((inf, i) => {
    const isBase = Math.abs(inf - baseInflation) < 0.002;
    if (isBase) {
      excelSheet6.getCell(cfoRowEN, 3 + i).value = '-';
      excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    } else {
      const pctChange = baseInflNpv !== 0 ? (inflNpvValues[i] - baseInflNpv) / Math.abs(baseInflNpv) : 0;
      const colLetter = _col(3 + i);
      if (withFormulas && baseInflColLetterEN) {
        excelSheet6.getCell(cfoRowEN, 3 + i).value = {
          formula: `(${colLetter}${inflValuesRowActualEN}-${baseInflColLetterEN}${inflValuesRowActualEN})/${baseInflColLetterEN}${inflValuesRowActualEN}`,
          result: pctChange
        };
      } else {
        excelSheet6.getCell(cfoRowEN, 3 + i).value = pctChange;
      }
      excelSheet6.getCell(cfoRowEN, 3 + i).numFmt = '+0%;-0%';
      excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
      excelSheet6.getCell(cfoRowEN, 3 + i).font = { color: { argb: pctChange >= 0 ? 'FF2E7D32' : 'FFC62828' } };
    }
  });

  // --- DECISION SUMMARY (English - Full) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'DECISION SUMMARY - EaaS vs STATUS QUO';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF283593' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8EAF6' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Criterion';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'EaaS';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`E${cfoRowEN}`).value = 'Status Quo';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
  excelSheet6.getCell(`F${cfoRowEN}`).value = 'Winner';
  excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };

  // Decision criteria with formulas support (matching Polish version)
  const decisionsEN = [
    { criterion: 'Investment (CAPEX)', eaas: '0 PLN', statusQuo: '0 PLN', winner: 'Tie', winColor: 'FF757575', useFormula: false },
    { criterion: `${cfoPeriod}-year energy cost`, eaas: `${roundNum(plnToTysPln(autoconsumptionMwh * eaasPriceDisplay * cfoPeriod * degradationFactor30), 0)} k`, statusQuo: `${roundNum(plnToTysPln(autoconsumptionMwh * gridPriceDisplay * cfoPeriod * degradationFactor30), 0)} k`, winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'energyCost' },
    { criterion: `${cfoPeriod}-year savings`, eaas: `${roundNum(baseTotalSavings, 0)} k${currencyLabel}`, statusQuo: '0', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'savings' },
    { criterion: 'Technical risk', eaas: 'Provider', statusQuo: 'No installation', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Price risk', eaas: 'Partial hedge', statusQuo: '100% exposure', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Balance sheet impact', eaas: 'Off-balance', statusQuo: 'None', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Green energy', eaas: 'YES', statusQuo: 'NO', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'CO2 reduction', eaas: `${roundNum(totalCO2Tons, 0)} tons`, statusQuo: '0 tons', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'co2' }
  ];

  const _s2decEN = "'EaaS Year by Year'!";
  const decisionFirstRowEN = cfoRowEN + 1;
  decisionsEN.forEach(d => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = d.criterion;
    excelSheet6.mergeCells(`B${cfoRowEN}:C${cfoRowEN}`);

    // D column (EaaS value) — formulas matching reference ROUND pattern
    if (withFormulas && d.useFormula) {
      if (d.formulaType === 'savings') {
        excelSheet6.getCell(`D${cfoRowEN}`).value = { formula: `ROUND($C$${kpiTotalTysRowEN},0)\n&" k${currencyLabel}"`, result: d.eaas };
      } else if (d.formulaType === 'energyCost') {
        excelSheet6.getCell(`D${cfoRowEN}`).value = {
          formula: `ROUND(\n  SUM(${_s2decEN}F${dataStartRow}:${_s2decEN}F${lastDataRow}),\n  0)\n&" k"`,
          result: d.eaas
        };
      } else if (d.formulaType === 'co2') {
        excelSheet6.getCell(`D${cfoRowEN}`).value = { formula: `ROUND($C$${totalCO2RowEN},0)\n&" tons"`, result: d.eaas };
      }
    } else {
      excelSheet6.getCell(`D${cfoRowEN}`).value = d.eaas;
    }
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF2E7D32' } };

    // E column (Status Quo value) — formulas when applicable
    if (withFormulas && d.useFormula && d.formulaType === 'energyCost') {
      excelSheet6.getCell(`E${cfoRowEN}`).value = {
        formula: `ROUND(\n  SUM(${_s2decEN}E${dataStartRow}:${_s2decEN}E${lastDataRow}),\n  0)\n&" k"`,
        result: d.statusQuo
      };
    } else {
      excelSheet6.getCell(`E${cfoRowEN}`).value = d.statusQuo;
    }
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).font = { color: { argb: 'FF757575' } };

    // F column (Winner) — formulas when applicable
    if (withFormulas && d.useFormula) {
      if (d.formulaType === 'savings') {
        excelSheet6.getCell(`F${cfoRowEN}`).value = { formula: `IF($C$${kpiTotalTysRowEN}>0,\n  "EaaS","Status Quo")`, result: d.winner };
      } else if (d.formulaType === 'energyCost') {
        excelSheet6.getCell(`F${cfoRowEN}`).value = {
          formula: `IF(\n  SUM(${_s2decEN}F${dataStartRow}:${_s2decEN}F${lastDataRow})\n  < SUM(${_s2decEN}E${dataStartRow}:${_s2decEN}E${lastDataRow}),\n  "EaaS","Status Quo")`,
          result: d.winner
        };
      } else if (d.formulaType === 'co2') {
        excelSheet6.getCell(`F${cfoRowEN}`).value = { formula: `IF($C$${totalCO2RowEN}>0,\n  "EaaS","Status Quo")`, result: d.winner };
      }
    } else {
      excelSheet6.getCell(`F${cfoRowEN}`).value = d.winner;
    }
    excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true, color: { argb: d.winColor } };
    if (d.winner === 'EaaS') {
      excelSheet6.getCell(`F${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    }
    for (let c = 2; c <= 6; c++) {
      excelSheet6.getRow(cfoRowEN).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });
  const decisionLastRowEN = cfoRowEN;
  const eaasWinCountEN = decisionsEN.filter(d => d.winner === 'EaaS').length;

  // Final verdict — dynamic COUNTIF formula
  cfoRowEN += 2;
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);
  if (withFormulas) {
    const fRangeEN = `F${decisionFirstRowEN}:F${decisionLastRowEN}`;
    const nCriteriaEN = decisionsEN.length;
    excelSheet6.getCell(`B${cfoRowEN}`).value = {
      formula: `IF(\n  COUNTIF(${fRangeEN},"EaaS")\n  > COUNTIF(${fRangeEN},"Status Quo"),\n  "✅ RECOMMENDATION: EaaS model wins in "\n  & COUNTIF(${fRangeEN},"EaaS")\n  & " of ${nCriteriaEN} criteria",\n  "⛔ RECOMMENDATION: Status Quo wins in "\n  & COUNTIF(${fRangeEN},"Status Quo")\n  & " of ${nCriteriaEN} criteria")`,
      result: `✅ RECOMMENDATION: EaaS model wins in ${eaasWinCountEN} of ${nCriteriaEN} criteria`
    };
  } else {
    excelSheet6.getCell(`B${cfoRowEN}`).value = `✅ RECOMMENDATION: EaaS model wins in ${eaasWinCountEN} of ${decisionsEN.length} criteria`;
  }
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
  excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'center' };

  cfoRowEN++;
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);
  // Use formula for final summary when withFormulas=true
  if (withFormulas) {
    excelSheet6.getCell(`B${cfoRowEN}`).value = { formula: `"Expected savings: "\n&ROUND($C$${kpiTotalTysRowEN},0)\n&" k${currencyLabel} over ${cfoPeriod} years with zero CAPEX"` };
  } else {
    excelSheet6.getCell(`B${cfoRowEN}`).value = `Expected savings: ${roundNum(baseTotalSavings, 0)} k${currencyLabel} over ${cfoPeriod} years with zero CAPEX`;
  }
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'center' };

  // Footer
  cfoRowEN += 3;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Generated: ${new Date().toLocaleDateString('en-GB')} | Pagra Energy Studio`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);

  console.log('✅ Sheet 6: CFO Analysis (EN) created - FULL VERSION');

  // ========== BANKABILITY SHEETS (if data available) ==========
  if (bankabilityData && typeof Bankability !== 'undefined') {
    console.log('📊 Adding Bankability sheets to Excel...');

    // Get financing params
    const financingParams = getBankabilityFinancingParams();
    const covenant = financingParams.covenantMinDSCR || 1.20;

    // ========== SHEET 7: Assumptions_Financing ==========
    const excelSheet7 = excelWorkbook.addWorksheet('Assumptions_Financing');
    excelSheet7.columns = [
      { width: 3 },   // A: margin
      { width: 30 },  // B: parameter name
      { width: 18 },  // C: value
      { width: 30 }   // D: description
    ];
    excelSheet7.views = [{ showGridLines: false }];

    let assRow = 1;
    excelSheet7.mergeCells(`B${assRow}:D${assRow}`);
    excelSheet7.getCell(`B${assRow}`).value = 'FINANCING ASSUMPTIONS';
    excelSheet7.getCell(`B${assRow}`).font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };

    assRow += 2;
    const assumptionsData = [
      ['Debt Amount', financingParams.debtAmount, 'PLN'],
      ['Tenor', financingParams.tenorYears, 'years'],
      ['Interest Rate', financingParams.interestRate, 'p.a.'],
      ['Repayment Type', financingParams.repaymentType, ''],
      ['Grace Period', financingParams.graceYears, 'years'],
      ['Covenant Min DSCR', covenant, ''],
      ['Target DSCR', 1.25, 'for implied capacity'],
      ['Fees Rate', financingParams.feesRate || 0.005, 'p.a.']
    ];

    assumptionsData.forEach(([param, value, desc]) => {
      excelSheet7.getCell(`B${assRow}`).value = param;
      excelSheet7.getCell(`B${assRow}`).font = { bold: true };

      if (typeof value === 'number' && (param.includes('Rate') || param.includes('DSCR'))) {
        excelSheet7.getCell(`C${assRow}`).value = value;
        excelSheet7.getCell(`C${assRow}`).numFmt = param.includes('DSCR') ? '0.00' : '0.00%';
      } else {
        excelSheet7.getCell(`C${assRow}`).value = value;
        if (typeof value === 'number') {
          excelSheet7.getCell(`C${assRow}`).numFmt = '#,##0';
        }
      }
      excelSheet7.getCell(`C${assRow}`).font = { color: { argb: 'FF1565C0' } };
      excelSheet7.getCell(`D${assRow}`).value = desc;
      excelSheet7.getCell(`D${assRow}`).font = { italic: true, color: { argb: 'FF757575' } };
      assRow++;
    });

    // Store row references for formulas
    const covenantCellRef = `Assumptions_Financing!$C$${assRow - 3}`;  // Covenant row
    console.log('✅ Sheet 7: Assumptions_Financing created');

    // ========== SHEET 8: Cashflow ==========
    const excelSheet8 = excelWorkbook.addWorksheet('Cashflow');
    excelSheet8.columns = [
      { width: 6 },   // A: Year
      { width: 14 },  // B: Revenue_P50
      { width: 12 },  // C: OPEX_P50
      { width: 14 },  // D: CFADS_P50
      { width: 14 },  // E: DebtService
      { width: 10 },  // F: DSCR_P50
      { width: 14 },  // G: Revenue_P90
      { width: 12 },  // H: OPEX_P90
      { width: 14 },  // I: CFADS_P90
      { width: 10 },  // J: DSCR_P90
      { width: 14 },  // K: Revenue_P97
      { width: 12 },  // L: OPEX_P97
      { width: 14 },  // M: CFADS_P97
      { width: 10 },  // N: DSCR_P97
      { width: 12 }   // O: Flag_Below
    ];
    excelSheet8.views = [{ state: 'frozen', ySplit: 1 }];

    // Header row
    const cfHeaders = [
      'Year',
      'Revenue_P50', 'OPEX_P50', 'CFADS_P50', 'DebtService', 'DSCR_P50',
      'Revenue_P90', 'OPEX_P90', 'CFADS_P90', 'DSCR_P90',
      'Revenue_P97', 'OPEX_P97', 'CFADS_P97', 'DSCR_P97',
      'Flag_Below'
    ];
    cfHeaders.forEach((header, i) => {
      const cell = excelSheet8.getCell(1, i + 1);
      cell.value = header;
      cell.font = { bold: true, color: { argb: 'FFFFFFFF' } };
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1565C0' } };
      cell.alignment = { horizontal: 'center' };
    });

    // Data rows with formulas
    const scenarios = ['P50', 'P90', 'P97'];
    const years = bankabilityData.scenarios?.P90?.cashflow
      ? Object.keys(bankabilityData.scenarios.P90.cashflow).sort((a, b) => a - b)
      : [];

    let cfRow = 2;
    const dscrP90StartRow = cfRow;

    years.forEach(year => {
      const rowNum = cfRow;

      // Year column
      excelSheet8.getCell(`A${rowNum}`).value = parseInt(year);

      // P50 data
      const p50 = bankabilityData.scenarios?.P50?.cashflow?.[year] || {};
      excelSheet8.getCell(`B${rowNum}`).value = p50.revenue || 0;
      excelSheet8.getCell(`B${rowNum}`).numFmt = '#,##0';
      excelSheet8.getCell(`C${rowNum}`).value = p50.opex || 0;
      excelSheet8.getCell(`C${rowNum}`).numFmt = '#,##0';

      // CFADS_P50 with formula
      if (withFormulas) {
        excelSheet8.getCell(`D${rowNum}`).value = { formula: `B${rowNum}-C${rowNum}`, result: p50.cfads || 0 };
      } else {
        excelSheet8.getCell(`D${rowNum}`).value = p50.cfads || 0;
      }
      excelSheet8.getCell(`D${rowNum}`).numFmt = '#,##0';

      // DebtService (same for all scenarios)
      excelSheet8.getCell(`E${rowNum}`).value = p50.debtService || 0;
      excelSheet8.getCell(`E${rowNum}`).numFmt = '#,##0';

      // DSCR_P50 with formula (empty string if DS=0, not "n/a" text!)
      if (withFormulas) {
        excelSheet8.getCell(`F${rowNum}`).value = {
          formula: `IF(E${rowNum}>0,D${rowNum}/E${rowNum},"")`,
          result: p50.dscr !== null ? p50.dscr : ''
        };
      } else {
        excelSheet8.getCell(`F${rowNum}`).value = p50.dscr !== null ? p50.dscr : '';
      }
      excelSheet8.getCell(`F${rowNum}`).numFmt = '0.00';

      // P90 data
      const p90 = bankabilityData.scenarios?.P90?.cashflow?.[year] || {};
      excelSheet8.getCell(`G${rowNum}`).value = p90.revenue || 0;
      excelSheet8.getCell(`G${rowNum}`).numFmt = '#,##0';
      excelSheet8.getCell(`H${rowNum}`).value = p90.opex || 0;
      excelSheet8.getCell(`H${rowNum}`).numFmt = '#,##0';

      // CFADS_P90 with formula
      if (withFormulas) {
        excelSheet8.getCell(`I${rowNum}`).value = { formula: `G${rowNum}-H${rowNum}`, result: p90.cfads || 0 };
      } else {
        excelSheet8.getCell(`I${rowNum}`).value = p90.cfads || 0;
      }
      excelSheet8.getCell(`I${rowNum}`).numFmt = '#,##0';

      // DSCR_P90 with formula
      if (withFormulas) {
        excelSheet8.getCell(`J${rowNum}`).value = {
          formula: `IF(E${rowNum}>0,I${rowNum}/E${rowNum},"")`,
          result: p90.dscr !== null ? p90.dscr : ''
        };
      } else {
        excelSheet8.getCell(`J${rowNum}`).value = p90.dscr !== null ? p90.dscr : '';
      }
      excelSheet8.getCell(`J${rowNum}`).numFmt = '0.00';

      // P97 data
      const p97 = bankabilityData.scenarios?.P97?.cashflow?.[year] || {};
      excelSheet8.getCell(`K${rowNum}`).value = p97.revenue || 0;
      excelSheet8.getCell(`K${rowNum}`).numFmt = '#,##0';
      excelSheet8.getCell(`L${rowNum}`).value = p97.opex || 0;
      excelSheet8.getCell(`L${rowNum}`).numFmt = '#,##0';

      // CFADS_P97 with formula
      if (withFormulas) {
        excelSheet8.getCell(`M${rowNum}`).value = { formula: `K${rowNum}-L${rowNum}`, result: p97.cfads || 0 };
      } else {
        excelSheet8.getCell(`M${rowNum}`).value = p97.cfads || 0;
      }
      excelSheet8.getCell(`M${rowNum}`).numFmt = '#,##0';

      // DSCR_P97 with formula
      if (withFormulas) {
        excelSheet8.getCell(`N${rowNum}`).value = {
          formula: `IF(E${rowNum}>0,M${rowNum}/E${rowNum},"")`,
          result: p97.dscr !== null ? p97.dscr : ''
        };
      } else {
        excelSheet8.getCell(`N${rowNum}`).value = p97.dscr !== null ? p97.dscr : '';
      }
      excelSheet8.getCell(`N${rowNum}`).numFmt = '0.00';

      // Flag_Below_Covenant (based on P90 DSCR)
      if (withFormulas) {
        excelSheet8.getCell(`O${rowNum}`).value = {
          formula: `IF(AND(J${rowNum}<>"",J${rowNum}<${covenant}),TRUE,FALSE)`,
          result: p90.flags?.belowCovenant || false
        };
      } else {
        excelSheet8.getCell(`O${rowNum}`).value = p90.flags?.belowCovenant || false;
      }

      // Conditional formatting for breach rows
      if (p90.flags?.belowCovenant) {
        for (let c = 1; c <= 15; c++) {
          excelSheet8.getRow(rowNum).getCell(c).fill = {
            type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' }
          };
        }
      }

      cfRow++;
    });
    const dscrP90EndRow = cfRow - 1;

    console.log('✅ Sheet 8: Cashflow created');

    // ========== SHEET 9: Decision_Summary ==========
    const excelSheet9 = excelWorkbook.addWorksheet('Decision_Summary');
    excelSheet9.columns = [
      { width: 3 },   // A: margin
      { width: 28 },  // B: KPI name
      { width: 16 },  // C: value
      { width: 35 }   // D: description/formula
    ];
    excelSheet9.views = [{ showGridLines: false }];

    let dsRow = 1;
    excelSheet9.mergeCells(`B${dsRow}:D${dsRow}`);
    excelSheet9.getCell(`B${dsRow}`).value = 'BANKABILITY DECISION SUMMARY';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };
    excelSheet9.getCell(`B${dsRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

    dsRow += 2;
    excelSheet9.getCell(`B${dsRow}`).value = 'Option Type';
    excelSheet9.getCell(`C${dsRow}`).value = 'EaaS';
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true };

    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Analysis Mode';
    excelSheet9.getCell(`C${dsRow}`).value = financingParams.debtAmount > 0 ? 'DSCR (Debt assigned)' : 'No debt assigned';
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true, color: { argb: financingParams.debtAmount > 0 ? 'FF1565C0' : 'FF757575' } };

    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Covenant Min DSCR';
    excelSheet9.getCell(`C${dsRow}`).value = covenant;
    excelSheet9.getCell(`C${dsRow}`).numFmt = '0.00';
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true };
    const covenantRowInDS = dsRow;

    dsRow += 2;
    excelSheet9.mergeCells(`B${dsRow}:D${dsRow}`);
    excelSheet9.getCell(`B${dsRow}`).value = 'KEY METRICS @P90';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };

    // Min DSCR with formula
    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Min DSCR @P90';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true };
    if (withFormulas) {
      excelSheet9.getCell(`C${dsRow}`).value = {
        formula: `MIN(Cashflow!J${dscrP90StartRow}:J${dscrP90EndRow})`,
        result: bankabilityData.scenarios?.P90?.kpi?.minDSCR || ''
      };
    } else {
      excelSheet9.getCell(`C${dsRow}`).value = bankabilityData.scenarios?.P90?.kpi?.minDSCR || '';
    }
    excelSheet9.getCell(`C${dsRow}`).numFmt = '0.00';
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true, size: 14, color: { argb: 'FF1565C0' } };
    excelSheet9.getCell(`D${dsRow}`).value = withFormulas ? '=MIN(Cashflow!J:J)' : '';
    excelSheet9.getCell(`D${dsRow}`).font = { italic: true, color: { argb: 'FF757575' } };
    const minDscrRow = dsRow;

    // Avg DSCR (weighted) with formula
    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Avg DSCR @P90 (weighted)';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true };
    if (withFormulas) {
      excelSheet9.getCell(`C${dsRow}`).value = {
        formula: `IF(SUM(Cashflow!E${dscrP90StartRow}:E${dscrP90EndRow})=0,"N/A",SUMPRODUCT(Cashflow!I${dscrP90StartRow}:I${dscrP90EndRow})/SUM(Cashflow!E${dscrP90StartRow}:E${dscrP90EndRow}))`,
        result: bankabilityData.scenarios?.P90?.kpi?.avgDSCRWeighted || ''
      };
    } else {
      excelSheet9.getCell(`C${dsRow}`).value = bankabilityData.scenarios?.P90?.kpi?.avgDSCRWeighted || '';
    }
    excelSheet9.getCell(`C${dsRow}`).numFmt = '0.00';
    excelSheet9.getCell(`D${dsRow}`).value = '= sum(CFADS) / sum(DebtService)';
    excelSheet9.getCell(`D${dsRow}`).font = { italic: true, color: { argb: 'FF757575' } };

    // Worst Year
    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Worst Year';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true };
    if (withFormulas) {
      excelSheet9.getCell(`C${dsRow}`).value = {
        formula: `INDEX(Cashflow!A${dscrP90StartRow}:A${dscrP90EndRow},MATCH(MIN(Cashflow!J${dscrP90StartRow}:J${dscrP90EndRow}),Cashflow!J${dscrP90StartRow}:J${dscrP90EndRow},0))`,
        result: bankabilityData.scenarios?.P90?.kpi?.worstYear || ''
      };
    } else {
      excelSheet9.getCell(`C${dsRow}`).value = bankabilityData.scenarios?.P90?.kpi?.worstYear || '';
    }
    excelSheet9.getCell(`D${dsRow}`).value = 'Year with lowest DSCR@P90';
    excelSheet9.getCell(`D${dsRow}`).font = { italic: true, color: { argb: 'FF757575' } };

    // Headroom with formula
    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Headroom vs Covenant';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true };
    if (withFormulas) {
      excelSheet9.getCell(`C${dsRow}`).value = {
        formula: `IF(C${covenantRowInDS}=0,"N/A",(C${minDscrRow}/C${covenantRowInDS})-1)`,
        result: bankabilityData.scenarios?.P90?.kpi?.headroom || ''
      };
    } else {
      excelSheet9.getCell(`C${dsRow}`).value = bankabilityData.scenarios?.P90?.kpi?.headroom || '';
    }
    excelSheet9.getCell(`C${dsRow}`).numFmt = '+0.0%;-0.0%';
    const headroomVal = bankabilityData.scenarios?.P90?.kpi?.headroom;
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true, color: { argb: headroomVal >= 0 ? 'FF2E7D32' : 'FFC62828' } };
    excelSheet9.getCell(`D${dsRow}`).value = '= (MinDSCR / Covenant) - 1';
    excelSheet9.getCell(`D${dsRow}`).font = { italic: true, color: { argb: 'FF757575' } };

    // Years below covenant with formula
    dsRow++;
    excelSheet9.getCell(`B${dsRow}`).value = 'Years Below Covenant';
    excelSheet9.getCell(`B${dsRow}`).font = { bold: true };
    if (withFormulas) {
      excelSheet9.getCell(`C${dsRow}`).value = {
        formula: `COUNTIF(Cashflow!O${dscrP90StartRow}:O${dscrP90EndRow},TRUE)`,
        result: bankabilityData.scenarios?.P90?.kpi?.yearsBelowCovenant?.length || 0
      };
    } else {
      excelSheet9.getCell(`C${dsRow}`).value = bankabilityData.scenarios?.P90?.kpi?.yearsBelowCovenant?.length || 0;
    }
    const belowCount = bankabilityData.scenarios?.P90?.kpi?.yearsBelowCovenant?.length || 0;
    excelSheet9.getCell(`C${dsRow}`).font = { bold: true, color: { argb: belowCount > 0 ? 'FFC62828' : 'FF2E7D32' } };
    if (belowCount > 0) {
      excelSheet9.getCell(`C${dsRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };
    }

    // Status summary
    dsRow += 2;
    excelSheet9.mergeCells(`B${dsRow}:D${dsRow}`);
    if (belowCount === 0 && financingParams.debtAmount > 0) {
      excelSheet9.getCell(`B${dsRow}`).value = '✓ DSCR meets covenant in all years';
      excelSheet9.getCell(`B${dsRow}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
      excelSheet9.getCell(`B${dsRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    } else if (belowCount > 0) {
      excelSheet9.getCell(`B${dsRow}`).value = `⚠ DSCR BREACH in ${belowCount} year(s) - review required`;
      excelSheet9.getCell(`B${dsRow}`).font = { bold: true, size: 12, color: { argb: 'FFC62828' } };
      excelSheet9.getCell(`B${dsRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };
    } else {
      excelSheet9.getCell(`B${dsRow}`).value = 'ℹ No debt assigned - configure financing in Assumptions sheet';
      excelSheet9.getCell(`B${dsRow}`).font = { bold: true, size: 11, color: { argb: 'FF757575' } };
    }

    console.log('✅ Sheet 9: Decision_Summary created');
  }

  // ========== OPTIONAL: RDN vs TARYFA SHEET (EaaS Export) ==========
  const rdnResultEaaS = (typeof rdnMetrics !== 'undefined') && rdnMetrics[currentVariant];
  if (rdnResultEaaS) {
    try {
      const sheetRdn = excelWorkbook.addWorksheet('RDN vs Taryfa');
      const monthNamesRdn = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                              'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];
      sheetRdn.columns = [
        { width: 2 },  // A: margin
        { width: 30 }, // B: Parameter
        { width: 22 }, // C: Fixed
        { width: 22 }, // D: RDN
        { width: 22 }, // E: Delta
      ];

      sheetRdn.getCell('B1').value = `RDN vs TARYFA - Scenariusz ${scenarioName}`;
      sheetRdn.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FFE65100' } };
      sheetRdn.mergeCells('B1:E1');

      let rdnRow = 3;
      const hdrFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF424242' } };
      const hdrFont = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };

      ['Parametr', 'Taryfa Stała/ToU', 'RDN Dynamiczne', 'Delta'].forEach((h, i) => {
        const col = ['B','C','D','E'][i];
        sheetRdn.getCell(`${col}${rdnRow}`).value = h;
        sheetRdn.getCell(`${col}${rdnRow}`).fill = hdrFill;
        sheetRdn.getCell(`${col}${rdnRow}`).font = hdrFont;
        sheetRdn.getCell(`${col}${rdnRow}`).alignment = { horizontal: 'center' };
      });
      rdnRow++;

      [['Roczne oszczędności [PLN]', rdnResultEaaS.fixed_annual_savings_pln, rdnResultEaaS.rdn_annual_savings_pln],
       ['Cena efektywna [PLN/MWh]', rdnResultEaaS.fixed_total_price_plnmwh, rdnResultEaaS.rdn_avg_effective_price_plnmwh],
      ].forEach(([label, fixedV, rdnV]) => {
        sheetRdn.getCell(`B${rdnRow}`).value = label;
        sheetRdn.getCell(`B${rdnRow}`).font = { bold: true };
        sheetRdn.getCell(`C${rdnRow}`).value = Math.round(fixedV);
        sheetRdn.getCell(`C${rdnRow}`).numFmt = '#,##0';
        sheetRdn.getCell(`D${rdnRow}`).value = Math.round(rdnV);
        sheetRdn.getCell(`D${rdnRow}`).numFmt = '#,##0';
        sheetRdn.getCell(`E${rdnRow}`).value = Math.round(rdnV - fixedV);
        sheetRdn.getCell(`E${rdnRow}`).numFmt = '+#,##0;-#,##0;0';
        sheetRdn.getCell(`E${rdnRow}`).font = { color: { argb: (rdnV - fixedV) >= 0 ? 'FF2E7D32' : 'FFC62828' }, bold: true };
        rdnRow++;
      });

      rdnRow += 2;
      ['Miesiąc', 'Oszcz. Taryfa [PLN]', 'Oszcz. RDN [PLN]', 'Delta [PLN]'].forEach((h, i) => {
        const col = ['B','C','D','E'][i];
        sheetRdn.getCell(`${col}${rdnRow}`).value = h;
        sheetRdn.getCell(`${col}${rdnRow}`).fill = hdrFill;
        sheetRdn.getCell(`${col}${rdnRow}`).font = hdrFont;
        sheetRdn.getCell(`${col}${rdnRow}`).alignment = { horizontal: 'center' };
      });
      rdnRow++;

      if (rdnResultEaaS.monthly_comparison) {
        rdnResultEaaS.monthly_comparison.forEach((m, i) => {
          const d = m.rdn_savings_pln - m.fixed_savings_pln;
          sheetRdn.getCell(`B${rdnRow}`).value = monthNamesRdn[i];
          sheetRdn.getCell(`C${rdnRow}`).value = Math.round(m.fixed_savings_pln);
          sheetRdn.getCell(`C${rdnRow}`).numFmt = '#,##0';
          sheetRdn.getCell(`D${rdnRow}`).value = Math.round(m.rdn_savings_pln);
          sheetRdn.getCell(`D${rdnRow}`).numFmt = '#,##0';
          sheetRdn.getCell(`E${rdnRow}`).value = Math.round(d);
          sheetRdn.getCell(`E${rdnRow}`).numFmt = '+#,##0;-#,##0;0';
          sheetRdn.getCell(`E${rdnRow}`).font = { color: { argb: d >= 0 ? 'FF2E7D32' : 'FFC62828' }, bold: true };
          rdnRow++;
        });
      }
      console.log('✅ RDN vs Taryfa sheet added to EaaS export');
    } catch (rdnErr) {
      console.warn('⚠️ Failed to add RDN sheet to EaaS export:', rdnErr);
    }
  }

  // TCSL Audit sheet (only in RDN mode)
  if (isRdnExport && rdnBLEaas) {
    try {
      const params = getEconomicParameters();
      const pvDegYear1 = pctToDecimal(systemSettings?.pvDegradationYear1 !== undefined ? systemSettings.pvDegradationYear1 : 1.0);
      addTcslAuditSheet(excelWorkbook, rdnBLEaas, {
        inflationRate,
        discountRate,
        pvDegYear1,
        pvDegYear2Plus: params.degradation_rate,
        analysisPeriod: centralizedCalc.common.analysisPeriod || params.analysis_period || 30,
      }, logoImageId);
    } catch (auditErr) {
      console.warn('⚠️ Failed to add TCSL audit sheet to EaaS export:', auditErr);
    }
  }

  // Apply watermark (multi-layer document traceability)
  if (window.applyExcelWatermark) {
    try {
      const wmDataRows = [];
      for (let y = 1; y <= (analysisPeriod || 30); y++) wmDataRows.push(dataStartRow + y - 1);
      window.applyExcelWatermark(excelWorkbook, {
        visibleSheets: ['Podsumowanie EaaS', 'EaaS Summary'],
        stegoTargets: [{ sheet: 'EaaS Rok po Roku', rows: wmDataRows, cols: [4, 5, 6, 7, 8] }],
      });
    } catch (wmErr) { console.warn('⚠️ Watermark failed:', wmErr); }
  }

  // Generate filename
  const timestamp = new Date().toISOString().slice(0, 10);
  const formulasSuffix = withFormulas ? '_FORMULY' : '';
  const rdnPrefix = window._rdnExportMode ? 'EaaS_RDN' : 'EaaS';
  const filename = `${rdnPrefix}_Analiza_${currentVariant}_${capacityKwp}kWp_${scenarioName}_${timestamp}${formulasSuffix}.xlsx`;

  // Save file using ExcelJS
  excelWorkbook.xlsx.writeBuffer().then(buffer => {
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    saveAs(blob, filename);
    console.log('✅ EaaS analysis exported to:', filename, withFormulas ? '(with formulas)' : '');
  }).catch(err => {
    console.error('❌ Error exporting Excel:', err);
    alert('Błąd eksportu Excel: ' + err.message);
  });
  } catch (exportErr) {
    console.error('❌ EaaS Excel export failed:', exportErr);
    alert('Błąd eksportu EaaS Excel: ' + exportErr.message);
  }
}

// ============================================================================
// === TCSL AUDIT SHEET - shared by CAPEX RDN and EaaS RDN exports ===
// ============================================================================
/**
 * Adds an audit sheet "Dane bazowe TCSL (Rok 1)" to any ExcelJS workbook.
 * Clean look styling matching capex-export sheets. Logo + hidden grids.
 * FULL breakdown of every fee component with rates and Excel FORMULAS.
 *
 * FIXED ROW LAYOUT (for cross-sheet references):
 *   Columns: B=labels, C=stawka, D=bez PV [PLN], E=z PV [PLN], F=oszczednosc [PLN]
 *   Row 1-3: Title (merged, blue text, logo top-right)
 *   Row 5-7: Source info (year, MWh volumes)
 *   Row 9:   Section A header
 *   Row 10:  Column headers (dark)
 *   Row 11:  Energia aktywna RDN           D=bezPV  E=zPV   F=D11-E11
 *   Row 12:  Section B header
 *   Row 13:  Opl. dystrybucyjna zmienna    C=rate   D/E=grid*rate  F=D13-E13
 *   Row 14:  Opl. jakosciowa               C=rate   D/E=grid*rate  F=D14-E14
 *   Row 15:  Opl. OZE                      C=rate   D/E=grid*rate  F=D15-E15
 *   Row 16:  Opl. kogeneracyjna             C=rate   D/E=grid*rate  F=D16-E16
 *   Row 17:  Akcyza                        C=rate   D/E=grid*rate  F=D17-E17
 *   Row 18:  SUMA ZMIENNE (A+B)            D=SUM   E=SUM   F=D18-E18  <- energyFeesSavings
 *   Row 20:  Section C header
 *   Row 21:  OPLATA MOCOWA                 D=val   E=val   F=D21-E21  <- capacitySavings
 *   Row 24:  Section D header
 *   Row 25:  Opl. dystr. stala             C=rate   D/E=rate*kW*12
 *   Row 26:  Abonament OSD                 C=rate   D/E=rate*12
 *   Row 27:  Opl. przejsciowa              C=rate   D/E=rate*12
 *   Row 28:  Opl. handlowa                 C=rate   D/E=rate*12
 *   Row 29:  SUMA STALE (D)                D=SUM   E=SUM   F=D29-E29
 *   Row 31:  TCSL RAZEM (A+B+C+D)          D=SUM   E=SUM   F=D31-E31  <- totalSavings
 *
 * @param {ExcelJS.Workbook} workbook
 * @param {Object} rdnBaseline
 * @param {Object} econParams
 * @param {number|null} logoImageId - from workbook.addImage()
 * @returns {{ sheetName, energyFees:'F18', capacity:'F21', total:'F31', nopvTcsl:'D31' }}
 */
function addTcslAuditSheet(workbook, rdnBaseline, econParams, logoImageId) {
  const r = (window.tcslMetrics || tcslMetrics)[currentVariant];
  if (!r || !rdnBaseline) {
    console.warn('addTcslAuditSheet: brak danych TCSL lub rdnBaseline');
    return null;
  }

  const SHEET = 'Dane bazowe TCSL (Rok 1)';
  const ws = workbook.addWorksheet(SHEET);
  const fmt = v => Math.round(v);
  const pct = v => +(decimalToPct(v)).toFixed(2);
  const numFmt = '#,##0';

  // Clean look: hide grid lines and row/col headers
  ws.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Read individual fee rates from settings
  const s = systemSettings || {};
  const fmf = s.fixedMonthlyFees || {};
  const cfc = s.capacityFeeConfig || {};
  const distRate = s.distribution || 200;
  const qualRate = s.qualityFee || 10;
  const ozeRate = s.ozeFee || 7;
  const cogenRate = s.cogenerationFee || 10;
  const exciseRate = s.exciseTax || 5;
  const distFixedPerKw = fmf.distFixedRatePerKwMonth || 9.14;
  const contractedPowerKw = fmf.contractedPowerKw || 50;
  const osdSubMonth = fmf.osdSubscriptionFeeMonth || 5.54;
  const transitionFeeMonth = fmf.transitionFeeMonth || 0;
  const supplierFeeMonth = fmf.supplierTradeFeeMonth || 0;
  const somRate = cfc.somRate || 0.2194;

  // Energy volumes from TCSL
  const gridNoPvMwh = kwhToMwh(r.annual_consumption_kwh || 0);
  const gridWPvMwh = kwhToMwh(r.annual_grid_import_kwh || 0);
  const selfConsumedMwh = kwhToMwh(r.annual_self_consumed_kwh || 0);

  // Column widths
  ws.columns = [
    { width: 3 },   // A - margin (clean look)
    { width: 48 },  // B - labels
    { width: 16 },  // C - Stawka
    { width: 16 },  // D - Bez PV
    { width: 16 },  // E - Z PV
    { width: 16 },  // F - Oszczednosc
  ];

  // Style constants (matching capex-export clean look)
  const titleFont = { bold: true, size: 16, color: { argb: 'FF1565C0' } };
  const sectionFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  const sectionFont = { bold: true, size: 11, color: { argb: 'FF1565C0' } };
  const colHdrFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF37474F' } };
  const colHdrFont = { bold: true, size: 9, color: { argb: 'FFFFFFFF' } };
  const sumFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };
  const greenFont = { bold: true, color: { argb: 'FF2E7D32' } };
  const totalFill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  const totalFont = { bold: true, size: 13, color: { argb: 'FF2E7D32' } };
  const greyNote = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
  const paramLabel = { color: { argb: 'FF616161' } };
  const paramValue = { bold: true, color: { argb: 'FF1976D2' } };
  const subtleBorder = { bottom: { style: 'thin', color: { argb: 'FFEEEEEE' } } };

  // Helper: set cell with number format
  const setNum = (cell, val) => { ws.getCell(cell).value = fmt(val); ws.getCell(cell).numFmt = numFmt; };
  const setFormula = (cell, formula, result) => {
    ws.getCell(cell).value = { formula, result: fmt(result) };
    ws.getCell(cell).numFmt = numFmt;
  };

  // =============================================
  // ROW 1-3: TITLE (clean look - blue text, no background fill)
  // =============================================
  ws.getRow(1).height = 20;
  ws.getRow(2).height = 20;
  ws.getRow(3).height = 24;
  ws.mergeCells('B1:F3');
  ws.getCell('B1').value = 'DANE BAZOWE - ROK 1 (analiza TCSL z cenami RDN)';
  ws.getCell('B1').font = titleFont;
  ws.getCell('B1').alignment = { horizontal: 'center', vertical: 'middle' };

  // Logo (top-right)
  if (logoImageId !== null && logoImageId !== undefined) {
    ws.addImage(logoImageId, {
      tl: { col: 5.2, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  // ROW 5-7: Source info (parameter style)
  ws.getCell('B5').value = 'Zrodlo danych:';
  ws.getCell('B5').font = paramLabel;
  ws.getCell('B5').border = subtleBorder;
  ws.getCell('C5').value = 'Godzinowe ceny RDN (8760h) + rzeczywisty profil zuzycia';
  ws.mergeCells('C5:F5');
  ws.getCell('C5').font = paramValue;
  ws.getCell('C5').border = subtleBorder;

  ws.getCell('B6').value = 'Rok bazowy:';
  ws.getCell('B6').font = paramLabel;
  ws.getCell('B6').border = subtleBorder;
  ws.getCell('C6').value = r.rdn_price_stats?.year || new Date().getFullYear();
  ws.getCell('C6').font = paramValue;
  ws.getCell('C6').border = subtleBorder;

  ws.getCell('B7').value = 'Pobor z sieci bez PV [MWh]:';
  ws.getCell('B7').font = paramLabel;
  ws.getCell('B7').border = subtleBorder;
  ws.getCell('C7').value = +gridNoPvMwh.toFixed(1);
  ws.getCell('C7').font = paramValue;
  ws.getCell('C7').border = subtleBorder;
  ws.getCell('D7').value = 'Pobor z PV [MWh]:';
  ws.getCell('D7').font = paramLabel;
  ws.getCell('D7').border = subtleBorder;
  ws.getCell('E7').value = +gridWPvMwh.toFixed(1);
  ws.getCell('E7').font = paramValue;
  ws.getCell('E7').border = subtleBorder;

  // =============================================
  // ROW 9: SECTION A - ENERGIA AKTYWNA
  // =============================================
  ws.mergeCells('B9:F9');
  ws.getCell('B9').value = 'A. ENERGIA AKTYWNA RDN';
  ws.getCell('B9').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}9`).fill = sectionFill; });

  // ROW 10: Column headers (dark header like capex-export)
  ws.getRow(10).height = 32;
  ['Skladnik kosztu', 'Stawka', 'Bez PV [PLN]', 'Z PV [PLN]', 'Oszczednosc [PLN]'].forEach((h, i) => {
    const cell = ws.getCell(`${['B','C','D','E','F'][i]}10`);
    cell.value = h;
    cell.fill = colHdrFill;
    cell.font = colHdrFont;
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  // ROW 11: Energia aktywna RDN
  const nopvEnergyActive = r.nopv_rdn_energy_active_pln || 0;
  const wpvEnergyActive = r.rdn_energy_active_cost_pln || 0;
  ws.getCell('B11').value = 'Energia aktywna RDN (suma godzinowych: cena_h x pobor_h)';
  ws.getCell('C11').value = 'godzinowe';
  ws.getCell('C11').font = greyNote;
  setNum('D11', nopvEnergyActive);
  setNum('E11', wpvEnergyActive);
  setFormula('F11', 'D11-E11', nopvEnergyActive - wpvEnergyActive);
  ws.getCell('F11').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}11`).border = subtleBorder; });

  // =============================================
  // ROW 12: SECTION B - OPLATY ZMIENNE (per fee)
  // =============================================
  ws.mergeCells('B12:F12');
  ws.getCell('B12').value = 'B. OPLATY ZMIENNE (proporcjonalne do poboru z sieci)';
  ws.getCell('B12').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}12`).fill = sectionFill; });

  // ROW 13: Opl. dystrybucyjna zmienna
  ws.getCell('B13').value = 'Oplata dystrybucyjna zmienna';
  ws.getCell('C13').value = distRate + ' PLN/MWh';
  ws.getCell('C13').font = greyNote;
  setNum('D13', gridNoPvMwh * distRate);
  setNum('E13', gridWPvMwh * distRate);
  setFormula('F13', 'D13-E13', (gridNoPvMwh - gridWPvMwh) * distRate);
  ws.getCell('F13').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}13`).border = subtleBorder; });

  // ROW 14: Opl. jakosciowa
  ws.getCell('B14').value = 'Oplata jakosciowa';
  ws.getCell('C14').value = qualRate + ' PLN/MWh';
  ws.getCell('C14').font = greyNote;
  setNum('D14', gridNoPvMwh * qualRate);
  setNum('E14', gridWPvMwh * qualRate);
  setFormula('F14', 'D14-E14', (gridNoPvMwh - gridWPvMwh) * qualRate);
  ws.getCell('F14').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}14`).border = subtleBorder; });

  // ROW 15: Opl. OZE
  ws.getCell('B15').value = 'Oplata OZE';
  ws.getCell('C15').value = ozeRate + ' PLN/MWh';
  ws.getCell('C15').font = greyNote;
  setNum('D15', gridNoPvMwh * ozeRate);
  setNum('E15', gridWPvMwh * ozeRate);
  setFormula('F15', 'D15-E15', (gridNoPvMwh - gridWPvMwh) * ozeRate);
  ws.getCell('F15').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}15`).border = subtleBorder; });

  // ROW 16: Opl. kogeneracyjna
  ws.getCell('B16').value = 'Oplata kogeneracyjna';
  ws.getCell('C16').value = cogenRate + ' PLN/MWh';
  ws.getCell('C16').font = greyNote;
  setNum('D16', gridNoPvMwh * cogenRate);
  setNum('E16', gridWPvMwh * cogenRate);
  setFormula('F16', 'D16-E16', (gridNoPvMwh - gridWPvMwh) * cogenRate);
  ws.getCell('F16').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}16`).border = subtleBorder; });

  // ROW 17: Akcyza
  ws.getCell('B17').value = 'Akcyza';
  ws.getCell('C17').value = exciseRate + ' PLN/MWh';
  ws.getCell('C17').font = greyNote;
  setNum('D17', gridNoPvMwh * exciseRate);
  setNum('E17', gridWPvMwh * exciseRate);
  setFormula('F17', 'D17-E17', (gridNoPvMwh - gridWPvMwh) * exciseRate);
  ws.getCell('F17').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}17`).border = subtleBorder; });

  // ROW 18: SUMA ZMIENNE (A+B) - ALL FORMULAS
  ws.getCell('B18').value = 'SUMA KOSZTY ZMIENNE (A + B)';
  setFormula('D18', 'D11+SUM(D13:D17)', nopvEnergyActive + gridNoPvMwh * (distRate + qualRate + ozeRate + cogenRate + exciseRate));
  setFormula('E18', 'E11+SUM(E13:E17)', wpvEnergyActive + gridWPvMwh * (distRate + qualRate + ozeRate + cogenRate + exciseRate));
  setFormula('F18', 'D18-E18', rdnBaseline.energyFeesSavingsYear1);
  ws.getRow(18).font = { bold: true };
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}18`).fill = sumFill; });

  // =============================================
  // ROW 20: SECTION C - OPLATA MOCOWA
  // =============================================
  ws.mergeCells('B20:F20');
  ws.getCell('B20').value = 'C. OPLATA MOCOWA (SOM x pobor w godzinach wybranych 7-22)';
  ws.getCell('B20').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}20`).fill = sectionFill; });

  const nopvCapacity = r.capacity_fee_without_pv_pln || 0;
  const wpvCapacity = r.capacity_fee_with_pv_pln || 0;

  // ROW 21: Oplata mocowa
  ws.getCell('B21').value = `Oplata mocowa (stawka SOM: ${somRate} PLN/kWh)`;
  ws.getCell('C21').value = `K=${rdnBaseline.kclassNoPv}/${rdnBaseline.kclassWithPv}`;
  ws.getCell('C21').font = { bold: true, color: { argb: 'FF1976D2' } };
  setNum('D21', nopvCapacity);
  setNum('E21', wpvCapacity);
  setFormula('F21', 'D21-E21', nopvCapacity - wpvCapacity);
  ws.getCell('F21').font = greenFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}21`).border = subtleBorder; });

  ws.getCell('B22').value = `  Klasa K bez PV: ${rdnBaseline.kclassNoPv} -> z PV: ${rdnBaseline.kclassWithPv} (PV obniza szczyt -> nizsza klasa)`;
  ws.getCell('B22').font = greyNote;

  // =============================================
  // ROW 24: SECTION D - OPLATY STALE
  // =============================================
  ws.mergeCells('B24:F24');
  ws.getCell('B24').value = 'D. OPLATY STALE (miesieczne x 12, niezalezne od PV)';
  ws.getCell('B24').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}24`).fill = sectionFill; });

  const distFixed = distFixedPerKw * contractedPowerKw;
  ws.getCell('B25').value = `Oplata dystrybucyjna stala (${distFixedPerKw} PLN/kW x ${contractedPowerKw} kW)`;
  ws.getCell('C25').value = fmt(distFixed) + ' PLN/mies';
  ws.getCell('C25').font = greyNote;
  setNum('D25', distFixed * 12);
  setNum('E25', distFixed * 12);
  setFormula('F25', 'D25-E25', 0);
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}25`).border = subtleBorder; });

  ws.getCell('B26').value = 'Abonament OSD';
  ws.getCell('C26').value = osdSubMonth.toFixed(2) + ' PLN/mies';
  ws.getCell('C26').font = greyNote;
  setNum('D26', osdSubMonth * 12);
  setNum('E26', osdSubMonth * 12);
  setFormula('F26', 'D26-E26', 0);
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}26`).border = subtleBorder; });

  if (transitionFeeMonth > 0) {
    ws.getCell('B27').value = 'Oplata przejsciowa';
    ws.getCell('C27').value = transitionFeeMonth.toFixed(2) + ' PLN/mies';
    ws.getCell('C27').font = greyNote;
    setNum('D27', transitionFeeMonth * 12);
    setNum('E27', transitionFeeMonth * 12);
    setFormula('F27', 'D27-E27', 0);
    ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}27`).border = subtleBorder; });
  }

  if (supplierFeeMonth > 0) {
    ws.getCell('B28').value = 'Oplata handlowa (sprzedawca)';
    ws.getCell('C28').value = supplierFeeMonth.toFixed(2) + ' PLN/mies';
    ws.getCell('C28').font = greyNote;
    setNum('D28', supplierFeeMonth * 12);
    setNum('E28', supplierFeeMonth * 12);
    setFormula('F28', 'D28-E28', 0);
    ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}28`).border = subtleBorder; });
  }

  // ROW 29: SUMA STALE
  const fixedTotal = (distFixed + osdSubMonth + transitionFeeMonth + supplierFeeMonth) * 12;
  ws.getCell('B29').value = 'SUMA OPLATY STALE (D)';
  setFormula('D29', 'SUM(D25:D28)', fixedTotal);
  setFormula('E29', 'SUM(E25:E28)', fixedTotal);
  setFormula('F29', 'D29-E29', 0);
  ws.getRow(29).font = { bold: true };
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}29`).fill = sumFill; });

  // =============================================
  // ROW 31: TCSL RAZEM - ALL FORMULAS
  // =============================================
  ws.getCell('B31').value = 'TCSL ROCZNY RAZEM (A+B+C+D)';
  setFormula('D31', 'D18+D21+D29', (r.nopv_rdn_tcsl_pln || 0));
  setFormula('E31', 'E18+E21+E29', (r.rdn_tcsl_annual_pln || 0));
  setFormula('F31', 'D31-E31', (r.nopv_rdn_tcsl_pln || 0) - (r.rdn_tcsl_annual_pln || 0));
  ws.getRow(31).font = totalFont;
  ['B','C','D','E','F'].forEach(c => {
    ws.getCell(`${c}31`).fill = totalFill;
    ws.getCell(`${c}31`).border = {
      top: { style: 'medium', color: { argb: 'FF2E7D32' } },
      bottom: { style: 'medium', color: { argb: 'FF2E7D32' } }
    };
  });

  // =============================================
  // ROW 33: WERYFIKACJA
  // =============================================
  ws.getCell('B33').value = 'WERYFIKACJA - wartosci uzyte do projekcji NPV:';
  ws.getCell('B33').font = { bold: true, size: 9, color: { argb: 'FF757575' } };
  ws.getCell('B34').value = '  Oszcz. energia+oplaty zmienne (=F18):';
  ws.getCell('B34').font = { italic: true, size: 9 };
  setFormula('C34', 'F18', rdnBaseline.energyFeesSavingsYear1);
  ws.getCell('B35').value = '  Oszcz. mocowa (=F21):';
  ws.getCell('B35').font = { italic: true, size: 9 };
  setFormula('C35', 'F21', rdnBaseline.capacitySavingsYear1);
  ws.getCell('B36').value = '  Suma oszcz. (=F31):';
  ws.getCell('B36').font = { italic: true, size: 9 };
  setFormula('C36', 'F31', rdnBaseline.totalSavingsYear1);

  // =============================================
  // ROW 38: MONTHLY BREAKDOWN
  // =============================================
  ws.mergeCells('B38:F38');
  ws.getCell('B38').value = 'ROZBICIE MIESIECZNE (ROK 1)';
  ws.getCell('B38').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}38`).fill = sectionFill; });

  ws.getColumn(7).width = 18;   // G
  ws.getColumn(8).width = 18;   // H
  ws.getColumn(9).width = 18;   // I
  ws.getColumn(10).width = 16;  // J

  const mHeaders = ['Miesiac', 'Pobor bez PV\n[MWh]', 'Pobor z PV\n[MWh]', 'Koszt zmienny\nbez PV [PLN]',
    'Koszt zmienny\nz PV [PLN]', 'Oszcz.\nenergia [PLN]', 'Opl. mocowa\nbez PV [PLN]',
    'Opl. mocowa\nz PV [PLN]', 'Oszcz.\nmocowa [PLN]'];
  const mCols = ['B','C','D','E','F','G','H','I','J'];
  ws.getRow(39).height = 36;
  mHeaders.forEach((h, i) => {
    const cell = ws.getCell(`${mCols[i]}39`);
    cell.value = h;
    cell.fill = colHdrFill;
    cell.font = colHdrFont;
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
    cell.border = {
      top: { style: 'thin', color: { argb: 'FF263238' } },
      bottom: { style: 'thin', color: { argb: 'FF263238' } }
    };
  });

  const mNames = ['Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
    'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien'];
  const months = r.monthly_breakdown || [];
  const nopvM = r.nopv_monthly_breakdown || [];

  for (let m = 0; m < 12; m++) {
    const mRow = 40 + m;
    const wpvR = months[m]?.rdn || {};
    const npvR = nopvM[m]?.rdn_nopv || {};
    const gNP = kwhToMwh(npvR.consumption_kwh || npvR.grid_import_kwh || 0);
    const gWP = kwhToMwh(wpvR.grid_import_kwh || 0);
    const cNP = (npvR.energy_active_pln || 0) + (npvR.fees_var_pln || 0);
    const cWP = (wpvR.energy_active_pln || 0) + (wpvR.fees_var_pln || 0);
    const capNP = npvR.capacity_fee_pln || nopvM[m]?.tariff_nopv?.capacity_fee_pln || 0;
    const capWP = wpvR.capacity_fee_pln || months[m]?.tariff?.capacity_fee_pln || 0;

    ws.getCell(`B${mRow}`).value = mNames[m];
    ws.getCell(`C${mRow}`).value = +gNP.toFixed(1);
    ws.getCell(`D${mRow}`).value = +gWP.toFixed(1);
    setNum(`E${mRow}`, cNP);
    setNum(`F${mRow}`, cWP);
    setFormula(`G${mRow}`, `E${mRow}-F${mRow}`, cNP - cWP);
    ws.getCell(`G${mRow}`).font = (cNP - cWP) > 0 ? greenFont : {};
    setNum(`H${mRow}`, capNP);
    setNum(`I${mRow}`, capWP);
    setFormula(`J${mRow}`, `H${mRow}-I${mRow}`, capNP - capWP);
    ws.getCell(`J${mRow}`).font = (capNP - capWP) > 0 ? greenFont : {};

    // Alternating row shading
    if (m % 2 === 0) {
      mCols.forEach(col => {
        ws.getCell(`${col}${mRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFBFBFB' } };
      });
    }
    // Subtle borders on all data rows
    mCols.forEach(col => {
      ws.getCell(`${col}${mRow}`).border = subtleBorder;
    });
  }

  // ROW 52: Monthly SUM
  ws.getCell('B52').value = 'SUMA ROK';
  ['C','D','E','F','G','H','I','J'].forEach(col => {
    ws.getCell(`${col}52`).value = { formula: `SUM(${col}40:${col}51)`, result: 0 };
    ws.getCell(`${col}52`).numFmt = (col === 'C' || col === 'D') ? '#,##0.0' : numFmt;
  });
  ws.getRow(52).font = { bold: true, size: 11 };
  ['B','C','D','E','F','G','H','I','J'].forEach(c => { ws.getCell(`${c}52`).fill = sumFill; });

  // =============================================
  // ROW 54: BILANS ENERGII
  // =============================================
  ws.mergeCells('B54:F54');
  ws.getCell('B54').value = 'BILANS ENERGII (ROK 1)';
  ws.getCell('B54').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}54`).fill = sectionFill; });

  const addInfo = (rw, label, val) => {
    ws.getCell(`B${rw}`).value = label;
    ws.getCell(`B${rw}`).font = paramLabel;
    ws.getCell(`B${rw}`).border = subtleBorder;
    ws.getCell(`C${rw}`).value = val;
    ws.getCell(`C${rw}`).font = paramValue;
    ws.getCell(`C${rw}`).border = subtleBorder;
  };
  addInfo(55, 'Roczne zuzycie energii [MWh]', +gridNoPvMwh.toFixed(1));
  addInfo(56, 'Roczna produkcja PV [MWh]', +kwhToMwh(r.annual_production_kwh || 0).toFixed(1));
  addInfo(57, 'Autokonsumpcja [MWh]', +selfConsumedMwh.toFixed(1));
  addInfo(58, 'Pobor z sieci z PV [MWh]', +gridWPvMwh.toFixed(1));
  const selfPct = gridNoPvMwh > 0 ? decimalToPct(selfConsumedMwh / gridNoPvMwh).toFixed(1) : '0';
  addInfo(59, 'Wspolczynnik autokonsumpcji [%]', +selfPct);

  // =============================================
  // ROW 61: METHODOLOGY
  // =============================================
  ws.mergeCells('B61:F61');
  ws.getCell('B61').value = 'METODOLOGIA PROJEKCJI NA LATA 2-' + (econParams.analysisPeriod || 30);
  ws.getCell('B61').font = sectionFont;
  ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}61`).fill = sectionFill; });

  ws.getCell('B62').value = 'Zasada:';
  ws.getCell('B62').font = { bold: true, color: { argb: 'FF5D4037' } };
  ws.getCell('C62').value = 'Rok 1 = rzeczywiste dane godzinowe RDN z TCSL (ten arkusz)';
  ws.mergeCells('C62:F62');
  ws.getCell('C62').font = paramLabel;
  ws.getCell('C63').value = 'Rok N = Rok1 x degradacja_PV(N) x (1+CPI)^(N-1) - patrz formuly w arkuszu NPV';
  ws.mergeCells('C63:F63');
  ws.getCell('C63').font = paramLabel;

  ws.getCell('B65').value = 'PARAMETRY:';
  ws.getCell('B65').font = { bold: true, color: { argb: 'FF5D4037' } };
  addInfo(66, '  Stopa inflacji (CPI):', pct(econParams.inflationRate ?? 0) + '%');
  addInfo(67, '  Stopa dyskontowa:', pct(econParams.discountRate ?? 0) + '%');
  addInfo(68, '  Degradacja PV rok 1:', pct(econParams.pvDegYear1 ?? 0) + '%');
  addInfo(69, '  Degradacja PV lata 2+:', pct(econParams.pvDegYear2Plus || 0.005) + '%/rok');
  addInfo(70, '  Okres analizy:', (econParams.analysisPeriod || 30) + ' lat');

  ws.getCell('B72').value = 'FORMULY W ARKUSZU NPV (cross-sheet):';
  ws.getCell('B72').font = { bold: true, color: { argb: 'FF5D4037' } };
  ws.getCell('B73').value = '  Oszcz. energ.+opl. rok N =';
  ws.getCell('B73').font = paramLabel;
  ws.getCell('C73').value = "F18 (ten arkusz) x deg_PV(rok) x POWER(1+CPI, rok-1) / 1000";
  ws.mergeCells('C73:F73');
  ws.getCell('C73').font = { italic: true, color: { argb: 'FF757575' } };
  ws.getCell('B74').value = '  Oszcz. mocowa rok N =';
  ws.getCell('B74').font = paramLabel;
  ws.getCell('C74').value = "F21 (ten arkusz) x POWER(1+CPI, rok-1) / 1000  [BEZ degradacji PV]";
  ws.mergeCells('C74:F74');
  ws.getCell('C74').font = { italic: true, color: { argb: 'FF757575' } };
  ws.getCell('B75').value = '  (klasa K sie nie zmienia - PV zawsze obniza szczyt -> nizsza klasa)';
  ws.getCell('B75').font = greyNote;

  // RDN price stats
  const stats = r.rdn_price_stats;
  if (stats) {
    ws.mergeCells('B77:F77');
    ws.getCell('B77').value = 'STATYSTYKI CEN RDN';
    ws.getCell('B77').font = sectionFont;
    ['B','C','D','E','F'].forEach(c => { ws.getCell(`${c}77`).fill = sectionFill; });
    [['Srednia wazona [PLN/MWh]', stats.weighted_avg], ['Min [PLN/MWh]', stats.min],
     ['Max [PLN/MWh]', stats.max], ['Mediana [PLN/MWh]', stats.median]].forEach(([l, v], i) => {
      ws.getCell(`B${78 + i}`).value = l;
      ws.getCell(`B${78 + i}`).font = paramLabel;
      ws.getCell(`B${78 + i}`).border = subtleBorder;
      ws.getCell(`C${78 + i}`).value = v ? Math.round(v) : '-';
      ws.getCell(`C${78 + i}`).font = paramValue;
      ws.getCell(`C${78 + i}`).border = subtleBorder;
      if (v) ws.getCell(`C${78 + i}`).numFmt = numFmt;
    });
  }

  ws.getCell('B83').value = 'Wygenerowano: ' + new Date().toISOString().replace('T', ' ').slice(0, 19);
  ws.getCell('B83').font = { size: 8, color: { argb: 'FF9E9E9E' } };

  console.log('TCSL Audit sheet added (clean look, F18=energyFees, F21=capacity, F31=total)');

  // Return cell references for cross-sheet formulas
  return {
    sheetName: SHEET,
    energyFees: 'F18',   // energyFeesSavingsYear1 [PLN]
    capacity: 'F21',     // capacitySavingsYear1 [PLN]
    total: 'F31',        // totalSavingsYear1 [PLN]
    nopvTcsl: 'D31',     // TCSL bez PV [PLN]
  };
}
window.addTcslAuditSheet = addTcslAuditSheet;

// ============================================================================
// === EXCEL WATERMARKING - multi-layer document traceability ===
// ============================================================================
//
// LAYER 1: Document properties (creator, keywords) - visible in File > Properties
// LAYER 2: veryHidden sheet - invisible in Excel UI, requires VBA Editor to see
// LAYER 3: Zero-width Unicode characters - encoded in text cells, invisible to eye
// LAYER 4: Numeric steganography - fingerprint bits in least-significant decimals
//
// Usage:  applyExcelWatermark(workbook, { visibleSheets: ['Sheet1','Sheet2'] })
// Decode: decodeExcelWatermark(workbook) → { fingerprint, layers }
// ============================================================================

/**
 * Generates a SHA-like fingerprint from input string.
 * Not cryptographic - sufficient for unique document identification.
 */
function generateWatermarkHash(input) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const combined = 4294967296 * (2097151 & h2) + (h1 >>> 0);
  return combined.toString(36).padStart(12, '0');
}

/**
 * Encode a string as zero-width Unicode characters.
 * U+200B (zero-width space) = bit 0
 * U+200C (zero-width non-joiner) = bit 1
 * U+200D (zero-width joiner) = byte separator
 * U+FEFF (BOM) = start/end marker
 */
function encodeZeroWidth(payload) {
  let encoded = '\uFEFF'; // start marker
  for (let i = 0; i < payload.length; i++) {
    if (i > 0) encoded += '\u200D'; // byte separator
    const bits = payload.charCodeAt(i).toString(2).padStart(8, '0');
    for (const bit of bits) {
      encoded += bit === '0' ? '\u200B' : '\u200C';
    }
  }
  encoded += '\uFEFF'; // end marker
  return encoded;
}

/**
 * Decode zero-width characters back to string.
 */
function decodeZeroWidth(text) {
  // Extract only zero-width chars between FEFF markers
  const match = text.match(/\uFEFF([\u200B\u200C\u200D]+)\uFEFF/);
  if (!match) return null;
  const zw = match[1];
  const bytes = zw.split('\u200D');
  let decoded = '';
  for (const byteStr of bytes) {
    if (!byteStr) continue;
    const bits = [...byteStr].map(c => c === '\u200B' ? '0' : '1').join('');
    decoded += String.fromCharCode(parseInt(bits, 2));
  }
  return decoded;
}

/**
 * Inject a numeric steganography fingerprint into data cells.
 * Adds imperceptible values (±0.0000001 to ±0.0000009) to numeric cells.
 * The pattern encodes the fingerprint hash.
 *
 * @param {ExcelJS.Worksheet} sheet - target sheet
 * @param {string} hash - fingerprint hash to encode (alphanumeric)
 * @param {number[]} dataRows - row numbers containing numeric data
 * @param {number[]} dataCols - column numbers containing numeric data
 */
function injectNumericSteganography(sheet, hash, dataRows, dataCols) {
  if (!hash || !dataRows.length || !dataCols.length) return;
  let hashIdx = 0;
  const BASE = 0.00000001; // 10^-8 - invisible in any practical format

  for (const row of dataRows) {
    for (const col of dataCols) {
      const cell = sheet.getRow(row).getCell(col);
      const val = cell.value;
      // Only modify pure numbers (not formulas, not strings)
      if (typeof val === 'number' && val !== 0) {
        const charCode = hash.charCodeAt(hashIdx % hash.length);
        const perturbation = (charCode % 9 + 1) * BASE; // 1-9 × 10^-8
        cell.value = val + perturbation;
        hashIdx++;
      }
    }
  }
}

/**
 * Read numeric steganography from data cells.
 * Extracts the fractional part beyond 6 decimal places.
 */
function readNumericSteganography(sheet, dataRows, dataCols, hashLength) {
  if (!dataRows.length || !dataCols.length) return null;
  const BASE = 0.00000001;
  let recovered = '';
  let count = 0;

  for (const row of dataRows) {
    for (const col of dataCols) {
      if (count >= hashLength) break;
      const cell = sheet.getRow(row).getCell(col);
      const val = typeof cell.value === 'number' ? cell.value :
                  (cell.value?.result || 0);
      if (val === 0) continue;
      // Extract the perturbation: round to 6dp, get diff, divide by BASE
      const rounded = Math.round(val * 1000000) / 1000000;
      const diff = val - rounded;
      const digit = Math.round(diff / BASE);
      if (digit >= 1 && digit <= 9) {
        // Reverse: charCode = (original % 9 + 1) → need hash table to verify
        recovered += digit.toString();
        count++;
      }
    }
    if (count >= hashLength) break;
  }
  return recovered;
}

/**
 * Apply multi-layer watermark to an ExcelJS workbook.
 *
 * @param {ExcelJS.Workbook} workbook - target workbook
 * @param {Object} options
 * @param {string[]} [options.visibleSheets] - names of sheets with text headers to inject zero-width chars
 * @param {Array<{sheet:string, rows:number[], cols:number[]}>} [options.stegoTargets] - sheets+cells for numeric stego
 */
function applyExcelWatermark(workbook, options = {}) {
  // Gather identity data
  const proj = window.parent?.sharedData?.currentProject || {};
  const now = new Date();
  const identity = {
    pid: proj.id || proj.uuid || 'unknown',
    name: proj.name || 'draft',
    cid: proj.companyId || 'none',
    ts: now.toISOString(),
    variant: window.currentVariant || currentVariant || '?',
  };
  const payload = `${identity.pid}|${identity.cid}|${identity.ts}|${identity.variant}`;
  const hash = generateWatermarkHash(payload);
  const shortId = `PV-${identity.pid}-${hash}`;

  console.log(`🔒 Watermark: applying fingerprint ${hash} for project ${identity.pid}`);

  // ── LAYER 1: Document properties ──────────────────────────────
  workbook.creator = 'Analizator PV';
  workbook.lastModifiedBy = 'Analizator PV';
  workbook.created = now;
  workbook.modified = now;
  // Fingerprint hidden in properties - looks like a report ID
  if (workbook.properties) {
    workbook.properties.company = 'Analizator PV';
  }
  // Subject field carries the encoded fingerprint
  workbook.subject = shortId;
  workbook.keywords = `pv,analizator,${hash}`;
  workbook.description = `Report ${hash} generated ${now.toISOString().slice(0, 10)}`;

  // ── LAYER 2: veryHidden sheet ─────────────────────────────────
  const hiddenWs = workbook.addWorksheet('_sys_config');
  hiddenWs.state = 'veryHidden';
  hiddenWs.getCell('A1').value = 'WATERMARK_V1';
  hiddenWs.getCell('A2').value = hash;
  hiddenWs.getCell('A3').value = identity.pid;
  hiddenWs.getCell('A4').value = identity.cid;
  hiddenWs.getCell('A5').value = identity.name;
  hiddenWs.getCell('A6').value = identity.ts;
  hiddenWs.getCell('A7').value = identity.variant;
  hiddenWs.getCell('A8').value = payload;
  // Add verification: hash of payload must match A2
  hiddenWs.getCell('A9').value = generateWatermarkHash(hash + payload); // double-hash for tamper detection

  // ── LAYER 3: Zero-width Unicode in text cells ─────────────────
  const zwPayload = encodeZeroWidth(hash);
  const sheetsToMark = options.visibleSheets || [];
  for (const sheetName of sheetsToMark) {
    const ws = workbook.getWorksheet(sheetName);
    if (!ws) continue;
    // Inject into the first text cell we find in row 1 (title)
    for (let col = 1; col <= 10; col++) {
      const cell = ws.getRow(1).getCell(col);
      if (cell.value && typeof cell.value === 'string' && cell.value.length > 5) {
        cell.value = cell.value + zwPayload;
        break;
      }
    }
  }

  // ── LAYER 4: Numeric steganography ────────────────────────────
  const targets = options.stegoTargets || [];
  for (const t of targets) {
    const ws = workbook.getWorksheet(t.sheet);
    if (!ws) continue;
    injectNumericSteganography(ws, hash, t.rows, t.cols);
  }

  console.log(`🔒 Watermark: 4 layers applied (props, veryHidden, zero-width, stego)`);
  return { hash, shortId, identity };
}

/**
 * Decode/verify watermark from an ExcelJS workbook.
 * Returns all found layers and whether they match.
 */
function decodeExcelWatermark(workbook) {
  const result = { found: false, layers: {}, hash: null, identity: null };

  // Layer 1: properties
  if (workbook.subject && workbook.subject.startsWith('PV-')) {
    result.layers.properties = workbook.subject;
    result.hash = workbook.keywords?.split(',').pop() || null;
    result.found = true;
  }

  // Layer 2: veryHidden sheet
  const hiddenWs = workbook.getWorksheet('_sys_config');
  if (hiddenWs) {
    const marker = hiddenWs.getCell('A1').value;
    if (marker === 'WATERMARK_V1') {
      result.layers.veryHidden = {
        hash: hiddenWs.getCell('A2').value,
        projectId: hiddenWs.getCell('A3').value,
        companyId: hiddenWs.getCell('A4').value,
        projectName: hiddenWs.getCell('A5').value,
        timestamp: hiddenWs.getCell('A6').value,
        variant: hiddenWs.getCell('A7').value,
        payload: hiddenWs.getCell('A8').value,
        verifyHash: hiddenWs.getCell('A9').value,
      };
      result.hash = result.layers.veryHidden.hash;
      result.identity = result.layers.veryHidden;
      result.found = true;

      // Verify tamper detection
      const expectedVerify = generateWatermarkHash(
        result.layers.veryHidden.hash + result.layers.veryHidden.payload
      );
      result.layers.veryHidden.tamperCheck =
        expectedVerify === result.layers.veryHidden.verifyHash ? 'PASS' : 'FAIL';
    }
  }

  // Layer 3: zero-width in any visible sheet
  workbook.eachSheet((ws) => {
    if (ws.state === 'veryHidden') return;
    for (let col = 1; col <= 10; col++) {
      const val = ws.getRow(1).getCell(col).value;
      if (val && typeof val === 'string') {
        const decoded = decodeZeroWidth(val);
        if (decoded) {
          result.layers.zeroWidth = { sheet: ws.name, decoded };
          result.found = true;
          return;
        }
      }
    }
  });

  return result;
}

// Expose watermark functions globally
window.applyExcelWatermark = applyExcelWatermark;
window.decodeExcelWatermark = decodeExcelWatermark;
window.decodeZeroWidth = decodeZeroWidth;
window.generateWatermarkHash = generateWatermarkHash;

// ============================================================================
// === EXPORT WITH FORMULAS (CFO AUDIT VERSION) ===
// ============================================================================
// This function creates the SAME structure as exportEaaSToExcel()
// but adds Excel formulas in Sheet 3 (Analiza CFO) for CFO audit/transparency

async function exportEaaSToExcelWithFormulas() {
  // Call the regular export function with formulas flag = true
  await exportEaaSToExcel(true);
}

// RDN wrapper: swap centralizedMetrics with centralizedMetricsRdn, export, restore
async function exportEaaSRdnToExcel(withFormulas = false) {
  const rdnCalc = centralizedMetricsRdn[currentVariant];
  if (!rdnCalc || !rdnCalc.eaas) {
    alert('Brak danych EaaS (RDN) do eksportu. Najpierw wykonaj analizę TCSL.');
    return;
  }
  const backup = centralizedMetrics[currentVariant];
  centralizedMetrics[currentVariant] = rdnCalc;
  window._rdnExportMode = true;
  try {
    await exportEaaSToExcel(withFormulas);
  } finally {
    centralizedMetrics[currentVariant] = backup;
    window._rdnExportMode = false;
  }
}

// Export functions to window for HTML onclick handlers
window.exportEaaSToExcel = exportEaaSToExcel;
window.exportEaaSToExcelWithFormulas = exportEaaSToExcelWithFormulas;
window.exportEaaSRdnToExcel = exportEaaSRdnToExcel;
window.exportRevenueToExcel = exportRevenueToExcel;

// ============================================================================
// === BANKABILITY METRICS MODULE ===
// ============================================================================

// Global state for Bankability
let bankabilityData = null;
let currentBankabilityScenario = 'P90';
let assumptionsCollapsed = false;

/**
 * Initialize Bankability section with data from EaaS yearly analysis
 */
function initializeBankability() {
  console.log('🏦 Initializing Bankability metrics...');

  // Check if Bankability module is loaded
  if (typeof Bankability === 'undefined') {
    console.warn('⚠️ Bankability module not loaded');
    return;
  }

  // Show section
  const section = document.getElementById('bankabilitySection');
  if (section) {
    section.style.display = 'block';
  }

  // Get financing assumptions from inputs
  const financingParams = getBankabilityFinancingParams();

  // Check if we have EaaS yearly data
  if (!eaasYearlyData || eaasYearlyData.length === 0) {
    console.warn('⚠️ No EaaS yearly data for Bankability');
    renderBankabilityNoData();
    return;
  }

  // Build scenario data (P50, P90, P97)
  // For now, P90/P97 use scaled revenue (conservative energy yield)
  const scenarioData = buildScenarioData(eaasYearlyData);

  // Generate debt schedule
  const debtSchedule = Bankability.generateDebtSchedule(financingParams);

  // Determine option type
  const optionType = 'EaaS';  // Currently EaaS module
  const hasAssignedDebt = financingParams.debtAmount > 0;

  // Calculate full bankability metrics
  bankabilityData = Bankability.calculateMultiScenarioBankability(
    scenarioData,
    debtSchedule,
    financingParams,
    {
      covenant: financingParams.covenantMinDSCR,
      targetDSCR: 1.25,
      optionType,
      hasAssignedDebt
    }
  );

  console.log('📊 Bankability data calculated:', bankabilityData);

  // Render UI
  renderBankabilityUI();
}

/**
 * Get financing parameters from input fields
 */
function getBankabilityFinancingParams() {
  return {
    debtAmount: parseFloat(document.getElementById('bankDebtAmount')?.value) || 0,
    tenorYears: parseInt(document.getElementById('bankTenor')?.value) || 15,
    interestRate: (parseFloat(document.getElementById('bankInterestRate')?.value) || 6.5) / 100,
    repaymentType: document.getElementById('bankRepaymentType')?.value || 'annuity',
    graceYears: parseInt(document.getElementById('bankGraceYears')?.value) || 0,
    covenantMinDSCR: parseFloat(document.getElementById('bankCovenant')?.value) || 1.20,
    feesRate: 0.005  // 0.5% p.a. default
  };
}

/**
 * Build scenario data from EaaS yearly data
 * P50 = base, P90 = 93% revenue, P97 = 88% revenue (conservative yield)
 */
function buildScenarioData(yearlyData) {
  const P50_FACTOR = 1.0;
  const P90_FACTOR = 0.93;  // 7% lower yield
  const P97_FACTOR = 0.88;  // 12% lower yield

  const scenarios = {
    P50: [],
    P90: [],
    P97: []
  };

  yearlyData.forEach(year => {
    const baseRevenue = year.savings || year.oszczednosc || 0;
    const opex = year.oAndM || year.koszt || 0;

    // P50 (base)
    scenarios.P50.push({
      year: year.rok || year.year,
      revenue: baseRevenue,
      opex: opex,
      savings: baseRevenue,
      oAndM: opex,
      taxesCash: 0,
      maintCapex: 0,
      deltaWC: 0,
      contractRevenue: baseRevenue
    });

    // P90 (conservative)
    scenarios.P90.push({
      year: year.rok || year.year,
      revenue: baseRevenue * P90_FACTOR,
      opex: opex,
      savings: baseRevenue * P90_FACTOR,
      oAndM: opex,
      taxesCash: 0,
      maintCapex: 0,
      deltaWC: 0,
      contractRevenue: baseRevenue * P90_FACTOR
    });

    // P97 (very conservative)
    scenarios.P97.push({
      year: year.rok || year.year,
      revenue: baseRevenue * P97_FACTOR,
      opex: opex,
      savings: baseRevenue * P97_FACTOR,
      oAndM: opex,
      taxesCash: 0,
      maintCapex: 0,
      deltaWC: 0,
      contractRevenue: baseRevenue * P97_FACTOR
    });
  });

  return scenarios;
}

/**
 * Render Bankability UI
 */
function renderBankabilityUI() {
  if (!bankabilityData) return;

  const scenario = currentBankabilityScenario;
  const scenarioData = bankabilityData.scenarios[scenario];

  if (!scenarioData) {
    console.warn(`⚠️ No data for scenario ${scenario}`);
    return;
  }

  const kpi = scenarioData.kpi;
  const covenant = scenarioData.assumptions.covenant;
  const mode = scenarioData.mode;

  // Update mode indicator
  updateBankabilityModeIndicator(mode, bankabilityData.financing?.debtAmount > 0);

  // Update KPI cards
  updateBankabilityKPIs(kpi, covenant, scenario);

  // Update alerts
  updateBankabilityAlerts(kpi, covenant);

  // Update yearly table
  updateBankabilityTable(scenarioData.cashflow, covenant);

  // Update scenario buttons
  updateScenarioButtons(scenario);
}

/**
 * Update mode indicator badge
 */
function updateBankabilityModeIndicator(mode, hasDebt) {
  const indicator = document.getElementById('bankabilityModeIndicator');
  if (!indicator) return;

  if (mode === 'DSCR' && hasDebt) {
    indicator.innerHTML = '<span class="mode-badge dscr-mode">📊 CAPEX/EaaS + DEBT → DSCR Analysis</span>';
  } else if (mode === 'CCR') {
    indicator.innerHTML = '<span class="mode-badge ccr-mode">📋 EaaS → CCR + Implied Debt Capacity</span>';
  } else {
    indicator.innerHTML = '<span class="mode-badge no-debt-mode">ℹ️ No debt assigned - configure financing above</span>';
  }
}

/**
 * Update KPI cards
 */
function updateBankabilityKPIs(kpi, covenant, scenario) {
  // Min DSCR
  const minDSCREl = document.getElementById('kpiMinDSCRValue');
  const minDSCRStatus = document.getElementById('kpiMinDSCRStatus');
  if (minDSCREl) {
    minDSCREl.textContent = Bankability.formatDSCR(kpi.minDSCR);
    const statusColor = Bankability.getDSCRStatusColor(kpi.minDSCR, covenant);
    if (minDSCRStatus) {
      minDSCRStatus.className = `kpi-status ${statusColor}`;
      minDSCRStatus.textContent = getStatusText(statusColor, covenant);
    }
  }

  // Update label
  const minDSCRLabel = document.querySelector('#kpiMinDSCR .kpi-label');
  if (minDSCRLabel) {
    minDSCRLabel.textContent = `Min DSCR @${scenario}`;
  }

  // Avg DSCR (weighted)
  const avgDSCREl = document.getElementById('kpiAvgDSCRValue');
  if (avgDSCREl) {
    avgDSCREl.textContent = Bankability.formatDSCR(kpi.avgDSCRWeighted);
  }

  // Worst Year
  const worstYearEl = document.getElementById('kpiWorstYearValue');
  if (worstYearEl) {
    worstYearEl.textContent = kpi.worstYear ? `Rok ${kpi.worstYear}` : 'n/a';
  }

  // Headroom
  const headroomEl = document.getElementById('kpiHeadroomValue');
  if (headroomEl) {
    headroomEl.textContent = Bankability.formatHeadroom(kpi.headroom);
    headroomEl.style.color = kpi.headroom !== null && kpi.headroom >= 0 ? '#2e7d32' : '#c62828';
  }
}

/**
 * Get status text for DSCR status
 */
function getStatusText(statusColor, covenant) {
  switch (statusColor) {
    case 'excellent': return `✓ Excellent (>${(covenant * 1.25).toFixed(2)}x)`;
    case 'good': return `✓ Good (>${(covenant * 1.10).toFixed(2)}x)`;
    case 'acceptable': return `✓ At covenant (${covenant.toFixed(2)}x)`;
    case 'warning': return `⚠ Near breach`;
    case 'critical': return `✗ Below covenant`;
    default: return 'n/a';
  }
}

/**
 * Update alerts section
 */
function updateBankabilityAlerts(kpi, covenant) {
  const alertsContainer = document.getElementById('bankabilityAlerts');
  if (!alertsContainer) return;

  alertsContainer.innerHTML = '';

  // Alert for years below covenant
  if (kpi.yearsBelowCovenant && kpi.yearsBelowCovenant.length > 0) {
    const yearsStr = kpi.yearsBelowCovenant.join(', ');
    alertsContainer.innerHTML += `
      <div class="bankability-alert critical">
        <span class="alert-icon">🚨</span>
        <span class="alert-text">
          DSCR poniżej covenant (${covenant.toFixed(2)}x) w latach:
          <span class="alert-years">${yearsStr}</span>
        </span>
      </div>
    `;
  }

  // Info alert if no debt
  if (kpi.minDSCR === null) {
    alertsContainer.innerHTML += `
      <div class="bankability-alert info">
        <span class="alert-icon">ℹ️</span>
        <span class="alert-text">
          Wprowadź parametry finansowania powyżej, aby obliczyć DSCR
        </span>
      </div>
    `;
  }

  // Success alert if all OK
  if (kpi.minDSCR !== null && kpi.yearsBelowCovenant.length === 0) {
    alertsContainer.innerHTML += `
      <div class="bankability-alert info">
        <span class="alert-icon">✅</span>
        <span class="alert-text">
          DSCR spełnia covenant we wszystkich latach analizy
        </span>
      </div>
    `;
  }
}

/**
 * Update yearly DSCR table
 */
function updateBankabilityTable(cashflow, covenant) {
  const tbody = document.getElementById('bankabilityTableBody');
  if (!tbody) return;

  tbody.innerHTML = '';

  const years = Object.keys(cashflow).sort((a, b) => a - b);

  years.forEach(year => {
    const cf = cashflow[year];
    const dscr = cf.dscr;
    const dscrFormatted = Bankability.formatDSCR(dscr);
    const dscrColor = Bankability.getDSCRStatusColor(dscr, covenant);
    const isBelowCovenant = cf.flags?.belowCovenant;

    const statusBadge = dscr === null
      ? '<span class="status-badge na">n/a</span>'
      : isBelowCovenant
        ? '<span class="status-badge breach">BREACH</span>'
        : '<span class="status-badge ok">OK</span>';

    const rowClass = isBelowCovenant ? 'below-covenant' : '';

    tbody.innerHTML += `
      <tr class="${rowClass}">
        <td>${year}</td>
        <td>${formatNumber(cf.revenue)}</td>
        <td>${formatNumber(cf.opex)}</td>
        <td>${formatNumber(cf.cfads)}</td>
        <td>${formatNumber(cf.debtService)}</td>
        <td class="dscr-cell ${dscrColor}">${dscrFormatted}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  });
}

/**
 * Update scenario toggle buttons
 */
function updateScenarioButtons(activeScenario) {
  document.querySelectorAll('.bankability-scenario-toggle .scenario-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.scenario === activeScenario);
  });
}

/**
 * Set bankability scenario (P50/P90/P97)
 */
function setBankabilityScenario(scenario) {
  currentBankabilityScenario = scenario;
  renderBankabilityUI();
}

/**
 * Recalculate bankability when parameters change
 */
function recalculateBankability() {
  console.log('🔄 Recalculating bankability...');
  initializeBankability();
}

/**
 * Toggle assumptions panel
 */
function toggleBankabilityAssumptions() {
  const body = document.getElementById('assumptionsBody');
  const btn = document.querySelector('.toggle-assumptions');

  if (body && btn) {
    assumptionsCollapsed = !assumptionsCollapsed;
    body.classList.toggle('collapsed', assumptionsCollapsed);
    btn.textContent = assumptionsCollapsed ? '▶' : '▼';
  }
}

/**
 * Render "no data" state
 */
function renderBankabilityNoData() {
  const kpis = document.getElementById('bankabilityKPIs');
  if (kpis) {
    document.getElementById('kpiMinDSCRValue').textContent = '-';
    document.getElementById('kpiAvgDSCRValue').textContent = '-';
    document.getElementById('kpiWorstYearValue').textContent = '-';
    document.getElementById('kpiHeadroomValue').textContent = '-';
  }

  const tbody = document.getElementById('bankabilityTableBody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999;">Brak danych - uruchom analizę EaaS</td></tr>';
  }
}

/**
 * Format number for display
 */
function formatNumber(value) {
  if (value === null || value === undefined || isNaN(value)) return '-';
  return new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 0 }).format(value);
}

// Export to window
window.initializeBankability = initializeBankability;
window.setBankabilityScenario = setBankabilityScenario;
window.recalculateBankability = recalculateBankability;
window.toggleBankabilityAssumptions = toggleBankabilityAssumptions;

// ============================================================================
// === EAAS MODULE END ===
// ============================================================================

// ============================================================================
// === HELPER FUNCTIONS (used by main initialization) ===
// ============================================================================

// Populate variant selector (used in performEconomicAnalysis)
function populateVariantSelector() {
  const selector = document.getElementById('variantSelector');
  if (!selector) return;

  selector.innerHTML = '';

  const sortedVariants = Object.keys(variants).sort();
  sortedVariants.forEach(variantName => {
    const option = document.createElement('option');
    option.value = variantName;
    option.textContent = `Wariant ${variantName}`;
    selector.appendChild(option);
  });

  // Set current variant
  if (sortedVariants.includes(currentVariant)) {
    selector.value = currentVariant;
  } else if (sortedVariants.length > 0) {
    currentVariant = sortedVariants[0];
    selector.value = currentVariant;
  }

  console.log('✅ Populated variant selector with:', sortedVariants.join(', '));
}

// Show "no data" message
function showNoData() {
  const noDataDiv = document.getElementById('noData');
  const contentDiv = document.getElementById('economicsContent');

  if (noDataDiv && contentDiv) {
    noDataDiv.style.display = 'block';
    contentDiv.style.display = 'none';
  }
}

// Hide "no data" message
function hideNoData() {
  const noDataDiv = document.getElementById('noData');
  const contentDiv = document.getElementById('economicsContent');

  if (noDataDiv && contentDiv) {
    noDataDiv.style.display = 'none';
    contentDiv.style.display = 'block';
  }
}

// Clear economics data
function clearEconomicsData() {
  analysisResults = null;
  variants = {};
  consumptionData = null;
  pvConfig = null;

  localStorage.removeItem('pv_analysis_results');
  localStorage.removeItem('pv_consumption_data');
  localStorage.removeItem('pv_config');

  showNoData();
  console.log('✅ Economics data cleared');
}

// ============================================================================
// ESG Dashboard - Environmental metrics display
// ============================================================================

/**
 * Update ESG Dashboard with calculated environmental metrics
 * Uses calculateESGMetrics from Settings module (exposed via window)
 */
function updateESGDashboard() {
  console.log('🌱 Updating ESG Dashboard...');

  const variant = variants[currentVariant];
  if (!variant) {
    console.warn('⚠️ No variant data for ESG calculation');
    return;
  }

  // Read from centralizedMetrics (SSoT) — already computed with correct scenarioFactor and preciseAnnualSavings
  const cm = centralizedMetrics[currentVariant]?.common;
  if (!cm) {
    console.warn('⚠️ centralizedMetrics not yet available for ESG calculation');
    return;
  }

  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = kwhToMwh(annualConsumptionKwh);
  const gridConsumptionBeforeMwh = annualConsumptionMwh;
  const gridConsumptionAfterMwh = Math.max(0, annualConsumptionMwh - cm.selfConsumedMwh);

  // Build parameters for ESG calculation
  const esgParams = {
    capacityKwp: cm.capacityKwp,
    annualProductionMwh: cm.productionMwh,
    selfConsumedMwh: cm.selfConsumedMwh,
    gridConsumptionBeforeMwh: gridConsumptionBeforeMwh,
    gridConsumptionAfterMwh: gridConsumptionAfterMwh,
    projectLifetimeYears: cm.analysisPeriod,
    degradationRate: window.economicsSettings?.degradationRate
  };

  console.log('📊 ESG calculation params:', esgParams);

  // Try to call calculateESGMetrics from Settings module
  let esgMetrics = null;
  if (typeof window.calculateESGMetrics === 'function') {
    esgMetrics = window.calculateESGMetrics(esgParams);
    console.log('✅ ESG metrics calculated:', esgMetrics);
  } else {
    // Fallback: calculate locally with defaults
    console.warn('⚠️ calculateESGMetrics not available, using local fallback');
    esgMetrics = calculateESGMetricsLocal(esgParams);
  }

  // Update ESG Dashboard UI
  updateESGUI(esgMetrics);
}

/**
 * Local fallback ESG calculation if Settings module not available
 */
function calculateESGMetricsLocal(params) {
  const {
    capacityKwp = 0,
    annualProductionMwh = 0,
    selfConsumedMwh = 0,
    gridConsumptionBeforeMwh = 0,
    gridConsumptionAfterMwh = 0,
    projectLifetimeYears = 25,
    degradationRate = window.economicsSettings?.degradationRate || 0.005
  } = params;

  // Default emission factors (Poland)
  const efGrid = 0.658; // kgCO2e/kWh (KOBiZE 2023)
  const embodiedCarbonPerKwp = 700; // kgCO2e/kWp (c-Si)

  // Annual CO2 reduction
  const co2BaselineYear = gridConsumptionBeforeMwh * efGrid / 1000; // tonnes
  const co2AfterYear = gridConsumptionAfterMwh * efGrid / 1000; // tonnes
  const co2ReductionYear = co2BaselineYear - co2AfterYear;

  // Lifetime CO2 reduction
  let co2ReductionLifetime = 0;
  for (let year = 1; year <= projectLifetimeYears; year++) {
    const degradationFactor = Math.pow(1 - degradationRate, year - 1);
    co2ReductionLifetime += co2ReductionYear * degradationFactor;
  }

  // Share of RES
  const totalConsumptionAfter = selfConsumedMwh + gridConsumptionAfterMwh;
  const shareRES = totalConsumptionAfter > 0
    ? (selfConsumedMwh / totalConsumptionAfter) * 100
    : 0;

  // Embodied carbon and payback
  const co2Embodied = (capacityKwp * embodiedCarbonPerKwp) / 1000; // tonnes
  const carbonPaybackYears = co2ReductionYear > 0
    ? co2Embodied / co2ReductionYear
    : Infinity;

  // Net CO2 lifetime
  const co2NetLifetime = co2ReductionLifetime - co2Embodied;

  return {
    co2BaselineYear,
    co2AfterYear,
    co2ReductionYear,
    co2ReductionLifetime,
    co2Embodied,
    co2NetLifetime,
    shareRES,
    carbonPaybackYears,
    efGrid,
    efGridSource: 'KOBiZE',
    embodiedCarbonPerKwp,
    embodiedCarbonSource: 'IEA PVPS Task 12 / NREL',
    pvTechnology: 'crystalline',
    projectLifetimeYears,
    taxonomyAligned: true,
    taxonomyActivityCode: '4.1'
  };
}

/**
 * Update ESG Dashboard UI elements
 */
function updateESGUI(metrics) {
  if (!metrics) return;

  // KPI Cards - European format
  const co2ReductionYearEl = document.getElementById('esgCo2ReductionYear');
  if (co2ReductionYearEl) {
    co2ReductionYearEl.textContent = formatNumberEU(metrics.co2ReductionYear, 1);
  }

  const co2ReductionLifetimeEl = document.getElementById('esgCo2ReductionLifetime');
  if (co2ReductionLifetimeEl) {
    co2ReductionLifetimeEl.textContent = formatNumberEU(metrics.co2ReductionLifetime, 0);
  }

  const shareResEl = document.getElementById('esgShareRes');
  if (shareResEl) {
    shareResEl.textContent = formatNumberEU(metrics.shareRES, 1);
  }

  const carbonPaybackEl = document.getElementById('esgCarbonPayback');
  if (carbonPaybackEl) {
    if (metrics.carbonPaybackYears === Infinity || metrics.carbonPaybackYears > 100) {
      carbonPaybackEl.textContent = '–';
    } else {
      carbonPaybackEl.textContent = formatNumberEU(metrics.carbonPaybackYears, 1);
    }
  }

  // Emissions Before/After - European format
  const co2BeforeEl = document.getElementById('esgCo2Before');
  if (co2BeforeEl) {
    co2BeforeEl.textContent = formatNumberEU(metrics.co2BaselineYear, 1);
  }

  const co2AfterEl = document.getElementById('esgCo2After');
  if (co2AfterEl) {
    co2AfterEl.textContent = formatNumberEU(metrics.co2AfterYear, 1);
  }

  const co2ReductionPctEl = document.getElementById('esgCo2ReductionPct');
  if (co2ReductionPctEl && metrics.co2BaselineYear > 0) {
    const reductionPct = (metrics.co2ReductionYear / metrics.co2BaselineYear) * 100;
    co2ReductionPctEl.textContent = formatNumberEU(reductionPct, 1);
  }

  // Embodied Carbon / LCA - European format
  const embodiedCarbonEl = document.getElementById('esgEmbodiedCarbon');
  if (embodiedCarbonEl) {
    embodiedCarbonEl.textContent = formatNumberEU(metrics.co2Embodied, 1);
  }

  const netCo2El = document.getElementById('esgNetCo2');
  if (netCo2El) {
    netCo2El.textContent = formatNumberEU(metrics.co2NetLifetime, 0);
    netCo2El.style.color = metrics.co2NetLifetime >= 0 ? '#1565c0' : '#d32f2f';
  }

  const pvTechnologyEl = document.getElementById('esgPvTechnology');
  if (pvTechnologyEl) {
    const techNames = {
      'crystalline': 'c-Si',
      'CIS': 'CIS/CIGS',
      'CdTe': 'CdTe'
    };
    pvTechnologyEl.textContent = techNames[metrics.pvTechnology] || metrics.pvTechnology;
  }

  const embodiedPerKwpEl = document.getElementById('esgEmbodiedPerKwp');
  if (embodiedPerKwpEl) {
    embodiedPerKwpEl.textContent = metrics.embodiedCarbonPerKwp;
  }

  // EU Taxonomy Badge
  const taxonomyBadgeEl = document.getElementById('esgTaxonomyBadge');
  if (taxonomyBadgeEl) {
    if (metrics.taxonomyAligned) {
      taxonomyBadgeEl.style.background = '#4caf50';
      taxonomyBadgeEl.innerHTML = `✓ EU Taxonomy ${metrics.taxonomyActivityCode || '4.1'}`;
    } else {
      taxonomyBadgeEl.style.background = '#9e9e9e';
      taxonomyBadgeEl.innerHTML = '○ EU Taxonomy';
    }
  }

  // EF Grid info - European format
  const efGridEl = document.getElementById('esgEfGrid');
  if (efGridEl) {
    efGridEl.textContent = formatNumberEU(metrics.efGrid, 3);
  }

  const efSourceEl = document.getElementById('esgEfSource');
  if (efSourceEl) {
    efSourceEl.textContent = metrics.efGridSource || 'KOBiZE';
  }

  // Embodied carbon source
  const embodiedSourceEl = document.getElementById('esgEmbodiedSource');
  if (embodiedSourceEl) {
    embodiedSourceEl.textContent = metrics.embodiedCarbonSource || 'IEA PVPS Task 12 / NREL';
  }

  console.log('✅ ESG Dashboard updated');

  // Try to fetch real-time data if API key is available
  tryFetchElectricityMapsData();
}

/**
 * Try to fetch Electricity Maps data if API key is available in settings
 */
async function tryFetchElectricityMapsData() {
  // Check if API key is available in systemSettings
  const apiKey = systemSettings?.electricitymapsApiKey;
  const zone = systemSettings?.electricitymapsZone || 'PL';

  if (!apiKey) {
    console.log('📡 Electricity Maps API key not configured - skipping real-time data');
    return;
  }

  console.log('📡 Fetching Electricity Maps data for zone:', zone);
  await refreshElectricityMapsInEconomics();
}

/**
 * Refresh Electricity Maps data in Economics module
 */
async function refreshElectricityMapsInEconomics() {
  const apiKey = systemSettings?.electricitymapsApiKey;
  const zone = systemSettings?.electricitymapsZone || 'PL';

  if (!apiKey) {
    console.warn('⚠️ Electricity Maps API key not configured');
    return;
  }

  try {
    // Fetch all three endpoints in parallel
    const baseUrl = 'https://api.electricitymaps.com';
    const headers = {
      'auth-token': apiKey,
      'Accept': 'application/json'
    };

    const [carbonRes, renewableRes, fossilRes] = await Promise.all([
      fetch(`${baseUrl}/v3/carbon-intensity/latest?zone=${zone}`, { headers }).then(r => r.json()),
      fetch(`${baseUrl}/v3/renewable-percentage-level/latest?zone=${zone}`, { headers }).then(r => r.json()),
      fetch(`${baseUrl}/v3/carbon-intensity-fossil-only/latest?zone=${zone}`, { headers }).then(r => r.json())
    ]);

    // Update UI
    updateElectricityMapsUIInEconomics({
      carbonIntensity: carbonRes?.carbonIntensity,
      renewablePercentage: renewableRes?.renewablePercentage,
      fossilCarbonIntensity: fossilRes?.carbonIntensity,
      zone: zone,
      timestamp: carbonRes?.datetime || new Date().toISOString(),
      isEstimated: carbonRes?.isEstimated
    });

    // Show the real-time section
    const section = document.getElementById('esgRealTimeSection');
    if (section) section.style.display = 'block';

    console.log('✅ Electricity Maps data updated in Economics');

  } catch (error) {
    console.error('❌ Error fetching Electricity Maps data:', error);
  }
}

/**
 * Update Electricity Maps UI elements in Economics module - European format
 */
function updateElectricityMapsUIInEconomics(data) {
  // Carbon Intensity
  const ciEl = document.getElementById('esgRealTimeCarbonIntensity');
  if (ciEl && data.carbonIntensity !== null && data.carbonIntensity !== undefined) {
    ciEl.textContent = formatNumberEU(data.carbonIntensity, 0);
    // Color coding
    if (data.carbonIntensity < 200) {
      ciEl.style.color = '#388e3c';
    } else if (data.carbonIntensity < 400) {
      ciEl.style.color = '#ffa000';
    } else {
      ciEl.style.color = '#d32f2f';
    }
  }

  // Renewable Percentage
  const renewEl = document.getElementById('esgRealTimeRenewable');
  if (renewEl && data.renewablePercentage !== null && data.renewablePercentage !== undefined) {
    renewEl.textContent = formatNumberEU(data.renewablePercentage, 1);
    // Color coding
    if (data.renewablePercentage > 50) {
      renewEl.style.color = '#388e3c';
    } else if (data.renewablePercentage > 25) {
      renewEl.style.color = '#ffa000';
    } else {
      renewEl.style.color = '#d32f2f';
    }
  }

  // Fossil Fuels CI
  const fossilEl = document.getElementById('esgRealTimeFossilCI');
  if (fossilEl && data.fossilCarbonIntensity !== null && data.fossilCarbonIntensity !== undefined) {
    fossilEl.textContent = formatNumberEU(data.fossilCarbonIntensity, 0);
  }

  // Timestamp
  const tsEl = document.getElementById('esgRealTimeTimestamp');
  if (tsEl && data.timestamp) {
    const ts = new Date(data.timestamp);
    let label = ts.toLocaleString('pl-PL');
    if (data.isEstimated) label += ' (szacunek)';
    tsEl.textContent = label;
  }

  // Zone
  const zoneEl = document.getElementById('esgRealTimeZone');
  if (zoneEl) {
    zoneEl.textContent = `Zone: ${data.zone}`;
  }
}

// Note: Main initialization is at line ~1443 (DOMContentLoaded)
// This file uses single unified event handling defined earlier

// ============================================
// BESS ECONOMICS SECTION
// ============================================

/**
 * Update BESS Economics section with degradation table
 * Shows BESS CAPEX, OPEX, replacement schedule, and energy over time
 */
function updateBessEconomicsSection() {
  const variant = variants[currentVariant];
  const settings = systemSettings;

  // Check if BESS is enabled
  const hasBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  const bessSection = document.getElementById('bessEconomicsSection');

  if (!bessSection) {
    console.log('🔋 BESS Economics section not found in DOM');
    return;
  }

  if (!hasBess) {
    bessSection.style.display = 'none';
    console.log('🔋 BESS disabled - hiding economics section');
    return;
  }

  bessSection.style.display = 'block';
  console.log('🔋 Updating BESS Economics section...');

  // Get BESS parameters
  const bessPowerKw = variant.bess_power_kw;
  const bessEnergyKwh = variant.bess_energy_kwh;
  const bessDischargedKwh = variant.bess_discharged_kwh || variant.bess_self_consumed_from_bess_kwh || 0;

  // Get economic parameters from settings
  const bessCapexPerKwh = settings?.bessCapexPerKwh || 1500;
  const bessCapexPerKw = settings?.bessCapexPerKw || 300;
  const bessOpexPct = settings?.bessOpexPctPerYear || 1.5;
  const bessLifetime = settings?.bessLifetimeYears;
  const bessDegradationYear1 = settings?.bessDegradationYear1 || 3.0;
  const bessDegradationPerYear = settings?.bessDegradationPctPerYear || 2.0;
  const analysisPeriod = parseInt(document.getElementById('analysisPeriod')?.value) || 25;

  // Calculate BESS CAPEX
  const bessCapexEnergy = bessEnergyKwh * bessCapexPerKwh;
  const bessCapexPower = bessPowerKw * bessCapexPerKw;
  const bessCapexTotal = bessCapexEnergy + bessCapexPower;

  // Calculate BESS OPEX
  const bessOpexAnnual = bessCapexTotal * (bessOpexPct / 100);

  // Calculate duration
  const duration = bessPowerKw > 0 ? bessEnergyKwh / bessPowerKw : 0;

  // Update header cards
  document.getElementById('bessEconSizingCard').textContent = `${bessPowerKw.toFixed(0)} kW / ${bessEnergyKwh.toFixed(0)} kWh`;
  document.getElementById('bessEconDurationCard').textContent = `Duration: ${duration.toFixed(1)}h`;

  // Update KPI cards
  document.getElementById('bessEconCapex').textContent = formatNumberEU(plnToTysPln(bessCapexTotal), 0);
  document.getElementById('bessEconCapexDetail').textContent = `${formatNumberEU(bessCapexPerKwh, 0)} PLN/kWh + ${formatNumberEU(bessCapexPerKw, 0)} PLN/kW`;

  document.getElementById('bessEconOpex').textContent = formatNumberEU(plnToTysPln(bessOpexAnnual), 1);
  document.getElementById('bessEconOpexPct').textContent = `${formatNumberEU(bessOpexPct, 1)}% CAPEX/rok`;

  // Battery replacement
  const replacementYear = Math.min(bessLifetime, analysisPeriod);
  const needsReplacement = analysisPeriod > bessLifetime;
  document.getElementById('bessEconReplacement').textContent = needsReplacement ? replacementYear.toString() : 'N/A';
  document.getElementById('bessEconReplacementCost').textContent = needsReplacement
    ? `Koszt: ${formatNumberEU(plnToTysPln(bessCapexTotal * 0.7), 0)} tys. PLN`
    : 'Brak wymiany w okresie';

  // Update degradation parameters info
  document.getElementById('bessEconDegradationParams').textContent =
    `Rok 1: ${formatNumberEU(bessDegradationYear1, 1)}% | Lata 2+: ${formatNumberEU(bessDegradationPerYear, 1)}%/rok | Żywotność: ${bessLifetime} lat`;

  // Generate degradation table
  generateBessDegradationTable(
    bessEnergyKwh,
    bessDischargedKwh,
    bessDegradationYear1,
    bessDegradationPerYear,
    bessLifetime,
    analysisPeriod
  );

  console.log('🔋 BESS Economics section updated successfully');
}

/**
 * Generate BESS degradation table showing energy over years
 */
function generateBessDegradationTable(
  nominalCapacityKwh,
  year1DischargeKwh,
  degradationYear1Pct,
  degradationPerYearPct,
  lifetimeYears,
  analysisPeriod
) {
  const tbody = document.getElementById('bessDegradationTableBody');
  if (!tbody) return;

  let html = '';
  let cumulativeEnergyMWh = 0;
  let currentCapacity = nominalCapacityKwh;
  let batteryNumber = 1;

  // Initial energy factor (based on first year discharge)
  // year1DischargeKwh is the energy delivered in year 1 at 100% capacity
  const baseEnergyFactor = year1DischargeKwh / nominalCapacityKwh; // energy per kWh of capacity

  for (let year = 1; year <= analysisPeriod; year++) {
    // Calculate degradation
    let degradationPct;
    let yearInBatteryLife = ((year - 1) % lifetimeYears) + 1;

    if (yearInBatteryLife === 1) {
      // First year of battery life - higher degradation
      degradationPct = degradationYear1Pct;
      if (year > 1) {
        // Battery replacement happened
        batteryNumber++;
        currentCapacity = nominalCapacityKwh; // Reset to nominal capacity
      }
    } else {
      // Subsequent years - lower degradation
      degradationPct = degradationPerYearPct;
    }

    // Apply degradation to get effective capacity
    const capacityBeforeDegradation = currentCapacity;
    currentCapacity = currentCapacity * (1 - degradationPct / 100);
    const effectiveCapacity = currentCapacity;

    // Calculate energy delivered this year (proportional to effective capacity)
    const energyMWh = kwhToMwh(effectiveCapacity * baseEnergyFactor);
    cumulativeEnergyMWh += energyMWh;

    // EOL check (80% of nominal)
    const eolPct = (effectiveCapacity / nominalCapacityKwh) * 100;
    const isNearEOL = eolPct < 85;
    const isEOL = eolPct < 80;

    // Status
    let status, statusColor;
    if (yearInBatteryLife === lifetimeYears || isEOL) {
      status = `🔄 Wymiana (Bat. ${batteryNumber})`;
      statusColor = '#e74c3c';
    } else if (isNearEOL) {
      status = `⚠️ Blisko EOL (${eolPct.toFixed(0)}%)`;
      statusColor = '#ff9800';
    } else if (yearInBatteryLife === 1 && year > 1) {
      status = `🆕 Nowa bateria (#${batteryNumber})`;
      statusColor = '#27ae60';
    } else {
      status = `✅ OK (${eolPct.toFixed(0)}%)`;
      statusColor = '#27ae60';
    }

    html += `
      <tr style="${yearInBatteryLife === lifetimeYears ? 'background:#fff3e0;' : ''}">
        <td style="font-weight:600;">${year}</td>
        <td>${formatNumberEU(nominalCapacityKwh, 0)}</td>
        <td style="color:${degradationPct > 2.5 ? '#e74c3c' : '#888'}">
          -${formatNumberEU(degradationPct, 1)}%
          ${yearInBatteryLife === 1 ? '<span style="font-size:10px;color:#9c27b0">(rok 1)</span>' : ''}
        </td>
        <td style="font-weight:500;">${formatNumberEU(effectiveCapacity, 0)}</td>
        <td>${formatNumberEU(energyMWh, 2)}</td>
        <td style="font-weight:600;">${formatNumberEU(cumulativeEnergyMWh, 1)}</td>
        <td style="color:${statusColor};font-size:12px;">${status}</td>
      </tr>
    `;
  }

  tbody.innerHTML = html;

  // Update total energy display
  document.getElementById('bessEconTotalEnergy').textContent = formatNumberEU(cumulativeEnergyMWh, 0);
  document.getElementById('bessEconTotalEnergyPeriod').textContent = `przez ${analysisPeriod} lat`;
}

// ============================================
// BESS SAVINGS BREAKDOWN (SSoT REFACTORED)
// ============================================
// The UI for selecting a BESS data source has been removed. BESS data now comes
// exclusively from the main analysis results (pv-calculation).

/**
 * Display BESS Savings Breakdown section (v2 payload)
 * Shows detailed breakdown of where savings come from.
 * SSoT-Refactored: Now reads data directly from the variant object.
 */
function displayBessSavingsBreakdown() {
  const section = document.getElementById('bessSavingsBreakdownSection');
  if (!section) return;

  const variant = variants[currentVariant];
  // Ensure savings_breakdown exists (generate locally if needed for pv-calculation source)
  ensureSavingsBreakdown(variant);
  // The savings_breakdown is expected to be on the variant object, populated by pv-calculation or generated locally
  const hasSavingsBreakdown = variant?.savings_breakdown;

  if (!hasSavingsBreakdown) {
    section.style.display = 'none';
    console.log('📊 Savings breakdown section HIDDEN (no savings_breakdown in variant).');
    return;
  }

  // Show section
  section.style.display = 'block';

  const sb = variant.savings_breakdown;
  const dm = variant.dispatch_metadata || {};
  const ps = variant.prices_summary || {};

  // Fallback to systemSettings for mode/topology/price if not in variant
  const settings = systemSettings || {};
  const fallbackMode = settings.bessDispatchMode || settings.bessPeakShavingEnabled ? 'stacked' : 'pv_surplus';
  const fallbackTopology = settings.bessTopology || (variant.bess_power_kw ? 'pv_load' : 'pv_only');
  const fallbackImportPrice = window.economicsSettings?.totalEnergyPrice || settings.totalEnergyPrice || settings.energyPrice;

  // Format helper
  const fmt = (val) => {
    if (val === null || val === undefined || val === 0) return '-';
    return val.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  };

  // Update values with tooltips for clarity
  const sbEnergyEl = document.getElementById('sbEnergy');
  sbEnergyEl.textContent = fmt(sb.energy_savings_pln);
  sbEnergyEl.title = 'Oszczędność z autokonsumpcji PV (przy cenie flat)';

  const sbDemandEl = document.getElementById('sbDemandCharge');
  sbDemandEl.textContent = fmt(sb.demand_charge_savings_pln);
  sbDemandEl.title = 'Oszczędność z redukcji opłaty mocowej (peak shaving)';

  const sbCapacityEl = document.getElementById('sbCapacityFee');
  sbCapacityEl.textContent = fmt(sb.capacity_fee_savings_pln);
  sbCapacityEl.title = 'Oszczędność z opłaty mocowej (SOM/capacity fee)';

  const sbArbitrageEl = document.getElementById('sbArbitrage');
  sbArbitrageEl.textContent = fmt(sb.arbitrage_savings_pln);
  sbArbitrageEl.title = 'Premia ToU: DODATKOWA oszczędność z różnicy cen dzień/noc (ponad flat rate)';

  // Degradation is negative (cost)
  const degEl = document.getElementById('sbDegradation');
  if (sb.degradation_cost_pln > 0) {
    degEl.textContent = '-' + fmt(sb.degradation_cost_pln);
    degEl.style.color = '#c62828';
  } else {
    degEl.textContent = '-';
    degEl.style.color = '#666';
  }
  degEl.title = 'Koszt degradacji baterii z tytułu przepustowości (throughput × degradation_cost_pln_kwh)';

  const sbNetEl = document.getElementById('sbNet');
  sbNetEl.textContent = fmt(sb.net_savings_pln);
  sbNetEl.title = 'Oszczędność NETTO = energia + demand + capacity + arbitraż - degradacja (SSoT)';

  // Update source badge to reflect actual source
  const sourceEl = document.getElementById('savingsBreakdownSource');
  if (sb.source === 'local-estimate') {
    sourceEl.textContent = '⚡ Szacunkowe';
    sourceEl.style.background = '#fff3e0';
    sourceEl.style.color = '#e65100';
    sourceEl.title = 'Oszczędności oszacowane lokalnie na podstawie parametrów BESS';
  } else {
    sourceEl.textContent = '✓ pv-calculation';
    sourceEl.style.background = '#c8e6c9';
    sourceEl.style.color = '#1b5e20';
    sourceEl.title = 'Oszczędności obliczone przez silnik pv-calculation';
  }

  // Dispatch metadata
  const modeLabels = {
    'pv_surplus': 'PV Surplus',
    'peak_shaving': 'Peak Shaving',
    'stacked': 'Stacked (PV+Peak)',
    'arbitrage': 'Arbitraż',
    'load_only': 'BESS Only'
  };
  const topoLabels = {
    'pv_load': 'PV + BESS + Load',
    'pv_bess': 'PV + BESS + Load',
    'load_only': 'BESS + Load (bez PV)',
    'pv_only': 'Tylko PV (bez BESS)'
  };

  // Use fallback values if dispatch_metadata is empty
  const displayMode = dm.dispatch_mode || fallbackMode;
  const displayTopology = dm.topology || fallbackTopology;

  // Get tariff info - ToU tariffs have variable prices, so don't show single "import price"
  const tariffId = ps.tariff_id || settings.bessOsdTariffGroup || settings.tariffGroup || null;
  let displayTariff = '-';
  if (tariffId) {
    // Show tariff name for ToU (prices vary by hour/day)
    displayTariff = `${tariffId} (ToU)`;
  } else if (ps.import_price_pln_mwh) {
    // Flat pricing - show the price
    displayTariff = `Flat ${ps.import_price_pln_mwh} PLN/MWh`;
  }

  document.getElementById('sbDispatchMode').textContent = modeLabels[displayMode] || displayMode || '-';
  document.getElementById('sbTopology').textContent = topoLabels[displayTopology] || displayTopology || '-';
  document.getElementById('sbTariff').textContent = displayTariff;

  console.log('📊 Savings breakdown displayed from SSoT:', {
    source: 'pv-calculation',
    net_savings: sb.net_savings_pln
  });
}

// ============================================
// SKAN WARIANTÓW - Wykres i tabela analizy mocy
// ============================================

/**
 * Generate Variant Scan section (chart + table)
 * Shows autoconsumption vs coverage for different PV capacities
 * Uses FULL scenarios data from analysisResults (not just key_variants)
 */
function generateVariantScanSection() {
  console.log('📊 Generating Variant Scan section...');

  const noDataEl = document.getElementById('variantScanNoData');
  const contentEl = document.getElementById('variantScanContent');

  // Check if we have scenarios data (full range analysis)
  const scenarios = analysisResults?.scenarios || [];
  const hasScenarios = scenarios.length > 0;
  const hasVariants = variants && Object.keys(variants).length > 0;

  if (!hasScenarios && !hasVariants) {
    console.log('⚠️ No scenarios or variants data for scan section - showing placeholder');
    if (noDataEl) noDataEl.style.display = 'block';
    if (contentEl) contentEl.style.display = 'none';
    return;
  }

  const params = getEconomicParameters();
  const factor = window.currentScenarioFactor || 1.0;

  // Prepare data - prefer scenarios (full range) over key_variants
  let scanData;
  if (hasScenarios) {
    console.log('📊 Using FULL scenarios data:', scenarios.length, 'points');
    scanData = prepareVariantScanDataFromScenarios(scenarios, params, factor);
  } else {
    console.log('📊 Fallback to key_variants:', Object.keys(variants).length, 'points');
    scanData = prepareVariantScanDataFromVariants(params, factor);
  }

  if (scanData.length === 0) {
    console.log('⚠️ No scan data generated - showing placeholder');
    if (noDataEl) noDataEl.style.display = 'block';
    if (contentEl) contentEl.style.display = 'none';
    return;
  }

  // Hide placeholder, show content
  if (noDataEl) noDataEl.style.display = 'none';
  if (contentEl) contentEl.style.display = 'grid';

  // Generate chart
  generateVariantScanChart(scanData);

  // Generate table - same density as chart (125 points) or ALL data if less
  // Table scrolls fast and reads quickly - no need to sample
  generateVariantScanTable(scanData);

  // Update observation text
  updateVariantScanObservation(scanData);

  // Generate LCOE Analysis Chart
  generateLcoeAnalysisChart(scanData);

  console.log('✅ Variant Scan section generated with', scanData.length, 'rows');
}

/**
 * Update break-even mode and regenerate table
 */
function updateBreakevenMode(mode) {
  breakevenMode = mode;
  console.log('📊 Break-even mode changed to:', mode);

  // Regenerate the variant scan section with new mode
  generateVariantScanSection();
}

// Expose globally
window.updateBreakevenMode = updateBreakevenMode;

/**
 * Sample scan data with UNIFORM distribution
 * Simple strategy: evenly spaced points across entire range
 */
function sampleScanData(scanData, maxRows) {
  if (scanData.length <= maxRows) return scanData;

  // Find key indices for special highlighting
  let maxNpvIdx = 0;
  let minPaybackIdx = 0;
  let currentIdx = -1;
  let maxNpv = -Infinity;
  let minPayback = Infinity;

  scanData.forEach((d, idx) => {
    if (d.npv > maxNpv) { maxNpv = d.npv; maxNpvIdx = idx; }
    if (d.payback < minPayback && d.payback < 99) { minPayback = d.payback; minPaybackIdx = idx; }
    if (d.isCurrent) currentIdx = idx;
  });

  const modeName = (breakevenMode === 'payback') ? 'Min Payback' : 'Max NPV';

  // SIMPLE UNIFORM SAMPLING: evenly distributed across entire range
  const step = (scanData.length - 1) / (maxRows - 1);
  const indices = new Set();

  for (let i = 0; i < maxRows; i++) {
    const idx = Math.round(i * step);
    if (idx < scanData.length) {
      indices.add(idx);
    }
  }

  // Always include critical points
  indices.add(0);                          // First
  indices.add(scanData.length - 1);        // Last
  indices.add(maxNpvIdx);                  // Max NPV
  indices.add(minPaybackIdx);              // Min Payback
  if (currentIdx >= 0) indices.add(currentIdx); // Current variant

  // Convert to sorted array
  const sortedIndices = Array.from(indices).sort((a, b) => a - b);
  const result = sortedIndices.map(idx => scanData[idx]).filter(Boolean);

  console.log(`📊 Table sampling [${modeName}]: ${scanData.length} → ${result.length} rows, step=${step.toFixed(1)}`);

  return result;
}

/**
 * Prepare variant scan data from FULL scenarios array
 */
function prepareVariantScanDataFromScenarios(scenarios, params, factor) {
  const scanData = [];

  // Sort scenarios by capacity
  const sortedScenarios = [...scenarios].sort((a, b) => (a.capacity || 0) - (b.capacity || 0));

  // Get current variant capacity for highlighting
  const currentVariantData = variants?.[currentVariant];
  const currentCapacity = currentVariantData?.capacity || 0;

  for (const s of sortedScenarios) {
    if (!s || !s.capacity) continue;

    const capacityKwp = s.capacity;
    const productionKwh = (s.production || 0) * factor;
    const selfConsumedKwh = (s.self_consumed || 0) * factor;
    const exportedKwh = (s.exported || 0) * factor;
    const autoConsumptionPct = s.auto_consumption_pct || 0;
    const coveragePct = s.coverage_pct || 0;

    // Calculate economics for this scenario
    const economics = calculateVariantEconomics(s, params, factor);

    scanData.push({
      key: `${capacityKwp}kWp`,
      capacity: capacityKwp,
      capacityMWp: kwhToMwh(capacityKwp),
      productionMWh: kwhToMwh(productionKwh),
      selfConsumedMWh: kwhToMwh(selfConsumedKwh),
      exportedMWh: kwhToMwh(exportedKwh),
      autoConsumptionPct: autoConsumptionPct,
      coveragePct: coveragePct,
      npv: economics.npv,
      payback: economics.payback,
      lcoe: economics.lcoe,
      lcoeStd: economics.lcoeStd,
      lcoeEff: economics.lcoeEff,
      lcoeGrid: economics.lcoeGrid,           // NOWE: benchmark sieci
      lcoeOfftaker: economics.lcoeOfftaker,   // NOWE: koszt klienta EaaS
      deltaLevelized: economics.deltaLevelized, // NOWE: oszczędność klienta
      lcoeMargin: economics.lcoeMargin,
      irr: economics.irr,
      isCurrent: Math.abs(capacityKwp - currentCapacity) < 1 // Highlight if matches current
    });
  }

  return scanData;
}

/**
 * Prepare variant scan data from key_variants (fallback)
 */
function prepareVariantScanDataFromVariants(params, factor) {
  const scanData = [];
  const variantKeys = Object.keys(variants).sort((a, b) => {
    const capA = variants[a]?.capacity || 0;
    const capB = variants[b]?.capacity || 0;
    return capA - capB;
  });

  for (const key of variantKeys) {
    const v = variants[key];
    if (!v || !v.capacity) continue;

    const capacityKwp = v.capacity;
    const productionKwh = (v.production || 0) * factor;
    const selfConsumedKwh = (v.self_consumed || 0) * factor;
    const exportedKwh = (v.exported || 0) * factor;
    const autoConsumptionPct = v.auto_consumption_pct || 0;
    const coveragePct = v.coverage_pct || 0;

    const economics = calculateVariantEconomics(v, params, factor);

    scanData.push({
      key: key,
      capacity: capacityKwp,
      capacityMWp: kwhToMwh(capacityKwp),
      productionMWh: kwhToMwh(productionKwh),
      selfConsumedMWh: kwhToMwh(selfConsumedKwh),
      exportedMWh: kwhToMwh(exportedKwh),
      autoConsumptionPct: autoConsumptionPct,
      coveragePct: coveragePct,
      npv: economics.npv,
      payback: economics.payback,
      lcoe: economics.lcoe,
      lcoeStd: economics.lcoeStd,
      lcoeEff: economics.lcoeEff,
      lcoeGrid: economics.lcoeGrid,           // NOWE: benchmark sieci
      lcoeOfftaker: economics.lcoeOfftaker,   // NOWE: koszt klienta EaaS
      deltaLevelized: economics.deltaLevelized, // NOWE: oszczędność klienta
      lcoeMargin: economics.lcoeMargin,
      irr: economics.irr,
      isCurrent: key === currentVariant
    });
  }

  return scanData;
}

// ===== LCOE CALCULATION HELPERS =====
// Zgodne z IEA/NREL metodologią: LCOE = PV(costs) / PV(energy)
// Ref: https://www.nrel.gov/analysis/tech-lcoe-documentation.html

/**
 * Present Value Factor dla roku t
 * PV = 1 / (1 + r)^t
 * @param {number} year - rok (1-indexed, year=1 to pierwszy rok operacyjny)
 * @param {number} rate - stopa dyskontowa (decimal, np. 0.07 dla 7%)
 * @returns {number} - discount factor
 */
const pvFactor = (year, rate) => 1 / Math.pow(1 + rate, year);

/**
 * Konwersja stopy nominalnej na realną (Fisher equation)
 * realRate = (1 + nominalRate) / (1 + inflationRate) - 1
 *
 * Użycie: gdy model ma stałe koszty (useInflation=false),
 * ale użytkownik wpisuje stopę nominalną, przeliczamy na realną
 * aby zachować spójność ekonomiczną.
 *
 * @param {number} nominalRate - stopa nominalna (decimal)
 * @param {number} inflationRate - stopa inflacji (decimal)
 * @returns {number} - stopa realna (decimal)
 */
const nominalToReal = (nominalRate, inflationRate) =>
  (1 + nominalRate) / (1 + inflationRate) - 1;

/**
 * Uniwersalna funkcja do obliczania LCOE
 * LCOE = PV(koszty) / PV(energia)
 *
 * @param {Object} config - konfiguracja
 * @param {number} config.capex - CAPEX w roku 0 [PLN]
 * @param {number} config.opexBase - bazowy OPEX roczny [PLN]
 * @param {number} config.energyBase - bazowa energia roczna [MWh]
 * @param {number} config.years - okres analizy [lat]
 * @param {number} config.discountRate - stopa dyskontowa (decimal)
 * @param {number} config.degradationRate - roczna degradacja energii (decimal)
 * @param {number} config.inflationRate - stopa inflacji (decimal, 0 jeśli model realny)
 * @param {boolean} config.applyInflationToOpex - czy OPEX rośnie z inflacją
 * @returns {number} - LCOE [PLN/MWh]
 */
function computeLCOE(config) {
  const {
    capex = 0,
    opexBase = 0,
    energyBase = 0,
    years = 25,
    discountRate = window.economicsSettings?.discountRate,
    degradationRate = 0,
    inflationRate = 0,
    applyInflationToOpex = false
  } = config;

  if (energyBase <= 0 || years <= 0) return 0;

  let pvCosts = capex; // CAPEX w t=0, bez dyskonta
  let pvEnergy = 0;

  for (let year = 1; year <= years; year++) {
    const df = pvFactor(year, discountRate);
    const degradation = Math.pow(1 - degradationRate, year - 1);
    const inflFactor = applyInflationToOpex ? Math.pow(1 + inflationRate, year - 1) : 1;

    pvCosts += opexBase * inflFactor * df;
    pvEnergy += energyBase * degradation * df;
  }

  return pvEnergy > 0 ? pvCosts / pvEnergy : 0;
}

/**
 * Testy walidacyjne LCOE (uruchamiane przy DEBUG)
 * Sprawdzają poprawność implementacji zgodnie z teorią finansową
 */
function validateLCOECalculations() {
  console.log('🧪 LCOE Validation Tests:');

  // Test A: r=0, stałe koszty i energia
  // LCOE = (CAPEX + N*OPEX) / (N*Energia) = (1M + 10*10k) / (10*1000) = 1,100,000 / 10,000 = 110 PLN/MWh
  const testA = computeLCOE({
    capex: 1000000, opexBase: 10000, energyBase: 1000,
    years: 10, discountRate: 0, degradationRate: 0
  });
  const expectedA = (1000000 + 10 * 10000) / (10 * 1000); // = 110 PLN/MWh
  const passA = Math.abs(testA - expectedA) < 0.01;
  console.log(`  A) r=0, stałe: ${testA.toFixed(1)} vs expected ${expectedA.toFixed(1)} PLN/MWh - ${passA ? '✅ PASS' : '❌ FAIL'}`);

  // Test B: CAPEX only w t=0, energia stała, r=10%
  // LCOE maleje z dłuższym okresem (więcej MWh w mianowniku PV)
  const testB10 = computeLCOE({
    capex: 1000000, opexBase: 0, energyBase: 1000,
    years: 10, discountRate: 0.1, degradationRate: 0
  });
  const testB20 = computeLCOE({
    capex: 1000000, opexBase: 0, energyBase: 1000,
    years: 20, discountRate: 0.1, degradationRate: 0
  });
  const passB = testB20 < testB10;
  console.log(`  B) CAPEX only, r=10%: 10y=${testB10.toFixed(0)}, 20y=${testB20.toFixed(0)} PLN/MWh - ${passB ? '✅ PASS (20y < 10y)' : '❌ FAIL'}`);

  // Test C: autokonsumpcja = 50% produkcji → lcoeEff = 2 * lcoeStd
  // Te same koszty, połowa energii w mianowniku = 2x wyższe LCOE
  const testCstd = computeLCOE({
    capex: 1000000, opexBase: 10000, energyBase: 1000,
    years: 10, discountRate: 0.05, degradationRate: 0
  });
  const testCeff = computeLCOE({
    capex: 1000000, opexBase: 10000, energyBase: 500, // 50% energii
    years: 10, discountRate: 0.05, degradationRate: 0
  });
  const ratio = testCeff / testCstd;
  const passC = Math.abs(ratio - 2.0) < 0.01;
  console.log(`  C) 50% autokons: ratio=${ratio.toFixed(3)} vs expected 2.000 - ${passC ? '✅ PASS' : '❌ FAIL'}`);

  // Podsumowanie
  const allPass = passA && passB && passC;
  console.log(`  📋 Overall: ${allPass ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED'}`);

  return allPass;
}

/**
 * Calculate economics for a single variant
 *
 * METODOLOGIA LCOE (IEA/NREL compliant):
 * =====================================
 *
 * 1. LCOE Standard (lcoeStd) - perspektywa OWNER/SYSTEM
 *    = PV(CAPEX + OPEX) / PV(Produkcja)
 *    Interpretacja: koszt wytworzenia 1 MWh energii przez instalację
 *
 * 2. LCOE Efektywne (lcoeEff) - perspektywa OWNER dla behind-the-meter
 *    = PV(CAPEX + OPEX) / PV(Autokonsumpcja)
 *    Interpretacja: koszt 1 MWh energii faktycznie zużytej (nie eksportowanej)
 *    UWAGA: rośnie przy niskiej autokonsumpcji (te same koszty, mniej energii "pracującej")
 *
 * 3. LCOE Grid (lcoeGrid) - BENCHMARK ceny sieci
 *    = PV(Autokonsumpcja × CenaSieci_t) / PV(Autokonsumpcja)
 *    Interpretacja: levelized koszt zakupu tej samej energii z sieci
 *    KLUCZOWE: używa projekcji cen (z inflacją), nie dzisiejszej ceny!
 *
 * 4. LCOE Offtaker (lcoeOfftaker) - perspektywa KLIENTA EaaS
 *    = PV(Płatności klienta) / PV(Autokonsumpcja)
 *    Płatności = abonament (faza EaaS) + O&M+insurance (po wykupie) + wykup
 *    Interpretacja: realny koszt 1 MWh dla klienta w modelu EaaS
 *
 * 5. Delta Levelized (deltaLevelized)
 *    = lcoeGrid - lcoeOfftaker
 *    Interpretacja: oszczędność klienta [PLN/MWh] vs zakup z sieci
 *    Warunek opłacalności: deltaLevelized > 0
 *
 * SPÓJNOŚĆ NOMINALNA/REALNA:
 * ==========================
 * - useInflation=true  → koszty rosną o inflację, stopa nominalna
 * - useInflation=false → koszty stałe (realne), stopa przeliczana na realną
 *
 * EKSPORT DO SIECI:
 * =================
 * W tym modelu zakładamy eksport=0 (behind-the-meter, pełna autokonsumpcja).
 * Jeśli eksport istnieje, należy odjąć przychody z eksportu od kosztów w liczniku.
 */
function calculateVariantEconomics(variant, params, factor) {
  const capacityKwp = variant.capacity || 0;
  const productionKwh = (variant.production || 0) * factor;
  const selfConsumedKwh = (variant.self_consumed || 0) * factor;
  const autoConsumptionPct = variant.auto_consumption_pct || 0;

  // ===== PARAMETRY WEJŚCIOWE =====
  const capexPerKwp = getCapexForCapacity(capacityKwp);
  const totalCapex = capacityKwp * capexPerKwp;

  // Cena sieci bazowa [PLN/MWh] - użyj zapisanej wartości z economicsSettings (już zawiera ToU + opłaty stałe)
  // lub oblicz na nowo jeśli nie ma
  const totalPricePerMwh = window.economicsSettings?.totalEnergyPrice || calculateTotalEnergyPrice(params);
  const annualOpexBase = capacityKwp * (params.opex_per_kwp || 15); // Bazowy OPEX [PLN/rok]

  const productionMwh = kwhToMwh(productionKwh);
  const selfConsumedMwhYear1 = kwhToMwh(selfConsumedKwh);

  // ===== PARAMETRY FINANSOWE (z ustawień użytkownika) =====
  const discountRateNominal = window.economicsSettings?.discountRate;
  const inflationRate = window.economicsSettings?.inflationRate;
  const useInflation = window.economicsSettings?.useInflation || false;
  const analysisPeriod = params.analysis_period || 25;
  const degradationRate = params.degradation_rate || window.economicsSettings?.degradationRate;

  // ===== SPÓJNOŚĆ NOMINALNA/REALNA =====
  // Jeśli useInflation=false (model realny), przeliczamy stopę na realną
  // aby uniknąć przeszacowania dyskonta przy stałych kosztach
  const discountRateUsed = useInflation
    ? discountRateNominal
    : nominalToReal(discountRateNominal, inflationRate);

  // ===== OBLICZENIA PV - JEDNA PĘTLA, JEDEN DF =====
  // Wszystkie PV liczone w tej samej pętli dla spójności denominatora

  let pvOwnerCosts = totalCapex;  // CAPEX w t=0 (bez dyskonta)
  let pvProd = 0;                 // PV produkcji
  let pvSelf = 0;                 // PV autokonsumpcji (wspólny mianownik!)
  let pvGridCost = 0;             // PV kosztu zakupu z sieci
  let pvClientPayments = 0;       // PV płatności klienta (EaaS)
  let totalOpexSum = 0;           // Suma OPEX niezdyskontowana (do raportu)
  let npv = -totalCapex;          // NPV dla payback

  // Parametry EaaS (jeśli dostępne)
  const eaasParams = window.currentEaaSParams || null;
  const eaasDuration = eaasParams?.duration || 10;
  const baseSubscription = eaasParams?.subscription || 0;
  const baseOmCost = capacityKwp * (eaasParams?.omPerKwp || params.opex_per_kwp || 24);
  const baseInsuranceCost = totalCapex * (window.economicsSettings?.insuranceRate || 0.005);
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';

  for (let year = 1; year <= analysisPeriod; year++) {
    // Discount factor dla tego roku
    const df = pvFactor(year, discountRateUsed);

    // Degradacja per rok (nie jeden factor dla wszystkich lat!)
    const degradation = Math.pow(1 - degradationRate, year - 1);

    // Energia w danym roku [MWh]
    const yearProdMwh = productionMwh * degradation;
    const yearSelfMwh = selfConsumedMwhYear1 * degradation;

    // PV energii (wspólny mianownik dla wszystkich metryk LCOE)
    pvProd += yearProdMwh * df;
    pvSelf += yearSelfMwh * df;

    // Inflacja - stosowana tylko jeśli useInflation=true
    const inflFactor = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;

    // OPEX z inflacją (jeśli włączona)
    const yearOpex = annualOpexBase * inflFactor;
    pvOwnerCosts += yearOpex * df;
    totalOpexSum += yearOpex;

    // Cena sieci w danym roku (z inflacją jako proxy wzrostu cen energii)
    // TODO: jeśli masz gridPriceByYear[] lub escalationRate, użyj tego zamiast CPI
    const gridPriceYear = totalPricePerMwh * inflFactor;
    pvGridCost += yearSelfMwh * gridPriceYear * df;

    // Płatności klienta EaaS
    let clientPaymentYear = 0;
    if (eaasParams && baseSubscription > 0) {
      if (year <= eaasDuration) {
        // Faza EaaS: klient płaci abonament (z indeksacją CPI jeśli włączona)
        const eaasInflFactor = eaasIndexation === 'cpi' ? inflFactor : 1;
        clientPaymentYear = baseSubscription * eaasInflFactor;
      } else {
        // Po wykupie: klient płaci O&M + ubezpieczenie (z inflacją)
        clientPaymentYear = (baseOmCost + baseInsuranceCost) * inflFactor;
      }
      // Wykup na koniec kontraktu EaaS (wartość rezydualna = 0 w tym modelu)
      // Jeśli jest buyout cost, dodaj go w roku eaasDuration
    } else {
      // Brak EaaS - klient = owner, płaci OPEX
      clientPaymentYear = yearOpex;
    }
    pvClientPayments += clientPaymentYear * df;

    // NPV dla simple payback (savings - opex)
    const yearSavings = yearSelfMwh * gridPriceYear;
    const yearNet = yearSavings - yearOpex;
    npv += yearNet * df;
  }

  // ===== METRYKI LCOE =====

  // LCOE Standard - koszt produkcji 1 MWh [PLN/MWh]
  const lcoeStd = pvProd > 0 ? (pvOwnerCosts / pvProd) : 0;

  // LCOE Efektywne - koszt 1 MWh autokonsumowanej [PLN/MWh]
  const lcoeEff = pvSelf > 0 ? (pvOwnerCosts / pvSelf) : 0;

  // LCOE Grid - aktualna cena zakupu z sieci [PLN/MWh]
  // Używamy dzisiejszej ceny (totalPricePerMwh) - prosty benchmark dla użytkownika
  // Nie levelized średnia z inflacją - to byłoby: pvGridCost / pvSelf
  const lcoeGrid = totalPricePerMwh;

  // LCOE Offtaker - levelized koszt dla klienta EaaS [PLN/MWh]
  const lcoeOfftaker = pvSelf > 0 ? (pvClientPayments / pvSelf) : 0;

  // Delta - oszczędność klienta vs aktualna cena sieci [PLN/MWh]
  // Porównanie: LCOE Eff (koszt własnej energii) vs cena sieci dziś
  const deltaLevelized = lcoeGrid - lcoeEff;

  // Marża LCOE - o ile drożej płacisz za autokonsumpcję vs produkcję [%]
  const lcoeMargin = lcoeStd > 0 ? decimalToPct((lcoeEff - lcoeStd) / lcoeStd) : 0;

  // ===== PAYBACK =====
  const annualSavings = selfConsumedMwhYear1 * totalPricePerMwh;
  const netAnnualBenefit = annualSavings - annualOpexBase;
  const payback = totalCapex > 0 && netAnnualBenefit > 0
    ? totalCapex / netAnnualBenefit
    : 99;

  // ===== DEBUG LOG =====
  if (capacityKwp === 500 || capacityKwp === 647 || capacityKwp === 1000) {
    console.log(`📊 LCOE Debug [${capacityKwp} kWp]:`);
    console.log(`   Mode: ${useInflation ? 'NOMINAL' : 'REAL'}, Discount: ${decimalToPct(discountRateUsed).toFixed(1)}%`);
    console.log(`   CAPEX: ${totalCapex.toLocaleString()} PLN (${capexPerKwp} PLN/kWp)`);
    console.log(`   OPEX/rok (base): ${annualOpexBase.toLocaleString()} PLN`);
    console.log(`   Produkcja rok1: ${productionMwh.toFixed(1)} MWh`);
    console.log(`   Autokons. rok1: ${selfConsumedMwhYear1.toFixed(1)} MWh (${autoConsumptionPct.toFixed(1)}%)`);
    console.log(`   PV Owner Costs: ${pvOwnerCosts.toLocaleString()} PLN`);
    console.log(`   PV Production: ${pvProd.toFixed(1)} MWh`);
    console.log(`   PV Self-consumed: ${pvSelf.toFixed(1)} MWh`);
    console.log(`   ---`);
    console.log(`   LCOE Std: ${lcoeStd.toFixed(0)} PLN/MWh (owner, per produkcja)`);
    console.log(`   LCOE Eff: ${lcoeEff.toFixed(0)} PLN/MWh (owner, per autokons)`);
    console.log(`   LCOE Grid: ${lcoeGrid.toFixed(0)} PLN/MWh (benchmark sieci)`);
    console.log(`   LCOE Offtaker: ${lcoeOfftaker.toFixed(0)} PLN/MWh (klient EaaS)`);
    console.log(`   Delta Levelized: ${deltaLevelized.toFixed(0)} PLN/MWh (oszczędność)`);
    console.log(`   Marża: ${lcoeMargin.toFixed(1)}%`);
  }

  return {
    // Legacy fields (zachowane dla kompatybilności UI)
    npv: plnToMlnPln(npv), // mln PLN
    payback: Math.min(payback, 99),
    lcoe: lcoeStd,           // LCOE standardowe (legacy alias)

    // Metryki LCOE - pełny zestaw
    lcoeStd: lcoeStd,        // LCOE owner per produkcja [PLN/MWh]
    lcoeEff: lcoeEff,        // LCOE owner per autokonsumpcja [PLN/MWh]
    lcoeGrid: lcoeGrid,      // LCOE benchmark sieci [PLN/MWh] - NOWE!
    lcoeOfftaker: lcoeOfftaker, // LCOE klient EaaS [PLN/MWh] - NOWE!
    deltaLevelized: deltaLevelized, // Oszczędność klienta [PLN/MWh] - NOWE!
    lcoeMargin: lcoeMargin,  // Marża % (kara za niską autokonsumpcję)

    // Efektywność
    costEfficiency: autoConsumptionPct, // % kosztów "pracujących"
    irr: 0,

    // Dane do analizy i raportów Excel
    totalCapex: totalCapex,
    totalOpex: totalOpexSum,
    totalCostsPV: pvOwnerCosts,        // PV kosztów owner
    totalProductionPV: pvProd,          // PV produkcji
    totalSelfConsumedPV: pvSelf,        // PV autokonsumpcji
    pvGridCost: pvGridCost,             // PV kosztu sieci - NOWE!
    pvClientPayments: pvClientPayments, // PV płatności klienta - NOWE!
    annualOpex: annualOpexBase,
    annualSavings: annualSavings,

    // Parametry wejściowe (do weryfikacji/audytu)
    capexPerKwp: capexPerKwp,
    productionMwhYear1: productionMwh,
    selfConsumedMwhYear1: selfConsumedMwhYear1,
    discountRate: discountRateUsed,     // Faktycznie użyta stopa (nominal lub real)
    discountRateNominal: discountRateNominal, // Stopa z ustawień
    degradationRate: degradationRate,
    analysisPeriod: analysisPeriod,
    useInflation: useInflation,
    inflationRate: inflationRate
  };
}

/**
 * Generate variant scan chart - Professional clean design
 */
function generateVariantScanChart(scanData) {
  const ctx = document.getElementById('variantScanChart');
  if (!ctx) {
    console.log('⚠️ variantScanChart canvas not found');
    return;
  }

  // Destroy existing chart
  if (variantScanChart) {
    variantScanChart.destroy();
    variantScanChart = null;
  }

  // Use more data points for smoother chart (max 125 points)
  const step = Math.max(1, Math.floor(scanData.length / 125));
  const sampledData = scanData.filter((_, i) => i % step === 0 || i === scanData.length - 1);

  const labels = sampledData.map(d => d.capacityMWp.toFixed(1));
  const autoConsData = sampledData.map(d => d.autoConsumptionPct);
  const coverageData = sampledData.map(d => d.coveragePct);

  // Find key points for markers
  let maxNpvIdx = 0;
  let minPaybackIdx = 0;
  let maxNpv = -Infinity;
  let minPayback = Infinity;

  sampledData.forEach((d, idx) => {
    if (d.npv > maxNpv) { maxNpv = d.npv; maxNpvIdx = idx; }
    if (d.payback < minPayback && d.payback < 99) { minPayback = d.payback; minPaybackIdx = idx; }
  });

  // Create gradient fills
  const ctxCanvas = ctx.getContext('2d');

  // Green gradient for autoconsumption
  const greenGradient = ctxCanvas.createLinearGradient(0, 0, 0, 300);
  greenGradient.addColorStop(0, 'rgba(46, 125, 50, 0.25)');
  greenGradient.addColorStop(0.5, 'rgba(46, 125, 50, 0.08)');
  greenGradient.addColorStop(1, 'rgba(46, 125, 50, 0)');

  // Blue gradient for coverage
  const blueGradient = ctxCanvas.createLinearGradient(0, 0, 0, 300);
  blueGradient.addColorStop(0, 'rgba(25, 118, 210, 0.2)');
  blueGradient.addColorStop(0.5, 'rgba(25, 118, 210, 0.05)');
  blueGradient.addColorStop(1, 'rgba(25, 118, 210, 0)');

  // Point radius array - highlight optimum points
  const autoConsPointRadius = autoConsData.map((_, idx) => {
    if (breakevenMode === 'npv' && idx === maxNpvIdx) return 6;
    if (breakevenMode === 'payback' && idx === minPaybackIdx) return 6;
    return 0; // No points normally - cleaner look
  });

  const coveragePointRadius = coverageData.map((_, idx) => {
    if (breakevenMode === 'npv' && idx === maxNpvIdx) return 6;
    if (breakevenMode === 'payback' && idx === minPaybackIdx) return 6;
    return 0;
  });

  variantScanChart = new Chart(ctxCanvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Autokonsumpcja [%]',
          data: autoConsData,
          borderColor: '#2e7d32',
          backgroundColor: greenGradient,
          fill: true,
          tension: 0.3,
          pointRadius: autoConsPointRadius,
          pointHoverRadius: 5,
          pointBackgroundColor: '#2e7d32',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          borderWidth: 2,
          order: 1
        },
        {
          label: 'Pokrycie zużycia [%]',
          data: coverageData,
          borderColor: '#1976d2',
          backgroundColor: blueGradient,
          fill: true,
          tension: 0.3,
          pointRadius: coveragePointRadius,
          pointHoverRadius: 5,
          pointBackgroundColor: '#1976d2',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          borderWidth: 2,
          order: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          position: 'top',
          align: 'center',
          labels: {
            usePointStyle: true,
            pointStyle: 'line',
            padding: 20,
            font: {
              size: 12,
              weight: '500'
            },
            color: '#424242'
          }
        },
        tooltip: {
          backgroundColor: 'rgba(33, 33, 33, 0.95)',
          titleColor: '#fff',
          bodyColor: '#e0e0e0',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          cornerRadius: 8,
          padding: 12,
          displayColors: true,
          boxPadding: 6,
          callbacks: {
            title: function(items) {
              const idx = items[0].dataIndex;
              const d = sampledData[idx];
              return `⚡ ${d.capacity.toFixed(0)} kWp`;
            },
            label: function(context) {
              const value = context.parsed.y.toFixed(1);
              return ` ${context.dataset.label}: ${value}%`;
            },
            afterBody: function(items) {
              const idx = items[0].dataIndex;
              const d = sampledData[idx];
              return [
                '',
                `📊 Produkcja: ${formatNumberEU(d.productionMWh, 0)} MWh/rok`,
                `💰 NPV: ${formatNumberEU(d.npv, 2)} mln PLN`,
                `⏱️ Payback: ${d.payback < 99 ? formatNumberEU(d.payback, 1) + ' lat' : '> 25 lat'}`
              ];
            }
          }
        }
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Moc instalacji PV [MWp]',
            color: '#616161',
            font: {
              size: 12,
              weight: '600'
            },
            padding: { top: 8 }
          },
          ticks: {
            color: '#757575',
            font: { size: 10 },
            maxRotation: 45,
            minRotation: 0,
            autoSkip: true,
            maxTicksLimit: 15
          },
          grid: {
            display: true,
            color: 'rgba(0,0,0,0.04)',
            drawBorder: false
          },
          border: {
            display: false
          }
        },
        y: {
          min: 0,
          max: 100,
          title: {
            display: true,
            text: 'Procent [%]',
            color: '#616161',
            font: {
              size: 12,
              weight: '600'
            },
            padding: { bottom: 8 }
          },
          ticks: {
            color: '#757575',
            font: { size: 10 },
            stepSize: 20,
            callback: function(value) {
              return value + '%';
            }
          },
          grid: {
            display: true,
            color: 'rgba(0,0,0,0.06)',
            drawBorder: false
          },
          border: {
            display: false
          }
        }
      },
      elements: {
        line: {
          capBezierPoints: true
        }
      }
    }
  });
}

// Global variable for LCOE chart
let lcoeAnalysisChart = null;

/**
 * Generate LCOE Analysis Chart
 * Shows LCOE Standard vs LCOE Effective vs Grid Price
 */
function generateLcoeAnalysisChart(scanData) {
  const ctx = document.getElementById('lcoeAnalysisChart');
  if (!ctx) {
    console.log('⚠️ lcoeAnalysisChart canvas not found');
    return;
  }

  // Destroy existing chart
  if (lcoeAnalysisChart) {
    lcoeAnalysisChart.destroy();
    lcoeAnalysisChart = null;
  }

  // Sample data for smoother chart
  const step = Math.max(1, Math.floor(scanData.length / 100));
  const sampledData = scanData.filter((_, i) => i % step === 0 || i === scanData.length - 1);

  const labels = sampledData.map(d => d.capacityMWp.toFixed(1));
  const lcoeStdData = sampledData.map(d => d.lcoeStd || d.lcoe || 0);
  const lcoeEffData = sampledData.map(d => d.lcoeEff || 0);
  const autoConsData = sampledData.map(d => d.autoConsumptionPct || 0);

  // Get grid price for reference line
  const gridPrice = window.economicsSettings?.totalEnergyPrice;

  // Find key points
  let minLcoeEffIdx = 0;
  let minLcoeEff = Infinity;
  let breakEvenIdx = -1; // Where LCOE Eff crosses grid price

  sampledData.forEach((d, idx) => {
    if (d.lcoeEff && d.lcoeEff < minLcoeEff && d.lcoeEff > 0) {
      minLcoeEff = d.lcoeEff;
      minLcoeEffIdx = idx;
    }
    // Find where LCOE Eff crosses grid price (from below)
    if (breakEvenIdx < 0 && d.lcoeEff && d.lcoeEff >= gridPrice) {
      breakEvenIdx = idx;
    }
  });

  const ctxCanvas = ctx.getContext('2d');

  // Create gradients
  const blueGradient = ctxCanvas.createLinearGradient(0, 0, 0, 300);
  blueGradient.addColorStop(0, 'rgba(33, 150, 243, 0.2)');
  blueGradient.addColorStop(1, 'rgba(33, 150, 243, 0)');

  const orangeGradient = ctxCanvas.createLinearGradient(0, 0, 0, 300);
  orangeGradient.addColorStop(0, 'rgba(255, 152, 0, 0.3)');
  orangeGradient.addColorStop(1, 'rgba(255, 152, 0, 0)');

  // Point radius - highlight optimal LCOE Eff point
  const lcoeEffPointRadius = lcoeEffData.map((_, idx) => {
    if (idx === minLcoeEffIdx) return 8;
    if (idx === breakEvenIdx) return 6;
    return 0;
  });

  lcoeAnalysisChart = new Chart(ctxCanvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'LCOE Standardowe [PLN/MWh]',
          data: lcoeStdData,
          borderColor: '#2196f3',
          backgroundColor: blueGradient,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2,
          order: 2,
          yAxisID: 'y'
        },
        {
          label: 'LCOE Efektywne [PLN/MWh]',
          data: lcoeEffData,
          borderColor: '#ff9800',
          backgroundColor: orangeGradient,
          fill: true,
          tension: 0.3,
          pointRadius: lcoeEffPointRadius,
          pointHoverRadius: 6,
          pointBackgroundColor: '#ff9800',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          borderWidth: 3,
          order: 1,
          yAxisID: 'y'
        },
        {
          label: `Cena sieci [${gridPrice} PLN/MWh]`,
          data: labels.map(() => gridPrice),
          borderColor: '#f44336',
          borderDash: [8, 4],
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
          order: 3,
          yAxisID: 'y'
        },
        {
          label: 'Autokonsumpcja [%]',
          data: autoConsData,
          borderColor: '#4caf50',
          borderWidth: 1.5,
          borderDash: [4, 2],
          pointRadius: 0,
          fill: false,
          order: 4,
          yAxisID: 'y2'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            usePointStyle: true,
            padding: 15,
            font: { size: 11, weight: '500' },
            color: '#424242'
          }
        },
        tooltip: {
          backgroundColor: 'rgba(33, 33, 33, 0.95)',
          titleColor: '#fff',
          bodyColor: '#e0e0e0',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          cornerRadius: 8,
          padding: 12,
          callbacks: {
            title: function(items) {
              const idx = items[0].dataIndex;
              const d = sampledData[idx];
              return `⚡ ${d.capacity.toFixed(0)} kWp`;
            },
            label: function(context) {
              const value = context.parsed.y;
              const label = context.dataset.label;
              if (label.includes('%')) {
                return ` ${label.split(' [')[0]}: ${value.toFixed(1)}%`;
              }
              return ` ${label.split(' [')[0]}: ${value.toFixed(0)} PLN/MWh`;
            },
            afterBody: function(items) {
              const idx = items[0].dataIndex;
              const d = sampledData[idx];
              const margin = d.lcoeMargin || 0;
              const savings = gridPrice - (d.lcoeEff || 0);
              return [
                '',
                `📊 Marza LCOE: +${margin.toFixed(0)}%`,
                savings > 0
                  ? `💰 Oszczednosc vs siec: ${savings.toFixed(0)} PLN/MWh`
                  : `⚠️ Drozej niz siec o: ${Math.abs(savings).toFixed(0)} PLN/MWh`
              ];
            }
          }
        },
        annotation: breakEvenIdx >= 0 ? {
          annotations: {
            breakEvenLine: {
              type: 'line',
              xMin: breakEvenIdx,
              xMax: breakEvenIdx,
              borderColor: '#f44336',
              borderWidth: 2,
              borderDash: [5, 5],
              label: {
                display: true,
                content: 'Break-even',
                position: 'start',
                backgroundColor: '#f44336',
                color: '#fff',
                font: { size: 10 }
              }
            }
          }
        } : {}
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Moc instalacji PV [MWp]',
            font: { size: 12, weight: '600' },
            color: '#616161'
          },
          grid: { display: false },
          ticks: {
            maxTicksLimit: 12,
            font: { size: 10 },
            color: '#757575'
          }
        },
        y: {
          position: 'left',
          title: {
            display: true,
            text: 'LCOE [PLN/MWh]',
            font: { size: 12, weight: '600' },
            color: '#616161'
          },
          grid: {
            color: 'rgba(0,0,0,0.06)',
            drawBorder: false
          },
          ticks: {
            font: { size: 10 },
            color: '#757575',
            callback: function(value) {
              return value.toFixed(0);
            }
          },
          suggestedMin: 0,
          suggestedMax: Math.max(gridPrice * 1.5, Math.max(...lcoeEffData) * 1.1)
        },
        y2: {
          position: 'right',
          title: {
            display: true,
            text: 'Autokonsumpcja [%]',
            font: { size: 12, weight: '600' },
            color: '#4caf50'
          },
          grid: { display: false },
          ticks: {
            font: { size: 10 },
            color: '#4caf50',
            callback: function(value) {
              return value.toFixed(0) + '%';
            }
          },
          min: 0,
          max: 100
        }
      }
    }
  });

  // Update LCOE observation text
  updateLcoeObservation(sampledData, minLcoeEffIdx, breakEvenIdx, gridPrice);
}

/**
 * Update LCOE observation text
 */
function updateLcoeObservation(scanData, minLcoeEffIdx, breakEvenIdx, gridPrice) {
  const observationEl = document.getElementById('lcoeObservation');
  if (!observationEl || scanData.length === 0) return;

  const minLcoeData = scanData[minLcoeEffIdx];
  const breakEvenData = breakEvenIdx >= 0 ? scanData[breakEvenIdx] : null;

  let observation = '';

  if (minLcoeData) {
    const savings = gridPrice - minLcoeData.lcoeEff;
    observation = `<strong>Optymalny punkt LCOE Eff:</strong> ${minLcoeData.capacity.toFixed(0)} kWp `;
    observation += `(LCOE Eff: ${minLcoeData.lcoeEff.toFixed(0)} PLN/MWh, `;
    observation += `autokonsumpcja: ${minLcoeData.autoConsumptionPct.toFixed(0)}%). `;

    if (savings > 0) {
      observation += `Oszczednosc vs cena sieci: <strong>${savings.toFixed(0)} PLN/MWh</strong>. `;
    }
  }

  if (breakEvenData) {
    observation += `<br/><strong>Uwaga:</strong> Powyzej ${breakEvenData.capacity.toFixed(0)} kWp LCOE Efektywne przekracza cene sieci - `;
    observation += `instalacja staje sie nieoplacalna przy autokonsumpcji ${breakEvenData.autoConsumptionPct.toFixed(0)}%.`;
  } else if (scanData.length > 0) {
    const lastData = scanData[scanData.length - 1];
    if (lastData.lcoeEff < gridPrice) {
      observation += `<br/>Nawet przy maksymalnej mocy (${lastData.capacity.toFixed(0)} kWp) LCOE Eff pozostaje ponizej ceny sieci.`;
    }
  }

  observationEl.innerHTML = observation;
}

/**
 * Generate variant scan table
 * Highlights optimum point based on selected mode (Max NPV or Min Payback)
 */
function generateVariantScanTable(scanData) {
  const tbody = document.getElementById('variantScanTableBody');
  if (!tbody) return;

  // Find key indices
  let maxNpv = -Infinity;
  let minPayback = Infinity;
  let maxNpvIdx = -1;
  let minPaybackIdx = -1;

  scanData.forEach((d, idx) => {
    if (d.npv > maxNpv) {
      maxNpv = d.npv;
      maxNpvIdx = idx;
    }
    if (d.payback < minPayback && d.payback < 99) {
      minPayback = d.payback;
      minPaybackIdx = idx;
    }
  });

  // Select optimum based on current mode
  const optimumIdx = (breakevenMode === 'payback') ? minPaybackIdx : maxNpvIdx;

  tbody.innerHTML = scanData.map((d, idx) => {
    const rowClass = [];

    // Current variant highlighting
    if (d.isCurrent) rowClass.push('current-variant');

    // OPTIMUM row (based on selected mode) - PRIMARY highlight
    if (idx === optimumIdx) {
      rowClass.push('optimum-row');
    }

    // Secondary highlights for the "other" optimum
    if (breakevenMode === 'npv' && idx === minPaybackIdx && idx !== optimumIdx) {
      rowClass.push('secondary-optimum');
    }
    if (breakevenMode === 'payback' && idx === maxNpvIdx && idx !== optimumIdx) {
      rowClass.push('secondary-optimum');
    }

    // Optimum zone highlighting (5 rows around optimum)
    if (optimumIdx >= 0) {
      const distanceFromOptimum = idx - optimumIdx;
      if (distanceFromOptimum >= -5 && distanceFromOptimum <= 5 && distanceFromOptimum !== 0) {
        rowClass.push('optimum-zone');
      }
    }

    // Color coding for autoconsumption
    let autoConsClass = '';
    if (d.autoConsumptionPct >= 80) autoConsClass = 'value-good';
    else if (d.autoConsumptionPct >= 60) autoConsClass = 'value-warning';
    else autoConsClass = 'value-bad';

    // Color coding for NPV
    let npvClass = '';
    if (d.npv > 0) npvClass = 'value-good';
    else if (d.npv > -0.5) npvClass = 'value-warning';
    else npvClass = 'value-bad';

    // Color coding for payback
    let paybackClass = '';
    if (d.payback < 7) paybackClass = 'value-good';
    else if (d.payback < 12) paybackClass = 'value-warning';
    else paybackClass = 'value-bad';

    // Color coding for LCOE Eff (porównanie z LCOE Grid - poprawne levelized!)
    const lcoeGridValue = d.lcoeGrid || (window.economicsSettings?.totalEnergyPrice);
    let lcoeEffClass = '';
    if (d.lcoeEff && d.lcoeEff < lcoeGridValue * 0.7) lcoeEffClass = 'value-good';      // <70% LCOE Grid
    else if (d.lcoeEff && d.lcoeEff < lcoeGridValue) lcoeEffClass = 'value-warning';    // <100% LCOE Grid
    else lcoeEffClass = 'value-bad';                                                      // >= LCOE Grid

    // Color coding for Delta Levelized (oszczędność klienta)
    const deltaValue = d.deltaLevelized || 0;
    let deltaClass = '';
    if (deltaValue > 100) deltaClass = 'value-good';        // >100 PLN/MWh oszczędności
    else if (deltaValue > 0) deltaClass = 'value-warning';  // >0 PLN/MWh (dodatnia, ale mała)
    else deltaClass = 'value-bad';                           // <=0 (nieopłacalne!)

    // Color coding for LCOE Margin (% narzut)
    let lcoeMarginClass = '';
    if (d.lcoeMargin < 25) lcoeMarginClass = 'value-good';       // <25% narzut
    else if (d.lcoeMargin < 50) lcoeMarginClass = 'value-warning'; // <50% narzut
    else lcoeMarginClass = 'value-bad';                            // >=50% narzut

    return `<tr class="${rowClass.join(' ')}">
      <td>${formatNumberEU(d.capacity, 0)}</td>
      <td>${formatNumberEU(d.productionMWh, 1)}</td>
      <td class="${autoConsClass}">${formatNumberEU(d.autoConsumptionPct, 1)}</td>
      <td>${formatNumberEU(d.coveragePct, 1)}</td>
      <td>${formatNumberEU(d.exportedMWh, 1)}</td>
      <td class="${npvClass}">${formatNumberEU(d.npv, 2)}</td>
      <td class="${paybackClass}">${d.payback < 99 ? formatNumberEU(d.payback, 1) : '> 25'}</td>
      <td>${formatNumberEU(d.lcoeStd || d.lcoe, 0)}</td>
      <td class="${lcoeEffClass}">${formatNumberEU(d.lcoeEff || 0, 0)}</td>
      <td>${formatNumberEU(d.lcoeGrid || 0, 0)}</td>
      <td class="${deltaClass}">${formatNumberEU(deltaValue, 0)}</td>
    </tr>`;
  }).join('');
}

/**
 * Update observation text based on scan data and selected mode
 */
function updateVariantScanObservation(scanData) {
  const observationEl = document.getElementById('variantScanObservation');
  if (!observationEl || scanData.length === 0) return;

  // Find key points
  let threshold80Capacity = null;
  let maxNpvCapacity = null;
  let maxNpv = -Infinity;
  let minPaybackCapacity = null;
  let minPayback = Infinity;

  for (const d of scanData) {
    if (d.autoConsumptionPct <= 80 && threshold80Capacity === null) {
      threshold80Capacity = d.capacity;
    }
    if (d.npv > maxNpv) {
      maxNpv = d.npv;
      maxNpvCapacity = d.capacity;
    }
    if (d.payback < minPayback && d.payback < 99) {
      minPayback = d.payback;
      minPaybackCapacity = d.capacity;
    }
  }

  let observation = '';

  if (breakevenMode === 'payback') {
    // Min Payback mode
    if (minPaybackCapacity) {
      observation = `<strong>Tryb: Minimalny Payback</strong> - Najkrótszy okres zwrotu (${formatNumberEU(minPayback, 1)} lat) przy mocy ${formatNumberEU(minPaybackCapacity, 0)} kWp.`;
      if (maxNpvCapacity && maxNpvCapacity !== minPaybackCapacity) {
        observation += ` Dla porównania: maksymalny NPV (${formatNumberEU(maxNpv, 2)} mln PLN) osiągany jest przy ${formatNumberEU(maxNpvCapacity, 0)} kWp.`;
      }
    } else {
      observation = 'Nie znaleziono optymalnego punktu zwrotu inwestycji w analizowanym zakresie mocy.';
    }
  } else {
    // Max NPV mode (default)
    if (threshold80Capacity && maxNpvCapacity) {
      if (maxNpvCapacity < threshold80Capacity) {
        observation = `<strong>Tryb: Maksymalny NPV</strong> - Optymalny NPV (${formatNumberEU(maxNpv, 2)} mln PLN) osiągany przy ${formatNumberEU(maxNpvCapacity, 0)} kWp, gdzie autokonsumpcja wynosi ponad 80%.`;
      } else {
        observation = `<strong>Tryb: Maksymalny NPV</strong> - Maksymalny NPV (${formatNumberEU(maxNpv, 2)} mln PLN) przy ${formatNumberEU(maxNpvCapacity, 0)} kWp. Granica 80% autokonsumpcji: ${formatNumberEU(threshold80Capacity, 0)} kWp.`;
      }
      if (minPaybackCapacity && minPaybackCapacity !== maxNpvCapacity) {
        observation += ` Najkrótszy payback (${formatNumberEU(minPayback, 1)} lat) przy ${formatNumberEU(minPaybackCapacity, 0)} kWp.`;
      }
    } else if (maxNpvCapacity) {
      observation = `<strong>Tryb: Maksymalny NPV</strong> - Najwyższy NPV (${formatNumberEU(maxNpv, 2)} mln PLN) przy mocy ${formatNumberEU(maxNpvCapacity, 0)} kWp.`;
    } else {
      observation = 'Wraz ze wzrostem mocy instalacji powyżej pewnego progu, autokonsumpcja spada, co oznacza, że dodatkowa moc generuje głównie nadwyżki eksportowane do sieci.';
    }
  }

  observationEl.innerHTML = observation;
}

// Expose function globally
window.generateVariantScanSection = generateVariantScanSection;

/**
 * Export Variant Scan data to Excel with European formatting, formulas, and clean look
 * Uses ExcelJS for advanced styling (matching EaaS export)
 */
async function exportVariantScanToExcel() {
  // Get scenarios data
  const scenarios = analysisResults?.scenarios;
  if (!scenarios || scenarios.length === 0) {
    alert('Brak danych do eksportu. Wykonaj najpierw symulację.');
    return;
  }

  const params = getEconomicParameters();
  const factor = window.currentScenarioFactor || 1.0;
  const gridPrice = window.economicsSettings?.totalEnergyPrice;
  const discountRate = window.economicsSettings?.discountRate;
  const analysisPeriod = params.analysis_period || 25;
  const opexPerKwp = params.opex_per_kwp || 15;
  const degradationRate = params.degradation_rate || window.economicsSettings?.degradationRate;
  const useInflation = window.economicsSettings?.useInflation || false;
  const inflationRate = useInflation ? window.economicsSettings?.inflationRate : 0;

  // Sort scenarios by capacity
  const sortedScenarios = [...scenarios].sort((a, b) => (a.capacity || 0) - (b.capacity || 0));

  // Find optimal points
  let maxNpvCapacity = 0, maxNpv = -Infinity;
  let minPaybackCapacity = 0, minPayback = Infinity;
  let minLcoeEffCapacity = 0, minLcoeEff = Infinity;

  // Prepare main data
  const mainData = [];
  for (const s of sortedScenarios) {
    if (!s || !s.capacity) continue;

    const capacityKwp = s.capacity;
    const productionKwh = (s.production || 0) * factor;
    const selfConsumedKwh = (s.self_consumed || 0) * factor;
    const exportedKwh = (s.exported || 0) * factor;
    const autoConsumptionPct = s.auto_consumption_pct || 0;
    const coveragePct = s.coverage_pct || 0;

    const economics = calculateVariantEconomics(s, params, factor);

    // Track optimal points
    if (economics.npv > maxNpv) { maxNpv = economics.npv; maxNpvCapacity = capacityKwp; }
    if (economics.payback < minPayback && economics.payback < 99) { minPayback = economics.payback; minPaybackCapacity = capacityKwp; }
    if (economics.lcoeEff < minLcoeEff && economics.lcoeEff > 0) { minLcoeEff = economics.lcoeEff; minLcoeEffCapacity = capacityKwp; }

    mainData.push({
      capacity: capacityKwp,
      capacityMwp: kwhToMwh(capacityKwp),
      productionMwh: kwhToMwh(productionKwh),
      autoConsumptionPct: autoConsumptionPct,
      coveragePct: coveragePct,
      selfConsumedMwh: kwhToMwh(selfConsumedKwh),
      exportedMwh: kwhToMwh(exportedKwh),
      capexTotal: economics.totalCapex,
      capexPerKwp: economics.capexPerKwp,
      opexAnnual: economics.annualOpex,
      npv: economics.npv,
      payback: economics.payback,
      lcoeStd: economics.lcoeStd,
      lcoeEff: economics.lcoeEff,
      lcoeGrid: economics.lcoeGrid,           // NOWE: levelized grid cost
      lcoeOfftaker: economics.lcoeOfftaker,   // NOWE: levelized client cost
      deltaLevelized: economics.deltaLevelized, // NOWE: oszczędność klienta
      lcoeMargin: economics.lcoeMargin,
      savings: economics.deltaLevelized || (gridPrice - economics.lcoeEff) // Używaj deltaLevelized jeśli dostępne
    });
  }

  if (mainData.length === 0) {
    alert('Brak danych do eksportu.');
    return;
  }

  // Create ExcelJS workbook (for advanced styling)
  const excelWorkbook = new ExcelJS.Workbook();
  excelWorkbook.creator = 'Pagra Energy Studio';
  excelWorkbook.created = new Date();

  // Try to load logo
  let logoImageId = null;
  try {
    const logoResponse = await fetch('logo.png');
    if (logoResponse.ok) {
      const logoBlob = await logoResponse.blob();
      const logoBase64 = await new Promise(resolve => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.readAsDataURL(logoBlob);
      });
      logoImageId = excelWorkbook.addImage({
        base64: logoBase64,
        extension: 'png'
      });
    }
  } catch (err) {
    console.warn('⚠️ Could not load logo:', err);
  }

  // ========== SHEET 1: Podsumowanie LCOE (clean look) ==========
  const sheet1 = excelWorkbook.addWorksheet('Podsumowanie LCOE');
  sheet1.columns = [
    { width: 3 },   // A: margin
    { width: 32 },  // B: labels
    { width: 18 },  // C: values
    { width: 14 },  // D: units
    { width: 35 }   // E: descriptions
  ];
  sheet1.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Header with logo
  sheet1.mergeCells('B1:E3');
  const headerCell = sheet1.getCell('B1');
  headerCell.value = 'ANALIZA LCOE - Skan Wariantów Mocy PV';
  headerCell.font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  headerCell.alignment = { horizontal: 'center', vertical: 'bottom' };
  sheet1.getRow(1).height = 20;
  sheet1.getRow(2).height = 20;
  sheet1.getRow(3).height = 24;

  if (logoImageId !== null) {
    sheet1.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },
      ext: { width: 180, height: 45 }
    });
  }

  // Section: PARAMETRY MODELU (row 5)
  let row = 5;
  const addSectionHeader = (sheet, rowNum, title) => {
    const r = sheet.getRow(rowNum);
    r.getCell(2).value = title;
    r.getCell(2).font = { bold: true, size: 11, color: { argb: 'FF2E7D32' } };
    r.getCell(2).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    r.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    r.getCell(4).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    r.getCell(5).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  };

  const addDataRow = (sheet, rowNum, label, value, unit, desc) => {
    const r = sheet.getRow(rowNum);
    r.getCell(2).value = label;
    r.getCell(3).value = value;
    r.getCell(3).alignment = { horizontal: 'right' };
    r.getCell(4).value = unit;
    r.getCell(5).value = desc || '';
    r.getCell(2).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    r.getCell(3).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    r.getCell(4).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
  };

  addSectionHeader(sheet1, row, 'PARAMETRY MODELU');
  row++;
  addDataRow(sheet1, row++, 'Okres analizy', analysisPeriod, 'lat', 'Horyzont NPV i LCOE');
  addDataRow(sheet1, row++, 'Stopa dyskontowa', decimalToPct(discountRate).toFixed(1), '%', 'Dyskontowanie przepływów');
  addDataRow(sheet1, row++, 'Degradacja PV', decimalToPct(degradationRate).toFixed(2), '%/rok', 'Roczny spadek produkcji');
  addDataRow(sheet1, row++, 'OPEX', opexPerKwp, 'PLN/kWp/rok', 'Koszty O&M');
  addDataRow(sheet1, row++, 'Inflacja OPEX', useInflation ? decimalToPct(inflationRate).toFixed(1) + '%' : 'wyłączona', '', useInflation ? 'Indeksacja kosztów O&M' : '');
  addDataRow(sheet1, row++, 'Cena energii z sieci', Math.round(gridPrice), 'PLN/MWh', 'Benchmark zakupu');

  row += 2;
  addSectionHeader(sheet1, row, 'SKŁADNIKI CENY ENERGII Z SIECI');
  row++;
  addDataRow(sheet1, row++, 'Energia czynna (śr. ToU)', Math.round(params.energy_active), 'PLN/MWh', 'Średnia stawka trzystrefowa');
  addDataRow(sheet1, row++, 'Dystrybucja', Math.round(params.distribution), 'PLN/MWh', 'Opłata sieciowa OSD');
  addDataRow(sheet1, row++, 'Opłata jakościowa', Math.round(params.quality_fee), 'PLN/MWh', '');
  addDataRow(sheet1, row++, 'Opłata OZE', Math.round(params.oze_fee), 'PLN/MWh', '');
  addDataRow(sheet1, row++, 'Opłata kogeneracyjna', Math.round(params.cogeneration_fee), 'PLN/MWh', '');
  addDataRow(sheet1, row++, 'Opłata mocowa', Math.round(params.capacity_fee), 'PLN/MWh', 'Tylko 7-22 Pn-Pt');
  addDataRow(sheet1, row++, 'Akcyza', Math.round(params.excise_tax), 'PLN/MWh', '');

  // Highlight total
  const totalRow = sheet1.getRow(row);
  totalRow.getCell(2).value = 'SUMA (cena z sieci)';
  totalRow.getCell(2).font = { bold: true, color: { argb: 'FF1565C0' } };
  totalRow.getCell(3).value = { formula: `SUM(C${row-7}:C${row-1})` };  // English formula - Excel converts
  totalRow.getCell(3).font = { bold: true, color: { argb: 'FF1565C0' } };
  totalRow.getCell(3).alignment = { horizontal: 'right' };
  totalRow.getCell(4).value = 'PLN/MWh';
  totalRow.getCell(4).font = { bold: true, color: { argb: 'FF1565C0' } };

  row += 3;
  addSectionHeader(sheet1, row, 'PUNKTY OPTYMALNE');
  row++;
  addDataRow(sheet1, row++, '★ Max NPV', maxNpvCapacity, 'kWp', maxNpv.toFixed(2) + ' mln PLN');
  addDataRow(sheet1, row++, '★ Min Payback', minPaybackCapacity, 'kWp', minPayback.toFixed(1) + ' lat');
  addDataRow(sheet1, row++, '★ Min LCOE Efektywne', minLcoeEffCapacity, 'kWp', Math.round(minLcoeEff) + ' PLN/MWh');

  // ========== SHEET 2: Skan Wariantów - FULLY AUDITABLE ==========
  const sheet2 = excelWorkbook.addWorksheet('Skan Wariantów');
  sheet2.columns = [
    { width: 3 },   // A: margin
    { width: 12 },  // B: Moc kWp
    { width: 14 },  // C: Produkcja MWh
    { width: 12 },  // D: Autokons. %
    { width: 14 },  // E: Autokons. MWh
    { width: 16 },  // F: CAPEX PLN
    { width: 12 },  // G: CAPEX/kWp
    { width: 14 },  // H: OPEX/rok
    { width: 14 },  // I: NPV PLN
    { width: 10 },  // J: Payback
    { width: 12 },  // K: LCOE Std
    { width: 12 },  // L: LCOE Eff
    { width: 10 },  // M: Marża %
    { width: 12 }   // N: vs Sieć
  ];
  sheet2.views = [{ showGridLines: false, showRowColHeaders: false, state: 'frozen', ySplit: 10 }];

  // Number format for Polish Excel: # ##0,00 (space as thousands separator, comma as decimal)
  const numFmtInt = '#,##0';        // 1 000
  const numFmtDec1 = '#,##0.0';     // 1 000,0
  const numFmtDec2 = '#,##0.00';    // 1 000,00
  const numFmtPct = '0.0%';         // 85,5%

  // Header
  sheet2.mergeCells('B1:N2');
  sheet2.getCell('B1').value = 'SKAN WARIANTÓW MOCY PV - Analiza LCOE';
  sheet2.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  sheet2.getCell('B1').alignment = { horizontal: 'center', vertical: 'middle' };

  // ===== PARAMETERS SECTION (rows 4-7) - referenced by formulas =====
  addSectionHeader(sheet2, 4, 'PARAMETRY MODELU (używane w formułach)');

  // Row 5: Main parameters
  sheet2.getCell('B5').value = 'Cena sieci [PLN/MWh]';
  sheet2.getCell('C5').value = gridPrice;  // Cell C5 - referenced as $C$5
  sheet2.getCell('C5').numFmt = numFmtInt;
  sheet2.getCell('C5').font = { bold: true };

  sheet2.getCell('D5').value = 'OPEX [PLN/kWp/rok]';
  sheet2.getCell('E5').value = opexPerKwp;  // Cell E5 - referenced as $E$5
  sheet2.getCell('E5').numFmt = numFmtInt;
  sheet2.getCell('E5').font = { bold: true };

  sheet2.getCell('F5').value = 'Stopa dysk.';
  sheet2.getCell('G5').value = discountRate;  // Cell G5 - referenced as $G$5
  sheet2.getCell('G5').numFmt = numFmtPct;
  sheet2.getCell('G5').font = { bold: true };

  sheet2.getCell('H5').value = 'Okres [lat]';
  sheet2.getCell('I5').value = analysisPeriod;  // Cell I5 - referenced as $I$5
  sheet2.getCell('I5').numFmt = numFmtInt;
  sheet2.getCell('I5').font = { bold: true };

  // Row 6: Additional parameters
  sheet2.getCell('B6').value = 'Degradacja [%/rok]';
  sheet2.getCell('C6').value = degradationRate;  // Cell C6 - referenced as $C$6
  sheet2.getCell('C6').numFmt = '0.00%';
  sheet2.getCell('C6').font = { bold: true };

  sheet2.getCell('D6').value = 'Inflacja OPEX';
  sheet2.getCell('E6').value = inflationRate;  // Cell E6 - referenced as $E$6
  sheet2.getCell('E6').numFmt = numFmtPct;
  sheet2.getCell('E6').font = { bold: true };
  if (!useInflation) {
    sheet2.getCell('E6').font = { bold: true, color: { argb: 'FF999999' } };
  }

  // Row 8: Formula legend
  sheet2.getCell('B8').value = 'LEGENDA FORMUŁ:';
  sheet2.getCell('B8').font = { bold: true, size: 9, color: { argb: 'FF666666' } };
  sheet2.getCell('C8').value = 'NPV = -CAPEX + Σ(Oszczędności × Faktor_dysk)';
  sheet2.getCell('C8').font = { italic: true, size: 9, color: { argb: 'FF666666' } };
  sheet2.mergeCells('C8:G8');
  sheet2.getCell('H8').value = 'LCOE = Σ(Koszty_dysk) / Σ(Energia_dysk)';
  sheet2.getCell('H8').font = { italic: true, size: 9, color: { argb: 'FF666666' } };
  sheet2.mergeCells('H8:L8');

  // ===== COLUMN HEADERS (row 10) =====
  const headers = ['Moc [kWp]', 'Prod. [MWh]', 'Autok. [%]', 'Autok. [MWh]', 'CAPEX [PLN]', 'CAPEX/kWp', 'OPEX/rok [PLN]', 'NPV [PLN]', 'Payback [lat]', 'LCOE Std', 'LCOE Eff', 'Marża [%]', 'Oszcz. [PLN/MWh]'];
  const headerRow = sheet2.getRow(10);
  headers.forEach((h, i) => {
    const cell = headerRow.getCell(i + 2);
    cell.value = h;
    cell.font = { bold: true, size: 10, color: { argb: 'FFFFFFFF' } };
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1976D2' } };
    cell.alignment = { horizontal: 'center' };
    cell.border = {
      bottom: { style: 'thin', color: { argb: 'FF0D47A1' } },
      right: { style: 'thin', color: { argb: 'FF0D47A1' } }
    };
  });

  // ===== DATA ROWS WITH FORMULAS =====
  const sheet2DataStartRow = 11;
  mainData.forEach((d, idx) => {
    const rowNum = sheet2DataStartRow + idx;
    const r = sheet2.getRow(rowNum);

    // B: Moc kWp (input value)
    r.getCell(2).value = d.capacity;
    r.getCell(2).numFmt = numFmtInt;

    // C: Produkcja MWh (input value - from simulation)
    r.getCell(3).value = d.productionMwh;
    r.getCell(3).numFmt = numFmtDec1;

    // D: Autokonsumpcja % (input value - from simulation)
    r.getCell(4).value = d.autoConsumptionPct / 100;
    r.getCell(4).numFmt = numFmtPct;

    // E: Autokonsumpcja MWh - FORMULA: =C*D
    r.getCell(5).value = { formula: `C${rowNum}*D${rowNum}` };
    r.getCell(5).numFmt = numFmtDec1;

    // F: CAPEX PLN (input value - from CAPEX tiers)
    r.getCell(6).value = d.capexTotal;
    r.getCell(6).numFmt = numFmtInt;

    // G: CAPEX/kWp - FORMULA: =F/B
    r.getCell(7).value = { formula: `F${rowNum}/B${rowNum}` };
    r.getCell(7).numFmt = numFmtInt;

    // H: OPEX/rok - FORMULA: =B*$E$5 (Moc * OPEX per kWp)
    r.getCell(8).value = { formula: `B${rowNum}*$E$5` };
    r.getCell(8).numFmt = numFmtInt;

    // I: NPV PLN - FORMULA using Excel NPV approximation
    // NPV = -CAPEX + Σ[(AutoMWh*1000*CenaSieci*(1-degr)^(y-1) - OPEX*(1+infl)^(y-1)) / (1+r)^y]
    // Using geometric series approximation for auditable formula:
    // Roczne oszczędności rok 1 = E (AutoMWh) * $C$5 (cena) * 1000 - H (OPEX)
    // PV factor for growing annuity = (1 - ((1-g)/(1+r))^n) / (r+g) where g=degradation
    // Simplified NPV formula: = -F + (E*$C$5*1000 - H) * PV_factor
    // For full auditability, we use a compound formula
    r.getCell(9).value = { formula: `-F${rowNum}+(E${rowNum}*$C$5*1000-H${rowNum})*((1-POWER((1-$C$6)/(1+$G$5),$I$5))/($G$5+$C$6))` };
    r.getCell(9).numFmt = numFmtInt;

    // J: Payback - FORMULA: =CAPEX / Roczne_oszczędności
    // Prosty payback = CAPEX / (AutoMWh * Cena * 1000 - OPEX)
    r.getCell(10).value = { formula: `IF((E${rowNum}*$C$5*1000-H${rowNum})>0,F${rowNum}/(E${rowNum}*$C$5*1000-H${rowNum}),"-")` };
    r.getCell(10).numFmt = numFmtDec1;

    // K: LCOE Std - FORMULA using discounted costs / discounted production
    // LCOE = (CAPEX + Σ OPEX_dysk) / Σ Prod_dysk
    // Using PV factors: LCOE = (CAPEX + OPEX * PV_annuity) / (Prod * PV_degraded_annuity)
    // PV_annuity = (1 - 1/(1+r)^n) / r
    // PV_degraded = (1 - ((1-g)/(1+r))^n) / (r+g)
    const pvAnnuityFormula = `(1-1/POWER(1+$G$5,$I$5))/$G$5`;  // For OPEX
    const pvDegradedFormula = `(1-POWER((1-$C$6)/(1+$G$5),$I$5))/($G$5+$C$6)`;  // For production
    r.getCell(11).value = { formula: `(F${rowNum}+H${rowNum}*${pvAnnuityFormula})/(C${rowNum}*${pvDegradedFormula})` };
    r.getCell(11).numFmt = numFmtInt;

    // L: LCOE Eff - FORMULA: LCOE based on autoconsumption (not total production)
    r.getCell(12).value = { formula: `(F${rowNum}+H${rowNum}*${pvAnnuityFormula})/(E${rowNum}*${pvDegradedFormula})` };
    r.getCell(12).numFmt = numFmtInt;

    // M: Marża % - FORMULA: =(L-K)/K
    r.getCell(13).value = { formula: `(L${rowNum}-K${rowNum})/K${rowNum}` };
    r.getCell(13).numFmt = numFmtPct;

    // N: Oszczędność vs Sieć - FORMULA: =$C$5-L (GridPrice - LCOE Eff)
    r.getCell(14).value = { formula: `$C$5-L${rowNum}` };
    r.getCell(14).numFmt = numFmtInt;

    // Conditional formatting colors
    const autoConsPct = d.autoConsumptionPct;
    const lcoeEff = d.lcoeEff;

    // Row background based on autoconsumption
    let rowColor = 'FFFFFFFF';
    if (autoConsPct >= 80) rowColor = 'FFE8F5E9';      // Green - optimal
    else if (autoConsPct >= 60) rowColor = 'FFFFFDE7'; // Yellow - good
    else if (autoConsPct >= 40) rowColor = 'FFFFF3E0'; // Orange - warning
    else rowColor = 'FFFFEBEE';                         // Red - oversized

    for (let c = 2; c <= 14; c++) {
      r.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: rowColor } };
      r.getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
      r.getCell(c).alignment = { horizontal: 'right' };
    }

    // LCOE Eff color based on grid price comparison
    if (lcoeEff > gridPrice) {
      r.getCell(12).font = { color: { argb: 'FFC62828' }, bold: true }; // Red - unprofitable
      r.getCell(14).font = { color: { argb: 'FFC62828' }, bold: true };
    } else if (lcoeEff < gridPrice * 0.7) {
      r.getCell(12).font = { color: { argb: 'FF2E7D32' }, bold: true }; // Green - very good
      r.getCell(14).font = { color: { argb: 'FF2E7D32' }, bold: true };
    }
  });

  // Add note about NPV/LCOE calculation methodology
  const noteRow = sheet2DataStartRow + mainData.length + 2;
  sheet2.getCell(`B${noteRow}`).value = 'UWAGA: NPV, LCOE Std i LCOE Eff są obliczane metodą DCF (Discounted Cash Flow) z uwzględnieniem:';
  sheet2.getCell(`B${noteRow}`).font = { italic: true, size: 9, color: { argb: 'FF666666' } };
  sheet2.mergeCells(`B${noteRow}:N${noteRow}`);
  sheet2.getCell(`B${noteRow+1}`).value = '• Degradacji paneli PV (spadek produkcji rok do roku)  • Dyskontowania przepływów pieniężnych  • Inflacji kosztów OPEX (jeśli włączona)';
  sheet2.getCell(`B${noteRow+1}`).font = { italic: true, size: 9, color: { argb: 'FF666666' } };
  sheet2.mergeCells(`B${noteRow+1}:N${noteRow+1}`);
  sheet2.getCell(`B${noteRow+2}`).value = 'Szczegółowy model rok-po-roku znajduje się w arkuszu "Model LCOE"';
  sheet2.getCell(`B${noteRow+2}`).font = { italic: true, size: 9, color: { argb: 'FF1976D2' } };
  sheet2.mergeCells(`B${noteRow+2}:N${noteRow+2}`);

  // ========== SHEET 3: Model LCOE z formułami ==========
  const sheet3 = excelWorkbook.addWorksheet('Model LCOE');
  sheet3.columns = [
    { width: 3 },   // A: margin
    { width: 6 },   // B: Rok
    { width: 14 },  // C: Produkcja
    { width: 14 },  // D: Autokons.
    { width: 14 },  // E: OPEX
    { width: 14 },  // F: Dyskonto
    { width: 16 },  // G: Koszty zdysk
    { width: 16 },  // H: Prod. zdysk
    { width: 16 }   // I: Auto. zdysk
  ];
  sheet3.views = [{ showGridLines: false, showRowColHeaders: false, state: 'frozen', ySplit: 11 }];

  // Example calculation for ~500 kWp or middle point
  const exampleData = mainData.find(d => d.capacity >= 450 && d.capacity <= 550) || mainData[Math.floor(mainData.length / 2)];
  const exampleCapex = exampleData.capexTotal;
  const exampleOpexYear1 = exampleData.opexAnnual;
  const exampleProdYear1 = exampleData.productionMwh;
  const exampleAutoYear1 = exampleData.selfConsumedMwh;

  sheet3.mergeCells('B1:I3');
  sheet3.getCell('B1').value = 'MODEL LCOE - Obliczenia z formułami';
  sheet3.getCell('B1').font = { bold: true, size: 14, color: { argb: 'FF1976D2' } };
  sheet3.getCell('B1').alignment = { horizontal: 'center', vertical: 'bottom' };

  // Input parameters section
  addSectionHeader(sheet3, 5, 'DANE WEJŚCIOWE (przykład)');

  // Parameters - use values directly for clarity
  sheet3.getCell('B6').value = 'Moc [kWp]';
  sheet3.getCell('C6').value = exampleData.capacity;
  sheet3.getCell('C6').numFmt = '#,##0';
  sheet3.getCell('C6').font = { bold: true };

  sheet3.getCell('D6').value = 'CAPEX [PLN]';
  sheet3.getCell('E6').value = exampleCapex;
  sheet3.getCell('E6').numFmt = '#,##0';

  sheet3.getCell('F6').value = 'OPEX rok1';
  sheet3.getCell('G6').value = exampleOpexYear1;
  sheet3.getCell('G6').numFmt = '#,##0';

  sheet3.getCell('B7').value = 'Prod. rok1 [MWh]';
  sheet3.getCell('C7').value = exampleProdYear1;
  sheet3.getCell('C7').numFmt = '#,##0,0';

  sheet3.getCell('D7').value = 'Auto. rok1 [MWh]';
  sheet3.getCell('E7').value = exampleAutoYear1;
  sheet3.getCell('E7').numFmt = '#,##0,0';

  sheet3.getCell('F7').value = 'Stopa dysk.';
  sheet3.getCell('G7').value = discountRate;
  sheet3.getCell('G7').numFmt = '0.0%';

  sheet3.getCell('H6').value = 'Degradacja';
  sheet3.getCell('I6').value = degradationRate;
  sheet3.getCell('I6').numFmt = '0.00%';

  sheet3.getCell('H7').value = 'Inflacja OPEX';
  sheet3.getCell('I7').value = useInflation ? inflationRate : 0;
  sheet3.getCell('I7').numFmt = '0.0%';
  if (!useInflation) {
    sheet3.getCell('I7').font = { color: { argb: 'FF999999' } };
  }

  // Year-by-year calculation headers (row 11)
  const calcHeaders = ['Rok', 'Produkcja [MWh]', 'Autokons. [MWh]', 'OPEX [PLN]', 'Faktor dysk.', 'Koszty zdysk.', 'Prod. zdysk.', 'Auto. zdysk.'];
  const calcHeaderRow = sheet3.getRow(11);
  calcHeaders.forEach((h, i) => {
    const cell = calcHeaderRow.getCell(i + 2);
    cell.value = h;
    cell.font = { bold: true, size: 10, color: { argb: 'FFFFFFFF' } };
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1976D2' } };
    cell.alignment = { horizontal: 'center' };
  });

  // Year 0 (CAPEX only) - row 12
  const year0Row = sheet3.getRow(12);
  year0Row.getCell(2).value = 0;
  year0Row.getCell(3).value = '-';
  year0Row.getCell(4).value = '-';
  year0Row.getCell(5).value = '-';
  year0Row.getCell(6).value = 1;
  year0Row.getCell(7).value = { formula: 'E6' }; // CAPEX - English formula
  year0Row.getCell(7).numFmt = '#,##0';
  year0Row.getCell(8).value = 0;
  year0Row.getCell(9).value = 0;

  // Years 1-N with FORMULAS (English syntax - Excel converts automatically)
  // Row 13 = year 1, Row 14 = year 2, etc.
  const dataStartRow = 13;
  for (let year = 1; year <= analysisPeriod; year++) {
    const rowNum = dataStartRow + year - 1;
    const r = sheet3.getRow(rowNum);
    r.getCell(2).value = year;

    // Produkcja = Prod_rok1 * (1-degr)^(rok-1)  -->  =C7*POWER(1-I6,B13-1)
    r.getCell(3).value = { formula: `$C$7*POWER(1-$I$6,B${rowNum}-1)` };
    r.getCell(3).numFmt = '#,##0,0';

    // Autokonsumpcja = Auto_rok1 * (1-degr)^(rok-1)  -->  =E7*POWER(1-I6,B13-1)
    r.getCell(4).value = { formula: `$E$7*POWER(1-$I$6,B${rowNum}-1)` };
    r.getCell(4).numFmt = '#,##0,0';

    // OPEX z inflacją = OPEX_rok1 * (1+infl)^(rok-1)  -->  =G6*POWER(1+I7,B13-1)
    r.getCell(5).value = { formula: `$G$6*POWER(1+$I$7,B${rowNum}-1)` };
    r.getCell(5).numFmt = '#,##0';

    // Faktor dyskontowy = 1/(1+r)^rok  -->  =1/POWER(1+G7,B13)
    r.getCell(6).value = { formula: `1/POWER(1+$G$7,B${rowNum})` };
    r.getCell(6).numFmt = '0.0000';

    // Koszty zdyskontowane = OPEX * faktor  -->  =E13*F13
    r.getCell(7).value = { formula: `E${rowNum}*F${rowNum}` };
    r.getCell(7).numFmt = '#,##0';

    // Produkcja zdyskontowana  -->  =C13*F13
    r.getCell(8).value = { formula: `C${rowNum}*F${rowNum}` };
    r.getCell(8).numFmt = '#,##0,00';

    // Autokonsumpcja zdyskontowana  -->  =D13*F13
    r.getCell(9).value = { formula: `D${rowNum}*F${rowNum}` };
    r.getCell(9).numFmt = '#,##0,00';

    // Alternate row coloring
    const bgColor = year % 2 === 0 ? 'FFF5F5F5' : 'FFFFFFFF';
    for (let c = 2; c <= 9; c++) {
      r.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } };
    }
  }

  // SUMA row (English SUM - Excel converts)
  const lastDataRow = dataStartRow + analysisPeriod - 1;
  const sumRowNum = lastDataRow + 1;
  const sumRow = sheet3.getRow(sumRowNum);
  sumRow.getCell(2).value = 'SUMA';
  sumRow.getCell(2).font = { bold: true };
  // Koszty sum = CAPEX (row 12) + sum of OPEX discounted (rows 13-N)
  sumRow.getCell(7).value = { formula: `G12+SUM(G${dataStartRow}:G${lastDataRow})` };
  sumRow.getCell(7).numFmt = '#,##0';
  sumRow.getCell(7).font = { bold: true, color: { argb: 'FF1565C0' } };
  sumRow.getCell(8).value = { formula: `SUM(H${dataStartRow}:H${lastDataRow})` };
  sumRow.getCell(8).numFmt = '#,##0,0';
  sumRow.getCell(8).font = { bold: true, color: { argb: 'FF1565C0' } };
  sumRow.getCell(9).value = { formula: `SUM(I${dataStartRow}:I${lastDataRow})` };
  sumRow.getCell(9).numFmt = '#,##0,0';
  sumRow.getCell(9).font = { bold: true, color: { argb: 'FF1565C0' } };

  // LCOE Results
  const lcoeRowNum = sumRowNum + 2;
  addSectionHeader(sheet3, lcoeRowNum, 'WYNIKI LCOE');

  sheet3.getCell(`B${lcoeRowNum+1}`).value = 'LCOE Standardowe';
  sheet3.getCell(`C${lcoeRowNum+1}`).value = { formula: `G${sumRowNum}/H${sumRowNum}` };
  sheet3.getCell(`C${lcoeRowNum+1}`).numFmt = '#,##0';
  sheet3.getCell(`C${lcoeRowNum+1}`).font = { bold: true, size: 12 };
  sheet3.getCell(`D${lcoeRowNum+1}`).value = 'PLN/MWh';
  sheet3.getCell(`E${lcoeRowNum+1}`).value = '= Σ Kosztów / Σ Produkcji';
  sheet3.getCell(`E${lcoeRowNum+1}`).font = { italic: true, color: { argb: 'FF666666' } };

  sheet3.getCell(`B${lcoeRowNum+2}`).value = 'LCOE Efektywne';
  sheet3.getCell(`C${lcoeRowNum+2}`).value = { formula: `G${sumRowNum}/I${sumRowNum}` };
  sheet3.getCell(`C${lcoeRowNum+2}`).numFmt = '#,##0';
  sheet3.getCell(`C${lcoeRowNum+2}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  sheet3.getCell(`D${lcoeRowNum+2}`).value = 'PLN/MWh';
  sheet3.getCell(`E${lcoeRowNum+2}`).value = '= Σ Kosztów / Σ Autokonsumpcji';
  sheet3.getCell(`E${lcoeRowNum+2}`).font = { italic: true, color: { argb: 'FF666666' } };

  sheet3.getCell(`B${lcoeRowNum+3}`).value = 'Marża LCOE';
  sheet3.getCell(`C${lcoeRowNum+3}`).value = { formula: `(C${lcoeRowNum+2}-C${lcoeRowNum+1})/C${lcoeRowNum+1}` };
  sheet3.getCell(`C${lcoeRowNum+3}`).numFmt = '0.0%';
  sheet3.getCell(`C${lcoeRowNum+3}`).font = { bold: true };
  sheet3.getCell(`E${lcoeRowNum+3}`).value = '= (LCOE_Eff - LCOE_Std) / LCOE_Std';
  sheet3.getCell(`E${lcoeRowNum+3}`).font = { italic: true, color: { argb: 'FF666666' } };

  sheet3.getCell(`B${lcoeRowNum+5}`).value = 'Porównanie z ceną sieci:';
  sheet3.getCell(`B${lcoeRowNum+5}`).font = { bold: true };
  sheet3.getCell(`C${lcoeRowNum+5}`).value = Math.round(gridPrice);
  sheet3.getCell(`D${lcoeRowNum+5}`).value = 'PLN/MWh';

  sheet3.getCell(`B${lcoeRowNum+6}`).value = 'Oszczędność na MWh:';
  sheet3.getCell(`C${lcoeRowNum+6}`).value = { formula: `C${lcoeRowNum+5}-C${lcoeRowNum+2}` };
  sheet3.getCell(`C${lcoeRowNum+6}`).numFmt = '#,##0';
  sheet3.getCell(`D${lcoeRowNum+6}`).value = 'PLN/MWh';

  // Generate filename and save
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  const projectName = window.parent?.sharedData?.currentProject?.name || 'Analiza';
  const filename = `${projectName}_LCOE_Analysis_${dateStr}.xlsx`;

  // Apply watermark
  if (window.applyExcelWatermark) {
    try { window.applyExcelWatermark(excelWorkbook, { visibleSheets: ['Podsumowanie LCOE'] }); }
    catch (e) { console.warn('⚠️ Watermark:', e); }
  }

  // Write file using ExcelJS
  const buffer = await excelWorkbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);

  console.log(`📥 Exported LCOE analysis to ${filename}`);
}

// Expose export function globally
window.exportVariantScanToExcel = exportVariantScanToExcel;

// ============================================================================
// CAPACITY FEE K-CLASS ANALYSIS WIDGET
// ============================================================================

/**
 * Toggle K-class details panel visibility
 */
function toggleKClassDetails() {
  const panel = document.getElementById('kclassDetailsPanel');
  const btn = document.getElementById('kclassToggleBtn');
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    btn.textContent = '▲ Ukryj';
  } else {
    panel.style.display = 'none';
    btn.textContent = '▼ Szczegóły';
  }
}
window.toggleKClassDetails = toggleKClassDetails;

/**
 * Calculate Easter Sunday for a given year (Anonymous Gregorian algorithm).
 */
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

/**
 * Get Polish public holidays for a given year (dynamic, works for any year).
 * Wigilia (Dec 24) only from 2025 (Dz.U. 2024 poz. 1911).
 */
const _economicsHolidayCache = {};
function _getPolishHolidays(year) {
  if (_economicsHolidayCache[year]) return _economicsHolidayCache[year];
  const easter = _getEasterDate(year);
  const easterMs = easter.getTime();
  const oneDay = 86400000;
  const dates = [
    new Date(year, 0, 1),             // Nowy Rok
    new Date(year, 0, 6),             // Trzech Króli
    easter,                            // Wielkanoc (Niedziela)
    new Date(easterMs + oneDay),       // Poniedziałek Wielkanocny
    new Date(year, 4, 1),             // Święto Pracy
    new Date(year, 4, 3),             // Święto Konstytucji
    new Date(easterMs + 49 * oneDay), // Zielone Świątki
    new Date(easterMs + 60 * oneDay), // Boże Ciało
    new Date(year, 7, 15),            // Wniebowzięcie NMP
    new Date(year, 10, 1),            // Wszystkich Świętych
    new Date(year, 10, 11),           // Święto Niepodległości
    new Date(year, 11, 25),           // Boże Narodzenie 1
    new Date(year, 11, 26),           // Boże Narodzenie 2
  ];
  // Wigilia — only from 2025
  if (year >= 2025) {
    dates.push(new Date(year, 11, 24));
  }
  const set = new Set(dates.map(d => {
    const yy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yy}-${mm}-${dd}`;
  }));
  _economicsHolidayCache[year] = set;
  return set;
}

/**
 * Check if a date is a Polish workday (Mon-Fri, not a holiday).
 * Dynamic — works for any year.
 */
function isPolishWorkday(date) {
  const dayOfWeek = date.getDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) return false;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return !_getPolishHolidays(y).has(`${y}-${m}-${d}`);
}

/**
 * Get K-class from delta_s percentage
 */
function getKClassFromDeltaS(deltaS) {
  // Progi K-class (spójne z consumption.js, settings.js, backend calculator.py)
  if (deltaS < 5) return { klass: 'K1', coeff: 0.17, color: '#4caf50' };
  if (deltaS < 10) return { klass: 'K2', coeff: 0.50, color: '#8bc34a' };
  if (deltaS < 15) return { klass: 'K3', coeff: 0.83, color: '#ff9800' };
  return { klass: 'K4', coeff: 1.00, color: '#f44336' };
}

/**
 * Calculate K-class analysis from hourly consumption and PV data
 * @param {number[]} loadHourly - Hourly consumption profile (8760 values) [kWh]
 * @param {number[]} pvHourly - Hourly PV generation profile (8760 values) [kWh]
 * @param {number} year - Analysis year
 * @param {number} somPLNperKWh - SOM rate [PLN/kWh], default 0.2194
 * @returns {Object} K-class analysis results
 */
function calculateKClassAnalysis(loadHourly, pvHourly, year = 2025, somPLNperKWh = 0.2194) {
  console.log('⚡ Calculating K-class analysis...');

  if (!loadHourly || loadHourly.length < 8760) {
    console.warn('K-class: Need 8760 hourly load values');
    return null;
  }

  // Calculate grid import (with and without PV)
  const gridImportWithoutPV = [...loadHourly];
  const gridImportWithPV = loadHourly.map((load, i) => {
    const pv = pvHourly && pvHourly[i] ? pvHourly[i] : 0;
    return Math.max(0, load - pv);
  });

  // Create time index
  const startDate = new Date(year, 0, 1, 0, 0, 0);

  // Analyze each day
  const dailyResultsBefore = [];
  const dailyResultsAfter = [];

  for (let dayOfYear = 0; dayOfYear < 365; dayOfYear++) {
    const dayStart = new Date(startDate.getTime() + dayOfYear * 24 * 60 * 60 * 1000);

    // Skip non-workdays
    if (!isPolishWorkday(dayStart)) continue;

    const hourOffset = dayOfYear * 24;

    // Get selected hours (7:00-21:59) and outside hours for this day
    let zsBeforePV = 0, zpsBeforePV = 0;
    let zsAfterPV = 0, zpsAfterPV = 0;
    let nSelected = 0, nOutside = 0;

    for (let hour = 0; hour < 24; hour++) {
      const idx = hourOffset + hour;
      if (idx >= gridImportWithoutPV.length) break;

      const isSelected = hour >= 7 && hour < 22; // 7:00-21:59

      if (isSelected) {
        zsBeforePV += gridImportWithoutPV[idx];
        zsAfterPV += gridImportWithPV[idx];
        nSelected++;
      } else {
        zpsBeforePV += gridImportWithoutPV[idx];
        zpsAfterPV += gridImportWithPV[idx];
        nOutside++;
      }
    }

    // Calculate Δs for before PV
    if (zpsBeforePV > 0 && nSelected > 0 && nOutside > 0) {
      const avgS = zsBeforePV / nSelected;
      const avgPS = zpsBeforePV / nOutside;
      const deltaS = (avgS / avgPS - 1) * 100;
      const kInfo = getKClassFromDeltaS(deltaS);
      const fee = kInfo.coeff * somPLNperKWh * zsBeforePV;
      dailyResultsBefore.push({
        date: dayStart,
        deltaS,
        klass: kInfo.klass,
        coeff: kInfo.coeff,
        zs: zsBeforePV,
        fee
      });
    }

    // Calculate Δs for after PV
    if (nSelected > 0 && nOutside > 0) {
      const avgS = zsAfterPV / nSelected;
      const avgPS = zpsAfterPV / nOutside;
      // When outside hours have zero grid import, Δs = 0 → K2 (per backend convention)
      const deltaS = avgPS > 0 ? (avgS / avgPS - 1) * 100 : 0;
      const kInfo = getKClassFromDeltaS(deltaS);
      const fee = kInfo.coeff * somPLNperKWh * zsAfterPV;
      dailyResultsAfter.push({
        date: dayStart,
        deltaS,
        klass: kInfo.klass,
        coeff: kInfo.coeff,
        zs: zsAfterPV,
        fee
      });
    }
  }

  // Aggregate results
  const histogramBefore = { K1: 0, K2: 0, K3: 0, K4: 0 };
  const histogramAfter = { K1: 0, K2: 0, K3: 0, K4: 0 };

  let totalFeeBefore = 0, totalFeeAfter = 0;
  let avgDeltaSBefore = 0, avgDeltaSAfter = 0;

  dailyResultsBefore.forEach(d => {
    histogramBefore[d.klass]++;
    totalFeeBefore += d.fee;
    avgDeltaSBefore += d.deltaS;
  });
  avgDeltaSBefore /= dailyResultsBefore.length || 1;

  dailyResultsAfter.forEach(d => {
    histogramAfter[d.klass]++;
    totalFeeAfter += d.fee;
    avgDeltaSAfter += d.deltaS;
  });
  avgDeltaSAfter /= dailyResultsAfter.length || 1;

  // Determine dominant K-class
  const getDominantK = (hist) => {
    let maxCount = 0, dominant = 'K4';
    for (const [k, count] of Object.entries(hist)) {
      if (count > maxCount) {
        maxCount = count;
        dominant = k;
      }
    }
    return dominant;
  };

  const dominantKBefore = getDominantK(histogramBefore);
  const dominantKAfter = getDominantK(histogramAfter);

  const savings = totalFeeBefore - totalFeeAfter;
  const savingsPct = totalFeeBefore > 0 ? decimalToPct(savings / totalFeeBefore) : 0;

  // Calculate total ZS before and after
  const totalZsBefore = dailyResultsBefore.reduce((sum, d) => sum + d.zs, 0);
  const totalZsAfter = dailyResultsAfter.reduce((sum, d) => sum + d.zs, 0);

  // Calculate the TWO effects separately:
  // Effect 1: ZS Reduction - what would savings be if K-class stayed the same?
  // Effect 2: K-class improvement - additional savings from better K-class

  // For Effect 1: Calculate fee "after" using BEFORE k-class but AFTER ZS
  // This isolates the pure ZS reduction effect
  let feeWithSameKclass = 0;
  let daysImproved = 0;
  const dailyComparison = [];

  for (let i = 0; i < dailyResultsBefore.length; i++) {
    const before = dailyResultsBefore[i];
    const after = dailyResultsAfter[i];
    if (!after) continue;

    // Fee if we kept the same K-class but used new (lower) ZS
    const feeWithOldKclass = before.coeff * somPLNperKWh * after.zs;
    feeWithSameKclass += feeWithOldKclass;

    // Track K-class improvements
    const kOrder = { K1: 1, K2: 2, K3: 3, K4: 4 };
    if (kOrder[after.klass] < kOrder[before.klass]) {
      daysImproved++;
    }

    // Store for Excel export
    dailyComparison.push({
      date: before.date,
      zsBefore: before.zs,
      zsAfter: after.zs,
      klassBefore: before.klass,
      klassAfter: after.klass,
      coeffBefore: before.coeff,
      coeffAfter: after.coeff,
      deltaSBefore: before.deltaS,
      deltaSAfter: after.deltaS,
      feeBefore: before.fee,
      feeAfter: after.fee,
      feeWithOldKclass: feeWithOldKclass
    });
  }

  // Effect 1: Pure ZS reduction (using same K-class)
  const savingsFromZsReduction = totalFeeBefore - feeWithSameKclass;

  // Effect 2: K-class improvement (difference between actual fee and fee with old K-class)
  const savingsFromKclassImprovement = feeWithSameKclass - totalFeeAfter;

  console.log(`⚡ K-class: Before=${dominantKBefore} (Δs=${avgDeltaSBefore.toFixed(1)}%), After=${dominantKAfter} (Δs=${avgDeltaSAfter.toFixed(1)}%)`);
  console.log(`⚡ K-class: Fee before=${totalFeeBefore.toFixed(0)} PLN, after=${totalFeeAfter.toFixed(0)} PLN, savings=${savings.toFixed(0)} PLN`);
  console.log(`⚡ K-class: ZS reduction effect: ${savingsFromZsReduction.toFixed(0)} PLN, K-class improvement: ${savingsFromKclassImprovement.toFixed(0)} PLN`);
  console.log(`⚡ K-class: Days with K-class improvement: ${daysImproved}`);

  // Calculate average hourly profile for chart
  const hourlyProfileBefore = new Array(24).fill(0);
  const hourlyProfileAfter = new Array(24).fill(0);
  const hourlyCount = new Array(24).fill(0);

  for (let dayOfYear = 0; dayOfYear < 365; dayOfYear++) {
    const dayStart = new Date(startDate.getTime() + dayOfYear * 24 * 60 * 60 * 1000);
    if (!isPolishWorkday(dayStart)) continue;

    const hourOffset = dayOfYear * 24;
    for (let hour = 0; hour < 24; hour++) {
      const idx = hourOffset + hour;
      if (idx >= gridImportWithoutPV.length) break;
      hourlyProfileBefore[hour] += gridImportWithoutPV[idx];
      hourlyProfileAfter[hour] += gridImportWithPV[idx];
      hourlyCount[hour]++;
    }
  }

  // Calculate averages
  for (let hour = 0; hour < 24; hour++) {
    if (hourlyCount[hour] > 0) {
      hourlyProfileBefore[hour] /= hourlyCount[hour];
      hourlyProfileAfter[hour] /= hourlyCount[hour];
    }
  }

  // Calculate average peak and off-peak consumption
  let avgPeakBefore = 0, avgPeakAfter = 0, peakCount = 0;
  let avgOffpeakBefore = 0, avgOffpeakAfter = 0, offpeakCount = 0;

  for (let hour = 0; hour < 24; hour++) {
    if (hour >= 7 && hour < 22) {
      avgPeakBefore += hourlyProfileBefore[hour];
      avgPeakAfter += hourlyProfileAfter[hour];
      peakCount++;
    } else {
      avgOffpeakBefore += hourlyProfileBefore[hour];
      avgOffpeakAfter += hourlyProfileAfter[hour];
      offpeakCount++;
    }
  }
  avgPeakBefore /= peakCount || 1;
  avgPeakAfter /= peakCount || 1;
  avgOffpeakBefore /= offpeakCount || 1;
  avgOffpeakAfter /= offpeakCount || 1;

  // Calculate flatness coefficient (1.0 = perfectly flat)
  const flatnessBefore = avgOffpeakBefore > 0 ? Math.min(avgOffpeakBefore / avgPeakBefore, avgPeakBefore / avgOffpeakBefore) : 0;
  const flatnessAfter = avgOffpeakAfter > 0 ? Math.min(avgOffpeakAfter / avgPeakAfter, avgPeakAfter / avgOffpeakAfter) : 0;

  // Calculate monthly savings for chart
  const monthlySavings = [];
  for (let month = 1; month <= 12; month++) {
    const monthDays = dailyComparison.filter(d => d.date.getMonth() + 1 === month);
    const monthFeeBefore = monthDays.reduce((sum, d) => sum + d.feeBefore, 0);
    const monthFeeAfter = monthDays.reduce((sum, d) => sum + d.feeAfter, 0);
    monthlySavings.push({
      month,
      feeBefore: monthFeeBefore,
      feeAfter: monthFeeAfter,
      savings: monthFeeBefore - monthFeeAfter
    });
  }

  return {
    before: {
      dominantK: dominantKBefore,
      avgDeltaS: avgDeltaSBefore,
      histogram: histogramBefore,
      totalFee: totalFeeBefore,
      totalZs: totalZsBefore,
      workdays: dailyResultsBefore.length,
      avgPeak: avgPeakBefore,
      avgOffpeak: avgOffpeakBefore
    },
    after: {
      dominantK: dominantKAfter,
      avgDeltaS: avgDeltaSAfter,
      histogram: histogramAfter,
      totalFee: totalFeeAfter,
      totalZs: totalZsAfter,
      workdays: dailyResultsAfter.length,
      avgPeak: avgPeakAfter,
      avgOffpeak: avgOffpeakAfter
    },
    savings: {
      pln: savings,
      pct: savingsPct,
      fromZsReduction: savingsFromZsReduction,
      fromKclassImprovement: savingsFromKclassImprovement,
      daysImproved: daysImproved
    },
    dailyComparison: dailyComparison,
    monthlySavings: monthlySavings,
    hourlyProfile: {
      before: hourlyProfileBefore,
      after: hourlyProfileAfter
    },
    flatness: {
      before: flatnessBefore,
      after: flatnessAfter
    },
    somPLNperKWh: somPLNperKWh
  };
}

/**
 * Update K-class widget UI with analysis results
 */
function updateKClassWidget(analysis) {
  if (!analysis) {
    document.getElementById('capacityFeeKClassSection').style.display = 'none';
    return;
  }

  const section = document.getElementById('capacityFeeKClassSection');
  section.style.display = 'block';

  // Get color for K-class
  const getKColor = (k) => {
    switch(k) {
      case 'K1': return '#4caf50';
      case 'K2': return '#8bc34a';
      case 'K3': return '#ff9800';
      default: return '#f44336';
    }
  };

  const getCoeff = (k) => {
    switch(k) {
      case 'K1': return 0.17;
      case 'K2': return 0.50;
      case 'K3': return 0.83;
      default: return 1.00;
    }
  };

  // Update summary cards
  document.getElementById('kclassBeforePV').textContent = analysis.before.dominantK;
  document.getElementById('kclassBeforePV').style.color = getKColor(analysis.before.dominantK);

  document.getElementById('kclassAfterPV').textContent = analysis.after.dominantK;
  document.getElementById('kclassAfterPV').style.color = getKColor(analysis.after.dominantK);
  document.getElementById('kclassAfterCoeff').textContent = `A = ${getCoeff(analysis.after.dominantK).toFixed(2)}`;

  const formatDeltaS = (val) => (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
  document.getElementById('deltaSBefore').textContent = formatDeltaS(analysis.before.avgDeltaS);
  document.getElementById('deltaSAfter').textContent = formatDeltaS(analysis.after.avgDeltaS);

  // Color Δs based on value
  const deltaSBeforeEl = document.getElementById('deltaSBefore');
  const deltaSAfterEl = document.getElementById('deltaSAfter');
  deltaSBeforeEl.style.color = analysis.before.avgDeltaS >= 15 ? '#f44336' : (analysis.before.avgDeltaS >= 10 ? '#ff9800' : '#43a047');
  deltaSAfterEl.style.color = analysis.after.avgDeltaS >= 15 ? '#f44336' : (analysis.after.avgDeltaS >= 10 ? '#ff9800' : '#43a047');

  // Update savings
  const fmt = (val) => val.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  document.getElementById('kclassSavings').textContent = fmt(analysis.savings.pln) + ' PLN';
  document.getElementById('kclassSavingsPct').textContent = `(-${analysis.savings.pct.toFixed(0)}% vs bez PV)`;

  // Update ZS values
  const fmtZs = (val) => (val / 1000).toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  const kclassZsBeforeEl = document.getElementById('kclassZsBefore');
  const kclassZsAfterEl = document.getElementById('kclassZsAfter');
  if (kclassZsBeforeEl) kclassZsBeforeEl.textContent = fmtZs(analysis.before.totalZs);
  if (kclassZsAfterEl) kclassZsAfterEl.textContent = fmtZs(analysis.after.totalZs);

  // Update effect 1: ZS reduction
  const savingsZsEl = document.getElementById('kclassSavingsZs');
  const savingsZsPctEl = document.getElementById('kclassSavingsZsPct');
  if (savingsZsEl) {
    savingsZsEl.textContent = fmt(analysis.savings.fromZsReduction) + ' PLN';
    const zsReductionPct = analysis.before.totalZs > 0
      ? decimalToPct((analysis.before.totalZs - analysis.after.totalZs) / analysis.before.totalZs)
      : 0;
    savingsZsPctEl.textContent = `(ZS -${zsReductionPct.toFixed(0)}%)`;
  }

  // Update effect 2: K-class improvement
  const savingsKclassEl = document.getElementById('kclassSavingsKclass');
  const savingsKclassPctEl = document.getElementById('kclassSavingsKclassPct');
  const daysImprovedEl = document.getElementById('kclassDaysImproved');
  if (savingsKclassEl) {
    savingsKclassEl.textContent = fmt(analysis.savings.fromKclassImprovement) + ' PLN';
    const kclassEffectPct = analysis.savings.pln > 0
      ? decimalToPct(analysis.savings.fromKclassImprovement / analysis.savings.pln)
      : 0;
    savingsKclassPctEl.textContent = `(${kclassEffectPct.toFixed(0)}% całości)`;
  }
  if (daysImprovedEl) {
    daysImprovedEl.textContent = analysis.savings.daysImproved;
  }

  // Update fee values
  const feeBeforeEl = document.getElementById('kclassFeeBefore');
  const feeAfterEl = document.getElementById('kclassFeeAfter');
  if (feeBeforeEl) feeBeforeEl.textContent = fmt(analysis.before.totalFee);
  if (feeAfterEl) feeAfterEl.textContent = fmt(analysis.after.totalFee);

  // Store analysis globally for Excel export
  window.lastKClassAnalysis = analysis;

  // Update histograms
  const renderHistogram = (containerId, histogram, workdays) => {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    const colors = { K1: '#4caf50', K2: '#8bc34a', K3: '#ff9800', K4: '#f44336' };
    const total = workdays || Object.values(histogram).reduce((a, b) => a + b, 0);

    ['K1', 'K2', 'K3', 'K4'].forEach(k => {
      const count = histogram[k] || 0;
      const pct = total > 0 ? decimalToPct(count / total) : 0;
      const bar = document.createElement('div');
      bar.style.cssText = 'display:flex;align-items:center;gap:8px;';
      bar.innerHTML = `
        <span style="width:24px;font-weight:600;color:${colors[k]};font-size:12px;">${k}</span>
        <div style="flex:1;height:16px;background:#eee;border-radius:4px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${colors[k]};border-radius:4px;transition:width 0.3s;"></div>
        </div>
        <span style="width:50px;font-size:11px;color:#666;text-align:right;">${count} dni</span>
        <span style="width:40px;font-size:11px;color:#999;text-align:right;">${pct.toFixed(0)}%</span>
      `;
      container.appendChild(bar);
    });
  };

  renderHistogram('kclassHistBefore', analysis.before.histogram, analysis.before.workdays);
  renderHistogram('kclassHistAfter', analysis.after.histogram, analysis.after.workdays);

  // Update additional analytics
  const fmtKw = (val) => val.toLocaleString('pl-PL', { maximumFractionDigits: 1 });
  const avgPeakBeforeEl = document.getElementById('kclassAvgPeakBefore');
  const avgPeakAfterEl = document.getElementById('kclassAvgPeakAfter');
  const avgOffpeakBeforeEl = document.getElementById('kclassAvgOffpeakBefore');
  const avgOffpeakAfterEl = document.getElementById('kclassAvgOffpeakAfter');
  const flatnessBeforeEl = document.getElementById('kclassFlatnessBefore');
  const flatnessAfterEl = document.getElementById('kclassFlatnessAfter');

  if (avgPeakBeforeEl) avgPeakBeforeEl.textContent = fmtKw(analysis.before.avgPeak);
  if (avgPeakAfterEl) avgPeakAfterEl.textContent = fmtKw(analysis.after.avgPeak);
  if (avgOffpeakBeforeEl) avgOffpeakBeforeEl.textContent = fmtKw(analysis.before.avgOffpeak);
  if (avgOffpeakAfterEl) avgOffpeakAfterEl.textContent = fmtKw(analysis.after.avgOffpeak);
  if (flatnessBeforeEl) flatnessBeforeEl.textContent = analysis.flatness.before.toFixed(2);
  if (flatnessAfterEl) flatnessAfterEl.textContent = analysis.flatness.after.toFixed(2);

  // Render profile chart
  renderKClassProfileChart(analysis);

  // Render monthly chart
  renderKClassMonthlyChart(analysis);
}

// Global chart instances for cleanup
let kclassProfileChartInstance = null;
let kclassMonthlyChartInstance = null;

/**
 * Render the daily profile chart showing before/after PV curves
 */
function renderKClassProfileChart(analysis) {
  const canvas = document.getElementById('kclassProfileChart');
  if (!canvas || !analysis.hourlyProfile) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing chart
  if (kclassProfileChartInstance) {
    kclassProfileChartInstance.destroy();
  }

  const hours = Array.from({length: 24}, (_, i) => `${i}:00`);

  // Create background highlight for selected hours (7-22) as a separate bar dataset
  const maxVal = Math.max(...analysis.hourlyProfile.before, ...analysis.hourlyProfile.after) * 1.15;
  const selectedHoursBackground = hours.map((_, i) => (i >= 7 && i < 22) ? maxVal : 0);

  kclassProfileChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: hours,
      datasets: [
        {
          label: 'Godz. wybrane (7-22)',
          data: selectedHoursBackground,
          type: 'bar',
          backgroundColor: 'rgba(255, 193, 7, 0.15)',
          borderWidth: 0,
          barPercentage: 1.0,
          categoryPercentage: 1.0,
          order: 3
        },
        {
          label: 'Bez PV (zużycie)',
          data: analysis.hourlyProfile.before,
          borderColor: '#f44336',
          backgroundColor: 'transparent',
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          order: 1
        },
        {
          label: 'Z PV (pobór z sieci)',
          data: analysis.hourlyProfile.after,
          borderColor: '#4caf50',
          backgroundColor: 'transparent',
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          order: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index'
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          filter: function(tooltipItem) {
            return tooltipItem.dataset.label !== 'Godz. wybrane (7-22)';
          },
          callbacks: {
            label: function(context) {
              return `${context.dataset.label}: ${context.parsed.y.toFixed(1)} kW`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            font: { size: 9 },
            callback: function(val, index) {
              return index % 3 === 0 ? this.getLabelForValue(val) : '';
            }
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(0,0,0,0.05)'
          },
          ticks: {
            font: { size: 10 },
            callback: function(val) {
              return val.toFixed(0) + ' kW';
            }
          }
        }
      }
    }
  });
}

/**
 * Render the monthly savings chart
 */
function renderKClassMonthlyChart(analysis) {
  const canvas = document.getElementById('kclassMonthlyChart');
  if (!canvas || !analysis.monthlySavings) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing chart
  if (kclassMonthlyChartInstance) {
    kclassMonthlyChartInstance.destroy();
  }

  const months = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];

  kclassMonthlyChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months,
      datasets: [
        {
          label: 'Oszczędność',
          data: analysis.monthlySavings.map(m => m.savings),
          backgroundColor: '#4caf50',
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `Oszczędność: ${context.parsed.y.toLocaleString('pl-PL', {maximumFractionDigits: 0})} PLN`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            font: { size: 9 }
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(0,0,0,0.05)'
          },
          ticks: {
            font: { size: 9 },
            callback: function(val) {
              return val.toLocaleString('pl-PL') + ' PLN';
            }
          }
        }
      }
    }
  });
}

/**
 * Initialize K-class analysis when data is available
 * Called from main calculation flow
 */
async function initKClassAnalysis() {
  try {
    const state = window.economicsState || {};

    // Get hourly load profile
    let loadHourly = state.hourlyConsumption;
    if (!loadHourly && state.annualConsumption) {
      // Generate flat profile if no hourly data
      loadHourly = new Array(8760).fill(state.annualConsumption / 8760);
    }

    // Get hourly PV profile
    let pvHourly = state.hourlyPV;
    if (!pvHourly && state.pvPower && state.annualProduction) {
      // Use simple approximation if no hourly data
      pvHourly = new Array(8760).fill(0);
      // Basic solar curve
      for (let day = 0; day < 365; day++) {
        for (let hour = 0; hour < 24; hour++) {
          const idx = day * 24 + hour;
          if (hour >= 6 && hour <= 20) {
            // Simple bell curve for PV
            const solarFactor = Math.sin(Math.PI * (hour - 6) / 14);
            pvHourly[idx] = (state.annualProduction / 8760) * 3 * solarFactor;
          }
        }
      }
    }

    if (!loadHourly) {
      console.log('⚡ K-class: No load data available');
      document.getElementById('capacityFeeKClassSection').style.display = 'none';
      return;
    }

    const dataYear = cachedHourlyConsumption?.timestamps?.[0]
      ? new Date(cachedHourlyConsumption.timestamps[0]).getFullYear() : 2025;
    const analysis = calculateKClassAnalysis(loadHourly, pvHourly, dataYear, 0.2194);
    updateKClassWidget(analysis);

  } catch (e) {
    console.error('⚡ K-class analysis error:', e);
    document.getElementById('capacityFeeKClassSection').style.display = 'none';
  }
}
window.initKClassAnalysis = initKClassAnalysis;

/**
 * Initialize K-class analysis using cached hourly data from PULS DNIA
 * This is called from the main display function
 */
async function initKClassAnalysisFromData() {
  try {
    console.log('⚡ K-class: Initializing from cached data...');

    // Try to get cached hourly data (from PULS DNIA)
    let loadHourly = null;
    let pvHourly = null;

    // Check if we have cached data from fetchRealHourlyData
    if (typeof cachedHourlyConsumption !== 'undefined' && cachedHourlyConsumption?.values) {
      loadHourly = cachedHourlyConsumption.values;
      console.log(`⚡ K-class: Found cached consumption data (${loadHourly.length} points)`);
    }

    if (typeof cachedHourlyProduction !== 'undefined' && cachedHourlyProduction?.values) {
      pvHourly = cachedHourlyProduction.values;
      console.log(`⚡ K-class: Found cached production data (${pvHourly.length} points)`);
    }

    // If no cached data, try to fetch it
    if (!loadHourly) {
      console.log('⚡ K-class: No cached data, trying to fetch...');
      try {
        const apiData = await fetchRealHourlyData();
        if (apiData?.consumption?.values) {
          loadHourly = apiData.consumption.values;
        }
        if (apiData?.production?.values) {
          pvHourly = apiData.production.values;
        }
      } catch (e) {
        console.log('⚡ K-class: Could not fetch hourly data:', e.message);
      }
    }

    // If still no data, try to get from variant
    if (!loadHourly) {
      const variant = variants[currentVariant];
      const annualConsumption = getAnnualConsumptionKwh();

      if (annualConsumption > 0) {
        console.log(`⚡ K-class: Using flat profile from annual consumption (${annualConsumption} kWh)`);
        // Generate a typical commercial profile (higher during work hours)
        loadHourly = new Array(8760).fill(0);
        for (let day = 0; day < 365; day++) {
          for (let hour = 0; hour < 24; hour++) {
            const idx = day * 24 + hour;
            // Commercial profile: higher 7-18, lower at night
            let factor = 0.5; // night baseline
            if (hour >= 7 && hour < 18) {
              factor = 1.5; // daytime peak
            } else if (hour >= 18 && hour < 22) {
              factor = 0.8; // evening
            }
            loadHourly[idx] = (annualConsumption / 8760) * factor;
          }
        }
      }
    }

    // If still no PV data, generate synthetic from variant
    if (!pvHourly) {
      const variant = variants[currentVariant];
      if (variant?.production > 0) {
        const annualProduction = variant.production; // kWh
        console.log(`⚡ K-class: Generating synthetic PV profile (${annualProduction} kWh/year)`);

        pvHourly = new Array(8760).fill(0);
        for (let day = 0; day < 365; day++) {
          // Seasonal factor (higher in summer)
          const dayOfYear = day;
          const seasonalFactor = 0.6 + 0.4 * Math.sin(2 * Math.PI * (dayOfYear - 80) / 365);

          for (let hour = 0; hour < 24; hour++) {
            const idx = day * 24 + hour;
            if (hour >= 6 && hour <= 20) {
              // Solar curve with seasonal adjustment
              const solarFactor = Math.sin(Math.PI * (hour - 6) / 14);
              pvHourly[idx] = (annualProduction / 8760) * 2.5 * solarFactor * seasonalFactor;
            }
          }
        }
      }
    }

    if (!loadHourly || loadHourly.length < 8760) {
      console.log('⚡ K-class: Insufficient load data, hiding widget');
      const section = document.getElementById('capacityFeeKClassSection');
      if (section) section.style.display = 'none';
      return;
    }

    // Ensure arrays are exactly 8760 (pad or trim)
    if (loadHourly.length > 8760) loadHourly = loadHourly.slice(0, 8760);
    if (pvHourly && pvHourly.length > 8760) pvHourly = pvHourly.slice(0, 8760);

    // Get SOM rate from parameters
    const params = typeof getEconomicParameters === 'function' ? getEconomicParameters() : {};
    const somPLNperKWh = (params.capacity_fee || 219) / 1000; // Convert PLN/MWh to PLN/kWh

    // Calculate K-class analysis
    const dataYear2 = cachedHourlyConsumption?.timestamps?.[0]
      ? new Date(cachedHourlyConsumption.timestamps[0]).getFullYear() : 2025;
    const analysis = calculateKClassAnalysis(loadHourly, pvHourly, dataYear2, somPLNperKWh);
    updateKClassWidget(analysis);

  } catch (e) {
    console.error('⚡ K-class analysis error:', e);
    const section = document.getElementById('capacityFeeKClassSection');
    if (section) section.style.display = 'none';
  }
}
window.initKClassAnalysisFromData = initKClassAnalysisFromData;

/**
 * Export K-class analysis to Excel with full formulas
 */
async function exportKClassToExcel() {
  const analysis = window.lastKClassAnalysis;
  if (!analysis || !analysis.dailyComparison || analysis.dailyComparison.length === 0) {
    alert('Brak danych do eksportu. Uruchom najpierw analizę.');
    return;
  }

  console.log('📥 Exporting K-class analysis to Excel...');

  // Check if ExcelJS is available
  if (typeof ExcelJS === 'undefined') {
    alert('Biblioteka ExcelJS nie jest załadowana. Eksport niedostępny.');
    return;
  }

  const workbook = new ExcelJS.Workbook();

  // Precompute Sheet 2 row references for cross-sheet formulas
  const numDays = analysis.dailyComparison.length;
  const dailyDataLastRow = numDays + 1;  // header row 1, data rows 2..numDays+1
  const dailyTotalRow = numDays + 2;     // totals row

  // Load and add logo image
  let logoImageId = null;
  try {
    const logoResponse = await fetch('logo.png');
    if (logoResponse.ok) {
      const logoBlob = await logoResponse.blob();
      const logoBase64 = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.readAsDataURL(logoBlob);
      });
      logoImageId = workbook.addImage({ base64: logoBase64, extension: 'png' });
    }
  } catch (e) {
    console.warn('⚠️ Could not load logo:', e);
  }

  // Polish number format helper
  const plNum = (val, decimals = 2) => {
    if (typeof val !== 'number') return val;
    return parseFloat(val.toFixed(decimals));
  };

  // Number format styles
  const numFmt2 = '#,##0.00';
  const numFmt0 = '#,##0';

  // ==========================================
  // SHEET 1: PODSUMOWANIE (with margin col A)
  // ==========================================
  const summarySheet = workbook.addWorksheet('Podsumowanie');
  summarySheet.columns = [
    { width: 3 },   // A: margin
    { width: 35 },  // B: labels
    { width: 20 },  // C: value 1
    { width: 20 },  // D: value 2
    { width: 45 }   // E: description
  ];
  summarySheet.views = [{ state: 'frozen', ySplit: 2, showGridLines: false, showRowColHeaders: false }];

  // Logo
  if (logoImageId !== null) {
    summarySheet.addImage(logoImageId, {
      tl: { col: 1.3, row: 0.1 },
      ext: { width: 200, height: 50 }
    });
  }

  // Title
  summarySheet.getRow(1).height = 20;
  summarySheet.getRow(2).height = 20;
  summarySheet.mergeCells('B1:F1');
  summarySheet.getCell('B1').value = 'ANALIZA KLASY K - OPŁATA MOCOWA';
  summarySheet.getCell('B1').font = { bold: true, size: 16, color: { argb: 'FF6A1B9A' } };
  summarySheet.getCell('B1').alignment = { horizontal: 'center', vertical: 'bottom' };

  summarySheet.getCell('B3').value = 'Wygenerowano:';
  summarySheet.getCell('C3').value = new Date().toLocaleString('pl-PL');

  // Parameters — C6 holds SOM value (cross-sheet ref target)
  summarySheet.getCell('B5').value = 'PARAMETRY';
  summarySheet.getCell('B5').font = { bold: true };
  summarySheet.getCell('B6').value = 'Stawka SOM [PLN/kWh]:';
  summarySheet.getCell('C6').value = analysis.somPLNperKWh;
  summarySheet.getCell('C6').numFmt = numFmt2;
  summarySheet.getCell('C6').note = 'Stawka Opłaty Mocowej\nPobierana z ustawień taryfy';
  summarySheet.getCell('B7').value = 'Dni robocze w roku:';
  summarySheet.getCell('C7').value = analysis.before.workdays;

  // Before/After comparison
  summarySheet.getCell('B9').value = 'PORÓWNANIE';
  summarySheet.getCell('B9').font = { bold: true };

  const compRow = summarySheet.getRow(11);
  ['', '', 'Bez PV', 'Z PV', 'Różnica'].forEach((v, i) => compRow.getCell(i + 1).value = v);
  compRow.font = { bold: true };
  compRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8E8E8' } };

  // Row 12: Dominant K-class
  const row12 = summarySheet.getRow(12);
  row12.getCell(2).value = 'Dominująca klasa K';
  row12.getCell(3).value = analysis.before.dominantK;
  row12.getCell(4).value = analysis.after.dominantK;

  // Row 13: Avg Δs — cross-sheet AVERAGE
  const row13 = summarySheet.getRow(13);
  row13.getCell(2).value = 'Średnie Δs [%]';
  row13.getCell(3).value = { formula: `AVERAGE('Dane dzienne'!K2:K${dailyDataLastRow})`, result: plNum(analysis.before.avgDeltaS, 1) };
  row13.getCell(4).value = { formula: `AVERAGE('Dane dzienne'!L2:L${dailyDataLastRow})`, result: plNum(analysis.after.avgDeltaS, 1) };
  row13.getCell(5).value = { formula: 'D13-C13', result: plNum(analysis.after.avgDeltaS - analysis.before.avgDeltaS, 1) };
  [3, 4, 5].forEach(c => row13.getCell(c).numFmt = numFmt2);
  row13.getCell(3).note = 'Δs = (śr_wybranych / śr_poza - 1) × 100%';

  // Row 14: ZS — cross-sheet total
  const row14 = summarySheet.getRow(14);
  row14.getCell(2).value = 'ZS - energia w godz. wybranych [kWh]';
  row14.getCell(3).value = { formula: `'Dane dzienne'!D${dailyTotalRow}`, result: plNum(analysis.before.totalZs, 0) };
  row14.getCell(4).value = { formula: `'Dane dzienne'!E${dailyTotalRow}`, result: plNum(analysis.after.totalZs, 0) };
  row14.getCell(5).value = { formula: 'D14-C14', result: plNum(analysis.after.totalZs - analysis.before.totalZs, 0) };
  [3, 4, 5].forEach(c => row14.getCell(c).numFmt = numFmt0);

  // Row 15: Opłata mocowa — cross-sheet total
  const row15 = summarySheet.getRow(15);
  row15.getCell(2).value = 'Opłata mocowa [PLN/rok]';
  row15.getCell(3).value = { formula: `'Dane dzienne'!M${dailyTotalRow}`, result: plNum(analysis.before.totalFee, 2) };
  row15.getCell(4).value = { formula: `'Dane dzienne'!N${dailyTotalRow}`, result: plNum(analysis.after.totalFee, 2) };
  row15.getCell(5).value = { formula: 'D15-C15', result: plNum(analysis.after.totalFee - analysis.before.totalFee, 2) };
  [3, 4, 5].forEach(c => row15.getCell(c).numFmt = numFmt2);
  row15.getCell(2).note = 'WOM = A × SOM × ZS\nA = współczynnik klasy K';

  // Effects breakdown
  summarySheet.getCell('B18').value = 'ROZKŁAD OSZCZĘDNOŚCI';
  summarySheet.getCell('B18').font = { bold: true };

  const effectRow = summarySheet.getRow(20);
  ['', 'Efekt', 'Oszczędność [PLN]', 'Udział [%]', 'Opis'].forEach((v, i) => effectRow.getCell(i + 1).value = v);
  effectRow.font = { bold: true };
  effectRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  // Row 21: Redukcja ZS — cross-sheet ref
  const row21 = summarySheet.getRow(21);
  row21.getCell(2).value = '1. Redukcja ZS';
  row21.getCell(3).value = { formula: `'Dane dzienne'!Q${dailyTotalRow}`, result: plNum(analysis.savings.fromZsReduction, 2) };
  row21.getCell(4).value = { formula: 'C21/$C$23*100' };
  row21.getCell(5).value = 'Mniejszy pobór z sieci w godz. 7-22 (PV produkuje)';
  row21.getCell(3).numFmt = numFmt2;
  row21.getCell(4).numFmt = numFmt2;
  row21.getCell(3).note = 'Opłata_przed - Opłata(stara_K)\nIle oszczędzamy z samej redukcji ZS';

  // Row 22: Poprawa klasy K — cross-sheet ref
  const row22 = summarySheet.getRow(22);
  row22.getCell(2).value = '2. Poprawa klasy K';
  row22.getCell(3).value = { formula: `'Dane dzienne'!R${dailyTotalRow}`, result: plNum(analysis.savings.fromKclassImprovement, 2) };
  row22.getCell(4).value = { formula: 'C22/$C$23*100' };
  row22.getCell(5).value = `Niższy współczynnik A w ${analysis.savings.daysImproved} dniach`;
  row22.getCell(3).numFmt = numFmt2;
  row22.getCell(4).numFmt = numFmt2;
  row22.getCell(3).note = 'Opłata(stara_K) - Opłata_po\nIle oszczędzamy z poprawy klasy';

  // Row 23: SUMA
  const row23 = summarySheet.getRow(23);
  row23.getCell(2).value = 'SUMA';
  row23.getCell(3).value = { formula: 'C21+C22', result: plNum(analysis.savings.fromZsReduction + analysis.savings.fromKclassImprovement, 2) };
  row23.getCell(4).value = 100;
  row23.getCell(3).numFmt = numFmt2;
  row23.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  row23.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF4CAF50' } };

  // K-class histogram
  summarySheet.getCell('B26').value = 'ROZKŁAD KLAS K';
  summarySheet.getCell('B26').font = { bold: true };

  const histRow = summarySheet.getRow(28);
  ['', 'Klasa', 'Współczynnik A', 'Dni (bez PV)', 'Dni (z PV)', 'Zmiana'].forEach((v, i) => histRow.getCell(i + 1).value = v);
  histRow.font = { bold: true };
  histRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  // Rows 29-32: K1-K4 with COUNTIF cross-sheet refs
  ['K1', 'K2', 'K3', 'K4'].forEach((k, i) => {
    const coeffs = { K1: 0.17, K2: 0.50, K3: 0.83, K4: 1.00 };
    const rn = 29 + i;
    const row = summarySheet.getRow(rn);
    row.getCell(2).value = k;
    row.getCell(3).value = coeffs[k];
    row.getCell(4).value = { formula: `COUNTIF('Dane dzienne'!G2:G${dailyDataLastRow},"${k}")`, result: analysis.before.histogram[k] || 0 };
    row.getCell(5).value = { formula: `COUNTIF('Dane dzienne'!H2:H${dailyDataLastRow},"${k}")`, result: analysis.after.histogram[k] || 0 };
    row.getCell(6).value = { formula: `E${rn}-D${rn}`, result: (analysis.after.histogram[k] || 0) - (analysis.before.histogram[k] || 0) };
  });

  // Formula explanation
  summarySheet.getCell('B35').value = 'WZORY OBLICZENIOWE';
  summarySheet.getCell('B35').font = { bold: true };
  summarySheet.getCell('B36').value = 'Opłata mocowa: WOM = A × SOM × ZS';
  summarySheet.getCell('B37').value = 'Δs = (śr_wybrane / śr_poza - 1) × 100%';
  summarySheet.getCell('B38').value = 'Klasa K: K1 (Δs < -10%), K2 (-10% do 10%), K3 (10% do 30%), K4 (≥ 30%)';

  // Print area
  summarySheet.pageSetup = { printArea: 'A1:F38', fitToPage: true, fitToWidth: 1, orientation: 'portrait' };

  // ==========================================
  // SHEET 2: DANE DZIENNE (with margin col A, formulas for fees)
  // ==========================================
  const dailySheet = workbook.addWorksheet('Dane dzienne');

  // Column widths: A=margin, B-R=data (D9)
  const dailyColWidths = [3, 12, 8, 14, 14, 14, 8, 8, 8, 8, 10, 10, 14, 14, 14, 14, 12, 12];
  dailyColWidths.forEach((w, i) => dailySheet.getColumn(i + 1).width = w);

  dailySheet.views = [{ state: 'frozen', ySplit: 1, showGridLines: false, showRowColHeaders: false }];

  // SOM cross-sheet ref for fee formulas: cell C6 on Podsumowanie sheet
  const somRef = "'Podsumowanie'!$C$6";

  // Header row 1 — via getRow (same pattern as CAPEX export)
  const dailyHeaders = [
    '', 'Data', 'Dzień tyg.',
    'ZS przed [kWh]', 'ZS po [kWh]', 'Redukcja ZS [kWh]',
    'Klasa przed', 'Klasa po', 'A przed', 'A po',
    'Δs przed [%]', 'Δs po [%]',
    'Opłata przed [PLN]', 'Opłata po [PLN]', 'Oszczędność [PLN]',
    'Opłata (stara K) [PLN]', 'Efekt ZS [PLN]', 'Efekt K [PLN]'
  ];
  const hdrRow = dailySheet.getRow(1);
  dailyHeaders.forEach((h, i) => { hdrRow.getCell(i + 1).value = h; });
  hdrRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  hdrRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF6A1B9A' } };
  hdrRow.getCell(16).note = 'A_przed × SOM × ZS_po\nHipotetyczna opłata gdyby klasa K się nie zmieniła';

  // Data rows — ALL cells via getRow().getCell() (proven ExcelJS pattern from CAPEX)
  const dayNames = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So'];
  const kColors = { K1: 'FF4CAF50', K2: 'FF8BC34A', K3: 'FFFF9800', K4: 'FFF44336' };

  analysis.dailyComparison.forEach((day, idx) => {
    const rn = idx + 2;
    const row = dailySheet.getRow(rn);

    row.getCell(1).value = '';                           // A: margin
    row.getCell(2).value = day.date.toLocaleDateString('pl-PL');  // B: Data
    row.getCell(3).value = dayNames[day.date.getDay()];  // C: Dzień tyg.
    row.getCell(4).value = plNum(day.zsBefore, 2);       // D: ZS przed
    row.getCell(5).value = plNum(day.zsAfter, 2);        // E: ZS po
    row.getCell(6).value = { formula: `D${rn}-E${rn}`, result: plNum(day.zsBefore - day.zsAfter, 2) };  // F: Redukcja ZS
    row.getCell(7).value = day.klassBefore;              // G: Klasa przed
    row.getCell(8).value = day.klassAfter;               // H: Klasa po
    row.getCell(9).value = plNum(day.coeffBefore, 2);    // I: A przed
    row.getCell(10).value = plNum(day.coeffAfter, 2);    // J: A po
    row.getCell(11).value = plNum(day.deltaSBefore, 2);  // K: Δs przed
    row.getCell(12).value = plNum(day.deltaSAfter, 2);   // L: Δs po
    row.getCell(13).value = { formula: `I${rn}*${somRef}*D${rn}`, result: plNum(day.feeBefore, 2) };         // M: Opłata przed
    row.getCell(14).value = { formula: `J${rn}*${somRef}*E${rn}`, result: plNum(day.feeAfter, 2) };          // N: Opłata po
    row.getCell(15).value = { formula: `M${rn}-N${rn}`, result: plNum(day.feeBefore - day.feeAfter, 2) };    // O: Oszczędność
    row.getCell(16).value = { formula: `I${rn}*${somRef}*E${rn}`, result: plNum(day.feeWithOldKclass, 2) };  // P: Opłata (stara K)
    row.getCell(17).value = { formula: `M${rn}-P${rn}`, result: plNum(day.feeBefore - day.feeWithOldKclass, 2) };   // Q: Efekt ZS
    row.getCell(18).value = { formula: `P${rn}-N${rn}`, result: plNum(day.feeWithOldKclass - day.feeAfter, 2) };    // R: Efekt K

    // Number formats
    [4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18].forEach(col => {
      row.getCell(col).numFmt = numFmt2;
    });

    // Color K-class cells
    row.getCell(7).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: kColors[day.klassBefore] } };
    row.getCell(8).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: kColors[day.klassAfter] } };
  });

  // Totals row — also via getRow (no addRow)
  const lr = dailyDataLastRow;
  const tRow = dailySheet.getRow(dailyTotalRow);
  tRow.getCell(2).value = 'SUMA';
  tRow.getCell(4).value  = { formula: `SUM(D2:D${lr})`, result: plNum(analysis.before.totalZs, 0) };
  tRow.getCell(5).value  = { formula: `SUM(E2:E${lr})`, result: plNum(analysis.after.totalZs, 0) };
  tRow.getCell(6).value  = { formula: `SUM(F2:F${lr})`, result: plNum(analysis.before.totalZs - analysis.after.totalZs, 0) };
  tRow.getCell(13).value = { formula: `SUM(M2:M${lr})`, result: plNum(analysis.before.totalFee, 2) };
  tRow.getCell(14).value = { formula: `SUM(N2:N${lr})`, result: plNum(analysis.after.totalFee, 2) };
  tRow.getCell(15).value = { formula: `SUM(O2:O${lr})`, result: plNum(analysis.before.totalFee - analysis.after.totalFee, 2) };
  tRow.getCell(16).value = { formula: `SUM(P2:P${lr})`, result: plNum(analysis.before.totalFee - analysis.savings.fromKclassImprovement, 2) };
  tRow.getCell(17).value = { formula: `SUM(Q2:Q${lr})`, result: plNum(analysis.savings.fromZsReduction, 2) };
  tRow.getCell(18).value = { formula: `SUM(R2:R${lr})`, result: plNum(analysis.savings.fromKclassImprovement, 2) };
  [4, 5, 6, 13, 14, 15, 16, 17, 18].forEach(c => tRow.getCell(c).numFmt = numFmt2);
  tRow.font = { bold: true };
  tRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8E8E8' } };

  // Print area
  dailySheet.pageSetup = { printArea: `A1:R${dailyTotalRow}`, fitToPage: true, fitToWidth: 1, orientation: 'landscape' };

  // ==========================================
  // SHEET 3: OBJAŚNIENIA (with margin col A)
  // ==========================================
  const helpSheet = workbook.addWorksheet('Objaśnienia');
  helpSheet.getColumn(1).width = 3;   // A: margin
  helpSheet.getColumn(2).width = 30;  // B: column name
  helpSheet.getColumn(3).width = 70;  // C: description
  helpSheet.views = [{ state: 'frozen', ySplit: 2, showGridLines: false, showRowColHeaders: false }];

  helpSheet.getCell('B1').value = 'OBJAŚNIENIA KOLUMN';
  helpSheet.getCell('B1').font = { bold: true, size: 14 };

  const explanations = [
    ['', '', ''],
    ['', 'Kolumna', 'Opis'],
    ['', 'Data', 'Dzień roboczy (Pn-Pt, bez świąt)'],
    ['', 'ZS przed [kWh]', 'Energia pobrana z sieci w godz. wybranych (7-22) BEZ PV'],
    ['', 'ZS po [kWh]', 'Energia pobrana z sieci w godz. wybranych (7-22) Z PV'],
    ['', 'Redukcja ZS', 'ZS przed - ZS po (ile kWh mniej z sieci dzięki PV)'],
    ['', 'Klasa przed/po', 'Klasa taryfowa K1-K4 wyznaczona na podstawie Δs'],
    ['', 'A przed/po', 'Współczynnik opłaty mocowej (K1=0.17, K2=0.50, K3=0.83, K4=1.00)'],
    ['', 'Δs przed/po [%]', '(śr. pobór w godz. wybranych / śr. pobór poza - 1) × 100%'],
    ['', 'Opłata przed [PLN]', 'A_przed × SOM × ZS_przed'],
    ['', 'Opłata po [PLN]', 'A_po × SOM × ZS_po'],
    ['', 'Oszczędność [PLN]', 'Opłata przed - Opłata po (łączna oszczędność)'],
    ['', 'Opłata (stara K) [PLN]', 'A_przed × SOM × ZS_po (opłata gdyby klasa K się nie zmieniła)'],
    ['', 'Efekt ZS [PLN]', 'Opłata przed - Opłata (stara K) (oszczędność z samej redukcji ZS)'],
    ['', 'Efekt K [PLN]', 'Opłata (stara K) - Opłata po (oszczędność z poprawy klasy K)'],
    ['', '', ''],
    ['', 'WZORY', ''],
    ['', 'WOM = A × SOM × ZS', 'Opłata mocowa = Współczynnik × Stawka × Energia w godz. wybranych'],
    ['', 'Δs = (śr_s / śr_ps - 1) × 100%', 'Stosunek średniego zużycia w szczycie do poza szczytem'],
    ['', '', ''],
    ['', 'KLASY K (Dz.U. 2023 poz. 503)', ''],
    ['', 'K1: Δs < -10%', 'Współczynnik A = 0.17 (zużycie nocą wyższe niż w szczycie)'],
    ['', 'K2: Δs -10% do 10%', 'Współczynnik A = 0.50 (profil płaski)'],
    ['', 'K3: Δs 10% do 30%', 'Współczynnik A = 0.83 (profil umiarkowanie szczytowy)'],
    ['', 'K4: Δs ≥ 30%', 'Współczynnik A = 1.00 (profil wybitnie szczytowy)'],
  ];

  explanations.forEach(row => helpSheet.addRow(row));
  helpSheet.getRow(2).font = { bold: true };

  // ==========================================
  // SAVE FILE
  // ==========================================
  if (window.applyExcelWatermark) {
    try { window.applyExcelWatermark(workbook, {}); }
    catch (e) { console.warn('⚠️ Watermark:', e); }
  }

  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const cap = window.currentVariant?.capacity || window.centralizedCalc?.common?.capacityKwp || '';
  const capSuffix = cap ? `_${Math.round(cap)}kWp` : '';
  const filename = `Analiza_Klasy_K${capSuffix}_${new Date().toISOString().slice(0,10)}.xlsx`;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);

  console.log(`📥 Exported K-class analysis to ${filename}`);
}
window.exportKClassToExcel = exportKClassToExcel;

// ============================================================================
// LOAD DURATION CURVE (KRZYWA UPORZĄDKOWANA MOCY)
// ============================================================================

let loadDurationCurveChartInstance = null;

/**
 * Calculate Load Duration Curve data
 * @param {Array} loadHourly - Array of 8760 hourly load values (kW)
 * @param {Array} pvHourly - Array of 8760 hourly PV production values (kW)
 * @returns {Object} LDC analysis data
 */
function calculateLoadDurationCurve(loadHourly, pvHourly) {
  if (!loadHourly || loadHourly.length < 8760) {
    return null;
  }

  // Calculate grid draw (load - PV, min 0)
  const gridDraw = loadHourly.map((load, i) => {
    const pv = pvHourly?.[i] || 0;
    return Math.max(0, load - pv);
  });

  // Sort both arrays in descending order for LDC
  const loadSorted = [...loadHourly].sort((a, b) => b - a);
  const gridSorted = [...gridDraw].sort((a, b) => b - a);

  // Calculate statistics
  const peakBefore = Math.max(...loadHourly);
  const peakAfter = Math.max(...gridDraw);
  const avgBefore = loadHourly.reduce((a, b) => a + b, 0) / loadHourly.length;
  const avgAfter = gridDraw.reduce((a, b) => a + b, 0) / gridDraw.length;
  const loadFactorBefore = avgBefore / peakBefore;
  const loadFactorAfter = peakAfter > 0 ? avgAfter / peakAfter : 0;

  // Calculate hours above thresholds
  const thresholds = [0.9, 0.75, 0.5, 0.25]; // 90%, 75%, 50%, 25% of peak
  const hoursAboveThreshold = thresholds.map(t => {
    const thresholdValueBefore = peakBefore * t;
    const thresholdValueAfter = peakAfter * t;
    return {
      threshold: t,
      thresholdKwBefore: thresholdValueBefore,
      thresholdKwAfter: thresholdValueAfter,
      hoursBefore: loadHourly.filter(v => v >= thresholdValueBefore).length,
      hoursAfter: gridDraw.filter(v => v >= thresholdValueAfter).length
    };
  });

  // Sample LDC curves (reduce to 100 points for charting)
  const sampleSize = 100;
  const step = Math.floor(8760 / sampleSize);
  const ldcBefore = [];
  const ldcAfter = [];
  const ldcLabels = [];

  for (let i = 0; i < sampleSize; i++) {
    const idx = i * step;
    ldcBefore.push(loadSorted[idx]);
    ldcAfter.push(gridSorted[idx]);
    ldcLabels.push(idx);
  }

  return {
    loadSorted,
    gridSorted,
    ldcBefore,
    ldcAfter,
    ldcLabels,
    peakBefore,
    peakAfter,
    avgBefore,
    avgAfter,
    loadFactorBefore,
    loadFactorAfter,
    hoursAboveThreshold,
    peakReductionKw: peakBefore - peakAfter,
    peakReductionPct: peakBefore > 0 ? ((peakBefore - peakAfter) / peakBefore) * 100 : 0
  };
}

/**
 * Update the Load Duration Curve widget UI
 * @param {Object} ldcData - Data from calculateLoadDurationCurve
 */
function updateLoadDurationCurveWidget(ldcData) {
  if (!ldcData) {
    const section = document.getElementById('loadDurationCurveSection');
    if (section) section.style.display = 'none';
    return;
  }

  // Show the section
  const section = document.getElementById('loadDurationCurveSection');
  if (section) section.style.display = 'block';

  // Update statistics
  const peakBefore = document.getElementById('ldcPeakBefore');
  const peakAfter = document.getElementById('ldcPeakAfter');
  const peakReduction = document.getElementById('ldcPeakReduction');
  const avgBefore = document.getElementById('ldcAvgBefore');
  const avgAfter = document.getElementById('ldcAvgAfter');
  const loadFactorBefore = document.getElementById('ldcLoadFactorBefore');
  const loadFactorAfter = document.getElementById('ldcLoadFactorAfter');

  if (peakBefore) peakBefore.textContent = ldcData.peakBefore.toFixed(1);
  if (peakAfter) peakAfter.textContent = ldcData.peakAfter.toFixed(1);
  if (peakReduction) {
    peakReduction.textContent = `-${ldcData.peakReductionKw.toFixed(1)} kW (${ldcData.peakReductionPct.toFixed(1)}%)`;
  }
  if (avgBefore) avgBefore.textContent = ldcData.avgBefore.toFixed(1);
  if (avgAfter) avgAfter.textContent = ldcData.avgAfter.toFixed(1);
  if (loadFactorBefore) loadFactorBefore.textContent = decimalToPct(ldcData.loadFactorBefore).toFixed(1) + '%';
  if (loadFactorAfter) loadFactorAfter.textContent = decimalToPct(ldcData.loadFactorAfter).toFixed(1) + '%';

  // Update threshold table
  const thresholdTable = document.getElementById('ldcThresholdTable');
  if (thresholdTable && ldcData.hoursAboveThreshold) {
    thresholdTable.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:10px;">
        <tr style="background:#e3f2fd;">
          <th style="padding:4px;text-align:left;">Próg</th>
          <th style="padding:4px;text-align:right;">Bez PV</th>
          <th style="padding:4px;text-align:right;">Z PV</th>
          <th style="padding:4px;text-align:right;">Δ</th>
        </tr>
        ${ldcData.hoursAboveThreshold.map(t => `
          <tr>
            <td style="padding:3px;">${decimalToPct(t.threshold).toFixed(0)}% (${t.thresholdKwBefore.toFixed(0)} kW)</td>
            <td style="padding:3px;text-align:right;color:#c62828;">${t.hoursBefore} h</td>
            <td style="padding:3px;text-align:right;color:#2e7d32;">${t.hoursAfter} h</td>
            <td style="padding:3px;text-align:right;color:#1565c0;">${t.hoursAfter - t.hoursBefore} h</td>
          </tr>
        `).join('')}
      </table>
    `;
  }

  // Render the chart
  renderLoadDurationCurveChart(ldcData);

  // Store for potential export
  window.lastLdcData = ldcData;
}

/**
 * Render the Load Duration Curve chart
 * @param {Object} ldcData - Data from calculateLoadDurationCurve
 */
function renderLoadDurationCurveChart(ldcData) {
  const canvas = document.getElementById('loadDurationCurveChart');
  if (!canvas || !ldcData) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing chart
  if (loadDurationCurveChartInstance) {
    loadDurationCurveChartInstance.destroy();
  }

  loadDurationCurveChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: ldcData.ldcLabels,
      datasets: [
        {
          label: 'Bez PV (zużycie)',
          data: ldcData.ldcBefore,
          borderColor: '#f44336',
          backgroundColor: 'rgba(244, 67, 54, 0.1)',
          borderWidth: 2,
          fill: true,
          tension: 0.1,
          pointRadius: 0
        },
        {
          label: 'Z PV (pobór z sieci)',
          data: ldcData.ldcAfter,
          borderColor: '#4caf50',
          backgroundColor: 'rgba(76, 175, 80, 0.1)',
          borderWidth: 2,
          fill: true,
          tension: 0.1,
          pointRadius: 0
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index'
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            title: function(context) {
              return `Godzina ${context[0].label} w rankingu`;
            },
            label: function(context) {
              return `${context.dataset.label}: ${context.parsed.y.toFixed(1)} kW`;
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          title: {
            display: true,
            text: 'Godziny (posortowane malejąco)',
            font: { size: 10 }
          },
          ticks: {
            font: { size: 9 },
            callback: function(val) {
              return val.toFixed(0);
            }
          },
          grid: {
            display: false
          }
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: 'Moc [kW]',
            font: { size: 10 }
          },
          ticks: {
            font: { size: 9 },
            callback: function(val) {
              return val.toFixed(0);
            }
          },
          grid: {
            color: 'rgba(0,0,0,0.05)'
          }
        }
      }
    }
  });
}

/**
 * Initialize Load Duration Curve analysis from cached data
 */
async function initLoadDurationCurve() {
  try {
    console.log('📈 LDC: Initializing Load Duration Curve...');

    let loadHourly = null;
    let pvHourly = null;

    // Check if we have cached data from fetchRealHourlyData
    if (typeof cachedHourlyConsumption !== 'undefined' && cachedHourlyConsumption?.values) {
      loadHourly = cachedHourlyConsumption.values;
      console.log(`📈 LDC: Found cached consumption data (${loadHourly.length} points)`);
    }

    if (typeof cachedHourlyProduction !== 'undefined' && cachedHourlyProduction?.values) {
      pvHourly = cachedHourlyProduction.values;
      console.log(`📈 LDC: Found cached production data (${pvHourly.length} points)`);
    }

    // If no cached data, try to fetch it
    if (!loadHourly) {
      console.log('📈 LDC: No cached data, trying to fetch...');
      try {
        const apiData = await fetchRealHourlyData();
        if (apiData?.consumption?.values) {
          loadHourly = apiData.consumption.values;
        }
        if (apiData?.production?.values) {
          pvHourly = apiData.production.values;
        }
      } catch (e) {
        console.log('📈 LDC: Could not fetch hourly data:', e.message);
      }
    }

    // If still no data, try to generate from variant
    if (!loadHourly) {
      const variant = variants[currentVariant];
      const annualConsumption = getAnnualConsumptionKwh();

      if (annualConsumption > 0) {
        console.log(`📈 LDC: Using synthetic profile from annual consumption (${annualConsumption} kWh)`);
        loadHourly = new Array(8760).fill(0);
        for (let day = 0; day < 365; day++) {
          for (let hour = 0; hour < 24; hour++) {
            const idx = day * 24 + hour;
            let factor = 0.5;
            if (hour >= 7 && hour < 18) {
              factor = 1.5;
            } else if (hour >= 18 && hour < 22) {
              factor = 0.8;
            }
            loadHourly[idx] = (annualConsumption / 8760) * factor;
          }
        }
      }
    }

    // If still no PV data, generate synthetic from variant
    if (!pvHourly) {
      const variant = variants[currentVariant];
      if (variant?.production > 0) {
        const annualProduction = variant.production;
        console.log(`📈 LDC: Generating synthetic PV profile (${annualProduction} kWh/year)`);

        pvHourly = new Array(8760).fill(0);
        for (let day = 0; day < 365; day++) {
          const dayOfYear = day;
          const seasonalFactor = 0.6 + 0.4 * Math.sin(2 * Math.PI * (dayOfYear - 80) / 365);

          for (let hour = 0; hour < 24; hour++) {
            const idx = day * 24 + hour;
            if (hour >= 6 && hour <= 20) {
              const solarFactor = Math.sin(Math.PI * (hour - 6) / 14);
              pvHourly[idx] = (annualProduction / 8760) * 2.5 * solarFactor * seasonalFactor;
            }
          }
        }
      }
    }

    if (!loadHourly || loadHourly.length < 8760) {
      console.log('📈 LDC: Insufficient load data, hiding widget');
      const section = document.getElementById('loadDurationCurveSection');
      if (section) section.style.display = 'none';
      return;
    }

    // Ensure arrays are exactly 8760
    if (loadHourly.length > 8760) loadHourly = loadHourly.slice(0, 8760);
    if (pvHourly && pvHourly.length > 8760) pvHourly = pvHourly.slice(0, 8760);

    // Calculate and update
    const ldcData = calculateLoadDurationCurve(loadHourly, pvHourly);
    updateLoadDurationCurveWidget(ldcData);

    console.log('📈 LDC: Initialization complete');

  } catch (e) {
    console.error('📈 LDC error:', e);
    const section = document.getElementById('loadDurationCurveSection');
    if (section) section.style.display = 'none';
  }
}

window.initLoadDurationCurve = initLoadDurationCurve;

console.log('📦 economics.js fully loaded');

// ============================================================================
// TCSL - TOTAL COST TO SERVE LOAD (Unified Cost Engine)
// ============================================================================

let tcslMetrics = {};         // { variantKey: TcslResult }
window.tcslMetrics = tcslMetrics;
let tcslMonthlyChart = null;  // Chart.js instance

/**
 * Main TCSL comparison function.
 * Called from performEconomicAnalysis(). Always computes tariff TCSL.
 * Optionally computes RDN TCSL if RDN pricing is enabled.
 */
async function calculateTcslComparison(variant) {
  const tcslSection = document.getElementById('tcslComparisonSection');

  try {
    // 1. Get hourly consumption
    let hourlyConsumption = hourlyData?.values || hourlyData || [];
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      console.log('⚡ TCSL: No hourly consumption in memory, trying /api/data/export-data...');
      try {
        const consResp = await fetch('/api/data/export-data');
        if (consResp.ok) {
          const consData = await consResp.json();
          hourlyConsumption = consData.values || [];
          if (hourlyConsumption.length >= 720) {
            hourlyData = { values: hourlyConsumption };
          }
        }
      } catch (e) { /* ignore */ }
    }
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      throw new Error(`Hourly consumption too short: ${hourlyConsumption?.length || 0}`);
    }

    // 2. Get hourly production
    const variantKey = currentVariant || 'B';
    const variantData = analysisResults?.key_variants?.[variantKey];
    let hourlyProduction = variantData?.hourly_production || [];
    const scenarioFactor = window.currentScenarioFactor || 1.0;
    if (scenarioFactor !== 1.0 && hourlyProduction.length > 0) {
      hourlyProduction = hourlyProduction.map(v => v * scenarioFactor);
    }
    if (hourlyProduction.length < 720) {
      const annualProdKwh = (variant?.production || 0) * scenarioFactor;
      hourlyProduction = new Array(8760).fill(annualProdKwh / 8760);
    }

    // 3. RDN prices (from centralized PriceConfig, with API fallback)
    let rdnPrices = _getRdnHourlyPrices();
    const rdnConfig = systemSettings?.rdnPricingConfig;
    if (!rdnPrices && rdnConfig?.enabled && rdnConfig?.scenarioId) {
      try {
        const priceResp = await fetch(`/api/db/prices/${rdnConfig.scenarioId}/hourly-array`);
        if (priceResp.ok) {
          const priceData = await priceResp.json();
          rdnPrices = priceData.prices_plnmwh || priceData.prices || priceData;
          localStorage.setItem('rdn_hourly_prices', JSON.stringify(rdnPrices));
        }
      } catch (e) { /* ignore */ }
    }
    if (!Array.isArray(rdnPrices) || rdnPrices.length < 720) rdnPrices = null;

    // 4. Build TCSL request
    const s = systemSettings || {};
    const tc = s.tariffConfig || {};
    const fmf = s.fixedMonthlyFees || {};
    const cfc = s.capacityFeeConfig || {};
    const rdnYear = rdnConfig?.year || cfc.year || 2025;

    // Derive actual data start date from consumption timestamps (for correct calendar mapping)
    let dataStartDate = null;
    if (cachedHourlyConsumption?.timestamps?.length > 0) {
      dataStartDate = cachedHourlyConsumption.timestamps[0].substring(0, 10); // "YYYY-MM-DD"
    }

    const requestBody = {
      load_kwh: hourlyConsumption,
      pv_generation_kwh: hourlyProduction,
      tariff_config: {
        type: tc.type || 'flat',
        flat_rate: tc.flatRate || 750,
        two_zone: tc.twoZone ? {
          day_rate: tc.twoZone.dayRate, night_rate: tc.twoZone.nightRate,
          weekday: tc.twoZone.weekday, weekend: tc.twoZone.weekend
        } : null,
        three_zone: tc.threeZone ? {
          peak_rate: tc.threeZone.peakRate, partial_rate: tc.threeZone.partialRate,
          off_peak_rate: tc.threeZone.offPeakRate,
          peak1: tc.threeZone.peak1, peak2: tc.threeZone.peak2, partial: tc.threeZone.partial
        } : null
      },
      rdn_prices_plnmwh: rdnPrices,
      fees_variable: {
        distribution_plnmwh: s.distribution || 200,
        distribution_peak_plnmwh: s.distributionPeak || s.distribution || 200,
        distribution_day_plnmwh: s.distributionDay || s.distribution || 200,
        distribution_night_plnmwh: s.distributionNight || s.distribution || 200,
        distribution_valley_plnmwh: s.distributionValley || s.distributionNight || 13.5,
        quality_fee_plnmwh: s.qualityFee || 10,
        oze_fee_plnmwh: s.ozeFee || 7,
        cogeneration_fee_plnmwh: s.cogenerationFee || 10,
        excise_tax_plnmwh: s.exciseTax || 5
      },
      fees_fixed_monthly: {
        dist_fixed_rate_zl_per_kw_month: fmf.distFixedRatePerKwMonth || 9.14,
        contracted_power_kw: fmf.contractedPowerKw || 50,
        osd_subscription_pln_month: fmf.osdSubscriptionFeeMonth || 5.54,
        transition_fee_pln_month: fmf.transitionFeeMonth || 0,
        supplier_trade_fee_pln_month: fmf.supplierTradeFeeMonth || 0
      },
      capacity_fee_config: {
        som_rate_pln_kwh: (cfc.somRate || 0.2194),
        selected_hours_start: cfc.selectedHours?.Q1?.start ?? 7,
        selected_hours_end: cfc.selectedHours?.Q1?.end ?? 22,
        year: rdnYear
      },
      start_year: rdnYear,
      data_start_date: dataStartDate
    };

    console.log('⚡ TCSL: Sending to /api/profile/compute-tcsl, load:', hourlyConsumption.length, 'h, PV:', hourlyProduction.length, 'h, RDN:', rdnPrices ? rdnPrices.length + 'h' : 'none');

    const resp = await fetch('/api/profile/compute-tcsl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`Backend error ${resp.status}: ${errText}`);
    }

    const result = await resp.json();
    console.log('⚡ TCSL result:', result);

    tcslMetrics[currentVariant] = result;
    renderTcslWidget(result);

    // Calculate RDN-based year-by-year NPV (CAPEX + EaaS)
    if (result.rdn_tcsl_annual_pln != null) {
      try { calculateRdnYearByYear(); } catch (e) { console.error('RDN YbY error:', e); }
    }

    if (tcslSection) tcslSection.style.display = 'block';

  } catch (err) {
    console.error('⚡ TCSL comparison failed:', err);
    if (tcslSection) tcslSection.style.display = 'none';
  }
}

/**
 * Render the TCSL comparison widget with data from backend.
 */
function renderTcslWidget(r) {
  const fmtPLN = v => (v == null || isNaN(v)) ? '-' : Math.round(v).toLocaleString('pl-PL') + ' PLN';
  const fmtMWh = v => (v == null || isNaN(v)) ? '-' : kwhToMwh(v).toFixed(1);

  // PV Annual Cost - CAPEX annualized + OPEX + insurance
  const variantKey = currentVariant || 'B';
  const variantData = analysisResults?.key_variants?.[variantKey];
  const capacityKwp = variantData?.capacity || variantData?.capacity_kwp || 0;
  const capexPerKwp = capacityKwp > 0 ? getCapexForCapacity(capacityKwp) : 0;
  const totalCapex = capacityKwp * capexPerKwp;
  const analysisPeriod = systemSettings?.analysisPeriod || 25;
  const opexPerKwp = systemSettings?.opexPerKwp || 15;
  const insuranceRate = systemSettings?.insuranceRate || 0.005;
  const annualOpex = capacityKwp * opexPerKwp;
  const annualInsurance = totalCapex * insuranceRate;
  // Real cash costs only (no depreciation - it's an accounting concept, not a cash outflow)
  const pvAnnualCost = annualOpex + annualInsurance;

  console.log(`⚡ TCSL PV Cost: ${capacityKwp} kWp, OPEX=${annualOpex.toFixed(0)}/yr, ins=${annualInsurance.toFixed(0)}/yr → total=${pvAnnualCost.toFixed(0)} PLN/yr`);

  // PV Savings - gross, cost, net
  const pvSavT = document.getElementById('tcslPvSavingsTariff');
  if (pvSavT) pvSavT.textContent = fmtPLN(r.pv_savings_tariff_pln);

  const pvCostEl = document.getElementById('tcslPvAnnualCost');
  if (pvCostEl) pvCostEl.textContent = pvAnnualCost > 0 ? fmtPLN(pvAnnualCost) : '-';
  const pvCostBreak = document.getElementById('tcslPvCostBreakdown');
  if (pvCostBreak && pvAnnualCost > 0) {
    pvCostBreak.textContent = `${Math.round(annualOpex).toLocaleString('pl-PL')} OPEX + ${Math.round(annualInsurance).toLocaleString('pl-PL')} ubezp.`;
  }

  const netSavT = r.pv_savings_tariff_pln - pvAnnualCost;
  const netSavTEl = document.getElementById('tcslPvNetSavingsTariff');
  if (netSavTEl) {
    netSavTEl.textContent = fmtPLN(netSavT);
    netSavTEl.style.color = netSavT >= 0 ? '#1b5e20' : '#c62828';
  }
  const netPctEl = document.getElementById('tcslPvNetSavingsTariffPct');
  if (netPctEl && r.pv_savings_tariff_pln > 0) {
    const costPct = decimalToPct(pvAnnualCost / r.pv_savings_tariff_pln).toFixed(0);
    netPctEl.textContent = `Koszt PV = ${costPct}% oszcz. brutto`;
  }

  // RDN row
  const pvSavRWrap = document.getElementById('tcslPvSavingsRdnWrap');
  const pvSavR = document.getElementById('tcslPvSavingsRdn');
  if (r.pv_savings_rdn_pln != null) {
    if (pvSavRWrap) pvSavRWrap.hidden = false;
    if (pvSavR) pvSavR.textContent = fmtPLN(r.pv_savings_rdn_pln);
    const pvCostRdn = document.getElementById('tcslPvAnnualCostRdn');
    if (pvCostRdn) pvCostRdn.textContent = pvAnnualCost > 0 ? fmtPLN(pvAnnualCost) : '-';
    const netSavR = r.pv_savings_rdn_pln - pvAnnualCost;
    const netSavREl = document.getElementById('tcslPvNetSavingsRdn');
    if (netSavREl) {
      netSavREl.textContent = fmtPLN(netSavR);
      netSavREl.style.color = netSavR >= 0 ? '#bf360c' : '#c62828';
    }
  } else {
    if (pvSavRWrap) pvSavRWrap.hidden = true;
  }

  // Capacity Fee / K-class savings card
  const capNoPv = document.getElementById('tcslCapacityNoPv');
  const capWithPv = document.getElementById('tcslCapacityWithPv');
  const capSaving = document.getElementById('tcslCapacitySaving');
  const capSavingPct = document.getElementById('tcslCapacitySavingPct');
  const kNoPv = document.getElementById('tcslKclassNoPv');
  const kWithPv = document.getElementById('tcslKclassWithPv');
  if (capNoPv) capNoPv.textContent = fmtPLN(r.capacity_fee_without_pv_pln);
  if (capWithPv) capWithPv.textContent = fmtPLN(r.capacity_fee_with_pv_pln);
  if (kNoPv) {
    let kNoPvText = r.kclass_without_pv;
    if (r.kclass_stochastic_nopv) {
      const s = r.kclass_stochastic_nopv;
      kNoPvText += ` (eff. ${s.effective_coefficient.toFixed(2)})`;
    }
    kNoPv.textContent = kNoPvText;
  }
  if (kWithPv) {
    let kWithPvText = r.kclass_with_pv;
    if (r.kclass_stochastic_pv) {
      const s = r.kclass_stochastic_pv;
      kWithPvText += ` (eff. ${s.effective_coefficient.toFixed(2)})`;
    }
    kWithPv.textContent = kWithPvText;
  }
  const capDelta = (r.capacity_fee_without_pv_pln || 0) - (r.capacity_fee_with_pv_pln || 0);
  if (capSaving) capSaving.textContent = fmtPLN(capDelta);
  if (capSavingPct && r.capacity_fee_without_pv_pln > 0) {
    const pct = decimalToPct(capDelta / r.capacity_fee_without_pv_pln).toFixed(0);
    capSavingPct.textContent = pct + '% redukcji';
  }

  // Stochastic correction indicator
  const stochNote = document.getElementById('tcslStochasticNote');
  if (stochNote) {
    if (r.kclass_stochastic_nopv) {
      const s = r.kclass_stochastic_nopv;
      const p = s.probabilities;
      stochNote.innerHTML = `<small style="color:#ff9800;">Korekta stochastyczna K-class: `
        + `K1=${(p.K1*100).toFixed(0)}% K2=${(p.K2*100).toFixed(0)}% `
        + `K3=${(p.K3*100).toFixed(0)}% K4=${(p.K4*100).toFixed(0)}% `
        + `(eff.coeff=${s.effective_coefficient.toFixed(3)})</small>`;
      stochNote.hidden = false;
    } else {
      stochNote.hidden = true;
    }
  }

  // Tariff card
  const setT = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = fmtPLN(val); };
  setT('tcslTariffTotal', r.tariff_tcsl_annual_pln);
  setT('tcslTariffEnergy', r.tariff_energy_active_cost_pln);
  setT('tcslTariffFeesVar', r.tariff_fees_var_cost_pln);
  setT('tcslTariffCapacity', r.tariff_capacity_fee_total_pln);
  setT('tcslTariffFixed', r.tariff_fixed_monthly_total_pln);
  const kEl = document.getElementById('tcslTariffKclass');
  if (kEl) {
    let kText = r.kclass_with_pv + ' (bez PV: ' + r.kclass_without_pv + ')';
    if (r.kclass_stochastic_nopv) kText += ' *stoch.';
    kEl.textContent = kText;
  }

  // RDN card (conditional)
  const rdnCard = document.getElementById('tcslRdnCard');
  const cardsGrid = document.getElementById('tcslCardsGrid');
  if (r.rdn_tcsl_annual_pln != null) {
    if (rdnCard) rdnCard.hidden = false;
    if (cardsGrid) cardsGrid.style.gridTemplateColumns = '1fr 1fr';
    setT('tcslRdnTotal', r.rdn_tcsl_annual_pln);
    setT('tcslRdnEnergy', r.rdn_energy_active_cost_pln);
    setT('tcslRdnFeesVar', r.rdn_fees_var_cost_pln);
    setT('tcslRdnCapacity', r.rdn_capacity_fee_total_pln);
    setT('tcslRdnFixed', r.rdn_fixed_monthly_total_pln);
  } else {
    if (rdnCard) rdnCard.hidden = true;
    if (cardsGrid) cardsGrid.style.gridTemplateColumns = '1fr';
  }

  // Delta card (conditional)
  const deltaCard = document.getElementById('tcslDeltaCard');
  if (r.rdn_vs_tariff_delta_pln != null) {
    if (deltaCard) deltaCard.hidden = false;
    const dEl = document.getElementById('tcslDelta');
    const dpEl = document.getElementById('tcslDeltaPct');
    const dvEl = document.getElementById('tcslDeltaVerdict');
    const d = r.rdn_vs_tariff_delta_pln;
    if (dEl) {
      dEl.textContent = fmtPLN(Math.abs(d));
      dEl.style.color = d > 0 ? '#2e7d32' : '#c62828';
    }
    if (dpEl) dpEl.textContent = (r.rdn_vs_tariff_delta_pct || 0).toFixed(1) + '%';
    if (dvEl) dvEl.textContent = d > 0 ? 'RDN TANSZE' : d < 0 ? 'TARYFA TANSZA' : 'ROWNE';
    if (dvEl) dvEl.style.color = d > 0 ? '#2e7d32' : '#c62828';
  } else {
    if (deltaCard) deltaCard.hidden = true;
  }

  // Energy balance
  const setMWh = (id, kwh) => { const el = document.getElementById(id); if (el) el.textContent = fmtMWh(kwh); };
  setMWh('tcslConsumption', r.annual_consumption_kwh);
  setMWh('tcslProduction', r.annual_production_kwh);
  setMWh('tcslSelfConsumed', r.annual_self_consumed_kwh);
  setMWh('tcslGridImport', r.annual_grid_import_kwh);

  // Monthly chart
  renderTcslMonthlyChart(r);

  // Monthly table
  renderTcslMonthlyTable(r);
}

/**
 * Render TCSL monthly grouped bar chart.
 */
function renderTcslMonthlyChart(r) {
  const ctx = document.getElementById('tcslMonthlyChart');
  if (!ctx) return;
  if (tcslMonthlyChart) tcslMonthlyChart.destroy();

  const labels = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paz', 'Lis', 'Gru'];
  const months = r.monthly_breakdown || [];

  const tariffData = months.map(m => Math.round(m.tariff?.tcsl_pln || 0));
  const datasets = [
    { label: 'TCSL Taryfa', data: tariffData, backgroundColor: '#1565c0' }
  ];

  if (r.rdn_tcsl_annual_pln != null) {
    const rdnData = months.map(m => Math.round(m.rdn?.tcsl_pln || 0));
    datasets.push({ label: 'TCSL RDN', data: rdnData, backgroundColor: '#ff6f00' });
  }

  tcslMonthlyChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' } },
      scales: { y: { beginAtZero: true, title: { display: true, text: 'PLN' } } }
    }
  });
}

/**
 * Render TCSL monthly breakdown table.
 */
function renderTcslMonthlyTable(r) {
  const tbody = document.getElementById('tcslMonthlyTableBody');
  if (!tbody) return;
  const hasRdn = r.rdn_tcsl_annual_pln != null;
  const rdnH = document.getElementById('tcslTableRdnHeader');
  const deltaH = document.getElementById('tcslTableDeltaHeader');
  if (rdnH) rdnH.hidden = !hasRdn;
  if (deltaH) deltaH.hidden = !hasRdn;

  const names = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paz', 'Lis', 'Gru'];
  const months = r.monthly_breakdown || [];
  let html = '';
  let sumT = 0, sumR = 0;

  for (const m of months) {
    const t = m.tariff || {};
    const rd = m.rdn || {};
    const tTcsl = t.tcsl_pln || 0;
    const rTcsl = rd.tcsl_pln || 0;
    sumT += tTcsl;
    sumR += rTcsl;
    html += `<tr>
      <td style="padding:6px 8px;">${names[(m.month || 1) - 1]}</td>
      <td style="padding:6px 8px;text-align:right;">${kwhToMwh(t.grid_import_kwh || 0).toFixed(1)}</td>
      <td style="padding:6px 8px;text-align:right;">${Math.round(t.energy_active_pln || 0).toLocaleString()}</td>
      <td style="padding:6px 8px;text-align:right;">${Math.round(t.fees_var_pln || 0).toLocaleString()}</td>
      <td style="padding:6px 8px;text-align:right;">${Math.round(t.capacity_fee_pln || 0).toLocaleString()}</td>
      <td style="padding:6px 8px;text-align:right;">${Math.round(t.fixed_monthly_pln || 0).toLocaleString()}</td>
      <td style="padding:6px 8px;text-align:right;font-weight:700;">${Math.round(tTcsl).toLocaleString()}</td>
      ${hasRdn ? `<td style="padding:6px 8px;text-align:right;color:#e65100;">${Math.round(rTcsl).toLocaleString()}</td>` : ''}
      ${hasRdn ? `<td style="padding:6px 8px;text-align:right;color:${tTcsl > rTcsl ? '#2e7d32' : '#c62828'};font-weight:600;">${Math.round(tTcsl - rTcsl).toLocaleString()}</td>` : ''}
    </tr>`;
  }

  html += `<tr style="background:#f5f5f5;font-weight:700;border-top:2px solid #333;">
    <td style="padding:8px;">SUMA</td>
    <td style="padding:8px;text-align:right;">${kwhToMwh(r.annual_grid_import_kwh).toFixed(1)}</td>
    <td style="padding:8px;text-align:right;">${Math.round(r.tariff_energy_active_cost_pln).toLocaleString()}</td>
    <td style="padding:8px;text-align:right;">${Math.round(r.tariff_fees_var_cost_pln).toLocaleString()}</td>
    <td style="padding:8px;text-align:right;">${Math.round(r.tariff_capacity_fee_total_pln).toLocaleString()}</td>
    <td style="padding:8px;text-align:right;">${Math.round(r.tariff_fixed_monthly_total_pln / 12).toLocaleString()}</td>
    <td style="padding:8px;text-align:right;font-size:14px;">${Math.round(r.tariff_tcsl_annual_pln).toLocaleString()}</td>
    ${hasRdn ? `<td style="padding:8px;text-align:right;color:#e65100;font-size:14px;">${Math.round(r.rdn_tcsl_annual_pln).toLocaleString()}</td>` : ''}
    ${hasRdn ? `<td style="padding:8px;text-align:right;color:${r.rdn_vs_tariff_delta_pln > 0 ? '#2e7d32' : '#c62828'};font-size:14px;">${Math.round(r.rdn_vs_tariff_delta_pln).toLocaleString()}</td>` : ''}
  </tr>`;

  tbody.innerHTML = html;
}

/**
 * Export TCSL hourly Excel.
 * Uses TCSL backend result for summary, builds hourly rows client-side.
 */
async function exportTcslHourlyExcel() {
  try {
    const result = tcslMetrics[currentVariant];
    if (!result) { alert('Brak wynikow TCSL. Poczekaj na zakonczenie analizy.'); return; }

    // RDN prices
    const rdnConfig = systemSettings?.rdnPricingConfig;
    let rdnPrices = null;
    if (rdnConfig?.enabled && rdnConfig?.scenarioId) {
      const resp = await fetch(`/api/db/prices/${rdnConfig.scenarioId}/hourly-array`);
      if (resp.ok) {
        const d = await resp.json();
        rdnPrices = d.prices_plnmwh || d.prices || d;
        localStorage.setItem('rdn_hourly_prices', JSON.stringify(rdnPrices));
      }
    }

    // Hourly data
    let hourlyConsumption = hourlyData?.values || hourlyData || [];
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      try {
        const consResp = await fetch('/api/data/export-data');
        if (consResp.ok) { hourlyConsumption = (await consResp.json()).values || []; }
      } catch (e) { /* ignore */ }
    }
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      alert('Brak danych godzinowych konsumpcji.'); return;
    }

    const variantData = analysisResults?.key_variants?.[currentVariant || 'B'];
    let hourlyProd = variantData?.hourly_production || [];
    const sf = window.currentScenarioFactor || 1.0;
    if (sf !== 1.0 && hourlyProd.length > 0) hourlyProd = hourlyProd.map(v => v * sf);
    if (hourlyProd.length < 720) hourlyProd = new Array(8760).fill((variantData?.production || 0) * sf / 8760);

    // Tariff prices (build client-side)
    const rdnYear = rdnConfig?.year || 2025;
    const tariffPrices = buildHourlyTariffPrices(hourlyConsumption.length, rdnYear);

    const s = systemSettings || {};
    const feesVar = (s.distribution || 200) + (s.qualityFee || 10) + (s.ozeFee || 7) + (s.cogenerationFee || 10) + (s.exciseTax || 5);

    const len = Math.min(hourlyConsumption.length, hourlyProd.length, tariffPrices.length, rdnPrices ? rdnPrices.length : Infinity);
    const hasRdn = rdnPrices && rdnPrices.length >= len;

    // Build workbook
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('TCSL godzinowy');

    const cols = [
      { header: 'Data', key: 'date', width: 12 },
      { header: 'Godz', key: 'hour', width: 6 },
      { header: 'Kons [kWh]', key: 'load', width: 12 },
      { header: 'PV [kWh]', key: 'pv', width: 10 },
      { header: 'Z sieci [kWh]', key: 'grid', width: 13 },
      { header: 'Cena Taryfa [PLN/MWh]', key: 'price_t', width: 20 },
    ];
    if (hasRdn) cols.push({ header: 'Cena RDN [PLN/MWh]', key: 'price_r', width: 18 });
    cols.push({ header: 'Koszt Taryfa [PLN]', key: 'cost_t', width: 16 });
    if (hasRdn) cols.push({ header: 'Koszt RDN [PLN]', key: 'cost_r', width: 14 });
    if (hasRdn) cols.push({ header: 'ROZNICA [PLN]', key: 'diff', width: 14 });
    ws.columns = cols;

    const hdr = ws.getRow(1);
    hdr.font = { bold: true };
    hdr.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

    const mDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (rdnYear % 4 === 0 && (rdnYear % 100 !== 0 || rdnYear % 400 === 0)) mDays[1] = 29;

    let totCostT = 0, totCostR = 0;

    for (let h = 0; h < len; h++) {
      const load = hourlyConsumption[h] || 0;
      const pv = hourlyProd[h] || 0;
      const grid = Math.max(0, load - pv);
      const tPrice = (tariffPrices[h] || 510) + feesVar;
      const costT = grid * tPrice / 1000;
      totCostT += costT;

      const dayOfYear = Math.floor(h / 24);
      const hourOfDay = h % 24;
      let month = 0, acc = 0;
      for (let m = 0; m < 12; m++) { if (dayOfYear < acc + mDays[m]) { month = m; break; } acc += mDays[m]; }
      const dayOfMonth = dayOfYear - acc + 1;
      const dateStr = `${rdnYear}-${String(month + 1).padStart(2, '0')}-${String(dayOfMonth).padStart(2, '0')}`;

      const row = { date: dateStr, hour: hourOfDay, load: +load.toFixed(2), pv: +pv.toFixed(2), grid: +grid.toFixed(2), price_t: +tPrice.toFixed(1), cost_t: +costT.toFixed(2) };

      if (hasRdn) {
        const rPrice = (rdnPrices[h] || 0) + feesVar;
        const costR = grid * rPrice / 1000;
        totCostR += costR;
        row.price_r = +rPrice.toFixed(1);
        row.cost_r = +costR.toFixed(2);
        row.diff = +(costR - costT).toFixed(2);
      }

      const xlRow = ws.addRow(row);
      if (hasRdn) {
        const diffCell = xlRow.getCell('diff');
        if (row.diff < -0.01) diffCell.font = { color: { argb: 'FF2E7D32' }, bold: true };
        else if (row.diff > 0.01) diffCell.font = { color: { argb: 'FFC62828' } };
      }
    }

    // Summary block
    ws.addRow({});
    const addSumRow = (label, costT, costR, bold, bg) => {
      const data = { date: label, cost_t: Math.round(costT) };
      if (hasRdn) { data.cost_r = Math.round(costR); data.diff = Math.round(costR - costT); }
      const r = ws.addRow(data);
      if (bold) r.font = { bold: true, size: bold };
      if (bg) r.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bg } };
      return r;
    };

    addSumRow('SUMA ZMIENNE', totCostT, totCostR, 11, null);
    addSumRow('+ Opl. mocowa (K-class)', result.tariff_capacity_fee_total_pln, result.rdn_capacity_fee_total_pln || result.tariff_capacity_fee_total_pln, 11, null);
    addSumRow('+ Opl. stale (12 mies)', result.tariff_fixed_monthly_total_pln, result.rdn_fixed_monthly_total_pln || result.tariff_fixed_monthly_total_pln, 11, null);
    addSumRow('= TCSL ROCZNY', result.tariff_tcsl_annual_pln, result.rdn_tcsl_annual_pln || 0, 14, 'FFFFF9C4');

    if (hasRdn) {
      const d = result.rdn_vs_tariff_delta_pln || 0;
      const vRow = ws.addRow({ date: d > 0 ? 'RDN TANSZE o:' : 'TARYFA TANSZA o:', diff: Math.abs(Math.round(d)) });
      vRow.font = { bold: true, size: 14, color: { argb: d > 0 ? 'FF2E7D32' : 'FFC62828' } };
    }

    // ===== PV SAVINGS SECTION =====
    ws.addRow({});
    ws.addRow({});
    const pvHeader = ws.addRow({ date: 'OSZCZEDNOSCI DZIEKI PV' });
    pvHeader.font = { bold: true, size: 14 };
    pvHeader.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };

    const addPvRow = (label, valT, valR, bold, bg) => {
      const data = { date: label, cost_t: Math.round(valT) };
      if (hasRdn) { data.cost_r = Math.round(valR); }
      const r = ws.addRow(data);
      if (bold) r.font = { bold: true, size: bold };
      if (bg) r.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bg } };
      return r;
    };

    // Labels row
    const lblRow = ws.addRow({ date: '', cost_t: 'Taryfa', cost_r: hasRdn ? 'RDN' : undefined });
    lblRow.font = { bold: true, italic: true, size: 10 };

    // TCSL bez PV
    const nopvT = result.nopv_tariff_tcsl_pln || 0;
    const nopvR = result.nopv_rdn_tcsl_pln || 0;
    addPvRow('TCSL BEZ PV (baseline)', nopvT, nopvR, 11, null);

    // TCSL z PV
    const wpvT = result.tariff_tcsl_annual_pln || 0;
    const wpvR = result.rdn_tcsl_annual_pln || 0;
    addPvRow('TCSL Z PV', wpvT, wpvR, 11, null);

    // Gross savings
    const grossT = result.pv_savings_tariff_pln || 0;
    const grossR = result.pv_savings_rdn_pln || 0;
    const gsRow = addPvRow('= OSZCZ. BRUTTO (bezPV - zPV)', grossT, grossR, 12, 'FFE8F5E9');
    gsRow.getCell('cost_t').font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
    if (hasRdn) gsRow.getCell('cost_r').font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };

    // PV annual cost
    const vd = analysisResults?.key_variants?.[currentVariant || 'B'];
    const capKwp = vd?.capacity || vd?.capacity_kwp || 0;
    const cxPerKwp = capKwp > 0 ? getCapexForCapacity(capKwp) : 0;
    const totalCx = capKwp * cxPerKwp;
    const period = systemSettings?.analysisPeriod || 25;
    const opxKwp = systemSettings?.opexPerKwp || 15;
    const insRate = systemSettings?.insuranceRate || 0.005;
    const annOpex = capKwp * opxKwp;
    const annIns = totalCx * insRate;
    // Real cash costs only (no depreciation - it's accounting, not cash outflow)
    const pvCostYr = annOpex + annIns;

    ws.addRow({});
    const costHdr = ws.addRow({ date: 'ROCZNY KOSZT PV (koszty gotówkowe)' });
    costHdr.font = { bold: true, size: 11 };
    ws.addRow({ date: `  Moc PV: ${capKwp} kWp`, cost_t: '' });
    ws.addRow({ date: `  OPEX (${opxKwp} PLN/kWp/rok)`, cost_t: Math.round(annOpex) });
    ws.addRow({ date: `  Ubezpieczenie (${decimalToPct(insRate).toFixed(1)}% CAPEX)`, cost_t: Math.round(annIns) });
    const pvTotRow = addPvRow('  = RAZEM koszt PV/rok', pvCostYr, pvCostYr, 11, 'FFFFCDD2');
    pvTotRow.getCell('cost_t').font = { bold: true, size: 11, color: { argb: 'FFC62828' } };
    if (hasRdn) pvTotRow.getCell('cost_r').font = { bold: true, size: 11, color: { argb: 'FFC62828' } };

    // Net savings
    ws.addRow({});
    const netT = grossT - pvCostYr;
    const netR = grossR - pvCostYr;
    const netRow = addPvRow('= OSZCZ. NETTO (brutto - koszt PV)', netT, netR, 14, 'FFA5D6A7');
    netRow.getCell('cost_t').font = { bold: true, size: 14, color: { argb: netT >= 0 ? 'FF1B5E20' : 'FFC62828' } };
    if (hasRdn) netRow.getCell('cost_r').font = { bold: true, size: 14, color: { argb: netR >= 0 ? 'FF1B5E20' : 'FFC62828' } };

    // Capacity fee breakdown
    ws.addRow({});
    const capHdr = ws.addRow({ date: 'OPLATA MOCOWA - wplyw PV' });
    capHdr.font = { bold: true, size: 11 };
    const stochLabelNoPv = result.kclass_stochastic_nopv ? ` (stoch. eff.=${result.kclass_stochastic_nopv.effective_coefficient.toFixed(3)})` : '';
    const stochLabelPv = result.kclass_stochastic_pv ? ` (stoch. eff.=${result.kclass_stochastic_pv.effective_coefficient.toFixed(3)})` : '';
    ws.addRow({ date: `  Bez PV: klasa ${result.kclass_without_pv}${stochLabelNoPv}`, cost_t: Math.round(result.capacity_fee_without_pv_pln) });
    ws.addRow({ date: `  Z PV: klasa ${result.kclass_with_pv}${stochLabelPv}`, cost_t: Math.round(result.capacity_fee_with_pv_pln) });
    const capSavRow = ws.addRow({ date: '  = Oszcz. na opl. mocowej', cost_t: Math.round(result.capacity_fee_without_pv_pln - result.capacity_fee_with_pv_pln) });
    capSavRow.font = { bold: true, color: { argb: 'FF2E7D32' } };

    // Energy balance
    ws.addRow({});
    const balHdr = ws.addRow({ date: 'BILANS ENERGII' });
    balHdr.font = { bold: true, size: 11 };
    ws.addRow({ date: '  Zuzycie roczne [MWh]', cost_t: +kwhToMwh(result.annual_consumption_kwh).toFixed(1) });
    ws.addRow({ date: '  Produkcja PV [MWh]', cost_t: +kwhToMwh(result.annual_production_kwh).toFixed(1) });
    ws.addRow({ date: '  Autokonsumpcja [MWh]', cost_t: +kwhToMwh(result.annual_self_consumed_kwh).toFixed(1) });
    ws.addRow({ date: '  Pobor z sieci [MWh]', cost_t: +kwhToMwh(result.annual_grid_import_kwh).toFixed(1) });

    // Apply watermark
    if (window.applyExcelWatermark) {
      try { window.applyExcelWatermark(wb, {}); }
      catch (e) { console.warn('⚠️ Watermark:', e); }
    }

    const buf = await wb.xlsx.writeBuffer();
    const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `TCSL_${currentVariant || 'B'}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    console.log(`⚡ TCSL Excel exported: ${len}h`);
  } catch (err) {
    console.error('⚡ TCSL Excel error:', err);
    alert('Blad eksportu: ' + err.message);
  }
}

// =====================================================================
// RDN Year-by-Year NPV Analysis (CAPEX + EaaS)
// Uses TCSL year-1 data as baseline, then projects with CPI escalation
// =====================================================================

function calculateRdnYearByYear() {
  const r = tcslMetrics[currentVariant];
  if (!r || r.rdn_tcsl_annual_pln == null) {
    console.log('⏭️ No RDN TCSL data, skipping RDN year-by-year');
    return;
  }

  const variant = variants[currentVariant];
  if (!variant) return;

  const params = getEconomicParameters();

  // Extract RDN baseline from TCSL results
  const nopvVariable = (r.nopv_rdn_energy_active_pln || 0) + (r.nopv_rdn_fees_var_pln || 0);
  const withPvVariable = (r.rdn_energy_active_cost_pln || 0) + (r.rdn_fees_var_cost_pln || 0);
  const energyFeesSavingsYear1 = nopvVariable - withPvVariable;
  const capacitySavingsYear1 = (r.capacity_fee_without_pv_pln || 0) - (r.capacity_fee_with_pv_pln || 0);

  const rdnBaseline = {
    energyFeesSavingsYear1,
    capacitySavingsYear1,
    totalSavingsYear1: energyFeesSavingsYear1 + capacitySavingsYear1,
    // Actual annual RDN costs from TCSL (real hourly data, not averages)
    nopvRdnTcslAnnual: r.nopv_rdn_tcsl_pln || 0,       // full annual cost WITHOUT PV
    rdnTcslAnnual: r.rdn_tcsl_annual_pln || 0,           // full annual cost WITH PV
    nopvVariable,                                          // variable fees without PV
    withPvVariable,                                        // variable fees with PV
    capacityFeeNoPv: r.capacity_fee_without_pv_pln || 0,
    capacityFeeWithPv: r.capacity_fee_with_pv_pln || 0,
    kclassNoPv: r.kclass_without_pv || '-',
    kclassWithPv: r.kclass_with_pv || '-',
  };

  console.log('📊 RDN Year-by-Year baseline:', rdnBaseline);

  // Get EaaS params (same as tariff calculation)
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || 10;
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value) || 24;
  const subscriptionData = calculateEaasSubscription(
    variant.capacity,
    systemSettings || {},
    params,
    variant
  );

  const eaasParams = subscriptionData ? {
    subscription: subscriptionData.annualSubscription,
    duration: eaasDuration,
    omPerKwp: eaasOM
  } : null;

  centralizedMetricsRdn[currentVariant] = calculateCentralizedFinancialMetrics(
    variant, params, eaasParams,
    { pricingMode: 'rdn', rdnBaseline }
  );

  console.log('✅ RDN Year-by-Year calculated:', {
    capexNPV: plnToMlnPln(centralizedMetricsRdn[currentVariant].capex.npv).toFixed(2) + ' mln PLN',
    eaasNPV: centralizedMetricsRdn[currentVariant].eaas ? plnToMlnPln(centralizedMetricsRdn[currentVariant].eaas.npv).toFixed(2) + ' mln PLN' : 'N/A'
  });

  renderRdnYearByYearTables();
}

function renderRdnYearByYearTables() {
  const rdnCalc = centralizedMetricsRdn[currentVariant];
  if (!rdnCalc) return;

  const fmtK = v => plnToTysPln(v).toFixed(0);
  const fmtM = v => plnToMlnPln(v).toFixed(2);
  const fmtPct = v => v.toFixed(1);

  // --- CAPEX RDN Table ---
  const capexSection = document.getElementById('rdnCapexTableSection');
  if (capexSection && rdnCalc.capex) {
    capexSection.style.display = 'block';
    const tableBody = document.getElementById('rdnCapexTableBody');
    if (!tableBody) return;
    tableBody.innerHTML = '';

    const cashFlows = rdnCalc.capex.cashFlows;
    const investment = rdnCalc.capex.investment;
    const discountRate = rdnCalc.common.discountRate;
    const baseline = rdnCalc.capex.rdnBaseline;

    // Info row above table
    const infoEl = document.getElementById('rdnCapexInfo');
    if (infoEl) {
      infoEl.innerHTML = `Rok 1 oszcz.: <b>${plnToTysPln(baseline.totalSavingsYear1).toFixed(0)} tys. PLN</b> (energia+opl: ${plnToTysPln(baseline.energyFeesSavingsYear1).toFixed(0)}k + mocowa: ${plnToTysPln(baseline.capacitySavingsYear1).toFixed(0)}k) | Inwestycja: <b>${plnToMlnPln(investment).toFixed(2)} mln PLN</b>`;
    }

    // Year 0 row
    const row0 = document.createElement('tr');
    row0.style.background = '#ffebee';
    row0.innerHTML = `<td><b>0</b></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
      <td style="color:#c62828;font-weight:bold">-${fmtK(investment)}</td>
      <td style="color:#c62828;font-weight:bold">-${fmtM(investment)}</td>`;
    tableBody.appendChild(row0);

    let cumulativeNPV = -investment;

    cashFlows.forEach(cf => {
      const discountedCF = cf.net_cash_flow / Math.pow(1 + discountRate, cf.year);
      const prevNPV = cumulativeNPV;
      cumulativeNPV += discountedCF;

      const row = document.createElement('tr');

      // Highlight break-even year
      if (prevNPV < 0 && cumulativeNPV >= 0) {
        row.style.background = '#e8f5e9';
        row.style.borderTop = '3px solid #4caf50';
      }

      const npvColor = cumulativeNPV >= 0 ? '#2e7d32' : '#c62828';
      const cfColor = cf.net_cash_flow >= 0 ? '#2e7d32' : '#c62828';
      row.innerHTML = `
        <td>${cf.year}</td>
        <td>${fmtPct(cf.pvDegradationPct)}</td>
        <td>${fmtK(cf.energyFeesSavings)}</td>
        <td>${fmtK(cf.capacitySavings)}</td>
        <td><b>${fmtK(cf.savings)}</b></td>
        <td>${fmtK(cf.opex)}</td>
        <td style="color:${cfColor};font-weight:bold">${fmtK(cf.net_cash_flow)}</td>
        <td style="color:${npvColor};font-weight:bold">${fmtM(cumulativeNPV)}</td>`;
      tableBody.appendChild(row);
    });

    // Summary row
    const sumRow = document.createElement('tr');
    sumRow.style.background = '#fff9c4';
    sumRow.style.fontWeight = 'bold';
    const totalSav = cashFlows.reduce((s, cf) => s + cf.savings, 0);
    const totalOpex = cashFlows.reduce((s, cf) => s + cf.opex, 0);
    const totalCF = cashFlows.reduce((s, cf) => s + cf.net_cash_flow, 0);
    sumRow.innerHTML = `<td>SUMA</td><td>-</td>
      <td>${fmtK(cashFlows.reduce((s,cf) => s + cf.energyFeesSavings, 0))}</td>
      <td>${fmtK(cashFlows.reduce((s,cf) => s + cf.capacitySavings, 0))}</td>
      <td>${fmtK(totalSav)}</td><td>${fmtK(totalOpex)}</td>
      <td>${fmtK(totalCF)}</td>
      <td style="color:${cumulativeNPV >= 0 ? '#2e7d32' : '#c62828'}">${fmtM(cumulativeNPV)}</td>`;
    tableBody.appendChild(sumRow);
  }

  // --- EaaS RDN Table ---
  const eaasSection = document.getElementById('rdnEaasTableSection');
  if (eaasSection && rdnCalc.eaas) {
    eaasSection.style.display = 'block';
    const tableBody = document.getElementById('rdnEaasTableBody');
    if (!tableBody) return;
    tableBody.innerHTML = '';

    const cashFlows = rdnCalc.eaas.cashFlows;
    const discountRate = rdnCalc.common.discountRate;
    const eaasDuration = rdnCalc.eaas.duration;
    const baseline = rdnCalc.eaas.rdnBaseline;

    const infoEl = document.getElementById('rdnEaasInfo');
    if (infoEl) {
      infoEl.innerHTML = `Rok 1 oszcz.: <b>${plnToTysPln(baseline.totalSavingsYear1).toFixed(0)} tys. PLN</b> | Abonament EaaS: <b>${plnToTysPln(rdnCalc.eaas.baseSubscription).toFixed(0)} tys. PLN/rok</b> | Kontrakt: <b>${eaasDuration} lat</b>`;
    }

    let cumulativeNPV = 0;

    cashFlows.forEach(cf => {
      cumulativeNPV += cf.discountedCF;
      const row = document.createElement('tr');

      // Phase coloring
      if (cf.phase === 'eaas') {
        row.style.background = '#fffde7';
      } else {
        row.style.background = '#e8f5e9';
      }
      // Phase transition borders
      if (cf.year === eaasDuration) {
        row.style.borderBottom = '3px solid #f57c00';
      }
      if (cf.year === eaasDuration + 1) {
        row.style.borderTop = '3px solid #4caf50';
      }

      const phaseLabel = cf.phase === 'eaas' ? 'EaaS' : 'Wlasnosc';
      const cfColor = cf.savings >= 0 ? '#2e7d32' : '#c62828';
      const npvColor = cumulativeNPV >= 0 ? '#2e7d32' : '#c62828';
      row.innerHTML = `
        <td>${cf.year}</td>
        <td>${phaseLabel}</td>
        <td>${fmtPct(cf.pvDegradationPct)}</td>
        <td>${fmtK(cf.energyFeesSavings)}</td>
        <td>${fmtK(cf.capacitySavings)}</td>
        <td><b>${fmtK(cf.gridCost)}</b></td>
        <td>${fmtK(cf.eaasCost)}</td>
        <td style="color:${cfColor};font-weight:bold">${fmtK(cf.savings)}</td>
        <td style="color:${npvColor};font-weight:bold">${fmtM(cumulativeNPV)}</td>`;
      tableBody.appendChild(row);
    });

    // Summary
    const sumRow = document.createElement('tr');
    sumRow.style.background = '#fff9c4';
    sumRow.style.fontWeight = 'bold';
    const totalGrid = cashFlows.reduce((s, cf) => s + cf.gridCost, 0);
    const totalEaas = cashFlows.reduce((s, cf) => s + cf.eaasCost, 0);
    const totalSav = cashFlows.reduce((s, cf) => s + cf.savings, 0);
    sumRow.innerHTML = `<td>SUMA</td><td>-</td><td>-</td>
      <td>${fmtK(cashFlows.reduce((s,cf) => s + cf.energyFeesSavings, 0))}</td>
      <td>${fmtK(cashFlows.reduce((s,cf) => s + cf.capacitySavings, 0))}</td>
      <td>${fmtK(totalGrid)}</td><td>${fmtK(totalEaas)}</td>
      <td>${fmtK(totalSav)}</td>
      <td style="color:${cumulativeNPV >= 0 ? '#2e7d32' : '#c62828'}">${fmtM(cumulativeNPV)}</td>`;
    tableBody.appendChild(sumRow);
  }
}

/**
 * Raport: O ile fotowoltaika obniża koszty zakupu energii z RDN i opłatę mocową.
 * Prosty, czytelny Excel dla klienta.
 */
async function exportPvImpactExcel() {
  try {
    const r = tcslMetrics[currentVariant];
    if (!r) { alert('Brak danych. Poczekaj na zakonczenie analizy.'); return; }
    if (r.rdn_tcsl_annual_pln == null) { alert('Scenariusz RDN nie jest wlaczony. Wlacz go w Ustawieniach.'); return; }

    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Wplyw PV na koszty RDN');
    const fmt = v => Math.round(v || 0);
    const fmt2 = v => +(v || 0).toFixed(2);
    const mNames = ['Styczen','Luty','Marzec','Kwiecien','Maj','Czerwiec',
                     'Lipiec','Sierpien','Wrzesien','Pazdziernik','Listopad','Grudzien'];

    // --- Stawki opłat z ustawień ---
    const s = systemSettings || {};
    const distRate = s.distribution || 200;
    const qualRate = s.qualityFee || 10;
    const ozeRate = s.ozeFee || 7;
    const cogenRate = s.cogenerationFee || 10;
    const exciseRate = s.exciseTax || 5;

    // --- Wolumeny energii ---
    const gridNoPvMwh = kwhToMwh(r.annual_consumption_kwh || 0);
    const gridWPvMwh = kwhToMwh(r.annual_grid_import_kwh || 0);
    const selfConsumedMwh = kwhToMwh(r.annual_self_consumed_kwh || 0);
    const pvProductionMwh = kwhToMwh(r.annual_production_kwh || 0);

    // --- Obliczenie per opłata: Bez PV = gridNoPv * stawka, Z PV = gridWPv * stawka ---
    const distNoPv = gridNoPvMwh * distRate;
    const distWPv = gridWPvMwh * distRate;
    const qualNoPv = gridNoPvMwh * qualRate;
    const qualWPv = gridWPvMwh * qualRate;
    const ozeNoPv = gridNoPvMwh * ozeRate;
    const ozeWPv = gridWPvMwh * ozeRate;
    const cogenNoPv = gridNoPvMwh * cogenRate;
    const cogenWPv = gridWPvMwh * cogenRate;
    const excNoPv = gridNoPvMwh * exciseRate;
    const excWPv = gridWPvMwh * exciseRate;

    // Energia czynna RDN (ceny godzinowe - z backendu)
    const enNoPv = r.nopv_rdn_energy_active_pln || 0;
    const enWPv = r.rdn_energy_active_cost_pln || 0;

    // Opłata mocowa
    const capNoPv = r.capacity_fee_without_pv_pln || 0;
    const capWPv = r.capacity_fee_with_pv_pln || 0;

    // --- Kolumny tabeli ---
    ws.columns = [
      { header: 'Skladnik kosztu', key: 'label', width: 48 },
      { header: 'Stawka [PLN/MWh]', key: 'rate', width: 18 },
      { header: 'Bez PV [PLN]', key: 'nopv', width: 16 },
      { header: 'Z PV [PLN]', key: 'wpv', width: 16 },
      { header: 'Oszczednosc [PLN]', key: 'saving', width: 18 },
    ];
    const hdr = ws.getRow(1);
    hdr.font = { bold: true, size: 11 };
    hdr.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
    hdr.alignment = { wrapText: true };

    // ==========================================
    // TYTUL
    // ==========================================
    ws.addRow({});
    const title = ws.addRow({ label: 'WPLYW FOTOWOLTAIKI NA KOSZTY ENERGII Z RDN - PELNE ROZBICIE' });
    title.font = { bold: true, size: 14 };
    ws.mergeCells(title.number, 1, title.number, 5);
    ws.addRow({});

    // --- Info o wolumenach ---
    const infoRow1 = ws.addRow({ label: `Pobor z sieci BEZ PV: ${gridNoPvMwh.toFixed(1)} MWh`, rate: '', nopv: '', wpv: '', saving: '' });
    infoRow1.font = { italic: true, size: 10, color: { argb: 'FF616161' } };
    const infoRow2 = ws.addRow({ label: `Pobor z sieci Z PV:   ${gridWPvMwh.toFixed(1)} MWh  (autokonsumpcja: ${selfConsumedMwh.toFixed(1)} MWh)`, rate: '', nopv: '', wpv: '', saving: '' });
    infoRow2.font = { italic: true, size: 10, color: { argb: 'FF616161' } };
    ws.addRow({});

    // --- Helper: wiersz tabeli ---
    const addFeeRow = (label, rate, nopv, wpv, opts = {}) => {
      const sav = nopv - wpv;
      const row = ws.addRow({
        label,
        rate: rate != null ? fmt2(rate) : '',
        nopv: fmt(nopv),
        wpv: fmt(wpv),
        saving: fmt(sav),
      });
      if (opts.bold) row.font = { bold: true, size: opts.size || 11 };
      if (opts.bg) {
        for (let c = 1; c <= 5; c++) {
          row.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: opts.bg } };
        }
      }
      row.getCell('saving').font = { bold: true, color: { argb: sav > 0 ? 'FF2E7D32' : 'FFC62828' }, size: opts.size || 11 };
      return row;
    };

    // ==========================================
    // CZESC 1: KOSZTY ZMIENNE (per MWh)
    // ==========================================
    const s1 = ws.addRow({ label: 'KOSZTY ZMIENNE (naliczane od kazdej MWh pobranej z sieci)' });
    s1.font = { bold: true, size: 12 };
    for (let c = 1; c <= 5; c++) s1.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFBBDEFB' } };
    ws.addRow({});

    addFeeRow('Energia czynna (ceny godzinowe RDN)', null, enNoPv, enWPv);
    ws.addRow({ label: '  (cena zmienna godzinowa z Rynku Dnia Nastepnego - nie jest stalą stawka)' }).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
    ws.addRow({});
    addFeeRow('Oplata dystrybucyjna zmienna', distRate, distNoPv, distWPv);
    addFeeRow('Oplata jakosciowa', qualRate, qualNoPv, qualWPv);
    addFeeRow('Oplata OZE', ozeRate, ozeNoPv, ozeWPv);
    addFeeRow('Oplata kogeneracyjna', cogenRate, cogenNoPv, cogenWPv);
    addFeeRow('Akcyza', exciseRate, excNoPv, excWPv);
    ws.addRow({});

    const sumVarNoPv = enNoPv + distNoPv + qualNoPv + ozeNoPv + cogenNoPv + excNoPv;
    const sumVarWPv = enWPv + distWPv + qualWPv + ozeWPv + cogenWPv + excWPv;
    addFeeRow('SUMA KOSZTOW ZMIENNYCH', null, sumVarNoPv, sumVarWPv, { bold: true, size: 12, bg: 'FFC8E6C9' });

    // ==========================================
    // CZESC 2: OPLATA MOCOWA
    // ==========================================
    ws.addRow({});
    const s2 = ws.addRow({ label: 'OPLATA MOCOWA (zalezy od klasy K - profilu poboru w szczycie 7:00-22:00)' });
    s2.font = { bold: true, size: 12 };
    for (let c = 1; c <= 5; c++) s2.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
    ws.addRow({});

    const stochTag = r.kclass_stochastic_nopv ? ' *stoch.' : '';
    addFeeRow(`Oplata mocowa (bez PV: klasa ${r.kclass_without_pv}, z PV: klasa ${r.kclass_with_pv})${stochTag}`, null, capNoPv, capWPv);
    const capNote = r.kclass_stochastic_nopv
      ? `  (Korekta stochastyczna: K1=${(r.kclass_stochastic_nopv.probabilities.K1*100).toFixed(0)}% K2=${(r.kclass_stochastic_nopv.probabilities.K2*100).toFixed(0)}% K3=${(r.kclass_stochastic_nopv.probabilities.K3*100).toFixed(0)}% K4=${(r.kclass_stochastic_nopv.probabilities.K4*100).toFixed(0)}%, eff.coeff=${r.kclass_stochastic_nopv.effective_coefficient.toFixed(3)})`
      : '  (PV obniza pobor w szczycie dnia co zmniejsza klase K i stawke oplaty mocowej)';
    ws.addRow({ label: capNote }).font = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };
    ws.addRow({});

    const capPct = capNoPv > 0 ? Math.round(decimalToPct((capNoPv - capWPv) / capNoPv)) : 0;
    addFeeRow(`OSZCZEDNOSC NA OPLACIE MOCOWEJ (${capPct}% redukcji)`, null, capNoPv, capWPv, { bold: true, size: 12, bg: 'FFFFF9C4' });

    // ==========================================
    // CZESC 3: PODSUMOWANIE
    // ==========================================
    ws.addRow({});
    ws.addRow({});
    const totalNoPv = sumVarNoPv + capNoPv;
    const totalWPv = sumVarWPv + capWPv;
    addFeeRow('RAZEM ROCZNY KOSZT (zmienne + mocowa)', null, totalNoPv, totalWPv, { bold: true, size: 14, bg: 'FF81C784' });

    ws.addRow({});
    const totalSav = totalNoPv - totalWPv;
    const totalPct = totalNoPv > 0 ? Math.round(decimalToPct(totalSav / totalNoPv)) : 0;
    const summRow = ws.addRow({ label: `LACZNA ROCZNA OSZCZEDNOSC DZIEKI PV (${totalPct}% redukcji kosztow)`, rate: '', nopv: '', wpv: '', saving: fmt(totalSav) });
    summRow.font = { bold: true, size: 16 };
    summRow.getCell('saving').font = { bold: true, size: 16, color: { argb: 'FF1B5E20' } };
    for (let c = 1; c <= 5; c++) summRow.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF66BB6A' } };

    // ==========================================
    // CZESC 4: BILANS ENERGII
    // ==========================================
    ws.addRow({});
    ws.addRow({});
    const s4 = ws.addRow({ label: 'BILANS ENERGII' });
    s4.font = { bold: true, size: 12 };
    for (let c = 1; c <= 5; c++) s4.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0E0E0' } };
    ws.addRow({});

    const addInfo = (label, val) => ws.addRow({ label, rate: '', nopv: '', wpv: '', saving: val });
    addInfo('Roczne zuzycie energii [MWh]', gridNoPvMwh.toFixed(1));
    addInfo('Roczna produkcja fotowoltaiki [MWh]', pvProductionMwh.toFixed(1));
    addInfo('Energia z PV zuzyta na miejscu [MWh]', selfConsumedMwh.toFixed(1));
    addInfo('Energia pobrana z sieci Z PV [MWh]', gridWPvMwh.toFixed(1));
    addInfo('Redukcja poboru z sieci [MWh]', selfConsumedMwh.toFixed(1));

    // ==========================================
    // SHEET 2: Miesieczne
    // ==========================================
    const ws2 = wb.addWorksheet('Miesieczne');
    ws2.columns = [
      { header: 'Miesiac', key: 'month', width: 14 },
      { header: 'Pobor z sieci\nbez PV [MWh]', key: 'grid_nopv', width: 16 },
      { header: 'Pobor z sieci\nz PV [MWh]', key: 'grid_wpv', width: 16 },
      { header: 'Koszt RDN\nbez PV [PLN]', key: 'cost_nopv', width: 16 },
      { header: 'Koszt RDN\nz PV [PLN]', key: 'cost_wpv', width: 16 },
      { header: 'Oszczednosc\nna energii [PLN]', key: 'saving_energy', width: 18 },
      { header: 'Oplata mocowa\nbez PV [PLN]', key: 'cap_nopv', width: 16 },
      { header: 'Oplata mocowa\nz PV [PLN]', key: 'cap_wpv', width: 16 },
      { header: 'Oszczednosci na\noplacie mocowej', key: 'cap_saving', width: 18 },
    ];
    const h2 = ws2.getRow(1);
    h2.font = { bold: true, size: 10 };
    h2.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
    h2.alignment = { wrapText: true };

    const months = r.monthly_breakdown || [];
    const nopvM = r.nopv_monthly_breakdown || [];
    let sGNP = 0, sGWP = 0, sCNP = 0, sCWP = 0, sSE = 0, sCAPnp = 0, sCAPwp = 0, sCAPsav = 0;

    for (let m = 0; m < 12; m++) {
      const wpvR = months[m]?.rdn || {};
      const npvR = nopvM[m]?.rdn_nopv || {};

      const gridNoPv = kwhToMwh(npvR.consumption_kwh || npvR.grid_import_kwh || 0);
      const gridWPv = kwhToMwh(wpvR.grid_import_kwh || 0);
      const costNoPv = (npvR.energy_active_pln || 0) + (npvR.fees_var_pln || 0);
      const costWPv = (wpvR.energy_active_pln || 0) + (wpvR.fees_var_pln || 0);
      const savEnergy = costNoPv - costWPv;
      const capNoPv = npvR.capacity_fee_pln || nopvM[m]?.tariff_nopv?.capacity_fee_pln || 0;
      const capWPv = wpvR.capacity_fee_pln || months[m]?.tariff?.capacity_fee_pln || 0;
      const capSav = capNoPv - capWPv;

      sGNP += gridNoPv; sGWP += gridWPv; sCNP += costNoPv; sCWP += costWPv; sSE += savEnergy;
      sCAPnp += capNoPv; sCAPwp += capWPv; sCAPsav += capSav;

      const row = ws2.addRow({
        month: mNames[m],
        grid_nopv: +gridNoPv.toFixed(1),
        grid_wpv: +gridWPv.toFixed(1),
        cost_nopv: fmt(costNoPv),
        cost_wpv: fmt(costWPv),
        saving_energy: fmt(savEnergy),
        cap_nopv: fmt(capNoPv),
        cap_wpv: fmt(capWPv),
        cap_saving: fmt(capSav),
      });
      row.getCell('saving_energy').font = { bold: true, color: { argb: 'FF2E7D32' } };
      row.getCell('cap_saving').font = { bold: true, color: { argb: 'FF2E7D32' } };
    }

    ws2.addRow({});
    const sumRow = ws2.addRow({
      month: 'SUMA ROK',
      grid_nopv: +sGNP.toFixed(1),
      grid_wpv: +sGWP.toFixed(1),
      cost_nopv: fmt(sCNP),
      cost_wpv: fmt(sCWP),
      saving_energy: fmt(sSE),
      cap_nopv: fmt(sCAPnp),
      cap_wpv: fmt(sCAPwp),
      cap_saving: fmt(sCAPsav),
    });
    sumRow.font = { bold: true, size: 12 };
    sumRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };

    // ==========================================
    // SHEET 3: NPV CAPEX (scenariusz RDN)
    // ==========================================
    const rdnCalc = centralizedMetricsRdn[currentVariant];
    if (rdnCalc && rdnCalc.capex) {
      const ws3 = wb.addWorksheet('NPV CAPEX (RDN)');
      ws3.columns = [
        { header: 'Rok', key: 'year', width: 6 },
        { header: 'Deg PV [%]', key: 'deg', width: 10 },
        { header: 'Oszcz. Energ.+Opl. [PLN]', key: 'en_sav', width: 24 },
        { header: 'Oszcz. Mocowa [PLN]', key: 'cap_sav', width: 18 },
        { header: 'Suma Oszcz. [PLN]', key: 'total_sav', width: 16 },
        { header: 'OPEX [PLN]', key: 'opex', width: 14 },
        { header: 'CF Netto [PLN]', key: 'net_cf', width: 16 },
        { header: 'NPV Skum. [PLN]', key: 'npv', width: 18 },
      ];
      const h3 = ws3.getRow(1);
      h3.font = { bold: true, size: 10 };
      h3.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
      h3.alignment = { wrapText: true };

      // Parameters info
      const base = rdnCalc.capex.rdnBaseline;
      ws3.addRow({});
      const t3 = ws3.addRow({ year: 'ANALIZA CAPEX ROK PO ROKU - SCENARIUSZ RDN' });
      t3.font = { bold: true, size: 13 };
      ws3.addRow({ year: `Inwestycja: ${fmt(rdnCalc.capex.investment)} PLN | Stopa dyskonta: ${(rdnCalc.common.discountRate*100).toFixed(1)}% | CPI: ${(rdnCalc.common.inflationRate*100).toFixed(1)}%` });
      ws3.addRow({ year: `Oszcz. rok 1: ${fmt(base.totalSavingsYear1)} PLN (energia+opl: ${fmt(base.energyFeesSavingsYear1)} + mocowa: ${fmt(base.capacitySavingsYear1)})` });
      ws3.addRow({ year: `Klasa K: bez PV = ${base.kclassNoPv}, z PV = ${base.kclassWithPv}` });
      ws3.addRow({});

      // Year 0
      const y0 = ws3.addRow({ year: 0, deg: '', en_sav: '', cap_sav: '', total_sav: '', opex: '', net_cf: -fmt(rdnCalc.capex.investment), npv: -fmt(rdnCalc.capex.investment) });
      y0.font = { bold: true };
      y0.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

      let cumNPV = -rdnCalc.capex.investment;
      rdnCalc.capex.cashFlows.forEach(cf => {
        const disc = cf.net_cash_flow / Math.pow(1 + rdnCalc.common.discountRate, cf.year);
        cumNPV += disc;
        const row = ws3.addRow({
          year: cf.year,
          deg: +(cf.pvDegradationPct).toFixed(1),
          en_sav: fmt(cf.energyFeesSavings),
          cap_sav: fmt(cf.capacitySavings),
          total_sav: fmt(cf.savings),
          opex: fmt(cf.opex),
          net_cf: fmt(cf.net_cash_flow),
          npv: fmt(cumNPV),
        });
        row.getCell('net_cf').font = { color: { argb: cf.net_cash_flow >= 0 ? 'FF2E7D32' : 'FFC62828' } };
        row.getCell('npv').font = { bold: true, color: { argb: cumNPV >= 0 ? 'FF2E7D32' : 'FFC62828' } };
      });

      ws3.addRow({});
      const s3 = ws3.addRow({ year: 'NPV', deg: '', en_sav: '', cap_sav: '', total_sav: '', opex: '', net_cf: '', npv: fmt(cumNPV) });
      s3.font = { bold: true, size: 12 };
      s3.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: cumNPV >= 0 ? 'FFC8E6C9' : 'FFFFCDD2' } };
    }

    // ==========================================
    // SHEET 4: NPV EaaS (scenariusz RDN)
    // ==========================================
    if (rdnCalc && rdnCalc.eaas) {
      const ws4 = wb.addWorksheet('NPV EaaS (RDN)');
      ws4.columns = [
        { header: 'Rok', key: 'year', width: 6 },
        { header: 'Faza', key: 'phase', width: 10 },
        { header: 'Deg PV [%]', key: 'deg', width: 10 },
        { header: 'Oszcz. Energ.+Opl. [PLN]', key: 'en_sav', width: 24 },
        { header: 'Oszcz. Mocowa [PLN]', key: 'cap_sav', width: 18 },
        { header: 'Suma Oszcz. [PLN]', key: 'total_sav', width: 16 },
        { header: 'Koszt EaaS/O&M [PLN]', key: 'eaas_cost', width: 20 },
        { header: 'CF Netto [PLN]', key: 'net_cf', width: 16 },
        { header: 'NPV Skum. [PLN]', key: 'npv', width: 18 },
      ];
      const h4 = ws4.getRow(1);
      h4.font = { bold: true, size: 10 };
      h4.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
      h4.alignment = { wrapText: true };

      const base = rdnCalc.eaas.rdnBaseline;
      ws4.addRow({});
      const t4 = ws4.addRow({ year: 'ANALIZA EaaS ROK PO ROKU - SCENARIUSZ RDN' });
      t4.font = { bold: true, size: 13 };
      ws4.addRow({ year: `Abonament EaaS: ${fmt(rdnCalc.eaas.baseSubscription)} PLN/rok | Kontrakt: ${rdnCalc.eaas.duration} lat | CPI: ${(rdnCalc.common.inflationRate*100).toFixed(1)}%` });
      ws4.addRow({ year: `Oszcz. rok 1: ${fmt(base.totalSavingsYear1)} PLN | Klasa K: bez PV = ${base.kclassNoPv}, z PV = ${base.kclassWithPv}` });
      ws4.addRow({});

      let cumNPV4 = 0;
      rdnCalc.eaas.cashFlows.forEach(cf => {
        cumNPV4 += cf.discountedCF;
        const phaseLabel = cf.phase === 'eaas' ? 'EaaS' : 'Wlasnosc';
        const row = ws4.addRow({
          year: cf.year,
          phase: phaseLabel,
          deg: +(cf.pvDegradationPct).toFixed(1),
          en_sav: fmt(cf.energyFeesSavings),
          cap_sav: fmt(cf.capacitySavings),
          total_sav: fmt(cf.gridCost),
          eaas_cost: fmt(cf.eaasCost),
          net_cf: fmt(cf.savings),
          npv: fmt(cumNPV4),
        });
        if (cf.phase === 'eaas') {
          row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFDE7' } };
        } else {
          row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
        }
        row.getCell('net_cf').font = { color: { argb: cf.savings >= 0 ? 'FF2E7D32' : 'FFC62828' } };
        row.getCell('npv').font = { bold: true, color: { argb: cumNPV4 >= 0 ? 'FF2E7D32' : 'FFC62828' } };
      });

      ws4.addRow({});
      const s4 = ws4.addRow({ year: 'NPV', phase: '', deg: '', en_sav: '', cap_sav: '', total_sav: '', eaas_cost: '', net_cf: '', npv: fmt(cumNPV4) });
      s4.font = { bold: true, size: 12 };
      s4.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: cumNPV4 >= 0 ? 'FFC8E6C9' : 'FFFFCDD2' } };
    }

    // ==========================================
    // SHEET 5: Koszt PV (rozbicie CAPEX vs EaaS)
    // ==========================================
    const ws5 = wb.addWorksheet('Koszt PV');
    ws5.columns = [
      { header: 'Skladnik', key: 'label', width: 44 },
      { header: 'Wartosc', key: 'value', width: 20 },
    ];
    const h5 = ws5.getRow(1);
    h5.font = { bold: true, size: 11 };
    h5.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

    const s5 = systemSettings || {};
    const capKwp = variants[currentVariant]?.capacity || 0;
    const capexPerKwp = getCapexForCapacity(capKwp);
    const totalCapex = capKwp * capexPerKwp;
    const analysisPrd = s5.analysisPeriod || 25;
    const opexPerKwp5 = s5.opexPerKwp || 24;
    const insuranceRate = window.economicsSettings?.insuranceRate || 0.005;
    const annualAmort = analysisPrd > 0 ? totalCapex / analysisPrd : 0;
    const annualOpex5 = capKwp * opexPerKwp5;
    const annualIns = totalCapex * insuranceRate;

    // Section A: CAPEX
    ws5.addRow({});
    const tA = ws5.addRow({ label: 'WARIANT CAPEX - ROCZNY KOSZT FOTOWOLTAIKI' });
    tA.font = { bold: true, size: 14 };
    tA.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFBBDEFB' } };
    ws5.addRow({});
    ws5.addRow({ label: 'Moc instalacji [kWp]', value: capKwp });
    ws5.addRow({ label: 'CAPEX jednostkowy [PLN/kWp]', value: fmt(capexPerKwp) });
    ws5.addRow({ label: 'CAPEX calkowity [PLN]', value: fmt(totalCapex) });
    ws5.addRow({ label: 'Okres analizy [lat]', value: analysisPrd });
    ws5.addRow({});
    ws5.addRow({ label: 'Amortyzacja roczna (CAPEX / okres) [PLN/rok]', value: fmt(annualAmort) });
    ws5.addRow({ label: `OPEX serwisowy (${opexPerKwp5} PLN/kWp x ${capKwp} kWp) [PLN/rok]`, value: fmt(annualOpex5) });
    ws5.addRow({ label: `Ubezpieczenie (${(insuranceRate*100).toFixed(1)}% CAPEX) [PLN/rok]`, value: fmt(annualIns) });
    ws5.addRow({});
    const capCostRow = ws5.addRow({ label: 'ROCZNY KOSZT PV (CAPEX)', value: fmt(annualAmort + annualOpex5 + annualIns) });
    capCostRow.font = { bold: true, size: 13 };
    capCostRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };

    // Section B: EaaS
    ws5.addRow({});
    ws5.addRow({});
    const tB = ws5.addRow({ label: 'WARIANT EaaS - ROCZNY KOSZT FOTOWOLTAIKI' });
    tB.font = { bold: true, size: 14 };
    tB.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFECB3' } };
    ws5.addRow({});

    const eaasDur = parseInt(document.getElementById('eaasDuration')?.value) || 10;
    const eaasSub = rdnCalc?.eaas?.baseSubscription || centralizedMetrics[currentVariant]?.eaas?.baseSubscription || 0;
    const eaasOM = rdnCalc?.eaas?.baseOmCost || centralizedMetrics[currentVariant]?.eaas?.baseOmCost || annualOpex5;
    const eaasIns = rdnCalc?.eaas?.baseInsuranceCost || centralizedMetrics[currentVariant]?.eaas?.baseInsuranceCost || annualIns;

    ws5.addRow({ label: 'Czas trwania kontraktu EaaS [lat]', value: eaasDur });
    ws5.addRow({ label: 'Abonament roczny EaaS (faza kontraktu) [PLN/rok]', value: fmt(eaasSub) });
    ws5.addRow({ label: '  (abonament zawiera: O&M + ubezpieczenie + amortyzacje inwestora)' }).font = { italic: true, size: 10, color: { argb: 'FF757575' } };
    ws5.addRow({});
    ws5.addRow({ label: 'Po zakonczeniu kontraktu (wlasnosc klienta):' }).font = { bold: true };
    ws5.addRow({ label: `  O&M serwisowy [PLN/rok]`, value: fmt(eaasOM) });
    ws5.addRow({ label: `  Ubezpieczenie [PLN/rok]`, value: fmt(eaasIns) });
    ws5.addRow({});
    const eaasCostRow1 = ws5.addRow({ label: 'ROCZNY KOSZT PV (EaaS, faza kontraktu)', value: fmt(eaasSub) });
    eaasCostRow1.font = { bold: true, size: 12 };
    eaasCostRow1.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFDE7' } };
    const eaasCostRow2 = ws5.addRow({ label: 'ROCZNY KOSZT PV (EaaS, po kontrakcie)', value: fmt(eaasOM + eaasIns) });
    eaasCostRow2.font = { bold: true, size: 12 };
    eaasCostRow2.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

    // Apply watermark
    if (window.applyExcelWatermark) {
      try { window.applyExcelWatermark(wb, {}); }
      catch (e) { console.warn('⚠️ Watermark:', e); }
    }

    // Download
    const buf = await wb.xlsx.writeBuffer();
    const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Wplyw_PV_na_RDN_${currentVariant || 'B'}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error('PV Impact Excel error:', err);
    alert('Blad eksportu: ' + err.message);
  }
}

/**
 * Build hourly tariff energy-active prices based on tariffConfig (flat/two_zone/three_zone).
 * Returns array of numHours PLN/MWh values, one per hour.
 * For ToU tariffs, weekends are treated as off-peak/night rate.
 */
function buildHourlyTariffPrices(numHours, startYear) {
  const tc = systemSettings?.tariffConfig;
  const type = tc?.type || 'flat';

  // Determine Jan 1 day-of-week for the given year (0=Sunday)
  const jan1 = new Date(startYear || 2025, 0, 1);
  const jan1DayOfWeek = jan1.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat

  const prices = new Array(numHours);

  if (type === 'flat') {
    const rate = tc?.flatRate || 750;
    prices.fill(rate);
    return prices;
  }

  if (type === 'two_zone' && tc?.twoZone) {
    const dayRate = tc.twoZone.dayRate || 850;
    const nightRate = tc.twoZone.nightRate || 450;
    const wdStart = tc.twoZone.weekday?.start ?? 6;
    const wdEnd = tc.twoZone.weekday?.end ?? 22;
    const weStart = tc.twoZone.weekend?.start ?? 6;
    const weEnd = tc.twoZone.weekend?.end ?? 13;

    for (let h = 0; h < numHours; h++) {
      const dayOfYear = Math.floor(h / 24);
      const hourOfDay = h % 24;
      const dayOfWeek = (jan1DayOfWeek + dayOfYear) % 7;
      const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);

      if (isWeekend) {
        prices[h] = (hourOfDay >= weStart && hourOfDay < weEnd) ? dayRate : nightRate;
      } else {
        prices[h] = (hourOfDay >= wdStart && hourOfDay < wdEnd) ? dayRate : nightRate;
      }
    }
    return prices;
  }

  if (type === 'three_zone' && tc?.threeZone) {
    const peakRate = tc.threeZone.peakRate || 950;
    const partialRate = tc.threeZone.partialRate || 700;
    const offPeakRate = tc.threeZone.offPeakRate || 400;
    const peak1Start = tc.threeZone.peak1?.start ?? 7;
    const peak1End = tc.threeZone.peak1?.end ?? 13;
    const peak2Start = tc.threeZone.peak2?.start ?? 17;
    const peak2End = tc.threeZone.peak2?.end ?? 21;
    const partialStart = tc.threeZone.partial?.start ?? 13;
    const partialEnd = tc.threeZone.partial?.end ?? 17;

    for (let h = 0; h < numHours; h++) {
      const dayOfYear = Math.floor(h / 24);
      const hourOfDay = h % 24;
      const dayOfWeek = (jan1DayOfWeek + dayOfYear) % 7;
      const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);

      if (isWeekend) {
        // Weekends: all off-peak (standard for C12b)
        prices[h] = offPeakRate;
      } else if ((hourOfDay >= peak1Start && hourOfDay < peak1End) ||
                 (hourOfDay >= peak2Start && hourOfDay < peak2End)) {
        prices[h] = peakRate;
      } else if (hourOfDay >= partialStart && hourOfDay < partialEnd) {
        prices[h] = partialRate;
      } else {
        prices[h] = offPeakRate;
      }
    }
    return prices;
  }

  // Fallback
  prices.fill(510);
  return prices;
}

/**
 * Get zone label for a given hour (for Excel display)
 */
function getTariffZoneLabel(hourOfDay, isWeekend, tariffType) {
  if (tariffType === 'flat') return 'Jednolita';
  if (isWeekend) return tariffType === 'two_zone' ? 'Weekend' : 'Dolina (weekend)';

  const tc = systemSettings?.tariffConfig;
  if (tariffType === 'two_zone') {
    const wdStart = tc?.twoZone?.weekday?.start ?? 6;
    const wdEnd = tc?.twoZone?.weekday?.end ?? 22;
    return (hourOfDay >= wdStart && hourOfDay < wdEnd) ? 'Dzień' : 'Noc';
  }
  if (tariffType === 'three_zone') {
    const p1s = tc?.threeZone?.peak1?.start ?? 7;
    const p1e = tc?.threeZone?.peak1?.end ?? 13;
    const p2s = tc?.threeZone?.peak2?.start ?? 17;
    const p2e = tc?.threeZone?.peak2?.end ?? 21;
    const ps = tc?.threeZone?.partial?.start ?? 13;
    const pe = tc?.threeZone?.partial?.end ?? 17;
    if ((hourOfDay >= p1s && hourOfDay < p1e) || (hourOfDay >= p2s && hourOfDay < p2e)) return 'Szczyt';
    if (hourOfDay >= ps && hourOfDay < pe) return 'Pośrednia';
    return 'Dolina';
  }
  return '-';
}

/** @deprecated Use exportTcslHourlyExcel() instead */
async function exportRdnHourlyExcel() { return exportTcslHourlyExcel(); }

/** @deprecated Old export - kept for backwards compatibility */
async function _oldExportRdnHourlyExcel() {
  try {
    // 1. ALWAYS fetch fresh RDN prices from API (localStorage may have stale data)
    const rdnConfig = systemSettings?.rdnPricingConfig;
    if (!rdnConfig?.scenarioId) {
      alert('Brak scenariusza RDN. Wybierz scenariusz w Settings.');
      return;
    }
    const resp = await fetch(`/api/db/prices/${rdnConfig.scenarioId}/hourly-array`);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const apiData = await resp.json();
    const rdnPrices = apiData.prices_plnmwh || [];
    if (rdnPrices.length < 720) throw new Error(`Za mało danych RDN: ${rdnPrices.length}`);

    // Update localStorage cache with fresh data
    localStorage.setItem('rdn_hourly_prices', JSON.stringify(rdnPrices));
    console.log(`📊 Fresh RDN prices: ${rdnPrices.length}h, min=${Math.min(...rdnPrices).toFixed(0)}, max=${Math.max(...rdnPrices).toFixed(0)}, avg=${(rdnPrices.reduce((a,b)=>a+b,0)/rdnPrices.length).toFixed(0)}`);

    // 2. Hourly consumption - try memory first, then API fallback
    let hourlyConsumption = hourlyData?.values || hourlyData || [];
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      console.log('📊 RDN Excel: No hourly consumption in memory, trying /api/data/export-data...');
      try {
        const consResp = await fetch('/api/data/export-data');
        if (consResp.ok) {
          const consData = await consResp.json();
          hourlyConsumption = consData.values || [];
          if (hourlyConsumption.length >= 720) {
            // Cache in hourlyData for future use
            hourlyData = { values: hourlyConsumption };
            console.log(`📊 RDN Excel: Loaded ${hourlyConsumption.length}h from API`);
          }
        }
      } catch (e) {
        console.warn('📊 RDN Excel: /api/data/export-data failed:', e.message);
      }
    }
    if (!Array.isArray(hourlyConsumption) || hourlyConsumption.length < 720) {
      alert('Brak danych godzinowych konsumpcji. Uruchom najpierw analizę w module Konfiguracja.');
      return;
    }

    // 3. Hourly production
    const variantKey = currentVariant || 'B';
    const variantData = analysisResults?.key_variants?.[variantKey];
    let hourlyProduction = variantData?.hourly_production || [];
    const scenarioFactor = window.currentScenarioFactor || 1.0;
    if (scenarioFactor !== 1.0 && hourlyProduction.length > 0) {
      hourlyProduction = hourlyProduction.map(v => v * scenarioFactor);
    }
    if (hourlyProduction.length < 720) {
      const annualProdKwh = (variantData?.production || 0) * scenarioFactor;
      hourlyProduction = new Array(8760).fill(annualProdKwh / 8760);
    }

    const len = Math.min(rdnPrices.length, hourlyConsumption.length, hourlyProduction.length);

    // 4. Fees
    const s = systemSettings || {};
    const fees = (s.distribution||200) + (s.qualityFee||10) + (s.ozeFee||7) +
                 (s.cogenerationFee||10) + (s.capacityFee||219) + (s.exciseTax||5);

    // 5. Hourly tariff prices (zone-based)
    const rdnYear = rdnConfig.year || 2025;
    const tariffPrices = buildHourlyTariffPrices(len, rdnYear);
    const jan1Dow = new Date(rdnYear, 0, 1).getDay();
    const tc = s.tariffConfig;
    const tariffType = tc?.type || 'flat';

    // 6. Build simple workbook
    const workbook = new ExcelJS.Workbook();
    const ws = workbook.addWorksheet('RDN vs Taryfa');

    ws.columns = [
      { header: 'Data', key: 'date', width: 18 },
      { header: 'Godz.', key: 'hour', width: 6 },
      { header: 'Kons. [kWh]', key: 'load', width: 12 },
      { header: 'PV [kWh]', key: 'pv', width: 10 },
      { header: 'Z sieci [kWh]', key: 'grid', width: 12 },
      { header: 'Cena Taryfa [PLN/MWh]', key: 'price_t', width: 20 },
      { header: 'Cena RDN [PLN/MWh]', key: 'price_r', width: 18 },
      { header: 'Koszt Taryfa [PLN]', key: 'cost_t', width: 16 },
      { header: 'Koszt RDN [PLN]', key: 'cost_r', width: 14 },
      { header: 'RÓŻNICA [PLN]', key: 'diff', width: 14 }
    ];

    const hdr = ws.getRow(1);
    hdr.font = { bold: true };
    hdr.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };

    const monthDays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (rdnYear % 4 === 0 && (rdnYear % 100 !== 0 || rdnYear % 400 === 0)) monthDays[1] = 29;

    let totCostT = 0, totCostR = 0;

    for (let h = 0; h < len; h++) {
      const load = hourlyConsumption[h] || 0;
      const pv = hourlyProduction[h] || 0;
      const grid = Math.max(0, load - pv); // what you actually take from grid

      const tariffTotal = (tariffPrices[h] || 510) + fees;
      const rdnTotal = (rdnPrices[h] || 0) + fees;

      const costT = grid * tariffTotal / 1000;
      const costR = grid * rdnTotal / 1000;
      const diff = costR - costT; // positive = RDN droższe

      totCostT += costT;
      totCostR += costR;

      // Date string
      const dayOfYear = Math.floor(h / 24);
      const hourOfDay = h % 24;
      let month = 0, dayAccum = 0;
      for (let m = 0; m < 12; m++) {
        if (dayOfYear < dayAccum + monthDays[m]) { month = m; break; }
        dayAccum += monthDays[m];
      }
      const dayOfMonth = dayOfYear - dayAccum + 1;
      const dateStr = `${rdnYear}-${String(month+1).padStart(2,'0')}-${String(dayOfMonth).padStart(2,'0')}`;

      const row = ws.addRow({
        date: dateStr,
        hour: hourOfDay,
        load: Math.round(load * 100) / 100,
        pv: Math.round(pv * 100) / 100,
        grid: Math.round(grid * 100) / 100,
        price_t: Math.round(tariffTotal * 10) / 10,
        price_r: Math.round(rdnTotal * 10) / 10,
        cost_t: Math.round(costT * 100) / 100,
        cost_r: Math.round(costR * 100) / 100,
        diff: Math.round(diff * 100) / 100
      });

      // Color: green = RDN tańsze, red = RDN droższe
      const diffCell = row.getCell('diff');
      if (diff < -0.01) diffCell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      else if (diff > 0.01) diffCell.font = { color: { argb: 'FFC62828' } };
    }

    // SUMA
    ws.addRow({});
    const sumRow = ws.addRow({
      date: 'SUMA ROK', hour: '', load: '', pv: '', grid: '',
      price_t: '', price_r: '',
      cost_t: Math.round(totCostT),
      cost_r: Math.round(totCostR),
      diff: Math.round(totCostR - totCostT)
    });
    sumRow.font = { bold: true, size: 12 };
    sumRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };

    // Verdict
    const verdictRow = ws.addRow({
      date: totCostR < totCostT ? 'RDN TAŃSZE o:' : 'TARYFA TAŃSZA o:',
      hour: '', load: '', pv: '', grid: '', price_t: '', price_r: '', cost_t: '', cost_r: '',
      diff: Math.abs(Math.round(totCostR - totCostT))
    });
    verdictRow.font = { bold: true, size: 14, color: { argb: totCostR < totCostT ? 'FF2E7D32' : 'FFC62828' } };

    // Apply watermark
    if (window.applyExcelWatermark) {
      try { window.applyExcelWatermark(workbook, {}); }
      catch (e) { console.warn('⚠️ Watermark:', e); }
    }

    // Download
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `RDN_vs_Taryfa_${variantKey}_${new Date().toISOString().slice(0,10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    console.log(`📊 Excel: ${len}h, Taryfa=${Math.round(totCostT)} PLN, RDN=${Math.round(totCostR)} PLN, diff=${Math.round(totCostR-totCostT)} PLN`);
  } catch (err) {
    console.error('📊 RDN Excel error:', err);
    alert('Błąd: ' + err.message);
  }
}

/** @deprecated Use renderTcslWidget() instead */
function renderRdnComparisonWidget(result) { return renderTcslWidget(result); }

/** @deprecated Old rendering - kept for backwards compatibility */
function _oldRenderRdnComparisonWidget(result) {
  const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                       'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

  // Summary cards
  const fixedSavingsEl = document.getElementById('rdnFixedSavings');
  const dynamicSavingsEl = document.getElementById('rdnDynamicSavings');
  const deltaEl = document.getElementById('rdnDelta');
  const deltaPctEl = document.getElementById('rdnDeltaPct');
  const deltaVerdictEl = document.getElementById('rdnDeltaVerdict');
  const fixedPriceEl = document.getElementById('rdnFixedPrice');
  const avgPriceEl = document.getElementById('rdnAvgPrice');

  if (fixedSavingsEl) fixedSavingsEl.textContent = formatPLN(result.fixed_annual_savings_pln);
  if (dynamicSavingsEl) dynamicSavingsEl.textContent = formatPLN(result.rdn_annual_savings_pln);

  const delta = result.rdn_vs_fixed_delta_pln;
  const deltaPct = result.rdn_vs_fixed_delta_pct;
  if (deltaEl) {
    deltaEl.textContent = (delta >= 0 ? '+' : '') + formatPLN(delta);
    deltaEl.style.color = delta >= 0 ? '#2e7d32' : '#c62828';
  }
  if (deltaPctEl) {
    deltaPctEl.textContent = `${(deltaPct >= 0 ? '+' : '')}${deltaPct.toFixed(1)}% ${deltaPct >= 0 ? 'więcej' : 'mniej'} z RDN`;
  }
  if (deltaVerdictEl) {
    if (delta >= 0) {
      deltaVerdictEl.innerHTML = '<span style="color:#2e7d32;font-weight:600;">RDN korzystniejszy</span>';
    } else {
      deltaVerdictEl.innerHTML = '<span style="color:#c62828;font-weight:600;">Taryfa stała korzystniejsza</span>';
    }
  }

  if (fixedPriceEl) fixedPriceEl.textContent = `Cena stała: ${result.fixed_total_price_plnmwh.toFixed(0)} PLN/MWh`;
  if (avgPriceEl) avgPriceEl.textContent = `Śr. ważona RDN: ${result.rdn_avg_effective_price_plnmwh.toFixed(0)} PLN/MWh`;

  // Price statistics
  const stats = result.rdn_price_stats || {};
  const statAvg = document.getElementById('rdnStatAvg');
  const statMin = document.getElementById('rdnStatMin');
  const statMax = document.getElementById('rdnStatMax');
  const statMedian = document.getElementById('rdnStatMedian');
  if (statAvg) statAvg.textContent = (stats.avg != null ? stats.avg : (result.rdn_overall_avg_price || 0)).toFixed(0);
  if (statMin) statMin.textContent = (stats.min != null ? stats.min : 0).toFixed(0);
  if (statMax) statMax.textContent = (stats.max != null ? stats.max : 0).toFixed(0);
  if (statMedian) statMedian.textContent = (stats.median != null ? stats.median : 0).toFixed(0);

  // Monthly comparison chart
  renderRdnMonthlyChart(result.monthly_comparison, monthNames);

  // Monthly table
  renderRdnMonthlyTable(result.monthly_comparison, monthNames);
}

/**
 * Render monthly comparison bar chart (RDN vs Fixed)
 */
function renderRdnMonthlyChart(monthly, monthNames) {
  const canvas = document.getElementById('rdnMonthlyChart');
  if (!canvas) return;

  if (rdnMonthlyChart) {
    rdnMonthlyChart.destroy();
  }

  const shortMonths = monthNames.map(m => m.substring(0, 3));
  const fixedData = monthly.map(m => m.fixed_savings_pln);
  const rdnData = monthly.map(m => m.rdn_savings_pln);

  rdnMonthlyChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: shortMonths,
      datasets: [
        {
          label: 'Taryfa stała/ToU',
          data: fixedData,
          backgroundColor: 'rgba(21,101,192,0.7)',
          borderColor: 'rgba(21,101,192,1)',
          borderWidth: 1
        },
        {
          label: 'Ceny RDN',
          data: rdnData,
          backgroundColor: 'rgba(230,81,0,0.7)',
          borderColor: 'rgba(230,81,0,1)',
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        title: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              return `${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString('pl-PL', { maximumFractionDigits: 0 })} PLN`;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: 'Oszczędności [PLN]'
          },
          ticks: {
            callback: function(value) {
              return value.toLocaleString('pl-PL');
            }
          }
        }
      }
    }
  });
}

/**
 * Render monthly breakdown table
 */
function renderRdnMonthlyTable(monthly, monthNames) {
  const tbody = document.getElementById('rdnMonthlyTableBody');
  if (!tbody) return;

  let html = '';
  let totalFixed = 0, totalRdn = 0, totalSelfConsumed = 0;

  monthly.forEach((m, i) => {
    const delta = m.rdn_savings_pln - m.fixed_savings_pln;
    const deltaColor = delta >= 0 ? '#2e7d32' : '#c62828';
    totalFixed += m.fixed_savings_pln;
    totalRdn += m.rdn_savings_pln;
    totalSelfConsumed += m.self_consumed_kwh;

    html += `<tr style="border-bottom:1px solid #eee;">
      <td style="padding:6px 8px;">${monthNames[i]}</td>
      <td style="padding:6px 8px;text-align:right;">${m.self_consumed_kwh.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
      <td style="padding:6px 8px;text-align:right;">${m.fixed_savings_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
      <td style="padding:6px 8px;text-align:right;">${m.rdn_savings_pln.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
      <td style="padding:6px 8px;text-align:right;color:${deltaColor};font-weight:600;">${delta >= 0 ? '+' : ''}${delta.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
      <td style="padding:6px 8px;text-align:right;">${(m.rdn_avg_price_plnmwh || 0).toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
    </tr>`;
  });

  // Summary row
  const totalDelta = totalRdn - totalFixed;
  const totalDeltaColor = totalDelta >= 0 ? '#2e7d32' : '#c62828';
  html += `<tr style="border-top:2px solid #333;font-weight:700;background:#f9f9f9;">
    <td style="padding:8px;">RAZEM</td>
    <td style="padding:8px;text-align:right;">${totalSelfConsumed.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
    <td style="padding:8px;text-align:right;">${totalFixed.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
    <td style="padding:8px;text-align:right;">${totalRdn.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
    <td style="padding:8px;text-align:right;color:${totalDeltaColor};">${totalDelta >= 0 ? '+' : ''}${totalDelta.toLocaleString('pl-PL', { maximumFractionDigits: 0 })}</td>
    <td style="padding:8px;text-align:right;">-</td>
  </tr>`;

  tbody.innerHTML = html;
}

/**
 * Format PLN value for display
 */
function formatPLN(value) {
  if (value === null || value === undefined || isNaN(value)) return '-';
  return value.toLocaleString('pl-PL', { maximumFractionDigits: 0 }) + ' PLN';
}

// ============================================================================
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    // P0-1: BESS + Inverter Replacement
    calculateBessReplacementSchedule,
    calculateInverterReplacementSchedule,
    calculateReinvestmentSchedule,
    // P0-2: Residual Value
    calculateResidualValue,
    // P0-3: Nominal/Real Rate Helpers
    getEffectiveDiscountRate,
    nominalToRealRate,
    realToNominalRate
  };
}
