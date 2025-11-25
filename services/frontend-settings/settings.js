// Settings Module - Centralized Configuration Management

console.log('⚙️ Settings module loaded');

// Default configuration values
const DEFAULT_CONFIG = {
  // Energy Tariff Components (PLN/MWh)
  energyActive: 550,
  distribution: 200,
  qualityFee: 10,
  ozeFee: 7,
  cogenerationFee: 10,
  capacityFee: 219,
  exciseTax: 5,

  // CAPEX Tiers (PLN/kWp)
  capexTiers: [
    { min: 150, max: 500, capex: 4200, id: 'capex1' },
    { min: 501, max: 1000, capex: 3800, id: 'capex2' },
    { min: 1001, max: 2500, capex: 3500, id: 'capex3' },
    { min: 2501, max: 5000, capex: 3200, id: 'capex4' },
    { min: 5001, max: 10000, capex: 3000, id: 'capex5' },
    { min: 10001, max: 15000, capex: 2850, id: 'capex6' },
    { min: 15001, max: 50000, capex: 2700, id: 'capex7' }
  ],

  // OPEX Parameters
  opexPerKwp: 15,
  eaasOM: 24,
  insuranceRate: 0.005,  // 0.5% of CAPEX per year
  landLeasePerKwp: 0,    // Land lease cost [PLN/kWp/year]

  // Financial Parameters
  discountRate: 7,
  degradationRate: 0.5,
  analysisPeriod: 25,
  inflationRate: 2.5,

  // IRR Calculation Mode
  useInflation: false,   // false = real IRR (constant prices), true = nominal IRR (inflation-indexed)
  irrMode: 'real',       // 'real' or 'nominal' - alternative to useInflation for clarity

  // EaaS Parameters
  eaasCurrency: 'PLN',       // 'PLN' or 'EUR'
  eaasDuration: 10,          // Contract duration in years
  eaasIndexation: 'fixed',   // 'fixed' (constant) or 'cpi' (inflation-indexed)
  eaasTargetIrrPln: 12.0,    // Target IRR for PLN contracts (%)
  eaasTargetIrrEur: 10.0,    // Target IRR for EUR contracts (%)
  cpiPln: 2.5,               // Annual CPI inflation rate for PLN (%)
  cpiEur: 2.0,               // Annual CPI inflation rate for EUR (%)
  fxPlnEur: 4.5,             // FX rate PLN/EUR

  // Weather Data Source
  weatherDataSource: 'pvgis', // 'pvgis' or 'clearsky'

  // Environmental Parameters (Advanced)
  altitude: 100,      // meters above sea level
  albedo: 0.2,        // ground reflectance (0.2 = grass, 0.3 = concrete, 0.8 = snow)
  soilingLoss: 2,     // soiling loss percentage (2-3% typical for Europe)

  // DC/AC Ratio Mode
  dcacMode: 'manual', // 'manual' (use tiers table) or 'auto' (automatic selection in future)

  // PV Installation Defaults - per type (Yield, Latitude, Tilt, Azimuth)
  // Ground South
  pvYield_ground_s: 1050,
  latitude_ground_s: 52.0,
  tilt_ground_s: 0,       // 0 = auto (uses latitude)
  azimuth_ground_s: 180,  // South
  // Roof East-West
  pvYield_roof_ew: 950,
  latitude_roof_ew: 52.0,
  tilt_roof_ew: 10,       // Low tilt for E-W
  azimuth_roof_ew: 90,    // East (will also calculate West at 270)
  // Ground East-West
  pvYield_ground_ew: 980,
  latitude_ground_ew: 52.0,
  tilt_ground_ew: 15,
  azimuth_ground_ew: 90,  // East (will also calculate West at 270)

  // DC/AC Ratio Tiers - by capacity range and installation type
  dcacTiers: [
    { min: 150, max: 500, ground_s: 1.15, roof_ew: 1.20, ground_ew: 1.25 },
    { min: 501, max: 1000, ground_s: 1.20, roof_ew: 1.25, ground_ew: 1.30 },
    { min: 1001, max: 2500, ground_s: 1.25, roof_ew: 1.30, ground_ew: 1.35 },
    { min: 2501, max: 5000, ground_s: 1.30, roof_ew: 1.35, ground_ew: 1.40 },
    { min: 5001, max: 10000, ground_s: 1.30, roof_ew: 1.35, ground_ew: 1.40 },
    { min: 10001, max: 15000, ground_s: 1.35, roof_ew: 1.40, ground_ew: 1.45 },
    { min: 15001, max: 50000, ground_s: 1.40, roof_ew: 1.45, ground_ew: 1.50 }
  ],

  // Analysis Range
  capMin: 1000,
  capMax: 50000,
  capStep: 500,

  // Autoconsumption Thresholds
  thrA: 95,
  thrB: 90,
  thrC: 85,
  thrD: 80
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  setupEventListeners();
  updateTotalEnergyPrice();
});

