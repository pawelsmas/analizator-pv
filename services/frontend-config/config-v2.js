// Configuration Module - Data Upload & Analysis Setup

// Backend API URLs
const API = {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002',
  economics: 'http://localhost:8003'
};

// Global state
let uploadedData = null;
let analysisInProgress = false;
let fileUploadedThisSession = false;
let systemSettings = null; // Settings from pv_system_settings

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();

  // Request settings from shell (shell has central localStorage)
  requestSettingsFromShell();

  loadSavedConfig(); // Load local config (pvType, strategy)

  // Initialize strategy options visibility
  toggleStrategyOptions();

  // Initialize NPV mode hint
  updateNpvModeHint();

  // Check if data already exists
  checkExistingData();
});

// Request settings from shell via postMessage
function requestSettingsFromShell() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
    console.log('Requested settings from shell');
  } else {
    // Fallback - apply defaults if not in iframe
    applyDefaultSettings();
  }
}

// Setup event listeners
function setupEventListeners() {
  document.getElementById('loadFile').addEventListener('change', handleFileUpload);

  // Only save local config on change (pvType, optimizationStrategy, npvMode)
  ['pvType', 'optimizationStrategy', 'npvMode'].forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.addEventListener('change', saveConfig);
    }
  });

  // When PV type changes, update displayed parameters
  const pvTypeSelect = document.getElementById('pvType');
  if (pvTypeSelect) {
    pvTypeSelect.addEventListener('change', () => {
      if (systemSettings) {
        applySystemSettingsToUI(systemSettings);
      }
    });
  }
}

// Apply settings received from shell
function applySettingsFromShell(settings) {
  if (settings) {
    systemSettings = settings;
    applySystemSettingsToUI(systemSettings);
    console.log('Applied settings from shell:', systemSettings.totalEnergyPrice);
  } else {
    applyDefaultSettings();
  }
}

// Apply system settings to readonly UI fields
function applySystemSettingsToUI(settings) {
  console.log('Applying system settings to UI:', settings);

  // Get selected PV type to show corresponding params
  const pvType = document.getElementById('pvType')?.value || 'ground_s';

  // PV Installation parameters - based on selected type
  const pvYield = getSettingValue(settings, `pvYield_${pvType}`, 1050);
  const dcacRatio = getSettingValue(settings, `dcacRatio_${pvType}`, 1.2);

  setFieldValue('yield', pvYield);
  setFieldValue('dcac', dcacRatio);

  // Analysis range
  setFieldValue('capMin', getSettingValue(settings, 'capMin', 1000));
  setFieldValue('capMax', getSettingValue(settings, 'capMax', 50000));
  setFieldValue('capStep', getSettingValue(settings, 'capStep', 500));

  // Autoconsumption thresholds
  setFieldValue('thrA', getSettingValue(settings, 'thrA', 95));
  setFieldValue('thrB', getSettingValue(settings, 'thrB', 90));
  setFieldValue('thrC', getSettingValue(settings, 'thrC', 85));
  setFieldValue('thrD', getSettingValue(settings, 'thrD', 80));

  // NPV parameters - calculate totalEnergyPrice if not present
  let totalEnergyPrice = settings.totalEnergyPrice;
  if (!totalEnergyPrice && settings.energyActive) {
    // Recalculate from components
    totalEnergyPrice = (settings.energyActive || 550) +
      (settings.distribution || 200) +
      (settings.qualityFee || 10) +
      (settings.ozeFee || 7) +
      (settings.cogenerationFee || 10) +
      (settings.capacityFee || 219) +
      (settings.exciseTax || 5);
  }
  setFieldValue('npvEnergyPrice', totalEnergyPrice || 1001);
  setFieldValue('npvOpex', getSettingValue(settings, 'opexPerKwp', 15));
  setFieldValue('npvDiscountRate', getSettingValue(settings, 'discountRate', 7));
  setFieldValue('npvDegradation', getSettingValue(settings, 'degradationRate', 0.5));
  setFieldValue('npvAnalysisPeriod', getSettingValue(settings, 'analysisPeriod', 25));

  console.log('Energy price applied:', totalEnergyPrice || 1001);

  // CAPEX tiers display
  const defaultCapexTiers = [
    { capex: 4200 }, { capex: 3800 }, { capex: 3500 },
    { capex: 3200 }, { capex: 3000 }, { capex: 2850 }, { capex: 2700 }
  ];
  const capexTiers = settings.capexTiers || defaultCapexTiers;
  capexTiers.forEach((tier, index) => {
    const el = document.getElementById(`capexDisplay${index + 1}`);
    if (el) {
      el.textContent = tier.capex || defaultCapexTiers[index].capex;
    }
  });
}

// Helper to get value safely
function getSettingValue(settings, key, defaultValue) {
  const val = settings?.[key];
  return (val !== undefined && val !== null && val !== '') ? val : defaultValue;
}

// Apply default settings
function applyDefaultSettings() {
  systemSettings = {
    // PV params per type (Yield, DC/AC, Latitude, Tilt, Azimuth)
    pvYield_ground_s: 1050,
    dcacRatio_ground_s: 1.2,
    latitude_ground_s: 52.0,
    tilt_ground_s: 0,        // 0 = auto (uses latitude)
    azimuth_ground_s: 180,   // South
    pvYield_roof_ew: 950,
    dcacRatio_roof_ew: 1.15,
    latitude_roof_ew: 52.0,
    tilt_roof_ew: 10,        // Low tilt for E-W
    azimuth_roof_ew: 90,     // East (also calculates West)
    pvYield_ground_ew: 980,
    dcacRatio_ground_ew: 1.25,
    latitude_ground_ew: 52.0,
    tilt_ground_ew: 15,
    azimuth_ground_ew: 90,   // East (also calculates West)
    // Analysis range
    capMin: 1000,
    capMax: 50000,
    capStep: 500,
    thrA: 95,
    thrB: 90,
    thrC: 85,
    thrD: 80,
    // Energy tariff components
    energyActive: 550,
    distribution: 200,
    qualityFee: 10,
    ozeFee: 7,
    cogenerationFee: 10,
    capacityFee: 219,
    exciseTax: 5,
    totalEnergyPrice: 1001, // Sum of all above
    opexPerKwp: 15,
    discountRate: 7,
    degradationRate: 0.5,
    analysisPeriod: 25,
    capexTiers: [
      { min: 150, max: 500, capex: 4200 },
      { min: 501, max: 1000, capex: 3800 },
      { min: 1001, max: 2500, capex: 3500 },
      { min: 2501, max: 5000, capex: 3200 },
      { min: 5001, max: 10000, capex: 3000 },
      { min: 10001, max: 15000, capex: 2850 },
      { min: 15001, max: 50000, capex: 2700 }
    ]
  };
  applySystemSettingsToUI(systemSettings);
  console.log('Applied default settings (no pv_system_settings found in localStorage)');
}

// Helper to set field value
function setFieldValue(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.value = value;
  }
}

