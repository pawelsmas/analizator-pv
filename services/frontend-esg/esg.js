// ESG Module - Environmental, Social, Governance Dashboard
// Separate module for ESG metrics and Electricity Maps integration

// Store received data
let analysisResults = null;
let pvConfig = null;
let hourlyData = null;
let masterVariant = null;
let masterVariantKey = null;
let systemSettings = null;
let consumptionData = null;

// Electricity Maps data cache
let lastElectricityMapsData = null;

// Chart instances
let carbonFootprintChart = null;

// Default ESG parameters (Poland)
const DEFAULT_ESG_PARAMS = {
  efGrid: 0.658,  // kgCO2e/kWh - Poland grid average
  efSource: 'KOBiZE 2023',
  embodiedCarbonPerKwp: 1000,  // kgCO2e/kWp - mono-Si default
  pvLifetime: 25,  // years
  pvTechnology: 'mono-Si'
};

// ============================================
// NUMBER FORMATTING - European format
// ============================================

/**
 * Format number in European style
 * - Decimal separator: comma (,)
 * - Thousands separator: non-breaking space (\u00A0)
 * @param {number} value - Number to format
 * @param {number} decimals - Number of decimal places (default: 2)
 * @returns {string} Formatted number string
 */
function formatNumber(value, decimals = 2) {
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
function formatWithUnit(value, unit, decimals = 2) {
  return `${formatNumber(value, decimals)} ${unit}`;
}

// Initialize module
document.addEventListener('DOMContentLoaded', () => {
  console.log('ESG Module loaded');

  // Request shared data from shell
  window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');

  // Initialize Carbon Footprint chart with default values
  setTimeout(() => {
    updateCarbonFootprintChart({
      efGrid: DEFAULT_ESG_PARAMS.efGrid,
      pvTechnology: DEFAULT_ESG_PARAMS.pvTechnology
    });
  }, 500);

  // Try to fetch Electricity Maps data on load
  setTimeout(() => {
    tryFetchElectricityMapsData();
  }, 1000);
});

// Listen for messages from shell
window.addEventListener('message', (event) => {
  console.log('ESG Module received message:', event.data?.type);

  switch (event.data?.type) {
    case 'SHARED_DATA_RESPONSE':
    case 'ANALYSIS_RESULTS':
      handleAnalysisData(event.data.data);
      break;
    case 'MASTER_VARIANT_CHANGED':
      masterVariant = event.data.data?.variantData;
      masterVariantKey = event.data.data?.variantKey;
      updateESGDashboard();
      break;
    case 'SETTINGS_UPDATED':
      systemSettings = event.data.data;
      console.log('ESG: Settings received:', systemSettings);
      updateESGDashboard();
      tryFetchElectricityMapsData();
      break;
    case 'DATA_CLEARED':
      clearData();
      break;
    case 'PROJECT_LOADED':
      // Project was loaded - request shared data to refresh
      console.log('📂 ESG: Project loaded, requesting shared data');
      if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
      }
      break;
  }
});

// Handle analysis data from shell
function handleAnalysisData(data) {
  console.log('ESG: Handling analysis data', data);

  // Handle SHARED_DATA_RESPONSE format (data is sharedData directly)
  if (data.analysisResults !== undefined || data.masterVariant !== undefined) {
    analysisResults = data.analysisResults;
    pvConfig = data.pvConfig;
    hourlyData = data.hourlyData;
    masterVariant = data.masterVariant;
    masterVariantKey = data.masterVariantKey;
    consumptionData = data.consumptionData;
    if (data.settings) {
      systemSettings = data.settings;
    }
    console.log('ESG: Loaded from sharedData format', {
      hasAnalysisResults: !!analysisResults,
      hasMasterVariant: !!masterVariant,
      masterVariantKey: masterVariantKey,
      hasConsumptionData: !!consumptionData
    });
  }

  // Handle ANALYSIS_RESULTS format (nested in sharedData)
  if (data.sharedData) {
    analysisResults = data.sharedData.analysisResults || analysisResults;
    pvConfig = data.sharedData.pvConfig || pvConfig;
    hourlyData = data.sharedData.hourlyData || hourlyData;
    masterVariant = data.sharedData.masterVariant || masterVariant;
    masterVariantKey = data.sharedData.masterVariantKey || masterVariantKey;
    consumptionData = data.sharedData.consumptionData || consumptionData;
    if (data.sharedData.settings) {
      systemSettings = data.sharedData.settings;
    }
    console.log('ESG: Loaded from nested sharedData', {
      hasAnalysisResults: !!analysisResults,
      hasMasterVariant: !!masterVariant,
      masterVariantKey: masterVariantKey,
      hasConsumptionData: !!consumptionData
    });
  }

  // Handle direct fullResults format
  if (data.fullResults) {
    analysisResults = data.fullResults;
    pvConfig = data.pvConfig || pvConfig;
    hourlyData = data.hourlyData || hourlyData;
  }

  // Log what we have
  console.log('ESG: Final data state', {
    analysisResults: analysisResults ? Object.keys(analysisResults) : null,
    masterVariant: masterVariant,
    masterVariantKey: masterVariantKey
  });

  // Show content if we have data
  if (analysisResults || masterVariant) {
    document.getElementById('noDataState').classList.remove('active');
    document.getElementById('mainContent').classList.remove('hidden');
    updateESGDashboard();
  }
}

// Clear all data
function clearData() {
  analysisResults = null;
  pvConfig = null;
  hourlyData = null;
  masterVariant = null;
  masterVariantKey = null;
  consumptionData = null;

  document.getElementById('noDataState').classList.add('active');
  document.getElementById('mainContent').classList.add('hidden');
}