// Setup event listeners for auto-save and calculations
function setupEventListeners() {
  // Energy tariff inputs - update total on change
  const energyInputs = ['energyActive', 'distribution', 'qualityFee', 'ozeFee',
                        'cogenerationFee', 'capacityFee', 'exciseTax'];
  energyInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', updateTotalEnergyPrice);
    }
  });

  // All inputs - mark as changed
  document.querySelectorAll('input').forEach(input => {
    input.addEventListener('change', () => {
      markUnsaved();
    });
  });
}

// Calculate and display total energy price
function updateTotalEnergyPrice() {
  const total =
    parseFloat(document.getElementById('energyActive')?.value || 0) +
    parseFloat(document.getElementById('distribution')?.value || 0) +
    parseFloat(document.getElementById('qualityFee')?.value || 0) +
    parseFloat(document.getElementById('ozeFee')?.value || 0) +
    parseFloat(document.getElementById('cogenerationFee')?.value || 0) +
    parseFloat(document.getElementById('capacityFee')?.value || 0) +
    parseFloat(document.getElementById('exciseTax')?.value || 0);

  const totalInput = document.getElementById('totalEnergyPrice');
  if (totalInput) {
    totalInput.value = total.toFixed(0);
  }
}

// Load settings from localStorage
function loadSettings() {
  const saved = localStorage.getItem('pv_system_settings');
  let config = { ...DEFAULT_CONFIG }; // Start with all defaults

  if (saved) {
    try {
      const parsed = JSON.parse(saved);

      // Merge saved settings, but ensure numeric fields have valid values
      Object.keys(DEFAULT_CONFIG).forEach(key => {
        if (parsed[key] !== undefined && parsed[key] !== null && parsed[key] !== '') {
          // For numeric fields, ensure they are actual numbers
          if (typeof DEFAULT_CONFIG[key] === 'number') {
            const val = parseFloat(parsed[key]);
            if (!isNaN(val)) {
              config[key] = val;
            }
          } else if (Array.isArray(DEFAULT_CONFIG[key])) {
            // For arrays like capexTiers
            config[key] = parsed[key];
          } else {
            config[key] = parsed[key];
          }
        }
      });

      console.log('Loaded saved settings, merged with defaults');
    } catch (e) {
      console.error('Failed to parse saved settings:', e);
    }
  }

  // Apply settings to UI
  applySettingsToUI(config);

  // Recalculate total to ensure it's correct
  setTimeout(updateTotalEnergyPrice, 100);
}

