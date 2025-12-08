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
  pvDegradationYear1: 2.0,        // First year PV degradation [%] (higher due to initial settling)
  degradationRate: 0.5,           // Annual PV degradation for years 2+ [%/year]
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
  pxxSource: 'manual',         // 'manual' | 'pvgis_uncertainty' | 'pvgis_timeseries'
  productionP50Factor: 1.00,   // 100% of expected production (median)
  productionP75Factor: 0.97,   // 97% - 75th percentile (25% chance of being lower)
  productionP90Factor: 0.94,   // 94% - 90th percentile (10% chance of being lower)

  // PVGIS Pxx Settings (used when pxxSource != 'manual')
  pxxModelUncertaintyPct: 3,   // Model uncertainty (PR, etc.) [%]
  pxxOtherUncertaintyPct: 2,   // Other uncertainties (soiling, construction) [%]
  pvgisRadDatabase: 'PVGIS-SARAH3',  // Radiation database for Poland
  pvgisLossPct: 14,            // System losses [%]
  pvgisStartYear: 2005,        // Start year for timeseries (min 10 years range)
  pvgisEndYear: 2020,          // End year for timeseries
  pvgisPvTechChoice: 'crystSi', // PV technology: 'crystSi', 'CIS', 'CdTe'
  pvgisMountingPlace: 'free',  // 'free' (ground) or 'building' (roof)

  // Weather Data Source
  weatherDataSource: 'pvgis', // 'pvgis' or 'clearsky'

  // Environmental Parameters (Advanced)
  altitude: 100,      // meters above sea level
  albedo: 0.2,        // ground reflectance (0.2 = grass, 0.3 = concrete, 0.8 = snow)
  soilingLoss: 2,     // soiling loss percentage (2-3% typical for Europe)

  // DC/AC Ratio Mode
  dcacMode: 'manual', // 'manual' (use tiers table) or 'auto' (automatic selection in future)

  // PV Installation Defaults - per type (Yield, Latitude, Longitude, Tilt, Azimuth)
  // Ground South
  pvYield_ground_s: 1050,
  latitude_ground_s: 52.0,
  longitude_ground_s: 21.0,
  tilt_ground_s: 0,       // 0 = auto (uses latitude)
  azimuth_ground_s: 180,  // South
  // Roof East-West
  pvYield_roof_ew: 950,
  latitude_roof_ew: 52.0,
  longitude_roof_ew: 21.0,
  tilt_roof_ew: 10,       // Low tilt for E-W
  azimuth_roof_ew: 90,    // East (will also calculate West at 270)
  // Ground East-West
  pvYield_ground_ew: 980,
  latitude_ground_ew: 52.0,
  longitude_ground_ew: 21.0,
  tilt_ground_ew: 15,
  azimuth_ground_ew: 90,  // East (will also calculate West at 270)

  // DC/AC Ratio Tiers - by capacity range and installation type
  // Predefiniowane wartości bazowe (typowe dla polskiego rynku)
  dcacTiers: [
    { min: 150, max: 300, ground_s: 1.10, roof_ew: 1.15, ground_ew: 1.20 },
    { min: 301, max: 600, ground_s: 1.15, roof_ew: 1.20, ground_ew: 1.25 },
    { min: 601, max: 1200, ground_s: 1.20, roof_ew: 1.25, ground_ew: 1.30 },
    { min: 1201, max: 3000, ground_s: 1.25, roof_ew: 1.30, ground_ew: 1.35 },
    { min: 3001, max: 7000, ground_s: 1.30, roof_ew: 1.35, ground_ew: 1.40 },
    { min: 7001, max: 15000, ground_s: 1.35, roof_ew: 1.40, ground_ew: 1.45 },
    { min: 15001, max: 50000, ground_s: 1.40, roof_ew: 1.45, ground_ew: 1.50 }
  ],

  // DC/AC Slider Adjustment (zaawansowani użytkownicy mogą przesunąć ±0.1)
  dcacAdjustment: 0,  // Korekta stosowana do wszystkich wartości z tabeli

  // Analysis Range
  capMin: 1000,
  capMax: 50000,
  capStep: 500,

  // Autoconsumption Thresholds
  thrA: 95,
  thrB: 90,
  thrC: 85,
  thrD: 80,

  // Operational Calendar
  operatingMode: '24_7',   // '24_7' | 'workdays' | 'custom'
  workHourStart: 6,        // Start hour (for custom mode)
  workHourEnd: 22,         // End hour (for custom mode)
  workOnSaturdays: false,  // Work on Saturdays (for custom mode)
  workOnSundays: false,    // Work on Sundays (for custom mode)
  peakHourStart: 7,        // Capacity fee peak start (URE standard: 7)
  peakHourEnd: 21,         // Capacity fee peak end (URE standard: 21)

  // ============================================================================
  // ESG - Environmental, Social, Governance Parameters
  // ============================================================================

  // ESG - Grid Emission Factor (Scope 2, Location-based)
  esgGridEmissionProvider: 'manual',  // 'manual' | 'climatiq' | 'electricitymaps'
  esgGridEmissionFactor: 0.658,       // kgCO2e/kWh (Poland 2023 average, source: KOBiZE)
  esgGridEmissionYear: 2023,          // Reference year for emission factor
  esgGridEmissionSource: 'KOBiZE',    // Source description

  // ESG - Embodied Carbon (PV Manufacturing LCA)
  // Values in kgCO2e/kWp, source: IEA PVPS Task 12, NREL
  esgEmbodiedCarbonCrystalline: 700,  // Crystalline silicon (c-Si) - most common
  esgEmbodiedCarbonCIS: 600,          // Copper Indium Selenide (CIS/CIGS)
  esgEmbodiedCarbonCdTe: 500,         // Cadmium Telluride (thin-film)
  esgEmbodiedCarbonSource: 'IEA PVPS Task 12 / NREL',

  // ESG - Project PV Technology (for embodied carbon calculation)
  esgPvTechnology: 'crystalline',     // 'crystalline' | 'CIS' | 'CdTe'

  // ESG - EU Taxonomy Compliance
  esgTaxonomyAligned: true,           // Project meets EU Taxonomy criteria
  esgTaxonomyActivityCode: '4.1',     // Activity code (4.1 = Electricity generation using solar PV)

  // ESG - Reporting Method
  esgReportingMethod: 'location',     // 'location' (location-based) | 'market' (market-based)

  // ESG - Component Compliance
  esgComponentCompliance: 'Tier 1, EPD, RoHS, ISO 9001/14001',  // Compliance note

  // ESG - Electricity Maps API
  electricitymapsApiKey: '',          // Electricity Maps API key
  electricitymapsZone: 'PL',          // Default zone for Poland

  // ============================================================================
  // BESS - Battery Energy Storage System (LIGHT/AUTO Mode)
  // ============================================================================
  // Tryb uproszczony dla handlowców - system automatycznie dobiera moc i pojemność

  bessEnabled: false,                  // Master switch: false = OFF (no battery), true = ON (AUTO)
  bessDuration: 'auto',                // Duration mode: 'auto' | 1 | 2 | 4 (hours)
                                       // 'auto' = system tests 1h/2h/4h and picks best NPV

  // BESS Technical Defaults (used by AUTO sizing algorithm)
  bessRoundtripEfficiency: 0.90,       // Round-trip efficiency (88-92% typical for Li-ion)
  bessSocMin: 0.10,                    // Minimum SOC (10% = protect battery health)
  bessSocMax: 0.90,                    // Maximum SOC (90% = protect battery health)
  bessSocInitial: 0.50,                // Initial SOC at start of simulation

  // BESS Economic Defaults
  bessCapexPerKwh: 1500,               // CAPEX per kWh capacity [PLN/kWh] (battery cells + BMS)
  bessCapexPerKw: 300,                 // CAPEX per kW power [PLN/kW] (inverter/PCS)
  bessOpexPctPerYear: 1.5,             // Annual OPEX as % of CAPEX
  bessLifetimeYears: 15,               // Expected battery lifetime [years]
  bessCycleLifetime: 6000,             // Cycle lifetime (number of full cycles before replacement)
  bessDegradationYear1: 3.0,           // First year degradation [%] (higher due to initial settling)
  bessDegradationPctPerYear: 2.0       // Annual capacity degradation for years 2+ [%/year]
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  // Initialize DC/AC tiers BEFORE loadSettings (so data is available)
  initDcacTiers();
  loadSettings();
  setupEventListeners();
  updateTotalEnergyPrice();
  // Initialize and render dynamic CAPEX tables
  initCapexData();
  renderAllCapexTables();
  // Initialize BESS section visibility
  toggleBessSection();
});

