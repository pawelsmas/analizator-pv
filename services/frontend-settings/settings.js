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

  // CAPEX Power Ranges (shared for all types)
  capexRanges: [
    { min: 50, max: 150 },
    { min: 150, max: 300 },
    { min: 300, max: 1000 },
    { min: 1000, max: 3000 },
    { min: 3000, max: 10000 },
    { min: 10000, max: Infinity }
  ],

  // CAPEX per Installation Type (cost, margin, sale = cost * (1 + margin/100))
  capexPerType: {
    ground_s: [
      { cost: 2800, margin: 23, sale: 3444 },
      { cost: 2400, margin: 20, sale: 2880 },
      { cost: 2000, margin: 18, sale: 2360 },
      { cost: 1700, margin: 16, sale: 1972 },
      { cost: 1500, margin: 15, sale: 1725 },
      { cost: 1400, margin: 13, sale: 1582 }
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
      { cost: 3100, margin: 23, sale: 3813 },
      { cost: 2700, margin: 20, sale: 3240 },
      { cost: 2300, margin: 18, sale: 2714 },
      { cost: 1950, margin: 16, sale: 2262 },
      { cost: 1650, margin: 15, sale: 1898 },
      null // No installations above 10 MWp for roof
    ],
    carport: [
      { cost: 3500, margin: 23, sale: 4305 },
      { cost: 3200, margin: 20, sale: 3840 },
      { cost: 2800, margin: 18, sale: 3304 },
      { cost: 2500, margin: 16, sale: 2900 },
      { cost: 2200, margin: 15, sale: 2530 },
      { cost: 2000, margin: 13, sale: 2260 }
    ]
  },

  // Legacy CAPEX Tiers (for backwards compatibility)
  capexTiers: [
    { min: 50, max: 150, capex: 3444, id: 'capex1' },
    { min: 150, max: 300, capex: 2880, id: 'capex2' },
    { min: 300, max: 1000, capex: 2360, id: 'capex3' },
    { min: 1000, max: 3000, capex: 1972, id: 'capex4' },
    { min: 3000, max: 10000, capex: 1725, id: 'capex5' },
    { min: 10000, max: 50000, capex: 1582, id: 'capex6' }
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

  // EaaS Parameters - Contract Basics
  eaasCurrency: 'PLN',       // 'PLN' or 'EUR'
  eaasDuration: 10,          // Contract duration in years
  eaasIndexation: 'fixed',   // 'fixed' (constant) or 'cpi' (inflation-indexed)
  eaasTargetIrrPln: 12.0,    // Target IRR for PLN contracts (%)
  eaasTargetIrrEur: 10.0,    // Target IRR for EUR contracts (%)
  cpiPln: 2.5,               // Annual CPI inflation rate for PLN (%)
  cpiEur: 2.0,               // Annual CPI inflation rate for EUR (%)
  fxPlnEur: 4.5,             // FX rate PLN/EUR
  irrDriver: 'PLN',          // 'PLN' or 'EUR' - currency for IRR optimization

  // EaaS Parameters - Tax & Depreciation
  citRate: 19.0,             // Corporate Income Tax rate (%)
  projectLifetime: 25,       // Total project lifetime [years]
  depreciationMethod: 'linear', // 'linear' or 'degressive'
  depreciationPeriod: 20,    // Depreciation period [years]

  // EaaS Parameters - Financing (Debt)
  leverageRatio: 0,          // % of CAPEX financed by debt (0-80%)
  costOfDebt: 7.0,           // Nominal debt interest rate (%)
  debtTenor: 8,              // Debt repayment period [years]
  debtGracePeriod: 0,        // Grace period - interest only [years]
  debtAmortization: 'annuity', // 'annuity' or 'linear'

  // EaaS Parameters - Technical
  availabilityFactor: 98.0,  // Plant availability (%)
  zeroExportMargin: 0,       // Safety margin for 0-export [%]

  // EaaS Parameters - CPI Indexation Limits
  indexationFrequency: 'annual', // 'annual' or 'quarterly'
  cpiFloor: 0,               // Minimum CPI applied (%)
  cpiCapAnnual: 5.0,         // Maximum annual CPI (%)
  cpiCapTotal: 50.0,         // Maximum cumulative CPI over contract (%)

  // EaaS Parameters - Risk
  expectedLossRate: 0,       // Expected credit loss rate (%)

  // Production Scenarios (P-factors for risk analysis)
  // P50 = median, P75/P90 = lower percentiles (more conservative)
  productionP50Factor: 1.00,  // 100% of expected production (median)
  productionP75Factor: 0.97,  // 97% - 75th percentile (25% chance of being lower)
  productionP90Factor: 0.94,  // 94% - 90th percentile (10% chance of being lower)

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
  // Initialize and render dynamic CAPEX tables
  initCapexData();
  renderAllCapexTables();
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
  // Simple fields (inputs with numeric or text values)
  const simpleFields = [
    'energyActive', 'distribution', 'qualityFee', 'ozeFee', 'cogenerationFee',
    'capacityFee', 'exciseTax', 'opexPerKwp', 'eaasOM', 'insuranceRate', 'landLeasePerKwp',
    'discountRate', 'degradationRate', 'analysisPeriod', 'inflationRate',
    // EaaS basic
    'eaasDuration', 'eaasTargetIrrPln', 'eaasTargetIrrEur', 'cpiPln', 'cpiEur', 'fxPlnEur',
    // EaaS tax & depreciation
    'citRate', 'projectLifetime', 'depreciationPeriod',
    // EaaS financing
    'leverageRatio', 'costOfDebt', 'debtTenor', 'debtGracePeriod',
    // EaaS technical
    'availabilityFactor', 'zeroExportMargin',
    // EaaS CPI limits
    'cpiFloor', 'cpiCapAnnual', 'cpiCapTotal',
    // EaaS risk
    'expectedLossRate',
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

  // Select fields
  const selectFields = [
    'eaasCurrency', 'eaasIndexation', 'irrDriver',
    'depreciationMethod', 'debtAmortization', 'indexationFrequency',
    'weatherDataSource'
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

  // Apply select fields
  selectFields.forEach(field => {
    const el = document.getElementById(field);
    if (el) {
      el.value = config[field] !== undefined ? config[field] : DEFAULT_CONFIG[field];
    }
  });

  // CAPEX per type (NEW)
  applyCapexPerTypeToUI(config);

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

    // CAPEX Ranges (NEW)
    capexRanges: getCapexRangesFromUI(),

    // CAPEX per Type (NEW)
    capexPerType: getCapexPerTypeFromUI(),

    // Legacy CAPEX Tiers (for backwards compatibility - uses ground_s sale prices)
    capexTiers: (function() {
      const ranges = getCapexRangesFromUI();
      const perType = getCapexPerTypeFromUI();
      return ranges.map((range, i) => ({
        min: range.min,
        max: range.max === Infinity ? 50000 : range.max,
        capex: perType.ground_s[i]?.sale || DEFAULT_CONFIG.capexPerType.ground_s[i]?.sale || 3000
      }));
    })(),

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

    // EaaS - Contract Basics
    eaasCurrency: document.getElementById('eaasCurrency')?.value || DEFAULT_CONFIG.eaasCurrency,
    eaasDuration: parseInt(document.getElementById('eaasDuration')?.value || DEFAULT_CONFIG.eaasDuration),
    eaasIndexation: document.getElementById('eaasIndexation')?.value || DEFAULT_CONFIG.eaasIndexation,
    eaasTargetIrrPln: parseFloat(document.getElementById('eaasTargetIrrPln')?.value || DEFAULT_CONFIG.eaasTargetIrrPln),
    eaasTargetIrrEur: parseFloat(document.getElementById('eaasTargetIrrEur')?.value || DEFAULT_CONFIG.eaasTargetIrrEur),
    cpiPln: parseFloat(document.getElementById('cpiPln')?.value || DEFAULT_CONFIG.cpiPln),
    cpiEur: parseFloat(document.getElementById('cpiEur')?.value || DEFAULT_CONFIG.cpiEur),
    fxPlnEur: parseFloat(document.getElementById('fxPlnEur')?.value || DEFAULT_CONFIG.fxPlnEur),
    irrDriver: document.getElementById('irrDriver')?.value || DEFAULT_CONFIG.irrDriver,

    // EaaS - Tax & Depreciation
    citRate: parseFloat(document.getElementById('citRate')?.value || DEFAULT_CONFIG.citRate),
    projectLifetime: parseInt(document.getElementById('projectLifetime')?.value || DEFAULT_CONFIG.projectLifetime),
    depreciationMethod: document.getElementById('depreciationMethod')?.value || DEFAULT_CONFIG.depreciationMethod,
    depreciationPeriod: parseInt(document.getElementById('depreciationPeriod')?.value || DEFAULT_CONFIG.depreciationPeriod),

    // EaaS - Financing (Debt)
    leverageRatio: parseFloat(document.getElementById('leverageRatio')?.value || DEFAULT_CONFIG.leverageRatio),
    costOfDebt: parseFloat(document.getElementById('costOfDebt')?.value || DEFAULT_CONFIG.costOfDebt),
    debtTenor: parseInt(document.getElementById('debtTenor')?.value || DEFAULT_CONFIG.debtTenor),
    debtGracePeriod: parseInt(document.getElementById('debtGracePeriod')?.value || DEFAULT_CONFIG.debtGracePeriod),
    debtAmortization: document.getElementById('debtAmortization')?.value || DEFAULT_CONFIG.debtAmortization,

    // EaaS - Technical
    availabilityFactor: parseFloat(document.getElementById('availabilityFactor')?.value || DEFAULT_CONFIG.availabilityFactor),
    zeroExportMargin: parseFloat(document.getElementById('zeroExportMargin')?.value || DEFAULT_CONFIG.zeroExportMargin),

    // EaaS - CPI Indexation Limits
    indexationFrequency: document.getElementById('indexationFrequency')?.value || DEFAULT_CONFIG.indexationFrequency,
    cpiFloor: parseFloat(document.getElementById('cpiFloor')?.value || DEFAULT_CONFIG.cpiFloor),
    cpiCapAnnual: parseFloat(document.getElementById('cpiCapAnnual')?.value || DEFAULT_CONFIG.cpiCapAnnual),
    cpiCapTotal: parseFloat(document.getElementById('cpiCapTotal')?.value || DEFAULT_CONFIG.cpiCapTotal),

    // EaaS - Risk
    expectedLossRate: parseFloat(document.getElementById('expectedLossRate')?.value || DEFAULT_CONFIG.expectedLossRate),

    // Production Scenarios (P-factors)
    productionP50Factor: parseFloat(document.getElementById('productionP50Factor')?.value || DEFAULT_CONFIG.productionP50Factor),
    productionP75Factor: parseFloat(document.getElementById('productionP75Factor')?.value || DEFAULT_CONFIG.productionP75Factor),
    productionP90Factor: parseFloat(document.getElementById('productionP90Factor')?.value || DEFAULT_CONFIG.productionP90Factor),

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
  // Safely get capex value with fallback
  const getCapex = (index) => {
    if (settings.capexTiers && settings.capexTiers[index]) {
      return settings.capexTiers[index].capex || settings.capexTiers[index].sale || 3000;
    }
    // Fallback to last available tier or default
    const lastTier = settings.capexTiers && settings.capexTiers.length > 0
      ? settings.capexTiers[settings.capexTiers.length - 1]
      : null;
    return lastTier ? (lastTier.capex || lastTier.sale || 3000) : 3000;
  };

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
    capex1: getCapex(0),
    capex2: getCapex(1),
    capex3: getCapex(2),
    capex4: getCapex(3),
    capex5: getCapex(4),
    capex6: getCapex(5),
    capex7: getCapex(6)
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

// ============================================================================
// CAPEX Per Type Management - Dynamic Tables with Add/Remove
// ============================================================================

// Type configurations with styling
const CAPEX_TYPE_CONFIG = {
  ground_s: {
    name: 'Grunt Południe',
    icon: '🌍',
    colors: {
      bg: '#e8f5e9', border: '#4caf50', headerBg: '#c8e6c9',
      cellBorder: '#a5d6a7', saleBg: '#81c784', textColor: '#2e7d32'
    }
  },
  ground_ew: {
    name: 'Grunt Wschód-Zachód',
    icon: '🌍',
    colors: {
      bg: '#fff3e0', border: '#ff9800', headerBg: '#ffe0b2',
      cellBorder: '#ffcc80', saleBg: '#ffb74d', textColor: '#e65100'
    }
  },
  roof_ew: {
    name: 'Dach Wschód-Zachód',
    icon: '🏠',
    colors: {
      bg: '#e3f2fd', border: '#2196f3', headerBg: '#90caf9',
      cellBorder: '#64b5f6', saleBg: '#42a5f5', textColor: '#1565c0'
    }
  },
  carport: {
    name: 'Carport',
    icon: '🚗',
    colors: {
      bg: '#f3e5f5', border: '#9c27b0', headerBg: '#e1bee7',
      cellBorder: '#ce93d8', saleBg: '#ba68c8', textColor: '#7b1fa2'
    }
  }
};

// In-memory storage for CAPEX data per type
let capexDataPerType = null;

// Initialize CAPEX data from config or defaults
function initCapexData() {
  const saved = localStorage.getItem('pv_system_settings');
  let config = DEFAULT_CONFIG;

  if (saved) {
    try {
      config = { ...DEFAULT_CONFIG, ...JSON.parse(saved) };
    } catch (e) {
      console.error('Failed to parse saved settings:', e);
    }
  }

  capexDataPerType = JSON.parse(JSON.stringify(config.capexPerType || DEFAULT_CONFIG.capexPerType));

  // Ensure each type has ranges stored with tiers
  const types = ['ground_s', 'ground_ew', 'roof_ew', 'carport'];
  const defaultRanges = config.capexRanges || DEFAULT_CONFIG.capexRanges;

  types.forEach(type => {
    if (!capexDataPerType[type]) {
      capexDataPerType[type] = [];
    }
    // Attach range info to each tier
    capexDataPerType[type] = capexDataPerType[type].map((tier, i) => {
      if (!tier) return null;
      return {
        ...tier,
        min: tier.min !== undefined ? tier.min : (defaultRanges[i]?.min || 0),
        max: tier.max !== undefined ? tier.max : (defaultRanges[i]?.max || Infinity)
      };
    });
  });
}

// Render CAPEX table for a specific type
function renderCapexTable(type) {
  const container = document.getElementById(`capex_${type}`);
  if (!container) return;

  const cfg = CAPEX_TYPE_CONFIG[type];
  const tiers = capexDataPerType[type] || [];

  let html = `
    <div style="padding:15px;background:${cfg.colors.bg};border-radius:8px;border-left:4px solid ${cfg.colors.border}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div style="font-weight:600;color:${cfg.colors.textColor}">${cfg.icon} ${cfg.name} - Przedziały CAPEX</div>
        <button onclick="addCapexTier('${type}')" style="padding:6px 12px;background:${cfg.colors.border};color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600">
          ➕ Dodaj przedział
        </button>
      </div>
      <table class="capex-table" style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:${cfg.colors.headerBg}">
            <th style="padding:8px;text-align:left;border:1px solid ${cfg.colors.cellBorder}">Od [kWp]</th>
            <th style="padding:8px;text-align:left;border:1px solid ${cfg.colors.cellBorder}">Do [kWp]</th>
            <th style="padding:8px;text-align:center;border:1px solid ${cfg.colors.cellBorder}">Koszt/kWp</th>
            <th style="padding:8px;text-align:center;border:1px solid ${cfg.colors.cellBorder}">Marża [%]</th>
            <th style="padding:8px;text-align:center;border:1px solid ${cfg.colors.cellBorder};background:${cfg.colors.saleBg}">Sprzedaż/kWp</th>
            <th style="padding:8px;text-align:center;border:1px solid ${cfg.colors.cellBorder};width:50px">Akcje</th>
          </tr>
        </thead>
        <tbody id="capex_tbody_${type}">
  `;

  tiers.forEach((tier, index) => {
    if (!tier) return; // Skip null entries

    const isLast = index === tiers.length - 1;
    const maxDisplay = tier.max === Infinity ? '∞' : tier.max;

    html += `
      <tr data-tier-index="${index}">
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder}">
          <input type="number" value="${tier.min}" step="10" style="width:70px;text-align:right"
                 onchange="updateCapexTierRange('${type}', ${index}, 'min', this.value)">
        </td>
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder}">
          ${isLast ?
            `<span style="font-weight:600;color:#666;padding:0 10px">∞</span>` :
            `<input type="number" value="${tier.max}" step="10" style="width:70px;text-align:right"
                    onchange="updateCapexTierRange('${type}', ${index}, 'max', this.value)">`
          }
        </td>
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder}">
          <input type="number" value="${tier.cost}" step="10" style="width:80px;text-align:right"
                 onchange="updateCapexTierValue('${type}', ${index}, 'cost', this.value)">
        </td>
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder}">
          <input type="number" value="${tier.margin}" step="0.1" min="0" max="100" style="width:70px;text-align:right"
                 onchange="updateCapexTierValue('${type}', ${index}, 'margin', this.value)">
        </td>
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder};background:${cfg.colors.bg}">
          <input type="number" value="${tier.sale}" readonly
                 style="width:80px;text-align:right;background:${cfg.colors.bg};font-weight:600;color:${cfg.colors.textColor};border:none">
        </td>
        <td style="padding:4px;border:1px solid ${cfg.colors.cellBorder};text-align:center">
          ${tiers.filter(t => t !== null).length > 1 ?
            `<button onclick="removeCapexTier('${type}', ${index})"
                     style="padding:4px 8px;background:#f44336;color:white;border:none;border-radius:3px;cursor:pointer;font-size:11px"
                     title="Usuń przedział">🗑️</button>` :
            ''
          }
        </td>
      </tr>
    `;
  });

  html += `
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;
}

// Render all CAPEX tables
function renderAllCapexTables() {
  if (!capexDataPerType) initCapexData();

  const types = ['ground_s', 'ground_ew', 'roof_ew', 'carport'];
  types.forEach(type => renderCapexTable(type));
}

// Show CAPEX tab
function showCapexTab(type) {
  // Hide all panels
  document.querySelectorAll('.capex-panel').forEach(panel => {
    panel.style.display = 'none';
  });

  // Show selected panel
  const selectedPanel = document.getElementById(`capex_${type}`);
  if (selectedPanel) {
    selectedPanel.style.display = 'block';
  }

  // Update tab styles
  const tabColors = {
    ground_s: { active: '#4caf50' },
    ground_ew: { active: '#ff9800' },
    roof_ew: { active: '#2196f3' },
    carport: { active: '#9c27b0' }
  };

  document.querySelectorAll('.capex-tab').forEach(tab => {
    const tabType = tab.id.replace('tab_', '');
    if (tabType === type) {
      tab.style.background = tabColors[type].active;
      tab.style.color = 'white';
    } else {
      tab.style.background = '#f5f5f5';
      tab.style.color = '#666';
    }
  });
}

// Update tier range (min/max)
function updateCapexTierRange(type, index, field, value) {
  if (!capexDataPerType[type] || !capexDataPerType[type][index]) return;

  const numValue = parseFloat(value) || 0;
  capexDataPerType[type][index][field] = numValue;

  markUnsaved();
}

// Update tier value (cost/margin) and recalculate sale
// Marża handlowa: cena_sprzedaży = koszt / (1 - marża/100)
// Przykład: koszt 2000, marża 20% → 2000 / 0.80 = 2500 PLN
function updateCapexTierValue(type, index, field, value) {
  if (!capexDataPerType[type] || !capexDataPerType[type][index]) return;

  const tier = capexDataPerType[type][index];
  tier[field] = parseFloat(value) || 0;

  // Recalculate sale price using margin formula: sale = cost / (1 - margin/100)
  if (tier.margin >= 100) {
    tier.sale = 0; // Invalid margin (100% or more)
  } else {
    tier.sale = Math.round(tier.cost / (1 - tier.margin / 100));
  }

  // Re-render to update display
  renderCapexTable(type);
  markUnsaved();
}

// Add new tier to a type
function addCapexTier(type) {
  if (!capexDataPerType[type]) capexDataPerType[type] = [];

  const tiers = capexDataPerType[type].filter(t => t !== null);
  const lastTier = tiers[tiers.length - 1];

  // Create new tier based on last one
  const newMin = lastTier ? (lastTier.max === Infinity ? lastTier.min + 5000 : lastTier.max) : 0;
  const newTier = {
    min: newMin,
    max: Infinity,
    cost: lastTier ? Math.round(lastTier.cost * 0.9) : 2000,
    margin: lastTier ? lastTier.margin : 15,
    sale: 0
  };
  newTier.sale = Math.round(newTier.cost / (1 - newTier.margin / 100));

  // Update previous last tier's max
  if (lastTier && lastTier.max === Infinity) {
    lastTier.max = newMin;
  }

  capexDataPerType[type].push(newTier);

  renderCapexTable(type);
  markUnsaved();
}

// Remove tier from a type
function removeCapexTier(type, index) {
  if (!capexDataPerType[type]) return;

  const tiers = capexDataPerType[type];
  if (tiers.filter(t => t !== null).length <= 1) {
    alert('Musi pozostać przynajmniej jeden przedział!');
    return;
  }

  // If removing last tier, make previous one extend to infinity
  if (index === tiers.length - 1 && index > 0) {
    tiers[index - 1].max = Infinity;
  }

  // Remove the tier
  tiers.splice(index, 1);

  renderCapexTable(type);
  markUnsaved();
}

// Get CAPEX per type from in-memory data
function getCapexPerTypeFromUI() {
  if (!capexDataPerType) initCapexData();
  return JSON.parse(JSON.stringify(capexDataPerType));
}

// Get CAPEX ranges from in-memory data (uses ground_s as reference)
function getCapexRangesFromUI() {
  if (!capexDataPerType) initCapexData();

  const groundS = capexDataPerType.ground_s || [];
  return groundS.filter(t => t !== null).map(tier => ({
    min: tier.min,
    max: tier.max
  }));
}

// Apply CAPEX per type settings to UI (re-renders tables)
function applyCapexPerTypeToUI(config) {
  // Update in-memory data
  if (config.capexPerType) {
    capexDataPerType = JSON.parse(JSON.stringify(config.capexPerType));

    // Ensure ranges are attached
    const defaultRanges = config.capexRanges || DEFAULT_CONFIG.capexRanges;
    const types = ['ground_s', 'ground_ew', 'roof_ew', 'carport'];

    types.forEach(type => {
      if (!capexDataPerType[type]) return;
      capexDataPerType[type] = capexDataPerType[type].map((tier, i) => {
        if (!tier) return null;
        return {
          ...tier,
          min: tier.min !== undefined ? tier.min : (defaultRanges[i]?.min || 0),
          max: tier.max !== undefined ? tier.max : (defaultRanges[i]?.max || Infinity)
        };
      });
    });
  }

  // Re-render all tables
  renderAllCapexTables();
}

// Get CAPEX for capacity and installation type (NEW)
function getCapexForCapacityAndType(capacityKwp, pvType) {
  const settings = getCurrentSettings();
  const ranges = settings.capexRanges || DEFAULT_CONFIG.capexRanges;
  const perType = settings.capexPerType || DEFAULT_CONFIG.capexPerType;

  // Find the matching range
  for (let i = 0; i < ranges.length; i++) {
    const range = ranges[i];
    if (capacityKwp >= range.min && capacityKwp < range.max) {
      const tierData = perType[pvType]?.[i];
      if (tierData) {
        return {
          cost: tierData.cost,
          margin: tierData.margin,
          sale: tierData.sale,
          rangeMin: range.min,
          rangeMax: range.max
        };
      }
    }
  }

  // Fallback to last tier for very large installations
  const lastIndex = ranges.length - 1;
  const tierData = perType[pvType]?.[lastIndex];
  if (tierData) {
    return {
      cost: tierData.cost,
      margin: tierData.margin,
      sale: tierData.sale,
      rangeMin: ranges[lastIndex].min,
      rangeMax: ranges[lastIndex].max
    };
  }

  // Ultimate fallback - use ground_s
  return {
    cost: DEFAULT_CONFIG.capexPerType.ground_s[0].cost,
    margin: DEFAULT_CONFIG.capexPerType.ground_s[0].margin,
    sale: DEFAULT_CONFIG.capexPerType.ground_s[0].sale,
    rangeMin: 50,
    rangeMax: 150
  };
}

// Make CAPEX management functions globally available
window.showCapexTab = showCapexTab;
window.addCapexTier = addCapexTier;
window.removeCapexTier = removeCapexTier;
window.updateCapexTierRange = updateCapexTierRange;
window.updateCapexTierValue = updateCapexTierValue;

// Make settings globally available for other scripts
window.PVSettings = {
  get: getCurrentSettings,
  getCapexForCapacity: getCapexForCapacity,
  getCapexForCapacityAndType: getCapexForCapacityAndType,
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