// Toggle strategy options visibility
function toggleStrategyOptions() {
  const strategy = document.getElementById('optimizationStrategy').value;
  const autoconsumptionOptions = document.getElementById('autoconsumptionOptions');
  const npvOptions = document.getElementById('npvOptions');
  const seasonalityInfo = document.getElementById('seasonalityInfo');
  const seasonSelector = document.getElementById('seasonSelector');

  console.log('🔧 toggleStrategyOptions:', {
    strategy,
    autoconsumptionOptions: !!autoconsumptionOptions,
    npvOptions: !!npvOptions,
    seasonalityInfo: !!seasonalityInfo,
    seasonSelector: !!seasonSelector
  });

  // Hide all options first
  if (autoconsumptionOptions) autoconsumptionOptions.style.display = 'none';
  if (npvOptions) npvOptions.style.display = 'none';
  if (seasonalityInfo) seasonalityInfo.style.display = 'none';
  if (seasonSelector) seasonSelector.style.display = 'none';

  if (strategy === 'autoconsumption') {
    if (autoconsumptionOptions) autoconsumptionOptions.style.display = 'block';
  } else if (strategy === 'npv') {
    if (npvOptions) npvOptions.style.display = 'block';
  } else if (strategy === 'seasonality_auto' || strategy === 'seasonality_npv') {
    // Show seasonality info, season selector, and check for seasonality
    if (seasonalityInfo) seasonalityInfo.style.display = 'block';
    if (seasonSelector) seasonSelector.style.display = 'block';
    checkSeasonality();
  }

  saveConfig();
}

// Global seasonality data
let seasonalityData = null;

// Check seasonality from API
async function checkSeasonality() {
  const seasonalityDetected = document.getElementById('seasonalityDetected');
  const seasonalityNotDetected = document.getElementById('seasonalityNotDetected');
  const seasonalityLoading = document.getElementById('seasonalityLoading');

  // Show loading state
  if (seasonalityDetected) seasonalityDetected.style.display = 'none';
  if (seasonalityNotDetected) seasonalityNotDetected.style.display = 'none';
  if (seasonalityLoading) seasonalityLoading.style.display = 'block';

  // Check if data is uploaded
  if (!sessionStorage.getItem('file_uploaded')) {
    if (seasonalityLoading) {
      seasonalityLoading.innerHTML = '<div style="font-size:11px;color:#1565c0">⏳ Wgraj dane aby sprawdzić sezonowość...</div>';
    }
    return;
  }

  try {
    const response = await fetch(`${API.dataAnalysis}/seasonality/summary`);
    if (!response.ok) throw new Error('Failed to get seasonality');

    const summary = await response.json();
    seasonalityData = summary;

    // Hide loading
    if (seasonalityLoading) seasonalityLoading.style.display = 'none';

    if (summary.detected) {
      // Show detected message
      if (seasonalityDetected) {
        seasonalityDetected.style.display = 'block';
        document.getElementById('seasonalityMessage').textContent = summary.message;
        document.getElementById('highMonthsCount').textContent = summary.high_months_count;
        document.getElementById('midMonthsCount').textContent = summary.mid_months_count;
        document.getElementById('lowMonthsCount').textContent = summary.low_months_count;
      }
    } else {
      // Show not detected message
      if (seasonalityNotDetected) seasonalityNotDetected.style.display = 'block';
    }

    console.log('🌡️ Seasonality check:', summary);

  } catch (error) {
    console.error('Seasonality check error:', error);
    if (seasonalityLoading) {
      seasonalityLoading.innerHTML = '<div style="font-size:11px;color:#e74c3c">❌ Błąd sprawdzania sezonowości</div>';
    }
  }
}

// Update NPV mode hint text
function updateNpvModeHint() {
  const npvMode = document.getElementById('npvMode')?.value || 'constrained';
  const hintEl = document.getElementById('npvModeHint');

  if (hintEl) {
    if (npvMode === 'constrained') {
      hintEl.innerHTML = 'Optymalna instalacja zostanie dobrana w zakresie autokonsumpcji A-D% z uwzględnieniem przedziałów CAPEX';
    } else {
      hintEl.innerHTML = 'Optymalna instalacja zostanie dobrana z całego zakresu mocy (Min-Max kWp) bez ograniczenia autokonsumpcji, z uwzględnieniem przedziałów CAPEX';
    }
  }
}

// Get CAPEX tiers from system settings
function getCapexTiers() {
  if (systemSettings && systemSettings.capexTiers) {
    return systemSettings.capexTiers;
  }
  // Fallback defaults
  return [
    { min: 150, max: 500, capex: 4200 },
    { min: 501, max: 1000, capex: 3800 },
    { min: 1001, max: 2500, capex: 3500 },
    { min: 2501, max: 5000, capex: 3200 },
    { min: 5001, max: 10000, capex: 3000 },
    { min: 10001, max: 15000, capex: 2850 },
    { min: 15001, max: 50000, capex: 2700 }
  ];
}

// Get CAPEX per kWp based on capacity
function getCapexForCapacity(capacityKwp) {
  const tiers = getCapexTiers();

  for (const tier of tiers) {
    if (capacityKwp >= tier.min && capacityKwp <= tier.max) {
      return tier.capex;
    }
  }

  // Fallback: use last tier for very large installations
  if (capacityKwp > 50000) {
    return tiers[tiers.length - 1].capex;
  }

  // Fallback: use first tier for very small installations
  return tiers[0].capex;
}

// Calculate NPV for a given capacity scenario
function calculateScenarioNPV(scenario, params) {
  // Use tiered CAPEX based on capacity
  const capexPerKwp = getCapexForCapacity(scenario.capacity);
  const capex = scenario.capacity * capexPerKwp;
  const energyPrice = params.energyPrice / 1000; // PLN/kWh
  const opex = scenario.capacity * params.opex;

  // Get parameters from system settings
  const discountRate = (systemSettings?.discountRate || 7) / 100;
  const analysisPeriod = systemSettings?.analysisPeriod || 25;
  const degradationRate = (systemSettings?.degradationRate || 0.5) / 100;

  let npv = -capex;

  for (let year = 1; year <= analysisPeriod; year++) {
    const degradation = Math.pow(1 - degradationRate, year - 1);
    const yearSelfConsumed = scenario.self_consumed * degradation;
    const yearSavings = yearSelfConsumed * energyPrice;
    const yearCashFlow = yearSavings - opex;
    const discountedCF = yearCashFlow / Math.pow(1 + discountRate, year);
    npv += discountedCF;
  }

  return npv;
}

