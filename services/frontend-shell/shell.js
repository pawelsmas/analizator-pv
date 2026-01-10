// Micro-Frontend Shell - Routes to individual modules

// Proxy mode: use path-based routing via nginx reverse proxy
// When USE_PROXY=true, all URLs use /modules/* and /api/* paths
// When USE_PROXY=false, direct port access for development
const USE_PROXY = true; // Production mode: use nginx reverse proxy

// Module URLs
const MODULES = USE_PROXY ? {
  hub: '/modules/hub/',
  admin: '/modules/admin/',
  config: '/modules/config/',
  consumption: '/modules/consumption/',
  production: '/modules/production/',
  bess: '/modules/bess/',
  profile: '/modules/profile/',
  comparison: '/modules/comparison/',
  economics: '/modules/economics/',
  scoring: '/modules/scoring/',
  settings: '/modules/settings/',
  esg: '/modules/esg/',
  energyprices: '/modules/energyprices/',
  reports: '/modules/reports/',
  projects: '/modules/projects/',
  estimator: '/modules/estimator/'
} : {
  hub: 'http://localhost:9015',
  admin: 'http://localhost:9001',
  config: 'http://localhost:9002',
  consumption: 'http://localhost:9003',
  production: 'http://localhost:9004',
  bess: 'http://localhost:9013',
  profile: 'http://localhost:9014',
  comparison: 'http://localhost:9005',
  economics: 'http://localhost:9006',
  scoring: 'http://localhost:9016',
  settings: 'http://localhost:9007',
  esg: 'http://localhost:9008',
  energyprices: 'http://localhost:9009',
  reports: 'http://localhost:9010',
  projects: 'http://localhost:9011',
  estimator: 'http://localhost:9012'
};

// Backend API URLs
const BACKEND = USE_PROXY ? {
  dataAnalysis: '/api/data',
  pvCalculation: '/api/pv',
  economics: '/api/economics',
  advancedAnalytics: '/api/analytics',
  typicalDays: '/api/typical-days',
  energyPrices: '/api/energy-prices',
  reports: '/api/reports',
  projectsDb: '/api/projects',
  databaseApi: '/api/db'  // PostgreSQL database API (via nginx proxy)
} : {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002',
  economics: 'http://localhost:8003',
  advancedAnalytics: 'http://localhost:8004',
  typicalDays: 'http://localhost:8005',
  energyPrices: 'http://localhost:8010',
  reports: 'http://localhost:8011',
  projectsDb: 'http://localhost:8012',
  databaseApi: 'http://localhost:8050'  // PostgreSQL database API (direct)
};

// Current module
let currentModule = 'config';

// Shared data storage (alternative to localStorage for iframe isolation)
let sharedData = {
  analysisResults: null,
  pvConfig: null,
  consumptionData: null,
  hourlyData: null,
  masterVariant: null,
  masterVariantKey: null,
  settings: null, // System settings from Settings module
  economics: null, // Economics calculation results
  currentScenario: 'P50', // Current production scenario (P50/P75/P90)
  currentProject: null, // Current project info { id, name, client }

  // =========================================================================
  // ANALYTICAL PERIOD - Single Source of Truth for Time Axis
  // =========================================================================
  // This object defines the analysis time window. ALL modules must use this
  // for time-related calculations. DO NOT use new Date().getFullYear() or
  // hardcoded 8760/365 values - always reference analyticalPeriod.
  //
  // Structure:
  // {
  //   start_datetime: "2024-10-01T00:00:00",  // ISO 8601 - analysis start
  //   end_datetime: "2025-03-31T23:00:00",    // ISO 8601 - analysis end (calculated)
  //   interval_minutes: 60,                    // Data resolution: 15 or 60
  //   n_points: 4380,                          // Actual number of data points
  //   timezone: "Europe/Warsaw",               // Timezone for ToU/capacity fee
  //   clock_mode: "CET_FIXED",                 // CET_FIXED or LOCAL_TZ
  //   is_full_year: false,                     // true if n_points >= 8760 (hourly)
  //   annualization_factor: 2.0,               // 8760 / period_hours (for scaling)
  //   period_hours: 4380,                      // Total hours in analysis period
  //   period_days: 182.5,                      // Total days in analysis period
  //   source: "data_file"                      // 'data_file' | 'user_input' | 'fallback' | 'emergency_fallback'
  // }
  analyticalPeriod: null,

  // DEPRECATED: Use analyticalPeriod instead
  analyticalYear: null, // Kept for backward compatibility

  // BESS sizing result from pv-calculation (Single Source of Truth)
  bessResult: null,

  // Raw data arrays for BESS calculations
  loadData: null,  // Load profile array [kW]
  pvData: null     // PV generation array [kW]
};

// Also save settings to shell's localStorage as central storage
function saveSettingsToShell(settings) {
  sharedData.settings = settings;
  localStorage.setItem('pv_system_settings', JSON.stringify(settings));
  console.log('Settings saved to shell localStorage');
}

// Load settings from shell's localStorage
function loadSettingsFromShell() {
  const saved = localStorage.getItem('pv_system_settings');
  if (saved) {
    try {
      sharedData.settings = JSON.parse(saved);
      console.log('Settings loaded from shell localStorage');
      return sharedData.settings;
    } catch (e) {
      console.error('Failed to load settings:', e);
    }
  }
  return null;
}

// Load current project from localStorage
function loadCurrentProjectFromShell() {
  const saved = localStorage.getItem('pv_current_project');
  if (saved) {
    try {
      sharedData.currentProject = JSON.parse(saved);
      console.log('Current project loaded from shell localStorage:', sharedData.currentProject);
      return sharedData.currentProject;
    } catch (e) {
      console.error('Failed to load current project:', e);
    }
  }
  return null;
}

// =============================================================================
// DRAFT PROJECT MANAGER (Hybrid Workflow)
// =============================================================================
// This manages automatic draft project creation and finalization.
// Users work freely, data saves to draft. When ready, they click "Save" to name it.

const DraftProjectManager = {
  sessionId: null,
  draftProject: null,
  hasUnsavedChanges: false,

  // Generate unique session ID
  generateSessionId() {
    return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  },

  // Initialize draft project on app start
  async init() {
    // Check localStorage for existing session
    const savedSession = localStorage.getItem('pv_draft_session');
    if (savedSession) {
      try {
        const sessionData = JSON.parse(savedSession);
        this.sessionId = sessionData.sessionId;
        this.draftProject = sessionData.draftProject;
        console.log('📁 Restored draft session:', this.sessionId);

        // Verify draft still exists in database
        if (this.draftProject?.id) {
          const verified = await this.verifyDraft();
          if (verified) {
            this.updateProjectBar();
            return;
          }
        }
      } catch (e) {
        console.error('Failed to restore draft session:', e);
      }
    }

    // Create new session
    this.sessionId = this.generateSessionId();
    await this.createDraft();
  },

  // Create new draft project
  async createDraft() {
    try {
      const response = await fetch(`${BACKEND.databaseApi}/projects/draft?session_id=${this.sessionId}`, {
        method: 'POST'
      });

      if (!response.ok) {
        console.error('Failed to create draft project:', response.status);
        return null;
      }

      this.draftProject = await response.json();
      this.saveSession();
      this.updateProjectBar();

      // Set as current project in sharedData
      sharedData.currentProject = {
        id: this.draftProject.id,
        uuid: this.draftProject.uuid,
        name: this.draftProject.name,
        isDraft: true
      };
      localStorage.setItem('pv_current_project', JSON.stringify(sharedData.currentProject));

      console.log('📁 Created draft project:', this.draftProject.id, this.draftProject.uuid);
      return this.draftProject;
    } catch (error) {
      console.error('Error creating draft project:', error);
      return null;
    }
  },

  // Verify draft still exists
  async verifyDraft() {
    if (!this.draftProject?.id) return false;

    try {
      const response = await fetch(`${BACKEND.databaseApi}/projects/${this.draftProject.id}`);
      if (response.ok) {
        const data = await response.json();
        const project = data.project || data;
        return project.status === 'draft';
      }
    } catch (e) {
      console.error('Failed to verify draft:', e);
    }
    return false;
  },

  // Save session to localStorage
  saveSession() {
    localStorage.setItem('pv_draft_session', JSON.stringify({
      sessionId: this.sessionId,
      draftProject: this.draftProject
    }));
  },

  // Mark that there are unsaved changes
  markChanged() {
    this.hasUnsavedChanges = true;
    this.updateProjectBar();
  },

  // Finalize draft (convert to real project)
  async finalize(name, companyId, description, locationName) {
    if (!this.draftProject?.id) {
      console.error('No draft project to finalize');
      return null;
    }

    try {
      const params = new URLSearchParams({ name });
      if (companyId) params.append('company_id', companyId);
      if (description) params.append('description', description);
      if (locationName) params.append('location_name', locationName);

      const response = await fetch(`${BACKEND.databaseApi}/projects/${this.draftProject.id}/finalize?${params}`, {
        method: 'PUT'
      });

      if (!response.ok) {
        const error = await response.json();
        console.error('Failed to finalize project:', error);
        return null;
      }

      const finalizedProject = await response.json();

      // Update current project
      sharedData.currentProject = {
        id: finalizedProject.id,
        uuid: finalizedProject.uuid,
        name: finalizedProject.name,
        companyId: finalizedProject.company_id,
        isDraft: false
      };
      localStorage.setItem('pv_current_project', JSON.stringify(sharedData.currentProject));

      // *** SAVE ALL STATE TO DATABASE ***
      // This saves all accumulated data (settings, profiles, calculations) to PostgreSQL
      await saveAllStateToDb(finalizedProject.id);

      // Clear draft session
      this.draftProject = null;
      this.hasUnsavedChanges = false;
      localStorage.removeItem('pv_draft_session');

      // Update UI
      this.updateProjectBar();
      this.showSaveConfirmation(finalizedProject.name);

      // Broadcast to modules
      broadcastToModules({
        type: 'PROJECT_FINALIZED',
        data: sharedData.currentProject
      });

      console.log('✅ Project finalized:', finalizedProject.name);
      return finalizedProject;
    } catch (error) {
      console.error('Error finalizing project:', error);
      return null;
    }
  },

  // Update project bar in header
  updateProjectBar() {
    const bar = document.getElementById('projectBar');
    if (!bar) return;

    if (this.draftProject && sharedData.currentProject?.isDraft !== false) {
      // Draft mode
      bar.className = 'project-bar draft';
      bar.innerHTML = `
        <span class="project-status">📝 Wersja robocza</span>
        <span class="project-name">${this.draftProject.name}</span>
        ${this.hasUnsavedChanges ? '<span class="unsaved-indicator">●</span>' : ''}
        <button class="save-project-btn" onclick="openSaveProjectModal()">💾 Zapisz projekt</button>
      `;
    } else if (sharedData.currentProject && !sharedData.currentProject.isDraft) {
      // Saved project
      bar.className = 'project-bar saved';
      bar.innerHTML = `
        <span class="project-status">✓ Zapisany</span>
        <span class="project-name">${sharedData.currentProject.name}</span>
        <button class="new-project-btn" onclick="startNewProject()">+ Nowa analiza</button>
      `;
    }
  },

  // Show save confirmation toast
  showSaveConfirmation(projectName) {
    const toast = document.createElement('div');
    toast.className = 'save-toast';
    toast.innerHTML = `✓ Zapisano: <strong>${projectName}</strong>`;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }
};