// ============================================================================
// BESS Section Toggle Functions
// ============================================================================

/**
 * Toggle BESS configuration sections based on bessEnabled checkbox
 * Shows/hides duration, economics, and technical parameters
 */
function toggleBessSection() {
  const bessEnabled = document.getElementById('bessEnabled')?.checked || false;
  const durationSection = document.getElementById('bessDurationSection');
  const economicsSection = document.getElementById('bessEconomicsSection');
  const technicalSection = document.getElementById('bessTechnicalSection');
  const statusOff = document.getElementById('bessStatusOff');
  const statusOn = document.getElementById('bessStatusOn');

  if (bessEnabled) {
    // Show BESS configuration sections
    if (durationSection) durationSection.style.display = 'block';
    if (economicsSection) economicsSection.style.display = 'block';
    if (technicalSection) technicalSection.style.display = 'block';

    // Update status indicators
    if (statusOff) {
      statusOff.style.border = '2px solid transparent';
      statusOff.style.opacity = '0.5';
    }
    if (statusOn) {
      statusOn.style.border = '2px solid #4caf50';
      statusOn.style.opacity = '1';
    }

    console.log('🔋 BESS enabled - showing configuration sections');
  } else {
    // Hide BESS configuration sections
    if (durationSection) durationSection.style.display = 'none';
    if (economicsSection) economicsSection.style.display = 'none';
    if (technicalSection) technicalSection.style.display = 'none';

    // Update status indicators
    if (statusOff) {
      statusOff.style.border = '2px solid #ef5350';
      statusOff.style.opacity = '1';
    }
    if (statusOn) {
      statusOn.style.border = '2px solid transparent';
      statusOn.style.opacity = '0.5';
    }

    console.log('🔋 BESS disabled - hiding configuration sections');
  }

  // Mark as unsaved
  markUnsaved();
}

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
    // Pxx manual factors
    'productionP50Factor', 'productionP75Factor', 'productionP90Factor',
    // Pxx PVGIS settings
    'pxxModelUncertaintyPct', 'pxxOtherUncertaintyPct', 'pvgisLossPct',
    'pvgisStartYear', 'pvgisEndYear',
    // Environmental parameters
    'altitude', 'albedo', 'soilingLoss',
    // DC/AC Mode
    'dcacMode',
    // PV params per type (Yield, Latitude, Longitude, Tilt, Azimuth)
    'pvYield_ground_s', 'latitude_ground_s', 'longitude_ground_s', 'tilt_ground_s', 'azimuth_ground_s',
    'pvYield_roof_ew', 'latitude_roof_ew', 'longitude_roof_ew', 'tilt_roof_ew', 'azimuth_roof_ew',
    'pvYield_ground_ew', 'latitude_ground_ew', 'longitude_ground_ew', 'tilt_ground_ew', 'azimuth_ground_ew',
    'capMin', 'capMax', 'capStep', 'thrA', 'thrB', 'thrC', 'thrD',
    // BESS economic parameters
    'bessCapexPerKwh', 'bessCapexPerKw', 'bessOpexPctPerYear', 'bessLifetimeYears',
    // BESS technical parameters
    'bessRoundtripEfficiency', 'bessSocMin', 'bessSocMax', 'bessDegradationYear1', 'bessDegradationPctPerYear'
  ];

  // Select fields
  const selectFields = [
    'eaasCurrency', 'eaasIndexation', 'irrDriver',
    'depreciationMethod', 'debtAmortization', 'indexationFrequency',
    'weatherDataSource',
    // Pxx select fields
    'pxxSource', 'pvgisRadDatabase', 'pvgisPvTechChoice', 'pvgisMountingPlace',
    // BESS
    'bessDuration'
  ];

  // IRR mode checkbox
  const useInflationEl = document.getElementById('useInflation');
  if (useInflationEl) {
    useInflationEl.checked = config.useInflation || config.irrMode === 'nominal' || false;
  }

  // BESS enabled checkbox
  const bessEnabledEl = document.getElementById('bessEnabled');
  if (bessEnabledEl) {
    bessEnabledEl.checked = config.bessEnabled || false;
  }

  // Fields that are stored as decimals but displayed as percentages in UI
  const percentageFields = ['bessRoundtripEfficiency', 'bessSocMin', 'bessSocMax'];

  simpleFields.forEach(field => {
    const el = document.getElementById(field);
    if (el) {
      // Use config value if exists, otherwise use default
      let value = config[field] !== undefined ? config[field] : DEFAULT_CONFIG[field];
      // Convert decimal to percentage for display (e.g., 0.90 -> 90)
      if (percentageFields.includes(field) && value < 1) {
        value = value * 100;
      }
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

  // DC/AC Ratio tiers - load into dynamic table
  if (config.dcacTiers && config.dcacTiers.length > 0) {
    dcacTiersData = config.dcacTiers;
    saveDcacTiers();
  }
  renderDcacTable();

  // DC/AC Adjustment slider
  const dcacSlider = document.getElementById('dcacAdjustment');
  const dcacDisplay = document.getElementById('dcacAdjustmentDisplay');
  if (dcacSlider) {
    dcacSlider.value = config.dcacAdjustment !== undefined ? config.dcacAdjustment : 0;
    if (dcacDisplay) {
      const val = parseFloat(dcacSlider.value);
      dcacDisplay.textContent = (val >= 0 ? '+' : '') + val.toFixed(2);
    }
  }

  updateTotalEnergyPrice();

  // Update BESS section visibility after loading settings
  toggleBessSection();
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
    pvDegradationYear1: parseFloat(document.getElementById('pvDegradationYear1')?.value || DEFAULT_CONFIG.pvDegradationYear1),
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

    // Production Scenarios (P-factors) - Manual values
    pxxSource: document.getElementById('pxxSource')?.value || DEFAULT_CONFIG.pxxSource,
    productionP50Factor: parseFloat(document.getElementById('productionP50Factor')?.value || DEFAULT_CONFIG.productionP50Factor),
    productionP75Factor: parseFloat(document.getElementById('productionP75Factor')?.value || DEFAULT_CONFIG.productionP75Factor),
    productionP90Factor: parseFloat(document.getElementById('productionP90Factor')?.value || DEFAULT_CONFIG.productionP90Factor),

    // PVGIS Pxx Settings
    pxxModelUncertaintyPct: parseFloat(document.getElementById('pxxModelUncertaintyPct')?.value || DEFAULT_CONFIG.pxxModelUncertaintyPct),
    pxxOtherUncertaintyPct: parseFloat(document.getElementById('pxxOtherUncertaintyPct')?.value || DEFAULT_CONFIG.pxxOtherUncertaintyPct),
    pvgisRadDatabase: document.getElementById('pvgisRadDatabase')?.value || DEFAULT_CONFIG.pvgisRadDatabase,
    pvgisLossPct: parseFloat(document.getElementById('pvgisLossPct')?.value || DEFAULT_CONFIG.pvgisLossPct),
    pvgisStartYear: parseInt(document.getElementById('pvgisStartYear')?.value || DEFAULT_CONFIG.pvgisStartYear),
    pvgisEndYear: parseInt(document.getElementById('pvgisEndYear')?.value || DEFAULT_CONFIG.pvgisEndYear),
    pvgisPvTechChoice: document.getElementById('pvgisPvTechChoice')?.value || DEFAULT_CONFIG.pvgisPvTechChoice,
    pvgisMountingPlace: document.getElementById('pvgisMountingPlace')?.value || DEFAULT_CONFIG.pvgisMountingPlace,

    // Weather Data Source
    weatherDataSource: document.getElementById('weatherDataSource')?.value || DEFAULT_CONFIG.weatherDataSource,

    // Environmental Parameters (Advanced)
    altitude: parseFloat(document.getElementById('altitude')?.value || DEFAULT_CONFIG.altitude),
    albedo: parseFloat(document.getElementById('albedo')?.value || DEFAULT_CONFIG.albedo),
    soilingLoss: parseFloat(document.getElementById('soilingLoss')?.value || DEFAULT_CONFIG.soilingLoss),

    // DC/AC Ratio Mode
    dcacMode: document.getElementById('dcacMode')?.value || DEFAULT_CONFIG.dcacMode,

    // PV Installation - per type (Yield, Latitude, Longitude, Tilt, Azimuth)
    // Ground South
    pvYield_ground_s: parseFloat(document.getElementById('pvYield_ground_s')?.value || DEFAULT_CONFIG.pvYield_ground_s),
    latitude_ground_s: parseFloat(document.getElementById('latitude_ground_s')?.value || DEFAULT_CONFIG.latitude_ground_s),
    longitude_ground_s: parseFloat(document.getElementById('longitude_ground_s')?.value || DEFAULT_CONFIG.longitude_ground_s),
    tilt_ground_s: parseFloat(document.getElementById('tilt_ground_s')?.value || DEFAULT_CONFIG.tilt_ground_s),
    azimuth_ground_s: parseFloat(document.getElementById('azimuth_ground_s')?.value || DEFAULT_CONFIG.azimuth_ground_s),
    // Roof East-West
    pvYield_roof_ew: parseFloat(document.getElementById('pvYield_roof_ew')?.value || DEFAULT_CONFIG.pvYield_roof_ew),
    latitude_roof_ew: parseFloat(document.getElementById('latitude_roof_ew')?.value || DEFAULT_CONFIG.latitude_roof_ew),
    longitude_roof_ew: parseFloat(document.getElementById('longitude_roof_ew')?.value || DEFAULT_CONFIG.longitude_roof_ew),
    tilt_roof_ew: parseFloat(document.getElementById('tilt_roof_ew')?.value || DEFAULT_CONFIG.tilt_roof_ew),
    azimuth_roof_ew: parseFloat(document.getElementById('azimuth_roof_ew')?.value || DEFAULT_CONFIG.azimuth_roof_ew),
    // Ground East-West
    pvYield_ground_ew: parseFloat(document.getElementById('pvYield_ground_ew')?.value || DEFAULT_CONFIG.pvYield_ground_ew),
    latitude_ground_ew: parseFloat(document.getElementById('latitude_ground_ew')?.value || DEFAULT_CONFIG.latitude_ground_ew),
    longitude_ground_ew: parseFloat(document.getElementById('longitude_ground_ew')?.value || DEFAULT_CONFIG.longitude_ground_ew),
    tilt_ground_ew: parseFloat(document.getElementById('tilt_ground_ew')?.value || DEFAULT_CONFIG.tilt_ground_ew),
    azimuth_ground_ew: parseFloat(document.getElementById('azimuth_ground_ew')?.value || DEFAULT_CONFIG.azimuth_ground_ew),

    // DC/AC Ratio Tiers (z dynamicznej tabeli)
    dcacTiers: dcacTiersData.length > 0 ? dcacTiersData : DEFAULT_CONFIG.dcacTiers,

    // DC/AC Adjustment (slider korekty)
    dcacAdjustment: parseFloat(document.getElementById('dcacAdjustment')?.value || 0),

    // Analysis Range
    capMin: parseFloat(document.getElementById('capMin')?.value || DEFAULT_CONFIG.capMin),
    capMax: parseFloat(document.getElementById('capMax')?.value || DEFAULT_CONFIG.capMax),
    capStep: parseFloat(document.getElementById('capStep')?.value || DEFAULT_CONFIG.capStep),

    // Thresholds
    thrA: parseFloat(document.getElementById('thrA')?.value || DEFAULT_CONFIG.thrA),
    thrB: parseFloat(document.getElementById('thrB')?.value || DEFAULT_CONFIG.thrB),
    thrC: parseFloat(document.getElementById('thrC')?.value || DEFAULT_CONFIG.thrC),
    thrD: parseFloat(document.getElementById('thrD')?.value || DEFAULT_CONFIG.thrD),

    // BESS - Battery Energy Storage System (LIGHT/AUTO Mode)
    bessEnabled: document.getElementById('bessEnabled')?.checked || false,
    bessDuration: document.getElementById('bessDuration')?.value || DEFAULT_CONFIG.bessDuration,
    // BESS Technical
    bessRoundtripEfficiency: parseFloat(document.getElementById('bessRoundtripEfficiency')?.value || DEFAULT_CONFIG.bessRoundtripEfficiency * 100) / 100,
    bessSocMin: parseFloat(document.getElementById('bessSocMin')?.value || DEFAULT_CONFIG.bessSocMin * 100) / 100,
    bessSocMax: parseFloat(document.getElementById('bessSocMax')?.value || DEFAULT_CONFIG.bessSocMax * 100) / 100,
    bessSocInitial: DEFAULT_CONFIG.bessSocInitial,
    // BESS Economic
    bessCapexPerKwh: parseFloat(document.getElementById('bessCapexPerKwh')?.value || DEFAULT_CONFIG.bessCapexPerKwh),
    bessCapexPerKw: parseFloat(document.getElementById('bessCapexPerKw')?.value || DEFAULT_CONFIG.bessCapexPerKw),
    bessOpexPctPerYear: parseFloat(document.getElementById('bessOpexPctPerYear')?.value || DEFAULT_CONFIG.bessOpexPctPerYear),
    bessLifetimeYears: parseInt(document.getElementById('bessLifetimeYears')?.value || DEFAULT_CONFIG.bessLifetimeYears),
    bessCycleLifetime: DEFAULT_CONFIG.bessCycleLifetime,
    bessDegradationYear1: parseFloat(document.getElementById('bessDegradationYear1')?.value || DEFAULT_CONFIG.bessDegradationYear1),
    bessDegradationPctPerYear: parseFloat(document.getElementById('bessDegradationPctPerYear')?.value || DEFAULT_CONFIG.bessDegradationPctPerYear),

    // ESG Parameters
    esgGridEmissionProvider: document.getElementById('esgGridEmissionProvider')?.value || DEFAULT_CONFIG.esgGridEmissionProvider,
    esgGridEmissionFactor: parseFloat(document.getElementById('esgGridEmissionFactor')?.value || DEFAULT_CONFIG.esgGridEmissionFactor),
    esgGridEmissionYear: parseInt(document.getElementById('esgGridEmissionYear')?.value || DEFAULT_CONFIG.esgGridEmissionYear),
    esgGridEmissionSource: document.getElementById('esgGridEmissionSource')?.value || DEFAULT_CONFIG.esgGridEmissionSource,
    esgEmbodiedCarbonCrystalline: parseFloat(document.getElementById('esgEmbodiedCarbonCrystalline')?.value || DEFAULT_CONFIG.esgEmbodiedCarbonCrystalline),
    esgEmbodiedCarbonCIS: parseFloat(document.getElementById('esgEmbodiedCarbonCIS')?.value || DEFAULT_CONFIG.esgEmbodiedCarbonCIS),
    esgEmbodiedCarbonCdTe: parseFloat(document.getElementById('esgEmbodiedCarbonCdTe')?.value || DEFAULT_CONFIG.esgEmbodiedCarbonCdTe),
    esgEmbodiedCarbonSource: document.getElementById('esgEmbodiedCarbonSource')?.value || DEFAULT_CONFIG.esgEmbodiedCarbonSource,
    esgPvTechnology: document.getElementById('esgPvTechnology')?.value || DEFAULT_CONFIG.esgPvTechnology,
    esgTaxonomyAligned: document.getElementById('esgTaxonomyAligned')?.checked ?? DEFAULT_CONFIG.esgTaxonomyAligned,
    esgTaxonomyActivityCode: document.getElementById('esgTaxonomyActivityCode')?.value || DEFAULT_CONFIG.esgTaxonomyActivityCode,
    esgReportingMethod: document.getElementById('esgReportingMethod')?.value || DEFAULT_CONFIG.esgReportingMethod,
    esgComponentCompliance: document.getElementById('esgComponentCompliance')?.value || DEFAULT_CONFIG.esgComponentCompliance,
    electricitymapsApiKey: document.getElementById('electricitymapsApiKey')?.value || DEFAULT_CONFIG.electricitymapsApiKey,
    electricitymapsZone: document.getElementById('electricitymapsZone')?.value || DEFAULT_CONFIG.electricitymapsZone
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
  console.log('Received message:', event.data.type);

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

    case 'SETTINGS_UPDATED':
      // Settings updated from project load or other source
      if (event.data.data) {
        console.log('📥 Applying settings from SETTINGS_UPDATED');
        applySettingsToUI(event.data.data);
        // Also save to localStorage for persistence
        localStorage.setItem('pv_system_settings', JSON.stringify(event.data.data));
        // Recalculate totals
        setTimeout(updateTotalEnergyPrice, 100);
      }
      break;

    case 'PROJECT_LOADED':
      // Project was loaded - request fresh settings from shell
      console.log('📂 Project loaded, requesting settings refresh');
      if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
      }
      break;

    case 'SHARED_DATA_RESPONSE':
      // Received shared data from shell - apply settings if present
      if (event.data.data && event.data.data.settings) {
        console.log('📥 Applying settings from SHARED_DATA_RESPONSE');
        applySettingsToUI(event.data.data.settings);
        localStorage.setItem('pv_system_settings', JSON.stringify(event.data.data.settings));
        setTimeout(updateTotalEnergyPrice, 100);
      }
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
// Uwzględnia slider korekty (dcacAdjustment)
function getDcacForCapacity(capacityKwp, pvType) {
  const settings = getCurrentSettings();
  const dcacTiers = settings.dcacTiers || DEFAULT_CONFIG.dcacTiers;
  const adjustment = settings.dcacAdjustment || 0;

  let baseValue = dcacTiers[0][pvType] || dcacTiers[0].ground_s;

  for (const tier of dcacTiers) {
    if (capacityKwp >= tier.min && capacityKwp <= tier.max) {
      baseValue = tier[pvType] || tier.ground_s;
      break;
    }
  }

  // Fallback - use last tier for very large installations
  if (capacityKwp > 50000 && dcacTiers.length > 0) {
    const lastTier = dcacTiers[dcacTiers.length - 1];
    baseValue = lastTier[pvType] || lastTier.ground_s;
  }

  // Apply adjustment (slider korekty)
  return Math.round((baseValue + adjustment) * 100) / 100;
}

// ============================================================================
// DC/AC Ratio Tiers Management (dynamiczna tabela)
// ============================================================================

// Global storage for DC/AC tiers
let dcacTiersData = [];

// Initialize DC/AC tiers from DEFAULT_CONFIG or localStorage
function initDcacTiers() {
  const saved = localStorage.getItem('pv_dcac_tiers');
  if (saved) {
    try {
      dcacTiersData = JSON.parse(saved);
    } catch (e) {
      dcacTiersData = [...DEFAULT_CONFIG.dcacTiers];
    }
  } else {
    dcacTiersData = [...DEFAULT_CONFIG.dcacTiers];
  }
  renderDcacTable();
}

// Render DC/AC tiers table
function renderDcacTable() {
  const container = document.getElementById('dcac_tiers_container');
  if (!container) return;

  let html = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div style="font-weight:600;color:#333">Przedziały DC/AC Ratio</div>
      <div style="display:flex;gap:8px">
        <button onclick="resetDcacToDefaults()" style="padding:6px 12px;background:#ff9800;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600" title="Przywróć domyślne wartości">
          🔄 Resetuj
        </button>
        <button onclick="addDcacTier()" style="padding:6px 12px;background:#4caf50;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600">
          ➕ Dodaj przedział
        </button>
      </div>
    </div>
    <table class="dcac-table" style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f5f5f5">
          <th style="padding:8px;text-align:left;border:1px solid #ddd;width:70px">Od [kWp]</th>
          <th style="padding:8px;text-align:left;border:1px solid #ddd;width:70px">Do [kWp]</th>
          <th style="padding:8px;text-align:center;border:1px solid #ddd;background:#e8f5e9">Grunt Płd</th>
          <th style="padding:8px;text-align:center;border:1px solid #ddd;background:#e3f2fd">Dach E-W</th>
          <th style="padding:8px;text-align:center;border:1px solid #ddd;background:#fff3e0">Grunt E-W</th>
          <th style="padding:8px;text-align:center;border:1px solid #ddd;width:50px">Akcje</th>
        </tr>
      </thead>
      <tbody>
  `;

  dcacTiersData.forEach((tier, index) => {
    const isLast = index === dcacTiersData.length - 1;
    const maxDisplay = tier.max === Infinity || tier.max >= 999999 ? '∞' : tier.max;

    html += `
      <tr data-tier-index="${index}">
        <td style="padding:4px;border:1px solid #ddd">
          <input type="number" value="${tier.min}" step="100" min="0" style="width:65px;text-align:right"
                 onchange="updateDcacTierRange(${index}, 'min', this.value)">
        </td>
        <td style="padding:4px;border:1px solid #ddd">
          ${isLast ?
            `<span style="display:inline-block;width:65px;text-align:right;color:#666">∞</span>` :
            `<input type="number" value="${tier.max}" step="100" min="0" style="width:65px;text-align:right"
                    onchange="updateDcacTierRange(${index}, 'max', this.value)">`
          }
        </td>
        <td style="padding:4px;border:1px solid #ddd;background:#f1f8e9">
          <input type="number" value="${tier.ground_s}" step="0.05" min="1.0" max="2.0" style="width:60px;text-align:center"
                 onchange="updateDcacTierValue(${index}, 'ground_s', this.value)">
        </td>
        <td style="padding:4px;border:1px solid #ddd;background:#e3f2fd">
          <input type="number" value="${tier.roof_ew}" step="0.05" min="1.0" max="2.0" style="width:60px;text-align:center"
                 onchange="updateDcacTierValue(${index}, 'roof_ew', this.value)">
        </td>
        <td style="padding:4px;border:1px solid #ddd;background:#fff8e1">
          <input type="number" value="${tier.ground_ew}" step="0.05" min="1.0" max="2.0" style="width:60px;text-align:center"
                 onchange="updateDcacTierValue(${index}, 'ground_ew', this.value)">
        </td>
        <td style="padding:4px;border:1px solid #ddd;text-align:center">
          ${dcacTiersData.length > 1 ?
            `<button onclick="removeDcacTier(${index})" style="padding:4px 8px;background:#f44336;color:white;border:none;border-radius:3px;cursor:pointer;font-size:11px" title="Usuń przedział">✕</button>` :
            `<span style="color:#ccc">–</span>`
          }
        </td>
      </tr>
    `;
  });

  html += `
      </tbody>
    </table>
  `;

  container.innerHTML = html;
}

// Add new DC/AC tier
function addDcacTier() {
  const lastTier = dcacTiersData[dcacTiersData.length - 1];

  // Update previous last tier's max
  const newMin = lastTier ? (lastTier.max === Infinity || lastTier.max >= 999999 ? lastTier.min + 5000 : lastTier.max + 1) : 150;

  if (lastTier && (lastTier.max === Infinity || lastTier.max >= 999999)) {
    lastTier.max = newMin - 1;
  }

  // Create new tier with slightly higher ratios
  const newTier = {
    min: newMin,
    max: Infinity,
    ground_s: lastTier ? Math.round((lastTier.ground_s + 0.05) * 100) / 100 : 1.10,
    roof_ew: lastTier ? Math.round((lastTier.roof_ew + 0.05) * 100) / 100 : 1.15,
    ground_ew: lastTier ? Math.round((lastTier.ground_ew + 0.05) * 100) / 100 : 1.20
  };

  dcacTiersData.push(newTier);
  saveDcacTiers();
  renderDcacTable();
  markUnsaved();
}

// Remove DC/AC tier
function removeDcacTier(index) {
  if (dcacTiersData.length <= 1) return;

  // If removing last tier, make previous one extend to infinity
  if (index === dcacTiersData.length - 1 && index > 0) {
    dcacTiersData[index - 1].max = Infinity;
  }

  // If removing middle tier, adjust ranges
  if (index < dcacTiersData.length - 1 && index > 0) {
    dcacTiersData[index + 1].min = dcacTiersData[index].min;
  }

  dcacTiersData.splice(index, 1);
  saveDcacTiers();
  renderDcacTable();
  markUnsaved();
}

// Update DC/AC tier range (min/max)
function updateDcacTierRange(index, field, value) {
  const numValue = parseInt(value) || 0;
  dcacTiersData[index][field] = numValue;

  // Auto-adjust adjacent tiers
  if (field === 'max' && index < dcacTiersData.length - 1) {
    dcacTiersData[index + 1].min = numValue + 1;
  }
  if (field === 'min' && index > 0) {
    dcacTiersData[index - 1].max = numValue - 1;
  }

  saveDcacTiers();
  renderDcacTable();
  markUnsaved();
}

// Update DC/AC tier value (ground_s, roof_ew, ground_ew)
function updateDcacTierValue(index, field, value) {
  dcacTiersData[index][field] = parseFloat(value) || 1.0;
  saveDcacTiers();
  markUnsaved();
}

// Reset DC/AC tiers to defaults
function resetDcacToDefaults() {
  if (confirm('Czy na pewno chcesz przywrócić domyślne wartości DC/AC Ratio?')) {
    dcacTiersData = JSON.parse(JSON.stringify(DEFAULT_CONFIG.dcacTiers));
    saveDcacTiers();
    renderDcacTable();

    // Reset slider too
    const slider = document.getElementById('dcacAdjustment');
    const display = document.getElementById('dcacAdjustmentDisplay');
    if (slider) slider.value = 0;
    if (display) display.textContent = '0.00';

    markUnsaved();
  }
}

// Save DC/AC tiers to localStorage
function saveDcacTiers() {
  localStorage.setItem('pv_dcac_tiers', JSON.stringify(dcacTiersData));
}

// Get current DC/AC tiers
function getDcacTiers() {
  return dcacTiersData;
}

// Update slider display
function updateDcacSlider(value) {
  const display = document.getElementById('dcacAdjustmentDisplay');
  if (display) {
    const numVal = parseFloat(value);
    display.textContent = (numVal >= 0 ? '+' : '') + numVal.toFixed(2);
    display.style.color = numVal > 0 ? '#4caf50' : (numVal < 0 ? '#f44336' : '#666');
  }
  markUnsaved();
}

// Make DC/AC management functions globally available
window.initDcacTiers = initDcacTiers;
window.renderDcacTable = renderDcacTable;
window.addDcacTier = addDcacTier;
window.removeDcacTier = removeDcacTier;
window.updateDcacTierRange = updateDcacTierRange;
window.updateDcacTierValue = updateDcacTierValue;
window.resetDcacToDefaults = resetDcacToDefaults;
window.getDcacTiers = getDcacTiers;
window.updateDcacSlider = updateDcacSlider;

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

// ============================================================================
// Pxx Source Selection (PVGIS Integration)
// ============================================================================

// Toggle visibility of Pxx sections based on source selection
function togglePxxSourceFields() {
  const source = document.getElementById('pxxSource')?.value || 'manual';
  const manualSection = document.getElementById('pxxManualSection');
  const pvgisSection = document.getElementById('pxxPvgisSection');
  const timeseriesSettings = document.getElementById('pxxTimeseriesSettings');
  const calculatedDisplay = document.getElementById('pxxCalculatedDisplay');

  if (source === 'manual') {
    // Show manual, hide PVGIS
    if (manualSection) manualSection.style.display = 'block';
    if (pvgisSection) pvgisSection.style.display = 'none';
  } else {
    // Hide manual, show PVGIS
    if (manualSection) manualSection.style.display = 'none';
    if (pvgisSection) pvgisSection.style.display = 'block';

    // Show/hide timeseries-specific settings
    if (timeseriesSettings) {
      timeseriesSettings.style.display = source === 'pvgis_timeseries' ? 'block' : 'none';
    }
  }

  // Reset calculated display when switching
  if (calculatedDisplay) {
    calculatedDisplay.style.display = 'none';
  }

  markUnsaved();
}

// PVGIS Proxy API base URL (backend service)
const PVGIS_PROXY_BASE = 'http://localhost:8020';

// Fetch Pxx factors from PVGIS via backend proxy
async function fetchPxxFromPVGIS() {
  const statusEl = document.getElementById('pxxFetchStatus');
  const calculatedDisplay = document.getElementById('pxxCalculatedDisplay');
  const source = document.getElementById('pxxSource')?.value;

  if (source === 'manual') {
    if (statusEl) statusEl.textContent = '⚠️ Wybierz źródło PVGIS';
    return;
  }

  // Get settings
  const settings = getCurrentSettings();

  // Get location from the active PV type (use ground_s as default)
  const lat = settings.latitude_ground_s || 52.0;
  const lon = settings.longitude_ground_s || 21.0;

  if (statusEl) statusEl.innerHTML = '⏳ <strong>Pobieranie danych z PVGIS...</strong>';

  try {
    let response;
    let result;

    if (source === 'pvgis_uncertainty') {
      // Method 1: PVcalc endpoint - quick uncertainty-based calculation
      response = await fetch(`${PVGIS_PROXY_BASE}/pvgis/pvcalc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat: lat,
          lon: lon,
          peakpower: 1, // Normalize to 1 kWp
          loss: settings.pvgisLossPct || 14,
          pvtechchoice: settings.pvgisPvTechChoice || 'crystSi',
          mountingplace: settings.pvgisMountingPlace || 'free',
          raddatabase: settings.pvgisRadDatabase || 'PVGIS-SARAH3',
          model_uncertainty_pct: settings.pxxModelUncertaintyPct || 3,
          other_uncertainty_pct: settings.pxxOtherUncertaintyPct || 2
        })
      });

      if (!response.ok) {
        throw new Error(`PVGIS PVcalc error: ${response.status}`);
      }

      result = await response.json();

    } else if (source === 'pvgis_timeseries') {
      // Method 2: Seriescalc endpoint - accurate timeseries-based calculation
      response = await fetch(`${PVGIS_PROXY_BASE}/pvgis/seriescalc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat: lat,
          lon: lon,
          peakpower: 1, // Normalize to 1 kWp
          loss: settings.pvgisLossPct || 14,
          pvtechchoice: settings.pvgisPvTechChoice || 'crystSi',
          mountingplace: settings.pvgisMountingPlace || 'free',
          raddatabase: settings.pvgisRadDatabase || 'PVGIS-SARAH3',
          startyear: settings.pvgisStartYear || 2005,
          endyear: settings.pvgisEndYear || 2020
        })
      });

      if (!response.ok) {
        throw new Error(`PVGIS Seriescalc error: ${response.status}`);
      }

      result = await response.json();
    }

    // Display calculated factors
    if (result && result.p50_factor !== undefined) {
      // Update calculated display
      document.getElementById('pxxCalcP50').textContent = (result.p50_factor * 100).toFixed(1) + '%';
      document.getElementById('pxxCalcP75').textContent = (result.p75_factor * 100).toFixed(1) + '%';
      document.getElementById('pxxCalcP90').textContent = (result.p90_factor * 100).toFixed(1) + '%';

      // Update info
      const infoEl = document.getElementById('pxxCalcInfo');
      if (infoEl) {
        const method = source === 'pvgis_uncertainty' ? 'Metoda: Uncertainty (σ=' + (result.sigma_rel * 100).toFixed(1) + '%)' :
                       `Metoda: Timeseries (${result.years_count || '?'} lat)`;
        infoEl.textContent = `${method} | DB: ${settings.pvgisRadDatabase} | Lok: ${lat.toFixed(2)}°N`;
      }

      // Show calculated display
      if (calculatedDisplay) calculatedDisplay.style.display = 'block';

      // Auto-update manual factors with calculated values
      const p50Input = document.getElementById('productionP50Factor');
      const p75Input = document.getElementById('productionP75Factor');
      const p90Input = document.getElementById('productionP90Factor');

      if (p50Input) p50Input.value = result.p50_factor.toFixed(3);
      if (p75Input) p75Input.value = result.p75_factor.toFixed(3);
      if (p90Input) p90Input.value = result.p90_factor.toFixed(3);

      if (statusEl) {
        statusEl.innerHTML = `✅ <strong>Pobrano pomyślnie!</strong> P50=${(result.p50_factor * 100).toFixed(1)}%, P75=${(result.p75_factor * 100).toFixed(1)}%, P90=${(result.p90_factor * 100).toFixed(1)}%`;
      }

      // Cache result
      localStorage.setItem('pxx_pvgis_cache', JSON.stringify({
        timestamp: Date.now(),
        lat, lon, source,
        factors: result
      }));

      markUnsaved();

    } else {
      throw new Error('Nieprawidłowa odpowiedź z PVGIS proxy');
    }

  } catch (error) {
    console.error('PVGIS fetch error:', error);

    // Try to use cached values
    const cached = localStorage.getItem('pxx_pvgis_cache');
    if (cached) {
      try {
        const cachedData = JSON.parse(cached);
        const age = (Date.now() - cachedData.timestamp) / (1000 * 60 * 60); // hours
        if (statusEl) {
          statusEl.innerHTML = `⚠️ <strong>Błąd połączenia.</strong> Używam cache (${age.toFixed(0)}h temu): P50=${(cachedData.factors.p50_factor * 100).toFixed(1)}%, P75=${(cachedData.factors.p75_factor * 100).toFixed(1)}%, P90=${(cachedData.factors.p90_factor * 100).toFixed(1)}%`;
        }
        return;
      } catch (e) {
        // Cache parse error
      }
    }

    if (statusEl) {
      statusEl.innerHTML = `❌ <strong>Błąd:</strong> ${error.message}. Sprawdź czy backend PVGIS działa (port 8020).`;
    }

    // Fallback to manual defaults
    if (calculatedDisplay) calculatedDisplay.style.display = 'none';
  }
}

// Initialize Pxx source fields on load
document.addEventListener('DOMContentLoaded', () => {
  // Wait a bit for settings to load, then toggle
  setTimeout(() => {
    togglePxxSourceFields();
  }, 200);
});

// Make Pxx functions globally available
window.togglePxxSourceFields = togglePxxSourceFields;
window.fetchPxxFromPVGIS = fetchPxxFromPVGIS;

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
  calculateCapacityFee: calculateCapacityFee,
  // Pxx functions
  togglePxxSourceFields: togglePxxSourceFields,
  fetchPxxFromPVGIS: fetchPxxFromPVGIS,
  // ESG functions
  calculateESGMetrics: calculateESGMetrics,
  getEmbodiedCarbonForTechnology: getEmbodiedCarbonForTechnology,
  toggleEsgEmissionProvider: toggleEsgEmissionProvider
};

// ============================================================================
// ESG Calculation Functions
// ============================================================================

/**
 * Get embodied carbon value for PV technology
 * @param {string} technology - 'crystalline' | 'CIS' | 'CdTe'
 * @returns {number} kgCO2e/kWp
 */
function getEmbodiedCarbonForTechnology(technology) {
  const settings = getCurrentSettings();
  switch (technology) {
    case 'CIS':
      return settings.esgEmbodiedCarbonCIS;
    case 'CdTe':
      return settings.esgEmbodiedCarbonCdTe;
    case 'crystalline':
    default:
      return settings.esgEmbodiedCarbonCrystalline;
  }
}

/**
 * Calculate all ESG metrics for a PV project
 * @param {Object} params - Project parameters
 * @param {number} params.capacityKwp - Installed capacity [kWp]
 * @param {number} params.annualProductionMwh - Annual production [MWh] (P50)
 * @param {number} params.selfConsumedMwh - Annual self-consumed energy [MWh]
 * @param {number} params.gridConsumptionBeforeMwh - Grid consumption before PV [MWh/year]
 * @param {number} params.gridConsumptionAfterMwh - Grid consumption after PV [MWh/year]
 * @param {number} params.projectLifetimeYears - Project lifetime [years]
 * @param {number} params.degradationRate - Annual degradation [decimal, e.g. 0.005]
 * @returns {Object} ESG metrics
 */
function calculateESGMetrics(params) {
  const settings = getCurrentSettings();

  const {
    capacityKwp = 0,
    annualProductionMwh = 0,
    selfConsumedMwh = 0,
    gridConsumptionBeforeMwh = 0,
    gridConsumptionAfterMwh = 0,
    projectLifetimeYears = settings.analysisPeriod || 25,
    degradationRate = (settings.degradationRate || 0.5) / 100
  } = params;

  // Get emission factor (kgCO2e/kWh → tCO2e/MWh)
  const efGrid = settings.esgGridEmissionFactor; // kgCO2e/kWh
  const efGridTonnesPerMwh = efGrid; // kgCO2e/kWh = tCO2e/MWh (same numeric value)

  // Get embodied carbon for selected technology
  const embodiedCarbonPerKwp = getEmbodiedCarbonForTechnology(settings.esgPvTechnology);

  // [E1] Annual CO2 reduction (Scope 2, location-based)
  // CO2_baseline = MWh_baseline × EF_grid (in tonnes)
  // CO2_after = MWh_grid_after × EF_grid
  // CO2_reduction_year = CO2_baseline - CO2_after
  const co2BaselineYear = gridConsumptionBeforeMwh * efGridTonnesPerMwh / 1000; // tonnes CO2e
  const co2AfterYear = gridConsumptionAfterMwh * efGridTonnesPerMwh / 1000; // tonnes CO2e
  const co2ReductionYear = co2BaselineYear - co2AfterYear; // tonnes CO2e/year

  // Alternative calculation: based on self-consumed PV energy
  const co2AvoidedFromPV = selfConsumedMwh * efGridTonnesPerMwh / 1000; // tonnes CO2e/year

  // [E2] Lifetime CO2 reduction (with degradation)
  let co2ReductionLifetime = 0;
  for (let year = 1; year <= projectLifetimeYears; year++) {
    const degradationFactor = Math.pow(1 - degradationRate, year - 1);
    co2ReductionLifetime += co2ReductionYear * degradationFactor;
  }

  // [E3] Share of RES in energy consumption after PV
  // Share_RES = MWh_EaaS / (MWh_EaaS + MWh_grid_after) × 100%
  const totalConsumptionAfter = selfConsumedMwh + gridConsumptionAfterMwh;
  const shareRES = totalConsumptionAfter > 0
    ? (selfConsumedMwh / totalConsumptionAfter) * 100
    : 0;

  // [E4] Carbon payback (years to "repay" embodied carbon)
  // CO2_embodied = kWp × EF_PV_embodied (in kg → convert to tonnes)
  const co2Embodied = (capacityKwp * embodiedCarbonPerKwp) / 1000; // tonnes CO2e
  const carbonPaybackYears = co2ReductionYear > 0
    ? co2Embodied / co2ReductionYear
    : Infinity;

  // Net CO2 over lifetime (avoided - embodied)
  const co2NetLifetime = co2ReductionLifetime - co2Embodied;

  // Carbon intensity of PV electricity (gCO2e/kWh)
  // = embodied carbon / lifetime production
  let lifetimeProductionMwh = 0;
  for (let year = 1; year <= projectLifetimeYears; year++) {
    const degradationFactor = Math.pow(1 - degradationRate, year - 1);
    lifetimeProductionMwh += annualProductionMwh * degradationFactor;
  }
  const carbonIntensityPV = lifetimeProductionMwh > 0
    ? (co2Embodied * 1000000) / (lifetimeProductionMwh * 1000) // gCO2e/kWh
    : 0;

  return {
    // Annual metrics
    co2BaselineYear,              // tonnes CO2e/year (grid before PV)
    co2AfterYear,                 // tonnes CO2e/year (grid after PV)
    co2ReductionYear,             // tonnes CO2e/year (avoided)
    co2AvoidedFromPV,             // tonnes CO2e/year (from self-consumption)

    // Lifetime metrics
    co2ReductionLifetime,         // tonnes CO2e (total avoided over lifetime)
    co2Embodied,                  // tonnes CO2e (manufacturing footprint)
    co2NetLifetime,               // tonnes CO2e (net = avoided - embodied)

    // Ratios and payback
    shareRES,                     // % of energy from RES after PV
    carbonPaybackYears,           // years to repay embodied carbon
    carbonIntensityPV,            // gCO2e/kWh of PV electricity

    // Metadata
    efGrid,                       // kgCO2e/kWh (grid emission factor)
    efGridSource: settings.esgGridEmissionSource,
    embodiedCarbonPerKwp,         // kgCO2e/kWp
    embodiedCarbonSource: settings.esgEmbodiedCarbonSource,
    pvTechnology: settings.esgPvTechnology,
    projectLifetimeYears,
    reportingMethod: settings.esgReportingMethod,
    taxonomyAligned: settings.esgTaxonomyAligned,
    taxonomyActivityCode: settings.esgTaxonomyActivityCode,
    componentCompliance: settings.esgComponentCompliance
  };
}

/**
 * Toggle ESG emission provider settings visibility
 */
function toggleEsgEmissionProvider() {
  const provider = document.getElementById('esgGridEmissionProvider')?.value || 'manual';
  const manualSection = document.getElementById('esgManualEmissionSection');
  const apiSection = document.getElementById('esgApiEmissionSection');

  if (provider === 'manual') {
    if (manualSection) manualSection.style.display = 'block';
    if (apiSection) apiSection.style.display = 'none';
  } else {
    if (manualSection) manualSection.style.display = 'none';
    if (apiSection) apiSection.style.display = 'block';
  }

  markUnsaved();
}

// Make ESG functions globally available
window.calculateESGMetrics = calculateESGMetrics;
window.getEmbodiedCarbonForTechnology = getEmbodiedCarbonForTechnology;
window.toggleEsgEmissionProvider = toggleEsgEmissionProvider;

// ============================================================================
// Electricity Maps API Integration
// ============================================================================

// Store for last fetched data
let lastElectricityMapsData = null;

/**
 * Fetch data from Electricity Maps API
 * Endpoints used:
 * - /v3/carbon-intensity/latest - current carbon intensity
 * - /v3/renewable-percentage-level/latest - current renewable %
 * - /v3/carbon-intensity-fossil-only/latest - fossil fuels only CI
 */
async function fetchElectricityMapsData() {
  const apiKey = document.getElementById('electricitymapsApiKey')?.value?.trim();
  const zone = document.getElementById('electricitymapsZone')?.value || 'PL';
  const emissionType = document.getElementById('electricitymapsEmissionType')?.value || 'lifecycle';
  const statusEl = document.getElementById('emFetchStatus');

  if (!apiKey) {
    if (statusEl) statusEl.innerHTML = '<span style="color:#e74c3c">❌ Wprowadź API Key</span>';
    return;
  }

  if (statusEl) statusEl.innerHTML = '<span style="color:#3498db">⏳ Pobieranie danych...</span>';

  try {
    // Fetch all three endpoints in parallel
    const [carbonIntensityRes, renewableRes, fossilCIRes] = await Promise.all([
      fetchElectricityMapsEndpoint(apiKey, `/v3/carbon-intensity/latest?zone=${zone}&emissionFactorType=${emissionType}`),
      fetchElectricityMapsEndpoint(apiKey, `/v3/renewable-percentage-level/latest?zone=${zone}`),
      fetchElectricityMapsEndpoint(apiKey, `/v3/carbon-intensity-fossil-only/latest?zone=${zone}&emissionFactorType=${emissionType}`)
    ]);

    // Store data
    lastElectricityMapsData = {
      carbonIntensity: carbonIntensityRes?.carbonIntensity ?? null,
      renewablePercentage: renewableRes?.renewablePercentage ?? null,
      fossilCarbonIntensity: fossilCIRes?.carbonIntensity ?? null,
      zone: zone,
      timestamp: new Date().toISOString(),
      isEstimated: carbonIntensityRes?.isEstimated ?? false
    };

    // Update UI
    updateElectricityMapsUI(lastElectricityMapsData);

    if (statusEl) statusEl.innerHTML = '<span style="color:#27ae60">✅ Dane pobrane</span>';
    console.log('✅ Electricity Maps data fetched:', lastElectricityMapsData);

  } catch (error) {
    console.error('❌ Error fetching Electricity Maps data:', error);
    if (statusEl) statusEl.innerHTML = `<span style="color:#e74c3c">❌ Błąd: ${error.message}</span>`;
  }
}

/**
 * Fetch single endpoint from Electricity Maps API
 */
async function fetchElectricityMapsEndpoint(apiKey, endpoint) {
  const baseUrl = 'https://api.electricitymaps.com';
  const url = baseUrl + endpoint;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'auth-token': apiKey,
      'Accept': 'application/json'
    }
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API error ${response.status}: ${errorText}`);
  }

  return response.json();
}

