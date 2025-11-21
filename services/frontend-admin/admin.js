// API Configuration
const API = {
  dataAnalysis: 'http://localhost:8001',
  pvCalculation: 'http://localhost:8002',
  economics: 'http://localhost:8003',
  advancedAnalytics: 'http://localhost:8004',
  typicalDays: 'http://localhost:8005'
};

// Service definitions
const SERVICES = [
  { name: 'Data Analysis', url: API.dataAnalysis, port: 8001 },
  { name: 'PV Calculation', url: API.pvCalculation, port: 8002 },
  { name: 'Economics', url: API.economics, port: 8003 },
  { name: 'Advanced Analytics', url: API.advancedAnalytics, port: 8004 },
  { name: 'Typical Days', url: API.typicalDays, port: 8005 }
];

// Logging
function addLog(message, type = 'info') {
  const logsContainer = document.getElementById('systemLogs');
  const logEntry = document.createElement('div');
  logEntry.className = `log-entry ${type}`;
  logEntry.setAttribute('data-time', new Date().toLocaleTimeString('pl-PL'));
  logEntry.textContent = message;
  logsContainer.appendChild(logEntry);
  logsContainer.scrollTop = logsContainer.scrollHeight;
}

// Check backend service health
async function checkServiceHealth(service) {
  try {
    const response = await fetch(`${service.url}/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(5000)
    });
    return response.ok;
  } catch (error) {
    return false;
  }
}

// Refresh all services status
async function refreshServices() {
  const servicesContainer = document.getElementById('servicesStatus');
  servicesContainer.innerHTML = '<div class="service-item loading">Checking services...</div>';

  addLog('Refreshing backend services status...', 'info');

  const results = await Promise.all(
    SERVICES.map(async (service) => {
      const isOnline = await checkServiceHealth(service);
      return { ...service, isOnline };
    })
  );

  servicesContainer.innerHTML = '';
  let onlineCount = 0;

  results.forEach(service => {
    const serviceItem = document.createElement('div');
    serviceItem.className = `service-item ${service.isOnline ? 'online' : 'offline'}`;
    serviceItem.innerHTML = `
      <div>
        <div class="service-name">${service.name}</div>
        <div class="service-url">${service.url}</div>
      </div>
      <div class="service-status ${service.isOnline ? 'online' : 'offline'}">
        ${service.isOnline ? 'ONLINE' : 'OFFLINE'}
      </div>
    `;
    servicesContainer.appendChild(serviceItem);

    if (service.isOnline) {
      onlineCount++;
      addLog(`${service.name} is online`, 'success');
    } else {
      addLog(`${service.name} is offline`, 'error');
    }

    // Update API endpoint status
    const statusElement = document.getElementById(`api-status-${service.port}`);
    if (statusElement) {
      statusElement.textContent = service.isOnline ? 'ONLINE' : 'OFFLINE';
      statusElement.className = `endpoint-status ${service.isOnline ? 'online' : 'offline'}`;
    }
  });

  // Update backend count
  document.getElementById('backendCount').textContent = onlineCount;

  // Update system status
  const systemStatus = document.getElementById('systemStatus');
  const statusText = document.getElementById('statusText');
  if (onlineCount === SERVICES.length) {
    systemStatus.className = 'status-dot healthy';
    statusText.textContent = 'All Systems Operational';
  } else if (onlineCount > 0) {
    systemStatus.className = 'status-dot warning';
    statusText.textContent = `${onlineCount}/${SERVICES.length} Services Online`;
  } else {
    systemStatus.className = 'status-dot error';
    statusText.textContent = 'All Services Offline';
  }

  updateDataManagement();
}

// Update data management section
function updateDataManagement() {
  const consumptionData = localStorage.getItem('consumptionData');
  const analysisResults = localStorage.getItem('analysisResults');
  const pvConfig = localStorage.getItem('pvConfig');

  const dataStatus = document.getElementById('dataStatus');
  const resultsStatus = document.getElementById('resultsStatus');
  const configCount = document.getElementById('configCount');

  if (consumptionData) {
    dataStatus.textContent = 'Loaded';
    dataStatus.className = 'badge success';
    try {
      const data = JSON.parse(consumptionData);
      dataStatus.textContent = `Loaded (${data.dataPoints || 'N/A'} points)`;
    } catch (e) {
      dataStatus.textContent = 'Loaded (Invalid)';
      dataStatus.className = 'badge warning';
    }
  } else {
    dataStatus.textContent = 'Not Loaded';
    dataStatus.className = 'badge';
  }

  if (analysisResults) {
    resultsStatus.textContent = 'Available';
    resultsStatus.className = 'badge success';
  } else {
    resultsStatus.textContent = 'Not Available';
    resultsStatus.className = 'badge';
  }

  if (pvConfig) {
    configCount.textContent = '1';
    configCount.className = 'badge success';
  } else {
    configCount.textContent = '0';
    configCount.className = 'badge';
  }
}

// Export configuration
function exportConfig() {
  const config = {
    pvConfig: localStorage.getItem('pvConfig'),
    consumptionData: localStorage.getItem('consumptionData'),
    analysisResults: localStorage.getItem('analysisResults'),
    exportDate: new Date().toISOString()
  };

  const dataStr = JSON.stringify(config, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(dataBlob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `pv-config-${new Date().toISOString().split('T')[0]}.json`;
  link.click();

  URL.revokeObjectURL(url);
  addLog('Configuration exported successfully', 'success');
}

// Import configuration
function importConfig() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';

  input.onchange = (e) => {
    const file = e.target.files[0];
    const reader = new FileReader();

    reader.onload = (event) => {
      try {
        const config = JSON.parse(event.target.result);

        if (config.pvConfig) localStorage.setItem('pvConfig', config.pvConfig);
        if (config.consumptionData) localStorage.setItem('consumptionData', config.consumptionData);
        if (config.analysisResults) localStorage.setItem('analysisResults', config.analysisResults);

        addLog('Configuration imported successfully', 'success');
        updateDataManagement();

        // Notify other modules
        notifyShell('CONFIG_IMPORTED', { timestamp: new Date().toISOString() });
      } catch (error) {
        addLog(`Import failed: ${error.message}`, 'error');
        alert('Failed to import configuration. Please check the file format.');
      }
    };

    reader.readAsText(file);
  };

  input.click();
}

// Clear all data
function clearAllData() {
  if (confirm('Are you sure you want to clear all data? This action cannot be undone.')) {
    localStorage.removeItem('pvConfig');
    localStorage.removeItem('consumptionData');
    localStorage.removeItem('analysisResults');

    addLog('All data cleared', 'warning');
    updateDataManagement();

    // Notify other modules
    notifyShell('DATA_CLEARED', { timestamp: new Date().toISOString() });

    alert('All data has been cleared successfully.');
  }
}

// View storage details
function viewStorageDetails() {
  const modal = document.getElementById('storageModal');
  const detailsElement = document.getElementById('storageDetails');

  const storageData = {
    pvConfig: localStorage.getItem('pvConfig'),
    consumptionData: localStorage.getItem('consumptionData') ? 'Present (hidden for brevity)' : null,
    analysisResults: localStorage.getItem('analysisResults') ? 'Present (hidden for brevity)' : null,
    totalKeys: localStorage.length,
    estimatedSize: new Blob(Object.values(localStorage)).size + ' bytes'
  };

  detailsElement.textContent = JSON.stringify(storageData, null, 2);
  modal.classList.add('active');

  addLog('Storage details viewed', 'info');
}

// Close modal
function closeModal() {
  const modal = document.getElementById('storageModal');
  modal.classList.remove('active');
}

// Clear logs
function clearLogs() {
  const logsContainer = document.getElementById('systemLogs');
  logsContainer.innerHTML = '<div class="log-entry info">Logs cleared</div>';
}

// Notify parent shell
function notifyShell(type, data) {
  if (window.parent !== window) {
    window.parent.postMessage({ type, data }, '*');
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  switch (event.data.type) {
    case 'DATA_UPLOADED':
      addLog(`Data uploaded: ${event.data.data.filename}`, 'success');
      updateDataManagement();
      break;
    case 'ANALYSIS_COMPLETE':
      addLog('Analysis completed', 'success');
      updateDataManagement();
      break;
    case 'DATA_CLEARED':
      addLog('Data cleared from another module', 'warning');
      updateDataManagement();
      break;
  }
});

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  addLog('Admin module initialized', 'success');
  refreshServices();
  updateDataManagement();

  // Auto-refresh services every 30 seconds
  setInterval(refreshServices, 30000);
});
