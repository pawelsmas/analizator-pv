/**
 * Quick PV Estimator Module
 * Simple calculator for PV installation estimation without consumption data
 * Integrates with USTAWIENIA module for location, prices, and CAPEX data
 */

console.log('Quick Estimator module loaded');

// Default yields per installation type [kWh/kWp/year]
let YIELDS = {
  ground_s: 1050,
  ground_ew: 980,
  roof_ew: 950,
  carport: 900
};

// P-factors for scenarios
const P_FACTORS = {
  P50: 1.00,
  P75: 0.97,
  P90: 0.94
};

// Default CAPEX tiers [PLN/kWp] based on capacity
let CAPEX_TIERS = [
  { min: 50, max: 150, price: 3444 },
  { min: 150, max: 300, price: 2880 },
  { min: 300, max: 1000, price: 2360 },
  { min: 1000, max: 3000, price: 1972 },
  { min: 3000, max: 10000, price: 1725 },
  { min: 10000, max: 50000, price: 1582 }
];

// Additional parameters from settings
let degradationRate = 0.5; // % per year
let systemLifetime = 25; // years (analysisPeriod)
let discountRate = 7; // % for NPV calculations
let curtailmentLossPercent = 0; // % straty od ograniczeń (0-export, clipping)
let locationInfo = null; // { city, latitude, longitude, elevation }

// Settings received from shell
let settings = null;
let settingsLoaded = false;

/**
 * Get CAPEX per kWp for given capacity
 */
function getCapexPerKwp(capacityKwp) {
  for (const tier of CAPEX_TIERS) {
    if (capacityKwp >= tier.min && capacityKwp < tier.max) {
      return tier.price;
    }
  }
  // If above all tiers, use last tier price
  if (capacityKwp >= CAPEX_TIERS[CAPEX_TIERS.length - 1].max) {
    return CAPEX_TIERS[CAPEX_TIERS.length - 1].price;
  }
  // If below all tiers, use first tier price
  return CAPEX_TIERS[0].price;
}

/**
 * Format number with Polish locale (space as thousand separator, comma as decimal)
 */
