console.log('🚀 economics.js LOADED v=FINAL - timestamp:', new Date().toISOString());
console.log('💡💡💡 NOWA WERSJA: v=20241204-FINAL - Obsługa CAPEX per typ instalacji 💡💡💡');

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

// Data storage
let economicData = null;
let pvConfig = null;
let analysisResults = null;
let variants = {};
let currentVariant = 'A'; // Default variant
let consumptionData = null;
let systemSettings = null; // Settings from Settings module
let hourlyData = null; // Hourly consumption/production data
let profileAnalysisBessData = null; // BESS data from Profile Analysis module
let configBessData = null; // BESS data from pv-calculation (via key_variants)
let currentBessSource = 'pv-calculation'; // 'pv-calculation' or 'profile-analysis'

// CENTRALIZED FINANCIAL METRICS STORAGE
// This is the SINGLE SOURCE OF TRUTH for all NPV calculations
// All UI sections should read from this object
let centralizedMetrics = {};

// Initialize window.economicsSettings with defaults
window.economicsSettings = {
  discountRate: 0.07, // 7%
  insuranceRate: 0.005, // 0.5%
  inflationRate: 0.03, // 3%
  eaasIndexation: 'fixed', // 'fixed' or 'cpi'
  useInflation: false, // false = real IRR, true = nominal IRR
  irrMode: 'real' // 'real' or 'nominal'
};

// Production scenario selector for P50/P75/P90
window.currentProductionScenario = 'P50';

// P-factor values (can be overwritten by settings)
window.productionFactors = {
  P50: 1.00,
  P75: 0.97,
  P90: 0.94
};

/**
 * Helper function to get annual consumption in kWh
 * Uses multiple sources with fallbacks
 */
