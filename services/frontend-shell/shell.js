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
  projectsDb: '/api/projects'
} : {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002',
  economics: 'http://localhost:8003',
  advancedAnalytics: 'http://localhost:8004',
  typicalDays: 'http://localhost:8005',
  energyPrices: 'http://localhost:8010',
  reports: 'http://localhost:8011',
  projectsDb: 'http://localhost:8012'
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

// ============== Auto-save to current project ==============
async function autoSaveToProject(dataType, data) {
  // Only save if we have a current project
  if (!sharedData.currentProject || !sharedData.currentProject.id) {
    console.log(`Auto-save skipped (no current project): ${dataType}`);
    return;
  }

  try {
    const response = await fetch(`${BACKEND.projectsDb}/projects/${sharedData.currentProject.id}/data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data_type: dataType,
        data: data
      })
    });

    const result = await response.json();
    if (result.success) {
      console.log(`✅ Auto-saved ${dataType} to project ${sharedData.currentProject.id}`);
    } else {
      console.error(`❌ Failed to auto-save ${dataType}:`, result);
    }
  } catch (error) {
    console.error(`❌ Error auto-saving ${dataType}:`, error);
  }
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
document.addEventListener('DOMContentLoaded', () => {
  checkBackendServices();

  // Load saved settings from shell's localStorage
  loadSettingsFromShell();

  // Load saved scenario from shell's localStorage
  loadScenarioFromShell();

  // Load current project from shell's localStorage
  loadCurrentProjectFromShell();

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
        // Auto-save all analysis data to current project
        autoSaveToProject('analysisResults', event.data.data.fullResults);
        autoSaveToProject('pvConfig', event.data.data.pvConfig);
        autoSaveToProject('hourlyData', event.data.data.hourlyData);
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
        // Auto-save to current project
        autoSaveToProject('profileAnalysis', event.data.data);
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
        console.log('Economics data stored:', {
          variantKey: event.data.data.variantKey,
          eaasPhaseSavings: event.data.data.eaasPhaseSavings,
          ownershipPhaseSavings: event.data.data.ownershipPhaseSavings
        });
        // Auto-save to current project
        autoSaveToProject('economics', event.data.data);
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
