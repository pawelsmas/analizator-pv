console.log('🚀 production.js v16 LOADED - Fixed: use actualProduction from hourly data - timestamp:', new Date().toISOString());

// Production mode - use nginx reverse proxy routes
const USE_PROXY = true;

// Backend API URLs
const API_URLS = USE_PROXY ? {
  dataAnalysis: '/api/data',
  pvCalculation: '/api/pv'
} : {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002'
};

// Chart.js instances
let dailyProductionChart, monthlyProductionChart, energyBalanceChart, hourlyProfileChart, daylightProfileChart;

// Data storage
let productionData = null;
let consumptionData = null;
let pvConfig = null;
let analysisResults = null;
let currentVariant = 'A'; // Default variant
let variants = {};
let systemSettings = null;
let analyticalYear = null; // { start_date, end_date, total_hours, total_days, is_complete }

// ============================================
// PRODUCTION SCENARIO P50/P75/P90
// ============================================

// Current production scenario
let currentScenario = 'P50';

// Production factors (can be overwritten by settings)
let productionFactors = {
  P50: 1.00,   // 100% - median/expected production
  P75: 0.97,   // 97% - conservative (75th percentile)
  P90: 0.94    // 94% - cautious (90th percentile)
};

// Base production values (before scenario adjustment)
let baseProductionKwh = 0;

/**
 * Get dynamic X-axis label for hourly profile chart
 * Shows actual data hours and date range instead of hardcoded "8760"
 */
function getHourlyChartXAxisLabel() {
  if (analyticalYear && analyticalYear.total_hours) {
    const hours = analyticalYear.total_hours;
    const startDate = analyticalYear.start_date || '';
    const endDate = analyticalYear.end_date || '';
    const isComplete = analyticalYear.is_complete;

    if (startDate && endDate) {
      const completeness = isComplete ? '' : ' ⚠️ niepełny rok';
      return `Rok analityczny (${hours}h: ${startDate} → ${endDate})${completeness}`;
    }
    return `Profil godzinowy (${hours} godzin)`;
  }
  // Fallback: use actual data points if available
  if (consumptionData && consumptionData.hourlyData && consumptionData.hourlyData.values) {
    const hours = consumptionData.hourlyData.values.length;
    return `Profil godzinowy (${hours} godzin)`;
  }
  return 'Rok (etykiety co 7 dni)';
}

/**
 * Format number in European style
 * - Decimal separator: comma (,)
 * - Thousands separator: non-breaking space
 */
function formatNumberEU(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }
  const fixed = Number(value).toFixed(decimals);
  const parts = fixed.split('.');
  let integerPart = parts[0];
  const decimalPart = parts[1];
  integerPart = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00A0');
  if (decimals > 0 && decimalPart) {
    return integerPart + ',' + decimalPart;
  }
  return integerPart;
}

/**
 * Set production scenario and recalculate all data
 */
function setProductionScenario(scenario) {
  console.log(`📊 Setting production scenario: ${scenario}`);
  currentScenario = scenario;

  // Update floating button styles
  updateFloatingButtonStyles(scenario);

  // Update factor display
  const factorDisplay = document.getElementById('scenarioFactorDisplay');
  if (factorDisplay) {
    const factor = productionFactors[scenario] || 1.0;
    factorDisplay.textContent = `${Math.round(factor * 100)}%`;
  }

  // Recalculate and update all displays
  performAnalysis();

  // Notify shell about scenario change (for cross-module sync)
  if (window.parent !== window) {
    window.parent.postMessage({
      type: 'PRODUCTION_SCENARIO_CHANGED',
      data: {
        scenario: scenario,
        factor: productionFactors[scenario],
        source: 'production'
      }
    }, '*');
  }

  console.log(`✅ Scenario ${scenario} applied with factor ${productionFactors[scenario]}`);
}

/**
 * Update floating scenario button styles
 */
function updateFloatingButtonStyles(scenario) {
  const btnConfig = {
    P50: { borderColor: '#27ae60', activeBackground: '#27ae60', textColor: '#27ae60' },
    P75: { borderColor: '#3498db', activeBackground: '#3498db', textColor: '#3498db' },
    P90: { borderColor: '#e74c3c', activeBackground: '#e74c3c', textColor: '#e74c3c' }
  };

  ['P50', 'P75', 'P90'].forEach(s => {
    const btn = document.getElementById(`btn${s}`);
    if (btn) {
      const isActive = s === scenario;
      const cfg = btnConfig[s];
      btn.style.borderColor = cfg.borderColor;
      btn.style.background = isActive ? cfg.activeBackground : 'white';
      btn.style.color = isActive ? 'white' : cfg.textColor;
    }
  });
}

/**
 * Initialize scenario selector with values from settings
 */
function initializeScenarioSelector() {
  // Load factors from settings if available
  if (systemSettings) {
    productionFactors.P50 = systemSettings.productionP50Factor || 1.00;
    productionFactors.P75 = systemSettings.productionP75Factor || 0.97;
    productionFactors.P90 = systemSettings.productionP90Factor || 0.94;
  }

  // Update floating button styles
  updateFloatingButtonStyles(currentScenario);

  // Update factor display
  const factorDisplay = document.getElementById('scenarioFactorDisplay');
  if (factorDisplay) {
    const factor = productionFactors[currentScenario] || 1.0;
    factorDisplay.textContent = `${Math.round(factor * 100)}%`;
  }

  console.log('📊 Scenario selector initialized with factors:', productionFactors);
}

// Check for data on load
document.addEventListener('DOMContentLoaded', () => {
  console.log('📱 DOMContentLoaded event fired in production.js');
  loadAllData();
  // Request shared data from parent shell
  requestSharedData();
  // Request settings from shell
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  }
  // Setup sticky variant selector
  setupStickyVariantSelector();
  // Initialize scenario selector
  initializeScenarioSelector();
});

// Setup sticky variant selector with scroll animation
function setupStickyVariantSelector() {
  const variantSelector = document.querySelector('.variant-selector');
  if (!variantSelector) return;

  let lastScrollTop = 0;
  const scrollThreshold = 100; // Pixels to scroll before adding "scrolled" class

  window.addEventListener('scroll', () => {
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    if (scrollTop > scrollThreshold) {
      variantSelector.classList.add('scrolled');
    } else {
      variantSelector.classList.remove('scrolled');
    }

    lastScrollTop = scrollTop;
  });
}

// Request shared data from shell
function requestSharedData() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  switch (event.data.type) {
    case 'DATA_AVAILABLE':
    case 'DATA_UPLOADED':
    case 'PV_CONFIG_UPDATED':
      loadAllData();
      break;
    case 'DATA_CLEARED':
      clearAnalysis();
      break;
    case 'ANALYSIS_RESULTS':
      // Receive analysis results from shell
      if (event.data.data && event.data.data.sharedData) {
        const shared = event.data.data.sharedData;
        analysisResults = shared.analysisResults;
        if (analysisResults && analysisResults.key_variants) {
          variants = analysisResults.key_variants;
        }
        pvConfig = shared.pvConfig;
        if (shared.hourlyData) {
          consumptionData = {
            filename: 'Dane z Shell',
            dataPoints: shared.hourlyData.values.length,
            year: new Date(shared.hourlyData.timestamps[0]).getFullYear(),
            hourlyData: shared.hourlyData
          };
        }
        performAnalysis();
      }
      break;
    case 'MASTER_VARIANT_CHANGED':
      // Master variant was changed in Configuration
      if (event.data.data && event.data.data.variantKey) {
        currentVariant = event.data.data.variantKey;
        // Update active button
        document.querySelectorAll('.variant-btn').forEach(btn => {
          btn.classList.remove('active');
        });
        document.querySelector(`.variant-btn[data-variant="${currentVariant}"]`)?.classList.add('active');
        performAnalysis();
      }
      break;
    case 'SHARED_DATA_RESPONSE':
      // Receive shared data response
      console.log('📨 SHARED_DATA_RESPONSE received:', event.data.data);
      if (event.data.data) {
        if (event.data.data.analysisResults) {
          analysisResults = event.data.data.analysisResults;
          console.log('  - analysisResults loaded:', !!analysisResults);
          if (analysisResults && analysisResults.key_variants) {
            variants = analysisResults.key_variants;
            console.log('  - variants loaded:', Object.keys(variants));
          }
        }
        pvConfig = event.data.data.pvConfig;
        console.log('  - pvConfig loaded:', !!pvConfig);
        if (event.data.data.hourlyData) {
          consumptionData = {
            filename: 'Dane z Shell',
            dataPoints: event.data.data.hourlyData.values.length,
            year: new Date(event.data.data.hourlyData.timestamps[0]).getFullYear(),
            hourlyData: event.data.data.hourlyData
          };
          console.log('  - consumptionData loaded:', consumptionData.dataPoints, 'points');
        }
        // Load settings if available
        if (event.data.data.settings) {
          systemSettings = event.data.data.settings;
          initializeScenarioSelector();
        }
        // Load master variant if available
        if (event.data.data.masterVariantKey) {
          currentVariant = event.data.data.masterVariantKey;
          console.log('  - currentVariant set to:', currentVariant);
          // Update active button
          document.querySelectorAll('.variant-btn').forEach(btn => {
            btn.classList.remove('active');
          });
          document.querySelector(`.variant-btn[data-variant="${currentVariant}"]`)?.classList.add('active');
        }
        // Load analytical year metadata if available
        if (event.data.data.analyticalYear) {
          analyticalYear = event.data.data.analyticalYear;
          console.log('  - analyticalYear loaded:', analyticalYear);
        }
        console.log('🚀 Calling performAnalysis() from SHARED_DATA_RESPONSE');
        performAnalysis();
      }
      break;
    case 'SETTINGS_UPDATED':
      // Settings were changed in Settings module
      console.log('📨 SETTINGS_UPDATED received:', event.data.data);
      if (event.data.data) {
        systemSettings = event.data.data;
        initializeScenarioSelector();
        performAnalysis();
      }
      break;
    case 'SCENARIO_CHANGED':
      // Scenario was changed from another module (Economics or shell)
      console.log('📨 SCENARIO_CHANGED received:', event.data.data);
      if (event.data.data && event.data.data.scenario) {
        const newScenario = event.data.data.scenario;
        const source = event.data.data.source || 'unknown';

        // Only update if scenario is different and not from production itself
        if (newScenario !== currentScenario && source !== 'production') {
          currentScenario = newScenario;
          // Update floating button styles
          updateFloatingButtonStyles(currentScenario);
          // Update factor display
          const factorDisplay = document.getElementById('scenarioFactorDisplay');
          if (factorDisplay) {
            const factor = productionFactors[currentScenario] || 1.0;
            factorDisplay.textContent = `${Math.round(factor * 100)}%`;
          }
          performAnalysis();
          console.log(`✅ Scenario synced to ${currentScenario} from ${source}`);
        }
      }
      break;
    case 'PROJECT_LOADED':
      // Project was loaded - request shared data to refresh
      console.log('📂 Production: Project loaded, requesting shared data');
      if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
      }
      break;
  }
});

