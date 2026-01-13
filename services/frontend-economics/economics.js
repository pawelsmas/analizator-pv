console.log('🚀 economics.js LOADED v=20260113-P1-FIX - timestamp:', new Date().toISOString());

// DEBUG flag - set to true for verbose logging (or via URL ?debug_economics=1)
const DEBUG_ECONOMICS = window.location?.search?.includes('debug_economics=1') || false;

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

// Data storage
let economicData = null;
let pvConfig = null;
let analysisResults = null;
let variants = {};
let currentVariant = 'A'; // Default variant
let consumptionData = null;
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

// EaaS yearly data for Bankability calculations
let eaasYearlyData = [];

// Initialize window.economicsSettings with defaults
window.economicsSettings = {
  discountRate: 0.07, // 7%
  insuranceRate: 0.005, // 0.5%
  inflationRate: 0.03, // 3%
  eaasIndexation: 'fixed', // 'fixed' or 'cpi'
  useInflation: false, // false = real IRR, true = nominal IRR
  irrMode: 'real', // 'real' or 'nominal'

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

// P-factor values (can be overwritten by settings)
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
  const bessLifetime = settings.bessLifetimeYears ?? window.economicsSettings?.bessLifetimeYears ?? 15;
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
      description = `FMV: ${(fmvPercent * 100).toFixed(0)}% of initial CAPEX`;
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
  let discountRate = settings.discountRate ?? window.economicsSettings?.discountRate ?? 0.07;
  let inflationRate = settings.inflationRate ?? window.economicsSettings?.inflationRate ?? 0.03;
  const useInflation = settings.useInflation ?? window.economicsSettings?.useInflation ?? false;

  // P0-3 GUARDRAIL: Ensure numeric values
  discountRate = parseFloat(discountRate);
  inflationRate = parseFloat(inflationRate);

  if (isNaN(discountRate)) {
    console.warn('⚠️ getEffectiveDiscountRate: discountRate is NaN, using default 0.07');
    discountRate = 0.07;
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
        console.log(`📊 Rate conversion: ${(discountRate * 100).toFixed(2)}% real → ${(effectiveRate * 100).toFixed(2)}% nominal (inflation: ${(inflationRate * 100).toFixed(1)}%)`);
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
    console.warn('⚠️ getEffectiveDiscountRate: effectiveRate is NaN/Infinity, using default 0.07');
    effectiveRate = 0.07;
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
      import_price_pln_mwh: settings.totalEnergyPrice || settings.energyPrice || 800,
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
 * Helper function to get annual consumption in kWh
 * This is the TOTAL ENERGY CONSUMPTION of the facility (from uploaded consumption file)
 * NOT to be confused with autoconsumption (self_consumed) which is energy from PV used on-site
 *
 * Uses multiple sources with fallbacks
 */
function getAnnualConsumptionKwh() {
  // Priority 1: consumptionData.annual_consumption_kwh (sent from config module)
  if (consumptionData?.annual_consumption_kwh && consumptionData.annual_consumption_kwh > 0) {
    console.log('📊 [P1] Using annual_consumption_kwh from consumptionData:',
      (consumptionData.annual_consumption_kwh / 1000).toFixed(1), 'MWh');
    return consumptionData.annual_consumption_kwh;
  }

  // Priority 2: consumptionData.total_consumption_gwh (convert GWh to kWh)
  if (consumptionData?.total_consumption_gwh && consumptionData.total_consumption_gwh > 0) {
    const kwh = consumptionData.total_consumption_gwh * 1000000;
    console.log('📊 [P2] Using total_consumption_gwh from consumptionData:',
      consumptionData.total_consumption_gwh, 'GWh =', (kwh / 1000).toFixed(1), 'MWh');
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
      console.log('📊 [P3] Calculated annual consumption from hourlyData:', (sum / 1000).toFixed(1), 'MWh');
      return sum;
    }
  }

  // Priority 4: Get from analysisResults (data sent back from pv-calculation)
  if (analysisResults?.consumption_stats?.total_consumption_gwh) {
    const kwh = analysisResults.consumption_stats.total_consumption_gwh * 1000000;
    console.log('📊 [P4] Using total_consumption_gwh from analysisResults:', (kwh / 1000).toFixed(1), 'MWh');
    return kwh;
  }

  // FALLBACK WARNING: The values below are NOT the total consumption!
  // They are approximations and should be avoided if possible
  console.warn('⚠️ WARNING: consumptionData not available! Using fallback values.');
  console.warn('   consumptionData:', consumptionData);

  // Priority 5: Get from current variant (grid_import + self_consumed = approximate total consumption)
  // NOTE: This is NOT accurate if BESS is present!
  const variant = variants[currentVariant];
  if (variant) {
    const selfConsumed = variant.self_consumed || 0;
    const gridImport = variant.bess_grid_import_kwh || 0;

    if (selfConsumed > 0 && gridImport > 0) {
      const totalConsumption = selfConsumed + gridImport;
      console.warn('📊 [P5 FALLBACK] Estimated from variant: self_consumed + grid_import =',
        (totalConsumption / 1000).toFixed(1), 'MWh (INACCURATE!)');
      return totalConsumption;
    }
  }

  // Priority 6: Last resort fallback
  console.error('❌ No consumption data found! Using default 5000 MWh');
  return 5000000; // 5 GWh = 5,000 MWh - fallback
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
function recalculateCapexWithScenario(scenario) {
  const factor = window.productionFactors[scenario] || 1.0;
  console.log(`📊 Recalculating CAPEX economics with factor: ${factor} (${scenario})`);

  // Store factor for use in calculations
  window.currentScenarioFactor = factor;

  // Clear cached centralized metrics so they get recalculated with new scenario
  // This ensures optimization tables use the new scenario values
  centralizedMetrics = {};
  console.log('🔄 Cleared centralizedMetrics cache for scenario recalculation');

  // If we have analysis results, recalculate and update displays
  if (analysisResults && variants && Object.keys(variants).length > 0) {
    // Update key metrics (NPV, IRR, Payback)
    updateCapexMetricsWithScenario(factor);

    // Regenerate all charts and tables with new scenario
    regenerateAllChartsAndTables();
  }
}

/**
 * Regenerate all charts and tables after scenario change
 */
function regenerateAllChartsAndTables() {
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

  // Update charts
  if (typeof generateCashFlowChart === 'function' && scenarioAdjustedData) {
    generateCashFlowChart(scenarioAdjustedData);
  }

  if (typeof generateRevenueChart === 'function') {
    generateRevenueChart();
  }

  // Update payback table
  if (typeof generatePaybackTable === 'function' && scenarioAdjustedData) {
    generatePaybackTable(scenarioAdjustedData, variant.capacity, params);
  }

  // Update revenue table
  if (typeof generateRevenueTable === 'function' && scenarioAdjustedData) {
    generateRevenueTable(scenarioAdjustedData);
  }

  // Update optimization tables
  if (typeof calculateOptimization === 'function') {
    try {
      calculateOptimization();
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
  const adjustedProductionMwh = adjustedProductionKwh / 1000;
  const adjustedSelfConsumedMwh = adjustedSelfConsumedKwh / 1000;

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
  const degradationRate = params.degradation_rate || 0.005;
  const discountRate = params.discount_rate || 0.07;
  const inflationRate = window.economicsSettings?.useInflation ? (params.inflation_rate || 0.03) : 0;

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
 * Update CAPEX metrics (key indicators, tables) with scenario factor
 */
function updateCapexMetricsWithScenario(factor) {
  console.log('🔄 updateCapexMetricsWithScenario called with factor:', factor);

  const variant = variants[currentVariant];
  if (!variant) {
    console.warn('⚠️ No variant data available for scenario update');
    return;
  }
  console.log('  📊 Variant:', currentVariant, variant);

  // Get economic parameters (properly formatted for calculations)
  const params = getEconomicParameters();
  console.log('  📊 Params:', params);

  // Get base annual production (kWh) - use self_consumed for savings calculation
  // variant.production is total production, variant.self_consumed is what saves money
  const baseAnnualSelfConsumedKwh = variant.self_consumed || variant.production || 0;
  const adjustedSelfConsumedKwh = baseAnnualSelfConsumedKwh * factor;
  const adjustedSelfConsumedMwh = adjustedSelfConsumedKwh / 1000;
  console.log('  📊 Self-consumed: base=', baseAnnualSelfConsumedKwh, 'adjusted=', adjustedSelfConsumedKwh);

  // Get total energy price (already includes all components: energy_active, distribution, fees, capacity_fee, excise)
  const totalPricePerMwh = calculateTotalEnergyPrice(params); // PLN/MWh
  console.log('  📊 Total energy price:', totalPricePerMwh, 'PLN/MWh');

  // Calculate adjusted annual savings (self-consumed energy * full price)
  const annualSavings = adjustedSelfConsumedMwh * totalPricePerMwh;
  console.log('  📊 Annual savings:', annualSavings, 'PLN');

  // Get CAPEX using getCapexForCapacity function
  const capacityKwp = variant.capacity || 0;
  const capexPerKwp = getCapexForCapacity(capacityKwp);
  const capex = capacityKwp * capexPerKwp;
  console.log('  📊 CAPEX: capacity=', capacityKwp, 'kWp, capexPerKwp=', capexPerKwp, 'total=', capex);

  // Calculate adjusted payback
  const opexPerKwp = params.opex_per_kwp || 15;
  const annualOpex = capacityKwp * opexPerKwp;
  const netAnnualSavings = annualSavings - annualOpex;
  const paybackYears = netAnnualSavings > 0 ? capex / netAnnualSavings : null;

  // Calculate adjusted NPV
  const discountRate = params.discount_rate || (systemSettings?.discountRate || 7) / 100;
  const analysisPeriod = params.analysis_period || systemSettings?.analysisPeriod || 25;
  const degradationRate = params.degradation_rate || (systemSettings?.degradationRate || 0.5) / 100;
  const inflationRate = window.economicsSettings?.useInflation ? (params.inflation_rate || (systemSettings?.inflationRate || 3) / 100) : 0;

  let npv = -capex;
  for (let year = 1; year <= analysisPeriod; year++) {
    const degradedSelfConsumedMwh = adjustedSelfConsumedMwh * Math.pow(1 - degradationRate, year - 1);
    const yearSavings = degradedSelfConsumedMwh * totalPricePerMwh;
    // OPEX with inflation if enabled
    const yearOpex = capacityKwp * opexPerKwp * Math.pow(1 + inflationRate, year - 1);
    const yearCashFlow = yearSavings - yearOpex;
    npv += yearCashFlow / Math.pow(1 + discountRate, year);
  }

  // Calculate IRR using binary search
  const irr = calculateSimpleIRR(capex, annualSavings, annualOpex, analysisPeriod, degradationRate);

  // Update UI elements (using actual element IDs from index.html) - European format
  const paybackEl = document.getElementById('paybackPeriod');
  if (paybackEl) paybackEl.textContent = paybackYears ? formatNumberEU(paybackYears, 1) : '–';

  const npvEl = document.getElementById('npv');
  if (npvEl) npvEl.textContent = formatNumberEU(npv / 1000000, 2);

  const irrEl = document.getElementById('irr');
  if (irrEl) irrEl.textContent = irr ? formatNumberEU(irr * 100, 1) : '–';

  // Update scenario factor display
  const factorDisplayEl = document.getElementById('scenarioFactorDisplay');
  if (factorDisplayEl) factorDisplayEl.textContent = `${formatNumberEU(factor * 100, 0)}%`;

  // Store scenario-adjusted data for use by other functions
  window.scenarioAdjustedData = {
    factor: factor,
    scenario: window.currentProductionScenario,
    production: adjustedSelfConsumedKwh,
    annualSavings: annualSavings,
    npv: npv,
    irr: irr,
    paybackYears: paybackYears,
    capex: capex,
    capacityKwp: capacityKwp
  };

  // Update "Szczegółowe Wskaźniki Finansowe" section - European format
  const savingsAnnualEl = document.getElementById('savingsAnnual');
  if (savingsAnnualEl) savingsAnnualEl.textContent = `${formatNumberEU(netAnnualSavings / 1000, 0)} tys. PLN`;

  const revenueAnnualEl = document.getElementById('revenueAnnual');
  if (revenueAnnualEl) revenueAnnualEl.textContent = `${formatNumberEU(annualSavings / 1000, 0)} tys. PLN`;

  const opexAnnualEl = document.getElementById('opexAnnual');
  if (opexAnnualEl) opexAnnualEl.textContent = `${formatNumberEU(annualOpex / 1000, 0)} tys. PLN`;

  const roiEl = document.getElementById('roi');
  if (roiEl && capex > 0) roiEl.textContent = `${formatNumberEU((npv / capex) * 100, 1)}%`;

  const unitCapexEl = document.getElementById('unitCapex');
  if (unitCapexEl && capacityKwp > 0) unitCapexEl.textContent = `${formatNumberEU(capex / capacityKwp, 0)} PLN/kWp`;

  console.log(`📈 CAPEX metrics updated: Payback=${paybackYears?.toFixed(1)}y, NPV=${(npv/1000000).toFixed(2)}M, IRR=${irr ? (irr*100).toFixed(1) : 'N/A'}%`);
  console.log(`   Self-consumed: ${adjustedSelfConsumedMwh.toFixed(1)} MWh/yr, Savings: ${(annualSavings/1000).toFixed(0)}k PLN/yr`);
}

/**
 * Simple IRR calculation using binary search
 */
function calculateSimpleIRR(capex, annualSavings, annualOpex, years, degradationRate) {
  let low = -0.5, high = 1.0;
  for (let i = 0; i < 50; i++) {
    const mid = (low + high) / 2;
    let npv = -capex;
    for (let year = 1; year <= years; year++) {
      const degradedSavings = annualSavings * Math.pow(1 - degradationRate, year - 1);
      const cf = degradedSavings - annualOpex;
      npv += cf / Math.pow(1 + mid, year);
    }
    if (Math.abs(npv) < 100) return mid;
    if (npv > 0) low = mid;
    else high = mid;
  }
  return (low + high) / 2;
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
    annualSavingsEl.textContent = formatNumberEU(cs.annualSavings / 1000, 1);
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

  // Recalculate EaaS subscription with adjusted production
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value) || 24;
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || 10;

  // Get subscription from calculateEaasSubscription (it uses currentScenarioFactor internally)
  // Pass variant to include BESS CAPEX/OPEX in subscription calculation
  const subscriptionData = calculateEaasSubscription(
    variant.capacity,
    systemSettings || {},
    params,
    variant  // Include variant for BESS data
  );

  // Recalculate centralized metrics with scenario factor
  centralizedMetrics[currentVariant] = calculateCentralizedFinancialMetrics(variant, params, {
    subscription: subscriptionData.annualSubscription,
    duration: eaasDuration,
    omPerKwp: eaasOM
  });

  // Regenerate EaaS yearly table
  const eaasParams = {
    annualConsumptionKWh: getAnnualConsumptionKwh(),
    annualPVProductionKWh: variant.production * factor,
    selfConsumptionRatio: variant.self_consumed / variant.production,
    pvPowerKWp: variant.capacity,
    pvCapexPLN: variant.capacity * getCapexForCapacity(variant.capacity),
    eaasSubscriptionPLNperYear: subscriptionData.annualSubscription,
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
        el.textContent = formatNumberEU(value / 1000000, 2);
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

// Get CAPEX per kWp based on capacity using tiered pricing
function getCapexForCapacity(capacityKwp) {
  // Get current PV type from pvConfig or default to ground_s
  const currentPvType = pvConfig?.pvType || pvConfig?.pv_type || 'ground_s';

  // Try to get CAPEX data - prefer capexPerType (new format) over capexTiers (legacy)
  // Use defaults if systemSettings doesn't have the new format
  const capexPerType = systemSettings?.capexPerType || DEFAULT_CAPEX_PER_TYPE;
  const capexRanges = systemSettings?.capexRanges || DEFAULT_CAPEX_RANGES;
  const capexTiers = systemSettings?.capexTiers || analysisResults?.economicParams?.capexTiers;

  // NEW FORMAT: Use capexPerType with capexRanges
  if (capexPerType && capexRanges && capexRanges.length > 0) {
    // Get tiers for current PV type
    const typeTiers = capexPerType[currentPvType] || capexPerType.ground_s;
    if (typeTiers && typeTiers.length > 0) {
      // Find matching tier by range
      for (let i = 0; i < capexRanges.length; i++) {
        const range = capexRanges[i];
        const tier = typeTiers[i];
        if (!tier || !range) continue;

        const minVal = range.min || 0;
        const maxVal = (range.max === null || range.max === undefined || range.max === Infinity || range.max >= 999999)
                       ? Infinity : range.max;

        if (capacityKwp >= minVal && capacityKwp <= maxVal) {
          const price = tier.sale || tier.capex || tier.cost || 3500;
          return price;
        }
      }

      // Fallback: use last non-null tier for large installations
      // Find the last valid (non-null) tier
      let lastValidTierIndex = -1;
      for (let i = typeTiers.length - 1; i >= 0; i--) {
        if (typeTiers[i] !== null) {
          lastValidTierIndex = i;
          break;
        }
      }

      if (lastValidTierIndex >= 0) {
        const lastTier = typeTiers[lastValidTierIndex];
        const lastRange = capexRanges[lastValidTierIndex];
        if (lastTier && capacityKwp >= (lastRange?.min || 0)) {
          const price = lastTier.sale || lastTier.capex || lastTier.cost || 3500;
          console.log(`  → Using last valid tier (capexPerType/${currentPvType}): ${lastRange?.min}-${lastRange?.max} kWp, price: ${price} PLN/kWp`);
          return price;
        }
      }
    }
  }

  // LEGACY FORMAT: Use capexTiers
  if (capexTiers && capexTiers.length > 0) {
    const sortedTiers = [...capexTiers].sort((a, b) => a.min - b.min);

    for (const tier of sortedTiers) {
      const maxValue = (tier.max === null || tier.max === undefined ||
                       tier.max === Infinity || tier.max === '∞' ||
                       tier.max === 'Infinity' || tier.max >= 999999)
                       ? Infinity : tier.max;

      console.log(`  → Checking tier (legacy): ${tier.min}-${maxValue} kWp for capacity ${capacityKwp}`);

      if (capacityKwp >= tier.min && capacityKwp <= maxValue) {
        const price = tier.capex || tier.sale || tier.cost || 3500;
        console.log(`  ✓ MATCHED tier (legacy): ${tier.min}-${maxValue} kWp, price: ${price} PLN/kWp`);
        return price;
      }
    }

    // Fallback to last tier for large installations
    const lastTier = sortedTiers[sortedTiers.length - 1];
    if (capacityKwp >= lastTier.min) {
      const price = lastTier.capex || lastTier.sale || lastTier.cost || 3500;
      console.log(`  → Using last tier (legacy): price: ${price} PLN/kWp`);
      return price;
    }
  }

  // Ultimate fallback
  const fallback = parseFloat(document.getElementById('investmentCost')?.value || 3500);
  console.log(`  → No valid tiers found, using fallback: ${fallback} PLN/kWp`);
  return fallback;
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
    quality_fee: systemSettings?.qualityFee || parseFloat(document.getElementById('qualityFee')?.value || 10),
    oze_fee: systemSettings?.ozeFee || parseFloat(document.getElementById('ozeFee')?.value || 7),
    cogeneration_fee: systemSettings?.cogenerationFee || parseFloat(document.getElementById('cogenerationFee')?.value || 10),
    capacity_fee: systemSettings?.capacityFee || parseFloat(document.getElementById('capacityFee')?.value || 219),
    excise_tax: systemSettings?.exciseTax || parseFloat(document.getElementById('exciseTax')?.value || 5),
    investment_cost: parseFloat(document.getElementById('investmentCost')?.value || 3500), // This is display only
    opex_per_kwp: systemSettings?.opexPerKwp || parseFloat(document.getElementById('opexPerKwp')?.value || 15),
    degradation_rate: (systemSettings?.degradationRate || parseFloat(document.getElementById('degradationRate')?.value || 0.5)) / 100,
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
  return params.energy_active + params.distribution + params.quality_fee +
         params.oze_fee + params.cogeneration_fee + params.capacity_fee + params.excise_tax;
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
    parametersData.bess_lifetime_years = settings.bessLifetimeYears || 15;
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
    target_irr: (settings?.eaasTargetIrrPln ?? 12.0) / 100,
    indexation: settings?.eaasIndexation ?? 'fixed',
    cpi: window.economicsSettings?.inflationRate ?? 0.025,
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
    ? (settings.eaasTargetIrrPln || 12.0) / 100
    : (settings.eaasTargetIrrEur || 10.0) / 100;

  // CPI
  const cpi = irrDriver === 'PLN'
    ? (settings.cpiPln || 2.5) / 100
    : (settings.cpiEur || 2.0) / 100;
  const cpiFloor = (settings.cpiFloor || 0) / 100;
  const cpiCapAnnual = (settings.cpiCapAnnual || 5.0) / 100;
  const cpiCapTotal = (settings.cpiCapTotal || 50.0) / 100;

  // Tax & Depreciation
  const citRate = (settings.citRate || 19.0) / 100;
  const depPeriod = settings.depreciationPeriod || 20;

  // Financing
  const leverageRatio = (settings.leverageRatio || 0) / 100;
  const costOfDebt = (settings.costOfDebt || 7.0) / 100;
  const debtTenor = settings.debtTenor || 8;
  const debtGracePeriod = settings.debtGracePeriod || 0;
  const debtAmortization = settings.debtAmortization || 'annuity';

  // Technical
  const availability = (settings.availabilityFactor || 98.0) / 100;
  const degradationRate = (settings.degradationRate || economicParams?.degradation_rate * 100 || 0.5) / 100;
  const expectedLossRate = (settings.expectedLossRate || 0) / 100;

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
  console.log(`   Abonament roczny (rok 1): ${(optimalSubscription * currencyMultiplier / 1000).toFixed(0)} tys. ${currencyDisplay}`);
  console.log(`   Abonament miesięczny: ${(monthlySubscription * currencyMultiplier / 1000).toFixed(1)} tys. ${currencyDisplay}`);
  console.log(`   Cena EaaS: ${(pricePerMWh * currencyMultiplier).toFixed(0)} ${currencyDisplay}/MWh`);
  console.log(`   Project IRR: ${(projectIrr * 100).toFixed(2)}%`);
  console.log(`   Equity IRR: ${(equityIrr * 100).toFixed(2)}%`);
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
    ? (settings.eaasTargetIrrPln || 12.0) / 100
    : (settings.eaasTargetIrrEur || 10.0) / 100;

  // CPI inflation rates - use unified inflationRate from financial parameters
  const systemInflationRate = window.economicsSettings?.inflationRate || 0.025;
  const g_PLN = systemInflationRate; // Use system-wide inflation rate for PLN
  const g_EUR = (settings.cpiEur || 2.0) / 100; // Keep separate EUR inflation if needed
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
    opexBESS_PLN = capexBESS_PLN * (bessOpexPctPerYear / 100);
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
  console.log(`     Target IRR: ${(r * 100).toFixed(1)}%`);
  console.log(`     Inflacja (CPI ${currency}): ${(g * 100).toFixed(1)}%`);
  console.log(`  `);
  console.log(`  💰 PARAMETRY (waluta bazowa PLN):`);
  console.log(`     CAPEX (I₀): ${(I0_PLN / 1000000).toFixed(2)} mln PLN (${capexPerKwp} PLN/kWp)`);
  if (hasBess) {
    console.log(`       - PV CAPEX: ${(capexPV_PLN / 1000000).toFixed(2)} mln PLN`);
    console.log(`       - BESS CAPEX: ${(capexBESS_PLN / 1000000).toFixed(2)} mln PLN`);
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
    console.log(`     r_real = (1+r)/(1+g) - 1 = ${(r_real * 100).toFixed(3)}%`);
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
  console.log(`     Całkowity przychód (${N} lat): ${(totalRevenue_contract / 1000000).toFixed(2)} mln ${currency_display}`);
  console.log(`     Osiągnięte IRR: ${(achievedIRR * 100).toFixed(2)}% (target: ${(r * 100).toFixed(1)}%)`);
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
  window.economicsSettings.discountRate = (settings.discountRate || 7) / 100; // Convert % to decimal
  window.economicsSettings.insuranceRate = getInsuranceRate(settings);
  window.economicsSettings.inflationRate = (settings.inflationRate || 3) / 100;
  window.economicsSettings.eaasIndexation = settings.eaasIndexation || 'fixed'; // 'fixed' or 'cpi'
  // IRR calculation mode
  window.economicsSettings.useInflation = settings.useInflation || false;
  window.economicsSettings.irrMode = settings.irrMode || (settings.useInflation ? 'nominal' : 'real');

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

      // Load consumptionData - CRITICAL for correct energy consumption values
      if (event.data.data.consumptionData) {
        consumptionData = event.data.data.consumptionData;
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

      // Obsolete multi-source BESS data handling removed.
      // Data now comes from analysisResults only.

      console.log('🚀 Calling performEconomicAnalysis() from SHARED_DATA_RESPONSE');
      performEconomicAnalysis();
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
      performEconomicAnalysis();
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
        console.log('🚀 Calling performEconomicAnalysis() from ANALYSIS_RESULTS');
        performEconomicAnalysis();
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
      applySettingsToUI(systemSettings);
      // Recalculate if we have analysis data
      if (analysisResults) {
        performEconomicAnalysis();
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
          performEconomicAnalysis();
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
          bessSizingData.annual_discharge_mwh = (v.dispatch_summary?.total_discharge_kwh || 0) / 1000;
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
          performEconomicAnalysis();
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
          performEconomicAnalysis();
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
          performEconomicAnalysis();
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
        const discountRate = (systemSettings?.discountRate || 5) / 100;
        console.log('📤 DEBUG: eaasDuration =', eaasDuration, 'analysisPeriod =', analysisPeriod);

        // Calculate Full Investor Model on-demand to ensure fresh data
        let fullInvestorModelData = null;
        try {
          const annualEnergyMWh = (variant.production || 0) / 1000;
          const bessDataForModel = (variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0) ? variant : null;
          const economicParams = {
            gridPrice: systemSettings?.gridPrice || 0.8,
            opexPerKwp: systemSettings?.omCostPerKwp || 24,
            insuranceRate: systemSettings?.insuranceRate || 0.005,
            degradationRate: systemSettings?.degradationRate || 0.005
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
function calculateCentralizedFinancialMetrics(variant, params, eaasParams = null) {
  console.log('💰 CENTRALIZED CALCULATION for variant:', variant.capacity, 'kWp');

  // Apply production scenario factor
  const scenarioFactor = window.currentScenarioFactor || 1.0;
  const scenarioName = window.currentProductionScenario || 'P50';
  console.log(`  📊 Using scenario: ${scenarioName} (factor: ${scenarioFactor})`);

  // Common parameters - convert to MWh for consistent calculations with PLN/MWh prices
  const capacityKwp = variant.capacity;
  const productionMwh = (variant.production * scenarioFactor) / 1000; // kWh → MWh
  const selfConsumedMwh = (variant.self_consumed * scenarioFactor) / 1000; // kWh → MWh (total = PV direct + BESS)

  // BESS autoconsumption breakdown (for table display)
  const bessSelfConsumedMwh = ((variant.bess_self_consumed_from_bess_kwh || 0) * scenarioFactor) / 1000; // MWh from BESS

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
    bessDegradationYear1 = (rawDegYear1 !== undefined ? rawDegYear1 : 3.0) / 100;
    bessDegradationPctPerYear = (rawDegPerYear !== undefined ? rawDegPerYear : 2.0) / 100;
    capexBESS = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);
    opexBESS = capexBESS * (bessOpexPctPerYear / 100);
    console.log(`  🔋 BESS CAPEX: ${(capexBESS/1000000).toFixed(2)} mln PLN`);
    console.log(`  🔋 BESS OPEX: ${(opexBESS/1000).toFixed(0)} tys. PLN/rok`);
    console.log(`  🔋 BESS Degradation from settings: Year1=${(bessDegradationYear1*100).toFixed(1)}% (raw: ${rawDegYear1}), Years2+=${(bessDegradationPctPerYear*100).toFixed(1)}%/yr (raw: ${rawDegPerYear})`);
  }

  // Total CAPEX = PV + BESS
  const capex = capexPV + capexBESS;

  const discountRate = window.economicsSettings?.discountRate ?? 0.07;
  const inflationRate = window.economicsSettings?.inflationRate || 0.025;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';
  // =========================================================================
  // DATA CONTRACT: Client analysis horizon = 30 years
  // Must match: shell.js CLIENT_ANALYSIS_PERIOD, app.py CLIENT_ANALYSIS_PERIOD
  // =========================================================================
  const CLIENT_ANALYSIS_PERIOD = 30;
  const analysisPeriod = CLIENT_ANALYSIS_PERIOD; // Fixed for client models (CAPEX_CLIENT, EAAS_CLIENT)
  const degradationRate = params.degradation_rate; // PV degradation for years 2+ [fraction]

  // PV degradation Year 1 from settings (user configurable)
  const settings = systemSettings || {};
  const rawPvDegYear1 = settings.pvDegradationYear1;
  const pvDegradationYear1 = (rawPvDegYear1 !== undefined ? rawPvDegYear1 : 2.0) / 100; // default 2%

  // IRR calculation mode - determines if we apply inflation to cash flows
  const useInflation = window.economicsSettings?.useInflation || false;
  const irrMode = useInflation ? 'nominal' : 'real';

  // Total energy price in PLN/MWh (same unit as params)
  const totalEnergyPrice = params.energy_active + params.distribution + params.quality_fee +
                            params.oze_fee + params.cogeneration_fee + params.capacity_fee +
                            params.excise_tax; // PLN/MWh

  // ========== CAPEX MODEL CALCULATION ==========
  console.log('🔢 CENTRALIZED CAPEX NPV Calculation:');
  console.log('  📅 Analysis period:', analysisPeriod, 'years');
  console.log('  📊 Discount rate:', (discountRate * 100).toFixed(1), '%');
  console.log('  📈 Inflation rate:', (inflationRate * 100).toFixed(1), '%');
  console.log(`  📉 PV Degradation from settings: Year1=${(pvDegradationYear1*100).toFixed(1)}% (raw: ${rawPvDegYear1}), Years2+=${(degradationRate*100).toFixed(2)}%/yr`);
  console.log('  💰 Initial CAPEX:', (-capex / 1000000).toFixed(2), 'mln PLN');
  console.log('  📊 IRR Mode:', irrMode, useInflation ? '(inflation-indexed cash flows)' : '(constant prices)');

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

    // Apply inflation factor only if useInflation is true (nominal mode)
    const inflationFactor = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;

    // Breakdown: PV direct uses PV degradation, BESS uses BESS degradation
    const yearPvDirectMwh = pvDirectSelfConsumedMwh * pvDegradation;
    const yearBessMwh = bessSelfConsumedMwh * bessDegradation;
    const yearSelfConsumedMwh = yearPvDirectMwh + yearBessMwh;

    const adjustedEnergyPrice = totalEnergyPrice * inflationFactor; // PLN/MWh

    // OPEX = PV OPEX + BESS OPEX (z inflacją jeśli włączona)
    const adjustedOpexPV = capacityKwp * params.opex_per_kwp * inflationFactor;
    const adjustedOpexBESS = opexBESS * inflationFactor;
    const adjustedOpex = adjustedOpexPV + adjustedOpexBESS;

    const yearSavings = yearSelfConsumedMwh * adjustedEnergyPrice; // MWh * PLN/MWh = PLN
    const yearCashFlow = yearSavings - adjustedOpex;
    const discountedCF = yearCashFlow / Math.pow(1 + discountRate, year);
    capexNPV += discountedCF;

    capexCashFlows.push({
      year: year,
      savings: yearSavings,
      opex: adjustedOpex,
      net_cash_flow: yearCashFlow,
      production: productionMwh * pvDegradation * 1000, // MWh → kWh for display (PV degradation)
      selfConsumed: yearSelfConsumedMwh * 1000,  // MWh → kWh for display (total = PV + BESS)
      selfConsumedPvDirect: yearPvDirectMwh * 1000,  // kWh - direct from PV (PV degradation)
      selfConsumedBess: yearBessMwh * 1000,  // kWh - from BESS discharge (BESS degradation)
      energyPrice: adjustedEnergyPrice,  // PLN/MWh for this year
      pvDegradationPct: pvDegradation * 100,  // % - for table display
      bessDegradationPct: bessDegradation * 100  // % - for table display
    });

    // Log sample years
    if (year <= 2 || year === analysisPeriod) {
      console.log(`  Year ${year}: NetCF=${(yearCashFlow/1000).toFixed(0)}k PLN, Discounted=${(discountedCF/1000).toFixed(0)}k PLN, RunningNPV=${(capexNPV/1000000).toFixed(2)}M PLN`);
    }
  }

  console.log('  ✅ Final CAPEX NPV:', (capexNPV / 1000000).toFixed(2), 'mln PLN');

  // Calculate CAPEX IRR using local Newton-Raphson method
  // NOTE: This is for display purposes; backend IRR (when available) should be preferred
  const irrCashFlows = capexCashFlows.map((cf, i) => ({
    year: i + 1,
    net_cash_flow: cf.net_cash_flow
  }));
  console.log('  📊 IRR Input - Initial investment:', (capex / 1000000).toFixed(2), 'mln PLN');
  console.log('  📊 IRR Input - Cash flows count:', irrCashFlows.length);
  console.log('  📊 IRR Input - First 3 cash flows:', irrCashFlows.slice(0, 3).map(cf => `Year ${cf.year}: ${(cf.net_cash_flow/1000).toFixed(0)}k PLN`));
  const capexIRR = calculateIRR()
  console.log('  📊 IRR Result:', capexIRR, '(', (capexIRR * 100).toFixed(2), '%) - Mode:', irrMode);

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
    console.log('  📊 Discount rate:', (discountRate * 100).toFixed(1), '%');
    console.log('  📈 Inflation rate:', (inflationRate * 100).toFixed(1), '%');
    console.log('  📋 EaaS indexation:', eaasIndexation);
    console.log('  💰 Base subscription:', (baseSubscriptionCost / 1000).toFixed(0), 'k PLN/year');
    console.log('  💰 Base O&M:', (baseOmCost / 1000).toFixed(0), 'k PLN/year');
    console.log('  💰 Base insurance:', (baseInsuranceCost / 1000).toFixed(0), 'k PLN/year');
    if (baseLandLeaseCost > 0) {
      console.log('  💰 Base land lease:', (baseLandLeaseCost / 1000).toFixed(0), 'k PLN/year');
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

      const gridCost = yearSelfConsumedMwh * adjustedGridPrice; // MWh * PLN/MWh = PLN

      let eaasCost;
      if (year <= eaasDuration) {
        // IMPORTANT: Subscription already includes OPEX (O&M + insurance + land lease) from annuity formula
        // Do NOT add them again - that would be triple-counting!
        eaasCost = adjustedSubscriptionCost;
      } else {
        // After EaaS contract ends, customer pays O&M + insurance + land lease + BESS OPEX (inflation-indexed)
        eaasCost = adjustedOmCost + adjustedInsuranceCost + adjustedLandLeaseCost + adjustedBessOpex;
      }

      const savings = gridCost - eaasCost;
      const discountedCF = savings / Math.pow(1 + discountRate, year);
      eaasNPV += discountedCF;

      eaasCashFlows.push({
        year: year,
        selfConsumed: yearSelfConsumedMwh * 1000,  // MWh → kWh for display (total)
        selfConsumedPvDirect: yearPvDirectMwh * 1000,  // kWh - direct from PV
        selfConsumedBess: yearBessMwh * 1000,  // kWh - from BESS discharge
        gridCost: gridCost,  // equivalent OSD cost for autoconsumption
        eaasCost: eaasCost,
        savings: savings,
        discountedCF: discountedCF,
        phase: year <= eaasDuration ? 'eaas' : 'ownership',
        energyPrice: adjustedGridPrice,  // PLN/MWh for this year
        pvDegradationPct: pvDegradation * 100,  // % - for table display
        bessDegradationPct: bessDegradation * 100  // % - for table display
      });

      // Log sample years
      if (year <= 2 || year === eaasDuration || year === eaasDuration + 1 || year === analysisPeriod) {
        console.log(`  Year ${year} (${year <= eaasDuration ? 'EaaS' : 'Own'}): GridCost=${(gridCost/1000).toFixed(0)}k, EaasCost=${(eaasCost/1000).toFixed(0)}k, Savings=${(savings/1000).toFixed(0)}k, Discounted=${(discountedCF/1000).toFixed(0)}k, RunningNPV=${(eaasNPV/1000000).toFixed(2)}M`);
      }
    }

    console.log('  ✅ Final EaaS NPV:', (eaasNPV / 1000000).toFixed(2), 'mln PLN');

    eaasMetrics = {
      npv: eaasNPV,
      duration: eaasDuration,
      baseSubscription: baseSubscriptionCost,
      baseOmCost: baseOmCost,
      baseInsuranceCost: baseInsuranceCost,
      cashFlows: eaasCashFlows
    };
  }

  return {
    capex: {
      npv: capexNPV,
      irr: capexIRR,
      irrMode: irrMode,  // 'real' or 'nominal'
      irrStatus: 'converged',  // Local calculation status (always converged or error)
      cashFlows: capexCashFlows,
      investment: capex,
      capexPerKwp: capexPerKwp
    },
    eaas: eaasMetrics,
    common: {
      capacityKwp: capacityKwp,
      productionMwh: productionMwh,  // MWh - annual production
      selfConsumedMwh: selfConsumedMwh,  // MWh - annual self-consumed
      productionKwh: productionMwh * 1000,  // kWh - for backward compatibility
      selfConsumedKwh: selfConsumedMwh * 1000,  // kWh - for backward compatibility
      totalEnergyPrice: totalEnergyPrice,  // PLN/MWh
      discountRate: discountRate,
      inflationRate: inflationRate,
      analysisPeriod: analysisPeriod,
      useInflation: useInflation
    }
  };
}

// Perform economic analysis
// Perform economic analysis using backend API
async function performEconomicAnalysis() {
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

  try {
    // Get parameters from sidebar inputs
    const params = getEconomicParameters();
    console.log('📊 Using economic parameters:', params);

    // Calculate total energy cost (PLN/MWh) - już zawiera wszystkie składniki włącznie z opłatą mocową
    const totalEnergyPrice = calculateTotalEnergyPrice(params);

    console.log('💰 Total energy price (with capacity fee):', totalEnergyPrice, 'PLN/MWh');

    // Podstawowe dane z wariantu
    const capacity_kwp = variant.capacity; // Already in kWp from backend
    const production_annual = variant.production / 1000; // kWh → MWh

    // Autokonsumpcja: bezpośrednia PV + energia z BESS (jeśli jest)
    // variant.self_consumed już zawiera całkowitą autokonsumpcję z BESS
    // ale dla pewności sprawdzamy czy bess_self_consumed_from_bess_kwh jest dostępne
    let self_consumed_annual = variant.self_consumed / 1000; // kWh → MWh

    // BESS dodatkowa autokonsumpcja (energia rozładowana z baterii do zużycia)
    const bess_self_consumed_from_bess = (variant.bess_self_consumed_from_bess_kwh || 0) / 1000; // kWh → MWh

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
    console.log(`💰 PV CAPEX: ${capacity_kwp} kWp × ${capexPerKwp} PLN/kWp = ${(capexPV/1000000).toFixed(2)} mln PLN`);

    // 1b. Nakłady inwestycyjne BESS (jeśli włączony)
    let capexBESS = 0;
    const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
    if (hasBess) {
      const settings = systemSettings || {};
      const bessCapexPerKwh = settings.bessCapexPerKwh || 1500;
      const bessCapexPerKw = settings.bessCapexPerKw || 300;
      capexBESS = (variant.bess_energy_kwh * bessCapexPerKwh) + (variant.bess_power_kw * bessCapexPerKw);
      console.log(`🔋 BESS CAPEX: ${variant.bess_energy_kwh} kWh × ${bessCapexPerKwh} + ${variant.bess_power_kw} kW × ${bessCapexPerKw} = ${(capexBESS/1000000).toFixed(2)} mln PLN`);
    }

    // 1c. Całkowity CAPEX = PV + BESS
    const capex = capexPV + capexBESS;
    console.log(`💰 TOTAL CAPEX: ${(capexPV/1000000).toFixed(2)} + ${(capexBESS/1000000).toFixed(2)} = ${(capex/1000000).toFixed(2)} mln PLN`);

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
      opex_bess_annual = capexBESS * (bessOpexPctPerYear / 100);
      console.log(`🔋 BESS OPEX: ${capexBESS.toFixed(0)} × ${bessOpexPctPerYear}% = ${opex_bess_annual.toFixed(0)} PLN/rok`);
    }

    // 2c. Całkowity OPEX = PV + BESS
    const opex_annual = opex_pv_annual + opex_bess_annual;
    console.log(`💰 TOTAL OPEX: ${opex_pv_annual.toFixed(0)} + ${opex_bess_annual.toFixed(0)} = ${opex_annual.toFixed(0)} PLN/rok`);

    // 3. Roczne oszczędności = autoconsumption * cena energii
    // self_consumed_annual już zawiera energię z BESS (backend liczy to razem)
    const savings_year1 = self_consumed_annual * totalEnergyPrice; // PLN
    console.log(`💰 Savings Year 1: ${self_consumed_annual.toFixed(1)} MWh × ${totalEnergyPrice.toFixed(0)} PLN/MWh = ${(savings_year1/1000).toFixed(0)} tys. PLN`);

    // 4. Prosty okres zwrotu (bez zdyskontowania, bez degradacji)
    const simple_payback = capex / (savings_year1 - opex_annual); // lata

    // 5. Przepływy pieniężne z uwzględnieniem degradacji
    let cash_flows = [];
    let cumulative_cash_flow = -capex; // Start with negative CAPEX

    // Check if inflation should be applied (nominal IRR mode)
    const useInflation = window.economicsSettings?.useInflation || false;
    const inflationRate = useInflation ? (window.economicsSettings?.inflationRate || 0.025) : 0;

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
      console.log(`📊 NPV Calculation using ${discountRateResult.mode} discount_rate:`, (discount_rate * 100).toFixed(2), '%');
      if (discountRateResult.isConverted) {
        console.log(`   (converted from real rate, inflation: ${(discountRateResult.inflationRate * 100).toFixed(1)}%)`);
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
      inflation_rate: window.economicsSettings?.inflationRate || 0.0,
      // P0-3: Rate mode for backend reference
      rate_mode: window.economicsSettings?.rateMode || 'nominal',
      // P0-1: BESS replacement parameters
      bess_replacement_schedule: bessReplacementSchedule,
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


    // Update UI
    updateMetrics(economicData);
    updateDataInfo();

    // Generate charts (don't need centralizedMetrics)
    generateCashFlowChart(economicData);
    generateRevenueChart(economicData);

    // CRITICAL: calculateEaaS() MUST run FIRST - it populates centralizedMetrics[currentVariant]
    // ALL tables below depend on centralizedMetrics being set!
    console.log('🎯 About to call calculateEaaS()...');
    await calculateEaaS();
    console.log('🎯 calculateEaaS() completed - centralizedMetrics should now be set');

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

  } catch (error) {
    console.error('❌ Error performing economic analysis:', error);
    showNoData();
  }
}

// Legacy function for backward compatibility
function performAnalysis() {
  performEconomicAnalysis();
}

// Generate sample economic data
function generateSampleEconomicData(config) {
  const capacity = config.installedCapacity || 1000; // kWp
  const unitCost = 3500; // PLN/kWp

  return {
    capex: capacity * unitCost,
    opexAnnual: capacity * 50, // PLN/year
    energyPrice: 0.65, // PLN/kWh
    discountRate: 0.05,
    analysisHorizon: 25,
    inflationRate: 0.03,
    taxRate: 0.19,
    subsidies: 0
  };
}

// Calculate financial metrics
function calculateFinancialMetrics() {
  const capacity = pvConfig?.installedCapacity || 1000;
  const capex = economicData?.capex || capacity * getCapexForCapacity(capacity);
  const opexAnnual = economicData?.opexAnnual || capacity * 50;
  const energyPrice = economicData?.energyPrice || 0.65;
  const discountRate = economicData?.discountRate || 0.05;
  const horizon = economicData?.analysisHorizon || 25;

  // Annual production (kWh)
  const annualProduction = capacity * 1000; // Assuming 1000 kWh/kWp

  // Annual revenue
  const revenueAnnual = annualProduction * energyPrice;

  // Annual savings (revenue - opex)
  const savingsAnnual = revenueAnnual - opexAnnual;

  // Simple payback period
  const paybackPeriod = capex / savingsAnnual;

  // NPV calculation
  let npv = -capex;
  for (let year = 1; year <= horizon; year++) {
    const cashFlow = savingsAnnual;
    npv += cashFlow / Math.pow(1 + discountRate, year);
  }

  // IRR calculation removed (backend is source of truth)
  const irr = economicData?.irr !== undefined && economicData?.irr !== null ? formatNumberEU(economicData.irr * 100, 1) : 'N/A';

  // LCOE (Levelized Cost of Energy)
  // P1-4 FIX: Add degradation to production for consistency with other LCOE calculations
  const degradationRate = economicData?.parameters?.degradation_rate || window.economicsSettings?.degradationRate || 0.005;
  let totalCosts = capex;
  let totalEnergy = 0;
  for (let year = 1; year <= horizon; year++) {
    const degradation = Math.pow(1 - degradationRate, year - 1);
    totalCosts += opexAnnual / Math.pow(1 + discountRate, year);
    totalEnergy += (annualProduction * degradation) / Math.pow(1 + discountRate, year);
  }
  const lcoe = totalEnergy > 0 ? totalCosts / totalEnergy : 0;

  // ROI
  const roi = (npv / capex) * 100;

  return {
    capex: formatNumberEU(capex / 1000000, 2), // PLN -> mln PLN
    paybackPeriod: formatNumberEU(paybackPeriod, 1),
    npv: formatNumberEU(npv / 1000000, 2),
    irr: irr,
    unitCapex: `${formatNumberEU(capex / capacity, 0)} PLN/kWp`,
    lcoe: `${formatNumberEU(lcoe, 2)} PLN/kWh`,
    opexAnnual: `${formatNumberEU(opexAnnual / 1000, 0)} tys. PLN`,
    revenueAnnual: `${formatNumberEU(revenueAnnual / 1000, 0)} tys. PLN`,
    savingsAnnual: `${formatNumberEU(savingsAnnual / 1000, 0)} tys. PLN`,
    roi: `${formatNumberEU(roi, 1)}%`,
    discountRate: `${formatNumberEU((economicData?.discountRate || 0.05) * 100, 1)}%`,
    analysisHorizon: `${horizon} lat`,
    energyPrice: `${formatNumberEU(energyPrice, 2)} PLN/kWh`,
    subsidies: `${formatNumberEU((economicData?.subsidies || 0) / 1000, 0)} tys. PLN`,
    taxRate: `${formatNumberEU((economicData?.taxRate || 0.19) * 100, 0)}%`,
    inflationRate: `${formatNumberEU((economicData?.inflationRate || 0.03) * 100, 1)}%`
  };
}

// Update metrics display
function updateMetrics(data) {
  // Main metrics from backend API - European format
  document.getElementById('capex').textContent = formatNumberEU(data.investment / 1000000, 2); // PLN → mln PLN
  document.getElementById('paybackPeriod').textContent = formatNumberEU(data.simple_payback, 1);
  document.getElementById('npv').textContent = formatNumberEU(data.npv / 1000000, 2); // PLN → mln PLN

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
      irrElement.textContent = formatNumberEU(irrValue * 100, 1); // decimal → %
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
  document.getElementById('opexAnnual').textContent = `${formatNumberEU(data.metrics.annual_opex / 1000, 0)} tys. PLN`;
  document.getElementById('revenueAnnual').textContent = `${formatNumberEU(data.annual_total_revenue / 1000, 0)} tys. PLN`;
  document.getElementById('savingsAnnual').textContent = `${formatNumberEU(data.annual_savings / 1000, 0)} tys. PLN`;
  document.getElementById('roi').textContent = `${formatNumberEU((data.npv / data.investment) * 100, 1)}%`;

  // Display parameters from sidebar inputs - European format
  const params = data.parameters;
  const discountRateValue = window.economicsSettings?.discountRate ?? 0.07;
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
  const capacity = formatNumberEU(variant.capacity / 1000, 1); // kWp → MWp
  const params = getEconomicParameters();
  const irrMode = economicData?.irrMode || centralizedMetrics[currentVariant]?.capex?.irrMode || 'real';
  const irrValue = economicData?.irr;
  const irrDisplay = irrValue !== null && irrValue !== undefined
    ? `${formatNumberEU(irrValue * 100, 1)}% (${irrMode === 'nominal' ? 'nom.' : 'real'})`
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
    capexPVEl.textContent = formatNumberEU(pvCapex / 1000000, 2);
    capexBESSEl.textContent = formatNumberEU(bessCapexTotal / 1000000, 2);
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
              return context.label + ': ' + (context.parsed / 1000).toFixed(0) + ' tys. PLN';
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
              return context.label + ': ' + (context.parsed / 1000).toFixed(1) + ' tys. PLN/rok';
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
  const cumulativeCashFlow = data.cash_flows.map(cf => (cf.cumulative_cash_flow / 1000000).toFixed(2)); // PLN → mln PLN

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
    revenues.push((annualProduction * energyPrice / 1000).toFixed(0));
    costs.push((opexAnnual / 1000).toFixed(0));
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

// Generate sensitivity analysis chart
function generateSensitivityChart() {
  const ctx = document.getElementById('sensitivityAnalysis').getContext('2d');

  if (sensitivityChart) sensitivityChart.destroy();

  const baseNPV = parseFloat(calculateFinancialMetrics().npv);

  // Simulate changes in key parameters
  const variations = [-20, -10, 0, 10, 20];
  const parameters = ['Cena energii', 'CAPEX', 'OPEX', 'Produkcja', 'Stopa dyskontowa'];

  const datasets = parameters.map((param, index) => {
    const colors = ['#27ae60', '#3498db', '#e74c3c', '#f39c12', '#9b59b6'];
    const npvChanges = variations.map(variation => {
      // Simplified sensitivity - in reality would recalculate NPV
      let factor = 1;
      if (param === 'Cena energii' || param === 'Produkcja') {
        factor = 1 + (variation / 100);
      } else {
        factor = 1 - (variation / 100);
      }
      return (baseNPV * factor).toFixed(2);
    });

    return {
      label: param,
      data: npvChanges,
      borderColor: colors[index],
      backgroundColor: `${colors[index]}33`,
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
  const self_consumed_annual_mwh = self_consumed_annual_kwh / 1000;

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
  const base_eaas_annual_cost = eaas_subscription + (capacity_kwp * eaas_om_per_kwp) + (capex * insurance_rate);
  const self_consumed_annual_mwh = self_consumed_annual_kwh / 1000;

  let npv = 0;
  for (let year = 1; year <= analysis_period; year++) {
    const degradation_factor = Math.pow(1 - degradation_rate, year - 1);
    // Apply inflation to energy price (always)
    const inflation_factor = Math.pow(1 + inflation_rate, year - 1);
    const adjusted_energy_price = total_energy_price_per_kwh * inflation_factor;

    const savings = self_consumed_annual_mwh * degradation_factor * adjusted_energy_price * 1000;

    // EaaS costs: apply inflation only if indexation is 'cpi', otherwise fixed
    const eaas_inflation_factor = eaas_indexation === 'cpi' ? inflation_factor : 1;
    const adjusted_eaas_cost = base_eaas_annual_cost * eaas_inflation_factor;
    const costs = year <= eaas_duration ? adjusted_eaas_cost : 0;
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
  const base_discount_rate = window.economicsSettings?.discountRate ?? 0.07;
  const inflation_rate = window.economicsSettings?.inflationRate || 0.025; // 2.5% default
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

    capexNPVsByEnergy.push((capexNPV / 1000000).toFixed(2));
    eaasNPVsByEnergy.push((eaasNPV / 1000000).toFixed(2));
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

    capexNPVsByDiscount.push((capexNPV / 1000000).toFixed(2));
    eaasNPVsByDiscount.push((eaasNPV / 1000000).toFixed(2));
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
  const discountRate = centralizedCalc.common.discountRate || 0.07;
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice || 800;
  const inflationRate = centralizedCalc.common.inflationRate || 0.025;

  // Get annual consumption using helper function
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = annualConsumptionKwh / 1000;

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
    <td class="negative">-${formatNumberEU(investment / 1000, 0)}</td>
    <td class="negative">-${formatNumberEU(investment / 1000000, 2)}</td>
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
    const selfConsumedMwh = (cf.selfConsumed || 0) / 1000;
    const pvDirectMwh = (cf.selfConsumedPvDirect || 0) / 1000;
    const bessMwh = (cf.selfConsumedBess || 0) / 1000;

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
      <td>${formatNumberEU(yearGridCostFull / 1000, 0)}</td>
      <td>${formatNumberEU(pvDirectMwh, 1)}</td>
      <td>${formatNumberEU(bessMwh, 1)}</td>
      <td>${formatNumberEU(selfConsumedMwh, 1)}</td>
      <td>${formatNumberEU(equivalentGridCost / 1000, 0)}</td>
      <td>${formatNumberEU(opex / 1000, 0)}</td>
      <td class="${savingsClass}">${formatNumberEU(savings / 1000, 0)}</td>
      <td class="${npvClass}">${formatNumberEU(cumulativeNPV / 1000000, 2)}</td>
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
    <td colspan="10" style="text-align:right">💰 SUMA CAŁKOWITA (${cashFlows.length} lat) / NPV (${formatNumberEU(discountRate * 100, 0)}%):</td>
    <td class="positive">${formatNumberEU(totalSavings / 1000, 0)}</td>
    <td class="${npvClass}">${formatNumberEU(cumulativeNPV / 1000000, 2)}</td>
  `;
  tableBody.appendChild(summaryRow);

  console.log('✅ CAPEX table generated. Break-even year:', breakEvenYear || 'Beyond analysis period', ', Final NPV:', (cumulativeNPV / 1000000).toFixed(2), 'mln PLN');
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
    const margin = savings > 0 ? ((profit / savings) * 100) : 0;

    totalSavings += savings;
    totalOpex += opex;
    totalProfit += profit;

    const profitClass = profit >= 0 ? 'positive' : 'negative';
    const marginClass = margin >= 0 ? 'positive' : 'negative';

    row.innerHTML = `
      <td>${cf.year}</td>
      <td>${formatNumberEU(savings / 1000, 0)}</td>
      <td>${formatNumberEU(opex / 1000, 0)}</td>
      <td class="${profitClass}">${formatNumberEU(profit / 1000, 0)}</td>
      <td class="${marginClass}">${formatNumberEU(margin, 1)}%</td>
    `;

    tableBody.appendChild(row);
  }

  // Add summary row
  const summaryRow = document.createElement('tr');
  summaryRow.style.background = '#f8f9fa';
  summaryRow.style.fontWeight = '600';
  summaryRow.style.borderTop = '2px solid #27ae60';

  const avgMargin = totalSavings > 0 ? ((totalProfit / totalSavings) * 100) : 0;
  const avgMarginClass = avgMargin >= 0 ? 'positive' : 'negative';

  summaryRow.innerHTML = `
    <td>SUMA</td>
    <td>${formatNumberEU(totalSavings / 1000, 0)}</td>
    <td>${formatNumberEU(totalOpex / 1000, 0)}</td>
    <td class="positive">${formatNumberEU(totalProfit / 1000, 0)}</td>
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
    const savings = cf.savings / 1000; // PLN → tys. PLN
    const opex = cf.opex / 1000;
    const bessReplacement = (cf.bessReplacementCost || 0) / 1000;  // P0-1
    const residualVal = (cf.residualValue || 0) / 1000;            // P0-2
    const profit = cf.net_cash_flow / 1000;
    const margin = savings > 0 ? (profit / savings) * 100 : 0;

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
  const avgMargin = totalSavings > 0 ? (totalProfit / totalSavings) * 100 : 0;
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
  const capacity = (variant.capacity / 1000).toFixed(1);
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

  console.log(`📊 calculateEaaSEffectivePrice RESULT: ${(eaasPricePLNperKWh * 1000).toFixed(2)} PLN/MWh (subscription=${(eaasTotalAnnualCostPLN/1000).toFixed(0)}k / energy=${(pvSelfConsumedKWh/1000).toFixed(1)} MWh)`);

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

  const gridPricePLNperKWh = calculateGridEnergyPrice(tariffComponents);

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
    pvSelfConsumedMWh: (m.breakdown?.pvSelfConsumedKWh || 0) / 1000
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
        <div id="eaasVal_annualSavings" style="color:#27ae60;font-size:24px;font-weight:600">${(m.annualSavingsPLN / 1000).toFixed(1)}</div>
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
        <div id="eaasVal_production" style="color:#3f51b5;font-size:24px;font-weight:600">${((m.breakdown?.pvSelfConsumedKWh || 0) / 1000).toFixed(0)}</div>
        <div style="color:#7f8c8d;font-size:11px">MWh/rok</div>
      </div>

      <div id="eaasCard_subscription" style="background:#e8eaf6;padding:16px;border-radius:8px;border-left:4px solid #3f51b5">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Abonament EaaS</div>
        <div id="eaasVal_subscription" style="color:#3f51b5;font-size:24px;font-weight:600">${((m.breakdown?.subscriptionCost || 0) / 1000).toFixed(0)}</div>
        <div style="color:#7f8c8d;font-size:11px">tys. PLN/rok</div>
      </div>

      <div id="eaasCard_escoIrr" style="background:#e8eaf6;padding:16px;border-radius:8px;border-left:4px solid #3f51b5">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">ESCO IRR (fixed)</div>
        <div id="eaasVal_escoIrr" style="color:#3f51b5;font-size:24px;font-weight:600">${((window.eaasEscoIrr || 0) * 100).toFixed(1)}</div>
        <div style="color:#7f8c8d;font-size:11px">% (stała subskrypcja)</div>
      </div>
    </div>

    <div style="padding:12px;background:#f8f9fa;border-radius:8px;border:1px solid #e0e0e0;font-size:12px">
      <div style="color:#7f8c8d;font-weight:600;margin-bottom:6px">Rozbicie kosztów EaaS (rocznych):</div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:4px;color:#2c3e50">
        <span>• Abonament: <strong>${(m.breakdown.subscriptionCost / 1000).toFixed(1)}</strong> tys. PLN</span>
        <span>• O&M: <strong>${(m.breakdown.omCost / 1000).toFixed(1)}</strong> tys. PLN</span>
        <span>• Ubezpieczenie: <strong>${(m.breakdown.insuranceCost / 1000).toFixed(1)}</strong> tys. PLN</span>
        <span>• Suma: <strong>${(m.breakdown.totalAnnualCost / 1000).toFixed(1)}</strong> tys. PLN/rok</span>
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
  annualEnergyMWh = variant.self_consumed / 1000; // kWh -> MWh
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
    if (btnP50) btnP50.innerHTML = `P50 <span style="font-size:10px;opacity:0.9">(${(p50Factor * 100).toFixed(0)}%)</span>`;
    if (btnP75) btnP75.innerHTML = `P75 <span style="font-size:10px;opacity:0.9">(${(p75Factor * 100).toFixed(0)}%)</span>`;
    if (btnP90) btnP90.innerHTML = `P90 <span style="font-size:10px;opacity:0.9">(${(p90Factor * 100).toFixed(0)}%)</span>`;

    // Annual subscription (fixed for all scenarios)
    const annualSubscriptionPLN = fullModelResult.annualSubscriptionPLN || fullModelResult.annualSubscription;

    // Grid price for comparison (PLN/MWh)
    const gridPricePLN = calculateTotalEnergyPrice(params);

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
      s.savingsPercent = gridPricePLN > 0 ? (s.savingsPerMWh / gridPricePLN * 100) : 0;
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

    // Call selectProductionScenario to update metrics in the main cards
    // This will update all eaasVal_* elements with scenario-adjusted values
    selectProductionScenario(currentScenario);

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
  console.log('  - CAPEX NPV:', (centralizedCalc.capex.npv / 1000000).toFixed(2), 'mln PLN');
  console.log('  - EaaS NPV:', ((centralizedCalc.eaas?.npv || 0) / 1000000).toFixed(2), 'mln PLN');

  const annualConsumption = getAnnualConsumptionKwh();
  const eaasParams = {
    annualConsumptionKWh: annualConsumption,
    annualPVProductionKWh: variant.production,
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

  generateEaaSYearlyTable(eaasParams, result);

  const eaasSection = document.getElementById('eaasSection');
  if (eaasSection) {
    eaasSection.style.display = 'block';
  }

  console.log('EaaS analysis completed:', result);

  // Initialize Bankability metrics after EaaS calculation
  if (typeof initializeBankability === 'function') {
    setTimeout(() => {
      initializeBankability();
    }, 100);
  }

  calculateOptimization();
}
function calculateOptimization() {
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

  // ========== CALCULATE CENTRALIZED METRICS FOR ALL VARIANTS ==========
  // This ensures we have consistent calculations for all variants
  for (const key of variantKeys) {
    const variant = variants[key];
    if (!variant) continue;

    // Check if we already have centralized metrics for this variant
    if (!centralizedMetrics[key]) {
      console.log(`📊 Calculating centralized metrics for variant ${key}...`);

      // Get EaaS subscription for this variant (including BESS if present)
      const subscriptionData = calculateEaasSubscription(
        variant.capacity,
        systemSettings || {},
        params,
        variant  // Include variant for BESS data
      );

      // Calculate and store centralized metrics
      centralizedMetrics[key] = calculateCentralizedFinancialMetrics(variant, params, {
        subscription: subscriptionData.annualSubscription,
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
    console.log(`   CAPEX NPV = ${(capexNPV/1000000).toFixed(2)} mln PLN`);
    console.log(`   EaaS NPV = ${(eaasNPV/1000000).toFixed(2)} mln PLN`);

    results.push({
      key: key,
      capacity: centralizedCalc.common.capacityKwp,
      autoconsumptionRatio: autoconsumptionRatio * 100,
      capexNPV: capexNPV,
      capexIRR: capexIRR,
      eaasNPV: eaasNPV,
      // Composite score: normalized NPV * autoconsumption ratio
      capexScore: (capexNPV / 1000000) * autoconsumptionRatio,
      eaasScore: (eaasNPV / 1000000) * autoconsumptionRatio
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
          <div style="margin-left:20px;color:#1565c0">NPV: ${(r.capexNPV / 1000000).toFixed(2)} mln PLN</div>
          <div style="margin-left:20px;color:#1565c0">IRR: ${(r.capexIRR * 100).toFixed(1)}%</div>
          <div style="margin-left:20px;color:#1565c0">Autokonsumpcja: ${r.autoconsumptionRatio.toFixed(1)}%</div>
        </div>
      `;
    } else {
      capexPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>🏆 Najlepszy NPV:</strong> Wariant ${bestCapexNPV.key} (${bestCapexNPV.capacity} kWp)</div>
          <div style="margin-left:20px;color:#1565c0">NPV: ${(bestCapexNPV.capexNPV / 1000000).toFixed(2)} mln PLN, IRR: ${(bestCapexNPV.capexIRR * 100).toFixed(1)}%</div>
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
          <div style="margin-left:20px;color:#e65100">NPV: ${(r.eaasNPV / 1000000).toFixed(2)} mln PLN</div>
          <div style="margin-left:20px;color:#e65100">Autokonsumpcja: ${r.autoconsumptionRatio.toFixed(1)}%</div>
        </div>
      `;
    } else {
      eaasPanel.innerHTML = `
        <div style="font-size:13px;line-height:1.8">
          <div><strong>🏆 Najlepszy NPV:</strong> Wariant ${bestEaasNPV.key} (${bestEaasNPV.capacity} kWp)</div>
          <div style="margin-left:20px;color:#e65100">NPV: ${(bestEaasNPV.eaasNPV / 1000000).toFixed(2)} mln PLN</div>
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
        <td class="${r.capexNPV >= 0 ? 'positive' : 'negative'}">${formatNumberEU(r.capexNPV / 1000000, 2)}</td>
        <td>${formatNumberEU(r.capexIRR * 100, 1)}</td>
        <td class="${r.eaasNPV >= 0 ? 'positive' : 'negative'}">${formatNumberEU(r.eaasNPV / 1000000, 2)}</td>
        <td style="color:${modelColor};font-weight:600">${betterModel}</td>
      `;

      tableBody.appendChild(row);
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
  const totalEnergyPrice = centralizedCalc.common.totalEnergyPrice || 800; // PLN/MWh
  const inflationRate = centralizedCalc.common.inflationRate || 0.025;

  // A. Energia z sieci = całkowite zużycie zakładu (bez PV musiałby pobrać całość z sieci)
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = annualConsumptionKwh / 1000;

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
    selfConsumedMwh: (yearData.selfConsumed || 0) / 1000,
    gridCost: yearData.gridCost || 0,
    eaasCost: yearData.eaasCost || 0,
    netSavings: yearData.savings || 0
  }));
  console.log('📊 eaasYearlyData populated with', eaasYearlyData.length, 'years for Bankability');

  for (const yearData of eaasCashFlows) {
    const year = yearData.year;
    // Use selfConsumed directly from cashFlows (already includes degradation) - in kWh
    const autoconsumptionKwh = yearData.selfConsumed || 0;
    const autoconsumptionMwh = autoconsumptionKwh / 1000;
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
    // B. Koszt OSD (tys. PLN) - koszt całego zużycia z sieci (gdyby nie było PV)
    // C. Auto PV (MWh) - bezpośrednia autokonsumpcja z PV
    // D. Auto BESS (MWh) - autokonsumpcja z baterii
    // E. Suma Auto (MWh) - całkowita autokonsumpcja
    // F. Równow. OSD (tys. PLN) - koszt energii z sieci za ilość równą autokonsumpcji
    // G. Koszt EaaS (tys. PLN) - koszt abonamentu EaaS
    // H. Oszczędn. (tys. PLN) - Równoważny Koszt OSD minus Koszt EaaS
    // I. NPV (mln PLN) - skumulowany NPV

    // Breakdown autokonsumpcji
    const pvDirectMwh = (yearData.selfConsumedPvDirect || 0) / 1000; // kWh → MWh
    const bessMwh = (yearData.selfConsumedBess || 0) / 1000; // kWh → MWh

    // Degradation percentages (from cashFlows)
    const pvDegPct = yearData.pvDegradationPct || 100;
    const bessDegPct = yearData.bessDegradationPct || 100;

    // Równoważny koszt OSD = autokonsumpcja × cena sieci (to jest gridCost z cash flows)
    const equivalentGridCost = gridCost; // yearData.gridCost already = autoconsumption × price with inflation

    row.innerHTML = `
      <td>${phaseLabel} ${year}</td>
      <td>${formatNumberEU(pvDegPct, 1)}</td>
      <td>${formatNumberEU(bessDegPct, 1)}</td>
      <td>${formatNumberEU(gridEnergyMwh, 1)}</td>
      <td>${formatNumberEU(yearGridCostFull / 1000, 0)}</td>
      <td>${formatNumberEU(pvDirectMwh, 1)}</td>
      <td>${formatNumberEU(bessMwh, 1)}</td>
      <td>${formatNumberEU(autoconsumptionMwh, 1)}</td>
      <td>${formatNumberEU(equivalentGridCost / 1000, 0)}</td>
      <td>${formatNumberEU(eaasCost / 1000, 0)}</td>
      <td class="${savingsClass}">${formatNumberEU(savings / 1000, 0)}</td>
      <td class="${npvClass}">${formatNumberEU(cumulativeNPV / 1000000, 2)}</td>
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
    <td class="positive" style="color:#f57c00">${formatNumberEU(eaasPhaseSavings / 1000, 0)}</td>
    <td style="text-align:left;font-size:11px;color:#666">&nbsp;tys. PLN</td>
  `;
  tableBody.appendChild(eaasSummaryRow);

  // Add ownership phase summary row
  const ownershipSummaryRow = document.createElement('tr');
  ownershipSummaryRow.style.background = '#e8f5e9';
  ownershipSummaryRow.style.fontWeight = '600';

  ownershipSummaryRow.innerHTML = `
    <td colspan="10" style="text-align:right;color:#4caf50">🏠 Suma oszczędności w fazie własności (lata ${eaasDuration + 1}-${analysisPeriod}):</td>
    <td class="positive" style="color:#4caf50">${formatNumberEU(ownershipPhaseSavings / 1000, 0)}</td>
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
    <td colspan="10" style="text-align:right">💰 SUMA CAŁKOWITA (25 lat) / NPV (${formatNumberEU(discountRate * 100, 0)}%):</td>
    <td class="positive">${formatNumberEU(totalSavings / 1000, 0)}</td>
    <td class="${npvClass}">${formatNumberEU(cumulativeNPV / 1000000, 2)}</td>
  `;
  tableBody.appendChild(totalSummaryRow);

  console.log('✅ EaaS yearly table generated. EaaS phase:', (eaasPhaseSavings / 1000).toFixed(0), 'tys. PLN, Ownership phase:', (ownershipPhaseSavings / 1000).toFixed(0), 'tys. PLN, NPV:', (cumulativeNPV / 1000000).toFixed(2), 'mln PLN');

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
  console.log('📥 Exporting EaaS analysis to Excel...', withFormulas ? '(WITH FORMULAS)' : '(values only)');

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
  const autoconsumptionMwh = variant.self_consumed / 1000; // kWh to MWh
  const capex = capacityKwp * getCapexForCapacity(capacityKwp);
  const annualConsumption = getAnnualConsumptionKwh();

  // Calculate EaaS metrics (same params as calculateEaaS)
  const eaasParams = {
    annualConsumptionKWh: annualConsumption,
    annualPVProductionKWh: variant.production,
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
  const annualConsumptionMwh = annualConsumptionKwh / 1000;

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
  const annualSavingsDisplay = result.metrics.annualSavingsPLN * currencyMultiplier / 1000;

  const summaryData = [
    [''],  // Row 1 - logo area
    [''],  // Row 2 - logo area
    ['ANALIZA EaaS (Energy-as-a-Service)'],  // Row 3 - title at bottom of merged area
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
  const baseSubscriptionCost = centralizedCalc.eaas.baseSubscription || (window.eaasSubscription || 166760);
  const baseOmCost = centralizedCalc.eaas.baseOmCost || 0;
  const baseInsuranceCost = centralizedCalc.eaas.baseInsuranceCost || 0;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';

  // currency and fxPlnEur already defined above (for Sheet 1)

  // Get degradation rates (same as used in centralizedMetrics)
  const pvDegradationYear1 = (systemSettings?.pvDegradationYear1 !== undefined ? systemSettings.pvDegradationYear1 : 2.0) / 100;
  const pvDegradationYears2Plus = params.degradation_rate; // for years 2+

  // Base autoconsumption BEFORE Year 1 degradation (to match centralizedMetrics calculation)
  // centralizedMetrics applies: Year1 = base * (1 - pvDegradationYear1), Year2+ = Year1 * (1 - degradationRate)^(year-1)
  const baseAutoconsumptionMwh = autoconsumptionMwh; // This is variant.self_consumed / 1000 (before any degradation)

  console.log('📥 Export EaaS with FORMULAS - baseAutoconsumption:', baseAutoconsumptionMwh, 'MWh');
  console.log('📥 Degradation: Year1:', (pvDegradationYear1 * 100).toFixed(1) + '%, Years2+:', (pvDegradationYears2Plus * 100).toFixed(2) + '%/yr');

  // Convert values to contract currency for Sheet 2
  const baseSubscriptionDisplay = baseSubscriptionCost * currencyMultiplier / 1000; // tys. w walucie kontraktu
  const totalEnergyPriceDisplay = totalEnergyPrice * currencyMultiplier; // w walucie kontraktu

  // Create worksheet manually to set formulas
  // PARAMETRY: labels in columns B-D (merged), values in column E
  const ws2 = XLSX.utils.aoa_to_sheet([
    ['', 'ANALIZA EaaS ROK PO ROKU Z NPV'],
    [''],
    ['', 'PARAMETRY:'],
    ['', 'Stopa dyskontowa:', '', '', roundNum(discountRate, 4)],                                // B4, E4 (0.10 = 10%)
    ['', 'Inflacja:', '', '', roundNum(inflationRate, 4)],                                       // B5, E5 (0.025 = 2.5%)
    ['', 'Degradacja PV Rok 1:', '', '', roundNum(pvDegradationYear1, 4)],                       // B6, E6 (0.02 = 2%)
    ['', 'Degradacja PV Lata 2+:', '', '', roundNum(pvDegradationYears2Plus, 4)],                // B7, E7 (0.004 = 0.4%)
    ['', 'Okres umowy EaaS [lat]:', '', '', eaasDuration],                                       // B8, E8
    ['', 'Okres analizy [lat]:', '', '', analysisPeriod],                                        // B9, E9
    ['', 'Autokonsumpcja bazowa [MWh]:', '', '', roundNum(baseAutoconsumptionMwh, 2)],           // B10, E10
    ['', `Cena sieci bazowa [${currencyLabel}/MWh]:`, '', '', roundNum(totalEnergyPriceDisplay, 2)],    // B11, E11
    ['', `Abonament EaaS [tys. ${currencyLabel}/rok]:`, '', '', roundNum(baseSubscriptionDisplay, 2)],  // B12, E12
    ['', `O&M + Ubezp. (rok 1 własności) [tys. ${currencyLabel}/rok]:`, '', '', null], // B13, E13 - formula set below
    ['', 'Indeksacja EaaS:', '', '', eaasIndexation === 'cpi' ? 'Rata indeksowana inflacją' : 'Rata stała'],  // B14, E14
    ['', currencyInfoLabel, '', '', currencyInfoValue],  // B15, E15 - Currency info (Waluta EUR: / 4,25 PLN/EUR)
    [''],  // Row 16 - empty row before header
    // Header row (row 17)
    ['Rok', 'Faza', 'Autokonsumpcja [MWh]', `Koszt Sieci [tys. ${currencyLabel}]`, `Koszt EaaS/Własność [tys. ${currencyLabel}]`, `Oszczędności [tys. ${currencyLabel}]`, `CF Zdyskontowany [tys. ${currencyLabel}]`, `Skumulowany NPV [mln ${currencyLabel}]`]
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
  const baseOmTotalThousands = (baseOmCost + baseInsuranceCost) * currencyMultiplier / 1000; // tys. w walucie kontraktu
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

  const dataStartRow = 18; // Row 18 is first data row (header is now row 17 due to currency info row)
  let cumulativeNPV = 0;
  let eaasPhaseSavings = 0;
  let ownershipPhaseSavings = 0;

  for (let year = 1; year <= analysisPeriod; year++) {
    const row = dataStartRow + year - 1;
    const prevRow = row - 1;
    const yearData = eaasCashFlows[year - 1]; // Get pre-calculated values from centralizedMetrics

    // Get values from centralizedMetrics (these are the correct values in PLN)
    const autoconsumptionKwh = yearData?.selfConsumed || 0;
    const autoconsumptionYearMwh = autoconsumptionKwh / 1000;
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

    // Column C: Autokonsumpcja [MWh] - formula with Year1 and Years2+ degradation
    // Year 1: base * (1 - degYear1)
    // Year 2+: base * (1 - degYear1) * (1 - degYears2+)^(year-1)
    // E10=autokonsumpcja bazowa, E6=degradacja rok 1, E7=degradacja lata 2+
    const autoFormula = `ROUND($E$10*(1-$E$6)*POWER(1-$E$7,A${row}-1),2)`;
    setCell(ws2, 2, row, autoFormula, roundNum(autoconsumptionYearMwh, 2));

    // Column D: Koszt Sieci [tys. PLN] = Autokonsumpcja * cena * inflacja
    // E11 jest teraz w PLN/MWh, autokonsumpcja w MWh -> wynik w PLN, dzielimy przez 1000 żeby mieć tys. PLN
    // E5 = inflacja
    const gridCostFormula = `ROUND(C${row}*$E$11/1000*POWER(1+$E$5,A${row}-1),2)`;
    setCell(ws2, 3, row, gridCostFormula, roundNum(gridCost / 1000, 2));

    // Column E: Koszt EaaS/Własność [tys. PLN]
    // W fazie EaaS: abonament (z lub bez indeksacji inflacją) - O&M nie występuje
    // W fazie Własność: E13 (już zindeksowane na rok 1 własności) × inflacja od tego momentu
    // E8=okres EaaS, E14=indeksacja, E12=abonament, E5=inflacja
    // E13=O&M już zindeksowane = bazowy * (1+inflacja)^okres_EaaS
    // Rok 16: E13 * (1.03)^0 = E13, Rok 17: E13 * (1.03)^1, itd.
    const eaasCostFormula = `IF(A${row}<=$E$8,IF($E$14="Rata indeksowana inflacją",$E$12*POWER(1+$E$5,A${row}-1),$E$12),$E$13*POWER(1+$E$5,A${row}-$E$8-1))`;
    setCell(ws2, 4, row, eaasCostFormula, roundNum(eaasCost / 1000, 2));

    // Column F: Oszczędności [tys. PLN] = Koszt Sieci - Koszt EaaS
    const savingsFormula = `ROUND(D${row}-E${row},2)`;
    setCell(ws2, 5, row, savingsFormula, roundNum(savings / 1000, 2));

    // Column G: CF Zdyskontowany [tys. PLN]
    // E4 = stopa dyskontowa
    const discountedFormula = `ROUND(F${row}/POWER(1+$E$4,A${row}),2)`;
    setCell(ws2, 6, row, discountedFormula, roundNum(discountedCF / 1000, 2));

    // Column H: Skumulowany NPV [mln PLN]
    const npvFormula = year === 1 ? `ROUND(G${row}/1000,2)` : `ROUND(H${prevRow}+G${row}/1000,2)`;
    setCell(ws2, 7, row, npvFormula, roundNum(cumulativeNPV / 1000000, 2));
  }

  // Summary rows
  const lastDataRow = dataStartRow + analysisPeriod - 1;
  const summaryRow1 = lastDataRow + 2;
  const summaryRow2 = summaryRow1 + 1;
  const summaryRow3 = summaryRow2 + 1;

  // Extend sheet range
  ws2['!ref'] = XLSX.utils.encode_range({ s: { c: 0, r: 0 }, e: { c: 7, r: summaryRow3 - 1 } });

  // Suma faza EaaS
  ws2[XLSX.utils.encode_cell({ c: 4, r: summaryRow1 - 1 })] = { t: 's', v: `Suma faza EaaS (1-${eaasDuration}):` };
  ws2[XLSX.utils.encode_cell({ c: 5, r: summaryRow1 - 1 })] = {
    t: 'n',
    f: `SUMIF(B${dataStartRow}:B${lastDataRow},"EaaS",F${dataStartRow}:F${lastDataRow})`,
    v: roundNum(eaasPhaseSavings / 1000, 0)
  };

  // Suma faza Własność
  ws2[XLSX.utils.encode_cell({ c: 4, r: summaryRow2 - 1 })] = { t: 's', v: `Suma faza Własność (${eaasDuration + 1}-${analysisPeriod}):` };
  ws2[XLSX.utils.encode_cell({ c: 5, r: summaryRow2 - 1 })] = {
    t: 'n',
    f: `SUMIF(B${dataStartRow}:B${lastDataRow},"Własność",F${dataStartRow}:F${lastDataRow})`,
    v: roundNum(ownershipPhaseSavings / 1000, 0)
  };

  // Suma całkowita
  ws2[XLSX.utils.encode_cell({ c: 4, r: summaryRow3 - 1 })] = { t: 's', v: 'SUMA CAŁKOWITA:' };
  ws2[XLSX.utils.encode_cell({ c: 5, r: summaryRow3 - 1 })] = {
    t: 'n',
    f: `SUM(F${dataStartRow}:F${lastDataRow})`,
    v: roundNum((eaasPhaseSavings + ownershipPhaseSavings) / 1000, 0)
  };
  ws2[XLSX.utils.encode_cell({ c: 6, r: summaryRow3 - 1 })] = { t: 's', v: `NPV [mln ${currency}]:` };
  ws2[XLSX.utils.encode_cell({ c: 7, r: summaryRow3 - 1 })] = {
    t: 'n',
    f: `H${lastDataRow}`,
    v: roundNum(cumulativeNPV / 1000000, 2)
  };

  // Set column widths
  ws2['!cols'] = [
    { wch: 6 },   // Rok
    { wch: 12 },  // Faza
    { wch: 22 },  // Autokonsumpcja
    { wch: 22 },  // Koszt Sieci
    { wch: 28 },  // Koszt EaaS/Własność
    { wch: 22 },  // Oszczędności
    { wch: 24 },  // CF Zdyskontowany
    { wch: 24 }   // Skumulowany NPV
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
  headerCell.value = 'ANALIZA EaaS (Energy-as-a-Service)';
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
    { width: 14 },  // D: Autokonsumpcja
    { width: 12 },  // E: Koszt Sieci
    { width: 14 },  // F: Koszt EaaS/Własność / Parameter values
    { width: 13 },  // G: Oszczędności
    { width: 15 },  // H: CF Zdyskontowany (wider)
    { width: 18 }   // I: Skumulowany NPV / NPV [mln PLN]: (wider for summary label)
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
            // First pass: replace with temporary tokens (absolute refs)
            .replace(/\$H/g, '§H§')
            .replace(/\$G/g, '§G§')
            .replace(/\$F/g, '§F§')
            .replace(/\$E/g, '§E§')
            .replace(/\$D/g, '§D§')
            .replace(/\$C/g, '§C§')
            .replace(/\$B/g, '§B§')
            .replace(/\$A/g, '§A§')
            // Second pass: replace tokens with shifted columns
            .replace(/§A§/g, '$B')
            .replace(/§B§/g, '$C')
            .replace(/§C§/g, '$D')
            .replace(/§D§/g, '$E')
            .replace(/§E§/g, '$F')
            .replace(/§F§/g, '$G')
            .replace(/§G§/g, '$H')
            .replace(/§H§/g, '$I');
          // Also handle non-absolute references with tokens
          shiftedFormula = shiftedFormula
            .replace(/([^$§])H(\d+)/g, '$1«H»$2')
            .replace(/([^$§])G(\d+)/g, '$1«G»$2')
            .replace(/([^$§])F(\d+)/g, '$1«F»$2')
            .replace(/([^$§])E(\d+)/g, '$1«E»$2')
            .replace(/([^$§])D(\d+)/g, '$1«D»$2')
            .replace(/([^$§])C(\d+)/g, '$1«C»$2')
            .replace(/([^$§])B(\d+)/g, '$1«B»$2')
            .replace(/([^$§])A(\d+)/g, '$1«A»$2')
            .replace(/«A»/g, 'B')
            .replace(/«B»/g, 'C')
            .replace(/«C»/g, 'D')
            .replace(/«D»/g, 'E')
            .replace(/«E»/g, 'F')
            .replace(/«F»/g, 'G')
            .replace(/«G»/g, 'H')
            .replace(/«H»/g, 'I');
          excelCell.value = { formula: shiftedFormula, result: cell.v };
        } else {
          excelCell.value = cell.v;
        }
        // Apply percentage format for cells F4:F7 (was E4:E7, column F = index 5 after shift)
        if (C === 4 && R >= 3 && R <= 6) {
          excelCell.numFmt = '0.00%';
        }
        // Apply number format with thousand separator for data rows (row 17+, columns D-I)
        // Row 16 is header (R=15), data starts at R=16 (row 17)
        if (R >= 16 && C >= 2 && C <= 7 && typeof cell.v === 'number') {
          excelCell.numFmt = '#,##0.00';  // Format: 1 000,00
        }
      }
    }
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

  // Merge cells C:E for parameter labels (rows 4-15, including currency info) and style them - shifted +1
  for (let r = 4; r <= 15; r++) {
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

  // Style header row (row 17) - enhanced with text wrapping, taller for visibility
  const headerRow = excelSheet2.getRow(17);
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

  // Add logo to Sheet 2 (top right corner, columns H-I, row 1) - shifted +1
  if (logoImageId !== null) {
    excelSheet2.addImage(logoImageId, {
      tl: { col: 7, row: 0.2 },  // Top-left position (column H, row 1)
      ext: { width: 180, height: 45 }  // Size in pixels
    });
  }

  // Freeze header row and parameters (header is now row 17)
  excelSheet2.views = [{ state: 'frozen', ySplit: 17, xSplit: 0, showGridLines: false, showRowColHeaders: false }];

  // Add alternating row shading will be handled by conditional formatting
  // Add borders to data cells - shifted +1 column
  for (let r = dataStartRow; r <= lastDataRow; r++) {
    const row = excelSheet2.getRow(r);
    for (let c = 2; c <= 9; c++) {  // Start from 2 (skip margin), end at 9
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
  const dataRange = `B${dataStartRow}:I${lastDataRow}`;  // B-I instead of A-H

  console.log('📥 Adding conditional formatting for range:', dataRange);

  // Rule 1: EaaS phase - light yellow (#fff8e1) when year <= eaasDuration (cell F8, was E8)
  // Rule 2: Ownership phase - light green (#e8f5e9) when year > eaasDuration
  excelSheet2.addConditionalFormatting({
    ref: dataRange,
    rules: [
      {
        type: 'expression',
        formulae: ['$B18<=$F$8'],  // B is Rok (first data row is 18), F is okres EaaS
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
        formulae: ['$B18>$F$8'],  // B is Rok (first data row is 18), F is okres EaaS
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

  // Add summary rows with styling matching HTML table exactly (like the image)
  // All columns shifted +1 for margin
  const summaryStartRow = lastDataRow + 2;

  // Row 1: Suma oszczędności w fazie EaaS - orange background
  const eaasSummaryRow = excelSheet2.getRow(summaryStartRow);
  eaasSummaryRow.height = 22;
  excelSheet2.mergeCells(summaryStartRow, 2, summaryStartRow, 6); // Merge B-F for label (was A-E)
  eaasSummaryRow.getCell(2).value = `📋  Suma oszczędności w fazie EaaS (lata 1-${eaasDuration}):`;
  eaasSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  eaasSummaryRow.getCell(7).value = { formula: `SUMIF(C${dataStartRow}:C${lastDataRow},"EaaS",G${dataStartRow}:G${lastDataRow})`, result: roundNum(eaasPhaseSavings / 1000, 2) };
  eaasSummaryRow.getCell(7).numFmt = '#,##0.00';
  eaasSummaryRow.getCell(7).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: light orange background #fff3e0, orange text #f57c00
  for (let col = 2; col <= 9; col++) {
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
  excelSheet2.mergeCells(summaryStartRow + 1, 2, summaryStartRow + 1, 6); // Merge B-F for label (was A-E)
  ownershipSummaryRow.getCell(2).value = `🏠  Suma oszczędności w fazie własności (${eaasDuration + 1}-${analysisPeriod}):`;
  ownershipSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  ownershipSummaryRow.getCell(7).value = { formula: `SUMIF(C${dataStartRow}:C${lastDataRow},"Własność",G${dataStartRow}:G${lastDataRow})`, result: roundNum(ownershipPhaseSavings / 1000, 2) };
  ownershipSummaryRow.getCell(7).numFmt = '#,##0.00';
  ownershipSummaryRow.getCell(7).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: light green background #e8f5e9, green text #4caf50
  for (let col = 2; col <= 9; col++) {
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
  excelSheet2.mergeCells(summaryStartRow + 2, 2, summaryStartRow + 2, 6); // Merge B-F for label (was A-E)
  totalSummaryRow.getCell(2).value = '💰  SUMA CAŁKOWITA:';
  totalSummaryRow.getCell(2).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(7).value = { formula: `SUM(G${dataStartRow}:G${lastDataRow})`, result: roundNum((eaasPhaseSavings + ownershipPhaseSavings) / 1000, 2) };
  totalSummaryRow.getCell(7).numFmt = '#,##0.00';
  totalSummaryRow.getCell(7).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(8).value = `NPV [mln ${currency}]:`;
  totalSummaryRow.getCell(8).alignment = { horizontal: 'right', vertical: 'middle' };
  totalSummaryRow.getCell(9).value = { formula: `I${lastDataRow}`, result: roundNum(cumulativeNPV / 1000000, 2) };
  totalSummaryRow.getCell(9).numFmt = '#,##0.00';
  totalSummaryRow.getCell(9).alignment = { horizontal: 'right', vertical: 'middle' };
  // Style: gradient-like effect with bold
  for (let col = 2; col <= 9; col++) {
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

  // Set print area and page setup
  excelSheet2.pageSetup.printArea = `A1:H${summaryStartRow + 2}`;
  excelSheet2.pageSetup.fitToPage = true;
  excelSheet2.pageSetup.fitToWidth = 1;
  excelSheet2.pageSetup.orientation = 'landscape';

  // Store row references for Sheet 3 formulas (when withFormulas=true)
  // Sheet 2 has: column G = Oszczędności [tys. PLN], column I = Skumulowany NPV [mln PLN]
  const sheet2Refs = {
    eaasSumRow: summaryStartRow,        // Row with EaaS phase sum (column G)
    ownershipSumRow: summaryStartRow + 1, // Row with Ownership phase sum (column G)
    totalSumRow: summaryStartRow + 2,    // Row with SUMA CAŁKOWITA (column G)
    npvFinalRow: lastDataRow,            // Row with final NPV (column I)
    // Excel cell references for cross-sheet formulas
    eaasSum: `'EaaS Rok po Roku'!G${summaryStartRow}`,
    ownershipSum: `'EaaS Rok po Roku'!G${summaryStartRow + 1}`,
    totalSum: `'EaaS Rok po Roku'!G${summaryStartRow + 2}`,
    npvFinal: `'EaaS Rok po Roku'!I${lastDataRow}`
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
  excelSheet3.getCell('B1').value = `ANALIZA CFO - Model EaaS`;
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
  // Row 6: More parameters
  excelSheet3.getCell(`B${cfoRow}`).value = 'Autokonsumpcja [MWh/rok]';
  excelSheet3.getCell(`C${cfoRow}`).value = autoconsumptionMwh;  // C6 = autoconsumption
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0.0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = 'Degradacja PV [%/rok]';
  excelSheet3.getCell(`E${cfoRow}`).value = pvDegradationYears2Plus;  // E6 = degradation
  excelSheet3.getCell(`E${cfoRow}`).numFmt = '0.00%';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };

  cfoRow++;
  // Row 7: More parameters
  excelSheet3.getCell(`B${cfoRow}`).value = `Cena sieci [${currencyLabel}/MWh]`;
  excelSheet3.getCell(`C${cfoRow}`).value = gridPriceDisplay;  // C7 = grid price
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`D${cfoRow}`).value = `Cena EaaS [${currencyLabel}/MWh]`;
  excelSheet3.getCell(`E${cfoRow}`).value = eaasPriceDisplay;  // E7 = EaaS price
  excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
  excelSheet3.getCell(`F${cfoRow}`).value = 'Emisja CO₂ [kg/kWh]';
  excelSheet3.getCell(`G${cfoRow}`).value = 0.7;  // G7 = CO2 factor
  excelSheet3.getCell(`G${cfoRow}`).numFmt = '0.0';
  excelSheet3.getCell(`G${cfoRow}`).font = { bold: true };
  const gridPriceParamRow = cfoRow; // Store row number for matrix formulas

  cfoRow++;
  // Row 8: Calculated degradation factor for formulas
  excelSheet3.getCell(`B${cfoRow}`).value = 'Wskaźnik degradacji śr.';
  excelSheet3.getCell(`C${cfoRow}`).value = 1 - pvDegradationYears2Plus * cfoPeriod / 2;  // C8 = degradation factor
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0.000';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = '= 1 - degradacja × okres / 2';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };
  const degradFactorParamRow = cfoRow;

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
  const baseTotalSavings = (totalSavingsEaaS + totalSavingsOwnership) / 1000; // Convert from PLN to tys. PLN
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
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `${sheet2Refs.eaasSum}/1000`, result: roundNum(totalSavingsEaaS / 1000, 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(totalSavingsEaaS / 1000, 2);
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
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `${sheet2Refs.ownershipSum}/1000`, result: roundNum(totalSavingsOwnership / 1000, 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum(totalSavingsOwnership / 1000, 2);
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
    excelSheet3.getCell(`C${cfoRow}`).value = { formula: `C${kpiEaaSRow}+C${kpiOwnRow}`, result: roundNum((totalSavingsEaaS + totalSavingsOwnership) / 1000, 2) };
  } else {
    excelSheet3.getCell(`C${cfoRow}`).value = roundNum((totalSavingsEaaS + totalSavingsOwnership) / 1000, 2);
  }
  excelSheet3.getCell(`C${cfoRow}`).numFmt = `#,##0.00 "mln ${currencyLabel}"`;
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF1565C0' }, size: 12 };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = withFormulas ? `= C${kpiEaaSRow} + C${kpiOwnRow}` : 'Skumulowana z uwzgl. degradacji PV';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

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

  // --- SECTION 2: TORNADO CHART - Oszczędności na 30 lat w PLN ---
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'ANALIZA WRAŻLIWOŚCI - TORNADO CHART';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF1565C0' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `Wpływ na CAŁKOWITE oszczędności (${cfoPeriod} lat) przy zmianie parametru:`;
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

  // Sensitivity data with 30-year calculations (tys. PLN)
  //
  // === LOGIKA EKONOMICZNA TORNADO CHART ===
  //
  // Oszczędności = Autokonsumpcja × (Cena_sieci - Cena_EaaS) = Autokonsumpcja × Marża
  //
  // Dla CENY ENERGII Z SIECI:
  //   Marża bazowa = Cena_sieci - Cena_EaaS
  //   Jeśli Cena_sieci spada o 20%:
  //     Nowa_cena = Cena_sieci × 0.80
  //     Nowa_marża = Nowa_cena - Cena_EaaS = Cena_sieci×0.80 - Cena_EaaS
  //     Zmiana_marży = (Nowa_marża) / (Stara_marża)
  //                  = (Cena_sieci×0.80 - Cena_EaaS) / (Cena_sieci - Cena_EaaS)
  //
  //   gridPriceRatio = Cena_sieci / Marża = ile razy zmiana ceny wpływa na marżę
  //   Przy cenie 961 i EaaS 398: ratio = 961/(961-398) = 1.71
  //   Zmiana ceny o -20% → zmiana marży o -20%×1.71 = -34%
  //
  // Dla CENY ABONAMENTU EaaS (odwrotnie!):
  //   eaasPriceRatio = Cena_EaaS / Marża
  //   Przy cenie EaaS 398: ratio = 398/563 = 0.71
  //   Wzrost ceny EaaS o +20% → spadek marży o -20%×0.71 = -14%
  //
  const gridPriceRatio = gridPriceDisplay / (gridPriceDisplay - eaasPriceDisplay);
  const eaasPriceRatio = eaasPriceDisplay / (gridPriceDisplay - eaasPriceDisplay);

  console.log('📊 Tornado ratios:', { gridPriceRatio, eaasPriceRatio, gridPrice: gridPriceDisplay, eaasPrice: eaasPriceDisplay });

  const tornadoData = [
    {
      param: 'Cena energii z sieci',
      variation: '±20%',
      // Cena sieci -20% → marża spada o 20% × gridPriceRatio
      pessimisticSavings: baseTotalSavings * (1 - 0.20 * gridPriceRatio),
      optimisticSavings: baseTotalSavings * (1 + 0.20 * gridPriceRatio),
      // Mnożniki do formul Excel
      pessMultiplier: roundNum(1 - 0.20 * gridPriceRatio, 4),
      optMultiplier: roundNum(1 + 0.20 * gridPriceRatio, 4),
      formulaExplanation: `base × (1 - 0.20 × ${roundNum(gridPriceRatio, 2)})`
    },
    {
      param: 'Cena abonamentu EaaS',
      variation: '±20%',
      // Cena EaaS +20% → marża SPADA o 20% × eaasPriceRatio
      pessimisticSavings: baseTotalSavings * (1 - 0.20 * eaasPriceRatio),
      optimisticSavings: baseTotalSavings * (1 + 0.20 * eaasPriceRatio),
      pessMultiplier: roundNum(1 - 0.20 * eaasPriceRatio, 4),
      optMultiplier: roundNum(1 + 0.20 * eaasPriceRatio, 4),
      formulaExplanation: `base × (1 - 0.20 × ${roundNum(eaasPriceRatio, 2)})`
    },
    {
      param: 'Yield PV (produkcja)',
      variation: '±15%',
      // Yield bezpośrednio skaluje oszczędności (proporcjonalnie)
      pessimisticSavings: baseTotalSavings * 0.85,
      optimisticSavings: baseTotalSavings * 1.15,
      pessMultiplier: 0.85,
      optMultiplier: 1.15,
      formulaExplanation: 'base × 0.85 / base × 1.15'
    },
    {
      param: 'Autokonsumpcja',
      variation: '±10%',
      // Autokonsumpcja bezpośrednio skaluje oszczędności
      pessimisticSavings: baseTotalSavings * 0.90,
      optimisticSavings: baseTotalSavings * 1.10,
      pessMultiplier: 0.90,
      optMultiplier: 1.10,
      formulaExplanation: 'base × 0.90 / base × 1.10'
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
  // When withFormulas=true, use Excel formulas referencing base savings cell (C${kpiTotalTysRow})
  const tornadoDataStartRow = cfoRow + 1;
  tornadoData.forEach((t, idx) => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = t.param;
    excelSheet3.getCell(`C${cfoRow}`).value = t.variation;
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    // Pessimistic value (tys. PLN) - formula: base × pessMultiplier
    if (withFormulas) {
      excelSheet3.getCell(`D${cfoRow}`).value = {
        formula: `ROUND($C$${kpiTotalTysRow}*${t.pessMultiplier},0)`,
        result: roundNum(t.pessimisticSavings, 0)
      };
    } else {
      excelSheet3.getCell(`D${cfoRow}`).value = roundNum(t.pessimisticSavings, 0);
    }
    excelSheet3.getCell(`D${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FFC62828' } };
    excelSheet3.getCell(`D${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFEBEE' } };

    // Base value (tys. PLN) - formula: reference to total savings cell
    if (withFormulas) {
      excelSheet3.getCell(`E${cfoRow}`).value = {
        formula: `ROUND($C$${kpiTotalTysRow},0)`,
        result: roundNum(tornadoBaseSavings30, 0)
      };
    } else {
      excelSheet3.getCell(`E${cfoRow}`).value = roundNum(tornadoBaseSavings30, 0);
    }
    excelSheet3.getCell(`E${cfoRow}`).numFmt = '#,##0';
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`E${cfoRow}`).font = { bold: true };
    excelSheet3.getCell(`E${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    // Optimistic value (tys. PLN) - formula: base × optMultiplier
    if (withFormulas) {
      excelSheet3.getCell(`F${cfoRow}`).value = {
        formula: `ROUND($C$${kpiTotalTysRow}*${t.optMultiplier},0)`,
        result: roundNum(t.optimisticSavings, 0)
      };
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

  // Add formula explanation column (H) when withFormulas=true for audit trail
  if (withFormulas) {
    excelSheet3.getCell(`H${tornadoHeaderRow}`).value = 'Formuła (mnożnik)';
    excelSheet3.getCell(`H${tornadoHeaderRow}`).font = { bold: true, size: 9 };
    excelSheet3.getCell(`H${tornadoHeaderRow}`).alignment = { horizontal: 'left' };
    excelSheet3.getColumn('H').width = 28;

    let explRow = tornadoDataStartRow;
    tornadoData.forEach((t, idx) => {
      excelSheet3.getCell(`H${explRow}`).value = `pess=${t.pessMultiplier}, opt=${t.optMultiplier}`;
      excelSheet3.getCell(`H${explRow}`).font = { size: 8, italic: true, color: { argb: 'FF757575' } };
      explRow++;
    });
  }

  // Horizontal bar chart visualization using Unicode bars
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `📊 WYKRES TORNADO - Oszczędności ${cfoPeriod} lat [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };

  cfoRow++;
  const chartBaseCol = 4; // Where "0" baseline is
  tornadoData.forEach((t, idx) => {
    cfoRow++;
    // Parameter name
    excelSheet3.getCell(`B${cfoRow}`).value = t.param;
    excelSheet3.getCell(`B${cfoRow}`).font = { size: 10 };

    // Calculate bar lengths relative to max range
    const maxRange = tornadoData[0].range;
    const pessimisticDelta = t.pessimisticSavings - tornadoBaseSavings30;
    const optimisticDelta = t.optimisticSavings - tornadoBaseSavings30;

    // Red bar (pessimistic - left side)
    const redBarLen = Math.round(Math.abs(pessimisticDelta) / maxRange * 15);
    const redBar = '█'.repeat(Math.max(1, redBarLen));
    excelSheet3.getCell(`C${cfoRow}`).value = redBar;
    excelSheet3.getCell(`C${cfoRow}`).font = { color: { argb: 'FFC62828' }, size: 10 };
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'right' };

    // Values
    excelSheet3.getCell(`D${cfoRow}`).value = `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(tornadoBaseSavings30, 0)} | ${roundNum(t.optimisticSavings, 0)}`;
    excelSheet3.getCell(`D${cfoRow}`).font = { size: 9 };
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // Green bar (optimistic - right side)
    const greenBarLen = Math.round(Math.abs(optimisticDelta) / maxRange * 15);
    const greenBar = '█'.repeat(Math.max(1, greenBarLen));
    excelSheet3.getCell(`E${cfoRow}`).value = greenBar;
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

  // --- SECTION 3: SENSITIVITY MATRIX - Oszczędności na 30 lat ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = `MACIERZ WRAŻLIWOŚCI - Oszczędności ${cfoPeriod} lat vs Cena Sieci vs Yield`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  cfoRow += 2;
  const yieldVariations = [-0.15, -0.10, -0.05, 0, 0.05, 0.10, 0.15];
  const gridPriceVariations = [-0.20, -0.10, 0, 0.10, 0.20];

  // Header
  excelSheet3.getCell(`B${cfoRow}`).value = `Oszcz. ${cfoPeriod} lat [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  excelSheet3.mergeCells(`C${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`C${cfoRow}`).value = '← Yield PV →';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, size: 10 };
  excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Cena sieci ↓';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
  excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    excelSheet3.getCell(cfoRow, 3 + i).value = `${yv >= 0 ? '+' : ''}${(yv * 100).toFixed(0)}%`;
    excelSheet3.getCell(cfoRow, 3 + i).font = { bold: true, size: 9 };
    excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    excelSheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  // Matrix data - 30-year savings
  // withFormulas: formula = Autokonsum*(1+yieldVar) * (CenaSieci*(1+gridPriceVar) - CenaEaaS) * Okres * DegradFactor / 1000
  // Parameters: C5=okres, C6=autokonsumpcja, C7=cena_sieci, E7=cena_EaaS, C8=degrad_factor
  gridPriceVariations.forEach(gpv => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = `${gpv >= 0 ? '+' : ''}${(gpv * 100).toFixed(0)}%`;
    excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 9 };
    excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'right' };
    excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      const adjGridPrice = gridPriceDisplay * (1 + gpv);
      const adjAutoconsumption = autoconsumptionMwh * (1 + yv);
      // 30-year savings with degradation
      const savings30 = adjAutoconsumption * (adjGridPrice - eaasPriceDisplay) * cfoPeriod * degradationFactor30 / 1000; // tys. PLN

      const cell = excelSheet3.getCell(cfoRow, 3 + i);

      if (withFormulas) {
        // Formula: Autokons*(1+yv) * (CenaSieci*(1+gpv) - CenaEaaS) * Okres * DegradFactor / 1000
        // Using fixed cell references: C5=okres, C6=autokonsumpcja, C7=cena_sieci, E7=cena_EaaS, C8=degrad_factor
        const yvStr = yv >= 0 ? `+${yv}` : yv.toString();
        const gpvStr = gpv >= 0 ? `+${gpv}` : gpv.toString();
        cell.value = {
          formula: `ROUND($C$6*(1${yvStr})*($C$7*(1${gpvStr})-$E$7)*$C$5*$C$8/1000,0)`,
          result: roundNum(savings30, 0)
        };
      } else {
        cell.value = roundNum(savings30, 0);
      }
      cell.numFmt = '#,##0';
      cell.alignment = { horizontal: 'center' };

      // Color coding based on 30-year base savings
      if (savings30 > tornadoBaseSavings30 * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (savings30 > tornadoBaseSavings30 * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (savings30 > 0) {
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
  excelSheet3.getCell(`C${cfoRow}`).value = co2FactorKgPerKwh;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '0.0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Średnia dla Polski (2024)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = '🌍 Redukcja CO₂ rocznie [tony]';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons, 0);
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = `= ${roundNum(autoconsumptionMwh, 0)} MWh × ${co2FactorKgPerKwh} t/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `🌍 Redukcja CO₂ (${cfoPeriod} lat) [tony]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(totalCO2Tons, 0);
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Całkowity wpływ projektu (z degradacją)';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = '🚗 Ekwiwalent samochodów';
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 4.6, 0); // car emits 4.6 tons/year
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Roczna emisja tylu aut osobowych';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '🌳 Ekwiwalent drzew';
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 0.022, 0); // tree absorbs 22kg/year
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet3.mergeCells(`D${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`D${cfoRow}`).value = 'Drzew potrzebnych do pochłonięcia CO₂';
  excelSheet3.getCell(`D${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '✈️ Ekwiwalent lotów WAW-LON';
  excelSheet3.getCell(`C${cfoRow}`).value = roundNum(annualCO2Tons / 0.255, 0); // WAW-LON ~255kg CO2
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

  // --- SECTION 5: BREAK-EVEN ANALYSIS - DIRECT VALUES ---
  const breakEvenGridPrice = eaasPriceDisplay; // Break-even = when grid price = EaaS price
  const safetyMarginPct = (gridPriceDisplay - eaasPriceDisplay) / gridPriceDisplay;

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
  excelSheet3.getCell(`B${cfoRow}`).value = '⚠️ BREAK-EVEN: Cena sieci';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  excelSheet3.getCell(`C${cfoRow}`).value = breakEvenGridPrice;
  excelSheet3.getCell(`C${cfoRow}`).numFmt = '#,##0';
  excelSheet3.getCell(`C${cfoRow}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  excelSheet3.getCell(`C${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  excelSheet3.getCell(`D${cfoRow}`).value = `${currencyLabel}/MWh`;
  excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF757575' } };
  excelSheet3.mergeCells(`E${cfoRow}:G${cfoRow}`);
  excelSheet3.getCell(`E${cfoRow}`).value = 'Poniżej tej ceny EaaS nie generuje oszczędności';
  excelSheet3.getCell(`E${cfoRow}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = '🛡️ Margines bezpieczeństwa';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 11 };
  excelSheet3.getCell(`C${cfoRow}`).value = safetyMarginPct;
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
  excelSheet3.getCell(`B${cfoRow}`).value = `Projekcja oszczędności ${cfoPeriod} lat przy różnych założeniach:`;
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
  excelSheet3.getCell(`E${cfoRow}`).value = `Oszcz. ${cfoPeriod} lat`;
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
  // baseTotalSavings is already defined earlier (after KPI section)
  console.log('📊 Scenarios - baseTotalSavings:', baseTotalSavings, 'tys. PLN');

  scenarios.forEach((s, idx) => {
    cfoRow++;
    // For BAZOWY scenario (gridMult=1.0, yieldMult=1.0), use exact value from Sheet 2
    // For other scenarios, scale proportionally based on grid price and yield multipliers
    let scenarioSavings;
    if (s.gridMult === 1.0 && s.yieldMult === 1.0) {
      // Bazowy = exact same as SUMA CAŁKOWITA
      scenarioSavings = baseTotalSavings;
    } else {
      // For other scenarios, approximate scaling:
      // Grid price affects both phases, yield affects energy production
      // Simplified: savings ≈ baseSavings * yieldMult * weighted_grid_factor
      // where weighted_grid_factor accounts for grid price change in both phases
      const gridFactor = s.gridMult; // Grid price multiplier affects savings proportionally
      const yieldFactor = s.yieldMult; // Yield affects energy production
      scenarioSavings = baseTotalSavings * yieldFactor * gridFactor;
    }
    const weightedValue = scenarioSavings * s.prob;
    console.log(`📊 Scenario ${s.name}:`, { gridMult: s.gridMult, yieldMult: s.yieldMult, scenarioSavings });

    excelSheet3.getCell(`B${cfoRow}`).value = s.name;
    excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, color: { argb: s.color } };

    excelSheet3.getCell(`C${cfoRow}`).value = s.gridMult - 1;
    excelSheet3.getCell(`C${cfoRow}`).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(`C${cfoRow}`).alignment = { horizontal: 'center' };

    excelSheet3.getCell(`D${cfoRow}`).value = s.yieldMult - 1;
    excelSheet3.getCell(`D${cfoRow}`).numFmt = '+0%;-0%;0%';
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };

    // Oszczędności - use formula or value
    if (withFormulas) {
      // Formula: base * (1 + gridMult-1) * (1 + yieldMult-1) = base * gridMult * yieldMult
      excelSheet3.getCell(`E${cfoRow}`).value = { formula: `ROUND($C$${kpiTotalTysRow}*(1+C${cfoRow})*(1+D${cfoRow}),0)`, result: roundNum(scenarioSavings, 0) };
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

  // --- SECTION 7: INFLATION SENSITIVITY ---
  cfoRow += 3;
  excelSheet3.mergeCells(`B${cfoRow}:I${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = 'WRAŻLIWOŚĆ NA INFLACJĘ CEN ENERGII';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `Jak zmienia się całkowita oszczędność ${cfoPeriod} lat przy różnej inflacji cen energii:`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet3.mergeCells(`B${cfoRow}:H${cfoRow}`);

  // Inflation scenarios
  const inflationRates = [0, 0.02, 0.03, 0.05, 0.07, 0.10];

  cfoRow += 2;
  excelSheet3.getCell(`B${cfoRow}`).value = 'Roczna inflacja cen energii';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };
  inflationRates.forEach((inf, i) => {
    excelSheet3.getCell(cfoRow, 3 + i).value = inf;
    excelSheet3.getCell(cfoRow, 3 + i).numFmt = '0%';
    excelSheet3.getCell(cfoRow, 3 + i).font = { bold: true };
    excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    excelSheet3.getCell(cfoRow, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRow++;
  const inflValuesRow = cfoRow;  // Store row for % change formulas
  excelSheet3.getCell(`B${cfoRow}`).value = `Oszczędności ${cfoPeriod} lat [tys. ${currencyLabel}]`;
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true };

  // Base inflation from centralizedMetrics (typically 2.5%)
  const baseInflation = inflationRate; // from centralizedCalc.common.inflationRate
  const inflHeaderRow = cfoRow - 1;  // Row with inflation rates

  // Find column with base inflation for formulas
  const baseInflColIndex = inflationRates.findIndex(r => Math.abs(r - baseInflation) < 0.01);
  const baseInflColLetter = String.fromCharCode(67 + (baseInflColIndex >= 0 ? baseInflColIndex : 1)); // C=67, default to D

  inflationRates.forEach((inf, i) => {
    // Scale from baseTotalSavings based on inflation difference
    // At baseInflation (2.5%), savings = baseTotalSavings
    // At higher inflation, savings increase (energy prices grow faster)
    // At 0% inflation, savings are lower (no grid price growth)

    // Approximate: each 1% extra inflation adds ~15% to total savings over 30 years
    // This is a simplification - proper calculation would need year-by-year recalculation
    const inflationDiff = inf - baseInflation;
    const inflationMultiplier = 1 + inflationDiff * cfoPeriod * 0.5; // Approximation
    const totalSavings = baseTotalSavings * inflationMultiplier;

    const cell = excelSheet3.getCell(cfoRow, 3 + i);
    const colLetter = String.fromCharCode(67 + i);  // C, D, E, F, G, H

    // Use formula or value
    if (withFormulas) {
      // Formula: base * (1 + (thisInflation - baseInflation) * period * 0.5)
      cell.value = {
        formula: `ROUND($C$${kpiTotalTysRow}*(1+(${colLetter}$${inflHeaderRow}-${baseInflation})*${cfoPeriod}*0.5),0)`,
        result: roundNum(totalSavings, 0)
      };
    } else {
      cell.value = roundNum(totalSavings, 0);
    }
    cell.numFmt = '#,##0';
    cell.alignment = { horizontal: 'center' };
    cell.font = { bold: true };

    // Color coding - highlight the base inflation scenario
    if (Math.abs(inf - baseInflation) < 0.005) {
      // Base scenario (2.5% or closest)
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

  cfoRow++;
  excelSheet3.getCell(`B${cfoRow}`).value = `vs scenariusz ${(baseInflation * 100).toFixed(1)}% inflacji`;
  excelSheet3.getCell(`B${cfoRow}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };

  // Calculate 0% inflation savings for comparison
  const zeroInflationMultiplier = 1 + (0 - baseInflation) * cfoPeriod * 0.5;
  const zeroInflationSavings = baseTotalSavings * zeroInflationMultiplier;

  inflationRates.forEach((inf, i) => {
    const inflationDiff = inf - baseInflation;
    const inflationMultiplier = 1 + inflationDiff * cfoPeriod * 0.5;
    const totalSavings = baseTotalSavings * inflationMultiplier;
    const colLetter = String.fromCharCode(67 + i);  // C, D, E, F, G, H

    if (Math.abs(inf - baseInflation) < 0.005) {
      // Base scenario - reference point
      excelSheet3.getCell(cfoRow, 3 + i).value = '—';
      excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
    } else {
      const diff = totalSavings - baseTotalSavings;
      // Use formula or value
      if (withFormulas) {
        excelSheet3.getCell(cfoRow, 3 + i).value = {
          formula: `(${colLetter}${inflValuesRow}-${baseInflColLetter}${inflValuesRow})/${baseInflColLetter}${inflValuesRow}`,
          result: diff / baseTotalSavings
        };
      } else {
        excelSheet3.getCell(cfoRow, 3 + i).value = diff / baseTotalSavings;
      }
      excelSheet3.getCell(cfoRow, 3 + i).numFmt = '+0%;-0%';
      excelSheet3.getCell(cfoRow, 3 + i).alignment = { horizontal: 'center' };
      excelSheet3.getCell(cfoRow, 3 + i).font = { color: { argb: diff >= 0 ? 'FF2E7D32' : 'FFC62828' } };
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

  // Decision rows with formulas for savings
  const decisions = [
    { criterion: 'Nakład inwestycyjny (CAPEX)', eaas: '0 PLN', statusQuo: '0 PLN', winner: 'Remis', winColor: 'FF757575', useFormula: false },
    { criterion: `Koszt energii ${cfoPeriod} lat`, eaas: `${roundNum(autoconsumptionMwh * eaasPriceDisplay * cfoPeriod * degradationFactor30 / 1000, 0)} tys.`, statusQuo: `${roundNum(autoconsumptionMwh * gridPriceDisplay * cfoPeriod * degradationFactor30 / 1000, 0)} tys.`, winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: `Oszczędności ${cfoPeriod} lat`, eaas: `${roundNum(tornadoBaseSavings30, 0)} tys. PLN`, statusQuo: '0 PLN', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'savings' },
    { criterion: 'Ryzyko techniczne', eaas: 'Dostawca', statusQuo: 'Brak instalacji', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Ryzyko cenowe', eaas: 'Częściowe zabezp.', statusQuo: '100% ekspozycji', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Wpływ na bilans', eaas: 'Off-balance', statusQuo: 'Brak', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Zielona energia', eaas: 'TAK', statusQuo: 'NIE', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Redukcja CO₂', eaas: `${totalCO2Reduction} ton`, statusQuo: '0 ton', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false }
  ];

  decisions.forEach(d => {
    cfoRow++;
    excelSheet3.getCell(`B${cfoRow}`).value = d.criterion;
    excelSheet3.mergeCells(`B${cfoRow}:C${cfoRow}`);

    // Use formula for savings row when withFormulas=true
    if (withFormulas && d.useFormula && d.formulaType === 'savings') {
      excelSheet3.getCell(`D${cfoRow}`).value = { formula: `$C$${kpiTotalTysRow}&" tys. PLN"`, result: d.eaas };
    } else {
      excelSheet3.getCell(`D${cfoRow}`).value = d.eaas;
    }
    excelSheet3.getCell(`D${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`D${cfoRow}`).font = { color: { argb: 'FF2E7D32' } };
    excelSheet3.getCell(`E${cfoRow}`).value = d.statusQuo;
    excelSheet3.getCell(`E${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`E${cfoRow}`).font = { color: { argb: 'FF757575' } };
    excelSheet3.getCell(`F${cfoRow}`).value = d.winner;
    excelSheet3.getCell(`F${cfoRow}`).alignment = { horizontal: 'center' };
    excelSheet3.getCell(`F${cfoRow}`).font = { bold: true, color: { argb: d.winColor } };

    if (d.winner === 'EaaS') {
      excelSheet3.getCell(`F${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    }

    for (let c = 2; c <= 6; c++) {
      excelSheet3.getRow(cfoRow).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Final verdict
  cfoRow += 2;
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);
  excelSheet3.getCell(`B${cfoRow}`).value = '✅ REKOMENDACJA: Model EaaS wygrywa w 7 z 8 kryteriów';
  excelSheet3.getCell(`B${cfoRow}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet3.getCell(`B${cfoRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
  excelSheet3.getCell(`B${cfoRow}`).alignment = { horizontal: 'center' };

  cfoRow++;
  excelSheet3.mergeCells(`B${cfoRow}:F${cfoRow}`);
  // Use formula for final summary when withFormulas=true
  if (withFormulas) {
    excelSheet3.getCell(`B${cfoRow}`).value = { formula: `"Oczekiwana oszczędność: "&TEXT($C$${kpiTotalTysRow},"# ##0")&" tys. ${currencyLabel} przez ${cfoPeriod} lat bez nakładów CAPEX"` };
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
  headerCell4.value = 'EaaS ANALYSIS (Energy-as-a-Service)';
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
  excelSheet5.getRow(1).getCell(3).value = 'EaaS YEAR BY YEAR ANALYSIS WITH NPV';
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
    [`Base grid price [${currencyLabel}/MWh]:`, roundNum(totalEnergyPriceDisplay, 2)],
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

  // Row 17: Header row (English)
  const headerRowEN = excelSheet5.getRow(17);
  headerRowEN.height = 40;
  const headersEN = ['', 'Year', 'Phase', `Self-consumption [MWh]`, `Grid Cost [k${currencyLabel}]`, `EaaS/Ownership Cost [k${currencyLabel}]`, `Savings [k${currencyLabel}]`, `Discounted CF [k${currencyLabel}]`, `Cumulative NPV [M${currencyLabel}]`];
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

  // Copy data rows from Sheet 2 (rows 18 onwards)
  const dataStartRowEN = 18;
  for (let year = 1; year <= analysisPeriod; year++) {
    const srcRow = excelSheet2.getRow(dataStartRow + year - 1);
    const destRow = excelSheet5.getRow(dataStartRowEN + year - 1);
    const yearData = eaasCashFlows[year - 1];
    const phase = yearData?.phase || (year <= eaasDuration ? 'eaas' : 'ownership');

    // Copy values from Sheet 2 but translate phase
    destRow.getCell(2).value = year;
    destRow.getCell(3).value = phase === 'eaas' ? 'EaaS' : 'Ownership';
    destRow.getCell(3).font = { color: { argb: phase === 'eaas' ? 'FF1565C0' : 'FF2E7D32' } };

    // Copy numeric values from source row
    for (let c = 4; c <= 9; c++) {
      const srcCell = srcRow.getCell(c);
      const destCell = destRow.getCell(c);
      destCell.value = srcCell.value;
      destCell.numFmt = srcCell.numFmt || '#,##0.00';
      destCell.alignment = { horizontal: 'right' };
    }

    // Styling based on phase
    const bgColor = phase === 'eaas' ? 'FFE3F2FD' : 'FFE8F5E9';
    for (let c = 2; c <= 9; c++) {
      destRow.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: bgColor } };
      destRow.getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  }

  // Summary rows
  const summaryStartRowEN = dataStartRowEN + analysisPeriod + 1;
  excelSheet5.getRow(summaryStartRowEN).getCell(3).value = 'TOTAL EaaS Phase:';
  excelSheet5.getRow(summaryStartRowEN).getCell(3).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet5.getRow(summaryStartRowEN).getCell(7).value = excelSheet2.getRow(summaryStartRow).getCell(7).value;
  excelSheet5.getRow(summaryStartRowEN).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN).getCell(7).font = { bold: true, color: { argb: 'FF1565C0' } };

  excelSheet5.getRow(summaryStartRowEN + 1).getCell(3).value = 'TOTAL Ownership Phase:';
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(3).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).value = excelSheet2.getRow(summaryStartRow + 1).getCell(7).value;
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN + 1).getCell(7).font = { bold: true, color: { argb: 'FF2E7D32' } };

  excelSheet5.getRow(summaryStartRowEN + 2).getCell(3).value = 'GRAND TOTAL:';
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(3).font = { bold: true, size: 11 };
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).value = excelSheet2.getRow(summaryStartRow + 2).getCell(7).value;
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).numFmt = '#,##0.00';
  excelSheet5.getRow(summaryStartRowEN + 2).getCell(7).font = { bold: true, size: 11 };

  // NPV row
  const npvRowEN = summaryStartRowEN + 4;
  excelSheet5.getRow(npvRowEN).getCell(3).value = `NPV [M${currencyLabel}]:`;
  excelSheet5.getRow(npvRowEN).getCell(3).font = { bold: true, size: 12, color: { argb: 'FF1976D2' } };
  excelSheet5.getRow(npvRowEN).getCell(9).value = excelSheet2.getRow(lastDataRow).getCell(9).value;
  excelSheet5.getRow(npvRowEN).getCell(9).numFmt = '#,##0.00';
  excelSheet5.getRow(npvRowEN).getCell(9).font = { bold: true, size: 12, color: { argb: 'FF1976D2' } };

  if (logoImageId !== null) {
    excelSheet5.addImage(logoImageId, {
      tl: { col: 7, row: 0.2 },
      ext: { width: 180, height: 45 }
    });
  }
  excelSheet5.views = [{ state: 'frozen', ySplit: 17, showGridLines: false, showRowColHeaders: false }];
  console.log('✅ Sheet 5: EaaS Year by Year (EN) created');

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
  excelSheet6.getCell('B2').value = `CFO ANALYSIS - EaaS (${cfoPeriod} years)`;
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
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Self-consumption [MWh/year]';
  excelSheet6.getCell(`C${cfoRowEN}`).value = autoconsumptionMwh;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0.0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'PV degradation [%/year]';
  excelSheet6.getCell(`E${cfoRowEN}`).value = pvDegradationYears2Plus;
  excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '0.00%';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Grid price [${currencyLabel}/MWh]`;
  excelSheet6.getCell(`C${cfoRowEN}`).value = gridPriceDisplay;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `EaaS price [${currencyLabel}/MWh]`;
  excelSheet6.getCell(`E${cfoRowEN}`).value = eaasPriceDisplay;
  excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true };
  excelSheet6.getCell(`F${cfoRowEN}`).value = 'CO2 emission [kg/kWh]';
  excelSheet6.getCell(`G${cfoRowEN}`).value = 0.7;
  excelSheet6.getCell(`G${cfoRowEN}`).numFmt = '0.0';
  excelSheet6.getCell(`G${cfoRowEN}`).font = { bold: true };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Avg. degradation factor';
  excelSheet6.getCell(`C${cfoRowEN}`).value = 1 - pvDegradationYears2Plus * cfoPeriod / 2;
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
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `${sheet2Refs.eaasSum}/1000`, result: roundNum(totalSavingsEaaS / 1000, 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(totalSavingsEaaS / 1000, 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE3F2FD' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= ${sheet2Refs.eaasSum} / 1000` : 'Savings with EaaS subscription';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // Ownership Phase savings
  cfoRowEN++;
  const kpiOwnRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Ownership Phase (years ${eaasPhaseYears + 1}-${cfoPeriod})`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `${sheet2Refs.ownershipSum}/1000`, result: roundNum(totalSavingsOwnership / 1000, 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(totalSavingsOwnership / 1000, 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= ${sheet2Refs.ownershipSum} / 1000` : 'Free energy (O&M only)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // TOTAL SAVINGS
  cfoRowEN++;
  const kpiTotalRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `TOTAL SAVINGS (${cfoPeriod} years)`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  if (withFormulas) {
    excelSheet6.getCell(`C${cfoRowEN}`).value = { formula: `C${kpiEaaSRowEN}+C${kpiOwnRowEN}`, result: roundNum((totalSavingsEaaS + totalSavingsOwnership) / 1000, 2) };
  } else {
    excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum((totalSavingsEaaS + totalSavingsOwnership) / 1000, 2);
  }
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = `#,##0.00 "M${currencyLabel}"`;
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF1565C0' }, size: 12 };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF9C4' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = withFormulas ? `= C${kpiEaaSRowEN} + C${kpiOwnRowEN}` : 'Cumulative incl. PV degradation';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

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
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Impact on TOTAL savings (${cfoPeriod} years) when changing parameter:`;
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
  if (withFormulas) {
    excelSheet6.getCell(`H${cfoRowEN}`).value = 'Formula (multiplier)';
    excelSheet6.getCell(`H${cfoRowEN}`).font = { bold: true, size: 9 };
  }

  // Tornado data (English)
  const tornadoDataEN = [
    { param: 'Grid energy price', variation: '±20%', pessMultiplier: tornadoData[0].pessMultiplier, optMultiplier: tornadoData[0].optMultiplier },
    { param: 'EaaS subscription price', variation: '±20%', pessMultiplier: tornadoData[1].pessMultiplier, optMultiplier: tornadoData[1].optMultiplier },
    { param: 'PV yield (production)', variation: '±15%', pessMultiplier: tornadoData[2].pessMultiplier, optMultiplier: tornadoData[2].optMultiplier },
    { param: 'Self-consumption', variation: '±10%', pessMultiplier: tornadoData[3].pessMultiplier, optMultiplier: tornadoData[3].optMultiplier }
  ];

  // Sort by range (same order as Polish version)
  tornadoDataEN.forEach((t, idx) => {
    t.pessimisticSavings = baseTotalSavings * t.pessMultiplier;
    t.optimisticSavings = baseTotalSavings * t.optMultiplier;
    t.range = Math.abs(t.optimisticSavings - t.pessimisticSavings);
  });
  tornadoDataEN.sort((a, b) => b.range - a.range);

  tornadoDataEN.forEach((t, idx) => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = t.param;
    excelSheet6.getCell(`C${cfoRowEN}`).value = t.variation;
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };

    if (withFormulas) {
      excelSheet6.getCell(`D${cfoRowEN}`).value = { formula: `ROUND($C$${kpiTotalTysRowEN}*${t.pessMultiplier},0)`, result: roundNum(t.pessimisticSavings, 0) };
      excelSheet6.getCell(`E${cfoRowEN}`).value = { formula: `ROUND($C$${kpiTotalTysRowEN},0)`, result: roundNum(baseTotalSavings, 0) };
      excelSheet6.getCell(`F${cfoRowEN}`).value = { formula: `ROUND($C$${kpiTotalTysRowEN}*${t.optMultiplier},0)`, result: roundNum(t.optimisticSavings, 0) };
      excelSheet6.getCell(`G${cfoRowEN}`).value = { formula: `F${cfoRowEN}-D${cfoRowEN}`, result: roundNum(t.range, 0) };
      excelSheet6.getCell(`H${cfoRowEN}`).value = `pess=${t.pessMultiplier}, opt=${t.optMultiplier}`;
      excelSheet6.getCell(`H${cfoRowEN}`).font = { size: 8, italic: true, color: { argb: 'FF757575' } };
    } else {
      excelSheet6.getCell(`D${cfoRowEN}`).value = roundNum(t.pessimisticSavings, 0);
      excelSheet6.getCell(`E${cfoRowEN}`).value = roundNum(baseTotalSavings, 0);
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
  excelSheet6.getCell(`B${cfoRowEN}`).value = `📊 TORNADO CHART - ${cfoPeriod}-year Savings [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };

  cfoRowEN++;
  tornadoDataEN.forEach((t, idx) => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = t.param;
    excelSheet6.getCell(`B${cfoRowEN}`).font = { size: 10 };

    const maxRange = tornadoDataEN[0].range;
    const pessimisticDelta = t.pessimisticSavings - baseTotalSavings;
    const optimisticDelta = t.optimisticSavings - baseTotalSavings;

    const redBarLen = Math.round(Math.abs(pessimisticDelta) / maxRange * 15);
    const redBar = '█'.repeat(Math.max(1, redBarLen));
    excelSheet6.getCell(`C${cfoRowEN}`).value = redBar;
    excelSheet6.getCell(`C${cfoRowEN}`).font = { color: { argb: 'FFC62828' }, size: 10 };
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'right' };

    excelSheet6.getCell(`D${cfoRowEN}`).value = `${roundNum(t.pessimisticSavings, 0)} | ${roundNum(baseTotalSavings, 0)} | ${roundNum(t.optimisticSavings, 0)}`;
    excelSheet6.getCell(`D${cfoRowEN}`).font = { size: 9 };
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };

    const greenBarLen = Math.round(Math.abs(optimisticDelta) / maxRange * 15);
    const greenBar = '█'.repeat(Math.max(1, greenBarLen));
    excelSheet6.getCell(`E${cfoRowEN}`).value = greenBar;
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

  // --- SENSITIVITY MATRIX (English) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = `SENSITIVITY MATRIX - ${cfoPeriod}-year Savings vs Grid Price vs Yield`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF7B1FA2' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF3E5F5' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `Savings ${cfoPeriod}yr [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
  excelSheet6.mergeCells(`C${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`C${cfoRowEN}`).value = '← PV Yield →';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, size: 10 };
  excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Grid price ↓';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
  excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'right' };
  yieldVariations.forEach((yv, i) => {
    excelSheet6.getCell(cfoRowEN, 3 + i).value = `${yv >= 0 ? '+' : ''}${(yv * 100).toFixed(0)}%`;
    excelSheet6.getCell(cfoRowEN, 3 + i).font = { bold: true, size: 9 };
    excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    excelSheet6.getCell(cfoRowEN, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  gridPriceVariations.forEach(gpv => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = `${gpv >= 0 ? '+' : ''}${(gpv * 100).toFixed(0)}%`;
    excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 9 };
    excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'right' };
    excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };

    yieldVariations.forEach((yv, i) => {
      const adjGridPrice = gridPriceDisplay * (1 + gpv);
      const adjAutoconsumption = autoconsumptionMwh * (1 + yv);
      const savings30 = adjAutoconsumption * (adjGridPrice - eaasPriceDisplay) * cfoPeriod * degradationFactor30 / 1000;

      const cell = excelSheet6.getCell(cfoRowEN, 3 + i);
      cell.value = roundNum(savings30, 0);
      cell.numFmt = '#,##0';
      cell.alignment = { horizontal: 'center' };

      if (savings30 > baseTotalSavings * 1.1) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
        cell.font = { color: { argb: 'FF2E7D32' }, bold: true };
      } else if (savings30 > baseTotalSavings * 0.9) {
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFFDE' } };
      } else if (savings30 > 0) {
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
  const annualCO2TonsEN = autoconsumptionMwh * 0.7;
  const totalCO2TonsEN = annualCO2TonsEN * cfoPeriod * degradationFactor30;

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
  excelSheet6.getCell(`C${cfoRowEN}`).value = 0.7;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '0.0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Poland average (2024)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🌍 Annual CO2 reduction [tons]';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2TonsEN, 0);
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = `= ${roundNum(autoconsumptionMwh, 0)} MWh × 0.7 t/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `🌍 Total CO2 reduction (${cfoPeriod} years) [tons]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(totalCO2TonsEN, 0);
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' }, size: 12 };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Total project impact (with degradation)';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🚗 Equivalent cars/year';
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2TonsEN / 4.6, 0);
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Annual emission of this many cars';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🌳 Equivalent trees';
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2TonsEN / 0.022, 0);
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Trees needed to absorb CO2';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '✈️ Equivalent flights WAW-LON';
  excelSheet6.getCell(`C${cfoRowEN}`).value = roundNum(annualCO2TonsEN / 0.255, 0); // WAW-LON ~255kg CO2
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FF00695C' } };
  excelSheet6.mergeCells(`D${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`D${cfoRowEN}`).value = 'Economy class flights';
  excelSheet6.getCell(`D${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  // --- BREAK-EVEN ANALYSIS (English) ---
  const breakEvenGridPriceEN = eaasPriceDisplay;
  const safetyMarginPctEN = (gridPriceDisplay - eaasPriceDisplay) / gridPriceDisplay;

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
  excelSheet6.getCell(`B${cfoRowEN}`).value = '⚠️ BREAK-EVEN: Grid price';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  excelSheet6.getCell(`C${cfoRowEN}`).value = breakEvenGridPriceEN;
  excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '#,##0';
  excelSheet6.getCell(`C${cfoRowEN}`).font = { bold: true, color: { argb: 'FFE65100' }, size: 12 };
  excelSheet6.getCell(`C${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF3E0' } };
  excelSheet6.getCell(`D${cfoRowEN}`).value = `${currencyLabel}/MWh`;
  excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF757575' } };
  excelSheet6.mergeCells(`E${cfoRowEN}:G${cfoRowEN}`);
  excelSheet6.getCell(`E${cfoRowEN}`).value = 'Below this price EaaS generates no savings';
  excelSheet6.getCell(`E${cfoRowEN}`).font = { italic: true, color: { argb: 'FF757575' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = '🛡️ Safety margin';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 11 };
  excelSheet6.getCell(`C${cfoRowEN}`).value = safetyMarginPctEN;
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
  excelSheet6.getCell(`B${cfoRowEN}`).value = `${cfoPeriod}-year savings projection under different assumptions:`;
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
  excelSheet6.getCell(`E${cfoRowEN}`).value = `${cfoPeriod}yr Savings`;
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
    const scenarioSavings = s.gridMult === 1.0 && s.yieldMult === 1.0 ? baseTotalSavings : baseTotalSavings * s.yieldMult * s.gridMult;
    const weightedValue = scenarioSavings * s.prob;

    excelSheet6.getCell(`B${cfoRowEN}`).value = s.name;
    excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, color: { argb: s.color } };
    excelSheet6.getCell(`C${cfoRowEN}`).value = s.gridMult - 1;
    excelSheet6.getCell(`C${cfoRowEN}`).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(`C${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`D${cfoRowEN}`).value = s.yieldMult - 1;
    excelSheet6.getCell(`D${cfoRowEN}`).numFmt = '+0%;-0%;0%';
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).value = roundNum(scenarioSavings, 0);
    excelSheet6.getCell(`E${cfoRowEN}`).numFmt = '#,##0';
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).font = { bold: true, color: { argb: s.color } };
    excelSheet6.getCell(`E${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: s.bgColor } };
    excelSheet6.getCell(`F${cfoRowEN}`).value = s.prob;
    excelSheet6.getCell(`F${cfoRowEN}`).numFmt = '0%';
    excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`G${cfoRowEN}`).value = roundNum(weightedValue, 0);
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

  // --- INFLATION SENSITIVITY (English) ---
  cfoRowEN += 3;
  excelSheet6.mergeCells(`B${cfoRowEN}:I${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'ENERGY PRICE INFLATION SENSITIVITY';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF00838F' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0F7FA' } };

  cfoRowEN++;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `How total ${cfoPeriod}-year savings change with different energy price inflation:`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 10, color: { argb: 'FF616161' } };
  excelSheet6.mergeCells(`B${cfoRowEN}:H${cfoRowEN}`);

  // Inflation scenarios
  const inflationRatesEN = [0, 0.02, 0.03, 0.05, 0.07, 0.10];

  cfoRowEN += 2;
  excelSheet6.getCell(`B${cfoRowEN}`).value = 'Annual energy price inflation';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };
  inflationRatesEN.forEach((inf, i) => {
    excelSheet6.getCell(cfoRowEN, 3 + i).value = inf;
    excelSheet6.getCell(cfoRowEN, 3 + i).numFmt = '0%';
    excelSheet6.getCell(cfoRowEN, 3 + i).font = { bold: true };
    excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    excelSheet6.getCell(cfoRowEN, 3 + i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
  });

  cfoRowEN++;
  const inflValuesRowEN = cfoRowEN;
  excelSheet6.getCell(`B${cfoRowEN}`).value = `${cfoPeriod}-year savings [k${currencyLabel}]`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true };

  // Base inflation from settings
  const baseInflationEN = inflationRate;
  const inflHeaderRowEN = cfoRowEN - 1;

  // Find column with base inflation for formulas
  const baseInflColIndexEN = inflationRatesEN.findIndex(r => Math.abs(r - baseInflationEN) < 0.01);
  const baseInflColLetterEN = String.fromCharCode(67 + (baseInflColIndexEN >= 0 ? baseInflColIndexEN : 1));

  inflationRatesEN.forEach((inf, i) => {
    const inflationDiff = inf - baseInflationEN;
    const inflationMultiplier = 1 + inflationDiff * cfoPeriod * 0.5;
    const totalSavingsInf = baseTotalSavings * inflationMultiplier;

    const cell = excelSheet6.getCell(cfoRowEN, 3 + i);
    const colLetter = String.fromCharCode(67 + i);

    if (withFormulas) {
      cell.value = {
        formula: `ROUND($C$${kpiTotalTysRowEN}*(1+(${colLetter}$${inflHeaderRowEN}-${baseInflationEN})*${cfoPeriod}*0.5),0)`,
        result: roundNum(totalSavingsInf, 0)
      };
    } else {
      cell.value = roundNum(totalSavingsInf, 0);
    }
    cell.numFmt = '#,##0';
    cell.alignment = { horizontal: 'center' };
    cell.font = { bold: true };

    if (Math.abs(inf - baseInflationEN) < 0.005) {
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
  excelSheet6.getCell(`B${cfoRowEN}`).value = `vs ${(baseInflationEN * 100).toFixed(1)}% inflation scenario`;
  excelSheet6.getCell(`B${cfoRowEN}`).font = { italic: true, size: 9, color: { argb: 'FF757575' } };

  inflationRatesEN.forEach((inf, i) => {
    const inflationDiff = inf - baseInflationEN;
    const inflationMultiplier = 1 + inflationDiff * cfoPeriod * 0.5;
    const totalSavingsInf = baseTotalSavings * inflationMultiplier;
    const colLetter = String.fromCharCode(67 + i);

    if (Math.abs(inf - baseInflationEN) < 0.005) {
      excelSheet6.getCell(cfoRowEN, 3 + i).value = '—';
      excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
    } else {
      const diff = totalSavingsInf - baseTotalSavings;
      if (withFormulas) {
        excelSheet6.getCell(cfoRowEN, 3 + i).value = {
          formula: `(${colLetter}${inflValuesRowEN}-${baseInflColLetterEN}${inflValuesRowEN})/${baseInflColLetterEN}${inflValuesRowEN}`,
          result: diff / baseTotalSavings
        };
      } else {
        excelSheet6.getCell(cfoRowEN, 3 + i).value = diff / baseTotalSavings;
      }
      excelSheet6.getCell(cfoRowEN, 3 + i).numFmt = '+0%;-0%';
      excelSheet6.getCell(cfoRowEN, 3 + i).alignment = { horizontal: 'center' };
      excelSheet6.getCell(cfoRowEN, 3 + i).font = { color: { argb: diff >= 0 ? 'FF2E7D32' : 'FFC62828' } };
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
    { criterion: `${cfoPeriod}-year energy cost`, eaas: `${roundNum(autoconsumptionMwh * eaasPriceDisplay * cfoPeriod * degradationFactor30 / 1000, 0)} k`, statusQuo: `${roundNum(autoconsumptionMwh * gridPriceDisplay * cfoPeriod * degradationFactor30 / 1000, 0)} k`, winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: `${cfoPeriod}-year savings`, eaas: `${roundNum(baseTotalSavings, 0)} k${currencyLabel}`, statusQuo: '0', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: true, formulaType: 'savings' },
    { criterion: 'Technical risk', eaas: 'Provider', statusQuo: 'No installation', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Price risk', eaas: 'Partial hedge', statusQuo: '100% exposure', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Balance sheet impact', eaas: 'Off-balance', statusQuo: 'None', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'Green energy', eaas: 'YES', statusQuo: 'NO', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false },
    { criterion: 'CO2 reduction', eaas: `${roundNum(totalCO2TonsEN, 0)} tons`, statusQuo: '0 tons', winner: 'EaaS', winColor: 'FF2E7D32', useFormula: false }
  ];

  decisionsEN.forEach(d => {
    cfoRowEN++;
    excelSheet6.getCell(`B${cfoRowEN}`).value = d.criterion;
    excelSheet6.mergeCells(`B${cfoRowEN}:C${cfoRowEN}`);

    // Use formula for savings row when withFormulas=true
    if (withFormulas && d.useFormula && d.formulaType === 'savings') {
      excelSheet6.getCell(`D${cfoRowEN}`).value = { formula: `$C$${kpiTotalTysRowEN}&" k${currencyLabel}"`, result: d.eaas };
    } else {
      excelSheet6.getCell(`D${cfoRowEN}`).value = d.eaas;
    }
    excelSheet6.getCell(`D${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`D${cfoRowEN}`).font = { color: { argb: 'FF2E7D32' } };
    excelSheet6.getCell(`E${cfoRowEN}`).value = d.statusQuo;
    excelSheet6.getCell(`E${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`E${cfoRowEN}`).font = { color: { argb: 'FF757575' } };
    excelSheet6.getCell(`F${cfoRowEN}`).value = d.winner;
    excelSheet6.getCell(`F${cfoRowEN}`).alignment = { horizontal: 'center' };
    excelSheet6.getCell(`F${cfoRowEN}`).font = { bold: true, color: { argb: d.winColor } };
    if (d.winner === 'EaaS') {
      excelSheet6.getCell(`F${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8F5E9' } };
    }
    for (let c = 2; c <= 6; c++) {
      excelSheet6.getRow(cfoRowEN).getCell(c).border = { bottom: { style: 'thin', color: { argb: 'FFE0E0E0' } } };
    }
  });

  // Final verdict
  cfoRowEN += 2;
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);
  excelSheet6.getCell(`B${cfoRowEN}`).value = '✅ RECOMMENDATION: EaaS model wins in 7 out of 8 criteria';
  excelSheet6.getCell(`B${cfoRowEN}`).font = { bold: true, size: 12, color: { argb: 'FF2E7D32' } };
  excelSheet6.getCell(`B${cfoRowEN}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFC8E6C9' } };
  excelSheet6.getCell(`B${cfoRowEN}`).alignment = { horizontal: 'center' };

  cfoRowEN++;
  excelSheet6.mergeCells(`B${cfoRowEN}:F${cfoRowEN}`);
  // Use formula for final summary when withFormulas=true
  if (withFormulas) {
    excelSheet6.getCell(`B${cfoRowEN}`).value = { formula: `"Expected savings: "&TEXT($C$${kpiTotalTysRowEN},"# ##0")&" k${currencyLabel} over ${cfoPeriod} years with zero CAPEX"` };
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
        formula: `SUMPRODUCT(Cashflow!I${dscrP90StartRow}:I${dscrP90EndRow})/SUM(Cashflow!E${dscrP90StartRow}:E${dscrP90EndRow})`,
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
        formula: `(C${minDscrRow}/C${covenantRowInDS})-1`,
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

  // Generate filename
  const timestamp = new Date().toISOString().slice(0, 10);
  const formulasSuffix = withFormulas ? '_FORMULY' : '';
  const filename = `EaaS_Analiza_${currentVariant}_${capacityKwp}kWp_${timestamp}${formulasSuffix}.xlsx`;

  // Save file using ExcelJS
  excelWorkbook.xlsx.writeBuffer().then(buffer => {
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    saveAs(blob, filename);
    console.log('✅ EaaS analysis exported to:', filename, withFormulas ? '(with formulas)' : '');
  }).catch(err => {
    console.error('❌ Error exporting Excel:', err);
    alert('Błąd eksportu Excel: ' + err.message);
  });
}

// ============================================================================
// === EXPORT WITH FORMULAS (CFO AUDIT VERSION) ===
// ============================================================================
// This function creates the SAME structure as exportEaaSToExcel()
// but adds Excel formulas in Sheet 3 (Analiza CFO) for CFO audit/transparency

async function exportEaaSToExcelWithFormulas() {
  // Call the regular export function with formulas flag = true
  await exportEaaSToExcel(true);
}

// Export functions to window for HTML onclick handlers
window.exportEaaSToExcel = exportEaaSToExcel;
window.exportEaaSToExcelWithFormulas = exportEaaSToExcelWithFormulas;
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

  // Get consumption data using helper function
  const annualConsumptionKwh = getAnnualConsumptionKwh();
  const annualConsumptionMwh = annualConsumptionKwh / 1000;

  // Get production data (apply scenario factor)
  const factor = window.currentScenarioFactor || 1.0;
  const annualProductionMwh = (variant.production || 0) * factor / 1000;
  const selfConsumedMwh = (variant.self_consumed || 0) * factor / 1000;

  // Grid consumption before PV = total consumption
  // Grid consumption after PV = total consumption - self consumed
  const gridConsumptionBeforeMwh = annualConsumptionMwh;
  const gridConsumptionAfterMwh = Math.max(0, annualConsumptionMwh - selfConsumedMwh);

  // Build parameters for ESG calculation
  const esgParams = {
    capacityKwp: variant.capacity || 0,
    annualProductionMwh: annualProductionMwh,
    selfConsumedMwh: selfConsumedMwh,
    gridConsumptionBeforeMwh: gridConsumptionBeforeMwh,
    gridConsumptionAfterMwh: gridConsumptionAfterMwh,
    projectLifetimeYears: systemSettings?.analysisPeriod || 25,
    degradationRate: (systemSettings?.degradationRate || 0.5) / 100
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
    degradationRate = 0.005
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
  const bessLifetime = settings?.bessLifetimeYears || 15;
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
  document.getElementById('bessEconCapex').textContent = formatNumberEU(bessCapexTotal / 1000, 0);
  document.getElementById('bessEconCapexDetail').textContent = `${formatNumberEU(bessCapexPerKwh, 0)} PLN/kWh + ${formatNumberEU(bessCapexPerKw, 0)} PLN/kW`;

  document.getElementById('bessEconOpex').textContent = formatNumberEU(bessOpexAnnual / 1000, 1);
  document.getElementById('bessEconOpexPct').textContent = `${formatNumberEU(bessOpexPct, 1)}% CAPEX/rok`;

  // Battery replacement
  const replacementYear = Math.min(bessLifetime, analysisPeriod);
  const needsReplacement = analysisPeriod > bessLifetime;
  document.getElementById('bessEconReplacement').textContent = needsReplacement ? replacementYear.toString() : 'N/A';
  document.getElementById('bessEconReplacementCost').textContent = needsReplacement
    ? `Koszt: ${formatNumberEU(bessCapexTotal * 0.7 / 1000, 0)} tys. PLN`
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
    const energyMWh = (effectiveCapacity * baseEnergyFactor) / 1000;
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
  // The savings_breakdown is expected to be on the variant object, populated by pv-calculation
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
  const fallbackImportPrice = settings.totalEnergyPrice || settings.energyPrice || 800;

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

  // Update source badge to reflect SSoT
  const sourceEl = document.getElementById('savingsBreakdownSource');
  sourceEl.textContent = '✓ pv-calculation';
  sourceEl.style.background = '#c8e6c9';
  sourceEl.style.color = '#1b5e20';

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
      capacityMWp: capacityKwp / 1000,
      productionMWh: productionKwh / 1000,
      selfConsumedMWh: selfConsumedKwh / 1000,
      exportedMWh: exportedKwh / 1000,
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
      capacityMWp: capacityKwp / 1000,
      productionMWh: productionKwh / 1000,
      selfConsumedMWh: selfConsumedKwh / 1000,
      exportedMWh: exportedKwh / 1000,
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
    discountRate = 0.07,
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

  const productionMwh = productionKwh / 1000;
  const selfConsumedMwhYear1 = selfConsumedKwh / 1000;

  // ===== PARAMETRY FINANSOWE (z ustawień użytkownika) =====
  const discountRateNominal = window.economicsSettings?.discountRate ?? 0.07;
  const inflationRate = window.economicsSettings?.inflationRate || 0.025;
  const useInflation = window.economicsSettings?.useInflation || false;
  const analysisPeriod = params.analysis_period || 25;
  const degradationRate = params.degradation_rate || 0.005;

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
  const lcoeMargin = lcoeStd > 0 ? ((lcoeEff - lcoeStd) / lcoeStd * 100) : 0;

  // ===== PAYBACK =====
  const annualSavings = selfConsumedMwhYear1 * totalPricePerMwh;
  const netAnnualBenefit = annualSavings - annualOpexBase;
  const payback = totalCapex > 0 && netAnnualBenefit > 0
    ? totalCapex / netAnnualBenefit
    : 99;

  // ===== DEBUG LOG =====
  if (capacityKwp === 500 || capacityKwp === 647 || capacityKwp === 1000) {
    console.log(`📊 LCOE Debug [${capacityKwp} kWp]:`);
    console.log(`   Mode: ${useInflation ? 'NOMINAL' : 'REAL'}, Discount: ${(discountRateUsed * 100).toFixed(1)}%`);
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
    npv: npv / 1000000, // mln PLN
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
  const gridPrice = window.economicsSettings?.totalEnergyPrice || 750;

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
    const lcoeGridValue = d.lcoeGrid || (window.economicsSettings?.totalEnergyPrice || 750);
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
      observation = `<strong>Tryb: Minimalny Payback</strong> — Najkrótszy okres zwrotu (${formatNumberEU(minPayback, 1)} lat) przy mocy ${formatNumberEU(minPaybackCapacity, 0)} kWp.`;
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
        observation = `<strong>Tryb: Maksymalny NPV</strong> — Optymalny NPV (${formatNumberEU(maxNpv, 2)} mln PLN) osiągany przy ${formatNumberEU(maxNpvCapacity, 0)} kWp, gdzie autokonsumpcja wynosi ponad 80%.`;
      } else {
        observation = `<strong>Tryb: Maksymalny NPV</strong> — Maksymalny NPV (${formatNumberEU(maxNpv, 2)} mln PLN) przy ${formatNumberEU(maxNpvCapacity, 0)} kWp. Granica 80% autokonsumpcji: ${formatNumberEU(threshold80Capacity, 0)} kWp.`;
      }
      if (minPaybackCapacity && minPaybackCapacity !== maxNpvCapacity) {
        observation += ` Najkrótszy payback (${formatNumberEU(minPayback, 1)} lat) przy ${formatNumberEU(minPaybackCapacity, 0)} kWp.`;
      }
    } else if (maxNpvCapacity) {
      observation = `<strong>Tryb: Maksymalny NPV</strong> — Najwyższy NPV (${formatNumberEU(maxNpv, 2)} mln PLN) przy mocy ${formatNumberEU(maxNpvCapacity, 0)} kWp.`;
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
  const gridPrice = window.economicsSettings?.totalEnergyPrice || 750;
  const discountRate = window.economicsSettings?.discountRate ?? 0.07;
  const analysisPeriod = params.analysis_period || 25;
  const opexPerKwp = params.opex_per_kwp || 15;
  const degradationRate = params.degradation_rate || 0.005;
  const useInflation = window.economicsSettings?.useInflation || false;
  const inflationRate = useInflation ? (window.economicsSettings?.inflationRate || 0.03) : 0;

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
      capacityMwp: capacityKwp / 1000,
      productionMwh: productionKwh / 1000,
      autoConsumptionPct: autoConsumptionPct,
      coveragePct: coveragePct,
      selfConsumedMwh: selfConsumedKwh / 1000,
      exportedMwh: exportedKwh / 1000,
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
  addDataRow(sheet1, row++, 'Stopa dyskontowa', (discountRate * 100).toFixed(1), '%', 'Dyskontowanie przepływów');
  addDataRow(sheet1, row++, 'Degradacja PV', (degradationRate * 100).toFixed(2), '%/rok', 'Roczny spadek produkcji');
  addDataRow(sheet1, row++, 'OPEX', opexPerKwp, 'PLN/kWp/rok', 'Koszty O&M');
  addDataRow(sheet1, row++, 'Inflacja OPEX', useInflation ? (inflationRate * 100).toFixed(1) + '%' : 'wyłączona', '', useInflation ? 'Indeksacja kosztów O&M' : '');
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

console.log('📦 economics.js fully loaded');

// ============================================================================
// CommonJS Exports for Node.js Testing
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
