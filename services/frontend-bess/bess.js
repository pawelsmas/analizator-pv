console.log('[BESS] bess.js LOADED v=3.24 - timestamp:', new Date().toISOString());

// ============================================
// CROSS-MODULE NAVIGATION
// ============================================

/**
 * Navigate to another module via parent shell
 * @param {string} moduleName - module name (profile, economics, config, etc.)
 */
function navigateToModule(moduleName) {
  console.log(`🔗 Navigating to module: ${moduleName}`);

  // Save current BESS config to localStorage for sharing
  saveBessConfigToSharedStorage();

  // Send navigation request to parent shell
  window.parent.postMessage({
    type: 'NAVIGATE_TO_MODULE',
    module: moduleName
  }, '*');
}

/**
 * Send BESS sizing result to Shell/Economics using v2 payload format
 * This enables Economics to display savings breakdown (energy, peak shaving, capacity fee, etc.)
 * @param {object} sizingResult - Result from bess-dispatch sizing API
 */
function sendBessResultToShell(sizingResult) {
  if (!sizingResult || !sizingResult.variants || sizingResult.variants.length === 0) {
    console.log('⚠️ No sizing result to send to shell');
    return;
  }

  // Find recommended variant or best NPV
  const recommended = sizingResult.variants.find(v => v.is_recommended) ||
                      sizingResult.variants.reduce((best, v) =>
                        (v.npv_pln || 0) > (best.npv_pln || 0) ? v : best, sizingResult.variants[0]);

  if (!recommended) return;

  // Build v2 payload matching profile.js format
  const bessData = {
    schema_version: 'bess_economics_v2',

    // BESS sizing
    bess_power_kw: recommended.power_kw || 0,
    bess_energy_kwh: recommended.energy_kwh || 0,

    // Energy flows (basic metrics)
    annual_cycles: recommended.dispatch_summary?.degradation?.efc || 0,
    annual_discharge_mwh: (recommended.dispatch_summary?.total_discharge_kwh || 0) / 1000,

    // Energy flows (detailed totals from SSoT)
    energy_flows: recommended.dispatch_summary?.energy_flows?.totals_mwh ? {
      grid_import_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.grid_import_mwh || 0,
      grid_export_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.grid_export_mwh || 0,
      pv_to_load_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.pv_to_load_mwh || 0,
      pv_to_batt_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.pv_to_batt_mwh || 0,
      pv_curtail_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.pv_curtail_mwh || 0,
      batt_to_load_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.batt_to_load_mwh || 0,
      batt_charge_from_grid_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.batt_charge_from_grid_mwh || 0,
      batt_losses_mwh: recommended.dispatch_summary.energy_flows.totals_mwh.batt_losses_mwh || 0,
    } : null,

    // Economics
    npv_pln: recommended.npv_pln || 0,
    payback_years: recommended.payback_years || 0,
    capex_pln: recommended.capex_pln || 0,
    annual_savings_pln: recommended.annual_savings_pln || 0,

    // Dispatch metadata
    dispatch_metadata: {
      dispatch_mode: recommended.dispatch_summary?.mode || sizingResult.request_summary?.mode || 'stacked',
      topology: sizingResult.request_summary?.topology || 'pv_load',
      interval_minutes: sizingResult.request_summary?.interval_minutes || 60,
      start_date: sizingResult.request_summary?.start_date || null,
      export_policy: 'zero_export',
      peak_shaving_enabled: recommended.dispatch_summary?.peak_reduction_kw > 0,
      price_arbitrage_enabled: false,
    },

    // Savings breakdown - from bess-dispatch (accurate!)
    savings_breakdown: recommended.savings_breakdown ? {
      energy_savings_pln: recommended.savings_breakdown.energy_savings_pln || 0,
      demand_charge_savings_pln: recommended.savings_breakdown.demand_charge_savings_pln || 0,
      capacity_fee_savings_pln: recommended.savings_breakdown.capacity_fee_savings_pln || 0,
      arbitrage_savings_pln: recommended.savings_breakdown.arbitrage_savings_pln || 0,
      // Export revenue breakdown (v0.3.4)
      baseline_export_revenue_pln: recommended.savings_breakdown.baseline_export_revenue_pln || 0,
      project_export_revenue_pln: recommended.savings_breakdown.project_export_revenue_pln || 0,
      export_revenue_savings_pln: recommended.savings_breakdown.export_revenue_savings_pln || 0,
      export_revenue_pln: recommended.savings_breakdown.export_revenue_pln || 0,  // legacy
      // Degradation (v0.3.4)
      battery_throughput_mwh: recommended.savings_breakdown.battery_throughput_mwh || 0,
      degradation_cost_pln: recommended.savings_breakdown.degradation_cost_pln || 0,
      // Unserved load penalty (v0.7.0)
      unserved_load_penalty_pln: recommended.savings_breakdown.unserved_load_penalty_pln || 0,
      net_savings_pln: recommended.savings_breakdown.net_savings_pln || recommended.annual_savings_pln || 0,
      source: 'bess_dispatch_accurate',
    } : {
      energy_savings_pln: recommended.annual_savings_pln || 0,
      demand_charge_savings_pln: 0,
      capacity_fee_savings_pln: 0,
      arbitrage_savings_pln: 0,
      baseline_export_revenue_pln: 0,
      project_export_revenue_pln: 0,
      export_revenue_savings_pln: 0,
      export_revenue_pln: 0,
      battery_throughput_mwh: 0,
      degradation_cost_pln: 0,
      unserved_load_penalty_pln: 0,
      net_savings_pln: recommended.annual_savings_pln || 0,
      source: 'bess_pro_fallback',
    },

    // Prices summary
    prices_summary: recommended.prices_summary ? {
      import_price_pln_mwh: recommended.prices_summary.import_price_pln_mwh || 0,
      export_price_pln_mwh: recommended.prices_summary.export_price_pln_mwh || 0,
      demand_charge_pln_kw_month: recommended.prices_summary.demand_charge_pln_kw_month || 0,
      tariff_type: recommended.prices_summary.tariff_type || 'flat',
      tariff_id: recommended.prices_summary.tariff_id || null,
      zone_rates: recommended.prices_summary.zone_rates || null,
    } : {
      import_price_pln_mwh: 800,
      export_price_pln_mwh: 0,
      demand_charge_pln_kw_month: 0,
      tariff_type: 'flat',
      tariff_id: null,
      zone_rates: null,
    },

    // Strategy (from BESS PRO is always 'sizing' not profile-analysis)
    strategy: 'bess_pro_sizing',

    // All variants for reference
    all_variants: sizingResult.variants.map(v => ({
      variant_label: v.variant_label,
      power_kw: v.power_kw,
      energy_kwh: v.energy_kwh,
      npv_pln: v.npv_pln,
      payback_years: v.payback_years,
      is_recommended: v.is_recommended
    }))
  };

  // Send to Shell
  if (window.parent !== window) {
    window.parent.postMessage({
      type: 'BESS_SIZING_COMPLETE',
      data: {
        bessData: bessData,
        sizingResult: sizingResult
      }
    }, '*');
    console.log('📤 BESS PRO: Sent BESS_SIZING_COMPLETE v2 to shell:', {
      schema_version: bessData.schema_version,
      bess_power_kw: bessData.bess_power_kw,
      bess_energy_kwh: bessData.bess_energy_kwh,
      savings_source: bessData.savings_breakdown?.source,
      dispatch_mode: bessData.dispatch_metadata?.dispatch_mode
    });
  }

  // Also save to localStorage for cross-module access
  localStorage.setItem('bess_economics_payload_v2', JSON.stringify(bessData));
}

/**
 * Save current BESS configuration to shared localStorage
 * This allows Profile Analysis and Economics modules to access BESS params
 */
function saveBessConfigToSharedStorage() {
  const currentData = variants[currentVariant];
  if (!currentData) return;

  const settings = systemSettings || {};
  const bessSettings = settings[`variant${currentVariant}`]?.bess || {};

  const sharedBessConfig = {
    power_kw: bessSettings.power || currentData.bess?.power_kw || 0,
    energy_kwh: bessSettings.energy || currentData.bess?.energy_kwh || 0,
    enabled: bessSettings.enabled || false,
    variant: currentVariant,
    pv_capacity_kwp: currentData.capacity || 0,
    annual_production_kwh: currentData.production || 0,
    self_consumed_kwh: currentData.self_consumed || 0,
    updated_at: new Date().toISOString()
  };

  localStorage.setItem('pv_shared_bess_config', JSON.stringify(sharedBessConfig));
  console.log('💾 Saved shared BESS config:', sharedBessConfig);
}

/**
 * Update the shared BESS config display in cross-module nav bar
 */
function updateSharedBessConfigDisplay() {
  const el = document.getElementById('sharedBessConfig');
  if (!el) return;

  const currentData = variants[currentVariant];
  const settings = systemSettings || {};
  const bessSettings = settings[`variant${currentVariant}`]?.bess || {};

  const power = bessSettings.power || currentData?.bess?.power_kw || 0;
  const energy = bessSettings.energy || currentData?.bess?.energy_kwh || 0;

  if (power > 0 && energy > 0) {
    el.textContent = `BESS: ${power} kW / ${energy} kWh`;
    el.style.color = '#2e7d32';
  } else {
    el.textContent = 'BESS: nie skonfigurowany';
    el.style.color = '#999';
  }
}

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
let lastSizingResult = null; // Store last sizing result for Excel export

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  console.log('📱 DOMContentLoaded - BESS module');

  // Request data from parent shell
  requestSharedData();
  requestSettingsFromShell();

  // Setup sticky variant selector
  setupStickyVariantSelector();

  // v3.15: Arbitrage settings are now in Settings module (no local restore needed)

  // Fallback: try localStorage
  setTimeout(() => {
    if (!analysisResults || Object.keys(variants).length === 0) {
      console.log('⏳ No data from shell, trying localStorage...');
      loadFromLocalStorage();
    }
  }, 500);
});

// Setup sticky variant selector with scroll animation
function setupStickyVariantSelector() {
  const variantSelector = document.querySelector('.variant-selector');
  if (!variantSelector) return;

  window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
      variantSelector.classList.add('scrolled');
    } else {
      variantSelector.classList.remove('scrolled');
    }
  });
}

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

  // Handle variant changes from other modules (via shell broadcast)
  if (type === 'MASTER_VARIANT_CHANGED') {
    console.log('📥 Received MASTER_VARIANT_CHANGED:', data);
    if (data && data.variantKey && data.variantKey !== currentVariant) {
      // Update local state without re-broadcasting to shell
      currentVariant = data.variantKey;
      // Update button states
      document.querySelectorAll('.variant-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.variant === data.variantKey);
      });
      updateDisplay();
    }
  }

  // Legacy support for VARIANT_CHANGED
  if (type === 'VARIANT_CHANGED') {
    console.log('📥 Received VARIANT_CHANGED:', data);
    if (data && data.variant && data.variant !== currentVariant) {
      currentVariant = data.variant;
      document.querySelectorAll('.variant-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.variant === data.variant);
      });
      updateDisplay();
    }
  }

  // Also listen for SCENARIO_CHANGED (P50/P75/P90)
  if (type === 'SCENARIO_CHANGED') {
    console.log('📥 Received SCENARIO_CHANGED:', data);
    // Refresh data
    requestSharedData();
  }

  // =========================================================================
  // NEW: BESS_RESULT_UPDATED - Single Source of Truth from shell
  // =========================================================================
  if (type === 'BESS_RESULT_UPDATED') {
    console.log('🔋 BESS result updated (Single Source of Truth):', data);
    if (data) {
      // Store bessResult for display
      window.bessResult = data;

      // Update display with new BESS data
      if (data.variants && data.variants.length > 0) {
        // Display sizing variants from single source
        displaySizingVariants({ variants: data.variants });

        // Display degradation if available
        const recommended = data.variants.find(v => v.is_recommended) || data.variants[0];
        if (recommended?.degradation) {
          displayDegradationBudget(recommended.degradation, {});
        }

        // Log savings breakdown (displayed in economics module)
        if (recommended?.savings_breakdown) {
          console.log('📊 Savings breakdown available:', recommended.savings_breakdown);
        }

        console.log('✅ BESS display updated from Single Source of Truth');
      }
    }
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

  // Update button states to match current variant
  document.querySelectorAll('.variant-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.variant === currentVariant);
  });

  updateDisplay();
}

function resolveSavingsBreakdown(sourceObj) {
  // Try multiple possible shapes/locations for savings_breakdown
  if (!sourceObj) return null;
  return (
    sourceObj.savings_breakdown ||
    sourceObj.savingsBreakdown ||
    sourceObj?.bess_summary?.savings_breakdown ||
    sourceObj?.bessResult?.savings_breakdown ||
    (analysisResults?.bess_summary?.savings_breakdown || null) ||
    (typeof window !== 'undefined' &&
      window.sharedData?.analysisResults?.bess_summary?.savings_breakdown) ||
    (typeof window !== 'undefined' &&
      window.sharedData?.bessResult?.variants?.[0]?.savings_breakdown) ||
    null
  );
}

function parseKeyVariants(keyVariants) {
  variants = {};

  if (!keyVariants || typeof keyVariants !== 'object') return;

  Object.entries(keyVariants).forEach(([key, s]) => {
    // Debug: log raw BESS data from backend
    console.log(`🔍 Variant ${key} raw BESS data:`, {
      bess_power_kw: s.bess_power_kw,
      bess_energy_kwh: s.bess_energy_kwh,
      bess_monthly_data: s.bess_monthly_data?.length || 'NONE',
      bess_soc_histogram: s.bess_soc_histogram ? 'EXISTS' : 'NONE'
    });

    // Normalize savings_breakdown casing and fallback sources
    const savingsBreakdown = resolveSavingsBreakdown(s);
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
      // Economics metadata passed from backend (SSoT)
      savings_breakdown: savingsBreakdown,
      dispatch_metadata: s.dispatch_metadata || null,
      prices_summary: s.prices_summary || null,
      // Monthly breakdown (NEW in v3.2)
      bess_monthly_data: s.bess_monthly_data || [],
      // SOC histogram (NEW in v3.2)
      bess_soc_histogram: s.bess_soc_histogram || null,
      // Baseline for comparison
      baseline_no_bess: s.baseline_no_bess || {}
    };
  });

  console.log('📊 Parsed key_variants:', Object.keys(variants));
}

function loadFromLocalStorage() {
  try {
    // Check for BESS-only results first (from KONFIGURACJA with bess_only topology)
    const bessOnlyResultsStr = localStorage.getItem('bessOnlyResults');
    if (bessOnlyResultsStr) {
      try {
        const bessOnlyResults = JSON.parse(bessOnlyResultsStr);
        if (bessOnlyResults.topology === 'bess_only' && bessOnlyResults.variants) {
          console.log('🔋 Loading BESS-only results from localStorage');
          loadBessOnlyResults(bessOnlyResults);
          return;
        }
      } catch (e) {
        console.warn('Failed to parse bessOnlyResults:', e);
      }
    }

    // Load PV analysis results - try different localStorage keys
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

    // Also check pvAnalysisVariants for BESS-only data
    const pvVariantsStr = localStorage.getItem('pvAnalysisVariants');
    if (pvVariantsStr && Object.keys(variants).length === 0) {
      try {
        const pvVariants = JSON.parse(pvVariantsStr);
        // Check if this is BESS-only data
        if (pvVariants.A?.topology === 'bess_only') {
          console.log('🔋 Loading BESS-only variants from pvAnalysisVariants');
          variants = pvVariants;
          currentVariant = 'A';
        }
      } catch (e) {
        console.warn('Failed to parse pvAnalysisVariants:', e);
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
    const savingsBreakdown = resolveSavingsBreakdown(s);
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
      // Economics metadata passed from backend (SSoT)
      savings_breakdown: savingsBreakdown,
      dispatch_metadata: s.dispatch_metadata || null,
      prices_summary: s.prices_summary || null,
      // Monthly breakdown (NEW in v3.2)
      bess_monthly_data: s.bess_monthly_data || [],
      // SOC histogram (NEW in v3.2)
      bess_soc_histogram: s.bess_soc_histogram || null,
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
  console.log('🔄 Variant selected:', variantKey);

  // Update button states
  document.querySelectorAll('.variant-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.variant === variantKey);
  });

  // Notify parent shell - use MASTER_VARIANT_SELECTED for shell compatibility
  if (window.parent !== window) {
    window.parent.postMessage({
      type: 'MASTER_VARIANT_SELECTED',
      data: {
        variantKey: variantKey,
        variantData: variants[variantKey],
        source: 'bess'
      }
    }, '*');
    console.log('📤 Sent MASTER_VARIANT_SELECTED to shell:', variantKey);
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

  // Update shared BESS config display for cross-module navigation
  updateSharedBessConfigDisplay();

  const variant = variants[currentVariant];

  if (!variant) {
    console.log('❌ No variant found for:', currentVariant);
    showNoData();
    return;
  }

  // Check if BESS is enabled
  const hasBess = variant.bess_power_kw > 0 && variant.bess_energy_kwh > 0;
  console.log('🔋 BESS check:', {
    power: variant.bess_power_kw,
    energy: variant.bess_energy_kwh,
    hasBess: hasBess,
    monthly_data_length: variant.bess_monthly_data?.length || 0
  });

  if (!hasBess) {
    console.log('⚠️ BESS disabled - showing banner');
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

  // Debug: Check if monthly data exists
  console.log('📊 BESS Monthly Data:', variant.bess_monthly_data?.length || 0, 'months');
  console.log('📊 BESS SOC Histogram:', variant.bess_soc_histogram ? 'available' : 'NOT AVAILABLE');

  generateMonthlyTable(variant);  // NEW in v3.2
  updateQuarterlyCycles(variant); // NEW in v3.2
  renderSOCHistogramChart(variant); // NEW in v3.2
  renderCurtailmentChart(variant);  // NEW in v3.2
  updateDeltaEconomics(variant);    // NEW in v3.2
  updateComparison(variant);
  updateEconomics(variant);
  updateTechnicalParams(variant);
  generateDegradationTable(variant);
  updateDataInfo(variant);

  // NEW v3.3: Try to fetch sizing variants from bess-dispatch service
  tryFetchSizingVariants(variant);

  // NEW v3.17: Capacity fee overlay (if enabled in settings)
  runCapacityFeeAnalysisIfEnabled(variant);
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

// ============================================
// MONTHLY TABLE (NEW in v3.2)
// ============================================

function generateMonthlyTable(variant) {
  const tbody = document.getElementById('bessMonthlyTableBody');
  const tfoot = document.getElementById('bessMonthlyTableFoot');
  if (!tbody || !tfoot) return;

  const monthlyData = variant.bess_monthly_data || [];

  // If no monthly data, show empty message
  if (monthlyData.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;padding:20px;">Brak danych miesięcznych - wymagana ponowna analiza</td></tr>';
    tfoot.innerHTML = '';
    return;
  }

  // Season mapping for styling
  const seasonClass = {
    1: 'winter-month', 2: 'winter-month', 3: 'spring-month',
    4: 'spring-month', 5: 'spring-month', 6: 'summer-month',
    7: 'summer-month', 8: 'summer-month', 9: 'autumn-month',
    10: 'autumn-month', 11: 'autumn-month', 12: 'winter-month'
  };

  // Totals
  let totalCharged = 0;
  let totalDischarged = 0;
  let totalCurtailed = 0;
  let totalGridImport = 0;
  let totalCycles = 0;
  let totalThroughput = 0;

  let html = '';
  monthlyData.forEach(m => {
    const chargedMWh = m.charged_kwh / 1000;
    const dischargedMWh = m.discharged_kwh / 1000;
    const curtailedMWh = m.curtailed_kwh / 1000;
    const gridImportMWh = m.grid_import_kwh / 1000;
    const throughputMWh = m.throughput_kwh / 1000;

    totalCharged += chargedMWh;
    totalDischarged += dischargedMWh;
    totalCurtailed += curtailedMWh;
    totalGridImport += gridImportMWh;
    totalCycles += m.cycles_equivalent;
    totalThroughput += throughputMWh;

    html += `
      <tr class="${seasonClass[m.month]}">
        <td>${m.month_name}</td>
        <td>${formatNumberEU(chargedMWh, 2)}</td>
        <td>${formatNumberEU(dischargedMWh, 2)}</td>
        <td style="color:${curtailedMWh > 0 ? '#e74c3c' : 'inherit'}">${formatNumberEU(curtailedMWh, 2)}</td>
        <td>${formatNumberEU(gridImportMWh, 2)}</td>
        <td>${formatNumberEU(m.cycles_equivalent, 1)}</td>
        <td>${formatNumberEU(throughputMWh, 2)}</td>
      </tr>
    `;
  });

  tbody.innerHTML = html;

  // Footer with totals
  tfoot.innerHTML = `
    <tr>
      <td>SUMA ROK</td>
      <td>${formatNumberEU(totalCharged, 1)}</td>
      <td>${formatNumberEU(totalDischarged, 1)}</td>
      <td>${formatNumberEU(totalCurtailed, 1)}</td>
      <td>${formatNumberEU(totalGridImport, 1)}</td>
      <td>${formatNumberEU(totalCycles, 0)}</td>
      <td>${formatNumberEU(totalThroughput, 1)}</td>
    </tr>
  `;
}

function updateQuarterlyCycles(variant) {
  const monthlyData = variant.bess_monthly_data || [];

  // Initialize quarterly accumulators
  const quarters = {
    Q1: { cycles: 0, throughput: 0 },  // Jan-Mar (months 1-3)
    Q2: { cycles: 0, throughput: 0 },  // Apr-Jun (months 4-6)
    Q3: { cycles: 0, throughput: 0 },  // Jul-Sep (months 7-9)
    Q4: { cycles: 0, throughput: 0 }   // Oct-Dec (months 10-12)
  };

  monthlyData.forEach(m => {
    const throughputMWh = m.throughput_kwh / 1000;
    if (m.month <= 3) {
      quarters.Q1.cycles += m.cycles_equivalent;
      quarters.Q1.throughput += throughputMWh;
    } else if (m.month <= 6) {
      quarters.Q2.cycles += m.cycles_equivalent;
      quarters.Q2.throughput += throughputMWh;
    } else if (m.month <= 9) {
      quarters.Q3.cycles += m.cycles_equivalent;
      quarters.Q3.throughput += throughputMWh;
    } else {
      quarters.Q4.cycles += m.cycles_equivalent;
      quarters.Q4.throughput += throughputMWh;
    }
  });

  // Update UI
  document.getElementById('bessQ1Cycles').textContent = formatNumberEU(quarters.Q1.cycles, 0);
  document.getElementById('bessQ1Throughput').textContent = `${formatNumberEU(quarters.Q1.throughput, 1)} MWh`;

  document.getElementById('bessQ2Cycles').textContent = formatNumberEU(quarters.Q2.cycles, 0);
  document.getElementById('bessQ2Throughput').textContent = `${formatNumberEU(quarters.Q2.throughput, 1)} MWh`;

  document.getElementById('bessQ3Cycles').textContent = formatNumberEU(quarters.Q3.cycles, 0);
  document.getElementById('bessQ3Throughput').textContent = `${formatNumberEU(quarters.Q3.throughput, 1)} MWh`;

  document.getElementById('bessQ4Cycles').textContent = formatNumberEU(quarters.Q4.cycles, 0);
  document.getElementById('bessQ4Throughput').textContent = `${formatNumberEU(quarters.Q4.throughput, 1)} MWh`;
}

// ============================================
// CHARTS (NEW in v3.2)
// ============================================

let socHistogramChart = null;
let curtailmentChart = null;

function renderSOCHistogramChart(variant) {
  const ctx = document.getElementById('socHistogramChart');
  if (!ctx) return;

  // Destroy existing chart
  if (socHistogramChart) {
    socHistogramChart.destroy();
    socHistogramChart = null;
  }

  const histogram = variant.bess_soc_histogram;
  if (!histogram || !histogram.bins || histogram.bins.length === 0) {
    // No data - show message on canvas
    const context = ctx.getContext('2d');
    context.clearRect(0, 0, ctx.width, ctx.height);
    context.font = '14px Segoe UI';
    context.fillStyle = '#888';
    context.textAlign = 'center';
    context.fillText('Brak danych histogramu SOC - wymagana ponowna analiza', ctx.width / 2, ctx.height / 2);
    return;
  }

  // Create gradient colors for SOC levels (red at low, green at high)
  const colors = histogram.bins.map((_, i) => {
    const ratio = i / 9; // 0 to 1
    const r = Math.round(220 - ratio * 180);
    const g = Math.round(60 + ratio * 140);
    const b = 60;
    return `rgba(${r}, ${g}, ${b}, 0.7)`;
  });

  socHistogramChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: histogram.bins,
      datasets: [{
        label: 'Godziny w roku',
        data: histogram.hours,
        backgroundColor: colors,
        borderColor: colors.map(c => c.replace('0.7', '1')),
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => {
              const hours = context.raw;
              const pct = histogram.percentages[context.dataIndex];
              return `${formatNumberEU(hours, 0)} godz. (${formatNumberEU(pct, 1)}%)`;
            }
          }
        }
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Przedział SOC',
            color: '#666'
          },
          grid: { display: false }
        },
        y: {
          title: {
            display: true,
            text: 'Liczba godzin',
            color: '#666'
          },
          beginAtZero: true
        }
      }
    }
  });
}

function renderCurtailmentChart(variant) {
  const ctx = document.getElementById('curtailmentChart');
  if (!ctx) return;

  // Destroy existing chart
  if (curtailmentChart) {
    curtailmentChart.destroy();
    curtailmentChart = null;
  }

  const monthlyData = variant.bess_monthly_data || [];
  if (monthlyData.length === 0) {
    const context = ctx.getContext('2d');
    context.clearRect(0, 0, ctx.width, ctx.height);
    context.font = '14px Segoe UI';
    context.fillStyle = '#888';
    context.textAlign = 'center';
    context.fillText('Brak danych miesięcznych - wymagana ponowna analiza', ctx.width / 2, ctx.height / 2);
    return;
  }

  const labels = monthlyData.map(m => m.month_name.substring(0, 3)); // Sty, Lut, etc.
  const curtailmentMWh = monthlyData.map(m => m.curtailed_kwh / 1000);
  const chargedMWh = monthlyData.map(m => m.charged_kwh / 1000);

  curtailmentChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Ładowanie BESS [MWh]',
          data: chargedMWh,
          backgroundColor: 'rgba(39, 174, 96, 0.6)',
          borderColor: 'rgba(39, 174, 96, 1)',
          borderWidth: 1
        },
        {
          label: 'Curtailment [MWh]',
          data: curtailmentMWh,
          backgroundColor: 'rgba(231, 76, 60, 0.7)',
          borderColor: 'rgba(231, 76, 60, 1)',
          borderWidth: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { usePointStyle: true }
        },
        tooltip: {
          callbacks: {
            label: (context) => `${context.dataset.label}: ${formatNumberEU(context.raw, 2)} MWh`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false }
        },
        y: {
          title: {
            display: true,
            text: 'Energia [MWh]',
            color: '#666'
          },
          beginAtZero: true,
          stacked: false
        }
      }
    }
  });
}

// ============================================
// DELTA ECONOMICS (NEW in v3.2)
// ============================================

/**
 * Calculate full energy price including energia czynna from tariff + fixed charges
 *
 * Since settings.totalEnergyPrice now contains only fixed charges (bez energii czynnej),
 * we need to add the average energia czynna from tariffConfig.
 *
 * @param {object} settings - System settings
 * @returns {number} - Full energy price in PLN/MWh
 */
function calculateFullEnergyPrice(settings) {
  // Fixed charges (dystrybucja, jakość, OZE, kog, akcyza, opłata mocowa)
  const fixedCharges = settings.totalFixedCharges || settings.totalEnergyPrice || 0;

  // Get energia czynna from tariffConfig
  const tariffConfig = settings.tariffConfig || {};
  const tariffType = tariffConfig.type || 'flat';

  let averageEnergiaPrice = 0;

  if (tariffType === 'flat') {
    averageEnergiaPrice = tariffConfig.flatRate || 350;
  } else if (tariffType === 'two_zone') {
    // C12a: weighted average (assume 60% day, 40% night for typical load)
    const dayRate = tariffConfig.twoZone?.dayRate || 450;
    const nightRate = tariffConfig.twoZone?.nightRate || 280;
    averageEnergiaPrice = dayRate * 0.6 + nightRate * 0.4;
  } else if (tariffType === 'three_zone') {
    // C12b: weighted average (assume 20% peak, 40% partial, 40% off-peak)
    const peakRate = tariffConfig.threeZone?.peakRate || 550;
    const partialRate = tariffConfig.threeZone?.partialRate || 400;
    const offPeakRate = tariffConfig.threeZone?.offPeakRate || 250;
    averageEnergiaPrice = peakRate * 0.2 + partialRate * 0.4 + offPeakRate * 0.4;
  }

  // Full price = energia czynna + opłaty stałe
  const fullPrice = averageEnergiaPrice + fixedCharges;

  console.log('💰 calculateFullEnergyPrice:', {
    tariffType,
    averageEnergiaPrice,
    fixedCharges,
    fullPrice
  });

  // Fallback to legacy energyPurchasePrice if no tariffConfig
  if (!tariffConfig.type && settings.energyPurchasePrice) {
    return settings.energyPurchasePrice;
  }

  return fullPrice > 0 ? fullPrice : 800; // Default fallback
}