// Update ESG Dashboard with calculated metrics
function updateESGDashboard() {
  console.log('🌱 Updating ESG Dashboard...');
  console.log('🌱 masterVariant:', masterVariant);
  console.log('🌱 analysisResults:', analysisResults);

  // Get variant data (prefer master variant)
  let variantData = masterVariant;

  // If no master variant, try to get from analysisResults
  if (!variantData && analysisResults) {
    // Try key_variants first
    if (analysisResults.key_variants && analysisResults.key_variants.length > 0) {
      variantData = analysisResults.key_variants[0];
      console.log('🌱 Using first key_variant:', variantData);
    }
    // Try variants object
    else if (analysisResults.variants) {
      variantData = Object.values(analysisResults.variants)[0];
      console.log('🌱 Using first variant from variants object:', variantData);
    }
    // Try scenarios
    else if (analysisResults.scenarios && analysisResults.scenarios.length > 0) {
      variantData = analysisResults.scenarios[0];
      console.log('🌱 Using first scenario:', variantData);
    }
  }

  if (!variantData) {
    console.warn('⚠️ No variant data for ESG calculation');
    // Show default values if we have any analysis results
    if (analysisResults) {
      console.log('🌱 analysisResults keys:', Object.keys(analysisResults));
    }
    // Still show Carbon Footprint chart with default values
    updateCarbonFootprintChart({
      efGrid: DEFAULT_ESG_PARAMS.efGrid,
      pvTechnology: DEFAULT_ESG_PARAMS.pvTechnology
    });
    return;
  }

  console.log('🌱 Using variantData:', variantData);
  console.log('🌱 variantData FULL:', JSON.stringify(variantData, null, 2));

  // Extract key values - handle various data structures
  const annualProductionKwh = variantData.production ||  // from key_variants
                              variantData.totalProduction_kWh ||
                              variantData.summary?.total_production_kWh ||
                              variantData.annual_production_kwh ||
                              variantData.production_kwh || 0;

  const pvCapacityKwp = variantData.capacity ||  // from key_variants (in kW)
                        variantData.capacity_kwp ||
                        pvConfig?.capacity_kWp ||
                        variantData.systemCapacity_kWp || 10;

  const selfConsumptionKwh = variantData.self_consumed ||  // from comparison module (kWh)
                              variantData.self_consumption ||  // from key_variants
                              variantData.selfConsumption_kWh ||
                              variantData.summary?.self_consumption_kWh || 0;

  // Calculate self consumption from autoconsumption ratio if needed
  const autoconsumptionRatio = variantData.auto_consumption_pct ||  // from comparison module (%)
                               variantData.autoconsumption ||
                               variantData.autoconsumption_ratio || 0;
  const calculatedSelfConsumption = selfConsumptionKwh || (annualProductionKwh * autoconsumptionRatio / 100);

  const totalConsumptionKwh = consumptionData?.annual_consumption_kwh ||  // from consumption module (kWh)
                               (consumptionData?.total_consumption_gwh * 1000000) ||  // from consumption (GWh -> kWh)
                               analysisResults?.totalConsumption_kWh ||
                               analysisResults?.total_consumption_kwh ||
                               variantData.consumption_kWh ||
                               variantData.total_consumption || 50000;

  console.log('🌱 ESG input values:', {
    annualProductionKwh,
    pvCapacityKwp,
    selfConsumptionKwh: calculatedSelfConsumption,
    totalConsumptionKwh,
    autoconsumptionRatio,
    // Debug: raw values from sources
    rawSelfConsumed: variantData.self_consumed,
    rawSelfConsumption: variantData.self_consumption,
    rawAutoConsumptionPct: variantData.auto_consumption_pct,
    hasConsumptionData: !!consumptionData,
    consumptionDataAnnual: consumptionData?.annual_consumption_kwh
  });

  // Get ESG parameters from settings or defaults
  const esgParams = getESGParameters();

  // Calculate ESG metrics
  const metrics = calculateESGMetrics({
    annualProductionKwh,
    pvCapacityKwp,
    selfConsumptionKwh: calculatedSelfConsumption,
    totalConsumptionKwh,
    ...esgParams
  });

  console.log('📊 ESG metrics calculated:', metrics);

  // Update UI
  updateESGUI(metrics);
}

// Get ESG parameters from settings or defaults
function getESGParameters() {
  let params = { ...DEFAULT_ESG_PARAMS };

  if (systemSettings?.esg) {
    const esg = systemSettings.esg;

    if (esg.gridEmissionFactor) {
      params.efGrid = parseFloat(esg.gridEmissionFactor);
    }
    if (esg.emissionFactorSource) {
      params.efSource = esg.emissionFactorSource;
    }
    if (esg.embodiedCarbonPerKwp) {
      params.embodiedCarbonPerKwp = parseFloat(esg.embodiedCarbonPerKwp);
    }
    if (esg.pvTechnology) {
      params.pvTechnology = esg.pvTechnology;
    }
    if (esg.pvLifetime) {
      params.pvLifetime = parseInt(esg.pvLifetime);
    }
  }

  return params;
}