/**
 * Update Electricity Maps live data UI
 */
function updateElectricityMapsUI(data) {
  const liveDataSection = document.getElementById('electricitymapsLiveData');
  if (liveDataSection) {
    liveDataSection.style.display = 'block';
  }

  // Carbon Intensity (gCO2eq/kWh)
  const ciEl = document.getElementById('emLiveCarbonIntensity');
  if (ciEl && data.carbonIntensity !== null) {
    ciEl.textContent = data.carbonIntensity.toFixed(0);
    // Color based on value (green < 200, yellow < 400, red > 400)
    if (data.carbonIntensity < 200) {
      ciEl.style.color = '#388e3c';
    } else if (data.carbonIntensity < 400) {
      ciEl.style.color = '#ffa000';
    } else {
      ciEl.style.color = '#d32f2f';
    }
  }

  // Renewable Percentage
  const renewEl = document.getElementById('emLiveRenewable');
  if (renewEl && data.renewablePercentage !== null) {
    renewEl.textContent = data.renewablePercentage.toFixed(1);
    // Color based on value (green > 50%, yellow > 25%, red < 25%)
    if (data.renewablePercentage > 50) {
      renewEl.style.color = '#388e3c';
    } else if (data.renewablePercentage > 25) {
      renewEl.style.color = '#ffa000';
    } else {
      renewEl.style.color = '#d32f2f';
    }
  }

  // Fossil Fuels Carbon Intensity
  const fossilEl = document.getElementById('emLiveFossilCI');
  if (fossilEl && data.fossilCarbonIntensity !== null) {
    fossilEl.textContent = data.fossilCarbonIntensity.toFixed(0);
  }

  // Timestamp
  const timestampEl = document.getElementById('emLiveTimestamp');
  if (timestampEl && data.timestamp) {
    const ts = new Date(data.timestamp);
    timestampEl.textContent = `Ostatnia aktualizacja: ${ts.toLocaleString('pl-PL')}`;
    if (data.isEstimated) {
      timestampEl.textContent += ' (szacunek)';
    }
  }

  // Zone
  const zoneEl = document.getElementById('emLiveZone');
  if (zoneEl) {
    zoneEl.textContent = `Zone: ${data.zone}`;
  }
}