function updateDeltaEconomics(variant) {
  const settings = systemSettings || {};
  const powerKw = variant.bess_power_kw || 0;
  const energyKwh = variant.bess_energy_kwh || 0;

  // BESS CAPEX
  const capexPerKwh = settings.bessCapexPerKwh || 1500;
  const capexPerKw = settings.bessCapexPerKw || 300;
  const bessCapex = energyKwh * capexPerKwh + powerKw * capexPerKw;

  // Additional self-consumption from BESS (energy from battery)
  const bessDischargedMWh = (variant.bess_discharged_kwh || 0) / 1000;
  const deltaSelfConsumedMWh = bessDischargedMWh; // This is energy delivered by BESS

  // SSoT: Use savings_breakdown.net_savings_pln from backend (same as EKONOMIA module)
  // This ensures both modules display identical savings values
  let deltaSavingsAnnual;
  let savingsSource = 'local';

  if (variant.savings_breakdown && Number.isFinite(variant.savings_breakdown.net_savings_pln)) {
    // Use backend SSoT value (includes energy savings, demand charge, capacity fee, etc.)
    deltaSavingsAnnual = variant.savings_breakdown.net_savings_pln;
    savingsSource = variant.savings_breakdown.source || 'dispatch';
    console.log('updateDeltaEconomics: Using SSoT savings_breakdown.net_savings_pln:', deltaSavingsAnnual, variant.savings_breakdown);
  } else {
    // Fallback: local calculation (only if SSoT not available)
    const energyPrice = calculateFullEnergyPrice(settings); // PLN/MWh
    deltaSavingsAnnual = deltaSelfConsumedMWh * energyPrice; // PLN/year
    console.log('updateDeltaEconomics: Fallback to local calculation:', deltaSavingsAnnual, 'at', energyPrice, 'PLN/MWh', { savings_breakdown: variant.savings_breakdown });
  }

  const deltaSavingsAnnualK = deltaSavingsAnnual / 1000; // tys. PLN/year

  // Simple payback = CAPEX / annual savings
  const simplePayback = deltaSavingsAnnual > 0 ? bessCapex / deltaSavingsAnnual : Infinity;

  // ROI = (annual savings / CAPEX) * 100%
  const roi = bessCapex > 0 ? (deltaSavingsAnnual / bessCapex) * 100 : 0;

  // Update UI
  document.getElementById('deltaSelfConsumed').textContent = formatNumberEU(deltaSelfConsumedMWh, 1);
  document.getElementById('deltaSelfConsumedInfo').textContent = `${formatNumberEU(variant.bess_discharged_kwh || 0, 0)} kWh/rok`;

  document.getElementById('deltaSavings').textContent = formatNumberEU(deltaSavingsAnnualK, 1);
  // Show source of savings (SSoT or local fallback) with clear labeling
  if (savingsSource === 'local') {
    document.getElementById('deltaSavingsInfo').textContent = 'Estymacja brutto (flat)';
    document.getElementById('deltaSavingsInfo').title = 'Kalkulacja lokalna bez uwzględnienia ToU/arbitrażu. Użyj danych z backendu dla dokładniejszych wyników.';
  } else {
    document.getElementById('deltaSavingsInfo').textContent = 'Oszczędność netto (SSoT)';
    document.getElementById('deltaSavingsInfo').title = 'savings_breakdown.net_savings_pln - uwzględnia energię, opłaty sieciowe, arbitraż i degradację';
  }

  if (simplePayback === Infinity || simplePayback > 50) {
    document.getElementById('deltaPayback').textContent = '>50';
    document.getElementById('deltaPaybackInfo').textContent = 'nieopłacalny';
  } else {
    document.getElementById('deltaPayback').textContent = formatNumberEU(simplePayback, 1);
    document.getElementById('deltaPaybackInfo').textContent = `CAPEX ${formatNumberEU(bessCapex / 1000, 0)} tys. PLN`;
  }

  document.getElementById('deltaROI').textContent = formatNumberEU(roi, 1);
  document.getElementById('deltaROIInfo').textContent = roi > 0 ? `${formatNumberEU(100 / roi, 1)} lat zwrotu` : '-';
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

/**
 * Load BESS-only results from KONFIGURACJA module (bess_only topology)
 * These results are pre-calculated - just display them
 */
function loadBessOnlyResults(bessOnlyResults) {
  console.log('🔋 Loading BESS-only results:', bessOnlyResults);

  // Load settings
  const storedSettings = localStorage.getItem('systemSettings');
  if (storedSettings) {
    systemSettings = JSON.parse(storedSettings);
    window.systemSettings = systemSettings;
  }

  // Hide variant selector (not applicable for BESS-only)
  const variantSelector = document.querySelector('.variant-selector');
  if (variantSelector) {
    variantSelector.style.display = 'none';
  }

  // Hide no-data message and disabled banner
  document.getElementById('noDataMessage').style.display = 'none';
  document.getElementById('bessDisabledBanner').style.display = 'none';

  // Show main content
  document.getElementById('bessContent').style.display = 'grid';

  // Update header info
  const dataInfo = document.getElementById('dataInfo');
  if (dataInfo) {
    const totalMWh = (bessOnlyResults.totalLoadMwh || 0).toFixed(1);
    dataInfo.textContent = `🔋 BESS-only: ${totalMWh} MWh/rok | ${bessOnlyResults.variants?.length || 0} wariantów`;
  }

  // Display sizing variants directly
  const sizingResult = {
    variants: bessOnlyResults.variants,
    recommended_variant: bessOnlyResults.recommendedVariant,
    warnings: bessOnlyResults.warnings
  };

  displaySizingVariants(sizingResult);
  updateConfigResultsSummary(sizingResult);

  // Show sizing variants section prominently
  const sizingSection = document.getElementById('sizingVariantsSection');
  if (sizingSection) {
    sizingSection.style.display = 'block';
    setTimeout(() => {
      sizingSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 200);
  }

  // Update status
  const statusEl = document.getElementById('advancedConfigStatus');
  if (statusEl) {
    statusEl.textContent = '✅ Wyniki analizy BESS (bez PV) załadowane z KONFIGURACJI';
    statusEl.className = 'config-status success';
  }

  console.log('✅ BESS-only results displayed');
}

/**
 * Show LOAD_ONLY mode interface when consumption data is available but no PV variants
 * This allows BESS sizing analysis without requiring PV configuration
 */
function showLoadOnlyMode(consumptionData) {
  console.log('🔋 Entering LOAD_ONLY mode with consumption data:', consumptionData);

  // Load settings first
  const storedSettings = localStorage.getItem('systemSettings');
  if (storedSettings) {
    systemSettings = JSON.parse(storedSettings);
    window.systemSettings = systemSettings;
  }

  // Hide variant selector (not needed for LOAD_ONLY)
  const variantSelector = document.querySelector('.variant-selector');
  if (variantSelector) {
    variantSelector.style.display = 'none';
  }

  // Hide no-data message
  document.getElementById('noDataMessage').style.display = 'none';
  document.getElementById('bessDisabledBanner').style.display = 'none';

  // Show main content
  document.getElementById('bessContent').style.display = 'grid';

  // Update header info
  const dataInfo = document.getElementById('dataInfo');
  if (dataInfo) {
    const totalMWh = ((consumptionData.totalConsumption || consumptionData.sum || 0) / 1000).toFixed(1);
    const dataPoints = consumptionData.dataPoints || consumptionData.hourlyData?.values?.length || 0;
    const interval = dataPoints > 8760 ? '15-min' : '1h';
    dataInfo.textContent = `LOAD_ONLY: ${totalMWh} MWh/rok (${dataPoints} punktów, ${interval})`;
  }

  // Set topology to load_only
  advancedConfig.topology = 'load_only';
  const loadOnlyRadio = document.querySelector('input[name="topology"][value="load_only"]');
  if (loadOnlyRadio) {
    loadOnlyRadio.checked = true;
  }

  // Store consumption data for later use
  window.loadOnlyConsumptionData = consumptionData;

  // Show advanced config section prominently
  const advSection = document.getElementById('advancedConfigSection');
  if (advSection) {
    advSection.style.display = 'block';
    // Scroll to it
    setTimeout(() => {
      advSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 200);
  }

  // Update status
  const statusEl = document.getElementById('advancedConfigStatus');
  if (statusEl) {
    statusEl.textContent = '🔋 Tryb LOAD_ONLY - uruchamiam analizę doboru BESS...';
    statusEl.className = 'config-status info';
  }

  console.log('✅ LOAD_ONLY mode UI ready - auto-running sizing analysis');

  // AUTO-RUN: Automatically trigger BESS sizing analysis
  setTimeout(() => {
    console.log('🚀 Auto-triggering applyAdvancedConfig for LOAD_ONLY mode');
    applyAdvancedConfig();
  }, 500); // Short delay to ensure UI is fully rendered
}

// ============================================
// ACTIONS
// ============================================

function refreshData() {
  console.log('🔄 Refreshing BESS data...');
  requestSharedData();
  requestSettingsFromShell();
}

// DEBUG: Show current variant data
function debugVariantData() {
  const variant = variants[currentVariant];
  console.log('🔍 DEBUG - Current variant:', currentVariant);
  console.log('🔍 DEBUG - All variants:', Object.keys(variants));
  console.log('🔍 DEBUG - Variant data:', variant);
  console.log('🔍 DEBUG - BESS fields:', {
    bess_power_kw: variant?.bess_power_kw,
    bess_energy_kwh: variant?.bess_energy_kwh,
    bess_charged_kwh: variant?.bess_charged_kwh,
    bess_discharged_kwh: variant?.bess_discharged_kwh,
    production: variant?.production,
    consumption: variant?.consumption
  });
  console.log('🔍 DEBUG - System settings:', systemSettings);

  alert(`Wariant: ${currentVariant}\nBESS Power: ${variant?.bess_power_kw || 0} kW\nBESS Energy: ${variant?.bess_energy_kwh || 0} kWh\nProduction: ${variant?.production || 0} kWh`);
}
window.debugVariantData = debugVariantData;

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

// ============================================
// EXCEL EXPORT - DETAILED HOURLY ECONOMICS
// ============================================

/**
 * Export detailed hourly economics to Excel via backend endpoint.
 *
 * Generates Excel with:
 * - Summary sheet with annual totals
 * - Hourly breakdown: energia czynna, dystrybucja, jakość, OZE, kog, akcyza, mocowa
 * - Baseline (PV only) vs Project (PV+BESS) comparison
 * - Daily and monthly summaries
 */
async function exportEconomicsToExcel() {
  const variant = variants[currentVariant];
  if (!variant) {
    alert('Najpierw uruchom analizę BESS (Sizing)');
    return;
  }

  const settings = systemSettings || {};
  const tariffConfig = settings.tariffConfig || {};

  // Use lastSizingResult (stored from displaySizingVariants) or fallback
  const sizingResult = lastSizingResult || analysisResults?.sizingResult;

  // Check if we have sizing data
  if (!sizingResult?.variants || sizingResult.variants.length === 0) {
    alert('Brak danych do eksportu. Uruchom analizę sizing.');
    return;
  }

  // Find matching variant with hourly data
  let sizingVariant = sizingResult.variants.find(v =>
    v.power_kw === variant.bess_power_kw &&
    v.energy_kwh === variant.bess_energy_kwh
  );

  // Fallback: use first variant if no exact match
  if (!sizingVariant) {
    sizingVariant = sizingResult.variants[0];
    console.log('⚠️ Using first sizing variant as fallback');
  }

  // Check for hourly data - if not available, generate from load profile
  let projectImport = sizingVariant?.hourly_grid_import_kw;
  if (!projectImport || projectImport.length === 0) {
    console.log('⚠️ No hourly_grid_import_kw in sizing result, generating from load profile');

    // Try multiple sources for load profile
    let loadProfile = variant.hourlyLoad ||
                      variant.hourly_load_kw ||
                      variants[currentVariant]?.hourlyLoad ||
                      variants[currentVariant]?.hourly_load_kw ||
                      [];

    // Try localStorage consumption data
    if (loadProfile.length === 0) {
      const storedConsumption = localStorage.getItem('pv_consumption_data');
      if (storedConsumption) {
        try {
          const consumptionData = JSON.parse(storedConsumption);
          loadProfile = consumptionData.hourlyData?.values ||
                       consumptionData.values ||
                       consumptionData.hourly ||
                       [];
          console.log('📊 Loaded consumption from localStorage:', loadProfile.length, 'points');
        } catch (e) {
          console.warn('Failed to parse consumption data:', e);
        }
      }
    }

    // Try window.loadOnlyConsumptionData
    if (loadProfile.length === 0 && window.loadOnlyConsumptionData) {
      loadProfile = window.loadOnlyConsumptionData.hourlyData?.values ||
                   window.loadOnlyConsumptionData.values ||
                   [];
      console.log('📊 Using loadOnlyConsumptionData:', loadProfile.length, 'points');
    }

    // Try sizing request load_kw from lastSizingResult
    if (loadProfile.length === 0 && lastSizingResult?.request_summary?.load_kw) {
      loadProfile = lastSizingResult.request_summary.load_kw;
      console.log('📊 Using load_kw from sizing request:', loadProfile.length, 'points');
    }

    const pvProfile = variant.hourlyPv ||
                     variant.hourly_pv_kw ||
                     variants[currentVariant]?.hourlyPv ||
                     [];

    if (loadProfile.length > 0) {
      // Estimate: project import = load - pv - bess_discharge_per_hour
      const avgDischargePerHour = (sizingVariant.bess_discharged_kwh || variant.bess_discharged_kwh || 0) / loadProfile.length;
      projectImport = loadProfile.map((load, i) => {
        const pv = pvProfile[i] || 0;
        return Math.max(0, load - pv - avgDischargePerHour);
      });
      console.log('✅ Generated projectImport from load profile:', projectImport.length, 'points');
    } else {
      // Last resort: generate synthetic 8760-hour profile from annual totals
      const annualLoadKwh = variant.consumption ||
                           sizingVariant.dispatch_summary?.total_load_kwh ||
                           500000; // Default 500 MWh
      const avgLoadKw = annualLoadKwh / 8760;
      loadProfile = Array(8760).fill(avgLoadKw);

      const annualPvKwh = variant.production || 0;
      const avgPvKw = annualPvKwh / 8760;

      const avgDischargePerHour = (sizingVariant.bess_discharged_kwh || variant.bess_discharged_kwh || 0) / 8760;
      projectImport = loadProfile.map((load, i) => {
        // Simple sinusoidal pattern for PV (peak at noon)
        const hour = i % 24;
        const pvFactor = hour >= 6 && hour <= 18 ? Math.sin((hour - 6) * Math.PI / 12) : 0;
        const pv = avgPvKw * 2 * pvFactor;
        return Math.max(0, load - pv - avgDischargePerHour);
      });
      console.log('⚠️ Generated synthetic 8760h profile from annual totals');
    }
  }

  // Show loading state
  const btn = document.getElementById('exportExcelBtn');
  const originalText = btn.innerHTML;
  btn.innerHTML = '<span style="font-size: 18px;">⏳</span> Generowanie...';
  btn.disabled = true;

  try {
    // projectImport is already set above (either from sizing or generated)
    // Calculate baseline: load - pv (clipped to 0)
    const currentData = variants[currentVariant];
    const pvGeneration = currentData.hourlyPv || [];
    const loadProfile = currentData.hourlyLoad || [];

    let baselineImport = [];
    if (pvGeneration.length === projectImport.length && loadProfile.length === projectImport.length) {
      baselineImport = loadProfile.map((load, i) => Math.max(0, load - pvGeneration[i]));
    } else {
      // Fallback: use dispatch summary
      const baselineGridKwh = sizingVariant.dispatch_summary?.baseline_grid_import_kwh || 0;
      const projectGridKwh = sizingVariant.dispatch_summary?.total_grid_import_kwh || 0;

      // Estimate baseline from ratio
      const ratio = baselineGridKwh > 0 ? (baselineGridKwh / projectGridKwh) : 1.2;
      baselineImport = projectImport.map(v => v * ratio);
    }

    // Build request payload
    const payload = {
      baseline_import_kw: baselineImport,
      project_import_kw: projectImport,
      bess_power_kw: variant.bess_power_kw,
      bess_energy_kwh: variant.bess_energy_kwh,
      start_date: '2025-01-01',
      interval_minutes: 60,

      // ToU configuration from settings
      tariff_type: tariffConfig.type || 'two_zone',
      flat_rate: tariffConfig.flatRate || 750,
      day_rate: tariffConfig.twoZone?.dayRate || 850,
      night_rate: tariffConfig.twoZone?.nightRate || 450,
      peak_rate: tariffConfig.threeZone?.peakRate || 950,
      partial_rate: tariffConfig.threeZone?.partialRate || 700,
      off_peak_rate: tariffConfig.threeZone?.offPeakRate || 400,

      // ToU time windows
      weekday_day_start: tariffConfig.twoZone?.weekday?.start || 6,
      weekday_day_end: tariffConfig.twoZone?.weekday?.end || 22,
      weekend_day_start: tariffConfig.twoZone?.weekend?.start || 6,
      weekend_day_end: tariffConfig.twoZone?.weekend?.end || 13,
      peak1_start: tariffConfig.threeZone?.peak1?.start || 7,
      peak1_end: tariffConfig.threeZone?.peak1?.end || 13,
      peak2_start: tariffConfig.threeZone?.peak2?.start || 17,
      peak2_end: tariffConfig.threeZone?.peak2?.end || 21,

      // Fixed charges from settings
      distribution: settings.distribution || 200,
      quality_fee: settings.qualityFee || 10,
      oze_fee: settings.ozeFee || 7,
      cogeneration_fee: settings.cogenerationFee || 10,
      excise_tax: settings.exciseTax || 5,
      capacity_fee_som: settings.capacityFeeConfig?.somRate || 0.2194,

      // Report title
      project_name: `Analiza BESS Wariant ${currentVariant} - ${variant.bess_power_kw} kW / ${variant.bess_energy_kwh} kWh`,
    };

    console.log('📊 Exporting economics to Excel:', payload);

    // Call backend endpoint
    const response = await fetch('/api/bess-dispatch/sizing-export-excel', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Export failed: ${response.status} - ${errorText}`);
    }

    // Download the file
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `BESS_Economics_${variant.bess_power_kw}kW_${variant.bess_energy_kwh}kWh.xlsx`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    console.log('✅ Excel exported successfully');

  } catch (error) {
    console.error('❌ Excel export error:', error);
    alert(`Błąd eksportu Excel: ${error.message}`);
  } finally {
    // Restore button state
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}
window.exportEconomicsToExcel = exportEconomicsToExcel;

// ============================================
// BESS CYCLE ANIMATION
// ============================================

// Animation state
let bessAnimInterval = null;
let bessAnimIsPlaying = false;
let bessAnimCurrentHour = 0;
let bessAnimSpeed = 500; // ms per hour
let bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };

// Simulated hourly data (will be generated from variant data)
let bessAnimHourlyData = [];

/**
 * Initialize BESS animation with current variant data
 */
function initBessAnimation() {
  const variant = variants[currentVariant];
  if (!variant) {
    console.log('BESS Animation: No variant data');
    return;
  }

  // Generate simulated hourly data for 8760 hours
  bessAnimHourlyData = generateHourlyBessData(variant);
  bessAnimCurrentHour = 0;
  bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };

  // Update initial display
  updateBessAnimDisplay(0);

  console.log('BESS Animation initialized with', bessAnimHourlyData.length, 'hours of data');
}

/**
 * Generate simulated hourly BESS data from variant statistics
 */
function generateHourlyBessData(variant) {
  const hours = 8760;
  const data = [];

  const totalProduction = variant.production || 0; // kWh/year
  const totalLoad = variant.consumption || variant.load || totalProduction * 1.5;
  const bessEnergyKwh = variant.bess_energy_kwh || 100;
  const bessPowerKw = variant.bess_power_kw || 50;
  const bessCharged = variant.bess_charged_kwh || 0;
  const bessDischargedTotal = variant.bess_discharged_kwh || 0;
  const bessCurtailed = variant.bess_curtailed_kwh || 0;

  // Calculate average hourly values
  const avgPvPerHour = totalProduction / hours;
  const avgLoadPerHour = totalLoad / hours;

  // SOC tracking
  let soc = 20; // Start at 20%
  const socMin = 10;
  const socMax = 90;

  for (let h = 0; h < hours; h++) {
    const hourOfDay = h % 24;
    const dayOfYear = Math.floor(h / 24);
    const month = Math.floor(dayOfYear / 30.4);

    // Simulate PV production (peak at noon, seasonal variation)
    const solarFactor = Math.max(0, Math.sin((hourOfDay - 6) * Math.PI / 12));
    const seasonFactor = 0.5 + 0.5 * Math.sin((dayOfYear - 80) * 2 * Math.PI / 365);
    const pvPower = avgPvPerHour * 3 * solarFactor * (0.7 + 0.6 * seasonFactor);

    // Simulate load (higher during day, some variation)
    const loadFactor = 0.6 + 0.4 * Math.sin((hourOfDay - 14) * Math.PI / 12);
    const loadPower = avgLoadPerHour * (0.8 + 0.4 * loadFactor);

    // Energy balance
    const surplus = pvPower - loadPower;
    let charging = 0;
    let discharging = 0;
    let gridImport = 0;
    let curtailment = 0;

    if (surplus > 0) {
      // Excess PV - try to charge battery
      const canCharge = Math.min(surplus, bessPowerKw, (socMax - soc) * bessEnergyKwh / 100);
      if (canCharge > 0) {
        charging = canCharge;
        soc += (charging / bessEnergyKwh) * 100;
      }
      // Any remaining surplus is curtailed (0-export mode)
      curtailment = surplus - charging;
    } else {
      // Deficit - try to discharge battery
      const deficit = -surplus;
      const canDischarge = Math.min(deficit, bessPowerKw, (soc - socMin) * bessEnergyKwh / 100);
      if (canDischarge > 0) {
        discharging = canDischarge;
        soc -= (discharging / bessEnergyKwh) * 100;
      }
      // Remaining deficit from grid
      gridImport = deficit - discharging;
    }

    // Clamp SOC
    soc = Math.max(socMin, Math.min(socMax, soc));

    data.push({
      hour: h,
      hourOfDay,
      dayOfYear,
      month,
      pvPower: Math.round(pvPower * 10) / 10,
      loadPower: Math.round(loadPower * 10) / 10,
      charging: Math.round(charging * 10) / 10,
      discharging: Math.round(discharging * 10) / 10,
      gridImport: Math.round(gridImport * 10) / 10,
      curtailment: Math.round(curtailment * 10) / 10,
      soc: Math.round(soc * 10) / 10,
      batteryKwh: Math.round(soc * bessEnergyKwh / 100)
    });
  }

  return data;
}

/**
 * Toggle BESS animation play/pause
 */
function toggleBessAnimation() {
  if (bessAnimIsPlaying) {
    stopBessAnimation();
  } else {
    startBessAnimation();
  }
}

/**
 * Start BESS animation
 */
function startBessAnimation() {
  if (bessAnimHourlyData.length === 0) {
    initBessAnimation();
  }

  if (bessAnimHourlyData.length === 0) {
    console.warn('BESS Animation: No data to animate');
    return;
  }

  bessAnimIsPlaying = true;

  // Update button state
  const btn = document.getElementById('bessAnimPlayBtn');
  const icon = document.getElementById('bessAnimPlayIcon');
  const text = document.getElementById('bessAnimPlayText');
  if (btn) btn.classList.add('playing');
  if (icon) icon.textContent = '⏸️';
  if (text) text.textContent = 'Pauza';

  // Get speed from selector
  bessAnimSpeed = parseInt(document.getElementById('bessAnimSpeedSelect')?.value || '500');

  // Start animation loop
  bessAnimInterval = setInterval(() => {
    bessAnimCurrentHour++;
    if (bessAnimCurrentHour >= bessAnimHourlyData.length) {
      bessAnimCurrentHour = 0;
      bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };
    }
    updateBessAnimDisplay(bessAnimCurrentHour);
  }, bessAnimSpeed);

  console.log('BESS Animation started at speed:', bessAnimSpeed, 'ms/hour');
}

/**
 * Stop BESS animation
 */
function stopBessAnimation() {
  bessAnimIsPlaying = false;

  if (bessAnimInterval) {
    clearInterval(bessAnimInterval);
    bessAnimInterval = null;
  }

  // Update button state
  const btn = document.getElementById('bessAnimPlayBtn');
  const icon = document.getElementById('bessAnimPlayIcon');
  const text = document.getElementById('bessAnimPlayText');
  if (btn) btn.classList.remove('playing');
  if (icon) icon.textContent = '▶️';
  if (text) text.textContent = 'Start';

  console.log('BESS Animation stopped');
}

/**
 * Reset BESS animation
 */
function resetBessAnimation() {
  stopBessAnimation();
  bessAnimCurrentHour = 0;
  bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };
  updateBessAnimDisplay(0);
  console.log('BESS Animation reset');
}

/**
 * Jump to specific position in animation
 */
function bessAnimJump(direction) {
  const wasPlaying = bessAnimIsPlaying;
  if (wasPlaying) stopBessAnimation();

  switch (direction) {
    case 'start':
      bessAnimCurrentHour = 0;
      bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };
      break;
    case 'end':
      bessAnimCurrentHour = Math.max(0, bessAnimHourlyData.length - 1);
      break;
    case 'prev-day':
      bessAnimCurrentHour = Math.max(0, bessAnimCurrentHour - 24);
      recalculateDailyStats();
      break;
    case 'next-day':
      bessAnimCurrentHour = Math.min(bessAnimHourlyData.length - 1, bessAnimCurrentHour + 24);
      recalculateDailyStats();
      break;
  }

  updateBessAnimDisplay(bessAnimCurrentHour);
  if (wasPlaying) startBessAnimation();
}

/**
 * Update animation speed
 */
function updateBessAnimSpeed() {
  if (bessAnimIsPlaying) {
    stopBessAnimation();
    startBessAnimation();
  }
}

/**
 * Recalculate daily stats when jumping
 */
function recalculateDailyStats() {
  bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };
  const dayStart = Math.floor(bessAnimCurrentHour / 24) * 24;
  const dayEnd = Math.min(dayStart + 24, bessAnimCurrentHour + 1);

  for (let h = dayStart; h < dayEnd; h++) {
    const hourData = bessAnimHourlyData[h];
    if (hourData) {
      bessAnimDailyStats.pv += hourData.pvPower;
      bessAnimDailyStats.load += hourData.loadPower;
      bessAnimDailyStats.fromBess += hourData.discharging;
    }
  }

  // Calculate equivalent cycles
  const variant = variants[currentVariant];
  const bessEnergyKwh = variant?.bess_energy_kwh || 100;
  bessAnimDailyStats.cycles = bessAnimDailyStats.fromBess / bessEnergyKwh;
}

/**
 * Update BESS animation display
 */
function updateBessAnimDisplay(hourIndex) {
  if (hourIndex < 0 || hourIndex >= bessAnimHourlyData.length) return;

  const hourData = bessAnimHourlyData[hourIndex];
  const variant = variants[currentVariant];

  // Update time display
  const hourOfDay = hourData.hourOfDay;
  const dayOfYear = hourData.dayOfYear + 1;
  const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                      'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];
  const dayInMonth = (dayOfYear - 1) % 30 + 1;
  const monthIndex = Math.min(11, Math.floor((dayOfYear - 1) / 30.4));

  document.getElementById('animDate').textContent = `${dayInMonth} ${monthNames[monthIndex]}`;
  document.getElementById('animTime').textContent =
    `${hourOfDay.toString().padStart(2, '0')}:00`;

  // Day/night indicator
  const dayNightEl = document.getElementById('animDayNight');
  if (hourOfDay >= 6 && hourOfDay < 20) {
    dayNightEl.textContent = '☀️';
    dayNightEl.className = 'anim-daynight day';
  } else {
    dayNightEl.textContent = '🌙';
    dayNightEl.className = 'anim-daynight night';
  }

  // Update node values
  document.getElementById('animPvPower').textContent = `${formatNumberEU(hourData.pvPower, 1)} kW`;
  document.getElementById('animLoadPower').textContent = `${formatNumberEU(hourData.loadPower, 1)} kW`;
  document.getElementById('animBatteryKwh').textContent = `${formatNumberEU(hourData.batteryKwh, 0)} kWh`;
  document.getElementById('animGridPower').textContent = `${formatNumberEU(hourData.gridImport, 1)} kW`;
  document.getElementById('animCurtailment').textContent = `${formatNumberEU(hourData.curtailment, 1)} kW`;

  // Update battery fill level
  const batteryFill = document.getElementById('batteryFill');
  const batteryLevel = document.getElementById('batteryLevel');
  if (batteryFill) {
    batteryFill.style.height = `${hourData.soc}%`;
    // Add charging/discharging animation class
    batteryFill.classList.remove('charging', 'discharging');
    if (hourData.charging > 0) batteryFill.classList.add('charging');
    else if (hourData.discharging > 0) batteryFill.classList.add('discharging');
  }
  if (batteryLevel) {
    batteryLevel.textContent = `${Math.round(hourData.soc)}%`;
  }

  // Update flow arrows
  updateFlowArrow('arrowPvBattery', hourData.charging > 0);
  updateFlowArrow('arrowPvLoad', hourData.pvPower > 0 && hourData.loadPower > 0);
  updateFlowArrow('arrowBatteryLoad', hourData.discharging > 0);
  updateFlowArrow('arrowGridLoad', hourData.gridImport > 0);
  updateFlowArrow('arrowCurtailment', hourData.curtailment > 0);

  // Update flow values
  document.getElementById('flowPvBattery').textContent = hourData.charging > 0 ? `${formatNumberEU(hourData.charging, 0)} kW` : '';
  document.getElementById('flowPvLoad').textContent = hourData.pvPower > 0 ? `${formatNumberEU(Math.min(hourData.pvPower, hourData.loadPower), 0)} kW` : '';
  document.getElementById('flowBatteryLoad').textContent = hourData.discharging > 0 ? `${formatNumberEU(hourData.discharging, 0)} kW` : '';
  document.getElementById('flowGridLoad').textContent = hourData.gridImport > 0 ? `${formatNumberEU(hourData.gridImport, 0)} kW` : '';
  document.getElementById('flowCurtailment').textContent = hourData.curtailment > 0 ? `${formatNumberEU(hourData.curtailment, 0)} kW` : '';

  // Show/hide curtailment node
  const curtailmentNode = document.getElementById('curtailmentNode');
  if (curtailmentNode) {
    curtailmentNode.style.display = hourData.curtailment > 0 ? 'flex' : 'none';
  }

  // Update daily stats
  if (hourOfDay === 0) {
    bessAnimDailyStats = { pv: 0, load: 0, fromBess: 0, cycles: 0 };
  }
  bessAnimDailyStats.pv += hourData.pvPower;
  bessAnimDailyStats.load += hourData.loadPower;
  bessAnimDailyStats.fromBess += hourData.discharging;

  const bessEnergyKwh = variant?.bess_energy_kwh || 100;
  bessAnimDailyStats.cycles = bessAnimDailyStats.fromBess / bessEnergyKwh;

  document.getElementById('animDailyPv').textContent = `${formatNumberEU(bessAnimDailyStats.pv, 0)} kWh`;
  document.getElementById('animDailyLoad').textContent = `${formatNumberEU(bessAnimDailyStats.load, 0)} kWh`;
  document.getElementById('animDailyFromBess').textContent = `${formatNumberEU(bessAnimDailyStats.fromBess, 0)} kWh`;
  document.getElementById('animDailyCycles').textContent = formatNumberEU(bessAnimDailyStats.cycles, 2);

  // Update year progress
  document.getElementById('animDayOfYear').textContent = `${dayOfYear} / 365`;
  const yearProgressEl = document.getElementById('animYearProgress');
  if (yearProgressEl) {
    yearProgressEl.style.width = `${(dayOfYear / 365) * 100}%`;
  }
}

/**
 * Show/hide flow arrow with animation
 */
function updateFlowArrow(arrowId, active) {
  const arrow = document.getElementById(arrowId);
  if (arrow) {
    if (active) {
      arrow.classList.add('active');
    } else {
      arrow.classList.remove('active');
    }
  }
}

// Expose functions globally
window.selectVariant = selectVariant;
window.refreshData = refreshData;
window.exportBessData = exportBessData;
window.toggleBessAnimation = toggleBessAnimation;
window.bessAnimJump = bessAnimJump;
window.resetBessAnimation = resetBessAnimation;
window.updateBessAnimSpeed = updateBessAnimSpeed;

// Initialize animation when variant changes
const originalSelectVariant = selectVariant;
window.selectVariant = function(v) {
  originalSelectVariant(v);
  setTimeout(initBessAnimation, 500);
};

console.log('📦 bess.js fully loaded with animation support');

// ============================================
// NEW v3.3: SIZING VARIANTS (S/M/L) DISPLAY
// ============================================

/**
 * Display sizing variants (S/M/L) from bess-dispatch service
 * @param {Object} sizingResult - Result from /sizing endpoint
 */
function displaySizingVariants(sizingResult) {
  const section = document.getElementById('sizingVariantsSection');
  const grid = document.getElementById('sizingVariantsGrid');

  if (!section || !grid) {
    console.log('⚠️ Sizing variants section not found in DOM');
    return;
  }

  if (!sizingResult || !sizingResult.variants || sizingResult.variants.length === 0) {
    section.style.display = 'none';
    return;
  }

  // Store sizing result for Excel export
  lastSizingResult = sizingResult;
  console.log('📊 Stored sizing result for export:', sizingResult.variants?.length, 'variants');

  // Send v2 payload to Shell/Economics for savings breakdown display
  sendBessResultToShell(sizingResult);

  // Show section
  section.style.display = 'block';

  // Build HTML for variants
  let html = '';

  for (const v of sizingResult.variants) {
    const isRecommended = v.is_recommended;
    const statusClass = getStatusClass(v.degradation_status);
    const statusIcon = getStatusIcon(v.degradation_status);
    const statusLabel = getStatusLabel(v.degradation_status);

    html += `
      <div class="sizing-variant-card ${isRecommended ? 'recommended' : ''}">
        <div class="variant-header">
          <span class="variant-name">${v.variant_label}</span>
          <span class="variant-duration">${v.duration_h}h</span>
        </div>

        <div class="variant-specs">
          <div class="variant-spec">
            <div class="variant-spec-value">${formatNumberEU(v.power_kw, 0)}</div>
            <div class="variant-spec-label">kW</div>
          </div>
          <div class="variant-spec">
            <div class="variant-spec-value">${formatNumberEU(v.energy_kwh, 0)}</div>
            <div class="variant-spec-label">kWh</div>
          </div>
        </div>

        <div class="variant-economics">
          <div class="variant-econ-row">
            <span class="variant-econ-label">CAPEX:</span>
            <span class="variant-econ-value">${formatNumberEU(v.capex_pln / 1000, 1)} tys. PLN</span>
          </div>
          <div class="variant-econ-row">
            <span class="variant-econ-label">Oszczędności/rok:</span>
            <span class="variant-econ-value">${formatNumberEU(v.annual_savings_pln / 1000, 1)} tys. PLN</span>
          </div>
          ${v.savings_breakdown ? `
          <div class="savings-breakdown-section">
            <div class="breakdown-row">
              <span class="breakdown-label">⚡ Autokonsumpcja / redukcja importu</span>
              <span class="breakdown-value">${formatNumberEU(v.savings_breakdown.energy_savings_pln, 0)} PLN</span>
            </div>
            ${v.savings_breakdown.demand_charge_savings_pln > 0 ? `
            <div class="breakdown-row">
              <span class="breakdown-label">📉 Peak shaving (opłata za moc)</span>
              <span class="breakdown-value">${formatNumberEU(v.savings_breakdown.demand_charge_savings_pln, 0)} PLN</span>
            </div>
            ` : ''}
            ${v.savings_breakdown.capacity_fee_savings_pln > 0 ? `
            <div class="breakdown-row">
              <span class="breakdown-label">🧾 Opłata mocowa PL</span>
              <span class="breakdown-value">${formatNumberEU(v.savings_breakdown.capacity_fee_savings_pln, 0)} PLN</span>
            </div>
            ` : ''}
            ${v.savings_breakdown.arbitrage_savings_pln > 0 ? `
            <div class="breakdown-row">
              <span class="breakdown-label">🕐 Arbitraż ToU</span>
              <span class="breakdown-value">${formatNumberEU(v.savings_breakdown.arbitrage_savings_pln, 0)} PLN</span>
            </div>
            ` : ''}
            ${v.savings_breakdown.export_revenue_pln > 0 ? `
            <div class="breakdown-row">
              <span class="breakdown-label">💰 Sprzedaż do sieci</span>
              <span class="breakdown-value">${formatNumberEU(v.savings_breakdown.export_revenue_pln, 0)} PLN</span>
            </div>
            ` : ''}
            ${v.savings_breakdown.degradation_cost_pln > 0 ? `
            <div class="breakdown-row degradation">
              <span class="breakdown-label">🔋 Koszt degradacji</span>
              <span class="breakdown-value negative">-${formatNumberEU(v.savings_breakdown.degradation_cost_pln, 0)} PLN</span>
            </div>
            ` : ''}
            ${v.savings_breakdown.unserved_load_penalty_pln > 0 ? `
            <div class="breakdown-row unserved-penalty">
              <span class="breakdown-label">⚡ Kara za nieobsluzony</span>
              <span class="breakdown-value negative">-${formatNumberEU(v.savings_breakdown.unserved_load_penalty_pln, 0)} PLN</span>
            </div>
            ` : ''}
          </div>
          ` : ''}
          <div class="variant-econ-row">
            <span class="variant-econ-label">NPV:</span>
            <span class="variant-econ-value ${v.npv_pln < 0 ? 'negative' : ''}">${formatNumberEU(v.npv_pln / 1000, 0)} tys. PLN</span>
          </div>
          <div class="variant-econ-row">
            <span class="variant-econ-label">Payback:</span>
            <span class="variant-econ-value">${v.simple_payback_years < 100 ? formatNumberEU(v.simple_payback_years, 1) + ' lat' : '> 25 lat'}</span>
          </div>
          ${v.prices_summary ? `
          <div class="prices-info-section">
            ${v.prices_summary.baseline ? `
            <!-- ToU pricing breakdown -->
            <div class="tou-breakdown">
              <div class="tou-row baseline">
                <span class="tou-label">Baseline (PV-only):</span>
                <span class="tou-value">${formatNumberEU(v.prices_summary.baseline.total_cost_pln / 1000, 1)} tys. PLN/rok</span>
              </div>
              <div class="tou-row project">
                <span class="tou-label">Projekt (PV+BESS):</span>
                <span class="tou-value">${formatNumberEU(v.prices_summary.project.total_cost_pln / 1000, 1)} tys. PLN/rok</span>
              </div>
              <div class="tou-row savings">
                <span class="tou-label">Oszczędność całkowita:</span>
                <span class="tou-value positive">${formatNumberEU(v.prices_summary.savings.total_savings_pln / 1000, 1)} tys. PLN/rok</span>
              </div>
              ${v.prices_summary.config?.tariff_id ? `
              <div class="tou-row config">
                <span class="tou-label">Taryfa:</span>
                <span class="tou-value">${v.prices_summary.config.tariff_id}</span>
              </div>
              ` : ''}
            </div>
            ` : `
            <!-- Legacy flat pricing display -->
            <span class="prices-label">💰 Ceny:</span>
            <span class="prices-value">${formatNumberEU(v.prices_summary.import_price_pln_mwh, 0)} PLN/MWh</span>
            ${v.prices_summary.demand_charge_pln_kw_month > 0 ? `
            <span class="prices-value">${formatNumberEU(v.prices_summary.demand_charge_pln_kw_month, 0)} PLN/kW/mies.</span>
            ` : ''}
            `}
          </div>
          ` : ''}
          ${v.money_ledger ? `
          <!-- v1.9.0: Money Ledger - Koszty panel -->
          <div class="money-ledger-section">
            <div class="ledger-title">💰 Koszty (rocznie)</div>
            <table class="ledger-table">
              <thead>
                <tr>
                  <th>Kategoria</th>
                  <th>Baseline</th>
                  <th>Projekt</th>
                  <th>Delta</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Import energii</td>
                  <td>${formatNumberEU(v.money_ledger.baseline_annual.import_energy_cost_pln, 0)}</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.import_energy_cost_pln, 0)}</td>
                  <td class="${v.money_ledger.delta_annual_pln.import_energy_cost_pln > 0 ? 'positive' : ''}">${formatNumberEU(v.money_ledger.delta_annual_pln.import_energy_cost_pln, 0)}</td>
                </tr>
                <tr>
                  <td>Eksport do sieci</td>
                  <td>${formatNumberEU(v.money_ledger.baseline_annual.export_revenue_pln, 0)}</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.export_revenue_pln, 0)}</td>
                  <td class="${v.money_ledger.delta_annual_pln.export_revenue_pln > 0 ? 'positive' : ''}">${formatNumberEU(v.money_ledger.delta_annual_pln.export_revenue_pln, 0)}</td>
                </tr>
                ${v.money_ledger.baseline_annual.capacity_fee_pln > 0 || v.money_ledger.project_annual.capacity_fee_pln > 0 ? `
                <tr>
                  <td>Opłata mocowa</td>
                  <td>${formatNumberEU(v.money_ledger.baseline_annual.capacity_fee_pln, 0)}</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.capacity_fee_pln, 0)}</td>
                  <td class="${v.money_ledger.delta_annual_pln.capacity_fee_pln > 0 ? 'positive' : ''}">${formatNumberEU(v.money_ledger.delta_annual_pln.capacity_fee_pln, 0)}</td>
                </tr>
                ` : ''}
                ${v.money_ledger.baseline_annual.demand_charge_pln > 0 || v.money_ledger.project_annual.demand_charge_pln > 0 ? `
                <tr>
                  <td>Opłata za moc</td>
                  <td>${formatNumberEU(v.money_ledger.baseline_annual.demand_charge_pln, 0)}</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.demand_charge_pln, 0)}</td>
                  <td class="${v.money_ledger.delta_annual_pln.demand_charge_pln > 0 ? 'positive' : ''}">${formatNumberEU(v.money_ledger.delta_annual_pln.demand_charge_pln, 0)}</td>
                </tr>
                ` : ''}
                ${v.money_ledger.project_annual.degradation_cost_pln > 0 ? `
                <tr class="degradation-row">
                  <td>Degradacja baterii</td>
                  <td>0</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.degradation_cost_pln, 0)}</td>
                  <td class="negative">-${formatNumberEU(v.money_ledger.delta_annual_pln.degradation_cost_pln, 0)}</td>
                </tr>
                ` : ''}
                ${v.money_ledger.project_annual.unserved_penalty_pln > 0 ? `
                <tr class="penalty-row">
                  <td>Kara za nieobsłużone</td>
                  <td>0</td>
                  <td>${formatNumberEU(v.money_ledger.project_annual.unserved_penalty_pln, 0)}</td>
                  <td class="negative">-${formatNumberEU(v.money_ledger.delta_annual_pln.unserved_penalty_pln, 0)}</td>
                </tr>
                ` : ''}
              </tbody>
              <tfoot>
                <tr class="total-row">
                  <td><strong>SUMA</strong></td>
                  <td><strong>${formatNumberEU(v.money_ledger.baseline_annual.total_cost_pln, 0)}</strong></td>
                  <td><strong>${formatNumberEU(v.money_ledger.project_annual.total_cost_pln, 0)}</strong></td>
                  <td class="${v.money_ledger.delta_annual_pln.total_cost_pln > 0 ? 'positive' : ''} total-delta"><strong>${formatNumberEU(v.money_ledger.delta_annual_pln.total_cost_pln, 0)} PLN</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
          ` : ''}
        </div>

        <div class="variant-degradation">
          <div class="variant-degradation-title">Metryki degradacji</div>
          <div class="variant-deg-row">
            <span class="variant-deg-label">Throughput:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.throughput_total_mwh || 0, 1)} MWh/rok</span>
          </div>
          <div class="variant-deg-row">
            <span class="variant-deg-label">EFC łącznie:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.efc_total || 0, 0)} cykli/rok</span>
          </div>
          ${v.degradation?.efc_pv > 0 || v.degradation?.efc_peak > 0 ? `
          <div class="variant-deg-row">
            <span class="variant-deg-label">↳ EFC PV surplus:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.efc_pv || 0, 0)} cykli</span>
          </div>
          <div class="variant-deg-row">
            <span class="variant-deg-label">↳ EFC Peak Shaving:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.efc_peak || 0, 0)} cykli</span>
          </div>
          ` : ''}
          ${v.degradation?.peak_events_count > 0 ? `
          <div class="variant-deg-row peak-shaving-info">
            <span class="variant-deg-label">Peak Shaving zdarzenia:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.peak_events_count || 0, 0)} h/rok</span>
          </div>
          <div class="variant-deg-row">
            <span class="variant-deg-label">↳ Energia Peak:</span>
            <span class="variant-deg-value">${formatNumberEU((v.degradation?.peak_events_energy_kwh || 0) / 1000, 1)} MWh</span>
          </div>
          <div class="variant-deg-row">
            <span class="variant-deg-label">↳ Max moc Peak:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.peak_max_discharge_kw || 0, 0)} kW</span>
          </div>
          ` : ''}
          ${v.degradation?.charge_from_pv_kwh > 0 || v.degradation?.charge_from_grid_kwh > 0 ? `
          <div class="variant-deg-row charge-source-info">
            <span class="variant-deg-label">Ładowanie z PV:</span>
            <span class="variant-deg-value">${formatNumberEU(v.degradation?.charge_pv_pct || 0, 0)}% (${formatNumberEU((v.degradation?.charge_from_pv_kwh || 0) / 1000, 1)} MWh)</span>
          </div>
          ${v.degradation?.charge_from_grid_kwh > 0 ? `
          <div class="variant-deg-row">
            <span class="variant-deg-label">Ładowanie z sieci:</span>
            <span class="variant-deg-value">${formatNumberEU((v.degradation?.charge_from_grid_kwh || 0) / 1000, 1)} MWh</span>
          </div>
          ` : ''}
          ` : ''}
        </div>

        <div class="variant-status ${statusClass}">
          ${statusIcon} ${statusLabel}
        </div>
      </div>
    `;
  }

  grid.innerHTML = html;
  console.log('✅ Sizing variants displayed:', sizingResult.variants.length);
}

/**
 * Display degradation budget status
 * @param {Object} degradation - Degradation metrics from dispatch result
 * @param {Object} budget - Budget limits (optional)
 */
function displayDegradationBudget(degradation, budget) {
  const section = document.getElementById('degradationBudgetSection');

  if (!section) {
    console.log('⚠️ Degradation budget section not found');
    return;
  }

  if (!degradation) {
    section.style.display = 'none';
    return;
  }

  // Show section
  section.style.display = 'block';

  // Update values
  setElementText('budgetThroughput', formatNumberEU(degradation.throughput_total_mwh || 0, 1));
  setElementText('budgetEFC', formatNumberEU(degradation.efc_total || 0, 0));

  // Budget limits
  if (budget) {
    setElementText('budgetThroughputLimit', budget.max_throughput_mwh_per_year
      ? `Limit: ${formatNumberEU(budget.max_throughput_mwh_per_year, 0)} MWh`
      : 'Limit: brak');
    setElementText('budgetEFCLimit', budget.max_efc_per_year
      ? `Limit: ${formatNumberEU(budget.max_efc_per_year, 0)} cykli`
      : 'Limit: brak');
  }

  // Status
  const status = degradation.budget_status || 'ok';
  const statusCard = document.getElementById('budgetStatusCard');

  setElementText('budgetStatusIcon', getStatusIcon(status));
  setElementText('budgetStatus', getStatusLabel(status));
  setElementText('budgetUtilization', `Wykorzystanie: ${formatNumberEU(degradation.budget_utilization_pct || 0, 0)}%`);

  // Update card class
  if (statusCard) {
    statusCard.className = 'stat-card bess-budget-' + status;
  }

  // Breakdown (for STACKED mode)
  if (degradation.throughput_pv_mwh > 0 || degradation.throughput_peak_mwh > 0) {
    setElementText('budgetBreakdown', 'STACKED');
    setElementText('budgetBreakdownDetail',
      `PV: ${formatNumberEU(degradation.throughput_pv_mwh, 1)} MWh | Peak: ${formatNumberEU(degradation.throughput_peak_mwh, 1)} MWh`);
  } else {
    setElementText('budgetBreakdown', 'PV Surplus');
    setElementText('budgetBreakdownDetail', `Total: ${formatNumberEU(degradation.throughput_total_mwh, 1)} MWh`);
  }
}

/**
 * Display STACKED mode info banner
 * @param {Object} stackedInfo - Stacked mode parameters
 * @param {Object} arbitrageInfo - Optional arbitrage info from dispatch result
 */
function displayStackedModeInfo(stackedInfo, arbitrageInfo = null) {
  const banner = document.getElementById('stackedModeInfo');

  if (!banner) return;

  if (!stackedInfo || !stackedInfo.peak_limit_kw) {
    banner.style.display = 'none';
    return;
  }

  banner.style.display = 'block';

  // Check if arbitrage is enabled
  const arbitrageConfig = collectArbitrageConfig();
  const hasArbitrage = arbitrageConfig !== null || (arbitrageInfo && arbitrageInfo.enabled);

  if (hasArbitrage) {
    banner.classList.add('with-arbitrage');
    // Update banner text to include arbitrage
    const bannerText = banner.querySelector('.banner-text');
    if (bannerText) {
      // Determine arbitrage type and display name
      const isOsdArbitrage = arbitrageConfig?.type === 'osd_tariff';
      const isRdnArbitrage = arbitrageConfig?.type === 'rdn_spot';

      let arbitrageLabel = 'ToU';
      if (isOsdArbitrage) {
        const settings = window.systemSettings || systemSettings || {};
        const operator = (settings.bessOsdOperator || 'pge').toUpperCase();
        const group = settings.bessOsdTariffGroup || 'C12a';
        arbitrageLabel = `OSD ${operator} ${group}`;
      } else if (isRdnArbitrage) {
        arbitrageLabel = 'RDN Spot';
      }

      bannerText.innerHTML = `
        <strong>Tryb STACKED + Arbitraż:</strong> Bateria świadczy trzy usługi - Peak Shaving (priorytet 1), PV Shifting (priorytet 2) i Arbitraż ${isOsdArbitrage ? 'Taryfowy' : 'Cenowy'} (priorytet 3).
        <span id="stackedReserveInfo">Rezerwa SOC: ${(stackedInfo.reserve_fraction * 100).toFixed(0)}% dla peak shaving.</span>
        <span id="stackedPeakLimit">Limit importu: ${formatNumberEU(stackedInfo.peak_limit_kw, 0)} kW.</span>
        <span class="arbitrage-savings-highlight">⚡ Arbitraż aktywny (${arbitrageLabel})</span>
      `;
    }
  } else {
    banner.classList.remove('with-arbitrage');
    setElementText('stackedReserveInfo', `Rezerwa SOC: ${(stackedInfo.reserve_fraction * 100).toFixed(0)}% dla peak shaving.`);
    setElementText('stackedPeakLimit', `Limit importu: ${formatNumberEU(stackedInfo.peak_limit_kw, 0)} kW.`);
  }
}

// Helper functions
function getStatusClass(status) {
  switch (status?.toLowerCase()) {
    case 'ok': return 'ok';
    case 'warning': return 'warning';
    case 'exceeded': return 'exceeded';
    default: return 'ok';
  }
}

function getStatusIcon(status) {
  switch (status?.toLowerCase()) {
    case 'ok': return '✅';
    case 'warning': return '⚠️';
    case 'exceeded': return '🚫';
    default: return '✅';
  }
}

function getStatusLabel(status) {
  switch (status?.toLowerCase()) {
    case 'ok': return 'OK - w budżecie';
    case 'warning': return 'Uwaga - zbliża się do limitu';
    case 'exceeded': return 'Przekroczono budżet!';
    default: return 'OK';
  }
}

function setElementText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

/**
 * Fetch sizing variants from bess-dispatch service
 * Uses unified BESS Request Builder for consistent parameters
 * This is now a WHAT-IF function - main sizing comes from pv-calculation/config
 */
async function fetchSizingVariants(pvData, loadData, bessConfig) {
  // Skip if no data or BESS disabled
  if (!pvData || !loadData || !bessConfig || !bessConfig.enabled) {
    console.log('⚠️ Cannot fetch sizing variants - missing data or BESS disabled');
    return;
  }

  // Use relative URL to go through nginx proxy
  const bessDispatchUrl = '/api/bess-dispatch';

  try {
    console.log('🔬 Fetching sizing variants (what-if mode)...');

    // =========================================================================
    // Use unified BESS Request Builder (Single Source of Truth)
    // =========================================================================
    let requestBody;
    const parentWindow = window.parent !== window ? window.parent : window;

    // Collect arbitrage configuration from UI
    const arbitrageConfig = collectArbitrageConfig();

    if (parentWindow.buildBessRequest) {
      // Use unified builder with what-if overrides from bessConfig
      const overrides = {
        mode: bessConfig.stacked_mode ? 'stacked' : 'pv_surplus',
        peak_limit_kw: bessConfig.peak_limit_kw || null,
        reserve_fraction: bessConfig.reserve_fraction || 0.3,
        roundtrip_efficiency: bessConfig.roundtrip_efficiency || 0.90,
        soc_min: bessConfig.soc_min || 0.10,
        soc_max: bessConfig.soc_max || 0.90,
        max_efc_per_year: bessConfig.max_efc_per_year || null,
        max_throughput_mwh_per_year: bessConfig.max_throughput_mwh_per_year || null,
      };

      // Add arbitrage if enabled
      if (arbitrageConfig && bessConfig.stacked_mode) {
        overrides.arbitrage_config = {
          enabled: true,
          tariff_id: arbitrageConfig.tariff_id,
          strategy: arbitrageConfig.strategy,
          charge_below_percentile: arbitrageConfig.charge_below_percentile,
          discharge_above_percentile: arbitrageConfig.discharge_above_percentile,
          arbitrage_soc_min: arbitrageConfig.arbitrage_soc_min,
        };
        console.log('⚡ Arbitrage enabled for sizing:', arbitrageConfig);
      }

      requestBody = parentWindow.buildBessRequest({
        load_kw: loadData,
        pv_generation_kw: pvData,
        overrides: overrides
      });

      // Validate
      const validation = parentWindow.validateBessRequest(requestBody);
      if (!validation.valid) {
        console.error('❌ Invalid BESS request:', validation.errors);
        throw new Error('Cannot build valid BESS request: ' + validation.errors.join(', '));
      }
      if (validation.warnings.length > 0) {
        console.warn('⚠️ BESS request warnings:', validation.warnings);
      }

      // Mark as what-if
      requestBody._isWhatIf = true;

      // v0.6.0: Finance config with lifecycle features
      requestBody.finance_config = {
        horizon_years: 15,
        discount_rate: 0.08,
        include_cashflow_timeseries: true,
        discount_rate_sweep: [0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
        // v0.6.0 PR2: Battery replacement (optional)
        replacement_year: bessConfig.replacement_year || null,
        replacement_capex_pln: bessConfig.replacement_capex_pln || null,
        // v0.6.0 PR3: Performance degradation
        bess_degradation_pct_per_year: bessConfig.bess_degradation_pct_per_year || 0.0,
        pv_degradation_pct_per_year: bessConfig.pv_degradation_pct_per_year || 0.0,
        // v0.6.0 PR4: Price/CAPEX sensitivity sweeps
        energy_price_multiplier_sweep: [0.8, 0.9, 1.0, 1.1, 1.2],
        capex_multiplier_sweep: [0.8, 0.9, 1.0, 1.1, 1.2],
      };

    } else {
      // Fallback: legacy inline request
      console.warn('⚠️ BESS Request Builder not available - using legacy inline request');
      requestBody = {
        pv_generation_kw: pvData,
        load_kw: loadData,
        interval_minutes: 60,
        mode: bessConfig.stacked_mode ? 'stacked' : 'pv_surplus',
        peak_limit_kw: bessConfig.peak_limit_kw || null,
        reserve_fraction: bessConfig.reserve_fraction || 0.3,
        durations_h: [1.0, 2.0, 4.0],
        roundtrip_efficiency: bessConfig.roundtrip_efficiency || 0.90,
        soc_min: bessConfig.soc_min || 0.10,
        soc_max: bessConfig.soc_max || 0.90,
        capex_per_kwh: bessConfig.capex_per_kwh || 1500,
        capex_per_kw: bessConfig.capex_per_kw || 300,
        import_price_pln_mwh: 800,
        max_efc_per_year: bessConfig.max_efc_per_year || null,
        max_throughput_mwh_per_year: bessConfig.max_throughput_mwh_per_year || null,
      };

      // Add arbitrage config if enabled
      if (arbitrageConfig && bessConfig.stacked_mode) {
        requestBody.arbitrage_config = {
          enabled: true,
          tariff_id: arbitrageConfig.tariff_id,
          strategy: arbitrageConfig.strategy,
          charge_below_percentile: arbitrageConfig.charge_below_percentile,
          discharge_above_percentile: arbitrageConfig.discharge_above_percentile,
          arbitrage_soc_min: arbitrageConfig.arbitrage_soc_min,
        };
        requestBody.start_date = arbitrageConfig.start_date;
        console.log('⚡ Arbitrage enabled for sizing:', arbitrageConfig);
      }
    }

    // v0.6.0: Finance config with lifecycle features
    requestBody.finance_config = {
      horizon_years: 15,
      discount_rate: 0.08,
      include_cashflow_timeseries: true,
      // v0.5.0: Discount rate sensitivity
      discount_rate_sweep: [0.04, 0.06, 0.08, 0.10, 0.12, 0.15],
      // v0.6.0 PR2: Battery replacement (optional - from bessConfig)
      replacement_year: bessConfig.replacement_year || null,
      replacement_capex_pln: bessConfig.replacement_capex_pln || null,
      // v0.6.0 PR3: Performance degradation (from bessConfig)
      bess_degradation_pct_per_year: bessConfig.bess_degradation_pct_per_year || 0.0,
      pv_degradation_pct_per_year: bessConfig.pv_degradation_pct_per_year || 0.0,
      // v0.6.0 PR4: Price/CAPEX sensitivity sweeps
      energy_price_multiplier_sweep: [0.8, 0.9, 1.0, 1.1, 1.2],
      capex_multiplier_sweep: [0.8, 0.9, 1.0, 1.1, 1.2],
    };
    console.log('[BESS] Finance config with lifecycle features:', requestBody.finance_config);

    const response = await fetch(`${bessDispatchUrl}/sizing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();
    result._isWhatIf = true;  // Mark result as what-if
    console.log('✅ Sizing variants received (what-if):', result);

    // Display results
    displaySizingVariants(result);

    // v0.5.0: Display finance section (cashflow + sensitivity)
    displayFinanceSection(result);

    // Display degradation for recommended variant
    if (result.variants && result.variants.length > 0) {
      const recommended = result.variants.find(v => v.is_recommended) || result.variants[0];
      if (recommended.degradation) {
        displayDegradationBudget(recommended.degradation, {
          max_efc_per_year: bessConfig.max_efc_per_year,
          max_throughput_mwh_per_year: bessConfig.max_throughput_mwh_per_year,
        });
      }
    }

    // Display STACKED mode info if active
    if (bessConfig.stacked_mode && bessConfig.peak_limit_kw) {
      displayStackedModeInfo({
        peak_limit_kw: bessConfig.peak_limit_kw,
        reserve_fraction: bessConfig.reserve_fraction || 0.3,
      });
    }

  } catch (error) {
    console.error('❌ Error fetching sizing variants:', error);
    // Hide sections on error
    const section = document.getElementById('sizingVariantsSection');
    if (section) section.style.display = 'none';
  }
}