// Apply configuration to UI inputs
function applySettingsToUI(config) {
  // Simple fields
  const simpleFields = [
    'energyActive', 'distribution', 'qualityFee', 'ozeFee', 'cogenerationFee',
    'capacityFee', 'exciseTax', 'opexPerKwp', 'eaasOM', 'insuranceRate', 'landLeasePerKwp',
    'discountRate', 'degradationRate', 'analysisPeriod', 'inflationRate',
    'eaasDuration', 'eaasTargetIrrPln', 'eaasTargetIrrEur', 'cpiPln', 'cpiEur', 'fxPlnEur',
    // Environmental parameters
    'altitude', 'albedo', 'soilingLoss',
    // DC/AC Mode
    'dcacMode',
    // PV params per type (Yield, Latitude, Tilt, Azimuth)
    'pvYield_ground_s', 'latitude_ground_s', 'tilt_ground_s', 'azimuth_ground_s',
    'pvYield_roof_ew', 'latitude_roof_ew', 'tilt_roof_ew', 'azimuth_roof_ew',
    'pvYield_ground_ew', 'latitude_ground_ew', 'tilt_ground_ew', 'azimuth_ground_ew',
    'capMin', 'capMax', 'capStep', 'thrA', 'thrB', 'thrC', 'thrD'
  ];

  // IRR mode checkbox
  const useInflationEl = document.getElementById('useInflation');
  if (useInflationEl) {
    useInflationEl.checked = config.useInflation || config.irrMode === 'nominal' || false;
  }

  simpleFields.forEach(field => {
    const el = document.getElementById(field);
    if (el) {
      // Use config value if exists, otherwise use default
      const value = config[field] !== undefined ? config[field] : DEFAULT_CONFIG[field];
      el.value = value;
    }
  });

  // EaaS currency (select element)
  const eaasCurrencyEl = document.getElementById('eaasCurrency');
  if (eaasCurrencyEl) {
    eaasCurrencyEl.value = config.eaasCurrency || DEFAULT_CONFIG.eaasCurrency;
  }

  // EaaS indexation (select element)
  const eaasIndexationEl = document.getElementById('eaasIndexation');
  if (eaasIndexationEl) {
    eaasIndexationEl.value = config.eaasIndexation || DEFAULT_CONFIG.eaasIndexation;
  }

  // Weather data source (select element)
  const weatherDataSourceEl = document.getElementById('weatherDataSource');
  if (weatherDataSourceEl) {
    weatherDataSourceEl.value = config.weatherDataSource || DEFAULT_CONFIG.weatherDataSource;
  }

  // CAPEX tiers
  const capexTiers = config.capexTiers || DEFAULT_CONFIG.capexTiers;
  capexTiers.forEach((tier, index) => {
    const el = document.getElementById(`capex${index + 1}`);
    if (el) {
      el.value = tier.capex;
    }
  });

  // DC/AC Ratio tiers
  const dcacTiers = config.dcacTiers || DEFAULT_CONFIG.dcacTiers;
  dcacTiers.forEach((tier, index) => {
    const tierNum = index + 1;
    const groundS = document.getElementById(`dcac_ground_s_${tierNum}`);
    const roofEw = document.getElementById(`dcac_roof_ew_${tierNum}`);
    const groundEw = document.getElementById(`dcac_ground_ew_${tierNum}`);
    if (groundS) groundS.value = tier.ground_s;
    if (roofEw) roofEw.value = tier.roof_ew;
    if (groundEw) groundEw.value = tier.ground_ew;
  });

  updateTotalEnergyPrice();
}