/**
 * Apply Electricity Maps Carbon Intensity to manual EF_grid field
 */
function applyElectricityMapsToManual() {
  if (!lastElectricityMapsData || lastElectricityMapsData.carbonIntensity === null) {
    alert('⚠️ Najpierw pobierz dane z Electricity Maps');
    return;
  }

  // Convert gCO2eq/kWh to kgCO2e/kWh (divide by 1000)
  const efGridKg = lastElectricityMapsData.carbonIntensity / 1000;

  // Update manual fields
  const efGridEl = document.getElementById('esgGridEmissionFactor');
  if (efGridEl) {
    efGridEl.value = efGridKg.toFixed(3);
  }

  const yearEl = document.getElementById('esgGridEmissionYear');
  if (yearEl) {
    yearEl.value = new Date().getFullYear();
  }

  const sourceEl = document.getElementById('esgGridEmissionSource');
  if (sourceEl) {
    sourceEl.value = `Electricity Maps (${lastElectricityMapsData.zone})`;
  }

  // Switch back to manual mode
  const providerEl = document.getElementById('esgGridEmissionProvider');
  if (providerEl) {
    providerEl.value = 'manual';
    toggleEsgEmissionProvider();
  }

  markUnsaved();
  showStatus('✅ EF_grid zaktualizowany z Electricity Maps', 'success');
}