/**
 * Try to fetch sizing variants using existing variant data
 * Generates simulated hourly profile from variant statistics
 */
async function tryFetchSizingVariants(variant) {
  // Re-enabled for S/M/L grid display (what-if analysis, does not override SSoT)
  console.log('🔋 tryFetchSizingVariants: checking if we can show S/M/L grid...');

  if (!variant || variant.bess_power_kw <= 0) {
    console.log('⚠️ No BESS data in variant, skipping S/M/L grid');
    return;
  }

  // Check if we already have bessResult with variants from shell
  if (window.bessResult?.variants?.length > 0) {
    console.log('✅ Using existing bessResult variants from shell');
    displaySizingVariants({ variants: window.bessResult.variants });
    return;
  }

  // Try to get hourly data from shell
  const hourlyData = window.sharedData?.hourlyData || window.hourlyData;
  const consumptionValues = hourlyData?.values || hourlyData;
  const pvData = window.sharedData?.pvData;

  if (!consumptionValues || !Array.isArray(consumptionValues) || consumptionValues.length < 24) {
    console.log('⚠️ No hourly data available for S/M/L sizing. Use "Zastosuj konfigurację" button to run sizing manually.');
    // Show the advanced config section so user can trigger sizing manually
    const advSection = document.getElementById('advancedConfigSection');
    if (advSection) {
      advSection.style.display = 'block';
    }
    return;
  }

  // Build BESS config from current variant and settings
  const settings = systemSettings || {};
  const bessConfig = {
    enabled: true,
    power_kw: variant.bess_power_kw,
    energy_kwh: variant.bess_energy_kwh,
    roundtrip_efficiency: settings.bessRoundtripEfficiency || 0.90,
    soc_min: settings.bessSocMin || 0.10,
    soc_max: settings.bessSocMax || 0.90,
    durations_h: [1, 2, 4],  // S/M/L grid
    capex_per_kwh: settings.bessCapexPerKwh || 1500,
    capex_per_kw: settings.bessCapexPerKw || 300,
    discount_rate: (settings.discountRate || 7) / 100,
    analysis_years: settings.analysisYears || 15,
    stacked_mode: settings.bessPeakShavingEnabled || false,
    peak_limit_kw: settings.bessPeakShavingTargetKw || null,
    reserve_fraction: settings.bessReserveFraction || 0.30,
    max_efc_per_year: settings.bessMaxEfcPerYear || null,
  };

  console.log('🔋 Calling fetchSizingVariants for S/M/L grid...');
  try {
    await fetchSizingVariants(pvData || [], consumptionValues, bessConfig);
  } catch (error) {
    console.error('❌ tryFetchSizingVariants error:', error);
  }
}

// Export new functions
window.displaySizingVariants = displaySizingVariants;
window.displayDegradationBudget = displayDegradationBudget;
window.displayStackedModeInfo = displayStackedModeInfo;
window.fetchSizingVariants = fetchSizingVariants;
window.tryFetchSizingVariants = tryFetchSizingVariants;

// ============================================
// SENSITIVITY ANALYSIS (TORNADO CHART)
// ============================================

let tornadoChart = null;
let sensitivityData = null;

/**
 * Run sensitivity analysis for current BESS configuration
 */
async function runSensitivityAnalysis() {
  console.log('📊 Running sensitivity analysis...');

  const statusEl = document.getElementById('sensitivityStatus');
  const btnEl = document.getElementById('runSensitivityBtn');

  if (statusEl) statusEl.textContent = 'Obliczanie...';
  if (btnEl) btnEl.disabled = true;

  try {
    // Get current variant data
    const variantData = variants[currentVariant];
    if (!variantData) {
      throw new Error('Brak danych dla bieżącego wariantu');
    }

    // Check for BESS data (flat properties, not nested object)
    const bessPowerKw = variantData.bess_power_kw || 0;
    const bessEnergyKwh = variantData.bess_energy_kwh || 0;

    if (bessPowerKw <= 0 || bessEnergyKwh <= 0) {
      throw new Error('Brak konfiguracji BESS - najpierw wybierz wariant z BESS');
    }

    const settings = systemSettings || {};

    // Generate 8760 hourly profiles from variant statistics (same as buildSizingRequest)
    const hours = 8760;
    const pvData = [];
    const loadData = [];

    const totalProduction = variantData.production || 500000; // kWh/year
    const totalLoad = variantData.consumption || variantData.load || totalProduction * 1.2;

    // Scale factors to match annual totals
    const pvScaleFactor = totalProduction / 1127000; // Base 1 MWp production ~1127 MWh
    const loadScaleFactor = totalLoad / 8760 / 50; // Base load ~50 kW avg

    for (let h = 0; h < hours; h++) {
      const dayOfYear = Math.floor(h / 24);
      const hourOfDay = h % 24;

      // PV profile: bell curve during daylight, seasonal variation
      const seasonFactor = 1 + 0.5 * Math.sin((dayOfYear - 80) * 2 * Math.PI / 365);
      let pvHour = 0;
      if (hourOfDay >= 6 && hourOfDay <= 20) {
        const solarAngle = (hourOfDay - 6) / 14 * Math.PI;
        pvHour = Math.sin(solarAngle) * seasonFactor * 1000 * pvScaleFactor;
      }
      pvData.push(Math.max(0, pvHour));

      // Load profile: base load + daily pattern + some randomness
      const workdayFactor = (dayOfYear % 7 < 5) ? 1.2 : 0.6;
      let loadHour = 30 * loadScaleFactor; // base load
      if (hourOfDay >= 8 && hourOfDay <= 18) {
        loadHour += 40 * loadScaleFactor * workdayFactor;
      } else if (hourOfDay >= 6 && hourOfDay <= 22) {
        loadHour += 15 * loadScaleFactor;
      }
      loadData.push(Math.max(10, loadHour));
    }

    console.log('📊 Sensitivity: Generated profiles - PV sum:', pvData.reduce((a, b) => a + b, 0).toFixed(0), 'kWh, Load sum:', loadData.reduce((a, b) => a + b, 0).toFixed(0), 'kWh');

    // Build request
    const request = {
      pv_generation_kw: pvData,
      load_kw: loadData,
      interval_minutes: 60,
      battery_power_kw: bessPowerKw,
      battery_energy_kwh: bessEnergyKwh,
      roundtrip_efficiency: settings.bessRoundtripEfficiency || 0.9,
      soc_min: settings.bessSocMin || 0.1,
      soc_max: settings.bessSocMax || 0.9,
      mode: settings.bessPeakShavingEnabled ? 'stacked' : 'pv_surplus',
      capex_per_kwh: settings.bessCapexPerKwh || 1500,
      capex_per_kw: settings.bessCapexPerKw || 300,
      opex_pct_per_year: 0.015,
      discount_rate: 0.07,
      analysis_years: settings.bessLifetimeYears || 15,
      import_price_pln_mwh: settings.energyPurchasePrice || 800,
    };

    // Call API via nginx proxy
    const response = await fetch('/api/bess-dispatch/sensitivity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`API error: ${response.status} - ${err}`);
    }

    sensitivityData = await response.json();
    console.log('📊 Sensitivity result:', sensitivityData);

    // Display results
    displaySensitivityResults(sensitivityData);

    if (statusEl) statusEl.textContent = '✅ Gotowe';

  } catch (error) {
    console.error('❌ Sensitivity analysis error:', error);
    if (statusEl) statusEl.textContent = '❌ Błąd: ' + error.message;
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}

/**
 * Display sensitivity analysis results
 */
function displaySensitivityResults(data) {
  const section = document.getElementById('sensitivitySection');
  if (section) section.style.display = 'block';

  // Base case summary
  document.getElementById('sensBaseNpv').textContent =
    formatNumberEU(data.base_npv_pln / 1000, 0) + ' tys. PLN';
  document.getElementById('sensBasePayback').textContent =
    data.base_payback_years < 100 ? formatNumberEU(data.base_payback_years, 1) + ' lat' : '> 25 lat';
  document.getElementById('sensBaseCapex').textContent =
    formatNumberEU(data.base_capex_pln / 1000, 0) + ' tys. PLN';

  // Build table
  const tbody = document.getElementById('sensitivityTableBody');
  if (tbody) {
    let html = '';
    for (const p of data.parameters) {
      html += `
        <tr>
          <td><strong>${p.parameter_label}</strong></td>
          <td>${formatNumberEU(p.base_value, 1)} ${p.unit}</td>
          <td>${formatNumberEU(p.low_value, 1)}</td>
          <td class="${p.low_npv_pln < 0 ? 'negative' : ''}">${formatNumberEU(p.low_npv_pln / 1000, 0)} tys.</td>
          <td>${formatNumberEU(p.high_value, 1)}</td>
          <td class="${p.high_npv_pln < 0 ? 'negative' : ''}">${formatNumberEU(p.high_npv_pln / 1000, 0)} tys.</td>
          <td><strong>${formatNumberEU(p.npv_swing_pct, 0)}%</strong></td>
        </tr>
      `;
    }
    tbody.innerHTML = html;
  }

  // Breakeven warnings
  const warningsDiv = document.getElementById('breakevenWarnings');
  const warningsText = document.getElementById('breakevenText');
  if (data.breakeven_scenarios && data.breakeven_scenarios.length > 0) {
    warningsDiv.style.display = 'flex';
    warningsText.innerHTML = data.breakeven_scenarios.join('<br>');
  } else {
    warningsDiv.style.display = 'none';
  }

  // Draw tornado chart
  drawTornadoChart(data);
}

/**
 * Draw tornado chart using Chart.js
 */
function drawTornadoChart(data) {
  const canvas = document.getElementById('tornadoChart');
  if (!canvas) return;

  // Destroy existing chart
  if (tornadoChart) {
    tornadoChart.destroy();
    tornadoChart = null;
  }

  const ctx = canvas.getContext('2d');

  // Prepare data - sorted by swing (already sorted from API)
  const labels = data.parameters.map(p => p.parameter_label);
  const baseNpv = data.base_npv_pln / 1000;

  // For each parameter: negative side (low NPV - base) and positive side (high NPV - base)
  const lowDeltas = data.parameters.map(p => (p.low_npv_pln - data.base_npv_pln) / 1000);
  const highDeltas = data.parameters.map(p => (p.high_npv_pln - data.base_npv_pln) / 1000);

  tornadoChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: '-20%',
          data: lowDeltas,
          backgroundColor: lowDeltas.map(d => d < 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(34, 197, 94, 0.8)'),
          borderColor: lowDeltas.map(d => d < 0 ? 'rgb(239, 68, 68)' : 'rgb(34, 197, 94)'),
          borderWidth: 1
        },
        {
          label: '+20%',
          data: highDeltas,
          backgroundColor: highDeltas.map(d => d < 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(34, 197, 94, 0.8)'),
          borderColor: highDeltas.map(d => d < 0 ? 'rgb(239, 68, 68)' : 'rgb(34, 197, 94)'),
          borderWidth: 1
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: {
          display: true,
          text: `Wpływ na NPV (baza: ${formatNumberEU(baseNpv, 0)} tys. PLN)`,
          font: { size: 14 }
        },
        legend: {
          display: true,
          position: 'top'
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              const value = context.raw;
              return `${context.dataset.label}: ${value > 0 ? '+' : ''}${formatNumberEU(value, 0)} tys. PLN`;
            }
          }
        }
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Zmiana NPV [tys. PLN]'
          },
          grid: {
            color: 'rgba(0, 0, 0, 0.1)'
          }
        },
        y: {
          grid: {
            display: false
          }
        }
      }
    }
  });
}

/**
 * Show sensitivity section if BESS data is available
 */
function showSensitivitySectionIfAvailable() {
  const section = document.getElementById('sensitivitySection');
  const variantData = variants[currentVariant];

  if (section && variantData && variantData.bess && variantData.bess.enabled) {
    section.style.display = 'block';
  }
}

// Export sensitivity functions
window.runSensitivityAnalysis = runSensitivityAnalysis;
window.displaySensitivityResults = displaySensitivityResults;
window.drawTornadoChart = drawTornadoChart;
window.showSensitivitySectionIfAvailable = showSensitivitySectionIfAvailable;

// ============================================
// ADVANCED CONFIGURATION (Topology, Objective, Constraints)
// v3.12 - Multi-topology and Multi-objective support
// ============================================

// Current configuration state
let advancedConfig = {
  topology: 'pv_load',           // 'pv_load', 'load_only', 'pv_only'
  objective: 'npv',              // 'npv', 'payback', 'self_consumption', 'peak_reduction', 'efc_utilization'
  constraints: [],               // Array of {type, value, hard}
  // v0.7.0 Grid Constraints
  gridConstraints: {
    maxExportKw: null,           // null = unlimited export
    maxImportKw: null,           // null = unlimited import
    allowExport: true,           // false = no export allowed
    unservedLoadPenaltyPlnKwh: 0 // penalty rate for unserved load
  },
  // v0.8.0 Sizing Constraints (soft constraints for variant feasibility)
  sizingConstraints: {
    maxCapexPln: null,           // null = no limit
    maxPaybackYears: null,       // null = no limit
    minNpvPln: null,             // null = no limit
    minNetSavingsPln: null,      // null = no limit
    requireNoUnservedLoad: false,
    maxUnservedLoadKwh: null     // null = no limit
  }
};

// Objective descriptions for info display
const objectiveDescriptions = {
  npv: 'NPV uwzględnia wartość pieniądza w czasie i pełne koszty inwestycji',
  payback: 'Minimalizuj okres zwrotu - szybszy zwrot inwestycji',
  self_consumption: 'Maksymalizuj wykorzystanie własnej energii z PV',
  peak_reduction: 'Maksymalizuj redukcję szczytów mocy z sieci',
  efc_utilization: 'Optymalizuj wykorzystanie cykli baterii w budżecie degradacji'
};

