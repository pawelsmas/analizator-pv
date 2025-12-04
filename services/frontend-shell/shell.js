// Micro-Frontend Shell - Routes to individual modules

// Proxy mode: use path-based routing via nginx reverse proxy
// When USE_PROXY=true, all URLs use /modules/* and /api/* paths
// When USE_PROXY=false, direct port access for development
const USE_PROXY = false; // TODO: Set to true for production with nginx reverse proxy

// Module URLs
const MODULES = USE_PROXY ? {
  admin: '/modules/admin/',
  config: '/modules/config/',
  consumption: '/modules/consumption/',
  production: '/modules/production/',
  comparison: '/modules/comparison/',
  economics: '/modules/economics/',
  settings: '/modules/settings/',
  esg: '/modules/esg/',
  energyprices: '/modules/energyprices/',
  reports: '/modules/reports/',
  projects: '/modules/projects/',
  estimator: '/modules/estimator/'
} : {
  admin: 'http://localhost:9001',
  config: 'http://localhost:9002',
  consumption: 'http://localhost:9003',
  production: 'http://localhost:9004',
  comparison: 'http://localhost:9005',
  economics: 'http://localhost:9006',
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
  // Data coverage metadata - indicates actual data range (may be <8760h)
  analyticalYear: null // { start_date, end_date, total_hours, total_days, is_complete }
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

  // When iframe loads, send it the current settings and scenario
  iframe.onload = () => {
    if (sharedData.settings) {
      iframe.contentWindow.postMessage({
        type: 'SETTINGS_UPDATED',
        data: sharedData.settings
      }, '*');
      console.log('Sent settings to loaded module:', moduleName);
    }
    // Send current scenario to module
    iframe.contentWindow.postMessage({
      type: 'SCENARIO_CHANGED',
      data: {
        scenario: sharedData.currentScenario,
        source: 'shell'
      }
    }, '*');
    console.log('Sent scenario to loaded module:', moduleName, sharedData.currentScenario);
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

  // When iframe loads, send it the current settings and scenario
  iframe.onload = () => {
    if (sharedData.settings) {
      iframe.contentWindow.postMessage({
        type: 'SETTINGS_UPDATED',
        data: sharedData.settings
      }, '*');
      console.log('Sent settings to initial module');
    }
    // Send current scenario to module
    iframe.contentWindow.postMessage({
      type: 'SCENARIO_CHANGED',
      data: {
        scenario: sharedData.currentScenario,
        source: 'shell'
      }
    }, '*');
    console.log('Sent scenario to initial module:', sharedData.currentScenario);
  };

  console.log('Ładowanie domyślnego modułu: Configuration');

  // Refresh health status every 30 seconds
  setInterval(checkBackendServices, 30000);
});

// Inter-module communication via postMessage
window.addEventListener('message', (event) => {
  // Validate origin
  const validOrigins = Object.values(MODULES);
  if (!validOrigins.includes(event.origin)) {
    return;
  }

  console.log('Message from module:', event.data);

  // Handle different message types
  switch (event.data.type) {
    case 'NAVIGATE':
      // Extract module name from data
      const targetModule = event.data.data?.module || event.data.module;
      if (targetModule && MODULES[targetModule]) {
        loadModule(targetModule);
      }
      break;
    case 'DATA_UPLOADED':
      // Store consumption data and fetch full hourly data for project storage
      if (event.data.data) {
        sharedData.consumptionData = event.data.data;

        // Store analytical year metadata if present
        if (event.data.data.analytical_year) {
          sharedData.analyticalYear = event.data.data.analytical_year;
          console.log('📅 Analytical year stored:', sharedData.analyticalYear);
        }

        // Fetch full hourly data from data-analysis for project storage
        fetchAndSaveFullConsumptionData();
      }
      // Broadcast to all modules
      broadcastToModules({ type: 'DATA_AVAILABLE', data: event.data.data });
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