function formatNumber(num, decimals = 0) {
  return num.toLocaleString('pl-PL', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

/**
 * Format currency for compact display
 */
function formatCurrency(num) {
  if (num >= 1000000) {
    return formatNumber(num / 1000000, 2) + ' mln';
  } else if (num >= 1000) {
    return formatNumber(num / 1000, 0) + ' tys.';
  }
  return formatNumber(num, 0);
}

/**
 * Calculate NPV with degradation
 */
function calculateNPV(initialSavings, capex, years, degradation, discount) {
  let npv = -capex;
  for (let year = 1; year <= years; year++) {
    const degradedSavings = initialSavings * Math.pow(1 - degradation / 100, year - 1);
    npv += degradedSavings / Math.pow(1 + discount / 100, year);
  }
  return npv;
}

/**
 * Calculate LCOE (Levelized Cost of Energy)
 */
function calculateLCOE(capex, productionMwh, degradation, discount, years) {
  let totalProduction = 0;
  for (let year = 1; year <= years; year++) {
    const yearProduction = productionMwh * Math.pow(1 - degradation / 100, year - 1);
    totalProduction += yearProduction / Math.pow(1 + discount / 100, year);
  }
  return totalProduction > 0 ? capex / totalProduction : 0;
}

/**
 * Get selected installation type from radio buttons
 */
function getSelectedInstallationType() {
  const selected = document.querySelector('input[name="installationType"]:checked');
  return selected ? selected.value : 'ground_s';
}

/**
 * Get selected scenario from radio buttons
 */
function getSelectedScenario() {
  const selected = document.querySelector('input[name="scenario"]:checked');
  return selected ? selected.value : 'P50';
}

/**
 * Calculate and display results
 */
function calculate() {
  // Get input values
  const powerKwp = parseFloat(document.getElementById('powerKwp').value) || 100;
  const installationType = getSelectedInstallationType();
  const scenario = getSelectedScenario();
  const energyPrice = parseFloat(document.getElementById('energyPrice').value) || 1000;

  // Get curtailment loss from input
  const curtailmentInput = document.getElementById('curtailmentLoss');
  curtailmentLossPercent = curtailmentInput ? parseFloat(curtailmentInput.value) || 0 : 0;

  // Get yield for installation type
  const baseYield = YIELDS[installationType] || 1050;

  // Apply P-factor
  const pFactor = P_FACTORS[scenario] || 1.0;
  const adjustedYield = baseYield * pFactor;

  // ============================================
  // OBLICZENIA PRODUKCJI I GODZIN PEŁNEGO OBCIĄŻENIA
  // ============================================

  // Roczna produkcja BRUTTO (przed ograniczeniami) [MWh]
  const annualProductionMWh = (powerKwp * adjustedYield) / 1000;

  // Godziny pełnego obciążenia BRUTTO [h/rok]
  const fullLoadHoursGross = (annualProductionMWh * 1000) / powerKwp;

  // Współczynnik strat od ograniczeń
  const curtailmentLossRatio = curtailmentLossPercent / 100;

  // Efektywna roczna produkcja (po ograniczeniach) [MWh]
  const effectiveAnnualProductionMWh = annualProductionMWh * (1 - curtailmentLossRatio);

  // Godziny pełnego obciążenia PO OGRANICZENIACH [h/rok]
  const fullLoadHoursEffective = (effectiveAnnualProductionMWh * 1000) / powerKwp;

  // ============================================
  // OBLICZENIA FINANSOWE
  // ============================================

  const productionMwh = effectiveAnnualProductionMWh;
  const savingsPln = productionMwh * energyPrice;
  const capexPerKwp = getCapexPerKwp(powerKwp);
  const totalCapex = powerKwp * capexPerKwp;
  const paybackYears = savingsPln > 0 ? totalCapex / savingsPln : Infinity;
  const npv = calculateNPV(savingsPln, totalCapex, systemLifetime, degradationRate, discountRate);
  const lcoe = calculateLCOE(totalCapex, productionMwh, degradationRate, discountRate, systemLifetime);
  const irr = estimateIRR(paybackYears);

  // ============================================
  // UPDATE UI - PRIMARY RESULTS
  // ============================================

  document.getElementById('resultProduction').textContent = formatNumber(productionMwh, 1);
  document.getElementById('resultFLH').textContent = formatNumber(fullLoadHoursEffective, 0);

  // ============================================
  // UPDATE UI - FINANCIAL RESULTS
  // ============================================

  document.getElementById('resultSavings').textContent = formatCurrency(savingsPln) + ' PLN';
  document.getElementById('resultCapex').textContent = formatCurrency(totalCapex) + ' PLN';
  document.getElementById('resultPayback').textContent = formatNumber(paybackYears, 1);

  const npvEl = document.getElementById('resultNPV');
  if (npvEl) {
    npvEl.textContent = formatCurrency(npv) + ' PLN';
    npvEl.style.color = npv >= 0 ? '#059669' : '#dc2626';
  }

  // Update NPV period label
  const npvPeriodEl = document.getElementById('npvPeriod');
  if (npvPeriodEl) {
    npvPeriodEl.textContent = `${systemLifetime} lat`;
  }

  // ============================================
  // UPDATE UI - SUMMARY BAR
  // ============================================

  const summaryBar = document.getElementById('summaryBar');
  if (summaryBar) {
    summaryBar.style.display = 'flex';
    document.getElementById('summaryCapexKwp').textContent = formatNumber(capexPerKwp, 0) + ' PLN';
    document.getElementById('summaryIRR').textContent = '~' + irr + '%';
    document.getElementById('summaryLCOE').textContent = formatNumber(lcoe, 0) + ' PLN/MWh';
  }

  // ============================================
  // UPDATE UI - DETAILS TABLE
  // ============================================

  const tbody = document.querySelector('#detailsTable tbody');
  let detailsHtml = `
    <tr><td>Moc instalacji</td><td>${formatNumber(powerKwp, 0)} kWp</td></tr>
    <tr><td>Typ instalacji</td><td>${getInstallationTypeName(installationType)}</td></tr>
    <tr><td>Scenariusz</td><td>${scenario} (${(pFactor * 100).toFixed(0)}%)</td></tr>
    <tr><td>Uzysk bazowy</td><td>${formatNumber(baseYield, 0)} kWh/kWp/rok</td></tr>
    <tr><td>Uzysk po korekcie</td><td>${formatNumber(adjustedYield, 0)} kWh/kWp/rok</td></tr>
    <tr style="background:#1e293b"><td colspan="2"><strong>⏱️ Godziny pełnego obciążenia</strong></td></tr>
    <tr><td>FLH brutto</td><td>${formatNumber(fullLoadHoursGross, 0)} h/rok</td></tr>
    <tr><td>Straty od ograniczeń</td><td>${formatNumber(curtailmentLossPercent, 1)}%</td></tr>
    <tr><td>FLH efektywne</td><td><strong>${formatNumber(fullLoadHoursEffective, 0)} h/rok</strong></td></tr>
    <tr style="background:#1e293b"><td colspan="2"><strong>⚡ Produkcja energii</strong></td></tr>
    <tr><td>Produkcja brutto</td><td>${formatNumber(annualProductionMWh, 1)} MWh/rok</td></tr>
    <tr><td>Produkcja efektywna</td><td><strong>${formatNumber(effectiveAnnualProductionMWh, 1)} MWh/rok</strong></td></tr>
    <tr style="background:#1e293b"><td colspan="2"><strong>💰 Parametry finansowe</strong></td></tr>
    <tr><td>CAPEX/kWp</td><td>${formatNumber(capexPerKwp, 0)} PLN</td></tr>
    <tr><td>Cena energii</td><td>${formatNumber(energyPrice, 0)} PLN/MWh</td></tr>
    <tr><td>Degradacja</td><td>${formatNumber(degradationRate, 1)}%/rok</td></tr>
    <tr><td>Okres analizy</td><td>${systemLifetime} lat</td></tr>
    <tr><td>Stopa dyskontowa</td><td>${formatNumber(discountRate, 1)}%</td></tr>
    <tr><td>LCOE</td><td>${formatNumber(lcoe, 0)} PLN/MWh</td></tr>
    <tr><td>IRR szacunkowe</td><td>~${irr}%</td></tr>
  `;

  if (locationInfo && locationInfo.city) {
    detailsHtml = `
      <tr style="background:#1e293b"><td colspan="2"><strong>📍 Lokalizacja</strong></td></tr>
      <tr><td>Miasto</td><td>${locationInfo.city || 'N/A'}</td></tr>
      <tr><td>Współrzędne</td><td>${locationInfo.latitude?.toFixed(2) || 'N/A'}°N, ${locationInfo.longitude?.toFixed(2) || 'N/A'}°E</td></tr>
    ` + detailsHtml;
  }

  tbody.innerHTML = detailsHtml;

  // Update type card yields display
  updateTypeCardYields();

  // Notify shell about calculation
  notifyShell({
    type: 'QUICK_ESTIMATE',
    data: {
      powerKwp,
      installationType,
      scenario,
      annualProductionMWh,
      effectiveAnnualProductionMWh,
      fullLoadHoursGross,
      fullLoadHoursEffective,
      curtailmentLossPercent,
      savingsPln,
      totalCapex,
      capexPerKwp,
      paybackYears,
      npv,
      lcoe,
      irr,
      locationInfo
    }
  });
}

/**
 * Update type card yield displays
 */
function updateTypeCardYields() {
  const typeYields = {
    ground_s: YIELDS.ground_s,
    ground_ew: YIELDS.ground_ew,
    roof_ew: YIELDS.roof_ew,
    carport: YIELDS.carport
  };

  document.querySelectorAll('.type-card').forEach(card => {
    const type = card.dataset.type;
    const yieldEl = card.querySelector('.type-yield');
    if (yieldEl && typeYields[type]) {
      yieldEl.textContent = `${typeYields[type]} kWh/kWp`;
    }
  });
}

/**
 * Get human-readable installation type name
 */
function getInstallationTypeName(type) {
  const names = {
    ground_s: 'Grunt Południe',
    ground_ew: 'Grunt Wschód-Zachód',
    roof_ew: 'Dach Wschód-Zachód',
    carport: 'Carport'
  };
  return names[type] || type;
}

/**
 * Estimate IRR based on payback period (rough approximation)
 */
function estimateIRR(paybackYears) {
  if (paybackYears <= 0 || !isFinite(paybackYears)) return 0;
  const roughIRR = (1 / paybackYears) * 100 * 0.7;
  return Math.round(roughIRR);
}

/**
 * Notify shell about events
 */
function notifyShell(message) {
  if (window.parent !== window) {
    window.parent.postMessage(message, '*');
  }
}

/**
 * Handle messages from shell
 */
window.addEventListener('message', (event) => {
  const { type, data } = event.data || {};

  switch (type) {
    case 'SETTINGS_UPDATED':
      if (data) {
        settings = data;
        updateFromSettings(data);
      }
      break;

    case 'SHARED_DATA_RESPONSE':
      if (data && data.settings) {
        settings = data.settings;
        updateFromSettings(data.settings);
      }
      break;

    case 'SCENARIO_CHANGED':
      if (data && data.scenario) {
        setScenario(data.scenario);
        calculate();
      }
      break;

    case 'INIT_ESTIMATOR':
      if (data) {
        if (data.powerKwp) {
          document.getElementById('powerKwp').value = data.powerKwp;
          updatePresetButtons(data.powerKwp);
        }
        if (data.installationType) {
          setInstallationType(data.installationType);
        }
        calculate();
      }
      break;
  }
});

/**
 * Set installation type programmatically
 */
function setInstallationType(type) {
  const radio = document.querySelector(`input[name="installationType"][value="${type}"]`);
  if (radio) {
    radio.checked = true;
    updateTypeCardSelection();
  }
}

/**
 * Set scenario programmatically
 */
function setScenario(scenario) {
  const radio = document.querySelector(`input[name="scenario"][value="${scenario}"]`);
  if (radio) {
    radio.checked = true;
    updateScenarioPillSelection();
  }
}

/**
 * Update type card visual selection
 */
function updateTypeCardSelection() {
  document.querySelectorAll('.type-card').forEach(card => {
    const radio = card.querySelector('input[type="radio"]');
    card.classList.toggle('selected', radio && radio.checked);
  });
}

/**
 * Update scenario pill visual selection
 */
function updateScenarioPillSelection() {
  document.querySelectorAll('.scenario-pill').forEach(pill => {
    const radio = pill.querySelector('input[type="radio"]');
    pill.classList.toggle('selected', radio && radio.checked);
  });
}

/**
 * Update preset button active state
 */
function updatePresetButtons(power) {
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.power) === power);
  });
}