// v3.19: Reason code to Polish description mapping
const reasonCodeDescriptions = {
  npv_max: 'Najwyższe NPV',
  payback_min: 'Najkrótszy payback',
  self_consumption_max: 'Najwyższe autokonsumpcja',
  peak_reduction_max: 'Najwyższa redukcja szczytów',
  efc_utilization_max: 'Optymalne wykorzystanie cykli',
  constrained_fallback: 'Wariant awaryjny (ograniczenia)'
};

/**
 * v3.19: Format recommended reason using structured fields from API
 * Uses machine-readable code/metric/value/unit fields instead of string parsing
 * @param {object} result - Sizing result from bess-dispatch API
 * @returns {string} Human-readable reason in Polish
 */
function formatRecommendedReason(result) {
  // Prefer structured fields (v0.4.1+)
  const code = result.recommended_reason_code;
  const metric = result.recommended_reason_metric;
  const value = result.recommended_reason_value;
  const unit = result.recommended_reason_unit;

  if (code && value !== undefined && value !== null) {
    // Use structured data
    const description = reasonCodeDescriptions[code] || code;
    const formattedValue = formatReasonValue(value, metric, unit);
    return `${description}: ${formattedValue}`;
  }

  // Fallback to legacy string if available
  if (result.recommended_reason) {
    return result.recommended_reason;
  }

  // Final fallback
  return 'Najlepszy wynik optymalizacji';
}

/**
 * v3.19: Format reason value based on metric type
 * @param {number} value - The metric value
 * @param {string} metric - Metric name (npv_pln, payback_years, etc.)
 * @param {string} unit - Unit string (PLN, years, %, etc.)
 * @returns {string} Formatted value with unit
 */
function formatReasonValue(value, metric, unit) {
  if (metric === 'npv_pln' || unit === 'PLN') {
    // Format NPV in thousands
    return `${formatNumberEU(value / 1000, 0)} tys. PLN`;
  }
  if (metric === 'payback_years' || unit === 'years') {
    // Format payback with 1 decimal
    return `${formatNumberEU(value, 1)} lat`;
  }
  if (unit === '%') {
    // Percentage
    return `${formatNumberEU(value, 1)}%`;
  }
  if (unit === 'kW') {
    return `${formatNumberEU(value, 0)} kW`;
  }
  // Default: value + unit
  return `${formatNumberEU(value, 2)} ${unit || ''}`.trim();
}

/**
 * Update topology selection
 */
function updateTopology(value) {
  console.log('🔌 Topology changed to:', value);
  advancedConfig.topology = value;

  // Update UI based on topology
  const pvSections = document.querySelectorAll('.pv-dependent');
  const bessSections = document.querySelectorAll('.bess-dependent');

  if (value === 'pv_only') {
    // PV only - hide BESS sections, show warning
    document.getElementById('configStatus').textContent = '⚠️ Tryb PV-only - BESS wyłączony';
    document.getElementById('configStatus').className = 'config-status warning';
  } else if (value === 'load_only') {
    // BESS only - adjust available modes
    document.getElementById('configStatus').textContent = 'ℹ️ Tryb BESS bez PV - peak shaving/arbitraż';
    document.getElementById('configStatus').className = 'config-status';
  } else {
    document.getElementById('configStatus').textContent = '';
  }

  // Store in localStorage for persistence
  localStorage.setItem('bessTopology', value);
}

/**
 * Update optimization objective
 */
function updateOptimizationObjective(value) {
  console.log('🎯 Objective changed to:', value);
  advancedConfig.objective = value;

  // Update info text
  const infoEl = document.getElementById('objectiveInfo');
  if (infoEl && objectiveDescriptions[value]) {
    infoEl.innerHTML = `<span class="info-icon">ℹ️</span><span>${objectiveDescriptions[value]}</span>`;
  }

  // Store in localStorage
  localStorage.setItem('bessObjective', value);
}

/**
 * Toggle constraint enabled/disabled
 */
function toggleConstraint(constraintType) {
  const checkboxMap = {
    'max_capex': 'constraintCapex',
    'max_payback': 'constraintPayback',
    'min_npv': 'constraintNpv',
    'max_efc': 'constraintEfc',
    'min_self_consumption': 'constraintSelfConsumption'
  };

  const checkboxId = checkboxMap[constraintType];
  if (!checkboxId) return;

  const checkbox = document.getElementById(checkboxId);
  const valueInput = document.getElementById(checkboxId + 'Value');
  const typeSelect = document.getElementById(checkboxId + 'Type');

  if (checkbox && valueInput && typeSelect) {
    const isChecked = checkbox.checked;
    valueInput.disabled = !isChecked;
    typeSelect.disabled = !isChecked;

    if (isChecked) {
      valueInput.focus();
    }
  }

  console.log(`Constraint ${constraintType} toggled:`, checkbox?.checked);
}

/**
 * v0.7.0: Update grid constraint configuration
 * @param {string} field - Field name (maxExportKw, maxImportKw, allowExport, unservedLoadPenaltyPlnKwh)
 * @param {any} value - Field value
 */
function updateGridConstraint(field, value) {
  if (!advancedConfig.gridConstraints) {
    advancedConfig.gridConstraints = {
      maxExportKw: null,
      maxImportKw: null,
      allowExport: true,
      unservedLoadPenaltyPlnKwh: 0
    };
  }

  // Parse value based on field type
  if (field === 'allowExport') {
    advancedConfig.gridConstraints.allowExport = Boolean(value);
  } else if (field === 'maxExportKw' || field === 'maxImportKw') {
    // Empty string or null means no limit
    const numValue = value === '' || value === null ? null : parseFloat(value);
    advancedConfig.gridConstraints[field] = numValue;
  } else if (field === 'unservedLoadPenaltyPlnKwh') {
    advancedConfig.gridConstraints.unservedLoadPenaltyPlnKwh = parseFloat(value) || 0;
  }

  console.log('Grid constraint updated:', field, '=', advancedConfig.gridConstraints[field]);

  // Store in localStorage for persistence
  localStorage.setItem('bessGridConstraints', JSON.stringify(advancedConfig.gridConstraints));
}

/**
 * v0.8.0: Update sizing constraint value
 * Sizing constraints are soft constraints that determine variant feasibility
 */
function updateSizingConstraint(field, value) {
  if (!advancedConfig.sizingConstraints) {
    advancedConfig.sizingConstraints = {
      maxCapexPln: null,
      maxPaybackYears: null,
      minNpvPln: null,
      minNetSavingsPln: null,
      requireNoUnservedLoad: false,
      maxUnservedLoadKwh: null
    };
  }

  // Parse value based on field type
  if (field === 'requireNoUnservedLoad') {
    advancedConfig.sizingConstraints.requireNoUnservedLoad = Boolean(value);
  } else {
    // Numeric fields - empty string means no limit (null)
    const numValue = value === '' || value === null || value === undefined ? null : parseFloat(value);
    advancedConfig.sizingConstraints[field] = numValue;
  }

  console.log('Sizing constraint updated:', field, '=', advancedConfig.sizingConstraints[field]);

  // Store in localStorage for persistence
  localStorage.setItem('bessSizingConstraints', JSON.stringify(advancedConfig.sizingConstraints));
}

// v3.15: toggleArbitrage() and updateArbitrageTariff() removed
// Arbitrage configuration is now in Settings module (USTAWIENIA > BESS Advanced Features)

/**
 * v3.15: Collect arbitrage configuration from systemSettings (Settings module)
 * Returns OSD tariff arbitrage config if enabled, or RDN arbitrage config, or null
 */
function collectArbitrageConfig() {
  const settings = window.systemSettings || systemSettings || {};

  // Check OSD Tariff Arbitrage first (higher priority - predictable zones)
  if (settings.bessOsdArbitrageEnabled) {
    // Build tariff_id from OSD operator and tariff group
    const operator = settings.bessOsdOperator || 'pge';
    const group = settings.bessOsdTariffGroup || 'C12a';
    const year = new Date().getFullYear();

    // Map operator to full name for tariff_id
    const operatorMap = {
      'pge': 'pge_dystrybucja',
      'tauron': 'tauron_dystrybucja',
      'energa': 'energa-operator',
      'enea': 'enea_operator',
      'innogy': 'stoen_operator'
    };

    const tariffId = `${operatorMap[operator] || operator}_${group.toLowerCase()}_${year}`;

    console.log('⚡ OSD Tariff Arbitrage enabled:', {
      operator, group, tariffId,
      peakRate: settings.bessOsdPeakRate,
      offPeakRate: settings.bessOsdOffPeakRate,
      minSpread: settings.bessOsdMinSpread
    });

    return {
      enabled: true,
      type: 'osd_tariff',
      tariff_id: tariffId,
      strategy: 'tou_zones',  // Time-of-Use zones strategy
      peak_rate_pln_kwh: settings.bessOsdPeakRate || 0.75,
      offpeak_rate_pln_kwh: settings.bessOsdOffPeakRate || 0.45,
      min_spread_pln_kwh: settings.bessOsdMinSpread || 0.15,
      // Default percentiles for zone-based strategy
      charge_below_percentile: 25,
      discharge_above_percentile: 75,
      arbitrage_soc_min: 0.20,
      start_date: `${year}-01-01`,
    };
  }

  // Check RDN Price Arbitrage (spot market)
  if (settings.bessPriceArbitrageEnabled) {
    const year = new Date().getFullYear();

    console.log('💹 RDN Price Arbitrage enabled:', {
      source: settings.bessPriceArbitrageSource,
      buyThreshold: settings.bessPriceArbitrageBuyThreshold,
      sellThreshold: settings.bessPriceArbitrageSellThreshold,
      spread: settings.bessPriceArbitrageSpread
    });

    return {
      enabled: true,
      type: 'rdn_spot',
      tariff_id: 'rdn_spot_' + year,
      strategy: 'percentile',  // Price percentile strategy
      price_source: settings.bessPriceArbitrageSource || 'manual',
      buy_threshold_pln_mwh: settings.bessPriceArbitrageBuyThreshold || 300,
      sell_threshold_pln_mwh: settings.bessPriceArbitrageSellThreshold || 600,
      min_spread_pln_mwh: settings.bessPriceArbitrageSpread || 100,
      flat_price_pln_mwh: settings.bessRdnPriceFlat || 500,
      price_multiplier: settings.bessRdnPriceMultiplier || 1.0,
      // Percentiles calculated from thresholds (approximation)
      charge_below_percentile: 25,
      discharge_above_percentile: 75,
      arbitrage_soc_min: 0.20,
      start_date: `${year}-01-01`,
    };
  }

  // No arbitrage enabled
  return null;
}

/**
 * Collect all active constraints from UI
 */
function collectConstraints() {
  const constraints = [];

  const constraintConfigs = [
    { id: 'constraintCapex', type: 'max_capex' },
    { id: 'constraintPayback', type: 'max_payback' },
    { id: 'constraintNpv', type: 'min_npv' },
    { id: 'constraintEfc', type: 'max_efc' },
    { id: 'constraintSelfConsumption', type: 'min_self_consumption' }
  ];

  for (const cfg of constraintConfigs) {
    const checkbox = document.getElementById(cfg.id);
    const valueInput = document.getElementById(cfg.id + 'Value');
    const typeSelect = document.getElementById(cfg.id + 'Type');

    if (checkbox?.checked && valueInput?.value) {
      constraints.push({
        constraint_type: cfg.type,
        value: parseFloat(valueInput.value),
        hard: typeSelect?.value === 'hard'
      });
    }
  }

  return constraints;
}

/**
 * Apply advanced configuration and re-run analysis
 */