// Calculate ESG metrics
function calculateESGMetrics(params) {
  const {
    annualProductionKwh,
    pvCapacityKwp,
    selfConsumptionKwh,
    totalConsumptionKwh,
    efGrid,
    efSource,
    embodiedCarbonPerKwp,
    pvLifetime,
    pvTechnology
  } = params;

  // CO2 avoided per year - based on REDUCED GRID IMPORT (self-consumption)
  // This is the correct methodology: only energy that displaces grid import counts
  // Export to grid may avoid emissions elsewhere but doesn't reduce facility's Scope 2
  const co2AvoidedYearKg = selfConsumptionKwh * efGrid;
  const co2AvoidedYearTon = co2AvoidedYearKg / 1000;

  // Alternative calculation: total production (for reference/transparency)
  const co2AvoidedProductionBasedKg = annualProductionKwh * efGrid;
  const co2AvoidedProductionBasedTon = co2AvoidedProductionBasedKg / 1000;

  // CO2 avoided lifetime
  const co2AvoidedLifetimeTon = co2AvoidedYearTon * pvLifetime;
  const co2AvoidedLifetimeProductionBasedTon = co2AvoidedProductionBasedTon * pvLifetime;

  // Embodied carbon
  const embodiedCarbonTotalKg = pvCapacityKwp * embodiedCarbonPerKwp;
  const embodiedCarbonTotalTon = embodiedCarbonTotalKg / 1000;

  // Carbon payback (years to offset embodied carbon)
  const carbonPaybackYears = co2AvoidedYearKg > 0 ?
    embodiedCarbonTotalKg / co2AvoidedYearKg : 0;

  // Net CO2 benefit over lifetime
  const netCo2BenefitTon = co2AvoidedLifetimeTon - embodiedCarbonTotalTon;

  // Share of renewable energy
  const shareRES = totalConsumptionKwh > 0 ?
    (selfConsumptionKwh / totalConsumptionKwh) * 100 : 0;

  // Scope 2 emissions
  const co2BeforeTon = (totalConsumptionKwh * efGrid) / 1000;
  const gridConsumptionAfter = totalConsumptionKwh - selfConsumptionKwh;
  const co2AfterTon = (gridConsumptionAfter * efGrid) / 1000;
  const co2ReductionPct = co2BeforeTon > 0 ?
    ((co2BeforeTon - co2AfterTon) / co2BeforeTon) * 100 : 0;

  // Grid export and related avoided emissions (for transparency - not counted in Scope 2)
  const gridExportKwh = annualProductionKwh - selfConsumptionKwh;
  const co2AvoidedExportKg = gridExportKwh * efGrid;
  const co2AvoidedExportTon = co2AvoidedExportKg / 1000;

  return {
    // Primary metrics (import-based methodology - correct for Scope 2)
    co2ReductionYear: co2AvoidedYearTon,
    co2ReductionLifetime: co2AvoidedLifetimeTon,
    shareRES: shareRES,
    carbonPayback: carbonPaybackYears,
    co2Before: co2BeforeTon,
    co2After: co2AfterTon,
    co2ReductionPct: co2ReductionPct,
    embodiedCarbon: embodiedCarbonTotalTon,
    embodiedCarbonPerKwp: embodiedCarbonPerKwp,
    netCo2: netCo2BenefitTon,
    pvTechnology: pvTechnology,
    efGrid: efGrid,
    efSource: efSource,
    pvCapacityKwp: pvCapacityKwp,
    pvLifetime: pvLifetime,
    // Transparency metrics (production-based for reference)
    co2ReductionYearProductionBased: co2AvoidedProductionBasedTon,
    co2ReductionLifetimeProductionBased: co2AvoidedLifetimeProductionBasedTon,
    // Grid export contribution (avoided emissions outside facility)
    gridExportKwh: gridExportKwh,
    co2AvoidedExport: co2AvoidedExportTon,
    // Self-consumption details
    selfConsumptionKwh: selfConsumptionKwh,
    annualProductionKwh: annualProductionKwh
  };
}

// Update ESG UI elements
function updateESGUI(metrics) {
  console.log('🎯 updateESGUI called with metrics:', JSON.stringify(metrics, null, 2));

  // Main KPIs - European format
  const co2YearFormatted = formatNumber(metrics.co2ReductionYear, 2);
  console.log('🎯 CO2 Year value:', metrics.co2ReductionYear, '-> formatted:', co2YearFormatted);

  setElementValue('esgCo2ReductionYear', co2YearFormatted);
  setElementValue('esgCo2ReductionLifetime', formatNumber(metrics.co2ReductionLifetime, 1));
  setElementValue('esgShareRes', formatNumber(metrics.shareRES, 1));
  setElementValue('esgCarbonPayback', formatNumber(metrics.carbonPayback, 1));

  // Scope 2 emissions
  setElementValue('esgCo2Before', formatWithUnit(metrics.co2Before, 'tCO2e/rok', 2));
  setElementValue('esgCo2After', formatWithUnit(metrics.co2After, 'tCO2e/rok', 2));
  setElementValue('esgCo2ReductionPct', `-${formatNumber(metrics.co2ReductionPct, 1)}%`);

  // CO2 Breakdown (transparency section)
  setElementValue('esgSelfConsumptionKwh', formatWithUnit((metrics.selfConsumptionKwh || 0) / 1000, 'MWh/rok', 1));
  setElementValue('esgCo2SelfConsumption', formatWithUnit(metrics.co2ReductionYear, 'tCO2e/rok', 2));
  setElementValue('esgGridExportKwh', formatWithUnit((metrics.gridExportKwh || 0) / 1000, 'MWh/rok', 1));
  setElementValue('esgCo2Export', formatWithUnit(metrics.co2AvoidedExport || 0, 'tCO2e/rok', 2));
  setElementValue('esgTotalProductionKwh', formatWithUnit((metrics.annualProductionKwh || 0) / 1000, 'MWh/rok', 1));
  setElementValue('esgCo2ProductionBased', formatWithUnit(metrics.co2ReductionYearProductionBased || 0, 'tCO2e/rok', 2));

  // CO2 Savings for Environment (in tons) - based on total production
  // This represents the actual CO2 that won't be emitted due to PV generation
  updateCo2SavingsSection(metrics);

  // Embodied carbon
  setElementValue('esgPvTechnology', getTechnologyLabel(metrics.pvTechnology));
  setElementValue('esgEmbodiedCarbon', formatWithUnit(metrics.embodiedCarbon, 'tCO2e', 2));
  setElementValue('esgEmbodiedPerKwp', formatWithUnit(metrics.embodiedCarbonPerKwp, 'kgCO2e/kWp', 0));
  setElementValue('esgNetCo2', `${formatNumber(metrics.netCo2, 1)} tCO2e (korzysc netto)`);

  // Technical parameters
  setElementValue('esgEfGrid', formatWithUnit(metrics.efGrid, 'kgCO2e/kWh', 3));
  setElementValue('esgEfSource', metrics.efSource);
  setElementValue('esgEmbodiedSource', 'IPCC 2021 / Fraunhofer ISE');
  setElementValue('esgPvCapacity', formatWithUnit(metrics.pvCapacityKwp, 'kWp', 1));

  // EU Taxonomy badge styling
  const taxonomyBadge = document.getElementById('esgTaxonomyBadge');
  if (taxonomyBadge) {
    taxonomyBadge.classList.add('compliant');
  }

  // Update Carbon Footprint chart
  updateCarbonFootprintChart(metrics);

  // Initialize Carbon Clock with metrics
  initCarbonClock(metrics);

  console.log('✅ ESG Dashboard updated');
}