// Load all data from localStorage or backend
async function loadAllData() {
  console.log('📂 loadAllData() called');
  // Try localStorage first
  const storedProduction = localStorage.getItem('pvProductionData');
  const storedConsumption = localStorage.getItem('consumptionData');
  const storedConfig = localStorage.getItem('pvConfig');
  const storedAnalysis = localStorage.getItem('pv_analysis_results');

  console.log('  - storedProduction:', storedProduction ? 'EXISTS' : 'NULL');
  console.log('  - storedConsumption:', storedConsumption ? 'EXISTS' : 'NULL');
  console.log('  - storedAnalysis:', storedAnalysis ? 'EXISTS' : 'NULL');

  // Always try to load analysisResults from localStorage first
  if (storedAnalysis) {
    try {
      analysisResults = JSON.parse(storedAnalysis);
      if (analysisResults && analysisResults.key_variants) {
        variants = analysisResults.key_variants;
        console.log('  - Loaded variants:', Object.keys(variants));
      }
    } catch (error) {
      console.error('Błąd ładowania analysisResults:', error);
    }
  }

  // Load master variant selection if available
  const masterVariantKey = localStorage.getItem('masterVariant');
  if (masterVariantKey && variants[masterVariantKey]) {
    currentVariant = masterVariantKey;
    // Update active button
    setTimeout(() => {
      document.querySelectorAll('.variant-btn').forEach(btn => {
        btn.classList.remove('active');
      });
      document.querySelector(`.variant-btn[data-variant="${currentVariant}"]`)?.classList.add('active');
    }, 100);
  }

  if (storedProduction || storedConfig || storedAnalysis) {
    try {
      if (storedProduction) productionData = JSON.parse(storedProduction);
      if (storedConsumption) consumptionData = JSON.parse(storedConsumption);
      if (storedConfig) pvConfig = JSON.parse(storedConfig);

      performAnalysis();
      return;
    } catch (error) {
      console.error('Błąd ładowania danych z localStorage:', error);
    }
  }

  // Fallback: try to load from backend
  try {
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

    // Backend has data, fetch hourly data
    const dataResponse = await fetch(`${API_URLS.dataAnalysis}/hourly-data`);
    if (!dataResponse.ok) {
      showNoData();
      return;
    }

    const hourlyData = await dataResponse.json();

    // Try to get analysis results from localStorage or backend
    const storedAnalysis = localStorage.getItem('pv_analysis_results');

    if (storedAnalysis) {
      try {
        analysisResults = JSON.parse(storedAnalysis);
        if (analysisResults && analysisResults.key_variants) {
          variants = analysisResults.key_variants;
        }
      } catch (e) {
        console.error('Błąd parsowania wyników analizy:', e);
      }
    }

    // If no analysis results, try to get from analyzer
    if (!analysisResults) {
      try {
        const analyzeResponse = await fetch(`${API_URLS.pvCalculation}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        if (analyzeResponse.ok) {
          analysisResults = await analyzeResponse.json();
          localStorage.setItem('pv_analysis_results', JSON.stringify(analysisResults));
        }
      } catch (e) {
        console.error('Błąd pobierania analizy z backendu:', e);
      }
    }

    // Build production data
    if (analysisResults && analysisResults.hourly_production) {
      productionData = {
        filename: 'Dane z backendu',
        hourlyProduction: analysisResults.hourly_production,
        dataPoints: analysisResults.hourly_production.length
      };
    } else {
      // Generate sample production data if analysis not available
      productionData = {
        filename: 'Dane z backendu',
        hourlyProduction: hourlyData.values.map(() => 0),
        dataPoints: hourlyData.values.length
      };
    }

    // Get consumption data for comparison
    consumptionData = {
      filename: 'Dane z backendu',
      dataPoints: hourlyData.values.length,
      year: new Date(hourlyData.timestamps[0]).getFullYear(),
      hourlyData: hourlyData
    };

    // Save to localStorage for next time
    localStorage.setItem('pvProductionData', JSON.stringify(productionData));
    localStorage.setItem('consumptionData', JSON.stringify(consumptionData));

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

// Generate hourly PV production based on selected variant
function generateHourlyProduction(capacity_kW, timestamps) {
  if (!timestamps || timestamps.length === 0) return [];

  const production = [];

  for (let i = 0; i < timestamps.length; i++) {
    const date = new Date(timestamps[i]);
    const month = date.getMonth(); // 0-11 (0=Jan, 5=Jun, 11=Dec)
    const hour = date.getHours(); // 0-23
    const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 86400000);

    // Realistic seasonal irradiance factor for Poland/Central Europe
    // Peak in June (month=5), minimum in December (month=11)
    // Based on real solar irradiance data: Jun≈5.5 kWh/m²/day, Dec≈0.8 kWh/m²/day
    const seasonalIrradiance = [
      0.25,  // Jan - very low
      0.35,  // Feb - low
      0.55,  // Mar - moderate
      0.75,  // Apr - good
      0.90,  // May - very good
      1.00,  // Jun - PEAK (longest days, highest sun)
      0.95,  // Jul - very good (slightly lower than Jun)
      0.85,  // Aug - good
      0.65,  // Sep - moderate
      0.45,  // Oct - moderate-low
      0.30,  // Nov - low
      0.20   // Dec - minimum (shortest days, lowest sun)
    ];
    const seasonalFactor = seasonalIrradiance[month];

    // Day length varies by season (affects when sun is up)
    const dayLengthHours = [
      8,   // Jan
      10,  // Feb
      12,  // Mar
      14,  // Apr
      16,  // May
      16,  // Jun - longest days
      16,  // Jul
      14,  // Aug
      12,  // Sep
      10,  // Oct
      8,   // Nov
      8    // Dec - shortest days
    ];
    const sunriseHour = 12 - dayLengthHours[month] / 2;
    const sunsetHour = 12 + dayLengthHours[month] / 2;

    // Daily solar curve (Gaussian bell curve centered at solar noon)
    let hourlyFactor = 0;
    if (hour >= sunriseHour && hour <= sunsetHour) {
      const solarNoon = 12;
      const sigma = dayLengthHours[month] / 5; // Curve width based on day length
      hourlyFactor = Math.exp(-Math.pow(hour - solarNoon, 2) / (2 * sigma * sigma));
    }

    // Weather variability (random clouds, +/- 20%)
    const weatherNoise = 0.9 + 0.2 * Math.sin(dayOfYear * 7.3) * Math.cos(dayOfYear * 3.7);

    // Performance ratio: typical PV system efficiency accounting for:
    // - Panel temperature losses
    // - Inverter efficiency
    // - Cable losses
    // - Soiling
    // Typical PR = 0.75-0.85, we use 0.80
    const performanceRatio = 0.80;

    // Peak sun hours factor: converts capacity to actual production
    // At peak conditions (solar noon, clear summer day), panel produces ~80% of rated capacity
    const peakSunFactor = 0.80;

    // Calculate hourly production in kWh
    const hourlyProduction = capacity_kW * hourlyFactor * seasonalFactor * weatherNoise * performanceRatio * peakSunFactor;

    production.push(Math.max(0, hourlyProduction));
  }

  return production;
}

// Perform production analysis
function performAnalysis() {
  console.log('🔍 performAnalysis() called');
  console.log('📊 Data availability check:');
  console.log('  - productionData:', productionData ? 'EXISTS' : 'NULL');
  console.log('  - pvConfig:', pvConfig ? 'EXISTS' : 'NULL');
  console.log('  - analysisResults:', analysisResults ? 'EXISTS' : 'NULL');
  console.log('  - variants:', variants ? 'EXISTS' : 'NULL');
  console.log('  - currentVariant:', currentVariant);
  console.log('  - consumptionData:', consumptionData ? 'EXISTS' : 'NULL');

  hideNoData();

  if (!productionData && !pvConfig && !analysisResults) {
    console.log('❌ No data available - showing no data message');
    showNoData();
    return;
  }

  // Generate hourly production if we have variant data but no hourly production
  console.log('🔄 Checking if hourly production generation is needed...');
  console.log('  Condition 1 - analysisResults:', !!analysisResults);
  console.log('  Condition 2 - variants:', !!variants);
  console.log('  Condition 3 - currentVariant:', !!currentVariant);
  console.log('  Condition 4 - consumptionData:', !!consumptionData);

  // If we don't have consumptionData, try to load it from localStorage
  if (!consumptionData) {
    console.log('⚠️ consumptionData missing, trying to load from localStorage...');
    const storedConsumption = localStorage.getItem('consumptionData');
    if (storedConsumption) {
      try {
        consumptionData = JSON.parse(storedConsumption);
        console.log('✅ Loaded consumptionData from localStorage:', consumptionData.dataPoints, 'points');
      } catch (error) {
        console.error('❌ Error loading consumptionData:', error);
      }
    }
  }

  // Get current scenario factor
  const scenarioFactor = productionFactors[currentScenario] || 1.0;
  console.log(`📊 Using scenario ${currentScenario} with factor ${scenarioFactor}`);

  if (analysisResults && variants && currentVariant && consumptionData) {
    console.log('✓ All conditions met, attempting to generate hourly production');
    const variant = variants[currentVariant];
    console.log('  - Variant object:', variant);
    console.log('  - Variant capacity:', variant?.capacity);
    console.log('  - consumptionData.hourlyData:', consumptionData.hourlyData ? 'EXISTS' : 'NULL');
    console.log('  - Timestamps count:', consumptionData.hourlyData?.timestamps?.length);

    if (variant && consumptionData.hourlyData && consumptionData.hourlyData.timestamps) {
      console.log('🚀 Generating hourly production with scenario factor...');

      // Generate base hourly production (P50)
      const baseHourlyProduction = generateHourlyProduction(
        variant.capacity,
        consumptionData.hourlyData.timestamps
      );

      // Apply scenario factor to hourly production
      const hourlyProduction = baseHourlyProduction.map(val => val * scenarioFactor);

      console.log('✅ Generated hourly production:');
      console.log('  - Data points:', hourlyProduction.length);
      console.log('  - Scenario factor:', scenarioFactor);
      console.log('  - Sum (base):', baseHourlyProduction.reduce((a, b) => a + b, 0).toFixed(2), 'kWh');
      console.log('  - Sum (adjusted):', hourlyProduction.reduce((a, b) => a + b, 0).toFixed(2), 'kWh');
      console.log('  - Max:', Math.max(...hourlyProduction).toFixed(2), 'kW');

      productionData = {
        filename: `Generated for Variant ${currentVariant} (${currentScenario})`,
        hourlyProduction: hourlyProduction,
        dataPoints: hourlyProduction.length,
        scenario: currentScenario,
        scenarioFactor: scenarioFactor
      };

      // Save to localStorage for persistence
      localStorage.setItem('pvProductionData', JSON.stringify(productionData));

      console.log('✅ productionData object created and saved to localStorage');
    } else {
      console.log('❌ Inner condition failed - missing variant or consumption data');
    }
  } else {
    console.log('❌ Hourly production generation skipped - missing required data');
  }

  // Update variant descriptions
  updateVariantDescriptions();

  // Calculate statistics for selected variant
  const stats = calculateStatistics();

  // Update UI
  updateStatistics(stats);
  updateBessSection();
  updateDataInfo();

  // Generate charts
  generateHourlyProfile(); // Full year hourly profile (8760h)
  generateDaylightProfile(); // Daylight hours only profile (~5000-6000h)
  generateMonthlyProduction();
  generateDailyProductionProfile();
  generateEnergyBalance();
}

// Calculate statistics
function calculateStatistics() {
  // Get current scenario factor
  const scenarioFactor = productionFactors[currentScenario] || 1.0;
  console.log(`📊 Calculating statistics with scenario ${currentScenario} (factor: ${scenarioFactor})`);
  console.log('📊 variants object:', variants);
  console.log('📊 currentVariant:', currentVariant);

  // Try to get data from selected variant first - use variants object (not analysisResults.key_variants)
  if (variants && variants[currentVariant]) {
    const variant = variants[currentVariant];
    console.log('📊 Found variant:', variant);

    // Store base production for info panel (P50 baseline)
    baseProductionKwh = variant.production || 0;

    // Apply scenario factor to production values
    const adjustedProduction = (variant.production || 0) * scenarioFactor;

    // Calculate self-consumption, export and import dynamically from hourly data
    let selfConsumedKwh = 0;
    let gridExportKwh = 0;
    let gridImportKwh = 0;
    let totalConsumptionKwh = 0;
    let totalProductionFromHourly = 0;

    if (productionData && productionData.hourlyProduction && consumptionData && consumptionData.hourlyData) {
      const production = productionData.hourlyProduction;
      const consumption = consumptionData.hourlyData.values;

      console.log('📊 Hourly data check:', {
        productionLength: production.length,
        consumptionLength: consumption.length,
        productionFirst5: production.slice(0, 5),
        consumptionFirst5: consumption.slice(0, 5),
        productionScenario: productionData.scenario,
        productionFactor: productionData.scenarioFactor
      });

      for (let i = 0; i < Math.min(production.length, consumption.length); i++) {
        const prod = production[i]; // Already has scenario factor applied
        const cons = consumption[i];
        totalProductionFromHourly += prod;

        if (prod >= cons) {
          selfConsumedKwh += cons;
          gridExportKwh += (prod - cons);
        } else {
          selfConsumedKwh += prod;
          gridImportKwh += (cons - prod);
        }
        totalConsumptionKwh += cons;
      }

      console.log('📊 Loop results:', {
        totalProductionFromHourly,
        adjustedProductionFromVariant: adjustedProduction,
        difference: Math.abs(totalProductionFromHourly - adjustedProduction),
        selfConsumedKwh,
        gridExportKwh,
        gridImportKwh,
        totalConsumptionKwh
      });
    } else {
      // Fallback to variant data if no hourly data available
      console.log('⚠️ Using fallback - no hourly data available');
      selfConsumedKwh = (variant.self_consumed || 0) * scenarioFactor;
      gridExportKwh = (variant.exported || 0) * scenarioFactor;
      totalConsumptionKwh = analysisResults?.totalConsumption_kWh || 0;
      gridImportKwh = Math.max(0, totalConsumptionKwh - selfConsumedKwh);
      totalProductionFromHourly = adjustedProduction;
    }

    // Use actual production from hourly data for percentage calculations
    const actualProduction = totalProductionFromHourly > 0 ? totalProductionFromHourly : adjustedProduction;

    // Calculate percentages
    const selfConsumptionPct = actualProduction > 0 ? (selfConsumedKwh / actualProduction) * 100 : 0;
    const selfSufficiencyPct = totalConsumptionKwh > 0 ? (selfConsumedKwh / totalConsumptionKwh) * 100 : 0;

    console.log('📊 Final calculated values:', {
      actualProduction,
      adjustedProduction,
      selfConsumedKwh,
      gridExportKwh,
      gridImportKwh,
      totalConsumptionKwh,
      selfConsumptionPct: selfConsumptionPct.toFixed(2),
      selfSufficiencyPct: selfSufficiencyPct.toFixed(2),
      capacity: variant.capacity,
      scenario: currentScenario
    });

    return {
      annualProduction: formatNumberEU(actualProduction / 1000000, 2), // kWh -> GWh (from hourly data)
      installedCapacity: formatNumberEU((variant.capacity || 0) / 1000, 2), // kWp -> MWp
      specificYield: formatNumberEU(variant.capacity > 0 ? (actualProduction / variant.capacity) : 0, 0), // kWh/kWp (from hourly)
      performanceRatio: formatNumberEU(selfConsumptionPct, 1), // % - using actual self-consumption
      selfConsumption: `${formatNumberEU(selfConsumptionPct, 1)}%`, // %
      selfSufficiency: `${formatNumberEU(selfSufficiencyPct, 1)}%`, // %
      gridExport: `${formatNumberEU(gridExportKwh / 1000000, 2)} GWh`, // GWh (from hourly calculation)
      gridImport: `${formatNumberEU(gridImportKwh / 1000000, 2)} GWh`, // GWh (from hourly calculation)
      peakPower: `${formatNumberEU((variant.capacity || 0) / 1000, 2)} MW`, // MW
      fullLoadHours: `${formatNumberEU(variant.capacity > 0 ? (actualProduction / variant.capacity) : 0, 0)} h` // from hourly
    };
  }

  // Fallback to old logic if no variants
  if (!productionData || !productionData.hourlyProduction) {
    return {
      annualProduction: 0,
      installedCapacity: pvConfig?.installedCapacity || 0,
      specificYield: 0,
      performanceRatio: 0,
      selfConsumption: 0,
      selfSufficiency: 0,
      gridExport: 0,
      gridImport: 0,
      peakPower: 0,
      fullLoadHours: 0
    };
  }

  const production = productionData.hourlyProduction;
  const totalProduction = production.reduce((a, b) => a + b, 0);
  const maxProduction = Math.max(...production);
  const installedCapacity = pvConfig?.installedCapacity || 1000; // kWp

  // Annual production (kWh -> GWh)
  const annualProduction = (totalProduction / 1000000).toFixed(2);

  // Specific yield (kWh/kWp)
  const specificYield = (totalProduction / installedCapacity).toFixed(0);

  // Performance Ratio (assuming standard 1000 kWh/m2 irradiation)
  const theoreticalProduction = installedCapacity * 1000;
  const performanceRatio = ((totalProduction / theoreticalProduction) * 100).toFixed(1);

  // Full load hours
  const fullLoadHours = (totalProduction / installedCapacity).toFixed(0);

  // Self-consumption analysis
  let selfConsumed = 0;
  let gridExport = 0;
  let gridImport = 0;

  if (consumptionData && consumptionData.hourlyData) {
    const consumption = consumptionData.hourlyData.values;

    for (let i = 0; i < Math.min(production.length, consumption.length); i++) {
      const prod = production[i];
      const cons = consumption[i];

      if (prod >= cons) {
        selfConsumed += cons;
        gridExport += (prod - cons);
      } else {
        selfConsumed += prod;
        gridImport += (cons - prod);
      }
    }
  }

  const totalConsumption = consumptionData?.hourlyData?.values.reduce((a, b) => a + b, 0) || 0;

  const selfConsumption = totalProduction > 0 ? ((selfConsumed / totalProduction) * 100).toFixed(1) : 0;
  const selfSufficiency = totalConsumption > 0 ? ((selfConsumed / totalConsumption) * 100).toFixed(1) : 0;

  return {
    annualProduction,
    installedCapacity: (installedCapacity / 1000).toFixed(2), // kWp -> MWp
    specificYield,
    performanceRatio,
    selfConsumption: `${selfConsumption}%`,
    selfSufficiency: `${selfSufficiency}%`,
    gridExport: `${(gridExport / 1000000).toFixed(2)} GWh`,
    gridImport: `${(gridImport / 1000000).toFixed(2)} GWh`,
    peakPower: `${(maxProduction / 1000).toFixed(2)} MW`,
    fullLoadHours: `${fullLoadHours} h`
  };
}

// Update statistics display
function updateStatistics(stats) {
  document.getElementById('annualProduction').textContent = stats.annualProduction;
  document.getElementById('installedCapacity').textContent = stats.installedCapacity;
  document.getElementById('specificYield').textContent = stats.specificYield;
  document.getElementById('performanceRatio').textContent = stats.performanceRatio;
  document.getElementById('selfConsumption').textContent = stats.selfConsumption;
  document.getElementById('selfSufficiency').textContent = stats.selfSufficiency;
  document.getElementById('gridExport').textContent = stats.gridExport;
  document.getElementById('gridImport').textContent = stats.gridImport;
  document.getElementById('peakPower').textContent = stats.peakPower;
  document.getElementById('fullLoadHours').textContent = stats.fullLoadHours;
}

// Update BESS section display
function updateBessSection() {
  const bessSection = document.getElementById('bessSection');
  if (!bessSection) return;

  // Check if current variant has BESS data
  if (!variants || !variants[currentVariant]) {
    console.log('🔋 BESS check: No variants or currentVariant');
    bessSection.style.display = 'none';
    return;
  }

  const variant = variants[currentVariant];
  console.log('🔋 BESS check for variant:', currentVariant, {
    bess_power_kw: variant.bess_power_kw,
    bess_energy_kwh: variant.bess_energy_kwh,
    baseline_no_bess: variant.baseline_no_bess
  });

  const hasBess = variant.bess_power_kw != null && variant.bess_energy_kwh != null && variant.bess_power_kw > 0;

  if (!hasBess) {
    console.log('🔋 BESS not enabled for this variant (bess_power_kw is null or 0)');
    bessSection.style.display = 'none';
    return;
  }

  // Show BESS section
  bessSection.style.display = 'block';

  // BESS parameters
  const bessPowerKw = variant.bess_power_kw || 0;
  const bessEnergyKwh = variant.bess_energy_kwh || 0;
  const bessFromBattery = variant.bess_discharged_kwh || variant.bess_self_consumed_from_bess_kwh || 0;
  const bessToBattery = variant.bess_charged_kwh || 0;
  const bessCurtailed = variant.bess_curtailed_kwh || 0;
  const bessCycles = variant.bess_cycles_equivalent || 0;
  const duration = bessPowerKw > 0 ? (bessEnergyKwh / bessPowerKw).toFixed(1) : 0;

  // Current values with BESS
  const bessAutoConsumption = variant.auto_consumption_pct || 0;
  const bessSelfConsumed = variant.self_consumed || 0;
  const bessExported = variant.exported || 0;
  const bessCoveragePct = variant.coverage_pct || 0;
  const bessProduction = variant.production || 0;

  // Baseline values (without BESS) from backend
  const baseline = variant.baseline_no_bess || {};
  console.log('🔋 Baseline data from backend:', baseline);
  console.log('🔋 Full variant data:', variant);

  // If baseline is empty but we have BESS, we need to estimate baseline values
  // Baseline = current values minus BESS contribution
  let baselineAutoConsumption = baseline.auto_consumption_pct || 0;
  let baselineSelfConsumed = baseline.self_consumed || 0;
  let baselineExported = baseline.exported || 0;
  let baselineCoveragePct = baseline.coverage_pct || 0;

  // If baseline is missing, estimate it from BESS data
  if (!baseline.auto_consumption_pct && bessFromBattery > 0) {
    // Without BESS: self_consumed would be less by the amount from battery
    // and exported would be more (energy that went to battery would be exported)
    baselineSelfConsumed = bessSelfConsumed - bessFromBattery;
    baselineExported = bessToBattery; // Energy that was stored would have been exported
    baselineAutoConsumption = bessProduction > 0 ? (baselineSelfConsumed / bessProduction * 100) : 0;
    // Coverage remains similar (based on consumption not production)
    const totalConsumption = consumptionData?.hourlyData?.values?.reduce((a,b) => a+b, 0) || 0;
    baselineCoveragePct = totalConsumption > 0 ? (baselineSelfConsumed / totalConsumption * 100) : 0;
    console.log('🔋 Estimated baseline (no backend data):', { baselineAutoConsumption, baselineSelfConsumed, baselineExported, baselineCoveragePct });
  }

  // Calculate differences
  const diffAuto = bessAutoConsumption - baselineAutoConsumption;
  const diffSelfConsumed = bessSelfConsumed - baselineSelfConsumed;
  const diffExported = bessExported - baselineExported;
  const diffCoverage = bessCoveragePct - baselineCoveragePct;
  const curtailmentPct = bessProduction > 0 ? (bessCurtailed / bessProduction * 100) : 0;

  // Format and display - BESS Parameters
  document.getElementById('bessPowerKw').textContent = `${bessPowerKw.toFixed(0)} kW`;
  document.getElementById('bessEnergyKwh').textContent = `${bessEnergyKwh.toFixed(0)} kWh`;
  const bessDurationEl = document.getElementById('bessDuration');
  if (bessDurationEl) bessDurationEl.textContent = `${duration}h`;

  // Energy flow
  document.getElementById('bessFromBattery').textContent = `${(bessFromBattery / 1000).toFixed(1)} MWh`;
  document.getElementById('bessToBattery').textContent = `${(bessToBattery / 1000).toFixed(1)} MWh`;
  document.getElementById('bessCycles').textContent = `${bessCycles.toFixed(0)} cykli/rok`;

  // BESS Sizing Card (new)
  const bessSizingCardEl = document.getElementById('bessSizingCard');
  if (bessSizingCardEl) {
    bessSizingCardEl.textContent = `${bessPowerKw.toFixed(0)} kW / ${bessEnergyKwh.toFixed(0)} kWh`;
  }
  const bessDurationCardEl = document.getElementById('bessDurationCard');
  if (bessDurationCardEl) {
    bessDurationCardEl.textContent = `Duration: ${duration}h`;
  }

  // Impact summary cards
  const bessAutoIncreaseEl = document.getElementById('bessAutoIncrease');
  if (bessAutoIncreaseEl) {
    bessAutoIncreaseEl.textContent = `+${diffAuto.toFixed(1)}%`;
  }
  const bessAutoCompareEl = document.getElementById('bessAutoCompare');
  if (bessAutoCompareEl) {
    bessAutoCompareEl.textContent = `${baselineAutoConsumption.toFixed(1)}% → ${bessAutoConsumption.toFixed(1)}%`;
  }

  const bessEnergyFromBatteryEl = document.getElementById('bessEnergyFromBattery');
  if (bessEnergyFromBatteryEl) {
    bessEnergyFromBatteryEl.textContent = `${(bessFromBattery / 1000).toFixed(1)}`;
  }
  const bessCyclesInfoEl = document.getElementById('bessCyclesInfo');
  if (bessCyclesInfoEl) {
    bessCyclesInfoEl.textContent = `${bessCycles.toFixed(0)} cykli ekw./rok`;
  }

  const bessCurtailmentTotalEl = document.getElementById('bessCurtailmentTotal');
  if (bessCurtailmentTotalEl) {
    bessCurtailmentTotalEl.textContent = `${(bessCurtailed / 1000).toFixed(1)}`;
  }
  const bessCurtailmentPctEl = document.getElementById('bessCurtailmentPct');
  if (bessCurtailmentPctEl) {
    bessCurtailmentPctEl.textContent = `${curtailmentPct.toFixed(1)}% produkcji PV`;
  }

  // Comparison table
  const setEl = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  // Baseline (without BESS)
  setEl('baselineAuto', `${baselineAutoConsumption.toFixed(1)}%`);
  setEl('baselineSelfConsumed', `${(baselineSelfConsumed / 1000).toFixed(1)}`);
  setEl('baselineExported', `${(baselineExported / 1000).toFixed(1)}`);
  setEl('baselineCoverage', `${baselineCoveragePct.toFixed(1)}%`);

  // With BESS
  setEl('bessAuto', `${bessAutoConsumption.toFixed(1)}%`);
  setEl('bessSelfConsumed', `${(bessSelfConsumed / 1000).toFixed(1)}`);
  setEl('bessExported', `${(bessExported / 1000).toFixed(1)}`);
  setEl('bessCoverage', `${bessCoveragePct.toFixed(1)}%`);

  // Differences
  setEl('diffAuto', `+${diffAuto.toFixed(1)}%`);
  setEl('diffSelfConsumed', `+${(diffSelfConsumed / 1000).toFixed(1)}`);
  setEl('diffExported', `${(diffExported / 1000).toFixed(1)}`);
  setEl('diffCoverage', `+${diffCoverage.toFixed(1)}%`);

  console.log('🔋 BESS section updated:', {
    power: bessPowerKw,
    energy: bessEnergyKwh,
    duration: duration,
    discharged: bessFromBattery,
    charged: bessToBattery,
    curtailed: bessCurtailed,
    cycles: bessCycles,
    baseline: baseline,
    autoIncrease: diffAuto
  });
}

// Update data info
function updateDataInfo() {
  // Get capacity from current variant if available
  let capacity = 0;
  if (variants && variants[currentVariant]) {
    capacity = variants[currentVariant].capacity || 0;
  } else if (pvConfig?.installedCapacity) {
    capacity = pvConfig.installedCapacity;
  }

  const dataPoints = productionData?.hourlyProduction?.length ||
                     consumptionData?.hourlyData?.timestamps?.length ||
                     8760;

  const info = `Moc: ${formatNumberEU(capacity / 1000, 1)} MWp • ${dataPoints} punktów`;
  document.getElementById('dataInfo').textContent = info;
}

// Generate daily production profile chart
function generateDailyProductionProfile() {
  if (!productionData || !productionData.hourlyProduction) return;

  const production = productionData.hourlyProduction;
  const hourlyAverages = new Array(24).fill(0);
  const hourlyCounts = new Array(24).fill(0);

  production.forEach((value, index) => {
    const hour = index % 24;
    hourlyAverages[hour] += value;
    hourlyCounts[hour]++;
  });

  const avgProfile = hourlyAverages.map((sum, hour) =>
    (sum / hourlyCounts[hour] / 1000).toFixed(2) // kW -> MW
  );

  const ctx = document.getElementById('dailyProductionProfile').getContext('2d');

  if (dailyProductionChart) dailyProductionChart.destroy();

  dailyProductionChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
      datasets: [{
        label: 'Produkcja PV [MW]',
        data: avgProfile,
        borderColor: '#f39c12',
        backgroundColor: 'rgba(243, 156, 18, 0.1)',
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
          beginAtZero: true,
          title: { display: true, text: 'Moc [MW]' }
        },
        x: {
          title: { display: true, text: 'Godzina' }
        }
      }
    }
  });
}

// Generate monthly production chart
function generateMonthlyProduction() {
  console.log('📊 generateMonthlyProduction() called');
  if (!productionData || !productionData.hourlyProduction) {
    console.log('❌ Missing productionData');
    return;
  }
  if (!consumptionData || !consumptionData.hourlyData || !consumptionData.hourlyData.timestamps) {
    console.log('❌ Missing timestamps from consumptionData');
    return;
  }

  const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
  const monthlyTotals = new Array(12).fill(0);
  const hoursPerMonth = new Array(12).fill(0);

  // Use REAL timestamps from consumptionData to determine actual month
  const timestamps = consumptionData.hourlyData.timestamps;

  productionData.hourlyProduction.forEach((value, index) => {
    if (index < timestamps.length) {
      const date = new Date(timestamps[index]);
      const month = date.getMonth(); // 0-11 (REAL month from timestamp)
      monthlyTotals[month] += value;
      hoursPerMonth[month]++;
    }
  });

  console.log('📈 Monthly totals (kWh):', monthlyTotals.map((v, i) => `${monthNames[i]}: ${v.toFixed(0)}`));

  const monthlyMWh = monthlyTotals.map(total => (total / 1000).toFixed(2));

  // Fill debug table with monthly data
  const totalAnnual = monthlyTotals.reduce((sum, val) => sum + val, 0);
  const totalHoursCount = hoursPerMonth.reduce((sum, val) => sum + val, 0);
  const tbody = document.getElementById('monthlyDebugBody');
  tbody.innerHTML = monthlyTotals.map((total, i) => {
    const mwh = formatNumberEU(total / 1000, 2);
    const hours = hoursPerMonth[i];
    const avgKW = hours > 0 ? formatNumberEU(total / hours, 2) : '0,00';
    const percent = totalAnnual > 0 ? formatNumberEU((total / totalAnnual) * 100, 1) : '0,0';

    // Color coding based on expected values
    let rowColor = '';
    if (i === 5) rowColor = 'background: #d4edda;'; // June should be green (peak)
    else if (i === 4 || i === 6) rowColor = 'background: #fff3cd;'; // May/July should be yellow (high)
    else if (i === 11 || i === 0) rowColor = 'background: #f8d7da;'; // Dec/Jan should be red (low)

    return `
      <tr style="${rowColor}">
        <td style="padding: 8px; border: 1px solid #dee2e6; font-weight: ${i === 5 ? 'bold' : 'normal'};">${monthNames[i]}</td>
        <td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">${mwh}</td>
        <td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">${hours}</td>
        <td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">${avgKW}</td>
        <td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">${percent}%</td>
      </tr>
    `;
  }).join('');

  // Update footer totals
  document.getElementById('totalProduction').textContent = formatNumberEU(totalAnnual / 1000, 2) + ' MWh';
  document.getElementById('totalHours').textContent = totalHoursCount;
  document.getElementById('avgPower').textContent = totalHoursCount > 0 ? formatNumberEU(totalAnnual / totalHoursCount, 2) + ' kW' : '0,00 kW';

  const ctx = document.getElementById('monthlyProduction').getContext('2d');

  if (monthlyProductionChart) monthlyProductionChart.destroy();

  monthlyProductionChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: monthNames,
      datasets: [{
        label: 'Produkcja [MWh]',
        data: monthlyMWh,
        backgroundColor: 'rgba(243, 156, 18, 0.7)',
        borderColor: '#f39c12',
        borderWidth: 2
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
          beginAtZero: true,
          title: { display: true, text: 'Produkcja [MWh]' }
        }
      }
    }
  });
}

// Generate PV vs Consumption comparison
function generatePVvsConsumption() {
  console.log('📈 generatePVvsConsumption() called');
  console.log('  - productionData:', productionData ? 'EXISTS' : 'NULL');
  console.log('  - productionData.hourlyProduction length:', productionData?.hourlyProduction?.length);
  console.log('  - consumptionData:', consumptionData ? 'EXISTS' : 'NULL');
  console.log('  - consumptionData.hourlyData.values length:', consumptionData?.hourlyData?.values?.length);

  if (!productionData || !consumptionData) {
    console.log('❌ generatePVvsConsumption: Missing required data');
    return;
  }

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;

  console.log('  - Production first 5 values:', production?.slice(0, 5));
  console.log('  - Consumption first 5 values:', consumption?.slice(0, 5));

  // Daily averages with self-consumption
  const hours = Math.min(production.length, consumption.length);
  const days = Math.floor(hours / 24);
  const displayDays = Math.min(days, 30);

  const dailyProd = new Array(displayDays).fill(0);
  const dailyCons = new Array(displayDays).fill(0);
  const dailySelfCons = new Array(displayDays).fill(0);

  for (let day = 0; day < displayDays; day++) {
    for (let hour = 0; hour < 24; hour++) {
      const idx = day * 24 + hour;
      const prod = production[idx] || 0;
      const cons = consumption[idx] || 0;
      const selfCons = Math.min(prod, cons); // Self-consumption = min(production, consumption)

      dailyProd[day] += prod;
      dailyCons[day] += cons;
      dailySelfCons[day] += selfCons;
    }
    dailyProd[day] = (dailyProd[day] / 1000).toFixed(2); // kWh -> MWh
    dailyCons[day] = (dailyCons[day] / 1000).toFixed(2);
    dailySelfCons[day] = (dailySelfCons[day] / 1000).toFixed(2);
  }

  const ctx = document.getElementById('pvVsConsumption').getContext('2d');

  if (pvVsConsumptionChart) pvVsConsumptionChart.destroy();

  pvVsConsumptionChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array.from({ length: displayDays }, (_, i) => `Dzień ${i + 1}`),
      datasets: [
        {
          label: 'Zużycie [MWh]',
          data: dailyCons,
          borderColor: '#667eea',
          backgroundColor: 'rgba(102, 126, 234, 0.2)',
          borderWidth: 2,
          fill: true,
          order: 3
        },
        {
          label: 'Produkcja PV [MWh]',
          data: dailyProd,
          borderColor: '#f39c12',
          backgroundColor: 'rgba(243, 156, 18, 0.2)',
          borderWidth: 2,
          fill: true,
          order: 2
        },
        {
          label: 'Autokonsumpcja [MWh]',
          data: dailySelfCons,
          borderColor: '#27ae60',
          backgroundColor: 'rgba(39, 174, 96, 0.3)',
          borderWidth: 3,
          fill: true,
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true },
        tooltip: {
          mode: 'index',
          intersect: false
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Energia [MWh]' }
        }
      }
    }
  });
}

// Calculate moving average for trend line
function calculateMovingAverage(data, windowSize) {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < windowSize - 1) {
      // Not enough data yet - use what we have
      const slice = data.slice(0, i + 1);
      const avg = slice.reduce((sum, val) => sum + val, 0) / slice.length;
      result.push(avg);
    } else {
      // Full window available
      const slice = data.slice(i - windowSize + 1, i + 1);
      const avg = slice.reduce((sum, val) => sum + val, 0) / windowSize;
      result.push(avg);
    }
  }
  return result;
}

// Generate hourly profile with DC/AC ratio clipping for 14 days
function generateHourlyProfile() {
  console.log('⏱️ generateHourlyProfile() called');
  if (!productionData || !consumptionData) {
    console.error('❌ Missing data - productionData:', !!productionData, 'consumptionData:', !!consumptionData);
    return;
  }

  // Save current checkbox states BEFORE destroying chart
  const checkboxStates = {
    load: document.getElementById('toggleLoad')?.checked ?? true,
    pv: document.getElementById('togglePV')?.checked ?? true,
    selfcons: document.getElementById('toggleSelfCons')?.checked ?? true,
    selfconsbess: document.getElementById('toggleSelfConsBess')?.checked ?? true,
    trendload: document.getElementById('toggleTrendLoad')?.checked ?? false,
    trendpv: document.getElementById('toggleTrendPV')?.checked ?? false,
    trendselfcons: document.getElementById('toggleTrendSelfCons')?.checked ?? false,
    trendselfconsbess: document.getElementById('toggleTrendSelfConsBess')?.checked ?? false
  };
  console.log('📊 Saved checkbox states:', checkboxStates);

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;
  const timestamps = consumptionData.hourlyData.timestamps;

  console.log('📊 Data lengths - production:', production?.length, 'consumption:', consumption?.length, 'timestamps:', timestamps?.length);

  // Get capacity and DC/AC ratio from variant
  let capacity_kW = 10000; // Default
  let dcAcRatio = 1.2; // Default DC/AC ratio

  if (analysisResults && variants && currentVariant) {
    const variant = variants[currentVariant];
    if (variant && variant.capacity) {
      capacity_kW = variant.capacity;
    }
  }

  // AC capacity limit (inverter clipping)
  const acCapacityLimit = capacity_kW / dcAcRatio;
  console.log('  - DC Capacity:', capacity_kW, 'kW');
  console.log('  - DC/AC Ratio:', dcAcRatio);
  console.log('  - AC Limit:', acCapacityLimit.toFixed(2), 'kW');

  // Display FULL YEAR (all available hours) - typically 8760 hours
  const hoursToShow = production.length;

  const labels = [];
  const prodData = [];
  const consData = [];
  const selfConsData = [];
  const selfConsBessData = []; // Self-consumption WITH BESS

  // Check if BESS is enabled for current variant
  let hasBess = false;
  let bessDischargedTotal = 0;
  if (variants && variants[currentVariant]) {
    const variant = variants[currentVariant];
    hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
    bessDischargedTotal = variant.bess_discharged_kwh || variant.bess_self_consumed_from_bess_kwh || 0;
  }

  // If BESS enabled, show checkbox controls
  const bessLabelEl = document.getElementById('toggleSelfConsBessLabel');
  const bessTrendLabelEl = document.getElementById('toggleTrendSelfConsBessLabel');
  if (bessLabelEl) bessLabelEl.style.display = hasBess ? 'flex' : 'none';
  if (bessTrendLabelEl) bessTrendLabelEl.style.display = hasBess ? 'flex' : 'none';

  // Calculate per-hour BESS contribution (simplified: distribute evenly based on surplus hours)
  // In reality this would come from hourly simulation, but we approximate
  let bessPerHourContribution = 0;
  if (hasBess && hoursToShow > 0) {
    // Count hours where PV > consumption (surplus hours when battery charges)
    // and hours where PV < consumption (deficit hours when battery discharges)
    let deficitHours = 0;
    for (let idx = 0; idx < hoursToShow; idx++) {
      const prodRaw = production[idx] || 0;
      const prodAC = Math.min(prodRaw, acCapacityLimit);
      const cons = consumption[idx] || 0;
      if (cons > prodAC && prodAC > 0) deficitHours++; // Hours where we can use stored energy
    }
    // Distribute BESS discharge over deficit hours
    bessPerHourContribution = deficitHours > 0 ? bessDischargedTotal / deficitHours : 0;
    console.log('🔋 BESS hourly contribution:', bessPerHourContribution.toFixed(2), 'kW over', deficitHours, 'deficit hours');
  }

  for (let idx = 0; idx < hoursToShow; idx++) {
    // Apply DC/AC ratio clipping to production
    let prodRaw = production[idx] || 0;
    const prodAC = Math.min(prodRaw, acCapacityLimit); // Inverter clipping

    const cons = consumption[idx] || 0;
    const selfCons = Math.min(prodAC, cons); // Self-consumption with AC production

    // Self-consumption with BESS: add battery discharge during deficit hours
    let selfConsBess = selfCons;
    if (hasBess && cons > prodAC && prodAC > 0) {
      // Deficit hour - battery can discharge
      const deficit = cons - prodAC;
      const bessContrib = Math.min(bessPerHourContribution, deficit);
      selfConsBess = selfCons + bessContrib;
    }

    // Label: show date for every 168th hour (weekly) to avoid clutter
    let label = '';
    if (timestamps && timestamps[idx]) {
      const date = new Date(timestamps[idx]);
      if (idx % 168 === 0) { // Every 7 days
        label = `${date.getMonth()+1}/${date.getDate()}`;
      }
    }

    labels.push(label);
    prodData.push(prodAC / 1000); // kW -> MW (as number, not string)
    consData.push(cons / 1000);
    selfConsData.push(selfCons / 1000);
    selfConsBessData.push(selfConsBess / 1000);
  }

  console.log('  - Hours displayed:', hoursToShow);
  console.log('  - Max PV AC:', Math.max(...prodData).toFixed(2), 'MW');
  console.log('  - Total production:', prodData.reduce((sum, v) => sum + v, 0).toFixed(2), 'MWh');
  console.log('  - Total consumption:', consData.reduce((sum, v) => sum + v, 0).toFixed(2), 'MWh');
  console.log('  - Total self-consumption:', selfConsData.reduce((sum, v) => sum + v, 0).toFixed(2), 'MWh');
  if (hasBess) {
    console.log('  - Total self-consumption + BESS:', selfConsBessData.reduce((sum, v) => sum + v, 0).toFixed(2), 'MWh');
  }

  // Calculate 7-day moving average (168 hours) for trend lines
  const window = 168; // 7 days
  const prodTrend = calculateMovingAverage(prodData, window);
  const consTrend = calculateMovingAverage(consData, window);
  const selfConsTrend = calculateMovingAverage(selfConsData, window);
  const selfConsBessTrend = hasBess ? calculateMovingAverage(selfConsBessData, window) : [];

  console.log('  - Calculated trend lines with', window, 'hour window');

  console.log('Sample prodData (first 5):', prodData.slice(0, 5));
  console.log('Sample consData (first 5):', consData.slice(0, 5));
  console.log('Sample selfConsData (first 5):', selfConsData.slice(0, 5));

  if (prodData.length === 0) {
    console.error('❌ NO DATA GENERATED for hourly profile!');
    return;
  }

  const ctx = document.getElementById('hourlyProfile').getContext('2d');

  if (hourlyProfileChart) hourlyProfileChart.destroy();

  hourlyProfileChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Autokonsumpcja [MW]',
          data: selfConsData,
          borderColor: 'rgba(39, 174, 96, 0.8)',
          backgroundColor: 'rgba(39, 174, 96, 0.4)',
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          order: 6, // Bottom layer
          tension: 0.2,
          hidden: !checkboxStates.selfcons // Use saved state
        },
        {
          label: 'Produkcja PV [MW]',
          data: prodData,
          borderColor: 'rgba(243, 156, 18, 0.9)',
          backgroundColor: 'rgba(243, 156, 18, 0.3)',
          borderWidth: 2.5,
          fill: true,
          pointRadius: 0,
          order: 5, // Middle layer
          tension: 0.2,
          hidden: !checkboxStates.pv // Use saved state
        },
        {
          label: 'Zużycie (Load) [MW]',
          data: consData,
          borderColor: '#e74c3c',
          backgroundColor: 'rgba(231, 76, 60, 0.0)',
          borderWidth: 3,
          fill: false,
          pointRadius: 0,
          order: 4, // Top layer - most visible
          tension: 0.2,
          hidden: !checkboxStates.load // Use saved state
        },
        // TREND LINES (7-day moving average)
        {
          label: 'Trend Autokonsumpcja (7d MA)',
          data: selfConsTrend,
          borderColor: 'rgba(39, 174, 96, 1.0)',
          backgroundColor: 'transparent',
          borderWidth: 3,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          order: 3,
          tension: 0.4,
          hidden: !checkboxStates.trendselfcons // Use saved state
        },
        {
          label: 'Trend PV (7d MA)',
          data: prodTrend,
          borderColor: 'rgba(243, 156, 18, 1.0)',
          backgroundColor: 'transparent',
          borderWidth: 3,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          order: 2,
          tension: 0.4,
          hidden: !checkboxStates.trendpv // Use saved state
        },
        {
          label: 'Trend Load (7d MA)',
          data: consTrend,
          borderColor: 'rgba(231, 76, 60, 1.0)',
          backgroundColor: 'transparent',
          borderWidth: 3,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          order: 1,
          tension: 0.4,
          hidden: !checkboxStates.trendload // Use saved state
        },
        // BESS datasets (only shown when BESS is enabled)
        {
          label: 'Autokonsumpcja + BESS [MW]',
          data: hasBess ? selfConsBessData : [],
          borderColor: '#9c27b0',
          backgroundColor: 'rgba(156, 39, 176, 0.3)',
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          order: 7, // Below regular self-consumption
          tension: 0.2,
          hidden: !hasBess || !checkboxStates.selfconsbess
        },
        {
          label: 'Trend Auto+BESS (7d MA)',
          data: hasBess ? selfConsBessTrend : [],
          borderColor: '#9c27b0',
          backgroundColor: 'transparent',
          borderWidth: 3,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          order: 0,
          tension: 0.4,
          hidden: !hasBess || !checkboxStates.trendselfconsbess
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false, // Allow flexible height for 8760 points
      interaction: {
        mode: 'nearest',
        axis: 'x',
        intersect: false
      },
      plugins: {
        legend: {
          display: true,
          position: 'top'
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            title: function(context) {
              const idx = context[0].dataIndex;
              if (timestamps && timestamps[idx]) {
                const date = new Date(timestamps[idx]);
                return `${date.toLocaleDateString('pl-PL')} ${date.getHours()}:00`;
              }
              return context[0].label;
            }
          }
        },
        decimation: {
          enabled: true,
          algorithm: 'lttb', // Largest-Triangle-Three-Buckets for better visual representation
          samples: 2000 // Reduce 8760 points to ~2000 for rendering performance
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Moc [MW]' },
          ticks: {
            callback: function(value) {
              return value.toFixed(2) + ' MW';
            }
          }
        },
        x: {
          title: {
            display: true,
            text: getHourlyChartXAxisLabel()
          },
          ticks: {
            maxTicksLimit: 52, // ~weekly ticks
            autoSkip: true
          }
        }
      }
    }
  });
}

// Toggle visibility of hourly profile layers
function toggleHourlyProfileLayer(layer) {
  if (!hourlyProfileChart) return;

  const datasetMap = {
    'load': 2,              // Load data
    'pv': 1,                // PV data
    'selfcons': 0,          // Self-consumption data
    'trendload': 5,         // Trend Load (7d MA)
    'trendpv': 4,           // Trend PV (7d MA)
    'trendselfcons': 3,     // Trend Self-consumption (7d MA)
    'selfconsbess': 6,      // Self-consumption + BESS
    'trendselfconsbess': 7  // Trend Self-consumption + BESS (7d MA)
  };

  const datasetIndex = datasetMap[layer];
  if (datasetIndex === undefined) return;

  const dataset = hourlyProfileChart.data.datasets[datasetIndex];
  if (!dataset) return; // BESS datasets might not exist

  // Get checkbox ID
  let checkboxId;
  if (layer === 'load') checkboxId = 'toggleLoad';
  else if (layer === 'pv') checkboxId = 'togglePV';
  else if (layer === 'selfcons') checkboxId = 'toggleSelfCons';
  else if (layer === 'trendload') checkboxId = 'toggleTrendLoad';
  else if (layer === 'trendpv') checkboxId = 'toggleTrendPV';
  else if (layer === 'trendselfcons') checkboxId = 'toggleTrendSelfCons';
  else if (layer === 'selfconsbess') checkboxId = 'toggleSelfConsBess';
  else if (layer === 'trendselfconsbess') checkboxId = 'toggleTrendSelfConsBess';

  const checkbox = document.getElementById(checkboxId);

  if (checkbox && checkbox.checked) {
    // Show layer
    dataset.hidden = false;
  } else {
    // Hide layer
    dataset.hidden = true;
  }

  hourlyProfileChart.update();
  console.log(`Layer "${layer}" visibility:`, !dataset.hidden);
}

// Generate Daylight Profile (only PV working hours)
function generateDaylightProfile() {
  console.log('🌅 generateDaylightProfile() called');
  if (!productionData || !consumptionData) {
    console.error('❌ Missing data - productionData:', !!productionData, 'consumptionData:', !!consumptionData);
    return;
  }

  // Save current checkbox states BEFORE destroying chart
  const checkboxStates = {
    load: document.getElementById('toggleLoadDaylight')?.checked ?? true,
    pv: document.getElementById('togglePVDaylight')?.checked ?? true,
    selfcons: document.getElementById('toggleSelfConsDaylight')?.checked ?? true,
    selfconsbess: document.getElementById('toggleSelfConsBessDaylight')?.checked ?? true,
    trendload: document.getElementById('toggleTrendLoadDaylight')?.checked ?? false,
    trendpv: document.getElementById('toggleTrendPVDaylight')?.checked ?? false,
    trendselfcons: document.getElementById('toggleTrendSelfConsDaylight')?.checked ?? false,
    trendselfconsbess: document.getElementById('toggleTrendSelfConsBessDaylight')?.checked ?? false
  };
  console.log('📊 Daylight saved checkbox states:', checkboxStates);

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;
  const timestamps = consumptionData.hourlyData.timestamps;

  console.log('📊 Data lengths - production:', production?.length, 'consumption:', consumption?.length, 'timestamps:', timestamps?.length);

  // Day length per month (from generateHourlyProduction)
  const dayLengthHours = [8, 10, 12, 14, 16, 16, 16, 14, 12, 10, 8, 8];

  // Filter to only daylight hours
  const daylightLabels = [];
  const daylightProd = [];
  const daylightCons = [];
  const daylightSelfCons = [];
  const daylightSelfConsBess = []; // Self-consumption WITH BESS

  // Check if BESS is enabled for current variant
  let hasBess = false;
  let bessDischargedTotal = 0;
  if (variants && variants[currentVariant]) {
    const variant = variants[currentVariant];
    hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
    bessDischargedTotal = variant.bess_discharged_kwh || variant.bess_self_consumed_from_bess_kwh || 0;
  }

  // If BESS enabled, show checkbox controls
  const bessLabelEl = document.getElementById('toggleSelfConsBessDaylightLabel');
  const bessTrendLabelEl = document.getElementById('toggleTrendSelfConsBessDaylightLabel');
  if (bessLabelEl) bessLabelEl.style.display = hasBess ? 'flex' : 'none';
  if (bessTrendLabelEl) bessTrendLabelEl.style.display = hasBess ? 'flex' : 'none';

  // Get capacity for DC/AC clipping
  const capacity = pvConfig?.capacity || 10000;
  const inverterLimit = capacity / 1.2;

  // First pass: count deficit daylight hours for BESS distribution
  let deficitDaylightHours = 0;
  if (hasBess) {
    for (let idx = 0; idx < Math.min(production.length, consumption.length, timestamps.length); idx++) {
      const date = new Date(timestamps[idx]);
      const month = date.getMonth();
      const hour = date.getHours();
      const dayLength = dayLengthHours[month];
      const sunrise = Math.floor(12 - dayLength / 2);
      const sunset = Math.floor(12 + dayLength / 2);

      if (hour >= sunrise && hour < sunset) {
        const pvAC = Math.min(production[idx], inverterLimit);
        const load = consumption[idx];
        if (load > pvAC && pvAC > 0) deficitDaylightHours++;
      }
    }
  }
  const bessPerHourContribution = deficitDaylightHours > 0 ? bessDischargedTotal / deficitDaylightHours : 0;
  if (hasBess) {
    console.log('🔋 BESS daylight contribution:', bessPerHourContribution.toFixed(2), 'kW over', deficitDaylightHours, 'deficit daylight hours');
  }

  for (let idx = 0; idx < Math.min(production.length, consumption.length, timestamps.length); idx++) {
    const date = new Date(timestamps[idx]);
    const month = date.getMonth();
    const hour = date.getHours();

    // Calculate sunrise/sunset for this month
    const dayLength = dayLengthHours[month];
    const sunrise = Math.floor(12 - dayLength / 2);
    const sunset = Math.floor(12 + dayLength / 2);

    // Only include if hour is between sunrise and sunset (when PV can produce)
    if (hour >= sunrise && hour < sunset) {
      daylightLabels.push(idx);

      // Apply DC/AC clipping (inverter capacity limit)
      const pvAC = Math.min(production[idx], inverterLimit);

      const load = consumption[idx];
      const selfCons = Math.min(load, pvAC);

      // Self-consumption with BESS: add battery discharge during deficit hours
      let selfConsBess = selfCons;
      if (hasBess && load > pvAC && pvAC > 0) {
        const deficit = load - pvAC;
        const bessContrib = Math.min(bessPerHourContribution, deficit);
        selfConsBess = selfCons + bessContrib;
      }

      daylightProd.push(pvAC / 1000); // kW → MW (as number, not string)
      daylightCons.push(load / 1000);
      daylightSelfCons.push(selfCons / 1000);
      daylightSelfConsBess.push(selfConsBess / 1000);
    }
  }

  console.log(`Daylight profile: ${daylightLabels.length} hours out of ${production.length} total hours`);
  console.log('Sample data - first 5 PV values:', daylightProd.slice(0, 5));
  console.log('Sample data - first 5 Load values:', daylightCons.slice(0, 5));
  console.log('Max PV:', Math.max(...daylightProd).toFixed(3), 'MW');
  console.log('Max Load:', Math.max(...daylightCons).toFixed(3), 'MW');
  if (hasBess) {
    console.log('Total daylight self-consumption + BESS:', daylightSelfConsBess.reduce((sum, v) => sum + v, 0).toFixed(2), 'MWh');
  }

  if (daylightLabels.length === 0) {
    console.error('❌ NO DAYLIGHT DATA - check sunrise/sunset logic');
    return;
  }

  // Calculate 7-day moving average (168 hours) for trend lines
  const window = 168;
  const prodTrend = calculateMovingAverage(daylightProd, window);
  const consTrend = calculateMovingAverage(daylightCons, window);
  const selfConsTrend = calculateMovingAverage(daylightSelfCons, window);
  const selfConsBessTrend = hasBess ? calculateMovingAverage(daylightSelfConsBess, window) : [];

  console.log('Trend lines calculated - lengths:', prodTrend.length, consTrend.length, selfConsTrend.length);

  const ctx = document.getElementById('daylightProfile').getContext('2d');

  if (daylightProfileChart) daylightProfileChart.destroy();

  daylightProfileChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: daylightLabels,
      datasets: [
        // Dataset 0: Self-consumption data (bottom layer, green)
        {
          label: 'Autokonsumpcja [MW]',
          data: daylightSelfCons,
          backgroundColor: 'rgba(39, 174, 96, 0.4)',
          borderColor: '#27ae60',
          borderWidth: 1,
          fill: true,
          pointRadius: 0,
          tension: 0,
          order: 6,
          hidden: !checkboxStates.selfcons // Use saved state
        },
        // Dataset 1: PV Production data (middle layer, orange)
        {
          label: 'Produkcja PV [MW]',
          data: daylightProd,
          backgroundColor: 'rgba(243, 156, 18, 0.3)',
          borderColor: '#f39c12',
          borderWidth: 1,
          fill: true,
          pointRadius: 0,
          tension: 0,
          order: 5,
          hidden: !checkboxStates.pv // Use saved state
        },
        // Dataset 2: Load data (top layer, red)
        {
          label: 'Zużycie (Load) [MW]',
          data: daylightCons,
          backgroundColor: 'rgba(231, 76, 60, 0.15)',
          borderColor: '#e74c3c',
          borderWidth: 2,
          fill: false,
          pointRadius: 0,
          tension: 0,
          order: 4,
          hidden: !checkboxStates.load // Use saved state
        },
        // Dataset 3: Trend Self-consumption (7d MA, dashed green)
        {
          label: 'Trend Autokonsumpcja (7d MA)',
          data: selfConsTrend,
          backgroundColor: 'transparent',
          borderColor: '#27ae60',
          borderWidth: 2,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          tension: 0.4,
          hidden: !checkboxStates.trendselfcons, // Use saved state
          order: 3
        },
        // Dataset 4: Trend PV (7d MA, dashed orange)
        {
          label: 'Trend PV (7d MA)',
          data: prodTrend,
          backgroundColor: 'transparent',
          borderColor: '#f39c12',
          borderWidth: 2,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          tension: 0.4,
          hidden: !checkboxStates.trendpv, // Use saved state
          order: 2
        },
        // Dataset 5: Trend Load (7d MA, dashed red)
        {
          label: 'Trend Load (7d MA)',
          data: consTrend,
          backgroundColor: 'transparent',
          borderColor: '#e74c3c',
          borderWidth: 2,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          tension: 0.4,
          hidden: !checkboxStates.trendload, // Use saved state
          order: 1
        },
        // BESS datasets (only shown when BESS is enabled)
        // Dataset 6: Self-consumption + BESS (purple)
        {
          label: 'Autokonsumpcja + BESS [MW]',
          data: hasBess ? daylightSelfConsBess : [],
          borderColor: '#9c27b0',
          backgroundColor: 'rgba(156, 39, 176, 0.3)',
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
          tension: 0,
          order: 7, // Below regular self-consumption
          hidden: !hasBess || !checkboxStates.selfconsbess
        },
        // Dataset 7: Trend Self-consumption + BESS (7d MA, dashed purple)
        {
          label: 'Trend Auto+BESS (7d MA)',
          data: hasBess ? selfConsBessTrend : [],
          backgroundColor: 'transparent',
          borderColor: '#9c27b0',
          borderWidth: 2,
          borderDash: [5, 5],
          fill: false,
          pointRadius: 0,
          tension: 0.4,
          hidden: !hasBess || !checkboxStates.trendselfconsbess,
          order: 0
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
          display: true,
          position: 'top'
        },
        title: {
          display: false
        },
        decimation: {
          enabled: true,
          algorithm: 'lttb',
          samples: 2000
        },
        tooltip: {
          callbacks: {
            title: function(context) {
              const hourIndex = context[0].label;
              if (timestamps[hourIndex]) {
                const date = new Date(timestamps[hourIndex]);
                return date.toLocaleString('pl-PL', {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit'
                });
              }
              return `Godzina ${hourIndex}`;
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          title: {
            display: true,
            text: 'Godziny (tylko daylight)'
          },
          ticks: {
            callback: function(value) {
              // Show every ~500 hours
              if (value % 500 === 0) {
                return value;
              }
              return '';
            }
          }
        },
        y: {
          title: {
            display: true,
            text: 'Moc [MW]'
          },
          beginAtZero: true
        }
      }
    }
  });
}

// Toggle visibility of daylight profile layers
function toggleDaylightLayer(layer) {
  if (!daylightProfileChart) return;

  const datasetMap = {
    'load': 2,              // Load data
    'pv': 1,                // PV data
    'selfcons': 0,          // Self-consumption data
    'trendload': 5,         // Trend Load (7d MA)
    'trendpv': 4,           // Trend PV (7d MA)
    'trendselfcons': 3,     // Trend Self-consumption (7d MA)
    'selfconsbess': 6,      // Self-consumption + BESS
    'trendselfconsbess': 7  // Trend Self-consumption + BESS (7d MA)
  };

  const checkboxMap = {
    'load': 'toggleLoadDaylight',
    'pv': 'togglePVDaylight',
    'selfcons': 'toggleSelfConsDaylight',
    'trendload': 'toggleTrendLoadDaylight',
    'trendpv': 'toggleTrendPVDaylight',
    'trendselfcons': 'toggleTrendSelfConsDaylight',
    'selfconsbess': 'toggleSelfConsBessDaylight',
    'trendselfconsbess': 'toggleTrendSelfConsBessDaylight'
  };

  const datasetIndex = datasetMap[layer];
  if (datasetIndex === undefined) {
    console.error('Unknown layer:', layer);
    return;
  }

  const dataset = daylightProfileChart.data.datasets[datasetIndex];
  if (!dataset) return; // BESS datasets might not exist

  const checkboxId = checkboxMap[layer];
  const checkbox = document.getElementById(checkboxId);

  if (checkbox && checkbox.checked) {
    dataset.hidden = false;
  } else {
    dataset.hidden = true;
  }

  daylightProfileChart.update();
  console.log(`Daylight layer "${layer}" visibility:`, !dataset.hidden);
}

// Generate energy balance chart
function generateEnergyBalance() {
  if (!productionData || !consumptionData) return;

  const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;

  const monthlyProd = new Array(12).fill(0);
  const monthlyCons = new Array(12).fill(0);

  const hours = Math.min(production.length, consumption.length);

  for (let i = 0; i < hours; i++) {
    const month = Math.floor((i / 24) / 30.44) % 12;
    monthlyProd[month] += production[i] || 0;
    monthlyCons[month] += consumption[i] || 0;
  }

  const balance = monthlyProd.map((prod, i) => ((prod - monthlyCons[i]) / 1000).toFixed(2));

  const ctx = document.getElementById('energyBalance').getContext('2d');

  if (energyBalanceChart) energyBalanceChart.destroy();

  energyBalanceChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: monthNames,
      datasets: [{
        label: 'Bilans [MWh]',
        data: balance,
        backgroundColor: balance.map(v => v >= 0 ? 'rgba(46, 204, 113, 0.7)' : 'rgba(231, 76, 60, 0.7)'),
        borderColor: balance.map(v => v >= 0 ? '#2ecc71' : '#e74c3c'),
        borderWidth: 2
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
          title: { display: true, text: 'Bilans [MWh]' }
        }
      }
    }
  });
}

// Export production analysis
function exportProduction() {
  if (!productionData && !pvConfig) {
    alert('Brak danych do eksportu');
    return;
  }

  const stats = calculateStatistics();

  const report = {
    analyzedAt: new Date().toISOString(),
    statistics: stats,
    pvConfig: pvConfig,
    productionData: productionData
  };

  const dataStr = JSON.stringify(report, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(dataBlob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `analiza-produkcji-pv-${new Date().toISOString().split('T')[0]}.json`;
  link.click();

  URL.revokeObjectURL(url);
}

// Export Hourly Profile to Excel
function exportHourlyProfileToExcel() {
  if (!productionData || !consumptionData) {
    alert('Brak danych do eksportu');
    return;
  }

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;
  const timestamps = consumptionData.hourlyData.timestamps;

  // Prepare data array
  const data = [];
  data.push(['Godzina', 'Timestamp', 'Produkcja PV [kW]', 'Zużycie Load [kW]', 'Autokonsumpcja [kW]', 'Nadwyżka [kW]', 'Deficyt [kW]']);

  const capacity = pvConfig?.capacity || 10000;
  const inverterLimit = capacity / 1.2;

  for (let i = 0; i < Math.min(production.length, consumption.length, timestamps.length); i++) {
    const pvAC = Math.min(production[i], inverterLimit);
    const load = consumption[i];
    const selfCons = Math.min(load, pvAC);
    const surplus = Math.max(0, pvAC - load);
    const deficit = Math.max(0, load - pvAC);

    const date = new Date(timestamps[i]);
    const timestamp = date.toLocaleString('pl-PL');

    data.push([
      i + 1,
      timestamp,
      pvAC.toFixed(2),
      load.toFixed(2),
      selfCons.toFixed(2),
      surplus.toFixed(2),
      deficit.toFixed(2)
    ]);
  }

  // Create workbook and worksheet
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(data);

  // Set column widths
  ws['!cols'] = [
    { wch: 10 },  // Godzina
    { wch: 20 },  // Timestamp
    { wch: 18 },  // Produkcja PV
    { wch: 18 },  // Zużycie Load
    { wch: 20 },  // Autokonsumpcja
    { wch: 15 },  // Nadwyżka
    { wch: 15 }   // Deficyt
  ];

  XLSX.utils.book_append_sheet(wb, ws, 'Profil Roczny 8760h');

  // Generate filename with date
  const filename = `Profil_Godzinowy_Roczny_${new Date().toISOString().split('T')[0]}.xlsx`;

  // Download file
  XLSX.writeFile(wb, filename);
}

// Export Daylight Profile to Excel
function exportDaylightProfileToExcel() {
  if (!productionData || !consumptionData) {
    alert('Brak danych do eksportu');
    return;
  }

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;
  const timestamps = consumptionData.hourlyData.timestamps;

  // Day length per month
  const dayLengthHours = [8, 10, 12, 14, 16, 16, 16, 14, 12, 10, 8, 8];

  // Prepare data array
  const data = [];
  data.push(['Indeks Daylight', 'Godzina Roczna', 'Timestamp', 'Produkcja PV [kW]', 'Zużycie Load [kW]', 'Autokonsumpcja [kW]', 'Nadwyżka [kW]', 'Deficyt [kW]']);

  const capacity = pvConfig?.capacity || 10000;
  const inverterLimit = capacity / 1.2;

  let daylightIndex = 1;

  for (let idx = 0; idx < Math.min(production.length, consumption.length, timestamps.length); idx++) {
    const date = new Date(timestamps[idx]);
    const month = date.getMonth();
    const hour = date.getHours();

    // Calculate sunrise/sunset for this month
    const dayLength = dayLengthHours[month];
    const sunrise = Math.floor(12 - dayLength / 2);
    const sunset = Math.floor(12 + dayLength / 2);

    // Only include if hour is between sunrise and sunset
    if (hour >= sunrise && hour < sunset) {
      const pvAC = Math.min(production[idx], inverterLimit);
      const load = consumption[idx];
      const selfCons = Math.min(load, pvAC);
      const surplus = Math.max(0, pvAC - load);
      const deficit = Math.max(0, load - pvAC);

      const timestamp = date.toLocaleString('pl-PL');

      data.push([
        daylightIndex,
        idx + 1,
        timestamp,
        pvAC.toFixed(2),
        load.toFixed(2),
        selfCons.toFixed(2),
        surplus.toFixed(2),
        deficit.toFixed(2)
      ]);

      daylightIndex++;
    }
  }

  // Create workbook and worksheet
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(data);

  // Set column widths
  ws['!cols'] = [
    { wch: 15 },  // Indeks Daylight
    { wch: 15 },  // Godzina Roczna
    { wch: 20 },  // Timestamp
    { wch: 18 },  // Produkcja PV
    { wch: 18 },  // Zużycie Load
    { wch: 20 },  // Autokonsumpcja
    { wch: 15 },  // Nadwyżka
    { wch: 15 }   // Deficyt
  ];

  XLSX.utils.book_append_sheet(wb, ws, 'Profil Daylight');

  // Generate filename with date
  const filename = `Profil_Godzinowy_Daylight_${new Date().toISOString().split('T')[0]}.xlsx`;

  // Download file
  XLSX.writeFile(wb, filename);
}

// Export Monthly Production to Excel
function exportMonthlyProductionToExcel() {
  if (!productionData || !consumptionData) {
    alert('Brak danych do eksportu');
    return;
  }

  const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec', 'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

  const production = productionData.hourlyProduction;
  const consumption = consumptionData.hourlyData.values;
  const timestamps = consumptionData.hourlyData.timestamps;

  // Calculate monthly totals
  const monthlyProd = new Array(12).fill(0);
  const monthlyCons = new Array(12).fill(0);
  const hoursPerMonth = new Array(12).fill(0);

  for (let idx = 0; idx < Math.min(production.length, consumption.length, timestamps.length); idx++) {
    const date = new Date(timestamps[idx]);
    const month = date.getMonth(); // 0-11
    monthlyProd[month] += production[idx] || 0;
    monthlyCons[month] += consumption[idx] || 0;
    hoursPerMonth[month]++;
  }

  // Prepare data array
  const data = [];
  data.push(['Miesiąc', 'Produkcja PV [MWh]', 'Zużycie Load [MWh]', 'Autokonsumpcja [MWh]', 'Nadwyżka [MWh]', 'Deficyt [MWh]', 'Bilans [MWh]', 'Godziny Danych', 'Śr. Moc PV [kW]', '% Rocznej Produkcji']);

  const totalProd = monthlyProd.reduce((a, b) => a + b, 0);

  for (let m = 0; m < 12; m++) {
    const prodMWh = (monthlyProd[m] / 1000).toFixed(2);
    const consMWh = (monthlyCons[m] / 1000).toFixed(2);
    const selfConsMWh = (Math.min(monthlyProd[m], monthlyCons[m]) / 1000).toFixed(2);
    const surplusMWh = (Math.max(0, monthlyProd[m] - monthlyCons[m]) / 1000).toFixed(2);
    const deficitMWh = (Math.max(0, monthlyCons[m] - monthlyProd[m]) / 1000).toFixed(2);
    const balanceMWh = ((monthlyProd[m] - monthlyCons[m]) / 1000).toFixed(2);
    const avgPowerKW = hoursPerMonth[m] > 0 ? (monthlyProd[m] / hoursPerMonth[m]).toFixed(2) : '0.00';
    const percentOfTotal = totalProd > 0 ? ((monthlyProd[m] / totalProd) * 100).toFixed(1) : '0.0';

    data.push([
      monthNames[m],
      prodMWh,
      consMWh,
      selfConsMWh,
      surplusMWh,
      deficitMWh,
      balanceMWh,
      hoursPerMonth[m],
      avgPowerKW,
      percentOfTotal + '%'
    ]);
  }

  // Add totals row
  const totalConsMWh = (monthlyCons.reduce((a, b) => a + b, 0) / 1000).toFixed(2);
  const totalSelfConsMWh = (monthlyProd.reduce((sum, prod, idx) => sum + Math.min(prod, monthlyCons[idx]), 0) / 1000).toFixed(2);
  const totalSurplusMWh = (monthlyProd.reduce((sum, prod, idx) => sum + Math.max(0, prod - monthlyCons[idx]), 0) / 1000).toFixed(2);
  const totalDeficitMWh = (monthlyCons.reduce((sum, cons, idx) => sum + Math.max(0, cons - monthlyProd[idx]), 0) / 1000).toFixed(2);
  const totalBalanceMWh = ((totalProd - monthlyCons.reduce((a, b) => a + b, 0)) / 1000).toFixed(2);
  const totalHours = hoursPerMonth.reduce((a, b) => a + b, 0);
  const avgPowerTotal = totalHours > 0 ? (totalProd / totalHours).toFixed(2) : '0.00';

  data.push([
    'RAZEM',
    (totalProd / 1000).toFixed(2),
    totalConsMWh,
    totalSelfConsMWh,
    totalSurplusMWh,
    totalDeficitMWh,
    totalBalanceMWh,
    totalHours,
    avgPowerTotal,
    '100.0%'
  ]);

  // Create workbook and worksheet
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(data);

  // Set column widths
  ws['!cols'] = [
    { wch: 12 },  // Miesiąc
    { wch: 18 },  // Produkcja PV
    { wch: 18 },  // Zużycie Load
    { wch: 20 },  // Autokonsumpcja
    { wch: 15 },  // Nadwyżka
    { wch: 15 },  // Deficyt
    { wch: 15 },  // Bilans
    { wch: 15 },  // Godziny
    { wch: 15 },  // Śr. Moc
    { wch: 18 }   // % Rocznej
  ];

  XLSX.utils.book_append_sheet(wb, ws, 'Produkcja Miesięczna');

  // Generate filename with date
  const filename = `Produkcja_Miesieczna_${new Date().toISOString().split('T')[0]}.xlsx`;

  // Download file
  XLSX.writeFile(wb, filename);
}

// Refresh data
function refreshData() {
  loadAllData();
}

// Clear analysis
function clearAnalysis() {
  productionData = null;
  consumptionData = null;
  pvConfig = null;

  if (dailyProductionChart) dailyProductionChart.destroy();
  if (monthlyProductionChart) monthlyProductionChart.destroy();
  if (hourlyProfileChart) hourlyProfileChart.destroy();
  if (daylightProfileChart) daylightProfileChart.destroy();
  if (energyBalanceChart) energyBalanceChart.destroy();

  showNoData();
}

// Select variant
function selectVariant(variantName) {
  currentVariant = variantName;

  // Update button states
  document.querySelectorAll('.variant-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelector(`.variant-btn[data-variant="${variantName}"]`)?.classList.add('active');

  // Reload analysis with selected variant
  performAnalysis();
}

// Update variant descriptions
function updateVariantDescriptions() {
  if (!analysisResults || !analysisResults.key_variants) return;

  const variantKeys = Object.keys(analysisResults.key_variants);
  variantKeys.forEach(key => {
    const variant = analysisResults.key_variants[key];
    const descElement = document.getElementById(`desc${key}`);
    if (descElement) {
      descElement.textContent = `${(variant.capacity / 1000).toFixed(1)} MWp • ${variant.threshold}% pokrycia`;
    }
  });
}
