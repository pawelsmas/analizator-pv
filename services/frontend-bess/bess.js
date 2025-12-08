console.log('🔋 bess.js LOADED v=1.0 - timestamp:', new Date().toISOString());

// ============================================
// NUMBER FORMATTING - European format
// ============================================

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

// ============================================
// DATA STORAGE
// ============================================

let variants = {};
let currentVariant = 'A';
let systemSettings = null;
let analysisResults = null;

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  console.log('📱 DOMContentLoaded - BESS module');

  // Request data from parent shell
  requestSharedData();
  requestSettingsFromShell();

  // Fallback: try localStorage
  setTimeout(() => {
    if (!analysisResults || Object.keys(variants).length === 0) {
      console.log('⏳ No data from shell, trying localStorage...');
      loadFromLocalStorage();
    }
  }, 500);
});

// Listen for messages from parent shell
window.addEventListener('message', (event) => {
  const { type, data } = event.data || {};

  // Shell sends SHARED_DATA_RESPONSE
  if (type === 'SHARED_DATA_RESPONSE') {
    console.log('📥 Received SHARED_DATA_RESPONSE from shell:', data);
    handleSharedData(data);
  }

  // Shell sends SETTINGS_UPDATED
  if (type === 'SETTINGS_UPDATED') {
    console.log('📥 Received SETTINGS_UPDATED from shell:', data);
    systemSettings = data;
    window.systemSettings = data;
    updateDisplay();
  }

  if (type === 'VARIANT_CHANGED') {
    console.log('📥 Received VARIANT_CHANGED:', data);
    if (data && data.variant) {
      selectVariant(data.variant);
    }
  }

  // Also listen for SCENARIO_CHANGED (P50/P75/P90)
  if (type === 'SCENARIO_CHANGED') {
    console.log('📥 Received SCENARIO_CHANGED:', data);
    // Refresh data
    requestSharedData();
  }
});

function requestSharedData() {
  if (window.parent !== window) {
    console.log('📤 Requesting shared data from shell...');
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  }
}

function requestSettingsFromShell() {
  if (window.parent !== window) {
    console.log('📤 Requesting settings from shell...');
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  }
}

function handleSharedData(data) {
  if (!data) {
    console.log('❌ handleSharedData: no data');
    return;
  }

  console.log('📦 handleSharedData - data keys:', Object.keys(data));
  analysisResults = data.analysisResults;

  // Parse variants - try key_variants first (object format), then scenarios (array format)
  if (data.analysisResults?.key_variants) {
    console.log('📊 Using key_variants format');
    parseKeyVariants(data.analysisResults.key_variants);
  } else if (data.analysisResults?.scenarios) {
    console.log('📊 Using scenarios format');
    parseVariants(data.analysisResults.scenarios);
  } else {
    console.log('❌ No key_variants or scenarios found in analysisResults');
  }

  // Get master variant
  if (data.masterVariantKey && variants[data.masterVariantKey]) {
    currentVariant = data.masterVariantKey;
    console.log('📌 Using masterVariantKey:', currentVariant);
  } else if (data.masterVariant && typeof data.masterVariant === 'string' && variants[data.masterVariant]) {
    currentVariant = data.masterVariant;
    console.log('📌 Using masterVariant:', currentVariant);
  }

  updateDisplay();
}

function parseKeyVariants(keyVariants) {
  variants = {};

  if (!keyVariants || typeof keyVariants !== 'object') return;

  Object.entries(keyVariants).forEach(([key, s]) => {
    variants[key] = {
      key: key,
      name: `Wariant ${key}`,
      capacity: s.capacity,
      production: s.production,
      self_consumed: s.self_consumed,
      exported: s.exported,
      auto_consumption_pct: s.auto_consumption_pct,
      coverage_pct: s.coverage_pct,
      threshold: s.threshold,
      // BESS fields
      bess_power_kw: s.bess_power_kw || 0,
      bess_energy_kwh: s.bess_energy_kwh || 0,
      bess_charged_kwh: s.bess_charged_kwh || 0,
      bess_discharged_kwh: s.bess_discharged_kwh || s.bess_self_consumed_from_bess_kwh || 0,
      bess_curtailed_kwh: s.bess_curtailed_kwh || 0,
      bess_cycles_equivalent: s.bess_cycles_equivalent || 0,
      bess_self_consumed_direct_kwh: s.bess_self_consumed_direct_kwh || 0,
      bess_self_consumed_from_bess_kwh: s.bess_self_consumed_from_bess_kwh || 0,
      bess_grid_import_kwh: s.bess_grid_import_kwh || 0,
      // Baseline for comparison
      baseline_no_bess: s.baseline_no_bess || {}
    };
  });

  console.log('📊 Parsed key_variants:', Object.keys(variants));
}