function getAnnualConsumptionKwh() {
  // Priority 1: consumptionData.annual_consumption_kwh (sent from config module)
  if (consumptionData?.annual_consumption_kwh) {
    console.log('📊 Using annual_consumption_kwh from consumptionData:', consumptionData.annual_consumption_kwh);
    return consumptionData.annual_consumption_kwh;
  }

  // Priority 2: consumptionData.total_consumption_gwh (convert GWh to kWh)
  if (consumptionData?.total_consumption_gwh) {
    const kwh = consumptionData.total_consumption_gwh * 1000000;
    console.log('📊 Using total_consumption_gwh from consumptionData:', consumptionData.total_consumption_gwh, 'GWh =', kwh, 'kWh');
    return kwh;
  }

  // Priority 3: Calculate from hourlyData array (sum of all values)
  if (hourlyData && Array.isArray(hourlyData) && hourlyData.length > 0) {
    // Each element might be {consumption: xxx} or just a number
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
      console.log('📊 Calculated annual consumption from hourlyData:', sum, 'kWh');
      return sum;
    }
  }

  // Priority 4: Get from current variant (grid_import = what we need from grid)
  const variant = variants[currentVariant];
  if (variant) {
    // Total consumption = self_consumed + grid_import (what's left after PV)
    // But we want the ORIGINAL consumption before PV
    // If we have baseline data, use it
    if (variant.baseline_no_bess?.self_consumed && variant.exported !== undefined) {
      // baseline_no_bess.self_consumed is in kWh
      const totalConsumption = (variant.self_consumed || 0) + (variant.bess_grid_import_kwh || 0);
      if (totalConsumption > 0) {
        console.log('📊 Estimated annual consumption from variant:', totalConsumption, 'kWh');
        return totalConsumption;
      }
    }
  }

  // Priority 5: Fallback - but use a more reasonable default (5 GWh = typical medium industry)
  console.warn('⚠️ No consumption data found, using fallback: 5 GWh (5,000 MWh)');
  return 5000000; // 5 GWh = 5,000 MWh - more reasonable default
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

  // Energy prices - calculateTotalEnergyPrice() already includes capacity_fee
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

  // DEBUG: Log pvConfig to see what we have
  console.log('🔍 pvConfig DEBUG:', {
    pvConfig_exists: !!pvConfig,
    pvConfig_pvType: pvConfig?.pvType,
    pvConfig_pv_type: pvConfig?.pv_type,
    resolved_currentPvType: currentPvType
  });

  // Try to get CAPEX data - prefer capexPerType (new format) over capexTiers (legacy)
  // Use defaults if systemSettings doesn't have the new format
  const capexPerType = systemSettings?.capexPerType || DEFAULT_CAPEX_PER_TYPE;
  const capexRanges = systemSettings?.capexRanges || DEFAULT_CAPEX_RANGES;
  const capexTiers = systemSettings?.capexTiers || analysisResults?.economicParams?.capexTiers;

  const usingDefaultCapex = !systemSettings?.capexPerType;
  console.log('💰 getCapexForCapacity DEBUG:', {
    capacityKwp,
    currentPvType,
    usingDefaultCapex,
    hasSystemSettings: !!systemSettings,
    typeTiersAvailable: capexPerType[currentPvType] ? capexPerType[currentPvType].filter(t => t !== null).length : 0
  });

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
          console.log(`  ✓ MATCHED (capexPerType/${currentPvType}): ${minVal}-${maxVal} kWp, price: ${price} PLN/kWp`);
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
  // Use systemSettings if available, otherwise fall back to input values
  return {
    energy_active: systemSettings?.energyActive || parseFloat(document.getElementById('energyActive')?.value || 550),
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

// Calculate total energy price (PLN/MWh)
function calculateTotalEnergyPrice(params) {
  // Suma wszystkich składowych ceny energii (włącznie z opłatą mocową)
  return params.energy_active + params.distribution + params.quality_fee +
         params.oze_fee + params.cogeneration_fee + params.capacity_fee + params.excise_tax;
}

// Calculate capacity fee
function calculateCapacityFeeForConsumption(consumptionData, params) {
  // Pełna opłata mocowa - ujednolicona z Settings module
  return params.capacity_fee;
}

// Recalculate button handler
function recalculateEconomics() {
  console.log('🔄 Recalculating economics with new parameters...');
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
 * @returns {object} - Full model results
 */
function calculateEaasFullModel(capacityKw, annualEnergyMWh, settings, economicParams) {
  console.log(`\n📊 ========== PEŁNY MODEL EaaS ==========`);
  console.log(`   Moc: ${capacityKw} kW, Energia roczna: ${annualEnergyMWh?.toFixed(0) || 'N/A'} MWh`);

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

  // ========== CAPEX ==========
  const capexPerKwp = getCapexForCapacity(capacityKw);
  const totalCapex = capacityKw * capexPerKwp;

  // ========== OPEX (annual) ==========
  const opexPerKwp = economicParams?.opex_per_kwp || settings.opexPerKwp || 15;
  const insuranceRate = getInsuranceRate(settings);
  const landLeasePerKwp = settings.landLeasePerKwp || 0;

  const annualOM = capacityKw * opexPerKwp;
  const annualInsurance = totalCapex * insuranceRate;
  const annualLandLease = capacityKw * landLeasePerKwp;
  const baseOpex = annualOM + annualInsurance + annualLandLease;

  // ========== DEPRECIATION ==========
  const annualDepreciation = totalCapex / depPeriod;

  // ========== DEBT ==========
  const debtAmount = totalCapex * leverageRatio;
  const equityAmount = totalCapex - debtAmount;

  console.log(`\n📋 PARAMETRY WEJŚCIOWE:`);
  console.log(`   CAPEX: ${(totalCapex/1e6).toFixed(2)} mln PLN (${capexPerKwp} PLN/kWp)`);
  console.log(`   OPEX bazowy: ${(baseOpex/1e3).toFixed(0)} tys. PLN/rok`);
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

  // Show loading state first
  showLoadingState();

  // Request shared data and settings from parent shell FIRST
  // Data from shell has priority over localStorage
  requestSharedData();
  requestSettingsFromShell();

  // Fallback: try to load from localStorage after a short delay
  // (in case shell doesn't respond)
  setTimeout(() => {
    if (!analysisResults || Object.keys(variants).length === 0) {
      console.log('⏳ No data from shell yet, trying localStorage...');
      loadAllData();
    }
  }, 500);
});

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

  console.log('📊 Applied settings to Economics UI:', {
    totalEnergyPrice: settings.totalEnergyPrice,
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

      if (event.data.data.consumptionData) {
        consumptionData = event.data.data.consumptionData;
        console.log('  - consumptionData loaded:', consumptionData.dataPoints, 'points');
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

      // Load profile analysis BESS data if available
      if (event.data.data.profileAnalysis?.bessData) {
        profileAnalysisBessData = event.data.data.profileAnalysis.bessData;
        console.log('  - profileAnalysisBessData loaded:', profileAnalysisBessData.bess_energy_kwh, 'kWh');
      }

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
        console.log('🔋 BESS data from profile analysis:', {
          power_kw: profileAnalysisBessData.bess_power_kw,
          energy_kwh: profileAnalysisBessData.bess_energy_kwh,
          annual_cycles: profileAnalysisBessData.annual_cycles,
          annual_discharge_mwh: profileAnalysisBessData.annual_discharge_mwh,  // <-- KEY: from hourly simulation!
          strategy: profileAnalysisBessData.strategy
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

        // Recalculate economics with new BESS data available
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

  const discountRate = window.economicsSettings?.discountRate || 0.07;
  const inflationRate = window.economicsSettings?.inflationRate || 0.025;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';
  const analysisPeriod = params.analysis_period;
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

  // Update BESS source selector UI and apply selected source
  updateBessSourceSelector();

  try {
    // Get parameters from sidebar inputs
    const params = getEconomicParameters();
    console.log('📊 Using economic parameters:', params);

    // Calculate total energy cost (PLN/MWh)
    const totalEnergyPrice = calculateTotalEnergyPrice(params);
    const totalEnergyPriceWithCapacity = totalEnergyPrice + calculateCapacityFeeForConsumption(consumptionData, params);

    console.log('💰 Total energy price:', totalEnergyPrice, 'PLN/MWh');
    console.log('💰 Total with capacity fee:', totalEnergyPriceWithCapacity, 'PLN/MWh');

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
    const savings_year1 = self_consumed_annual * totalEnergyPriceWithCapacity; // PLN
    console.log(`💰 Savings Year 1: ${self_consumed_annual.toFixed(1)} MWh × ${totalEnergyPriceWithCapacity.toFixed(0)} PLN/MWh = ${(savings_year1/1000).toFixed(0)} tys. PLN`);

    // 4. Prosty okres zwrotu (bez zdyskontowania, bez degradacji)
    const simple_payback = capex / (savings_year1 - opex_annual); // lata

    // 5. Przepływy pieniężne z uwzględnieniem degradacji
    let cash_flows = [];
    let cumulative_cash_flow = -capex; // Start with negative CAPEX

    // Check if inflation should be applied (nominal IRR mode)
    const useInflation = window.economicsSettings?.useInflation || false;
    const inflationRate = useInflation ? (window.economicsSettings?.inflationRate || 0.025) : 0;

    for (let year = 1; year <= params.analysis_period; year++) {
      // Degradacja produkcji
      const degradation_factor = Math.pow(1 - params.degradation_rate, year - 1);
      const production_year = production_annual * degradation_factor;
      const self_consumed_year = self_consumed_annual * degradation_factor;

      // Inflation factor (applied only in nominal IRR mode)
      const inflation_factor = Math.pow(1 + inflationRate, year - 1);

      // Oszczędności w danym roku (z inflacją cen energii jeśli włączona)
      const adjustedEnergyPrice = totalEnergyPriceWithCapacity * inflation_factor;
      const savings_year = self_consumed_year * adjustedEnergyPrice;

      // OPEX z inflacją jeśli włączona
      const opex_year = opex_annual * inflation_factor;

      // Przepływ netto = oszczędności - OPEX
      const net_cash_flow = savings_year - opex_year;
      cumulative_cash_flow += net_cash_flow;

      cash_flows.push({
        year: year,
        savings: savings_year,
        opex: opex_year,
        net_cash_flow: net_cash_flow,
        cumulative_cash_flow: cumulative_cash_flow,
        production: production_year,        // MWh - for display
        selfConsumed: self_consumed_year,   // MWh - for display (use selfConsumed for consistency)
        unit: 'MWh'                         // Mark unit explicitly
      });
    }

    // 6. NPV i IRR - uproszczone
    // NPV = suma zdyskontowanych przepływów - CAPEX
    const discount_rate = 0.07; // 7% (można dodać do parametrów jeśli potrzeba)
    let npv = -capex;
    for (let cf of cash_flows) {
      npv += cf.net_cash_flow / Math.pow(1 + discount_rate, cf.year);
    }

    // IRR - przybliżone (metoda Newton-Raphson)
    let irr = calculateIRR()

    // 7. LCOE - Levelized Cost of Energy
    // LCOE = (CAPEX + suma zdyskontowanych OPEX) / suma zdyskontowanej produkcji
    let discounted_costs = capex;
    let discounted_production = 0;
    for (let cf of cash_flows) {
      discounted_costs += cf.opex / Math.pow(1 + discount_rate, cf.year);
      discounted_production += cf.production / Math.pow(1 + discount_rate, cf.year);
    }
    const lcoe = discounted_costs / discounted_production; // PLN/MWh

    // Backend economics parameters (single source of truth for IRR/NPV)
    const backendParams = {
      energy_price: totalEnergyPriceWithCapacity, // PLN/MWh
      feed_in_tariff: params.feed_in_tariff || 0,
      investment_cost: capexPerKwp, // PLN/kWp (tiered)
      export_mode: params.export_mode || 'zero',
      discount_rate: window.economicsSettings?.discountRate || 0.07,
      degradation_rate: params.degradation_rate,
      opex_per_kwp: params.opex_per_kwp,
      analysis_period: params.analysis_period,
      use_inflation: window.economicsSettings?.useInflation || false,
      irr_mode: window.economicsSettings?.irrMode || ((window.economicsSettings?.useInflation) ? 'nominal' : 'real'),
      inflation_rate: window.economicsSettings?.inflationRate || 0.0
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
      metrics: {
        annual_opex: opex_annual,
        capacity_kwp: capacity_kwp,
        total_energy_price: totalEnergyPriceWithCapacity
      },
      parameters: {
        ...params,
        energy_price: totalEnergyPriceWithCapacity,
        investment_cost: capexPerKwp,
        use_inflation: backendParams.use_inflation,
        irr_mode: irrMode,
        inflation_rate: backendParams.inflation_rate
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

    // Generate charts
    generateCashFlowChart(economicData);
    generateRevenueChart(economicData);

    // Generate payback table
    generatePaybackTable(economicData, capacity_kwp, params);

    // Generate revenue/cost table
    generateRevenueTable(economicData);

    // Automatically calculate EaaS analysis
    console.log('🎯 About to call calculateEaaS()...');
    calculateEaaS();
    console.log('🎯 calculateEaaS() completed');

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
  let totalCosts = capex;
  let totalEnergy = 0;
  for (let year = 1; year <= horizon; year++) {
    totalCosts += opexAnnual / Math.pow(1 + discountRate, year);
    totalEnergy += annualProduction / Math.pow(1 + discountRate, year);
  }
  const lcoe = totalCosts / totalEnergy;

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
  const discountRateValue = window.economicsSettings?.discountRate || 0.07;
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
  const totalEnergyPrice = calculateTotalEnergyPrice(params);
  const capacityFee = calculateCapacityFeeForConsumption(consumptionData, params);
  const totalPriceWithCapacity = totalEnergyPrice + capacityFee;

  // Get EaaS parameters from fullModelResult (stored globally)
  const eaasSubscription = window.eaasSubscription || 800000;
  const eaasOM = params.opex_per_kwp || (systemSettings?.opexPerKwp || 15);
  const eaasDuration = systemSettings?.eaasDuration || 10;
  const insuranceRate = systemSettings?.insuranceRate || 0.005;

  // Base parameters
  const capacity_kwp = variant.capacity;
  const self_consumed = variant.self_consumed;
  const capex_per_kwp = getCapexForCapacity(capacity_kwp);
  const base_discount_rate = window.economicsSettings?.discountRate || 0.07;
  const inflation_rate = window.economicsSettings?.inflationRate || 0.025; // 2.5% default
  const eaas_indexation = window.economicsSettings?.eaasIndexation || 'fixed';

  // === 1. Energy Price Sensitivity Chart ===
  const energyPriceVariations = [-30, -20, -10, 0, 10, 20, 30, 40, 50];
  const capexNPVsByEnergy = [];
  const eaasNPVsByEnergy = [];
  const energyPriceLabels = [];

  energyPriceVariations.forEach(variation => {
    const factor = 1 + (variation / 100);
    const adjustedPrice = totalPriceWithCapacity * factor;
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
      total_energy_price_per_kwh: totalPriceWithCapacity / 1000,
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
      total_energy_price_per_kwh: totalPriceWithCapacity / 1000,
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
    baseEnergyPrice: totalPriceWithCapacity,
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
function exportRevenueToExcel() {
  if (!economicData || !economicData.cash_flows) {
    alert('Brak danych do eksportu. Wykonaj najpierw analizę.');
    return;
  }

  console.log('📥 Exporting revenue table to Excel...');

  // Prepare data for Excel
  const excelData = [];

  // Header row
  excelData.push(['Rok', 'Oszczędności [tys. PLN]', 'OPEX [tys. PLN]', 'Zysk netto [tys. PLN]', 'Marża [%]']);

  // Data rows
  let totalSavings = 0;
  let totalOpex = 0;
  let totalProfit = 0;

  economicData.cash_flows.forEach((cf) => {
    const savings = cf.savings / 1000; // PLN → tys. PLN
    const opex = cf.opex / 1000;
    const profit = cf.net_cash_flow / 1000;
    const margin = (profit / savings) * 100;

    totalSavings += savings;
    totalOpex += opex;
    totalProfit += profit;

    excelData.push([
      cf.year,
      parseFloat(savings.toFixed(2)),
      parseFloat(opex.toFixed(2)),
      parseFloat(profit.toFixed(2)),
      parseFloat(margin.toFixed(2))
    ]);
  });

  // Summary row
  const avgMargin = (totalProfit / totalSavings) * 100;
  excelData.push([
    'SUMA',
    parseFloat(totalSavings.toFixed(2)),
    parseFloat(totalOpex.toFixed(2)),
    parseFloat(totalProfit.toFixed(2)),
    parseFloat(avgMargin.toFixed(2))
  ]);

  // Create workbook and worksheet
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(excelData);

  // Set column widths
  ws['!cols'] = [
    { wch: 10 },  // Rok
    { wch: 20 },  // Oszczędności
    { wch: 15 },  // OPEX
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

  const pvSelfConsumedKWh = annualPVProductionKWh * selfConsumptionRatio;

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
  const annualEnergyMWh = variant.self_consumed / 1000; // kWh -> MWh

  // Run full investor model with all parameters from Settings
  const fullModelResult = calculateEaasFullModel(
    variant.capacity,
    annualEnergyMWh,
    systemSettings || {},
    params
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
    capexNPV: centralizedCalc.capex?.npv || 0,
    capexIRR: centralizedCalc.capex?.irr || 0,
    capexPayback: centralizedCalc.capex?.simplePayback || 0,
    // Common parameters
    totalEnergyPrice: centralizedCalc.common?.totalEnergyPrice || 0,
    inflationRate: centralizedCalc.common?.inflationRate || 0
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
 * Export EaaS analysis to Excel
 */
function exportEaaSToExcel() {
  console.log('📥 Exporting EaaS analysis to Excel...');

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

  // Sheet 1: Summary
  const summaryData = [
    ['ANALIZA EaaS (Energy-as-a-Service)'],
    [''],
    ['Data eksportu:', new Date().toLocaleString('pl-PL')],
    ['Wariant:', currentVariant],
    ['Moc instalacji [kWp]:', capacityKwp],
    ['Autokonsumpcja roczna [MWh]:', autoconsumptionMwh.toFixed(1)],
    [''],
    ['PARAMETRY WEJŚCIOWE'],
    ['Abonament EaaS [PLN/rok]:', eaasSubscription],
    ['O&M [PLN/kWp/rok]:', eaasOM],
    ['CAPEX [PLN]:', capex],
    ['Stopa ubezpieczenia [%]:', (EAAS_CONFIG.INSURANCE_RATE * 100).toFixed(1)],
    ['Degradacja [%/rok]:', (degradationRate * 100).toFixed(1)],
    ['Okres analizy [lat]:', analysisPeriod],
    [''],
    ['SKŁADNIKI TARYFY [PLN/MWh]'],
    ['Energia czynna:', tariffComponents.energyActive],
    ['Dystrybucja:', tariffComponents.distribution],
    ['Opłata jakościowa:', tariffComponents.quality],
    ['Opłata OZE:', tariffComponents.oze],
    ['Opłata kogeneracyjna:', tariffComponents.cogeneration],
    ['Opłata mocowa:', tariffComponents.capacity],
    ['Akcyza:', tariffComponents.excise],
    [''],
    ['WYNIKI ANALIZY'],
    ['Cena energii z sieci [PLN/MWh]:', (result.metrics.gridPricePLNperKWh * 1000).toFixed(2)],
    ['Efektywna cena EaaS [PLN/MWh]:', (result.metrics.eaasPricePLNperKWh * 1000).toFixed(2)],
    ['Różnica cen [PLN/MWh]:', (result.metrics.priceDifferencePLNperKWh * 1000).toFixed(2)],
    [''],
    ['Roczne oszczędności [tys. PLN]:', (result.metrics.annualSavingsPLN / 1000).toFixed(1)],
    ['Procent oszczędności [%]:', result.metrics.savingsPercentageVsBaseline.toFixed(1)],
    [''],
    ['Równoważny okres zwrotu [lat]:', result.metrics.eaasEquivalentPaybackYears.toFixed(1)],
    ['Równoważny ROI [%]:', result.metrics.eaasEquivalentROI.toFixed(1)],
    [''],
    ['STRUKTURA KOSZTÓW EaaS [PLN/rok]'],
    ['Abonament:', result.metrics.breakdown.subscriptionCost],
    ['O&M:', result.metrics.breakdown.omCost.toFixed(0)],
    ['Ubezpieczenie:', result.metrics.breakdown.insuranceCost.toFixed(0)],
    ['RAZEM:', result.metrics.breakdown.totalAnnualCost.toFixed(0)]
  ];

  const ws1 = XLSX.utils.aoa_to_sheet(summaryData);

  // Set column widths
  ws1['!cols'] = [
    { wch: 35 },
    { wch: 20 }
  ];

  XLSX.utils.book_append_sheet(wb, ws1, 'Podsumowanie EaaS');

  // Sheet 2: Year-by-year analysis with two phases
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || 10;

  const discountRate = window.economicsSettings?.discountRate || 0.07;
  const inflationRate = window.economicsSettings?.inflationRate || 0.025;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';
  const eaasIndexationLabel = eaasIndexation === 'cpi' ? 'Indeksacja CPI' : 'Stała cena';

  const yearlyData = [
    ['ANALIZA EaaS ROK PO ROKU Z NPV'],
    [''],
    ['Stopa dyskontowa:', `${(discountRate * 100).toFixed(0)}%`],
    ['Inflacja:', `${(inflationRate * 100).toFixed(1)}%`],
    ['Indeksacja EaaS:', eaasIndexationLabel],
    ['Okres umowy EaaS:', `${eaasDuration} lat`],
    [''],
    ['Rok', 'Faza', 'Autokonsumpcja [MWh]', 'Koszt Sieci [tys. PLN]', 'Koszt EaaS/Własność [tys. PLN]', 'Oszczędności [tys. PLN]', 'CF Zdyskontowany [tys. PLN]', 'Skumulowany NPV [mln PLN]']
  ];

  let cumulativeNPV = 0;
  let eaasPhaseSavings = 0;
  let ownershipPhaseSavings = 0;
  const baseAutoconsumption = autoconsumptionMwh * 1000; // kWh

  // Costs breakdown (base values)
  const baseSubscriptionCost = result.metrics.breakdown.subscriptionCost;
  const baseOmCost = result.metrics.breakdown.omCost;
  const baseInsuranceCost = result.metrics.breakdown.insuranceCost;
  const baseGridPrice = gridPrice;

  for (let year = 1; year <= analysisPeriod; year++) {
    const degradationFactor = Math.pow(1 - degradationRate, year - 1);
    const inflationFactor = Math.pow(1 + inflationRate, year - 1);
    const autoconsumption = baseAutoconsumption * degradationFactor;

    // Apply inflation to energy price (always)
    const adjustedGridPrice = baseGridPrice * inflationFactor;
    // EaaS costs: apply inflation only if indexation is 'cpi'
    const eaasInflationFactor = eaasIndexation === 'cpi' ? inflationFactor : 1;
    const adjustedSubscriptionCost = baseSubscriptionCost * eaasInflationFactor;
    const adjustedOmCost = baseOmCost * eaasInflationFactor;
    const adjustedInsuranceCost = baseInsuranceCost * eaasInflationFactor;

    const gridCost = autoconsumption * adjustedGridPrice;

    let eaasCost;
    let phase;

    if (year <= eaasDuration) {
      eaasCost = adjustedSubscriptionCost + adjustedOmCost + adjustedInsuranceCost;
      phase = 'EaaS';
      eaasPhaseSavings += gridCost - eaasCost;
    } else {
      eaasCost = adjustedOmCost + adjustedInsuranceCost;
      phase = 'Własność';
      ownershipPhaseSavings += gridCost - eaasCost;
    }

    const savings = gridCost - eaasCost;
    const discountFactor = Math.pow(1 + discountRate, year);
    const discountedCF = savings / discountFactor;
    cumulativeNPV += discountedCF;

    yearlyData.push([
      year,
      phase,
      (autoconsumption / 1000).toFixed(1),
      (gridCost / 1000).toFixed(0),
      (eaasCost / 1000).toFixed(0),
      (savings / 1000).toFixed(0),
      (discountedCF / 1000).toFixed(0),
      (cumulativeNPV / 1000000).toFixed(3)
    ]);
  }

  // Add phase summary rows
  yearlyData.push(['']);
  yearlyData.push(['', '', '', '', `Suma faza EaaS (1-${eaasDuration}):`, (eaasPhaseSavings / 1000).toFixed(0), '', '']);
  yearlyData.push(['', '', '', '', `Suma faza własności (${eaasDuration + 1}-${analysisPeriod}):`, (ownershipPhaseSavings / 1000).toFixed(0), '', '']);
  yearlyData.push(['', '', '', '', 'SUMA CAŁKOWITA:', ((eaasPhaseSavings + ownershipPhaseSavings) / 1000).toFixed(0), 'NPV:', (cumulativeNPV / 1000000).toFixed(3)]);

  const ws2 = XLSX.utils.aoa_to_sheet(yearlyData);

  // Set column widths
  ws2['!cols'] = [
    { wch: 6 },
    { wch: 10 },
    { wch: 20 },
    { wch: 20 },
    { wch: 25 },
    { wch: 20 },
    { wch: 20 },
    { wch: 22 }
  ];

  XLSX.utils.book_append_sheet(wb, ws2, 'EaaS Rok po Roku');

  // ========== SHEET 3: Monthly Cash Flows (Full Model) ==========
  // Run full model to get monthly flows
  const annualEnergyMWh = variant.self_consumed / 1000;
  const fullModelResult = calculateEaasFullModel(
    capacityKwp,
    annualEnergyMWh,
    systemSettings || {},
    params
  );

  if (fullModelResult && fullModelResult.monthlyFlows && fullModelResult.monthlyFlows.length > 0) {
    const monthlyData = [
      ['MIESIĘCZNE PRZEPŁYWY PIENIĘŻNE (PEŁNY MODEL INWESTORA)'],
      [''],
      ['Moc instalacji [kWp]:', capacityKwp],
      [`Waluta: ${fullModelResult.currency}`, `Target IRR: ${(fullModelResult.targetIrr * 100).toFixed(1)}%`],
      [`Project IRR: ${(fullModelResult.projectIrr * 100).toFixed(2)}%`, `Equity IRR: ${(fullModelResult.equityIrr * 100).toFixed(2)}%`],
      [''],
      ['Miesiąc', 'Rok', 'Abonament', 'OPEX', 'EBITDA', 'Amortyzacja', 'EBIT', 'Odsetki', 'Kapitał', 'Podatek', 'CF Project', 'CF Equity', 'Saldo długu', 'CPI kum.']
    ];

    for (const flow of fullModelResult.monthlyFlows) {
      if (flow.month === 0) {
        // Initial investment row
        monthlyData.push([
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          (flow.capex / 1000).toFixed(0),
          ((flow.cfEquity || flow.capex + flow.debtDraw) / 1000).toFixed(0),
          ((flow.debtDraw || 0) / 1000).toFixed(0),
          ''
        ]);
      } else {
        monthlyData.push([
          flow.month,
          flow.year,
          (flow.subscription / 1000).toFixed(1),
          (flow.opex / 1000).toFixed(1),
          (flow.ebitda / 1000).toFixed(1),
          (flow.depreciation / 1000).toFixed(1),
          (flow.ebit / 1000).toFixed(1),
          (flow.interest / 1000).toFixed(1),
          (flow.principal / 1000).toFixed(1),
          (flow.tax / 1000).toFixed(1),
          (flow.cfProject / 1000).toFixed(1),
          (flow.cfEquity / 1000).toFixed(1),
          (flow.debtBalance / 1000).toFixed(0),
          (flow.cumulativeCpi * 100).toFixed(1) + '%'
        ]);
      }
    }

    // Add residual value note
    monthlyData.push(['']);
    monthlyData.push([`Wartość rezydualna: ${(fullModelResult.residualValue || capacityKwp).toLocaleString()} PLN (wykup 1 PLN/kWp)`]);
    monthlyData.push([`Expected Loss Rate: ${fullModelResult.expectedLossRate?.toFixed(1) || 0}%`]);
    monthlyData.push([`Degradacja: ${fullModelResult.degradationRate?.toFixed(1) || 0.5}%/rok`]);

    const ws3 = XLSX.utils.aoa_to_sheet(monthlyData);

    // Set column widths
    ws3['!cols'] = [
      { wch: 8 },  // Miesiąc
      { wch: 5 },  // Rok
      { wch: 12 }, // Abonament
      { wch: 10 }, // OPEX
      { wch: 10 }, // EBITDA
      { wch: 12 }, // Amortyzacja
      { wch: 10 }, // EBIT
      { wch: 10 }, // Odsetki
      { wch: 10 }, // Kapitał
      { wch: 10 }, // Podatek
      { wch: 12 }, // CF Project
      { wch: 12 }, // CF Equity
      { wch: 12 }, // Saldo długu
      { wch: 10 }  // CPI kum.
    ];

    XLSX.utils.book_append_sheet(wb, ws3, 'CF Miesięczny');
    console.log('✅ Monthly cash flows sheet added');
  }

  // Generate filename
  const timestamp = new Date().toISOString().slice(0, 10);
  const filename = `EaaS_Analiza_${currentVariant}_${capacityKwp}kWp_${timestamp}.xlsx`;

  // Save file
  XLSX.writeFile(wb, filename);
  console.log('✅ EaaS analysis exported to:', filename);
}

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
// BESS SOURCE SELECTOR FUNCTIONS
// ============================================

/**
 * Update the BESS source selector UI based on available data
 */
function updateBessSourceSelector() {
  const section = document.getElementById('bessSourceSection');
  const select = document.getElementById('bessSourceSelect');
  const configInfo = document.getElementById('bessSourceConfig');
  const profileInfo = document.getElementById('bessSourceProfile');
  const warning = document.getElementById('bessSourceWarning');

  if (!section) return;

  // Get BESS data from both sources
  const variant = variants[currentVariant];
  const hasConfigBess = variant && variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  const hasProfileBess = profileAnalysisBessData && profileAnalysisBessData.bess_energy_kwh > 0;

  // Store config BESS data for later comparison
  if (hasConfigBess) {
    configBessData = {
      bess_power_kw: variant.bess_power_kw,
      bess_energy_kwh: variant.bess_energy_kwh,
      bess_cycles_equivalent: variant.bess_cycles_equivalent,
      // Store original BESS energy data for table calculations
      bess_self_consumed_from_bess_kwh: variant.bess_self_consumed_from_bess_kwh || 0,
      bess_discharged_kwh: variant.bess_discharged_kwh || 0
    };
  }

  // Show section only if at least one source has BESS data
  if (!hasConfigBess && !hasProfileBess) {
    section.style.display = 'none';
    return;
  }

  // Show section if we have both sources OR profile source
  if (hasConfigBess && hasProfileBess) {
    section.style.display = 'block';

    // Update info displays
    configInfo.style.display = 'inline';
    document.getElementById('bessConfigPower').textContent = configBessData.bess_power_kw.toFixed(0);
    document.getElementById('bessConfigEnergy').textContent = configBessData.bess_energy_kwh.toFixed(0);

    profileInfo.style.display = 'inline';
    document.getElementById('bessProfilePower').textContent = profileAnalysisBessData.bess_power_kw.toFixed(0);
    document.getElementById('bessProfileEnergy').textContent = profileAnalysisBessData.bess_energy_kwh.toFixed(0);

    // Enable both options
    select.querySelector('option[value="pv-calculation"]').disabled = false;
    select.querySelector('option[value="profile-analysis"]').disabled = false;

    // Show warning if sources differ significantly (>10%)
    const energyDiff = Math.abs(configBessData.bess_energy_kwh - profileAnalysisBessData.bess_energy_kwh) / configBessData.bess_energy_kwh;
    warning.style.display = energyDiff > 0.1 ? 'block' : 'none';

    // IMPORTANT: If profile-analysis data was just received (newer/more accurate),
    // auto-select it and apply to variant for consistent hourly simulation data
    // Check if annual_discharge_mwh exists (even if 0) - this is our "single source of truth" marker
    const hasHourlySimData = 'annual_discharge_mwh' in profileAnalysisBessData;
    console.log('🔋 Checking auto-select:', {
      hasHourlySimData,
      annual_discharge_mwh: profileAnalysisBessData.annual_discharge_mwh,
      currentBessSource
    });
    if (hasHourlySimData) {
      select.value = 'profile-analysis';
      currentBessSource = 'profile-analysis';
      applyBessSourceToVariant();
      console.log('🔋 Auto-selected profile-analysis (has hourly simulation data)');
    }

  } else if (hasProfileBess && !hasConfigBess) {
    // Only profile source available
    section.style.display = 'block';
    configInfo.style.display = 'none';
    profileInfo.style.display = 'inline';
    document.getElementById('bessProfilePower').textContent = profileAnalysisBessData.bess_power_kw.toFixed(0);
    document.getElementById('bessProfileEnergy').textContent = profileAnalysisBessData.bess_energy_kwh.toFixed(0);

    // Disable config option, auto-select profile
    select.querySelector('option[value="pv-calculation"]').disabled = true;
    select.querySelector('option[value="profile-analysis"]').disabled = false;
    select.value = 'profile-analysis';
    currentBessSource = 'profile-analysis';
    warning.style.display = 'none';

    // IMPORTANT: Apply profile-analysis data to variant immediately
    applyBessSourceToVariant();

  } else if (hasConfigBess && !hasProfileBess) {
    // Only config source available - hide section (no choice needed)
    section.style.display = 'none';
  }

  console.log('🔋 BESS source selector updated:', {
    hasConfigBess,
    hasProfileBess,
    currentSource: currentBessSource
  });
}

/**
 * Handle BESS source change from dropdown
 */
function changeBessSource() {
  const select = document.getElementById('bessSourceSelect');
  const newSource = select.value;

  if (newSource === currentBessSource) return;

  currentBessSource = newSource;
  console.log('🔋 BESS source changed to:', currentBessSource);

  // Apply BESS data from selected source to current variant
  applyBessSourceToVariant();

  // Recalculate economics
  if (analysisResults) {
    performEconomicAnalysis();
  }
}
window.changeBessSource = changeBessSource;

/**
 * Apply BESS data from selected source to the current variant
 *
 * IMPORTANT: This function updates ALL BESS-related fields including:
 * - bess_power_kw, bess_energy_kwh (sizing)
 * - bess_cycles_equivalent (cycles per year)
 * - bess_self_consumed_from_bess_kwh (energy delivered to load - used in NPV tables!)
 * - bess_discharged_kwh (total discharge)
 */
function applyBessSourceToVariant() {
  const variant = variants[currentVariant];
  if (!variant) return;

  // Get BESS efficiency from settings (default 90% round-trip = 95% one-way)
  const settings = systemSettings || {};
  const roundtripEfficiency = settings.bessRoundtripEfficiency || 0.90;
  const oneWayEfficiency = Math.sqrt(roundtripEfficiency);
  const usableDepthOfDischarge = 0.8; // 80% DoD

  if (currentBessSource === 'profile-analysis' && profileAnalysisBessData) {
    // Override with profile analysis data
    variant.bess_power_kw = profileAnalysisBessData.bess_power_kw;
    variant.bess_energy_kwh = profileAnalysisBessData.bess_energy_kwh;
    variant.bess_cycles_equivalent = profileAnalysisBessData.annual_cycles;
    variant.bess_source = 'profile-analysis';

    // USE annual_discharge_mwh DIRECTLY from profile-analysis!
    // This value comes from real hourly simulation - DO NOT recalculate from cycles!
    // The cycles × usable_capacity formula was overestimating by ~6x because it assumed
    // every day could fully utilize the average surplus.
    const annualDischargeMwh = profileAnalysisBessData.annual_discharge_mwh || 0;
    const annualDischargeKwh = annualDischargeMwh * 1000;

    variant.bess_self_consumed_from_bess_kwh = annualDischargeKwh;
    variant.bess_discharged_kwh = annualDischargeKwh;

    console.log('✅ Applied profile-analysis BESS:', variant.bess_power_kw, 'kW /', variant.bess_energy_kwh, 'kWh');
    console.log('   📊 Annual discharge from hourly simulation:', annualDischargeMwh.toFixed(1), 'MWh');
    console.log('   📊 Annual cycles:', (profileAnalysisBessData.annual_cycles || 0).toFixed(1));

  } else if (currentBessSource === 'pv-calculation' && configBessData) {
    // Restore original config data (from pv-calculation simulation)
    variant.bess_power_kw = configBessData.bess_power_kw;
    variant.bess_energy_kwh = configBessData.bess_energy_kwh;
    variant.bess_cycles_equivalent = configBessData.bess_cycles_equivalent;
    variant.bess_self_consumed_from_bess_kwh = configBessData.bess_self_consumed_from_bess_kwh;
    variant.bess_discharged_kwh = configBessData.bess_discharged_kwh;
    variant.bess_source = 'pv-calculation';
    console.log('✅ Applied pv-calculation BESS:', variant.bess_power_kw, 'kW /', variant.bess_energy_kwh, 'kWh');
    console.log('   📊 Original annual discharge:', ((configBessData.bess_self_consumed_from_bess_kwh || 0) / 1000).toFixed(1), 'MWh');
  }
}

/**
 * Get current BESS data based on selected source
 */
function getCurrentBessData() {
  if (currentBessSource === 'profile-analysis' && profileAnalysisBessData) {
    return profileAnalysisBessData;
  } else if (configBessData) {
    return configBessData;
  }
  return null;
}

console.log('📦 economics.js fully loaded');
