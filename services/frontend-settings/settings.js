// Settings Module - Centralized Configuration Management

console.log('⚙️ Settings module loaded');

// Production mode - use nginx reverse proxy routes
const USE_PROXY = true;

// Backend API URLs
const API_URLS = USE_PROXY ? {
  pvgisProxy: '/api/pvgis',
  geo: '/api/geo'
} : {
  pvgisProxy: 'http://localhost:8020',
  geo: 'http://localhost:8021'
};

// Default configuration values
const DEFAULT_CONFIG = {
  // OSD Operator + Tariff Group ('' = manual mode)
  osdOperator: '',
  osdTariffGroup: '',
  // Fixed Charges (PLN/MWh) - WITHOUT active energy (defined in ToU section)
  // These charges are the same for all hours, except capacityFee (7-22 workdays only)
  energyActive: 0,  // DEPRECATED: Now defined per zone in ToU tariff section
  distribution: 200,        // weighted average (computed, readonly)
  distributionPeak: 200,     // PLN/MWh - szczyt
  distributionDay: 200,      // PLN/MWh - dzień/pośrednia
  distributionNight: 200,    // PLN/MWh - noc/pozaszczyt
  distributionValley: 13.50, // PLN/MWh - dolina obciążenia (głęboka noc + weekendy, only four_zone)

  // Distribution Time Windows (separate from energy ToU — OSD tariff zones)
  distributionConfig: {
    type: 'three_zone',       // 'flat', 'two_zone', 'three_zone', 'four_zone'
    twoZone: {
      weekday: { start: 6, end: 22 },
      weekend: { start: 6, end: 22 }
    },
    threeZone: {
      peak1: { start: 7, end: 13 },
      peak2: { start: 16, end: 21 },
      weekendOffPeak: true       // weekends = off-peak (night rate)
    },
    fourZone: {
      peak1: { start: 7, end: 13 },
      peak2: { start: 16, end: 21 },
      valley: { start: 1, end: 5 } // deep night only: 1:00-4:59 weekdays; weekends = full valley
    }
  },
  qualityFee: 33.10,
  ozeFee: 7.30,
  cogenerationFee: 3,
  capacityFee: 219.40,  // Auto-calculated from SOM rate × 1000 (only 7-22 Pn-Pt)
  exciseTax: 5,
  totalFixedCharges: 467.80,  // Sum of fixed charges (200+33.10+7.30+3+219.40+5)

  // Capacity Fee (Opłata Mocowa) - Polish Capacity Market
  capacityFeeConfig: {
    year: 2026,
    somRate: 0.2194,              // SOM [PLN/kWh] - URE 58/2025
    qualificationPeriod: 'daily', // 'daily' (2025+), 'decadal' (2023-2024), 'monthly' (≤2022)
    somSource: 'URE 58/2025',
    selectedHours: {
      Q1: { start: 7, end: 22 },  // January-March
      Q2: { start: 7, end: 22 },  // April-June
      Q3: { start: 7, end: 22 },  // July-September
      Q4: { start: 7, end: 22 },  // October-December
    },
    // K-class coefficients (read-only, based on law)
    kCoefficients: {
      K1: 0.17,  // Δs < -10% (Dz.U. 2023 poz. 503)
      K2: 0.50,  // -10% ≤ Δs < 10%
      K3: 0.83,  // 10% ≤ Δs < 30%
      K4: 1.00,  // Δs ≥ 30%
    }
  },

  // Fixed Monthly Fees (not dependent on energy volume)
  fixedMonthlyFees: {
    contractedPowerKw: 50,          // kW — contracted power from OSD agreement
    distFixedRatePerKwMonth: 9.14,  // zł/kW/month — C11: 8.04, C12: 9.14, C21: 32.02
    osdSubscriptionFeeMonth: 5.54,  // PLN/month — OSD subscription fee
    transitionFeeMonth: 0,          // PLN/month — transition fee (0 in 2026)
    supplierTradeFeeMonth: 0        // PLN/month — supplier trade fee (optional)
  },

  // Time-of-Use Tariffs Configuration
  tariffConfig: {
    type: 'two_zone',     // 'flat', 'two_zone', 'three_zone'
    name: 'C12a',         // Tariff name for display
    // Flat tariff (single rate)
    flatRate: 750,        // PLN/MWh
    // Two-zone tariff (day/night)
    twoZone: {
      dayRate: 850,       // PLN/MWh
      nightRate: 450,     // PLN/MWh
      weekday: { start: 6, end: 22 },   // Mon-Fri day hours
      weekend: { start: 6, end: 13 },   // Sat-Sun day hours
    },
    // Three-zone tariff (peak/partial/off-peak)
    threeZone: {
      peakRate: 950,      // PLN/MWh
      partialRate: 700,   // PLN/MWh
      offPeakRate: 400,   // PLN/MWh
      peak1: { start: 7, end: 13 },     // Morning peak
      peak2: { start: 17, end: 21 },    // Evening peak
      partial: { start: 13, end: 17 },  // Partial peak (between peaks)
    }
  },

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
  discountRate: 10,
  pvDegradationYear1: 1.0,        // First year PV degradation [%] - LID (TOPCon ~1%, PERC ~2%)
  degradationRate: 0.5,           // Annual PV degradation for years 2+ [%/year]
  analysisPeriod: 25,
  inflationRate: 2.5,

  // Production scenario factors (P-values)
  productionFactorP50: 1.00,    // P50 = baseline
  productionFactorP75: 0.97,    // P75 = conservative
  productionFactorP90: 0.94,    // P90 = very conservative

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
  pvgisEndYear: 2023,          // End year for timeseries (SARAH3 data available to 2023)
  pvgisPvTechChoice: 'crystSi2025', // PV technology: 'crystSi2025' (recommended), 'crystSi', 'CIS', 'CdTe'
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
  capMin: 100,
  capMax: 25000,
  capStep: 50,

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
  // BESS - Battery Energy Storage System
  // ============================================================================
  // Tryby:
  //   - 'off'   = brak magazynu
  //   - 'pro'   = optymalizacja LP/MIP przez PyPSA + HiGHS (DOMYŚLNY)
  //   - 'light' = DEPRECATED - legacy auto-sizing

  bessMode: 'pro',                     // Master mode: 'off' | 'pro' (light deprecated)
  bessEnabled: true,                   // Legacy: for backwards compatibility
  bessDuration: 'auto',                // Duration mode: 'auto' | 1 | 2 | 4 (hours)
                                       // 'auto' = system tests 1h/2h/4h and picks best NPV

  // BESS Technical Defaults (used by LIGHT and PRO modes)
  bessRoundtripEfficiency: 0.85,       // Round-trip efficiency AC-DC-AC (cells + inverter + transformer)
  bessSocMin: 0.10,                    // Minimum SOC (10% = protect battery health)
  bessSocMax: 0.90,                    // Maximum SOC (90% = protect battery health)
  bessSocInitial: 0.50,                // Initial SOC at start of simulation

  // BESS Economic Defaults
  bessCapexPerKwh: 900,                // CAPEX per kWh capacity [PLN/kWh] (battery cells + BMS, LFP 2025)
  bessCapexPerKw: 200,                 // CAPEX per kW power [PLN/kW] (inverter/PCS)
  bessOpexPctPerYear: 1.5,             // Annual OPEX as % of CAPEX
  bessLifetimeYears: 15,               // Expected battery lifetime [years]
  bessCycleLifetime: 6000,             // Cycle lifetime (number of full cycles before replacement)
  bessDegradationYear1: 3.0,           // First year degradation [%] (higher due to initial settling)
  bessDegradationPctPerYear: 2.0,      // Annual capacity degradation for years 2+ [%/year]
  bessHouseLoadKwPerMwh: 2.75,         // House load [kW per MWh capacity] (HVAC, BMS, PCS standby)

  // ============================================================================
  // BESS PRO - Advanced LP/MIP Optimization (PyPSA + HiGHS)
  // ============================================================================

  // PRO Mode Sizing Constraints
  bessProMinPowerKw: 50,               // Minimum BESS power [kW]
  bessProMaxPowerKw: 10000,            // Maximum BESS power [kW]
  bessProMinEnergyKwh: 100,            // Minimum BESS energy [kWh]
  bessProMaxEnergyKwh: 50000,          // Maximum BESS energy [kWh]
  bessProDurationMin: 1,               // Minimum duration E/P [hours]
  bessProDurationMax: 4,               // Maximum duration E/P [hours]

  // PRO Mode Optimization Settings
  bessProSolver: 'highs',              // Solver: 'highs' (default, open-source) | 'glpk' | 'cbc'
  bessProObjective: 'npv',             // Objective: 'npv' | 'payback' | 'autoconsumption'
  bessProTimeResolution: 'hourly',     // Time resolution: 'hourly' | '15min'
  bessProTypicalDays: 0,               // 0 = use all 8760 hours, >0 = compress to N typical days

  // PRO Mode Zero-Export Constraint
  bessProZeroExport: true,             // Enforce zero grid export constraint
  bessProExportPenalty: 1000,          // Penalty for grid export [PLN/MWh] (soft constraint)

  // ============================================================================
  // BESS Advanced Features - Peak Shaving & Price Arbitrage
  // ============================================================================

  // Peak Shaving (redukcja opłat mocowych przez obcinanie szczytów zużycia)
  bessPeakShavingEnabled: false,       // Enable peak shaving optimization
  bessPeakShavingMode: 'auto',         // 'auto' (P95) | 'manual' | 'percentage'
  bessPeakShavingTargetKw: 0,          // Target peak power [kW] (for manual mode)
  bessPeakShavingPctReduction: 15,     // Target % reduction from historical peak (for percentage mode)
  bessPowerChargePlnPerKwMonth: 50,    // Power charge [PLN/kW/month] for peak shaving savings

  // OSD Tariff Arbitrage (ToU - arbitraż na strefach czasowych OSD)
  bessOsdArbitrageEnabled: false,      // Enable OSD tariff arbitrage
  bessOsdOperator: 'pge',              // 'pge' | 'tauron' | 'energa' | 'enea' | 'innogy'
  bessOsdTariffGroup: 'C12a',          // 'C11' | 'C12a' | 'C12b' | 'C22a' | 'C22b'
  bessOsdPeakRate: 0.75,               // Peak zone rate [PLN/kWh]
  bessOsdOffPeakRate: 0.45,            // Off-peak zone rate [PLN/kWh]
  bessOsdMinSpread: 0.15,              // Minimum spread to trigger arbitrage [PLN/kWh]

  // Hybrid Monthly Pricing (miks OSD + RDN per miesiąc)
  pricingMode: 'single',               // 'single' = one source all year, 'hybrid_monthly' = per-month mix
  monthlyPriceSources: {               // Per-month: 'osd' or 'rdn' (only used when pricingMode='hybrid_monthly')
    1: 'osd', 2: 'osd', 3: 'osd', 4: 'osd', 5: 'osd', 6: 'osd',
    7: 'osd', 8: 'osd', 9: 'osd', 10: 'osd', 11: 'osd', 12: 'osd'
  },

  // RDN Price Arbitrage (arbitraż cenowy RDN/spot - kupuj tanio, sprzedawaj drogo)
  bessPriceArbitrageEnabled: false,    // Enable RDN price arbitrage optimization
  bessPriceArbitrageSource: 'manual',  // 'manual' | 'tge_api' | 'csv_upload'
  bessPriceArbitrageBuyThreshold: 300, // Buy energy when price below [PLN/MWh]
  bessPriceArbitrageSellThreshold: 600,// Sell energy when price above [PLN/MWh]
  bessPriceArbitrageSpread: 100,       // Minimum spread to trigger arbitrage [PLN/MWh]
  bessRdnPriceFlat: 500,               // Flat RDN price [PLN/MWh] (for manual mode without profile)
  bessRdnPriceMultiplier: 1.0,         // RDN price multiplier (for scenario analysis)

  // ============================================================================
  // Ancillary Services (Revenue Stacking)
  // ============================================================================
  ancillaryServicesEnabled: false,       // Master toggle for ancillary revenue
  ancSvcAfrrUp: true,                    // aFRR Up (secondary reserve up)
  ancSvcAfrrDown: true,                  // aFRR Down (secondary reserve down)
  ancSvcMfrrUp: true,                    // mFRR Up (tertiary reserve up)
  ancSvcFcr: false,                      // FCR (frequency containment reserve)
  ancSvcCapMarket: false,                // Capacity Market (Rynek Mocy)
  ancillaryMarketYear: 2026,             // Reference year for PSE prices
  ancillaryAggregatorMarginPct: 20,      // Aggregator margin [%]
  ancillaryAfrrPrice: 200,              // aFRR capacity price [PLN/MW/h]
  ancillaryMfrrPrice: 95,               // mFRR capacity price [PLN/MW/h]
  ancillaryFcrPrice: 150,               // FCR capacity price [PLN/MW/h]
  ancillaryCapMarketPrice: 280000,       // Capacity market [PLN/MW/year]
  ancillaryKwd: 0.133,                  // KWD (power availability factor for BESS)
  ancillaryMinAvailability: 95,          // Min technical availability [%]
  ancillaryMaxCapacityShare: 80,         // Max % of battery power for ancillary
  ancillaryOptimizeMode: 'sample_days',  // 'year' or 'sample_days'

  // ============================================================================
  // BESS Scenarios - Work mode selection (MVP v3.17)
  // ============================================================================
  bessScenarioId: null,                 // Selected scenario ID (null = auto-select based on topology)
  bessCapacityFeeOverlay: false,        // Show capacity fee savings overlay after dispatch

  // ============================================================================
  // RDN Dynamic Pricing - Rynek Dnia Następnego (Day-Ahead Market)
  // ============================================================================
  rdnPricingConfig: {
    enabled: false,
    scenarioId: null,
    scenarioName: '',
    year: null,
    avgPrice: null,
    minPrice: null,
    maxPrice: null,
    dataPoints: 0
  }
};

// ============================================================================
// BESS SCENARIOS DEFINITIONS
// ============================================================================
// Note:
// - Scenario 6 (Capacity Fee) is a CHECKBOX OVERLAY, not a base scenario
// - Scenario 7 baseMode depends on topology (stacked for pv_bess, load_only for bess_only)

const BESS_SCENARIOS = {
  1: {
    id: 1,
    name: 'Autokonsumpcja PV (0-export)',
    shortName: 'Autokonsumpcja',
    description: 'Maksymalizacja zużycia własnego, minimalizacja curtailment',
    topologies: ['pv_bess'],
    modes: ['light', 'pro'],
    baseMode: 'pv_surplus',
    presets: {
      bessRoundtripEfficiency: 90,
      bessSocMin: 10,
      bessSocMax: 90,
      bessDuration: 'auto'
    },
    requiredFields: [],
    kpiLabels: ['Self-consumption', 'Curtailment'],
    icon: '☀️'
  },
  2: {
    id: 2,
    name: 'PV + Peak Shaving (STACKED)',
    shortName: 'PV + Peak',
    description: 'Autokonsumpcja + redukcja szczytów mocy pobieranej z sieci',
    topologies: ['pv_bess'],
    modes: ['light', 'pro'],
    baseMode: 'stacked',
    presets: {
      bessPeakShavingEnabled: true,
      bessPeakShavingMode: 'auto',
      // reserve_fraction handled via stacked_params in request
    },
    requiredFields: [],  // peak_limit_kw opcjonalny - auto z P95
    recommended: true,
    kpiLabels: ['Peak reduction', 'Savings'],
    icon: '⚡'
  },
  3: {
    id: 3,
    name: 'Peak Shaving (BESS-only)',
    shortName: 'Peak Shaving',
    description: 'Redukcja szczytów bez PV - tylko magazyn energii',
    topologies: ['bess_only'],
    modes: ['light', 'pro'],
    baseMode: 'load_only',
    presets: {
      bessPeakShavingEnabled: true,
      bessPeakShavingMode: 'auto'
    },
    requiredFields: [],  // peak_limit_kw opcjonalny - auto z P95
    recommended: true,  // Default dla bess_only
    kpiLabels: ['Peak reduction', 'Monthly savings'],
    icon: '📉'
  },
  // Scenarios 4 and 5 removed from tiles - arbitrage is now an overlay checkbox
  // (combinable with any base scenario, like capacity fee overlay)
  // Scenariusz 6 NIE jest kafelkiem - to checkbox overlay
  // Definicja tylko dla dokumentacji
  7: {
    id: 7,
    name: 'Backup / UPS (wysoka rezerwa)',
    shortName: 'Backup/UPS',
    description: 'Wysoka rezerwa SOC dla zasilania awaryjnego',
    topologies: ['pv_bess', 'bess_only'],
    modes: ['light', 'pro'],
    // baseMode zależny od topologii - obsługiwane w getScenarioBaseMode()
    baseMode: null,
    presets: {
      // reserve_fraction: 0.70 handled in request building
    },
    requiredFields: [],
    reserveFraction: 0.70,
    infoTooltip: 'MVP: rezerwa dotyczy PV shifting; peak shaving może naruszyć rezerwę w sytuacji awaryjnej',
    icon: '🔒'
  },
  8: {
    id: 8,
    name: 'Duże piki (EV hub / rozruchy)',
    shortName: 'Duże piki',
    description: 'Optymalizacja pod krótkie, intensywne szczyty mocy',
    topologies: ['pv_bess'],
    modes: ['pro'],
    baseMode: 'stacked',
    presets: {
      bessDuration: '1',  // 1h - wysoka moc, mała pojemność
      bessPeakShavingEnabled: true,
      bessPeakShavingMode: 'manual'
    },
    requiredFields: ['bessPeakShavingTargetKw'],
    interval15minSupport: true,  // 15-min tylko jeśli dane mają 35040 punktów
    kpiLabels: ['Peak kW cut', 'Duration coverage'],
    icon: '🚗'
  },
  9: {
    id: 9,
    name: 'PV + Arbitraż RDN (Spot)',
    shortName: 'PV + RDN',
    description: 'Ładuj BESS gdy ceny RDN niskie, rozładuj gdy wysokie. Wymaga cen RDN.',
    topologies: ['pv_bess'],
    modes: ['pro'],
    baseMode: 'pv_surplus',
    gridCharging: false,  // battery charges ONLY from PV surplus
    presets: {
      bessPeakShavingEnabled: false,
      bessPriceArbitrageEnabled: true,
    },
    requiredFields: [],
    requiresRdn: true,
    kpiLabels: ['RDN Spread', 'Arbitrage Savings'],
    icon: '📈'
  },
  10: {
    id: 10,
    name: 'Magazyn — Arbitraż ToU/RDN',
    shortName: 'Arbitraż BESS',
    description: 'BESS bez PV. Zarobek na spreadzie cenowym: ładuj tanio (noc/off-peak/niski RDN), rozładuj drogo (dzień/peak/wysoki RDN).',
    topologies: ['bess_only'],
    modes: ['light', 'pro'],
    baseMode: 'load_only',
    gridCharging: true,  // bateria ładuje wyłącznie z sieci
    presets: {
      bessPeakShavingEnabled: false,
      bessPriceArbitrageEnabled: true,
      bessOsdArbitrageEnabled: true,
    },
    requiredFields: [],
    requiresRdn: false,  // działa z ToU, RDN opcjonalnie
    recommended: false,
    kpiLabels: ['ToU/RDN Spread', 'Arbitrage Revenue', 'Cycles/year'],
    icon: '💹'
  },
  11: {
    id: 11,
    name: 'Magazyn — Pełny Stack',
    shortName: 'BESS Full Stack',
    description: 'BESS bez PV: arbitraż (ToU + RDN) + peak shaving + usługi sieciowe (aFRR, mFRR, FCR, rynek mocy).',
    topologies: ['bess_only'],
    modes: ['pro'],
    baseMode: 'load_only',
    gridCharging: true,  // bateria ładuje z sieci
    presets: {
      bessPeakShavingEnabled: true,
      bessPeakShavingMode: 'auto',
      bessPriceArbitrageEnabled: true,
      bessOsdArbitrageEnabled: true,
      ancillaryServicesEnabled: true,
    },
    requiredFields: [],
    requiresRdn: false,
    recommended: true,  // domyślny dla bess_only z pełnym stackiem
    kpiLabels: ['Total Revenue', 'Arbitrage', 'Peak Shaving', 'Ancillary'],
    icon: '🏦'
  }
}

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
  // Initialize pricing routing summary
  setTimeout(updatePricingRoutingSummary, 500);
});

// ============================================================================
// BESS Section Toggle Functions
// ============================================================================

/**
 * Set BESS topology (pv_bess vs bess_only) and update UI
 * @param {string} topology - 'pv_bess' | 'bess_only'
 */
function setBessTopology(topology) {
  // Update hidden input
  const topologyInput = document.getElementById('bessTopology');
  if (topologyInput) topologyInput.value = topology;

  // Update UI indicators
  const pvBessBtn = document.getElementById('topologyPvBess');
  const bessOnlyBtn = document.getElementById('topologyBessOnly');
  const bessOnlyInfo = document.getElementById('bessOnlyInfo');

  if (pvBessBtn) {
    pvBessBtn.style.border = topology === 'pv_bess' ? '2px solid #4caf50' : '2px solid transparent';
    pvBessBtn.style.opacity = topology === 'pv_bess' ? '1' : '0.6';
  }

  if (bessOnlyBtn) {
    bessOnlyBtn.style.border = topology === 'bess_only' ? '2px solid #ff9800' : '2px solid transparent';
    bessOnlyBtn.style.opacity = topology === 'bess_only' ? '1' : '0.6';
  }

  // Show/hide BESS-only info box
  if (bessOnlyInfo) {
    bessOnlyInfo.style.display = topology === 'bess_only' ? 'block' : 'none';
  }

  console.log(`🔋 BESS topology set to: ${topology}`);
  markUnsaved();
}