function loadFromLocalStorage() {
  try {
    // Load analysis results - try different localStorage keys
    const storedResults = localStorage.getItem('pv_analysis_results') || localStorage.getItem('analysisResults');
    if (storedResults) {
      analysisResults = JSON.parse(storedResults);
      console.log('📦 Loaded analysisResults from localStorage');

      // Try key_variants first, then scenarios
      if (analysisResults?.key_variants) {
        parseKeyVariants(analysisResults.key_variants);
      } else if (analysisResults?.scenarios) {
        parseVariants(analysisResults.scenarios);
      }
    }

    // Load settings
    const storedSettings = localStorage.getItem('systemSettings');
    if (storedSettings) {
      systemSettings = JSON.parse(storedSettings);
      window.systemSettings = systemSettings;
    }

    // Load master variant
    const masterVariant = localStorage.getItem('masterVariant');
    if (masterVariant) {
      try {
        const parsed = JSON.parse(masterVariant);
        if (parsed.variantKey && variants[parsed.variantKey]) {
          currentVariant = parsed.variantKey;
        }
      } catch {
        // masterVariant might be a plain string
        if (variants[masterVariant]) {
          currentVariant = masterVariant;
        }
      }
    }

    updateDisplay();
  } catch (e) {
    console.error('Error loading from localStorage:', e);
    showNoData();
  }
}

function parseVariants(scenarios) {
  variants = {};

  if (!scenarios || !Array.isArray(scenarios)) return;

  scenarios.forEach(s => {
    const variantKey = s.threshold_key || s.variant || 'A';
    variants[variantKey] = {
      key: variantKey,
      capacity: s.capacity,
      production: s.production,
      self_consumed: s.self_consumed,
      exported: s.exported,
      auto_consumption_pct: s.auto_consumption_pct,
      coverage_pct: s.coverage_pct,
      threshold: s.threshold,
      // BESS fields
      bess_power_kw: s.bess_power_kw || 0,
      bess_energy_kwh: s.bess_energy_kwh || 0,
      bess_charged_kwh: s.bess_charged_kwh || 0,
      bess_discharged_kwh: s.bess_discharged_kwh || s.bess_self_consumed_from_bess_kwh || 0,
      bess_curtailed_kwh: s.bess_curtailed_kwh || 0,
      bess_cycles_equivalent: s.bess_cycles_equivalent || 0,
      bess_self_consumed_direct_kwh: s.bess_self_consumed_direct_kwh || 0,
      bess_self_consumed_from_bess_kwh: s.bess_self_consumed_from_bess_kwh || 0,
      bess_grid_import_kwh: s.bess_grid_import_kwh || 0,
      // Baseline for comparison
      baseline_no_bess: s.baseline_no_bess || {}
    };
  });

  console.log('📊 Parsed variants:', Object.keys(variants));
}

// ============================================
// VARIANT SELECTION
// ============================================

function selectVariant(variantKey) {
  if (!variants[variantKey]) {
    console.warn('Variant not found:', variantKey);
    return;
  }

  currentVariant = variantKey;

  // Update button states
  document.querySelectorAll('.variant-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.variant === variantKey);
  });

  // Notify parent shell
  if (window.parent !== window) {
    window.parent.postMessage({
      type: 'VARIANT_CHANGED',
      data: { variant: variantKey, source: 'bess' }
    }, '*');
  }

  updateDisplay();
}

// ============================================
// DISPLAY UPDATE
// ============================================

function updateDisplay() {
  console.log('🔋 updateDisplay() called, currentVariant:', currentVariant);

  // Update variant buttons descriptions
  updateVariantDescriptions();

  const variant = variants[currentVariant];

  if (!variant) {
    showNoData();
    return;
  }

  // Check if BESS is enabled
  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;

  if (!hasBess) {
    showBessDisabled();
    return;
  }

  // Show content
  hideNoData();
  document.getElementById('bessDisabledBanner').style.display = 'none';
  document.getElementById('bessContent').style.display = 'grid';

  // Update all sections
  updateMainCard(variant);
  updateEnergyMetrics(variant);
  updateEnergyFlow(variant);
  updateComparison(variant);
  updateEconomics(variant);
  updateTechnicalParams(variant);
  generateDegradationTable(variant);
  updateDataInfo(variant);
}

