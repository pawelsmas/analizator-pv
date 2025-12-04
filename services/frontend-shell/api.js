/**
 * PV Optimizer - Centralized API Client
 *
 * All backend calls go through /api/* routes which nginx proxies to appropriate services.
 * This eliminates hardcoded localhost:PORT references and CORS issues.
 *
 * Usage in modules:
 *   const data = await API.dataAnalysis.getStatistics();
 *   const result = await API.pvCalculation.analyze(payload);
 */

// Base API paths (nginx reverse proxy routes)
const API_BASE = {
  dataAnalysis: '/api/data',
  pvCalculation: '/api/pv',
  economics: '/api/economics',
  advancedAnalytics: '/api/analytics',
  typicalDays: '/api/typical-days',
  energyPrices: '/api/energy-prices',
  reports: '/api/reports',
  projectsDb: '/api/projects',
  pvgisProxy: '/api/pvgis',
  geo: '/api/geo'
};

// Helper function for fetch with error handling
async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`API Error ${response.status}: ${error}`);
  }

  return response.json();
}

// Data Analysis Service API
const dataAnalysisAPI = {
  health: () => fetchJSON(`${API_BASE.dataAnalysis}/health`),
  uploadCSV: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${API_BASE.dataAnalysis}/upload/csv`, {
      method: 'POST',
      body: formData
    });
    if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
    return response.json();
  },
  uploadExcel: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${API_BASE.dataAnalysis}/upload/excel`, {
      method: 'POST',
      body: formData
    });
    if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
    return response.json();
  },
  getStatistics: () => fetchJSON(`${API_BASE.dataAnalysis}/statistics`),
  getHourlyData: () => fetchJSON(`${API_BASE.dataAnalysis}/hourly-data`),
  getHeatmap: () => fetchJSON(`${API_BASE.dataAnalysis}/heatmap`),
  getSeasonality: () => fetchJSON(`${API_BASE.dataAnalysis}/seasonality`),
  getAnalyticalYear: () => fetchJSON(`${API_BASE.dataAnalysis}/analytical-year`),
  exportData: () => fetchJSON(`${API_BASE.dataAnalysis}/export-data`),
  restoreData: (data) => fetchJSON(`${API_BASE.dataAnalysis}/restore-data`, {
    method: 'POST',
    body: JSON.stringify(data)
  })
};

// PV Calculation Service API
const pvCalculationAPI = {
  health: () => fetchJSON(`${API_BASE.pvCalculation}/health`),
  analyze: (payload) => fetchJSON(`${API_BASE.pvCalculation}/analyze`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  generateProfile: (payload) => fetchJSON(`${API_BASE.pvCalculation}/generate-profile`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  getMonthlyProduction: () => fetchJSON(`${API_BASE.pvCalculation}/monthly-production`)
};

// Economics Service API
const economicsAPI = {
  health: () => fetchJSON(`${API_BASE.economics}/health`),
  analyze: (payload) => fetchJSON(`${API_BASE.economics}/analyze`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  eaasMonthly: (payload) => fetchJSON(`${API_BASE.economics}/eaas-monthly`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  getDefaultParameters: () => fetchJSON(`${API_BASE.economics}/default-parameters`),
  sensitivity: (payload) => fetchJSON(`${API_BASE.economics}/comprehensive-sensitivity`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
};

// Advanced Analytics Service API
const advancedAnalyticsAPI = {
  health: () => fetchJSON(`${API_BASE.advancedAnalytics}/health`),
  getKPIs: () => fetchJSON(`${API_BASE.advancedAnalytics}/kpis`),
  getLDC: () => fetchJSON(`${API_BASE.advancedAnalytics}/load-duration-curve`)
};

// Typical Days Service API
const typicalDaysAPI = {
  health: () => fetchJSON(`${API_BASE.typicalDays}/health`),
  getTypicalDays: () => fetchJSON(`${API_BASE.typicalDays}/typical-days`)
};

// Energy Prices Service API
const energyPricesAPI = {
  health: () => fetchJSON(`${API_BASE.energyPrices}/health`),
  getTGE: (params) => fetchJSON(`${API_BASE.energyPrices}/tge?${new URLSearchParams(params)}`),
  getENTSOE: (params) => fetchJSON(`${API_BASE.energyPrices}/entsoe?${new URLSearchParams(params)}`)
};

// Reports Service API
const reportsAPI = {
  health: () => fetchJSON(`${API_BASE.reports}/health`),
  generatePDF: async (payload) => {
    const response = await fetch(`${API_BASE.reports}/generate-report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error(`Report generation failed: ${response.status}`);
    return response.blob();
  }
};

// Projects DB Service API
const projectsAPI = {
  health: () => fetchJSON(`${API_BASE.projectsDb}/health`),
  list: () => fetchJSON(`${API_BASE.projectsDb}/`),
  create: (data) => fetchJSON(`${API_BASE.projectsDb}/`, {
    method: 'POST',
    body: JSON.stringify(data)
  }),
  get: (id) => fetchJSON(`${API_BASE.projectsDb}/${id}`),
  loadFull: (id) => fetchJSON(`${API_BASE.projectsDb}/${id}/load-full`),
  saveData: (id, dataType, data) => fetchJSON(`${API_BASE.projectsDb}/${id}/data`, {
    method: 'POST',
    body: JSON.stringify({ data_type: dataType, data })
  }),
  delete: (id) => fetch(`${API_BASE.projectsDb}/${id}`, { method: 'DELETE' })
};

// PVGIS Proxy Service API
const pvgisAPI = {
  health: () => fetchJSON(`${API_BASE.pvgisProxy}/health`),
  pvcalc: (payload) => fetchJSON(`${API_BASE.pvgisProxy}/pvcalc`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  seriescalc: (payload) => fetchJSON(`${API_BASE.pvgisProxy}/seriescalc`, {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  getDatabases: () => fetchJSON(`${API_BASE.pvgisProxy}/databases`)
};

// Geo Service API (Geocoding + Elevation)
const geoAPI = {
  health: () => fetchJSON(`${API_BASE.geo}/health`),
  resolve: (params) => fetchJSON(`${API_BASE.geo}/resolve?${new URLSearchParams(params)}`),
  elevation: (lat, lon) => fetchJSON(`${API_BASE.geo}/elevation?lat=${lat}&lon=${lon}`),
  resolveBatch: (locations) => fetchJSON(`${API_BASE.geo}/resolve-batch`, {
    method: 'POST',
    body: JSON.stringify(locations)
  }),
  getPolishCities: () => fetchJSON(`${API_BASE.geo}/cities/pl`),
  cacheStats: () => fetchJSON(`${API_BASE.geo}/cache/stats`)
};

// Export unified API object
const API = {
  dataAnalysis: dataAnalysisAPI,
  pvCalculation: pvCalculationAPI,
  economics: economicsAPI,
  advancedAnalytics: advancedAnalyticsAPI,
  typicalDays: typicalDaysAPI,
  energyPrices: energyPricesAPI,
  reports: reportsAPI,
  projects: projectsAPI,
  pvgis: pvgisAPI,
  geo: geoAPI,
  // Base paths for modules that need direct access
  BASE: API_BASE
};

// Make API available globally
window.API = API;

console.log('API client initialized - all backend calls via /api/* routes');