/**
 * Set BESS mode (off/light/pro) and update UI accordingly
 * @param {string} mode - 'off' | 'light' | 'pro'
 */
function setBessMode(mode) {
  // Update hidden input
  const bessModeInput = document.getElementById('bessMode');
  if (bessModeInput) bessModeInput.value = mode;

  // Update legacy bessEnabled for backwards compatibility
  const bessEnabledInput = document.getElementById('bessEnabled');
  if (bessEnabledInput) bessEnabledInput.value = (mode !== 'off') ? 'true' : 'false';

  // Update UI and show/hide sections
  toggleBessSection();

  console.log(`🔋 BESS mode set to: ${mode}`);
  markUnsaved();
}

/**
 * Toggle BESS configuration sections based on bessMode
 * Shows/hides duration, economics, technical, and PRO parameters
 */
// Toggle ancillary services detail section based on master checkbox
function toggleAncillaryDetail() {
  const enabled = document.getElementById('ancillaryServicesEnabled')?.checked ?? false;
  const detail = document.getElementById('ancillarySettingsDetail');
  if (detail) detail.style.display = enabled ? 'block' : 'none';
}

function toggleBessSection() {
  const bessMode = document.getElementById('bessMode')?.value || 'off';
  const durationSection = document.getElementById('bessDurationSection');
  const economicsSection = document.getElementById('bessEconomicsSection');
  const technicalSection = document.getElementById('bessTechnicalSection');
  const proSection = document.getElementById('bessProSection');
  const statusOff = document.getElementById('bessStatusOff');
  const statusLight = document.getElementById('bessStatusLight');
  const statusPro = document.getElementById('bessStatusPro');

  // Reset all status indicators
  const resetStatus = (el, active, borderColor) => {
    if (el) {
      el.style.border = active ? `2px solid ${borderColor}` : '2px solid transparent';
      el.style.opacity = active ? '1' : '0.5';
    }
  };

  resetStatus(statusOff, bessMode === 'off', '#ef5350');
  resetStatus(statusLight, bessMode === 'light', '#4caf50');
  resetStatus(statusPro, bessMode === 'pro', '#ff9800');

  // Show/hide sections based on mode
  const isEnabled = bessMode !== 'off';
  const isPro = bessMode === 'pro';

  // Common BESS sections (shown for both LIGHT and PRO)
  if (durationSection) durationSection.style.display = isEnabled && !isPro ? 'block' : 'none';  // Duration only for LIGHT
  if (economicsSection) economicsSection.style.display = isEnabled ? 'block' : 'none';
  if (technicalSection) technicalSection.style.display = isEnabled ? 'block' : 'none';

  // PRO-specific section
  if (proSection) proSection.style.display = isPro ? 'block' : 'none';

  // Advanced features section (Peak Shaving & Arbitrage - shown for both LIGHT and PRO)
  const advancedSection = document.getElementById('bessAdvancedFeaturesSection');
  if (advancedSection) advancedSection.style.display = isEnabled ? 'block' : 'none';

  // Constraints section (Grid connection & EFC limit)
  const constraintsSection = document.getElementById('bessConstraintsSection');
  if (constraintsSection) constraintsSection.style.display = isEnabled ? 'block' : 'none';

  console.log(`🔋 BESS mode: ${bessMode} (enabled: ${isEnabled}, pro: ${isPro})`);
}

/**
 * Predefiniowane profile degradacji baterii od producentów
 * Wartości obliczone na podstawie gwarancji i specyfikacji technicznych
 *
 * Wzór: pozostała_pojemność = (1 - deg_rok1) × (1 - deg_roczna)^(lata-1)
 *
 * Przykład dla CATL LFP (80% po 10 latach):
 * 0.80 = (1 - 0.03) × (1 - 0.0189)^9
 * → deg_rok1 = 3%, deg_roczna = 1.89%
 */
const DEGRADATION_PROFILES = {
  // ========== Profile producentów ==========
  catl_lfp: {
    name: 'CATL LFP',
    year1: 3.0,      // % degradacji w roku 1
    annual: 1.9,     // % degradacji rocznie (lata 2+)
    lifetime: 15,    // gwarantowana żywotność [lat]
    cycles: 6000,    // gwarantowane cykle
    eol_capacity: 80, // % pojemności na koniec gwarancji
    chemistry: 'LFP',
    notes: 'Chińskie ogniwa LFP, wysoka żywotność, stabilność termiczna'
  },
  byd_blade: {
    name: 'BYD Blade',
    year1: 3.5,
    annual: 2.2,
    lifetime: 10,
    cycles: 6000,
    eol_capacity: 80,
    chemistry: 'LFP (Blade)',
    notes: 'Technologia Blade - bezpieczna, długa żywotność'
  },
  tesla_megapack: {
    name: 'Tesla Megapack',
    year1: 2.5,
    annual: 2.0,
    lifetime: 15,
    cycles: 4000,
    eol_capacity: 70,
    chemistry: 'NMC/LFP',
    notes: 'Przemysłowe magazyny Tesla, gwarancja 70% po 15 latach'
  },
  samsung_sdi: {
    name: 'Samsung SDI',
    year1: 3.0,
    annual: 2.0,
    lifetime: 10,
    cycles: 6000,
    eol_capacity: 80,
    chemistry: 'NMC',
    notes: 'Koreańskie ogniwa NMC, wysoka gęstość energii'
  },
  lg_resu: {
    name: 'LG RESU',
    year1: 4.0,
    annual: 3.5,
    lifetime: 10,
    cycles: 4000,
    eol_capacity: 60,
    chemistry: 'NMC',
    notes: 'Magazyny residencyjne LG, krótszy okres gwarancji'
  },
  pylontech: {
    name: 'Pylontech',
    year1: 3.0,
    annual: 2.0,
    lifetime: 10,
    cycles: 6000,
    eol_capacity: 80,
    chemistry: 'LFP',
    notes: 'Popularne chińskie ogniwa LFP, dobry stosunek cena/jakość'
  },
  huawei_luna: {
    name: 'Huawei LUNA',
    year1: 3.0,
    annual: 2.8,
    lifetime: 10,
    cycles: 4000,
    eol_capacity: 70,
    chemistry: 'LFP',
    notes: 'Magazyny Huawei, zintegrowane z falownikami'
  },

  // ========== Profile użytkowe ==========
  conservative: {
    name: 'Konserwatywny',
    year1: 4.0,
    annual: 3.0,
    lifetime: 10,
    cycles: 3000,
    eol_capacity: 70,
    chemistry: 'Generic',
    notes: 'Ostrożne założenia dla nieznanego producenta'
  },
  moderate: {
    name: 'Umiarkowany',
    year1: 3.0,
    annual: 2.0,
    lifetime: 15,
    cycles: 5000,
    eol_capacity: 80,
    chemistry: 'Generic',
    notes: 'Typowe wartości dla dobrych magazynów Li-ion'
  },
  optimistic: {
    name: 'Optymistyczny',
    year1: 2.0,
    annual: 1.5,
    lifetime: 15,
    cycles: 6000,
    eol_capacity: 85,
    chemistry: 'LFP Premium',
    notes: 'Optymistyczne założenia dla premium LFP'
  },
  aggressive: {
    name: 'Agresywny (wysoki DoD)',
    year1: 5.0,
    annual: 4.0,
    lifetime: 8,
    cycles: 2000,
    eol_capacity: 70,
    chemistry: 'Generic',
    notes: 'Intensywna eksploatacja, wysoki DoD, częste cykle'
  }
};

/**
 * Zastosuj profil degradacji do pól formularza
 * @param {string} profileId - ID profilu z DEGRADATION_PROFILES
 * @param {string} mode - 'light' lub 'pro'
 */
function applyDegradationProfile(profileId, mode) {
  if (profileId === 'custom') {
    console.log(`📝 Degradation profile: custom (manual input enabled)`);
    return;
  }

  const profile = DEGRADATION_PROFILES[profileId];
  if (!profile) {
    console.warn(`❓ Unknown degradation profile: ${profileId}`);
    return;
  }

  // Ustaw wartości w odpowiednich polach
  const prefix = mode === 'pro' ? 'bessProDegradation' : 'bessDegradation';

  const year1El = document.getElementById(`${prefix}Year1`);
  const annualEl = document.getElementById(`${prefix}PctPerYear`);

  if (year1El) year1El.value = profile.year1;
  if (annualEl) annualEl.value = profile.annual;

  // Synchronizuj do drugiego trybu
  syncDegradationParams(mode);

  // Synchronizuj również dropdown w drugim trybie
  const otherPrefix = mode === 'pro' ? 'bessDegradation' : 'bessProDegradation';
  const otherDropdown = document.getElementById(`${otherPrefix}Profile`);
  if (otherDropdown) {
    otherDropdown.value = profileId;
  }

  console.log(`🔋 Degradation profile applied: ${profile.name}`, {
    year1: profile.year1 + '%',
    annual: profile.annual + '%/rok',
    eol: profile.eol_capacity + '% po ' + profile.lifetime + ' lat',
    chemistry: profile.chemistry
  });

  markUnsaved();
}

/**
 * Obsługa ręcznej zmiany parametrów degradacji
 * Przełącza dropdown na "Własne parametry"
 */
function onDegradationManualChange(mode) {
  const prefix = mode === 'pro' ? 'bessProDegradation' : 'bessDegradation';
  const dropdown = document.getElementById(`${prefix}Profile`);
  if (dropdown) {
    dropdown.value = 'custom';
  }

  // Synchronizuj również drugi tryb
  const otherPrefix = mode === 'pro' ? 'bessDegradation' : 'bessProDegradation';
  const otherDropdown = document.getElementById(`${otherPrefix}Profile`);
  if (otherDropdown) {
    otherDropdown.value = 'custom';
  }

  syncDegradationParams(mode);
}

/**
 * Synchronize degradation parameters between LIGHT and PRO sections
 * When user changes a value in one mode, it updates the other mode
 * @param {string} source - 'light' or 'pro' - which section triggered the change
 */
function syncDegradationParams(source) {
  // Field mappings: LIGHT field ID -> PRO field ID
  const fieldMappings = {
    'bessDegradationYear1': 'bessProDegradationYear1',
    'bessDegradationPctPerYear': 'bessProDegradationPctPerYear',
    'bessHouseLoadKwPerMwh': 'bessProHouseLoadKwPerMwh'
  };

  if (source === 'light') {
    // Copy from LIGHT to PRO
    Object.entries(fieldMappings).forEach(([lightId, proId]) => {
      const lightEl = document.getElementById(lightId);
      const proEl = document.getElementById(proId);
      if (lightEl && proEl) {
        proEl.value = lightEl.value;
      }
    });
    console.log('🔄 Degradation params synced: LIGHT → PRO');
  } else if (source === 'pro') {
    // Copy from PRO to LIGHT
    Object.entries(fieldMappings).forEach(([lightId, proId]) => {
      const lightEl = document.getElementById(lightId);
      const proEl = document.getElementById(proId);
      if (lightEl && proEl) {
        lightEl.value = proEl.value;
      }
    });
    console.log('🔄 Degradation params synced: PRO → LIGHT');
  }

  markUnsaved();
}

// ============================================================================
// BESS SCENARIOS FUNCTIONS
// ============================================================================

// Current selected scenario ID
let currentBessScenarioId = null;

/**
 * Get available scenarios based on topology and bessMode
 * @param {string} topology - 'pv_bess' | 'bess_only'
 * @param {string} bessMode - 'off' | 'light' | 'pro'
 * @returns {Array} - Array of scenario objects
 */
function getAvailableScenarios(topology, bessMode) {
  if (bessMode === 'off') return [];

  return Object.values(BESS_SCENARIOS).filter(scenario => {
    const topologyMatch = scenario.topologies.includes(topology);
    const modeMatch = scenario.modes.includes(bessMode);
    return topologyMatch && modeMatch;
  });
}

/**
 * Get default scenario ID for given topology
 * @param {string} topology - 'pv_bess' | 'bess_only'
 * @returns {number|null} - Default scenario ID
 */
function getDefaultScenarioId(topology) {
  // pv_bess -> scenario 2 (STACKED), bess_only -> scenario 10 (Arbitraż BESS)
  return topology === 'pv_bess' ? 2 : 10;
}

/**
 * Get baseMode for a scenario, considering topology
 * Scenario 7 (Backup) has topology-dependent baseMode
 * @param {object} scenario - Scenario object
 * @param {string} topology - 'pv_bess' | 'bess_only'
 * @returns {string|null} - Base dispatch mode
 */
function getScenarioBaseMode(scenario, topology) {
  // Scenario 7 (Backup) - baseMode depends on topology
  if (scenario.id === 7) {
    return topology === 'pv_bess' ? 'stacked' : 'load_only';
  }
  return scenario.baseMode;
}

/**
 * Set BESS scenario and apply presets
 * @param {number} scenarioId - Scenario ID to select
 */