async function applyAdvancedConfig() {
  console.log('✅ Applying advanced configuration...');

  const statusEl = document.getElementById('configStatus');
  const btnEl = document.getElementById('applyConfigBtn');

  if (statusEl) statusEl.textContent = 'Przetwarzanie...';
  if (btnEl) btnEl.disabled = true;

  try {
    // Collect current config
    advancedConfig.constraints = collectConstraints();

    console.log('📊 Advanced config:', advancedConfig);

    // Get current variant data - for load_only we can work without PV variant
    let variantData = variants[currentVariant];

    // For LOAD_ONLY topology, we don't require PV variant data
    if (!variantData && advancedConfig.topology === 'load_only') {
      // First try window.loadOnlyConsumptionData (set by showLoadOnlyMode)
      let consumptionData = window.loadOnlyConsumptionData;

      // Fallback: try to load consumption data from localStorage
      if (!consumptionData) {
        const consumptionDataStr = localStorage.getItem('consumptionData');
        if (consumptionDataStr) {
          try {
            consumptionData = JSON.parse(consumptionDataStr);
          } catch (e) {
            console.warn('Failed to parse consumptionData:', e);
          }
        }
      }

      if (consumptionData) {
        // Create a minimal variant-like object with just consumption data
        variantData = {
          consumption: consumptionData.totalConsumption || consumptionData.sum || 500000,
          production: 0, // No PV production in load_only mode
          hourlyLoad: consumptionData.hourlyData?.values || null
        };
        console.log('📊 LOAD_ONLY mode: Using consumption data:', variantData.consumption, 'kWh/year, hourly points:', variantData.hourlyLoad?.length || 0);
      }

      // If still no data, use defaults for demonstration
      if (!variantData) {
        variantData = {
          consumption: 500000, // Default 500 MWh/year
          production: 0,
          hourlyLoad: null
        };
        console.log('📊 LOAD_ONLY mode: Using default consumption (500 MWh/year)');
      }
    } else if (!variantData) {
      throw new Error('Brak danych dla bieżącego wariantu. Dla trybu LOAD_ONLY wybierz topologię "BESS + Load (bez PV)".');
    }

    // Handle different topologies
    if (advancedConfig.topology === 'pv_only') {
      // PV-only mode - no BESS analysis needed
      if (statusEl) {
        statusEl.textContent = '✅ Tryb PV-only aktywny';
        statusEl.className = 'config-status success';
      }
      // Hide BESS-specific sections
      hideBessSpecificSections();
      return;
    }

    // For pv_load and load_only, call the sizing/dispatch API
    const request = buildSizingRequest(variantData);

    if (!request) {
      throw new Error('Nie można zbudować żądania - brak danych');
    }

    // Call bess-dispatch service via nginx proxy
    const response = await fetch('/api/bess-dispatch/sizing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`API error: ${response.status} - ${err}`);
    }

    const result = await response.json();
    console.log('📊 Sizing result with new config:', result);

    // Update display with new results
    updateDisplayWithSizingResult(result);

    if (statusEl) {
      statusEl.textContent = '✅ Konfiguracja zastosowana';
      statusEl.className = 'config-status success';
    }

    // Auto-scroll to results summary panel
    setTimeout(() => {
      const summaryPanel = document.getElementById('configResultsSummary');
      if (summaryPanel && summaryPanel.style.display !== 'none') {
        summaryPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 100);

  } catch (error) {
    console.error('❌ Config apply error:', error);
    if (statusEl) {
      statusEl.textContent = '❌ Błąd: ' + error.message;
      statusEl.className = 'config-status error';
    }
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}

/**
 * Build sizing request with current config
 */
/**
 * Build price configuration for sizing request
 * Supports ToU pricing (Opcja B - OSD_ALL_IN) or legacy flat pricing
 *
 * @param {object} settings - System settings
 * @returns {object} - Price config for API
 */
function buildPriceConfig(settings) {
  // Check if OSD tariff arbitrage is enabled (this means ToU pricing is active)
  if (settings.bessOsdArbitrageEnabled) {
    const operator = settings.bessOsdOperator || 'pge';
    const group = settings.bessOsdTariffGroup || 'C12a';
    const year = new Date().getFullYear();

    // Map operator to tariff_id format
    const operatorMap = {
      'pge': 'pge',
      'tauron': 'tauron',
      'energa': 'energa',
      'enea': 'enea',
      'innogy': 'stoen'
    };

    const tariffId = `${operatorMap[operator] || operator}_${group.toLowerCase()}_${year}`;

    console.log('📊 ToU pricing enabled:', { tariffId, operator, group, year });

    return {
      tariff_id: tariffId,
      other_fees_pln_mwh: settings.totalFixedCharges || 451,  // Suma opłat stałych (OSD, OZE, kog, jakość, mocowa, akcyza)
      capacity_fee_method: settings.bessCapacityFeeMethod || 'dynamic',
      capacity_fee_som_pln_kwh: settings.bessCapacityFeeSom || 0.2194,
      analysis_year: year,
      // Keep legacy fields for compatibility
      import_price_pln_mwh: settings.energyPurchasePrice || 800,
      export_price_pln_mwh: 0
    };
  }

  // Check tariffConfig from settings module (new format)
  if (settings.tariffConfig && settings.tariffConfig.type !== 'flat') {
    const year = new Date().getFullYear();

    // Build tariff_id from tariffConfig
    const operator = settings.tariffConfig.osdOperator || 'pge';
    const group = settings.tariffConfig.type === 'two_zone' ? 'c12a' :
                  settings.tariffConfig.type === 'three_zone' ? 'c12b' : 'c11';

    const tariffId = `${operator}_${group}_${year}`;

    console.log('📊 ToU pricing from tariffConfig:', { tariffId, type: settings.tariffConfig.type });

    return {
      tariff_id: tariffId,
      other_fees_pln_mwh: settings.totalFixedCharges || 451,  // Suma opłat stałych
      capacity_fee_method: 'dynamic',
      capacity_fee_som_pln_kwh: 0.2194,
      analysis_year: year,
      import_price_pln_mwh: settings.energyPurchasePrice || 800,
      export_price_pln_mwh: 0
    };
  }

  // Legacy flat pricing
  console.log('📊 Flat pricing (no ToU)');
  return {
    import_price_pln_mwh: settings.energyPurchasePrice || 800,
    export_price_pln_mwh: 0
  };
}

function buildSizingRequest(variantData) {
  const settings = systemSettings || {};

  // Generate 8760 hourly profile from variant statistics (same as tryFetchSizingVariants)
  const hours = 8760;
  let pvData = [];
  let loadData = [];

  const totalProduction = variantData.production || 0; // For LOAD_ONLY, production is 0
  const totalLoad = variantData.consumption || variantData.load || 500000; // Default 500 MWh

  // Check if we have real hourly load data (from consumption module)
  if (variantData.hourlyLoad && Array.isArray(variantData.hourlyLoad) && variantData.hourlyLoad.length > 0) {
    const rawData = variantData.hourlyLoad;

    if (rawData.length >= 35040) {
      // 15-min data (35040 points/year) - aggregate to hourly by summing groups of 4
      // For power data: take average of 4 readings (average power over the hour)
      console.log('📊 buildSizingRequest - Converting 15-min data to hourly:', rawData.length, 'points');
      loadData = [];
      for (let h = 0; h < 8760; h++) {
        const startIdx = h * 4;
        const endIdx = Math.min(startIdx + 4, rawData.length);
        let sum = 0;
        let count = 0;
        for (let i = startIdx; i < endIdx; i++) {
          sum += rawData[i] || 0;
          count++;
        }
        // For 15-min power readings, hourly power = average power (kW)
        // Energy in kWh = average power * 1 hour
        loadData.push(count > 0 ? sum / count : 0);
      }
      console.log('📊 buildSizingRequest - Aggregated to hourly:', loadData.length, 'points, sum:', (loadData.reduce((a,b) => a+b, 0)/1000).toFixed(0), 'MWh');
    } else if (rawData.length >= 8760) {
      // Already hourly data (8760 points/year)
      loadData = rawData.slice(0, 8760);
      console.log('📊 buildSizingRequest - Using REAL hourly load data:', loadData.length, 'points, sum:', (loadData.reduce((a,b) => a+b, 0)/1000).toFixed(0), 'MWh');
    } else {
      // Less than 8760 points - extrapolate to full year
      console.log('📊 buildSizingRequest - Extrapolating partial data:', rawData.length, 'points');
      const multiplier = Math.ceil(8760 / rawData.length);
      const extendedData = [];
      for (let m = 0; m < multiplier && extendedData.length < 8760; m++) {
        for (let i = 0; i < rawData.length && extendedData.length < 8760; i++) {
          extendedData.push(rawData[i] || 0);
        }
      }
      loadData = extendedData.slice(0, 8760);
      console.log('📊 buildSizingRequest - Extrapolated to:', loadData.length, 'points');
    }
  } else {
    // Generate synthetic profile based on annual total
    const loadScaleFactor = totalLoad / 8760 / 50; // Base load ~50 kW avg

    console.log('📊 buildSizingRequest - Generating synthetic 8760h load profile:', { totalLoad, loadScaleFactor });

    for (let h = 0; h < hours; h++) {
      const hourOfDay = h % 24;

      // Load: industrial profile with evening peak (for peak shaving scenarios)
      let loadPower = 30 * loadScaleFactor;

      if (hourOfDay >= 6 && hourOfDay <= 22) {
        // Working hours - higher load
        loadPower = (60 + 20 * Math.sin((hourOfDay - 6) * Math.PI / 16)) * loadScaleFactor;
      }

      // Evening peak (17:00-21:00) - when PV is low but consumption high
      if (hourOfDay >= 17 && hourOfDay <= 21) {
        const peakHourFactor = 1 - Math.abs(hourOfDay - 19) / 3; // Peak at 19:00
        loadPower = (80 + 40 * peakHourFactor) * loadScaleFactor;
      }

      loadData.push(Math.max(10, loadPower));
    }
  }

  // For load_only topology, PV should be empty array
  if (advancedConfig.topology === 'load_only' || totalProduction === 0) {
    pvData = new Array(hours).fill(0);
    console.log('📊 LOAD_ONLY mode: PV array set to zeros');
  } else {
    // Generate PV profile for PV+BESS mode
    const pvScaleFactor = totalProduction / 1127000; // Base 1 MWp production ~1127 MWh

    for (let h = 0; h < hours; h++) {
      const hourOfDay = h % 24;
      const dayOfYear = Math.floor(h / 24);

      // PV: realistic profile with daytime production and seasonal variation
      let pvPower = 0;
      if (hourOfDay >= 6 && hourOfDay <= 18) {
        const solarFactor = Math.sin((hourOfDay - 6) * Math.PI / 12);
        // Seasonal: peak in June (day 172), min in December
        const seasonFactor = 0.3 + 0.7 * (0.5 + 0.5 * Math.cos((dayOfYear - 172) * 2 * Math.PI / 365));
        // Peak power for 1 MWp ~800-1000 kW
        pvPower = 900 * solarFactor * seasonFactor * pvScaleFactor;
      }
      pvData.push(Math.max(0, pvPower));
    }
  }

  console.log('📊 Final profiles - PV sum:', (pvData.reduce((a,b) => a+b, 0)/1000).toFixed(0), 'MWh, Load sum:', (loadData.reduce((a,b) => a+b, 0)/1000).toFixed(0), 'MWh');

  // For load_only topology, PV should be empty
  const effectivePv = advancedConfig.topology === 'load_only' ? [] : pvData;

  // Determine dispatch mode based on topology
  let mode = 'pv_surplus';
  if (advancedConfig.topology === 'load_only') {
    mode = 'load_only';
  } else if (settings.bessPeakShavingEnabled) {
    mode = 'stacked';
  }

  const request = {
    pv_generation_kw: effectivePv,
    load_kw: loadData,
    interval_minutes: 60,
    mode: mode,

    // Battery constraints
    min_power_kw: 10,
    max_power_kw: 1000,
    power_steps: 15,
    durations_h: [1.0, 2.0, 4.0],

    // Battery params
    roundtrip_efficiency: settings.bessRoundtripEfficiency || 0.9,
    soc_min: settings.bessSocMin || 0.1,
    soc_max: settings.bessSocMax || 0.9,

    // Economics
    capex_per_kwh: settings.bessCapexPerKwh || 1500,
    capex_per_kw: settings.bessCapexPerKw || 300,
    opex_pct_per_year: 0.015,
    discount_rate: 0.07,
    analysis_years: settings.bessLifetimeYears || 15,

    // Pricing - check if ToU tariff is configured
    prices: buildPriceConfig(settings),

    // Optimization config
    optimization: {
      objective: advancedConfig.objective,
      constraints: advancedConfig.constraints,
      constraint_penalty_weight: 0.3
    }
  };

  // Add peak limit for load_only or stacked
  if (mode === 'load_only' || mode === 'stacked') {
    request.peak_limit_kw = settings.bessPeakLimitKw || Math.max(...loadData) * 0.7;
  }

  // Add stacked params
  if (mode === 'stacked') {
    request.stacked_params = {
      peak_limit_kw: settings.bessPeakLimitKw || Math.max(...loadData) * 0.7,
      reserve_fraction: settings.bessReserveFraction || 0.3,
      allow_reserve_breach: false
    };
  }

  // v0.7.0 Grid Constraints
  const gc = advancedConfig.gridConstraints;
  if (gc) {
    const hasConstraints = (
      gc.maxExportKw !== null ||
      gc.maxImportKw !== null ||
      !gc.allowExport ||
      gc.unservedLoadPenaltyPlnKwh > 0
    );
    if (hasConstraints) {
      request.grid_constraints = {
        max_export_kw: gc.maxExportKw,
        max_import_kw: gc.maxImportKw,
        allow_export: gc.allowExport,
        unserved_load_penalty_pln_kwh: gc.unservedLoadPenaltyPlnKwh || 0
      };
      console.log('📊 Grid constraints:', request.grid_constraints);
    }
  }

  // v0.8.0 Sizing Constraints (soft constraints for variant feasibility)
  const sc = advancedConfig.sizingConstraints;
  if (sc) {
    const hasConstraints = (
      sc.maxCapexPln !== null ||
      sc.maxPaybackYears !== null ||
      sc.minNpvPln !== null ||
      sc.minNetSavingsPln !== null ||
      sc.requireNoUnservedLoad ||
      sc.maxUnservedLoadKwh !== null
    );
    if (hasConstraints) {
      request.constraints_config = {
        max_capex_pln: sc.maxCapexPln,
        max_payback_years: sc.maxPaybackYears,
        min_npv_pln: sc.minNpvPln,
        min_net_savings_pln: sc.minNetSavingsPln,
        require_no_unserved_load: sc.requireNoUnservedLoad,
        max_unserved_load_kwh: sc.maxUnservedLoadKwh
      };
      console.log('📊 Sizing constraints:', request.constraints_config);
    }
  }

  // v2.2.0: Request battery trace for dispatch trace display
  request.include_battery_trace = true;
  request.include_invariants = true;

  return request;
}

/**
 * Hide BESS-specific sections for PV-only mode
 */
function hideBessSpecificSections() {
  const sectionsToHide = [
    'bessContent',
    'sizingVariantsSection',
    'degradationBudgetSection',
    'sensitivitySection',
    'advancedConfigSection'
  ];

  // Actually just show a message instead of hiding everything
  const banner = document.getElementById('bessDisabledBanner');
  if (banner) {
    banner.style.display = 'flex';
    banner.querySelector('h3').textContent = 'Tryb tylko PV';
    banner.querySelector('p').textContent = 'BESS nie jest analizowany w trybie PV-only. Przełącz topologię aby włączyć analizę BESS.';
  }

  const content = document.getElementById('bessContent');
  if (content) content.style.display = 'none';
}

/**
 * Update display with sizing result from API
 */
function updateDisplayWithSizingResult(result) {
  // This function updates the UI with results from the /sizing endpoint
  // when using multi-objective optimization

  if (!result || !result.variants) return;

  // Show sizing variants section
  const section = document.getElementById('sizingVariantsSection');
  if (section) section.style.display = 'block';

  // Display sizing variants
  displaySizingVariants(result);

  // Update recommended variant info
  if (result.recommended_variant) {
    console.log('📊 Recommended variant:', result.recommended_variant);
  }

  // Find and display warning about constraints
  if (result.warnings && result.warnings.length > 0) {
    console.warn('⚠️ Sizing warnings:', result.warnings);
  }

  // Update quick results summary panel
  updateConfigResultsSummary(result);

  // v2.2.0: Update dispatch trace display
  const recommended = result.variants?.find(v => v.is_recommended) || result.variants?.[0];
  if (recommended) {
    const batteryTrace = recommended.battery_trace || null;
    const cycleSummary = recommended.cycle_summary || recommended.dispatch_summary?.cycle_summary || null;
    const invariants = recommended.invariants || recommended.dispatch_summary?.invariants || null;
    updateDispatchTraceDisplay(batteryTrace, cycleSummary, invariants);
  }
}

/**
 * Update the quick results summary panel below advanced config
 */
function updateConfigResultsSummary(result) {
  const summaryPanel = document.getElementById('configResultsSummary');
  if (!summaryPanel) return;

  // Find recommended variant
  const recommended = result.variants?.find(v => v.is_recommended) || result.variants?.[0];

  if (!recommended) {
    summaryPanel.style.display = 'none';
    return;
  }

  // Show panel
  summaryPanel.style.display = 'block';

  // Update values
  const variantLabels = {
    'small': 'Small (1h)',
    'medium': 'Medium (2h)',
    'large': 'Large (4h)'
  };

  setElementText('summaryRecommended', variantLabels[result.recommended_variant] || result.recommended_variant || '-');

  // v3.19: Display structured reason for recommendation
  const reasonText = formatRecommendedReason(result);
  setElementText('summaryReason', reasonText);

  setElementText('summaryPowerEnergy', `${formatNumberEU(recommended.power_kw, 0)} kW / ${formatNumberEU(recommended.energy_kwh, 0)} kWh`);

  // NPV with color
  const npvEl = document.getElementById('summaryNpv');
  if (npvEl) {
    npvEl.textContent = `${formatNumberEU(recommended.npv_pln / 1000, 0)} tys. PLN`;
    npvEl.className = 'summary-value ' + (recommended.npv_pln >= 0 ? 'positive' : 'negative');
  }

  setElementText('summaryPayback', recommended.simple_payback_years < 100 ? `${formatNumberEU(recommended.simple_payback_years, 1)} lat` : '> 25 lat');
  setElementText('summaryCapex', `${formatNumberEU(recommended.capex_pln / 1000, 0)} tys. PLN`);
  setElementText('summaryEfc', `${formatNumberEU(recommended.degradation?.efc_total || 0, 0)} cykli`);

  // Handle constraint warnings (v0.7.0: includes grid constraint summary)
  const warningsPanel = document.getElementById('constraintWarnings');
  const warningsList = document.getElementById('warningsList');

  // Collect all warnings
  let allWarnings = [];

  // 1. Backend warnings (budget constraints, degradation limits)
  if (result.warnings && result.warnings.length > 0) {
    allWarnings = allWarnings.concat(result.warnings.map(w => {
      const isHard = w.includes('[TWARDE]');
      const isSoft = w.includes('[MIĘKKIE]');
      let className = '';
      let icon = 'X';
      if (isHard) {
        className = 'hard';
        icon = 'X';
      } else if (isSoft) {
        className = 'soft';
        icon = '!';
      }
      const cleanMsg = w.replace('[TWARDE]', '').replace('[MIĘKKIE]', '').trim();
      return { className, icon, msg: cleanMsg };
    }));
  }

  // 2. Grid constraint summary warnings (v0.7.0)
  const cs = recommended.dispatch_summary?.constraint_summary;
  if (cs) {
    // Export cap hit
    if (cs.export_cap_hit_steps > 0) {
      const curtailedKwh = cs.export_cap_curtailed_kwh || 0;
      allWarnings.push({
        className: 'info',
        icon: 'i',
        msg: `Limit eksportu aktywny przez ${cs.export_cap_hit_steps} krokow (ograniczono ${formatNumberEU(curtailedKwh, 1)} kWh)`
      });
    }
    // Import cap hit
    if (cs.import_cap_hit_steps > 0) {
      allWarnings.push({
        className: 'info',
        icon: 'i',
        msg: `Limit importu aktywny przez ${cs.import_cap_hit_steps} krokow`
      });
    }
    // Unserved load
    if (cs.unserved_load_kwh > 0) {
      allWarnings.push({
        className: 'hard',
        icon: 'X',
        msg: `Nieobsluzony pobor: ${formatNumberEU(cs.unserved_load_kwh, 1)} kWh (kara: ${formatNumberEU(recommended.savings_breakdown?.unserved_load_penalty_pln || 0, 0)} PLN)`
      });
    }
  }

  // Display warnings
  if (allWarnings.length > 0) {
    warningsPanel.style.display = 'block';
    warningsList.innerHTML = allWarnings.map(w =>
      `<li class="${w.className}"><span class="warning-icon">${w.icon}</span> <span class="warning-detail">${w.msg}</span></li>`
    ).join('');
  } else {
    warningsPanel.style.display = 'none';
  }

  // v3.19: Populate top 3 variants comparison table
  updateTopVariantsCompareTable(result);

  // v0.8.0: Populate Pareto Frontier table
  updateParetoFrontierTable(result);

  console.log('📊 Results summary updated:', {
    variant: result.recommended_variant,
    npv: recommended.npv_pln,
    payback: recommended.simple_payback_years,
    warnings: result.warnings?.length || 0
  });
}

/**
 * v3.19: Update top 3 variants comparison table
 * Uses top_variants_details from API (v0.4.1+) for consistent data
 * @param {object} result - Sizing result from bess-dispatch API
 */
function updateTopVariantsCompareTable(result) {
  const comparePanel = document.getElementById('topVariantsCompare');
  const tableBody = document.getElementById('topVariantsTableBody');

  if (!comparePanel || !tableBody) return;

  // Use top_variants_details if available (v0.4.1+)
  const details = result.top_variants_details;

  if (!details || details.length === 0) {
    comparePanel.style.display = 'none';
    return;
  }

  // Show panel
  comparePanel.style.display = 'block';

  // Variant labels
  const variantLabels = {
    'small': 'Small (1h)',
    'medium': 'Medium (2h)',
    'large': 'Large (4h)'
  };

  // Build table rows
  const rows = details.map((detail, index) => {
    const isRecommended = index === 0;
    const rowClass = isRecommended ? 'recommended-row' : '';
    const badge = isRecommended ? '<span class="rec-badge">★</span>' : '';

    const label = variantLabels[detail.variant] || detail.variant;
    const npvFormatted = `${formatNumberEU(detail.npv_pln / 1000, 0)} tys.`;
    const npvClass = detail.npv_pln >= 0 ? 'positive' : 'negative';
    const paybackFormatted = detail.payback_years < 100 ? `${formatNumberEU(detail.payback_years, 1)} lat` : '> 25 lat';
    const savingsFormatted = `${formatNumberEU(detail.net_savings_pln / 1000, 0)} tys.`;
    const scoreFormatted = formatNumberEU(detail.score / 1000, 0);

    return `
      <tr class="${rowClass}">
        <td>${badge}${label}</td>
        <td class="${npvClass}">${npvFormatted}</td>
        <td>${paybackFormatted}</td>
        <td>${savingsFormatted}</td>
        <td>${scoreFormatted}</td>
      </tr>
    `;
  }).join('');

  tableBody.innerHTML = rows;

  console.log('📊 Top variants table updated:', details.length, 'variants');
}

/**
 * v0.8.0: Update Pareto Frontier table
 * Uses pareto_frontier from API (v0.8.0+) to show dominance analysis
 * @param {object} result - Sizing result from bess-dispatch API
 */
function updateParetoFrontierTable(result) {
  const paretoPanel = document.getElementById('paretoFrontierCompare');
  const tableBody = document.getElementById('paretoFrontierTableBody');

  if (!paretoPanel || !tableBody) return;

  // Use pareto_frontier if available (v0.8.0+)
  const pareto = result.pareto_frontier;

  if (!pareto || pareto.length === 0) {
    paretoPanel.style.display = 'none';
    return;
  }

  // Show panel
  paretoPanel.style.display = 'block';

  // Variant labels
  const variantLabels = {
    'small': 'Small (1h)',
    'medium': 'Medium (2h)',
    'large': 'Large (4h)'
  };

  // Build table rows
  const rows = pareto.map(point => {
    const isOnFrontier = !point.is_dominated;
    const rowClass = isOnFrontier ? 'pareto-row' : 'dominated-row';
    const statusBadge = isOnFrontier
      ? '<span class="pareto-badge">Pareto</span>'
      : '<span class="dominated-badge">Dominated</span>';

    const label = variantLabels[point.variant] || point.variant;
    const npvFormatted = `${formatNumberEU(point.npv_pln / 1000, 0)} tys.`;
    const npvClass = point.npv_pln >= 0 ? 'positive' : 'negative';
    const paybackFormatted = point.payback_years < 100 ? `${formatNumberEU(point.payback_years, 1)} lat` : '> 25 lat';

    return `
      <tr class="${rowClass}">
        <td>${label}</td>
        <td class="${npvClass}">${npvFormatted}</td>
        <td>${paybackFormatted}</td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join('');

  tableBody.innerHTML = rows;

  const frontierCount = pareto.filter(p => !p.is_dominated).length;
  console.log('📈 Pareto frontier table updated:', pareto.length, 'points,', frontierCount, 'on frontier');
}

/**
 * Reset advanced configuration to defaults
 */
function resetAdvancedConfig() {
  console.log('🔄 Resetting advanced configuration...');

  // Reset config object
  advancedConfig = {
    topology: 'pv_load',
    objective: 'npv',
    constraints: []
  };

  // Reset UI elements
  document.querySelector('input[name="topology"][value="pv_load"]').checked = true;
  document.getElementById('optimizationObjective').value = 'npv';
  document.getElementById('objectiveInfo').innerHTML =
    '<span class="info-icon">ℹ️</span><span>NPV uwzględnia wartość pieniądza w czasie i pełne koszty inwestycji</span>';

  // Reset all constraints
  const constraintCheckboxes = [
    'constraintCapex', 'constraintPayback', 'constraintNpv',
    'constraintEfc', 'constraintSelfConsumption'
  ];

  for (const id of constraintCheckboxes) {
    const checkbox = document.getElementById(id);
    const valueInput = document.getElementById(id + 'Value');
    const typeSelect = document.getElementById(id + 'Type');

    if (checkbox) checkbox.checked = false;
    if (valueInput) {
      valueInput.value = '';
      valueInput.disabled = true;
    }
    if (typeSelect) {
      typeSelect.value = 'hard';
      typeSelect.disabled = true;
    }
  }

  // Clear localStorage
  localStorage.removeItem('bessTopology');
  localStorage.removeItem('bessObjective');

  // Update status
  const statusEl = document.getElementById('configStatus');
  if (statusEl) {
    statusEl.textContent = '🔄 Zresetowano do ustawień domyślnych';
    statusEl.className = 'config-status';
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  }
}

/**
 * Load saved configuration from localStorage
 */
function loadSavedConfig() {
  const savedTopology = localStorage.getItem('bessTopology');
  const savedObjective = localStorage.getItem('bessObjective');
  const savedGridConstraints = localStorage.getItem('bessGridConstraints');
  const savedSizingConstraints = localStorage.getItem('bessSizingConstraints');

  if (savedTopology) {
    advancedConfig.topology = savedTopology;
    const radioBtn = document.querySelector(`input[name="topology"][value="${savedTopology}"]`);
    if (radioBtn) radioBtn.checked = true;
  }

  if (savedObjective) {
    advancedConfig.objective = savedObjective;
    const selectEl = document.getElementById('optimizationObjective');
    if (selectEl) selectEl.value = savedObjective;
    updateOptimizationObjective(savedObjective);
  }

  // v0.7.0: Restore grid constraints
  if (savedGridConstraints) {
    try {
      const gc = JSON.parse(savedGridConstraints);
      advancedConfig.gridConstraints = gc;

      // Update UI inputs
      const maxExportEl = document.getElementById('maxExportKw');
      const maxImportEl = document.getElementById('maxImportKw');
      const allowExportEl = document.getElementById('allowExport');
      const penaltyEl = document.getElementById('unservedLoadPenalty');

      if (maxExportEl && gc.maxExportKw !== null) maxExportEl.value = gc.maxExportKw;
      if (maxImportEl && gc.maxImportKw !== null) maxImportEl.value = gc.maxImportKw;
      if (allowExportEl) allowExportEl.checked = gc.allowExport !== false;
      if (penaltyEl && gc.unservedLoadPenaltyPlnKwh) penaltyEl.value = gc.unservedLoadPenaltyPlnKwh;
    } catch (e) {
      console.warn('Failed to parse saved grid constraints:', e);
    }
  }

  // v0.8.0: Restore sizing constraints
  if (savedSizingConstraints) {
    try {
      const sc = JSON.parse(savedSizingConstraints);
      advancedConfig.sizingConstraints = sc;

      // Update UI inputs
      const maxCapexEl = document.getElementById('maxCapexPln');
      const maxPaybackEl = document.getElementById('maxPaybackYears');
      const minNpvEl = document.getElementById('minNpvPln');
      const minSavingsEl = document.getElementById('minNetSavingsPln');
      const requireNoUnservedEl = document.getElementById('requireNoUnservedLoad');
      const maxUnservedEl = document.getElementById('maxUnservedLoadKwh');

      if (maxCapexEl && sc.maxCapexPln !== null) maxCapexEl.value = sc.maxCapexPln;
      if (maxPaybackEl && sc.maxPaybackYears !== null) maxPaybackEl.value = sc.maxPaybackYears;
      if (minNpvEl && sc.minNpvPln !== null) minNpvEl.value = sc.minNpvPln;
      if (minSavingsEl && sc.minNetSavingsPln !== null) minSavingsEl.value = sc.minNetSavingsPln;
      if (requireNoUnservedEl) requireNoUnservedEl.checked = sc.requireNoUnservedLoad === true;
      if (maxUnservedEl && sc.maxUnservedLoadKwh !== null) maxUnservedEl.value = sc.maxUnservedLoadKwh;
    } catch (e) {
      console.warn('Failed to parse saved sizing constraints:', e);
    }
  }
}

// Initialize advanced config on load
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(loadSavedConfig, 100);
});

// Export advanced config functions
window.updateTopology = updateTopology;
window.updateOptimizationObjective = updateOptimizationObjective;
window.toggleConstraint = toggleConstraint;
window.updateGridConstraint = updateGridConstraint;  // v0.7.0
window.updateSizingConstraint = updateSizingConstraint;  // v0.8.0
window.applyAdvancedConfig = applyAdvancedConfig;
window.resetAdvancedConfig = resetAdvancedConfig;
window.advancedConfig = advancedConfig;

// ============================================================================
// ToU COST ANALYSIS (FE-only) - MVP v3.17 (PR3)
// ============================================================================

/**
 * Fetch OSD tariff presets from backend
 * @returns {Promise<Array>} - List of available tariff presets
 */
async function fetchTariffPresets() {
  try {
    const response = await fetch('/api/bess-dispatch/osd-tariffs/presets');
    if (!response.ok) {
      console.warn('Failed to fetch tariff presets:', response.status);
      return getHardcodedTariffPresets(); // Fallback
    }
    return await response.json();
  } catch (e) {
    console.warn('Error fetching tariff presets:', e);
    return getHardcodedTariffPresets();
  }
}

/**
 * Hardcoded tariff presets (fallback if API unavailable)
 */
function getHardcodedTariffPresets() {
  return [
    { id: 'pge_c11_2025', name: 'PGE C11 2025', group: 'C11', zones: ['flat'], osd: 'PGE' },
    { id: 'pge_c12a_2025', name: 'PGE C12a 2025', group: 'C12a', zones: ['peak', 'offpeak'], osd: 'PGE' },
    { id: 'pge_c12b_2025', name: 'PGE C12b 2025', group: 'C12b', zones: ['peak', 'day', 'night'], osd: 'PGE' },
    { id: 'tauron_c12a_2025', name: 'TAURON C12a 2025', group: 'C12a', zones: ['peak', 'offpeak'], osd: 'TAURON' },
    { id: 'energa_c12a_2025', name: 'ENERGA C12a 2025', group: 'C12a', zones: ['peak', 'offpeak'], osd: 'ENERGA' },
  ];
}

/**
 * Calculate ToU costs for a dispatch result (FE-only analysis)
 * Uses tariff rates from settings and hourly grid import from dispatch result
 *
 * @param {object} dispatchResult - Dispatch result with hourly_grid_import_kw
 * @param {object} settings - System settings with tariffConfig
 * @returns {object} - Cost analysis by zone
 */
function calculateToUCosts(dispatchResult, settings) {
  const tariffConfig = settings?.tariffConfig || {};
  const tariffType = tariffConfig.type || 'two_zone';
  const intervalHours = (dispatchResult.interval_minutes || 60) / 60;

  // Get hourly import data - may be from dispatch result or baseline
  const hourlyImportKw = dispatchResult.hourly_grid_import_kw || [];
  if (hourlyImportKw.length === 0) {
    console.warn('No hourly import data for ToU cost calculation');
    return null;
  }

  // Initialize cost accumulators
  let totalCost = 0;
  const costByZone = {};
  const energyByZone = {};

  // Get rates based on tariff type
  let rates = {};
  if (tariffType === 'flat') {
    rates = { flat: tariffConfig.flatRate || 750 };
  } else if (tariffType === 'two_zone') {
    rates = {
      day: tariffConfig.twoZone?.dayRate || 850,
      night: tariffConfig.twoZone?.nightRate || 450
    };
  } else if (tariffType === 'three_zone') {
    rates = {
      peak: tariffConfig.threeZone?.peakRate || 950,
      partial: tariffConfig.threeZone?.partialRate || 700,
      offpeak: tariffConfig.threeZone?.offPeakRate || 400
    };
  }

  // Initialize zone accumulators
  Object.keys(rates).forEach(zone => {
    costByZone[zone] = 0;
    energyByZone[zone] = 0;
  });

  // Calculate costs per hour
  hourlyImportKw.forEach((importKw, hourIndex) => {
    const hour = hourIndex % 24;
    const dayOfYear = Math.floor(hourIndex / 24);
    const dayOfWeek = (dayOfYear + 1) % 7; // Assume year starts on Monday
    const isWeekend = dayOfWeek === 5 || dayOfWeek === 6; // Sat/Sun

    const energyKwh = importKw * intervalHours;
    const zone = getZoneForHour(hour, isWeekend, tariffType, tariffConfig);
    const rate = rates[zone] || rates.flat || 750;

    const cost = energyKwh * rate / 1000; // PLN/MWh -> PLN/kWh
    totalCost += cost;
    costByZone[zone] = (costByZone[zone] || 0) + cost;
    energyByZone[zone] = (energyByZone[zone] || 0) + energyKwh;
  });

  return {
    totalCost,
    costByZone,
    energyByZone,
    tariffType,
    tariffName: tariffConfig.name || 'Custom',
    rates
  };
}

/**
 * Get zone for a given hour based on tariff configuration
 */
function getZoneForHour(hour, isWeekend, tariffType, config) {
  if (tariffType === 'flat') {
    return 'flat';
  }

  if (tariffType === 'two_zone') {
    const twoZone = config.twoZone || {};
    if (isWeekend) {
      const start = twoZone.weekend?.start || 6;
      const end = twoZone.weekend?.end || 13;
      return (hour >= start && hour < end) ? 'day' : 'night';
    } else {
      const start = twoZone.weekday?.start || 6;
      const end = twoZone.weekday?.end || 22;
      return (hour >= start && hour < end) ? 'day' : 'night';
    }
  }

  if (tariffType === 'three_zone') {
    const threeZone = config.threeZone || {};
    // Night zone (22:00-6:00)
    if (hour >= 22 || hour < 6) return 'offpeak';
    if (isWeekend) return 'offpeak';

    // Check peak periods
    const peak1 = threeZone.peak1 || { start: 7, end: 13 };
    const peak2 = threeZone.peak2 || { start: 17, end: 21 };

    if ((hour >= peak1.start && hour < peak1.end) ||
        (hour >= peak2.start && hour < peak2.end)) {
      return 'peak';
    }

    // Partial period (between peaks)
    return 'partial';
  }

  return 'flat';
}

/**
 * Display ToU cost analysis in UI
 * @param {object} costAnalysis - Result from calculateToUCosts
 * @param {object} baselineCostAnalysis - Baseline (without BESS) for comparison
 */
function displayToUCostAnalysis(costAnalysis, baselineCostAnalysis) {
  const container = document.getElementById('touCostAnalysis');
  if (!container) {
    console.warn('ToU cost analysis container not found');
    return;
  }

  if (!costAnalysis) {
    container.innerHTML = '<div class="info-box">Brak danych do analizy kosztów ToU</div>';
    return;
  }

  const savings = baselineCostAnalysis ?
    (baselineCostAnalysis.totalCost - costAnalysis.totalCost) : 0;
  const savingsPct = baselineCostAnalysis && baselineCostAnalysis.totalCost > 0 ?
    (savings / baselineCostAnalysis.totalCost * 100) : 0;

  let html = `
    <div class="tou-analysis-card">
      <div class="tou-header">
        <span class="tou-title">📊 Analiza kosztów wg taryfy ${costAnalysis.tariffName}</span>
        <span class="tou-type">${costAnalysis.tariffType.replace('_', ' ')}</span>
      </div>

      <div class="tou-summary">
        <div class="tou-metric">
          <div class="tou-value">${formatNumberEU(costAnalysis.totalCost, 0)}</div>
          <div class="tou-label">Koszt roczny [PLN]</div>
        </div>
        ${baselineCostAnalysis ? `
        <div class="tou-metric savings">
          <div class="tou-value">${formatNumberEU(savings, 0)}</div>
          <div class="tou-label">Oszczędność z BESS [PLN]</div>
          <div class="tou-pct">${savingsPct.toFixed(1)}%</div>
        </div>
        ` : ''}
      </div>

      <div class="tou-breakdown">
        <table class="tou-table">
          <thead>
            <tr>
              <th>Strefa</th>
              <th>Stawka [PLN/MWh]</th>
              <th>Energia [MWh]</th>
              <th>Koszt [PLN]</th>
            </tr>
          </thead>
          <tbody>
  `;

  Object.entries(costAnalysis.costByZone).forEach(([zone, cost]) => {
    const rate = costAnalysis.rates[zone] || 0;
    const energy = costAnalysis.energyByZone[zone] || 0;
    const zoneLabel = getZoneLabel(zone);

    html += `
      <tr>
        <td><span class="zone-badge zone-${zone}">${zoneLabel}</span></td>
        <td>${formatNumberEU(rate, 0)}</td>
        <td>${formatNumberEU(energy / 1000, 1)}</td>
        <td>${formatNumberEU(cost, 0)}</td>
      </tr>
    `;
  });

  html += `
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.innerHTML = html;
  container.style.display = 'block';
}

function getZoneLabel(zone) {
  const labels = {
    flat: 'Jednolita',
    day: 'Dzień (szczyt)',
    night: 'Noc (pozaszczyt)',
    peak: 'Szczyt',
    partial: 'Dzień (częściowy)',
    offpeak: 'Noc'
  };
  return labels[zone] || zone;
}

// ============================================================================
// CAPACITY FEE OVERLAY (PR4) - MVP v3.17
// ============================================================================

/**
 * Fetch capacity fee savings from backend
 *
 * @param {Array} gridImportKwhBefore - Baseline grid import (without BESS)
 * @param {Array} gridImportKwhAfter - Grid import with BESS
 * @param {object} settings - System settings
 * @returns {Promise<object>} - Capacity fee savings analysis
 */
async function fetchCapacityFeeSavings(gridImportKwhBefore, gridImportKwhAfter, settings) {
  const year = settings?.capacityFeeConfig?.year || 2026;
  const intervalMinutes = 60; // Default hourly

  const request = {
    grid_import_kwh_before: gridImportKwhBefore,
    grid_import_kwh_after: gridImportKwhAfter,
    interval_minutes: intervalMinutes,
    year: year,
    start_date: `${year}-01-01`,
    som_rate_pln_kwh: settings?.capacityFeeConfig?.somRate || 0.2194
  };

  try {
    const response = await fetch('/api/bess-dispatch/capacity-fee/savings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      console.warn('Capacity fee savings API failed:', response.status);
      return null;
    }

    return await response.json();
  } catch (e) {
    console.warn('Error fetching capacity fee savings:', e);
    return null;
  }
}

/**
 * Calculate baseline grid import from load and PV profiles
 * Baseline = max(0, load - pv) for pv_bess topology
 * Baseline = load for bess_only topology
 *
 * @param {object} variant - Current variant data
 * @param {string} topology - 'pv_bess' | 'bess_only'
 * @returns {Array} - Hourly baseline grid import [kWh]
 */
function calculateBaselineGridImport(variant, topology) {
  // Try to get hourly data from variant or localStorage
  const hourlyLoad = variant.hourly_load_kw ||
                     JSON.parse(localStorage.getItem('hourlyConsumption') || '[]');
  const hourlyPv = variant.hourly_pv_kw ||
                   JSON.parse(localStorage.getItem('hourlyPvProduction') || '[]');

  if (hourlyLoad.length === 0) {
    console.warn('No hourly load data for baseline calculation');
    return [];
  }

  const intervalHours = 1; // Assuming hourly data

  if (topology === 'bess_only') {
    // BESS-only: baseline = full load
    return hourlyLoad.map(kw => kw * intervalHours);
  }

  // PV+BESS: baseline = max(0, load - pv)
  return hourlyLoad.map((loadKw, i) => {
    const pvKw = hourlyPv[i] || 0;
    return Math.max(0, loadKw - pvKw) * intervalHours;
  });
}

/**
 * Display capacity fee savings overlay
 * @param {object} savings - Savings data from API
 */
function displayCapacityFeeOverlay(savings) {
  const container = document.getElementById('capacityFeeOverlay');
  if (!container) {
    console.warn('Capacity fee overlay container not found');
    return;
  }

  if (!savings) {
    container.style.display = 'none';
    return;
  }

  const feeBefore = savings.fee_before_pln || 0;
  const feeAfter = savings.fee_after_pln || 0;
  const savingsAmount = savings.savings_pln || (feeBefore - feeAfter);
  const savingsPct = feeBefore > 0 ? (savingsAmount / feeBefore * 100) : 0;
  const kClassBefore = savings.k_class_before || 'K4';
  const kClassAfter = savings.k_class_after || 'K4';

  const html = `
    <div class="capacity-fee-overlay-card">
      <div class="overlay-header">
        <span class="overlay-title">⚡ Oszczędności Opłaty Mocowej</span>
        <button class="overlay-close" onclick="hideCapacityFeeOverlay()">×</button>
      </div>

      <div class="overlay-comparison">
        <div class="comparison-item before">
          <div class="comparison-label">Bez BESS</div>
          <div class="comparison-value">${formatNumberEU(feeBefore, 0)} PLN</div>
          <div class="comparison-kclass">Klasa ${kClassBefore}</div>
        </div>
        <div class="comparison-arrow">→</div>
        <div class="comparison-item after">
          <div class="comparison-label">Z BESS</div>
          <div class="comparison-value">${formatNumberEU(feeAfter, 0)} PLN</div>
          <div class="comparison-kclass">Klasa ${kClassAfter}</div>
        </div>
      </div>

      <div class="overlay-savings">
        <div class="savings-amount">${formatNumberEU(savingsAmount, 0)} PLN</div>
        <div class="savings-label">Roczna oszczędność (${savingsPct.toFixed(1)}%)</div>
      </div>

      ${savings.peak_power_before_kw ? `
      <div class="overlay-details">
        <div class="detail-row">
          <span>Moc szczytowa przed:</span>
          <span>${formatNumberEU(savings.peak_power_before_kw, 1)} kW</span>
        </div>
        <div class="detail-row">
          <span>Moc szczytowa po:</span>
          <span>${formatNumberEU(savings.peak_power_after_kw, 1)} kW</span>
        </div>
        <div class="detail-row">
          <span>Redukcja:</span>
          <span>${formatNumberEU(savings.peak_reduction_pct || 0, 1)}%</span>
        </div>
      </div>
      ` : ''}
    </div>
  `;

  container.innerHTML = html;
  container.style.display = 'block';
}

function hideCapacityFeeOverlay() {
  const container = document.getElementById('capacityFeeOverlay');
  if (container) container.style.display = 'none';
}

/**
 * Run capacity fee analysis if enabled in settings
 * @param {object} variant - Current variant data
 */
async function runCapacityFeeAnalysisIfEnabled(variant) {
  const settings = systemSettings || {};
  if (!settings.bessCapacityFeeOverlay) {
    hideCapacityFeeOverlay();
    return;
  }

  console.log('📊 Running capacity fee analysis...');

  const topology = settings.bessTopology || 'pv_bess';

  // Calculate baseline (without BESS)
  const baselineImportKwh = calculateBaselineGridImport(variant, topology);
  if (baselineImportKwh.length === 0) {
    console.warn('Cannot calculate baseline - no load data');
    return;
  }

  // Get "after BESS" import from dispatch result
  // Convert kW to kWh (assuming 1h intervals)
  const afterImportKwh = variant.hourly_grid_import_kw?.map(kw => kw * 1) || [];

  if (afterImportKwh.length === 0) {
    // Fallback: estimate from annual values
    const annualImportBefore = baselineImportKwh.reduce((a, b) => a + b, 0);
    const annualImportAfter = variant.bess_grid_import_kwh || annualImportBefore * 0.85;
    console.log('Using estimated annual values for capacity fee analysis');

    // Show simplified overlay
    displayCapacityFeeOverlay({
      fee_before_pln: annualImportBefore * 0.00022 * 1000, // Rough estimate
      fee_after_pln: annualImportAfter * 0.00022 * 1000,
      savings_pln: (annualImportBefore - annualImportAfter) * 0.00022 * 1000
    });
    return;
  }

  // Fetch savings from API
  const savings = await fetchCapacityFeeSavings(baselineImportKwh, afterImportKwh, settings);
  displayCapacityFeeOverlay(savings);
}

// ============================================
// v0.5.0: FINANCE SECTION - Cashflow + Sensitivity
// ============================================

/**
 * Display finance section with cashflow table, IRR, and sensitivity charts
 * v0.6.0: Added IRR, energy price sensitivity, CAPEX sensitivity
 * @param {object} result - Sizing result from bess-dispatch API
 */
function displayFinanceSection(result) {
  const section = document.getElementById('financeSection');
  if (!section) {
    console.log('[BESS] Finance section element not found');
    return;
  }

  // Find recommended variant
  const recommended = result.variants?.find(v => v.is_recommended) || result.variants?.[0];
  if (!recommended || !recommended.finance_summary) {
    section.style.display = 'none';
    return;
  }

  const fs = recommended.finance_summary;
  section.style.display = 'block';

  // v0.6.0: Display IRR
  displayIRR(fs);

  // Display cashflow table
  displayCashflowTable(fs);

  // Display discount rate sensitivity chart
  displayDiscountRateSensitivity(fs);

  // v0.6.0: Display energy price sensitivity
  displayEnergyPriceSensitivity(fs);

  // v0.6.0: Display CAPEX sensitivity
  displayCapexSensitivity(fs);

  console.log('[BESS] Finance section updated (v0.6.0 with IRR + sweeps)');
}

/**
 * Display IRR (Internal Rate of Return) from finance_summary
 * v0.6.0 PR1
 */
function displayIRR(financeSummary) {
  const irrValueEl = document.getElementById('irrValue');
  if (!irrValueEl) return;

  const irr = financeSummary.irr_pct;
  if (irr === null || irr === undefined) {
    irrValueEl.textContent = 'N/A';
    irrValueEl.className = 'irr-value na';
  } else {
    irrValueEl.textContent = formatNumberEU(irr, 1) + '%';
    irrValueEl.className = irr >= financeSummary.discount_rate * 100 ? 'irr-value positive' : 'irr-value negative';
  }
}

/**
 * Display cashflow table from finance_summary.cashflow_timeseries
 */
function displayCashflowTable(financeSummary) {
  const tableBody = document.getElementById('cashflowTableBody');
  if (!tableBody) return;

  const cashflow = financeSummary.cashflow_timeseries;
  if (!cashflow || cashflow.length === 0) {
    document.getElementById('cashflowSection').style.display = 'none';
    return;
  }

  document.getElementById('cashflowSection').style.display = 'block';

  // Build table rows
  const rows = cashflow.map(cf => {
    const isYearZero = cf.year === 0;
    const netClass = cf.net_cashflow_pln >= 0 ? 'positive' : 'negative';
    const cumClass = cf.cumulative_cashflow_pln >= 0 ? 'positive' : 'negative';

    return `
      <tr class="${isYearZero ? 'year-zero' : ''}">
        <td>${cf.year}</td>
        <td>${isYearZero ? '-' : formatNumberEU(cf.savings_pln / 1000, 1)}</td>
        <td>${isYearZero ? '-' : formatNumberEU(cf.opex_pln / 1000, 1)}</td>
        <td class="${netClass}">${formatNumberEU(cf.net_cashflow_pln / 1000, 1)}</td>
        <td class="${cumClass}">${formatNumberEU(cf.cumulative_cashflow_pln / 1000, 1)}</td>
        <td>${formatNumberEU(cf.discounted_cashflow_pln / 1000, 1)}</td>
      </tr>
    `;
  }).join('');

  tableBody.innerHTML = rows;
}

/**
 * Display discount rate sensitivity (NPV at different rates)
 */
function displayDiscountRateSensitivity(financeSummary) {
  const section = document.getElementById('drSensitivitySection');
  const chartContainer = document.getElementById('drSensitivityChart');
  const tableBody = document.getElementById('drSensitivityTableBody');

  if (!section) return;

  const sensitivity = financeSummary.discount_rate_sensitivity;
  if (!sensitivity || sensitivity.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';

  // Build simple table (chart can be added later with Chart.js)
  if (tableBody) {
    const baseRate = financeSummary.discount_rate;
    const rows = sensitivity.map(point => {
      const isBase = Math.abs(point.discount_rate - baseRate) < 0.001;
      const npvClass = point.npv_pln >= 0 ? 'positive' : 'negative';
      const rowClass = isBase ? 'base-rate' : '';

      return `
        <tr class="${rowClass}">
          <td>${formatNumberEU(point.discount_rate_pct, 1)}%${isBase ? ' (bazowa)' : ''}</td>
          <td class="${npvClass}">${formatNumberEU(point.npv_pln / 1000, 0)} tys. PLN</td>
        </tr>
      `;
    }).join('');

    tableBody.innerHTML = rows;
  }

  // Draw chart if Chart.js is available
  if (chartContainer && typeof Chart !== 'undefined') {
    drawDiscountRateSensitivityChart(chartContainer, sensitivity, financeSummary.discount_rate);
  }
}

/**
 * Draw discount rate sensitivity chart using Chart.js
 */
function drawDiscountRateSensitivityChart(container, sensitivity, baseRate) {
  const canvasId = 'drSensitivityCanvas';
  let canvas = document.getElementById(canvasId);

  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = canvasId;
    canvas.height = 200;
    container.innerHTML = '';
    container.appendChild(canvas);
  }

  // Destroy existing chart
  if (window.drSensitivityChartInstance) {
    window.drSensitivityChartInstance.destroy();
  }

  const labels = sensitivity.map(p => `${formatNumberEU(p.discount_rate_pct, 0)}%`);
  const npvValues = sensitivity.map(p => p.npv_pln / 1000);
  const colors = sensitivity.map(p => p.npv_pln >= 0 ? 'rgba(34, 197, 94, 0.8)' : 'rgba(239, 68, 68, 0.8)');
  const borderColors = sensitivity.map(p => Math.abs(p.discount_rate - baseRate) < 0.001 ? '#3b82f6' : 'transparent');

  window.drSensitivityChartInstance = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'NPV (tys. PLN)',
        data: npvValues,
        backgroundColor: colors,
        borderColor: borderColors,
        borderWidth: 3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: 'NPV vs Stopa dyskontowa',
          color: '#e5e7eb'
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'NPV (tys. PLN)', color: '#9ca3af' },
          grid: { color: 'rgba(255,255,255,0.1)' },
          ticks: { color: '#9ca3af' }
        },
        x: {
          title: { display: true, text: 'Stopa dyskontowa', color: '#9ca3af' },
          grid: { display: false },
          ticks: { color: '#9ca3af' }
        }
      }
    }
  });
}

/**
 * Display energy price sensitivity (NPV at different price multipliers)
 * v0.6.0 PR4
 */
function displayEnergyPriceSensitivity(financeSummary) {
  const section = document.getElementById('epSensitivitySection');
  const chartContainer = document.getElementById('epSensitivityChart');
  const tableBody = document.getElementById('epSensitivityTableBody');

  if (!section) return;

  const sensitivity = financeSummary.energy_price_sensitivity;
  if (!sensitivity || sensitivity.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';

  // Build table
  if (tableBody) {
    const rows = sensitivity.map(point => {
      const isBase = Math.abs(point.multiplier - 1.0) < 0.01;
      const npvClass = point.npv_pln >= 0 ? 'positive' : 'negative';
      const rowClass = isBase ? 'base-rate' : '';

      return `
        <tr class="${rowClass}">
          <td>${formatNumberEU(point.multiplier_pct, 0)}%${isBase ? ' (bazowa)' : ''}</td>
          <td class="${npvClass}">${formatNumberEU(point.npv_pln / 1000, 0)} tys. PLN</td>
        </tr>
      `;
    }).join('');

    tableBody.innerHTML = rows;
  }

  // Draw chart if Chart.js is available
  if (chartContainer && typeof Chart !== 'undefined') {
    drawEnergyPriceSensitivityChart(chartContainer, sensitivity);
  }
}

/**
 * Draw energy price sensitivity chart using Chart.js
 * v0.6.0 PR4
 */
function drawEnergyPriceSensitivityChart(container, sensitivity) {
  const canvasId = 'epSensitivityCanvas';
  let canvas = document.getElementById(canvasId);

  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = canvasId;
    canvas.height = 200;
    container.innerHTML = '';
    container.appendChild(canvas);
  }

  // Destroy existing chart
  if (window.epSensitivityChartInstance) {
    window.epSensitivityChartInstance.destroy();
  }

  const labels = sensitivity.map(p => `${formatNumberEU(p.multiplier_pct, 0)}%`);
  const npvValues = sensitivity.map(p => p.npv_pln / 1000);
  const colors = sensitivity.map(p => p.npv_pln >= 0 ? 'rgba(34, 197, 94, 0.8)' : 'rgba(239, 68, 68, 0.8)');
  const borderColors = sensitivity.map(p => Math.abs(p.multiplier - 1.0) < 0.01 ? '#3b82f6' : 'transparent');

  window.epSensitivityChartInstance = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'NPV (tys. PLN)',
        data: npvValues,
        backgroundColor: colors,
        borderColor: borderColors,
        borderWidth: 3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: 'NPV vs Cena energii',
          color: '#e5e7eb'
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'NPV (tys. PLN)', color: '#9ca3af' },
          grid: { color: 'rgba(255,255,255,0.1)' },
          ticks: { color: '#9ca3af' }
        },
        x: {
          title: { display: true, text: 'Cena energii (% bazowej)', color: '#9ca3af' },
          grid: { display: false },
          ticks: { color: '#9ca3af' }
        }
      }
    }
  });
}

/**
 * Display CAPEX sensitivity (NPV at different CAPEX multipliers)
 * v0.6.0 PR4
 */
function displayCapexSensitivity(financeSummary) {
  const section = document.getElementById('capexSensitivitySection');
  const chartContainer = document.getElementById('capexSensitivityChart');
  const tableBody = document.getElementById('capexSensitivityTableBody');

  if (!section) return;

  const sensitivity = financeSummary.capex_sensitivity;
  if (!sensitivity || sensitivity.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';

  // Build table
  if (tableBody) {
    const rows = sensitivity.map(point => {
      const isBase = Math.abs(point.multiplier - 1.0) < 0.01;
      const npvClass = point.npv_pln >= 0 ? 'positive' : 'negative';
      const rowClass = isBase ? 'base-rate' : '';

      return `
        <tr class="${rowClass}">
          <td>${formatNumberEU(point.multiplier_pct, 0)}%${isBase ? ' (bazowy)' : ''}</td>
          <td class="${npvClass}">${formatNumberEU(point.npv_pln / 1000, 0)} tys. PLN</td>
        </tr>
      `;
    }).join('');

    tableBody.innerHTML = rows;
  }

  // Draw chart if Chart.js is available
  if (chartContainer && typeof Chart !== 'undefined') {
    drawCapexSensitivityChart(chartContainer, sensitivity);
  }
}

/**
 * Draw CAPEX sensitivity chart using Chart.js
 * v0.6.0 PR4
 */
function drawCapexSensitivityChart(container, sensitivity) {
  const canvasId = 'capexSensitivityCanvas';
  let canvas = document.getElementById(canvasId);

  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = canvasId;
    canvas.height = 200;
    container.innerHTML = '';
    container.appendChild(canvas);
  }

  // Destroy existing chart
  if (window.capexSensitivityChartInstance) {
    window.capexSensitivityChartInstance.destroy();
  }

  const labels = sensitivity.map(p => `${formatNumberEU(p.multiplier_pct, 0)}%`);
  const npvValues = sensitivity.map(p => p.npv_pln / 1000);
  const colors = sensitivity.map(p => p.npv_pln >= 0 ? 'rgba(34, 197, 94, 0.8)' : 'rgba(239, 68, 68, 0.8)');
  const borderColors = sensitivity.map(p => Math.abs(p.multiplier - 1.0) < 0.01 ? '#3b82f6' : 'transparent');

  window.capexSensitivityChartInstance = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'NPV (tys. PLN)',
        data: npvValues,
        backgroundColor: colors,
        borderColor: borderColors,
        borderWidth: 3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: 'NPV vs CAPEX',
          color: '#e5e7eb'
        }
      },
      scales: {
        y: {
          title: { display: true, text: 'NPV (tys. PLN)', color: '#9ca3af' },
          grid: { color: 'rgba(255,255,255,0.1)' },
          ticks: { color: '#9ca3af' }
        },
        x: {
          title: { display: true, text: 'CAPEX (% bazowego)', color: '#9ca3af' },
          grid: { display: false },
          ticks: { color: '#9ca3af' }
        }
      }
    }
  });
}