// Get current settings from UI
function getCurrentSettings() {
  const settings = {
    // Energy Tariff
    energyActive: parseFloat(document.getElementById('energyActive')?.value || DEFAULT_CONFIG.energyActive),
    distribution: parseFloat(document.getElementById('distribution')?.value || DEFAULT_CONFIG.distribution),
    qualityFee: parseFloat(document.getElementById('qualityFee')?.value || DEFAULT_CONFIG.qualityFee),
    ozeFee: parseFloat(document.getElementById('ozeFee')?.value || DEFAULT_CONFIG.ozeFee),
    cogenerationFee: parseFloat(document.getElementById('cogenerationFee')?.value || DEFAULT_CONFIG.cogenerationFee),
    capacityFee: parseFloat(document.getElementById('capacityFee')?.value || DEFAULT_CONFIG.capacityFee),
    exciseTax: parseFloat(document.getElementById('exciseTax')?.value || DEFAULT_CONFIG.exciseTax),

    // CAPEX Tiers
    capexTiers: [
      { min: 150, max: 500, capex: parseFloat(document.getElementById('capex1')?.value || 4200) },
      { min: 501, max: 1000, capex: parseFloat(document.getElementById('capex2')?.value || 3800) },
      { min: 1001, max: 2500, capex: parseFloat(document.getElementById('capex3')?.value || 3500) },
      { min: 2501, max: 5000, capex: parseFloat(document.getElementById('capex4')?.value || 3200) },
      { min: 5001, max: 10000, capex: parseFloat(document.getElementById('capex5')?.value || 3000) },
      { min: 10001, max: 15000, capex: parseFloat(document.getElementById('capex6')?.value || 2850) },
      { min: 15001, max: 50000, capex: parseFloat(document.getElementById('capex7')?.value || 2700) }
    ],

    // OPEX
    opexPerKwp: parseFloat(document.getElementById('opexPerKwp')?.value || DEFAULT_CONFIG.opexPerKwp),
    eaasOM: parseFloat(document.getElementById('eaasOM')?.value || DEFAULT_CONFIG.eaasOM),
    insuranceRate: parseFloat(document.getElementById('insuranceRate')?.value || DEFAULT_CONFIG.insuranceRate),
    landLeasePerKwp: parseFloat(document.getElementById('landLeasePerKwp')?.value || DEFAULT_CONFIG.landLeasePerKwp),

    // Financial
    discountRate: parseFloat(document.getElementById('discountRate')?.value || DEFAULT_CONFIG.discountRate),
    degradationRate: parseFloat(document.getElementById('degradationRate')?.value || DEFAULT_CONFIG.degradationRate),
    analysisPeriod: parseInt(document.getElementById('analysisPeriod')?.value || DEFAULT_CONFIG.analysisPeriod),
    inflationRate: parseFloat(document.getElementById('inflationRate')?.value || DEFAULT_CONFIG.inflationRate),

    // IRR Calculation Mode
    useInflation: document.getElementById('useInflation')?.checked || false,
    irrMode: document.getElementById('useInflation')?.checked ? 'nominal' : 'real',

    // EaaS
    eaasCurrency: document.getElementById('eaasCurrency')?.value || DEFAULT_CONFIG.eaasCurrency,
    eaasDuration: parseInt(document.getElementById('eaasDuration')?.value || DEFAULT_CONFIG.eaasDuration),
    eaasIndexation: document.getElementById('eaasIndexation')?.value || DEFAULT_CONFIG.eaasIndexation,
    eaasTargetIrrPln: parseFloat(document.getElementById('eaasTargetIrrPln')?.value || DEFAULT_CONFIG.eaasTargetIrrPln),
    eaasTargetIrrEur: parseFloat(document.getElementById('eaasTargetIrrEur')?.value || DEFAULT_CONFIG.eaasTargetIrrEur),
    cpiPln: parseFloat(document.getElementById('cpiPln')?.value || DEFAULT_CONFIG.cpiPln),
    cpiEur: parseFloat(document.getElementById('cpiEur')?.value || DEFAULT_CONFIG.cpiEur),
    fxPlnEur: parseFloat(document.getElementById('fxPlnEur')?.value || DEFAULT_CONFIG.fxPlnEur),

    // Weather Data Source
    weatherDataSource: document.getElementById('weatherDataSource')?.value || DEFAULT_CONFIG.weatherDataSource,

    // Environmental Parameters (Advanced)
    altitude: parseFloat(document.getElementById('altitude')?.value || DEFAULT_CONFIG.altitude),
    albedo: parseFloat(document.getElementById('albedo')?.value || DEFAULT_CONFIG.albedo),
    soilingLoss: parseFloat(document.getElementById('soilingLoss')?.value || DEFAULT_CONFIG.soilingLoss),

    // DC/AC Ratio Mode
    dcacMode: document.getElementById('dcacMode')?.value || DEFAULT_CONFIG.dcacMode,

    // PV Installation - per type (Yield, Latitude, Tilt, Azimuth)
    // Ground South
    pvYield_ground_s: parseFloat(document.getElementById('pvYield_ground_s')?.value || DEFAULT_CONFIG.pvYield_ground_s),
    latitude_ground_s: parseFloat(document.getElementById('latitude_ground_s')?.value || DEFAULT_CONFIG.latitude_ground_s),
    tilt_ground_s: parseFloat(document.getElementById('tilt_ground_s')?.value || DEFAULT_CONFIG.tilt_ground_s),
    azimuth_ground_s: parseFloat(document.getElementById('azimuth_ground_s')?.value || DEFAULT_CONFIG.azimuth_ground_s),
    // Roof East-West
    pvYield_roof_ew: parseFloat(document.getElementById('pvYield_roof_ew')?.value || DEFAULT_CONFIG.pvYield_roof_ew),
    latitude_roof_ew: parseFloat(document.getElementById('latitude_roof_ew')?.value || DEFAULT_CONFIG.latitude_roof_ew),
    tilt_roof_ew: parseFloat(document.getElementById('tilt_roof_ew')?.value || DEFAULT_CONFIG.tilt_roof_ew),
    azimuth_roof_ew: parseFloat(document.getElementById('azimuth_roof_ew')?.value || DEFAULT_CONFIG.azimuth_roof_ew),
    // Ground East-West
    pvYield_ground_ew: parseFloat(document.getElementById('pvYield_ground_ew')?.value || DEFAULT_CONFIG.pvYield_ground_ew),
    latitude_ground_ew: parseFloat(document.getElementById('latitude_ground_ew')?.value || DEFAULT_CONFIG.latitude_ground_ew),
    tilt_ground_ew: parseFloat(document.getElementById('tilt_ground_ew')?.value || DEFAULT_CONFIG.tilt_ground_ew),
    azimuth_ground_ew: parseFloat(document.getElementById('azimuth_ground_ew')?.value || DEFAULT_CONFIG.azimuth_ground_ew),

    // DC/AC Ratio Tiers
    dcacTiers: [
      { min: 150, max: 500,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_1')?.value || 1.15),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_1')?.value || 1.20),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_1')?.value || 1.25) },
      { min: 501, max: 1000,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_2')?.value || 1.20),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_2')?.value || 1.25),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_2')?.value || 1.30) },
      { min: 1001, max: 2500,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_3')?.value || 1.25),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_3')?.value || 1.30),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_3')?.value || 1.35) },
      { min: 2501, max: 5000,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_4')?.value || 1.30),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_4')?.value || 1.35),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_4')?.value || 1.40) },
      { min: 5001, max: 10000,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_5')?.value || 1.30),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_5')?.value || 1.35),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_5')?.value || 1.40) },
      { min: 10001, max: 15000,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_6')?.value || 1.35),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_6')?.value || 1.40),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_6')?.value || 1.45) },
      { min: 15001, max: 50000,
        ground_s: parseFloat(document.getElementById('dcac_ground_s_7')?.value || 1.40),
        roof_ew: parseFloat(document.getElementById('dcac_roof_ew_7')?.value || 1.45),
        ground_ew: parseFloat(document.getElementById('dcac_ground_ew_7')?.value || 1.50) }
    ],

    // Analysis Range
    capMin: parseFloat(document.getElementById('capMin')?.value || DEFAULT_CONFIG.capMin),
    capMax: parseFloat(document.getElementById('capMax')?.value || DEFAULT_CONFIG.capMax),
    capStep: parseFloat(document.getElementById('capStep')?.value || DEFAULT_CONFIG.capStep),

    // Thresholds
    thrA: parseFloat(document.getElementById('thrA')?.value || DEFAULT_CONFIG.thrA),
    thrB: parseFloat(document.getElementById('thrB')?.value || DEFAULT_CONFIG.thrB),
    thrC: parseFloat(document.getElementById('thrC')?.value || DEFAULT_CONFIG.thrC),
    thrD: parseFloat(document.getElementById('thrD')?.value || DEFAULT_CONFIG.thrD)
  };

  // Add calculated total energy price
  settings.totalEnergyPrice = settings.energyActive + settings.distribution +
    settings.qualityFee + settings.ozeFee + settings.cogenerationFee +
    settings.capacityFee + settings.exciseTax;

  return settings;
}