/**
 * Update all parameters from settings
 */
function updateFromSettings(s) {
  console.log('📥 Updating estimator from settings:', s);
  settingsLoaded = true;

  // Update yields from settings
  if (s.pvYield_ground_s) YIELDS.ground_s = s.pvYield_ground_s;
  if (s.pvYield_ground_ew) YIELDS.ground_ew = s.pvYield_ground_ew;
  if (s.pvYield_roof_ew) YIELDS.roof_ew = s.pvYield_roof_ew;
  if (s.pvYield_carport) YIELDS.carport = s.pvYield_carport;

  // Update energy price
  if (s.totalEnergyPrice) {
    document.getElementById('energyPrice').value = Math.round(s.totalEnergyPrice);
  }

  // Update degradation rate
  if (s.degradationRate !== undefined) {
    degradationRate = s.degradationRate;
  }

  // Update system lifetime
  if (s.analysisPeriod !== undefined) {
    systemLifetime = s.analysisPeriod;
  }

  // Update discount rate
  if (s.discountRate !== undefined) {
    discountRate = s.discountRate;
  }

  // Update CAPEX tiers
  if (s.capexTiers && Array.isArray(s.capexTiers) && s.capexTiers.length > 0) {
    CAPEX_TIERS = s.capexTiers.map(tier => ({
      min: tier.min || 0,
      max: tier.max || Infinity,
      price: tier.capex || tier.sale || tier.price || 2500
    }));
    console.log('📊 CAPEX tiers updated:', CAPEX_TIERS);
  }

  // Update location info
  if (s.latitude && s.longitude) {
    locationInfo = {
      city: s.city || s.locationCity || null,
      latitude: s.latitude,
      longitude: s.longitude,
      elevation: s.elevation || s.altitude || null
    };
  }

  updateSettingsInfo();
  updateTypeCardYields();
  calculate();
}