// Export ToU and Capacity Fee functions
window.fetchTariffPresets = fetchTariffPresets;
window.calculateToUCosts = calculateToUCosts;
window.displayToUCostAnalysis = displayToUCostAnalysis;
window.fetchCapacityFeeSavings = fetchCapacityFeeSavings;
window.displayCapacityFeeOverlay = displayCapacityFeeOverlay;
window.hideCapacityFeeOverlay = hideCapacityFeeOverlay;
window.runCapacityFeeAnalysisIfEnabled = runCapacityFeeAnalysisIfEnabled;
window.displayFinanceSection = displayFinanceSection;
window.displayIRR = displayIRR;
window.displayEnergyPriceSensitivity = displayEnergyPriceSensitivity;
window.displayCapexSensitivity = displayCapexSensitivity;

// =============================================================================
// Batch Sizing UI with Async Jobs (v1.1.0)
// =============================================================================

// Active job tracking
let activeJobId = null;
let jobPollingInterval = null;
let activeEventSource = null;  // SSE connection for job progress

/**
 * Run batch sizing with multiple scenarios.
 * Uses /jobs/sizing:batch endpoint with wait=true|false support.
 */
async function runBatchSizing() {
  const batchInput = document.getElementById('batchScenariosInput');
  const runBtn = document.getElementById('runBatchBtn');
  const resultsContainer = document.getElementById('batchResultsContainer');
  const asyncModeCheckbox = document.getElementById('batchAsyncMode');

  if (!batchInput || !resultsContainer) {
    console.error('[BATCH] Missing batch UI elements');
    return;
  }

  // Parse scenarios from textarea
  let scenarios;
  try {
    scenarios = JSON.parse(batchInput.value.trim());
    if (!Array.isArray(scenarios)) {
      scenarios = [scenarios]; // Single scenario
    }
  } catch (e) {
    resultsContainer.style.display = 'block';
    resultsContainer.innerHTML = `<div class="batch-error">Invalid JSON: ${e.message}</div>`;
    return;
  }

  // Validate scenarios
  if (scenarios.length === 0) {
    resultsContainer.style.display = 'block';
    resultsContainer.innerHTML = '<div class="batch-error">No scenarios provided</div>';
    return;
  }

  // Build batch request
  const batchRequest = {
    batch_id: `batch_${Date.now()}`,
    items: scenarios.map((scenario, idx) => ({
      item_id: scenario.name || scenario.item_id || `scenario_${idx + 1}`,
      request: {
        load_kw: scenario.load_kw || scenario.request?.load_kw,
        pv_generation_kw: scenario.pv_generation_kw || scenario.request?.pv_generation_kw,
        energy_price_pln_kwh: scenario.energy_price_pln_kwh || scenario.request?.energy_price_pln_kwh || 0.8,
        mode: scenario.mode || scenario.request?.mode || 'stacked',
        ...(scenario.request || scenario)  // Allow additional fields
      }
    }))
  };

  // Check async mode
  const asyncMode = asyncModeCheckbox?.checked || false;
  const waitParam = asyncMode ? 'false' : 'true';

  // Show loading state
  runBtn.disabled = true;
  runBtn.textContent = asyncMode ? 'Submitting...' : 'Processing...';
  resultsContainer.style.display = 'block';
  resultsContainer.innerHTML = '<div class="batch-loading"><div class="spinner"></div>Processing batch...</div>';

  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs/sizing:batch?wait=${waitParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(batchRequest)
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error: ${response.status} - ${errorText}`);
    }

    const result = await response.json();

    if (asyncMode) {
      // Async mode: received job_id, start SSE (with polling fallback)
      activeJobId = result.job_id;
      displayJobStatus(result);
      startJobSSE(result.job_id);
    } else {
      // Sync mode: received full result
      displayBatchResults(result);
    }

  } catch (e) {
    resultsContainer.innerHTML = `<div class="batch-error">Batch request failed: ${e.message}</div>`;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = 'Uruchom Batch';
  }
}

/**
 * Display job status for async mode (v1.2.0 with SSE + export buttons).
 */
function displayJobStatus(jobData) {
  const container = document.getElementById('batchResultsContainer');
  if (!container) return;

  const { job_id, status, items_done, items_total, error_count, message, created_at } = jobData;

  const progressPct = items_total > 0 ? Math.round((items_done / items_total) * 100) : 0;
  const statusClass = status === 'done' ? 'status-done' :
                      status === 'running' ? 'status-running' :
                      status === 'failed' ? 'status-failed' :
                      status === 'cancelled' ? 'status-cancelled' : 'status-pending';

  // SSE indicator
  const sseActive = activeEventSource !== null;
  const connectionIndicator = sseActive ?
    '<span class="sse-indicator active" title="SSE streaming active">⚡</span>' :
    '<span class="sse-indicator" title="Polling mode">📡</span>';

  let html = `
    <div class="job-status-card">
      <div class="job-header">
        <span class="job-id">Job: ${job_id.substring(0, 8)}... ${connectionIndicator}</span>
        <span class="job-status ${statusClass}">${status.toUpperCase()}</span>
      </div>
      <div class="job-progress">
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${progressPct}%"></div>
        </div>
        <div class="progress-text">${items_done || 0} / ${items_total || '?'} items (${progressPct}%)</div>
        ${error_count > 0 ? `<div class="error-count">${error_count} errors</div>` : ''}
      </div>
      ${message ? `<div class="job-message">${message}</div>` : ''}
      <div class="job-actions">
        ${status === 'pending' || status === 'running' ? `
          <button class="btn btn-small btn-danger" onclick="cancelJob('${job_id}')">Cancel</button>
        ` : ''}
        ${status === 'done' ? `
          <button class="btn btn-small btn-primary" onclick="fetchJobResult('${job_id}')">View Results</button>
          <div class="export-buttons">
            <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${job_id}', 'json')" title="Download JSON">📄 JSON</button>
            <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${job_id}', 'csv')" title="Download CSV">📊 CSV</button>
            <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${job_id}', 'zip')" title="Download ZIP">📦 ZIP</button>
          </div>
        ` : ''}
        ${status === 'failed' ? `
          <button class="btn btn-small btn-primary" onclick="fetchJobResult('${job_id}')">View Details</button>
        ` : ''}
      </div>
    </div>
  `;

  container.innerHTML = html;
}

/**
 * Start SSE-based progress tracking for a job (v1.2.0).
 * Falls back to polling if SSE is not supported.
 */
function startJobSSE(jobId) {
  // Stop any existing SSE or polling
  stopJobSSE();
  stopJobPolling();

  if (typeof EventSource === 'undefined') {
    console.warn('[BATCH] EventSource not supported, falling back to polling');
    startJobPolling(jobId);
    return;
  }

  const bessDispatchUrl = '/api/bess-dispatch';
  activeEventSource = new EventSource(`${bessDispatchUrl}/jobs/${jobId}/events?poll_interval=0.5`);

  activeEventSource.addEventListener('progress', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Progress event:', data);
      displayJobStatus({
        job_id: jobId,
        status: 'running',
        items_done: data.items_done,
        items_total: data.items_total,
        error_count: data.error_count || 0
      });
    } catch (e) {
      console.error('[SSE] Failed to parse progress event:', e);
    }
  });

  activeEventSource.addEventListener('done', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Done event:', data);
      displayJobStatus({
        job_id: jobId,
        status: 'done',
        items_done: data.items_done,
        items_total: data.items_total,
        error_count: data.error_count || 0
      });
      stopJobSSE();
      activeJobId = null;

      // Fetch full results
      fetchJobResult(jobId);
    } catch (e) {
      console.error('[SSE] Failed to parse done event:', e);
    }
  });

  activeEventSource.addEventListener('error', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Error event:', data);
      displayJobStatus({
        job_id: jobId,
        status: 'failed',
        items_done: data.items_done || 0,
        items_total: data.items_total || 0,
        error_count: data.error_count || 0,
        message: data.message
      });
      stopJobSSE();
      activeJobId = null;
    } catch (e) {
      console.error('[SSE] Failed to parse error event:', e);
    }
  });

  activeEventSource.addEventListener('cancelled', (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[SSE] Cancelled event:', data);
      displayJobStatus({
        job_id: jobId,
        status: 'cancelled',
        items_done: data.items_done || 0,
        items_total: data.items_total || 0,
        error_count: data.error_count || 0
      });
      stopJobSSE();
      activeJobId = null;
    } catch (e) {
      console.error('[SSE] Failed to parse cancelled event:', e);
    }
  });

  activeEventSource.addEventListener('timeout', (event) => {
    console.warn('[SSE] Stream timed out, falling back to polling');
    stopJobSSE();
    startJobPolling(jobId);
  });

  activeEventSource.onerror = (error) => {
    console.error('[SSE] Connection error:', error);
    stopJobSSE();
    // Fall back to polling on connection error
    startJobPolling(jobId);
  };

  console.log('[SSE] Started SSE stream for job:', jobId);
}

/**
 * Stop SSE connection.
 */
function stopJobSSE() {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
    console.log('[SSE] Stopped SSE stream');
  }
}

/**
 * Start polling for job status (fallback when SSE not available).
 */
function startJobPolling(jobId) {
  // Clear any existing polling
  stopJobPolling();

  console.log('[BATCH] Starting polling for job:', jobId);

  jobPollingInterval = setInterval(async () => {
    try {
      const bessDispatchUrl = '/api/bess-dispatch';
      const response = await fetch(`${bessDispatchUrl}/jobs/${jobId}`);

      if (!response.ok) {
        throw new Error(`Failed to get job status: ${response.status}`);
      }

      const jobData = await response.json();
      displayJobStatus(jobData);

      // Stop polling if job is complete
      if (jobData.status === 'done' || jobData.status === 'failed' || jobData.status === 'cancelled') {
        stopJobPolling();
        activeJobId = null;

        // Auto-fetch results if done
        if (jobData.status === 'done' && jobData.result) {
          displayBatchResults(jobData.result);
        }
      }
    } catch (e) {
      console.error('[BATCH] Polling error:', e);
    }
  }, 2000); // Poll every 2 seconds
}

/**
 * Stop job polling.
 */
function stopJobPolling() {
  if (jobPollingInterval) {
    clearInterval(jobPollingInterval);
    jobPollingInterval = null;
  }
}

/**
 * Download job export in specified format (v1.2.0).
 * @param {string} jobId - Job ID
 * @param {string} format - Export format: 'json', 'csv', or 'zip'
 */
async function downloadJobExport(jobId, format = 'json') {
  const validFormats = ['json', 'csv', 'zip'];
  if (!validFormats.includes(format)) {
    console.error('[EXPORT] Invalid format:', format);
    return;
  }

  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs/${jobId}/export/${format}`);

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Export failed: ${response.status} - ${errorText}`);
    }

    // Get filename from Content-Disposition header or generate one
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = `job_${jobId.substring(0, 8)}.${format}`;
    if (contentDisposition) {
      const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (match && match[1]) {
        filename = match[1].replace(/['"]/g, '');
      }
    }

    // Download the file
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    console.log('[EXPORT] Downloaded:', filename);
  } catch (e) {
    console.error('[EXPORT] Download failed:', e);
    alert(`Export failed: ${e.message}`);
  }
}

/**
 * Cancel an active job.
 */
async function cancelJob(jobId) {
  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs/${jobId}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      throw new Error(`Failed to cancel job: ${response.status}`);
    }

    const result = await response.json();
    displayJobStatus(result);
    stopJobSSE();
    stopJobPolling();

  } catch (e) {
    console.error('[BATCH] Cancel error:', e);
    alert(`Failed to cancel job: ${e.message}`);
  }
}

/**
 * Fetch and display job results.
 */
async function fetchJobResult(jobId) {
  const container = document.getElementById('batchResultsContainer');
  if (!container) return;

  container.innerHTML = '<div class="batch-loading"><div class="spinner"></div>Loading results...</div>';

  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs/${jobId}`);

    if (!response.ok) {
      throw new Error(`Failed to get job: ${response.status}`);
    }

    const jobData = await response.json();

    if (jobData.result) {
      displayBatchResults(jobData.result, jobId);
    } else {
      container.innerHTML = `<div class="batch-error">No results available (status: ${jobData.status})</div>`;
    }

  } catch (e) {
    container.innerHTML = `<div class="batch-error">Failed to load results: ${e.message}</div>`;
  }
}

/**
 * Refresh job list.
 */
async function refreshJobList() {
  const container = document.getElementById('jobListContainer');
  if (!container) return;

  try {
    const bessDispatchUrl = '/api/bess-dispatch';
    const response = await fetch(`${bessDispatchUrl}/jobs?limit=10`);

    if (!response.ok) {
      throw new Error(`Failed to get jobs: ${response.status}`);
    }

    const jobsData = await response.json();
    displayJobList(jobsData);

  } catch (e) {
    container.innerHTML = `<div class="batch-error">Failed to load jobs: ${e.message}</div>`;
  }
}

/**
 * Display list of recent jobs.
 */
function displayJobList(jobsData) {
  const container = document.getElementById('jobListContainer');
  if (!container) return;

  const { items, total } = jobsData;

  if (!items || items.length === 0) {
    container.innerHTML = '<div class="no-jobs">No recent jobs</div>';
    return;
  }

  let html = `
    <div class="job-list">
      <div class="job-list-header">
        <span>Recent Jobs (${items.length} of ${total})</span>
        <button class="btn btn-small btn-secondary" onclick="refreshJobList()">Refresh</button>
      </div>
      <table class="job-list-table">
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Status</th>
            <th>Progress</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(job => {
            const statusClass = job.status === 'done' ? 'status-done' :
                                job.status === 'running' ? 'status-running' :
                                job.status === 'failed' ? 'status-failed' :
                                job.status === 'cancelled' ? 'status-cancelled' : 'status-pending';
            const progressPct = job.items_total > 0 ? Math.round((job.items_done / job.items_total) * 100) : 0;
            const createdTime = new Date(job.created_at).toLocaleTimeString();

            return `
              <tr>
                <td class="job-id-cell">${job.job_id.substring(0, 8)}...</td>
                <td><span class="job-status-badge ${statusClass}">${job.status}</span></td>
                <td>${job.items_done || 0}/${job.items_total || '?'} (${progressPct}%)</td>
                <td>${createdTime}</td>
                <td>
                  ${job.status === 'done' ? `
                    <button class="btn btn-tiny btn-primary" onclick="fetchJobResult('${job.job_id}')">View</button>
                  ` : ''}
                  ${job.status === 'pending' || job.status === 'running' ? `
                    <button class="btn btn-tiny btn-danger" onclick="cancelJob('${job.job_id}')">Cancel</button>
                  ` : ''}
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;
}

/**
 * Display batch sizing results including portfolio summary (v1.2.0 with export buttons).
 * @param {object} batchResult - Batch result object
 * @param {string} [jobId] - Optional job ID for export buttons (when results fetched from job)
 */