// Save all settings
function saveAllSettings() {
  const settings = getCurrentSettings();

  // Save to localStorage
  localStorage.setItem('pv_system_settings', JSON.stringify(settings));

  // Also save in legacy formats for backwards compatibility
  saveLegacyFormats(settings);

  // Notify other modules
  notifySettingsChanged(settings);

  showStatus('Ustawienia zapisane!', 'success');
  console.log('Settings saved:', settings);
}

// Save in legacy formats for backwards compatibility with other modules
function saveLegacyFormats(settings) {
  // Legacy pv_config format (for Configuration module)
  const legacyConfig = {
    pvType: 'ground_s',
    yield: settings.pvYield,
    dcac: settings.dcacRatio,
    capMin: settings.capMin,
    capMax: settings.capMax,
    capStep: settings.capStep,
    thrA: settings.thrA,
    thrB: settings.thrB,
    thrC: settings.thrC,
    thrD: settings.thrD,
    optimizationStrategy: 'autoconsumption',
    npvEnergyPrice: settings.totalEnergyPrice,
    npvOpex: settings.opexPerKwp,
    capex1: settings.capexTiers[0].capex,
    capex2: settings.capexTiers[1].capex,
    capex3: settings.capexTiers[2].capex,
    capex4: settings.capexTiers[3].capex,
    capex5: settings.capexTiers[4].capex,
    capex6: settings.capexTiers[5].capex,
    capex7: settings.capexTiers[6].capex
  };
  localStorage.setItem('pv_config', JSON.stringify(legacyConfig));
}

