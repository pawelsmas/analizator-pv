// Micro-Frontend Shell - Routes to individual modules

// Module URLs (running on different ports)
const MODULES = {
  admin: 'http://localhost:9001',
  config: 'http://localhost:9002',
  consumption: 'http://localhost:9003',
  production: 'http://localhost:9004',
  comparison: 'http://localhost:9005',
  economics: 'http://localhost:9006',
  settings: 'http://localhost:9007',
  insights: 'http://localhost:9008',
  energyprices: 'http://localhost:9009',
  reports: 'http://localhost:9010'
};

// Backend services
const BACKEND = {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002',
  economics: 'http://localhost:8003',
  advancedAnalytics: 'http://localhost:8004',
  typicalDays: 'http://localhost:8005',
  energyPrices: 'http://localhost:8010',
  reports: 'http://localhost:8011'
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
  settings: null // System settings from Settings module
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

  // When iframe loads, send it the current settings
  iframe.onload = () => {
    if (sharedData.settings) {
      iframe.contentWindow.postMessage({
        type: 'SETTINGS_UPDATED',
        data: sharedData.settings
      }, '*');
      console.log('Sent settings to loaded module:', moduleName);
    }
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

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  checkBackendServices();

  // Load saved settings from shell's localStorage
  loadSettingsFromShell();

  // Load default module - Config
  const iframe = document.getElementById('module-frame');
  iframe.src = MODULES['config'];

  // When iframe loads, send it the current settings
  iframe.onload = () => {
    if (sharedData.settings) {
      iframe.contentWindow.postMessage({
        type: 'SETTINGS_UPDATED',
        data: sharedData.settings
      }, '*');
      console.log('Sent settings to initial module');
    }
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
      // Store consumption data
      if (event.data.data) {
        sharedData.consumptionData = event.data.data;
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
    case 'DATA_CLEARED':
      // Clear all shared data
      sharedData = {
        analysisResults: null,
        pvConfig: null,
        consumptionData: null,
        hourlyData: null,
        masterVariant: null,
        masterVariantKey: null
      };
      // Broadcast to all modules
      broadcastToModules({ type: 'DATA_CLEARED' });
      console.log('All shared data cleared');
      break;
    case 'SETTINGS_CHANGED':
      // Store settings in shell's localStorage and memory
      saveSettingsToShell(event.data.data);
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
  }
});

// Broadcast message to all modules
function broadcastToModules(message) {
  const iframe = document.getElementById('module-frame');
  if (iframe.contentWindow) {
    iframe.contentWindow.postMessage(message, '*');
  }
}