function displayBatchResults(batchResult, jobId = null) {
  const container = document.getElementById('batchResultsContainer');
  if (!container) return;

  const { batch_id, summary, portfolio_summary, results } = batchResult;

  // Export buttons (only when jobId is available)
  const exportButtonsHtml = jobId ? `
    <div class="export-buttons-header">
      <span class="export-label">Export:</span>
      <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${jobId}', 'json')" title="Download JSON">📄 JSON</button>
      <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${jobId}', 'csv')" title="Download CSV">📊 CSV</button>
      <button class="btn btn-small btn-secondary" onclick="downloadJobExport('${jobId}', 'zip')" title="Download ZIP">📦 ZIP</button>
    </div>
  ` : '';

  // Build HTML
  let html = `
    <div class="batch-results">
      <div class="batch-summary-header">
        <h4>Batch: ${batch_id}</h4>
        <div class="batch-stats">
          <span class="stat-ok">${summary.ok_count} OK</span>
          <span class="stat-error">${summary.error_count} errors</span>
          <span class="stat-time">${summary.processing_time_ms.toFixed(0)}ms</span>
        </div>
        ${exportButtonsHtml}
      </div>
  `;

  // Portfolio Summary
  if (portfolio_summary) {
    html += `
      <div class="portfolio-summary-card">
        <h5>Portfolio Summary</h5>
        <div class="portfolio-metrics">
          <div class="metric">
            <span class="metric-label">Total NPV</span>
            <span class="metric-value ${portfolio_summary.total_npv_pln >= 0 ? 'positive' : 'negative'}">
              ${formatNpv(portfolio_summary.total_npv_pln)}
            </span>
          </div>
          <div class="metric">
            <span class="metric-label">Avg NPV</span>
            <span class="metric-value">${formatNpv(portfolio_summary.avg_npv_pln)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Avg Payback</span>
            <span class="metric-value">${portfolio_summary.avg_payback_years.toFixed(1)} lat</span>
          </div>
          <div class="metric optimal">
            <span class="metric-label">Optymalny wariant</span>
            <span class="metric-value">${portfolio_summary.portfolio_optimal_variant}</span>
          </div>
        </div>

        <h6>Ranking wariantow</h6>
        <table class="variant-rankings-table">
          <thead>
            <tr>
              <th>Wariant</th>
              <th>Total NPV</th>
              <th>Avg NPV</th>
              <th>Avg Payback</th>
              <th>Recommended</th>
            </tr>
          </thead>
          <tbody>
            ${portfolio_summary.variant_rankings.map((r, idx) => `
              <tr class="${idx === 0 ? 'optimal-row' : ''}">
                <td>${r.variant}</td>
                <td class="${r.total_npv_pln >= 0 ? 'positive' : 'negative'}">${formatNpv(r.total_npv_pln)}</td>
                <td>${formatNpv(r.avg_npv_pln)}</td>
                <td>${r.avg_payback_years.toFixed(1)} lat</td>
                <td>${r.recommended_count}x</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  // Individual Results
  html += `
    <div class="batch-items">
      <h5>Wyniki scenariuszy</h5>
      ${results.map(r => `
        <div class="batch-item ${r.status}">
          <div class="item-header">
            <span class="item-id">${r.item_id}</span>
            <span class="item-status ${r.status}">${r.status.toUpperCase()}</span>
          </div>
          ${r.status === 'ok' ? `
            <div class="item-summary">
              <span>Recommended: <strong>${r.response.recommended_variant}</strong></span>
              <span>NPV: <strong class="${r.response.variants.find(v => v.is_recommended)?.npv_pln >= 0 ? 'positive' : 'negative'}">
                ${formatNpv(r.response.variants.find(v => v.is_recommended)?.npv_pln || 0)}
              </strong></span>
              ${r.response.cache_info ? `
                <span class="cache-status ${r.response.cache_info.cache_status}">
                  Cache: ${r.response.cache_info.cache_status}
                </span>
              ` : ''}
            </div>
          ` : `
            <div class="item-error">${r.error}</div>
          `}
        </div>
      `).join('')}
    </div>
    </div>
  `;

  container.innerHTML = html;
}

/**
 * Format NPV value for display.
 */
function formatNpv(value) {
  if (Math.abs(value) >= 1000) {
    return (value / 1000).toFixed(1) + ' tys. PLN';
  }
  return value.toFixed(0) + ' PLN';
}

/**
 * Load sample batch scenarios into the input.
 */
function loadSampleBatchScenarios() {
  const sampleScenarios = [
    {
      "name": "Site A - Office",
      "load_kw": [50, 60, 70, 80, 90, 100, 110, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 30, 30, 30, 30, 40, 50, 50],
      "pv_generation_kw": [0, 0, 0, 0, 5, 20, 40, 60, 80, 90, 95, 100, 95, 80, 60, 40, 20, 5, 0, 0, 0, 0, 0, 0],
      "energy_price_pln_kwh": 0.85
    },
    {
      "name": "Site B - Warehouse",
      "load_kw": [30, 30, 30, 40, 50, 60, 70, 80, 80, 80, 80, 80, 80, 80, 70, 60, 50, 40, 30, 30, 30, 30, 30, 30],
      "pv_generation_kw": [0, 0, 0, 0, 10, 30, 50, 70, 90, 95, 100, 100, 95, 80, 60, 40, 20, 10, 0, 0, 0, 0, 0, 0],
      "energy_price_pln_kwh": 0.75
    }
  ];

  const batchInput = document.getElementById('batchScenariosInput');
  if (batchInput) {
    batchInput.value = JSON.stringify(sampleScenarios, null, 2);
  }
}

// Export batch and job functions
window.runBatchSizing = runBatchSizing;
window.displayBatchResults = displayBatchResults;
window.loadSampleBatchScenarios = loadSampleBatchScenarios;
window.displayJobStatus = displayJobStatus;
window.cancelJob = cancelJob;
window.fetchJobResult = fetchJobResult;
window.refreshJobList = refreshJobList;
window.displayJobList = displayJobList;
// v1.2.0 exports
window.startJobSSE = startJobSSE;
window.stopJobSSE = stopJobSSE;
window.downloadJobExport = downloadJobExport;

// =============================================================================
// v1.3.0: Run Explorer (Run History + Metadata Edit)
// =============================================================================

/** Run Explorer state */
const runExplorerState = {
  runs: [],
  total: 0,
  limit: 10,
  offset: 0,
  currentSort: 'created_at_desc',
  currentTag: '',
  currentQuery: '',
  currentEndpoint: '',
  selectedRunId: null,
  debounceTimer: null,
  knownTags: new Set()
};

/**
 * Refresh the run list from API.
 */
async function refreshRunList() {
  const tbody = document.getElementById('runsTableBody');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="7" class="loading-row">Ladowanie...</td></tr>';

  try {
    const params = new URLSearchParams();
    params.set('limit', runExplorerState.limit);
    params.set('offset', runExplorerState.offset);
    params.set('sort', runExplorerState.currentSort);

    if (runExplorerState.currentTag) {
      params.set('tag', runExplorerState.currentTag);
    }
    if (runExplorerState.currentQuery) {
      params.set('q', runExplorerState.currentQuery);
    }
    if (runExplorerState.currentEndpoint) {
      params.set('endpoint', runExplorerState.currentEndpoint);
    }

    const response = await fetch(`http://localhost:8031/runs?${params.toString()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    runExplorerState.runs = data.items || [];
    runExplorerState.total = data.total || 0;

    // Collect tags for filter dropdown
    runExplorerState.runs.forEach(run => {
      if (run.tags && Array.isArray(run.tags)) {
        run.tags.forEach(tag => runExplorerState.knownTags.add(tag));
      }
    });
    updateTagFilterDropdown();

    displayRunsTable();
    updateRunsPagination();
  } catch (err) {
    console.error('[RunExplorer] Error fetching runs:', err);
    tbody.innerHTML = `<tr><td colspan="7" class="error-row">Blad: ${err.message}</td></tr>`;
  }
}

/**
 * Display runs in the table.
 */
function displayRunsTable() {
  const tbody = document.getElementById('runsTableBody');
  if (!tbody) return;

  if (runExplorerState.runs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row">Brak uruchomien</td></tr>';
    return;
  }

  tbody.innerHTML = runExplorerState.runs.map(run => {
    const shortId = run.run_id.substring(0, 8) + '...';
    const createdDate = new Date(run.created_at).toLocaleString('pl-PL');
    const label = run.label || '-';
    const tags = (run.tags && run.tags.length > 0) ? run.tags.join(', ') : '-';

    // Try to extract NPV from the run (if available)
    let npvDisplay = '-';
    // NPV might be in response if we fetched full run details

    return `
      <tr class="run-row ${runExplorerState.selectedRunId === run.run_id ? 'selected' : ''}"
          onclick="selectRun('${run.run_id}')">
        <td class="run-id-cell" title="${run.run_id}">${shortId}</td>
        <td>${createdDate}</td>
        <td><span class="endpoint-badge">${run.endpoint || 'sizing'}</span></td>
        <td class="run-label-cell">${escapeHtml(label)}</td>
        <td class="run-tags-cell">${escapeHtml(tags)}</td>
        <td>${npvDisplay}</td>
        <td>
          <button class="btn btn-tiny btn-primary" onclick="event.stopPropagation(); selectRun('${run.run_id}')">Szczegoly</button>
        </td>
      </tr>
    `;
  }).join('');
}

/**
 * Escape HTML characters.
 */
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
}

/**
 * Update pagination controls.
 */
function updateRunsPagination() {
  const pageInfo = document.getElementById('runsPageInfo');
  const prevBtn = document.getElementById('runsPrevBtn');
  const nextBtn = document.getElementById('runsNextBtn');

  const currentPage = Math.floor(runExplorerState.offset / runExplorerState.limit) + 1;
  const totalPages = Math.ceil(runExplorerState.total / runExplorerState.limit) || 1;

  if (pageInfo) {
    pageInfo.textContent = `Strona ${currentPage} z ${totalPages} (${runExplorerState.total} wynikow)`;
  }
  if (prevBtn) {
    prevBtn.disabled = runExplorerState.offset === 0;
  }
  if (nextBtn) {
    nextBtn.disabled = runExplorerState.offset + runExplorerState.limit >= runExplorerState.total;
  }
}

/**
 * Go to previous page.
 */
function prevRunsPage() {
  if (runExplorerState.offset > 0) {
    runExplorerState.offset -= runExplorerState.limit;
    if (runExplorerState.offset < 0) runExplorerState.offset = 0;
    refreshRunList();
  }
}

/**
 * Go to next page.
 */
function nextRunsPage() {
  if (runExplorerState.offset + runExplorerState.limit < runExplorerState.total) {
    runExplorerState.offset += runExplorerState.limit;
    refreshRunList();
  }
}

/**
 * Update tag filter dropdown with known tags.
 */
function updateTagFilterDropdown() {
  const select = document.getElementById('runTagFilter');
  if (!select) return;

  // Keep current selection
  const currentValue = select.value;

  // Rebuild options
  select.innerHTML = '<option value="">Wszystkie</option>';
  Array.from(runExplorerState.knownTags).sort().forEach(tag => {
    const option = document.createElement('option');
    option.value = tag;
    option.textContent = tag;
    select.appendChild(option);
  });

  // Restore selection
  select.value = currentValue;
}

/**
 * Filter by tag.
 */
function filterRunsByTag(tag) {
  runExplorerState.currentTag = tag;
  runExplorerState.offset = 0;
  refreshRunList();
}

/**
 * Filter by endpoint.
 */
function filterRunsByEndpoint(endpoint) {
  runExplorerState.currentEndpoint = endpoint;
  runExplorerState.offset = 0;
  refreshRunList();
}

/**
 * Debounced search handler.
 */
function debounceRunSearch(query) {
  clearTimeout(runExplorerState.debounceTimer);
  runExplorerState.debounceTimer = setTimeout(() => {
    runExplorerState.currentQuery = query;
    runExplorerState.offset = 0;
    refreshRunList();
  }, 300);
}

/**
 * Change sort order.
 */
function changeRunSort(sort) {
  runExplorerState.currentSort = sort;
  runExplorerState.offset = 0;
  refreshRunList();
}

/**
 * Select a run and show details panel.
 */
async function selectRun(runId) {
  runExplorerState.selectedRunId = runId;
  displayRunsTable(); // Re-render to show selection

  // Show detail panel
  const panel = document.getElementById('runDetailPanel');
  if (panel) panel.style.display = 'block';

  // Fetch full run details
  try {
    const response = await fetch(`http://localhost:8031/runs/${runId}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const run = await response.json();
    displayRunDetail(run);
  } catch (err) {
    console.error('[RunExplorer] Error fetching run details:', err);
    showRunMetadataStatus(`Blad: ${err.message}`, 'error');
  }
}

/**
 * Display run details in the panel.
 */
function displayRunDetail(run) {
  document.getElementById('detailRunId').textContent = run.run_id;
  document.getElementById('detailRequestHash').textContent = run.request_hash || '-';
  document.getElementById('detailCreatedAt').textContent = run.created_at ? new Date(run.created_at).toLocaleString('pl-PL') : '-';
  document.getElementById('detailUpdatedAt').textContent = run.updated_at ? new Date(run.updated_at).toLocaleString('pl-PL') : '-';
  document.getElementById('detailEndpoint').textContent = run.endpoint || 'sizing';
  document.getElementById('detailCacheHit').textContent = run.cache_hit ? 'Tak' : 'Nie';

  // Populate metadata form
  document.getElementById('editRunLabel').value = run.label || '';
  document.getElementById('editRunTags').value = (run.tags && run.tags.length > 0) ? run.tags.join(', ') : '';
  document.getElementById('editRunNotes').value = run.notes || '';

  // Clear save status
  showRunMetadataStatus('', '');
}

/**
 * Close run detail panel.
 */
function closeRunDetail() {
  const panel = document.getElementById('runDetailPanel');
  if (panel) panel.style.display = 'none';
  runExplorerState.selectedRunId = null;
  displayRunsTable();
}

/**
 * Save run metadata via PATCH.
 */
async function saveRunMetadata() {
  if (!runExplorerState.selectedRunId) return;

  const label = document.getElementById('editRunLabel').value.trim() || null;
  const tagsStr = document.getElementById('editRunTags').value.trim();
  const notes = document.getElementById('editRunNotes').value.trim() || null;

  // Parse tags
  let tags = null;
  if (tagsStr) {
    tags = tagsStr.split(',').map(t => t.trim()).filter(t => t.length > 0);
    // Validate tags
    const tagRegex = /^[a-zA-Z0-9_-]+$/;
    for (const tag of tags) {
      if (tag.length > 32) {
        showRunMetadataStatus(`Tag "${tag}" za dlugi (max 32 znaki)`, 'error');
        return;
      }
      if (!tagRegex.test(tag)) {
        showRunMetadataStatus(`Tag "${tag}" zawiera niedozwolone znaki`, 'error');
        return;
      }
    }
    if (tags.length > 20) {
      showRunMetadataStatus('Za duzo tagow (max 20)', 'error');
      return;
    }
  }

  const payload = {};
  if (label !== null) payload.label = label;
  if (tags !== null) payload.tags = tags;
  if (notes !== null) payload.notes = notes;

  try {
    showRunMetadataStatus('Zapisywanie...', 'info');

    const response = await fetch(`http://localhost:8031/runs/${runExplorerState.selectedRunId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errBody = await response.text();
      throw new Error(`HTTP ${response.status}: ${errBody}`);
    }

    const result = await response.json();
    showRunMetadataStatus('Zapisano!', 'success');

    // Add any new tags to known tags
    if (tags && tags.length > 0) {
      tags.forEach(t => runExplorerState.knownTags.add(t));
      updateTagFilterDropdown();
    }

    // Refresh the list to show updated label/tags
    refreshRunList();
  } catch (err) {
    console.error('[RunExplorer] Error saving metadata:', err);
    showRunMetadataStatus(`Blad: ${err.message}`, 'error');
  }
}

/**
 * Show metadata save status.
 */
function showRunMetadataStatus(message, type) {
  const status = document.getElementById('runMetadataSaveStatus');
  if (!status) return;

  status.textContent = message;
  status.className = 'save-status';
  if (type) status.classList.add(type);

  // Auto-clear success message
  if (type === 'success') {
    setTimeout(() => {
      status.textContent = '';
      status.className = 'save-status';
    }, 3000);
  }
}

// Export Run Explorer functions
window.refreshRunList = refreshRunList;
window.prevRunsPage = prevRunsPage;
window.nextRunsPage = nextRunsPage;
window.filterRunsByTag = filterRunsByTag;
window.filterRunsByEndpoint = filterRunsByEndpoint;
window.debounceRunSearch = debounceRunSearch;
window.changeRunSort = changeRunSort;
window.selectRun = selectRun;
window.closeRunDetail = closeRunDetail;
window.saveRunMetadata = saveRunMetadata;

// Initialize Run Explorer on load
document.addEventListener('DOMContentLoaded', () => {
  // Delay to allow page to render
  setTimeout(() => {
    refreshRunList();
  }, 500);
});

// ============================================
// v1.3.0: Compare Runs UI (PR 5/6)
// ============================================

// Compare state
const compareState = {
  runIdA: null,
  runIdB: null,
  pickerTarget: null, // 'A' or 'B'
  pickerRuns: [],
  pickerFilter: ''
};

/**
 * Open run picker modal for selecting comparison run
 */
function openRunPickerForCompare(target) {
  compareState.pickerTarget = target;
  compareState.pickerFilter = '';

  const modal = document.getElementById('runPickerModal');
  const searchInput = document.getElementById('runPickerSearch');

  modal.style.display = 'flex';
  searchInput.value = '';

  loadRunsForPicker();
}

/**
 * Close run picker modal
 */
function closeRunPicker() {
  const modal = document.getElementById('runPickerModal');
  modal.style.display = 'none';
  compareState.pickerTarget = null;
}

/**
 * Load runs for picker (uses existing run list API)
 */
async function loadRunsForPicker() {
  const listContainer = document.getElementById('runPickerList');
  listContainer.innerHTML = '<div class="loading-row">Ladowanie...</div>';

  try {
    const response = await fetch(`${API_BASE_URL}/runs?limit=50&sort=created_at_desc`);
    if (!response.ok) throw new Error('Failed to load runs');

    const data = await response.json();
    compareState.pickerRuns = data.items || [];
    renderRunPickerList();
  } catch (error) {
    console.error('[Compare] Failed to load runs for picker:', error);
    listContainer.innerHTML = '<div class="error-row">Blad ladowania</div>';
  }
}

/**
 * Render the run picker list with optional filter
 */
function renderRunPickerList() {
  const listContainer = document.getElementById('runPickerList');
  const filter = compareState.pickerFilter.toLowerCase();

  const filteredRuns = compareState.pickerRuns.filter(run => {
    if (!filter) return true;
    const runId = (run.run_id || '').toLowerCase();
    const label = (run.label || '').toLowerCase();
    return runId.includes(filter) || label.includes(filter);
  });

  if (filteredRuns.length === 0) {
    listContainer.innerHTML = '<div class="empty-row">Brak wynikow</div>';
    return;
  }

  listContainer.innerHTML = filteredRuns.map(run => {
    const shortId = (run.run_id || '').substring(0, 8);
    const label = run.label || '-';
    const createdAt = formatDateTime(run.created_at);
    return `
      <div class="run-picker-item" onclick="selectRunForCompare('${run.run_id}')">
        <span class="picker-run-id">${shortId}</span>
        <span class="picker-run-label">${label}</span>
        <span class="picker-run-date">${createdAt}</span>
      </div>
    `;
  }).join('');
}

/**
 * Filter run picker list
 */
function filterRunPickerList(value) {
  compareState.pickerFilter = value;
  renderRunPickerList();
}

/**
 * Select a run for comparison
 */
function selectRunForCompare(runId) {
  const target = compareState.pickerTarget;

  if (target === 'A') {
    compareState.runIdA = runId;
    document.getElementById('compareRunA').value = runId.substring(0, 8) + '...';
  } else if (target === 'B') {
    compareState.runIdB = runId;
    document.getElementById('compareRunB').value = runId.substring(0, 8) + '...';
  }

  closeRunPicker();
  updateCompareButton();
}

/**
 * Update compare button state
 */
function updateCompareButton() {
  const btn = document.getElementById('compareRunsBtn');
  btn.disabled = !(compareState.runIdA && compareState.runIdB);
}

/**
 * Compare the two selected runs
 */
async function compareRuns() {
  if (!compareState.runIdA || !compareState.runIdB) {
    alert('Wybierz dwa uruchomienia do porownania');
    return;
  }

  const btn = document.getElementById('compareRunsBtn');
  btn.disabled = true;
  btn.textContent = 'Porownywanie...';

  try {
    const response = await fetch(`${API_BASE_URL}/runs:compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id_a: compareState.runIdA,
        run_id_b: compareState.runIdB
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Compare failed');
    }

    const result = await response.json();
    displayCompareResults(result);
  } catch (error) {
    console.error('[Compare] Failed:', error);
    alert('Blad porownania: ' + error.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Porownaj';
  }
}

/**
 * Display compare results
 */
function displayCompareResults(result) {
  const panel = document.getElementById('compareResultsPanel');
  panel.style.display = 'block';

  // Summary
  document.getElementById('compareSameHash').textContent =
    result.same_request_hash ? 'Identyczny' : 'Rozny';
  document.getElementById('compareSameHash').className =
    'summary-value ' + (result.same_request_hash ? 'same' : 'different');

  document.getElementById('compareVariantA').textContent =
    result.recommended_variant_a || '-';
  document.getElementById('compareVariantB').textContent =
    result.recommended_variant_b || '-';

  document.getElementById('compareVariantChanged').textContent =
    result.variant_changed ? 'Tak' : 'Nie';
  document.getElementById('compareVariantChanged').className =
    'summary-value ' + (result.variant_changed ? 'changed' : 'unchanged');

  // Delta table
  const tbody = document.getElementById('deltaTableBody');
  const deltas = result.key_deltas || [];

  if (deltas.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Brak danych do porownania</td></tr>';
    return;
  }

  tbody.innerHTML = deltas.map(delta => {
    const fieldName = formatFieldName(delta.field);
    const valueA = formatDeltaValue(delta.a, delta.field);
    const valueB = formatDeltaValue(delta.b, delta.field);
    const deltaVal = formatDeltaValue(delta.delta, delta.field);
    const pctChange = formatPctChange(delta.pct_change);
    const deltaClass = getDeltaClass(delta.delta, delta.field);

    return `
      <tr>
        <td class="field-name">${fieldName}</td>
        <td class="value-a">${valueA}</td>
        <td class="value-b">${valueB}</td>
        <td class="delta-value ${deltaClass}">${deltaVal}</td>
        <td class="pct-change ${deltaClass}">${pctChange}</td>
      </tr>
    `;
  }).join('');
}

/**
 * Format field name for display
 */
function formatFieldName(field) {
  const fieldNames = {
    'npv_pln': 'NPV',
    'payback_years': 'Payback',
    'capex_pln': 'CAPEX',
    'net_savings_pln': 'Oszczednosci',
    'irr_pct': 'IRR',
    'power_kw': 'Moc',
    'energy_kwh': 'Energia'
  };
  return fieldNames[field] || field;
}

/**
 * Format delta value for display
 */
function formatDeltaValue(value, field) {
  if (value === null || value === undefined) return '-';

  if (field.includes('pln') || field.includes('PLN')) {
    return formatNumber(value) + ' PLN';
  }
  if (field.includes('years')) {
    return value.toFixed(1) + ' lat';
  }
  if (field.includes('pct') || field.includes('%')) {
    return value.toFixed(1) + '%';
  }
  if (field.includes('kw') || field.includes('kW')) {
    return formatNumber(value) + ' kW';
  }
  if (field.includes('kwh') || field.includes('kWh')) {
    return formatNumber(value) + ' kWh';
  }

  return typeof value === 'number' ? formatNumber(value) : value;
}

/**
 * Format percentage change
 */
function formatPctChange(pct) {
  if (pct === null || pct === undefined) return '-';
  const sign = pct >= 0 ? '+' : '';
  return sign + pct.toFixed(1) + '%';
}

/**
 * Get CSS class for delta value
 */
function getDeltaClass(delta, field) {
  if (delta === null || delta === undefined || delta === 0) return 'neutral';

  // For NPV, savings, IRR - positive is good
  if (field.includes('npv') || field.includes('savings') || field.includes('irr')) {
    return delta > 0 ? 'positive' : 'negative';
  }

  // For CAPEX, payback - negative is good (less cost, faster payback)
  if (field.includes('capex') || field.includes('payback')) {
    return delta < 0 ? 'positive' : 'negative';
  }

  return 'neutral';
}

/**
 * Format number with thousands separator
 */
function formatNumber(num) {
  if (typeof num !== 'number') return num;
  return Math.round(num).toLocaleString('pl-PL');
}

/**
 * Clear compare results
 */
function clearCompareResults() {
  const panel = document.getElementById('compareResultsPanel');
  panel.style.display = 'none';

  compareState.runIdA = null;
  compareState.runIdB = null;

  document.getElementById('compareRunA').value = '';
  document.getElementById('compareRunB').value = '';

  updateCompareButton();
}

// Export Compare Runs functions
window.openRunPickerForCompare = openRunPickerForCompare;
window.closeRunPicker = closeRunPicker;
window.filterRunPickerList = filterRunPickerList;
window.selectRunForCompare = selectRunForCompare;
window.compareRuns = compareRuns;
window.clearCompareResults = clearCompareResults;

// ============================================================================
// v1.4.0: Scenario Validation
// ============================================================================

/**
 * Scenario validation state
 */
const validationState = {
  scenarios: [],
  selectedScenario: null,
  isLoading: false
};

/**
 * Load available scenarios from docs/scenarios/ (via API)
 */
async function loadAvailableScenarios() {
  console.log('[Validation] Loading available scenarios...');

  // For now, use hardcoded list matching docs/scenarios/*.json
  // In a full implementation, this could fetch from an API endpoint
  const scenarios = [
    {
      id: 'baseline_stacked_no_arb',
      description: 'Baseline scenario: STACKED mode without arbitrage (from smoke test)',
      request_file: 'scripts/smoke/sizing_stacked_no_arbitrage.json'
    },
    {
      id: 'baseline_stacked_with_arb',
      description: 'Baseline scenario: STACKED mode with ToU arbitrage (C12a/PGE)',
      request_file: 'scripts/smoke/sizing_stacked_with_arbitrage.json'
    }
  ];

  validationState.scenarios = scenarios;

  // Populate the select dropdown
  const select = document.getElementById('validationScenarioSelect');
  if (!select) return;

  // Clear existing options (except the first placeholder)
  while (select.options.length > 1) {
    select.remove(1);
  }

  // Add scenario options
  scenarios.forEach(scenario => {
    const option = document.createElement('option');
    option.value = scenario.id;
    option.textContent = scenario.id;
    select.appendChild(option);
  });

  console.log(`[Validation] Loaded ${scenarios.length} scenarios`);
}

/**
 * Refresh scenario list
 */
function refreshScenarioList() {
  loadAvailableScenarios();
}

/**
 * Load scenario details when selected
 */
function loadScenarioDetails() {
  const select = document.getElementById('validationScenarioSelect');
  const scenarioId = select.value;

  const detailsDiv = document.getElementById('scenarioDetails');
  const runBtn = document.getElementById('runValidationBtn');

  if (!scenarioId) {
    detailsDiv.style.display = 'none';
    runBtn.disabled = true;
    validationState.selectedScenario = null;
    return;
  }

  // Find scenario
  const scenario = validationState.scenarios.find(s => s.id === scenarioId);
  if (!scenario) {
    detailsDiv.style.display = 'none';
    runBtn.disabled = true;
    return;
  }

  validationState.selectedScenario = scenario;

  // Update details
  document.getElementById('scenarioDescription').textContent = scenario.description;
  document.getElementById('scenarioRequestFile').textContent = scenario.request_file;

  detailsDiv.style.display = 'block';
  runBtn.disabled = false;
}

/**
 * Run scenario validation via POST /validate/sizing
 */
async function runScenarioValidation() {
  const scenario = validationState.selectedScenario;
  if (!scenario) {
    console.warn('[Validation] No scenario selected');
    return;
  }

  console.log(`[Validation] Running validation for scenario: ${scenario.id}`);

  // Show loading state
  const resultsContainer = document.getElementById('validationResultsContainer');
  const statusDiv = document.getElementById('validationStatus');
  const statusIcon = document.getElementById('validationStatusIcon');
  const statusText = document.getElementById('validationStatusText');
  const summaryDiv = document.getElementById('validationSummary');
  const diffsDiv = document.getElementById('validationDiffs');

  resultsContainer.style.display = 'block';
  statusDiv.className = 'validation-status';
  statusIcon.textContent = '⏳';
  statusText.textContent = 'Uruchamianie walidacji...';
  summaryDiv.style.display = 'none';
  diffsDiv.style.display = 'none';

  // Disable button
  const runBtn = document.getElementById('runValidationBtn');
  runBtn.disabled = true;
  runBtn.textContent = '⏳ Walidacja...';

  try {
    // Load scenario file to get expected_kpis
    const scenarioResponse = await fetch(`docs/scenarios/${scenario.id}.json`);
    if (!scenarioResponse.ok) {
      throw new Error(`Failed to load scenario file: ${scenarioResponse.status}`);
    }
    const scenarioData = await scenarioResponse.json();

    // Load request file
    const requestResponse = await fetch(scenario.request_file);
    if (!requestResponse.ok) {
      throw new Error(`Failed to load request file: ${requestResponse.status}`);
    }
    const requestData = await requestResponse.json();

    // Build validation request
    const validateRequest = {
      request: requestData,
      expected_kpis: scenarioData.expected_kpis,
      tolerances: scenarioData.tolerances || null,
      scenario_id: scenario.id
    };

    // Call validation endpoint
    const apiUrl = BESS_CONFIG?.apiBaseUrl || 'http://localhost:8031';
    const response = await fetch(`${apiUrl}/validate/sizing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(validateRequest)
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `Validation API error: ${response.status}`);
    }

    const result = await response.json();
    displayValidationResults(result);

  } catch (error) {
    console.error('[Validation] Error:', error);

    statusDiv.className = 'validation-status failed';
    statusIcon.textContent = '❌';
    statusText.textContent = `Blad: ${error.message}`;

  } finally {
    runBtn.disabled = false;
    runBtn.textContent = '🧪 Uruchom Walidacje';
  }
}

/**
 * Display validation results
 * @param {Object} result - Validation API response
 */
function displayValidationResults(result) {
  console.log('[Validation] Displaying results:', result);

  const statusDiv = document.getElementById('validationStatus');
  const statusIcon = document.getElementById('validationStatusIcon');
  const statusText = document.getElementById('validationStatusText');
  const summaryDiv = document.getElementById('validationSummary');
  const diffsDiv = document.getElementById('validationDiffs');

  // Update status
  if (result.passed) {
    statusDiv.className = 'validation-status passed';
    statusIcon.textContent = '✅';
    statusText.textContent = 'Walidacja PASSED - wszystkie KPI w tolerancji';
  } else {
    statusDiv.className = 'validation-status failed';
    statusIcon.textContent = '❌';
    statusText.textContent = `Walidacja FAILED - ${result.failed_fields?.length || 0} pol poza tolerancja`;
  }

  // Update summary
  const passedCount = result.passed_fields?.length || 0;
  const failedCount = result.failed_fields?.length || 0;

  document.getElementById('validationPassedCount').textContent = passedCount;
  document.getElementById('validationFailedCount').textContent = failedCount;
  document.getElementById('validationRunId').textContent = result.run_id ? result.run_id.substring(0, 8) : '-';

  summaryDiv.style.display = 'flex';

  // Update diffs table
  const diffsBody = document.getElementById('validationDiffsBody');
  diffsBody.innerHTML = '';

  if (result.diffs && result.diffs.length > 0) {
    // Sort: failed first, then by field name
    const sortedDiffs = [...result.diffs].sort((a, b) => {
      if (a.pass !== b.pass) return a.pass ? 1 : -1;
      return a.field.localeCompare(b.field);
    });

    sortedDiffs.forEach(diff => {
      const row = document.createElement('tr');
      row.className = diff.pass ? 'pass-row' : 'fail-row';

      const statusBadge = diff.pass
        ? '<span class="status-badge pass">PASS</span>'
        : '<span class="status-badge fail">FAIL</span>';

      const relPct = diff.rel_diff !== null && diff.rel_diff !== undefined
        ? `${(diff.rel_diff * 100).toFixed(2)}%`
        : '-';

      row.innerHTML = `
        <td>${statusBadge}</td>
        <td>${diff.field}</td>
        <td class="numeric">${formatNumber(diff.expected)}</td>
        <td class="numeric">${formatNumber(diff.actual)}</td>
        <td class="numeric">${formatNumber(diff.abs_diff)}</td>
        <td class="numeric">${relPct}</td>
      `;

      diffsBody.appendChild(row);
    });

    diffsDiv.style.display = 'block';
  }
}

/**
 * Format number for display
 */
function formatNumber(value) {
  if (value === null || value === undefined) return '-';
  if (typeof value !== 'number') return value;
  if (Math.abs(value) < 0.01) return value.toExponential(2);
  if (Math.abs(value) >= 1000) return value.toLocaleString('pl-PL', { maximumFractionDigits: 2 });
  return value.toFixed(4);
}

// ============================================
// BASELINE HEALTH (v1.7.0)
// ============================================

/**
 * Baseline health state
 */
const baselineHealthState = {
  packs: [],
  selectedPack: null,
  lastJobId: null,
  lastResult: null,
};

/**
 * Load available packs from GET /api/bess-dispatch/validation/packs
 */
async function loadAvailablePacks() {
  try {
    const response = await fetch('/api/bess-dispatch/validation/packs');
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    baselineHealthState.packs = data.packs || [];

    // Populate select
    const select = document.getElementById('baselineHealthPackSelect');
    if (!select) return;

    // Clear existing options except first
    while (select.options.length > 1) {
      select.remove(1);
    }

    // Add pack options
    for (const packName of baselineHealthState.packs) {
      const option = document.createElement('option');
      option.value = packName;
      option.textContent = packName;
      select.appendChild(option);
    }

    console.log(`[BaselineHealth] Loaded ${baselineHealthState.packs.length} packs`);
  } catch (error) {
    console.error('[BaselineHealth] Failed to load packs:', error);
  }
}

/**
 * Refresh pack list
 */
function refreshPackList() {
  loadAvailablePacks();
}

/**
 * Handle pack selection
 */
function loadPackDetails() {
  const select = document.getElementById('baselineHealthPackSelect');
  const packName = select.value;
  const runBtn = document.getElementById('runBaselineHealthBtn');

  if (!packName) {
    baselineHealthState.selectedPack = null;
    runBtn.disabled = true;
    return;
  }

  baselineHealthState.selectedPack = packName;
  runBtn.disabled = false;
  console.log(`[BaselineHealth] Selected pack: ${packName}`);
}

/**
 * Run baseline health validation
 */
async function runBaselineHealth() {
  const packName = baselineHealthState.selectedPack;
  if (!packName) {
    alert('Wybierz pakiet do walidacji');
    return;
  }

  console.log(`[BaselineHealth] Running validation for pack: ${packName}`);

  // Show results container
  const resultsContainer = document.getElementById('baselineHealthResultsContainer');
  const statusDiv = document.getElementById('baselineHealthStatus');
  const statusIcon = document.getElementById('baselineHealthStatusIcon');
  const statusText = document.getElementById('baselineHealthStatusText');
  const summaryDiv = document.getElementById('baselineHealthSummary');
  const scenariosDiv = document.getElementById('baselineHealthScenarios');
  const actionsDiv = document.getElementById('baselineHealthActions');

  resultsContainer.style.display = 'block';
  statusDiv.className = 'baseline-health-status';
  statusIcon.textContent = '⏳';
  statusText.textContent = 'Uruchamianie walidacji...';
  summaryDiv.style.display = 'none';
  scenariosDiv.style.display = 'none';
  actionsDiv.style.display = 'none';

  try {
    // Call validate-pack job with wait=true
    const response = await fetch('/api/bess-dispatch/jobs/validate-pack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pack: packName, wait: true }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const jobResult = await response.json();
    console.log('[BaselineHealth] Validation result:', jobResult);

    baselineHealthState.lastJobId = jobResult.job_id;
    baselineHealthState.lastResult = jobResult.result;

    // Display results
    displayBaselineHealthResults(jobResult);
  } catch (error) {
    console.error('[BaselineHealth] Validation failed:', error);
    statusDiv.className = 'baseline-health-status failed';
    statusIcon.textContent = '❌';
    statusText.textContent = `Blad: ${error.message}`;
  }
}

/**
 * Display baseline health results
 */
function displayBaselineHealthResults(jobResult) {
  const statusDiv = document.getElementById('baselineHealthStatus');
  const statusIcon = document.getElementById('baselineHealthStatusIcon');
  const statusText = document.getElementById('baselineHealthStatusText');
  const summaryDiv = document.getElementById('baselineHealthSummary');
  const scenariosDiv = document.getElementById('baselineHealthScenarios');
  const actionsDiv = document.getElementById('baselineHealthActions');

  const result = jobResult.result || {};
  const allPassed = result.pass === true;
  const summary = result.summary || {};

  // Update status
  if (allPassed) {
    statusDiv.className = 'baseline-health-status passed';
    statusIcon.textContent = '✅';
    statusText.textContent = 'Wszystkie scenariusze PASSED';
  } else {
    statusDiv.className = 'baseline-health-status failed';
    statusIcon.textContent = '❌';
    statusText.textContent = `${summary.fail || 0} scenariuszy FAILED`;
  }

  // Update summary
  document.getElementById('baselineHealthTotalCount').textContent = summary.total || 0;
  document.getElementById('baselineHealthPassedCount').textContent = summary.pass || 0;
  document.getElementById('baselineHealthFailedCount').textContent = summary.fail || 0;
  document.getElementById('baselineHealthJobId').textContent = jobResult.job_id || '-';
  summaryDiv.style.display = 'block';

  // Populate scenarios table
  const tbody = document.getElementById('baselineHealthScenariosBody');
  tbody.innerHTML = '';

  const scenarios = result.scenarios || [];
  for (const scenario of scenarios) {
    const row = document.createElement('tr');
    row.className = scenario.pass ? 'passed-row' : 'failed-row';
    // v1.8.0: Add click handler for drilldown
    row.onclick = () => openScenarioDrilldown(scenario);
    row.title = 'Kliknij aby zobaczyc szczegoly';

    const statusCell = document.createElement('td');
    statusCell.textContent = scenario.pass ? '✅' : '❌';
    row.appendChild(statusCell);

    const nameCell = document.createElement('td');
    nameCell.textContent = scenario.name || '-';
    row.appendChild(nameCell);

    const mismatchCell = document.createElement('td');
    mismatchCell.textContent = scenario.mismatch_count || 0;
    row.appendChild(mismatchCell);

    const errorCell = document.createElement('td');
    errorCell.textContent = scenario.error || '-';
    errorCell.style.maxWidth = '300px';
    errorCell.style.overflow = 'hidden';
    errorCell.style.textOverflow = 'ellipsis';
    errorCell.title = scenario.error || '';
    row.appendChild(errorCell);

    tbody.appendChild(row);
  }

  scenariosDiv.style.display = 'block';
  actionsDiv.style.display = 'block';
}

/**
 * Export baseline health CSV
 */
async function exportBaselineHealthCSV() {
  const jobId = baselineHealthState.lastJobId;
  if (!jobId) {
    alert('Brak wynikow do eksportu');
    return;
  }

  try {
    const response = await fetch(`/api/bess-dispatch/jobs/${jobId}/validate-pack/export/csv`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `validate_${baselineHealthState.selectedPack}_${jobId.substring(0, 8)}_summary.csv`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    console.error('[BaselineHealth] CSV export failed:', error);
    alert('Eksport CSV nie powiodl sie: ' + error.message);
  }
}

/**
 * Export baseline health ZIP
 */
async function exportBaselineHealthZIP() {
  const jobId = baselineHealthState.lastJobId;
  if (!jobId) {
    alert('Brak wynikow do eksportu');
    return;
  }

  try {
    const response = await fetch(`/api/bess-dispatch/jobs/${jobId}/validate-pack/export/zip`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `validate_${baselineHealthState.selectedPack}_${jobId.substring(0, 8)}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    console.error('[BaselineHealth] ZIP export failed:', error);
    alert('Eksport ZIP nie powiodl sie: ' + error.message);
  }
}

// =============================================================================
// SCENARIO DRILLDOWN MODAL (v1.8.0)
// =============================================================================

// State for scenario drilldown
let scenarioDrilldownState = {
  currentScenario: null,
  currentRunId: null,
};

/**
 * Open scenario drilldown modal
 */
function openScenarioDrilldown(scenario) {
  scenarioDrilldownState.currentScenario = scenario;
  scenarioDrilldownState.currentRunId = scenario.run_id || null;

  // Update title
  document.getElementById('scenarioDrilldownTitle').textContent = `Scenariusz: ${scenario.name || '-'}`;

  // Update status
  const statusDiv = document.getElementById('scenarioDrilldownStatus');
  if (scenario.pass) {
    statusDiv.className = 'drilldown-status passed';
    statusDiv.innerHTML = '<span class="status-icon">✅</span><span class="status-text">PASSED</span>';
  } else {
    statusDiv.className = 'drilldown-status failed';
    statusDiv.innerHTML = `<span class="status-icon">❌</span><span class="status-text">FAILED - ${scenario.mismatch_count || 0} mismatches</span>`;
  }

  // Populate top mismatches
  const mismatchesSection = document.getElementById('topMismatchesSection');
  const mismatchesBody = document.getElementById('topMismatchesBody');
  mismatchesBody.innerHTML = '';

  const topMismatches = scenario.top_mismatches || [];
  if (topMismatches.length > 0) {
    for (const m of topMismatches) {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${m.field || '-'}</td>
        <td>${formatNumber(m.expected)}</td>
        <td>${formatNumber(m.actual)}</td>
        <td>${formatNumber(m.abs_diff)}</td>
        <td>${m.rel_diff_pct != null ? m.rel_diff_pct.toFixed(1) + '%' : '-'}</td>
      `;
      mismatchesBody.appendChild(row);
    }
    mismatchesSection.style.display = 'block';
  } else {
    mismatchesSection.style.display = 'none';
  }

  // Populate debug summary
  const debugSection = document.getElementById('debugSummarySection');
  const debugGrid = document.getElementById('debugEventsGrid');
  debugGrid.innerHTML = '';

  const debugSummary = scenario.debug_summary || null;
  if (debugSummary) {
    const events = [
      { label: 'Steps', value: debugSummary.steps || 0, key: 'steps' },
      { label: 'Export Limited Steps', value: debugSummary.export_limited_steps || 0, key: 'export_limited_steps', warnIfPositive: true },
      { label: 'Export Limited MWh', value: debugSummary.export_limited_mwh || 0, key: 'export_limited_mwh', warnIfPositive: true },
      { label: 'Import Limited Steps', value: debugSummary.import_limited_steps || 0, key: 'import_limited_steps', warnIfPositive: true },
      { label: 'PV Curtail Steps', value: debugSummary.pv_curtail_steps || 0, key: 'pv_curtail_steps', warnIfPositive: true },
      { label: 'PV Curtail MWh', value: debugSummary.pv_curtail_mwh || 0, key: 'pv_curtail_mwh', warnIfPositive: true },
      { label: 'Unserved Load Steps', value: debugSummary.unserved_load_steps || 0, key: 'unserved_load_steps', errorIfPositive: true },
      { label: 'Unserved Load kWh', value: debugSummary.unserved_load_kwh || 0, key: 'unserved_load_kwh', errorIfPositive: true },
    ];

    for (const e of events) {
      const item = document.createElement('div');
      let className = 'debug-event-item';
      if (e.errorIfPositive && e.value > 0) className += ' error';
      else if (e.warnIfPositive && e.value > 0) className += ' warning';
      item.className = className;
      item.innerHTML = `
        <div class="event-label">${e.label}</div>
        <div class="event-value">${formatNumber(e.value)}</div>
      `;
      debugGrid.appendChild(item);
    }
    debugSection.style.display = 'block';
  } else {
    debugSection.style.display = 'none';
  }

  // Enable/disable repro download
  const reproBtn = document.getElementById('downloadReproBtn');
  if (scenarioDrilldownState.currentRunId) {
    reproBtn.disabled = false;
  } else {
    reproBtn.disabled = true;
  }

  // Show modal
  document.getElementById('scenarioDrilldownModal').style.display = 'flex';
}

/**
 * Close scenario drilldown modal
 */
function closeScenarioDrilldownModal(event) {
  // If clicked on overlay (not content), close
  if (event && event.target.id !== 'scenarioDrilldownModal') return;
  document.getElementById('scenarioDrilldownModal').style.display = 'none';
}

/**
 * Download scenario repro bundle
 */
async function downloadScenarioRepro() {
  const runId = scenarioDrilldownState.currentRunId;
  if (!runId) {
    alert('Brak run_id dla tego scenariusza');
    return;
  }

  try {
    const response = await fetch(`/runs/${runId}/repro.zip`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `repro_${runId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    console.error('[Drilldown] Repro download failed:', error);
    alert('Pobieranie repro.zip nie powiodlo sie: ' + error.message);
  }
}

/**
 * Format number for display
 */
function formatNumber(val) {
  if (val === null || val === undefined) return '-';
  if (typeof val === 'number') {
    return val.toLocaleString('pl-PL', { maximumFractionDigits: 4 });
  }
  return String(val);
}

// =============================================================================
// BACKEND VERSION BADGE (v1.8.0)
// =============================================================================

/**
 * Fetch backend version and display in header
 */
async function loadBackendVersion() {
  try {
    const response = await fetch('/api/bess-dispatch/version');
    if (!response.ok) {
      console.warn('[Version] Failed to fetch backend version:', response.status);
      return;
    }
    const data = await response.json();
    displayBackendVersion(data);
  } catch (error) {
    console.warn('[Version] Failed to fetch backend version:', error);
  }
}

/**
 * Display backend version in header badge
 * @param {object} versionInfo - Version info from /version endpoint
 */
function displayBackendVersion(versionInfo) {
  const badge = document.getElementById('backendVersion');
  if (!badge) return;

  // Format: "Backend: schema_version (git_sha short)"
  const shortSha = (versionInfo.git_sha || 'unknown').substring(0, 7);
  const schemaVer = versionInfo.schema_version || '?';

  badge.textContent = `Backend: v${schemaVer} (${shortSha})`;
  badge.title = `Build: ${versionInfo.build_time_utc || 'unknown'}\nAssumptions: ${versionInfo.assumptions_version || 'unknown'}`;
  badge.style.display = 'inline';
}

/**
 * Map version response to display format
 * @param {object} versionResponse - Raw version response
 * @returns {object} Mapped version for display
 */
function mapVersionResponse(versionResponse) {
  return {
    service: versionResponse.service || 'unknown',
    gitSha: versionResponse.git_sha || 'unknown',
    gitShaShort: (versionResponse.git_sha || 'unknown').substring(0, 7),
    buildTime: versionResponse.build_time_utc || 'unknown',
    schemaVersion: versionResponse.schema_version || 'unknown',
    assumptionsVersion: versionResponse.assumptions_version || 'unknown',
    displayText: `v${versionResponse.schema_version || '?'} (${(versionResponse.git_sha || 'unknown').substring(0, 7)})`,
  };
}

// Export version functions (v1.8.0)
window.loadBackendVersion = loadBackendVersion;
window.displayBackendVersion = displayBackendVersion;
window.mapVersionResponse = mapVersionResponse;

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  loadBackendVersion();  // v1.8.0: Load backend version
  loadAvailableScenarios();
  loadAvailablePacks();  // v1.7.0: Load packs for Baseline Health
});

// Export Validation functions
window.loadAvailableScenarios = loadAvailableScenarios;
window.refreshScenarioList = refreshScenarioList;
window.loadScenarioDetails = loadScenarioDetails;
window.runScenarioValidation = runScenarioValidation;

// Export Baseline Health functions (v1.7.0)
window.loadAvailablePacks = loadAvailablePacks;
window.refreshPackList = refreshPackList;
window.loadPackDetails = loadPackDetails;
window.runBaselineHealth = runBaselineHealth;
window.exportBaselineHealthCSV = exportBaselineHealthCSV;
window.exportBaselineHealthZIP = exportBaselineHealthZIP;

console.log('[BESS] bess.js v3.30 - v2.0.0 Pricing Engine Tab');

// =============================================================================
// v2.0.0: Pricing Engine Functions
// =============================================================================

// Store price override data
let priceOverrideData = null;

/**
 * Update pricing display from sizing response
 */
function updatePricingDisplay(response) {
  const variants = response.variants || [];
  const recommended = variants.find(v => v.is_recommended);

  if (!recommended) return;

  // Update pricing mode label
  const modeLabel = document.getElementById('pricingModeLabel');
  const priceHashShort = document.getElementById('priceHashShort');

  if (recommended.pricing_mode) {
    modeLabel.textContent = recommended.pricing_mode.toUpperCase();
    modeLabel.style.background = recommended.pricing_mode === 'override' ? '#ff9800' : '#4caf50';
  }

  if (recommended.price_hash) {
    priceHashShort.textContent = recommended.price_hash.substring(0, 12) + '...';
    priceHashShort.title = recommended.price_hash;
  }

  // Update price values from price_timeseries
  const priceTseries = recommended.price_timeseries;
  if (priceTseries) {
    const importPrices = priceTseries.import_price_pln_per_mwh || [];
    const exportPrices = priceTseries.export_price_pln_per_mwh || [];

    // Calculate averages
    const avgImport = importPrices.length > 0
      ? importPrices.reduce((a, b) => a + b, 0) / importPrices.length
      : 0;
    const avgExport = exportPrices.length > 0
      ? exportPrices.reduce((a, b) => a + b, 0) / exportPrices.length
      : 0;

    document.getElementById('priceImportValue').textContent = avgImport.toFixed(0) + ' PLN/MWh';
    document.getElementById('priceExportValue').textContent = avgExport.toFixed(0) + ' PLN/MWh';
  }

  // Update cost buckets from ledger_timeseries
  const ledgerTs = recommended.ledger_timeseries;
  if (ledgerTs) {
    updateCostBucketsChart(ledgerTs);
  }
}

/**
 * Update cost buckets display
 */
function updateCostBucketsChart(ledgerTs) {
  const container = document.getElementById('costBucketsChart');
  if (!container) return;

  const buckets = [
    { name: 'Import', value: ledgerTs.sum_import_cost_pln || 0, color: '#d32f2f' },
    { name: 'Export', value: ledgerTs.sum_export_revenue_pln || 0, color: '#388e3c' },
    { name: 'Opłaty', value: ledgerTs.sum_other_fees_pln || 0, color: '#ff9800' },
    { name: 'Kary', value: ledgerTs.sum_unserved_penalty_pln || 0, color: '#9c27b0' },
  ].filter(b => b.value !== 0);

  const total = buckets.reduce((sum, b) => sum + Math.abs(b.value), 0);

  container.innerHTML = buckets.map(b => {
    const pct = total > 0 ? (Math.abs(b.value) / total * 100).toFixed(1) : 0;
    const sign = b.name === 'Export' ? '+' : '';
    return `
      <div style="background:${b.color};color:white;padding:8px 12px;border-radius:4px;font-size:12px;">
        <div style="font-weight:600;">${b.name}</div>
        <div>${sign}${b.value.toFixed(2)} PLN</div>
        <div style="font-size:10px;opacity:0.8;">${pct}%</div>
      </div>
    `;
  }).join('');

  if (buckets.length === 0) {
    container.innerHTML = '<span style="color:#999;font-size:11px;">Brak danych kosztowych</span>';
  }
}

/**
 * Handle CSV price override upload
 */
function handlePriceOverrideCsv(input) {
  const file = input.files[0];
  if (!file) return;

  const statusDiv = document.getElementById('priceOverrideStatus');
  const clearBtn = document.getElementById('clearPriceOverride');

  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const lines = e.target.result.split('\n').filter(l => l.trim());
      const header = lines[0].toLowerCase();

      // Parse CSV - expect import_price, export_price columns
      const importPrices = [];
      const exportPrices = [];

      for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',');
        if (parts.length >= 2) {
          importPrices.push(parseFloat(parts[0]) || 0);
          exportPrices.push(parseFloat(parts[1]) || 0);
        }
      }

      if (importPrices.length === 0) {
        statusDiv.innerHTML = '<span style="color:#d32f2f;">❌ Błąd: Brak danych w CSV</span>';
        return;
      }

      priceOverrideData = {
        import_price_pln_per_mwh: importPrices,
        export_price_pln_per_mwh: exportPrices,
        step_minutes: 60,  // Default to hourly
        steps: importPrices.length,
        timezone: 'Europe/Warsaw',
        period_start: '2025-01-01T00:00:00',
        period_end: `2025-01-01T${(importPrices.length - 1).toString().padStart(2, '0')}:00:00`,
      };

      statusDiv.innerHTML = `<span style="color:#388e3c;">✅ Załadowano ${importPrices.length} kroków czasowych</span>`;
      clearBtn.style.display = 'inline-block';

      // Update mode label
      const modeLabel = document.getElementById('pricingModeLabel');
      modeLabel.textContent = 'OVERRIDE (pending)';
      modeLabel.style.background = '#ff9800';

    } catch (err) {
      statusDiv.innerHTML = `<span style="color:#d32f2f;">❌ Błąd parsowania: ${err.message}</span>`;
    }
  };
  reader.readAsText(file);
}