function updateVariantDescriptions() {
  ['A', 'B', 'C', 'D'].forEach(key => {
    const descEl = document.getElementById(`desc${key}`);
    if (descEl && variants[key]) {
      const v = variants[key];
      const capacityMW = (v.capacity / 1000).toFixed(2);
      const bessInfo = v.bess_power_kw > 0 ? ` + BESS ${v.bess_power_kw}kW` : '';
      descEl.textContent = `${capacityMW} MWp${bessInfo}`;
    } else if (descEl) {
      descEl.textContent = 'Brak danych';
    }
  });
}

function updateMainCard(variant) {
  const powerKw = variant.bess_power_kw;
  const energyKwh = variant.bess_energy_kwh;
  const duration = powerKw > 0 ? energyKwh / powerKw : 0;

  document.getElementById('bessConfigMain').textContent =
    `${formatNumberEU(powerKw, 0)} kW / ${formatNumberEU(energyKwh, 0)} kWh`;
  document.getElementById('bessDurationMain').textContent =
    `Duration: ${formatNumberEU(duration, 1)}h`;
}

function updateEnergyMetrics(variant) {
  const bessDischargedMWh = (variant.bess_discharged_kwh || 0) / 1000;
  const bessCurtailedMWh = (variant.bess_curtailed_kwh || 0) / 1000;
  const bessCycles = variant.bess_cycles_equivalent || 0;
  const production = variant.production / 1000; // kWh -> MWh

  // Auto-consumption increase
  const bessAuto = variant.auto_consumption_pct || 0;
  const baseline = variant.baseline_no_bess || {};
  let baselineAuto = baseline.auto_consumption_pct || 0;

  // Estimate baseline if not available
  if (!baselineAuto && bessDischargedMWh > 0) {
    const bessSelfConsumed = variant.self_consumed / 1000;
    const bessFromBattery = bessDischargedMWh;
    const baselineSelfConsumed = bessSelfConsumed - bessFromBattery;
    baselineAuto = production > 0 ? (baselineSelfConsumed / (production) * 100) : 0;
  }

  const autoIncrease = bessAuto - baselineAuto;

  document.getElementById('bessAutoIncrease').textContent = `+${formatNumberEU(autoIncrease, 1)}%`;
  document.getElementById('bessAutoCompare').textContent =
    `${formatNumberEU(baselineAuto, 1)}% → ${formatNumberEU(bessAuto, 1)}%`;

  // Energy from battery
  document.getElementById('bessEnergyFromBattery').textContent = formatNumberEU(bessDischargedMWh, 1);
  document.getElementById('bessCyclesInfo').textContent = `${formatNumberEU(bessCycles, 0)} cykli ekw./rok`;

  // Curtailment
  document.getElementById('bessCurtailmentTotal').textContent = formatNumberEU(bessCurtailedMWh, 1);
  const curtailmentPct = production > 0 ? (bessCurtailedMWh / production * 100) : 0;
  document.getElementById('bessCurtailmentPct').textContent = `${formatNumberEU(curtailmentPct, 1)}% produkcji PV`;

  // Cycles
  document.getElementById('bessCyclesYear').textContent = formatNumberEU(bessCycles, 0);
  const lifetimeCycles = systemSettings?.bessCycleLifetime || 6000;
  document.getElementById('bessCyclesLifetime').textContent = `Lifetime: ${formatNumberEU(lifetimeCycles, 0)} cykli`;
}

function updateEnergyFlow(variant) {
  const chargedMWh = (variant.bess_charged_kwh || 0) / 1000;
  const dischargedMWh = (variant.bess_discharged_kwh || 0) / 1000;
  const curtailedMWh = (variant.bess_curtailed_kwh || 0) / 1000;
  const efficiency = chargedMWh > 0 ? (dischargedMWh / chargedMWh * 100) : 0;

  document.getElementById('bessToBattery').textContent = `${formatNumberEU(chargedMWh, 1)} MWh`;
  document.getElementById('bessFromBattery').textContent = `${formatNumberEU(dischargedMWh, 1)} MWh`;
  document.getElementById('bessCurtailed').textContent = `${formatNumberEU(curtailedMWh, 1)} MWh`;
  document.getElementById('bessEfficiency').textContent = `${formatNumberEU(efficiency, 1)} %`;
}