// Make Electricity Maps functions globally available
window.fetchElectricityMapsData = fetchElectricityMapsData;
window.applyElectricityMapsToManual = applyElectricityMapsToManual;

// ============================================================================
// Location Resolver (Geo-Service Integration)
// ============================================================================

// Store last resolved location
let resolvedGeoLocation = null;

// Geo-service endpoint (direct or via nginx proxy)
const GEO_SERVICE_URL = 'http://localhost:8021';

/**
 * Load Polish cities list for autocomplete
 */
async function loadPolishCitiesList() {
  try {
    const response = await fetch(GEO_SERVICE_URL + '/geo/cities/pl');
    if (response.ok) {
      const data = await response.json();
      const datalist = document.getElementById('polishCitiesList');
      if (datalist && data.cities) {
        datalist.innerHTML = data.cities.map(function(city) {
          return '<option value="' + city + '">';
        }).join('');
        console.log('📍 Loaded ' + data.cities.length + ' Polish cities for autocomplete');
      }
    }
  } catch (err) {
    console.warn('Could not load Polish cities list:', err.message);
  }
}

/**
 * Resolve location using geo-service
 */
async function resolveLocation() {
  const country = document.getElementById('geoCountry')?.value || 'PL';
  const postalCode = document.getElementById('geoPostalCode')?.value?.trim() || '';
  const city = document.getElementById('geoCity')?.value?.trim() || '';

  if (!postalCode && !city) {
    showGeoStatus('⚠️ Wprowadź kod pocztowy lub nazwę miejscowości', 'warning');
    return;
  }

  showGeoStatus('🔄 Szukam lokalizacji...', 'info');

  try {
    let url = GEO_SERVICE_URL + '/geo/resolve?country=' + encodeURIComponent(country);
    if (postalCode) url += '&postal_code=' + encodeURIComponent(postalCode);
    if (city) url += '&city=' + encodeURIComponent(city);

    const response = await fetch(url);

    if (!response.ok) {
      if (response.status === 404) {
        showGeoStatus('❌ Nie znaleziono lokalizacji. Sprawdź dane.', 'error');
      } else {
        const error = await response.text();
        showGeoStatus('❌ Błąd: ' + error, 'error');
      }
      return;
    }

    const location = await response.json();
    resolvedGeoLocation = location;

    // Display resolved location
    displayResolvedLocation(location);
    showGeoStatus(location.cached ? '✅ Lokalizacja z cache' : '✅ Lokalizacja znaleziona', 'success');

  } catch (err) {
    console.error('Geo resolve error:', err);
    showGeoStatus('❌ Błąd połączenia z geo-service: ' + err.message, 'error');
  }
}