// Open save project modal
function openSaveProjectModal() {
  const modal = document.getElementById('saveProjectModal');
  if (modal) {
    modal.style.display = 'flex';
    // Load companies for dropdown
    loadCompaniesForModal();
    // Focus on name input
    document.getElementById('projectNameInput')?.focus();
  }
}

// Close save project modal
function closeSaveProjectModal() {
  const modal = document.getElementById('saveProjectModal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Load companies for the dropdown in save modal
async function loadCompaniesForModal() {
  try {
    const response = await fetch(`${BACKEND.databaseApi}/companies`);
    if (!response.ok) return;

    const companies = await response.json();
    const select = document.getElementById('projectCompanySelect');
    if (!select) return;

    select.innerHTML = '<option value="">-- Opcjonalnie wybierz firmę --</option>';
    companies.forEach(c => {
      select.innerHTML += `<option value="${c.id}">${c.name}${c.nip ? ` (NIP: ${c.nip})` : ''}</option>`;
    });
  } catch (error) {
    console.error('Failed to load companies:', error);
  }
}

// Save project (from modal)
async function saveProject() {
  const name = document.getElementById('projectNameInput')?.value?.trim();
  const companyId = document.getElementById('projectCompanySelect')?.value || null;
  const description = document.getElementById('projectDescriptionInput')?.value?.trim() || null;
  const location = document.getElementById('projectLocationInput')?.value?.trim() || null;

  if (!name) {
    alert('Podaj nazwę projektu');
    return;
  }

  const result = await DraftProjectManager.finalize(name, companyId, description, location);
  if (result) {
    closeSaveProjectModal();
  }
}

// Start a new project (clear current and create new draft)
async function startNewProject() {
  if (DraftProjectManager.hasUnsavedChanges) {
    if (!confirm('Masz niezapisane zmiany. Czy na pewno chcesz rozpocząć nową analizę?')) {
      return;
    }
  }

  // Clear all shared data
  const savedSettings = sharedData.settings;
  Object.keys(sharedData).forEach(key => {
    if (key !== 'settings' && key !== 'currentScenario') {
      sharedData[key] = null;
    }
  });
  sharedData.settings = savedSettings;

  // Clear localStorage
  localStorage.removeItem('pv_current_project');
  localStorage.removeItem('pv_draft_session');

  // Create new draft
  await DraftProjectManager.init();

  // Notify modules
  broadcastToModules({ type: 'DATA_CLEARED' });

  // Reload config module
  loadModule('config');
}

// ============== Fetch and save full consumption data ==============
async function fetchAndSaveFullConsumptionData() {
  // Only save if we have a current project
  if (!sharedData.currentProject || !sharedData.currentProject.id) {
    console.log('fetchAndSaveFullConsumptionData: No current project, skipping');
    return;
  }

  try {
    // Fetch full hourly data from data-analysis service
    const response = await fetch(`${BACKEND.dataAnalysis}/export-data`);
    if (!response.ok) {
      console.error('Failed to fetch full consumption data:', response.status);
      return;
    }

    const fullData = await response.json();
    console.log(`✅ Fetched full consumption data: ${fullData.data_points} points`);

    // Save full data to project (includes timestamps, values, analytical_year)
    await autoSaveToProject('rawConsumptionData', fullData);

    // Also save metadata
    if (sharedData.consumptionData) {
      await autoSaveToProject('consumptionData', {
        ...sharedData.consumptionData,
        data_points: fullData.data_points
      });
    }
  } catch (error) {
    console.error('Error fetching full consumption data:', error);
  }
}

// ============== Restore consumption data to data-analysis ==============
async function restoreConsumptionData(rawData) {
  if (!rawData || !rawData.timestamps || !rawData.values) {
    console.log('restoreConsumptionData: No valid data to restore');
    return false;
  }

  try {
    const response = await fetch(`${BACKEND.dataAnalysis}/restore-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        timestamps: rawData.timestamps,
        values: rawData.values,
        analytical_year: rawData.analytical_year || null
      })
    });

    if (!response.ok) {
      console.error('Failed to restore consumption data:', response.status);
      return false;
    }

    const result = await response.json();
    console.log(`✅ Restored consumption data: ${result.data_points} points`);
    return true;
  } catch (error) {
    console.error('Error restoring consumption data:', error);
    return false;
  }
}

// ============== Auto-save to current project (PostgreSQL) ==============
// This is the main function that saves data to the PostgreSQL database

// Debounce settings save to avoid too many requests
let settingsSaveTimeout = null;
let pendingSettings = null;

async function autoSaveToProject(dataType, data) {
  // Only save if we have a current project
  if (!sharedData.currentProject || !sharedData.currentProject.id) {
    console.log(`Auto-save skipped (no current project): ${dataType}`);
    return;
  }

  const projectId = sharedData.currentProject.id;

  try {
    switch (dataType) {
      case 'settings':
        // Save settings as new version (debounced)
        pendingSettings = data;
        if (settingsSaveTimeout) clearTimeout(settingsSaveTimeout);
        settingsSaveTimeout = setTimeout(() => saveSettingsToDb(projectId, pendingSettings), 2000);
        console.log(`⏳ Settings save scheduled for project ${projectId}`);
        break;

      case 'consumptionProfile':
        // Save consumption profile to database
        await saveProfileToDb(projectId, 'consumption', data);
        break;

      case 'pvProfile':
        // Save PV generation profile to database
        await saveProfileToDb(projectId, 'pv_generation', data);
        break;

      case 'calculation':
        // Save calculation result to database
        await saveCalculationToDb(projectId, data);
        break;

      default:
        // For other data types, save as part of settings JSON
        console.log(`📝 ${dataType} will be included in next settings save`);
        break;
    }
  } catch (error) {
    console.error(`❌ Error auto-saving ${dataType}:`, error);
  }
}

// Save settings to PostgreSQL
async function saveSettingsToDb(projectId, settings) {
  try {
    const response = await fetch(`${BACKEND.databaseApi}/projects/${projectId}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        settings: settings,
        description: 'Auto-saved from shell',
        created_by: 'shell-auto-save'
      })
    });

    if (response.ok) {
      const result = await response.json();
      console.log(`✅ Settings saved to DB (version ${result.version}) for project ${projectId}`);
    } else {
      console.error(`❌ Failed to save settings:`, await response.text());
    }
  } catch (error) {
    console.error(`❌ Error saving settings to DB:`, error);
  }
}