function updateComparison(variant) {
  const bessAuto = variant.auto_consumption_pct || 0;
  const bessSelfConsumedMWh = (variant.self_consumed || 0) / 1000;
  const bessExportedMWh = (variant.exported || 0) / 1000;
  const bessCoverage = variant.coverage_pct || 0;
  const bessProduction = (variant.production || 0) / 1000;

  // Baseline values
  const baseline = variant.baseline_no_bess || {};
  let baselineAuto = baseline.auto_consumption_pct || 0;
  let baselineSelfConsumedMWh = (baseline.self_consumed || 0) / 1000;
  let baselineExportedMWh = (baseline.exported || 0) / 1000;
  let baselineCoverage = baseline.coverage_pct || 0;

  // Estimate baseline if not available
  const bessDischargedMWh = (variant.bess_discharged_kwh || 0) / 1000;
  const bessChargedMWh = (variant.bess_charged_kwh || 0) / 1000;

  if (!baselineAuto && bessDischargedMWh > 0) {
    baselineSelfConsumedMWh = bessSelfConsumedMWh - bessDischargedMWh;
    baselineExportedMWh = bessChargedMWh; // What would have been exported
    baselineAuto = bessProduction > 0 ? (baselineSelfConsumedMWh / bessProduction * 100) : 0;
    // Estimate coverage based on grid import change
    const gridImport = (variant.bess_grid_import_kwh || 0) / 1000;
    const totalConsumption = bessSelfConsumedMWh + gridImport;
    baselineCoverage = totalConsumption > 0 ? (baselineSelfConsumedMWh / totalConsumption * 100) : 0;
  }

  // Update table
  document.getElementById('baselineAuto').textContent = `${formatNumberEU(baselineAuto, 1)}%`;
  document.getElementById('bessAuto').textContent = `${formatNumberEU(bessAuto, 1)}%`;
  document.getElementById('diffAuto').textContent = `+${formatNumberEU(bessAuto - baselineAuto, 1)}%`;

  document.getElementById('baselineSelfConsumed').textContent = formatNumberEU(baselineSelfConsumedMWh, 1);
  document.getElementById('bessSelfConsumed').textContent = formatNumberEU(bessSelfConsumedMWh, 1);
  document.getElementById('diffSelfConsumed').textContent =
    `+${formatNumberEU(bessSelfConsumedMWh - baselineSelfConsumedMWh, 1)}`;

  document.getElementById('baselineExported').textContent = formatNumberEU(baselineExportedMWh, 1);
  document.getElementById('bessExported').textContent = formatNumberEU(bessExportedMWh, 1);
  const diffExported = document.getElementById('diffExported');
  diffExported.textContent = formatNumberEU(bessExportedMWh - baselineExportedMWh, 1);
  diffExported.className = bessExportedMWh <= baselineExportedMWh ? 'diff-positive' : 'diff-negative';

  document.getElementById('baselineCoverage').textContent = `${formatNumberEU(baselineCoverage, 1)}%`;
  document.getElementById('bessCoverage').textContent = `${formatNumberEU(bessCoverage, 1)}%`;
  document.getElementById('diffCoverage').textContent = `+${formatNumberEU(bessCoverage - baselineCoverage, 1)}%`;
}