function setBessScenario(scenarioId) {
  const scenario = BESS_SCENARIOS[scenarioId];
  if (!scenario) {
    console.warn(`Unknown scenario ID: ${scenarioId}`);
    return;
  }

  // Check if scenario is BETA and disabled
  if (scenario.beta) {
    showToast('info', scenario.betaTooltip || 'Ten scenariusz jest w wersji BETA');
    return;
  }

  currentBessScenarioId = scenarioId;

  // Update hidden input
  const scenarioInput = document.getElementById('bessScenarioId');
  if (scenarioInput) scenarioInput.value = scenarioId;

  // Apply presets from scenario
  if (scenario.presets) {
    Object.entries(scenario.presets).forEach(([key, value]) => {
      applyScenarioPreset(key, value);
    });
  }

  // Auto-enable RDN overlay for scenarios that require it
  if (scenario.requiresRdn) {
    const rdnHidden = document.getElementById('bessPriceArbitrageEnabled');
    const rdnOverlay = document.getElementById('bessPriceArbitrageOverlay');
    if (rdnHidden && !rdnHidden.checked) {
      rdnHidden.checked = true;
      rdnHidden.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (rdnOverlay && !rdnOverlay.checked) {
      rdnOverlay.checked = true;
      rdnOverlay.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  // Update scenario tiles UI
  renderScenarioTiles();

  console.log(`🎯 BESS scenario set to: ${scenarioId} (${scenario.name})`);
  markUnsaved();
}

/**
 * Apply a single preset value to UI
 * @param {string} key - Setting key
 * @param {any} value - Value to set
 */
function applyScenarioPreset(key, value) {
  const el = document.getElementById(key);
  if (!el) return;

  if (el.type === 'checkbox') {
    el.checked = !!value;
  } else {
    el.value = value;
  }

  // Trigger change event for any dependent logic
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * Render scenario tiles in the UI
 * Called on topology/mode change and on page load
 */
function renderScenarioTiles() {
  const container = document.getElementById('bessScenarioTiles');
  if (!container) return;

  const topology = document.getElementById('bessTopology')?.value || 'pv_bess';
  const bessMode = document.getElementById('bessMode')?.value || 'off';

  // Hide entire section if bessMode is 'off'
  const scenarioSection = document.getElementById('bessScenarioSection');
  if (scenarioSection) {
    scenarioSection.style.display = bessMode === 'off' ? 'none' : 'block';
  }

  if (bessMode === 'off') {
    container.innerHTML = '';
    return;
  }

  const availableScenarios = getAvailableScenarios(topology, bessMode);

  // Load saved scenario ID from hidden input if currentBessScenarioId is not set
  if (!currentBessScenarioId) {
    const savedScenarioId = document.getElementById('bessScenarioId')?.value;
    if (savedScenarioId) {
      currentBessScenarioId = parseInt(savedScenarioId, 10);
    }
  }

  // Auto-select default scenario if none selected or current not available
  if (!currentBessScenarioId ||
      !availableScenarios.find(s => s.id === currentBessScenarioId)) {
    currentBessScenarioId = getDefaultScenarioId(topology);
  }

  // Build tiles HTML
  let tilesHTML = '';
  availableScenarios.forEach(scenario => {
    const isSelected = scenario.id === currentBessScenarioId;
    const isBeta = scenario.beta;
    const isRecommended = scenario.recommended;

    // Check if RDN data is actually loaded (not just checkbox enabled)
    const rdnDataLoaded = window._cachedPriceConfig?.rdnPrices?.available ||
                          (window.parent?.sharedData?.priceConfig?.rdnPrices?.available) ||
                          (() => { try { const c = localStorage.getItem('rdn_hourly_prices'); return c && JSON.parse(c).length > 100; } catch { return false; } })();
    const rdnMissing = scenario.requiresRdn && !rdnDataLoaded;

    const tileClass = [
      'scenario-tile',
      isSelected ? 'selected' : '',
      isBeta ? 'beta disabled' : '',
      rdnMissing ? 'rdn-missing' : '',
      isRecommended ? 'recommended' : ''
    ].filter(Boolean).join(' ');

    const tooltip = isBeta ? scenario.betaTooltip :
                   rdnMissing ? 'Wymaga załadowanych cen RDN (Spot) w sekcji Ceny' :
                   (scenario.infoTooltip || '');

    tilesHTML += `
      <div class="${tileClass}"
           onclick="setBessScenario(${scenario.id})"
           ${tooltip ? `title="${tooltip}"` : ''}>
        <div class="scenario-icon">${scenario.icon || '🔋'}</div>
        <div class="scenario-content">
          <div class="scenario-name">
            ${scenario.shortName || scenario.name}
            ${isRecommended ? '<span class="badge recommended">ZALECANY</span>' : ''}
            ${isBeta ? '<span class="badge beta">BETA</span>' : ''}
            ${rdnMissing ? '<span class="badge" style="background:#ff9800;color:#fff;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px">BRAK RDN</span>' : ''}
          </div>
          <div class="scenario-description">${scenario.description}</div>
        </div>
      </div>
    `;
  });

  container.innerHTML = tilesHTML;

  // Update hidden input
  const scenarioInput = document.getElementById('bessScenarioId');
  if (scenarioInput) scenarioInput.value = currentBessScenarioId || '';

  console.log(`📊 Rendered ${availableScenarios.length} scenario tiles for topology=${topology}, mode=${bessMode}`);
}

/**
 * Handle topology change - update scenarios and auto-select default
 * Extended version of setBessTopology
 */
const originalSetBessTopology = setBessTopology;
setBessTopology = function(topology) {
  // Call original function
  originalSetBessTopology(topology);

  // Re-render scenarios with new topology
  // Reset scenario selection to default for new topology
  currentBessScenarioId = null;
  renderScenarioTiles();
};

/**
 * Handle bessMode change - update scenarios visibility
 * Extended version of setBessMode
 */
const originalSetBessMode = setBessMode;
setBessMode = function(mode) {
  // Call original function
  originalSetBessMode(mode);

  // Re-render scenarios with new mode
  renderScenarioTiles();
};

/**
 * Show toast notification
 * @param {string} type - 'info' | 'success' | 'warning' | 'error'
 * @param {string} message - Message to display
 */
function showToast(type, message) {
  // Simple toast implementation - can be enhanced
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 12px 24px;
    background: ${type === 'info' ? '#2196f3' : type === 'success' ? '#4caf50' : type === 'warning' ? '#ff9800' : '#f44336'};
    color: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    z-index: 10000;
    font-size: 14px;
    animation: fadeIn 0.3s ease;
  `;

  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

/**
 * Get current scenario configuration for request building
 * @returns {object} - Scenario config with baseMode, presets, etc.
 */
function getCurrentScenarioConfig() {
  const topology = document.getElementById('bessTopology')?.value || 'pv_bess';
  const scenarioId = currentBessScenarioId || getDefaultScenarioId(topology);
  const scenario = BESS_SCENARIOS[scenarioId];

  if (!scenario) {
    return {
      scenarioId: null,
      baseMode: topology === 'pv_bess' ? 'stacked' : 'load_only',
      presets: {},
      requiredFields: []
    };
  }

  return {
    scenarioId: scenario.id,
    baseMode: getScenarioBaseMode(scenario, topology),
    presets: scenario.presets || {},
    requiredFields: scenario.requiredFields || [],
    feAnalysis: scenario.feAnalysis || false,
    reserveFraction: scenario.reserveFraction || 0.30,
    beta: scenario.beta || false
  };
}

// Make functions globally available
window.setBessScenario = setBessScenario;
window.renderScenarioTiles = renderScenarioTiles;
window.getAvailableScenarios = getAvailableScenarios;
window.getCurrentScenarioConfig = getCurrentScenarioConfig;
window.BESS_SCENARIOS = BESS_SCENARIOS;

// Marginal Cycle Cost UI toggle
function updateMarginalCycleCostUI() {
  const mode = document.getElementById('bessMarginalCycleCostMode')?.value || 'auto';
  const manualRow = document.getElementById('marginalCycleCostManualRow');
  if (manualRow) {
    manualRow.style.display = mode === 'manual' ? 'block' : 'none';
  }
}
window.updateMarginalCycleCostUI = updateMarginalCycleCostUI;

// Setup event listeners for auto-save and calculations
function setupEventListeners() {
  // Fixed charges inputs (without energyActive - now in ToU section)
  const fixedChargeInputs = ['distribution', 'qualityFee', 'ozeFee',
                              'cogenerationFee', 'capacityFee', 'exciseTax'];
  fixedChargeInputs.forEach(id => {
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

// Calculate and display total fixed charges (without active energy)
// Active energy rates are defined separately in ToU tariff section
function updateTotalEnergyPrice() {
  // Fixed charges (same for all hours, except capacity fee only 7-22 on workdays)
  const distribution = parseFloat(document.getElementById('distribution')?.value || 0);
  const qualityFee = parseFloat(document.getElementById('qualityFee')?.value || 0);
  const ozeFee = parseFloat(document.getElementById('ozeFee')?.value || 0);
  const cogenerationFee = parseFloat(document.getElementById('cogenerationFee')?.value || 0);
  const capacityFee = parseFloat(document.getElementById('capacityFee')?.value || 0);
  const exciseTax = parseFloat(document.getElementById('exciseTax')?.value || 0);

  // Total fixed charges (all components)
  const totalFixed = distribution + qualityFee + ozeFee + cogenerationFee + capacityFee + exciseTax;

  // Update the new totalFixedCharges field
  const totalFixedInput = document.getElementById('totalFixedCharges');
  if (totalFixedInput) {
    totalFixedInput.value = totalFixed.toFixed(0);
  }

  // Keep legacy totalEnergyPrice for backwards compatibility
  const totalInput = document.getElementById('totalEnergyPrice');
  if (totalInput) {
    totalInput.value = totalFixed.toFixed(0);
  }

  // Also set energyActive hidden field to 0 (now defined in ToU section)
  const energyActiveInput = document.getElementById('energyActive');
  if (energyActiveInput) {
    energyActiveInput.value = 0;
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

      // Migration: old CAPEX defaults (1500/300) → realistic 2025 LFP values (900/200)
      if (config.bessCapexPerKwh >= 1400) {
        console.log(`⬆️ CAPEX migration: ${config.bessCapexPerKwh}→${DEFAULT_CONFIG.bessCapexPerKwh} PLN/kWh`);
        config.bessCapexPerKwh = DEFAULT_CONFIG.bessCapexPerKwh;
      }
      if (config.bessCapexPerKw >= 280) {
        console.log(`⬆️ CAPEX migration: ${config.bessCapexPerKw}→${DEFAULT_CONFIG.bessCapexPerKw} PLN/kW`);
        config.bessCapexPerKw = DEFAULT_CONFIG.bessCapexPerKw;
      }
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
  // Backward compat: if no zonal distribution, use flat distribution for all zones
  if (config.distribution && !config.distributionPeak) {
    config.distributionPeak = config.distribution;
    config.distributionDay = config.distribution;
    config.distributionNight = config.distribution;
    config.distributionValley = config.distribution;
  }

  // Simple fields (inputs with numeric or text values)
  // Note: energyActive removed - now defined per zone in ToU section
  const simpleFields = [
    'distribution', 'distributionPeak', 'distributionDay', 'distributionNight', 'distributionValley',
    'qualityFee', 'ozeFee', 'cogenerationFee',
    'capacityFee', 'exciseTax', 'opexPerKwp', 'eaasOM', 'insuranceRate', 'landLeasePerKwp',
    'discountRate', 'pvDegradationYear1', 'degradationRate', 'analysisPeriod', 'inflationRate',
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
    'bessRoundtripEfficiency', 'bessSocMin', 'bessSocMax', 'bessDegradationYear1', 'bessDegradationPctPerYear', 'bessHouseLoadKwPerMwh',
    // BESS PRO parameters
    'bessProMinPowerKw', 'bessProMaxPowerKw', 'bessProMinEnergyKwh', 'bessProMaxEnergyKwh',
    'bessProDurationMin', 'bessProDurationMax', 'bessProTypicalDays', 'bessProExportPenalty'
  ];

  // Select fields
  const selectFields = [
    'eaasCurrency', 'eaasIndexation', 'irrDriver',
    'depreciationMethod', 'debtAmortization', 'indexationFrequency',
    'weatherDataSource',
    // Pxx select fields
    'pxxSource', 'pvgisRadDatabase', 'pvgisPvTechChoice', 'pvgisMountingPlace',
    // BESS
    'bessDuration',
    // BESS PRO
    'bessProSolver', 'bessProObjective', 'bessProTimeResolution'
  ];

  // IRR mode checkbox
  const useInflationEl = document.getElementById('useInflation');
  if (useInflationEl) {
    useInflationEl.checked = config.useInflation || config.irrMode === 'nominal' || false;
  }

  // BESS topology (pv_bess vs bess_only)
  const bessTopologyEl = document.getElementById('bessTopology');
  if (bessTopologyEl) {
    bessTopologyEl.value = config.bessTopology || 'pv_bess';
    // Update UI for topology selection
    setBessTopology(config.bessTopology || 'pv_bess');
  }

  // BESS mode - just set hidden input value here, will call setBessMode() at the end
  // to ensure all BESS fields (including bessScenarioId) are set first
  const bessModeEl = document.getElementById('bessMode');
  let bessMode = config.bessMode || 'pro';  // Default to PRO (light deprecated)
  if (!config.bessMode && config.bessEnabled) {
    bessMode = 'pro';  // Legacy: bessEnabled=true now means PRO mode
  }
  // Force PRO if light was saved
  if (bessMode === 'light') {
    bessMode = 'pro';
  }
  if (bessModeEl) bessModeEl.value = bessMode;

  // BESS PRO zero-export checkbox
  const bessProZeroExportEl = document.getElementById('bessProZeroExport');
  if (bessProZeroExportEl) {
    bessProZeroExportEl.checked = config.bessProZeroExport !== false;  // Default true
  }

  // BESS Physical Constraints (grid connection & EFC limit)
  const bessGridConnectionKwEl = document.getElementById('bessGridConnectionKw');
  if (bessGridConnectionKwEl && config.bessGridConnectionKw) {
    bessGridConnectionKwEl.value = config.bessGridConnectionKw;
  }
  const bessMaxEfcPerYearEl = document.getElementById('bessMaxEfcPerYear');
  if (bessMaxEfcPerYearEl && config.bessMaxEfcPerYear) {
    bessMaxEfcPerYearEl.value = config.bessMaxEfcPerYear;
  }

  // BESS Optimization Objective (new visible select)
  const bessOptObjEl = document.getElementById('bessOptimizationObjective');
  if (bessOptObjEl) {
    bessOptObjEl.value = config.bessProObjective || 'npv';
  }
  // Max payback constraint
  const bessMaxPaybackEl = document.getElementById('bessMaxPaybackYears');
  if (bessMaxPaybackEl && config.bessMaxPaybackYears) {
    bessMaxPaybackEl.value = config.bessMaxPaybackYears;
  }

  // Marginal cycle cost mode
  const mccModeEl = document.getElementById('bessMarginalCycleCostMode');
  if (mccModeEl && config.bessMarginalCycleCostMode) {
    mccModeEl.value = config.bessMarginalCycleCostMode;
  }
  const mccManualEl = document.getElementById('bessMarginalCycleCostManual');
  if (mccManualEl && config.bessMarginalCycleCostManual) {
    mccManualEl.value = config.bessMarginalCycleCostManual;
  }
  if (typeof updateMarginalCycleCostUI === 'function') updateMarginalCycleCostUI();

  // BESS Peak Shaving checkbox and fields
  const bessPeakShavingEnabledEl = document.getElementById('bessPeakShavingEnabled');
  if (bessPeakShavingEnabledEl) {
    bessPeakShavingEnabledEl.checked = config.bessPeakShavingEnabled ?? false;
  }
  const bessPeakShavingModeEl = document.getElementById('bessPeakShavingMode');
  if (bessPeakShavingModeEl) {
    bessPeakShavingModeEl.value = config.bessPeakShavingMode || 'auto';
  }
  const bessPeakShavingTargetKwEl = document.getElementById('bessPeakShavingTargetKw');
  if (bessPeakShavingTargetKwEl) {
    bessPeakShavingTargetKwEl.value = config.bessPeakShavingTargetKw ?? 0;
  }
  const bessPeakShavingPctReductionEl = document.getElementById('bessPeakShavingPctReduction');
  if (bessPeakShavingPctReductionEl) {
    bessPeakShavingPctReductionEl.value = config.bessPeakShavingPctReduction ?? 15;
  }
  const bessPowerChargePlnPerKwMonthEl = document.getElementById('bessPowerChargePlnPerKwMonth');
  if (bessPowerChargePlnPerKwMonthEl) {
    bessPowerChargePlnPerKwMonthEl.value = config.bessPowerChargePlnPerKwMonth ?? 50;
  }

  // BESS OSD Tariff Arbitrage (ToU) checkbox and fields
  const bessOsdArbitrageEnabledEl = document.getElementById('bessOsdArbitrageEnabled');
  if (bessOsdArbitrageEnabledEl) {
    bessOsdArbitrageEnabledEl.checked = config.bessOsdArbitrageEnabled ?? false;
    // Sync overlay checkbox in scenario section
    const osdOverlay = document.getElementById('bessOsdArbitrageOverlay');
    if (osdOverlay) osdOverlay.checked = bessOsdArbitrageEnabledEl.checked;
  }
  const bessOsdOperatorEl = document.getElementById('bessOsdOperator');
  if (bessOsdOperatorEl) {
    bessOsdOperatorEl.value = config.bessOsdOperator || 'pge';
  }
  const bessOsdTariffGroupEl = document.getElementById('bessOsdTariffGroup');
  if (bessOsdTariffGroupEl) {
    bessOsdTariffGroupEl.value = config.bessOsdTariffGroup || 'C12a';
  }
  const bessOsdPeakRateEl = document.getElementById('bessOsdPeakRate');
  if (bessOsdPeakRateEl) {
    bessOsdPeakRateEl.value = config.bessOsdPeakRate ?? 0.75;
  }
  const bessOsdOffPeakRateEl = document.getElementById('bessOsdOffPeakRate');
  if (bessOsdOffPeakRateEl) {
    bessOsdOffPeakRateEl.value = config.bessOsdOffPeakRate ?? 0.45;
  }
  const bessOsdMinSpreadEl = document.getElementById('bessOsdMinSpread');
  if (bessOsdMinSpreadEl) {
    bessOsdMinSpreadEl.value = config.bessOsdMinSpread ?? 0.15;
  }

  // OSD Operator + Tariff Group selector restore
  // Must populate dropdown options BEFORE setting value, otherwise value is silently ignored
  const savedOsdOperator = config.osdOperator || '';
  const savedOsdTariffGroup = config.osdTariffGroup || '';
  if (savedOsdOperator) {
    populateOsdOperatorDropdown().then(() => {
      const opSelect = document.getElementById('osdOperator');
      if (opSelect) {
        opSelect.value = savedOsdOperator;
        onOsdOperatorChange().then(() => {
          const tgSelect = document.getElementById('osdTariffGroup');
          if (tgSelect && savedOsdTariffGroup) {
            tgSelect.value = savedOsdTariffGroup;
            // Don't trigger onOsdTariffGroupChange — values already loaded from saved config
          }
        });
      }
    });
  }

  // Hybrid Monthly Pricing
  const pricingModeEl = document.getElementById('pricingMode');
  if (pricingModeEl) {
    pricingModeEl.value = config.pricingMode || 'single';
    toggleHybridMonthlySection();
  }
  if (config.monthlyPriceSources) {
    applyMonthlyPriceSources(config.monthlyPriceSources);
  }

  // BESS RDN Price Arbitrage (Spot) checkbox and fields
  const bessPriceArbitrageEnabledEl = document.getElementById('bessPriceArbitrageEnabled');
  if (bessPriceArbitrageEnabledEl) {
    bessPriceArbitrageEnabledEl.checked = config.bessPriceArbitrageEnabled ?? false;
    // Sync overlay checkbox in scenario section
    const rdnOverlay = document.getElementById('bessPriceArbitrageOverlay');
    if (rdnOverlay) rdnOverlay.checked = bessPriceArbitrageEnabledEl.checked;
  }
  const bessPriceArbitrageSourceEl = document.getElementById('bessPriceArbitrageSource');
  if (bessPriceArbitrageSourceEl) {
    bessPriceArbitrageSourceEl.value = config.bessPriceArbitrageSource || 'manual';
  }
  const bessPriceArbitrageBuyThresholdEl = document.getElementById('bessPriceArbitrageBuyThreshold');
  if (bessPriceArbitrageBuyThresholdEl) {
    bessPriceArbitrageBuyThresholdEl.value = config.bessPriceArbitrageBuyThreshold ?? 300;
  }
  const bessPriceArbitrageSellThresholdEl = document.getElementById('bessPriceArbitrageSellThreshold');
  if (bessPriceArbitrageSellThresholdEl) {
    bessPriceArbitrageSellThresholdEl.value = config.bessPriceArbitrageSellThreshold ?? 600;
  }
  const bessPriceArbitrageSpreadEl = document.getElementById('bessPriceArbitrageSpread');
  if (bessPriceArbitrageSpreadEl) {
    bessPriceArbitrageSpreadEl.value = config.bessPriceArbitrageSpread ?? 100;
  }
  const bessRdnPriceFlatEl = document.getElementById('bessRdnPriceFlat');
  if (bessRdnPriceFlatEl) {
    bessRdnPriceFlatEl.value = config.bessRdnPriceFlat ?? 500;
  }
  const bessRdnPriceMultiplierEl = document.getElementById('bessRdnPriceMultiplier');
  if (bessRdnPriceMultiplierEl) {
    bessRdnPriceMultiplierEl.value = config.bessRdnPriceMultiplier ?? 1.0;
  }

  // Legacy BESS enabled field (for backwards compat)
  const bessEnabledEl = document.getElementById('bessEnabled');
  if (bessEnabledEl) {
    bessEnabledEl.value = config.bessMode !== 'off' ? 'true' : 'false';
  }

  // Ancillary Services
  const ancillaryEnabledEl = document.getElementById('ancillaryServicesEnabled');
  if (ancillaryEnabledEl) {
    ancillaryEnabledEl.checked = config.ancillaryServicesEnabled ?? false;
  }
  const ancCheckboxes = ['ancSvcAfrrUp', 'ancSvcAfrrDown', 'ancSvcMfrrUp', 'ancSvcFcr', 'ancSvcCapMarket'];
  ancCheckboxes.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.checked = config[id] ?? DEFAULT_CONFIG[id];
  });
  const ancSimple = ['ancillaryAggregatorMarginPct', 'ancillaryAfrrPrice', 'ancillaryMfrrPrice',
    'ancillaryFcrPrice', 'ancillaryCapMarketPrice', 'ancillaryKwd', 'ancillaryMinAvailability',
    'ancillaryMaxCapacityShare'];
  ancSimple.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = config[id] ?? DEFAULT_CONFIG[id];
  });
  const ancSelects = ['ancillaryMarketYear', 'ancillaryOptimizeMode'];
  ancSelects.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = config[id] ?? DEFAULT_CONFIG[id];
  });
  // Toggle ancillary detail section visibility
  toggleAncillaryDetail();

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

  // Sync degradation params from LIGHT to PRO (LIGHT is the master)
  // This ensures PRO fields show the same values as LIGHT after loading
  syncDegradationParams('light');

  // BESS Scenarios (MVP v3.17)
  // Load saved scenario ID
  if (config.bessScenarioId) {
    currentBessScenarioId = config.bessScenarioId;
  }
  const bessScenarioIdEl = document.getElementById('bessScenarioId');
  if (bessScenarioIdEl) {
    bessScenarioIdEl.value = config.bessScenarioId || '';
  }

  // Capacity Fee Overlay checkbox
  const bessCapacityFeeOverlayEl = document.getElementById('bessCapacityFeeOverlay');
  if (bessCapacityFeeOverlayEl) {
    bessCapacityFeeOverlayEl.checked = config.bessCapacityFeeOverlay ?? false;
  }

  // NOW call setBessMode() to update UI (status indicators, sections visibility)
  // This also calls renderScenarioTiles() which needs bessScenarioId to be already set
  setBessMode(bessMode);

  // Apply Tariff Configuration (ToU zones and rates)
  if (config.tariffConfig) {
    const tc = config.tariffConfig;
    // Tariff type
    const tariffTypeEl = document.getElementById('tariffType');
    if (tariffTypeEl) tariffTypeEl.value = tc.type || 'two_zone';
    // Tariff name
    const tariffNameEl = document.getElementById('tariffName');
    if (tariffNameEl) tariffNameEl.value = tc.name || 'C12a';
    // Flat rate
    const tariffFlatRateEl = document.getElementById('tariffFlatRate');
    if (tariffFlatRateEl) tariffFlatRateEl.value = tc.flatRate || 750;
    // Two-zone rates
    if (tc.twoZone) {
      const tariffDayRateEl = document.getElementById('tariffDayRate');
      if (tariffDayRateEl) tariffDayRateEl.value = tc.twoZone.dayRate || 850;
      const tariffNightRateEl = document.getElementById('tariffNightRate');
      if (tariffNightRateEl) tariffNightRateEl.value = tc.twoZone.nightRate || 450;
      if (tc.twoZone.weekday) {
        const dayStartWeekdayEl = document.getElementById('tariffDayStartWeekday');
        if (dayStartWeekdayEl) dayStartWeekdayEl.value = tc.twoZone.weekday.start || 6;
        const dayEndWeekdayEl = document.getElementById('tariffDayEndWeekday');
        if (dayEndWeekdayEl) dayEndWeekdayEl.value = tc.twoZone.weekday.end || 22;
      }
      if (tc.twoZone.weekend) {
        const dayStartWeekendEl = document.getElementById('tariffDayStartWeekend');
        if (dayStartWeekendEl) dayStartWeekendEl.value = tc.twoZone.weekend.start || 6;
        const dayEndWeekendEl = document.getElementById('tariffDayEndWeekend');
        if (dayEndWeekendEl) dayEndWeekendEl.value = tc.twoZone.weekend.end || 13;
      }
    }
    // Three-zone rates
    if (tc.threeZone) {
      const tariffPeakRateEl = document.getElementById('tariffPeakRate');
      if (tariffPeakRateEl) tariffPeakRateEl.value = tc.threeZone.peakRate || 950;
      const tariffPartialRateEl = document.getElementById('tariffPartialRate');
      if (tariffPartialRateEl) tariffPartialRateEl.value = tc.threeZone.partialRate || 700;
      const tariffOffPeakRateEl = document.getElementById('tariffOffPeakRate');
      if (tariffOffPeakRateEl) tariffOffPeakRateEl.value = tc.threeZone.offPeakRate || 400;
      if (tc.threeZone.peak1) {
        const peakStartEl = document.getElementById('tariffPeakStart');
        if (peakStartEl) peakStartEl.value = tc.threeZone.peak1.start || 7;
        const peakEndEl = document.getElementById('tariffPeakEnd');
        if (peakEndEl) peakEndEl.value = tc.threeZone.peak1.end || 13;
      }
      if (tc.threeZone.peak2) {
        const peakStart2El = document.getElementById('tariffPeakStart2');
        if (peakStart2El) peakStart2El.value = tc.threeZone.peak2.start || 17;
        const peakEnd2El = document.getElementById('tariffPeakEnd2');
        if (peakEnd2El) peakEnd2El.value = tc.threeZone.peak2.end || 21;
      }
      if (tc.threeZone.partial) {
        const partialStartEl = document.getElementById('tariffPartialStart');
        if (partialStartEl) partialStartEl.value = tc.threeZone.partial.start || 13;
        const partialEndEl = document.getElementById('tariffPartialEnd');
        if (partialEndEl) partialEndEl.value = tc.threeZone.partial.end || 17;
      }
    }
    // Four-zone rates
    if (tc.fourZone) {
      setValueById('tariffFourPeakRate', tc.fourZone.peakRate || 950);
      setValueById('tariffFourDayRate', tc.fourZone.dayRate || 700);
      setValueById('tariffFourOffPeakRate', tc.fourZone.offPeakRate || 400);
      setValueById('tariffFourValleyRate', tc.fourZone.valleyRate || 200);
      if (tc.fourZone.peak1) {
        setValueById('tariffFourPeakStart', tc.fourZone.peak1.start || 7);
        setValueById('tariffFourPeakEnd', tc.fourZone.peak1.end || 13);
      }
      if (tc.fourZone.peak2) {
        setValueById('tariffFourPeakStart2', tc.fourZone.peak2.start || 16);
        setValueById('tariffFourPeakEnd2', tc.fourZone.peak2.end || 21);
      }
      if (tc.fourZone.valley) {
        setValueById('tariffFourValleyStart', tc.fourZone.valley.start || 1);
        setValueById('tariffFourValleyEnd', tc.fourZone.valley.end || 5);
      }
    }
    // Update tariff UI visibility
    if (typeof onTariffTypeChange === 'function') {
      onTariffTypeChange();
    }
    console.log('✅ Tariff config applied from import:', tc);
  }

  // Apply Distribution Config (OSD time windows — separate from energy ToU)
  if (config.distributionConfig) {
    const dc = config.distributionConfig;
    const distTypeEl = document.getElementById('distTariffType');
    if (distTypeEl) distTypeEl.value = dc.type || 'three_zone';
    if (dc.twoZone) {
      if (dc.twoZone.weekday) {
        setValueById('distDayStartWeekday', dc.twoZone.weekday.start);
        setValueById('distDayEndWeekday', dc.twoZone.weekday.end);
      }
      if (dc.twoZone.weekend) {
        setValueById('distDayStartWeekend', dc.twoZone.weekend.start);
        setValueById('distDayEndWeekend', dc.twoZone.weekend.end);
      }
    }
    if (dc.threeZone) {
      if (dc.threeZone.peak1) {
        setValueById('distPeak1Start', dc.threeZone.peak1.start);
        setValueById('distPeak1End', dc.threeZone.peak1.end);
      }
      if (dc.threeZone.peak2) {
        setValueById('distPeak2Start', dc.threeZone.peak2.start);
        setValueById('distPeak2End', dc.threeZone.peak2.end);
      }
      const woeEl = document.getElementById('distWeekendOffPeak');
      if (woeEl) woeEl.checked = dc.threeZone.weekendOffPeak !== false;
    }
    if (dc.fourZone) {
      if (dc.fourZone.peak1) {
        setValueById('distFourPeak1Start', dc.fourZone.peak1.start);
        setValueById('distFourPeak1End', dc.fourZone.peak1.end);
      }
      if (dc.fourZone.peak2) {
        setValueById('distFourPeak2Start', dc.fourZone.peak2.start);
        setValueById('distFourPeak2End', dc.fourZone.peak2.end);
      }
      if (dc.fourZone.valley) {
        setValueById('distValleyStart', dc.fourZone.valley.start);
        setValueById('distValleyEnd', dc.fourZone.valley.end);
      }
    }
    onDistTariffTypeChange();
    console.log('✅ Distribution config applied:', dc);
  }

  // Apply Fixed Monthly Fees Configuration
  if (config.fixedMonthlyFees) {
    const fmf = config.fixedMonthlyFees;
    const setVal = (id, key) => { const el = document.getElementById(id); if (el && fmf[key] !== undefined) el.value = fmf[key]; };
    setVal('contractedPowerKw', 'contractedPowerKw');
    setVal('distFixedRatePerKw', 'distFixedRatePerKwMonth');
    setVal('osdSubscriptionFee', 'osdSubscriptionFeeMonth');
    setVal('transitionFee', 'transitionFeeMonth');
    setVal('supplierTradeFee', 'supplierTradeFeeMonth');
    updateFixedMonthlyTotal();
    console.log('✅ Fixed monthly fees applied from import:', fmf);
  }

  // Apply Capacity Fee Configuration (opłata mocowa)
  if (config.capacityFeeConfig) {
    const cfc = config.capacityFeeConfig;
    // Save to localStorage for capacity fee functions to read
    localStorage.setItem('pv_settings', JSON.stringify({
      ...JSON.parse(localStorage.getItem('pv_settings') || '{}'),
      capacityFeeConfig: cfc
    }));
    // Re-render capacity fee chart
    if (typeof renderCapacityFeeChart === 'function') {
      renderCapacityFeeChart();
    }
    console.log('✅ Capacity fee config applied from import:', cfc);
  }

  // Apply ESG parameters
  const esgFields = [
    'esgGridEmissionProvider', 'esgGridEmissionFactor', 'esgGridEmissionYear', 'esgGridEmissionSource',
    'esgEmbodiedCarbonCrystalline', 'esgEmbodiedCarbonCIS', 'esgEmbodiedCarbonCdTe', 'esgEmbodiedCarbonSource',
    'esgPvTechnology', 'esgTaxonomyActivityCode', 'esgReportingMethod', 'esgComponentCompliance',
    'electricitymapsApiKey', 'electricitymapsZone'
  ];
  esgFields.forEach(field => {
    if (config[field] !== undefined) {
      const el = document.getElementById(field);
      if (el) el.value = config[field];
    }
  });
  // ESG checkbox
  const esgTaxonomyEl = document.getElementById('esgTaxonomyAligned');
  if (esgTaxonomyEl && config.esgTaxonomyAligned !== undefined) {
    esgTaxonomyEl.checked = config.esgTaxonomyAligned;
  }

  // Apply RDN Dynamic Pricing Configuration
  if (config.rdnPricingConfig) {
    const rdn = config.rdnPricingConfig;
    const rdnCheckbox = document.getElementById('rdnPricingEnabled');
    const rdnPanel = document.getElementById('rdnPricingPanel');
    if (rdnCheckbox) rdnCheckbox.checked = rdn.enabled || false;
    if (rdnPanel) rdnPanel.style.display = rdn.enabled ? 'block' : 'none';
    if (rdn.enabled && rdn.scenarioId) {
      loadSavedRdnScenarios().then(() => {
        const selectEl = document.getElementById('rdnScenarioSelect');
        if (selectEl) {
          selectEl.value = rdn.scenarioId;
          selectRdnScenario(rdn.scenarioId);
        }
      });
    }
    console.log('RDN pricing config applied:', rdn);
  }
}

// Get current settings from UI
function getCurrentSettings() {
  const settings = {
    // Energy Tariff
    energyActive: parseFloat(document.getElementById('energyActive')?.value || DEFAULT_CONFIG.energyActive),
    osdOperator: document.getElementById('osdOperator')?.value || '',
    osdTariffGroup: document.getElementById('osdTariffGroup')?.value || '',
    distribution: parseFloat(document.getElementById('distribution')?.value || DEFAULT_CONFIG.distribution),
    distributionPeak: parseFloat(document.getElementById('distributionPeak')?.value || DEFAULT_CONFIG.distributionPeak),
    distributionDay: parseFloat(document.getElementById('distributionDay')?.value || DEFAULT_CONFIG.distributionDay),
    distributionNight: parseFloat(document.getElementById('distributionNight')?.value || DEFAULT_CONFIG.distributionNight),
    distributionValley: parseFloat(document.getElementById('distributionValley')?.value || DEFAULT_CONFIG.distributionValley),
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
    // EaaS duration capped at 25 years (data contract maximum)
    eaasDuration: Math.min(25, parseInt(document.getElementById('eaasDuration')?.value || DEFAULT_CONFIG.eaasDuration)),
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

    // BESS - Battery Energy Storage System
    bessTopology: document.getElementById('bessTopology')?.value || 'pv_bess',  // pv_bess or bess_only
    bessMode: document.getElementById('bessMode')?.value || DEFAULT_CONFIG.bessMode,
    bessEnabled: document.getElementById('bessMode')?.value !== 'off',  // Legacy compatibility
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
    bessHouseLoadKwPerMwh: parseFloat(document.getElementById('bessHouseLoadKwPerMwh')?.value || DEFAULT_CONFIG.bessHouseLoadKwPerMwh),

    // BESS PRO - Advanced LP/MIP Optimization
    bessProMinPowerKw: parseFloat(document.getElementById('bessProMinPowerKw')?.value || DEFAULT_CONFIG.bessProMinPowerKw),
    bessProMaxPowerKw: parseFloat(document.getElementById('bessProMaxPowerKw')?.value || DEFAULT_CONFIG.bessProMaxPowerKw),
    bessProMinEnergyKwh: parseFloat(document.getElementById('bessProMinEnergyKwh')?.value || DEFAULT_CONFIG.bessProMinEnergyKwh),
    bessProMaxEnergyKwh: parseFloat(document.getElementById('bessProMaxEnergyKwh')?.value || DEFAULT_CONFIG.bessProMaxEnergyKwh),
    bessProDurationMin: parseFloat(document.getElementById('bessProDurationMin')?.value || DEFAULT_CONFIG.bessProDurationMin),
    bessProDurationMax: parseFloat(document.getElementById('bessProDurationMax')?.value || DEFAULT_CONFIG.bessProDurationMax),
    bessProSolver: document.getElementById('bessProSolver')?.value || DEFAULT_CONFIG.bessProSolver,
    bessProObjective: document.getElementById('bessOptimizationObjective')?.value || document.getElementById('bessProObjective')?.value || DEFAULT_CONFIG.bessProObjective,
    bessMaxPaybackYears: parseFloat(document.getElementById('bessMaxPaybackYears')?.value) || null,
    bessMarginalCycleCostMode: document.getElementById('bessMarginalCycleCostMode')?.value || 'auto',
    bessMarginalCycleCostManual: parseFloat(document.getElementById('bessMarginalCycleCostManual')?.value) || 0.125,
    bessProTimeResolution: document.getElementById('bessProTimeResolution')?.value || DEFAULT_CONFIG.bessProTimeResolution,
    bessProTypicalDays: parseInt(document.getElementById('bessProTypicalDays')?.value || DEFAULT_CONFIG.bessProTypicalDays),
    bessProZeroExport: document.getElementById('bessProZeroExport')?.checked ?? DEFAULT_CONFIG.bessProZeroExport,
    bessProExportPenalty: parseFloat(document.getElementById('bessProExportPenalty')?.value || DEFAULT_CONFIG.bessProExportPenalty),

    // BESS Peak Shaving
    bessPeakShavingEnabled: document.getElementById('bessPeakShavingEnabled')?.checked ?? DEFAULT_CONFIG.bessPeakShavingEnabled,
    bessPeakShavingMode: document.getElementById('bessPeakShavingMode')?.value || DEFAULT_CONFIG.bessPeakShavingMode,
    bessPeakShavingTargetKw: parseFloat(document.getElementById('bessPeakShavingTargetKw')?.value || DEFAULT_CONFIG.bessPeakShavingTargetKw),
    bessPeakShavingPctReduction: parseFloat(document.getElementById('bessPeakShavingPctReduction')?.value || DEFAULT_CONFIG.bessPeakShavingPctReduction),
    bessPowerChargePlnPerKwMonth: parseFloat(document.getElementById('bessPowerChargePlnPerKwMonth')?.value || DEFAULT_CONFIG.bessPowerChargePlnPerKwMonth),

    // BESS OSD Tariff Arbitrage (ToU)
    bessOsdArbitrageEnabled: document.getElementById('bessOsdArbitrageEnabled')?.checked ?? DEFAULT_CONFIG.bessOsdArbitrageEnabled,
    bessOsdOperator: document.getElementById('bessOsdOperator')?.value || DEFAULT_CONFIG.bessOsdOperator,
    bessOsdTariffGroup: document.getElementById('bessOsdTariffGroup')?.value || DEFAULT_CONFIG.bessOsdTariffGroup,
    bessOsdPeakRate: parseFloat(document.getElementById('bessOsdPeakRate')?.value || DEFAULT_CONFIG.bessOsdPeakRate),
    bessOsdOffPeakRate: parseFloat(document.getElementById('bessOsdOffPeakRate')?.value || DEFAULT_CONFIG.bessOsdOffPeakRate),
    bessOsdMinSpread: parseFloat(document.getElementById('bessOsdMinSpread')?.value || DEFAULT_CONFIG.bessOsdMinSpread),

    // BESS Physical Constraints (grid connection & cycle limits)
    bessGridConnectionKw: parseFloat(document.getElementById('bessGridConnectionKw')?.value) || null,
    bessMaxEfcPerYear: parseFloat(document.getElementById('bessMaxEfcPerYear')?.value) || null,

    // Hybrid Monthly Pricing
    pricingMode: document.getElementById('pricingMode')?.value || DEFAULT_CONFIG.pricingMode,
    monthlyPriceSources: collectMonthlyPriceSources(),

    // BESS RDN Price Arbitrage (Spot)
    bessPriceArbitrageEnabled: document.getElementById('bessPriceArbitrageEnabled')?.checked ?? DEFAULT_CONFIG.bessPriceArbitrageEnabled,
    bessPriceArbitrageSource: document.getElementById('bessPriceArbitrageSource')?.value || DEFAULT_CONFIG.bessPriceArbitrageSource,
    bessPriceArbitrageBuyThreshold: parseFloat(document.getElementById('bessPriceArbitrageBuyThreshold')?.value || DEFAULT_CONFIG.bessPriceArbitrageBuyThreshold),
    bessPriceArbitrageSellThreshold: parseFloat(document.getElementById('bessPriceArbitrageSellThreshold')?.value || DEFAULT_CONFIG.bessPriceArbitrageSellThreshold),
    bessPriceArbitrageSpread: parseFloat(document.getElementById('bessPriceArbitrageSpread')?.value || DEFAULT_CONFIG.bessPriceArbitrageSpread),
    bessRdnPriceFlat: parseFloat(document.getElementById('bessRdnPriceFlat')?.value || DEFAULT_CONFIG.bessRdnPriceFlat),
    bessRdnPriceMultiplier: parseFloat(document.getElementById('bessRdnPriceMultiplier')?.value || DEFAULT_CONFIG.bessRdnPriceMultiplier),

    // BESS Scenarios (MVP v3.17)
    bessScenarioId: parseInt(document.getElementById('bessScenarioId')?.value) || currentBessScenarioId || null,
    bessCapacityFeeOverlay: document.getElementById('bessCapacityFeeOverlay')?.checked ?? DEFAULT_CONFIG.bessCapacityFeeOverlay,

    // Ancillary Services (Revenue Stacking)
    ancillaryServicesEnabled: document.getElementById('ancillaryServicesEnabled')?.checked ?? DEFAULT_CONFIG.ancillaryServicesEnabled,
    ancSvcAfrrUp: document.getElementById('ancSvcAfrrUp')?.checked ?? DEFAULT_CONFIG.ancSvcAfrrUp,
    ancSvcAfrrDown: document.getElementById('ancSvcAfrrDown')?.checked ?? DEFAULT_CONFIG.ancSvcAfrrDown,
    ancSvcMfrrUp: document.getElementById('ancSvcMfrrUp')?.checked ?? DEFAULT_CONFIG.ancSvcMfrrUp,
    ancSvcFcr: document.getElementById('ancSvcFcr')?.checked ?? DEFAULT_CONFIG.ancSvcFcr,
    ancSvcCapMarket: document.getElementById('ancSvcCapMarket')?.checked ?? DEFAULT_CONFIG.ancSvcCapMarket,
    ancillaryMarketYear: parseInt(document.getElementById('ancillaryMarketYear')?.value || DEFAULT_CONFIG.ancillaryMarketYear),
    ancillaryAggregatorMarginPct: parseFloat(document.getElementById('ancillaryAggregatorMarginPct')?.value || DEFAULT_CONFIG.ancillaryAggregatorMarginPct),
    ancillaryAfrrPrice: parseFloat(document.getElementById('ancillaryAfrrPrice')?.value || DEFAULT_CONFIG.ancillaryAfrrPrice),
    ancillaryMfrrPrice: parseFloat(document.getElementById('ancillaryMfrrPrice')?.value || DEFAULT_CONFIG.ancillaryMfrrPrice),
    ancillaryFcrPrice: parseFloat(document.getElementById('ancillaryFcrPrice')?.value || DEFAULT_CONFIG.ancillaryFcrPrice),
    ancillaryCapMarketPrice: parseFloat(document.getElementById('ancillaryCapMarketPrice')?.value || DEFAULT_CONFIG.ancillaryCapMarketPrice),
    ancillaryKwd: parseFloat(document.getElementById('ancillaryKwd')?.value || DEFAULT_CONFIG.ancillaryKwd),
    ancillaryMinAvailability: parseFloat(document.getElementById('ancillaryMinAvailability')?.value || DEFAULT_CONFIG.ancillaryMinAvailability),
    ancillaryMaxCapacityShare: parseFloat(document.getElementById('ancillaryMaxCapacityShare')?.value || DEFAULT_CONFIG.ancillaryMaxCapacityShare),
    ancillaryOptimizeMode: document.getElementById('ancillaryOptimizeMode')?.value || DEFAULT_CONFIG.ancillaryOptimizeMode,

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
    electricitymapsZone: document.getElementById('electricitymapsZone')?.value || DEFAULT_CONFIG.electricitymapsZone,

    // Capacity Fee (Opłata Mocowa) Configuration
    capacityFeeConfig: getCapacityFeeConfig(),

    // Fixed Monthly Fees Configuration
    fixedMonthlyFees: getFixedMonthlyFeesConfig(),

    // Distribution Time Windows (OSD tariff zones — separate from energy ToU)
    distributionConfig: getDistributionConfig(),

    // Time-of-Use Tariff Configuration
    tariffConfig: getTariffConfig(),

    // RDN Dynamic Pricing Configuration
    rdnPricingConfig: getRdnPricingConfig()
  };

  // Calculate total fixed charges (without energia czynna - now in ToU section)
  settings.totalFixedCharges = settings.distribution +
    settings.qualityFee + settings.ozeFee + settings.cogenerationFee +
    settings.capacityFee + settings.exciseTax;

  // Legacy totalEnergyPrice for backwards compatibility (now equals fixed charges only)
  settings.totalEnergyPrice = settings.totalFixedCharges;
  settings.energyActive = 0; // DEPRECATED: energia czynna is now per-zone in ToU

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

// Collect monthly price sources from UI dropdowns
function collectMonthlyPriceSources() {
  const sources = {};
  for (let m = 1; m <= 12; m++) {
    const el = document.getElementById(`monthPriceSource_${m}`);
    sources[m] = el ? el.value : (DEFAULT_CONFIG.monthlyPriceSources?.[m] || 'osd');
  }
  return sources;
}

// Apply monthly price sources to UI dropdowns
function applyMonthlyPriceSources(sources) {
  if (!sources) return;
  for (let m = 1; m <= 12; m++) {
    const el = document.getElementById(`monthPriceSource_${m}`);
    if (el) el.value = sources[m] || 'osd';
  }
  updateHybridMonthlyPreview();
}

// Quick-set all months to a preset pattern
function setMonthlyPreset(preset) {
  const sources = {};
  for (let m = 1; m <= 12; m++) {
    if (preset === 'all_osd') {
      sources[m] = 'osd';
    } else if (preset === 'all_rdn') {
      sources[m] = 'rdn';
    } else if (preset === 'q2q3_rdn') {
      sources[m] = (m >= 4 && m <= 9) ? 'rdn' : 'osd';
    } else if (preset === 'q1q4_rdn') {
      sources[m] = (m <= 3 || m >= 10) ? 'rdn' : 'osd';
    } else if (preset === 'summer_rdn') {
      sources[m] = (m >= 5 && m <= 8) ? 'rdn' : 'osd';
    }
  }
  for (let m = 1; m <= 12; m++) {
    const el = document.getElementById(`monthPriceSource_${m}`);
    if (el) el.value = sources[m];
  }
  updateHybridMonthlyPreview();
  markUnsaved();
}

// Update visual preview of monthly pricing
function updateHybridMonthlyPreview() {
  const preview = document.getElementById('hybridMonthlyPreview');
  if (!preview) return;
  const monthNames = ['Sty','Lut','Mar','Kwi','Maj','Cze','Lip','Sie','Wrz','Paź','Lis','Gru'];
  let rdnCount = 0, osdCount = 0;
  let html = '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:8px">';
  for (let m = 1; m <= 12; m++) {
    const el = document.getElementById(`monthPriceSource_${m}`);
    const src = el ? el.value : 'osd';
    const isRdn = src === 'rdn';
    if (isRdn) rdnCount++; else osdCount++;
    const color = isRdn ? '#c2185b' : '#e65100';
    const bg = isRdn ? '#fce4ec' : '#fff3e0';
    html += `<span style="padding:2px 6px;border-radius:4px;font-size:11px;background:${bg};color:${color};font-weight:600">${monthNames[m-1]}: ${src.toUpperCase()}</span>`;
  }
  html += '</div>';
  html += `<div style="font-size:11px;color:#666;margin-top:4px">OSD: ${osdCount} mies. | RDN: ${rdnCount} mies.</div>`;
  preview.innerHTML = html;
}

// Toggle hybrid monthly pricing section visibility
function toggleHybridMonthlySection() {
  const mode = document.getElementById('pricingMode')?.value || 'single';
  const section = document.getElementById('hybridMonthlySection');
  if (section) {
    section.style.display = mode === 'hybrid_monthly' ? 'block' : 'none';
  }
  // In hybrid mode, ensure both OSD and RDN are enabled
  if (mode === 'hybrid_monthly') {
    const osdEl = document.getElementById('bessOsdArbitrageEnabled');
    const rdnEl = document.getElementById('bessPriceArbitrageEnabled');
    if (osdEl && !osdEl.checked) { osdEl.checked = true; const o = document.getElementById('bessOsdArbitrageOverlay'); if (o) o.checked = true; }
    if (rdnEl && !rdnEl.checked) { rdnEl.checked = true; const o = document.getElementById('bessPriceArbitrageOverlay'); if (o) o.checked = true; }
  }
  markUnsaved();
}

// Mark settings as unsaved
function markUnsaved() {
  // Update pricing routing summary on any settings change
  updatePricingRoutingSummary();
}

/**
 * Update the "Routing cen → Moduły" panel.
 * Shows clearly which price data goes to which module (PV Economics, BESS).
 */
function updatePricingRoutingSummary() {
  const el = document.getElementById('pricingRoutingContent');
  if (!el) return;

  // Read current UI state
  const osdOperator = document.getElementById('osdOperator')?.value || '(brak)';
  const osdGroup = document.getElementById('osdTariffGroup')?.value || '(brak)';
  const tariffType = document.getElementById('tariffType')?.value || 'two_zone';
  const pricingMode = document.getElementById('pricingMode')?.value || 'single';

  // Energy rates
  const summTotal = document.getElementById('summTotal')?.textContent || '?';
  const summEnergyAvg = document.getElementById('summEnergyAvg')?.textContent || '?';
  const summDistAvg = document.getElementById('summDistAvg')?.textContent || '?';
  const summCapacityVal = document.getElementById('summCapacityVal')?.textContent || '?';

  // BESS flags
  const osdArb = document.getElementById('bessOsdArbitrageOverlay')?.checked ||
                  document.getElementById('bessOsdArbitrageEnabled')?.checked;
  const rdnArb = document.getElementById('bessPriceArbitrageOverlay')?.checked ||
                  document.getElementById('bessPriceArbitrageEnabled')?.checked;
  const capFee = document.getElementById('bessCapacityFeeOverlay')?.checked;

  // RDN data
  let rdnStatus = '<span style="color:#c62828;font-weight:700">BRAK DANYCH</span>';
  try {
    const info = localStorage.getItem('rdn_scenario_info');
    if (info) {
      const rdnInfo = JSON.parse(info);
      rdnStatus = `<span style="color:#2e7d32;font-weight:700">${rdnInfo.dataPoints || '?'} h, avg ${rdnInfo.avgPrice?.toFixed(0) || '?'} PLN/MWh (${rdnInfo.scenarioName || rdnInfo.year || '?'})</span>`;
    }
  } catch (e) { /* ignore */ }

  // Hybrid monthly info
  let hybridInfo = '';
  if (pricingMode === 'hybrid_monthly') {
    const months = [];
    for (let m = 1; m <= 12; m++) {
      const sel = document.getElementById('monthPriceSource_' + m);
      if (sel) months.push({ m, src: sel.value || 'osd' });
    }
    const rdnMonths = months.filter(x => x.src === 'rdn').map(x => x.m);
    const osdMonths = months.filter(x => x.src !== 'rdn').map(x => x.m);
    hybridInfo = `<br>&nbsp;&nbsp;OSD miesiące: <strong>${osdMonths.join(', ') || 'brak'}</strong> | RDN miesiące: <strong style="color:#1565c0">${rdnMonths.join(', ') || 'brak'}</strong>`;
  }

  // Tariff type name
  const tariffNames = { flat: 'Stała', two_zone: '2-strefowa (C12a)', three_zone: '3-strefowa (C12b)', four_zone: '4-strefowa' };
  const tariffLabel = tariffNames[tariffType] || tariffType;

  // Build routing table
  const rows = [];

  // === PV ECONOMICS ===
  rows.push(`<tr style="background:#e8f5e9">
    <td style="padding:6px 10px;font-weight:700;color:#2e7d32;border-bottom:1px solid #c8e6c9">☀️ PV Ekonomia</td>
    <td style="padding:6px 10px;border-bottom:1px solid #c8e6c9">
      Taryfa <strong>${tariffLabel}</strong> (${osdOperator || 'ręcznie'} / ${osdGroup || '?'})<br>
      Stawka łączna: <strong>${summTotal} PLN/MWh</strong> (energia ${summEnergyAvg} + dystr. ${summDistAvg} + mocowa ${summCapacityVal})
      ${pricingMode === 'hybrid_monthly' ? '<br>Tryb: <strong style="color:#ff6f00">HYBRYDOWY</strong>' + hybridInfo : ''}
    </td>
  </tr>`);

  // === BESS AUTOKONSUMPCJA ===
  rows.push(`<tr style="background:#e3f2fd">
    <td style="padding:6px 10px;font-weight:700;color:#1565c0;border-bottom:1px solid #bbdefb">🔋 BESS Autokonsumpcja</td>
    <td style="padding:6px 10px;border-bottom:1px solid #bbdefb">
      Stawka łączna: <strong>${summTotal} PLN/MWh</strong> (ta sama co PV — oszczędność = uniknięty import)
    </td>
  </tr>`);

  // === BESS ARBITRAGE ===
  let arbDesc = '<span style="color:#999">wyłączony</span>';
  if (osdArb || rdnArb) {
    const parts = [];
    if (osdArb) parts.push(`<strong style="color:#4CAF50">OSD ToU</strong> (strefy ${tariffLabel})`);
    if (rdnArb) parts.push(`<strong style="color:#1565c0">RDN Spot</strong> — ${rdnStatus}`);
    arbDesc = parts.join(' + ');
    if (pricingMode === 'hybrid_monthly' && osdArb && rdnArb) {
      arbDesc += '<br><span style="color:#ff6f00;font-weight:600">HYBRID</span>: per-miesiąc OSD/RDN' + hybridInfo;
    }
  }
  rows.push(`<tr style="background:#fff8e1">
    <td style="padding:6px 10px;font-weight:700;color:#f57f17;border-bottom:1px solid #fff9c4">⚡ BESS Arbitraż</td>
    <td style="padding:6px 10px;border-bottom:1px solid #fff9c4">${arbDesc}</td>
  </tr>`);

  // === BESS CAPACITY FEE ===
  rows.push(`<tr style="background:#fce4ec">
    <td style="padding:6px 10px;font-weight:700;color:#c62828">📊 Opłata mocowa</td>
    <td style="padding:6px 10px">
      ${capFee ? '<strong style="color:#2e7d32">WŁĄCZONA</strong>' : '<span style="color:#999">wyłączona</span>'}
      — SOM: <strong>${(parseFloat(document.getElementById('capacitySomRate')?.value) || 0.2194).toFixed(4)} PLN/kWh</strong>
    </td>
  </tr>`);

  // === RDN DATA STATUS ===
  rows.push(`<tr style="background:#f3e5f5">
    <td style="padding:6px 10px;font-weight:700;color:#6a1b9a">💹 Dane RDN</td>
    <td style="padding:6px 10px">${rdnStatus}${rdnArb ? '' : ' <span style="color:#999">(nieużywane — arbitraż RDN wyłączony)</span>'}</td>
  </tr>`);

  el.innerHTML = `<table style="width:100%;border-collapse:collapse;border-radius:6px;overflow:hidden;border:1px solid #e0e0e0">${rows.join('')}</table>`;

  // Show/hide and auto-update OSD vs RDN comparison panel
  updateOsdVsRdnVisibility();
}

/**
 * Show/hide the OSD vs RDN comparison panel based on data availability.
 * Auto-update when both OSD tariff and RDN data are present.
 */
function updateOsdVsRdnVisibility() {
  const panel = document.getElementById('osdVsRdnComparison');
  if (!panel) return;

  // Check if RDN data exists
  let hasRdn = false;
  try {
    const raw = localStorage.getItem('rdn_hourly_prices');
    if (raw) {
      const arr = JSON.parse(raw);
      hasRdn = Array.isArray(arr) && arr.length >= 8760;
    }
  } catch (e) { /* ignore */ }

  // Always show panel if RDN data loaded (user can compare)
  if (hasRdn) {
    panel.style.display = 'block';
    updateOsdVsRdnComparison();
  } else {
    panel.style.display = 'none';
  }
}

/**
 * OSD vs RDN Profitability Comparison.
 *
 * Computes estimated annual BESS arbitrage revenue for:
 * 1) OSD ToU mode: buy at offpeak rate, sell at peak rate (tariff spread)
 * 2) RDN Spot mode: buy at P25 price, sell at P75 price (hourly volatility)
 *
 * Assumes a reference 1 MWh/1 MW BESS doing 1 cycle/day, 90% roundtrip efficiency.
 */
function updateOsdVsRdnComparison() {
  const el = document.getElementById('osdVsRdnContent');
  if (!el) return;

  // --- Reference BESS params ---
  const refCapacityMwh = 1.0;  // 1 MWh reference
  const eta = parseFloat(document.getElementById('bessRoundtripEfficiency')?.value || 90) / 100;

  // --- OSD Tariff rates ---
  const tariffConfig = getTariffConfig();
  const weekdayRates = getTariffHourlyRates('weekday');
  const weekendRates = getTariffHourlyRates('weekend');

  // --- RDN hourly prices ---
  let rdnPrices = null;
  try {
    const raw = localStorage.getItem('rdn_hourly_prices');
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length >= 8760) rdnPrices = arr.slice(0, 8760);
    }
  } catch (e) { /* ignore */ }

  if (!rdnPrices) {
    el.innerHTML = '<em style="color:#c62828">Brak danych RDN — załaduj scenariusz RDN w zakładce "Ceny energii" by porównać.</em>';
    return;
  }

  // --- Compute OSD annual arbitrage ---
  // For each day of year: find max/min energy rate, compute spread * capacity * eta
  const startDate = new Date(2025, 0, 1); // reference year
  let osdTotalRevenue = 0;
  let osdDaysTraded = 0;

  for (let d = 0; d < 365; d++) {
    const date = new Date(startDate.getTime() + d * 86400000);
    const isWeekend = (date.getDay() === 0 || date.getDay() === 6);
    const rates = isWeekend ? weekendRates : weekdayRates;

    const maxRate = Math.max(...rates);
    const minRate = Math.min(...rates);
    const spread = maxRate - minRate;

    if (spread > 0) {
      // Buy 1/eta MWh at minRate, sell 1 MWh at maxRate
      const dailyProfitPln = (maxRate - minRate / eta) * refCapacityMwh;
      osdTotalRevenue += dailyProfitPln;
      if (dailyProfitPln > 0) osdDaysTraded++;
    }
  }

  // --- Compute RDN annual arbitrage ---
  // For each day: find best buy hour and best sell hour
  let rdnTotalRevenue = 0;
  let rdnDaysTraded = 0;

  for (let d = 0; d < 365; d++) {
    const dayPrices = rdnPrices.slice(d * 24, (d + 1) * 24);
    if (dayPrices.length < 24) continue;

    const maxPrice = Math.max(...dayPrices);
    const minPrice = Math.min(...dayPrices);

    // Buy 1/eta MWh at min, sell 1 MWh at max
    const dailyProfitPln = (maxPrice - minPrice / eta) * refCapacityMwh;
    if (dailyProfitPln > 0) {
      rdnTotalRevenue += dailyProfitPln;
      rdnDaysTraded++;
    }
  }

  // --- RDN statistics ---
  const rdnSorted = [...rdnPrices].sort((a, b) => a - b);
  const rdnAvg = rdnPrices.reduce((s, v) => s + v, 0) / rdnPrices.length;
  const rdnP25 = rdnSorted[Math.floor(rdnPrices.length * 0.25)];
  const rdnP50 = rdnSorted[Math.floor(rdnPrices.length * 0.50)];
  const rdnP75 = rdnSorted[Math.floor(rdnPrices.length * 0.75)];
  const rdnMin = rdnSorted[0];
  const rdnMax = rdnSorted[rdnSorted.length - 1];

  // --- OSD statistics ---
  const osdAvgWeekday = weekdayRates.reduce((s, v) => s + v, 0) / 24;
  const osdMax = Math.max(...weekdayRates);
  const osdMin = Math.min(...weekdayRates);
  const osdSpread = osdMax - osdMin;

  // --- Winner ---
  const osdWins = osdTotalRevenue >= rdnTotalRevenue;
  const diff = Math.abs(osdTotalRevenue - rdnTotalRevenue);
  const diffPct = rdnTotalRevenue > 0 ? (diff / Math.max(osdTotalRevenue, rdnTotalRevenue) * 100) : 0;

  // --- Build HTML ---
  const fmt = (v) => v.toFixed(0);
  const fmtK = (v) => (v / 1000).toFixed(1);

  const winnerColor = osdWins ? '#e65100' : '#1565c0';
  const winnerLabel = osdWins ? 'OSD Taryfa' : 'RDN Spot';
  const winnerIcon = osdWins ? '📋' : '💹';

  el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
      <!-- OSD Column -->
      <div style="background:${osdWins ? 'linear-gradient(135deg,#fff3e0,#ffe0b2)' : '#fff'};border-radius:8px;padding:12px;border:2px solid ${osdWins ? '#ff9800' : '#e0e0e0'}">
        <div style="font-weight:700;color:#e65100;font-size:13px;margin-bottom:8px">📋 OSD Taryfa (${tariffConfig.type === 'flat' ? 'stała' : tariffConfig.type === 'two_zone' ? '2-stref.' : tariffConfig.type === 'three_zone' ? '3-stref.' : '4-stref.'})</div>
        <div style="font-size:11px;line-height:1.7">
          Szczyt: <strong>${fmt(osdMax)} PLN/MWh</strong><br>
          Pozaszczy: <strong>${fmt(osdMin)} PLN/MWh</strong><br>
          Spread: <strong>${fmt(osdSpread)} PLN/MWh</strong><br>
          Średnia: <strong>${fmt(osdAvgWeekday)} PLN/MWh</strong>
        </div>
        <div style="margin-top:8px;padding:8px;background:rgba(255,152,0,0.1);border-radius:6px;text-align:center">
          <div style="font-size:11px;color:#e65100;font-weight:600">Roczny przychód arbitraż</div>
          <div style="font-size:22px;font-weight:900;color:#e65100">${fmtK(osdTotalRevenue)} tys. PLN</div>
          <div style="font-size:10px;color:#999">na 1 MWh BESS, ${osdDaysTraded} dni handlowych</div>
        </div>
      </div>

      <!-- RDN Column -->
      <div style="background:${!osdWins ? 'linear-gradient(135deg,#e3f2fd,#bbdefb)' : '#fff'};border-radius:8px;padding:12px;border:2px solid ${!osdWins ? '#1976d2' : '#e0e0e0'}">
        <div style="font-weight:700;color:#1565c0;font-size:13px;margin-bottom:8px">💹 RDN Spot (godzinowe)</div>
        <div style="font-size:11px;line-height:1.7">
          Min: <strong>${fmt(rdnMin)} PLN/MWh</strong> | Max: <strong>${fmt(rdnMax)} PLN/MWh</strong><br>
          P25: <strong>${fmt(rdnP25)}</strong> | P50: <strong>${fmt(rdnP50)}</strong> | P75: <strong>${fmt(rdnP75)}</strong><br>
          Spread P25-P75: <strong>${fmt(rdnP75 - rdnP25)} PLN/MWh</strong><br>
          Średnia: <strong>${fmt(rdnAvg)} PLN/MWh</strong>
        </div>
        <div style="margin-top:8px;padding:8px;background:rgba(25,118,210,0.1);border-radius:6px;text-align:center">
          <div style="font-size:11px;color:#1565c0;font-weight:600">Roczny przychód arbitraż</div>
          <div style="font-size:22px;font-weight:900;color:#1565c0">${fmtK(rdnTotalRevenue)} tys. PLN</div>
          <div style="font-size:10px;color:#999">na 1 MWh BESS, ${rdnDaysTraded} dni handlowych</div>
        </div>
      </div>
    </div>

    <!-- Verdict -->
    <div style="padding:10px 14px;background:${winnerColor};border-radius:8px;text-align:center">
      <span style="font-size:14px;font-weight:800;color:white">
        ${winnerIcon} ${winnerLabel} jest korzystniejszy o ${fmtK(diff)} tys. PLN/rok (+${diffPct.toFixed(0)}%)
      </span>
      <div style="font-size:10px;color:rgba(255,255,255,0.8);margin-top:4px">
        Ref: 1 MWh BESS, η=${(eta*100).toFixed(0)}%, 1 cykl/dzień, ceny bez opłat dystr. Rzeczywisty wynik zależy od profilu obciążenia i strategii LP.
      </div>
    </div>
  `;
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

// Utility function to get CAPEX sale price [PLN/kWp] for capacity and optional pvType.
// Delegates to getCapexForCapacityAndType (NEW format with capexPerType + capexRanges).
// This is the SSoT — other modules should call window.PVSettings.getCapexForCapacity().
function getCapexForCapacity(capacityKwp, pvType) {
  const type = pvType || 'ground_s';
  const result = getCapexForCapacityAndType(capacityKwp, type);
  return result.sale;
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
  // Wigilia — only from 2025 (Dz.U. 2024 poz. 1911)
  if (year >= 2025) {
    holidays.push(new Date(year, 11, 24));
  }

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
function calculateConsumptionProfile(hourlyData, startDate = '2025-01-01') {
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
function calculateCapacityFee(hourlyData, startDate = '2025-01-01') {
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
const PVGIS_PROXY_BASE = API_URLS.pvgisProxy;

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
const GEO_SERVICE_URL = API_URLS.geo;

/**
 * Load cities list for autocomplete based on selected country
 */
async function loadCitiesList(countryCode) {
  countryCode = countryCode || 'PL';
  try {
    const response = await fetch(GEO_SERVICE_URL + '/cities/' + countryCode.toUpperCase());
    if (response.ok) {
      const data = await response.json();
      const datalist = document.getElementById('polishCitiesList');
      if (datalist && data.cities) {
        datalist.innerHTML = data.cities.map(function(city) {
          return '<option value="' + city + '">';
        }).join('');
        console.log('📍 Loaded ' + data.cities.length + ' cities for ' + countryCode + ' autocomplete');
      }
    }
  } catch (err) {
    console.warn('Could not load cities list for ' + countryCode + ':', err.message);
  }
}

/**
 * Legacy function for backward compatibility
 */
async function loadPolishCitiesList() {
  return loadCitiesList('PL');
}

/**
 * Called when country selection changes - reload cities list
 */
function onCountryChange() {
  const country = document.getElementById('geoCountry')?.value || 'PL';
  // Clear current city input
  const cityInput = document.getElementById('geoCity');
  if (cityInput) cityInput.value = '';
  // Load cities for new country
  loadCitiesList(country);
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
    let url = GEO_SERVICE_URL + '/resolve?country=' + encodeURIComponent(country);
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
  initCapacityFeeSection();
});

// Make function globally available
window.toggleOperatingModeFields = toggleOperatingModeFields;


// ============================================================================
// Capacity Fee (Opłata Mocowa) Functions
// ============================================================================

/**
 * Initialize capacity fee section with saved or default values
 */
function initCapacityFeeSection() {
  const saved = localStorage.getItem('pv_system_settings');
  let config = DEFAULT_CONFIG.capacityFeeConfig;

  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      if (parsed.capacityFeeConfig) {
        config = parsed.capacityFeeConfig;
      }
    } catch (e) {
      console.warn('Failed to parse saved capacity fee config:', e);
    }
  }

  // Populate fields
  const yearEl = document.getElementById('capacityFeeYear');
  const somRateEl = document.getElementById('somRate');
  const qualPeriodEl = document.getElementById('qualificationPeriod');
  const somSourceEl = document.getElementById('somSource');

  if (yearEl) yearEl.value = config.year || 2026;
  if (somRateEl) somRateEl.value = config.somRate || 0.2194;
  if (qualPeriodEl) qualPeriodEl.value = config.qualificationPeriod || 'daily';
  if (somSourceEl) somSourceEl.value = config.somSource || 'URE 58/2025';

  // Populate selected hours per quarter
  const hours = config.selectedHours || DEFAULT_CONFIG.capacityFeeConfig.selectedHours;
  ['Q1', 'Q2', 'Q3', 'Q4'].forEach(q => {
    const startEl = document.getElementById(`selectedHours${q}Start`);
    const endEl = document.getElementById(`selectedHours${q}End`);
    if (startEl && hours[q]) startEl.value = hours[q].start;
    if (endEl && hours[q]) endEl.value = hours[q].end;
  });

  // Update qualification period based on year
  updateQualificationPeriod(config.year);

  // Update capacityFee field (SOM × 1000 for PLN/MWh)
  updateCapacityFeeFromSom();

  console.log('⚡ Capacity fee section initialized:', config);
}

/**
 * Handle year change - update qualification period and optionally fetch preset
 */
function onCapacityFeeYearChange() {
  const year = parseInt(document.getElementById('capacityFeeYear')?.value || 2026);
  updateQualificationPeriod(year);
}

/**
 * Update qualification period selector based on year
 */
function updateQualificationPeriod(year) {
  const qualPeriodEl = document.getElementById('qualificationPeriod');
  if (!qualPeriodEl) return;

  if (year >= 2025) {
    qualPeriodEl.value = 'daily';
  } else if (year >= 2023) {
    qualPeriodEl.value = 'decadal';
  } else {
    qualPeriodEl.value = 'monthly';
  }
}

/**
 * Update capacityFee field from SOM rate (SOM × 1000 = PLN/MWh)
 */
function updateCapacityFeeFromSom() {
  const somRate = parseFloat(document.getElementById('somRate')?.value || 0.2194);
  const capacityFeeEl = document.getElementById('capacityFee');
  if (capacityFeeEl) {
    // SOM is PLN/kWh, capacityFee needs PLN/MWh
    capacityFeeEl.value = Math.round(somRate * 1000);
  }
  // Recalculate total energy price
  updateTotalEnergyPrice();
}

/**
 * Load capacity fee preset from backend API
 */
async function loadCapacityFeePreset() {
  const year = parseInt(document.getElementById('capacityFeeYear')?.value || 2026);
  const btn = event?.target;

  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Ładowanie...';
    }

    const response = await fetch(`/api/bess-dispatch/capacity-fee/presets/${year}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const preset = await response.json();
    console.log('📥 Loaded capacity fee preset:', preset);

    // Update fields
    document.getElementById('somRate').value = preset.som_pln_per_kwh;
    document.getElementById('qualificationPeriod').value = preset.qualification_period;
    document.getElementById('somSource').value = preset.notes?.som_source || `Preset ${year}`;

    // Update selected hours per quarter
    if (preset.selected_windows_by_quarter) {
      ['Q1', 'Q2', 'Q3', 'Q4'].forEach(q => {
        const window = preset.selected_windows_by_quarter[q];
        if (window) {
          document.getElementById(`selectedHours${q}Start`).value = window[0];
          document.getElementById(`selectedHours${q}End`).value = window[1];
        }
      });
    }

    // Update capacityFee and total
    updateCapacityFeeFromSom();

    alert(`✅ Załadowano preset dla roku ${year}\nStawka SOM: ${preset.som_pln_per_kwh} PLN/kWh`);

  } catch (error) {
    console.error('Failed to load capacity fee preset:', error);
    alert(`❌ Błąd pobierania presetu: ${error.message}\n\nSprawdź czy serwis bess-dispatch jest uruchomiony.`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 Pobierz preset z API';
    }
  }
}

/**
 * Get current capacity fee configuration
 */
function getCapacityFeeConfig() {
  return {
    year: parseInt(document.getElementById('capacityFeeYear')?.value || 2026),
    somRate: parseFloat(document.getElementById('somRate')?.value || 0.2194),
    qualificationPeriod: document.getElementById('qualificationPeriod')?.value || 'daily',
    somSource: document.getElementById('somSource')?.value || 'URE 58/2025',
    selectedHours: {
      Q1: {
        start: parseInt(document.getElementById('selectedHoursQ1Start')?.value || 7),
        end: parseInt(document.getElementById('selectedHoursQ1End')?.value || 22)
      },
      Q2: {
        start: parseInt(document.getElementById('selectedHoursQ2Start')?.value || 7),
        end: parseInt(document.getElementById('selectedHoursQ2End')?.value || 22)
      },
      Q3: {
        start: parseInt(document.getElementById('selectedHoursQ3Start')?.value || 7),
        end: parseInt(document.getElementById('selectedHoursQ3End')?.value || 22)
      },
      Q4: {
        start: parseInt(document.getElementById('selectedHoursQ4Start')?.value || 7),
        end: parseInt(document.getElementById('selectedHoursQ4End')?.value || 22)
      }
    },
    kCoefficients: DEFAULT_CONFIG.capacityFeeConfig.kCoefficients
  };
}

// Current selected quarter for capacity fee UI
let currentCapacityFeeQuarter = 'Q1';

/**
 * Select capacity fee quarter tab
 */
function selectCapacityFeeQuarter(quarter) {
  currentCapacityFeeQuarter = quarter;

  // Update tab styling
  ['Q1', 'Q2', 'Q3', 'Q4'].forEach(q => {
    const tab = document.getElementById(`cfTab${q}`);
    if (tab) {
      tab.classList.toggle('active', q === quarter);
    }
  });

  // Load values for selected quarter into visible inputs
  const startEl = document.getElementById('selectedHoursStart');
  const endEl = document.getElementById('selectedHoursEnd');
  const startHiddenEl = document.getElementById(`selectedHours${quarter}Start`);
  const endHiddenEl = document.getElementById(`selectedHours${quarter}End`);

  if (startEl && startHiddenEl) startEl.value = startHiddenEl.value;
  if (endEl && endHiddenEl) endEl.value = endHiddenEl.value;

  updateCapacityFeeVisualization();
}

/**
 * Update capacity fee visualization and save to hidden fields
 */
function updateCapacityFeeVisualization() {
  // Save current values to hidden fields for selected quarter
  const startEl = document.getElementById('selectedHoursStart');
  const endEl = document.getElementById('selectedHoursEnd');
  const startHiddenEl = document.getElementById(`selectedHours${currentCapacityFeeQuarter}Start`);
  const endHiddenEl = document.getElementById(`selectedHours${currentCapacityFeeQuarter}End`);

  if (startEl && startHiddenEl) startHiddenEl.value = startEl.value;
  if (endEl && endHiddenEl) endHiddenEl.value = endEl.value;

  // Update hours count display
  const start = parseInt(startEl?.value || 7);
  const end = parseInt(endEl?.value || 22);
  const hoursCount = end - start;

  const countEl = document.getElementById('selectedHoursCount');
  if (countEl) countEl.textContent = hoursCount;

  // Update timeline visualization
  const container = document.getElementById('capacityFeeTimeline');
  if (container) {
    const startPct = (start / 24) * 100;
    const widthPct = ((end - start) / 24) * 100;

    let html = '';

    // Unselected before
    if (start > 0) {
      html += `<div class="unselected" style="left:0;width:${startPct}%"></div>`;
    }

    // Selected window
    html += `<div class="selected-window" style="left:${startPct}%;width:${widthPct}%">
      ${String(start).padStart(2, '0')}:00 — ${String(end).padStart(2, '0')}:00 (${hoursCount}h)
    </div>`;

    // Unselected after
    if (end < 24) {
      const afterPct = (end / 24) * 100;
      const afterWidth = ((24 - end) / 24) * 100;
      html += `<div class="unselected" style="left:${afterPct}%;width:${afterWidth}%"></div>`;
    }

    container.innerHTML = html;
  }

  // Update hour markers highlighting
  const hoursContainer = container?.parentElement?.querySelector('.timeline-hours');
  if (hoursContainer) {
    const spans = hoursContainer.querySelectorAll('span');
    spans.forEach((span, idx) => {
      if (idx >= start && idx < end) {
        span.classList.add('highlight');
        span.style.color = '#e65100';
      } else {
        span.classList.remove('highlight');
        span.style.color = '#666';
      }
    });
  }
}

// Make capacity fee functions globally available
window.onCapacityFeeYearChange = onCapacityFeeYearChange;
window.loadCapacityFeePreset = loadCapacityFeePreset;
window.getCapacityFeeConfig = getCapacityFeeConfig;
window.updateCapacityFeeFromSom = updateCapacityFeeFromSom;
window.selectCapacityFeeQuarter = selectCapacityFeeQuarter;
window.updateCapacityFeeVisualization = updateCapacityFeeVisualization;

// Add event listener for SOM rate changes and initialize visualizations
document.addEventListener('DOMContentLoaded', function() {
  const somRateEl = document.getElementById('somRate');
  if (somRateEl) {
    somRateEl.addEventListener('change', updateCapacityFeeFromSom);
    somRateEl.addEventListener('input', updateCapacityFeeFromSom);
  }

  // Initialize capacity fee visualization
  setTimeout(() => {
    updateCapacityFeeVisualization();
    updateTariffVisualization();
  }, 100);
});


// ============================================================================
// Time-of-Use Tariffs Functions
// ============================================================================

/**
 * Initialize tariff section with saved or default values
 */
function initTariffSection() {
  const saved = localStorage.getItem('pv_system_settings');
  let config = JSON.parse(JSON.stringify(DEFAULT_CONFIG.tariffConfig)); // Deep copy

  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      if (parsed.tariffConfig) {
        // Deep merge tariff config
        config.type = parsed.tariffConfig.type || config.type;
        config.name = parsed.tariffConfig.name || config.name;
        config.flatRate = parsed.tariffConfig.flatRate || config.flatRate;

        // Deep merge twoZone
        if (parsed.tariffConfig.twoZone) {
          config.twoZone = {
            ...config.twoZone,
            ...parsed.tariffConfig.twoZone,
            weekday: { ...config.twoZone.weekday, ...(parsed.tariffConfig.twoZone.weekday || {}) },
            weekend: { ...config.twoZone.weekend, ...(parsed.tariffConfig.twoZone.weekend || {}) }
          };
        }

        // Deep merge threeZone
        if (parsed.tariffConfig.threeZone) {
          config.threeZone = {
            ...config.threeZone,
            ...parsed.tariffConfig.threeZone,
            peak1: { ...config.threeZone.peak1, ...(parsed.tariffConfig.threeZone.peak1 || {}) },
            peak2: { ...config.threeZone.peak2, ...(parsed.tariffConfig.threeZone.peak2 || {}) },
            partial: { ...config.threeZone.partial, ...(parsed.tariffConfig.threeZone.partial || {}) }
          };
        }

        console.log('🕐 Loaded tariff config from storage:', config);
      }
    } catch (e) {
      console.warn('Failed to parse saved tariff config:', e);
    }
  }

  // Populate fields
  const typeEl = document.getElementById('tariffType');
  const nameEl = document.getElementById('tariffName');

  if (typeEl) typeEl.value = config.type || 'two_zone';
  if (nameEl) nameEl.value = config.name || 'C12a';

  // Flat rate
  const flatRateEl = document.getElementById('tariffFlatRate');
  if (flatRateEl) flatRateEl.value = config.flatRate || 750;

  // Two-zone
  const twoZone = config.twoZone || DEFAULT_CONFIG.tariffConfig.twoZone;
  setValueById('tariffDayRate', twoZone.dayRate);
  setValueById('tariffNightRate', twoZone.nightRate);
  setValueById('tariffDayStartWeekday', twoZone.weekday?.start || 6);
  setValueById('tariffDayEndWeekday', twoZone.weekday?.end || 22);
  setValueById('tariffDayStartWeekend', twoZone.weekend?.start || 6);
  setValueById('tariffDayEndWeekend', twoZone.weekend?.end || 13);

  // Three-zone
  const threeZone = config.threeZone || DEFAULT_CONFIG.tariffConfig.threeZone;
  setValueById('tariffPeakRate', threeZone.peakRate);
  setValueById('tariffPartialRate', threeZone.partialRate);
  setValueById('tariffOffPeakRate', threeZone.offPeakRate);
  setValueById('tariffPeakStart', threeZone.peak1?.start || 7);
  setValueById('tariffPeakEnd', threeZone.peak1?.end || 13);
  setValueById('tariffPeakStart2', threeZone.peak2?.start || 17);
  setValueById('tariffPeakEnd2', threeZone.peak2?.end || 21);
  setValueById('tariffPartialStart', threeZone.partial?.start || 13);
  setValueById('tariffPartialEnd', threeZone.partial?.end || 17);

  // Show correct zone panel
  onTariffTypeChange();

  // Update visualization
  updateTariffVisualization();

  console.log('🕐 Tariff section initialized:', config);
}

function setValueById(id, value) {
  const el = document.getElementById(id);
  if (el && value !== undefined) el.value = value;
}

/**
 * Handle tariff type change - show/hide appropriate zone panels
 */
function onTariffTypeChange() {
  const type = document.getElementById('tariffType')?.value || 'two_zone';
  console.log('🕐 Tariff type changed to:', type);

  const flatZone = document.getElementById('tariffFlatZone');
  const twoZone = document.getElementById('tariffTwoZone');
  const threeZone = document.getElementById('tariffThreeZone');
  const fourZone = document.getElementById('tariffFourZone');

  if (flatZone) flatZone.style.display = type === 'flat' ? 'block' : 'none';
  if (twoZone) twoZone.style.display = type === 'two_zone' ? 'block' : 'none';
  if (threeZone) threeZone.style.display = type === 'three_zone' ? 'block' : 'none';
  if (fourZone) fourZone.style.display = type === 'four_zone' ? 'block' : 'none';

  // Update tariff name suggestion
  const nameEl = document.getElementById('tariffName');
  if (nameEl) {
    if (type === 'flat') nameEl.value = 'C11';
    else if (type === 'two_zone') nameEl.value = 'C12a';
    else if (type === 'three_zone') nameEl.value = 'C12b';
    else if (type === 'four_zone') nameEl.value = 'C24';
  }

  updateTariffVisualization();
  updateTariffAverageRate();

  // Mark settings as changed to trigger save
  markUnsaved();
}

/**
 * Update tariff visualization bar (new enhanced version)
 */
function updateTariffVisualization() {
  const container = document.getElementById('tariffTimeline');
  if (!container) return;

  const type = document.getElementById('tariffType')?.value || 'two_zone';
  let html = '';

  if (type === 'flat') {
    html = `<div class="timeline-segment zone-flat" style="left:0;width:100%">
      <span>Całodobowo</span>
    </div>`;
  } else if (type === 'two_zone') {
    const dayStart = parseInt(document.getElementById('tariffDayStartWeekday')?.value || 6);
    const dayEnd = parseInt(document.getElementById('tariffDayEndWeekday')?.value || 22);
    const dayRate = parseFloat(document.getElementById('tariffDayRate')?.value || 850);
    const nightRate = parseFloat(document.getElementById('tariffNightRate')?.value || 450);

    // Night before day (0 - dayStart)
    if (dayStart > 0) {
      const width = (dayStart / 24) * 100;
      html += `<div class="timeline-segment zone-night" style="left:0;width:${width}%">
        <span>Noc ${nightRate}</span>
      </div>`;
    }

    // Day zone
    const dayWidth = ((dayEnd - dayStart) / 24) * 100;
    const dayLeft = (dayStart / 24) * 100;
    html += `<div class="timeline-segment zone-day" style="left:${dayLeft}%;width:${dayWidth}%">
      <span>Dzień ${dayRate}</span>
    </div>`;

    // Night after day
    if (dayEnd < 24) {
      const nightWidth = ((24 - dayEnd) / 24) * 100;
      const nightLeft = (dayEnd / 24) * 100;
      html += `<div class="timeline-segment zone-night" style="left:${nightLeft}%;width:${nightWidth}%">
        <span>Noc ${nightRate}</span>
      </div>`;
    }

    // Update zone hours display
    const dayHoursEl = document.getElementById('dayZoneHoursDisplay');
    const nightHoursEl = document.getElementById('nightZoneHoursDisplay');
    if (dayHoursEl) dayHoursEl.textContent = `${String(dayStart).padStart(2, '0')}:00 — ${String(dayEnd).padStart(2, '0')}:00`;
    if (nightHoursEl) nightHoursEl.textContent = `${String(dayEnd).padStart(2, '0')}:00 — ${String(dayStart).padStart(2, '0')}:00`;

  } else if (type === 'three_zone') {
    const peak1Start = parseInt(document.getElementById('tariffPeakStart')?.value || 7);
    const peak1End = parseInt(document.getElementById('tariffPeakEnd')?.value || 13);
    const peak2Start = parseInt(document.getElementById('tariffPeakStart2')?.value || 17);
    const peak2End = parseInt(document.getElementById('tariffPeakEnd2')?.value || 21);
    const nightStart = parseInt(document.getElementById('tariffNightStart3')?.value || 22);
    const nightEnd = parseInt(document.getElementById('tariffNightEnd3')?.value || 6);

    const peakRate = parseFloat(document.getElementById('tariffPeakRate')?.value || 950);
    const partialRate = parseFloat(document.getElementById('tariffPartialRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffOffPeakRate')?.value || 400);

    // Build hour-by-hour zone array
    const zones = [];
    for (let h = 0; h < 24; h++) {
      if (h >= nightStart || h < nightEnd) {
        zones.push({ zone: 'offpeak', rate: offPeakRate });
      } else if ((h >= peak1Start && h < peak1End) || (h >= peak2Start && h < peak2End)) {
        zones.push({ zone: 'peak', rate: peakRate });
      } else {
        zones.push({ zone: 'day', rate: partialRate });
      }
    }

    // Render segments
    let currentZone = zones[0].zone;
    let segmentStart = 0;
    for (let h = 1; h <= 24; h++) {
      const nextZone = h < 24 ? zones[h].zone : null;
      if (nextZone !== currentZone) {
        const width = ((h - segmentStart) / 24) * 100;
        const left = (segmentStart / 24) * 100;
        const rate = zones[segmentStart].rate;
        const label = currentZone === 'peak' ? 'Szczyt' : currentZone === 'day' ? 'Dzień' : 'Noc';
        html += `<div class="timeline-segment zone-${currentZone}" style="left:${left}%;width:${width}%">
          <span>${label} ${rate}</span>
        </div>`;
        currentZone = nextZone;
        segmentStart = h;
      }
    }

    // Update dynamic peak hours label
    const threeZonePeakLabel = document.getElementById('threeZonePeakHoursLabel');
    if (threeZonePeakLabel) threeZonePeakLabel.textContent = `${String(peak1Start).padStart(2,'0')}-${String(peak1End).padStart(2,'0')}, ${String(peak2Start).padStart(2,'0')}-${String(peak2End).padStart(2,'0')}`;
  } else if (type === 'four_zone') {
    const peak1Start = parseInt(document.getElementById('tariffFourPeakStart')?.value || 7);
    const peak1End = parseInt(document.getElementById('tariffFourPeakEnd')?.value || 13);
    const peak2Start = parseInt(document.getElementById('tariffFourPeakStart2')?.value || 16);
    const peak2End = parseInt(document.getElementById('tariffFourPeakEnd2')?.value || 21);
    const valleyStart = parseInt(document.getElementById('tariffFourValleyStart')?.value || 1);
    const valleyEnd = parseInt(document.getElementById('tariffFourValleyEnd')?.value || 5);

    const peakRate = parseFloat(document.getElementById('tariffFourPeakRate')?.value || 950);
    const dayRate = parseFloat(document.getElementById('tariffFourDayRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffFourOffPeakRate')?.value || 400);
    const valleyRate = parseFloat(document.getElementById('tariffFourValleyRate')?.value || 200);

    // Build hour-by-hour zone array
    const zones = [];
    for (let h = 0; h < 24; h++) {
      if (h >= valleyStart && h < valleyEnd) {
        zones.push({ zone: 'valley', rate: valleyRate });
      } else if ((h >= peak1Start && h < peak1End) || (h >= peak2Start && h < peak2End)) {
        zones.push({ zone: 'peak', rate: peakRate });
      } else {
        zones.push({ zone: 'day', rate: dayRate });
      }
    }

    // Render segments
    let currentZone = zones[0].zone;
    let segmentStart = 0;
    for (let h = 1; h <= 24; h++) {
      const nextZone = h < 24 ? zones[h].zone : null;
      if (nextZone !== currentZone) {
        const width = ((h - segmentStart) / 24) * 100;
        const left = (segmentStart / 24) * 100;
        const rate = zones[segmentStart].rate;
        const label = currentZone === 'peak' ? 'Szczyt' : currentZone === 'valley' ? 'Dolina' : 'Pozost.';
        const zoneClass = currentZone === 'valley' ? 'zone-valley' : `zone-${currentZone}`;
        html += `<div class="timeline-segment ${zoneClass}" style="left:${left}%;width:${width}%">
          <span>${label} ${rate}</span>
        </div>`;
        currentZone = nextZone;
        segmentStart = h;
      }
    }

    // Update dynamic labels
    const peakLabel = document.getElementById('fourZonePeakHoursLabel');
    if (peakLabel) peakLabel.textContent = `${String(peak1Start).padStart(2,'0')}-${String(peak1End).padStart(2,'0')}, ${String(peak2Start).padStart(2,'0')}-${String(peak2End).padStart(2,'0')}`;
    const valleyLabel = document.getElementById('fourZoneValleyHoursLabel');
    if (valleyLabel) valleyLabel.textContent = `${String(valleyStart).padStart(2,'0')}-${String(valleyEnd).padStart(2,'0')} + weekendy`;
  }

  container.innerHTML = html;
  updateTariffStats();
}

/**
 * Update tariff summary statistics
 */
function updateTariffStats() {
  const type = document.getElementById('tariffType')?.value || 'two_zone';

  let avgRate = 0;
  let nightSavings = 0;
  let peakHours = 0;

  if (type === 'flat') {
    avgRate = parseFloat(document.getElementById('tariffFlatRate')?.value || 750);
    nightSavings = 0;
    peakHours = 24;
  } else if (type === 'two_zone') {
    const dayRate = parseFloat(document.getElementById('tariffDayRate')?.value || 850);
    const nightRate = parseFloat(document.getElementById('tariffNightRate')?.value || 450);
    const dayStart = parseInt(document.getElementById('tariffDayStartWeekday')?.value || 6);
    const dayEnd = parseInt(document.getElementById('tariffDayEndWeekday')?.value || 22);

    peakHours = dayEnd - dayStart;
    avgRate = dayRate * 0.6 + nightRate * 0.4;
    nightSavings = Math.round((1 - nightRate / dayRate) * 100);
  } else if (type === 'three_zone') {
    const peakRate = parseFloat(document.getElementById('tariffPeakRate')?.value || 950);
    const partialRate = parseFloat(document.getElementById('tariffPartialRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffOffPeakRate')?.value || 400);

    avgRate = peakRate * 0.35 + partialRate * 0.25 + offPeakRate * 0.40;
    nightSavings = Math.round((1 - offPeakRate / peakRate) * 100);
    peakHours = 10; // Typical 3-zone peak hours
  } else if (type === 'four_zone') {
    const peakRate = parseFloat(document.getElementById('tariffFourPeakRate')?.value || 950);
    const dayRate = parseFloat(document.getElementById('tariffFourDayRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffFourOffPeakRate')?.value || 400);
    const valleyRate = parseFloat(document.getElementById('tariffFourValleyRate')?.value || 200);

    avgRate = peakRate * 0.18 + dayRate * 0.15 + offPeakRate * 0.10 + valleyRate * 0.57;
    nightSavings = Math.round((1 - valleyRate / peakRate) * 100);
    peakHours = 11;
  }

  // Update display
  const avgEl = document.getElementById('tariffAverageRate');
  const savingsEl = document.getElementById('tariffNightSavings');
  const hoursEl = document.getElementById('tariffPeakHours');

  if (avgEl) avgEl.textContent = Math.round(avgRate);
  if (savingsEl) savingsEl.textContent = `${nightSavings}%`;
  if (hoursEl) hoursEl.textContent = `${peakHours}h`;
}

/**
 * Calculate and update average tariff rate
 */
function updateTariffAverageRate() {
  const type = document.getElementById('tariffType')?.value || 'two_zone';
  let avgRate = 0;

  if (type === 'flat') {
    avgRate = parseFloat(document.getElementById('tariffFlatRate')?.value || 750);
  } else if (type === 'two_zone') {
    const dayRate = parseFloat(document.getElementById('tariffDayRate')?.value || 850);
    const nightRate = parseFloat(document.getElementById('tariffNightRate')?.value || 450);
    const dayStart = parseInt(document.getElementById('tariffDayStartWeekday')?.value || 6);
    const dayEnd = parseInt(document.getElementById('tariffDayEndWeekday')?.value || 22);
    const dayHours = dayEnd - dayStart;
    const nightHours = 24 - dayHours;
    // Assuming 60% day / 40% night consumption profile
    avgRate = dayRate * 0.6 + nightRate * 0.4;
  } else if (type === 'three_zone') {
    const peakRate = parseFloat(document.getElementById('tariffPeakRate')?.value || 950);
    const partialRate = parseFloat(document.getElementById('tariffPartialRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffOffPeakRate')?.value || 400);
    // Assuming 40% peak / 25% partial / 35% off-peak
    avgRate = peakRate * 0.4 + partialRate * 0.25 + offPeakRate * 0.35;
  } else if (type === 'four_zone') {
    const peakRate = parseFloat(document.getElementById('tariffFourPeakRate')?.value || 950);
    const dayRate = parseFloat(document.getElementById('tariffFourDayRate')?.value || 700);
    const offPeakRate = parseFloat(document.getElementById('tariffFourOffPeakRate')?.value || 400);
    const valleyRate = parseFloat(document.getElementById('tariffFourValleyRate')?.value || 200);
    avgRate = peakRate * 0.18 + dayRate * 0.15 + offPeakRate * 0.10 + valleyRate * 0.57;
  }

  const avgEl = document.getElementById('tariffAverageRate');
  if (avgEl) avgEl.value = Math.round(avgRate);
}

/**
 * Get current tariff configuration
 */
/**
 * Build distributionConfig from UI fields (distribution time windows).
 * Separate from energy tariffConfig — these define OSD distribution zones.
 */
function getDistributionConfig() {
  const type = document.getElementById('distTariffType')?.value || 'three_zone';
  return {
    type: type,
    twoZone: {
      weekday: {
        start: parseInt(document.getElementById('distDayStartWeekday')?.value || 6),
        end: parseInt(document.getElementById('distDayEndWeekday')?.value || 22)
      },
      weekend: {
        start: parseInt(document.getElementById('distDayStartWeekend')?.value || 6),
        end: parseInt(document.getElementById('distDayEndWeekend')?.value || 22)
      }
    },
    threeZone: {
      peak1: {
        start: parseInt(document.getElementById('distPeak1Start')?.value || 7),
        end: parseInt(document.getElementById('distPeak1End')?.value || 13)
      },
      peak2: {
        start: parseInt(document.getElementById('distPeak2Start')?.value || 16),
        end: parseInt(document.getElementById('distPeak2End')?.value || 21)
      },
      weekendOffPeak: document.getElementById('distWeekendOffPeak')?.checked !== false
    },
    fourZone: {
      peak1: {
        start: parseInt(document.getElementById('distFourPeak1Start')?.value || 7),
        end: parseInt(document.getElementById('distFourPeak1End')?.value || 13)
      },
      peak2: {
        start: parseInt(document.getElementById('distFourPeak2Start')?.value || 16),
        end: parseInt(document.getElementById('distFourPeak2End')?.value || 21)
      },
      valley: {
        start: parseInt(document.getElementById('distValleyStart')?.value || 1),
        end: parseInt(document.getElementById('distValleyEnd')?.value || 5)
      }
    }
  };
}

/**
 * Toggle visibility of distribution zone panels based on distTariffType.
 */
function onDistTariffTypeChange() {
  const type = document.getElementById('distTariffType')?.value || 'three_zone';
  const twoZoneEl = document.getElementById('distTwoZonePanel');
  const threeZoneEl = document.getElementById('distThreeZonePanel');
  const fourZoneEl = document.getElementById('distFourZonePanel');
  const valleyItemEl = document.getElementById('distributionValleyItem');
  if (twoZoneEl) twoZoneEl.style.display = type === 'two_zone' ? '' : 'none';
  if (threeZoneEl) threeZoneEl.style.display = type === 'three_zone' ? '' : 'none';
  if (fourZoneEl) fourZoneEl.style.display = type === 'four_zone' ? '' : 'none';
  if (valleyItemEl) valleyItemEl.style.display = type === 'four_zone' ? '' : 'none';
  // Update distribution average weights
  updateDistributionAverage();
  markUnsaved();
}

function getTariffConfig() {
  const type = document.getElementById('tariffType')?.value || 'two_zone';

  const config = {
    type: type,
    name: document.getElementById('tariffName')?.value || 'C12a',
    flatRate: parseFloat(document.getElementById('tariffFlatRate')?.value || 750),
    twoZone: {
      dayRate: parseFloat(document.getElementById('tariffDayRate')?.value || 850),
      nightRate: parseFloat(document.getElementById('tariffNightRate')?.value || 450),
      weekday: {
        start: parseInt(document.getElementById('tariffDayStartWeekday')?.value || 6),
        end: parseInt(document.getElementById('tariffDayEndWeekday')?.value || 22)
      },
      weekend: {
        start: parseInt(document.getElementById('tariffDayStartWeekend')?.value || 6),
        end: parseInt(document.getElementById('tariffDayEndWeekend')?.value || 13)
      }
    },
    threeZone: {
      peakRate: parseFloat(document.getElementById('tariffPeakRate')?.value || 950),
      partialRate: parseFloat(document.getElementById('tariffPartialRate')?.value || 700),
      offPeakRate: parseFloat(document.getElementById('tariffOffPeakRate')?.value || 400),
      peak1: {
        start: parseInt(document.getElementById('tariffPeakStart')?.value || 7),
        end: parseInt(document.getElementById('tariffPeakEnd')?.value || 13)
      },
      peak2: {
        start: parseInt(document.getElementById('tariffPeakStart2')?.value || 17),
        end: parseInt(document.getElementById('tariffPeakEnd2')?.value || 21)
      },
      partial: {
        start: parseInt(document.getElementById('tariffPartialStart')?.value || 13),
        end: parseInt(document.getElementById('tariffPartialEnd')?.value || 17)
      }
    },
    fourZone: {
      peakRate: parseFloat(document.getElementById('tariffFourPeakRate')?.value || 950),
      dayRate: parseFloat(document.getElementById('tariffFourDayRate')?.value || 700),
      offPeakRate: parseFloat(document.getElementById('tariffFourOffPeakRate')?.value || 400),
      valleyRate: parseFloat(document.getElementById('tariffFourValleyRate')?.value || 200),
      peak1: {
        start: parseInt(document.getElementById('tariffFourPeakStart')?.value || 7),
        end: parseInt(document.getElementById('tariffFourPeakEnd')?.value || 13)
      },
      peak2: {
        start: parseInt(document.getElementById('tariffFourPeakStart2')?.value || 16),
        end: parseInt(document.getElementById('tariffFourPeakEnd2')?.value || 21)
      },
      valley: {
        start: parseInt(document.getElementById('tariffFourValleyStart')?.value || 1),
        end: parseInt(document.getElementById('tariffFourValleyEnd')?.value || 5)
      }
    }
  };

  console.log('🕐 getTariffConfig() returning:', config.type, config);
  return config;
}

/**
 * Get hourly rates array for a given day type
 * @param {string} dayType - 'weekday' or 'weekend'
 * @returns {number[]} - Array of 24 rates [PLN/MWh]
 */
function getTariffHourlyRates(dayType = 'weekday') {
  const config = getTariffConfig();
  const rates = new Array(24).fill(0);

  if (config.type === 'flat') {
    rates.fill(config.flatRate);
  } else if (config.type === 'two_zone') {
    const zone = dayType === 'weekend' ? config.twoZone.weekend : config.twoZone.weekday;
    for (let h = 0; h < 24; h++) {
      if (h >= zone.start && h < zone.end) {
        rates[h] = config.twoZone.dayRate;
      } else {
        rates[h] = config.twoZone.nightRate;
      }
    }
  } else if (config.type === 'three_zone') {
    const { peak1, peak2, partial } = config.threeZone;
    for (let h = 0; h < 24; h++) {
      if ((h >= peak1.start && h < peak1.end) || (h >= peak2.start && h < peak2.end)) {
        rates[h] = config.threeZone.peakRate;
      } else if (h >= partial.start && h < partial.end) {
        rates[h] = config.threeZone.partialRate;
      } else {
        rates[h] = config.threeZone.offPeakRate;
      }
    }
  } else if (config.type === 'four_zone') {
    const { peak1, peak2, valley } = config.fourZone;
    for (let h = 0; h < 24; h++) {
      if (h >= valley.start && h < valley.end) {
        rates[h] = config.fourZone.valleyRate;
      } else if ((h >= peak1.start && h < peak1.end) || (h >= peak2.start && h < peak2.end)) {
        rates[h] = config.fourZone.peakRate;
      } else {
        rates[h] = config.fourZone.dayRate;
      }
    }
  }

  return rates;
}

// ======== Fixed Monthly Fees Functions ========

/**
 * Read fixed monthly fees config from DOM inputs.
 */
function getFixedMonthlyFeesConfig() {
  return {
    contractedPowerKw: parseFloat(document.getElementById('contractedPowerKw')?.value) || 50,
    distFixedRatePerKwMonth: parseFloat(document.getElementById('distFixedRatePerKw')?.value) || 9.14,
    osdSubscriptionFeeMonth: parseFloat(document.getElementById('osdSubscriptionFee')?.value) || 5.54,
    transitionFeeMonth: parseFloat(document.getElementById('transitionFee')?.value) || 0,
    supplierTradeFeeMonth: parseFloat(document.getElementById('supplierTradeFee')?.value) || 0
  };
}

/**
 * Recalculate and display the total fixed monthly fee.
 * Called from oninput handlers on each fixed monthly fee field.
 */
function updateFixedMonthlyTotal() {
  const cfg = getFixedMonthlyFeesConfig();
  const total = (cfg.distFixedRatePerKwMonth * cfg.contractedPowerKw) +
                cfg.osdSubscriptionFeeMonth +
                cfg.transitionFeeMonth +
                cfg.supplierTradeFeeMonth;
  const el = document.getElementById('totalFixedMonthly');
  if (el) el.value = total.toFixed(2);
}

// ============================================================================
// OSD Operator + Tariff Group Selector (auto-fill from tariff_presets.json)
// ============================================================================

let tariffPresetsData = null;

async function loadTariffPresets() {
  if (tariffPresetsData) return tariffPresetsData;
  try {
    const response = await fetch('tariff_presets.json');
    tariffPresetsData = await response.json();
    console.log('📋 Tariff presets loaded:', Object.keys(tariffPresetsData.operators));
    return tariffPresetsData;
  } catch (e) {
    console.error('Failed to load tariff presets:', e);
    return null;
  }
}

async function populateOsdOperatorDropdown() {
  const data = await loadTariffPresets();
  if (!data) return;

  const select = document.getElementById('osdOperator');
  if (!select) return;

  // Keep the "manual" option, clear the rest
  select.innerHTML = '<option value="">-- Wybierz ręcznie --</option>';

  for (const [key, op] of Object.entries(data.operators)) {
    const option = document.createElement('option');
    option.value = key;
    option.textContent = op.label;
    select.appendChild(option);
  }
}

async function onOsdOperatorChange() {
  const operatorKey = document.getElementById('osdOperator')?.value;
  const tariffSelect = document.getElementById('osdTariffGroup');
  if (!tariffSelect) return;

  // Clear tariff dropdown
  tariffSelect.innerHTML = '';

  if (!operatorKey) {
    tariffSelect.innerHTML = '<option value="">-- Najpierw wybierz operatora --</option>';
    return;
  }

  const data = await loadTariffPresets();
  if (!data || !data.operators[operatorKey]) return;

  const tariffs = data.operators[operatorKey].tariffs;
  tariffSelect.innerHTML = '<option value="">-- Wybierz taryfę --</option>';

  for (const [tariffKey, tariff] of Object.entries(tariffs)) {
    const option = document.createElement('option');
    option.value = tariffKey;
    option.textContent = `${tariffKey} — ${tariff.label.split('—')[1]?.trim() || tariff.voltage}`;
    tariffSelect.appendChild(option);
  }

  markUnsaved();
}

async function onOsdTariffGroupChange() {
  const operatorKey = document.getElementById('osdOperator')?.value;
  const tariffKey = document.getElementById('osdTariffGroup')?.value;

  if (!operatorKey || !tariffKey) return;

  const data = await loadTariffPresets();
  if (!data) return;

  const tariff = data.operators[operatorKey]?.tariffs[tariffKey];
  if (!tariff) return;

  console.log(`📋 Auto-filling from preset: ${operatorKey} / ${tariffKey}`, tariff);

  // 1. Distribution zone rates from touRates
  if (tariff.touRates) {
    setValueById('distributionPeak', tariff.touRates.peakRate || tariff.touRates.flatRate);
    setValueById('distributionDay', tariff.touRates.partialRate || tariff.touRates.dayRate || tariff.touRates.flatRate);
    setValueById('distributionNight', tariff.touRates.offPeakRate || tariff.touRates.nightRate || tariff.touRates.flatRate);
    if (tariff.touRates.valleyRate !== undefined) {
      setValueById('distributionValley', tariff.touRates.valleyRate);
    }
  }
  // Weighted average (from preset)
  setValueById('distribution', tariff.variableFees.distribution);
  setValueById('qualityFee', tariff.variableFees.qualityFee);

  // 2. Common fees from presets (OZE, kogeneracja, akcyza) - statutory 2026
  if (data.commonFees) {
    setValueById('ozeFee', data.commonFees.ozeFee);
    setValueById('cogenerationFee', data.commonFees.cogenerationFee);
    setValueById('exciseTax', data.commonFees.exciseTax);
  }

  // 3. Fixed monthly fees (section "Opłaty Stałe Miesięczne")
  if (tariff.fixedFees) {
    setValueById('distFixedRatePerKw', tariff.fixedFees.distFixedRatePerKwMonth);
    setValueById('osdSubscriptionFee', tariff.fixedFees.osdSubscriptionFeeMonth);
    setValueById('transitionFee', tariff.fixedFees.transitionFeeMonth);
  }

  // 4. Distribution time windows (OSD tariff zones — separate from energy ToU)
  if (tariff.touRates) {
    const mappedType = tariff.tariffType || 'flat';

    // Fill DISTRIBUTION time windows from OSD preset
    setValueById('distTariffType', mappedType);
    if (mappedType === 'two_zone') {
      if (tariff.touRates.weekday) {
        setValueById('distDayStartWeekday', tariff.touRates.weekday.dayStart || 6);
        setValueById('distDayEndWeekday', tariff.touRates.weekday.dayEnd || 22);
      }
      if (tariff.touRates.weekend) {
        setValueById('distDayStartWeekend', tariff.touRates.weekend.dayStart || 6);
        setValueById('distDayEndWeekend', tariff.touRates.weekend.dayEnd || 22);
      }
    } else if (mappedType === 'three_zone') {
      if (tariff.touRates.weekday) {
        if (tariff.touRates.weekday.peak1Start !== undefined) {
          setValueById('distPeak1Start', tariff.touRates.weekday.peak1Start);
          setValueById('distPeak1End', tariff.touRates.weekday.peak1End);
        }
        if (tariff.touRates.weekday.peak2Start !== undefined) {
          setValueById('distPeak2Start', tariff.touRates.weekday.peak2Start);
          setValueById('distPeak2End', tariff.touRates.weekday.peak2End);
        }
      }
      // 3-zone weekends = off-peak by default (most OSD tariffs)
      const woeEl = document.getElementById('distWeekendOffPeak');
      const weekendIsOffPeak = !tariff.touRates.weekend?.peak1Start;
      if (woeEl) woeEl.checked = weekendIsOffPeak;
    } else if (mappedType === 'four_zone') {
      if (tariff.touRates.weekday) {
        if (tariff.touRates.weekday.peak1Start !== undefined) {
          setValueById('distFourPeak1Start', tariff.touRates.weekday.peak1Start);
          setValueById('distFourPeak1End', tariff.touRates.weekday.peak1End);
        }
        if (tariff.touRates.weekday.peak2Start !== undefined) {
          setValueById('distFourPeak2Start', tariff.touRates.weekday.peak2Start);
          setValueById('distFourPeak2End', tariff.touRates.weekday.peak2End);
        }
        if (tariff.touRates.weekday.valleyStart !== undefined) {
          setValueById('distValleyStart', tariff.touRates.weekday.valleyStart);
          setValueById('distValleyEnd', tariff.touRates.weekday.valleyEnd);
        }
      }
    }
    onDistTariffTypeChange();
  }

  // 5. Sync Energy ToU tariff type with OSD tariff type
  if (tariff.tariffType) {
    // Map OSD type to energy ToU type
    const energyTouType = tariff.tariffType;
    const tariffTypeEl = document.getElementById('tariffType');
    if (tariffTypeEl) {
      tariffTypeEl.value = energyTouType;
      onTariffTypeChange();
    }

    // If four_zone, populate energy four_zone fields from preset
    if (tariff.tariffType === 'four_zone' && tariff.touRates) {
      setValueById('tariffFourPeakRate', tariff.touRates.peakRate || 950);
      setValueById('tariffFourDayRate', tariff.touRates.partialRate || tariff.touRates.dayRate || 700);
      setValueById('tariffFourOffPeakRate', tariff.touRates.offPeakRate || tariff.touRates.nightRate || 400);
      setValueById('tariffFourValleyRate', tariff.touRates.valleyRate || 200);
      if (tariff.touRates.weekday) {
        if (tariff.touRates.weekday.peak1Start !== undefined) {
          setValueById('tariffFourPeakStart', tariff.touRates.weekday.peak1Start);
          setValueById('tariffFourPeakEnd', tariff.touRates.weekday.peak1End);
        }
        if (tariff.touRates.weekday.peak2Start !== undefined) {
          setValueById('tariffFourPeakStart2', tariff.touRates.weekday.peak2Start);
          setValueById('tariffFourPeakEnd2', tariff.touRates.weekday.peak2End);
        }
        if (tariff.touRates.weekday.valleyStart !== undefined) {
          setValueById('tariffFourValleyStart', tariff.touRates.weekday.valleyStart);
          setValueById('tariffFourValleyEnd', tariff.touRates.weekday.valleyEnd);
        }
      }
      updateTariffVisualization();
    }

    // Fill energy ToU time windows from OSD preset
    if (tariff.touRates?.weekday) {
      const wd = tariff.touRates.weekday;
      if (energyTouType === 'two_zone') {
        setValueById('tariffDayStartWeekday', wd.dayStart || 6);
        setValueById('tariffDayEndWeekday', wd.dayEnd || 21);
        if (tariff.touRates.weekend) {
          setValueById('tariffDayStartWeekend', tariff.touRates.weekend.dayStart || 6);
          setValueById('tariffDayEndWeekend', tariff.touRates.weekend.dayEnd || 21);
        }
      } else if (energyTouType === 'three_zone') {
        if (wd.peak1Start !== undefined) {
          setValueById('tariffPeakStart', wd.peak1Start);
          setValueById('tariffPeakEnd', wd.peak1End);
        }
        if (wd.peak2Start !== undefined) {
          setValueById('tariffPeakStart2', wd.peak2Start);
          setValueById('tariffPeakEnd2', wd.peak2End);
        }
      }
    }
  }

  // 6. Update tariff name
  setValueById('tariffName', tariffKey);

  // 7. Trigger visualization and average recalculation for energy ToU
  if (typeof updateTariffVisualization === 'function') updateTariffVisualization();
  if (typeof updateTariffAverageRate === 'function') updateTariffAverageRate();

  // 6. Recalculate totals
  updateTotalEnergyPrice();
  updateFixedMonthlyTotal();

  markUnsaved();
  updateEnergyCostSummary();
  console.log(`✅ Preset applied: ${operatorKey} ${tariffKey} — dystr.szczyt=${tariff.touRates?.peakRate}, dzień=${tariff.touRates?.partialRate}, noc=${tariff.touRates?.offPeakRate}, jakość=${tariff.variableFees.qualityFee}`);
}

// Make tariff functions globally available
window.onTariffTypeChange = onTariffTypeChange;
window.getTariffConfig = getTariffConfig;
window.getTariffHourlyRates = getTariffHourlyRates;
window.updateTariffVisualization = updateTariffVisualization;
window.updateTariffAverageRate = updateTariffAverageRate;
window.updateFixedMonthlyTotal = updateFixedMonthlyTotal;
window.onOsdOperatorChange = onOsdOperatorChange;
window.onOsdTariffGroupChange = onOsdTariffGroupChange;
window.updateDistributionAverage = updateDistributionAverage;
window.onDistTariffTypeChange = onDistTariffTypeChange;
window.getDistributionConfig = getDistributionConfig;
window.switchEnergyTab = switchEnergyTab;
window.navigateToEnergyTab = navigateToEnergyTab;
window.updateEnergyCostSummary = updateEnergyCostSummary;

/**
 * Switch between energy cost tabs in the unified panel.
 */
function switchEnergyTab(tabId, btn) {
  document.querySelectorAll('.energy-tab-panel').forEach(p => p.style.display = 'none');
  const panel = document.getElementById('energyTab_' + tabId);
  if (panel) panel.style.display = '';
  document.querySelectorAll('#energyTabBar .energy-tab').forEach(t => {
    t.style.color = '#666'; t.style.fontWeight = '600'; t.style.borderBottomColor = 'transparent';
  });
  if (btn) {
    btn.style.color = '#1565c0'; btn.style.fontWeight = '700'; btn.style.borderBottomColor = '#1565c0';
  }
}

/**
 * Navigate to a specific energy tab from the summary tiles.
 * Finds the correct tab button and triggers switchEnergyTab with scroll.
 */
function navigateToEnergyTab(tabId) {
  const tabBar = document.getElementById('energyTabBar');
  if (!tabBar) return;
  const buttons = tabBar.querySelectorAll('.energy-tab');
  const tabMap = ['dist', 'tou', 'pricing', 'fees', 'capacity', 'monthly'];
  const idx = tabMap.indexOf(tabId);
  const btn = idx >= 0 ? buttons[idx] : null;
  switchEnergyTab(tabId, btn);
  const panel = document.getElementById('energyTab_' + tabId);
  if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/**
 * Update the summary card in the unified energy cost panel.
 */
function updateEnergyCostSummary() {
  const v = id => parseFloat(document.getElementById(id)?.value) || 0;
  const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  const distP = v('distributionPeak'), distD = v('distributionDay'), distN = v('distributionNight'), distV = v('distributionValley');
  const quality = v('qualityFee'), oze = v('ozeFee'), cogen = v('cogenerationFee'), excise = v('exciseTax');
  const tariffAvgEl = document.getElementById('tariffAverageRate');
  const distAvg = Math.round(v('distribution'));
  const energyAvg = tariffAvgEl ? Math.round(parseFloat(tariffAvgEl.textContent) || 0) : 0;
  const statutory = Math.round(quality + oze + cogen + excise);
  const som = v('somRate') || 0.2194;
  const capacityVal = Math.round(som * 1000);
  const total = distAvg + energyAvg + statutory + capacityVal;

  el('summDistAvg', distAvg);
  el('summEnergyAvg', energyAvg);
  el('summStatutory', statutory);
  el('summCapacityVal', capacityVal);
  el('summTotal', total);
  el('summFixedMonthly', Math.round(v('totalFixedMonthly')));
  const distType = document.getElementById('distTariffType')?.value || 'three_zone';
  const valleyStr = distType === 'four_zone' ? ` | dolina ${Math.round(distV)}` : '';
  el('summDistZones', `szczyt ${Math.round(distP)} | dzień ${Math.round(distD)} | noc ${Math.round(distN)}${valleyStr}`);
  const sH = parseInt(document.getElementById('selectedHoursStart')?.value) || 7;
  const eH = parseInt(document.getElementById('selectedHoursEnd')?.value) || 22;
  el('summCapacity', `${capacityVal} PLN/MWh (${sH}-${eH} Pn-Pt)`);
}

/**
 * Compute weighted average distribution from 3 zone fields.
 * Approximate weights: peak ~20%, day ~40%, night ~40% (typical Polish tariff).
 * For flat tariffs all 3 are equal so weights don't matter.
 */
function updateDistributionAverage() {
  const peak = parseFloat(document.getElementById('distributionPeak')?.value) || 0;
  const day = parseFloat(document.getElementById('distributionDay')?.value) || 0;
  const night = parseFloat(document.getElementById('distributionNight')?.value) || 0;
  const valley = parseFloat(document.getElementById('distributionValley')?.value) || 0;

  // Use distribution zone type to determine weights
  const distType = document.getElementById('distTariffType')?.value || 'flat';
  let avg;
  if (distType === 'flat') {
    avg = peak; // all zones should be equal for flat
  } else if (distType === 'two_zone') {
    // day ~60%, night ~40%
    avg = day * 0.6 + night * 0.4;
  } else if (distType === 'four_zone') {
    // four_zone: peak ~18%, day ~15%, night ~10%, valley ~57% (deep night + weekends)
    avg = peak * 0.18 + day * 0.15 + night * 0.10 + valley * 0.57;
  } else {
    // three_zone: peak ~20%, day ~35%, night ~45%
    avg = peak * 0.20 + day * 0.35 + night * 0.45;
  }

  setValueById('distribution', Math.round(avg * 100) / 100);
  updateTotalEnergyPrice();
  markUnsaved();
}

// Initialize tariff section and add event listeners
document.addEventListener('DOMContentLoaded', function() {
  initTariffSection();
  populateOsdOperatorDropdown();
  setTimeout(updateEnergyCostSummary, 500); // update summary after init

  // Add change listeners for visualization updates
  const tariffInputs = [
    'tariffType', 'tariffFlatRate',
    'tariffDayRate', 'tariffNightRate',
    'tariffDayStartWeekday', 'tariffDayEndWeekday',
    'tariffDayStartWeekend', 'tariffDayEndWeekend',
    'tariffPeakRate', 'tariffPartialRate', 'tariffOffPeakRate',
    'tariffPeakStart', 'tariffPeakEnd',
    'tariffPeakStart2', 'tariffPeakEnd2',
    'tariffPartialStart', 'tariffPartialEnd'
  ];

  tariffInputs.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => {
        updateTariffVisualization();
        updateTariffAverageRate();
      });
      el.addEventListener('input', () => {
        updateTariffVisualization();
        updateTariffAverageRate();
      });
    }
  });
});

// ============================================================================
// RDN Arbitrage ↔ Ceny RDN widget validation
// ============================================================================

/**
 * Check if RDN hourly prices are available for BESS arbitrage.
 * Called when user toggles the RDN arbitrage checkbox.
 */
function checkRdnDataForArbitrage() {
  const statusEl = document.getElementById('rdnArbitrageStatus');
  const overlayStatusEl = document.getElementById('rdnOverlayStatus');

  const checkbox = document.getElementById('bessPriceArbitrageEnabled');
  const isEnabled = checkbox?.checked;

  // Check if RDN prices are cached from "Ceny RDN" widget
  let hasData = false;
  let dataLabel = '';
  try {
    const cachedInfo = localStorage.getItem('rdn_scenario_info');
    const cachedPrices = localStorage.getItem('rdn_hourly_prices');
    if (cachedInfo && cachedPrices) {
      const info = JSON.parse(cachedInfo);
      const prices = JSON.parse(cachedPrices);
      if (prices.length >= 8000) {
        hasData = true;
        dataLabel = `${info.scenarioName || 'RDN'} — ${prices.length} godz., śr. ${(info.avgPrice || 0).toFixed(0)} PLN/MWh`;
      }
    }
  } catch (e) { /* ignore */ }

  const okMsg = `<span style="color:#2e7d32">✓ ${dataLabel}</span>`;
  const noDataMsg = '<span style="color:#c62828">⚠ Brak danych RDN — wgraj ceny w sekcji "Ceny RDN" poniżej</span>';
  const offMsg = 'Ceny z widgetu "Ceny RDN" poniżej';

  if (statusEl) {
    statusEl.innerHTML = !isEnabled ? offMsg : (hasData ? okMsg : noDataMsg);
  }
  if (overlayStatusEl) {
    overlayStatusEl.innerHTML = !isEnabled ? offMsg : (hasData ? okMsg : noDataMsg);
  }
}

// ============================================================================
// RDN Dynamic Pricing - Rynek Dnia Następnego (Day-Ahead Market)
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
  // RDN enabled checkbox → toggle panel
  const rdnCheckbox = document.getElementById('rdnPricingEnabled');
  const rdnPanel = document.getElementById('rdnPricingPanel');
  if (rdnCheckbox && rdnPanel) {
    rdnCheckbox.addEventListener('change', function() {
      rdnPanel.style.display = this.checked ? 'block' : 'none';
      if (this.checked) {
        loadSavedRdnScenarios();
      }
      markUnsaved();
    });
  }

  // RDN file upload handler
  const rdnFileInput = document.getElementById('rdnFileInput');
  if (rdnFileInput) {
    rdnFileInput.addEventListener('change', handleRdnFileUpload);
  }

  // RDN scenario select handler
  const rdnSelect = document.getElementById('rdnScenarioSelect');
  if (rdnSelect) {
    rdnSelect.addEventListener('change', function() {
      const scenarioId = parseInt(this.value);
      if (scenarioId) {
        selectRdnScenario(scenarioId);
      } else {
        clearRdnScenarioInfo();
      }
    });
  }

  // Restore RDN state from config
  restoreRdnState();
});

/**
 * Handle RDN CSV/Excel file upload
 */
async function handleRdnFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const statusEl = document.getElementById('rdnUploadStatus');
  if (statusEl) statusEl.textContent = 'Wysyłanie...';

  // Get scenario metadata from UI inputs
  const scenarioName = document.getElementById('rdnScenarioName')?.value?.trim()
    || file.name.replace(/\.(csv|xlsx|xls)$/i, '');
  const scenarioYear = parseInt(document.getElementById('rdnScenarioYear')?.value) || 2025;
  const scenarioType = document.getElementById('rdnScenarioType')?.value || 'historical';

  const formData = new FormData();
  formData.append('file', file);

  // Build URL with required query parameters
  const params = new URLSearchParams({
    name: scenarioName,
    year: scenarioYear,
    scenario_type: scenarioType
  });

  try {
    const response = await fetch(`/api/db/prices/upload-tge-csv?${params.toString()}`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errText}`);
    }

    const result = await response.json();
    console.log('RDN upload result:', result);

    const stats = result.stats || {};
    if (statusEl) {
      statusEl.innerHTML = `<span style="color:#2e7d32">Wgrano: ${scenarioName} (${result.data_points || '?'} godzin, śr. ${stats.avg_price?.toFixed(0) || '?'} PLN/MWh)</span>`;
    }

    // Refresh scenarios list and auto-select the new one
    await loadSavedRdnScenarios();

    if (result.id) {
      const rdnSelect = document.getElementById('rdnScenarioSelect');
      if (rdnSelect) {
        rdnSelect.value = result.id;
        await selectRdnScenario(result.id);
      }
    }
  } catch (err) {
    console.error('RDN upload error:', err);
    if (statusEl) {
      statusEl.innerHTML = `<span style="color:#c62828">Błąd: ${err.message}</span>`;
    }
  }

  // Reset file input
  event.target.value = '';
}

/**
 * Download CSV template for RDN price upload
 * Generates a sample CSV matching TGE Fixing format: Date;Fixing 1
 * Format: D.MM.YYYY HH:MM (European, matching real TGE exports)
 */
function downloadRdnTemplate() {
  const year = parseInt(document.getElementById('rdnScenarioYear')?.value) || 2025;

  // Use semicolon separator and European format to match real TGE files
  const lines = ['Date;Fixing 1'];

  // Realistic RDN hourly price profile [PLN/MWh]
  const samplePrices = [
    // Night (00-05): low/negative (renewables oversupply)
    180, 150, 130, 120, 125, 140,
    // Morning ramp (06-09): rising demand
    220, 310, 420, 480,
    // Midday solar dip (10-14): solar pushes prices down
    390, 350, 320, 310, 330,
    // Evening peak (15-20): highest (no solar + peak demand)
    420, 510, 580, 620, 560, 490,
    // Night wind-down (21-23)
    380, 300, 230
  ];

  // Generate 3 sample days
  for (let day = 1; day <= 3; day++) {
    for (let h = 0; h < 24; h++) {
      // TGE format: D.MM.YYYY HH:MM (no leading zero for day)
      const dateStr = `${day}.01.${year} ${String(h).padStart(2, '0')}:00`;
      // Use comma as decimal separator (European)
      const price = samplePrices[h] + Math.round((Math.random() - 0.5) * 60);
      const priceStr = price.toFixed(2).replace('.', ',');
      lines.push(`${dateStr};${priceStr}`);
    }
  }

  lines.push('');
  lines.push('# ===== INSTRUKCJA =====');
  lines.push('# Format kompatybilny z eksportem TGE Fixing I');
  lines.push('# Kolumna "Date": D.MM.YYYY HH:MM lub DD.MM.YYYY HH:MM');
  lines.push('# Kolumna "Fixing 1": cena w PLN/MWh (przecinek lub kropka jako separator)');
  lines.push('# Ceny mogą być ujemne (np. -200 podczas nadpodaży OZE)');
  lines.push('# Uzupełnij dane za cały rok: 8760 godzin (365 x 24)');
  lines.push('# Można też wgrać bezpośrednio plik .xlsx z TGE');
  lines.push('# Źródło: https://tge.pl/energia-elektryczna-rdn');

  const bom = '\uFEFF'; // BOM for proper Excel encoding
  const csv = bom + lines.join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `szablon_ceny_rdn_${year}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Load saved RDN price scenarios from database
 */
async function loadSavedRdnScenarios() {
  const selectEl = document.getElementById('rdnScenarioSelect');
  if (!selectEl) return;

  try {
    const response = await fetch('/api/db/prices/scenarios-for-arbitrage');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const scenarios = await response.json();
    console.log('RDN scenarios loaded:', scenarios);

    // Clear existing options
    selectEl.innerHTML = '<option value="">-- Wybierz scenariusz --</option>';

    if (Array.isArray(scenarios)) {
      scenarios.forEach(s => {
        const option = document.createElement('option');
        option.value = s.id;
        const avgPrice = s.stats?.avg_price || s.avg_price;
        const avgLabel = avgPrice ? ` (śr. ${avgPrice.toFixed(0)} PLN/MWh, ${s.data_points || '?'} godz.)` : '';
        const yearLabel = s.year ? ` [${s.year}]` : '';
        option.textContent = `${s.name || s.scenario_name || 'Scenariusz #' + s.id}${yearLabel}${avgLabel}`;
        selectEl.appendChild(option);
      });
    }
  } catch (err) {
    console.error('Error loading RDN scenarios:', err);
  }
}

/**
 * Select an RDN price scenario and load its details
 */
async function selectRdnScenario(scenarioId) {
  const infoEl = document.getElementById('rdnScenarioInfo');

  try {
    // Try to use cached data first (avoids fetch errors during module transitions)
    const cachedInfo = localStorage.getItem('rdn_scenario_info');
    const cachedPrices = localStorage.getItem('rdn_hourly_prices');
    if (cachedInfo && cachedPrices) {
      const info = JSON.parse(cachedInfo);
      if (info.scenarioId == scenarioId && info.dataPoints > 0) {
        // Cache hit - update UI from localStorage without API call
        document.getElementById('rdnInfoName').textContent = info.scenarioName || `Scenariusz #${scenarioId}`;
        document.getElementById('rdnInfoYear').textContent = info.year || '-';
        document.getElementById('rdnInfoPoints').textContent = info.dataPoints;
        document.getElementById('rdnInfoAvg').textContent = (info.avgPrice || 0).toFixed(1);
        document.getElementById('rdnInfoMin').textContent = (info.minPrice || 0).toFixed(1);
        document.getElementById('rdnInfoMax').textContent = (info.maxPrice || 0).toFixed(1);
        if (infoEl) infoEl.style.display = 'block';
        console.log(`RDN scenario #${scenarioId} restored from cache: ${info.dataPoints} prices, avg=${(info.avgPrice || 0).toFixed(1)} PLN/MWh`);
        return;
      }
    }

    // Fetch hourly prices from API
    const response = await fetch(`/api/db/prices/${scenarioId}/hourly-array`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    console.log('RDN scenario data:', data);

    const prices = data.prices_plnmwh || data.prices || data.hourly_prices || data;
    const priceArray = Array.isArray(prices) ? prices : [];

    if (priceArray.length === 0) {
      throw new Error('Brak danych cenowych w scenariuszu');
    }

    // Calculate statistics
    const validPrices = priceArray.filter(p => p !== null && p !== undefined && !isNaN(p));
    const avg = validPrices.reduce((a, b) => a + b, 0) / validPrices.length;
    const min = Math.min(...validPrices);
    const max = Math.max(...validPrices);

    // Get scenario name from select dropdown
    const selectEl = document.getElementById('rdnScenarioSelect');
    const selectedOption = selectEl?.options[selectEl.selectedIndex];
    const scenarioName = selectedOption?.textContent || `Scenariusz #${scenarioId}`;

    // Determine year from data or name
    const yearMatch = scenarioName.match(/\[(\d{4})\]/);
    const year = data.year || (yearMatch ? parseInt(yearMatch[1]) : null);

    // Update info panel
    document.getElementById('rdnInfoName').textContent = scenarioName.replace(/\s*\[.*?\]\s*\(.*?\)/, '').trim();
    document.getElementById('rdnInfoYear').textContent = year || '-';
    document.getElementById('rdnInfoPoints').textContent = priceArray.length;
    document.getElementById('rdnInfoAvg').textContent = avg.toFixed(1);
    document.getElementById('rdnInfoMin').textContent = min.toFixed(1);
    document.getElementById('rdnInfoMax').textContent = max.toFixed(1);

    if (infoEl) infoEl.style.display = 'block';

    // Cache hourly prices in localStorage for Economics module
    const rdnInfo = {
      scenarioId,
      scenarioName: scenarioName.replace(/\s*\[.*?\]\s*\(.*?\)/, '').trim(),
      year,
      avgPrice: avg,
      minPrice: min,
      maxPrice: max,
      dataPoints: priceArray.length
    };
    localStorage.setItem('rdn_hourly_prices', JSON.stringify(priceArray));
    localStorage.setItem('rdn_scenario_info', JSON.stringify(rdnInfo));

    // Broadcast RDN prices to shell for centralized price config
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({
        type: 'RDN_PRICES_CHANGED',
        data: {
          hourlyPricesPlnMwh: priceArray,
          scenarioInfo: rdnInfo
        }
      }, '*');
      console.log('[Settings] RDN prices broadcast to shell:', priceArray.length, 'points');
    }

    markUnsaved();
    console.log(`RDN scenario #${scenarioId} selected: ${priceArray.length} prices, avg=${avg.toFixed(1)} PLN/MWh`);

  } catch (err) {
    console.error('Error loading RDN scenario:', err);
    if (infoEl) infoEl.style.display = 'none';
    const statusEl = document.getElementById('rdnUploadStatus');
    if (statusEl) {
      statusEl.innerHTML = `<span style="color:#c62828">Błąd ładowania scenariusza: ${err.message}</span>`;
    }
  }
}