// Save energy profile to PostgreSQL
async function saveProfileToDb(projectId, profileType, profileData) {
  try {
    // profileData should contain: { values: [...], year, resolution, source, filename }
    const values = profileData.values || profileData.hourlyData?.values || [];
    if (values.length === 0) {
      console.log(`⚠️ No values to save for ${profileType} profile`);
      return;
    }

    const response = await fetch(`${BACKEND.databaseApi}/profiles/bulk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: projectId,
        profile_type: profileType,
        time_resolution: profileData.resolution || 'hourly',
        year: profileData.year || new Date().getFullYear(),
        source: profileData.source || 'shell-upload',
        filename: profileData.filename || null,
        values: values
      })
    });

    if (response.ok) {
      const result = await response.json();
      console.log(`✅ ${profileType} profile saved to DB: ${result.data_points} points, ${result.total_kwh.toFixed(0)} kWh`);
    } else {
      console.error(`❌ Failed to save ${profileType} profile:`, await response.text());
    }
  } catch (error) {
    console.error(`❌ Error saving ${profileType} profile to DB:`, error);
  }
}

// Save calculation result to PostgreSQL
async function saveCalculationToDb(projectId, calcData) {
  try {
    // Create calculation record
    const response = await fetch(`${BACKEND.databaseApi}/calculations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: projectId,
        calc_type: calcData.calc_type || 'unknown',
        request_payload: calcData.request || {},
        service_name: calcData.service_name || 'shell',
        created_by: 'shell-auto-save'
      })
    });

    if (!response.ok) {
      console.error(`❌ Failed to create calculation:`, await response.text());
      return;
    }

    const calc = await response.json();

    // Update with result
    const updateResponse = await fetch(`${BACKEND.databaseApi}/calculations/${calc.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: 'completed',
        result_payload: calcData.result || calcData,
        completed_at: new Date().toISOString(),
        duration_ms: calcData.duration_ms || 0
      })
    });

    if (updateResponse.ok) {
      console.log(`✅ Calculation ${calcData.calc_type} saved to DB (id: ${calc.id})`);
    }
  } catch (error) {
    console.error(`❌ Error saving calculation to DB:`, error);
  }
}

// Request economics data from Economics module before saving
// Returns a promise that resolves when economics data is received (with timeout)
function requestEconomicsDataFromModule() {
  return new Promise((resolve) => {
    // If we already have economics data, resolve immediately
    if (sharedData.economics) {
      console.log('📊 Economics data already available in sharedData');
      resolve(sharedData.economics);
      return;
    }

    // Set up a one-time listener for the response
    const timeoutMs = 3000; // 3 second timeout
    let resolved = false;

    const handleEconomicsResponse = (event) => {
      if (event.data?.type === 'ECONOMICS_DATA_RESPONSE' && !resolved) {
        resolved = true;
        window.removeEventListener('message', handleEconomicsResponse);
        if (event.data.data) {
          sharedData.economics = event.data.data;
          console.log('📊 Received economics data from module:', event.data.data.variantKey);
        }
        resolve(sharedData.economics);
      }
    };

    window.addEventListener('message', handleEconomicsResponse);

    // Request data from Economics module
    console.log('📤 Requesting economics data from Economics module...');
    broadcastToModules({ type: 'REQUEST_ECONOMICS_DATA' });

    // Timeout fallback
    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        window.removeEventListener('message', handleEconomicsResponse);
        console.log('⏱️ Economics data request timed out, proceeding with existing data');
        resolve(sharedData.economics);
      }
    }, timeoutMs);
  });
}

// ============================================================================
// ECONOMICS SNAPSHOT V2 - Investor-Ready Persistence
// ============================================================================

/**
 * Get CAPEX margin data for a given capacity and PV type
 * Uses capexPerType from sharedData.settings
 */
function getCapexMarginData(capacityKwp, pvType) {
  const settings = sharedData.settings || {};
  const capexRanges = settings.capexRanges || [
    { min: 50, max: 150 },
    { min: 150, max: 300 },
    { min: 300, max: 1000 },
    { min: 1000, max: 3000 },
    { min: 3000, max: 10000 },
    { min: 10000, max: Infinity }
  ];
  const capexPerType = settings.capexPerType || {};

  // Find matching range index
  let rangeIndex = capexRanges.length - 1; // Default to last tier
  for (let i = 0; i < capexRanges.length; i++) {
    const range = capexRanges[i];
    if (capacityKwp >= range.min && capacityKwp < (range.max === Infinity ? 999999 : range.max)) {
      rangeIndex = i;
      break;
    }
  }

  // Get tier data for the PV type
  const typeData = capexPerType[pvType] || capexPerType['ground_s'] || [];
  const tierData = typeData[rangeIndex] || typeData[0] || { cost: 2800, margin: 23, sale: 3444 };

  return {
    costPerKwp: tierData.cost,
    marginPct: tierData.margin,
    salePerKwp: tierData.sale,
    rangeIndex: rangeIndex,
    rangeMin: capexRanges[rangeIndex]?.min || 50,
    rangeMax: capexRanges[rangeIndex]?.max || Infinity
  };
}

/**
 * Build Economics Snapshot Payload V2 for investor-ready persistence
 * Combines data from sharedData.economics (centralizedMetrics) and sharedData.settings
 */
function buildEconomicsSnapshotPayloadV2() {
  const economics = sharedData.economics;
  const settings = sharedData.settings || {};
  const masterVariant = sharedData.masterVariant;
  const pvConfig = sharedData.pvConfig || {};

  if (!economics || !masterVariant) {
    console.warn('⚠️ Cannot build Economics Snapshot V2 - missing economics or masterVariant data');
    return null;
  }

  // Get PV capacity and type
  const capacityKwp = masterVariant.capacity || 0;
  const pvType = pvConfig.pvType || pvConfig.pv_type || 'ground_s';
  const variantKey = sharedData.masterVariantKey || economics.variantKey || 'unknown';

  // Get CAPEX margin data
  const marginData = getCapexMarginData(capacityKwp, pvType);

  // Calculate deal economics
  const sellPricePln = capacityKwp * marginData.salePerKwp;
  const directCostPln = capacityKwp * marginData.costPerKwp;
  const grossMarginPln = sellPricePln - directCostPln;
  // CORRECT: Margin = Profit / Sale Price (not Profit / Cost which is markup)
  const grossMarginPct = sellPricePln > 0 ? (grossMarginPln / sellPricePln) * 100 : 0;

  // BESS info
  const bessPowerKw = masterVariant.bess_power_kw || economics.bessPowerKw || 0;
  const bessEnergyKwh = masterVariant.bess_energy_kwh || economics.bessEnergyKwh || 0;

  // =========================================================================
  // CASHFLOW GENERATION - Fixed horizons per model type
  // =========================================================================
  // Contract: Client analysis horizon = 30 years (CAPEX_CLIENT, EAAS_CLIENT)
  //           Investor horizon = EaaS contract duration (EAAS_INVESTOR, max 25 years)
  // =========================================================================
  const CLIENT_ANALYSIS_PERIOD = 30;  // Fixed for client models
  const MAX_EAAS_DURATION = 25;       // Max EaaS contract duration

  const capexClientCashflows = [];
  const eaasClientCashflows = [];
  const eaasInvestorCashflows = [];

  // Get key parameters
  const capexInvestment = economics.capexInvestment || (capacityKwp * marginData.salePerKwp);
  const eaasDuration = Math.min(settings.eaasDuration || economics.eaasDuration || 10, MAX_EAAS_DURATION);

  // Discount rate: settings is in % (e.g., 7), economics is in decimal (e.g., 0.07)
  const discountRate = settings.discountRate !== undefined && settings.discountRate !== null
    ? settings.discountRate / 100
    : (economics.discountRate || 0.07);

  // O&M and insurance costs for investor
  const omCostPerKwp = settings.omCostPerKwp || 24; // PLN/kWp/year
  const insuranceRate = settings.insuranceRate || 0.005; // 0.5% of CAPEX
  const annualOpex = (capacityKwp * omCostPerKwp) + (directCostPln * insuranceRate);

  // Get source cashflows from economics
  const sourceCapexCashFlows = economics.capexCashFlows || [];
  const sourceEaasCashFlows = economics.cashFlows || [];

  // Helper: Get data for a specific year from source cashflows
  const getCapexYearData = (year) => sourceCapexCashFlows.find(cf => cf.year === year) || {};
  const getEaasYearData = (year) => sourceEaasCashFlows.find(cf => cf.year === year) || sourceEaasCashFlows[year - 1] || {};

  // =========================================================================
  // CAPEX_CLIENT: Years 0..30 (31 records) - Client buying the system
  // =========================================================================
  if (sourceCapexCashFlows.length > 0 || capexInvestment > 0) {
    // Year 0: Initial investment
    capexClientCashflows.push({
      model_type: 'CAPEX_CLIENT',
      year: 0,
      capex_pln: capexInvestment,
      revenue_pln: 0,
      opex_pln: 0,
      net_cashflow_pln: -capexInvestment,
      cumulative_cashflow_pln: -capexInvestment,
      discounted_cashflow_pln: -capexInvestment,
      cumulative_discounted_pln: -capexInvestment,
      production_kwh: null,
      self_consumed_kwh: null,
      pv_degradation_pct: null,
      bess_degradation_pct: null
    });

    // Years 1..30: Operating cashflows
    let cumulativeCF = -capexInvestment;
    let cumulativeDiscountedCF = -capexInvestment;

    for (let year = 1; year <= CLIENT_ANALYSIS_PERIOD; year++) {
      const yearData = getCapexYearData(year);

      // If we have source data, use it; otherwise extrapolate from last available year
      const lastKnownYear = sourceCapexCashFlows.length > 0 ? sourceCapexCashFlows[sourceCapexCashFlows.length - 1] : {};
      const netCF = yearData.net_cash_flow !== undefined ? yearData.net_cash_flow : (lastKnownYear.net_cash_flow || 0);
      const discountedCF = netCF / Math.pow(1 + discountRate, year);
      cumulativeCF += netCF;
      cumulativeDiscountedCF += discountedCF;

      capexClientCashflows.push({
        model_type: 'CAPEX_CLIENT',
        year: year,
        capex_pln: 0,
        revenue_pln: yearData.savings || lastKnownYear.savings || 0,
        opex_pln: yearData.opex || lastKnownYear.opex || 0,
        net_cashflow_pln: netCF,
        cumulative_cashflow_pln: cumulativeCF,
        discounted_cashflow_pln: discountedCF,
        cumulative_discounted_pln: cumulativeDiscountedCF,
        production_kwh: yearData.production || null,
        self_consumed_kwh: yearData.selfConsumed || null,
        pv_degradation_pct: yearData.pvDegradationPct || null,
        bess_degradation_pct: yearData.bessDegradationPct || null
      });
    }
  }

  // =========================================================================
  // EAAS_CLIENT: Years 1..30 (30 records) - Client using EaaS subscription
  // =========================================================================
  // Phase 1 (years 1..eaasDuration): EaaS subscription phase
  // Phase 2 (years eaasDuration+1..30): Post-contract / Ownership phase
  if (sourceEaasCashFlows.length > 0) {
    let eaasClientCumulativeCF = 0;
    let eaasClientCumulativeDiscountedCF = 0;

    for (let year = 1; year <= CLIENT_ANALYSIS_PERIOD; year++) {
      const yearData = getEaasYearData(year);
      const isEaasPhase = year <= eaasDuration;

      // During EaaS phase: client pays subscription, gets savings
      // Post-contract: client owns the system, no subscription, just O&M savings
      let netCF, revenuePln, opexPln;

      if (isEaasPhase) {
        // EaaS phase: savings = grid cost avoided, opex = subscription cost
        revenuePln = yearData.savings || yearData.gridCost || 0;
        opexPln = yearData.eaasCost || 0;
        netCF = revenuePln - opexPln;
      } else {
        // Post-contract: client owns system, uses CAPEX-like economics
        // Revenue = energy savings, Opex = O&M + insurance
        const capexYearData = getCapexYearData(year);
        revenuePln = capexYearData.savings || yearData.savings || 0;
        opexPln = capexYearData.opex || annualOpex || 0;
        netCF = revenuePln - opexPln;
      }

      const discountedCF = netCF / Math.pow(1 + discountRate, year);
      eaasClientCumulativeCF += netCF;
      eaasClientCumulativeDiscountedCF += discountedCF;

      eaasClientCashflows.push({
        model_type: 'EAAS_CLIENT',
        year: year,
        capex_pln: 0,
        revenue_pln: revenuePln,
        opex_pln: opexPln,
        net_cashflow_pln: netCF,
        cumulative_cashflow_pln: eaasClientCumulativeCF,
        discounted_cashflow_pln: discountedCF,
        cumulative_discounted_pln: eaasClientCumulativeDiscountedCF,
        production_kwh: yearData.selfConsumed || null,
        self_consumed_kwh: yearData.selfConsumed || null,
        pv_degradation_pct: yearData.pvDegradationPct || null,
        bess_degradation_pct: yearData.bessDegradationPct || null
      });
    }
  }

  // =========================================================================
  // EAAS_INVESTOR: Years 0..eaasDuration (eaasDuration+1 records) - Developer perspective
  // =========================================================================
  // Horizon = contract duration only (not full 30 years)
  if (sourceEaasCashFlows.length > 0 && directCostPln > 0) {
    // Year 0: Initial investment (developer's cost, not sale price)
    eaasInvestorCashflows.push({
      model_type: 'EAAS_INVESTOR',
      year: 0,
      capex_pln: directCostPln,
      revenue_pln: 0,
      opex_pln: 0,
      net_cashflow_pln: -directCostPln,
      cumulative_cashflow_pln: -directCostPln,
      discounted_cashflow_pln: -directCostPln,
      cumulative_discounted_pln: -directCostPln,
      production_kwh: null,
      self_consumed_kwh: null,
      pv_degradation_pct: null,
      bess_degradation_pct: null
    });

    // Years 1..eaasDuration: Operating cashflows (contract period only)
    let investorCumulativeCF = -directCostPln;
    let investorCumulativeDiscountedCF = -directCostPln;

    for (let year = 1; year <= eaasDuration; year++) {
      const yearData = getEaasYearData(year);

      // Revenue = subscription from client
      const subscriptionRevenue = yearData.eaasCost || 0;
      const yearOpex = annualOpex;
      const netCF = subscriptionRevenue - yearOpex;
      const discountedCF = netCF / Math.pow(1 + discountRate, year);
      investorCumulativeCF += netCF;
      investorCumulativeDiscountedCF += discountedCF;

      eaasInvestorCashflows.push({
        model_type: 'EAAS_INVESTOR',
        year: year,
        capex_pln: 0,
        revenue_pln: subscriptionRevenue,
        opex_pln: yearOpex,
        net_cashflow_pln: netCF,
        cumulative_cashflow_pln: investorCumulativeCF,
        discounted_cashflow_pln: discountedCF,
        cumulative_discounted_pln: investorCumulativeDiscountedCF,
        production_kwh: yearData.selfConsumed || null,
        self_consumed_kwh: yearData.selfConsumed || null,
        pv_degradation_pct: yearData.pvDegradationPct || null,
        bess_degradation_pct: yearData.bessDegradationPct || null
      });
    }
  }

  // Combine all cashflows for saving
  const allCashflows = [...capexClientCashflows, ...eaasClientCashflows, ...eaasInvestorCashflows];

  // =========================================================================
  // NPV/IRR CALCULATIONS - from generated cashflow arrays (single source of truth)
  // =========================================================================
  // NOTE: NPV/IRR values are computed from the exact same yearly CF arrays
  // that are persisted to project_economics_cashflow_yearly table.
  // This ensures Portal #2 KPIs match the yearly cashflow charts.
  // =========================================================================

  // Calculate CAPEX Client NPV from generated cashflows (as backup/verification)
  let capexClientNpvFromCf = null;
  if (capexClientCashflows.length > 0) {
    const lastCapexCf = capexClientCashflows[capexClientCashflows.length - 1];
    capexClientNpvFromCf = lastCapexCf.cumulative_discounted_pln;
  }

  // Calculate EaaS Client NPV from generated cashflows (as backup/verification)
  let eaasClientNpvFromCf = null;
  if (eaasClientCashflows.length > 0) {
    const lastEaasCf = eaasClientCashflows[eaasClientCashflows.length - 1];
    eaasClientNpvFromCf = lastEaasCf.cumulative_discounted_pln;
  }

  // Calculate EaaS Investor NPV and IRR from generated cashflows
  let eaasInvestorNpv = null;
  let eaasInvestorIrr = null;
  let eaasInvestorRevenueAnnual = null;
  let eaasInvestorOpexAnnual = null;

  if (eaasInvestorCashflows.length > 1) {
    // NPV is the last cumulative discounted value
    const lastCf = eaasInvestorCashflows[eaasInvestorCashflows.length - 1];
    eaasInvestorNpv = lastCf.cumulative_discounted_pln;

    // Annual revenue/opex from year 1
    const year1Cf = eaasInvestorCashflows.find(cf => cf.year === 1);
    if (year1Cf) {
      eaasInvestorRevenueAnnual = year1Cf.revenue_pln;
      eaasInvestorOpexAnnual = year1Cf.opex_pln;
    }

    // Calculate IRR using Newton-Raphson method
    const cashFlowsForIrr = eaasInvestorCashflows.map(cf => cf.net_cashflow_pln);
    if (cashFlowsForIrr.length > 0 && cashFlowsForIrr[0] < 0) {
      // Simple IRR calculation
      let irr = 0.1; // Initial guess 10%
      const maxIterations = 100;
      const tolerance = 0.0001;

      for (let iter = 0; iter < maxIterations; iter++) {
        let npv = 0;
        let dnpv = 0; // derivative

        for (let t = 0; t < cashFlowsForIrr.length; t++) {
          const cf = cashFlowsForIrr[t];
          npv += cf / Math.pow(1 + irr, t);
          dnpv -= t * cf / Math.pow(1 + irr, t + 1);
        }

        if (Math.abs(dnpv) < 1e-10) break;
        const newIrr = irr - npv / dnpv;

        if (Math.abs(newIrr - irr) < tolerance) {
          irr = newIrr;
          break;
        }
        irr = newIrr;

        // Clamp to reasonable range
        if (irr < -0.99) irr = -0.99;
        if (irr > 10) irr = 10;
      }

      // Only use if it's a reasonable value
      if (irr > -0.99 && irr < 10 && !isNaN(irr)) {
        eaasInvestorIrr = irr;
      }
    }
  }

  // Build the snapshot payload
  const payload = {
    // System identification
    production_scenario: sharedData.currentScenario || 'P50',
    variant_key: variantKey,
    pv_capacity_kwp: capacityKwp,
    pv_type: pvType,
    bess_power_kw: bessPowerKw,
    bess_energy_kwh: bessEnergyKwh,

    // Analysis parameters
    // Client analysis period is fixed at 30 years (CONTRACT)
    analysis_period_years: CLIENT_ANALYSIS_PERIOD,
    // Store as percentage (e.g., 7.0 for 7%)
    discount_rate_pct: settings.discountRate !== undefined && settings.discountRate !== null
      ? settings.discountRate
      : (economics.discountRate ? economics.discountRate * 100 : 7),
    inflation_rate_pct: settings.inflationRate !== undefined && settings.inflationRate !== null
      ? settings.inflationRate
      : 2.5,

    // CAPEX Client (investor buying the system)
    // NPV from economics.js, with fallback to cashflow-calculated value for consistency
    capex_client_npv25: economics.capexNPV || capexClientNpvFromCf || null,
    capex_client_irr: economics.capexIRR || null,
    capex_client_irr_mode: economics.irrMode || settings.irrMode || 'real',
    capex_client_simple_payback: economics.capexPayback || null,
    capex_client_discounted_payback: null, // Could be calculated from cashflows
    capex_client_capex0_pln: economics.capexInvestment || (capacityKwp * marginData.salePerKwp),

    // CAPEX Deal (margin for installer/developer)
    capex_deal_sell_price_pln: sellPricePln,
    capex_deal_direct_cost_pln: directCostPln,
    capex_deal_gross_margin_pct: grossMarginPct,
    capex_deal_gross_margin_pln: grossMarginPln,

    // EaaS Client (subscription model for client)
    // NPV from economics.js, with fallback to cashflow-calculated value for consistency
    eaas_client_npv25: economics.cumulativeNPV || eaasClientNpvFromCf || null,
    eaas_client_duration_years: eaasDuration, // Uses calculated value (capped at MAX_EAAS_DURATION=25)
    eaas_client_subscription_annual: sourceEaasCashFlows[0]?.eaasCost || null,

    // EaaS Investor (reverse view - developer's perspective)
    eaas_investor_npv25: eaasInvestorNpv,
    eaas_investor_irr: eaasInvestorIrr,
    eaas_investor_capex0_pln: directCostPln, // Developer pays cost, not sale price
    eaas_investor_revenue_annual: eaasInvestorRevenueAnnual,
    eaas_investor_opex_annual: eaasInvestorOpexAnnual,

    // Full payload backup (JSONB)
    full_payload: {
      // Data contract documentation
      dataContract: {
        version: '2.0',
        clientAnalysisPeriod: CLIENT_ANALYSIS_PERIOD,
        maxEaasDuration: MAX_EAAS_DURATION,
        capexClientYears: '0..30',
        eaasClientYears: '1..30',
        eaasInvestorYears: `0..${eaasDuration}`
      },
      // Post-contract policy for EAAS_CLIENT years (duration+1..30)
      postContractPolicy: {
        type: 'om_insurance_ownership',
        description: 'After EaaS contract ends, client owns system and pays O&M + insurance',
        omCostPerKwp: omCostPerKwp,
        insuranceRate: insuranceRate,
        annualOpex: annualOpex
      },
      economics: economics,
      marginData: marginData,
      settings: {
        discountRate: settings.discountRate,
        inflationRate: settings.inflationRate,
        analysisPeriod: CLIENT_ANALYSIS_PERIOD, // Fixed at 30 years
        eaasDuration: eaasDuration,
        pvDegradationYear1: settings.pvDegradationYear1,
        degradationRate: settings.degradationRate
      },
      masterVariant: {
        capacity: masterVariant.capacity,
        production: masterVariant.production,
        self_consumed: masterVariant.self_consumed,
        bess_power_kw: masterVariant.bess_power_kw,
        bess_energy_kwh: masterVariant.bess_energy_kwh
      },
      // NPV calculation sources for audit trail
      npvSources: {
        capexClientNpv: economics.capexNPV ? 'economics.js' : 'cashflow-calculated',
        eaasClientNpv: economics.cumulativeNPV ? 'economics.js' : 'cashflow-calculated',
        eaasInvestorNpv: 'cashflow-calculated'
      }
    },

    created_by: 'shell-auto-save',

    // All cashflows: CAPEX_CLIENT + EAAS_CLIENT + EAAS_INVESTOR
    cashflows: allCashflows
  };

  console.log('📊 Built Economics Snapshot V2 Payload:', {
    variantKey: payload.variant_key,
    capacityKwp: payload.pv_capacity_kwp,
    pvType: payload.pv_type,
    capexNpv: payload.capex_client_npv25,
    capexIrr: payload.capex_client_irr,
    sellPrice: payload.capex_deal_sell_price_pln,
    grossMargin: payload.capex_deal_gross_margin_pln,
    cashflowsCount: payload.cashflows.length,
    cashflowsByModel: {
      CAPEX_CLIENT: capexClientCashflows.length,
      EAAS_CLIENT: eaasClientCashflows.length,
      EAAS_INVESTOR: eaasInvestorCashflows.length
    }
  });

  return payload;
}

/**
 * Save Economics Snapshot V2 to database
 */
async function saveEconomicsSnapshotToDb(projectId) {
  try {
    const payload = buildEconomicsSnapshotPayloadV2();

    if (!payload) {
      console.log('⚠️ Skipping Economics Snapshot V2 save - no payload built');
      return null;
    }

    // POST to new economics-snapshot endpoint
    const response = await fetch(`${BACKEND.databaseApi}/projects/${projectId}/economics-snapshot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`❌ Failed to save Economics Snapshot V2:`, errorText);
      return null;
    }

    const snapshot = await response.json();
    console.log(`✅ Economics Snapshot V2 saved (id: ${snapshot.id}, version: ${snapshot.snapshot_version})`);
    return snapshot;
  } catch (error) {
    console.error(`❌ Error saving Economics Snapshot V2:`, error);
    return null;
  }
}