/**
 * Display resolved location in UI
 */
function displayResolvedLocation(location) {
  const section = document.getElementById('geoResolvedSection');
  if (!section) return;

  section.style.display = 'block';

  // Display name (city or display_name)
  const nameEl = document.getElementById('geoResolvedName');
  if (nameEl) {
    nameEl.textContent = location.city || (location.display_name ? location.display_name.split(',')[0] : '–');
  }

  // Latitude
  const latEl = document.getElementById('geoResolvedLat');
  if (latEl) {
    latEl.textContent = location.latitude ? location.latitude.toFixed(4) + '°' : '–';
  }

  // Longitude
  const lonEl = document.getElementById('geoResolvedLon');
  if (lonEl) {
    lonEl.textContent = location.longitude ? location.longitude.toFixed(4) + '°' : '–';
  }

  // Elevation
  const elevEl = document.getElementById('geoResolvedElev');
  if (elevEl) {
    if (location.elevation !== null && location.elevation !== undefined) {
      elevEl.textContent = Math.round(location.elevation) + ' m';
    } else {
      elevEl.textContent = '–';
    }
  }
}

/**
 * Apply resolved location to all PV installation types
 */
function applyResolvedLocation() {
  if (!resolvedGeoLocation) {
    showGeoStatus('⚠️ Najpierw znajdź lokalizację', 'warning');
    return;
  }

  const lat = resolvedGeoLocation.latitude;
  const lon = resolvedGeoLocation.longitude;
  const elev = resolvedGeoLocation.elevation;

  // Apply latitude to all installation types
  const latFields = ['latitude_ground_s', 'latitude_roof_ew', 'latitude_ground_ew'];
  latFields.forEach(function(fieldId) {
    const el = document.getElementById(fieldId);
    if (el) {
      el.value = lat.toFixed(2);
    }
  });

  // Apply longitude to all installation types (if fields exist)
  const lonFields = ['longitude_ground_s', 'longitude_roof_ew', 'longitude_ground_ew'];
  lonFields.forEach(function(fieldId) {
    const el = document.getElementById(fieldId);
    if (el) {
      el.value = lon.toFixed(2);
    }
  });

  // Apply elevation to altitude field
  if (elev !== null && elev !== undefined) {
    const altEl = document.getElementById('altitude');
    if (altEl) {
      altEl.value = Math.round(elev);
    }
  }

  // Mark as unsaved and show status
  markUnsaved();

  const applyStatus = document.getElementById('geoApplyStatus');
  if (applyStatus) {
    let statusText = '✅ Zastosowano: lat=' + lat.toFixed(2) + '°, lon=' + lon.toFixed(2) + '°';
    if (elev !== null && elev !== undefined) {
      statusText += ', wysokość=' + Math.round(elev) + 'm';
    }
    applyStatus.textContent = statusText;
  }

  showStatus('✅ Lokalizacja zastosowana do parametrów instalacji', 'success');
}

