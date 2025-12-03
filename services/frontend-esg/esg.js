// ESG Module - Environmental, Social, Governance Dashboard
// Separate module for ESG metrics and Electricity Maps integration

// Store received data
let analysisResults = null;
let pvConfig = null;
let hourlyData = null;
let masterVariant = null;
let masterVariantKey = null;
let systemSettings = null;

// Electricity Maps data cache
let lastElectricityMapsData = null;

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
    if (data.settings) {
      systemSettings = data.settings;
    }
    console.log('ESG: Loaded from sharedData format', {
      hasAnalysisResults: !!analysisResults,
      hasMasterVariant: !!masterVariant,
      masterVariantKey: masterVariantKey
    });
  }

  // Handle ANALYSIS_RESULTS format (nested in sharedData)
  if (data.sharedData) {
    analysisResults = data.sharedData.analysisResults || analysisResults;
    pvConfig = data.sharedData.pvConfig || pvConfig;
    hourlyData = data.sharedData.hourlyData || hourlyData;
    masterVariant = data.sharedData.masterVariant || masterVariant;
    masterVariantKey = data.sharedData.masterVariantKey || masterVariantKey;
    if (data.sharedData.settings) {
      systemSettings = data.sharedData.settings;
    }
    console.log('ESG: Loaded from nested sharedData', {
      hasAnalysisResults: !!analysisResults,
      hasMasterVariant: !!masterVariant,
      masterVariantKey: masterVariantKey
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
    return;
  }

  console.log('🌱 Using variantData:', variantData);

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

  const selfConsumptionKwh = variantData.self_consumption ||  // from key_variants
                              variantData.selfConsumption_kWh ||
                              variantData.summary?.self_consumption_kWh || 0;

  // Calculate self consumption from autoconsumption ratio if needed
  const autoconsumptionRatio = variantData.autoconsumption || variantData.autoconsumption_ratio || 0;
  const calculatedSelfConsumption = selfConsumptionKwh || (annualProductionKwh * autoconsumptionRatio / 100);

  const totalConsumptionKwh = analysisResults?.totalConsumption_kWh ||
                               analysisResults?.total_consumption_kwh ||
                               variantData.consumption_kWh ||
                               variantData.total_consumption || 50000;

  console.log('🌱 ESG input values:', {
    annualProductionKwh,
    pvCapacityKwp,
    selfConsumptionKwh: calculatedSelfConsumption,
    totalConsumptionKwh,
    autoconsumptionRatio
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

  // CO2 avoided per year (from PV production replacing grid)
  const co2AvoidedYearKg = annualProductionKwh * efGrid;
  const co2AvoidedYearTon = co2AvoidedYearKg / 1000;

  // CO2 avoided lifetime
  const co2AvoidedLifetimeTon = co2AvoidedYearTon * pvLifetime;

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

  return {
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
    pvLifetime: pvLifetime
  };
}

// Update ESG UI elements
function updateESGUI(metrics) {
  // Main KPIs - European format
  setElementValue('esgCo2ReductionYear', formatNumber(metrics.co2ReductionYear, 2));
  setElementValue('esgCo2ReductionLifetime', formatNumber(metrics.co2ReductionLifetime, 1));
  setElementValue('esgShareRes', formatNumber(metrics.shareRES, 1));
  setElementValue('esgCarbonPayback', formatNumber(metrics.carbonPayback, 1));

  // Scope 2 emissions
  setElementValue('esgCo2Before', formatWithUnit(metrics.co2Before, 'tCO2e/rok', 2));
  setElementValue('esgCo2After', formatWithUnit(metrics.co2After, 'tCO2e/rok', 2));
  setElementValue('esgCo2ReductionPct', `-${formatNumber(metrics.co2ReductionPct, 1)}%`);

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

  console.log('✅ ESG Dashboard updated');
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
    'Raport ESG - PV Optimizer Pro',
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