// Save all current state to database (called on finalize or manual save)
async function saveAllStateToDb(projectId) {
  console.log(`💾 Saving all state to DB for project ${projectId}...`);

  // Request economics data from Economics module if not already available
  if (!sharedData.economics) {
    console.log('📊 Economics data not in sharedData, requesting from module...');
    await requestEconomicsDataFromModule();
  }

  // 1. Save current settings
  if (sharedData.settings) {
    await saveSettingsToDb(projectId, {
      ...sharedData.settings,
      pvConfig: sharedData.pvConfig,
      currentScenario: sharedData.currentScenario,
      masterVariantKey: sharedData.masterVariantKey
    });
  }

  // 2. Save consumption profile if available
  if (sharedData.consumptionData?.hourlyData?.values || sharedData.hourlyData?.values) {
    await saveProfileToDb(projectId, 'consumption', {
      values: sharedData.hourlyData?.values || sharedData.consumptionData?.hourlyData?.values,
      year: sharedData.analyticalPeriod?.start_datetime?.substring(0, 4) || new Date().getFullYear(),
      resolution: sharedData.analyticalPeriod?.interval_minutes === 15 ? '15min' : 'hourly',
      source: 'data-analysis',
      filename: sharedData.consumptionData?.filename
    });
  }

  // 3. Save PV profile if available
  if (sharedData.analysisResults?.pv_profile && sharedData.masterVariant?.capacity) {
    const pvValues = sharedData.analysisResults.pv_profile.map(v => v * sharedData.masterVariant.capacity);
    await saveProfileToDb(projectId, 'pv_generation', {
      values: pvValues,
      year: sharedData.analyticalPeriod?.start_datetime?.substring(0, 4) || new Date().getFullYear(),
      resolution: 'hourly',
      source: 'pv-calculation'
    });
  }

  // 4. Save analysis results as calculation
  if (sharedData.analysisResults) {
    await saveCalculationToDb(projectId, {
      calc_type: 'pv_sizing',
      service_name: 'pv-calculation',
      request: sharedData.pvConfig,
      result: {
        scenarios: sharedData.analysisResults.scenarios,
        key_variants: sharedData.analysisResults.key_variants,
        masterVariantKey: sharedData.masterVariantKey,
        masterVariant: sharedData.masterVariant
      }
    });
  }

  // 5. Save BESS/Profile analysis results
  if (sharedData.profileAnalysis?.bessData) {
    await saveCalculationToDb(projectId, {
      calc_type: 'bess_dispatch',
      service_name: 'bess-dispatch',
      request: {
        bess_power_kw: sharedData.profileAnalysis.bessData.bess_power_kw,
        bess_energy_kwh: sharedData.profileAnalysis.bessData.bess_energy_kwh,
        strategy: sharedData.profileAnalysis.bessData.strategy
      },
      result: sharedData.profileAnalysis.bessData
    });
  }

  // 6. Save economics results (legacy format for backwards compatibility)
  if (sharedData.economics) {
    await saveCalculationToDb(projectId, {
      calc_type: 'economics',
      service_name: 'economics',
      request: {
        variantKey: sharedData.economics.variantKey,
        bessIncluded: sharedData.economics.bessIncluded
      },
      result: sharedData.economics
    });
  }

  // 7. Save Economics Snapshot V2 (investor-ready format with margin data)
  if (sharedData.economics && sharedData.masterVariant) {
    await saveEconomicsSnapshotToDb(projectId);
  }

  console.log(`✅ All state saved to DB for project ${projectId}`);
}