// Reset to default values
function resetToDefaults() {
  if (!confirm('Czy na pewno chcesz przywrócić domyślne ustawienia?')) {
    return;
  }

  applySettingsToUI(DEFAULT_CONFIG);
  saveAllSettings();
  showStatus('Przywrócono domyślne ustawienia', 'success');
}

// Export settings to JSON file
function exportSettings() {
  const settings = getCurrentSettings();
  const json = JSON.stringify(settings, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `pv_settings_${new Date().toISOString().split('T')[0]}.json`;
  a.click();

  URL.revokeObjectURL(url);
  showStatus('Ustawienia wyeksportowane', 'success');
}

// Import settings from JSON file
function importSettings() {
  document.getElementById('importFile').click();
}

// Handle file import
function handleImport(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const settings = JSON.parse(e.target.result);
      applySettingsToUI(settings);
      saveAllSettings();
      showStatus('Ustawienia zaimportowane', 'success');
    } catch (error) {
      showStatus('Błąd importu: nieprawidłowy format JSON', 'error');
      console.error('Import error:', error);
    }
  };
  reader.readAsText(file);

  // Reset file input
  event.target.value = '';
}

// Notify other modules about settings change
function notifySettingsChanged(settings) {
  if (window.parent !== window) {
    window.parent.postMessage({
      type: 'SETTINGS_CHANGED',
      data: settings
    }, '*');
    console.log('Notified shell about settings change');
  }
}

// Mark settings as unsaved
function markUnsaved() {
  // Could add visual indicator that settings need saving
}

// Show status message
function showStatus(message, type) {
  const status = document.getElementById('saveStatus');
  if (status) {
    status.textContent = message;
    status.className = `save-status show ${type}`;

    setTimeout(() => {
      status.className = 'save-status';
    }, 3000);
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  switch (event.data.type) {
    case 'REQUEST_SETTINGS':
      // Send current settings to requesting module
      const settings = getCurrentSettings();
      if (window.parent !== window) {
        window.parent.postMessage({
          type: 'SETTINGS_RESPONSE',
          data: settings
        }, '*');
      }
      break;

    case 'RELOAD_SETTINGS':
      loadSettings();
      break;
  }
});

