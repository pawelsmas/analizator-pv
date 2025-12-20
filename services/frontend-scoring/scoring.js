/**
 * KPI / Scoring Module
 * ====================
 * Multi-criteria scoring for PV offers comparison.
 *
 * Based on savings vs baseline energy costs.
 * Uses 4 buckets: Value, Robustness, Tech, ESG.
 */

console.log('🏆 scoring.js LOADED - timestamp:', new Date().toISOString());

// API URL (nginx reverse proxy)
const API_URL = '/api/economics';

// State
let scoringResults = null;
let selectedOfferId = null;
let compareOfferIds = [];

// Current parameters
let currentProfile = 'cfo';
let currentHorizon = 25;
let currentConservativeYield = 0.90;
let currentConservativePrices = 0.90;
let customWeights = {
  value: 0.40,
  robustness: 0.30,
  tech: 0.20,
  esg: 0.10
};

// Weight profiles (from backend)
const WEIGHT_PROFILES = {
  cfo: { value: 0.50, robustness: 0.30, tech: 0.15, esg: 0.05 },
  esg: { value: 0.25, robustness: 0.20, tech: 0.20, esg: 0.35 },
  operations: { value: 0.30, robustness: 0.25, tech: 0.35, esg: 0.10 },
  custom: { value: 0.40, robustness: 0.30, tech: 0.20, esg: 0.10 }
};

// ============================================
// NUMBER FORMATTING
// ============================================

function formatNumberEU(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) return '-';
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

function formatPercent(value, decimals = 0) {
  if (value === null || value === undefined || isNaN(value)) return '-';
  return formatNumberEU(value * 100, decimals) + '%';
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  console.log('🏆 Scoring module initialized');

  // Listen for postMessage from shell
  window.addEventListener('message', handlePostMessage);

  // Try to load variants from localStorage
  loadVariantsFromStorage();

  // Load weight profiles from backend
  loadWeightProfiles();
});

function handlePostMessage(event) {
  const data = event.data;
  if (!data || !data.type) return;

  console.log('📨 Received message:', data.type);

  switch (data.type) {
    case 'ANALYSIS_RESULTS':
    case 'VARIANTS_UPDATED':
      if (data.data) {
        processVariantsData(data.data);
      }
      break;

    case 'CONSUMPTION_DATA':
      if (data.data) {
        window.consumptionData = data.data;
      }
      break;
  }
}

function loadVariantsFromStorage() {
  try {
    const stored = localStorage.getItem('analysisResults');
    if (stored) {
      const data = JSON.parse(stored);
      processVariantsData(data);
    }
  } catch (e) {
    console.warn('Could not load variants from storage:', e);
  }
}

async function loadWeightProfiles() {
  try {
    const response = await fetch(`${API_URL}/scoring/profiles`);
    if (response.ok) {
      const profiles = await response.json();
      console.log('📊 Loaded weight profiles:', profiles);
      // Update local profiles with backend values
      Object.assign(WEIGHT_PROFILES, profiles);
    }
  } catch (e) {
    console.warn('Could not load weight profiles:', e);
  }
}

// ============================================
// PROCESS VARIANTS DATA
// ============================================

function processVariantsData(data) {
  console.log('📊 Processing variants data:', data);

  // Extract key_variants from analysis results
  const keyVariants = data.key_variants || data;

  if (!keyVariants || Object.keys(keyVariants).length === 0) {
    showNoData();
    return;
  }

  // Convert variants to offers format for scoring API
  const offers = convertVariantsToOffers(keyVariants, data);

  if (offers.length === 0) {
    showNoData();
    return;
  }

  // Call scoring API
  calculateScores(offers);
}