// Find best variant by NPV optimization within autoconsumption limits
function findVariantsByNPV(scenarios, params, thresholds, npvMode = 'constrained') {
  // Calculate NPV for all scenarios
  const scoredScenarios = scenarios.map(s => {
    const npv = calculateScenarioNPV(s, params);
    const autoconsumptionRatio = s.self_consumed / s.production;

    return {
      ...s,
      npv: npv,
      autoconsumptionRatio: autoconsumptionRatio,
      auto_consumption_pct: autoconsumptionRatio * 100
    };
  });

  let bestNPV;
  let label;
  let meetsThreshold;

  if (npvMode === 'absolute') {
    // Mode 2: Absolute best NPV from entire range (no autoconsumption constraint)
    bestNPV = scoredScenarios.sort((a, b) => b.npv - a.npv)[0];
    label = `Optymalny NPV (cały zakres mocy)`;
    meetsThreshold = false; // Not constrained by A-D

    console.log(`Found absolute best NPV across entire range:`,
      bestNPV.capacity, 'kWp,',
      bestNPV.auto_consumption_pct.toFixed(1), '%,',
      'NPV:', (bestNPV.npv / 1000000).toFixed(2), 'mln PLN');
  } else {
    // Mode 1 (default): Constrained by autoconsumption range [D%, A%]
    const maxAutoconsumption = thresholds.A / 100; // e.g., 95% -> 0.95
    const minAutoconsumption = thresholds.D / 100; // e.g., 80% -> 0.80

    // Filter scenarios within autoconsumption range [D%, A%]
    const validScenarios = scoredScenarios.filter(s =>
      s.autoconsumptionRatio >= minAutoconsumption &&
      s.autoconsumptionRatio <= maxAutoconsumption
    );

    if (validScenarios.length === 0) {
      console.warn('No scenarios found within autoconsumption range', minAutoconsumption * 100, '-', maxAutoconsumption * 100);
      // Fallback to best NPV from all scenarios
      bestNPV = scoredScenarios.sort((a, b) => b.npv - a.npv)[0];
      label = `Best NPV (outside ${thresholds.D}-${thresholds.A}% range)`;
      meetsThreshold = false;
    } else {
      // Find best NPV within valid range
      bestNPV = validScenarios.sort((a, b) => b.npv - a.npv)[0];
      label = `Optymalny NPV (${thresholds.D}-${thresholds.A}%)`;
      meetsThreshold = true;

      console.log(`Found best NPV within ${thresholds.D}-${thresholds.A}% autoconsumption:`,
        bestNPV.capacity, 'kWp,',
        bestNPV.auto_consumption_pct.toFixed(1), '%,',
        'NPV:', (bestNPV.npv / 1000000).toFixed(2), 'mln PLN');
    }
  }

  // Ensure coverage_pct is set
  const coveragePct = bestNPV.coverage_pct || bestNPV.auto_consumption_pct || (bestNPV.autoconsumptionRatio * 100);

  // Create single optimal variant with all required fields
  const variants = {
    NPV: {
      ...bestNPV,
      threshold: Math.round(bestNPV.autoconsumptionRatio * 100),
      label: label,
      npv_mln: (bestNPV.npv / 1000000).toFixed(2),
      coverage_pct: coveragePct,
      auto_consumption_pct: bestNPV.auto_consumption_pct || (bestNPV.autoconsumptionRatio * 100),
      meets_threshold: meetsThreshold,
      npv_mode: npvMode
    }
  };

  return variants;
}

// Load saved local configuration from localStorage
function loadSavedConfig() {
  const saved = localStorage.getItem('pv_local_config');
  if (saved) {
    try {
      const config = JSON.parse(saved);
      // Only apply local settings (pvType, optimizationStrategy, npvMode)
      if (config.pvType) {
        const el = document.getElementById('pvType');
        if (el) el.value = config.pvType;
      }
      if (config.optimizationStrategy) {
        const el = document.getElementById('optimizationStrategy');
        if (el) el.value = config.optimizationStrategy;
      }
      if (config.npvMode) {
        const el = document.getElementById('npvMode');
        if (el) el.value = config.npvMode;
      }
      console.log('Loaded local configuration:', config);

      // After loading, update UI visibility
      toggleStrategyOptions();
      updateNpvModeHint();
    } catch (e) {
      console.error('Failed to load local config:', e);
    }
  }
}

// Save local configuration to localStorage (only pvType, strategy, npvMode)
function saveConfig() {
  const config = {
    pvType: document.getElementById('pvType').value,
    optimizationStrategy: document.getElementById('optimizationStrategy')?.value || 'autoconsumption',
    npvMode: document.getElementById('npvMode')?.value || 'constrained'
  };

  localStorage.setItem('pv_local_config', JSON.stringify(config));
  console.log('Local configuration saved');
}

// Show upload prompt
function showUploadPrompt() {
  document.getElementById('loadStatus').innerHTML = `
    <div style="color:#ff9800;padding:10px;background:#fff3e0;border-radius:6px;margin-top:10px;">
      ⚠️ Załaduj plik danych aby rozpocząć analizę
    </div>
  `;

  // Clear statistics
  document.getElementById('statConsumption').textContent = '–';
  document.getElementById('statPeak').textContent = '–';
  document.getElementById('statDays').textContent = '–';
  document.getElementById('statAvg').textContent = '–';
}

// Check if data already exists (from this session or saved analysis)
async function checkExistingData() {
  // Check if file was uploaded in this session
  const sessionUploaded = sessionStorage.getItem('file_uploaded');

  // Check if we have saved data info
  const dataInfo = localStorage.getItem('pv_data_info');

  // Check if analysis was completed
  const analysisResults = localStorage.getItem('pv_analysis_results');

  if (sessionUploaded === 'true' && dataInfo) {
    // File uploaded this session - restore upload status
    try {
      const info = JSON.parse(dataInfo);
      uploadedData = true;
      fileUploadedThisSession = true;

      document.getElementById('loadStatus').innerHTML = `
        <div class="success">
          ✓ Załadowano: ${info.filename}<br>
          ${info.points} godzin danych<br>
          Rok: ${info.year}
        </div>
      `;

      // Restore statistics
      await updateStatisticsFromAPI();

      // If analysis was completed, show the results screen with variant selector
      if (analysisResults) {
        showAnalysisResults(JSON.parse(analysisResults));
      }
    } catch (error) {
      console.error('Error restoring session data:', error);
      showUploadPrompt();
    }
  } else {
    // No data in this session - show upload prompt
    showUploadPrompt();
  }
}

// Handle file upload
async function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    document.getElementById('loadStatus').innerHTML =
      '<div style="color:#ffaa00">⏳ Uploading...</div>';

    const formData = new FormData();
    formData.append('file', file);

    // Determine endpoint based on file type
    const endpoint = file.name.endsWith('.csv') ? '/upload/csv' : '/upload/excel';

    const response = await fetch(`${API.dataAnalysis}${endpoint}`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Upload failed');
    }

    const result = await response.json();

    document.getElementById('loadStatus').innerHTML = `
      <div class="success">
        ✓ ${result.message}<br>
        ${result.data_points} hours loaded<br>
        Year: ${result.year}
      </div>
    `;

    uploadedData = true;
    fileUploadedThisSession = true; // Mark that file was uploaded THIS session
    sessionStorage.setItem('file_uploaded', 'true'); // Session flag

    // Update statistics
    await updateStatisticsFromAPI();

    // Save to localStorage
    localStorage.setItem('pv_data_uploaded', 'true');
    localStorage.setItem('pv_data_info', JSON.stringify({
      filename: file.name,
      points: result.data_points,
      year: result.year,
      uploadedAt: new Date().toISOString()
    }));

    // Notify parent shell that data is available
    notifyShell('DATA_UPLOADED', {
      filename: file.name,
      dataPoints: result.data_points,
      year: result.year
    });

  } catch (error) {
    document.getElementById('loadStatus').innerHTML =
      `<div style="color:#ff0088">❌ Error: ${error.message}</div>`;
    console.error('Upload error:', error);
  }
}

// Update statistics from API
async function updateStatisticsFromAPI() {
  try {
    const response = await fetch(`${API.dataAnalysis}/statistics`);
    if (!response.ok) throw new Error('Failed to get statistics');

    const stats = await response.json();
    updateStatistics(stats);
  } catch (error) {
    console.error('Failed to update statistics:', error);
  }
}

// Update statistics display
function updateStatistics(stats) {
  if (!stats) return;

  if (stats.total_consumption_gwh !== undefined) {
    document.getElementById('statConsumption').textContent =
      stats.total_consumption_gwh.toFixed(1);
  }
  if (stats.peak_power_mw !== undefined) {
    document.getElementById('statPeak').textContent =
      stats.peak_power_mw.toFixed(1);
  }
  if (stats.data_period !== undefined) {
    document.getElementById('statDays').textContent =
      stats.data_period;
  }
  if (stats.avg_daily_mwh !== undefined) {
    document.getElementById('statAvg').textContent =
      stats.avg_daily_mwh.toFixed(1);
  }
}

