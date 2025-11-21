// API Configuration
const API_CONFIG = {
  DATA_ANALYSIS: 'http://localhost:8001',
  PV_CALCULATION: 'http://localhost:8002',
  ECONOMICS: 'http://localhost:8003',
  ADVANCED_ANALYTICS: 'http://localhost:8004',
  TYPICAL_DAYS: 'http://localhost:8005'
};

// API Client
class APIClient {
  constructor() {
    this.services = {
      dataAnalysis: API_CONFIG.DATA_ANALYSIS,
      pvCalculation: API_CONFIG.PV_CALCULATION,
      economics: API_CONFIG.ECONOMICS,
      advancedAnalytics: API_CONFIG.ADVANCED_ANALYTICS,
      typicalDays: API_CONFIG.TYPICAL_DAYS
    };
  }

  async checkHealth() {
    const statuses = {};

    for (const [name, url] of Object.entries(this.services)) {
      try {
        const response = await fetch(`${url}/health`);
        statuses[name] = response.ok ? 'healthy' : 'unhealthy';
      } catch (error) {
        statuses[name] = 'offline';
      }
    }

    return statuses;
  }

  // Data Analysis Service
  async uploadCSV(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.services.dataAnalysis}/upload/csv`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Upload failed');
    }

    return await response.json();
  }

  async uploadExcel(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.services.dataAnalysis}/upload/excel`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Upload failed');
    }

    return await response.json();
  }

  async getStatistics() {
    const response = await fetch(`${this.services.dataAnalysis}/statistics`);

    if (!response.ok) {
      throw new Error('Failed to get statistics');
    }

    return await response.json();
  }

  async getHourlyData(month = 0) {
    const response = await fetch(
      `${this.services.dataAnalysis}/hourly-data?month=${month}`
    );

    if (!response.ok) {
      throw new Error('Failed to get hourly data');
    }

    return await response.json();
  }

  async getDailyConsumption(month = 0) {
    const response = await fetch(
      `${this.services.dataAnalysis}/daily-consumption?month=${month}`
    );

    if (!response.ok) {
      throw new Error('Failed to get daily consumption');
    }

    return await response.json();
  }

  async getHeatmapData(month = 0) {
    const response = await fetch(
      `${this.services.dataAnalysis}/heatmap?month=${month}`
    );

    if (!response.ok) {
      throw new Error('Failed to get heatmap data');
    }

    return await response.json();
  }

  // PV Calculation Service
  async generatePVProfile(config) {
    const response = await fetch(`${this.services.pvCalculation}/generate-profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to generate PV profile');
    }

    return await response.json();
  }

  async runPVAnalysis(analysisRequest) {
    const response = await fetch(`${this.services.pvCalculation}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(analysisRequest)
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Analysis failed');
    }

    return await response.json();
  }

  async simulatePV(simulationRequest) {
    const response = await fetch(`${this.services.pvCalculation}/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(simulationRequest)
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Simulation failed');
    }

    return await response.json();
  }

  async getMonthlyProduction(capacity, pvProfile) {
    const response = await fetch(
      `${this.services.pvCalculation}/monthly-production?capacity=${capacity}`,
      {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
      }
    );

    if (!response.ok) {
      throw new Error('Failed to get monthly production');
    }

    return await response.json();
  }

  // Economics Service
  async analyzeEconomics(request) {
    const response = await fetch(`${this.services.economics}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Economic analysis failed');
    }

    return await response.json();
  }

  async compareScenarios(scenarios) {
    const response = await fetch(`${this.services.economics}/compare-scenarios`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scenarios)
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Comparison failed');
    }

    return await response.json();
  }

  async sensitivityAnalysis(baseRequest, parameter, variations) {
    const response = await fetch(
      `${this.services.economics}/sensitivity-analysis?parameter=${parameter}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_request: baseRequest,
          parameter,
          variations
        })
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Sensitivity analysis failed');
    }

    return await response.json();
  }

  async getDefaultEconomicParameters() {
    const response = await fetch(`${this.services.economics}/default-parameters`);

    if (!response.ok) {
      throw new Error('Failed to get default parameters');
    }

    return await response.json();
  }

  async comprehensiveSensitivity(baseRequest, parametersToAnalyze = null, variationRange = 20.0) {
    const response = await fetch(`${this.services.economics}/comprehensive-sensitivity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_request: baseRequest,
        parameters_to_analyze: parametersToAnalyze,
        variation_range: variationRange
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Comprehensive sensitivity analysis failed');
    }

    return await response.json();
  }

  // Advanced Analytics Service
  async analyzeAdvancedKPI(consumption, pvProduction, capacity, options = {}) {
    const response = await fetch(`${this.services.advancedAnalytics}/analyze-kpi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        consumption,
        pv_production: pvProduction,
        capacity,
        include_curtailment: options.includeCurtailment !== false,
        include_weekend: options.includeWeekend !== false,
        inverter_limit: options.inverterLimit || null
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Advanced KPI analysis failed');
    }

    return await response.json();
  }

  // Typical Days Service
  async analyzeTypicalDays(consumption, pvProduction, startDate = '2024-01-01') {
    const response = await fetch(`${this.services.typicalDays}/analyze-typical-days`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        consumption,
        pv_production: pvProduction,
        start_date: startDate
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Typical days analysis failed');
    }

    return await response.json();
  }
}

// Export global instance
const apiClient = new APIClient();