function convertVariantsToOffers(keyVariants, analysisData) {
  const offers = [];

  // ========== TRY TO LOAD REAL ECONOMIC KPIs FROM ECONOMICS MODULE ==========
  let scoringKpiData = null;
  try {
    const stored = localStorage.getItem('scoringKpiData');
    if (stored) {
      scoringKpiData = JSON.parse(stored);
      console.log('📊 Loaded scoring KPI data from Economics module:', Object.keys(scoringKpiData));
    }
  } catch (e) {
    console.warn('⚠️ Could not load scoring KPI data:', e);
  }

  // Get baseline data for fallback calculations
  const annualConsumption = getAnnualConsumption(analysisData);

  for (const [variantId, variant] of Object.entries(keyVariants)) {
    // Skip invalid variants
    if (!variant || !variant.capacity) continue;

    // Get KPI data from Economics module (preferred) or use fallback
    const kpi = scoringKpiData?.[variantId];

    if (kpi) {
      // ========== USE REAL KPIs FROM ECONOMICS MODULE ==========
      console.log(`✅ Using real KPIs for variant ${variantId}:`, {
        npv: kpi.npv_pln,
        payback: kpi.payback_years,
        irr: kpi.irr_pct,
        lcoe: kpi.lcoe_pln_mwh
      });

      offers.push({
        offer_id: variantId,
        name: `Wariant ${variantId} - ${formatNumberEU(kpi.capacity_kwp, 0)} kWp`,
        capacity_kwp: kpi.capacity_kwp,
        capex_pln: kpi.capacity_kwp * getCapexPerKwp(),
        // REAL Economic KPIs from Economics module
        npv_pln: kpi.npv_pln,
        payback_years: kpi.payback_years,
        irr_pct: kpi.irr_pct,
        lcoe_pln_mwh: kpi.lcoe_pln_mwh,
        // Production/consumption metrics
        annual_production_kwh: kpi.annual_production_kwh,
        self_consumed_kwh: kpi.self_consumed_kwh,
        exported_kwh: kpi.exported_kwh,
        annual_consumption_kwh: kpi.annual_consumption_kwh,
        // Ratios (0-1 scale)
        auto_consumption_pct: kpi.auto_consumption_pct,
        coverage_pct: kpi.coverage_pct,
        // ESG
        co2_reduction_tons: kpi.co2_reduction_tons
      });
    } else {
      // ========== FALLBACK: Estimate KPIs (less accurate) ==========
      console.warn(`⚠️ No KPI data for variant ${variantId}, using estimates`);

      const productionKwh = variant.production || 0;
      const selfConsumedKwh = variant.self_consumed || 0;
      const exportedKwh = variant.exported || 0;
      const autoConsumptionPct = productionKwh > 0 ? selfConsumedKwh / productionKwh : 0;
      const coveragePct = annualConsumption > 0 ? selfConsumedKwh / annualConsumption : 0;

      // Rough NPV estimate (not accurate - Economics module has real calculation)
      const capex = variant.capacity * getCapexPerKwp();
      const annualSavings = (selfConsumedKwh / 1000) * getEnergyPrice();
      const roughNPV = annualSavings * 15 - capex; // Very rough 15-year estimate

      offers.push({
        offer_id: variantId,
        name: `Wariant ${variantId} - ${formatNumberEU(variant.capacity, 0)} kWp`,
        capacity_kwp: variant.capacity,
        capex_pln: capex,
        // Estimated KPIs (fallback)
        npv_pln: roughNPV,
        payback_years: annualSavings > 0 ? capex / annualSavings : 25,
        irr_pct: null, // Cannot calculate without full cash flows
        lcoe_pln_mwh: null, // Cannot calculate without full data
        // Production/consumption metrics
        annual_production_kwh: productionKwh,
        self_consumed_kwh: selfConsumedKwh,
        exported_kwh: exportedKwh,
        annual_consumption_kwh: annualConsumption,
        // Ratios
        auto_consumption_pct: autoConsumptionPct,
        coverage_pct: coveragePct,
        // ESG
        co2_reduction_tons: (selfConsumedKwh * 0.7) / 1000
      });
    }
  }

  return offers;
}

function calculateProjectCosts(variant, energyPrice, years) {
  const costs = [];
  const annualConsumption = getAnnualConsumption();
  const baselineCost = (annualConsumption / 1000) * energyPrice;

  // Self-consumed energy saves money at retail price
  const savingsFromSelfConsumption = ((variant.self_consumed || 0) / 1000) * energyPrice;

  // Grid import still costs money
  const gridImportKwh = variant.bess_grid_import_kwh || (annualConsumption - (variant.self_consumed || 0));
  const gridImportCost = (gridImportKwh / 1000) * energyPrice;

  // OPEX
  const annualOpex = variant.capacity * getOpexPerKwp();

  // Project cost = grid import + OPEX (no savings from self-consumption in "cost" view)
  const projectCostYear1 = gridImportCost + annualOpex;

  // Apply degradation over years
  for (let year = 0; year < years; year++) {
    const degradationFactor = Math.pow(1 - 0.005, year + 1); // 0.5% per year
    // As degradation increases, savings decrease, so project costs increase
    const adjustedGridImport = gridImportKwh + (variant.self_consumed || 0) * (1 - degradationFactor);
    const yearCost = (adjustedGridImport / 1000) * energyPrice + annualOpex;
    costs.push(yearCost);
  }

  return costs;
}