function updateEconomics(variant) {
  const settings = systemSettings || {};
  const powerKw = variant.bess_power_kw;
  const energyKwh = variant.bess_energy_kwh;

  const capexPerKwh = settings.bessCapexPerKwh || 1500;
  const capexPerKw = settings.bessCapexPerKw || 300;
  const opexPct = settings.bessOpexPctPerYear || 1.5;
  const lifetime = settings.bessLifetimeYears || 15;
  const analysisPeriod = 25;

  const bessCapex = energyKwh * capexPerKwh + powerKw * capexPerKw;
  const bessOpex = bessCapex * (opexPct / 100);

  document.getElementById('bessEconCapex').textContent = formatNumberEU(bessCapex / 1000, 0);
  document.getElementById('bessEconCapexDetail').textContent =
    `${formatNumberEU(capexPerKwh, 0)} PLN/kWh + ${formatNumberEU(capexPerKw, 0)} PLN/kW`;

  document.getElementById('bessEconOpex').textContent = formatNumberEU(bessOpex / 1000, 1);
  document.getElementById('bessEconOpexPct').textContent = `${formatNumberEU(opexPct, 1)}% CAPEX/rok`;

  const needsReplacement = analysisPeriod > lifetime;
  document.getElementById('bessEconReplacement').textContent = needsReplacement ? lifetime.toString() : 'N/A';
  document.getElementById('bessEconReplacementCost').textContent = needsReplacement
    ? `Koszt: ${formatNumberEU(bessCapex * 0.7 / 1000, 0)} tys. PLN`
    : 'Brak wymiany w okresie';

  // Degradation params
  const degYear1 = settings.bessDegradationYear1 || 3.0;
  const degYearN = settings.bessDegradationPctPerYear || 2.0;
  document.getElementById('bessEconDegradationParams').textContent =
    `Rok 1: ${formatNumberEU(degYear1, 1)}% | Lata 2+: ${formatNumberEU(degYearN, 1)}%/rok | Żywotność: ${lifetime} lat`;
}

function updateTechnicalParams(variant) {
  const settings = systemSettings || {};
  const powerKw = variant.bess_power_kw;
  const energyKwh = variant.bess_energy_kwh;
  const duration = powerKw > 0 ? energyKwh / powerKw : 0;

  document.getElementById('bessPowerKw').textContent = `${formatNumberEU(powerKw, 0)} kW`;
  document.getElementById('bessEnergyKwh').textContent = `${formatNumberEU(energyKwh, 0)} kWh`;
  document.getElementById('bessDuration').textContent = `${formatNumberEU(duration, 1)} h`;
  document.getElementById('bessRoundtrip').textContent = `${settings.bessRoundtripEfficiency || 90}%`;
  document.getElementById('bessSocMin').textContent = `${settings.bessSocMin || 10}%`;
  document.getElementById('bessSocMax').textContent = `${settings.bessSocMax || 90}%`;
  document.getElementById('bessDegYear1').textContent = `${settings.bessDegradationYear1 || 3.0}%`;
  document.getElementById('bessDegYearN').textContent = `${settings.bessDegradationPctPerYear || 2.0}%/rok`;
  document.getElementById('bessLifetime').textContent = `${settings.bessLifetimeYears || 15} lat`;
  document.getElementById('bessCapexKwh').textContent = `${formatNumberEU(settings.bessCapexPerKwh || 1500, 0)} PLN/kWh`;
  document.getElementById('bessCapexKw').textContent = `${formatNumberEU(settings.bessCapexPerKw || 300, 0)} PLN/kW`;
}