// Load module into iframe
function loadModule(moduleName, event) {
  currentModule = moduleName;

  // Update active tab
  document.querySelectorAll('.main-tab').forEach(tab => {
    tab.classList.remove('active');
  });
  if (event && event.target) {
    event.target.classList.add('active');
  } else {
    // Find and activate the correct tab
    const tabs = document.querySelectorAll('.main-tab');
    tabs.forEach(tab => {
      if (tab.textContent.toLowerCase().includes(moduleName.substring(0, 4))) {
        tab.classList.add('active');
      }
    });
  }

  // Load module in iframe
  const iframe = document.getElementById('module-frame');
  iframe.src = MODULES[moduleName];

  // When iframe loads, send it ALL shared data immediately
  iframe.onload = () => {
    // Send ALL shared data to the module (proactive push)
    // This eliminates the need for module to REQUEST_SHARED_DATA
    iframe.contentWindow.postMessage({
      type: 'SHARED_DATA_RESPONSE',
      data: sharedData
    }, '*');
    console.log('📤 Sent all shared data to loaded module:', moduleName, {
      hasSettings: !!sharedData.settings,
      hasAnalysisResults: !!sharedData.analysisResults,
      hasConsumptionData: !!sharedData.consumptionData,
      hasPvConfig: !!sharedData.pvConfig
    });

    // Also send scenario separately (some modules expect this format)
    iframe.contentWindow.postMessage({
      type: 'SCENARIO_CHANGED',
      data: {
        scenario: sharedData.currentScenario,
        source: 'shell'
      }
    }, '*');
  };

  console.log(`Ładowanie modułu: ${moduleName} z ${MODULES[moduleName]}`);
}

// Check backend services health
async function checkBackendServices() {
  const statuses = {};
  let pvlibVersion = null;

  for (const [name, url] of Object.entries(BACKEND)) {
    try {
      const response = await fetch(`${url}/health`, {
        method: 'GET',
        mode: 'cors'
      });

      if (response.ok) {
        const data = await response.json();
        statuses[name] = 'healthy';

        // Check for pvlib in pvCalculation service
        if (name === 'pvCalculation' && data.pvlib_available) {
          pvlibVersion = data.pvlib_version;
        }
      } else {
        statuses[name] = 'unhealthy';
      }
    } catch (error) {
      statuses[name] = 'offline';
    }
  }

  const statusHTML = Object.entries(statuses)
    .map(([name, status]) => {
      const icon = status === 'healthy' ? '✓' : '⚠️';
      const color = status === 'healthy' ? '#00ff88' : '#ff0088';

      // Add pvlib version info for pvCalculation
      if (name === 'pvCalculation' && pvlibVersion) {
        return `<span style="color:${color}">${icon} ${name} (pvlib ${pvlibVersion})</span>`;
      }

      return `<span style="color:${color}">${icon} ${name}</span>`;
    })
    .join(' | ');

  document.getElementById('servicesStatus').innerHTML = statusHTML;
}

