console.log('🚀 economics.js LOADED - timestamp:', new Date().toISOString());

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

function getInsuranceRate(settings) {
  const raw = settings?.insuranceRate;
  if (raw === undefined || raw === null) {
    return window.economicsSettings?.insuranceRate || 0.005;
  }
  // If user provided percentage (>1), convert to decimal fraction
  return raw > 1 ? raw / 100 : raw;
}

// Get CAPEX per kWp based on capacity using tiered pricing
function getCapexForCapacity(capacityKwp) {
  // Try to get CAPEX tiers from systemSettings first, then analysisResults
  const capexTiers = systemSettings?.capexTiers || analysisResults?.economicParams?.capexTiers;

  if (capexTiers && capexTiers.length > 0) {
    for (const tier of capexTiers) {
      if (capacityKwp >= tier.min && capacityKwp <= tier.max) {
        return tier.capex;
      }
    }
    // Fallback: use last tier for very large installations
    if (capacityKwp > 50000) {
      return capexTiers[capexTiers.length - 1].capex;
    }
    // Fallback: use first tier for very small installations
    return capexTiers[0].capex;
  }

  // Fallback to default investment cost from input
  return parseFloat(document.getElementById('investmentCost')?.value || 3500);
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
  // Suma wszystkich składowych ceny energii
  return params.energy_active + params.distribution + params.quality_fee +
         params.oze_fee + params.cogeneration_fee + params.excise_tax;
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
  const payload = {
    variant: {
      capacity: variant.capacity,
      production: variant.production,
      self_consumed: variant.self_consumed,
      exported: variant.exported,
      auto_consumption_pct: variant.auto_consumption_pct,
      coverage_pct: variant.coverage_pct
    },
    parameters: {
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
    }
  };

  const response = await fetch('http://localhost:8003/analyze', {
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

  const response = await fetch('http://localhost:8003/eaas-monthly', {
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
 * Calculate EaaS annual subscription to achieve target IRR
 *
 * Implements financial model with proper annuity formula:
 * - FIXED mode: A = O + I₀ · [r(1+r)^N] / [(1+r)^N - 1]
 * - CPI mode: A_real = O_real + I₀ · [r_real(1+r_real)^N] / [(1+r_real)^N - 1]
 *              where r_real = (1+r)/(1+g) - 1
 *
 * @param {number} capacityKw - Installation capacity in kW
 * @param {object} settings - System settings with EaaS parameters
 * @param {object} economicParams - Economic parameters (OPEX, degradation, etc.)
 * @returns {object} - { annualSubscription, monthlySubscription, totalRevenue, irr, pricePerMWh }
 */
function calculateEaasSubscription(capacityKw, settings, economicParams) {
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
  const capexPerKwp = getCapexForCapacity(capacityKw);
  const I0_PLN = capacityKw * capexPerKwp; // Total CAPEX in PLN

  // ========== OPEX (in PLN - base currency) ==========
  const opexPerKwp = economicParams.opex_per_kwp || settings.opexPerKwp || 15;
  const insuranceRate = getInsuranceRate(settings); // normalized decimal (e.g., 0.005 = 0.5%)
  const landLeasePerKwp = settings.landLeasePerKwp || 0; // Land lease cost per kWp [PLN/kWp/year]

  const annualOM_PLN = capacityKw * opexPerKwp; // O&M
  const annualInsurance_PLN = I0_PLN * insuranceRate; // Insurance
  const annualLandLease_PLN = capacityKw * landLeasePerKwp; // Land lease
  const O_PLN = annualOM_PLN + annualInsurance_PLN + annualLandLease_PLN; // Total annual OPEX

  console.log(`  📋 INPUTS:`);
  console.log(`     Waluta: ${currency}`);
  console.log(`     Okres umowy: ${N} lat`);
  console.log(`     Typ opłaty: ${indexationType}`);
  console.log(`     Target IRR: ${(r * 100).toFixed(1)}%`);
  console.log(`     Inflacja (CPI ${currency}): ${(g * 100).toFixed(1)}%`);
  console.log(`  `);
  console.log(`  💰 PARAMETRY (waluta bazowa PLN):`);
  console.log(`     CAPEX (I₀): ${(I0_PLN / 1000000).toFixed(2)} mln PLN (${capexPerKwp} PLN/kWp)`);
  console.log(`     OPEX (O): ${O_PLN.toFixed(0)} PLN/rok`);
  console.log(`       - O&M: ${annualOM_PLN.toFixed(0)} PLN/rok`);
  console.log(`       - Ubezpieczenie: ${annualInsurance_PLN.toFixed(0)} PLN/rok`);
  if (annualLandLease_PLN > 0) {
    console.log(`       - Najem powierzchni: ${annualLandLease_PLN.toFixed(0)} PLN/rok`);
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
  const achievedIRR = calculateIRR();
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
  loadAllData();
  // Request shared data and settings from parent shell
  requestSharedData();
  requestSettingsFromShell();
});

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
        pvConfig = event.data.data.pvConfig;
        console.log('  - pvConfig loaded:', !!pvConfig);
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

    case 'ECONOMIC_DATA_UPDATED':
    case 'PV_CONFIG_UPDATED':
    case 'DATA_AVAILABLE':
      console.log('🔄 Data updated, reloading...');
      loadAllData();
      break;
    case 'DATA_CLEARED':
      clearAnalysis();
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
  }
});

// Load all data from localStorage or backend
async function loadAllData() {
  // Try localStorage first
  const storedEconomic = localStorage.getItem('economicData');
  const storedConfig = localStorage.getItem('pvConfig');
  const storedProduction = localStorage.getItem('pvProductionData');
  const storedAnalysisResults = localStorage.getItem('analysisResults') || localStorage.getItem('pv_analysis_results');

  if (storedEconomic || storedConfig) {
    try {
      if (storedEconomic) economicData = JSON.parse(storedEconomic);
      if (storedConfig) pvConfig = JSON.parse(storedConfig);
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
      const economicsResponse = await fetch('http://localhost:8003/');
      if (economicsResponse.ok) {
        const economicsInfo = await economicsResponse.json();
        // Economics service is running, could fetch data here if available
        economicsDataFetched = true;
      }
    } catch (e) {
      console.log('Economics service not available, using generated data');
    }

    // Check if data service has data
    const healthResponse = await fetch('http://localhost:8001/health');
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
        name: 'Domyślna konfiguracja'
      };
    } else if (storedConfig) {
      try {
        pvConfig = JSON.parse(storedConfig);
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

  // Common parameters
  const capacityKwp = variant.capacity;
  const productionKwh = variant.production;
  const selfConsumedKwh = variant.self_consumed;
  const capexPerKwp = getCapexForCapacity(capacityKwp);
  const capex = capacityKwp * capexPerKwp;

  const discountRate = window.economicsSettings?.discountRate || 0.07;
  const inflationRate = window.economicsSettings?.inflationRate || 0.025;
  const eaasIndexation = window.economicsSettings?.eaasIndexation || 'fixed';
  const analysisPeriod = params.analysis_period;
  const degradationRate = params.degradation_rate;

  // IRR calculation mode - determines if we apply inflation to cash flows
  const useInflation = window.economicsSettings?.useInflation || false;
  const irrMode = useInflation ? 'nominal' : 'real';

  const totalEnergyPrice = (params.energy_active + params.distribution + params.quality_fee +
                            params.oze_fee + params.cogeneration_fee + params.capacity_fee +
                            params.excise_tax) / 1000; // PLN/kWh

  // ========== CAPEX MODEL CALCULATION ==========
  console.log('🔢 CENTRALIZED CAPEX NPV Calculation:');
  console.log('  📅 Analysis period:', analysisPeriod, 'years');
  console.log('  📊 Discount rate:', (discountRate * 100).toFixed(1), '%');
  console.log('  📈 Inflation rate:', (inflationRate * 100).toFixed(1), '%');
  console.log('  📉 Degradation:', (degradationRate * 100).toFixed(2), '%/year');
  console.log('  💰 Initial CAPEX:', (-capex / 1000000).toFixed(2), 'mln PLN');
  console.log('  📊 IRR Mode:', irrMode, useInflation ? '(inflation-indexed cash flows)' : '(constant prices)');

  let capexNPV = -capex;
  let capexCashFlows = [];

  for (let year = 1; year <= analysisPeriod; year++) {
    const degradation = Math.pow(1 - degradationRate, year - 1);
    // Apply inflation factor only if useInflation is true (nominal mode)
    const inflationFactor = useInflation ? Math.pow(1 + inflationRate, year - 1) : 1;
    const yearSelfConsumed = selfConsumedKwh * degradation;
    const adjustedEnergyPrice = totalEnergyPrice * inflationFactor;
    const adjustedOpex = capacityKwp * params.opex_per_kwp * inflationFactor;
    const yearSavings = yearSelfConsumed * adjustedEnergyPrice;
    const yearCashFlow = yearSavings - adjustedOpex;
    const discountedCF = yearCashFlow / Math.pow(1 + discountRate, year);
    capexNPV += discountedCF;

    capexCashFlows.push({
      year: year,
      savings: yearSavings,
      opex: adjustedOpex,
      net_cash_flow: yearCashFlow,
      production: productionKwh * degradation
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
      const degradation = Math.pow(1 - degradationRate, year - 1);
      const inflationFactor = Math.pow(1 + inflationRate, year - 1);
      const yearSelfConsumed = selfConsumedKwh * degradation;
      const adjustedGridPrice = totalEnergyPrice * inflationFactor;

      // EaaS subscription: apply inflation only if indexation is 'cpi'
      const eaasInflationFactor = eaasIndexation === 'cpi' ? inflationFactor : 1;
      const adjustedSubscriptionCost = baseSubscriptionCost * eaasInflationFactor;

      // OPEX costs after EaaS contract: ALWAYS apply inflation (real-world costs grow with inflation)
      const adjustedOmCost = baseOmCost * inflationFactor;
      const adjustedInsuranceCost = baseInsuranceCost * inflationFactor;
      const adjustedLandLeaseCost = baseLandLeaseCost * inflationFactor;

      const gridCost = yearSelfConsumed * adjustedGridPrice;

      let eaasCost;
      if (year <= eaasDuration) {
        // IMPORTANT: Subscription already includes OPEX (O&M + insurance + land lease) from annuity formula
        // Do NOT add them again - that would be triple-counting!
        eaasCost = adjustedSubscriptionCost;
      } else {
        // After EaaS contract ends, customer pays O&M + insurance + land lease (inflation-indexed)
        eaasCost = adjustedOmCost + adjustedInsuranceCost + adjustedLandLeaseCost;
      }

      const savings = gridCost - eaasCost;
      const discountedCF = savings / Math.pow(1 + discountRate, year);
      eaasNPV += discountedCF;

      eaasCashFlows.push({
        year: year,
        gridCost: gridCost,
        eaasCost: eaasCost,
        savings: savings,
        discountedCF: discountedCF,
        phase: year <= eaasDuration ? 'eaas' : 'ownership'
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
      productionKwh: productionKwh,
      selfConsumedKwh: selfConsumedKwh,
      totalEnergyPrice: totalEnergyPrice,
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
    const self_consumed_annual = variant.self_consumed / 1000; // kWh → MWh

    console.log('📊 Variant data:', {
      capacity_kwp,
      production_annual_MWh: production_annual,
      self_consumed_annual_MWh: self_consumed_annual
    });

    // === PROSTY MODEL CAPEX ===

    // 1. Nakłady inwestycyjne (CAPEX) - using tiered pricing based on capacity
    const capexPerKwp = getCapexForCapacity(capacity_kwp);
    const capex = capacity_kwp * capexPerKwp; // PLN
    console.log(`💰 CAPEX: ${capacity_kwp} kWp × ${capexPerKwp} PLN/kWp = ${(capex/1000000).toFixed(2)} mln PLN`);

    // Update investmentCost field to show the calculated tiered CAPEX
    const investmentCostField = document.getElementById('investmentCost');
    if (investmentCostField) {
      investmentCostField.value = capexPerKwp;
      console.log(`📝 Updated investmentCost field to: ${capexPerKwp} PLN/kWp`);
    }

    // 2. Roczne koszty operacyjne (OPEX)
    const opex_annual = capacity_kwp * params.opex_per_kwp; // PLN/rok

    // 3. Roczne oszczędności = autoconsumption * cena energii
    const savings_year1 = self_consumed_annual * totalEnergyPriceWithCapacity; // PLN

    // 4. Prosty okres zwrotu (bez zdyskontowania, bez degradacji)
    const simple_payback = capex / (savings_year1 - opex_annual); // lata

    // 5. Przepływy pieniężne z uwzględnieniem degradacji
    let cash_flows = [];
    let cumulative_cash_flow = -capex; // Start with negative CAPEX

    for (let year = 1; year <= params.analysis_period; year++) {
      // Degradacja produkcji
      const degradation_factor = Math.pow(1 - params.degradation_rate, year - 1);
      const production_year = production_annual * degradation_factor;
      const self_consumed_year = self_consumed_annual * degradation_factor;

      // Oszczędności w danym roku
      const savings_year = self_consumed_year * totalEnergyPriceWithCapacity;

      // Przepływ netto = oszczędności - OPEX
      const net_cash_flow = savings_year - opex_annual;
      cumulative_cash_flow += net_cash_flow;

      cash_flows.push({
        year: year,
        savings: savings_year,
        opex: opex_annual,
        net_cash_flow: net_cash_flow,
        cumulative_cash_flow: cumulative_cash_flow,
        production: production_year
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
  const irr = economicData?.irr !== undefined && economicData?.irr !== null ? (economicData.irr * 100).toFixed(1) : 'N/A';

  // LCOE (Levelized Cost of Energy)
  let totalCosts = capex;
  let totalEnergy = 0;
  for (let year = 1; year <= horizon; year++) {
    totalCosts += opexAnnual / Math.pow(1 + discountRate, year);
    totalEnergy += annualProduction / Math.pow(1 + discountRate, year);
  }
  const lcoe = (totalCosts / totalEnergy).toFixed(2);

  // ROI
  const roi = ((npv / capex) * 100).toFixed(1);

  return {
    capex: (capex / 1000000).toFixed(2), // PLN -> mln PLN
    paybackPeriod: paybackPeriod.toFixed(1),
    npv: (npv / 1000000).toFixed(2),
    irr: irr,
    unitCapex: `${(capex / capacity).toFixed(0)} PLN/kWp`,
    lcoe: `${lcoe} PLN/kWh`,
    opexAnnual: `${(opexAnnual / 1000).toFixed(0)} tys. PLN`,
    revenueAnnual: `${(revenueAnnual / 1000).toFixed(0)} tys. PLN`,
    savingsAnnual: `${(savingsAnnual / 1000).toFixed(0)} tys. PLN`,
    roi: `${roi}%`,
    discountRate: `${((economicData?.discountRate || 0.05) * 100).toFixed(1)}%`,
    analysisHorizon: `${horizon} lat`,
    energyPrice: `${energyPrice.toFixed(2)} PLN/kWh`,
    subsidies: `${((economicData?.subsidies || 0) / 1000).toFixed(0)} tys. PLN`,
    taxRate: `${((economicData?.taxRate || 0.19) * 100).toFixed(0)}%`,
    inflationRate: `${((economicData?.inflationRate || 0.03) * 100).toFixed(1)}%`
  };
}

// Update metrics display
function updateMetrics(data) {
  // Main metrics from backend API
  document.getElementById('capex').textContent = (data.investment / 1000000).toFixed(2); // PLN → mln PLN
  document.getElementById('paybackPeriod').textContent = data.simple_payback.toFixed(1);
  document.getElementById('npv').textContent = (data.npv / 1000000).toFixed(2); // PLN → mln PLN

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
      irrElement.textContent = (irrValue * 100).toFixed(1); // decimal → %
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

  // Detailed metrics
  const variant = variants[currentVariant];
  const capacity_kwp = variant.capacity; // Already in kWp

  document.getElementById('unitCapex').textContent = `${(data.investment / capacity_kwp).toFixed(0)} PLN/kWp`;
  document.getElementById('lcoe').textContent = `${(data.lcoe * 1000).toFixed(2)} PLN/kWh`; // /kWh → /kWh
  document.getElementById('opexAnnual').textContent = `${(data.metrics.annual_opex / 1000).toFixed(0)} tys. PLN`;
  document.getElementById('revenueAnnual').textContent = `${(data.annual_total_revenue / 1000).toFixed(0)} tys. PLN`;
  document.getElementById('savingsAnnual').textContent = `${(data.annual_savings / 1000).toFixed(0)} tys. PLN`;
  document.getElementById('roi').textContent = `${((data.npv / data.investment) * 100).toFixed(1)}%`;

  // Display parameters from sidebar inputs
  const params = data.parameters;
  const discountRateValue = window.economicsSettings?.discountRate || 0.07;
  document.getElementById('discountRate').textContent = `${(discountRateValue * 100).toFixed(1)}%`;
  document.getElementById('analysisHorizon').textContent = `${params.analysis_period} lat`;
  document.getElementById('energyPrice').textContent = `${data.metrics.total_energy_price.toFixed(0)} PLN/MWh`;
  document.getElementById('subsidies').textContent = '0 PLN'; // Not implemented yet
  document.getElementById('taxRate').textContent = '0%'; // Not implemented yet
  document.getElementById('inflationRate').textContent = `${(params.degradation_rate * 100).toFixed(1)}%`; // Show degradation rate
}

// Update data info
function updateDataInfo() {
  if (!variants || !currentVariant) return;

  const variant = variants[currentVariant];
  const capacity = (variant.capacity / 1000).toFixed(1); // kWp → MWp
  const params = getEconomicParameters();
  const irrMode = economicData?.irrMode || centralizedMetrics[currentVariant]?.capex?.irrMode || 'real';
  const irrValue = economicData?.irr;
  const irrDisplay = irrValue !== null && irrValue !== undefined
    ? `${(irrValue * 100).toFixed(1)}% (${irrMode === 'nominal' ? 'nom.' : 'real'})`
    : 'N/A';
  const info = `Wariant ${currentVariant}: ${capacity} MWp • Analiza ${params.analysis_period}-letnia • IRR: ${irrDisplay}`;
  document.getElementById('dataInfo').textContent = info;
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

  // Get EaaS parameters
  const eaasSubscription = parseFloat(document.getElementById('eaasSubscription')?.value || 800000);
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value || 24);
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value || 10);
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
    <td>${(params.baseEnergyPrice).toFixed(0)} PLN/MWh</td>
    <td>${energyBreakeven}</td>
    <td><span style="color:${betterModel === 'CAPEX' ? '#2196f3' : '#ff9800'};font-weight:600">${betterModel}</span></td>
    <td class="${npvDifference >= 0 ? 'positive' : 'negative'}">${npvDifference.toFixed(2)}</td>
  `;
  tableBody.appendChild(row1);

  // Row 2: Discount rate
  const row2 = document.createElement('tr');
  row2.innerHTML = `
    <td>Stopa dyskontowa</td>
    <td>${(params.baseDiscountRate * 100).toFixed(0)}%</td>
    <td>${discountBreakeven}</td>
    <td><span style="color:${betterModel === 'CAPEX' ? '#2196f3' : '#ff9800'};font-weight:600">${betterModel}</span></td>
    <td class="${npvDifference >= 0 ? 'positive' : 'negative'}">${npvDifference.toFixed(2)}</td>
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

// Generate payback table
function generatePaybackTable(data, capacity_kwp, params) {
  const tableBody = document.getElementById('paybackTableBody');
  if (!tableBody) return;

  tableBody.innerHTML = '';

  // Get total energy price (base, without inflation)
  const totalEnergyPrice = calculateTotalEnergyPrice(params);
  const totalEnergyPriceWithCapacity = totalEnergyPrice + calculateCapacityFeeForConsumption(consumptionData, params);

  // Use centralized cash flows WITH inflation
  const cashFlows = data.centralized_cash_flows || data.cash_flows;

  // Year 0 - Initial investment
  const row0 = document.createElement('tr');
  row0.className = 'year-0';
  row0.innerHTML = `
    <td>0</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td>-</td>
    <td class="negative">-${(data.investment / 1000).toFixed(0)}</td>
    <td class="negative">-${(data.investment / 1000000).toFixed(2)}</td>
  `;
  tableBody.appendChild(row0);

  // Calculate cumulative cash flows (needed for break-even detection)
  let cumulativeCF = -data.investment;
  let breakEvenYear = null;

  // Years 1-N
  cashFlows.forEach((cf) => {
    const row = document.createElement('tr');

    cumulativeCF += cf.net_cash_flow;

    // Check if this is the break-even year
    const prevCumulativeCF = cf.year === 1 ? -data.investment : cumulativeCF - cf.net_cash_flow;
    if (prevCumulativeCF < 0 && cumulativeCF >= 0 && !breakEvenYear) {
      breakEvenYear = cf.year;
      row.className = 'breakeven';
    }

    const degradationPct = ((1 - Math.pow(1 - params.degradation_rate, cf.year - 1)) * 100).toFixed(1);
    const cfClass = cumulativeCF >= 0 ? 'positive' : 'negative';

    // Calculate inflation factor for this year to show adjusted energy price
    const inflationFactor = Math.pow(1 + (window.economicsSettings?.inflationRate || 0.025), cf.year - 1);
    const adjustedEnergyPrice = totalEnergyPriceWithCapacity * inflationFactor;

    row.innerHTML = `
      <td>${cf.year}</td>
      <td>${cf.production.toFixed(1)}</td>
      <td>${(cf.savings / adjustedEnergyPrice).toFixed(1)}</td>
      <td>${degradationPct}%</td>
      <td>${(cf.savings / 1000).toFixed(0)}</td>
      <td>${(cf.opex / 1000).toFixed(0)}</td>
      <td class="${cf.net_cash_flow >= 0 ? 'positive' : 'negative'}">${(cf.net_cash_flow / 1000).toFixed(0)}</td>
      <td class="${cfClass}">${(cumulativeCF / 1000000).toFixed(2)}</td>
    `;

    tableBody.appendChild(row);
  });

  console.log('✅ Payback table generated. Break-even year:', breakEvenYear || 'Beyond analysis period');
}

// Generate revenue and costs table
function generateRevenueTable(data) {
  const tableBody = document.getElementById('revenueTableBody');
  if (!tableBody) return;

  tableBody.innerHTML = '';

  // Use centralized cash flows WITH inflation
  const cashFlows = data.centralized_cash_flows || data.cash_flows;

  // Show first 10 years
  const yearsToShow = Math.min(10, cashFlows.length);
  let totalSavings = 0;
  let totalOpex = 0;
  let totalProfit = 0;

  for (let i = 0; i < yearsToShow; i++) {
    const cf = cashFlows[i];
    const row = document.createElement('tr');

    const savings = cf.savings;
    const opex = cf.opex;
    const profit = cf.net_cash_flow;
    const margin = ((profit / savings) * 100);

    totalSavings += savings;
    totalOpex += opex;
    totalProfit += profit;

    const profitClass = profit >= 0 ? 'positive' : 'negative';
    const marginClass = margin >= 0 ? 'positive' : 'negative';

    row.innerHTML = `
      <td>${cf.year}</td>
      <td>${(savings / 1000).toFixed(0)}</td>
      <td>${(opex / 1000).toFixed(0)}</td>
      <td class="${profitClass}">${(profit / 1000).toFixed(0)}</td>
      <td class="${marginClass}">${margin.toFixed(1)}%</td>
    `;

    tableBody.appendChild(row);
  }

  // Add summary row
  const summaryRow = document.createElement('tr');
  summaryRow.style.background = '#f8f9fa';
  summaryRow.style.fontWeight = '600';
  summaryRow.style.borderTop = '2px solid #27ae60';

  const avgMargin = ((totalProfit / totalSavings) * 100);
  const avgMarginClass = avgMargin >= 0 ? 'positive' : 'negative';

  summaryRow.innerHTML = `
    <td>SUMA</td>
    <td>${(totalSavings / 1000).toFixed(0)}</td>
    <td>${(totalOpex / 1000).toFixed(0)}</td>
    <td class="positive">${(totalProfit / 1000).toFixed(0)}</td>
    <td class="${avgMarginClass}">${avgMargin.toFixed(1)}%</td>
  `;

  tableBody.appendChild(summaryRow);

  console.log('✅ Revenue table generated for first', yearsToShow, 'years');
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
      breakdown: eaasResult.breakdown
    }
  };
}

/**
 * Format EaaS results for display
 */
function formatEaaSResults(result) {
  if (result.error) {
    return `<div style="color:#e74c3c;padding:12px;background:#fff5f5;border-radius:8px;border:1px solid #e74c3c">
      <strong>⚠️ Błąd obliczeń EaaS:</strong> ${result.error}
    </div>`;
  }

  const m = result.metrics;

  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px">
      <div style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Cena energii z sieci</div>
        <div style="color:#2c3e50;font-size:24px;font-weight:600">${(m.gridPricePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>

      <div style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Efektywna cena EaaS</div>
        <div style="color:#27ae60;font-size:24px;font-weight:600">${(m.eaasPricePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>

      <div style="background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Różnica cen</div>
        <div style="color:#27ae60;font-size:24px;font-weight:600">${(m.priceDifferencePLNperKWh * 1000).toFixed(2)}</div>
        <div style="color:#7f8c8d;font-size:11px">PLN/MWh</div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px">
      <div style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Roczne oszczędności</div>
        <div style="color:#27ae60;font-size:24px;font-weight:600">${(m.annualSavingsPLN / 1000).toFixed(1)}</div>
        <div style="color:#7f8c8d;font-size:11px">tys. PLN (${m.savingsPercentageVsBaseline.toFixed(1)}% kosztu energii)</div>
      </div>

      ${m.eaasEquivalentPaybackYears !== null ? `
      <div style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Równoważny okres zwrotu</div>
        <div style="color:#27ae60;font-size:24px;font-weight:600">${m.eaasEquivalentPaybackYears.toFixed(1)}</div>
        <div style="color:#7f8c8d;font-size:11px">lat (względem CAPEX)</div>
      </div>

      <div style="background:#e8f8f5;padding:16px;border-radius:8px;border-left:4px solid #27ae60">
        <div style="color:#7f8c8d;font-size:12px;margin-bottom:4px">Równoważny ROI</div>
        <div style="color:#27ae60;font-size:24px;font-weight:600">${m.eaasEquivalentROI.toFixed(1)}</div>
        <div style="color:#7f8c8d;font-size:11px">% rocznie</div>
      </div>
      ` : '<div style="color:#e74c3c;padding:16px">Brak oszczędności - EaaS droższy od sieci</div>'}
    </div>

    <div style="padding:16px;background:#f8f9fa;border-radius:8px;border:1px solid #e0e0e0">
      <div style="color:#7f8c8d;font-size:12px;font-weight:600;margin-bottom:8px">Rozbicie kosztów EaaS (rocznych):</div>
      <div style="font-size:13px;line-height:1.8;color:#2c3e50">
        • <strong>Abonament:</strong> ${(m.breakdown.subscriptionCost / 1000).toFixed(1)} tys. PLN<br/>
        • <strong>O&M:</strong> ${(m.breakdown.omCost / 1000).toFixed(1)} tys. PLN<br/>
        • <strong>Ubezpieczenie (${(EAAS_CONFIG.INSURANCE_RATE * 100).toFixed(1)}% CAPEX):</strong> ${(m.breakdown.insuranceCost / 1000).toFixed(1)} tys. PLN<br/>
        • <strong>Suma:</strong> ${(m.breakdown.totalAnnualCost / 1000).toFixed(1)} tys. PLN/rok<br/>
        • <strong>Autokonsumpcja:</strong> ${(m.breakdown.pvSelfConsumedKWh / 1000).toFixed(1)} MWh/rok
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

  let subscriptionData = null;
  try {
    const backendEaas = await fetchEaasMonthlyLog(variant, systemSettings || {}, params);
    console.log('Backend EaaS monthly result received:', backendEaas);
    subscriptionData = {
      annualSubscription: backendEaas.subscription_annual_year1,
      annualSubscriptionPLN: backendEaas.subscription_annual_year1,
      monthlySubscription: backendEaas.subscription_monthly,
      irr: backendEaas.achieved_irr_annual ?? 0,
      duration: systemSettings?.eaasDuration || 10,
      currency: systemSettings?.eaasCurrency || 'PLN',
    };

    const dl = document.getElementById('eaasLogDownload');
    if (dl && backendEaas.log_csv) {
      const blob = new Blob([backendEaas.log_csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      dl.href = url;
      dl.download = `eaas_log_${currentVariant}.csv`;
      dl.style.display = 'inline-block';
    }
  } catch (err) {
    console.error('Backend EaaS solver failed, falling back to local:', err);
    subscriptionData = calculateEaasSubscription(variant.capacity, systemSettings || {}, params);
  }

  console.log('Calculated EaaS subscription:', subscriptionData);

  const currency = subscriptionData.currency || 'PLN';
  document.getElementById('eaasAnnualSub').textContent = subscriptionData.annualSubscription.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  document.getElementById('eaasAnnualSubUnit').textContent = `${currency}/rok`;
  document.getElementById('eaasMonthlySub').textContent = subscriptionData.monthlySubscription.toLocaleString('pl-PL', { maximumFractionDigits: 0 });
  document.getElementById('eaasMonthlySubUnit').textContent = `${currency}/mies`;
  document.getElementById('eaasTargetIRR').textContent = (subscriptionData.irr * 100).toFixed(1);
  document.getElementById('eaasDurationDisplay').textContent = subscriptionData.duration;

  const eaasSubscriptionPLN = subscriptionData.annualSubscriptionPLN;
  const eaasOM = params.opex_per_kwp || (systemSettings?.opexPerKwp || 15);
  const eaasDuration = parseInt(document.getElementById('eaasDuration')?.value) || subscriptionData.duration || 10;

  const centralizedCalc = calculateCentralizedFinancialMetrics(variant, params, {
    subscription: eaasSubscriptionPLN,
    duration: eaasDuration,
    omPerKwp: eaasOM,
  });

  centralizedMetrics[currentVariant] = centralizedCalc;

  console.log('CENTRALIZED METRICS stored:', centralizedCalc);
  console.log('  - CAPEX NPV:', (centralizedCalc.capex.npv / 1000000).toFixed(2), 'mln PLN');
  console.log('  - EaaS NPV:', ((centralizedCalc.eaas?.npv || 0) / 1000000).toFixed(2), 'mln PLN');

  const annualConsumption = consumptionData?.annual_consumption_kwh || 10000000;
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

      // Get EaaS subscription for this variant
      const subscriptionData = calculateEaasSubscription(
        variant.capacity,
        systemSettings || {},
        params
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
        <td>${r.capacity.toLocaleString()}</td>
        <td>${r.autoconsumptionRatio.toFixed(1)}</td>
        <td class="${r.capexNPV >= 0 ? 'positive' : 'negative'}">${(r.capexNPV / 1000000).toFixed(2)}</td>
        <td>${(r.capexIRR * 100).toFixed(1)}</td>
        <td class="${r.eaasNPV >= 0 ? 'positive' : 'negative'}">${(r.eaasNPV / 1000000).toFixed(2)}</td>
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

  let cumulativeNPV = 0;
  let eaasPhaseSavings = 0;
  let ownershipPhaseSavings = 0;

  for (const yearData of eaasCashFlows) {
    const year = yearData.year;
    const autoconsumption = yearData.gridCost / (centralizedCalc.common.totalEnergyPrice * Math.pow(1 + centralizedCalc.common.inflationRate, year - 1));
    const gridCost = yearData.gridCost;
    const eaasCost = yearData.eaasCost;
    const savings = yearData.savings;
    const discountedCF = yearData.discountedCF;
    const phase = yearData.phase;

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

    row.innerHTML = `
      <td>${phaseLabel} ${year}</td>
      <td>${(autoconsumption / 1000).toFixed(1)}</td>
      <td>${(gridCost / 1000).toFixed(0)}</td>
      <td>${(eaasCost / 1000).toFixed(0)}</td>
      <td class="${savingsClass}">${(savings / 1000).toFixed(0)}</td>
      <td class="${savingsClass}">${(discountedCF / 1000).toFixed(0)}</td>
      <td class="${npvClass}">${(cumulativeNPV / 1000000).toFixed(2)}</td>
    `;

    tableBody.appendChild(row);
  }

  // Add EaaS phase summary row
  const eaasSummaryRow = document.createElement('tr');
  eaasSummaryRow.style.background = '#fff3e0';
  eaasSummaryRow.style.fontWeight = '600';
  eaasSummaryRow.style.borderTop = '2px solid #f57c00';

  eaasSummaryRow.innerHTML = `
    <td colspan="4" style="text-align:right;color:#f57c00">📋 Suma oszczędności w fazie EaaS (lata 1-${eaasDuration}):</td>
    <td class="positive" style="color:#f57c00">${(eaasPhaseSavings / 1000).toFixed(0)}</td>
    <td colspan="2" style="text-align:left;font-size:11px;color:#666">&nbsp;tys. PLN</td>
  `;
  tableBody.appendChild(eaasSummaryRow);

  // Add ownership phase summary row
  const ownershipSummaryRow = document.createElement('tr');
  ownershipSummaryRow.style.background = '#e8f5e9';
  ownershipSummaryRow.style.fontWeight = '600';

  ownershipSummaryRow.innerHTML = `
    <td colspan="4" style="text-align:right;color:#4caf50">🏠 Suma oszczędności w fazie własności (lata ${eaasDuration + 1}-${analysisPeriod}):</td>
    <td class="positive" style="color:#4caf50">${(ownershipPhaseSavings / 1000).toFixed(0)}</td>
    <td colspan="2" style="text-align:left;font-size:11px;color:#666">&nbsp;tys. PLN</td>
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
    <td colspan="4" style="text-align:right">💰 SUMA CAŁKOWITA (25 lat) / NPV (${(discountRate * 100).toFixed(0)}%):</td>
    <td class="positive">${(totalSavings / 1000).toFixed(0)}</td>
    <td></td>
    <td class="${npvClass}">${(cumulativeNPV / 1000000).toFixed(2)}</td>
  `;
  tableBody.appendChild(totalSummaryRow);

  console.log('✅ EaaS yearly table generated. EaaS phase:', (eaasPhaseSavings / 1000).toFixed(0), 'tys. PLN, Ownership phase:', (ownershipPhaseSavings / 1000).toFixed(0), 'tys. PLN, NPV:', (cumulativeNPV / 1000000).toFixed(2), 'mln PLN');
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

  const eaasSubscription = parseFloat(document.getElementById('eaasSubscription')?.value) || 800000;
  const eaasOM = parseFloat(document.getElementById('eaasOM')?.value) || 24;
  const degradationRate = params.degradation_rate / 100;
  const analysisPeriod = params.analysis_period;

  const capacityKwp = variant.capacity;
  const autoconsumptionMwh = variant.self_consumed / 1000; // kWh to MWh
  const capex = capacityKwp * getCapexForCapacity(capacityKwp);
  const annualConsumption = consumptionData?.annual_consumption_kwh || 10000000;

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
// === MODULE INITIALIZATION ===
// ============================================================================

// Request shared data from shell on load
function requestSharedData() {
  if (window.parent !== window) {
    console.log('📤 Requesting shared data from shell...');
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  console.log('📨 Economics received message:', event.data.type);

  switch (event.data.type) {
    case 'SHARED_DATA_RESPONSE':
      console.log('✅ Received shared data:', event.data.data);
      if (event.data.data) {
        // Store settings
        if (event.data.data.settings) {
          systemSettings = event.data.data.settings;
          localStorage.setItem('pv_settings', JSON.stringify(systemSettings));
          console.log('💾 Stored settings');
        }

        // Store analysis results
        if (event.data.data.analysisResults) {
          analysisResults = event.data.data.analysisResults;
          localStorage.setItem('pv_analysis_results', JSON.stringify(analysisResults));
          console.log('💾 Stored analysis results');
        }

        // Store consumption data
        if (event.data.data.consumptionData) {
          consumptionData = event.data.data.consumptionData;
          localStorage.setItem('pv_consumption_data', JSON.stringify(consumptionData));
          console.log('💾 Stored consumption data');
        }

        // Store PV config
        if (event.data.data.pvConfig) {
          pvConfig = event.data.data.pvConfig;
          localStorage.setItem('pv_config', JSON.stringify(pvConfig));
          console.log('💾 Stored PV config');
        }

        // Load and display data
        loadStoredData();
      }
      break;

    case 'VARIANT_ADDED':
    case 'VARIANT_UPDATED':
    case 'DATA_AVAILABLE':
    case 'ANALYSIS_RESULTS':
      console.log('🔄 Data update notification, reloading...');
      loadStoredData();
      break;

    case 'SETTINGS_UPDATED':
      console.log('⚙️ Settings updated:', event.data.data);
      systemSettings = event.data.data;
      // Reload data to apply new settings
      loadStoredData();
      break;

    case 'DATA_CLEARED':
      console.log('🧹 Data cleared');
      clearEconomicsData();
      break;
  }
});

// Load data from localStorage
function loadStoredData() {
  console.log('📂 Loading stored data...');

  try {
    // Load system settings
    const storedSettings = localStorage.getItem('pv_settings');
    if (storedSettings) {
      systemSettings = JSON.parse(storedSettings);
      console.log('✅ Loaded system settings:', systemSettings);
    } else {
      console.log('⚠️ No settings in localStorage, will request from shell');
    }

    // Load analysis results
    const storedResults = localStorage.getItem('pv_analysis_results');
    if (storedResults) {
      analysisResults = JSON.parse(storedResults);
      console.log('✅ Loaded analysis results:', Object.keys(analysisResults.variants || {}).length, 'variants');

      // Extract variants
      if (analysisResults.variants) {
        variants = analysisResults.variants;
        populateVariantSelector();
      }
    }

    // Load consumption data
    const storedConsumption = localStorage.getItem('pv_consumption_data');
    if (storedConsumption) {
      consumptionData = JSON.parse(storedConsumption);
      console.log('✅ Loaded consumption data:', consumptionData.annual_consumption_kwh?.toLocaleString(), 'kWh/year');
    }

    // Load PV config
    const storedConfig = localStorage.getItem('pv_config');
    if (storedConfig) {
      pvConfig = JSON.parse(storedConfig);
      console.log('✅ Loaded PV config:', pvConfig.pv_type);
    }

    // If we have data, perform initial analysis
    if (analysisResults && variants && Object.keys(variants).length > 0) {
      console.log('✅ Data loaded successfully, performing initial analysis...');
      performEconomicAnalysis();
    } else {
      console.log('⚠️ No complete data available yet');
      showNoData();
    }

  } catch (error) {
    console.error('❌ Error loading stored data:', error);
    showNoData();
  }
}

// Populate variant selector
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

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 Economics module initializing...');

  // Try to load from localStorage first
  loadStoredData();

  // Request fresh data from shell
  requestSharedData();

  console.log('✅ Economics module initialized');
});

console.log('📦 economics.js fully loaded');