/**
 * Update settings info panel
 */
function updateSettingsInfo() {
  const infoEl = document.getElementById('settingsInfo');
  if (!infoEl) return;

  if (settingsLoaded && settings) {
    let infoHtml = '<div class="settings-badge">✅ Dane z USTAWIEŃ</div>';

    if (locationInfo && locationInfo.city) {
      infoHtml += `<div class="location-info">📍 ${locationInfo.city} (${locationInfo.latitude?.toFixed(2)}°N)</div>`;
    }

    infoHtml += `<div class="params-info">
      Cena: ${formatNumber(parseFloat(document.getElementById('energyPrice').value) || 0, 0)} PLN/MWh |
      Degradacja: ${formatNumber(degradationRate, 1)}%/rok |
      Okres: ${systemLifetime} lat
    </div>`;

    infoEl.innerHTML = infoHtml;
    infoEl.style.display = 'block';
  } else {
    infoEl.innerHTML = '<div class="settings-badge warning">⚠️ Używam domyślnych wartości. Skonfiguruj USTAWIENIA.</div>';
    infoEl.style.display = 'block';
  }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', function() {
  // Request settings from shell
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
    window.parent.postMessage({ type: 'REQUEST_SCENARIO' }, '*');
  }

  // ============================================
  // SETUP UI INTERACTIONS
  // ============================================

  // Power preset buttons
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const power = parseInt(this.dataset.power);
      document.getElementById('powerKwp').value = power;
      updatePresetButtons(power);
      calculate();
    });
  });

  // Type cards
  document.querySelectorAll('.type-card').forEach(card => {
    card.addEventListener('click', function() {
      const radio = this.querySelector('input[type="radio"]');
      if (radio) {
        radio.checked = true;
        updateTypeCardSelection();
        calculate();
      }
    });
  });

  // Scenario pills
  document.querySelectorAll('.scenario-pill').forEach(pill => {
    pill.addEventListener('click', function() {
      const radio = this.querySelector('input[type="radio"]');
      if (radio) {
        radio.checked = true;
        updateScenarioPillSelection();
        calculate();
      }
    });
  });

  // Power input change
  const powerInput = document.getElementById('powerKwp');
  if (powerInput) {
    powerInput.addEventListener('input', function() {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => {
        updatePresetButtons(parseInt(this.value));
        calculate();
      }, 300);
    });
  }

  // Other inputs
  ['energyPrice', 'curtailmentLoss'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', calculate);
      el.addEventListener('input', function() {
        clearTimeout(this._debounce);
        this._debounce = setTimeout(calculate, 300);
      });
    }
  });

  // Initial setup
  updateTypeCardSelection();
  updateScenarioPillSelection();
  updatePresetButtons(100);
  calculate();
  updateSettingsInfo();
});