/**
 * Clear RDN scenario info panel
 */
function clearRdnScenarioInfo() {
  const infoEl = document.getElementById('rdnScenarioInfo');
  if (infoEl) infoEl.style.display = 'none';
  localStorage.removeItem('rdn_hourly_prices');
  localStorage.removeItem('rdn_scenario_info');
  // Broadcast clear to shell
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'RDN_PRICES_CHANGED', data: null }, '*');
  }
}

/**
 * Get current RDN pricing config from UI state
 */
function getRdnPricingConfig() {
  const enabled = document.getElementById('rdnPricingEnabled')?.checked || false;
  const scenarioId = parseInt(document.getElementById('rdnScenarioSelect')?.value) || null;

  if (!enabled || !scenarioId) {
    return {
      enabled,
      scenarioId: null,
      scenarioName: '',
      year: null,
      avgPrice: null,
      minPrice: null,
      maxPrice: null,
      dataPoints: 0
    };
  }

  // Read cached info
  try {
    const info = JSON.parse(localStorage.getItem('rdn_scenario_info') || '{}');
    return {
      enabled: true,
      scenarioId: info.scenarioId || scenarioId,
      scenarioName: info.scenarioName || '',
      year: info.year || null,
      avgPrice: info.avgPrice || null,
      minPrice: info.minPrice || null,
      maxPrice: info.maxPrice || null,
      dataPoints: info.dataPoints || 0
    };
  } catch (e) {
    return { enabled: true, scenarioId, scenarioName: '', year: null, avgPrice: null, minPrice: null, maxPrice: null, dataPoints: 0 };
  }
}

/**
 * Restore RDN state from saved config on page load
 */
function restoreRdnState() {
  try {
    const savedSettings = JSON.parse(localStorage.getItem('pv_system_settings') || '{}');
    const rdnConfig = savedSettings.rdnPricingConfig || DEFAULT_CONFIG.rdnPricingConfig;

    const checkbox = document.getElementById('rdnPricingEnabled');
    const panel = document.getElementById('rdnPricingPanel');

    if (checkbox) checkbox.checked = rdnConfig.enabled || false;
    if (panel) panel.style.display = rdnConfig.enabled ? 'block' : 'none';

    if (rdnConfig.enabled) {
      // Load scenarios and restore selection
      loadSavedRdnScenarios().then(() => {
        if (rdnConfig.scenarioId) {
          const selectEl = document.getElementById('rdnScenarioSelect');
          if (selectEl) {
            selectEl.value = rdnConfig.scenarioId;
            selectRdnScenario(rdnConfig.scenarioId);
          }
        }
      });
    }
    // Update arbitrage status after RDN state is restored
    setTimeout(() => checkRdnDataForArbitrage(), 500);
  } catch (e) {
    console.error('Error restoring RDN state:', e);
  }
}