// Load scenario from localStorage
function loadScenarioFromShell() {
  const saved = localStorage.getItem('pv_current_scenario');
  if (saved && ['P50', 'P75', 'P90'].includes(saved)) {
    sharedData.currentScenario = saved;
    console.log('Scenario loaded from shell localStorage:', saved);
    return saved;
  }
  return 'P50';
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  checkBackendServices();

  // Load saved settings from shell's localStorage
  loadSettingsFromShell();

  // Load saved scenario from shell's localStorage
  loadScenarioFromShell();

  // Load current project from shell's localStorage
  loadCurrentProjectFromShell();

  // Initialize Draft Project Manager (Hybrid Workflow)
  // This will create/restore a draft project automatically
  await DraftProjectManager.init();

  // Load default module - Config
  const iframe = document.getElementById('module-frame');
  iframe.src = MODULES['config'];

  // When iframe loads, send it ALL shared data immediately
  iframe.onload = () => {
    // Send ALL shared data to the module (proactive push)
    iframe.contentWindow.postMessage({
      type: 'SHARED_DATA_RESPONSE',
      data: sharedData
    }, '*');
    console.log('📤 Sent all shared data to initial module (config)');

    // Also send scenario separately
    iframe.contentWindow.postMessage({
      type: 'SCENARIO_CHANGED',
      data: {
        scenario: sharedData.currentScenario,
        source: 'shell'
      }
    }, '*');
  };

  console.log('Ładowanie domyślnego modułu: Configuration');

  // Refresh health status every 30 seconds
  setInterval(checkBackendServices, 30000);
});