function generateDegradationTable(variant) {
  const settings = systemSettings || {};
  const tbody = document.getElementById('bessDegradationTableBody');
  if (!tbody) return;

  const energyKwh = variant.bess_energy_kwh;
  const dischargedKwh = variant.bess_discharged_kwh || 0;
  const degYear1 = settings.bessDegradationYear1 || 3.0;
  const degYearN = settings.bessDegradationPctPerYear || 2.0;
  const lifetime = settings.bessLifetimeYears || 15;
  const analysisPeriod = 25;

  // Energy factor based on first year discharge
  const baseEnergyFactor = energyKwh > 0 ? dischargedKwh / energyKwh : 0;

  let html = '';
  let currentCapacity = energyKwh;
  let cumulativeEnergyMWh = 0;
  let batteryNumber = 1;

  for (let year = 1; year <= analysisPeriod; year++) {
    let degradationPct;
    let yearInBatteryLife = ((year - 1) % lifetime) + 1;

    if (yearInBatteryLife === 1) {
      degradationPct = degYear1;
      if (year > 1) {
        batteryNumber++;
        currentCapacity = energyKwh;
      }
    } else {
      degradationPct = degYearN;
    }

    currentCapacity = currentCapacity * (1 - degradationPct / 100);
    const energyMWh = (currentCapacity * baseEnergyFactor) / 1000;
    cumulativeEnergyMWh += energyMWh;

    const eolPct = (currentCapacity / energyKwh) * 100;
    const isNearEOL = eolPct < 85;
    const isEOL = eolPct < 80;

    let status, statusColor;
    if (yearInBatteryLife === lifetime || isEOL) {
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
      <tr style="${yearInBatteryLife === lifetime ? 'background:#fff3e0;' : ''}">
        <td style="font-weight:600;">${year}</td>
        <td>${formatNumberEU(energyKwh, 0)}</td>
        <td style="color:${degradationPct > 2.5 ? '#e74c3c' : '#888'}">
          -${formatNumberEU(degradationPct, 1)}%
          ${yearInBatteryLife === 1 ? '<span style="font-size:10px;color:#9c27b0">(rok 1)</span>' : ''}
        </td>
        <td style="font-weight:500;">${formatNumberEU(currentCapacity, 0)}</td>
        <td>${formatNumberEU(energyMWh, 2)}</td>
        <td style="font-weight:600;">${formatNumberEU(cumulativeEnergyMWh, 1)}</td>
        <td style="color:${statusColor};font-size:12px;">${status}</td>
      </tr>
    `;
  }

  tbody.innerHTML = html;

  // Update total energy
  document.getElementById('bessEconTotalEnergy').textContent = formatNumberEU(cumulativeEnergyMWh, 0);
  document.getElementById('bessEconTotalEnergyPeriod').textContent = `przez ${analysisPeriod} lat`;
}

function updateDataInfo(variant) {
  const infoEl = document.getElementById('dataInfo');
  if (infoEl && variant) {
    const capacityMW = (variant.capacity / 1000).toFixed(2);
    infoEl.textContent = `Wariant ${currentVariant}: ${capacityMW} MWp | BESS ${variant.bess_power_kw} kW / ${variant.bess_energy_kwh} kWh`;
  }
}

// ============================================
// UI STATE MANAGEMENT
// ============================================

function showNoData() {
  document.getElementById('noDataMessage').style.display = 'block';
  document.getElementById('bessContent').style.display = 'none';
  document.getElementById('bessDisabledBanner').style.display = 'none';
}

function hideNoData() {
  document.getElementById('noDataMessage').style.display = 'none';
}

function showBessDisabled() {
  document.getElementById('bessDisabledBanner').style.display = 'flex';
  document.getElementById('bessContent').style.display = 'none';
  document.getElementById('noDataMessage').style.display = 'none';
}

// ============================================
// ACTIONS
// ============================================

function refreshData() {
  console.log('🔄 Refreshing BESS data...');
  requestSharedData();
  requestSettingsFromShell();
}

function exportBessData() {
  const variant = variants[currentVariant];
  if (!variant) {
    alert('Brak danych do eksportu');
    return;
  }

  // Prepare data for Excel
  const settings = systemSettings || {};
  const data = [
    ['MAGAZYN ENERGII BESS - Eksport danych'],
    [''],
    ['Konfiguracja'],
    ['Moc [kW]', variant.bess_power_kw],
    ['Pojemność [kWh]', variant.bess_energy_kwh],
    ['Duration [h]', variant.bess_power_kw > 0 ? variant.bess_energy_kwh / variant.bess_power_kw : 0],
    [''],
    ['Metryki energetyczne'],
    ['Ładowanie [MWh/rok]', variant.bess_charged_kwh / 1000],
    ['Rozładowanie [MWh/rok]', variant.bess_discharged_kwh / 1000],
    ['Curtailment [MWh/rok]', variant.bess_curtailed_kwh / 1000],
    ['Cykle ekwiwalentne/rok', variant.bess_cycles_equivalent],
    [''],
    ['Parametry ekonomiczne'],
    ['CAPEX per kWh [PLN]', settings.bessCapexPerKwh || 1500],
    ['CAPEX per kW [PLN]', settings.bessCapexPerKw || 300],
    ['OPEX [% CAPEX/rok]', settings.bessOpexPctPerYear || 1.5],
    ['Żywotność [lat]', settings.bessLifetimeYears || 15],
    ['Degradacja rok 1 [%]', settings.bessDegradationYear1 || 3.0],
    ['Degradacja lata 2+ [%/rok]', settings.bessDegradationPctPerYear || 2.0]
  ];

  const ws = XLSX.utils.aoa_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'BESS');

  XLSX.writeFile(wb, `BESS_Export_Wariant_${currentVariant}.xlsx`);
  console.log('📥 BESS data exported');
}

// Expose functions globally
window.selectVariant = selectVariant;
window.refreshData = refreshData;
window.exportBessData = exportBessData;

console.log('📦 bess.js fully loaded');