// Update CO2 Savings section with environmental impact metrics
function updateCo2SavingsSection(metrics) {
  // CO2 savings based on total production (environmental perspective)
  // Formula: annual_production_kWh * (grid_EF - PV_LCA_EF) / 1000 = tons CO2/year
  const gridEfKgPerKwh = metrics.efGrid || 0.658; // kgCO2/kWh
  const pvTech = metrics.pvTechnology || 'mono-Si';
  const pvLcaGPerKwh = PV_LCA_EMISSIONS[pvTech] || PV_LCA_EMISSIONS['default']; // gCO2/kWh
  const pvLcaKgPerKwh = pvLcaGPerKwh / 1000; // convert to kgCO2/kWh

  const annualProductionKwh = metrics.annualProductionKwh || 0;
  const pvLifetime = metrics.pvLifetime || 25;

  // Net CO2 savings per kWh (grid emissions minus PV lifecycle emissions)
  const netSavingsPerKwh = gridEfKgPerKwh - pvLcaKgPerKwh; // kgCO2/kWh

  // Annual CO2 savings in tons
  const co2SavingsYearTons = (annualProductionKwh * netSavingsPerKwh) / 1000;

  // Lifetime CO2 savings in tons
  const co2SavingsLifetimeTons = co2SavingsYearTons * pvLifetime;

  // Car equivalent: average car emits ~120 gCO2/km
  // How many km would emit the same CO2 as we're saving?
  const carEmissionsGPerKm = 120;
  const carEquivalentKm = (co2SavingsYearTons * 1000 * 1000) / carEmissionsGPerKm; // convert tons to g

  // Tree equivalent: average deciduous tree absorbs ~22 kg CO2/year
  const treeAbsorptionKgPerYear = 22;
  const treeEquivalent = (co2SavingsYearTons * 1000) / treeAbsorptionKgPerYear;

  console.log('🌳 CO2 Savings calculation:', {
    annualProductionKwh,
    gridEfKgPerKwh,
    pvLcaKgPerKwh,
    netSavingsPerKwh,
    co2SavingsYearTons,
    co2SavingsLifetimeTons,
    carEquivalentKm,
    treeEquivalent
  });

  // Update UI elements
  setElementValue('esgCo2SavingsYearTons', formatNumber(co2SavingsYearTons, 1));
  setElementValue('esgCo2SavingsLifetimeTons', formatNumber(co2SavingsLifetimeTons, 0));
  setElementValue('esgCarEquivalent', formatNumber(carEquivalentKm, 0));
  setElementValue('esgTreeEquivalent', formatNumber(treeEquivalent, 0));
}

// Helper: Set element value safely
function setElementValue(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value || '-';
  }
}

// Get technology label
function getTechnologyLabel(tech) {
  const labels = {
    'mono-Si': 'Monokrystaliczny Si',
    'poly-Si': 'Polikrystaliczny Si',
    'thin-film-CdTe': 'Cienkowarstwowy CdTe',
    'thin-film-CIGS': 'Cienkowarstwowy CIGS'
  };
  return labels[tech] || tech || 'Monokrystaliczny Si';
}

// ============================================
// ELECTRICITY MAPS INTEGRATION
// ============================================

// Try to fetch Electricity Maps data
async function tryFetchElectricityMapsData() {
  console.log('🌐 Trying to fetch Electricity Maps data...');

  // Get API key from settings
  const apiKey = systemSettings?.esg?.electricityMapsApiKey;

  if (!apiKey) {
    console.log('No Electricity Maps API key configured');
    return;
  }

  const zone = systemSettings?.esg?.electricityMapsZone || 'PL';
  const emissionType = systemSettings?.esg?.electricityMapsEmissionType || 'lifecycle';

  try {
    // Fetch all three endpoints in parallel
    const [carbonIntensityRes, renewableRes, fossilCIRes] = await Promise.all([
      fetchElectricityMapsEndpoint(apiKey, `/v3/carbon-intensity/latest?zone=${zone}&emissionFactorType=${emissionType}`),
      fetchElectricityMapsEndpoint(apiKey, `/v3/renewable-percentage-level/latest?zone=${zone}`),
      fetchElectricityMapsEndpoint(apiKey, `/v3/carbon-intensity-fossil-only/latest?zone=${zone}&emissionFactorType=${emissionType}`)
    ]);

    // Process results
    lastElectricityMapsData = {
      carbonIntensity: carbonIntensityRes?.carbonIntensity || null,
      renewablePercentage: renewableRes?.renewablePercentage || null,
      fossilCarbonIntensity: fossilCIRes?.carbonIntensity || null,
      zone: zone,
      timestamp: carbonIntensityRes?.datetime || new Date().toISOString()
    };

    console.log('✅ Electricity Maps data fetched:', lastElectricityMapsData);

    // Update real-time UI
    updateRealTimeUI(lastElectricityMapsData);

  } catch (error) {
    console.error('Error fetching Electricity Maps data:', error);
  }
}