// Utility function to get CAPEX for capacity (can be called from other modules)
function getCapexForCapacity(capacityKwp) {
  const settings = getCurrentSettings();
  for (const tier of settings.capexTiers) {
    if (capacityKwp >= tier.min && capacityKwp <= tier.max) {
      return tier.capex;
    }
  }
  // Fallback
  if (capacityKwp > 50000) return settings.capexTiers[6].capex;
  return settings.capexTiers[0].capex;
}

// Utility function to get DC/AC ratio for capacity and installation type
function getDcacForCapacity(capacityKwp, pvType) {
  const settings = getCurrentSettings();
  const dcacTiers = settings.dcacTiers || DEFAULT_CONFIG.dcacTiers;

  for (const tier of dcacTiers) {
    if (capacityKwp >= tier.min && capacityKwp <= tier.max) {
      return tier[pvType] || tier.ground_s;
    }
  }
  // Fallback - use last tier for very large installations
  if (capacityKwp > 50000) {
    return dcacTiers[6][pvType] || dcacTiers[6].ground_s;
  }
  // Fallback - use first tier for very small installations
  return dcacTiers[0][pvType] || dcacTiers[0].ground_s;
}

// ============================================================================
// NEW: CPH Tariff Management
// ============================================================================

// Load CPH prices from JSON file (DISABLED - CPH218 removed)
function loadCPHPrices() {
  alert('⚠️ Funkcja loadCPHPrices została wyłączona');
  console.warn('loadCPHPrices() called but function is disabled');
}

// Make loadCPHPrices globally available
window.loadCPHPrices = loadCPHPrices;

// ============================================================================
// NEW: Polish Holidays Calendar
// ============================================================================

// Get Polish national holidays for a given year
function getPolishHolidays(year) {
  const holidays = [];

  // Fixed holidays
  holidays.push(new Date(year, 0, 1));   // Nowy Rok
  holidays.push(new Date(year, 0, 6));   // Trzech Króli
  holidays.push(new Date(year, 4, 1));   // Święto Pracy
  holidays.push(new Date(year, 4, 3));   // Święto Konstytucji 3 Maja
  holidays.push(new Date(year, 7, 15));  // Wniebowzięcie NMP
  holidays.push(new Date(year, 10, 1));  // Wszystkich Świętych
  holidays.push(new Date(year, 10, 11)); // Święto Niepodległości
  holidays.push(new Date(year, 11, 25)); // Boże Narodzenie (1 dzień)
  holidays.push(new Date(year, 11, 26)); // Boże Narodzenie (2 dzień)
  holidays.push(new Date(year, 11, 24)); // Wigilia (treated as holiday for capacity fee)

  // Movable holidays (Easter-based)
  const easter = getEasterDate(year);
  holidays.push(easter); // Wielkanoc
  holidays.push(new Date(easter.getTime() + 86400000)); // Poniedziałek Wielkanocny
  holidays.push(new Date(easter.getTime() + 49 * 86400000)); // Zielone Świątki
  holidays.push(new Date(easter.getTime() + 60 * 86400000)); // Boże Ciało

  return holidays;
}

// Calculate Easter date using Meeus algorithm
function getEasterDate(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31) - 1; // 0-indexed
  const day = ((h + l - 7 * m + 114) % 31) + 1;

  return new Date(year, month, day);
}

// Check if a date is a Polish holiday
function isPolishHoliday(date) {
  const year = date.getFullYear();
  const holidays = getPolishHolidays(year);

  const dateStr = date.toISOString().split('T')[0];
  return holidays.some(holiday => holiday.toISOString().split('T')[0] === dateStr);
}

// Check if a date is a workday (Monday-Friday, not a holiday)
function isWorkday(date) {
  const dayOfWeek = date.getDay();
  // 0 = Sunday, 6 = Saturday
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    return false;
  }
  return !isPolishHoliday(date);
}