/**
 * Clear resolved location
 */
function clearResolvedLocation() {
  resolvedGeoLocation = null;

  const section = document.getElementById('geoResolvedSection');
  if (section) {
    section.style.display = 'none';
  }

  // Clear input fields
  const postalEl = document.getElementById('geoPostalCode');
  if (postalEl) postalEl.value = '';

  const cityEl = document.getElementById('geoCity');
  if (cityEl) cityEl.value = '';

  const applyStatus = document.getElementById('geoApplyStatus');
  if (applyStatus) applyStatus.textContent = '';

  showGeoStatus('', '');
}

/**
 * Show geo status message
 */
function showGeoStatus(message, type) {
  const statusEl = document.getElementById('geoStatus');
  if (!statusEl) return;

  statusEl.textContent = message;

  // Apply color based on type
  switch (type) {
    case 'error':
      statusEl.style.color = '#d32f2f';
      break;
    case 'warning':
      statusEl.style.color = '#f57c00';
      break;
    case 'success':
      statusEl.style.color = '#388e3c';
      break;
    case 'info':
      statusEl.style.color = '#1976d2';
      break;
    default:
      statusEl.style.color = '#666';
  }
}

// Initialize location resolver on load
document.addEventListener('DOMContentLoaded', function() {
  // Try to load Polish cities list for autocomplete
  setTimeout(loadPolishCitiesList, 500);
});

// Make functions globally available
window.resolveLocation = resolveLocation;
window.applyResolvedLocation = applyResolvedLocation;
window.clearResolvedLocation = clearResolvedLocation;

// ============================================================================
// Operational Calendar UI
// ============================================================================

/**
 * Toggle operating mode fields visibility
 */
function toggleOperatingModeFields() {
  const mode = document.getElementById('operatingMode')?.value || '24_7';
  const customSection = document.getElementById('customHoursSection');

  if (customSection) {
    customSection.style.display = (mode === 'custom') ? 'block' : 'none';
  }
}

// Initialize operational calendar on load
document.addEventListener('DOMContentLoaded', function() {
  toggleOperatingModeFields();
});

// Make function globally available
window.toggleOperatingModeFields = toggleOperatingModeFields;