// Fetch single Electricity Maps endpoint
async function fetchElectricityMapsEndpoint(apiKey, endpoint) {
  const baseUrl = 'https://api.electricitymaps.com';

  try {
    const response = await fetch(baseUrl + endpoint, {
      method: 'GET',
      headers: {
        'auth-token': apiKey,
        'Accept': 'application/json'
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`Error fetching ${endpoint}:`, error);
    return null;
  }
}

// Update real-time UI with Electricity Maps data
function updateRealTimeUI(data) {
  if (!data) return;

  const section = document.getElementById('realTimeSection');
  if (section) {
    section.style.display = 'block';
  }

  // Carbon Intensity
  const ciEl = document.getElementById('realTimeCarbonIntensity');
  if (ciEl && data.carbonIntensity !== null) {
    ciEl.textContent = Math.round(data.carbonIntensity);
    ciEl.className = 'stat-value ' + getCarbonIntensityClass(data.carbonIntensity);
  }

  // Renewable Percentage
  const renewEl = document.getElementById('realTimeRenewable');
  if (renewEl && data.renewablePercentage !== null) {
    renewEl.textContent = data.renewablePercentage.toFixed(1);
    renewEl.className = 'stat-value ' + getRenewableClass(data.renewablePercentage);
  }

  // Fossil Carbon Intensity
  const fossilEl = document.getElementById('realTimeFossilCI');
  if (fossilEl && data.fossilCarbonIntensity !== null) {
    fossilEl.textContent = Math.round(data.fossilCarbonIntensity);
  }

  // Timestamp
  const tsEl = document.getElementById('realTimeTimestamp');
  if (tsEl && data.timestamp) {
    const date = new Date(data.timestamp);
    tsEl.textContent = `Aktualizacja: ${date.toLocaleString('pl-PL')}`;
  }

  // Zone
  const zoneEl = document.getElementById('realTimeZone');
  if (zoneEl) {
    zoneEl.textContent = `Strefa: ${data.zone}`;
  }
}

// Get CSS class based on carbon intensity value
function getCarbonIntensityClass(value) {
  if (value < 200) return 'value-green';
  if (value < 400) return 'value-yellow';
  return 'value-red';
}

// Get CSS class based on renewable percentage
function getRenewableClass(value) {
  if (value > 50) return 'value-green';
  if (value > 25) return 'value-yellow';
  return 'value-red';
}

// Refresh Electricity Maps data (button handler)
function refreshElectricityMapsData() {
  console.log('🔄 Refreshing Electricity Maps data...');
  tryFetchElectricityMapsData();
}

// Refresh all ESG data
function refreshESGData() {
  console.log('🔄 Refreshing ESG data...');
  window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  tryFetchElectricityMapsData();
  updateESGDashboard();
}

// Export ESG Report
function exportESGReport() {
  console.log('📊 Exporting ESG report...');

  // Get current metrics
  const variantData = masterVariant || (analysisResults?.variants ? Object.values(analysisResults.variants)[0] : null);

  if (!variantData) {
    alert('Brak danych do eksportu');
    return;
  }

  const esgParams = getESGParameters();
  const annualProductionKwh = variantData.totalProduction_kWh || variantData.summary?.total_production_kWh || 0;
  const pvCapacityKwp = variantData.capacity_kwp || pvConfig?.capacity_kWp || 10;
  const selfConsumptionKwh = variantData.selfConsumption_kWh || variantData.summary?.self_consumption_kWh || 0;
  const totalConsumptionKwh = analysisResults?.totalConsumption_kWh || 50000;

  const metrics = calculateESGMetrics({
    annualProductionKwh,
    pvCapacityKwp,
    selfConsumptionKwh,
    totalConsumptionKwh,
    ...esgParams
  });

  // Create CSV content
  const csvContent = [
    'Raport ESG - Pagra ENERGY Studio',
    `Data: ${new Date().toLocaleDateString('pl-PL')}`,
    '',
    'KLUCZOWE WSKAZNIKI ESG',
    `Redukcja CO2 Rocznie;${metrics.co2ReductionYear?.toFixed(2)};tCO2e/rok`,
    `Redukcja CO2 Lifetime;${metrics.co2ReductionLifetime?.toFixed(1)};tCO2e`,
    `Udzial OZE;${metrics.shareRES?.toFixed(1)};%`,
    `Carbon Payback;${metrics.carbonPayback?.toFixed(1)};lat`,
    '',
    'EMISJE SCOPE 2',
    `CO2 przed PV;${metrics.co2Before?.toFixed(2)};tCO2e/rok`,
    `CO2 po PV;${metrics.co2After?.toFixed(2)};tCO2e/rok`,
    `Redukcja;${metrics.co2ReductionPct?.toFixed(1)};%`,
    '',
    'EMBODIED CARBON',
    `Technologia PV;${metrics.pvTechnology}`,
    `Embodied Carbon;${metrics.embodiedCarbon?.toFixed(2)};tCO2e`,
    `Net CO2 Benefit;${metrics.netCo2?.toFixed(1)};tCO2e`,
    '',
    'PARAMETRY',
    `EF Grid;${metrics.efGrid?.toFixed(3)};kgCO2e/kWh`,
    `Zrodlo EF;${metrics.efSource}`,
    `Moc PV;${metrics.pvCapacityKwp?.toFixed(1)};kWp`
  ].join('\n');

  // Download file
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `raport_esg_${new Date().toISOString().slice(0,10)}.csv`;
  link.click();

  console.log('✅ ESG report exported');
}

// ============================================
// CARBON FOOTPRINT VISUALIZATION
// ============================================

// LCA emission factors for PV technologies (gCO2e/kWh over lifetime)
const PV_LCA_EMISSIONS = {
  'mono-Si': 40,        // Monokrystaliczny Si
  'poly-Si': 45,        // Polikrystaliczny Si
  'thin-film-CdTe': 20, // Cienkowarstwowy CdTe
  'thin-film-CIGS': 25, // Cienkowarstwowy CIGS
  'default': 40         // Default mono-Si
};

// ============================================
// CARBON CLOCK - Real-time CO2 Savings Animation
// Uses actual hourly production data from analysis
// ============================================

// Carbon Clock state
let carbonClockInterval = null;
let carbonClockIsRunning = false;
let carbonClockStartTime = null;
let carbonClockCurrentHourIndex = 0;  // Current hour in the simulation (0 to 8759)
let carbonClockSpeed = 'fast'; // realtime, minute, fast, ultrafast, superfast, warp

// Hourly data from analysis (real production values)
let clockHourlyProduction = [];  // kWh per hour
let clockHourlyTimestamps = [];  // ISO timestamps
let clockTotalHours = 0;

// CO2 calculation parameters
let clockNetCo2PerKwh = 0;  // kg CO2 saved per kWh (grid EF - PV LCA)
let clockAnnualCo2Kg = 0;   // Total annual CO2 savings in kg
let treesPerYear = 0;
let carKmPerYear = 0;

// Cumulative counters
let clockCumulativeCo2Kg = 0;

/**
 * Initialize Carbon Clock with actual hourly data from analysis
 */
function initCarbonClock(metrics) {
  if (!metrics || !metrics.annualProductionKwh) {
    console.log('Carbon Clock: No metrics available');
    return;
  }

  // Calculate CO2 per kWh
  const gridEfKgPerKwh = metrics.efGrid || 0.658;
  const pvTech = metrics.pvTechnology || 'mono-Si';
  const pvLcaGPerKwh = PV_LCA_EMISSIONS[pvTech] || PV_LCA_EMISSIONS['default'];
  const pvLcaKgPerKwh = pvLcaGPerKwh / 1000;
  clockNetCo2PerKwh = gridEfKgPerKwh - pvLcaKgPerKwh;

  // Annual CO2 savings
  clockAnnualCo2Kg = metrics.annualProductionKwh * clockNetCo2PerKwh;

  // Tree equivalent (22 kg CO2/year per tree)
  treesPerYear = clockAnnualCo2Kg / 22;

  // Car km equivalent (120 g CO2/km)
  carKmPerYear = (clockAnnualCo2Kg * 1000) / 120;

  // Try to get hourly production data from shared data
  loadHourlyProductionData();

  console.log('Carbon Clock initialized:', {
    clockNetCo2PerKwh,
    clockAnnualCo2Kg,
    treesPerYear,
    carKmPerYear,
    hourlyDataPoints: clockTotalHours
  });

  // Reset display with first timestamp
  resetCarbonClockDisplay();
}

/**
 * Load hourly production data from analysis results
 */
function loadHourlyProductionData() {
  console.log('🕐 Carbon Clock: Loading hourly data...');
  console.log('  - hourlyData available:', !!hourlyData);
  console.log('  - hourlyData.timestamps:', hourlyData?.timestamps?.length || 0);
  console.log('  - hourlyData.values:', hourlyData?.values?.length || 0);
  console.log('  - masterVariant:', !!masterVariant);
  console.log('  - masterVariant.hourlyProduction:', masterVariant?.hourlyProduction?.length || 0);

  // Try to get hourly data from masterVariant or analysisResults
  let production = null;
  let timestamps = null;

  // Check masterVariant for hourly production
  if (masterVariant?.hourlyProduction) {
    production = masterVariant.hourlyProduction;
    console.log('Carbon Clock: Using hourlyProduction from masterVariant');
  }

  // Check hourlyData for timestamps
  if (hourlyData?.timestamps && hourlyData.timestamps.length > 0) {
    timestamps = hourlyData.timestamps;
    clockHourlyTimestamps = [...timestamps];  // Copy array
    console.log('Carbon Clock: Loaded', timestamps.length, 'timestamps from hourlyData');
    console.log('  First timestamp:', timestamps[0]);
    console.log('  Last timestamp:', timestamps[timestamps.length - 1]);
  }

  // If no hourly production but we have hourlyData values, estimate production distribution
  if (!production && hourlyData?.values && masterVariant) {
    const annualProduction = masterVariant.production || masterVariant.totalProduction_kWh || 0;
    const hours = hourlyData.values.length;

    if (annualProduction > 0 && hours > 0) {
      production = estimateHourlyProduction(timestamps || [], annualProduction, hours);
      console.log('Carbon Clock: Generated estimated hourly production for', hours, 'hours');
    }
  }

  // Store production data
  if (production && production.length > 0) {
    clockHourlyProduction = production;
    clockTotalHours = production.length;
  } else {
    // If no production data, at least set total hours from timestamps
    clockTotalHours = clockHourlyTimestamps.length || 8760;
  }

  // If still no timestamps, generate them starting from Jan 1 of current year
  if (clockHourlyTimestamps.length === 0) {
    const year = new Date().getFullYear();
    clockHourlyTimestamps = [];
    for (let h = 0; h < clockTotalHours; h++) {
      const date = new Date(year, 0, 1);
      date.setHours(h);
      clockHourlyTimestamps.push(date.toISOString());
    }
    console.log('Carbon Clock: Generated', clockTotalHours, 'default timestamps for year', year);
  }

  console.log('🕐 Carbon Clock data loaded:', {
    productionHours: clockHourlyProduction.length,
    timestampHours: clockHourlyTimestamps.length,
    totalHours: clockTotalHours
  });
}

/**
 * Estimate hourly production based on typical solar profile
 * Fallback when no real hourly production data is available
 */
function estimateHourlyProduction(timestamps, annualProductionKwh, hours) {
  const production = [];
  let totalWeight = 0;

  // Calculate weights for each hour based on typical solar profile
  for (let h = 0; h < hours; h++) {
    let hourOfDay = h % 24;
    let dayOfYear = Math.floor(h / 24);

    // Simple solar profile: production between 6:00-20:00, peak at 12:00
    let weight = 0;
    if (hourOfDay >= 6 && hourOfDay <= 20) {
      // Bell curve centered at 13:00
      const peakHour = 13;
      const spread = 4;
      weight = Math.exp(-Math.pow(hourOfDay - peakHour, 2) / (2 * spread * spread));

      // Seasonal variation: more production in summer (day ~172 = June 21)
      const summerPeak = 172;
      const seasonalFactor = 0.5 + 0.5 * Math.cos((dayOfYear - summerPeak) * 2 * Math.PI / 365);
      weight *= (0.5 + 0.5 * seasonalFactor);
    }

    production.push(weight);
    totalWeight += weight;
  }

  // Normalize to match annual production
  const factor = annualProductionKwh / totalWeight;
  return production.map(w => w * factor);
}

/**
 * Toggle Carbon Clock play/pause
 */
function toggleCarbonClock() {
  if (carbonClockIsRunning) {
    stopCarbonClock();
  } else {
    startCarbonClock();
  }
}

/**
 * Start Carbon Clock animation
 */
function startCarbonClock() {
  if (clockTotalHours === 0 && clockAnnualCo2Kg <= 0) {
    console.warn('Carbon Clock: No data to animate');
    return;
  }

  carbonClockIsRunning = true;
  carbonClockStartTime = Date.now();

  // Update button state
  const btn = document.getElementById('clockPlayBtn');
  const icon = document.getElementById('clockPlayIcon');
  const text = document.getElementById('clockPlayText');
  if (btn) btn.classList.add('playing');
  if (icon) icon.textContent = '⏸️';
  if (text) text.textContent = 'Pauza';

  // Start animation interval (update every 100ms)
  carbonClockInterval = setInterval(() => {
    const elapsedMs = Date.now() - carbonClockStartTime;
    const speedMultiplier = getClockSpeedMultiplier();

    // Calculate how many simulated hours have passed
    // Speed multiplier converts real seconds to simulated seconds
    const simulatedSeconds = (elapsedMs / 1000) * speedMultiplier;
    const simulatedHours = simulatedSeconds / 3600;

    // Update display with current hour index
    const currentHourIndex = Math.floor(simulatedHours) % Math.max(clockTotalHours, 8760);
    updateCarbonClockDisplay(currentHourIndex, simulatedSeconds);
  }, 100);

  console.log('Carbon Clock started with speed:', carbonClockSpeed, 'hours:', clockTotalHours);
}

/**
 * Stop Carbon Clock animation
 */
function stopCarbonClock() {
  carbonClockIsRunning = false;

  if (carbonClockInterval) {
    clearInterval(carbonClockInterval);
    carbonClockInterval = null;
  }

  // Update button state
  const btn = document.getElementById('clockPlayBtn');
  const icon = document.getElementById('clockPlayIcon');
  const text = document.getElementById('clockPlayText');
  if (btn) btn.classList.remove('playing');
  if (icon) icon.textContent = '▶️';
  if (text) text.textContent = 'Start';

  console.log('Carbon Clock stopped');
}

/**
 * Reset Carbon Clock to zero
 */
function resetCarbonClock() {
  stopCarbonClock();
  carbonClockSimulatedSeconds = 0;
  carbonClockStartTime = null;
  resetCarbonClockDisplay();
  console.log('Carbon Clock reset');
}

/**
 * Reset Carbon Clock display to initial state
 */
function resetCarbonClockDisplay() {
  clockCumulativeCo2Kg = 0;
  clockCurrentHourIndex = 0;

  setElementValue('clockCo2Value', '0,00');
  setElementValue('clockTreeCount', '0');
  setElementValue('clockTreeFraction', ',0');
  setElementValue('clockCarKm', '0');
  setElementValue('clockYearCo2', '0,0');
  setElementValue('clockCurrentTime', '00:00');

  // Show first date from data
  if (clockHourlyTimestamps.length > 0) {
    const firstDate = getCalendarDateFromHourIndex(0);
    setElementValue('clockCurrentDate', firstDate);
  } else {
    setElementValue('clockCurrentDate', 'Dzień 1 z 365');
  }

  // Reset progress bars
  const ringProgress = document.getElementById('clockRingProgress');
  if (ringProgress) ringProgress.style.strokeDashoffset = '339.292';

  const treeProgress = document.getElementById('clockTreeProgress');
  if (treeProgress) treeProgress.style.width = '0%';

  const carProgress = document.getElementById('clockCarProgress');
  if (carProgress) carProgress.style.width = '0%';

  const yearProgress = document.getElementById('clockYearProgress');
  if (yearProgress) yearProgress.style.width = '0%';
}

/**
 * Get calendar date string from hour index using actual timestamps
 */
function getCalendarDateFromHourIndex(hourIndex) {
  // Polish month names
  const months = [
    'stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca',
    'lipca', 'sierpnia', 'wrzesnia', 'pazdziernika', 'listopada', 'grudnia'
  ];

  let date;
  const dayNumber = Math.floor(hourIndex / 24) + 1;  // Day 1, 2, 3...

  // Use actual timestamp if available
  if (clockHourlyTimestamps.length > 0 && hourIndex < clockHourlyTimestamps.length) {
    date = new Date(clockHourlyTimestamps[hourIndex]);
    const day = date.getDate();
    const monthIndex = date.getMonth();
    const year = date.getFullYear();
    return `Dzień ${dayNumber}: ${day} ${months[monthIndex]} ${year}`;
  } else if (clockHourlyTimestamps.length > 0) {
    // Use first timestamp as base and add days
    const baseDate = new Date(clockHourlyTimestamps[0]);
    date = new Date(baseDate);
    date.setHours(date.getHours() + hourIndex);
    const day = date.getDate();
    const monthIndex = date.getMonth();
    const year = date.getFullYear();
    return `Dzień ${dayNumber}: ${day} ${months[monthIndex]} ${year}`;
  } else {
    // Fallback: just show day number
    return `Dzień ${dayNumber} z 365`;
  }
}

/**
 * Update Carbon Clock display with actual hourly data
 * @param {number} hourIndex - Current hour index in the data (0 to totalHours-1)
 * @param {number} simulatedSeconds - Total simulated seconds (for sub-hour animation)
 */
function updateCarbonClockDisplay(hourIndex, simulatedSeconds) {
  // Get current hour of day for time display
  const hourOfDay = hourIndex % 24;
  const minuteOfHour = Math.floor((simulatedSeconds % 3600) / 60) % 60;

  // Update time display (HH:MM format)
  setElementValue('clockCurrentTime',
    `${hourOfDay.toString().padStart(2, '0')}:${minuteOfHour.toString().padStart(2, '0')}`
  );

  // Update calendar date from actual timestamps
  const dateStr = getCalendarDateFromHourIndex(hourIndex);

  // Force update the date element directly (ensure it works)
  const dateEl = document.getElementById('clockCurrentDate');
  if (dateEl) {
    dateEl.textContent = dateStr;
  }

  // Calculate cumulative CO2 saved up to this hour
  let cumulativeCo2Kg = 0;
  let todayCo2Kg = 0;
  const startOfDayHour = Math.floor(hourIndex / 24) * 24;

  if (clockHourlyProduction.length > 0) {
    // Use actual hourly production data
    for (let h = 0; h <= hourIndex && h < clockHourlyProduction.length; h++) {
      const hourCo2 = clockHourlyProduction[h] * clockNetCo2PerKwh;
      cumulativeCo2Kg += hourCo2;

      if (h >= startOfDayHour) {
        todayCo2Kg += hourCo2;
      }
    }

    // Add partial hour (interpolation for smooth animation)
    if (hourIndex < clockHourlyProduction.length) {
      const fractionOfHour = (simulatedSeconds % 3600) / 3600;
      const currentHourCo2 = clockHourlyProduction[hourIndex] * clockNetCo2PerKwh;
      todayCo2Kg += currentHourCo2 * fractionOfHour;
      cumulativeCo2Kg += currentHourCo2 * fractionOfHour;
    }
  } else {
    // Fallback: use average rate
    const co2PerSecond = clockAnnualCo2Kg / (365.25 * 24 * 3600);
    cumulativeCo2Kg = simulatedSeconds * co2PerSecond;
    todayCo2Kg = (simulatedSeconds % 86400) * co2PerSecond;
  }

  // Update main CO2 display (daily)
  setElementValue('clockCo2Value', formatNumber(todayCo2Kg, 2));

  // Update ring progress (daily cycle based on hour of day)
  const dayProgress = (hourOfDay / 24) * 100;
  const ringProgress = document.getElementById('clockRingProgress');
  if (ringProgress) {
    const circumference = 339.292;
    const offset = circumference - (dayProgress / 100) * circumference;
    ringProgress.style.strokeDashoffset = offset;
  }

  // Trees equivalent (proportional to cumulative CO2)
  const treesWorking = (cumulativeCo2Kg / clockAnnualCo2Kg) * treesPerYear;
  const treeWhole = Math.floor(treesWorking);
  const treeFraction = Math.floor((treesWorking - treeWhole) * 10);
  setElementValue('clockTreeCount', formatNumber(treeWhole, 0));
  setElementValue('clockTreeFraction', `,${treeFraction}`);

  // Update tree progress (to next whole tree)
  const treeProgressPct = ((treesWorking - treeWhole) * 100);
  const treeProgressEl = document.getElementById('clockTreeProgress');
  if (treeProgressEl) treeProgressEl.style.width = `${treeProgressPct}%`;

  // Car km equivalent (proportional to cumulative CO2)
  const carKm = (cumulativeCo2Kg / clockAnnualCo2Kg) * carKmPerYear;
  setElementValue('clockCarKm', formatNumber(Math.floor(carKm), 0));

  // Update car progress (to next 100 km milestone)
  const carProgressPct = (carKm % 100);
  const carProgressEl = document.getElementById('clockCarProgress');
  if (carProgressEl) carProgressEl.style.width = `${carProgressPct}%`;

  // Year CO2 in tons (cumulative)
  const yearCo2Tons = cumulativeCo2Kg / 1000;
  setElementValue('clockYearCo2', formatNumber(yearCo2Tons, 1));

  // Update year progress (percentage of annual target)
  const yearProgressPct = Math.min((cumulativeCo2Kg / clockAnnualCo2Kg) * 100, 100);
  const yearProgressEl = document.getElementById('clockYearProgress');
  if (yearProgressEl) yearProgressEl.style.width = `${yearProgressPct}%`;
}

/**
 * Get speed multiplier based on selected mode
 */
function getClockSpeedMultiplier() {
  const speed = document.getElementById('clockSpeedSelect')?.value || 'fast';
  carbonClockSpeed = speed;

  switch (speed) {
    case 'realtime': return 1;           // 1 second = 1 second
    case 'minute': return 60;            // 1 second = 1 minute (1 min = 1 hour)
    case 'fast': return 1440;            // 1 second = 24 minutes (1 min = 1 day)
    case 'ultrafast': return 10080;      // 1 second = 168 minutes (1 min = 1 week)
    case 'superfast': return 43200;      // 1 second = 12 hours (1 min = 1 month)
    case 'warp': return 525600;          // 1 second = 6 days (1 min = 1 year)
    default: return 1440;
  }
}

/**
 * Update clock speed (called from select change)
 */
function updateClockSpeed() {
  // If running, restart with new speed
  if (carbonClockIsRunning) {
    // Save current simulated time
    const currentSimulated = carbonClockSimulatedSeconds;
    stopCarbonClock();
    carbonClockSimulatedSeconds = currentSimulated;
    startCarbonClock();
  }
  console.log('Clock speed updated to:', document.getElementById('clockSpeedSelect')?.value);
}

// Create or update Carbon Footprint chart
function updateCarbonFootprintChart(metrics) {
  if (!metrics) return;

  const ctx = document.getElementById('carbonFootprintChart');
  if (!ctx) {
    console.warn('Carbon footprint chart canvas not found');
    return;
  }

  // Get grid emission factor (convert from kgCO2e/kWh to gCO2e/kWh)
  const gridEF = (metrics.efGrid || 0.658) * 1000; // gCO2e/kWh

  // Get PV LCA emission factor based on technology
  const pvTech = metrics.pvTechnology || 'mono-Si';
  const pvLCA = PV_LCA_EMISSIONS[pvTech] || PV_LCA_EMISSIONS['default'];

  // Calculate reduction percentage
  const reductionPct = ((gridEF - pvLCA) / gridEF * 100).toFixed(0);

  // Update legend values
  setElementValue('carbonGridValue', `${gridEF.toFixed(0)} gCO2e/kWh`);
  setElementValue('carbonPvValue', `~${pvLCA} gCO2e/kWh`);
  setElementValue('carbonSavingsValue', `-${reductionPct}%`);

  // Destroy existing chart if exists
  if (carbonFootprintChart) {
    carbonFootprintChart.destroy();
  }

  // Chart data
  const chartData = {
    labels: ['Sieć PL', 'PV (LCA)'],
    datasets: [{
      data: [gridEF, pvLCA],
      backgroundColor: [
        'rgba(231, 76, 60, 0.8)',   // Red for grid
        'rgba(39, 174, 96, 0.8)'    // Green for PV
      ],
      borderColor: [
        'rgba(192, 57, 43, 1)',
        'rgba(30, 132, 73, 1)'
      ],
      borderWidth: 2,
      borderRadius: 8,
      barThickness: 60
    }]
  };

  // Create chart
  carbonFootprintChart = new Chart(ctx, {
    type: 'bar',
    data: chartData,
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `${context.raw.toFixed(0)} gCO2e/kWh`;
            }
          }
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          max: Math.ceil(gridEF / 100) * 100 + 100,
          grid: {
            color: 'rgba(0, 0, 0, 0.1)'
          },
          title: {
            display: true,
            text: 'Emisja CO2 [gCO2e/kWh]',
            font: {
              size: 12,
              weight: 'bold'
            }
          },
          ticks: {
            callback: function(value) {
              return value + ' g';
            }
          }
        },
        y: {
          grid: {
            display: false
          },
          ticks: {
            font: {
              size: 14,
              weight: 'bold'
            }
          }
        }
      },
      animation: {
        duration: 1000,
        easing: 'easeOutQuart'
      }
    }
  });

  console.log('📊 Carbon Footprint chart updated');
}