/**
 * Clear price override
 */
function clearPriceOverride() {
  priceOverrideData = null;
  document.getElementById('priceOverrideCsv').value = '';
  document.getElementById('priceOverrideStatus').innerHTML = '';
  document.getElementById('clearPriceOverride').style.display = 'none';

  const modeLabel = document.getElementById('pricingModeLabel');
  modeLabel.textContent = 'GENERATED';
  modeLabel.style.background = '#4caf50';
}

/**
 * Get price override for sizing request
 */
function getPriceOverrideForRequest() {
  return priceOverrideData;
}

// Export pricing functions
window.updatePricingDisplay = updatePricingDisplay;
window.updateCostBucketsChart = updateCostBucketsChart;
window.handlePriceOverrideCsv = handlePriceOverrideCsv;
window.clearPriceOverride = clearPriceOverride;
window.getPriceOverrideForRequest = getPriceOverrideForRequest;

// =============================================================================
// v2.1.0: Tariff Selector + Pricing Preview Functions
// =============================================================================

// Current tariff mode: 'preset', 'schedule', 'override'
let currentTariffMode = 'preset';

// Cached tariff presets from API
let cachedTariffPresets = [];

// Current preview result for CSV export
let currentPricePreviewResult = null;

/**
 * Initialize tariff selector on page load
 */
function initTariffSelector() {
  // Generate schedule input tables
  generateScheduleTables();
  // Load presets from API
  refreshTariffPresets();
}

/**
 * Select tariff mode (preset/schedule/override)
 */
function selectTariffMode(mode) {
  currentTariffMode = mode;

  // Update tab styles
  const tabs = ['preset', 'schedule', 'override'];
  tabs.forEach(t => {
    const tab = document.getElementById('tariffTab' + t.charAt(0).toUpperCase() + t.slice(1));
    const panel = document.getElementById('tariffPanel' + t.charAt(0).toUpperCase() + t.slice(1));
    if (t === mode) {
      tab.style.background = '#1976d2';
      tab.style.color = 'white';
      panel.style.display = 'block';
    } else {
      tab.style.background = '#e0e0e0';
      tab.style.color = '#333';
      panel.style.display = 'none';
    }
  });
}

/**
 * Refresh tariff presets from API
 */
async function refreshTariffPresets() {
  const select = document.getElementById('tariffPresetSelect');
  select.innerHTML = '<option value="">Ladowanie...</option>';

  try {
    const response = await fetch(getApiUrl('/api/bess-dispatch/tariffs'));
    if (!response.ok) {
      throw new Error('Failed to fetch tariffs');
    }
    const data = await response.json();
    cachedTariffPresets = data.presets || [];

    select.innerHTML = '<option value="">-- Wybierz preset --</option>';
    cachedTariffPresets.forEach(preset => {
      const option = document.createElement('option');
      option.value = preset.id;
      option.textContent = preset.label;
      select.appendChild(option);
    });

    console.log('[BESS] Loaded', cachedTariffPresets.length, 'tariff presets');
  } catch (err) {
    console.error('[BESS] Failed to load tariff presets:', err);
    select.innerHTML = '<option value="">Blad ladowania</option>';
  }
}

/**
 * Handle tariff preset selection change
 */
function onTariffPresetChange() {
  const select = document.getElementById('tariffPresetSelect');
  const infoDiv = document.getElementById('tariffPresetInfo');
  const presetId = select.value;

  if (!presetId) {
    infoDiv.style.display = 'none';
    return;
  }

  const preset = cachedTariffPresets.find(p => p.id === presetId);
  if (preset) {
    let html = `<strong>${preset.label}</strong><br>`;
    if (preset.description) {
      html += `${preset.description}<br>`;
    }
    if (preset.import_price_pln_per_mwh !== null) {
      html += `Import: ${preset.import_price_pln_per_mwh} PLN/MWh<br>`;
    }
    if (preset.weekday_peak_price_pln_per_mwh) {
      html += `Peak: ${preset.weekday_peak_price_pln_per_mwh} PLN/MWh, Off-peak: ${preset.weekday_offpeak_price_pln_per_mwh} PLN/MWh`;
    }
    infoDiv.innerHTML = html;
    infoDiv.style.display = 'block';
  }
}

/**
 * Generate 24-hour schedule input tables
 */
function generateScheduleTables() {
  const weekdayBody = document.getElementById('scheduleWeekdayBody');
  const weekendBody = document.getElementById('scheduleWeekendBody');

  if (!weekdayBody || !weekendBody) return;

  // Default prices
  const defaultImport = 500;
  const defaultExport = 0;

  for (let h = 0; h < 24; h++) {
    // Weekday row
    const wdRow = document.createElement('tr');
    wdRow.innerHTML = `
      <td style="padding:2px;border:1px solid #a5d6a7;text-align:center;">${h.toString().padStart(2,'0')}</td>
      <td style="padding:2px;border:1px solid #a5d6a7;">
        <input type="number" id="wdImport${h}" value="${defaultImport}" style="width:50px;font-size:10px;padding:2px;">
      </td>
      <td style="padding:2px;border:1px solid #a5d6a7;">
        <input type="number" id="wdExport${h}" value="${defaultExport}" style="width:50px;font-size:10px;padding:2px;">
      </td>
    `;
    weekdayBody.appendChild(wdRow);

    // Weekend row
    const weRow = document.createElement('tr');
    weRow.innerHTML = `
      <td style="padding:2px;border:1px solid #a5d6a7;text-align:center;">${h.toString().padStart(2,'0')}</td>
      <td style="padding:2px;border:1px solid #a5d6a7;">
        <input type="number" id="weImport${h}" value="${defaultImport}" style="width:50px;font-size:10px;padding:2px;">
      </td>
      <td style="padding:2px;border:1px solid #a5d6a7;">
        <input type="number" id="weExport${h}" value="${defaultExport}" style="width:50px;font-size:10px;padding:2px;">
      </td>
    `;
    weekendBody.appendChild(weRow);
  }
}

/**
 * Get tariff schedule from UI inputs
 */
function getTariffScheduleFromUI() {
  const weekdayImport = [];
  const weekdayExport = [];
  const weekendImport = [];
  const weekendExport = [];

  for (let h = 0; h < 24; h++) {
    weekdayImport.push(parseFloat(document.getElementById(`wdImport${h}`).value) || 0);
    weekdayExport.push(parseFloat(document.getElementById(`wdExport${h}`).value) || 0);
    weekendImport.push(parseFloat(document.getElementById(`weImport${h}`).value) || 0);
    weekendExport.push(parseFloat(document.getElementById(`weExport${h}`).value) || 0);
  }

  const holidaysInput = document.getElementById('scheduleHolidays').value.trim();
  const holidayDates = holidaysInput ? holidaysInput.split(',').map(d => d.trim()).filter(d => d) : [];

  return {
    weekday_import_price_pln_per_mwh: weekdayImport,
    weekend_import_price_pln_per_mwh: weekendImport,
    weekday_export_price_pln_per_mwh: weekdayExport,
    weekend_export_price_pln_per_mwh: weekendExport,
    weekday_other_fees_pln_per_mwh: new Array(24).fill(0),
    weekend_other_fees_pln_per_mwh: new Array(24).fill(0),
    holiday_dates: holidayDates,
    timezone: 'Europe/Warsaw',
  };
}

/**
 * Preview prices using the selected tariff configuration
 */
async function previewPrices() {
  const btn = document.getElementById('previewPricesBtn');
  btn.disabled = true;
  btn.textContent = 'Ladowanie...';

  try {
    // Build request based on current mode
    const request = {
      interval_minutes: 60,
      timezone: 'Europe/Warsaw',
      period_start: '2025-01-01T00:00:00',
      period_end: '2025-01-07T23:00:00',  // 7 days = 168 hours
    };

    if (currentTariffMode === 'preset') {
      const presetId = document.getElementById('tariffPresetSelect').value;
      if (!presetId) {
        alert('Wybierz preset taryfowy');
        return;
      }
      request.tariff_preset = presetId;
    } else if (currentTariffMode === 'schedule') {
      request.tariff_schedule = getTariffScheduleFromUI();
    } else if (currentTariffMode === 'override') {
      if (!priceOverrideData) {
        alert('Zaladuj plik CSV z cenami');
        return;
      }
      request.price_timeseries_override = priceOverrideData;
    }

    const response = await fetch(getApiUrl('/api/bess-dispatch/pricing/preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`API error: ${errText}`);
    }

    const result = await response.json();
    currentPricePreviewResult = result;

    // Update UI with results
    updatePricePreviewDisplay(result);

    console.log('[BESS] Price preview result:', result);
  } catch (err) {
    console.error('[BESS] Price preview failed:', err);
    alert('Blad podgladu cen: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Preview Prices';
  }
}

/**
 * Update price preview display from API result
 */
function updatePricePreviewDisplay(result) {
  const priceTseries = result.price_timeseries;
  if (!priceTseries) return;

  const importPrices = priceTseries.import_price_pln_per_mwh || [];
  const exportPrices = priceTseries.export_price_pln_per_mwh || [];
  const otherFees = priceTseries.other_fees_pln_per_mwh || [];

  // Update mode label
  const modeLabel = document.getElementById('pricingModeLabel');
  const mode = result.pricing_mode || 'generated';
  modeLabel.textContent = mode.toUpperCase();
  if (mode === 'preset') {
    modeLabel.style.background = '#1976d2';
  } else if (mode === 'schedule') {
    modeLabel.style.background = '#2e7d32';
  } else if (mode === 'override') {
    modeLabel.style.background = '#ff9800';
  } else {
    modeLabel.style.background = '#4caf50';
  }

  // Update price hash
  const priceHashShort = document.getElementById('priceHashShort');
  if (result.price_hash) {
    priceHashShort.textContent = result.price_hash.substring(0, 12) + '...';
    priceHashShort.title = result.price_hash;
  }

  // Calculate averages
  const avgImport = importPrices.length > 0
    ? importPrices.reduce((a, b) => a + b, 0) / importPrices.length
    : 0;
  const avgExport = exportPrices.length > 0
    ? exportPrices.reduce((a, b) => a + b, 0) / exportPrices.length
    : 0;

  document.getElementById('priceImportValue').textContent = avgImport.toFixed(0) + ' PLN/MWh';
  document.getElementById('priceExportValue').textContent = avgExport.toFixed(0) + ' PLN/MWh';

  // Update summary stats
  const statsDiv = document.getElementById('priceSummaryStats');
  if (importPrices.length > 0) {
    document.getElementById('priceMinValue').textContent = Math.min(...importPrices).toFixed(0);
    document.getElementById('priceMaxValue').textContent = Math.max(...importPrices).toFixed(0);
    document.getElementById('priceStepsValue').textContent = importPrices.length;
    statsDiv.style.display = 'block';
  }

  // Update preview table (show first 48 steps)
  const tableContainer = document.getElementById('pricePreviewTableContainer');
  const tableBody = document.getElementById('pricePreviewTableBody');
  tableBody.innerHTML = '';

  const maxRows = Math.min(48, importPrices.length);
  for (let i = 0; i < maxRows; i++) {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td style="padding:2px 4px;border:1px solid #ccc;text-align:center;">${i}</td>
      <td style="padding:2px 4px;border:1px solid #ccc;text-align:right;">${importPrices[i].toFixed(2)}</td>
      <td style="padding:2px 4px;border:1px solid #ccc;text-align:right;">${exportPrices[i].toFixed(2)}</td>
      <td style="padding:2px 4px;border:1px solid #ccc;text-align:right;">${(otherFees[i] || 0).toFixed(2)}</td>
    `;
    tableBody.appendChild(row);
  }
  tableContainer.style.display = 'block';

  // Show export button
  document.getElementById('exportPricesCsvBtn').style.display = 'inline-block';
}

/**
 * Export current price preview to CSV
 */
function exportPricesCsv() {
  if (!currentPricePreviewResult || !currentPricePreviewResult.price_timeseries) {
    alert('Brak danych do eksportu');
    return;
  }

  const priceTseries = currentPricePreviewResult.price_timeseries;
  const importPrices = priceTseries.import_price_pln_per_mwh || [];
  const exportPrices = priceTseries.export_price_pln_per_mwh || [];
  const otherFees = priceTseries.other_fees_pln_per_mwh || [];

  // Build CSV content
  let csv = 'step,import_price_pln_per_mwh,export_price_pln_per_mwh,other_fees_pln_per_mwh\n';
  for (let i = 0; i < importPrices.length; i++) {
    csv += `${i},${importPrices[i]},${exportPrices[i]},${otherFees[i] || 0}\n`;
  }

  // Create download link
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `price_timeseries_${currentPricePreviewResult.pricing_mode || 'export'}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Get current tariff configuration for sizing request
 */
function getTariffConfigForRequest() {
  if (currentTariffMode === 'preset') {
    const presetId = document.getElementById('tariffPresetSelect').value;
    return presetId ? { tariff_preset: presetId } : null;
  } else if (currentTariffMode === 'schedule') {
    return { tariff_schedule: getTariffScheduleFromUI() };
  } else if (currentTariffMode === 'override') {
    return priceOverrideData ? { price_timeseries_override: priceOverrideData } : null;
  }
  return null;
}

// Export v2.1.0 tariff functions
window.initTariffSelector = initTariffSelector;
window.selectTariffMode = selectTariffMode;
window.refreshTariffPresets = refreshTariffPresets;
window.onTariffPresetChange = onTariffPresetChange;
window.previewPrices = previewPrices;
window.exportPricesCsv = exportPricesCsv;
window.getTariffConfigForRequest = getTariffConfigForRequest;

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
  initTariffSelector();
});

// =============================================================================
// v2.2.0: DISPATCH TRACE SECTION
// =============================================================================

/**
 * Current battery trace data from sizing result
 */
let currentBatteryTrace = null;
let socTimeseriesChart = null;
let powerTimeseriesChart = null;

/**
 * Update dispatch trace display with battery trace data
 * @param {object} batteryTrace - BatteryTraceTimeseries from API
 * @param {object} cycleSummary - Cycle summary data (optional)
 * @param {object} invariants - Invariants check result (optional)
 */
function updateDispatchTraceDisplay(batteryTrace, cycleSummary, invariants) {
  console.log('[DispatchTrace] Updating display:', { batteryTrace, cycleSummary, invariants });

  currentBatteryTrace = batteryTrace;

  // Update SOC chart
  if (batteryTrace && batteryTrace.soc_kwh && batteryTrace.soc_kwh.length > 0) {
    updateSocChart(batteryTrace);
    updatePowerChart(batteryTrace);

    // Enable export button
    const exportBtn = document.getElementById('exportTraceBtn');
    if (exportBtn) exportBtn.disabled = false;

    // Hide placeholders, show charts
    document.getElementById('socChartPlaceholder').style.display = 'none';
    document.getElementById('socTimeseriesChart').style.display = 'block';
    document.getElementById('powerChartPlaceholder').style.display = 'none';
    document.getElementById('powerTimeseriesChart').style.display = 'block';
  } else {
    // Show placeholders
    document.getElementById('socChartPlaceholder').style.display = 'flex';
    document.getElementById('socTimeseriesChart').style.display = 'none';
    document.getElementById('powerChartPlaceholder').style.display = 'flex';
    document.getElementById('powerTimeseriesChart').style.display = 'none';

    const exportBtn = document.getElementById('exportTraceBtn');
    if (exportBtn) exportBtn.disabled = true;
  }

  // Update cycle summary
  updateCycleSummaryDisplay(cycleSummary);

  // Update invariants
  updateInvariantsDisplay(invariants);
}

/**
 * Update SOC timeseries chart
 */
function updateSocChart(trace) {
  const canvas = document.getElementById('socTimeseriesChart');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing chart
  if (socTimeseriesChart) {
    socTimeseriesChart.destroy();
    socTimeseriesChart = null;
  }

  const steps = trace.steps || trace.soc_kwh.length;
  const labels = Array.from({ length: steps }, (_, i) => i);

  // Downsample for large datasets
  const maxPoints = 500;
  let displayLabels = labels;
  let displaySoc = trace.soc_kwh;

  if (steps > maxPoints) {
    const step = Math.ceil(steps / maxPoints);
    displayLabels = labels.filter((_, i) => i % step === 0);
    displaySoc = trace.soc_kwh.filter((_, i) => i % step === 0);
  }

  socTimeseriesChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: displayLabels,
      datasets: [{
        label: 'SOC (kWh)',
        data: displaySoc,
        borderColor: '#4caf50',
        backgroundColor: 'rgba(76, 175, 80, 0.1)',
        fill: true,
        tension: 0.1,
        pointRadius: 0,
      }, {
        label: 'Capacity',
        data: displayLabels.map(() => trace.battery_energy_kwh || 0),
        borderColor: '#ff9800',
        borderDash: [5, 5],
        fill: false,
        pointRadius: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top' },
        title: { display: false }
      },
      scales: {
        x: {
          title: { display: true, text: 'Step (hour)' },
          ticks: { maxTicksLimit: 12 }
        },
        y: {
          title: { display: true, text: 'SOC (kWh)' },
          min: 0
        }
      }
    }
  });
}

/**
 * Update power timeseries chart (charge/discharge)
 */
function updatePowerChart(trace) {
  const canvas = document.getElementById('powerTimeseriesChart');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');

  // Destroy existing chart
  if (powerTimeseriesChart) {
    powerTimeseriesChart.destroy();
    powerTimeseriesChart = null;
  }

  const steps = trace.steps || trace.charge_kw.length;
  const labels = Array.from({ length: steps }, (_, i) => i);

  // Downsample for large datasets
  const maxPoints = 500;
  let displayLabels = labels;
  let displayCharge = trace.charge_kw;
  let displayDischarge = trace.discharge_kw;

  if (steps > maxPoints) {
    const step = Math.ceil(steps / maxPoints);
    displayLabels = labels.filter((_, i) => i % step === 0);
    displayCharge = trace.charge_kw.filter((_, i) => i % step === 0);
    displayDischarge = trace.discharge_kw.filter((_, i) => i % step === 0);
  }

  powerTimeseriesChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: displayLabels,
      datasets: [{
        label: 'Charge (kW)',
        data: displayCharge,
        borderColor: '#2196f3',
        backgroundColor: 'rgba(33, 150, 243, 0.1)',
        fill: true,
        tension: 0.1,
        pointRadius: 0,
      }, {
        label: 'Discharge (kW)',
        data: displayDischarge.map(v => -v), // Show as negative
        borderColor: '#f44336',
        backgroundColor: 'rgba(244, 67, 54, 0.1)',
        fill: true,
        tension: 0.1,
        pointRadius: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top' },
        title: { display: false }
      },
      scales: {
        x: {
          title: { display: true, text: 'Step (hour)' },
          ticks: { maxTicksLimit: 12 }
        },
        y: {
          title: { display: true, text: 'Power (kW)' }
        }
      }
    }
  });
}

/**
 * Update cycle summary display
 */
function updateCycleSummaryDisplay(cycleSummary) {
  const totalEfcEl = document.getElementById('cycleTotalEfc');
  const avgDailyEl = document.getElementById('cycleAvgDailyEfc');
  const maxDailyEl = document.getElementById('cycleMaxDailyEfc');
  const throughputEl = document.getElementById('cycleThroughputMwh');
  const warningEl = document.getElementById('cycleLimitWarning');
  const warningDaysEl = document.getElementById('cycleLimitDays');

  if (cycleSummary) {
    totalEfcEl.textContent = (cycleSummary.efc_total || 0).toFixed(1);
    avgDailyEl.textContent = (cycleSummary.avg_daily_efc || 0).toFixed(2);
    maxDailyEl.textContent = (cycleSummary.max_daily_efc || 0).toFixed(2);
    throughputEl.textContent = ((cycleSummary.total_throughput_kwh || 0) / 1000).toFixed(1) + ' MWh';

    if (cycleSummary.days_exceeding_limit && cycleSummary.days_exceeding_limit > 0) {
      warningEl.style.display = 'block';
      warningDaysEl.textContent = cycleSummary.days_exceeding_limit;
    } else {
      warningEl.style.display = 'none';
    }
  } else {
    totalEfcEl.textContent = '-';
    avgDailyEl.textContent = '-';
    maxDailyEl.textContent = '-';
    throughputEl.textContent = '- MWh';
    warningEl.style.display = 'none';
  }
}

/**
 * Update invariants status display
 */
function updateInvariantsDisplay(invariants) {
  const socBoundsEl = document.getElementById('invariantSocBounds');
  const powerLimitsEl = document.getElementById('invariantPowerLimits');
  const noSimultaneousEl = document.getElementById('invariantNoSimultaneous');
  const energyBalanceEl = document.getElementById('invariantEnergyBalance');
  const allOkEl = document.getElementById('invariantsAllOk');
  const violationsEl = document.getElementById('invariantsViolations');
  const violationCountEl = document.getElementById('invariantsViolationCount');

  if (invariants) {
    // SOC bounds
    if (invariants.soc_bounds_ok) {
      socBoundsEl.textContent = '✅ OK';
      socBoundsEl.style.color = '#2e7d32';
    } else {
      socBoundsEl.textContent = '❌ FAIL';
      socBoundsEl.style.color = '#c62828';
    }

    // Power limits
    if (invariants.power_limits_ok) {
      powerLimitsEl.textContent = '✅ OK';
      powerLimitsEl.style.color = '#2e7d32';
    } else {
      powerLimitsEl.textContent = '❌ FAIL';
      powerLimitsEl.style.color = '#c62828';
    }

    // No simultaneous
    if (invariants.no_simultaneous_ok) {
      noSimultaneousEl.textContent = '✅ OK';
      noSimultaneousEl.style.color = '#2e7d32';
    } else {
      noSimultaneousEl.textContent = '❌ FAIL';
      noSimultaneousEl.style.color = '#c62828';
    }

    // Energy balance
    if (invariants.energy_balance_ok) {
      energyBalanceEl.textContent = '✅ OK';
      energyBalanceEl.style.color = '#2e7d32';
    } else {
      energyBalanceEl.textContent = '⚠️ WARN';
      energyBalanceEl.style.color = '#ff9800';
    }

    // Overall status
    if (invariants.all_ok) {
      allOkEl.style.display = 'block';
      violationsEl.style.display = 'none';
    } else {
      allOkEl.style.display = 'none';
      violationsEl.style.display = 'block';
      violationCountEl.textContent = invariants.violations_count || 0;
    }
  } else {
    socBoundsEl.textContent = '-';
    powerLimitsEl.textContent = '-';
    noSimultaneousEl.textContent = '-';
    energyBalanceEl.textContent = '-';
    socBoundsEl.style.color = '#666';
    powerLimitsEl.style.color = '#666';
    noSimultaneousEl.style.color = '#666';
    energyBalanceEl.style.color = '#666';
    allOkEl.style.display = 'none';
    violationsEl.style.display = 'none';
  }
}

/**
 * Export battery trace to CSV
 */
function exportBatteryTrace() {
  if (!currentBatteryTrace) {
    alert('Brak danych battery trace do eksportu');
    return;
  }

  const trace = currentBatteryTrace;
  const steps = trace.steps || trace.soc_kwh.length;

  // Build CSV
  let csv = 'step,soc_kwh,charge_kw,discharge_kw,charge_from_pv_kw,charge_from_grid_kw,discharge_to_load_kw,discharge_to_grid_kw\n';

  for (let i = 0; i < steps; i++) {
    csv += `${i},${trace.soc_kwh[i] || 0},${trace.charge_kw[i] || 0},${trace.discharge_kw[i] || 0},`;
    csv += `${trace.charge_from_pv_kw ? trace.charge_from_pv_kw[i] || 0 : 0},`;
    csv += `${trace.charge_from_grid_kw ? trace.charge_from_grid_kw[i] || 0 : 0},`;
    csv += `${trace.discharge_to_load_kw ? trace.discharge_to_load_kw[i] || 0 : 0},`;
    csv += `${trace.discharge_to_grid_kw ? trace.discharge_to_grid_kw[i] || 0 : 0}\n`;
  }

  // Download
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'battery_trace.csv';
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Clear dispatch trace display
 */
function clearDispatchTraceDisplay() {
  currentBatteryTrace = null;

  // Destroy charts
  if (socTimeseriesChart) {
    socTimeseriesChart.destroy();
    socTimeseriesChart = null;
  }
  if (powerTimeseriesChart) {
    powerTimeseriesChart.destroy();
    powerTimeseriesChart = null;
  }

  // Show placeholders
  document.getElementById('socChartPlaceholder').style.display = 'flex';
  document.getElementById('socTimeseriesChart').style.display = 'none';
  document.getElementById('powerChartPlaceholder').style.display = 'flex';
  document.getElementById('powerTimeseriesChart').style.display = 'none';

  // Disable export
  const exportBtn = document.getElementById('exportTraceBtn');
  if (exportBtn) exportBtn.disabled = true;

  // Clear cycle summary
  updateCycleSummaryDisplay(null);

  // Clear invariants
  updateInvariantsDisplay(null);
}

// Export v2.2.0 dispatch trace functions
window.updateDispatchTraceDisplay = updateDispatchTraceDisplay;
window.clearDispatchTraceDisplay = clearDispatchTraceDisplay;
window.exportBatteryTrace = exportBatteryTrace;

// ============================================
// v2.3.0 PORTFOLIO SUMMARY
// ============================================

/**
 * Current portfolio state
 */
let portfolioSelectedRunIds = [];
let portfolioLastResponse = null;

/**
 * Load available runs for portfolio selection
 */
async function loadAvailableRuns() {
  console.log('[Portfolio] Loading available runs...');
  const select = document.getElementById('portfolioRunSelect');
  if (!select) return;

  try {
    // Get recent runs from /runs endpoint
    const response = await fetch('/runs?limit=50');
    if (!response.ok) {
      throw new Error(`Failed to fetch runs: ${response.status}`);
    }
    const data = await response.json();
    const runs = data.items || data.runs || [];

    // Clear existing options
    select.innerHTML = '';

    if (runs.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Brak dostepnych wynikow';
      opt.disabled = true;
      select.appendChild(opt);
      return;
    }

    // Add runs as options
    runs.forEach(run => {
      const opt = document.createElement('option');
      opt.value = run.run_id;
      const label = run.label || run.run_id.slice(0, 8);
      const npv = run.npv_pln ? ` (NPV: ${formatNpv(run.npv_pln)})` : '';
      opt.textContent = `${label}${npv}`;
      select.appendChild(opt);
    });

    console.log(`[Portfolio] Loaded ${runs.length} runs`);

  } catch (error) {
    console.error('[Portfolio] Error loading runs:', error);
    select.innerHTML = '<option value="" disabled>Blad ladowania wynikow</option>';
  }
}

/**
 * Refresh run list
 */
function refreshRunList() {
  loadAvailableRuns();
}

/**
 * Update portfolio selection state
 */
function updatePortfolioSelection() {
  const select = document.getElementById('portfolioRunSelect');
  if (!select) return;

  portfolioSelectedRunIds = Array.from(select.selectedOptions).map(opt => opt.value);

  const countEl = document.getElementById('portfolioSelectionCount');
  if (countEl) {
    countEl.textContent = `${portfolioSelectedRunIds.length} wybranych`;
  }

  const btn = document.getElementById('runPortfolioSummaryBtn');
  if (btn) {
    btn.disabled = portfolioSelectedRunIds.length < 2;
  }
}

/**
 * Run portfolio summary calculation
 */
async function runPortfolioSummary() {
  if (portfolioSelectedRunIds.length < 2) {
    alert('Wybierz co najmniej 2 wyniki do agregacji');
    return;
  }

  console.log('[Portfolio] Running portfolio summary for:', portfolioSelectedRunIds);

  // Show loading state
  const resultsContainer = document.getElementById('portfolioResultsContainer');
  const statusIcon = document.getElementById('portfolioStatusIcon');
  const statusText = document.getElementById('portfolioStatusText');
  const summaryDisplay = document.getElementById('portfolioSummaryDisplay');
  const itemsTable = document.getElementById('portfolioItemsTable');
  const actions = document.getElementById('portfolioActions');

  if (resultsContainer) resultsContainer.style.display = 'block';
  if (statusIcon) statusIcon.textContent = '⏳';
  if (statusText) statusText.textContent = 'Obliczanie portfolio...';
  if (summaryDisplay) summaryDisplay.style.display = 'none';
  if (itemsTable) itemsTable.style.display = 'none';
  if (actions) actions.style.display = 'none';

  try {
    const response = await fetch('/api/bess-dispatch/portfolio/summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: portfolioSelectedRunIds }),
    });

    if (!response.ok) {
      throw new Error(`Portfolio summary failed: ${response.status}`);
    }

    const data = await response.json();
    portfolioLastResponse = data;

    displayPortfolioResults(data);

    if (statusIcon) statusIcon.textContent = '✅';
    if (statusText) statusText.textContent = 'Portfolio obliczone';

  } catch (error) {
    console.error('[Portfolio] Error:', error);
    if (statusIcon) statusIcon.textContent = '❌';
    if (statusText) statusText.textContent = `Blad: ${error.message}`;
  }
}

/**
 * Display portfolio results
 * @param {object} data - PortfolioResponse from API
 */
function displayPortfolioResults(data) {
  const summary = data.summary;
  const items = data.items || [];

  // Update summary counts
  const totalEl = document.getElementById('portfolioItemsTotal');
  const okEl = document.getElementById('portfolioItemsOk');
  const errorEl = document.getElementById('portfolioItemsError');

  if (totalEl) totalEl.textContent = summary.items_total || 0;
  if (okEl) okEl.textContent = summary.items_ok || 0;
  if (errorEl) errorEl.textContent = summary.items_error || 0;

  // Update KPIs
  const npvEl = document.getElementById('portfolioTotalNpv');
  const capexEl = document.getElementById('portfolioTotalCapex');
  const paybackEl = document.getElementById('portfolioPayback');
  const mixedEl = document.getElementById('portfolioMixedAssumptions');

  if (npvEl) {
    const npv = summary.total_npv_pln || 0;
    npvEl.textContent = formatNpv(npv);
    npvEl.classList.toggle('positive', npv >= 0);
    npvEl.classList.toggle('negative', npv < 0);
  }
  if (capexEl) capexEl.textContent = formatNpv(summary.total_capex_pln || 0);
  if (paybackEl) {
    const payback = summary.weighted_payback_years;
    paybackEl.textContent = payback ? `${payback.toFixed(1)} lat` : '-';
  }
  if (mixedEl) {
    mixedEl.textContent = summary.mixed_assumptions ? '⚠️ Tak' : '✅ Nie';
    mixedEl.classList.toggle('warning', summary.mixed_assumptions);
  }

  // Show summary
  const summaryDisplay = document.getElementById('portfolioSummaryDisplay');
  if (summaryDisplay) summaryDisplay.style.display = 'block';

  // Populate top items table
  const topItems = summary.top_items_by_npv || items.slice(0, 5);
  const tbody = document.getElementById('portfolioItemsBody');
  if (tbody && topItems.length > 0) {
    tbody.innerHTML = '';
    topItems.forEach(item => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="monospace">${item.run_id.slice(0, 8)}</td>
        <td>${item.label || '-'}</td>
        <td class="${(item.npv_pln || 0) >= 0 ? 'positive' : 'negative'}">${formatNpv(item.npv_pln || 0)}</td>
        <td>${item.payback_years ? item.payback_years.toFixed(1) + ' lat' : '-'}</td>
        <td>${formatNpv(item.capex_pln || 0)}</td>
      `;
      tbody.appendChild(tr);
    });

    const itemsTable = document.getElementById('portfolioItemsTable');
    if (itemsTable) itemsTable.style.display = 'block';
  }

  // Show actions
  const actions = document.getElementById('portfolioActions');
  if (actions) actions.style.display = 'block';
}

/**
 * Export portfolio to CSV
 */
async function exportPortfolioCSV() {
  if (!portfolioSelectedRunIds.length) return;

  try {
    const response = await fetch('/api/bess-dispatch/portfolio/summary/export/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: portfolioSelectedRunIds }),
    });

    if (!response.ok) throw new Error('Export failed');

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `portfolio_${portfolioSelectedRunIds.length}items.csv`;
    link.click();
    URL.revokeObjectURL(url);

  } catch (error) {
    console.error('[Portfolio] CSV export error:', error);
    alert('Export CSV nie powiodl sie');
  }
}

/**
 * Export portfolio to ZIP
 */
async function exportPortfolioZIP() {
  if (!portfolioSelectedRunIds.length) return;

  try {
    const response = await fetch('/api/bess-dispatch/portfolio/summary/export/zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: portfolioSelectedRunIds }),
    });

    if (!response.ok) throw new Error('Export failed');

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `portfolio_${portfolioSelectedRunIds.length}items.zip`;
    link.click();
    URL.revokeObjectURL(url);

  } catch (error) {
    console.error('[Portfolio] ZIP export error:', error);
    alert('Export ZIP nie powiodl sie');
  }
}

// Initialize portfolio on page load
document.addEventListener('DOMContentLoaded', () => {
  loadAvailableRuns();
});

// Export v2.3.0 portfolio functions
window.loadAvailableRuns = loadAvailableRuns;
window.refreshRunList = refreshRunList;
window.updatePortfolioSelection = updatePortfolioSelection;
window.runPortfolioSummary = runPortfolioSummary;
window.exportPortfolioCSV = exportPortfolioCSV;
window.exportPortfolioZIP = exportPortfolioZIP;

console.log('[BESS] bess.js v3.33 - v2.3.0 Portfolio Summary');