// Inter-module communication via postMessage
window.addEventListener('message', (event) => {
  // Validate origin - in proxy mode, all modules share the same origin as shell
  // In direct mode, modules have different ports/origins
  const shellOrigin = window.location.origin;
  const isValidOrigin = USE_PROXY
    ? event.origin === shellOrigin  // Proxy mode: all modules same origin
    : Object.values(MODULES).some(url => event.origin === new URL(url).origin);

  if (!isValidOrigin) {
    // Silently ignore invalid origins (e.g. react-devtools)
    return;
  }

  // Only log important messages, skip noise from devtools and frequent pings
  const msgType = event.data?.type;
  if (msgType && !['PING', 'HEARTBEAT'].includes(msgType) && !event.data?.source?.includes('devtools')) {
    console.log('Message from module:', msgType, event.data?.data ? '(has data)' : '');
  }

  // Handle different message types
  switch (event.data.type) {
    case 'NAVIGATE':
    case 'NAVIGATE_TO_MODULE':
      // Extract module name from data (support both formats)
      const targetModule = event.data.data?.module || event.data.module;
      if (targetModule && MODULES[targetModule]) {
        console.log('🧭 Navigating to module:', targetModule);
        loadModule(targetModule);
      } else {
        console.warn('⚠️ Unknown module requested:', targetModule);
      }
      break;
    case 'DATA_UPLOADED':
      // Store consumption data and fetch full hourly data for project storage
      if (event.data.data) {
        sharedData.consumptionData = event.data.data;
        DraftProjectManager.markChanged(); // Mark as having unsaved changes
        console.log('📊 Shell: consumptionData stored:', {
          dataPoints: event.data.data.dataPoints,
          annual_consumption_kwh: event.data.data.annual_consumption_kwh,
          total_consumption_gwh: event.data.data.total_consumption_gwh
        });

        // Store analytical period if present (new format)
        if (event.data.data.analyticalPeriod) {
          sharedData.analyticalPeriod = event.data.data.analyticalPeriod;
          // Also set deprecated analyticalYear for backward compatibility
          sharedData.analyticalYear = {
            start_date: event.data.data.analyticalPeriod.start_datetime?.split('T')[0],
            end_date: event.data.data.analyticalPeriod.end_datetime?.split('T')[0],
            total_hours: event.data.data.analyticalPeriod.period_hours,
            total_days: event.data.data.analyticalPeriod.period_days,
            is_complete: event.data.data.analyticalPeriod.is_full_year
          };
          console.log('📅 AnalyticalPeriod stored (Single Source of Truth):', sharedData.analyticalPeriod);
        }
        // Backward compatibility: convert old analytical_year to new format
        else if (event.data.data.analytical_year) {
          const oldFormat = event.data.data.analytical_year;
          sharedData.analyticalYear = oldFormat;
          // Convert to new format
          sharedData.analyticalPeriod = {
            start_datetime: oldFormat.start_date ? `${oldFormat.start_date}T00:00:00` : null,
            end_datetime: oldFormat.end_date ? `${oldFormat.end_date}T23:00:00` : null,
            interval_minutes: 60,
            n_points: oldFormat.total_hours || 8760,
            timezone: 'Europe/Warsaw',
            clock_mode: 'CET_FIXED',
            is_full_year: oldFormat.is_complete !== false,
            annualization_factor: oldFormat.is_complete !== false ? 1.0 : (8760 / (oldFormat.total_hours || 8760)),
            period_hours: oldFormat.total_hours || 8760,
            period_days: oldFormat.total_days || 365,
            source: 'legacy_conversion'
          };
          console.log('📅 Converted legacy analytical_year to analyticalPeriod:', sharedData.analyticalPeriod);
        }

        // Store raw load data for BESS calculations
        if (event.data.data.hourlyData?.values) {
          sharedData.loadData = event.data.data.hourlyData.values;
          console.log('📊 Shell: loadData stored:', sharedData.loadData.length, 'points');

          // *** AUTO-SAVE CONSUMPTION PROFILE TO DB ***
          if (sharedData.currentProject?.id) {
            saveProfileToDb(sharedData.currentProject.id, 'consumption', {
              values: sharedData.loadData,
              year: sharedData.analyticalPeriod?.start_datetime?.substring(0, 4) || new Date().getFullYear(),
              resolution: sharedData.analyticalPeriod?.interval_minutes === 15 ? '15min' : 'hourly',
              source: 'data-analysis-upload',
              filename: event.data.data.filename
            });
          }
        }

        // Fetch full hourly data from data-analysis for project storage
        fetchAndSaveFullConsumptionData();
      }
      // Broadcast to all modules
      broadcastToModules({ type: 'DATA_AVAILABLE', data: event.data.data });
      break;

    case 'ANALYTICAL_PERIOD_SET':
      // Config module has extracted/set the analytical period
      if (event.data.data) {
        sharedData.analyticalPeriod = event.data.data;
        // Also update deprecated analyticalYear for backward compatibility
        sharedData.analyticalYear = {
          start_date: event.data.data.start_datetime?.split('T')[0],
          end_date: event.data.data.end_datetime?.split('T')[0],
          total_hours: event.data.data.period_hours,
          total_days: event.data.data.period_days,
          is_complete: event.data.data.is_full_year
        };
        console.log('📅 AnalyticalPeriod updated from module:', {
          start: sharedData.analyticalPeriod.start_datetime,
          n_points: sharedData.analyticalPeriod.n_points,
          is_full_year: sharedData.analyticalPeriod.is_full_year,
          source: sharedData.analyticalPeriod.source
        });
        // Broadcast to all modules so they can update their time context
        broadcastToModules({
          type: 'ANALYTICAL_PERIOD_CHANGED',
          data: sharedData.analyticalPeriod
        });
      }
      break;

    case 'BESS_RESULT_SET':
      // Config module has received BESS sizing result - store as single source of truth
      if (event.data.data) {
        sharedData.bessResult = event.data.data;
        console.log('🔋 Shell: bessResult stored (Single Source of Truth):', {
          recommended_power_kw: event.data.data.recommended_power_kw,
          recommended_energy_kwh: event.data.data.recommended_energy_kwh,
          variants: event.data.data.variants?.length
        });
        // Broadcast to all modules
        broadcastToModules({
          type: 'BESS_RESULT_UPDATED',
          data: sharedData.bessResult
        });
      }
      break;
    case 'ANALYSIS_COMPLETE':
      // Store full analysis results
      if (event.data.data) {
        sharedData.analysisResults = event.data.data.fullResults;
        sharedData.pvConfig = event.data.data.pvConfig;
        sharedData.hourlyData = event.data.data.hourlyData;
        DraftProjectManager.markChanged(); // Mark as having unsaved changes

        // *** AUTO-SAVE PV ANALYSIS TO DB ***
        if (sharedData.currentProject?.id) {
          // Save PV sizing calculation
          saveCalculationToDb(sharedData.currentProject.id, {
            calc_type: 'pv_sizing',
            service_name: 'pv-calculation',
            request: sharedData.pvConfig,
            result: {
              scenarios: sharedData.analysisResults.scenarios,
              key_variants: sharedData.analysisResults.key_variants,
              annual_production_kwh: sharedData.analysisResults.scenarios?.[0]?.annual_production_kwh
            }
          });

          // Save settings with pvConfig
          if (sharedData.settings) {
            autoSaveToProject('settings', {
              ...sharedData.settings,
              pvConfig: sharedData.pvConfig
            });
          }
        }
      }
      // Broadcast complete data to all modules
      broadcastToModules({
        type: 'ANALYSIS_RESULTS',
        data: {
          ...event.data.data,
          sharedData: sharedData // Include all shared data
        }
      });
      break;
    case 'REQUEST_SHARED_DATA':
      // Module requests shared data - send it back
      console.log('📡 Shell responding to REQUEST_SHARED_DATA');
      console.log('📦 sharedData.hourlyData:', sharedData.hourlyData ? `Array(${sharedData.hourlyData.length})` : 'NULL');
      console.log('📦 sharedData.analysisResults:', sharedData.analysisResults ? 'EXISTS' : 'NULL');
      broadcastToModules({
        type: 'SHARED_DATA_RESPONSE',
        data: sharedData
      });
      break;
    case 'MASTER_VARIANT_SELECTED':
      // Store master variant selection
      if (event.data.data) {
        sharedData.masterVariant = event.data.data.variantData;
        sharedData.masterVariantKey = event.data.data.variantKey;
        // Auto-save to current project
        autoSaveToProject('masterVariant', {
          variantKey: event.data.data.variantKey,
          variantData: event.data.data.variantData
        });
      }
      // Broadcast to all modules
      broadcastToModules({
        type: 'MASTER_VARIANT_CHANGED',
        data: {
          variantKey: sharedData.masterVariantKey,
          variantData: sharedData.masterVariant
        }
      });
      console.log('Master variant updated:', sharedData.masterVariantKey);
      break;
    case 'PROFILE_ANALYSIS_COMPLETE':
      // Store BESS analysis results from Profile Analysis module
      if (event.data.data) {
        sharedData.profileAnalysis = event.data.data;
        DraftProjectManager.markChanged(); // Mark as having unsaved changes
        const bd = event.data.data.bessData;
        console.log('📊 Profile analysis stored (v2):', {
          schema_version: bd?.schema_version,
          bess_power_kw: bd?.bess_power_kw,
          bess_energy_kwh: bd?.bess_energy_kwh,
          annual_cycles: bd?.annual_cycles,
          annual_discharge_mwh: bd?.annual_discharge_mwh,
          strategy: bd?.strategy,
          annual_load_mwh: bd?.annual_load_mwh,
          dispatch_mode: bd?.dispatch_metadata?.dispatch_mode,
          savings_breakdown_source: bd?.savings_breakdown?.source,
        });

        // *** AUTO-SAVE BESS ANALYSIS TO DB ***
        if (sharedData.currentProject?.id && bd) {
          saveCalculationToDb(sharedData.currentProject.id, {
            calc_type: 'bess_dispatch',
            service_name: 'bess-dispatch',
            request: {
              bess_power_kw: bd.bess_power_kw,
              bess_energy_kwh: bd.bess_energy_kwh,
              strategy: bd.strategy
            },
            result: bd
          });
        }
      }
      // Broadcast to Economics and other modules
      broadcastToModules({
        type: 'PROFILE_ANALYSIS_UPDATED',
        data: sharedData.profileAnalysis
      });
      break;

    case 'BESS_SIZING_COMPLETE':
      // BESS PRO sizing complete - store and forward to Economics
      if (event.data.data) {
        sharedData.bessSizing = event.data.data;
        const bd = event.data.data.bessData;
        console.log('📊 BESS sizing stored (v2):', {
          schema_version: bd?.schema_version,
          bess_power_kw: bd?.bess_power_kw,
          bess_energy_kwh: bd?.bess_energy_kwh,
          savings_source: bd?.savings_breakdown?.source,
          dispatch_mode: bd?.dispatch_metadata?.dispatch_mode,
        });
        // Auto-save to current project
        autoSaveToProject('bessSizing', event.data.data);
      }
      // Broadcast to Economics (same format as PROFILE_ANALYSIS_UPDATED)
      broadcastToModules({
        type: 'BESS_SIZING_UPDATED',
        data: sharedData.bessSizing
      });
      break;

    case 'ECONOMICS_CALCULATED':
      // Store economics data from Economics module
      if (event.data.data) {
        sharedData.economics = event.data.data;
        DraftProjectManager.markChanged(); // Mark as having unsaved changes
        console.log('Economics data stored:', {
          variantKey: event.data.data.variantKey,
          eaasPhaseSavings: event.data.data.eaasPhaseSavings,
          ownershipPhaseSavings: event.data.data.ownershipPhaseSavings
        });

        // *** AUTO-SAVE ECONOMICS TO DB ***
        if (sharedData.currentProject?.id) {
          saveCalculationToDb(sharedData.currentProject.id, {
            calc_type: 'economics',
            service_name: 'economics',
            request: {
              variantKey: event.data.data.variantKey,
              bessIncluded: event.data.data.bessIncluded,
              scenario: sharedData.currentScenario
            },
            result: event.data.data
          });
        }
      }
      // Broadcast to other modules (e.g., Reports)
      broadcastToModules({
        type: 'ECONOMICS_UPDATED',
        data: sharedData.economics
      });
      break;
    case 'DATA_CLEARED':
      // Clear all shared data (preserve settings and scenario)
      const savedSettings = sharedData.settings;
      const savedScenario = sharedData.currentScenario;
      sharedData = {
        analysisResults: null,
        pvConfig: null,
        consumptionData: null,
        hourlyData: null,
        masterVariant: null,
        masterVariantKey: null,
        economics: null,
        settings: savedSettings,
        currentScenario: savedScenario
      };
      // Broadcast to all modules
      broadcastToModules({ type: 'DATA_CLEARED' });
      console.log('All shared data cleared (settings and scenario preserved)');
      break;
    case 'SETTINGS_CHANGED':
      // Store settings in shell's localStorage and memory
      saveSettingsToShell(event.data.data);
      // Auto-save to current project
      autoSaveToProject('settings', event.data.data);
      // Broadcast to all modules
      broadcastToModules({
        type: 'SETTINGS_UPDATED',
        data: event.data.data
      });
      console.log('Settings updated and saved:', event.data.data);
      break;
    case 'REQUEST_SETTINGS':
      // Module requests current settings
      if (sharedData.settings) {
        broadcastToModules({
          type: 'SETTINGS_UPDATED',
          data: sharedData.settings
        });
        console.log('Sent settings on request');
      }
      break;
    case 'PRODUCTION_SCENARIO_CHANGED':
      // Store production scenario and broadcast to all modules
      if (event.data.data) {
        sharedData.currentScenario = event.data.data.scenario;
        // Save to localStorage for persistence
        localStorage.setItem('pv_current_scenario', event.data.data.scenario);
        // Auto-save to current project
        autoSaveToProject('currentScenario', { scenario: event.data.data.scenario });
        // Broadcast to all modules (including Economics)
        broadcastToModules({
          type: 'SCENARIO_CHANGED',
          data: {
            scenario: event.data.data.scenario,
            source: event.data.data.source || 'production'
          }
        });
        console.log('Production scenario changed:', event.data.data.scenario);
      }
      break;
    case 'REQUEST_SCENARIO':
      // Module requests current scenario
      broadcastToModules({
        type: 'SCENARIO_CHANGED',
        data: {
          scenario: sharedData.currentScenario,
          source: 'shell'
        }
      });
      console.log('Sent current scenario on request:', sharedData.currentScenario);
      break;
    case 'PV_TYPE_CHANGED':
      // Store PV type and broadcast to all modules (especially Economics)
      if (event.data.data) {
        const newPvType = event.data.data.pvType || event.data.data.pv_type;
        console.log('📋 PV type changed to:', newPvType);

        // Update pvConfig with new type
        if (!sharedData.pvConfig) {
          sharedData.pvConfig = {};
        }
        sharedData.pvConfig.pvType = newPvType;
        sharedData.pvConfig.pv_type = newPvType;

        // Auto-save to current project
        autoSaveToProject('pvConfig', sharedData.pvConfig);

        // Broadcast to all modules so they can update CAPEX calculations
        broadcastToModules({
          type: 'PV_TYPE_UPDATED',
          data: {
            pvType: newPvType,
            pv_type: newPvType,
            pvConfig: sharedData.pvConfig
          }
        });
        console.log('📢 Broadcasted PV type change to all modules:', newPvType);
      }
      break;

    // ============== Project Management Messages ==============
    case 'PROJECT_CREATED':
      // New project created
      if (event.data.data) {
        sharedData.currentProject = {
          id: event.data.data.projectId,
          name: event.data.data.projectName,
          client: event.data.data.clientName
        };
        localStorage.setItem('pv_current_project', JSON.stringify(sharedData.currentProject));
        console.log('Project created and set as current:', sharedData.currentProject);
        // Broadcast to all modules
        broadcastToModules({
          type: 'PROJECT_CHANGED',
          data: sharedData.currentProject
        });
      }
      break;

    case 'PROJECT_LOAD_REQUEST':
      // Load project data into shared state
      if (event.data.data) {
        const projectData = event.data.data;

        // Update current project info
        sharedData.currentProject = {
          id: projectData.projectId,
          name: projectData.projectName,
          client: projectData.clientName
        };
        localStorage.setItem('pv_current_project', JSON.stringify(sharedData.currentProject));

        // Load all data from project
        if (projectData.consumptionData) {
          sharedData.consumptionData = projectData.consumptionData;
        }
        if (projectData.pvConfig) {
          sharedData.pvConfig = projectData.pvConfig;
        }
        if (projectData.analysisResults) {
          sharedData.analysisResults = projectData.analysisResults;
        }
        if (projectData.hourlyData) {
          sharedData.hourlyData = projectData.hourlyData;
        }
        if (projectData.settings) {
          sharedData.settings = projectData.settings;
          saveSettingsToShell(projectData.settings);
        }
        if (projectData.economics) {
          sharedData.economics = projectData.economics;
        }
        if (projectData.masterVariant) {
          // masterVariant jest zapisany jako {variantKey, variantData}
          // Musimy rozdzielić te dane poprawnie
          if (projectData.masterVariant.variantData) {
            sharedData.masterVariant = projectData.masterVariant.variantData;
            sharedData.masterVariantKey = projectData.masterVariant.variantKey || null;
          } else {
            // Fallback: jeśli struktura jest inna (bezpośrednio dane wariantu)
            sharedData.masterVariant = projectData.masterVariant;
            sharedData.masterVariantKey = projectData.masterVariant.variantKey || null;
          }
          console.log('📊 masterVariant loaded:', {
            key: sharedData.masterVariantKey,
            data: sharedData.masterVariant
          });
        }
        if (projectData.currentScenario) {
          sharedData.currentScenario = projectData.currentScenario;
          localStorage.setItem('pv_current_scenario', projectData.currentScenario);
        }

        console.log('Project loaded into sharedData:', sharedData.currentProject);

        // KLUCZOWE: Przywróć dane zużycia do data-analysis service
        // Bez tego moduły nie będą mogły wykonać analiz
        if (projectData.rawConsumptionData) {
          console.log('🔄 Restoring raw consumption data to data-analysis service...');
          restoreConsumptionData(projectData.rawConsumptionData).then(success => {
            if (success) {
              console.log('✅ Consumption data restored to data-analysis');
              // Broadcast that data is available
              broadcastToModules({ type: 'DATA_AVAILABLE', data: sharedData.consumptionData });
            } else {
              console.error('❌ Failed to restore consumption data');
            }
          });
        }

        // Broadcast loaded data to all modules
        broadcastToModules({
          type: 'PROJECT_LOADED',
          data: {
            projectId: projectData.projectId,
            projectName: projectData.projectName,
            clientName: projectData.clientName
          }
        });

        // Send shared data to modules so they can refresh
        broadcastToModules({
          type: 'SHARED_DATA_RESPONSE',
          data: sharedData
        });

        // If we have analysis results, notify modules
        if (sharedData.analysisResults) {
          broadcastToModules({
            type: 'ANALYSIS_RESULTS',
            data: {
              fullResults: sharedData.analysisResults,
              pvConfig: sharedData.pvConfig,
              hourlyData: sharedData.hourlyData,
              sharedData: sharedData
            }
          });
        }

        // Send settings update
        if (sharedData.settings) {
          broadcastToModules({
            type: 'SETTINGS_UPDATED',
            data: sharedData.settings
          });
        }

        // Send scenario update
        broadcastToModules({
          type: 'SCENARIO_CHANGED',
          data: {
            scenario: sharedData.currentScenario,
            source: 'shell'
          }
        });
      }
      break;

    case 'REQUEST_PROJECT':
      // Module requests current project info
      broadcastToModules({
        type: 'PROJECT_CHANGED',
        data: sharedData.currentProject
      });
      break;

    case 'REQUEST_PV_DATA':
      // Profile module requests hourly PV generation data
      console.log('📊 Shell responding to REQUEST_PV_DATA');
      console.log('  - masterVariantKey:', sharedData.masterVariantKey);
      console.log('  - masterVariant?.capacity:', sharedData.masterVariant?.capacity);
      let pvHourlyGeneration = null;
      let pvCapacityUsed = null;

      // PRIORITY 1: Use masterVariant data (user's selected variant!)
      // This MUST come first - we always want to use the variant the user selected
      if (sharedData.masterVariant?.capacity) {
        pvCapacityUsed = sharedData.masterVariant.capacity;
        console.log(`  ✓ PRIORITY 1: masterVariant.capacity = ${pvCapacityUsed} kWp`);

        // Check if masterVariant has hourly_production
        if (sharedData.masterVariant.hourly_production?.length > 0) {
          pvHourlyGeneration = sharedData.masterVariant.hourly_production;
          console.log(`  ✓ Using masterVariant.hourly_production: ${pvHourlyGeneration.length} values`);
        }
      }

      // PRIORITY 2: Try key_variants with masterVariantKey
      if (!pvHourlyGeneration && sharedData.masterVariantKey && sharedData.analysisResults?.key_variants) {
        const masterData = sharedData.analysisResults.key_variants[sharedData.masterVariantKey];
        if (masterData) {
          if (!pvCapacityUsed) {
            pvCapacityUsed = masterData.capacity;
            console.log(`  ✓ PRIORITY 2: key_variants[${sharedData.masterVariantKey}].capacity = ${pvCapacityUsed} kWp`);
          }
          if (masterData.hourly_production?.length > 0) {
            pvHourlyGeneration = masterData.hourly_production;
            console.log(`  ✓ Using key_variants[${sharedData.masterVariantKey}].hourly_production: ${pvHourlyGeneration.length} values`);
          }
        }
      }

      // PRIORITY 3: Calculate from pv_profile * capacity
      // pv_profile is NORMALIZED per 1 kWp, so multiply by capacity to get actual kWh
      // This is the CORRECT way - never use pre-scaled hourly_production!
      if (!pvHourlyGeneration && sharedData.analysisResults?.pv_profile?.length > 0) {
        const pvProfile = sharedData.analysisResults.pv_profile;

        // Get capacity - MUST have it from masterVariant or key_variants
        let capacity = pvCapacityUsed;

        // If no capacity yet, try to find it
        if (!capacity) {
          // Try key_variants with masterVariantKey
          if (sharedData.masterVariantKey && sharedData.analysisResults.key_variants) {
            capacity = sharedData.analysisResults.key_variants[sharedData.masterVariantKey]?.capacity;
            if (capacity) console.log(`  - Found capacity from key_variants[${sharedData.masterVariantKey}]: ${capacity} kWp`);
          }
          // Try pvConfig
          if (!capacity && sharedData.pvConfig?.capacity) {
            capacity = sharedData.pvConfig.capacity;
            console.log(`  - Found capacity from pvConfig: ${capacity} kWp`);
          }
          // LAST RESORT: first scenario (with warning)
          if (!capacity && sharedData.analysisResults.scenarios?.length > 0) {
            capacity = sharedData.analysisResults.scenarios[0].capacity;
            console.log(`  ⚠️ WARNING: Using first scenario capacity: ${capacity} kWp`);
            console.log(`  ⚠️ This may not match your selected variant! Please select a master variant.`);
          }
        }

        if (capacity && pvProfile.length > 0) {
          pvHourlyGeneration = pvProfile.map(v => v * capacity);
          pvCapacityUsed = capacity;
          console.log(`  ✓ PRIORITY 3: Calculated from pv_profile * ${capacity} kWp: ${pvHourlyGeneration.length} values`);

          // Verify sum
          const totalMWh = pvHourlyGeneration.reduce((a, b) => a + b, 0) / 1000;
          console.log(`  ✓ Total annual production: ${totalMWh.toFixed(1)} MWh`);
        } else {
          console.log(`  ❌ ERROR: Cannot calculate PV data - no capacity available`);
          console.log(`  ❌ Please select a master variant in PORÓWNANIE WYNIKÓW`);
        }
      }

      // NOTE: We intentionally do NOT use analysisResults.hourly_production as fallback
      // because it is pre-scaled for a specific scenario capacity, not the masterVariant!

      broadcastToModules({
        type: 'PV_DATA_RESPONSE',
        data: {
          hourly_generation: pvHourlyGeneration || [],
          capacity_kwp: pvCapacityUsed
        }
      });
      console.log(`📤 Sent PV_DATA_RESPONSE: ${pvHourlyGeneration?.length || 0} values, capacity: ${pvCapacityUsed || 'unknown'} kWp`);
      break;

    case 'REQUEST_LOAD_DATA':
      // Profile module requests hourly consumption data
      console.log('📊 Shell responding to REQUEST_LOAD_DATA');
      let loadHourlyConsumption = null;

      if (sharedData.hourlyData?.values) {
        loadHourlyConsumption = sharedData.hourlyData.values;
        console.log(`  - Using hourlyData.values: ${loadHourlyConsumption.length} values`);
      }

      broadcastToModules({
        type: 'LOAD_DATA_RESPONSE',
        data: {
          hourly_consumption: loadHourlyConsumption || []
        }
      });
      console.log(`📤 Sent LOAD_DATA_RESPONSE: ${loadHourlyConsumption?.length || 0} values`);
      break;

    case 'REQUEST_ANALYSIS_RESULTS':
      // Profile module requests analysis results for config population
      console.log('📊 Shell responding to REQUEST_ANALYSIS_RESULTS');
      console.log('  - masterVariantKey:', sharedData.masterVariantKey);
      console.log('  - masterVariant.capacity:', sharedData.masterVariant?.capacity);
      console.log('  - analyticalYear:', sharedData.analyticalYear);
      broadcastToModules({
        type: 'ANALYSIS_RESULTS',
        data: {
          fullResults: sharedData.analysisResults,
          pvConfig: sharedData.pvConfig,
          hourlyData: sharedData.hourlyData,
          scenarios: sharedData.analysisResults?.scenarios || [],
          // Include master variant data directly for easy access
          masterVariant: sharedData.masterVariant,
          masterVariantKey: sharedData.masterVariantKey,
          // Include analytical year for correct month mapping
          analyticalYear: sharedData.analyticalYear,
          sharedData: sharedData
        }
      });
      break;
  }
});

/**
 * Get the target origin for postMessage based on current module.
 * In proxy mode, all modules are same-origin.
 * In direct mode, each module has its own port.
 */
function getModuleOrigin(moduleName) {
  if (USE_PROXY) {
    // All modules served from same origin via nginx proxy
    return window.location.origin;
  }
  // Direct port access - construct origin from module URL
  const moduleUrl = MODULES[moduleName || currentModule];
  if (moduleUrl && moduleUrl.startsWith('http')) {
    const url = new URL(moduleUrl);
    return url.origin;
  }
  return '*'; // Fallback for relative URLs
}

/**
 * Post message to the currently active module iframe.
 * Note: This is NOT a true broadcast to multiple modules.
 * Only the currently loaded module in 'module-frame' receives the message.
 * Other modules will request data via REQUEST_SHARED_DATA when they load.
 *
 * Security: Uses specific targetOrigin instead of '*' to prevent message leakage.
 */
function postToActiveModule(message) {
  const iframe = document.getElementById('module-frame');
  if (iframe && iframe.contentWindow) {
    const targetOrigin = getModuleOrigin(currentModule);
    iframe.contentWindow.postMessage(message, targetOrigin);
  }
}

// Legacy alias for backward compatibility
const broadcastToModules = postToActiveModule;