// Run analysis
async function runAnalysis() {
  // Check if file was uploaded THIS SESSION
  if (!sessionStorage.getItem('file_uploaded')) {
    showMessage('⚠️ Załaduj plik danych! Wgraj plik Excel/CSV przed uruchomieniem analizy.', 'warning');
    return;
  }

  // Validate data uploaded
  if (!uploadedData) {
    showMessage('⚠️ Please upload consumption data first! Select your Excel or CSV file above.', 'warning');
    return;
  }

  if (analysisInProgress) {
    showMessage('⚠️ Analysis already in progress...', 'warning');
    return;
  }

  try {
    analysisInProgress = true;

    // Progress indicator helper
    const updateProgress = (step, stepName, percent = null) => {
      const progressBar = percent !== null
        ? `<div style="margin-top:15px;background:#333;border-radius:10px;height:8px;width:200px;margin:15px auto 0;">
            <div style="background:linear-gradient(90deg,#667eea,#764ba2);height:100%;border-radius:10px;width:${percent}%;transition:width 0.3s"></div>
           </div>
           <div style="font-size:12px;margin-top:5px;color:#888">${percent}%</div>`
        : '';

      document.getElementById('configResults').innerHTML = `
        <div style="text-align:center;padding:40px;color:#ffaa00">
          <div style="font-size:36px;margin-bottom:10px">⏳</div>
          <div style="font-size:16px;font-weight:600">Trwa analiza...</div>
          <div style="font-size:14px;margin-top:10px;color:#ccc">${stepName}</div>
          ${progressBar}
          <div style="font-size:11px;margin-top:15px;color:#666">Krok ${step}</div>
        </div>
      `;
    };

    updateProgress(1, 'Pobieranie danych zużycia energii');

    // Get consumption data
    const hourlyDataResponse = await fetch(`${API.dataAnalysis}/hourly-data`);
    if (!hourlyDataResponse.ok) throw new Error('Failed to get hourly data');
    const hourlyData = await hourlyDataResponse.json();

    updateProgress(2, 'Przygotowanie konfiguracji PV', 15);

    // Save consumption data to localStorage for other modules
    const dataInfo = JSON.parse(localStorage.getItem('pv_data_info') || '{}');
    localStorage.setItem('consumptionData', JSON.stringify({
      filename: dataInfo.filename || 'uploaded_data',
      dataPoints: hourlyData.values.length,
      year: dataInfo.year || new Date().getFullYear(),
      hourlyData: hourlyData
    }));

    // Get configuration from systemSettings - based on selected type
    const pvType = document.getElementById('pvType').value;

    // Get DC/AC ratio tiers for this installation type
    const dcacTiers = systemSettings?.dcacTiers || [
      { min: 150, max: 500, ground_s: 1.15, roof_ew: 1.20, ground_ew: 1.25 },
      { min: 501, max: 1000, ground_s: 1.20, roof_ew: 1.25, ground_ew: 1.30 },
      { min: 1001, max: 2500, ground_s: 1.25, roof_ew: 1.30, ground_ew: 1.35 },
      { min: 2501, max: 5000, ground_s: 1.30, roof_ew: 1.35, ground_ew: 1.40 },
      { min: 5001, max: 10000, ground_s: 1.30, roof_ew: 1.35, ground_ew: 1.40 },
      { min: 10001, max: 15000, ground_s: 1.35, roof_ew: 1.40, ground_ew: 1.45 },
      { min: 15001, max: 50000, ground_s: 1.40, roof_ew: 1.45, ground_ew: 1.50 }
    ];

    // Get tilt (0 = auto = use latitude)
    const tiltValue = systemSettings?.[`tilt_${pvType}`] ?? 0;
    const latitudeValue = systemSettings?.[`latitude_${pvType}`] || 52.0;
    const effectiveTilt = tiltValue === 0 ? latitudeValue : tiltValue;

    const pvConfig = {
      pv_type: pvType,
      yield_target: systemSettings?.[`pvYield_${pvType}`] || 1050,
      latitude: latitudeValue,
      tilt: effectiveTilt,
      azimuth: systemSettings?.[`azimuth_${pvType}`] || (pvType === 'ground_s' ? 180 : 90),
      // Include DC/AC tiers for the selected installation type
      dcac_tiers: dcacTiers.map(tier => ({
        min: tier.min,
        max: tier.max,
        ratio: tier[pvType] || tier.ground_s
      })),
      // Weather data source (PVGIS or clearsky)
      use_pvgis: systemSettings?.weatherDataSource === 'pvgis'
    };

    // Log analysis parameters
    console.log('📊 Analysis parameters:', {
      pvType,
      yield: pvConfig.yield_target,
      latitude: pvConfig.latitude,
      tilt: pvConfig.tilt,
      azimuth: pvConfig.azimuth,
      dcacTiers: pvConfig.dcac_tiers,
      capacityRange: `${systemSettings?.capMin || 1000} - ${systemSettings?.capMax || 50000} kWp`
    });

    const analysisRequest = {
      pv_config: pvConfig,
      consumption: hourlyData.values,
      timestamps: hourlyData.timestamps,  // Pass timestamps for pvlib
      capacity_min: systemSettings?.capMin || 1000,
      capacity_max: systemSettings?.capMax || 50000,
      capacity_step: systemSettings?.capStep || 500,
      thresholds: {
        A: systemSettings?.thrA || 95,
        B: systemSettings?.thrB || 90,
        C: systemSettings?.thrC || 85,
        D: systemSettings?.thrD || 80
      }
    };

    // Add BESS configuration if enabled (LIGHT/AUTO mode)
    if (systemSettings?.bessEnabled) {
      analysisRequest.bess_config = {
        enabled: true,
        mode: 'lite',  // LIGHT/AUTO mode - system auto-sizes power and energy
        duration: systemSettings.bessDuration || 'auto',  // 'auto' | 1 | 2 | 4 hours
        // Technical parameters
        roundtrip_efficiency: systemSettings.bessRoundtripEfficiency || 0.90,
        soc_min: systemSettings.bessSocMin || 0.10,
        soc_max: systemSettings.bessSocMax || 0.90,
        soc_initial: systemSettings.bessSocInitial || 0.50,
        // Economic parameters (for NPV calculation)
        capex_per_kwh: systemSettings.bessCapexPerKwh || 1500,
        capex_per_kw: systemSettings.bessCapexPerKw || 300,
        opex_pct_per_year: systemSettings.bessOpexPctPerYear || 1.5,
        lifetime_years: systemSettings.bessLifetimeYears || 15,
        degradation_pct_per_year: systemSettings.bessDegradationPctPerYear || 2.0
      };
      console.log('🔋 BESS LIGHT/AUTO mode enabled:', analysisRequest.bess_config);
    } else {
      console.log('🔋 BESS disabled - running PV-only analysis');
    }

    console.log(`📅 Using ${hourlyData.timestamps?.length || 0} timestamps from consumption data`);

    // Store analysis logs for export
    window.analysisLogs = window.analysisLogs || [];
    window.analysisLogs.push({
      timestamp: new Date().toISOString(),
      type: 'REQUEST',
      data: {
        pvConfig,
        capacityMin: analysisRequest.capacity_min,
        capacityMax: analysisRequest.capacity_max,
        capacityStep: analysisRequest.capacity_step,
        thresholds: analysisRequest.thresholds
      }
    });

    updateProgress(3, 'Symulacja produkcji PV (PVGIS + pvlib)', 30);

    // Run PV analysis
    const analysisResponse = await fetch(`${API.pvCalculation}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(analysisRequest)
    });

    if (!analysisResponse.ok) {
      const error = await analysisResponse.json();
      throw new Error(error.detail || 'Analysis failed');
    }

    updateProgress(4, 'Przetwarzanie wyników bazowych', 50);

    const results = await analysisResponse.json();

    // Log analysis response
    console.log('📊 Analysis response:', {
      scenarios: results.scenarios?.length || 0,
      keyVariants: results.key_variants ? Object.keys(results.key_variants) : []
    });

    // Store analysis response in logs
    window.analysisLogs.push({
      timestamp: new Date().toISOString(),
      type: 'RESPONSE',
      data: {
        scenariosCount: results.scenarios?.length || 0,
        keyVariants: results.key_variants,
        pvProfile: results.pv_profile
      }
    });

    // Log sample scenarios for debugging
    if (results.scenarios && results.scenarios.length > 0) {
      const sampleCapacities = [1000, 5000, 10000, 16000, 20000];
      console.log('📊 Sample scenarios:');
      sampleCapacities.forEach(cap => {
        const scenario = results.scenarios.find(s => s.capacity === cap);
        if (scenario) {
          console.log(`  ${cap} kWp: prod=${(scenario.production/1000).toFixed(0)} MWh, auto=${scenario.auto_consumption_pct.toFixed(1)}%`);
        }
      });
    }

    // Check optimization strategy
    const strategy = document.getElementById('optimizationStrategy')?.value || 'autoconsumption';

    // Get economic parameters from systemSettings
    const economicParams = {
      energyPrice: systemSettings?.totalEnergyPrice || 1001,
      opex: systemSettings?.opexPerKwp || 15,
      capexTiers: getCapexTiers(),
      discountRate: systemSettings?.discountRate || 7,
      degradationRate: systemSettings?.degradationRate || 0.5,
      analysisPeriod: systemSettings?.analysisPeriod || 25
    };

    // Handle seasonality strategies
    if ((strategy === 'seasonality_auto' || strategy === 'seasonality_npv') && results.scenarios && results.scenarios.length > 0) {
      console.log('🌡️ Running seasonality optimization...');

      updateProgress(5, 'Pobieranie analizy sezonowości', 55);

      // Get full seasonality data from API
      const seasonalityResponse = await fetch(`${API.dataAnalysis}/seasonality`);
      if (!seasonalityResponse.ok) throw new Error('Failed to get seasonality data');
      const seasonality = await seasonalityResponse.json();

      // Prepare band_powers and monthly_bands for API
      const bandPowers = seasonality.band_powers.map(bp => ({
        band: bp.band,
        p_recommended: bp.p_recommended
      }));

      const monthlyBands = seasonality.monthly_bands.map(mb => ({
        month: mb.month,
        dominant_band: mb.dominant_band
      }));

      // Get target seasons from UI selector
      const targetSeasonValue = document.getElementById('targetSeason')?.value || 'high_mid';
      let targetSeasons;
      if (targetSeasonValue === 'high') {
        targetSeasons = ['High'];
      } else if (targetSeasonValue === 'high_mid') {
        targetSeasons = ['High', 'Mid'];
      } else {
        targetSeasons = ['High', 'Mid', 'Low'];
      }

      // Get autoconsumption thresholds from settings
      const autoconsumptionThresholds = {
        A: systemSettings?.autoA || 95,
        B: systemSettings?.autoB || 90,
        C: systemSettings?.autoC || 85,
        D: systemSettings?.autoD || 80
      };

      // Call seasonality optimization endpoint
      const seasonalityRequest = {
        pv_config: pvConfig,
        consumption: hourlyData.values,
        timestamps: hourlyData.timestamps,
        band_powers: bandPowers,
        monthly_bands: monthlyBands,
        capacity_min: systemSettings?.capMin || 1000,
        capacity_max: systemSettings?.capMax || 50000,
        capacity_step: systemSettings?.capStep || 500,
        capex_per_kwp: getCapexForCapacity(5000), // Use mid-range CAPEX
        opex_per_kwp_year: economicParams.opex,
        energy_price_import: economicParams.energyPrice,
        energy_price_esco: economicParams.energyPrice * 0.9, // 90% of import price
        discount_rate: economicParams.discountRate / 100,
        project_years: economicParams.analysisPeriod,
        mode: strategy === 'seasonality_npv' ? 'MAX_NPV' : 'MAX_AUTOCONSUMPTION',
        target_seasons: targetSeasons,
        autoconsumption_thresholds: autoconsumptionThresholds
      };

      console.log('🌡️ Seasonality optimization request:', seasonalityRequest);

      // Calculate estimated configurations for progress
      const numCapacities = Math.ceil((seasonalityRequest.capacity_max - seasonalityRequest.capacity_min) / seasonalityRequest.capacity_step) + 1;
      const numConfigs = numCapacities * 3; // 3 scalers
      updateProgress(6, `Optymalizacja PASMA_SEZONOWOŚĆ (${numConfigs} konfiguracji)`, 60);

      // Start SSE for live progress updates
      let progressEventSource = null;
      try {
        console.log('🔌 Starting SSE connection...');
        progressEventSource = new EventSource(`${API.pvCalculation}/optimization-progress`);

        progressEventSource.onopen = () => {
          console.log('🔌 SSE connection opened');
        };

        progressEventSource.onmessage = (event) => {
          try {
            const progress = JSON.parse(event.data);
            console.log('📡 SSE progress:', progress);
            if (progress.active) {
              const stepInfo = progress.step || `Testowanie mocy`;
              const percent = 60 + Math.round(progress.percent * 0.3); // Scale 0-100% to 60-90%
              updateProgress(6, `${stepInfo} (${progress.percent}%)`, percent);
            } else if (progress.step === "Oczekiwanie na optymalizację...") {
              updateProgress(6, 'Łączenie z serwerem...', 60);
            }
          } catch (e) {
            console.warn('SSE parse error:', e);
          }
        };

        progressEventSource.onerror = (e) => {
          console.warn('SSE connection error (may be normal at completion)', e);
          if (progressEventSource) {
            progressEventSource.close();
            progressEventSource = null;
          }
        };
      } catch (e) {
        console.warn('Could not start SSE progress:', e);
      }

      const seasonalityOptResponse = await fetch(`${API.pvCalculation}/optimize-seasonality`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(seasonalityRequest)
      });

      // Close SSE after fetch completes
      if (progressEventSource) {
        progressEventSource.close();
        progressEventSource = null;
      }

      if (!seasonalityOptResponse.ok) {
        const error = await seasonalityOptResponse.json();
        throw new Error(error.detail || 'Seasonality optimization failed');
      }

      updateProgress(7, 'Przetwarzanie wyników optymalizacji', 90);

      const seasonalityOptResult = await seasonalityOptResponse.json();
      console.log('🌡️ Seasonality optimization result:', seasonalityOptResult);

      // Create variant from seasonality result
      results.key_variants = {
        SEASONALITY: {
          capacity: seasonalityOptResult.best_capacity_kwp,
          dcac_ratio: seasonalityOptResult.best_dcac_ratio,
          production: seasonalityOptResult.annual_production_mwh * 1000, // Convert to kWh
          self_consumed: seasonalityOptResult.annual_self_consumed_mwh * 1000,
          exported: seasonalityOptResult.annual_exported_mwh * 1000,
          auto_consumption_pct: seasonalityOptResult.autoconsumption_pct,
          coverage_pct: seasonalityOptResult.coverage_pct,
          threshold: Math.round(seasonalityOptResult.autoconsumption_pct),
          meets_threshold: true,
          npv: seasonalityOptResult.npv,
          irr: seasonalityOptResult.irr,
          payback_years: seasonalityOptResult.payback_years,
          band_config: seasonalityOptResult.best_band_config
        }
      };

      results.optimization_strategy = strategy;
      results.seasonality_data = seasonality;
      results.seasonality_optimization = seasonalityOptResult;
      results.all_configurations = seasonalityOptResult.all_configurations;

    } else if (strategy === 'npv' && results.scenarios && results.scenarios.length > 0) {
      updateProgress(5, 'Optymalizacja NPV', 70);

      // Recalculate variants based on NPV optimization
      const npvParams = {
        energyPrice: economicParams.energyPrice,
        opex: economicParams.opex
      };

      // Use thresholds A and D as autoconsumption limits
      const thresholds = {
        A: systemSettings?.thrA || 95,
        D: systemSettings?.thrD || 80
      };

      // Get NPV mode from UI
      const npvMode = document.getElementById('npvMode')?.value || 'constrained';

      const npvVariants = findVariantsByNPV(results.scenarios, npvParams, thresholds, npvMode);
      results.key_variants = npvVariants;
      results.optimization_strategy = 'npv';
      results.npv_mode = npvMode;
      results.npv_autoconsumption_range = npvMode === 'constrained' ? { min: thresholds.D, max: thresholds.A } : null;

      updateProgress(6, 'Finalizacja wyników', 90);
      console.log(`📊 NPV-optimized variant (${npvMode} mode):`, npvVariants);
    } else {
      updateProgress(5, 'Przetwarzanie wariantów autokonsumpcji', 80);
      results.optimization_strategy = 'autoconsumption';
    }

    // Add economic parameters including CAPEX tiers to results
    results.economicParams = economicParams;

    updateProgress(8, 'Zapisywanie wyników', 95);

    // Save results to localStorage
    localStorage.setItem('pv_analysis_results', JSON.stringify(results));
    localStorage.setItem('pv_analysis_config', JSON.stringify(pvConfig));

    // Save PV config for other modules
    localStorage.setItem('pvConfig', JSON.stringify(pvConfig));

    // Save analysis results in format expected by other modules
    localStorage.setItem('analysisResults', JSON.stringify(results));

    // Generate and save PV production data for Production module
    if (results.key_variants && Object.keys(results.key_variants).length > 0) {
      const firstVariant = results.key_variants[Object.keys(results.key_variants)[0]];
      localStorage.setItem('pvProductionData', JSON.stringify({
        capacity: firstVariant.capacity,
        production: firstVariant.production,
        self_consumed: firstVariant.self_consumed,
        exported: firstVariant.exported,
        variants: results.key_variants,
        scenarios: results.scenarios
      }));
    }

    // Show analysis results with variant selector
    showAnalysisResults(results);

    // Auto-select first variant or restore saved selection
    setTimeout(() => selectMasterVariant(), 100);

    // Notify parent shell with FULL results
    notifyShell('ANALYSIS_COMPLETE', {
      scenarios: results.scenarios.length,
      variants: Object.keys(results.key_variants).length,
      fullResults: results, // Send complete analysis results
      pvConfig: pvConfig,
      hourlyData: hourlyData
    });

  } catch (error) {
    document.getElementById('configResults').innerHTML = `
      <div style="text-align:center;padding:40px;color:#ff0088">
        <div style="font-size:48px;margin-bottom:10px">❌</div>
        <div style="font-size:18px;margin-bottom:10px">Analysis Failed</div>
        <div style="font-size:14px">${error.message}</div>
      </div>
    `;
    console.error('Analysis error:', error);
  } finally {
    analysisInProgress = false;
  }
}

// Show analysis results screen with variant selector
function showAnalysisResults(results) {
  const isNPVStrategy = results.optimization_strategy === 'npv';
  const variantKeys = Object.keys(results.key_variants);

  // Build variant selector with appropriate labels
  const variantOptions = variantKeys.map(key => {
    const variant = results.key_variants[key];
    let label;
    const capacityMWp = (parseFloat(variant.capacity) / 1000).toFixed(1);

    if (isNPVStrategy) {
      // NPV strategy - single optimal variant
      const npvVal = variant.npv_mln != null ? parseFloat(variant.npv_mln).toFixed(2) : null;
      const npvInfo = npvVal ? ` | NPV: ${npvVal} mln PLN` : '';
      label = `${capacityMWp} MWp (${variant.threshold}% auto)${npvInfo}`;
    } else {
      // Autoconsumption strategy labels
      label = `Wariant ${key} - ${capacityMWp} MWp (${variant.threshold}% pokrycia)`;
    }

    return `<option value="${key}">${label}</option>`;
  }).join('');

  // Strategy label with range info for NPV
  const isSeasonalityStrategy = results.optimization_strategy?.startsWith('seasonality_');
  let strategyLabel;
  if (isSeasonalityStrategy) {
    const mode = results.optimization_strategy === 'seasonality_npv' ? 'MAX NPV' : 'MAX MWh';
    const bestMWh = results.seasonality_optimization?.annual_self_consumed_mwh?.toFixed(2) || '-';
    strategyLabel = `<span style="color:#9c27b0">🌡️ Strategia: PASMA_SEZONOWOŚĆ (${mode}) - ${bestMWh} MWh/rok autokonsumpcji</span>`;
  } else if (isNPVStrategy) {
    const npvMode = results.npv_mode || 'constrained';
    if (npvMode === 'absolute') {
      strategyLabel = `<span style="color:#ff9800">📈 Strategia: Maksymalizacja NPV (cały zakres mocy)</span>`;
    } else {
      const range = results.npv_autoconsumption_range;
      strategyLabel = `<span style="color:#ff9800">📈 Strategia: Maksymalizacja NPV w zakresie ${range?.min || 80}-${range?.max || 95}% autokonsumpcji</span>`;
    }
  } else {
    strategyLabel = '<span style="color:#4caf50">⚡ Strategia: Autokonsumpcja</span>';
  }

  // Show success message with variant selector
  const variantCount = variantKeys.length;
  let variantText;
  if (isSeasonalityStrategy) {
    variantText = `Znaleziono optymalną instalację dla sezonu`;
  } else if (isNPVStrategy) {
    variantText = `Znaleziono optymalną instalację`;
  } else {
    variantText = `Znaleziono ${variantCount} wariantów`;
  }

  const selectorLabel = (isSeasonalityStrategy || isNPVStrategy)
    ? 'Optymalna instalacja:'
    : 'Wybierz wariant główny do dalszych obliczeń:';

  // Check if BESS is enabled (any variant has BESS data)
  const hasBess = variantKeys.some(key => {
    const v = results.key_variants[key];
    return v.bess_power_kw != null && v.bess_energy_kwh != null;
  });

  // Build comparison table rows
  const comparisonRows = variantKeys.map(key => {
    const v = results.key_variants[key];
    // Konwertuj wszystkie wartości na liczby dla bezpieczeństwa
    const capacity = parseFloat(v.capacity) || 0;
    const production = parseFloat(v.production) || 0;
    const selfConsumed = parseFloat(v.self_consumed) || 0;
    const autoConsumptionPct = parseFloat(v.auto_consumption_pct) || 0;
    const coveragePct = parseFloat(v.coverage_pct) || 0;

    const capacityMWp = (capacity / 1000).toFixed(2);
    const productionGWh = (production / 1000000).toFixed(2);
    const selfConsumedGWh = (selfConsumed / 1000000).toFixed(2);
    const exportedGWh = ((production - selfConsumed) / 1000000).toFixed(2);

    // BESS data
    const bessPower = v.bess_power_kw != null ? parseFloat(v.bess_power_kw).toFixed(0) : '-';
    const bessEnergy = v.bess_energy_kwh != null ? parseFloat(v.bess_energy_kwh).toFixed(0) : '-';
    const bessFromBattery = v.bess_self_consumed_from_bess_kwh != null
      ? (parseFloat(v.bess_self_consumed_from_bess_kwh) / 1000).toFixed(1)
      : '-';
    const bessCurtailed = v.bess_curtailed_kwh != null
      ? (parseFloat(v.bess_curtailed_kwh) / 1000).toFixed(1)
      : '-';

    // Baseline comparison (without BESS)
    const baseline = v.baseline_no_bess || {};
    const baselineAuto = parseFloat(baseline.auto_consumption_pct) || 0;
    const autoIncrease = autoConsumptionPct - baselineAuto;

    // NPV może być w v.npv_mln (mln PLN) lub v.npv (PLN) - konwertuj na liczbę
    let npvMln = null;
    if (v.npv_mln != null) {
      npvMln = parseFloat(v.npv_mln);
    } else if (v.npv != null) {
      npvMln = parseFloat(v.npv) / 1000000;
    }
    const npvInfo = (npvMln != null && !isNaN(npvMln)) ? npvMln.toFixed(2) : '-';

    // BESS columns (only if BESS enabled)
    const bessColumns = hasBess ? `
        <td style="color:#9c27b0;font-weight:500">${bessPower}/${bessEnergy}</td>
        <td>${bessFromBattery}</td>
        <td>${bessCurtailed}</td>
        <td style="color:#27ae60;font-weight:600">+${autoIncrease.toFixed(1)}%</td>
    ` : '';

    return `
      <tr>
        <td style="font-weight:600;color:#667eea">${key}</td>
        <td>${v.threshold}%</td>
        <td>${capacityMWp}</td>
        <td>${productionGWh}</td>
        <td>${selfConsumedGWh}</td>
        <td>${exportedGWh}</td>
        ${bessColumns}
        <td>${autoConsumptionPct.toFixed(1)}%</td>
        <td>${coveragePct.toFixed(1)}%</td>
        <td>${npvInfo}</td>
      </tr>
    `;
  }).join('');

  // BESS header columns
  const bessHeaders = hasBess ? `
    <th style="padding:12px 8px;background:#9c27b0">BESS [kW/kWh]</th>
    <th style="padding:12px 8px;background:#9c27b0">Z baterii [MWh]</th>
    <th style="padding:12px 8px;background:#9c27b0">Curtailment [MWh]</th>
    <th style="padding:12px 8px;background:#27ae60">Wzrost Auto.</th>
  ` : '';

  // Determine scenario count - use configurations_tested for seasonality optimization
  const scenarioCount = results.seasonality_optimization?.configurations_tested
    || results.scenarios?.length
    || 0;

  document.getElementById('configResults').innerHTML = `
    <div style="text-align:center;padding:40px;color:#00ff88">
      <div style="font-size:48px;margin-bottom:10px">✓</div>
      <div style="font-size:20px;font-weight:600;margin-bottom:10px">Analiza zakończona!</div>
      <div style="font-size:14px;color:#888">
        Przeanalizowano ${scenarioCount} konfiguracji<br>
        ${variantText}
      </div>
      <div style="margin-top:12px">${strategyLabel}</div>

      ${hasBess ? `
      <!-- BESS Summary Box -->
      <div style="margin-top:20px;padding:16px 24px;background:linear-gradient(135deg,#9c27b0 0%,#673ab7 100%);border-radius:12px;color:white;max-width:600px;margin-left:auto;margin-right:auto;">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
          <span style="font-size:24px">🔋</span>
          <span style="font-size:16px;font-weight:600;">Magazyn Energii BESS (0-Export Mode)</span>
        </div>
        <div style="font-size:13px;opacity:0.9;">
          System auto-sizing dobiera pojemność i moc baterii dla każdego wariantu PV.
          Nadwyżka produkcji PV jest magazynowana, brak eksportu do sieci (curtailment gdy bateria pełna).
        </div>
      </div>
      ` : ''}

      <!-- Comparison Table -->
      <div style="margin-top:30px;padding:20px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <h3 style="color:#2c3e50;margin-bottom:16px;font-size:16px;">Tabela Porównawcza Wariantów</h3>
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:13px;text-align:center;">
            <thead>
              <tr style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;">
                <th style="padding:12px 8px;border-radius:8px 0 0 0">Wariant</th>
                <th style="padding:12px 8px">Próg</th>
                <th style="padding:12px 8px">Moc [MWp]</th>
                <th style="padding:12px 8px">Produkcja [GWh/rok]</th>
                <th style="padding:12px 8px">Autokonsum. [GWh]</th>
                <th style="padding:12px 8px">Eksport [GWh]</th>
                ${bessHeaders}
                <th style="padding:12px 8px">Autokonsum. [%]</th>
                <th style="padding:12px 8px">Pokrycie [%]</th>
                <th style="padding:12px 8px;border-radius:0 8px 0 0">NPV [mln PLN]</th>
              </tr>
            </thead>
            <tbody>
              ${comparisonRows}
            </tbody>
          </table>
        </div>
      </div>

      <div style="margin-top:30px;padding:20px;background:#f8f9fa;border-radius:8px;max-width:500px;margin-left:auto;margin-right:auto;">
        <label style="display:block;font-size:14px;color:#2c3e50;font-weight:600;margin-bottom:10px;">
          ${selectorLabel}
        </label>
        <select id="masterVariantSelector" onchange="selectMasterVariant()" style="width:100%;padding:12px;font-size:14px;border:2px solid ${isNPVStrategy ? '#ff9800' : '#667eea'};border-radius:6px;background:white;cursor:pointer;">
          ${variantOptions}
        </select>
        <div id="masterVariantInfo" style="margin-top:10px;font-size:12px;color:#666;"></div>
      </div>

      <div style="margin-top:20px">
        <button class="btn" onclick="navigateToResults()">PRZEJDŹ DO WYNIKÓW →</button>
      </div>
    </div>
  `;

  // Restore previously selected variant if available
  const savedVariant = localStorage.getItem('masterVariant');
  if (savedVariant) {
    const selector = document.getElementById('masterVariantSelector');
    if (selector) {
      selector.value = savedVariant;
    }
  }
}

// Select master variant for all calculations
function selectMasterVariant() {
  const selector = document.getElementById('masterVariantSelector');
  if (!selector) return;

  const selectedVariant = selector.value;
  const analysisResults = JSON.parse(localStorage.getItem('pv_analysis_results'));

  if (!analysisResults || !analysisResults.key_variants || !analysisResults.key_variants[selectedVariant]) {
    return;
  }

  const variant = analysisResults.key_variants[selectedVariant];

  // Save master variant to localStorage
  localStorage.setItem('masterVariant', selectedVariant);
  localStorage.setItem('masterVariantData', JSON.stringify(variant));

  // Update info display
  const infoDiv = document.getElementById('masterVariantInfo');
  if (infoDiv) {
    infoDiv.innerHTML = `
      ✓ Wybrany wariant: <strong>${selectedVariant}</strong>
      (${(variant.capacity/1000).toFixed(2)} MWp,
      ${(variant.production/1000000).toFixed(2)} GWh/rok,
      ${variant.coverage_pct.toFixed(1)}% pokrycia)
    `;
  }

  // Notify shell about master variant selection
  notifyShell('MASTER_VARIANT_SELECTED', {
    variantKey: selectedVariant,
    variantData: variant
  });

  console.log('Master variant selected:', selectedVariant, variant);
}

// Navigate to results (tell shell to switch module)
function navigateToResults() {
  notifyShell('NAVIGATE', { module: 'comparison' });
}

// Export to Excel
async function exportToExcel() {
  const results = localStorage.getItem('pv_analysis_results');
  if (!results) {
    showMessage('⚠️ No analysis results to export. Run analysis first.', 'warning');
    return;
  }

  try {
    const data = JSON.parse(results);

    // Create workbook
    const wb = XLSX.utils.book_new();

    // Scenarios sheet
    const scenariosData = data.scenarios.map(s => ({
      'Capacity [kWp]': s.capacity,
      'Production [kWh]': s.production.toFixed(0),
      'Self-Consumed [kWh]': s.self_consumed.toFixed(0),
      'Exported [kWh]': s.exported.toFixed(0),
      'Auto-Consumption [%]': s.auto_consumption_pct.toFixed(2),
      'Coverage [%]': s.coverage_pct.toFixed(2)
    }));
    const ws1 = XLSX.utils.json_to_sheet(scenariosData);
    XLSX.utils.book_append_sheet(wb, ws1, 'Scenarios');

    // Variants sheet
    const variantsData = Object.entries(data.key_variants).map(([name, v]) => ({
      'Variant': name,
      'Threshold [%]': v.threshold,
      'Capacity [kWp]': v.capacity,
      'Production [GWh]': (v.production / 1000000).toFixed(2),
      'Self-Consumed [GWh]': (v.self_consumed / 1000000).toFixed(2),
      'Auto-Consumption [%]': v.auto_consumption_pct.toFixed(2),
      'Coverage [%]': v.coverage_pct.toFixed(2),
      'Meets Threshold': v.meets_threshold ? 'Yes' : 'No'
    }));
    const ws2 = XLSX.utils.json_to_sheet(variantsData);
    XLSX.utils.book_append_sheet(wb, ws2, 'Key Variants');

    // Generate file
    const filename = `pv_analysis_${new Date().toISOString().split('T')[0]}.xlsx`;
    XLSX.writeFile(wb, filename);

    showMessage(`✓ Exported to ${filename}`, 'success');
  } catch (error) {
    showMessage(`❌ Export failed: ${error.message}`, 'error');
    console.error('Export error:', error);
  }
}

// Export analysis logs to JSON file
function exportAnalysisLogs() {
  const logs = window.analysisLogs || [];

  if (logs.length === 0) {
    showMessage('Brak logów do eksportu. Najpierw uruchom analizę.', 'warning');
    return;
  }

  // Add system settings to logs
  const exportData = {
    exportDate: new Date().toISOString(),
    systemSettings: systemSettings,
    analysisLogs: logs
  };

  const json = JSON.stringify(exportData, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `pv_analysis_logs_${new Date().toISOString().split('T')[0]}.json`;
  a.click();

  URL.revokeObjectURL(url);
  console.log('Analysis logs exported');
  showMessage(`✓ Wyeksportowano ${logs.length} wpisów logów`, 'success');
}

// Show non-intrusive message toast
function showMessage(text, type = 'info') {
  const colors = {
    success: '#27ae60',
    warning: '#f39c12',
    error: '#e74c3c',
    info: '#3498db'
  };

  const msg = document.createElement('div');
  msg.style.cssText = `position:fixed;top:20px;left:50%;transform:translateX(-50%);background:${colors[type]};color:#fff;padding:16px 24px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.2);z-index:10001;font-size:14px;font-weight:600;max-width:500px;text-align:center`;
  msg.textContent = text;
  document.body.appendChild(msg);

  setTimeout(() => {
    if (document.body.contains(msg)) {
      document.body.removeChild(msg);
    }
  }, 3000);
}

// Clear all data (localStorage + sessionStorage)
function clearAllData() {
  // Show confirmation UI instead of browser confirm dialog
  const confirmMsg = document.createElement('div');
  confirmMsg.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;padding:24px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.3);z-index:10000;max-width:400px;border:2px solid #e74c3c';
  confirmMsg.innerHTML = `
    <div style="font-size:16px;font-weight:600;color:#e74c3c;margin-bottom:16px">⚠️ Czy na pewno chcesz wyczyścić wszystkie dane?</div>
    <div style="font-size:14px;color:#666;margin-bottom:20px;line-height:1.6">
      To usunie:<br>
      • Załadowane pliki<br>
      • Wyniki analiz<br>
      • Wybrane warianty<br>
      • Konfigurację<br><br>
      <strong>Tej operacji nie można cofnąć!</strong>
    </div>
    <div style="display:flex;gap:12px;justify-content:flex-end">
      <button id="cancelClear" style="padding:10px 20px;border:1px solid #ddd;border-radius:6px;background:#f5f5f5;cursor:pointer;font-size:14px;font-weight:600">Anuluj</button>
      <button id="confirmClear" style="padding:10px 20px;border:none;border-radius:6px;background:#e74c3c;color:#fff;cursor:pointer;font-size:14px;font-weight:600">Wyczyść dane</button>
    </div>
  `;

  document.body.appendChild(confirmMsg);

  // Handle cancel
  document.getElementById('cancelClear').onclick = () => {
    document.body.removeChild(confirmMsg);
  };

  // Handle confirm
  document.getElementById('confirmClear').onclick = () => {
    document.body.removeChild(confirmMsg);

    // Clear all localStorage keys
    const keysToRemove = [
      'pv_config',
      'pv_data_uploaded',
      'pv_data_info',
      'pv_analysis_results',
      'pv_analysis_config',
      'pvConfig',
      'analysisResults',
      'pvProductionData',
      'consumptionData',
      'masterVariant',
      'masterVariantData'
    ];

    keysToRemove.forEach(key => localStorage.removeItem(key));

    // Clear sessionStorage
    sessionStorage.clear();

    // Reset global state
    uploadedData = null;
    fileUploadedThisSession = false;
    analysisInProgress = false;

    // Notify shell to clear shared data
    notifyShell('DATA_CLEARED', {});

    // Show upload prompt
    showUploadPrompt();

    // Clear results area
    document.getElementById('configResults').innerHTML = `
      <p style="color:#666;text-align:center;margin-top:40px">
        Upload consumption data and configure analysis parameters
      </p>
    `;

    // Show success message
    showMessage('✓ Wszystkie dane zostały wyczyszczone!', 'success');
    console.log('All data cleared');
  };
}

// Notify parent shell via postMessage
function notifyShell(type, data) {
  if (window.parent !== window) {
    window.parent.postMessage({ type, data }, '*');
    console.log('Notified shell:', type, data);
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  console.log('Received message:', event.data);

  switch (event.data.type) {
    case 'DATA_AVAILABLE':
      uploadedData = true;
      if (event.data.data) {
        updateStatistics(event.data.data);
      }
      break;
    case 'RELOAD_CONFIG':
      loadSavedConfig();
      break;
    case 'SETTINGS_UPDATED':
      // Apply settings received from shell
      applySettingsFromShell(event.data.data);
      console.log('System settings received from shell');
      break;
  }
});