// Check if an hour is in peak hours (7-22 for workdays only)
function isPeakHour(date) {
  const settings = getCurrentSettings();
  const peakStart = settings.peakHourStart || 7;
  const peakEnd = settings.peakHourEnd || 22;

  // Check if it's a workday
  if (!isWorkday(date)) {
    return false;
  }

  // Check if hour is within peak range
  const hour = date.getHours();
  return hour >= peakStart && hour < peakEnd;
}

// ============================================================================
// NEW: Capacity Fee Classification (K1-K4)
// ============================================================================

// Calculate consumption profile (ratio of peak vs off-peak consumption)
function calculateConsumptionProfile(hourlyData, startDate = '2024-01-01') {
  let peakConsumption = 0;
  let offPeakConsumption = 0;

  const start = new Date(startDate);

  for (let hour = 0; hour < hourlyData.length; hour++) {
    const currentDate = new Date(start.getTime() + hour * 3600000); // Add hours
    const consumption = hourlyData[hour];

    if (isPeakHour(currentDate)) {
      peakConsumption += consumption;
    } else {
      offPeakConsumption += consumption;
    }
  }

  const totalConsumption = peakConsumption + offPeakConsumption;
  const peakRatio = totalConsumption > 0 ? (peakConsumption / totalConsumption) * 100 : 0;

  return {
    peakConsumption,
    offPeakConsumption,
    totalConsumption,
    peakRatio: peakRatio.toFixed(2)
  };
}

// Classify company into capacity fee group (K1-K4) based on consumption profile
function classifyCapacityFeeGroup(peakRatio) {
  const settings = getCurrentSettings();

  // Check K1 (highest)
  if (peakRatio >= settings.k1_min && peakRatio <= settings.k1_max) {
    return {
      group: 'K1',
      coefficient: settings.k1_coeff,
      peakRatio: peakRatio
    };
  }

  // Check K2
  if (peakRatio >= settings.k2_min && peakRatio <= settings.k2_max) {
    return {
      group: 'K2',
      coefficient: settings.k2_coeff,
      peakRatio: peakRatio
    };
  }

  // Check K3
  if (peakRatio >= settings.k3_min && peakRatio <= settings.k3_max) {
    return {
      group: 'K3',
      coefficient: settings.k3_coeff,
      peakRatio: peakRatio
    };
  }

  // K4 (lowest) - default
  return {
    group: 'K4',
    coefficient: settings.k4_coeff,
    peakRatio: peakRatio
  };
}

// Calculate capacity fee using new K1-K4 system
function calculateCapacityFee(hourlyData, startDate = '2024-01-01') {
  const settings = getCurrentSettings();

  // Calculate profile
  const profile = calculateConsumptionProfile(hourlyData, startDate);

  // Classify into K group
  const kGroup = classifyCapacityFeeGroup(parseFloat(profile.peakRatio));

  // Calculate capacity fee: A × Energy_peak × Rate
  // Convert Wh to MWh
  const peakEnergyMWh = profile.peakConsumption / 1000000;
  const capacityFee = kGroup.coefficient * peakEnergyMWh * settings.capacityFeeRate;

  return {
    profile: profile,
    kGroup: kGroup,
    capacityFeePLN: capacityFee.toFixed(2),
    capacityFeePerMWh: (capacityFee / (profile.totalConsumption / 1000000)).toFixed(2)
  };
}

// Make settings globally available for other scripts
window.PVSettings = {
  get: getCurrentSettings,
  getCapexForCapacity: getCapexForCapacity,
  getDcacForCapacity: getDcacForCapacity,
  DEFAULT: DEFAULT_CONFIG,
  // NEW functions
  loadCPHPrices: loadCPHPrices,
  getPolishHolidays: getPolishHolidays,
  isPolishHoliday: isPolishHoliday,
  isWorkday: isWorkday,
  isPeakHour: isPeakHour,
  calculateConsumptionProfile: calculateConsumptionProfile,
  classifyCapacityFeeGroup: classifyCapacityFeeGroup,
  calculateCapacityFee: calculateCapacityFee
};