function getAnnualConsumption(data) {
  // Try various sources
  if (data?.annual_consumption_kwh) return data.annual_consumption_kwh;
  if (window.consumptionData?.annual_consumption_kwh) return window.consumptionData.annual_consumption_kwh;
  if (window.consumptionData?.total_consumption_gwh) return window.consumptionData.total_consumption_gwh * 1000000;

  // Default: 5 GWh (medium industry)
  return 5000000;
}

function getEnergyPrice() {
  // Try to get from settings, default 800 PLN/MWh
  return window.economicsSettings?.energyPrice || 800;
}

function getCapexPerKwp() {
  return window.economicsSettings?.capexPerKwp || 3500;
}

function getOpexPerKwp() {
  return window.economicsSettings?.opexPerKwp || 15;
}

// ============================================
// SCORING API CALL
// ============================================

async function calculateScores(offers) {
  console.log('🧮 Calculating scores for', offers.length, 'offers');

  const weights = currentProfile === 'custom' ? customWeights : WEIGHT_PROFILES[currentProfile];

  const request = {
    offers: offers,
    parameters: {
      horizon_years: currentHorizon,
      discount_rate: 0.07,
      conservative_yield_factor: currentConservativeYield,
      conservative_price_factor: currentConservativePrices,
      profile: {
        name: currentProfile,
        value_weight: weights.value,
        robustness_weight: weights.robustness,
        tech_weight: weights.tech,
        esg_weight: weights.esg
      }
    }
  };

  try {
    const response = await fetch(`${API_URL}/scoring/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    scoringResults = await response.json();
    console.log('✅ Scoring results:', scoringResults);

    renderRankingTable(scoringResults.results);

    // Select first offer by default
    if (scoringResults.results.length > 0) {
      selectOffer(scoringResults.results[0].offer_id);
    }

  } catch (error) {
    console.error('❌ Scoring API error:', error);
    showError('Blad podczas obliczania scoringu: ' + error.message);
  }
}

// ============================================
// RENDER RANKING TABLE
// ============================================

function renderRankingTable(results) {
  const wrapper = document.getElementById('rankingTableWrapper');
  const placeholder = document.getElementById('noDataPlaceholder');
  const tbody = document.getElementById('rankingTableBody');

  if (!results || results.length === 0) {
    wrapper.style.display = 'none';
    placeholder.style.display = 'block';
    return;
  }

  wrapper.style.display = 'block';
  placeholder.style.display = 'none';

  const weights = currentProfile === 'custom' ? customWeights : WEIGHT_PROFILES[currentProfile];

  tbody.innerHTML = results.map(result => {
    const isSelected = result.offer_id === selectedOfferId;
    const isCompared = compareOfferIds.includes(result.offer_id);

    // Calculate max possible points per bucket for percentage bars
    const maxValue = 100 * weights.value;
    const maxRobustness = 100 * weights.robustness;
    const maxTech = 100 * weights.tech;
    const maxEsg = 100 * weights.esg;

    return `
      <tr class="${isSelected ? 'selected' : ''} ${result.rank === 1 ? 'rank-1' : ''}"
          onclick="selectOffer('${result.offer_id}')">
        <td class="col-rank">
          ${result.rank === 1 ? '🥇' : result.rank === 2 ? '🥈' : result.rank === 3 ? '🥉' : result.rank}
        </td>
        <td class="col-name">${result.offer_name}</td>
        <td class="col-score">${formatNumberEU(result.total_score, 1)}</td>
        <td class="col-bucket">
          <div class="bucket-value">${formatNumberEU(result.bucket_scores.value, 1)}</div>
          <div class="mini-bucket-bar">
            <div class="mini-bucket-fill value" style="width: ${maxValue > 0 ? (result.bucket_scores.value / maxValue * 100) : 0}%"></div>
          </div>
        </td>
        <td class="col-bucket">
          <div class="bucket-value">${formatNumberEU(result.bucket_scores.robustness, 1)}</div>
          <div class="mini-bucket-bar">
            <div class="mini-bucket-fill robustness" style="width: ${maxRobustness > 0 ? (result.bucket_scores.robustness / maxRobustness * 100) : 0}%"></div>
          </div>
        </td>
        <td class="col-bucket">
          <div class="bucket-value">${formatNumberEU(result.bucket_scores.tech, 1)}</div>
          <div class="mini-bucket-bar">
            <div class="mini-bucket-fill tech" style="width: ${maxTech > 0 ? (result.bucket_scores.tech / maxTech * 100) : 0}%"></div>
          </div>
        </td>
        <td class="col-bucket">
          <div class="bucket-value">${formatNumberEU(result.bucket_scores.esg, 1)}</div>
          <div class="mini-bucket-bar">
            <div class="mini-bucket-fill esg" style="width: ${maxEsg > 0 ? (result.bucket_scores.esg / maxEsg * 100) : 0}%"></div>
          </div>
        </td>
        <td class="col-compare">
          <input type="checkbox" class="compare-checkbox"
                 ${isCompared ? 'checked' : ''}
                 onclick="event.stopPropagation(); toggleCompare('${result.offer_id}')">
        </td>
      </tr>
    `;
  }).join('');
}

// ============================================
// SELECT OFFER - SHOW DETAILS
// ============================================

function selectOffer(offerId) {
  selectedOfferId = offerId;

  // Update table selection
  document.querySelectorAll('.ranking-table tbody tr').forEach(row => {
    row.classList.remove('selected');
  });
  const selectedRow = document.querySelector(`.ranking-table tbody tr[onclick*="${offerId}"]`);
  if (selectedRow) {
    selectedRow.classList.add('selected');
  }

  // Find result
  const result = scoringResults?.results?.find(r => r.offer_id === offerId);
  if (!result) return;

  // Show details section
  const detailsSection = document.getElementById('detailsSection');
  detailsSection.style.display = 'block';

  // Update header
  document.getElementById('selectedOfferName').textContent = result.offer_name;

  // Update gauge
  updateGauge(result.total_score);

  // Update bucket bars
  updateBucketBars(result.bucket_scores);

  // Update KPI table
  updateKpiTable(result);

  // Update flags and reasons
  updateFlagsAndReasons(result);
}

function updateGauge(score) {
  const circle = document.getElementById('gaugeCircle');
  const valueEl = document.getElementById('gaugeValue');

  // Circle has circumference of 314 (2 * PI * 50)
  const circumference = 314;
  const offset = circumference - (score / 100) * circumference;

  circle.style.strokeDashoffset = offset;
  valueEl.textContent = formatNumberEU(score, 1);

  // Color based on score
  if (score >= 70) {
    circle.style.stroke = '#2e7d32'; // Green
  } else if (score >= 50) {
    circle.style.stroke = '#1976d2'; // Blue
  } else if (score >= 30) {
    circle.style.stroke = '#f57c00'; // Orange
  } else {
    circle.style.stroke = '#c62828'; // Red
  }
}

function updateBucketBars(bucketScores) {
  const weights = currentProfile === 'custom' ? customWeights : WEIGHT_PROFILES[currentProfile];

  // Value
  const maxValue = 100 * weights.value;
  document.getElementById('barValue').style.width = `${maxValue > 0 ? (bucketScores.value / maxValue * 100) : 0}%`;
  document.getElementById('barValueText').textContent = formatNumberEU(bucketScores.value, 1);

  // Robustness
  const maxRobustness = 100 * weights.robustness;
  document.getElementById('barRobustness').style.width = `${maxRobustness > 0 ? (bucketScores.robustness / maxRobustness * 100) : 0}%`;
  document.getElementById('barRobustnessText').textContent = formatNumberEU(bucketScores.robustness, 1);

  // Tech
  const maxTech = 100 * weights.tech;
  document.getElementById('barTech').style.width = `${maxTech > 0 ? (bucketScores.tech / maxTech * 100) : 0}%`;
  document.getElementById('barTechText').textContent = formatNumberEU(bucketScores.tech, 1);

  // ESG
  const maxEsg = 100 * weights.esg;
  document.getElementById('barEsg').style.width = `${maxEsg > 0 ? (bucketScores.esg / maxEsg * 100) : 0}%`;
  document.getElementById('barEsgText').textContent = formatNumberEU(bucketScores.esg, 1);
}

function updateKpiTable(result) {
  const tbody = document.getElementById('kpiTableBody');
  const kpiRaw = result.kpi_raw;
  const points = result.points_breakdown;

  // Format NPV in millions PLN
  const formatNpvMln = (val) => val !== null && val !== undefined ? `${formatNumberEU(val, 2)} mln PLN` : '-';
  // Format payback in years
  const formatPayback = (val) => val !== null && val !== undefined && val < 99 ? `${formatNumberEU(val, 1)} lat` : '> 25 lat';
  // Format IRR in %
  const formatIrr = (val) => val !== null && val !== undefined && val > 0 ? `${formatNumberEU(val, 1)}%` : '-';
  // Format LCOE in PLN/MWh
  const formatLcoe = (val) => val !== null && val !== undefined && val > 0 ? `${formatNumberEU(val, 0)} PLN/MWh` : '-';

  const kpis = [
    // VALUE bucket
    { name: 'NPV', value: formatNpvMln(kpiRaw.npv_mln), bucket: 'VALUE', points: points.npv_pts },
    { name: 'Okres zwrotu', value: formatPayback(kpiRaw.payback_years), bucket: 'VALUE', points: points.payback_pts },
    // ROBUSTNESS bucket
    { name: 'IRR', value: formatIrr(kpiRaw.irr_pct), bucket: 'ROBUSTNESS', points: points.irr_pts },
    { name: 'LCOE', value: formatLcoe(kpiRaw.lcoe_pln_mwh), bucket: 'ROBUSTNESS', points: points.lcoe_pts },
    // TECH bucket
    { name: 'Autokonsumpcja', value: formatPercent(kpiRaw.auto_consumption_pct, 0), bucket: 'TECH', points: points.auto_consumption_pts },
    { name: 'Pokrycie zużycia', value: formatPercent(kpiRaw.coverage_pct, 0), bucket: 'TECH', points: points.coverage_pts },
    // ESG bucket
    { name: 'Redukcja CO2', value: `${formatNumberEU(kpiRaw.co2_reduction_tons, 0)} ton/rok`, bucket: 'ESG', points: points.co2_pts }
  ];

  // Add exported warning if high
  if (kpiRaw.exported_pct > 0.3) {
    kpis.push({
      name: '⚠️ Eksport (nadprodukcja)',
      value: formatPercent(kpiRaw.exported_pct, 0),
      bucket: 'TECH',
      points: 0
    });
  }

  tbody.innerHTML = kpis.map(kpi => `
    <tr>
      <td>${kpi.name}</td>
      <td><strong>${kpi.value}</strong></td>
      <td><span class="bucket-tag ${kpi.bucket.toLowerCase()}">${kpi.bucket}</span></td>
      <td><strong>${formatNumberEU(kpi.points, 1)}</strong> pkt</td>
    </tr>
  `).join('');
}

function updateFlagsAndReasons(result) {
  const flagsList = document.getElementById('flagsList');
  const reasonsList = document.getElementById('reasonsList');

  // Flags
  flagsList.innerHTML = result.flags.map(flag => `
    <span class="flag-item ${flag.type}">
      ${flag.type === 'warning' ? '⚠️' : flag.type === 'success' ? '✅' : 'ℹ️'}
      ${flag.message}
    </span>
  `).join('');

  // Reasons
  reasonsList.innerHTML = result.reasons.map(reason => `
    <div class="reason-item">${reason}</div>
  `).join('');
}

// ============================================
// COMPARISON
// ============================================

function toggleCompare(offerId) {
  const index = compareOfferIds.indexOf(offerId);
  if (index >= 0) {
    compareOfferIds.splice(index, 1);
  } else {
    if (compareOfferIds.length >= 2) {
      compareOfferIds.shift(); // Remove oldest
    }
    compareOfferIds.push(offerId);
  }

  // Update checkboxes
  document.querySelectorAll('.compare-checkbox').forEach(cb => {
    const rowOfferId = cb.closest('tr').querySelector('td:nth-child(2)').textContent;
    // Actually get from onclick
  });

  // Show/hide comparison panel
  if (compareOfferIds.length === 2) {
    showComparison();
  } else {
    hideComparison();
  }
}

function showComparison() {
  const panel = document.getElementById('comparisonPanel');
  panel.style.display = 'block';

  const results = scoringResults?.results || [];
  const offer1 = results.find(r => r.offer_id === compareOfferIds[0]);
  const offer2 = results.find(r => r.offer_id === compareOfferIds[1]);

  if (!offer1 || !offer2) return;

  // Determine winner
  const winner = offer1.total_score >= offer2.total_score ? offer1 : offer2;
  const loser = winner === offer1 ? offer2 : offer1;

  // Update panels
  updateComparisonOffer('compOffer1', offer1);
  updateComparisonOffer('compOffer2', offer2);

  // Update justification
  const justificationList = document.getElementById('justificationList');
  const justificationTitle = document.querySelector('.comparison-justification h3');

  justificationTitle.textContent = `Dlaczego rekomendujemy ${winner.offer_name}?`;

  const reasons = [];
  const diff = winner.total_score - loser.total_score;
  reasons.push(`Przewaga ${formatNumberEU(diff, 1)} punktow w calkowitym scoringu`);

  // Compare buckets
  const bucketNames = { value: 'VALUE', robustness: 'ROBUSTNESS', tech: 'TECH', esg: 'ESG' };
  for (const [key, name] of Object.entries(bucketNames)) {
    const bucketDiff = winner.bucket_scores[key] - loser.bucket_scores[key];
    if (bucketDiff > 2) {
      reasons.push(`Lepsza ocena w kategorii ${name} (+${formatNumberEU(bucketDiff, 1)} pkt)`);
    }
  }

  // Add winner's top reasons
  winner.reasons.slice(0, 2).forEach(reason => {
    if (!reason.includes('Lider')) {
      reasons.push(reason);
    }
  });

  justificationList.innerHTML = reasons.map(r => `<li>${r}</li>`).join('');
}

function updateComparisonOffer(elementId, offer) {
  const el = document.getElementById(elementId);
  el.querySelector('.offer-rank').textContent = `#${offer.rank}`;
  el.querySelector('.offer-name').textContent = offer.offer_name;
  el.querySelector('.offer-score').textContent = `${formatNumberEU(offer.total_score, 1)} pkt`;
}

function closeComparison() {
  compareOfferIds = [];
  document.getElementById('comparisonPanel').style.display = 'none';

  // Uncheck all compare checkboxes
  document.querySelectorAll('.compare-checkbox').forEach(cb => {
    cb.checked = false;
  });
}

function hideComparison() {
  document.getElementById('comparisonPanel').style.display = 'none';
}

// ============================================
// CONTROLS
// ============================================

function setProfile(profile) {
  currentProfile = profile;

  // Update button states
  document.querySelectorAll('.profile-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.profile === profile);
  });

  // Show/hide weight editor
  const weightEditor = document.getElementById('weightEditor');
  weightEditor.style.display = profile === 'custom' ? 'block' : 'none';

  // Recalculate if we have data
  if (scoringResults) {
    recalculateScores();
  }
}

function updateHorizon(value) {
  currentHorizon = parseInt(value);
}

function updateConservative() {
  currentConservativeYield = parseFloat(document.getElementById('consYield').value);
  currentConservativePrices = parseFloat(document.getElementById('consPrices').value);
}

function updateWeight(bucket, value) {
  customWeights[bucket] = parseInt(value) / 100;

  // Update display
  document.getElementById(`weight${capitalize(bucket)}Display`).textContent = `${value}%`;

  // Update total
  const total = (customWeights.value + customWeights.robustness + customWeights.tech + customWeights.esg) * 100;
  document.getElementById('weightTotal').textContent = `${Math.round(total)}%`;
  document.getElementById('weightTotal').style.color = Math.abs(total - 100) < 1 ? 'inherit' : '#c62828';
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function recalculateScores() {
  // Re-process variants with new parameters
  loadVariantsFromStorage();
}

// ============================================
// UI HELPERS
// ============================================

function showNoData() {
  document.getElementById('rankingTableWrapper').style.display = 'none';
  document.getElementById('noDataPlaceholder').style.display = 'block';
  document.getElementById('detailsSection').style.display = 'none';
}

function showError(message) {
  console.error(message);
  // Could show a toast/alert here
}

// ============================================
// EXPOSE TO WINDOW
// ============================================

window.setProfile = setProfile;
window.updateHorizon = updateHorizon;
window.updateConservative = updateConservative;
window.updateWeight = updateWeight;
window.recalculateScores = recalculateScores;
window.selectOffer = selectOffer;
window.toggleCompare = toggleCompare;
window.closeComparison = closeComparison;
