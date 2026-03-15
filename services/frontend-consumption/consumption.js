// Production mode - use nginx reverse proxy routes
const USE_PROXY = true;

// Backend API URLs
const API_URLS = USE_PROXY ? {
  dataAnalysis: '/api/data',
  economics: '/api/economics',
  bessDispatch: '/api/bess-dispatch'
} : {
  dataAnalysis: 'http://localhost:8001',
  economics: 'http://localhost:8003',
  bessDispatch: 'http://localhost:8031'
};

// Chart.js instances
let dailyChart, weeklyChart, monthlyChart, loadDurationChart, seasonalityChart;
let tariffCompChart = null;

/**
 * Format number in European style
 * - Decimal separator: comma (,)
 * - Thousands separator: non-breaking space
 */
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

// Data storage
let consumptionData = null;
let peakShavingExportData = null; // Store for BESS optimization
let currentLoadProfile = null; // Load profile for BESS optimization (hourly or 15-min)
let currentTimestamps = null; // Timestamps for BESS optimization

// Production scenario (P50/P75/P90)
const productionFactors = { P50: 1.00, P75: 0.97, P90: 0.94 };
let currentProductionScenario = 'P50';
let currentScenarioFactor = 1.0;
let cachedRawPvData = null; // Raw PV data from shell (before scenario scaling)
let currentIntervalMinutes = 60; // Data interval: 15 for quarter-hourly, 60 for hourly

/**
 * Set production scenario (P50/P75/P90) and re-run K-class analysis.
 * @param {string} scenario - 'P50', 'P75', or 'P90'
 * @param {boolean} broadcast - if true, notify shell to sync other modules
 */
function setConsumptionScenario(scenario, broadcast = true) {
  if (!productionFactors[scenario]) return;
  currentProductionScenario = scenario;
  currentScenarioFactor = productionFactors[scenario];

  // Update UI buttons
  ['P50', 'P75', 'P90'].forEach(s => {
    const btn = document.getElementById(`consumptionBtn${s}`);
    if (!btn) return;
    const colors = { P50: '#27ae60', P75: '#3498db', P90: '#e74c3c' };
    const active = s === scenario;
    btn.style.background = active ? colors[s] : 'white';
    btn.style.color = active ? 'white' : colors[s];
    btn.style.borderColor = colors[s];
  });

  // Update factor display
  const factorEl = document.getElementById('consumptionScenarioFactor');
  if (factorEl) factorEl.textContent = `${(currentScenarioFactor * 100).toFixed(0)}%`;

  // Re-run K-class with scaled PV data
  if (cachedRawPvData && consumptionData?.hourlyData?.values) {
    rerunKClassWithScenario();
  }

  // Broadcast to shell → other modules
  if (broadcast) {
    window.parent.postMessage({
      type: 'PRODUCTION_SCENARIO_CHANGED',
      data: { scenario, source: 'consumption' }
    }, '*');
  }

  console.log(`📊 Consumption: Scenario set to ${scenario} (factor: ${currentScenarioFactor})`);
}

/**
 * Re-run K-class analysis with current scenario factor applied to cached PV data.
 */
function rerunKClassWithScenario() {
  if (!cachedRawPvData || !consumptionData?.hourlyData?.values) return;

  const pvScaled = cachedRawPvData.map(v => v * currentScenarioFactor);

  let loadHourly = consumptionData.hourlyData.values;
  if (loadHourly.length === 35040) {
    const hourlyLoad = [];
    for (let h = 0; h < 8760; h++) {
      const s = h * 4;
      hourlyLoad.push((loadHourly[s] + loadHourly[s+1] + loadHourly[s+2] + loadHourly[s+3]) / 4);
    }
    loadHourly = hourlyLoad;
  }
  if (loadHourly.length < 8760) return;

  let somPLNperKWh = 0.2194;
  try {
    const settings = cachedSystemSettings || JSON.parse(localStorage.getItem('pv_system_settings') || '{}');
    if (settings.capacityFeeRate) somPLNperKWh = settings.capacityFeeRate / 1000;
  } catch (e) {}

  const year = consumptionData?.year || 2025;
  const analysis = calculateKClassAnalysis(loadHourly, pvScaled, year, somPLNperKWh);
  updateKClassWidget(analysis);

  if (analysis) {
    console.log(`⚡ K-class [${currentProductionScenario}]: fee=${analysis.totalFeeBefore?.toFixed(0)}→${analysis.totalFeeAfter?.toFixed(0)}, savings=${analysis.totalSavings?.toFixed(0)} PLN`);
  }
}

// Check for data on load
document.addEventListener('DOMContentLoaded', () => {
  // Request settings and scenario from shell first
  console.log('📊 Consumption: Requesting settings from shell on load');
  window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  window.parent.postMessage({ type: 'REQUEST_SCENARIO' }, '*');

  // Load data after short delay to allow settings to arrive
  setTimeout(() => {
    loadConsumptionData();
  }, 100);
});

// Cache for system settings received from shell
let cachedSystemSettings = null;

// Listen for messages from shell
window.addEventListener('message', (event) => {
  switch (event.data.type) {
    case 'DATA_AVAILABLE':
    case 'DATA_UPLOADED':
      loadConsumptionData();
      break;
    case 'DATA_CLEARED':
      clearAnalysis();
      break;
    case 'PROJECT_LOADED':
      // Project was loaded - reload consumption data
      console.log('📂 Consumption: Project loaded, reloading data');
      loadConsumptionData();
      break;
    case 'SETTINGS_UPDATED':
      // Settings updated from shell - cache them
      if (event.data.data) {
        cachedSystemSettings = event.data.data;
        console.log('📊 Consumption: Settings received from shell:', cachedSystemSettings.tariffConfig);
        // Re-run tariff analysis with new settings
        if (consumptionData && consumptionData.hourlyData) {
          performTariffAnalysis();
        }
      }
      break;
    case 'SHARED_DATA_RESPONSE':
      // Shared data response - may contain settings
      if (event.data.data && event.data.data.settings) {
        cachedSystemSettings = event.data.data.settings;
        console.log('📊 Consumption: Settings from SHARED_DATA_RESPONSE:', cachedSystemSettings.tariffConfig);
      }
      // Restore scenario from shared data
      if (event.data.data?.currentScenario) {
        setConsumptionScenario(event.data.data.currentScenario, false);
      }
      break;
    case 'SCENARIO_CHANGED':
      // Production scenario changed from another module (economics/shell)
      if (event.data.data?.scenario) {
        console.log(`📊 Consumption: Scenario changed to ${event.data.data.scenario} (source: ${event.data.data.source})`);
        setConsumptionScenario(event.data.data.scenario, false);
      }
      break;
  }
});

// Load consumption data from localStorage or backend
async function loadConsumptionData() {
  // Try localStorage first
  const storedData = localStorage.getItem('consumptionData');

  if (storedData) {
    try {
      consumptionData = JSON.parse(storedData);
      performAnalysis();
      return;
    } catch (error) {
      console.error('Błąd ładowania danych z localStorage:', error);
    }
  }

  // Fallback: try to load from backend
  try {
    const healthResponse = await fetch(`${API_URLS.dataAnalysis}/health`);
    if (!healthResponse.ok) {
      showNoData();
      return;
    }

    const health = await healthResponse.json();
    if (!health.data_loaded) {
      showNoData();
      return;
    }

    // Backend has data, fetch it
    const dataResponse = await fetch(`${API_URLS.dataAnalysis}/hourly-data`);
    if (!dataResponse.ok) {
      showNoData();
      return;
    }

    const hourlyData = await dataResponse.json();

    // Get statistics for metadata
    const statsResponse = await fetch(`${API_URLS.dataAnalysis}/statistics`);
    const stats = statsResponse.ok ? await statsResponse.json() : {};

    consumptionData = {
      filename: 'Dane z backendu',
      dataPoints: hourlyData.values.length,
      year: new Date(hourlyData.timestamps[0]).getFullYear(),
      hourlyData: hourlyData
    };

    // Save to localStorage for next time
    localStorage.setItem('consumptionData', JSON.stringify(consumptionData));

    performAnalysis();
  } catch (error) {
    console.error('Błąd ładowania danych z backendu:', error);
    showNoData();
  }
}

// Show "no data" message
function showNoData() {
  document.querySelector('.content-grid').classList.add('hidden');
  document.getElementById('noDataMessage').classList.add('active');
  document.getElementById('dataInfo').textContent = 'Brak danych';
}

// Hide "no data" message
function hideNoData() {
  document.querySelector('.content-grid').classList.remove('hidden');
  document.getElementById('noDataMessage').classList.remove('active');
}

// Perform consumption analysis - fetch stats from backend
async function performAnalysis() {
  hideNoData();

  if (!consumptionData || !consumptionData.hourlyData) {
    showNoData();
    return;
  }

  try {
    // Fetch statistics from backend (all calculations done server-side)
    const statsResponse = await fetch(`${API_URLS.dataAnalysis}/statistics`);
    if (!statsResponse.ok) {
      throw new Error('Failed to fetch statistics');
    }
    const backendStats = await statsResponse.json();

    // Update UI with backend-calculated statistics
    updateStatisticsFromBackend(backendStats);
    updateDataInfo(consumptionData, backendStats);

    // Generate charts using backend data
    generateDailyProfileFromBackend(backendStats.daily_profile_mw);
    generateWeeklyProfileFromBackend(backendStats.weekly_profile_mwh);
    generateMonthlyProfileFromBackend(backendStats.monthly_consumption);

    // Fetch 15-minute data for Peak Shaving analysis (more accurate for BESS sizing)
    let peakShavingData = null;
    try {
      const quarterHourResponse = await fetch(`${API_URLS.dataAnalysis}/quarter-hour-data`);
      if (quarterHourResponse.ok) {
        peakShavingData = await quarterHourResponse.json();
        console.log(`📊 Loaded 15-min data: ${peakShavingData.total_intervals} intervals`);
      }
    } catch (e) {
      console.warn('⚠️ Could not load 15-min data, falling back to hourly:', e);
    }

    // Use 15-min data for Peak Shaving if available, otherwise fall back to hourly
    if (peakShavingData && peakShavingData.values?.length > 0) {
      generateLoadDurationCurve(peakShavingData.values, peakShavingData.timestamps, 15);
    } else {
      generateLoadDurationCurve(consumptionData.hourlyData.values, consumptionData.hourlyData.timestamps, 60);
    }

    // Fetch and display seasonality analysis
    await loadSeasonalityAnalysis();

  } catch (error) {
    console.error('Error fetching backend statistics:', error);
    // Fallback to local calculation if backend fails
    const hourlyData = consumptionData.hourlyData;
    const values = hourlyData.values;
    const stats = calculateStatistics(values);
    updateStatistics(stats);
    updateDataInfo(consumptionData, null);
    generateDailyProfile(hourlyData);
    generateWeeklyProfile(hourlyData);
    generateMonthlyProfile(hourlyData);
    generateLoadDurationCurve(values, consumptionData.hourlyData?.timestamps, 60);
  }
}

// Calculate statistics
function calculateStatistics(values) {
  const sum = values.reduce((a, b) => a + b, 0);
  const avg = sum / values.length;
  const max = Math.max(...values);
  const min = Math.min(...values);

  // Standard deviation
  const variance = values.reduce((sum, val) => sum + Math.pow(val - avg, 2), 0) / values.length;
  const stdDev = Math.sqrt(variance);

  // Variation coefficient
  const variationCoef = (stdDev / avg) * 100;

  // Load factor
  const loadFactor = (avg / max) * 100;

  // Annual consumption (kWh -> GWh)
  const annualConsumption = (sum / 1000000).toFixed(2);

  // Average daily (kWh -> MWh)
  const days = values.length / 24;
  const avgDaily = (sum / days / 1000).toFixed(2);

  return {
    annualConsumption,
    avgDaily,
    peakPower: (max / 1000).toFixed(2), // kW -> MW
    minPower: min.toFixed(0),
    avgPower: (avg / 1000).toFixed(2), // kW -> MW
    stdDev: (stdDev / 1000).toFixed(2), // kW -> MW
    variationCoef: variationCoef.toFixed(1),
    loadFactor: loadFactor.toFixed(1),
    dataPoints: values.length,
    days: Math.floor(days)
  };
}

// Update statistics display (legacy - local calculation)
function updateStatistics(stats) {
  document.getElementById('annualConsumption').textContent = stats.annualConsumption;
  document.getElementById('peakPower').textContent = stats.peakPower;
  document.getElementById('minPower').textContent = stats.minPower;
  document.getElementById('avgDaily').textContent = stats.avgDaily;
  document.getElementById('avgPower').textContent = `${stats.avgPower} MW`;
  document.getElementById('stdDev').textContent = `${stats.stdDev} MW`;
  document.getElementById('variationCoef').textContent = `${stats.variationCoef}%`;
  document.getElementById('loadFactor').textContent = `${stats.loadFactor}%`;
  document.getElementById('dataPoints').textContent = stats.dataPoints.toLocaleString('pl-PL');
  document.getElementById('dataPeriod').textContent = `${stats.days} dni`;
}

// Update statistics from backend response
function updateStatisticsFromBackend(stats) {
  document.getElementById('annualConsumption').textContent = stats.total_consumption_gwh.toFixed(2);
  document.getElementById('peakPower').textContent = stats.peak_power_mw.toFixed(2);
  document.getElementById('minPower').textContent = stats.min_power_kw.toFixed(0);
  document.getElementById('avgDaily').textContent = stats.avg_daily_mwh.toFixed(2);
  document.getElementById('avgPower').textContent = `${stats.avg_power_mw.toFixed(2)} MW`;
  document.getElementById('stdDev').textContent = `${stats.std_dev_mw.toFixed(2)} MW`;
  document.getElementById('variationCoef').textContent = `${stats.variation_coef_pct.toFixed(1)}%`;
  document.getElementById('loadFactor').textContent = `${stats.load_factor_pct.toFixed(1)}%`;

  // Show measurements count with resolution info
  const measurements = stats.measurements || stats.hours;
  const resolution = stats.data_resolution || 'hourly';
  const detectedInterval = stats.detected_interval_minutes || 15;
  const resolutionLabel = detectedInterval === 60 ? ' (1h)' : detectedInterval === 30 ? ' (30-min)' : ' (15-min)';
  document.getElementById('dataPoints').textContent = measurements.toLocaleString('pl-PL') + resolutionLabel;

  document.getElementById('dataPeriod').textContent = `${stats.days} dni (${stats.date_start} - ${stats.date_end})`;

  // Log data resolution for debugging
  console.log(`📊 Statistics resolution: ${resolution}, detected interval: ${detectedInterval} min, measurements: ${measurements}`);
}

// Update data info
function updateDataInfo(data, backendStats) {
  let info;
  if (backendStats) {
    info = `${data.filename} • ${backendStats.hours} godzin • ${backendStats.date_start} do ${backendStats.date_end}`;
  } else {
    info = `${data.filename} • ${data.dataPoints} punktów • ${data.year}`;
  }
  document.getElementById('dataInfo').textContent = info;
}

// Generate daily profile chart from backend data
function generateDailyProfileFromBackend(dailyProfileMw) {
  const ctx = document.getElementById('dailyProfile').getContext('2d');

  if (dailyChart) dailyChart.destroy();

  dailyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
      datasets: [{
        label: 'Średnia Moc [MW]',
        data: dailyProfileMw.map(v => v.toFixed(2)),
        borderColor: '#667eea',
        backgroundColor: 'rgba(102, 126, 234, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Moc [MW]' }
        },
        x: {
          title: { display: true, text: 'Godzina' }
        }
      }
    }
  });
}

// Generate daily profile chart (legacy - local calculation)
function generateDailyProfile(hourlyData) {
  const hourlyAverages = new Array(24).fill(0);
  const hourlyCounts = new Array(24).fill(0);

  hourlyData.values.forEach((value, index) => {
    const hour = index % 24;
    hourlyAverages[hour] += value;
    hourlyCounts[hour]++;
  });

  // Calculate averages
  const avgProfile = hourlyAverages.map((sum, hour) =>
    (sum / hourlyCounts[hour] / 1000).toFixed(2) // kW -> MW
  );

  const ctx = document.getElementById('dailyProfile').getContext('2d');

  if (dailyChart) dailyChart.destroy();

  dailyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array.from({ length: 24 }, (_, i) => `${i}:00`),
      datasets: [{
        label: 'Średnia Moc [MW]',
        data: avgProfile,
        borderColor: '#667eea',
        backgroundColor: 'rgba(102, 126, 234, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Moc [MW]' }
        },
        x: {
          title: { display: true, text: 'Godzina' }
        }
      }
    }
  });
}

// Generate weekly profile chart from backend data
function generateWeeklyProfileFromBackend(weeklyProfileMwh) {
  const dayNames = ['Pon', 'Wt', 'Śr', 'Czw', 'Pt', 'Sob', 'Nie'];
  const ctx = document.getElementById('weeklyProfile').getContext('2d');

  if (weeklyChart) weeklyChart.destroy();

  weeklyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: dayNames,
      datasets: [{
        label: 'Średnie Zużycie [MWh/dzień]',
        data: weeklyProfileMwh.map(v => v.toFixed(2)),
        backgroundColor: 'rgba(102, 126, 234, 0.7)',
        borderColor: '#667eea',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Zużycie [MWh/dzień]' }
        }
      }
    }
  });
}

// Generate weekly profile chart (legacy - local calculation)
function generateWeeklyProfile(hourlyData) {
  const dayNames = ['Pon', 'Wt', 'Śr', 'Czw', 'Pt', 'Sob', 'Nie'];
  const dailyTotals = new Array(7).fill(0);
  const dailyCounts = new Array(7).fill(0);

  // Parse timestamps and group by day of week
  hourlyData.timestamps.forEach((timestamp, index) => {
    const date = new Date(timestamp);
    const dayOfWeek = (date.getDay() + 6) % 7; // Monday = 0
    dailyTotals[dayOfWeek] += hourlyData.values[index];
    dailyCounts[dayOfWeek]++;
  });

  // Calculate daily averages (kWh -> MWh)
  const avgDaily = dailyTotals.map((total, day) =>
    (total / (dailyCounts[day] / 24) / 1000).toFixed(2)
  );

  const ctx = document.getElementById('weeklyProfile').getContext('2d');

  if (weeklyChart) weeklyChart.destroy();

  weeklyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: dayNames,
      datasets: [{
        label: 'Średnie Zużycie [MWh/dzień]',
        data: avgDaily,
        backgroundColor: 'rgba(102, 126, 234, 0.7)',
        borderColor: '#667eea',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Zużycie [MWh/dzień]' }
        }
      }
    }
  });
}

// Generate monthly profile chart from backend data
function generateMonthlyProfileFromBackend(monthlyConsumption) {
  const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];

  // Backend returns kWh, convert to MWh
  const monthlyMWh = monthlyConsumption.map(total => (total / 1000).toFixed(2));

  const ctx = document.getElementById('monthlyProfile').getContext('2d');

  if (monthlyChart) monthlyChart.destroy();

  monthlyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: monthNames,
      datasets: [{
        label: 'Zużycie Miesięczne [MWh]',
        data: monthlyMWh,
        backgroundColor: 'rgba(118, 75, 162, 0.7)',
        borderColor: '#764ba2',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Zużycie [MWh]' }
        }
      }
    }
  });
}

// Generate monthly profile chart (legacy - local calculation)
function generateMonthlyProfile(hourlyData) {
  const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
  const monthlyTotals = new Array(12).fill(0);

  hourlyData.timestamps.forEach((timestamp, index) => {
    const date = new Date(timestamp);
    const month = date.getMonth();
    monthlyTotals[month] += hourlyData.values[index];
  });

  // Convert kWh -> MWh
  const monthlyMWh = monthlyTotals.map(total => (total / 1000).toFixed(2));

  const ctx = document.getElementById('monthlyProfile').getContext('2d');

  if (monthlyChart) monthlyChart.destroy();

  monthlyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: monthNames,
      datasets: [{
        label: 'Zużycie Miesięczne [MWh]',
        data: monthlyMWh,
        backgroundColor: 'rgba(118, 75, 162, 0.7)',
        borderColor: '#764ba2',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Zużycie [MWh]' }
        }
      }
    }
  });
}

// Generate load duration curve with peak shaving analysis
// intervalMinutes: 15 for quarter-hourly data, 60 for hourly data
function generateLoadDurationCurve(values, timestamps = null, intervalMinutes = 60) {
  // Store for BESS optimization API
  currentLoadProfile = values;
  currentTimestamps = timestamps;
  currentIntervalMinutes = intervalMinutes;

  // Create indexed data with original positions
  const indexedData = values.map((val, idx) => ({
    value: val,
    originalIndex: idx,
    timestamp: timestamps ? timestamps[idx] : null
  }));

  // Sort by value descending
  const sortedData = [...indexedData].sort((a, b) => b.value - a.value);
  const totalIntervals = sortedData.length;
  const intervalsPerHour = 60 / intervalMinutes;  // 4 for 15-min, 1 for hourly
  const totalHours = totalIntervals / intervalsPerHour;  // Equivalent hours for display

  // Calculate percentiles and peak shaving metrics with timestamps
  // Pass interval info for proper energy/hours calculation
  const peakShavingAnalysis = calculatePeakShavingAnalysis(sortedData, timestamps, intervalMinutes);

  // Store for export
  peakShavingExportData = peakShavingAnalysis;

  // Convert to MW and sample for chart performance
  const sampleRate = Math.max(1, Math.floor(sortedData.length / 500));
  const sampled = sortedData.filter((_, i) => i % sampleRate === 0);
  const sampledMW = sampled.map(d => d.value / 1000);

  const ctx = document.getElementById('loadDurationCurve').getContext('2d');

  if (loadDurationChart) loadDurationChart.destroy();

  // Prepare threshold lines for visualization
  const thresholdDatasets = peakShavingAnalysis.thresholds.map(t => ({
    label: t.label,
    data: Array(sampled.length).fill(t.powerKW / 1000),
    borderColor: t.color,
    borderWidth: 2,
    borderDash: [5, 5],
    pointRadius: 0,
    fill: false
  }));

  loadDurationChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: sampled.map((_, i) => Math.round(i * sampleRate)),
      datasets: [
        {
          label: 'Moc obciążenia [MW]',
          data: sampledMW,
          borderColor: '#e74c3c',
          backgroundColor: 'rgba(231, 76, 60, 0.15)',
          borderWidth: 2.5,
          fill: true,
          pointRadius: 0,
          order: 1
        },
        ...thresholdDatasets.map((ds, i) => ({ ...ds, order: i + 2 }))
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          labels: {
            usePointStyle: true,
            padding: 15,
            font: { size: 11 }
          }
        },
        tooltip: {
          callbacks: {
            title: (items) => {
              const intervalIdx = parseInt(items[0].label);
              const hourEquiv = intervalIdx / intervalsPerHour;
              return `Interwał ${intervalIdx} (~${formatNumberEU(hourEquiv, 0)}h z ${formatNumberEU(totalHours, 0)}h)`;
            },
            label: (ctx) => {
              const value = ctx.raw;
              return `${ctx.dataset.label}: ${formatNumberEU(value, 3)} MW (${formatNumberEU(value * 1000, 0)} kW)`;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Moc [MW]', font: { weight: 'bold' } },
          grid: { color: 'rgba(0,0,0,0.08)' }
        },
        x: {
          title: { display: true, text: `Uporządkowane interwały (${formatNumberEU(totalHours, 0)}h ekw. w roku, dane ${intervalMinutes}-min)`, font: { weight: 'bold' } },
          ticks: {
            callback: function(value, index) {
              const interval = Math.round(index * sampleRate);
              const hourEquiv = interval / intervalsPerHour;
              if (interval === 0) return '0h';
              if (hourEquiv % 1000 === 0 || index === sampled.length - 1) return `${formatNumberEU(hourEquiv, 0)}h`;
              return '';
            },
            maxRotation: 0
          },
          grid: { display: false }
        }
      }
    }
  });

  // Update peak shaving table
  updatePeakShavingTable(peakShavingAnalysis);
}

/**
 * Calculate peak shaving analysis with multiple threshold levels
 * @param {Array} sortedData - Array of {value, originalIndex, timestamp} sorted by value descending
 * @param {Array} timestamps - Original timestamps array (for reference)
 * @param {Number} intervalMinutes - Data interval in minutes (15 for quarter-hourly, 60 for hourly)
 */
function calculatePeakShavingAnalysis(sortedData, timestamps, intervalMinutes = 60) {
  const totalIntervals = sortedData.length;
  const intervalsPerHour = 60 / intervalMinutes; // 4 for 15-min, 1 for hourly
  const totalHoursEquivalent = totalIntervals / intervalsPerHour;
  const peakPower = sortedData[0]?.value || 0;
  const avgPower = sortedData.reduce((sum, d) => sum + d.value, 0) / totalIntervals;

  // Info about data resolution
  const resolutionInfo = intervalMinutes === 15
    ? `Analiza 15-min (${totalIntervals} interwałów = ${formatNumberEU(totalHoursEquivalent, 0)} godz.)`
    : `Analiza godzinowa (${totalIntervals} godz.)`;

  console.log(`📊 Peak Shaving: ${resolutionInfo}`);

  // Define percentile thresholds for analysis
  const percentileConfigs = [
    { name: 'P100 (Szczyt)', percentile: 100, color: '#e74c3c' },
    { name: 'P99.5', percentile: 99.5, color: '#c0392b' },
    { name: 'P99', percentile: 99, color: '#e67e22' },
    { name: 'P98', percentile: 98, color: '#f39c12' },
    { name: 'P97', percentile: 97, color: '#f1c40f' },
    { name: 'P95', percentile: 95, color: '#27ae60' },
    { name: 'P90', percentile: 90, color: '#2ecc71' },
    { name: 'P85', percentile: 85, color: '#1abc9c' },
    { name: 'P80', percentile: 80, color: '#3498db' }
  ];

  const thresholds = [];
  const tableRows = [];

  for (const config of percentileConfigs) {
    // Calculate index for percentile (sorted descending, so P99 = top 1%)
    const exceedancePercent = 100 - config.percentile;
    const exactIntervalsAbove = totalIntervals * exceedancePercent / 100;
    const exactHoursAbove = exactIntervalsAbove / intervalsPerHour; // Convert to hours
    const index = Math.min(Math.ceil(exactIntervalsAbove), totalIntervals - 1);
    const powerAtPercentile = sortedData[index]?.value || 0;

    // Calculate energy above threshold and collect timestamps
    // For 15-min data: each interval = 0.25h of energy (power * 0.25)
    let energyToShave = 0;
    let intervalsToShave = 0;
    const exceedanceEvents = [];

    for (let i = 0; i < sortedData.length; i++) {
      const d = sortedData[i];
      if (d.value > powerAtPercentile) {
        const excess = d.value - powerAtPercentile;
        // Energy = Power * Time (in hours), for 15-min interval = 0.25h
        energyToShave += excess * (intervalMinutes / 60);
        intervalsToShave++;
        exceedanceEvents.push({
          rank: i + 1,
          timestamp: d.timestamp,
          powerKW: d.value,
          excessKW: excess,
          originalIndex: d.originalIndex
        });
      } else {
        break; // sorted descending, so we can stop
      }
    }

    // Convert intervals to hours for display
    const hoursToShave = intervalsToShave / intervalsPerHour;

    // Calculate peak reduction percentage
    const peakReductionPct = peakPower > 0 ? ((peakPower - powerAtPercentile) / peakPower) * 100 : 0;

    // Determine feasibility rating and code
    let rating, ratingColor, ratingBg, ratingCode;
    if (hoursToShave <= 50 && peakReductionPct >= 5) {
      rating = '🟢 Bardzo opłacalne';
      ratingCode = 'bardzo_oplacalne';
      ratingColor = '#27ae60';
      ratingBg = '#d5f4e6';
    } else if (hoursToShave <= 200 && peakReductionPct >= 3) {
      rating = '🟡 Opłacalne';
      ratingCode = 'oplacalne';
      ratingColor = '#f39c12';
      ratingBg = '#fef9e7';
    } else if (hoursToShave <= 500) {
      rating = '🟠 Możliwe';
      ratingCode = 'mozliwe';
      ratingColor = '#e67e22';
      ratingBg = '#fdebd0';
    } else {
      rating = '🔴 Nieopłacalne';
      ratingCode = 'nieoplacalne';
      ratingColor = '#e74c3c';
      ratingBg = '#fadbd8';
    }

    // Skip P100 from threshold lines but include in table
    if (config.percentile < 100) {
      thresholds.push({
        label: `${config.name} (${formatNumberEU(powerAtPercentile, 0)} kW)`,
        powerKW: powerAtPercentile,
        color: config.color
      });
    }

    tableRows.push({
      name: config.name,
      percentile: config.percentile,
      powerKW: powerAtPercentile,
      hoursAbove: hoursToShave,
      exactHours: exactHoursAbove,
      energyToShave: energyToShave,
      peakReductionPct: peakReductionPct,
      rating: rating,
      ratingCode: ratingCode,
      ratingColor: ratingColor,
      ratingBg: ratingBg,
      color: config.color,
      exceedanceEvents: exceedanceEvents
    });
  }

  // Find best recommendation (first "opłacalne" or "bardzo opłacalne")
  const recommended = tableRows.find(r => r.ratingCode === 'bardzo_oplacalne')
    || tableRows.find(r => r.ratingCode === 'oplacalne');

  // Find cutoff level for export (include up to "możliwe")
  const exportableLevels = tableRows.filter(r =>
    r.ratingCode === 'bardzo_oplacalne' ||
    r.ratingCode === 'oplacalne' ||
    r.ratingCode === 'mozliwe'
  );

  // Calculate BESS sizing based on grouped blocks for recommended level
  let bessRecommendation = null;
  if (recommended && recommended.exceedanceEvents.length > 0) {
    const blocks = groupConsecutiveEventsForBESS(recommended.exceedanceEvents, intervalMinutes);
    if (blocks.length > 0) {
      // Find the largest block by energy
      const largestBlock = blocks.reduce((max, b) => b.totalExcessKWh > max.totalExcessKWh ? b : max, blocks[0]);
      // Find max power deficit (for C-rate)
      const maxPowerDeficit = recommended.exceedanceEvents.reduce((max, e) => Math.max(max, e.excessKW || 0), 0);

      // BESS sizing:
      // - Capacity based on largest single block energy need (with DOD margin)
      // - Power based on max instantaneous deficit
      const DOD = 0.8; // 80% usable depth of discharge
      const safetyMargin = 1.2; // 20% safety margin

      const requiredCapacityKWh = (largestBlock.totalExcessKWh / DOD) * safetyMargin;
      const requiredPowerKW = maxPowerDeficit * safetyMargin;

      bessRecommendation = {
        capacityKWh: requiredCapacityKWh,
        powerKW: requiredPowerKW,
        largestBlockEnergyKWh: largestBlock.totalExcessKWh,
        largestBlockDurationH: largestBlock.durationHours,
        maxPowerDeficitKW: maxPowerDeficit,
        totalBlocks: blocks.length,
        dod: DOD * 100,
        safetyMargin: (safetyMargin - 1) * 100
      };
    }
  }

  return {
    peakPower,
    avgPower,
    totalHours: totalHoursEquivalent,
    totalIntervals,
    intervalMinutes,
    resolutionInfo,
    thresholds: thresholds.slice(0, 4), // Show top 4 thresholds on chart
    tableRows,
    recommended,
    exportableLevels,
    bessRecommendation
  };
}

/**
 * Group consecutive events for BESS sizing (simplified version for analysis)
 * @param {Array} events - Array of exceedance events
 * @param {Number} intervalMinutes - Interval in minutes (15 or 60), default 60 for backward compatibility
 */
function groupConsecutiveEventsForBESS(events, intervalMinutes = 60) {
  if (!events || events.length === 0) return [];

  const hoursPerInterval = intervalMinutes / 60; // 0.25 for 15-min, 1 for hourly

  // Sort events by original index (chronological order)
  const sortedByTime = [...events].sort((a, b) => a.originalIndex - b.originalIndex);

  const groups = [];
  let currentGroup = null;

  for (const event of sortedByTime) {
    if (!currentGroup) {
      currentGroup = {
        events: [event],
        // For 15-min data: energy = excess_kW * 0.25h
        totalExcessKWh: (event.excessKW || 0) * hoursPerInterval,
        maxPowerKW: event.powerKW || 0
      };
    } else {
      const lastEvent = currentGroup.events[currentGroup.events.length - 1];
      // Check if consecutive (indices differ by 1)
      const isConsecutive = (event.originalIndex - lastEvent.originalIndex) <= 1;

      if (isConsecutive) {
        currentGroup.events.push(event);
        currentGroup.totalExcessKWh += (event.excessKW || 0) * hoursPerInterval;
        currentGroup.maxPowerKW = Math.max(currentGroup.maxPowerKW, event.powerKW || 0);
      } else {
        // Close current group - calculate duration in hours
        currentGroup.durationHours = currentGroup.events.length * hoursPerInterval;
        groups.push(currentGroup);
        currentGroup = {
          events: [event],
          totalExcessKWh: (event.excessKW || 0) * hoursPerInterval,
          maxPowerKW: event.powerKW || 0
        };
      }
    }
  }

  if (currentGroup) {
    currentGroup.durationHours = currentGroup.events.length * hoursPerInterval;
    groups.push(currentGroup);
  }

  return groups;
}

/**
 * Update peak shaving analysis table
 */
function updatePeakShavingTable(analysis) {
  const tbody = document.getElementById('peakShavingTableBody');
  if (!tbody) return;

  const rows = analysis.tableRows.map(row => {
    const rowStyle = row.percentile === 100
      ? 'background: #f8f9fa; font-weight: 600;'
      : '';

    // Format hours - show decimal for partial hours
    const formatHours = (exact, actual) => {
      if (actual === 0) return '-';
      if (exact === actual) return formatNumberEU(actual, 0);
      return `${formatNumberEU(actual, 0)} <span style="color:#95a5a6;font-size:10px;">(~${formatNumberEU(exact, 1)})</span>`;
    };

    return `
      <tr style="${rowStyle}">
        <td style="padding: 10px 8px; border-bottom: 1px solid #eee;">
          <span style="display: inline-block; width: 12px; height: 12px; background: ${row.color}; border-radius: 3px; margin-right: 8px;"></span>
          ${row.name}
        </td>
        <td style="padding: 10px 8px; text-align: right; border-bottom: 1px solid #eee; font-weight: 500;">
          ${formatNumberEU(row.powerKW, 0)}
        </td>
        <td style="padding: 10px 8px; text-align: right; border-bottom: 1px solid #eee;">
          ${formatHours(row.exactHours, row.hoursAbove)}
        </td>
        <td style="padding: 10px 8px; text-align: right; border-bottom: 1px solid #eee;">
          ${row.energyToShave > 0 ? formatNumberEU(row.energyToShave, 0) : '-'}
        </td>
        <td style="padding: 10px 8px; text-align: right; border-bottom: 1px solid #eee; font-weight: 500; color: ${row.peakReductionPct > 0 ? '#27ae60' : '#95a5a6'};">
          ${row.peakReductionPct > 0 ? `-${formatNumberEU(row.peakReductionPct, 1)}%` : '-'}
        </td>
        <td style="padding: 10px 8px; text-align: center; border-bottom: 1px solid #eee;">
          <span style="padding: 4px 8px; border-radius: 4px; font-size: 11px; background: ${row.ratingBg}; color: ${row.ratingColor};">
            ${row.rating}
          </span>
        </td>
      </tr>
    `;
  }).join('');

  tbody.innerHTML = rows;

  // Update recommendation with export button
  const recDiv = document.getElementById('peakShavingRecommendation');
  if (recDiv && analysis.recommended) {
    const rec = analysis.recommended;
    const exportLevelsCount = analysis.exportableLevels?.length || 0;
    const totalEvents = analysis.exportableLevels?.reduce((sum, l) => sum + l.exceedanceEvents.length, 0) || 0;

    recDiv.style.display = 'block';
    recDiv.style.background = 'linear-gradient(135deg, #d5f4e6 0%, #c3f0db 100%)';
    recDiv.style.border = '2px solid #27ae60';
    recDiv.innerHTML = `
      <div style="display: flex; align-items: flex-start; gap: 12px;">
        <span style="font-size: 24px;">💡</span>
        <div style="flex: 1;">
          <strong style="color: #1e8449; font-size: 14px;">Rekomendacja Peak Shaving:</strong>
          <p style="margin: 8px 0 0 0; color: #2c3e50; font-size: 13px;">
            Ścięcie szczytów do poziomu <strong>${rec.name}</strong> (${formatNumberEU(rec.powerKW, 0)} kW)
            pozwoli obniżyć moc szczytową o <strong>${formatNumberEU(rec.peakReductionPct, 1)}%</strong>.
          </p>
          <p style="margin: 6px 0 0 0; color: #495057; font-size: 12px;">
            Wymaga pokrycia <strong>${formatNumberEU(rec.hoursAbove, 0)} godzin/rok</strong>
            i dostarczenia <strong>${formatNumberEU(rec.energyToShave, 0)} kWh</strong> z magazynu lub redukcji obciążenia.
          </p>
          ${analysis.bessRecommendation ? `
          <div id="bessRecommendationSection" style="margin-top: 12px; padding: 12px; background: rgba(255,255,255,0.7); border-radius: 8px; border-left: 4px solid #3498db;">
            <div style="margin-bottom: 10px;">
              <strong style="color: #2980b9; font-size: 13px;">🔋 Orientacyjny dobór BESS (heurystyka):</strong>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;">
              <select id="bessLevelSelect" style="
                padding: 6px 10px;
                border-radius: 4px;
                border: 1px solid #3498db;
                font-size: 12px;
                background: white;
                cursor: pointer;
                min-width: 220px;
              ">
                ${analysis.tableRows.filter(r => r.ratingCode !== 'nieoplacalne').map(row =>
                  `<option value="${row.name}" ${row.name === rec.name ? 'selected' : ''}>
                    ${row.name} (${formatNumberEU(row.powerKW, 0)} kW) - ${row.rating}
                  </option>`
                ).join('')}
              </select>
              <button onclick="runBESSOptimization()" id="bessOptimizeBtn" style="
                background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 12px;
                font-weight: 600;
                white-space: nowrap;
              ">⚡ Optymalizuj (PyPSA+HiGHS)</button>
            </div>
            <div style="display: flex; gap: 24px; margin-bottom: 8px;">
              <div style="font-size: 13px; color: #2c3e50;">
                <span style="color: #7f8c8d;">Pojemność:</span>
                <strong id="bessCapacityValue" style="margin-left: 6px;">${formatNumberEU(analysis.bessRecommendation.capacityKWh, 0)} kWh</strong>
              </div>
              <div style="font-size: 13px; color: #2c3e50;">
                <span style="color: #7f8c8d;">Moc:</span>
                <strong id="bessPowerValue" style="margin-left: 6px;">${formatNumberEU(analysis.bessRecommendation.powerKW, 0)} kW</strong>
              </div>
            </div>
            <p id="bessRationale" style="margin: 0; color: #7f8c8d; font-size: 11px;">
              Na podstawie największego bloku: ${formatNumberEU(analysis.bessRecommendation.largestBlockEnergyKWh, 1)} kWh
              przez ${formatNumberEU(analysis.bessRecommendation.largestBlockDurationH, 2)}h
              (${analysis.bessRecommendation.totalBlocks} bloków/rok, DOD ${analysis.bessRecommendation.dod}%, margines +${analysis.bessRecommendation.safetyMargin}%)
            </p>
            <div id="bessOptimizationDetails" style="display: none;"></div>
          </div>
          ` : `
          <p style="margin: 8px 0 0 0; color: #7f8c8d; font-size: 11px; font-style: italic;">
            Brak danych do wyliczenia rozmiaru BESS
          </p>
          `}
        </div>
      </div>
      <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(39, 174, 96, 0.3);">
        <button onclick="exportPeakShavingAnalysis()" style="
          background: linear-gradient(135deg, #27ae60 0%, #2ecc71 100%);
          color: white;
          border: none;
          padding: 10px 20px;
          border-radius: 6px;
          cursor: pointer;
          font-weight: 600;
          font-size: 13px;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          box-shadow: 0 2px 8px rgba(39, 174, 96, 0.3);
        ">
          📥 Eksportuj szczegóły Peak Shaving (${exportLevelsCount} poziomów, ${totalEvents} zdarzeń)
        </button>
        <span style="display: block; margin-top: 8px; font-size: 11px; color: #7f8c8d;">
          Excel z timestampami wszystkich przekroczeń dla poziomów: Bardzo opłacalne, Opłacalne, Możliwe
        </span>
      </div>
    `;
  } else if (recDiv) {
    recDiv.style.display = 'none';
  }
}

/**
 * Format number for Excel with European locale (comma as decimal separator)
 * Returns number for Excel to handle properly
 */
function formatNumericForExcel(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) return null;
  return Math.round(value * Math.pow(10, decimals)) / Math.pow(10, decimals);
}

/**
 * Format date/time for Excel as proper Date object
 */
function formatDateTimeForExcel(timestamp) {
  if (!timestamp) return { date: null, time: null, dateTime: null };
  try {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return { date: null, time: null, dateTime: null };
    return {
      date: d,  // Excel will format as date
      time: d,  // Excel will format as time
      dateTime: d,
      dateStr: d.toLocaleDateString('pl-PL'),
      timeStr: d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })
    };
  } catch (e) {
    return { date: null, time: null, dateTime: null };
  }
}

/**
 * Group consecutive intervals into peak events (blocks)
 * @param {Array} events - Array of exceedance events sorted by timestamp
 * @param {Number} intervalMinutes - Data interval in minutes (15 or 60), default 60
 * @returns {Array} Array of grouped peak events with start/end times
 */
function groupConsecutiveEvents(events, intervalMinutes = 60) {
  if (!events || events.length === 0) return [];

  const intervalMs = intervalMinutes * 60 * 1000;  // Interval in milliseconds
  const hoursPerInterval = intervalMinutes / 60;   // 0.25 for 15-min, 1.0 for hourly
  const toleranceMs = intervalMs * 1.5;            // 1.5x interval tolerance for gaps

  // Sort events by original index (chronological order)
  const sortedByTime = [...events].sort((a, b) => a.originalIndex - b.originalIndex);

  const groups = [];
  let currentGroup = null;

  for (const event of sortedByTime) {
    const eventTime = event.timestamp ? new Date(event.timestamp) : null;

    if (!currentGroup) {
      // Start new group
      currentGroup = {
        startTime: eventTime,
        endTime: eventTime ? new Date(eventTime.getTime() + intervalMs) : null,
        events: [event],
        totalExcessKWh: (event.excessKW || 0) * hoursPerInterval,  // Energy = power * time
        maxPowerKW: event.powerKW || 0,
        avgPowerKW: event.powerKW || 0
      };
    } else {
      // Check if this event is consecutive (within tolerance of last event)
      const lastEvent = currentGroup.events[currentGroup.events.length - 1];
      const lastEventTime = lastEvent.timestamp ? new Date(lastEvent.timestamp) : null;

      const isConsecutive = eventTime && lastEventTime &&
        (eventTime.getTime() - lastEventTime.getTime()) <= toleranceMs;

      if (isConsecutive) {
        // Add to current group
        currentGroup.events.push(event);
        currentGroup.endTime = new Date(eventTime.getTime() + intervalMs);
        currentGroup.totalExcessKWh += (event.excessKW || 0) * hoursPerInterval;
        currentGroup.maxPowerKW = Math.max(currentGroup.maxPowerKW, event.powerKW || 0);
        currentGroup.avgPowerKW = currentGroup.events.reduce((sum, e) => sum + (e.powerKW || 0), 0) / currentGroup.events.length;
      } else {
        // Save current group and start new one
        groups.push(currentGroup);
        currentGroup = {
          startTime: eventTime,
          endTime: eventTime ? new Date(eventTime.getTime() + intervalMs) : null,
          events: [event],
          totalExcessKWh: (event.excessKW || 0) * hoursPerInterval,
          maxPowerKW: event.powerKW || 0,
          avgPowerKW: event.powerKW || 0
        };
      }
    }
  }

  // Don't forget the last group
  if (currentGroup) {
    groups.push(currentGroup);
  }

  // Add duration to each group (in hours)
  for (const group of groups) {
    group.durationHours = group.events.length * hoursPerInterval;  // e.g., 4 intervals * 0.25h = 1h
    if (group.startTime && group.endTime) {
      group.durationMs = group.endTime.getTime() - group.startTime.getTime();
    }
  }

  return groups;
}

/**
 * Export Peak Shaving analysis to Excel with timestamps
 */
function exportPeakShavingAnalysis() {
  if (!peakShavingExportData) {
    alert('Brak danych do eksportu. Odśwież analizę.');
    return;
  }

  console.log('📥 Eksport Peak Shaving do Excel...');

  try {
    const wb = XLSX.utils.book_new();
    const analysis = peakShavingExportData;

    // ========== SHEET 1: PODSUMOWANIE PERCENTYLI ==========
    const summaryData = [
      ['ANALIZA PEAK SHAVING - PODSUMOWANIE'],
      [''],
      ['Data eksportu:', new Date().toLocaleString('pl-PL')],
      ['Całkowita liczba godzin:', analysis.totalHours],
      ['Moc szczytowa [kW]:', formatNumericForExcel(analysis.peakPower, 1)],
      ['Moc średnia [kW]:', formatNumericForExcel(analysis.avgPower, 1)],
      [''],
      ['PERCENTYLE MOCY'],
      ['Próg', 'Moc [kW]', 'Godz. teoretycznych', 'Godz. rzeczywistych', 'Energia [kWh]', '% redukcji Pmax', 'Ocena']
    ];

    for (const row of analysis.tableRows) {
      summaryData.push([
        row.name,
        formatNumericForExcel(row.powerKW, 1),
        formatNumericForExcel(row.exactHours, 2),
        row.hoursAbove,
        formatNumericForExcel(row.energyToShave, 1),
        row.peakReductionPct > 0 ? formatNumericForExcel(-row.peakReductionPct, 2) : null,
        row.rating.replace(/[🟢🟡🟠🔴]/g, '').trim()
      ]);
    }

    const ws1 = XLSX.utils.aoa_to_sheet(summaryData);
    ws1['!cols'] = [{ wch: 15 }, { wch: 12 }, { wch: 16 }, { wch: 16 }, { wch: 14 }, { wch: 14 }, { wch: 18 }];
    XLSX.utils.book_append_sheet(wb, ws1, 'Podsumowanie');

    // ========== SHEET 2: ZGRUPOWANE ZDARZENIA (główna tabela) ==========
    const intervalMin = analysis.intervalMinutes || 60;  // Get interval from analysis
    const intervalLabel = intervalMin === 15 ? '15-min' : 'godz.';
    const groupedData = [
      ['ZDARZENIA PEAK SHAVING - ZGRUPOWANE W BLOKI'],
      [''],
      [`Bloki czasowe przekroczeń - kolejne interwały (${intervalMin} min) połączone w jedno zdarzenie`],
      [''],
      ['Poziom', 'Nr bloku', 'Start (data)', 'Start (godz.)', 'Stop (data)', 'Stop (godz.)',
       'Czas trwania [h]', 'Moc max [kW]', 'Moc śr. [kW]', 'Próg [kW]', 'Suma nadwyżki [kWh]', `Liczba int. (${intervalLabel})`]
    ];

    let globalBlockNum = 0;
    for (const level of analysis.exportableLevels || []) {
      if (level.exceedanceEvents.length === 0) continue;

      const groups = groupConsecutiveEvents(level.exceedanceEvents, intervalMin);
      let blockNum = 0;

      for (const group of groups) {
        blockNum++;
        globalBlockNum++;

        const startDT = formatDateTimeForExcel(group.startTime);
        const endDT = formatDateTimeForExcel(group.endTime);

        groupedData.push([
          level.name,
          globalBlockNum,
          startDT.date,
          startDT.timeStr || '-',
          endDT.date,
          endDT.timeStr || '-',
          group.durationHours,
          formatNumericForExcel(group.maxPowerKW, 1),
          formatNumericForExcel(group.avgPowerKW, 1),
          formatNumericForExcel(level.powerKW, 1),
          formatNumericForExcel(group.totalExcessKWh, 2),
          group.events.length
        ]);
      }
    }

    const wsGrouped = XLSX.utils.aoa_to_sheet(groupedData);
    wsGrouped['!cols'] = [
      { wch: 12 }, { wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 10 },
      { wch: 14 }, { wch: 12 }, { wch: 12 }, { wch: 10 }, { wch: 16 }, { wch: 12 }
    ];
    // Format date columns
    XLSX.utils.book_append_sheet(wb, wsGrouped, 'Bloki czasowe');

    // ========== SHEET 3+: SZCZEGÓŁY DLA KAŻDEGO POZIOMU ==========
    for (const level of analysis.exportableLevels || []) {
      if (level.exceedanceEvents.length === 0) continue;

      const sheetName = level.name.replace(/[^a-zA-Z0-9]/g, '_').substring(0, 28);
      const groups = groupConsecutiveEvents(level.exceedanceEvents, intervalMin);

      const detailData = [
        [`ZDARZENIA: ${level.name}`],
        [''],
        ['Próg mocy [kW]:', formatNumericForExcel(level.powerKW, 1)],
        ['Liczba bloków:', groups.length],
        ['Łączna liczba godzin:', level.exceedanceEvents.length],
        ['Energia do ścięcia [kWh]:', formatNumericForExcel(level.energyToShave, 1)],
        ['Redukcja Pmax [%]:', formatNumericForExcel(-level.peakReductionPct, 2)],
        ['Ocena:', level.rating.replace(/[🟢🟡🟠🔴]/g, '').trim()],
        [''],
        ['BLOKI CZASOWE'],
        ['Nr bloku', 'Start (data)', 'Start (godz.)', 'Stop (data)', 'Stop (godz.)',
         'Czas [h]', 'Moc max [kW]', 'Moc śr. [kW]', 'Suma [kWh]']
      ];

      let blockNum = 0;
      for (const group of groups) {
        blockNum++;
        const startDT = formatDateTimeForExcel(group.startTime);
        const endDT = formatDateTimeForExcel(group.endTime);

        detailData.push([
          blockNum,
          startDT.date,
          startDT.timeStr || '-',
          endDT.date,
          endDT.timeStr || '-',
          group.durationHours,
          formatNumericForExcel(group.maxPowerKW, 1),
          formatNumericForExcel(group.avgPowerKW, 1),
          formatNumericForExcel(group.totalExcessKWh, 2)
        ]);
      }

      // Add detailed hourly breakdown
      detailData.push(['']);
      detailData.push(['SZCZEGÓŁY GODZINOWE']);
      detailData.push(['Nr', 'Data', 'Godzina', 'Moc [kW]', 'Nadwyżka [kW]']);

      // Sort by time for detailed view
      const sortedEvents = [...level.exceedanceEvents].sort((a, b) => a.originalIndex - b.originalIndex);
      let eventNum = 0;
      for (const event of sortedEvents) {
        eventNum++;
        const dt = formatDateTimeForExcel(event.timestamp);
        detailData.push([
          eventNum,
          dt.date,
          dt.timeStr || '-',
          formatNumericForExcel(event.powerKW, 1),
          formatNumericForExcel(event.excessKW, 2)
        ]);
      }

      const wsDetail = XLSX.utils.aoa_to_sheet(detailData);
      wsDetail['!cols'] = [
        { wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 10 },
        { wch: 8 }, { wch: 12 }, { wch: 12 }, { wch: 12 }
      ];
      XLSX.utils.book_append_sheet(wb, wsDetail, sheetName);
    }

    // ========== SHEET: WSZYSTKIE GODZINY (surowe dane) ==========
    const allHoursData = [
      ['WSZYSTKIE GODZINY PRZEKROCZENIA (surowe dane)'],
      [''],
      ['Poziom', 'Nr', 'Data', 'Godzina', 'Moc [kW]', 'Próg [kW]', 'Nadwyżka [kW]']
    ];

    for (const level of analysis.exportableLevels || []) {
      const sortedEvents = [...level.exceedanceEvents].sort((a, b) => a.originalIndex - b.originalIndex);
      let eventNum = 0;
      for (const event of sortedEvents) {
        eventNum++;
        const dt = formatDateTimeForExcel(event.timestamp);
        allHoursData.push([
          level.name,
          eventNum,
          dt.date,
          dt.timeStr || '-',
          formatNumericForExcel(event.powerKW, 1),
          formatNumericForExcel(level.powerKW, 1),
          formatNumericForExcel(event.excessKW, 2)
        ]);
      }
    }

    const wsAll = XLSX.utils.aoa_to_sheet(allHoursData);
    wsAll['!cols'] = [
      { wch: 12 }, { wch: 6 }, { wch: 12 }, { wch: 8 }, { wch: 12 }, { wch: 10 }, { wch: 12 }
    ];
    XLSX.utils.book_append_sheet(wb, wsAll, 'Wszystkie godziny');

    // ========== SHEET: HARMONOGRAM BESS ==========
    // Get recommended level or first available
    const bessLevel = analysis.recommended || analysis.tableRows.find(r => r.ratingCode !== 'nieoplacalne');

    if (bessLevel && bessLevel.exceedanceEvents?.length > 0) {
      const bessData = [
        ['HARMONOGRAM PRACY MAGAZYNU BESS'],
        [''],
        ['Poziom peak shaving:', bessLevel.name],
        ['Próg mocy [kW]:', formatNumericForExcel(bessLevel.powerKW, 1)],
        [''],
        ['Założenia BESS:'],
        ['DOD (głębokość rozładowania):', '80%'],
        ['Sprawność cyklu (round-trip):', '90%'],
        ['Margines bezpieczeństwa:', '20%'],
        [''],
        ['KIEDY BESS SIĘ ZAŁĄCZA (rozładowanie):'],
        ['']
      ];

      // Calculate BESS parameters based on recommendation
      const dod = 0.8;
      const efficiency = 0.9;
      const safetyMargin = 1.2;

      // Group events into blocks for BESS simulation
      const groups = groupConsecutiveEvents(bessLevel.exceedanceEvents, intervalMin);

      // Find largest block to size BESS
      let maxBlockEnergy = 0;
      let maxBlockPower = 0;
      for (const group of groups) {
        if (group.totalExcessKWh > maxBlockEnergy) {
          maxBlockEnergy = group.totalExcessKWh;
          maxBlockPower = group.maxPowerKW - bessLevel.powerKW; // Excess above threshold
        }
      }

      // BESS sizing
      const bessCapacity = (maxBlockEnergy / dod) * safetyMargin;
      const bessPower = maxBlockPower * safetyMargin;

      bessData.push(['REKOMENDOWANY ROZMIAR BESS:']);
      bessData.push(['Pojemność [kWh]:', formatNumericForExcel(bessCapacity, 0)]);
      bessData.push(['Moc [kW]:', formatNumericForExcel(bessPower, 0)]);
      bessData.push(['']);

      // Header for schedule
      bessData.push([
        'Nr bloku', 'Data start', 'Godz. start', 'Data stop', 'Godz. stop',
        'Czas pracy [h]', 'Moc max rozład. [kW]', 'Moc śr. rozład. [kW]',
        'Energia rozład. [kWh]', 'SOC przed [%]', 'SOC po [%]', 'Uwagi'
      ]);

      let blockNum = 0;
      let annualCycles = 0;

      for (const group of groups) {
        blockNum++;
        const startDT = formatDateTimeForExcel(group.startTime);
        const endDT = formatDateTimeForExcel(group.endTime);

        // Calculate discharge power (excess above threshold)
        const dischargePowerMax = group.maxPowerKW - bessLevel.powerKW;
        const dischargePowerAvg = group.avgPowerKW - bessLevel.powerKW;
        const dischargeEnergy = group.totalExcessKWh;

        // SOC calculation (assuming starts at 100%)
        const socBefore = 100;
        const socAfter = Math.max(0, socBefore - (dischargeEnergy / bessCapacity * 100));

        // Cycle counting
        annualCycles += dischargeEnergy / bessCapacity;

        // Notes
        let notes = '';
        if (dischargeEnergy > bessCapacity * dod) {
          notes = '⚠️ Przekracza DOD!';
        } else if (group.durationHours >= 4) {
          notes = 'Długi blok';
        }

        bessData.push([
          blockNum,
          startDT.date,
          startDT.timeStr || '-',
          endDT.date,
          endDT.timeStr || '-',
          group.durationHours,
          formatNumericForExcel(dischargePowerMax, 1),
          formatNumericForExcel(dischargePowerAvg, 1),
          formatNumericForExcel(dischargeEnergy, 2),
          formatNumericForExcel(socBefore, 0),
          formatNumericForExcel(socAfter, 0),
          notes
        ]);
      }

      // Summary
      bessData.push(['']);
      bessData.push(['PODSUMOWANIE ROCZNE:']);
      bessData.push(['Liczba cykli rozładowania:', blockNum]);
      bessData.push(['Ekwiwalent pełnych cykli:', formatNumericForExcel(annualCycles, 1)]);
      bessData.push(['Szacowana żywotność [lat]:', formatNumericForExcel(Math.min(15, 6000 / annualCycles), 1)]);
      bessData.push(['']);
      bessData.push(['KIEDY ŁADOWAĆ BESS:']);
      bessData.push(['Zalecenie:', 'Ładować w godzinach niskiej taryfy (np. 22:00-06:00) lub z nadwyżki PV']);
      bessData.push(['Min. czas ładowania [h]:', formatNumericForExcel(bessCapacity / bessPower, 1)]);

      const wsBess = XLSX.utils.aoa_to_sheet(bessData);
      wsBess['!cols'] = [
        { wch: 10 }, { wch: 12 }, { wch: 10 }, { wch: 12 }, { wch: 10 },
        { wch: 12 }, { wch: 16 }, { wch: 16 }, { wch: 16 },
        { wch: 12 }, { wch: 10 }, { wch: 20 }
      ];
      XLSX.utils.book_append_sheet(wb, wsBess, 'Harmonogram BESS');
    }

    // Save file
    const fileName = `peak_shaving_analysis_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(wb, fileName);
    console.log(`✅ Eksport zakończony: ${fileName}`);

  } catch (error) {
    console.error('Błąd eksportu:', error);
    alert('Błąd podczas eksportu: ' + error.message);
  }
}

// Export analysis to Excel
async function exportAnalysis() {
  if (!consumptionData) {
    alert('Brak danych do eksportu');
    return;
  }

  console.log('📥 Eksport analizy zużycia do Excel...');

  try {
    // Fetch fresh statistics from backend
    const statsResponse = await fetch(`${API_URLS.dataAnalysis}/statistics`);
    const stats = statsResponse.ok ? await statsResponse.json() : null;

    // Fetch seasonality data
    let seasonalityData = null;
    try {
      const seasonResponse = await fetch(`${API_URLS.dataAnalysis}/seasonality`);
      if (seasonResponse.ok) {
        seasonalityData = await seasonResponse.json();
      }
    } catch (e) {
      console.log('Brak danych sezonowości');
    }

    // Create workbook
    const wb = XLSX.utils.book_new();

    // ========== SHEET 1: PODSUMOWANIE ==========
    const summaryData = [
      ['ANALIZA ZUŻYCIA ENERGII'],
      [''],
      ['Data eksportu:', new Date().toLocaleString('pl-PL')],
      ['Źródło danych:', consumptionData.filename || 'Backend'],
      [''],
      ['STATYSTYKI ROCZNE'],
      ['Zużycie roczne [GWh]:', stats?.total_consumption_gwh?.toFixed(3) || '-'],
      ['Zużycie roczne [MWh]:', stats ? (stats.total_consumption_gwh * 1000).toFixed(1) : '-'],
      ['Moc szczytowa [MW]:', stats?.peak_power_mw?.toFixed(3) || '-'],
      ['Moc szczytowa [kW]:', stats ? (stats.peak_power_mw * 1000).toFixed(1) : '-'],
      ['Moc minimalna [kW]:', stats?.min_power_kw?.toFixed(1) || '-'],
      ['Moc średnia [MW]:', stats?.avg_power_mw?.toFixed(3) || '-'],
      ['Moc średnia [kW]:', stats ? (stats.avg_power_mw * 1000).toFixed(1) : '-'],
      [''],
      ['STATYSTYKI SZCZEGÓŁOWE'],
      ['Średnie zużycie dzienne [MWh]:', stats?.avg_daily_mwh?.toFixed(2) || '-'],
      ['Odchylenie standardowe [MW]:', stats?.std_dev_mw?.toFixed(3) || '-'],
      ['Współczynnik zmienności [%]:', stats?.variation_coef_pct?.toFixed(1) || '-'],
      ['Współczynnik obciążenia [%]:', stats?.load_factor_pct?.toFixed(1) || '-'],
      [''],
      ['OKRES DANYCH'],
      ['Liczba godzin:', stats?.hours || consumptionData.hourlyData?.values?.length || '-'],
      ['Liczba dni:', stats?.days || '-'],
      ['Data początkowa:', stats?.date_start || '-'],
      ['Data końcowa:', stats?.date_end || '-']
    ];

    const ws1 = XLSX.utils.aoa_to_sheet(summaryData);
    ws1['!cols'] = [{ wch: 30 }, { wch: 20 }];
    XLSX.utils.book_append_sheet(wb, ws1, 'Podsumowanie');

    // ========== SHEET 2: PROFIL DOBOWY ==========
    const dailyData = [
      ['ŚREDNI PROFIL DOBOWY'],
      [''],
      ['Godzina', 'Średnia moc [MW]', 'Średnia moc [kW]']
    ];

    if (stats?.daily_profile_mw) {
      stats.daily_profile_mw.forEach((mw, hour) => {
        dailyData.push([
          `${hour.toString().padStart(2, '0')}:00`,
          mw.toFixed(3),
          (mw * 1000).toFixed(1)
        ]);
      });

      // Add summary row
      const avgMw = stats.daily_profile_mw.reduce((a, b) => a + b, 0) / 24;
      const maxMw = Math.max(...stats.daily_profile_mw);
      const minMw = Math.min(...stats.daily_profile_mw);
      dailyData.push(['']);
      dailyData.push(['Średnia:', avgMw.toFixed(3), (avgMw * 1000).toFixed(1)]);
      dailyData.push(['Maximum:', maxMw.toFixed(3), (maxMw * 1000).toFixed(1)]);
      dailyData.push(['Minimum:', minMw.toFixed(3), (minMw * 1000).toFixed(1)]);
    }

    const ws2 = XLSX.utils.aoa_to_sheet(dailyData);
    ws2['!cols'] = [{ wch: 12 }, { wch: 18 }, { wch: 18 }];
    XLSX.utils.book_append_sheet(wb, ws2, 'Profil Dobowy');

    // ========== SHEET 3: PROFIL TYGODNIOWY ==========
    const dayNames = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota', 'Niedziela'];
    const weeklyData = [
      ['PROFIL TYGODNIOWY'],
      [''],
      ['Dzień tygodnia', 'Średnie zużycie [MWh/dzień]', 'Typ dnia']
    ];

    if (stats?.weekly_profile_mwh) {
      stats.weekly_profile_mwh.forEach((mwh, day) => {
        const dayType = day < 5 ? 'Roboczy' : 'Weekend';
        weeklyData.push([dayNames[day], mwh.toFixed(2), dayType]);
      });

      // Add summary
      const workdays = stats.weekly_profile_mwh.slice(0, 5);
      const weekend = stats.weekly_profile_mwh.slice(5, 7);
      const avgWorkday = workdays.reduce((a, b) => a + b, 0) / 5;
      const avgWeekend = weekend.reduce((a, b) => a + b, 0) / 2;

      weeklyData.push(['']);
      weeklyData.push(['Średnia dni robocze:', avgWorkday.toFixed(2), '']);
      weeklyData.push(['Średnia weekend:', avgWeekend.toFixed(2), '']);
      weeklyData.push(['Różnica weekend vs robocze [%]:', ((avgWeekend / avgWorkday - 1) * 100).toFixed(1), '']);
    }

    const ws3 = XLSX.utils.aoa_to_sheet(weeklyData);
    ws3['!cols'] = [{ wch: 18 }, { wch: 28 }, { wch: 12 }];
    XLSX.utils.book_append_sheet(wb, ws3, 'Profil Tygodniowy');

    // ========== SHEET 4: PROFIL MIESIĘCZNY ==========
    const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                        'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];
    const monthlyData = [
      ['PROFIL MIESIĘCZNY'],
      [''],
      ['Miesiąc', 'Zużycie [MWh]', 'Zużycie [kWh]', 'Moc szczytowa [kW]', '% Rocznego']
    ];

    if (stats?.monthly_consumption) {
      const totalKwh = stats.monthly_consumption.reduce((a, b) => a + b, 0);

      stats.monthly_consumption.forEach((kwh, month) => {
        const mwh = kwh / 1000;
        const peakKw = stats.monthly_peaks ? stats.monthly_peaks[month] : '-';
        const pct = totalKwh > 0 ? (kwh / totalKwh * 100).toFixed(1) : '-';

        monthlyData.push([
          monthNames[month],
          mwh.toFixed(2),
          kwh.toFixed(0),
          typeof peakKw === 'number' ? peakKw.toFixed(1) : peakKw,
          pct + '%'
        ]);
      });

      // Add totals
      monthlyData.push(['']);
      monthlyData.push(['RAZEM:', (totalKwh / 1000).toFixed(2), totalKwh.toFixed(0), '', '100%']);
    }

    const ws4 = XLSX.utils.aoa_to_sheet(monthlyData);
    ws4['!cols'] = [{ wch: 14 }, { wch: 16 }, { wch: 16 }, { wch: 20 }, { wch: 12 }];
    XLSX.utils.book_append_sheet(wb, ws4, 'Profil Miesięczny');

    // ========== SHEET 5: SEZONOWOŚĆ ==========
    if (seasonalityData) {
      const seasonData = [
        ['ANALIZA SEZONOWOŚCI'],
        [''],
        ['Wynik sezonowości [%]:', (seasonalityData.seasonality_score * 100).toFixed(1)],
        ['Sezonowość wykryta:', seasonalityData.detected ? 'TAK' : 'NIE'],
        ['Komunikat:', seasonalityData.message || ''],
        [''],
        ['PODZIAŁ DNI NA PASMA'],
        ['Pasmo', 'Liczba dni', 'Opis']
      ];

      // Count bands
      const bandCounts = { High: 0, Mid: 0, Low: 0 };
      if (seasonalityData.daily_bands) {
        seasonalityData.daily_bands.forEach(day => {
          if (day.band in bandCounts) bandCounts[day.band]++;
        });
      }

      seasonData.push(['HIGH', bandCounts.High, 'Dni z wysokim zużyciem']);
      seasonData.push(['MID', bandCounts.Mid, 'Dni ze średnim zużyciem']);
      seasonData.push(['LOW', bandCounts.Low, 'Dni z niskim zużyciem']);
      seasonData.push(['']);

      // Monthly bands
      if (seasonalityData.monthly_bands && seasonalityData.monthly_bands.length > 0) {
        seasonData.push(['MIESIĘCZNA KLASYFIKACJA PASM']);
        seasonData.push(['Miesiąc', 'Dominujące pasmo', 'Zużycie [MWh]', 'P95 Mocy [kW]', 'Śr. Moc [kW]']);

        const sortedMonths = [...seasonalityData.monthly_bands].sort((a, b) => a.month.localeCompare(b.month));
        sortedMonths.forEach(mb => {
          seasonData.push([
            mb.month,
            mb.dominant_band,
            ((mb.consumption_kwh || 0) / 1000).toFixed(2),
            (mb.p95_power || 0).toFixed(0),
            (mb.avg_power || 0).toFixed(0)
          ]);
        });
      }

      // Recommended powers
      if (seasonalityData.band_powers) {
        seasonData.push(['']);
        seasonData.push(['REKOMENDOWANE LIMITY MOCY AC']);
        seasonData.push(['Pasmo', 'Rekomendowana moc [kW]', 'Opis']);
        seasonalityData.band_powers.forEach(bp => {
          seasonData.push([bp.band, Math.round(bp.p_recommended), `P95 z okresu ${bp.band}`]);
        });
      }

      const ws5 = XLSX.utils.aoa_to_sheet(seasonData);
      ws5['!cols'] = [{ wch: 20 }, { wch: 20 }, { wch: 18 }, { wch: 18 }, { wch: 18 }];
      XLSX.utils.book_append_sheet(wb, ws5, 'Sezonowość');
    }

    // ========== SHEET 6: DANE GODZINOWE ==========
    if (consumptionData.hourlyData && consumptionData.hourlyData.values) {
      const hourlySheetData = [
        ['DANE GODZINOWE'],
        [''],
        ['Timestamp', 'Data', 'Godzina', 'Dzień tygodnia', 'Miesiąc', 'Zużycie [kWh]', 'Moc [kW]']
      ];

      const values = consumptionData.hourlyData.values;
      const timestamps = consumptionData.hourlyData.timestamps;
      const dayNamesShort = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So'];

      // Limit to 50000 rows for Excel performance (full year = 8760)
      const maxRows = Math.min(values.length, 50000);

      for (let i = 0; i < maxRows; i++) {
        const ts = timestamps[i];
        const date = new Date(ts);
        const dateStr = date.toLocaleDateString('pl-PL');
        const hour = date.getHours();
        const dayOfWeek = dayNamesShort[date.getDay()];
        const month = date.getMonth() + 1;
        const kwh = values[i];

        hourlySheetData.push([
          ts,
          dateStr,
          `${hour.toString().padStart(2, '0')}:00`,
          dayOfWeek,
          month,
          kwh.toFixed(2),
          kwh.toFixed(2)  // For hourly data, kWh = kW (1 hour)
        ]);
      }

      if (values.length > maxRows) {
        hourlySheetData.push(['']);
        hourlySheetData.push([`... (pokazano ${maxRows} z ${values.length} wierszy)`]);
      }

      const ws6 = XLSX.utils.aoa_to_sheet(hourlySheetData);
      ws6['!cols'] = [
        { wch: 22 }, { wch: 12 }, { wch: 10 }, { wch: 14 }, { wch: 10 }, { wch: 14 }, { wch: 12 }
      ];
      XLSX.utils.book_append_sheet(wb, ws6, 'Dane Godzinowe');
    }

    // ========== SHEET 7: KRZYWA UPORZĄDKOWANA ==========
    if (consumptionData.hourlyData && consumptionData.hourlyData.values) {
      const values = consumptionData.hourlyData.values;
      const sorted = [...values].sort((a, b) => b - a);

      const ldcData = [
        ['KRZYWA UPORZĄDKOWANA MOCY (Load Duration Curve)'],
        [''],
        ['Pozycja', 'Czas trwania [h]', '% czasu', 'Moc [kW]', 'Moc [MW]']
      ];

      // Sample points for LDC (every 100 hours + key percentiles)
      const totalHours = sorted.length;
      const samplePoints = new Set([0, 1, 2, 3, 4, 5, 10, 20, 50, 100]);

      // Add percentile points
      [1, 5, 10, 25, 50, 75, 90, 95, 99].forEach(pct => {
        samplePoints.add(Math.floor(totalHours * pct / 100));
      });

      // Add every 100th hour
      for (let i = 0; i < totalHours; i += 100) {
        samplePoints.add(i);
      }
      samplePoints.add(totalHours - 1);

      const sortedPoints = [...samplePoints].sort((a, b) => a - b).filter(p => p < totalHours);

      sortedPoints.forEach(pos => {
        const pct = (pos / totalHours * 100).toFixed(2);
        const kw = sorted[pos];
        ldcData.push([
          pos + 1,
          pos + 1,
          pct + '%',
          kw.toFixed(2),
          (kw / 1000).toFixed(3)
        ]);
      });

      // Add statistics
      ldcData.push(['']);
      ldcData.push(['STATYSTYKI KRZYWEJ']);
      ldcData.push(['Moc maksymalna [kW]:', '', '', sorted[0].toFixed(2)]);
      ldcData.push(['Moc minimalna [kW]:', '', '', sorted[sorted.length - 1].toFixed(2)]);
      ldcData.push(['Percentyl P95 [kW]:', '', '', sorted[Math.floor(totalHours * 0.05)].toFixed(2)]);
      ldcData.push(['Percentyl P50 (mediana) [kW]:', '', '', sorted[Math.floor(totalHours * 0.5)].toFixed(2)]);
      ldcData.push(['Percentyl P5 [kW]:', '', '', sorted[Math.floor(totalHours * 0.95)].toFixed(2)]);

      const ws7 = XLSX.utils.aoa_to_sheet(ldcData);
      ws7['!cols'] = [{ wch: 30 }, { wch: 16 }, { wch: 12 }, { wch: 14 }, { wch: 12 }];
      XLSX.utils.book_append_sheet(wb, ws7, 'Krzywa Uporządkowana');
    }

    // Generate filename
    const dateStr = new Date().toISOString().split('T')[0];
    const periodStr = stats?.date_start && stats?.date_end
      ? `${stats.date_start.replace(/-/g, '')}_${stats.date_end.replace(/-/g, '')}`
      : dateStr;
    const filename = `Analiza_Zuzycia_${periodStr}.xlsx`;

    // Save file
    XLSX.writeFile(wb, filename);
    console.log('✅ Eksport zakończony:', filename);

  } catch (error) {
    console.error('Błąd eksportu:', error);
    alert('Błąd podczas eksportu: ' + error.message);
  }
}

/**
 * Run BESS optimization using PyPSA+HiGHS backend
 * Calls /api/economics/bess/optimize endpoint
 */
async function runBESSOptimization() {
  const btn = document.getElementById('bessOptimizeBtn');
  const detailsDiv = document.getElementById('bessOptimizationDetails');
  const capacityEl = document.getElementById('bessCapacityValue');
  const powerEl = document.getElementById('bessPowerValue');
  const rationaleEl = document.getElementById('bessRationale');
  const levelSelect = document.getElementById('bessLevelSelect');

  if (!currentLoadProfile || !peakShavingExportData?.tableRows) {
    alert('Brak danych do optymalizacji BESS');
    return;
  }

  // Get selected level from dropdown
  const selectedLevelName = levelSelect?.value || peakShavingExportData.recommended?.name;
  const selectedLevel = peakShavingExportData.tableRows.find(r => r.name === selectedLevelName);

  if (!selectedLevel) {
    alert('Nie wybrano poziomu peak shaving');
    return;
  }

  // Update button state
  btn.disabled = true;
  btn.innerHTML = '⏳ Optymalizuję...';
  btn.style.background = '#95a5a6';

  try {
    const threshold = selectedLevel.powerKW;

    const requestBody = {
      load_profile_kw: currentLoadProfile,
      timestamps: currentTimestamps,
      interval_minutes: currentIntervalMinutes,  // 15 for quarter-hourly, 60 for hourly
      peak_shaving_threshold_kw: threshold,
      bess_capex_per_kwh: 1500,
      bess_capex_per_kw: 300,
      depth_of_discharge: 0.8,
      round_trip_efficiency: 0.9,
      max_c_rate: 1.0,
      method: 'lp_relaxed'  // Use PyPSA+HiGHS LP optimization
    };

    console.log('🔋 Calling BESS optimization API:', {
      intervals: currentLoadProfile.length,
      intervalMinutes: currentIntervalMinutes,
      level: selectedLevelName,
      threshold: threshold,
      rating: selectedLevel.rating,
      method: 'lp_relaxed'
    });

    const response = await fetch(`${API_URLS.economics}/bess/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }

    const result = await response.json();
    console.log('🔋 BESS optimization result:', result);

    // Update UI with optimization results
    capacityEl.innerHTML = `${formatNumberEU(result.optimal_capacity_kwh, 0)} kWh`;
    powerEl.innerHTML = `${formatNumberEU(result.optimal_power_kw, 0)} kW`;

    // Update rationale with optimization details
    const resolutionLabel = currentIntervalMinutes === 15 ? '15-min' : 'godzinowa';
    rationaleEl.innerHTML = `
      <strong style="color: #27ae60;">✓ Zoptymalizowano dla ${selectedLevelName} (${result.method_used.toUpperCase()}, ${resolutionLabel})</strong><br>
      ${result.sizing_rationale}<br>
      <span style="font-size: 9px;">
        C-rate: ${formatNumberEU(result.c_rate_actual, 2)} |
        Cykle/rok: ${formatNumberEU(result.total_annual_cycles, 0)} |
        Żywotność: ${formatNumberEU(result.expected_lifetime_years, 1)} lat |
        Czas: ${formatNumberEU(result.optimization_time_ms, 0)}ms
      </span>
    `;

    // Show detailed breakdown
    detailsDiv.style.display = 'block';
    detailsDiv.innerHTML = `
      <div style="margin-top: 10px; padding: 8px; background: rgba(39, 174, 96, 0.1); border-radius: 4px; font-size: 11px;">
        <strong>📊 Szczegóły optymalizacji (PyPSA+HiGHS):</strong>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 6px;">
          <div>
            <span style="color: #7f8c8d;">CAPEX:</span><br>
            <strong>${formatNumberEU(result.capex_total_pln, 0)} PLN</strong>
          </div>
          <div>
            <span style="color: #7f8c8d;">Koszt efektywny:</span><br>
            <strong>${formatNumberEU(result.capex_per_kwh_effective, 0)} PLN/kWh</strong>
          </div>
          <div>
            <span style="color: #7f8c8d;">OPEX roczny:</span><br>
            <strong>${formatNumberEU(result.annual_opex_pln, 0)} PLN/rok</strong>
          </div>
        </div>
        <div style="margin-top: 8px;">
          <span style="color: #7f8c8d;">Największy blok:</span>
          ${formatNumberEU(result.largest_block?.total_energy_kwh || 0, 1)} kWh
          przez ${formatNumberEU(result.largest_block?.duration_hours || 0, 2)}h
          (${result.blocks_analyzed} bloków/rok)
        </div>
        ${result.warnings?.length > 0 ? `
        <div style="margin-top: 6px; color: #e67e22;">
          ⚠️ ${result.warnings.join(' | ')}
        </div>
        ` : ''}
      </div>
    `;

    // Update button
    btn.innerHTML = '✓ Zoptymalizowano';
    btn.style.background = 'linear-gradient(135deg, #27ae60 0%, #2ecc71 100%)';
    btn.disabled = false;

  } catch (error) {
    console.error('BESS optimization error:', error);
    btn.innerHTML = '❌ Błąd';
    btn.style.background = '#e74c3c';

    rationaleEl.innerHTML += `<br><span style="color: #e74c3c;">Błąd: ${error.message}</span>`;

    // Re-enable after delay
    setTimeout(() => {
      btn.innerHTML = '⚡ Optymalizuj (PyPSA+HiGHS)';
      btn.style.background = 'linear-gradient(135deg, #3498db 0%, #2980b9 100%)';
      btn.disabled = false;
    }, 3000);
  }
}

// Refresh data
function refreshData() {
  loadConsumptionData();
}

// Clear analysis (called when data is cleared)
function clearAnalysis() {
  consumptionData = null;
  showNoData();

  // Destroy all charts
  if (dailyChart) { dailyChart.destroy(); dailyChart = null; }
  if (weeklyChart) { weeklyChart.destroy(); weeklyChart = null; }
  if (monthlyChart) { monthlyChart.destroy(); monthlyChart = null; }
  if (loadDurationChart) { loadDurationChart.destroy(); loadDurationChart = null; }
  if (seasonalityChart) { seasonalityChart.destroy(); seasonalityChart = null; }

  // Hide seasonality section
  document.getElementById('seasonalitySection').style.display = 'none';
}

// Load seasonality analysis from backend
async function loadSeasonalityAnalysis() {
  try {
    const response = await fetch(`${API_URLS.dataAnalysis}/seasonality`);
    if (!response.ok) {
      document.getElementById('seasonalitySection').style.display = 'none';
      return;
    }

    const data = await response.json();

    // Show section
    document.getElementById('seasonalitySection').style.display = 'block';

    // Count bands
    const bandCounts = { High: 0, Mid: 0, Low: 0 };
    data.daily_bands.forEach(day => {
      if (day.band in bandCounts) {
        bandCounts[day.band]++;
      }
    });

    // Update stats
    document.getElementById('highDaysCount').textContent = bandCounts.High;
    document.getElementById('midDaysCount').textContent = bandCounts.Mid;
    document.getElementById('lowDaysCount').textContent = bandCounts.Low;
    document.getElementById('seasonalityScore').textContent = (data.seasonality_score * 100).toFixed(1);

    // Update message
    const msgEl = document.getElementById('seasonalityMessage');
    msgEl.textContent = data.message;
    msgEl.className = 'seasonality-message' + (data.detected ? '' : ' warning');

    // Generate chart
    generateSeasonalityChart(data.daily_bands);

    // Update monthly bands table and details
    updateMonthlyBandsDisplay(data);

  } catch (error) {
    console.error('Error loading seasonality:', error);
    document.getElementById('seasonalitySection').style.display = 'none';
  }
}

// Update monthly bands display with detailed information
function updateMonthlyBandsDisplay(data) {
  const monthNames = {
    '01': 'Styczeń', '02': 'Luty', '03': 'Marzec', '04': 'Kwiecień',
    '05': 'Maj', '06': 'Czerwiec', '07': 'Lipiec', '08': 'Sierpień',
    '09': 'Wrzesień', '10': 'Październik', '11': 'Listopad', '12': 'Grudzień'
  };

  const monthNamesShort = {
    '01': 'Sty', '02': 'Lut', '03': 'Mar', '04': 'Kwi',
    '05': 'Maj', '06': 'Cze', '07': 'Lip', '08': 'Sie',
    '09': 'Wrz', '10': 'Paź', '11': 'Lis', '12': 'Gru'
  };

  // Group months by band
  const bandMonths = { High: [], Mid: [], Low: [] };
  const bandConsumption = { High: 0, Mid: 0, Low: 0 };
  let totalConsumption = 0;

  // Process monthly_bands data
  if (data.monthly_bands && data.monthly_bands.length > 0) {
    data.monthly_bands.forEach(mb => {
      const monthNum = mb.month.split('-')[1]; // "2024-06" -> "06"
      const band = mb.dominant_band;
      if (band in bandMonths) {
        bandMonths[band].push(monthNamesShort[monthNum]);
        bandConsumption[band] += mb.consumption_kwh || 0;
        totalConsumption += mb.consumption_kwh || 0;
      }
    });
  }

  // Update band summary boxes
  ['high', 'mid', 'low'].forEach(band => {
    const bandKey = band.charAt(0).toUpperCase() + band.slice(1);
    const box = document.getElementById(`${band}MonthsList`);
    if (box) {
      const monthsList = bandMonths[bandKey].length > 0 ? bandMonths[bandKey].join(', ') : 'Brak';
      const consumption = (bandConsumption[bandKey] / 1000).toFixed(1); // kWh -> MWh
      const percentage = totalConsumption > 0 ? ((bandConsumption[bandKey] / totalConsumption) * 100).toFixed(1) : 0;

      box.querySelector('.band-months-list').textContent = monthsList;
      box.querySelector('.band-consumption').textContent = `${consumption} MWh (${percentage}% rocznego)`;
    }
  });

  // Build detailed monthly table
  const tableBody = document.getElementById('monthlyBandsTableBody');
  if (tableBody && data.monthly_bands) {
    let tableRows = '';

    // Sort by month
    const sortedMonths = [...data.monthly_bands].sort((a, b) => a.month.localeCompare(b.month));

    sortedMonths.forEach(mb => {
      const monthNum = mb.month.split('-')[1];
      const year = mb.month.split('-')[0];
      const monthName = `${monthNames[monthNum]} ${year}`;
      const band = mb.dominant_band;
      const bandClass = band.toLowerCase();

      const consumptionMWh = ((mb.consumption_kwh || 0) / 1000).toFixed(1);
      const p95kW = (mb.p95_power || 0).toFixed(0);
      const avgkW = (mb.avg_power || 0).toFixed(0);
      const percentage = totalConsumption > 0 ? (((mb.consumption_kwh || 0) / totalConsumption) * 100).toFixed(1) : 0;

      tableRows += `
        <tr>
          <td style="text-align:left;font-weight:500">${monthName}</td>
          <td style="text-align:center"><span class="band-badge ${bandClass}">${band}</span></td>
          <td style="text-align:right">${consumptionMWh}</td>
          <td style="text-align:right">${p95kW}</td>
          <td style="text-align:right">${avgkW}</td>
          <td style="text-align:right">${percentage}%</td>
        </tr>
      `;
    });

    tableBody.innerHTML = tableRows;
  }

  // Update recommended powers
  if (data.band_powers) {
    data.band_powers.forEach(bp => {
      const band = bp.band.toLowerCase();
      const powerEl = document.getElementById(`${band}PowerRecommended`);
      if (powerEl) {
        const powerKW = Math.round(bp.p_recommended);
        powerEl.textContent = `${powerKW.toLocaleString('pl-PL')} kW`;
      }
    });
  }
}

// Generate seasonality timeline chart
function generateSeasonalityChart(dailyBands) {
  const ctx = document.getElementById('seasonalityChart').getContext('2d');

  if (seasonalityChart) seasonalityChart.destroy();

  // Prepare data
  const labels = dailyBands.map(d => d.date.slice(5)); // MM-DD format
  const p95Values = dailyBands.map(d => (d.daily_p95 / 1000).toFixed(2)); // kW -> MW

  // Color by band
  const colors = dailyBands.map(d => {
    switch (d.band) {
      case 'High': return 'rgba(231, 76, 60, 0.8)';
      case 'Mid': return 'rgba(243, 156, 18, 0.8)';
      case 'Low': return 'rgba(39, 174, 96, 0.8)';
      default: return 'rgba(149, 165, 166, 0.8)';
    }
  });

  seasonalityChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'P95 Mocy [MW]',
        data: p95Values,
        backgroundColor: colors,
        borderColor: colors.map(c => c.replace('0.8', '1')),
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const idx = items[0].dataIndex;
              return dailyBands[idx].date;
            },
            label: (item) => {
              const idx = item.dataIndex;
              const band = dailyBands[idx].band;
              return `${item.formattedValue} MW (${band})`;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: 'P95 Mocy [MW]' }
        },
        x: {
          title: { display: true, text: 'Dzień' },
          ticks: {
            maxTicksLimit: 12,
            callback: function(val, index) {
              // Show only every ~30th label
              return index % 30 === 0 ? this.getLabelForValue(val) : '';
            }
          }
        }
      }
    }
  });
}

// ===========================================
// TARIFF ANALYSIS SECTION
// ===========================================

// Chart instances for tariff analysis
let tariffEnergyChart = null;
let tariffCostChart = null;
let tariffMonthlyChart = null;

/**
 * Get tariff configuration from settings (cached from shell or localStorage)
 */
function getTariffConfig() {
  // FIRST: Try cached settings from shell (most reliable in iframe context)
  if (cachedSystemSettings && cachedSystemSettings.tariffConfig) {
    return cachedSystemSettings.tariffConfig;
  }

  // Try to get from parent window (shell's settings)
  if (window.parent && window.parent.getSettings) {
    try {
      const settings = window.parent.getSettings();
      if (settings && settings.tariffConfig) {
        console.log('📊 Tariff config from parent window:', settings.tariffConfig);
        cachedSystemSettings = settings; // Cache for future use
        return settings.tariffConfig;
      }
    } catch (e) {
      // Cross-origin error expected in iframe
    }
  }

  // Try pv_system_settings (main settings storage - may not work in iframe)
  try {
    const pvSettings = localStorage.getItem('pv_system_settings');
    if (pvSettings) {
      const settings = JSON.parse(pvSettings);
      if (settings && settings.tariffConfig) {
        console.log('📊 Tariff config from pv_system_settings:', settings.tariffConfig);
        cachedSystemSettings = settings;
        return settings.tariffConfig;
      }
    }
  } catch (e) {
    // localStorage may not be accessible
  }

  // Request settings from shell if not cached
  if (!cachedSystemSettings) {
    console.log('📊 Requesting settings from shell...');
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
  }

  console.warn('📊 Using DEFAULT tariff config - no settings found!');

  // Default configuration (C12a two-zone)
  return {
    type: 'two_zone',
    name: 'C12a',
    flatRate: 750,
    twoZone: {
      dayRate: 850,
      nightRate: 450,
      weekday: { start: 6, end: 22 },
      weekend: { start: 6, end: 13 }
    },
    threeZone: {
      peakRate: 950,
      partialRate: 700,
      offPeakRate: 400,
      peak1: { start: 7, end: 13 },
      peak2: { start: 16, end: 21 },
      partial: { start: 6, end: 22 }
    }
  };
}

/**
 * Get hourly rates for a specific day type (weekday or weekend)
 * Returns array of 24 rates (PLN/MWh)
 */
function getTariffHourlyRates(dayType = 'weekday') {
  const config = getTariffConfig();
  const rates = new Array(24).fill(0);

  if (config.type === 'flat') {
    rates.fill(config.flatRate || 750);
  } else if (config.type === 'two_zone') {
    const zone = config.twoZone || {};
    const nightRate = zone.nightRate || 450;
    const dayRate = zone.dayRate || 850;

    const schedule = dayType === 'weekend' ? zone.weekend : zone.weekday;
    const start = schedule?.start || 6;
    const end = schedule?.end || 22;

    for (let h = 0; h < 24; h++) {
      rates[h] = (h >= start && h < end) ? dayRate : nightRate;
    }
  } else if (config.type === 'three_zone') {
    const zone = config.threeZone || {};
    const offPeakRate = zone.offPeakRate || 400;
    const partialRate = zone.partialRate || 700;
    const peakRate = zone.peakRate || 950;

    const peak1 = zone.peak1 || { start: 7, end: 13 };
    const peak2 = zone.peak2 || { start: 16, end: 21 };
    const partial = zone.partial || { start: 6, end: 22 };

    for (let h = 0; h < 24; h++) {
      if ((h >= peak1.start && h < peak1.end) || (h >= peak2.start && h < peak2.end)) {
        rates[h] = peakRate;
      } else if (h >= partial.start && h < partial.end) {
        rates[h] = partialRate;
      } else {
        rates[h] = offPeakRate;
      }
    }
  }

  return rates;
}

/**
 * Get zone name for a specific hour and day type
 */
function getZoneForHour(hour, dayType = 'weekday') {
  const config = getTariffConfig();

  if (config.type === 'flat') {
    return 'flat';
  } else if (config.type === 'two_zone') {
    const zone = config.twoZone || {};
    const schedule = dayType === 'weekend' ? zone.weekend : zone.weekday;
    const start = schedule?.start || 6;
    const end = schedule?.end || 22;
    return (hour >= start && hour < end) ? 'day' : 'night';
  } else if (config.type === 'three_zone') {
    const zone = config.threeZone || {};
    const peak1 = zone.peak1 || { start: 7, end: 13 };
    const peak2 = zone.peak2 || { start: 16, end: 21 };
    const partial = zone.partial || { start: 6, end: 22 };

    if ((hour >= peak1.start && hour < peak1.end) || (hour >= peak2.start && hour < peak2.end)) {
      return 'peak';
    } else if (hour >= partial.start && hour < partial.end) {
      return 'partial';
    } else {
      return 'off-peak';
    }
  }
  return 'flat';
}

/**
 * Perform tariff analysis on consumption data
 */
async function performTariffAnalysis() {
  const config = getTariffConfig();

  // Update info banner
  updateTariffInfoBanner(config);

  // Generate 24h visualization bar
  generate24hVisualizationBar(config);

  // Get 15-min or hourly data
  let dataValues = [];
  let dataTimestamps = [];
  let intervalMinutes = 60;

  try {
    // Try 15-min data first
    const quarterHourResponse = await fetch(`${API_URLS.dataAnalysis}/quarter-hour-data`);
    if (quarterHourResponse.ok) {
      const data = await quarterHourResponse.json();
      if (data.values && data.values.length > 0) {
        dataValues = data.values;
        dataTimestamps = data.timestamps;
        intervalMinutes = 15;
        console.log(`📊 Tariff analysis using 15-min data: ${dataValues.length} intervals`);
      }
    }
  } catch (e) {
    console.warn('Could not load 15-min data for tariff analysis:', e);
  }

  // Fallback to hourly
  if (dataValues.length === 0 && consumptionData?.hourlyData) {
    dataValues = consumptionData.hourlyData.values;
    dataTimestamps = consumptionData.hourlyData.timestamps;
    intervalMinutes = 60;
    console.log(`📊 Tariff analysis using hourly data: ${dataValues.length} intervals`);
  }

  if (dataValues.length === 0) {
    console.warn('No data available for tariff analysis');
    return;
  }

  // Calculate zone statistics
  const zoneStats = calculateZoneStatistics(dataValues, dataTimestamps, intervalMinutes, config);

  // Update UI
  updateTariffZonesGrid(zoneStats, config);
  updateTariffSummary(zoneStats);
  updateTariffDetailsTable(zoneStats);
  generateTariffCharts(zoneStats);

  // Calculate monthly breakdown
  const monthlyStats = calculateMonthlyTariffStats(dataValues, dataTimestamps, intervalMinutes, config);
  generateTariffMonthlyChart(monthlyStats, config);

  // Generate optimization tips
  generateTariffTips(zoneStats, config);
}

/**
 * Calculate statistics for each tariff zone
 */
function calculateZoneStatistics(values, timestamps, intervalMinutes, config) {
  const hoursPerInterval = intervalMinutes / 60;
  const zones = {};

  // Initialize zones based on tariff type
  if (config.type === 'flat') {
    zones.flat = { energy: 0, hours: 0, rate: config.flatRate || 750, intervals: 0 };
  } else if (config.type === 'two_zone') {
    zones.day = { energy: 0, hours: 0, rate: config.twoZone?.dayRate || 850, intervals: 0 };
    zones.night = { energy: 0, hours: 0, rate: config.twoZone?.nightRate || 450, intervals: 0 };
  } else if (config.type === 'three_zone') {
    zones.peak = { energy: 0, hours: 0, rate: config.threeZone?.peakRate || 950, intervals: 0 };
    zones.partial = { energy: 0, hours: 0, rate: config.threeZone?.partialRate || 700, intervals: 0 };
    zones['off-peak'] = { energy: 0, hours: 0, rate: config.threeZone?.offPeakRate || 400, intervals: 0 };
  }

  // Process each interval
  for (let i = 0; i < values.length; i++) {
    const value = values[i];
    const timestamp = timestamps[i];
    const date = new Date(timestamp);
    const hour = date.getHours();
    const dayOfWeek = date.getDay(); // 0 = Sunday
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const dayType = isWeekend ? 'weekend' : 'weekday';

    const zoneName = getZoneForHour(hour, dayType);
    const energyKWh = value * hoursPerInterval; // value is in kW

    if (zones[zoneName]) {
      zones[zoneName].energy += energyKWh;
      zones[zoneName].intervals += 1;
    }
  }

  // Calculate hours and costs
  const totalIntervals = values.length;
  const totalHours = totalIntervals * hoursPerInterval;
  let totalEnergy = 0;
  let totalCost = 0;

  Object.keys(zones).forEach(key => {
    const zone = zones[key];
    zone.hours = zone.intervals * hoursPerInterval;
    zone.cost = (zone.energy / 1000) * zone.rate; // energy in kWh, rate in PLN/MWh
    zone.pctTime = (zone.hours / totalHours) * 100;
    totalEnergy += zone.energy;
    totalCost += zone.cost;
  });

  // Calculate percentages
  Object.keys(zones).forEach(key => {
    const zone = zones[key];
    zone.pctEnergy = totalEnergy > 0 ? (zone.energy / totalEnergy) * 100 : 0;
    zone.pctCost = totalCost > 0 ? (zone.cost / totalCost) * 100 : 0;
  });

  return {
    zones,
    totalEnergy,
    totalCost,
    totalHours,
    avgPrice: totalEnergy > 0 ? (totalCost / (totalEnergy / 1000)) : 0 // PLN/MWh
  };
}

/**
 * Calculate monthly tariff statistics
 */
function calculateMonthlyTariffStats(values, timestamps, intervalMinutes, config) {
  const hoursPerInterval = intervalMinutes / 60;
  const months = {};

  for (let i = 0; i < values.length; i++) {
    const value = values[i];
    const timestamp = timestamps[i];
    const date = new Date(timestamp);
    const monthKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    const hour = date.getHours();
    const dayOfWeek = date.getDay();
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const dayType = isWeekend ? 'weekend' : 'weekday';

    const zoneName = getZoneForHour(hour, dayType);
    const energyKWh = value * hoursPerInterval;

    if (!months[monthKey]) {
      months[monthKey] = {};
    }
    if (!months[monthKey][zoneName]) {
      months[monthKey][zoneName] = { energy: 0, cost: 0 };
    }

    const rate = getTariffRateForZone(zoneName, config);
    months[monthKey][zoneName].energy += energyKWh;
    months[monthKey][zoneName].cost += (energyKWh / 1000) * rate;
  }

  return months;
}

/**
 * Get tariff rate for a specific zone
 */
function getTariffRateForZone(zoneName, config) {
  if (config.type === 'flat') {
    return config.flatRate || 750;
  } else if (config.type === 'two_zone') {
    return zoneName === 'day' ? (config.twoZone?.dayRate || 850) : (config.twoZone?.nightRate || 450);
  } else if (config.type === 'three_zone') {
    if (zoneName === 'peak') return config.threeZone?.peakRate || 950;
    if (zoneName === 'partial') return config.threeZone?.partialRate || 700;
    return config.threeZone?.offPeakRate || 400;
  }
  return 750;
}

/**
 * Update tariff info banner
 */
function updateTariffInfoBanner(config) {
  const typeBadge = document.getElementById('tariffTypeBadge');
  const nameDisplay = document.getElementById('tariffNameDisplay');

  const typeNames = {
    flat: 'Jednostrefowa',
    two_zone: 'Dwustrefowa',
    three_zone: 'Trzystrefowa'
  };

  if (typeBadge) {
    typeBadge.textContent = typeNames[config.type] || config.type;
  }

  if (nameDisplay) {
    nameDisplay.textContent = `Taryfa: ${config.name || 'Nieokreślona'}`;
  }
}

/**
 * Generate 24h visualization bar
 */
function generate24hVisualizationBar(config) {
  const bar = document.getElementById('tariff24hBarConsumption');
  if (!bar) return;

  let html = '';
  for (let h = 0; h < 24; h++) {
    const zone = getZoneForHour(h, 'weekday');
    html += `<div class="hour-block ${zone}" title="${h}:00 - ${zone}">${h}</div>`;
  }
  bar.innerHTML = html;
}

/**
 * Update tariff zones grid with cards
 */
function updateTariffZonesGrid(stats, config) {
  const grid = document.getElementById('tariffZonesGrid');
  if (!grid) return;

  const zoneLabels = {
    flat: 'Strefa jednolita',
    day: 'Strefa dzienna',
    night: 'Strefa nocna',
    peak: 'Szczyt',
    partial: 'Strefa pośrednia',
    'off-peak': 'Pozaszczyt'
  };

  let html = '';
  Object.keys(stats.zones).forEach(key => {
    const zone = stats.zones[key];
    const label = zoneLabels[key] || key;
    const energyMWh = (zone.energy / 1000).toFixed(1);
    const costPLN = formatNumberEU(zone.cost, 0);

    html += `
      <div class="tariff-zone-card ${key}">
        <div class="zone-header">
          <span class="zone-name">${label}</span>
          <span class="zone-rate">${zone.rate} PLN/MWh</span>
        </div>
        <div class="zone-stats">
          <div class="zone-stat">
            <div class="stat-value">${energyMWh}</div>
            <div class="stat-label">MWh</div>
          </div>
          <div class="zone-stat">
            <div class="stat-value">${costPLN}</div>
            <div class="stat-label">PLN</div>
          </div>
          <div class="zone-stat">
            <div class="stat-value">${zone.pctEnergy.toFixed(1)}%</div>
            <div class="stat-label">Zużycia</div>
          </div>
          <div class="zone-stat">
            <div class="stat-value">${zone.pctCost.toFixed(1)}%</div>
            <div class="stat-label">Kosztu</div>
          </div>
        </div>
      </div>
    `;
  });

  grid.innerHTML = html;
}

/**
 * Update tariff summary
 */
function updateTariffSummary(stats) {
  const totalCostEl = document.getElementById('tariffTotalCost');
  const avgPriceEl = document.getElementById('tariffAvgPrice');
  const savingsEl = document.getElementById('tariffSavingsPotential');

  if (totalCostEl) {
    totalCostEl.textContent = `${formatNumberEU(stats.totalCost, 0)} PLN`;
  }

  if (avgPriceEl) {
    avgPriceEl.textContent = `${formatNumberEU(stats.avgPrice, 1)} PLN/MWh`;
  }

  // Calculate potential savings (shift 10% from peak to off-peak)
  if (savingsEl) {
    const zones = stats.zones;
    let potentialSavings = 0;

    if (zones.peak && zones['off-peak']) {
      // 10% of peak energy moved to off-peak
      const shiftableEnergy = zones.peak.energy * 0.1;
      const peakRate = zones.peak.rate;
      const offPeakRate = zones['off-peak'].rate;
      potentialSavings = (shiftableEnergy / 1000) * (peakRate - offPeakRate);
    } else if (zones.day && zones.night) {
      const shiftableEnergy = zones.day.energy * 0.1;
      const dayRate = zones.day.rate;
      const nightRate = zones.night.rate;
      potentialSavings = (shiftableEnergy / 1000) * (dayRate - nightRate);
    }

    if (potentialSavings > 0) {
      savingsEl.textContent = `~${formatNumberEU(potentialSavings, 0)} PLN/rok (przesunięcie 10% zużycia)`;
    } else {
      savingsEl.textContent = '-';
    }
  }
}

/**
 * Update tariff details table
 */
function updateTariffDetailsTable(stats) {
  const tbody = document.getElementById('tariffDetailsTableBody');
  if (!tbody) return;

  const zoneLabels = {
    flat: 'Strefa jednolita',
    day: 'Strefa dzienna',
    night: 'Strefa nocna',
    peak: 'Szczyt',
    partial: 'Strefa pośrednia',
    'off-peak': 'Pozaszczyt'
  };

  const zoneHoursLabels = {
    flat: 'Całą dobę',
    day: '6:00-22:00 (roboczy)',
    night: '22:00-6:00',
    peak: '7:00-13:00, 16:00-21:00',
    partial: '6:00-22:00 (bez szczytu)',
    'off-peak': '22:00-6:00'
  };

  let html = '';
  Object.keys(stats.zones).forEach(key => {
    const zone = stats.zones[key];
    const label = zoneLabels[key] || key;
    const hoursLabel = zoneHoursLabels[key] || '-';

    html += `
      <tr>
        <td>
          <span class="zone-badge">
            <span class="zone-dot ${key}"></span>
            ${label}
          </span>
        </td>
        <td>${hoursLabel}</td>
        <td>${formatNumberEU(zone.hours, 0)}</td>
        <td>${formatNumberEU(zone.pctTime, 1)}%</td>
        <td>${formatNumberEU(zone.energy / 1000, 1)}</td>
        <td>${formatNumberEU(zone.pctEnergy, 1)}%</td>
        <td>${formatNumberEU(zone.rate, 0)}</td>
        <td>${formatNumberEU(zone.cost, 0)}</td>
        <td>${formatNumberEU(zone.pctCost, 1)}%</td>
      </tr>
    `;
  });

  // Total row
  html += `
    <tr class="total-row">
      <td><strong>RAZEM</strong></td>
      <td>-</td>
      <td>${formatNumberEU(stats.totalHours, 0)}</td>
      <td>100%</td>
      <td>${formatNumberEU(stats.totalEnergy / 1000, 1)}</td>
      <td>100%</td>
      <td>${formatNumberEU(stats.avgPrice, 0)}</td>
      <td>${formatNumberEU(stats.totalCost, 0)}</td>
      <td>100%</td>
    </tr>
  `;

  tbody.innerHTML = html;
}

/**
 * Generate tariff pie charts
 */
function generateTariffCharts(stats) {
  const zoneColors = {
    flat: '#3498db',
    day: '#f39c12',
    night: '#27ae60',
    peak: '#e74c3c',
    partial: '#f39c12',
    'off-peak': '#27ae60'
  };

  const zoneLabels = {
    flat: 'Strefa jednolita',
    day: 'Dzień',
    night: 'Noc',
    peak: 'Szczyt',
    partial: 'Pośrednia',
    'off-peak': 'Pozaszczyt'
  };

  const labels = Object.keys(stats.zones).map(k => zoneLabels[k] || k);
  const colors = Object.keys(stats.zones).map(k => zoneColors[k] || '#95a5a6');
  const energyData = Object.values(stats.zones).map(z => z.energy / 1000); // MWh
  const costData = Object.values(stats.zones).map(z => z.cost);

  // Energy chart
  const energyCtx = document.getElementById('tariffEnergyChart');
  if (energyCtx) {
    if (tariffEnergyChart) tariffEnergyChart.destroy();
    tariffEnergyChart = new Chart(energyCtx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: energyData,
          backgroundColor: colors,
          borderWidth: 2,
          borderColor: 'white'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${formatNumberEU(ctx.raw, 1)} MWh`
            }
          }
        }
      }
    });
  }

  // Cost chart
  const costCtx = document.getElementById('tariffCostChart');
  if (costCtx) {
    if (tariffCostChart) tariffCostChart.destroy();
    tariffCostChart = new Chart(costCtx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: costData,
          backgroundColor: colors,
          borderWidth: 2,
          borderColor: 'white'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { font: { size: 11 } }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${formatNumberEU(ctx.raw, 0)} PLN`
            }
          }
        }
      }
    });
  }
}

/**
 * Generate monthly stacked bar chart for tariff zones
 */
function generateTariffMonthlyChart(monthlyStats, config) {
  const ctx = document.getElementById('tariffMonthlyChart');
  if (!ctx) return;

  if (tariffMonthlyChart) tariffMonthlyChart.destroy();

  const monthLabels = Object.keys(monthlyStats).sort();
  const monthNames = monthLabels.map(m => {
    const [year, month] = m.split('-');
    const months = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
    return months[parseInt(month) - 1] + ' ' + year.slice(2);
  });

  const zoneColors = {
    flat: '#3498db',
    day: '#f39c12',
    night: '#27ae60',
    peak: '#e74c3c',
    partial: '#f39c12',
    'off-peak': '#27ae60'
  };

  const zoneLabels = {
    flat: 'Strefa jednolita',
    day: 'Dzień',
    night: 'Noc',
    peak: 'Szczyt',
    partial: 'Pośrednia',
    'off-peak': 'Pozaszczyt'
  };

  // Get all zone keys
  const allZones = new Set();
  Object.values(monthlyStats).forEach(month => {
    Object.keys(month).forEach(z => allZones.add(z));
  });

  const datasets = Array.from(allZones).map(zone => ({
    label: zoneLabels[zone] || zone,
    data: monthLabels.map(m => (monthlyStats[m][zone]?.cost || 0)),
    backgroundColor: zoneColors[zone] || '#95a5a6',
    borderWidth: 0
  }));

  tariffMonthlyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: monthNames,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'top',
          labels: { font: { size: 11 } }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatNumberEU(ctx.raw, 0)} PLN`
          }
        }
      },
      scales: {
        x: {
          stacked: true,
          title: { display: false }
        },
        y: {
          stacked: true,
          title: { display: true, text: 'Koszt [PLN]' },
          ticks: {
            callback: (val) => formatNumberEU(val, 0)
          }
        }
      }
    }
  });
}

/**
 * Generate optimization tips based on tariff analysis
 */
function generateTariffTips(stats, config) {
  const tipsList = document.getElementById('tariffTipsList');
  if (!tipsList) return;

  const tips = [];
  const zones = stats.zones;

  if (config.type === 'flat') {
    tips.push({
      icon: '💡',
      text: 'Taryfa jednostrefowa nie daje możliwości optymalizacji czasowej. Rozważ przejście na taryfę dwu- lub trzystrefową.',
      type: 'warning'
    });
  } else if (zones.peak && zones['off-peak']) {
    // Three-zone tips
    if (zones.peak.pctEnergy > 40) {
      tips.push({
        icon: '⚠️',
        text: `Wysokie zużycie w szczycie (${zones.peak.pctEnergy.toFixed(1)}%). Rozważ przesunięcie procesów produkcyjnych na godziny pozaszczytowe.`,
        type: 'warning'
      });
    }

    if (zones['off-peak'].pctEnergy < 20) {
      tips.push({
        icon: '🔋',
        text: 'Niskie wykorzystanie taniej strefy nocnej. Magazyn energii BESS mógłby ładować się w nocy i rozładowywać w szczycie.',
        type: 'success'
      });
    }

    const rateDiff = zones.peak.rate - zones['off-peak'].rate;
    if (rateDiff > 300) {
      const savingsPerMWh = rateDiff;
      tips.push({
        icon: '💰',
        text: `Różnica cen szczyt/pozaszczyt: ${savingsPerMWh} PLN/MWh. Każda MWh przesunięta z szczytu do nocy to oszczędność ${savingsPerMWh} PLN.`,
        type: 'success'
      });
    }
  } else if (zones.day && zones.night) {
    // Two-zone tips
    if (zones.day.pctEnergy > 80) {
      tips.push({
        icon: '⚠️',
        text: `Aż ${zones.day.pctEnergy.toFixed(1)}% zużycia w droższej strefie dziennej. Rozważ przesunięcie niektórych procesów na noc.`,
        type: 'warning'
      });
    }

    if (zones.night.pctEnergy > 30) {
      tips.push({
        icon: '✅',
        text: `Dobre wykorzystanie tańszej strefy nocnej (${zones.night.pctEnergy.toFixed(1)}%). Utrzymuj tę strategię.`,
        type: 'success'
      });
    }
  }

  // BESS recommendation
  if (stats.totalEnergy > 100000) { // > 100 MWh/rok
    tips.push({
      icon: '🔋',
      text: 'Przy tym wolumenie zużycia magazyn energii BESS może przynieść znaczące oszczędności poprzez arbitraż taryfowy.',
      type: 'success'
    });
  }

  let html = '';
  tips.forEach(tip => {
    html += `
      <div class="tariff-tip ${tip.type}">
        <span class="tip-icon">${tip.icon}</span>
        <span>${tip.text}</span>
      </div>
    `;
  });

  if (tips.length === 0) {
    html = '<div class="tariff-tip success"><span class="tip-icon">✅</span><span>Profil zużycia jest dobrze zoptymalizowany pod obecną taryfę.</span></div>';
  }

  tipsList.innerHTML = html;
}

/**
 * Navigate to tariff settings
 */
function goToTariffSettings() {
  // Send message to parent (shell) to switch to Settings module
  if (window.parent && window.parent.postMessage) {
    window.parent.postMessage({ type: 'NAVIGATE_TO', module: 'settings', section: 'tariff' }, '*');
  }
}

// Call tariff analysis after main analysis
const originalPerformAnalysis = performAnalysis;
performAnalysis = async function() {
  await originalPerformAnalysis();
  // Run tariff analysis after main analysis completes
  await performTariffAnalysis();
  // Initialize K-class analysis
  initKClassAnalysis();
};

// ============================================================================
// K-CLASS ANALYSIS (CAPACITY FEE - OPŁATA MOCOWA)
// ============================================================================

let kclassProfileChartInstance = null;
let kclassMonthlyChartInstance = null;
let lastKClassAnalysis = null;

/**
 * Easter date calculation (Anonymous Gregorian algorithm)
 */
function getEasterDate(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(year, month - 1, day);
}

/**
 * Polish holidays for a given year (matching calendar.py PolishHolidayCalendar)
 */
function getPolishHolidays(year) {
  const easter = getEasterDate(year);
  const easterMs = easter.getTime();
  const oneDay = 24 * 60 * 60 * 1000;

  const dates = [
    new Date(year, 0, 1),             // Nowy Rok
    new Date(year, 0, 6),             // Trzech Króli
    easter,                            // Wielkanoc (Niedziela)
    new Date(easterMs + oneDay),       // Poniedziałek Wielkanocny
    new Date(year, 4, 1),             // Święto Pracy
    new Date(year, 4, 3),             // Święto Konstytucji
    new Date(easterMs + 49 * oneDay), // Zielone Świątki
    new Date(easterMs + 60 * oneDay), // Boże Ciało
    new Date(year, 7, 15),            // Wniebowzięcie NMP
    new Date(year, 10, 1),            // Wszystkich Świętych
    new Date(year, 10, 11),           // Święto Niepodległości
    new Date(year, 11, 25),           // Boże Narodzenie 1
    new Date(year, 11, 26),           // Boże Narodzenie 2
  ];
  // Wigilia — only from 2025 (Dz.U. 2024 poz. 1911)
  if (year >= 2025) {
    dates.push(new Date(year, 11, 24));
  }

  return new Set(dates.map(d => {
    const yy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yy}-${mm}-${dd}`;
  }));
}

// Cache holidays per year
const _holidayCache = {};
function getHolidaysForYear(year) {
  if (!_holidayCache[year]) _holidayCache[year] = getPolishHolidays(year);
  return _holidayCache[year];
}

/**
 * Check if a date is a Polish workday (Mon-Fri, not a holiday)
 */
function isPolishWorkday(date) {
  const dayOfWeek = date.getDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) return false;

  // Use local date parts (not toISOString which converts to UTC)
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const dateStr = `${y}-${m}-${d}`;

  return !getHolidaysForYear(y).has(dateStr);
}

/**
 * Determine K-class from Δs value
 */
function getKClass(deltaS) {
  // Boundaries per Rozporządzenie Ministra Klimatu i Środowiska
  if (deltaS < 5) return { class: 'K1', coefficient: 0.17 };
  if (deltaS < 10) return { class: 'K2', coefficient: 0.50 };
  if (deltaS < 15) return { class: 'K3', coefficient: 0.83 };
  return { class: 'K4', coefficient: 1.00 };
}

/**
 * Calculate K-class analysis for capacity fee
 * @param {Array} loadHourly - 8760 hourly load values (kW)
 * @param {Array} pvHourly - 8760 hourly PV production values (kW)
 * @param {number} year - Reference year (default 2025)
 * @param {number} somPLNperKWh - Capacity fee rate (PLN/kWh)
 * @returns {Object} Analysis results
 */
function calculateKClassAnalysis(loadHourly, pvHourly, year = 2025, somPLNperKWh = 0.2194) {
  if (!loadHourly || loadHourly.length < 8760) {
    console.log('⚡ K-class: Insufficient data');
    return null;
  }

  // Calculate grid draw after PV
  const gridDraw = loadHourly.map((load, i) => {
    const pv = pvHourly?.[i] || 0;
    return Math.max(0, load - pv);
  });

  // Build daily data
  const dailyData = [];
  const startDate = new Date(year, 0, 1);

  for (let day = 0; day < 365; day++) {
    const currentDate = new Date(startDate);
    currentDate.setDate(startDate.getDate() + day);

    const isWorkday = isPolishWorkday(currentDate);
    const dayStart = day * 24;

    let selectedHoursBefore = 0, outsideHoursBefore = 0;
    let selectedHoursAfter = 0, outsideHoursAfter = 0;
    let selectedCountBefore = 0, outsideCountBefore = 0;
    let selectedCountAfter = 0, outsideCountAfter = 0;

    for (let hour = 0; hour < 24; hour++) {
      const idx = dayStart + hour;
      const loadBefore = loadHourly[idx] || 0;
      const loadAfter = gridDraw[idx] || 0;

      const isSelectedHour = isWorkday && hour >= 7 && hour < 22;

      if (isSelectedHour) {
        selectedHoursBefore += loadBefore;
        selectedHoursAfter += loadAfter;
        selectedCountBefore++;
        selectedCountAfter++;
      } else {
        outsideHoursBefore += loadBefore;
        outsideHoursAfter += loadAfter;
        outsideCountBefore++;
        outsideCountAfter++;
      }
    }

    // Calculate averages
    const avgSelectedBefore = selectedCountBefore > 0 ? selectedHoursBefore / selectedCountBefore : 0;
    const avgOutsideBefore = outsideCountBefore > 0 ? outsideHoursBefore / outsideCountBefore : 0;
    const avgSelectedAfter = selectedCountAfter > 0 ? selectedHoursAfter / selectedCountAfter : 0;
    const avgOutsideAfter = outsideCountAfter > 0 ? outsideHoursAfter / outsideCountAfter : 0;

    // Calculate Δs
    const deltaSBefore = avgOutsideBefore > 0 ? ((avgSelectedBefore / avgOutsideBefore) - 1) * 100 : 0;
    const deltaSAfter = avgOutsideAfter > 0 ? ((avgSelectedAfter / avgOutsideAfter) - 1) * 100 : 0;

    const kclassBefore = getKClass(deltaSBefore);
    const kclassAfter = getKClass(deltaSAfter);

    dailyData.push({
      date: currentDate,
      isWorkday,
      selectedHoursBefore,
      outsideHoursBefore,
      selectedHoursAfter,
      outsideHoursAfter,
      deltaSBefore,
      deltaSAfter,
      kclassBefore: kclassBefore.class,
      kclassAfter: kclassAfter.class,
      coeffBefore: kclassBefore.coefficient,
      coeffAfter: kclassAfter.coefficient
    });
  }

  // Aggregate results
  let totalZsBefore = 0, totalZsAfter = 0;
  let totalFeeBefore = 0, totalFeeAfter = 0;
  let feeWithSameKclass = 0;
  const kclassDistBefore = { K1: 0, K2: 0, K3: 0, K4: 0 };
  const kclassDistAfter = { K1: 0, K2: 0, K3: 0, K4: 0 };
  const monthlySavings = new Array(12).fill(0);
  let daysWithKclassImprovement = 0;

  for (const day of dailyData) {
    if (!day.isWorkday) continue;

    const zsBefore = day.selectedHoursBefore / 1000; // kWh to MWh
    const zsAfter = day.selectedHoursAfter / 1000;

    totalZsBefore += zsBefore;
    totalZsAfter += zsAfter;

    const feeBefore = day.coeffBefore * somPLNperKWh * day.selectedHoursBefore;
    const feeAfter = day.coeffAfter * somPLNperKWh * day.selectedHoursAfter;
    const feeWithOriginalKclass = day.coeffBefore * somPLNperKWh * day.selectedHoursAfter;

    totalFeeBefore += feeBefore;
    totalFeeAfter += feeAfter;
    feeWithSameKclass += feeWithOriginalKclass;

    kclassDistBefore[day.kclassBefore]++;
    kclassDistAfter[day.kclassAfter]++;

    if (day.coeffAfter < day.coeffBefore) {
      daysWithKclassImprovement++;
    }

    const month = day.date.getMonth();
    monthlySavings[month] += feeBefore - feeAfter;
  }

  // Calculate averages for hourly profile
  const hourlyProfileBefore = new Array(24).fill(0);
  const hourlyProfileAfter = new Array(24).fill(0);
  const hourlyCount = new Array(24).fill(0);

  for (let day = 0; day < 365; day++) {
    for (let hour = 0; hour < 24; hour++) {
      const idx = day * 24 + hour;
      hourlyProfileBefore[hour] += loadHourly[idx] || 0;
      hourlyProfileAfter[hour] += gridDraw[idx] || 0;
      hourlyCount[hour]++;
    }
  }

  for (let i = 0; i < 24; i++) {
    if (hourlyCount[i] > 0) {
      hourlyProfileBefore[i] /= hourlyCount[i];
      hourlyProfileAfter[i] /= hourlyCount[i];
    }
  }

  // Calculate aggregate deltas — energy-weighted (sum all ZS/ZPS, then one Δs formula)
  const workdays = dailyData.filter(d => d.isWorkday);
  const totalSelectedBefore = workdays.reduce((s, d) => s + d.selectedHoursBefore, 0);
  const totalOutsideBefore = workdays.reduce((s, d) => s + d.outsideHoursBefore, 0);
  const totalSelectedAfter = workdays.reduce((s, d) => s + d.selectedHoursAfter, 0);
  const totalOutsideAfter = workdays.reduce((s, d) => s + d.outsideHoursAfter, 0);
  const avgDeltaSBefore = totalOutsideBefore > 0 ? ((totalSelectedBefore / 15) / (totalOutsideBefore / 9) - 1) * 100 : 0;
  const avgDeltaSAfter = totalOutsideAfter > 0 ? ((totalSelectedAfter / 15) / (totalOutsideAfter / 9) - 1) * 100 : 0;
  const overallKclassBefore = getKClass(avgDeltaSBefore);
  const overallKclassAfter = getKClass(avgDeltaSAfter);

  // Two effects breakdown
  const savingsFromZsReduction = totalFeeBefore - feeWithSameKclass;
  const savingsFromKclassImprovement = feeWithSameKclass - totalFeeAfter;

  return {
    kclassBefore: overallKclassBefore.class,
    kclassAfter: overallKclassAfter.class,
    coeffBefore: overallKclassBefore.coefficient,
    coeffAfter: overallKclassAfter.coefficient,
    deltaSBefore: avgDeltaSBefore,
    deltaSAfter: avgDeltaSAfter,
    totalZsBefore,
    totalZsAfter,
    totalFeeBefore,
    totalFeeAfter,
    totalSavings: totalFeeBefore - totalFeeAfter,
    savingsPercent: totalFeeBefore > 0 ? ((totalFeeBefore - totalFeeAfter) / totalFeeBefore) * 100 : 0,
    savingsFromZsReduction,
    savingsFromKclassImprovement,
    daysWithKclassImprovement,
    kclassDistBefore,
    kclassDistAfter,
    monthlySavings,
    hourlyProfile: {
      before: hourlyProfileBefore,
      after: hourlyProfileAfter
    },
    dailyComparison: dailyData,
    avgPeakBefore: Math.max(...hourlyProfileBefore.slice(7, 22)),
    avgPeakAfter: Math.max(...hourlyProfileAfter.slice(7, 22)),
    avgOffpeakBefore: hourlyProfileBefore.filter((_, i) => i < 7 || i >= 22).reduce((a, b) => a + b, 0) / 9,
    avgOffpeakAfter: hourlyProfileAfter.filter((_, i) => i < 7 || i >= 22).reduce((a, b) => a + b, 0) / 9,
    flatnessBefore: Math.min(...hourlyProfileBefore) / Math.max(...hourlyProfileBefore),
    flatnessAfter: Math.min(...hourlyProfileAfter) / Math.max(...hourlyProfileAfter)
  };
}

/**
 * Update K-class widget UI
 */
function updateKClassWidget(analysis) {
  if (!analysis) {
    document.getElementById('capacityFeeKClassSection').style.display = 'none';
    return;
  }

  lastKClassAnalysis = analysis;
  document.getElementById('capacityFeeKClassSection').style.display = 'block';

  // Helper: get indicator - clear icons without confusing arrows
  // ✓ green = OSZCZĘDNOŚĆ (lepiej z PV)
  // ✗ red = WZROST (gorzej z PV)
  // = gray = bez zmian
  const getIndicator = (before, after, lowerIsBetter = true) => {
    const diff = after - before;
    const pctChange = before !== 0 ? ((after - before) / Math.abs(before)) * 100 : 0;

    if (Math.abs(diff) < 0.001 || Math.abs(pctChange) < 0.1) {
      return { icon: '=', color: '#9e9e9e', text: 'bez zmian', isGood: null };
    }

    const isGood = lowerIsBetter ? diff < 0 : diff > 0;
    const absChange = Math.abs(pctChange).toFixed(1);

    if (isGood) {
      // OSZCZĘDNOŚĆ - green checkmark
      return {
        icon: '✓',
        color: '#2e7d32',
        text: lowerIsBetter ? `oszcz. ${absChange}%` : `+${absChange}%`,
        isGood: true
      };
    } else {
      // WZROST - red X
      return {
        icon: '✗',
        color: '#c62828',
        text: lowerIsBetter ? `wzrost ${absChange}%` : `-${absChange}%`,
        isGood: false
      };
    }
  };

  // Update main K-class cards
  const kclassBefore = document.getElementById('kclassBeforePV');
  const kclassAfter = document.getElementById('kclassAfterPV');
  const coeffBefore = document.getElementById('kclassCoeffBefore');
  const coeffAfter = document.getElementById('kclassCoeffAfter');
  const deltaSBefore = document.getElementById('deltaSBefore');
  const deltaSAfter = document.getElementById('deltaSAfter');
  const changeIndicator = document.getElementById('kclassChangeIndicator');

  if (kclassBefore) kclassBefore.textContent = analysis.kclassBefore;
  if (kclassAfter) kclassAfter.textContent = analysis.kclassAfter;
  if (coeffBefore) coeffBefore.textContent = analysis.coeffBefore.toFixed(2);
  if (coeffAfter) coeffAfter.textContent = analysis.coeffAfter.toFixed(2);
  if (deltaSBefore) deltaSBefore.textContent = `${analysis.deltaSBefore.toFixed(1)}%`;
  if (deltaSAfter) deltaSAfter.textContent = `${analysis.deltaSAfter.toFixed(1)}%`;

  // Update change indicator arrow
  if (changeIndicator) {
    const kclassImproved = analysis.coeffAfter < analysis.coeffBefore;
    const kclassSame = analysis.coeffAfter === analysis.coeffBefore;
    if (kclassImproved) {
      changeIndicator.innerHTML = `
        <div style="font-size:40px;color:#4caf50;">✓</div>
        <div style="font-size:11px;color:#4caf50;font-weight:600;">LEPIEJ</div>
      `;
    } else if (kclassSame) {
      changeIndicator.innerHTML = `
        <div style="font-size:36px;color:#9e9e9e;">=</div>
        <div style="font-size:11px;color:#666;">bez zmian</div>
      `;
    } else {
      changeIndicator.innerHTML = `
        <div style="font-size:40px;color:#f44336;">✗</div>
        <div style="font-size:11px;color:#f44336;font-weight:600;">GORZEJ</div>
      `;
    }
  }

  // Build indicators table
  const indicatorsTable = document.getElementById('kclassIndicatorsTable');
  if (indicatorsTable) {
    // Rows with clear descriptions - lower value = better for most metrics
    const rows = [
      {
        name: 'Pobór w szczycie (ZS)',
        before: analysis.totalZsBefore.toFixed(0),
        after: analysis.totalZsAfter.toFixed(0),
        indicator: getIndicator(analysis.totalZsBefore, analysis.totalZsAfter, true),
        unit: 'MWh/rok',
        tooltip: 'Energia pobrana z sieci w godz. 7-22 (dni robocze). Mniej = niższa opłata.'
      },
      {
        name: 'Opłata mocowa roczna',
        before: Math.round(analysis.totalFeeBefore).toLocaleString('pl-PL'),
        after: Math.round(analysis.totalFeeAfter).toLocaleString('pl-PL'),
        indicator: getIndicator(analysis.totalFeeBefore, analysis.totalFeeAfter, true),
        unit: 'PLN/rok',
        tooltip: 'Roczna opłata mocowa. Niższa = oszczędność.'
      },
      {
        name: 'Współczynnik A (klasa K)',
        before: analysis.coeffBefore.toFixed(2),
        after: analysis.coeffAfter.toFixed(2),
        indicator: getIndicator(analysis.coeffBefore, analysis.coeffAfter, true),
        unit: '',
        tooltip: 'Mnożnik opłaty (K1=0.17, K4=1.00). Niższy = niższa opłata.'
      },
      {
        name: 'Wskaźnik profilu Δs',
        before: `${analysis.deltaSBefore.toFixed(1)}%`,
        after: `${analysis.deltaSAfter.toFixed(1)}%`,
        indicator: getIndicator(analysis.deltaSBefore, analysis.deltaSAfter, true),
        unit: '',
        tooltip: 'Różnica szczyt vs poza-szczyt. Niższy = płaski profil = lepsza klasa K.'
      }
    ];

    indicatorsTable.innerHTML = rows.map(row => `
      <tr style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:10px 4px;color:#333;" title="${row.tooltip}">${row.name} ${row.unit ? `<span style="color:#888;font-size:10px;">[${row.unit}]</span>` : ''}</td>
        <td style="padding:10px 4px;text-align:right;color:#666;">${row.before}</td>
        <td style="padding:10px 4px;text-align:center;">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:${row.indicator.color}20;color:${row.indicator.color};font-size:16px;font-weight:700;">
            ${row.indicator.icon}
          </span>
        </td>
        <td style="padding:10px 4px;text-align:right;font-weight:600;color:${row.indicator.color};">${row.after}</td>
        <td style="padding:10px 4px;text-align:right;font-size:10px;color:${row.indicator.color};font-weight:500;">${row.indicator.text}</td>
      </tr>
    `).join('');
  }

  // Update savings section
  const feeBefore = document.getElementById('kclassFeeBefore');
  const feeAfter = document.getElementById('kclassFeeAfter');
  const savingsZs = document.getElementById('kclassSavingsZs');
  const savingsKclass = document.getElementById('kclassSavingsKclass');
  const totalSavings = document.getElementById('kclassSavings');
  const totalSavingsPct = document.getElementById('kclassSavingsPct');

  if (feeBefore) feeBefore.textContent = Math.round(analysis.totalFeeBefore).toLocaleString('pl-PL');
  if (feeAfter) feeAfter.textContent = Math.round(analysis.totalFeeAfter).toLocaleString('pl-PL');
  if (savingsZs) savingsZs.textContent = Math.round(analysis.savingsFromZsReduction).toLocaleString('pl-PL');
  if (savingsKclass) savingsKclass.textContent = Math.round(analysis.savingsFromKclassImprovement).toLocaleString('pl-PL');
  if (totalSavings) totalSavings.textContent = `${Math.round(analysis.totalSavings).toLocaleString('pl-PL')} PLN`;
  if (totalSavingsPct) totalSavingsPct.textContent = `-${analysis.savingsPercent.toFixed(1)}% opłaty`;

  // Update histograms
  updateKClassHistograms(analysis);

  // Render charts
  renderKClassProfileChart(analysis);
  renderKClassMonthlyChart(analysis);
}

/**
 * Update K-class distribution histograms
 */
function updateKClassHistograms(analysis) {
  const histBefore = document.getElementById('kclassHistBefore');
  const histAfter = document.getElementById('kclassHistAfter');

  if (!histBefore || !histAfter) return;

  const classes = ['K1', 'K2', 'K3', 'K4'];
  const colors = { K1: '#4caf50', K2: '#8bc34a', K3: '#ff9800', K4: '#f44336' };
  const totalBefore = Object.values(analysis.kclassDistBefore).reduce((a, b) => a + b, 0);
  const totalAfter = Object.values(analysis.kclassDistAfter).reduce((a, b) => a + b, 0);

  histBefore.innerHTML = classes.map(k => {
    const count = analysis.kclassDistBefore[k];
    const pct = totalBefore > 0 ? (count / totalBefore) * 100 : 0;
    return `
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="width:24px;font-weight:600;color:${colors[k]};">${k}</span>
        <div style="flex:1;height:16px;background:#e0e0e0;border-radius:4px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${colors[k]};"></div>
        </div>
        <span style="width:50px;font-size:10px;text-align:right;">${count} dni</span>
      </div>
    `;
  }).join('');

  histAfter.innerHTML = classes.map(k => {
    const count = analysis.kclassDistAfter[k];
    const pct = totalAfter > 0 ? (count / totalAfter) * 100 : 0;
    return `
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="width:24px;font-weight:600;color:${colors[k]};">${k}</span>
        <div style="flex:1;height:16px;background:#e0e0e0;border-radius:4px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${colors[k]};"></div>
        </div>
        <span style="width:50px;font-size:10px;text-align:right;">${count} dni</span>
      </div>
    `;
  }).join('');
}

/**
 * Render K-class profile chart (hourly before/after PV)
 */
function renderKClassProfileChart(analysis) {
  const canvas = document.getElementById('kclassProfileChart');
  if (!canvas || !analysis?.hourlyProfile) return;

  const ctx = canvas.getContext('2d');

  if (kclassProfileChartInstance) {
    kclassProfileChartInstance.destroy();
  }

  const hours = Array.from({length: 24}, (_, i) => `${i}:00`);
  const maxVal = Math.max(...analysis.hourlyProfile.before, ...analysis.hourlyProfile.after) * 1.15;
  const selectedHoursBackground = hours.map((_, i) => (i >= 7 && i < 22) ? maxVal : 0);

  kclassProfileChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: hours,
      datasets: [
        {
          label: 'Godz. wybrane (7-22)',
          data: selectedHoursBackground,
          type: 'bar',
          backgroundColor: 'rgba(255, 193, 7, 0.15)',
          borderWidth: 0,
          barPercentage: 1.0,
          categoryPercentage: 1.0,
          order: 3
        },
        {
          label: 'Bez PV (zużycie)',
          data: analysis.hourlyProfile.before,
          borderColor: '#f44336',
          backgroundColor: 'transparent',
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          order: 1
        },
        {
          label: 'Z PV (pobór z sieci)',
          data: analysis.hourlyProfile.after,
          borderColor: '#4caf50',
          backgroundColor: 'transparent',
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          order: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index'
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: function(tooltipItem) {
            return tooltipItem.dataset.label !== 'Godz. wybrane (7-22)';
          },
          callbacks: {
            label: function(context) {
              return `${context.dataset.label}: ${context.parsed.y.toFixed(1)} kW`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            font: { size: 9 },
            callback: function(val, index) {
              return index % 3 === 0 ? this.getLabelForValue(val) : '';
            }
          }
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: {
            font: { size: 10 },
            callback: function(val) {
              return val.toFixed(0) + ' kW';
            }
          }
        }
      }
    }
  });
}

/**
 * Render K-class monthly savings chart
 */
function renderKClassMonthlyChart(analysis) {
  const canvas = document.getElementById('kclassMonthlyChart');
  if (!canvas || !analysis?.monthlySavings) return;

  const ctx = canvas.getContext('2d');

  if (kclassMonthlyChartInstance) {
    kclassMonthlyChartInstance.destroy();
  }

  const months = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];

  kclassMonthlyChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months,
      datasets: [{
        label: 'Oszczędność',
        data: analysis.monthlySavings.map(v => v / 1000),
        backgroundColor: '#4caf50',
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `${context.parsed.y.toFixed(2)} tys PLN`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 9 } }
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: {
            font: { size: 9 },
            callback: function(val) {
              return val.toFixed(1) + ' tys';
            }
          }
        }
      }
    }
  });
}

/**
 * Toggle K-class details panel
 */
function toggleKClassDetails() {
  const panel = document.getElementById('kclassDetailsPanel');
  const btn = document.getElementById('kclassToggleBtn');
  if (!panel) return;

  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    if (btn) btn.textContent = '▲ Ukryj';
  } else {
    panel.style.display = 'none';
    if (btn) btn.textContent = '▼ Szczegóły';
  }
}

// ============================================================================
// WATERMARK — 4-layer document traceability (matching economics module)
// ============================================================================
function _wmHash(input) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36).padStart(12, '0');
}
function _wmEncodeZW(payload) {
  let e = '\uFEFF';
  for (let i = 0; i < payload.length; i++) {
    if (i > 0) e += '\u200D';
    const bits = payload.charCodeAt(i).toString(2).padStart(8, '0');
    for (const b of bits) e += b === '0' ? '\u200B' : '\u200C';
  }
  return e + '\uFEFF';
}
function _wmStego(sheet, hash, rows, cols) {
  if (!hash || !rows.length || !cols.length) return;
  let idx = 0;
  const B = 0.00000001;
  for (const r of rows) {
    for (const c of cols) {
      const cell = sheet.getRow(r).getCell(c);
      if (typeof cell.value === 'number' && cell.value !== 0) {
        cell.value += (hash.charCodeAt(idx % hash.length) % 9 + 1) * B;
        idx++;
      }
    }
  }
}
function applyConsumptionWatermark(workbook, options = {}) {
  const proj = (window.parent && window.parent.sharedData && window.parent.sharedData.currentProject) || {};
  const now = new Date();
  const identity = {
    pid: proj.id || proj.uuid || 'unknown',
    name: proj.name || 'draft',
    cid: proj.companyId || 'none',
    ts: now.toISOString(),
  };
  const payload = `${identity.pid}|${identity.cid}|${identity.ts}|kclass`;
  const hash = _wmHash(payload);
  const shortId = `PV-${identity.pid}-${hash}`;
  console.log(`\uD83D\uDD12 Watermark: fingerprint ${hash} for project ${identity.pid}`);

  // Layer 1: Document properties
  workbook.creator = 'Pagra Energy Studio';
  workbook.lastModifiedBy = 'Pagra Energy Studio';
  workbook.created = now;
  workbook.modified = now;
  workbook.subject = shortId;
  workbook.keywords = `pv,analizator,kclass,${hash}`;
  workbook.description = `Report ${hash} generated ${now.toISOString().slice(0, 10)}`;

  // Layer 2: veryHidden sheet
  const hw = workbook.addWorksheet('_sys_config');
  hw.state = 'veryHidden';
  hw.getCell('A1').value = 'WATERMARK_V1';
  hw.getCell('A2').value = hash;
  hw.getCell('A3').value = identity.pid;
  hw.getCell('A4').value = identity.cid;
  hw.getCell('A5').value = identity.name;
  hw.getCell('A6').value = identity.ts;
  hw.getCell('A7').value = payload;
  hw.getCell('A8').value = _wmHash(hash + payload);

  // Layer 3: Zero-width Unicode in titles
  const zw = _wmEncodeZW(hash);
  for (const name of (options.visibleSheets || [])) {
    const ws = workbook.getWorksheet(name);
    if (!ws) continue;
    for (let c = 1; c <= 10; c++) {
      const cell = ws.getRow(1).getCell(c);
      if (cell.value && typeof cell.value === 'string' && cell.value.length > 5) {
        cell.value = cell.value + zw;
        break;
      }
    }
  }

  // Layer 4: Numeric steganography
  for (const t of (options.stegoTargets || [])) {
    const ws = workbook.getWorksheet(t.sheet);
    if (ws) _wmStego(ws, hash, t.rows, t.cols);
  }
  console.log(`\uD83D\uDD12 Watermark: 4 layers applied`);
}

/**
 * Export K-class analysis to Excel (Clean Look - ExcelJS)
 * Styled like CAPEX/EaaS exports in economics module
 */
async function exportKClassToExcel() {
  if (!lastKClassAnalysis) {
    alert('Brak danych do eksportu. Uruchom najpierw analizę.');
    return;
  }

  console.log('📥 Eksport analizy K-class do Excel (Clean Look)...');

  const analysis = lastKClassAnalysis;
  const exportDate = new Date().toLocaleString('pl-PL');

  // Get SOM rate from settings
  let somRate = 0.2194;
  try {
    const settings = cachedSystemSettings || JSON.parse(localStorage.getItem('pv_system_settings') || '{}');
    if (settings.capacityFeeRate) somRate = settings.capacityFeeRate / 1000;
  } catch (e) {}

  // Helper: round number
  const roundNum = (val, decimals = 2) => {
    if (val === null || val === undefined || isNaN(val)) return 0;
    return Math.round(val * Math.pow(10, decimals)) / Math.pow(10, decimals);
  };

  // Create workbook using ExcelJS
  const workbook = new ExcelJS.Workbook();

  // Load logo image
  let logoImageId = null;
  try {
    const logoResponse = await fetch('logo.png');
    if (logoResponse.ok) {
      const logoBlob = await logoResponse.blob();
      const logoBase64 = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.readAsDataURL(logoBlob);
      });
      logoImageId = workbook.addImage({ base64: logoBase64, extension: 'png' });
      console.log('\uD83D\uDCF7 Logo loaded successfully');
    }
  } catch (e) {
    console.warn('\u26A0\uFE0F Could not load logo:', e);
  }

  // Color constants (matching CAPEX export)
  const COLORS = {
    headerBg: 'FF37474F',      // Dark blue-grey
    headerText: 'FFFFFFFF',    // White
    titleText: 'FF1565C0',     // Blue
    sectionBg: 'FFE3F2FD',     // Light blue
    positive: 'FF2E7D32',      // Green
    positiveBg: 'FFE8F5E9',    // Light green
    negative: 'FFC62828',      // Red
    negativeBg: 'FFFFEBEE',    // Light red
    neutralText: 'FF616161',   // Grey
    borderLight: 'FFEEEEEE',   // Light grey border
    highlightBg: 'FFFFF8E1',   // Amber highlight
    highlightBorder: 'FFFFC107' // Amber border
  };

  // Number format with space as thousands separator (Polish)
  const numFmtStandard = '# ##0.00';
  const numFmtInt = '# ##0';
  const numFmtPct = '0.0%';

  // ========== SHEET 1: Podsumowanie ==========
  const sheet1 = workbook.addWorksheet('Podsumowanie');
  sheet1.columns = [
    { width: 3 },   // A: margin
    { width: 38 },  // B: labels
    { width: 16 },  // C: Bez PV
    { width: 16 },  // D: Z PV
    { width: 14 },  // E: Zmiana
    { width: 16 }   // F: Ocena
  ];
  sheet1.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Title
  sheet1.mergeCells('B1:F2');
  const titleCell = sheet1.getCell('B1');
  titleCell.value = 'ANALIZA KLASY K - OPŁATA MOCOWA';
  titleCell.font = { bold: true, size: 16, color: { argb: COLORS.titleText } };
  titleCell.alignment = { horizontal: 'center', vertical: 'middle' };

  // Export date
  sheet1.getCell('B3').value = 'Raport wygenerowany:';
  sheet1.getCell('B3').font = { color: { argb: COLORS.neutralText }, size: 10 };
  sheet1.getCell('C3').value = exportDate;
  sheet1.getCell('C3').font = { color: { argb: COLORS.neutralText }, size: 10 };

  // === Section: Parametry ===
  let row = 5;
  sheet1.mergeCells(`B${row}:F${row}`);
  const paramHeader = sheet1.getCell(`B${row}`);
  paramHeader.value = 'PARAMETRY ANALIZY';
  paramHeader.font = { bold: true, color: { argb: COLORS.titleText } };
  paramHeader.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  row++;

  const paramData = [
    ['Stawka opłaty mocowej (SOM)', roundNum(somRate * 1000, 2), 'PLN/MWh'],
    ['Scenariusz produkcji', `${currentProductionScenario} (×${currentScenarioFactor})`, ''],
    ['Rok analizy', 2025, ''],
    ['Godziny wybrane', '7:00 - 22:00', 'dni robocze']
  ];
  paramData.forEach(p => {
    sheet1.getCell(`B${row}`).value = p[0];
    sheet1.getCell(`B${row}`).font = { color: { argb: COLORS.neutralText } };
    sheet1.getCell(`C${row}`).value = p[1];
    sheet1.getCell(`C${row}`).font = { bold: true };
    if (typeof p[1] === 'number') sheet1.getCell(`C${row}`).numFmt = numFmtStandard;
    sheet1.getCell(`D${row}`).value = p[2];
    sheet1.getCell(`D${row}`).font = { color: { argb: COLORS.neutralText }, italic: true };
    row++;
  });

  // === Section: Porównanie ===
  row += 2;
  sheet1.mergeCells(`B${row}:F${row}`);
  const compHeader = sheet1.getCell(`B${row}`);
  compHeader.value = 'PORÓWNANIE: BEZ PV vs Z PV';
  compHeader.font = { bold: true, color: { argb: COLORS.titleText } };
  compHeader.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  row++;

  // Table headers
  const tableHeaders = ['Wskaźnik', 'Bez PV', 'Z PV', 'Zmiana', 'Ocena'];
  tableHeaders.forEach((h, i) => {
    const cell = sheet1.getCell(row, i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.headerBg } };
    cell.font = { bold: true, color: { argb: COLORS.headerText }, size: 10 };
    cell.alignment = { horizontal: 'center', vertical: 'middle' };
  });
  row++;

  // Comparison data
  const compData = [
    { name: 'Klasa K (agregat)', before: analysis.kclassBefore, after: analysis.kclassAfter, change: '',
      isGood: analysis.coeffAfter < analysis.coeffBefore, isNeutral: analysis.coeffAfter === analysis.coeffBefore },
    { name: 'Współczynnik A', before: roundNum(analysis.coeffBefore, 2), after: roundNum(analysis.coeffAfter, 2),
      change: roundNum(analysis.coeffAfter - analysis.coeffBefore, 2), isGood: analysis.coeffAfter < analysis.coeffBefore,
      isNeutral: analysis.coeffAfter === analysis.coeffBefore },
    { name: 'Wskaźnik Δs [%]', before: roundNum(analysis.deltaSBefore, 2), after: roundNum(analysis.deltaSAfter, 2),
      change: roundNum(analysis.deltaSAfter - analysis.deltaSBefore, 2), isGood: analysis.deltaSAfter < analysis.deltaSBefore,
      isNeutral: Math.abs(analysis.deltaSAfter - analysis.deltaSBefore) < 0.01 },
    { name: 'Energia ZS [MWh]', before: roundNum(analysis.totalZsBefore, 2), after: roundNum(analysis.totalZsAfter, 2),
      change: roundNum(analysis.totalZsAfter - analysis.totalZsBefore, 2), isGood: analysis.totalZsAfter < analysis.totalZsBefore,
      isNeutral: Math.abs(analysis.totalZsAfter - analysis.totalZsBefore) < 0.01 },
    { name: 'Śr. pobór szczytowy [kW]', before: roundNum(analysis.avgPeakBefore, 1), after: roundNum(analysis.avgPeakAfter, 1),
      change: roundNum(analysis.avgPeakAfter - analysis.avgPeakBefore, 1), isGood: analysis.avgPeakAfter < analysis.avgPeakBefore,
      isNeutral: Math.abs(analysis.avgPeakAfter - analysis.avgPeakBefore) < 0.1 }
  ];

  compData.forEach(d => {
    sheet1.getCell(row, 2).value = d.name;
    sheet1.getCell(row, 2).font = { bold: true };
    sheet1.getCell(row, 3).value = d.before;
    sheet1.getCell(row, 3).alignment = { horizontal: 'center' };
    if (typeof d.before === 'number') sheet1.getCell(row, 3).numFmt = numFmtStandard;
    sheet1.getCell(row, 4).value = d.after;
    sheet1.getCell(row, 4).alignment = { horizontal: 'center' };
    if (typeof d.after === 'number') sheet1.getCell(row, 4).numFmt = numFmtStandard;
    sheet1.getCell(row, 5).value = d.change;
    sheet1.getCell(row, 5).alignment = { horizontal: 'center' };
    if (typeof d.change === 'number') sheet1.getCell(row, 5).numFmt = numFmtStandard;

    // Ocena column with color
    const ocenaCell = sheet1.getCell(row, 6);
    if (d.isNeutral) {
      ocenaCell.value = '= BEZ ZMIAN';
      ocenaCell.font = { color: { argb: COLORS.neutralText } };
    } else if (d.isGood) {
      ocenaCell.value = '✓ LEPIEJ';
      ocenaCell.font = { bold: true, color: { argb: COLORS.positive } };
      ocenaCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.positiveBg } };
    } else {
      ocenaCell.value = '✗ GORZEJ';
      ocenaCell.font = { bold: true, color: { argb: COLORS.negative } };
      ocenaCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.negativeBg } };
    }
    ocenaCell.alignment = { horizontal: 'center' };

    // Alternate row background
    if (row % 2 === 0) {
      for (let c = 2; c <= 5; c++) {
        sheet1.getCell(row, c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
      }
    }
    row++;
  });

  // === Section: Opłata Mocowa ===
  row += 2;
  sheet1.mergeCells(`B${row}:F${row}`);
  const feeHeader = sheet1.getCell(`B${row}`);
  feeHeader.value = 'OPŁATA MOCOWA ROCZNA';
  feeHeader.font = { bold: true, color: { argb: COLORS.titleText } };
  feeHeader.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  row++;

  // Fee comparison
  sheet1.getCell(`B${row}`).value = 'Opłata BEZ PV';
  sheet1.getCell(`C${row}`).value = roundNum(analysis.totalFeeBefore, 0);
  sheet1.getCell(`C${row}`).numFmt = numFmtInt;
  sheet1.getCell(`C${row}`).font = { bold: true };
  sheet1.getCell(`D${row}`).value = 'PLN/rok';
  sheet1.getCell(`D${row}`).font = { color: { argb: COLORS.neutralText } };
  row++;

  sheet1.getCell(`B${row}`).value = 'Opłata Z PV';
  sheet1.getCell(`C${row}`).value = roundNum(analysis.totalFeeAfter, 0);
  sheet1.getCell(`C${row}`).numFmt = numFmtInt;
  sheet1.getCell(`C${row}`).font = { bold: true };
  sheet1.getCell(`D${row}`).value = 'PLN/rok';
  sheet1.getCell(`D${row}`).font = { color: { argb: COLORS.neutralText } };
  row += 2;

  // Savings highlight box
  sheet1.mergeCells(`B${row}:C${row}`);
  const savingsLabel = sheet1.getCell(`B${row}`);
  savingsLabel.value = 'OSZCZĘDNOŚĆ ROCZNA:';
  savingsLabel.font = { bold: true, size: 12 };
  savingsLabel.alignment = { horizontal: 'right', vertical: 'middle' };

  sheet1.mergeCells(`D${row}:E${row}`);
  const savingsValue = sheet1.getCell(`D${row}`);
  savingsValue.value = roundNum(analysis.totalSavings, 0);
  savingsValue.numFmt = numFmtInt + ' "PLN"';
  savingsValue.font = { bold: true, size: 14, color: { argb: COLORS.positive } };
  savingsValue.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.positiveBg } };
  savingsValue.alignment = { horizontal: 'center', vertical: 'middle' };
  savingsValue.border = {
    top: { style: 'medium', color: { argb: COLORS.positive } },
    bottom: { style: 'medium', color: { argb: COLORS.positive } },
    left: { style: 'medium', color: { argb: COLORS.positive } },
    right: { style: 'medium', color: { argb: COLORS.positive } }
  };

  sheet1.getCell(`F${row}`).value = `(${roundNum(analysis.savingsPercent, 1)}%)`;
  sheet1.getCell(`F${row}`).font = { bold: true, color: { argb: COLORS.positive } };
  row += 2;

  // Savings breakdown
  sheet1.getCell(`B${row}`).value = 'Rozbicie oszczędności:';
  sheet1.getCell(`B${row}`).font = { bold: true, color: { argb: COLORS.neutralText } };
  row++;
  sheet1.getCell(`B${row}`).value = '• Efekt redukcji ZS:';
  sheet1.getCell(`C${row}`).value = roundNum(analysis.savingsFromZsReduction, 0);
  sheet1.getCell(`C${row}`).numFmt = numFmtInt;
  sheet1.getCell(`D${row}`).value = 'PLN';
  sheet1.getCell(`E${row}`).value = `(${roundNum(analysis.totalSavings > 0 ? analysis.savingsFromZsReduction / analysis.totalSavings * 100 : 0, 0)}%)`;
  row++;
  sheet1.getCell(`B${row}`).value = '• Efekt poprawy klasy K:';
  sheet1.getCell(`C${row}`).value = roundNum(analysis.savingsFromKclassImprovement, 0);
  sheet1.getCell(`C${row}`).numFmt = numFmtInt;
  sheet1.getCell(`D${row}`).value = 'PLN';
  sheet1.getCell(`E${row}`).value = `(${roundNum(analysis.totalSavings > 0 ? analysis.savingsFromKclassImprovement / analysis.totalSavings * 100 : 0, 0)}%)`;

  // === Section: Rozkład Klas K ===
  row += 3;
  sheet1.mergeCells(`B${row}:F${row}`);
  const distHeader = sheet1.getCell(`B${row}`);
  distHeader.value = 'ROZKŁAD KLAS K (DNI ROBOCZE)';
  distHeader.font = { bold: true, color: { argb: COLORS.titleText } };
  distHeader.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  row++;

  // Distribution table headers
  const distHeaders = ['Klasa', 'Zakres Δs', 'Wsp. A', 'Bez PV', 'Z PV', 'Zmiana'];
  distHeaders.forEach((h, i) => {
    const cell = sheet1.getCell(row, i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.headerBg } };
    cell.font = { bold: true, color: { argb: COLORS.headerText }, size: 10 };
    cell.alignment = { horizontal: 'center', vertical: 'middle' };
  });
  row++;

  // Distribution data
  const distData = [
    ['K1', '< 5%', 0.17, analysis.kclassDistBefore.K1, analysis.kclassDistAfter.K1],
    ['K2', '5% do 10%', 0.50, analysis.kclassDistBefore.K2, analysis.kclassDistAfter.K2],
    ['K3', '10% do 15%', 0.83, analysis.kclassDistBefore.K3, analysis.kclassDistAfter.K3],
    ['K4', '\u2265 15%', 1.00, analysis.kclassDistBefore.K4, analysis.kclassDistAfter.K4]
  ];

  distData.forEach(d => {
    sheet1.getCell(row, 2).value = d[0];
    sheet1.getCell(row, 2).font = { bold: true };
    sheet1.getCell(row, 2).alignment = { horizontal: 'center' };
    sheet1.getCell(row, 3).value = d[1];
    sheet1.getCell(row, 3).alignment = { horizontal: 'center' };
    sheet1.getCell(row, 4).value = d[2];
    sheet1.getCell(row, 4).numFmt = '0.00';
    sheet1.getCell(row, 4).alignment = { horizontal: 'center' };
    sheet1.getCell(row, 5).value = d[3];
    sheet1.getCell(row, 5).alignment = { horizontal: 'center' };
    sheet1.getCell(row, 6).value = d[4];
    sheet1.getCell(row, 6).alignment = { horizontal: 'center' };

    const change = d[4] - d[3];
    const changeCell = sheet1.getCell(row, 7);
    changeCell.value = change > 0 ? `+${change}` : change;
    changeCell.alignment = { horizontal: 'center' };

    // Color K1 increase (good) and K4 decrease (good)
    if ((d[0] === 'K1' && change > 0) || (d[0] === 'K4' && change < 0)) {
      changeCell.font = { bold: true, color: { argb: COLORS.positive } };
      changeCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.positiveBg } };
    } else if ((d[0] === 'K1' && change < 0) || (d[0] === 'K4' && change > 0)) {
      changeCell.font = { bold: true, color: { argb: COLORS.negative } };
      changeCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.negativeBg } };
    }
    row++;
  });

  // ========== SHEET 2: Profil 24h ==========
  const sheet2 = workbook.addWorksheet('Profil 24h');
  sheet2.columns = [
    { width: 3 },   // A: margin
    { width: 10 },  // B: Godzina
    { width: 14 },  // C: Bez PV
    { width: 14 },  // D: Z PV
    { width: 14 },  // E: Redukcja kW
    { width: 12 },  // F: Redukcja %
    { width: 12 }   // G: Typ
  ];
  sheet2.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Title
  sheet2.getCell('B1').value = 'ŚREDNI PROFIL DOBOWY POBORU Z SIECI';
  sheet2.getCell('B1').font = { bold: true, size: 14, color: { argb: COLORS.titleText } };
  sheet2.mergeCells('B1:G2');

  // Headers
  const hourlyHeaders = ['Godzina', 'Bez PV [kW]', 'Z PV [kW]', 'Redukcja [kW]', 'Redukcja [%]', 'Typ'];
  hourlyHeaders.forEach((h, i) => {
    const cell = sheet2.getCell(4, i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.headerBg } };
    cell.font = { bold: true, color: { argb: COLORS.headerText }, size: 10 };
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
  });
  sheet2.getRow(4).height = 30;

  // Data rows
  for (let h = 0; h < 24; h++) {
    const r = h + 5;
    const before = analysis.hourlyProfile.before[h];
    const after = analysis.hourlyProfile.after[h];
    const isPeak = (h >= 7 && h < 22);

    sheet2.getCell(r, 2).value = `${h.toString().padStart(2, '0')}:00`;
    sheet2.getCell(r, 2).alignment = { horizontal: 'center' };

    sheet2.getCell(r, 3).value = roundNum(before, 1);
    sheet2.getCell(r, 3).numFmt = numFmtStandard;
    sheet2.getCell(r, 3).alignment = { horizontal: 'right' };

    sheet2.getCell(r, 4).value = roundNum(after, 1);
    sheet2.getCell(r, 4).numFmt = numFmtStandard;
    sheet2.getCell(r, 4).alignment = { horizontal: 'right' };

    // Formulas
    sheet2.getCell(r, 5).value = { formula: `C${r}-D${r}` };
    sheet2.getCell(r, 5).numFmt = numFmtStandard;
    sheet2.getCell(r, 5).alignment = { horizontal: 'right' };

    sheet2.getCell(r, 6).value = { formula: `IF(C${r}>0,(C${r}-D${r})/C${r}*100,0)` };
    sheet2.getCell(r, 6).numFmt = '0.0"%"';
    sheet2.getCell(r, 6).alignment = { horizontal: 'right' };

    sheet2.getCell(r, 7).value = isPeak ? 'SZCZYT' : 'poza';
    sheet2.getCell(r, 7).alignment = { horizontal: 'center' };

    // Highlight peak hours
    if (isPeak) {
      sheet2.getCell(r, 7).font = { bold: true, color: { argb: COLORS.positive } };
      sheet2.getCell(r, 7).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.positiveBg } };
    }
  }

  // Summary below data
  const summaryRow = 30;
  sheet2.getCell(`B${summaryRow}`).value = 'PODSUMOWANIE';
  sheet2.getCell(`B${summaryRow}`).font = { bold: true, color: { argb: COLORS.titleText } };
  sheet2.mergeCells(`B${summaryRow}:G${summaryRow}`);
  sheet2.getCell(`B${summaryRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };

  const summaryData2 = [
    ['Suma dobowa [kWh]', { formula: 'SUM(C5:C28)' }, { formula: 'SUM(D5:D28)' }, { formula: `C${summaryRow+1}-D${summaryRow+1}` }],
    ['Średnia godz. 7-22 [kW]', { formula: 'AVERAGE(C12:C26)' }, { formula: 'AVERAGE(D12:D26)' }, { formula: `C${summaryRow+2}-D${summaryRow+2}` }],
    ['Maksimum [kW]', { formula: 'MAX(C5:C28)' }, { formula: 'MAX(D5:D28)' }, ''],
    ['Minimum [kW]', { formula: 'MIN(C5:C28)' }, { formula: 'MIN(D5:D28)' }, '']
  ];

  summaryData2.forEach((s, idx) => {
    const r = summaryRow + 1 + idx;
    sheet2.getCell(r, 2).value = s[0];
    sheet2.getCell(r, 2).font = { bold: true };
    sheet2.getCell(r, 3).value = s[1];
    sheet2.getCell(r, 3).numFmt = numFmtStandard;
    sheet2.getCell(r, 4).value = s[2];
    sheet2.getCell(r, 4).numFmt = numFmtStandard;
    if (s[3]) {
      sheet2.getCell(r, 5).value = s[3];
      sheet2.getCell(r, 5).numFmt = numFmtStandard;
      sheet2.getCell(r, 5).font = { bold: true, color: { argb: COLORS.positive } };
    }
  });

  // ========== SHEET 3: Miesięcznie ==========
  const sheet3 = workbook.addWorksheet('Miesięcznie');
  sheet3.columns = [
    { width: 3 },   // A: margin
    { width: 16 },  // B: Miesiąc
    { width: 18 },  // C: Oszczędność
    { width: 14 }   // D: Udział
  ];
  sheet3.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Row 1: logo (set height)
  sheet3.getRow(1).height = 35;

  // Title (rows 2-3, shifted down for logo)
  sheet3.getCell('B2').value = 'OSZCZĘDNOŚCI MIESIĘCZNE OPŁATY MOCOWEJ';
  sheet3.getCell('B2').font = { bold: true, size: 14, color: { argb: COLORS.titleText } };
  sheet3.mergeCells('B2:D3');

  // Headers
  const monthHeaders = ['Miesiąc', 'Oszczędność [PLN]', 'Udział [%]'];
  monthHeaders.forEach((h, i) => {
    const cell = sheet3.getCell(4, i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.headerBg } };
    cell.font = { bold: true, color: { argb: COLORS.headerText }, size: 10 };
    cell.alignment = { horizontal: 'center', vertical: 'middle' };
  });

  const months = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                  'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

  months.forEach((m, i) => {
    const r = i + 5;
    sheet3.getCell(r, 2).value = m;
    sheet3.getCell(r, 3).value = analysis.monthlySavings[i];
    sheet3.getCell(r, 3).numFmt = numFmtStandard;
    sheet3.getCell(r, 3).alignment = { horizontal: 'right' };
    sheet3.getCell(r, 4).value = { formula: `IF($C$17>0,C${r}/$C$17*100,0)` };
    sheet3.getCell(r, 4).numFmt = '0.0"%"';
    sheet3.getCell(r, 4).alignment = { horizontal: 'right' };
  });

  // Total row
  sheet3.getCell('B17').value = 'SUMA ROCZNA';
  sheet3.getCell('B17').font = { bold: true };
  sheet3.getCell('B17').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  sheet3.getCell('C17').value = { formula: 'SUM(C5:C16)' };
  sheet3.getCell('C17').numFmt = numFmtStandard;
  sheet3.getCell('C17').font = { bold: true };
  sheet3.getCell('C17').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
  sheet3.getCell('D17').value = '100%';
  sheet3.getCell('D17').font = { bold: true };
  sheet3.getCell('D17').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };

  // ========== SHEET 4: Dane dzienne ==========
  const sheet4 = workbook.addWorksheet('Dane dzienne');
  sheet4.columns = [
    { width: 3 },   // A: margin
    { width: 11 },  // B: Data
    { width: 5 },   // C: Dzień
    { width: 5 },   // D: Typ
    { width: 12 },  // E: Pobór 7-22h bez PV
    { width: 12 },  // F: Pobór 22-7h bez PV
    { width: 8 },   // G: Δs bez
    { width: 7 },   // H: Klasa K bez
    { width: 7 },   // I: Wsp. A bez
    { width: 12 },  // J: Pobór 7-22h z PV
    { width: 12 },  // K: Pobór 22-7h z PV
    { width: 8 },   // L: Δs z
    { width: 7 },   // M: Klasa K z
    { width: 7 },   // N: Wsp. A z
    { width: 13 },  // O: Opłata bez PV
    { width: 13 },  // P: Opłata z PV
    { width: 13 },  // Q: Oszcz. mniejszy pobór
    { width: 13 },  // R: Oszcz. zmiana klasy
    { width: 13 },  // S: Oszcz. łączna
    { width: 10 }   // T: Zmiana klasy
  ];
  sheet4.views = [{ showGridLines: false, showRowColHeaders: false, state: 'frozen', ySplit: 4, xSplit: 0 }];

  // Title (rows 1-2)
  sheet4.getCell('B1').value = 'ANALIZA DZIENNA - WSZYSTKIE DNI ROKU';
  sheet4.getCell('B1').font = { bold: true, size: 14, color: { argb: COLORS.titleText } };
  sheet4.mergeCells('B1:T2');

  // Row 3: Section headers (merged, colored)
  sheet4.mergeCells('B3:D3');
  sheet4.getCell('B3').value = 'DZIEŃ';
  sheet4.getCell('B3').font = { bold: true, size: 10 };
  sheet4.getCell('B3').alignment = { horizontal: 'center', vertical: 'middle' };
  sheet4.getCell('B3').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0E0E0' } };

  sheet4.mergeCells('E3:I3');
  sheet4.getCell('E3').value = 'BEZ INSTALACJI PV';
  sheet4.getCell('E3').font = { bold: true, size: 10 };
  sheet4.getCell('E3').alignment = { horizontal: 'center', vertical: 'middle' };
  sheet4.getCell('E3').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };

  sheet4.mergeCells('J3:N3');
  sheet4.getCell('J3').value = 'Z INSTALACJĄ PV';
  sheet4.getCell('J3').font = { bold: true, size: 10 };
  sheet4.getCell('J3').alignment = { horizontal: 'center', vertical: 'middle' };
  sheet4.getCell('J3').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.positiveBg } };

  sheet4.mergeCells('O3:T3');
  sheet4.getCell('O3').value = 'EFEKT — OSZCZĘDNOŚĆ';
  sheet4.getCell('O3').font = { bold: true, size: 10 };
  sheet4.getCell('O3').alignment = { horizontal: 'center', vertical: 'middle' };
  sheet4.getCell('O3').fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.highlightBg } };

  // SOM cross-sheet ref (Sheet1 C6 = SOM in PLN/MWh)
  const somRefDaily = "'Podsumowanie'!$C$6";

  // Row 4: Column headers
  const dailyHeaders = [
    'Data', 'Dzień', 'Typ',
    'Pobór\n7-22h\n[kWh]', 'Pobór\n22-7h\n[kWh]', 'Δs\n[%]', 'Klasa\nK', 'Wsp.\nA',
    'Pobór\n7-22h\n[kWh]', 'Pobór\n22-7h\n[kWh]', 'Δs\n[%]', 'Klasa\nK', 'Wsp.\nA',
    'Opłata\nbez PV\n[PLN]', 'Opłata\nz PV\n[PLN]', 'Oszcz.\nmniejszy\npobór', 'Oszcz.\nzmiana\nklasy', 'Oszcz.\nłączna\n[PLN]', 'Zmiana\nklasy'
  ];
  dailyHeaders.forEach((h, i) => {
    const cell = sheet4.getCell(4, i + 2);
    cell.value = h;
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.headerBg } };
    cell.font = { bold: true, color: { argb: COLORS.headerText }, size: 9 };
    cell.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
  });
  sheet4.getRow(4).height = 40;

  const dayNames = ['Nd', 'Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'So'];

  analysis.dailyComparison.forEach((day, idx) => {
    const r = idx + 5;
    const row = sheet4.getRow(r);

    // B: Data, C: Dzień, D: Typ
    row.getCell(2).value = day.date.toLocaleDateString('pl-PL');
    row.getCell(3).value = dayNames[day.date.getDay()];
    row.getCell(4).value = day.isWorkday ? 'R' : 'W';

    // --- BEZ INSTALACJI PV ---
    // E: Pobór 7-22h [kWh] (pełna precyzja, wyświetlane jako int)
    row.getCell(5).value = day.selectedHoursBefore;
    row.getCell(5).numFmt = numFmtInt;
    // F: Pobór 22-7h [kWh] (pełna precyzja, wyświetlane jako int)
    row.getCell(6).value = day.outsideHoursBefore;
    row.getCell(6).numFmt = numFmtInt;
    // G: Δs [%] = IFERROR(((E/15)/(F/9)-1)*100, -100)
    row.getCell(7).value = { formula: `IFERROR(((E${r}/15)/(F${r}/9)-1)*100,-100)`, result: roundNum(day.deltaSBefore, 1) };
    row.getCell(7).numFmt = '0.0';
    // H: Klasa K = IF(Δs<5,"K1",IF(Δs<10,"K2",IF(Δs<15,"K3","K4")))
    row.getCell(8).value = { formula: `IF(G${r}<5,"K1",IF(G${r}<10,"K2",IF(G${r}<15,"K3","K4")))`, result: day.kclassBefore };
    row.getCell(8).alignment = { horizontal: 'center' };
    // I: Wsp. A = współczynnik z klasy K
    row.getCell(9).value = { formula: `IF(H${r}="K1",0.17,IF(H${r}="K2",0.5,IF(H${r}="K3",0.83,1)))`, result: roundNum(day.coeffBefore, 2) };
    row.getCell(9).numFmt = '0.00';

    // --- Z INSTALACJĄ PV ---
    // J: Pobór 7-22h [kWh] (pełna precyzja, wyświetlane jako int)
    row.getCell(10).value = day.selectedHoursAfter;
    row.getCell(10).numFmt = numFmtInt;
    // K: Pobór 22-7h [kWh] (pełna precyzja, wyświetlane jako int)
    row.getCell(11).value = day.outsideHoursAfter;
    row.getCell(11).numFmt = numFmtInt;
    // L: Δs [%]
    row.getCell(12).value = { formula: `IFERROR(((J${r}/15)/(K${r}/9)-1)*100,-100)`, result: roundNum(day.deltaSAfter, 1) };
    row.getCell(12).numFmt = '0.0';
    // M: Klasa K
    row.getCell(13).value = { formula: `IF(L${r}<5,"K1",IF(L${r}<10,"K2",IF(L${r}<15,"K3","K4")))`, result: day.kclassAfter };
    row.getCell(13).alignment = { horizontal: 'center' };
    // N: Wsp. A
    row.getCell(14).value = { formula: `IF(M${r}="K1",0.17,IF(M${r}="K2",0.5,IF(M${r}="K3",0.83,1)))`, result: roundNum(day.coeffAfter, 2) };
    row.getCell(14).numFmt = '0.00';

    // --- EFEKT — OSZCZĘDNOŚĆ ---
    // O: Opłata bez PV [PLN] = Wsp.A × SOM/1000 × Pobór 7-22h
    row.getCell(15).value = { formula: `I${r}*${somRefDaily}/1000*E${r}`, result: roundNum(day.coeffBefore * somRate * day.selectedHoursBefore, 2) };
    row.getCell(15).numFmt = numFmtStandard;
    // P: Opłata z PV [PLN] = Wsp.A × SOM/1000 × Pobór 7-22h
    row.getCell(16).value = { formula: `N${r}*${somRefDaily}/1000*J${r}`, result: roundNum(day.coeffAfter * somRate * day.selectedHoursAfter, 2) };
    row.getCell(16).numFmt = numFmtStandard;
    // Q: Oszcz. mniejszy pobór [PLN] = A_bez × SOM/1000 × (Pobór_bez - Pobór_z)
    row.getCell(17).value = { formula: `I${r}*${somRefDaily}/1000*(E${r}-J${r})`, result: roundNum(day.coeffBefore * somRate * (day.selectedHoursBefore - day.selectedHoursAfter), 2) };
    row.getCell(17).numFmt = numFmtStandard;
    // R: Oszcz. zmiana klasy [PLN] = (A_bez - A_z) × SOM/1000 × Pobór_z
    row.getCell(18).value = { formula: `(I${r}-N${r})*${somRefDaily}/1000*J${r}`, result: roundNum((day.coeffBefore - day.coeffAfter) * somRate * day.selectedHoursAfter, 2) };
    row.getCell(18).numFmt = numFmtStandard;
    // S: Oszcz. łączna [PLN] = Q + R (= O - P)
    row.getCell(19).value = { formula: `Q${r}+R${r}`, result: roundNum(day.coeffBefore * somRate * day.selectedHoursBefore - day.coeffAfter * somRate * day.selectedHoursAfter, 2) };
    row.getCell(19).numFmt = numFmtStandard;
    // T: Zmiana klasy
    const klassChange = !day.isWorkday ? '\u2014' : (day.kclassBefore === day.kclassAfter ? '\u2014' : `${day.kclassBefore} \u2192 ${day.kclassAfter}`);
    row.getCell(20).value = { formula: `IF(D${r}="W","\u2014",IF(H${r}=M${r},"\u2014",H${r}&" \u2192 "&M${r}))`, result: klassChange };
    row.getCell(20).alignment = { horizontal: 'center' };

    // Section background colors (matching row 3 headers)
    const fillDay = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
    const fillBez = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFECF4FE' } };
    const fillPV  = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFECF6ED' } };
    const fillEf  = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFBEB' } };
    for (let c = 2; c <= 4; c++)  row.getCell(c).fill = fillDay;
    for (let c = 5; c <= 9; c++)  row.getCell(c).fill = fillBez;
    for (let c = 10; c <= 14; c++) row.getCell(c).fill = fillPV;
    for (let c = 15; c <= 20; c++) row.getCell(c).fill = fillEf;

    // Style: weekends grey font, workdays bold type
    if (day.isWorkday) {
      row.getCell(4).font = { bold: true };
    } else {
      for (let c = 2; c <= 20; c++) {
        row.getCell(c).font = { color: { argb: 'FF9E9E9E' } };
      }
    }
  });

  // Statistics below data
  const statRow = analysis.dailyComparison.length + 6;
  const lastDataRow = analysis.dailyComparison.length + 4;

  sheet4.getCell(`B${statRow}`).value = 'STATYSTYKI';
  sheet4.getCell(`B${statRow}`).font = { bold: true, color: { argb: COLORS.titleText } };
  sheet4.mergeCells(`B${statRow}:T${statRow}`);
  sheet4.getCell(`B${statRow}`).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };

  sheet4.getCell(`B${statRow+1}`).value = 'Dni robocze:';
  sheet4.getCell(`C${statRow+1}`).value = { formula: `COUNTIF(D5:D${lastDataRow},"R")` };
  sheet4.getCell(`B${statRow+2}`).value = 'Dni wolne:';
  sheet4.getCell(`C${statRow+2}`).value = { formula: `COUNTIF(D5:D${lastDataRow},"W")` };
  sheet4.getCell(`B${statRow+3}`).value = 'Dni ze zmianą klasy K:';
  sheet4.getCell(`C${statRow+3}`).value = { formula: `COUNTIF(T5:T${lastDataRow},"*\u2192*")` };
  sheet4.getCell(`C${statRow+3}`).font = { bold: true, color: { argb: COLORS.positive } };

  // Fee totals
  sheet4.getCell(`B${statRow+5}`).value = 'SUMY (dni robocze)';
  sheet4.getCell(`B${statRow+5}`).font = { bold: true, color: { argb: COLORS.titleText } };
  sheet4.getCell(`B${statRow+6}`).value = 'Opłata bez PV [PLN]:';
  sheet4.getCell(`C${statRow+6}`).value = { formula: `SUM(O5:O${lastDataRow})`, result: roundNum(analysis.totalFeeBefore || 0, 0) };
  sheet4.getCell(`C${statRow+6}`).numFmt = numFmtStandard;
  sheet4.getCell(`B${statRow+7}`).value = 'Opłata z PV [PLN]:';
  sheet4.getCell(`C${statRow+7}`).value = { formula: `SUM(P5:P${lastDataRow})`, result: roundNum(analysis.totalFeeAfter || 0, 0) };
  sheet4.getCell(`C${statRow+7}`).numFmt = numFmtStandard;
  sheet4.getCell(`B${statRow+8}`).value = 'Oszcz. z mniejszego poboru [PLN]:';
  sheet4.getCell(`C${statRow+8}`).value = { formula: `SUM(Q5:Q${lastDataRow})`, result: roundNum(analysis.savingsFromZsReduction || 0, 0) };
  sheet4.getCell(`C${statRow+8}`).numFmt = numFmtStandard;
  sheet4.getCell(`B${statRow+9}`).value = 'Oszcz. ze zmiany klasy [PLN]:';
  sheet4.getCell(`C${statRow+9}`).value = { formula: `SUM(R5:R${lastDataRow})`, result: roundNum(analysis.savingsFromKclassImprovement || 0, 0) };
  sheet4.getCell(`C${statRow+9}`).numFmt = numFmtStandard;
  sheet4.getCell(`B${statRow+10}`).value = 'Oszczędność łączna [PLN]:';
  sheet4.getCell(`C${statRow+10}`).value = { formula: `C${statRow+8}+C${statRow+9}`, result: roundNum(analysis.totalSavings || 0, 0) };
  sheet4.getCell(`C${statRow+10}`).numFmt = numFmtStandard;
  sheet4.getCell(`C${statRow+10}`).font = { bold: true, color: { argb: COLORS.positive } };

  // ========== SHEET 5: Metodologia ==========
  const sheet5 = workbook.addWorksheet('Metodologia');
  sheet5.columns = [
    { width: 3 },   // A: margin
    { width: 80 }   // B: content
  ];
  sheet5.views = [{ showGridLines: false, showRowColHeaders: false }];

  // Row 1: logo (set height)
  sheet5.getRow(1).height = 35;

  const methodologyText = [
    { text: 'METODOLOGIA OBLICZEŃ - OPŁATA MOCOWA', isTitle: true },
    { text: '' },
    { text: 'PODSTAWA PRAWNA', isHeader: true },
    { text: '• Rozporządzenie Ministra Klimatu i Środowiska z dnia 27 grudnia 2024 r.' },
    { text: '• URE - Metodyka wyznaczania klasy odbiorcy końcowego' },
    { text: '• Obowiązuje od 1 stycznia 2025 roku' },
    { text: '' },
    { text: 'WZÓR NA OPŁATĘ MOCOWĄ (WOM)', isHeader: true },
    { text: '    WOM = A × SOM × ZS' },
    { text: '' },
    { text: '    gdzie:' },
    { text: '    WOM - opłata mocowa [PLN]' },
    { text: '    A   - współczynnik klasy K (zależny od profilu odbiorcy)' },
    { text: '    SOM - stawka opłaty mocowej [PLN/kWh]' },
    { text: '    ZS  - energia pobrana w godzinach wybranych [kWh]' },
    { text: '' },
    { text: 'WZÓR NA WSKAŹNIK Δs (DELTA S)', isHeader: true },
    { text: '    Δs = (średnia_wybrana / średnia_poza - 1) × 100%' },
    { text: '' },
    { text: '    ZS  - energia w godzinach wybranych (7-22 dni robocze) [kWh]' },
    { text: '    ZPS - energia poza godzinami wybranymi [kWh]' },
    { text: '' },
    { text: 'KLASYFIKACJA KLAS K', isHeader: true },
    { text: '    K1: Δs < 5%      → A = 0.17 (profil bardzo płaski, 83% rabatu)' },
    { text: '    K2: 5% ≤ Δs < 10%  → A = 0.50 (profil płaski, 50% rabatu)' },
    { text: '    K3: 10% ≤ Δs < 15% → A = 0.83 (profil umiarkowany, 17% rabatu)' },
    { text: '    K4: Δs ≥ 15%     → A = 1.00 (profil szczytowy, brak rabatu)' },
    { text: '' },
    { text: 'GODZINY WYBRANE', isHeader: true },
    { text: '    7:00 - 22:00 w dni robocze' },
    { text: '    Wykluczone: weekendy i święta państwowe' },
    { text: '' },
    { text: 'WPŁYW PV NA OPŁATĘ MOCOWĄ', isHeader: true },
    { text: '    1. REDUKCJA ZS - PV zmniejsza pobór w godz. 7-22' },
    { text: '    2. POPRAWA KLASY K - PV spłaszcza profil dobowy' },
    { text: '' },
    { text: 'Wygenerowano przez Analizator PV', isFooter: true }
  ];

  methodologyText.forEach((item, idx) => {
    const r = idx + 2;
    const cell = sheet5.getCell(r, 2);
    cell.value = item.text;
    if (item.isTitle) {
      cell.font = { bold: true, size: 16, color: { argb: COLORS.titleText } };
    } else if (item.isHeader) {
      cell.font = { bold: true, size: 12, color: { argb: COLORS.titleText } };
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLORS.sectionBg } };
    } else if (item.isFooter) {
      cell.font = { italic: true, color: { argb: COLORS.neutralText } };
    } else {
      cell.font = { size: 11 };
    }
  });

  // ========== LOGO on all sheets ==========
  if (logoImageId !== null) {
    const logo = { width: 150, height: 38 };
    // Wide sheets: logo right-aligned in title row
    sheet1.addImage(logoImageId, { tl: { col: 5, row: 0.15 }, ext: logo });    // Sheet1: right edge (col F)
    sheet2.addImage(logoImageId, { tl: { col: 5.2, row: 0.15 }, ext: logo });  // Sheet2: right edge (col F-G)
    sheet4.addImage(logoImageId, { tl: { col: 18, row: 0.15 }, ext: logo });   // Sheet4: right edge (col S-T)
    // Narrow sheets: logo above title in dedicated row 1
    sheet3.addImage(logoImageId, { tl: { col: 2.5, row: 0.05 }, ext: logo }); // Sheet3: centered in row 1
    sheet5.addImage(logoImageId, { tl: { col: 1.2, row: 0.05 }, ext: logo }); // Sheet5: in row 1 above title
  }

  // ========== BRANDING footer on key sheets ==========
  const brandingText = `Wygenerowano: ${new Date().toLocaleDateString('pl-PL')} | Pagra Energy Studio`;
  const brandingFont = { italic: true, size: 9, color: { argb: 'FF9E9E9E' } };

  // Sheet 1: after last content row
  const s1BrandRow = sheet1.lastRow ? sheet1.lastRow.number + 2 : 30;
  sheet1.getCell(`B${s1BrandRow}`).value = brandingText;
  sheet1.getCell(`B${s1BrandRow}`).font = brandingFont;
  sheet1.mergeCells(`B${s1BrandRow}:D${s1BrandRow}`);

  // Sheet 4: after statistics
  const s4BrandRow = analysis.dailyComparison.length + 18;
  sheet4.getCell(`B${s4BrandRow}`).value = brandingText;
  sheet4.getCell(`B${s4BrandRow}`).font = brandingFont;
  sheet4.mergeCells(`B${s4BrandRow}:F${s4BrandRow}`);

  // Sheet 5: at the bottom of methodology
  const s5BrandRow = sheet5.lastRow ? sheet5.lastRow.number + 2 : 30;
  sheet5.getCell(`B${s5BrandRow}`).value = brandingText;
  sheet5.getCell(`B${s5BrandRow}`).font = brandingFont;

  // ========== WATERMARK (4-layer document traceability) ==========
  try {
    const stegoRows = [];
    for (let i = 5; i <= Math.min(analysis.dailyComparison.length + 4, 50); i++) stegoRows.push(i);
    applyConsumptionWatermark(workbook, {
      visibleSheets: ['Podsumowanie', 'Dane dzienne'],
      stegoTargets: [{ sheet: 'Dane dzienne', rows: stegoRows, cols: [5, 6, 10, 11] }],
    });
  } catch (wmErr) {
    console.warn('\u26A0\uFE0F Watermark failed:', wmErr);
  }

  // Generate and download
  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const filename = `Analiza_Klasy_K_Oplata_Mocowa_${new Date().toISOString().split('T')[0]}.xlsx`;

  if (typeof saveAs !== 'undefined') {
    saveAs(blob, filename);
  } else {
    // Fallback
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  console.log('📥 Exported K-class analysis to Excel (Clean Look):', filename);
}

/**
 * Initialize K-class analysis
 */
function initKClassAnalysis() {
  console.log('⚡ K-class: Initializing...');

  if (!consumptionData || !consumptionData.hourlyData || !consumptionData.hourlyData.values) {
    console.log('⚡ K-class: No consumption data available');
    document.getElementById('capacityFeeKClassSection').style.display = 'none';
    return;
  }

  const loadHourly = consumptionData.hourlyData.values;

  // Try to get PV production from shell or generate synthetic
  let pvHourly = null;

  try {
    // Try to get from localStorage
    const pvSettings = localStorage.getItem('pv_system_settings');
    if (pvSettings) {
      const settings = JSON.parse(pvSettings);
      const capacity = settings.pvCapacity || settings.capacity_kWp || 0;
      const annualProduction = capacity * 1000; // Approx 1000 kWh/kWp

      if (annualProduction > 0) {
        console.log(`⚡ K-class: Generating synthetic PV profile (${annualProduction} kWh/year)`);
        pvHourly = new Array(8760).fill(0);

        for (let day = 0; day < 365; day++) {
          const seasonalFactor = 0.6 + 0.4 * Math.sin(2 * Math.PI * (day - 80) / 365);

          for (let hour = 0; hour < 24; hour++) {
            const idx = day * 24 + hour;
            if (hour >= 6 && hour <= 20) {
              const solarFactor = Math.sin(Math.PI * (hour - 6) / 14);
              pvHourly[idx] = (annualProduction / 8760) * 2.5 * solarFactor * seasonalFactor;
            }
          }
        }
      }
    }
  } catch (e) {
    console.log('⚡ K-class: Could not load PV settings:', e.message);
  }

  // If still no PV data, request from shell but don't hide widget
  if (!pvHourly) {
    console.log('⚡ K-class: Requesting PV data from shell...');
    window.parent.postMessage({ type: 'REQUEST_PV_DATA' }, '*');

    // Show widget with "before PV" only (no PV comparison)
    pvHourly = new Array(8760).fill(0); // Zero PV = show only consumption profile
    console.log('⚡ K-class: No PV configured - showing consumption profile only');
  }

  // Cache raw PV for scenario switching & apply current scenario factor
  if (pvHourly.some(v => v > 0)) {
    cachedRawPvData = [...pvHourly];
    pvHourly = pvHourly.map(v => v * currentScenarioFactor);
    console.log(`⚡ K-class: Applied scenario ${currentProductionScenario} (×${currentScenarioFactor}) to PV profile`);
  }

  // Handle 15-min data - aggregate to hourly
  let hourlyLoad = loadHourly;
  if (loadHourly.length > 10000) {
    // 15-min data (35040 for 365 days, 35136 for 366 days)
    console.log(`⚡ K-class: Converting ${loadHourly.length} 15-min points to hourly`);
    const hourCount = Math.floor(loadHourly.length / 4);
    hourlyLoad = [];
    for (let h = 0; h < hourCount; h++) {
      const start = h * 4;
      const avg = (loadHourly[start] + (loadHourly[start+1]||0) + (loadHourly[start+2]||0) + (loadHourly[start+3]||0)) / 4;
      hourlyLoad.push(avg);
    }
  }

  // Need at least 30 days of data (720 hours) for meaningful K-class analysis
  if (hourlyLoad.length < 720) {
    console.log('⚡ K-class: Insufficient data points:', hourlyLoad.length, '(need ≥720)');
    document.getElementById('capacityFeeKClassSection').style.display = 'none';
    return;
  }

  // Pad to 8760 if slightly shorter (e.g. 8736 for 364 days), or truncate if longer (leap year 8784)
  if (hourlyLoad.length < 8760) {
    console.log(`⚡ K-class: Padding data from ${hourlyLoad.length} to 8760 hours`);
    while (hourlyLoad.length < 8760) hourlyLoad.push(0);
  } else if (hourlyLoad.length > 8760) {
    console.log(`⚡ K-class: Truncating data from ${hourlyLoad.length} to 8760 hours`);
    hourlyLoad = hourlyLoad.slice(0, 8760);
  }

  // Get capacity fee rate from settings
  let somPLNperKWh = 0.2194; // Default
  try {
    const settings = cachedSystemSettings || JSON.parse(localStorage.getItem('pv_system_settings') || '{}');
    if (settings.capacityFeeRate) {
      somPLNperKWh = settings.capacityFeeRate / 1000;
    }
  } catch (e) {}

  // Diagnostic: log data stats for comparison with backend Excel export
  const loadSum = hourlyLoad.reduce((a, b) => a + b, 0);
  const pvSum = pvHourly ? pvHourly.reduce((a, b) => a + b, 0) : 0;
  console.log(`⚡ K-class: DATA DIAGNOSTIC — loadHourly: ${hourlyLoad.length} pts, sum=${loadSum.toFixed(0)} kWh, avg=${(loadSum/hourlyLoad.length).toFixed(1)} kW`);
  console.log(`⚡ K-class: DATA DIAGNOSTIC — pvHourly: ${pvHourly?.length || 0} pts, sum=${pvSum.toFixed(0)} kWh`);
  console.log(`⚡ K-class: DATA DIAGNOSTIC — SOM=${somPLNperKWh} PLN/kWh, year=2025`);
  console.log(`⚡ K-class: DATA DIAGNOSTIC — sample load[0..5]:`, hourlyLoad.slice(0, 6).map(v => v.toFixed(1)));

  // Use actual data year (from timestamps) instead of hardcoding
  const dataYear = consumptionData.year || 2025;

  // Calculate and update (use hourlyLoad which handles 15-min conversion)
  const analysis = calculateKClassAnalysis(hourlyLoad, pvHourly, dataYear, somPLNperKWh);
  updateKClassWidget(analysis);

  if (analysis) {
    console.log(`⚡ K-class: RESULT — feeBefore=${analysis.totalFeeBefore?.toFixed(0)}, feeAfter=${analysis.totalFeeAfter?.toFixed(0)}, savings=${analysis.totalSavings?.toFixed(0)}`);
    console.log(`⚡ K-class: RESULT — ZS_before=${analysis.totalZsBefore?.toFixed(1)} MWh, ZS_after=${analysis.totalZsAfter?.toFixed(1)} MWh`);
  }

  console.log('⚡ K-class: Analysis complete');
}

// Listen for PV data from shell
window.addEventListener('message', (event) => {
  // Shell sends: { type: 'PV_DATA_RESPONSE', data: { hourly_generation: [...], capacity_kwp: ... } }
  const pvData = event.data?.data;
  if (event.data?.type === 'PV_DATA_RESPONSE' && pvData?.hourly_generation && pvData.hourly_generation.length > 0) {
    console.log('⚡ K-class: Received PV data from shell:', pvData.hourly_generation.length, 'values, capacity:', pvData.capacity_kwp, 'kWp');

    // Cache raw PV data (P50, before scenario scaling)
    cachedRawPvData = [...pvData.hourly_generation];

    if (!consumptionData?.hourlyData?.values) {
      console.log('⚡ K-class: No consumption data yet, cannot re-run analysis');
      return;
    }

    // Re-run with current scenario factor
    rerunKClassWithScenario();
  }
});


// =============================================================================
// TARIFF COST COMPARISON — FULL COST (energy + distribution + capacity + fees)
// Uses tariff_presets.json for real OSD tariff data
// =============================================================================

let _tariffPresetsCache = null;

async function loadTariffPresets() {
  if (_tariffPresetsCache) return _tariffPresetsCache;
  try {
    // Try from settings module via nginx
    const resp = await fetch('/modules/settings/tariff_presets.json');
    if (resp.ok) {
      _tariffPresetsCache = await resp.json();
      return _tariffPresetsCache;
    }
  } catch (e) { console.warn('Failed to load tariff_presets.json:', e); }
  return null;
}

function getCapacityFeeConfig() {
  // Try to get from shell settings
  try {
    const settings = cachedSystemSettings || {};
    if (settings.capacityFeeConfig) return settings.capacityFeeConfig;
  } catch (e) {}
  // Default URE 58/2025
  return { somRate: 0.2194, selectedHours: { Q1: {start:7,end:22}, Q2: {start:7,end:22}, Q3: {start:7,end:22}, Q4: {start:7,end:22} } };
}

function isCapacityFeeHour(hour, month, dayOfWeek) {
  // Capacity fee applies 7:00-22:00 on workdays (Mon-Fri)
  if (dayOfWeek === 0 || dayOfWeek === 6) return false; // weekend
  const cfg = getCapacityFeeConfig();
  let q = 'Q1';
  if (month >= 3 && month <= 5) q = 'Q2';
  else if (month >= 6 && month <= 8) q = 'Q3';
  else if (month >= 9) q = 'Q4';
  const sh = cfg.selectedHours?.[q] || { start: 7, end: 22 };
  return hour >= sh.start && hour < sh.end;
}

function calculateFullTariffCost(tariff, commonFees, loadKw, timestamps, intervalMinutes, energyActiveByVoltage) {
  const hoursPerStep = intervalMinutes / 60;
  const n = loadKw.length;
  const touRates = tariff.touRates || {};
  const varFees = tariff.variableFees || {};
  const fixFees = tariff.fixedFees || {};
  const capFee = getCapacityFeeConfig();
  const somRate = capFee.somRate || 0.2194; // PLN/kWh

  // Distribution rates per zone (PLN/MWh -> PLN/kWh)
  const distPeak = (touRates.peakRate || touRates.dayRate || touRates.flatRate || 0);
  const distPartial = (touRates.partialRate || touRates.dayRate || touRates.flatRate || 0);
  const distOffPeak = (touRates.offPeakRate || touRates.nightRate || touRates.flatRate || 0);
  const distValley = (touRates.valleyRate || distOffPeak);

  // Energy active rates per zone (PLN/MWh) — from energyActiveByVoltage
  const voltage = (tariff.voltage || 'C').toUpperCase();
  const eaRates = (energyActiveByVoltage && energyActiveByVoltage[voltage]) || { flat: 420, peak: 520, partial: 420, offpeak: 320, valley: 260 };
  const eaPeak = eaRates.peak || eaRates.flat || 420;
  const eaPartial = eaRates.partial || eaRates.flat || 420;
  const eaOffPeak = eaRates.offpeak || eaRates.flat || 420;
  const eaValley = eaRates.valley || eaOffPeak;
  const eaFlat = eaRates.flat || 420;

  // Fixed per-MWh fees
  const qualityFee = varFees.qualityFee || commonFees.qualityFeeDefault || 33.10; // PLN/MWh
  const ozeFee = commonFees.ozeFee || 7.30;
  const cogenFee = commonFees.cogenerationFee || 3.0;
  const excise = commonFees.exciseTax || 5.0;
  const fixedPerMwh = (qualityFee + ozeFee + cogenFee + excise); // PLN/MWh

  // Monthly fixed fees
  const contractedPowerKw = fixFees.contractedPowerKw || (cachedSystemSettings?.fixedMonthlyFees?.contractedPowerKw || 50);
  const distFixedPerKwMonth = fixFees.distFixedRatePerKwMonth || 9.14;
  const osdSubscription = fixFees.osdSubscriptionFeeMonth || 5.54;
  const transitionFee = fixFees.transitionFeeMonth || 0;
  const monthlyFixed = (distFixedPerKwMonth * contractedPowerKw) + osdSubscription + transitionFee;
  const annualFixed = monthlyFixed * 12;

  // ToU zone determination
  const peakWindows = tariff.touRates?.weekday || {};
  const p1s = peakWindows.peak1Start ?? 7, p1e = peakWindows.peak1End ?? 13;
  const p2s = peakWindows.peak2Start ?? 16, p2e = peakWindows.peak2End ?? 21;
  const vStart = peakWindows.valleyStart ?? 0, vEnd = peakWindows.valleyEnd ?? 0;
  const weekendIsValley = tariff.touRates?.weekend?.isValley || false;
  const tariffType = tariff.tariffType || 'flat';

  let totalEnergyCostSprzedawca = 0;
  let totalDistCost = 0;
  let totalCapacityFeeCost = 0;
  let totalFixedPerMwhCost = 0;
  let totalEnergyKwh = 0;
  let peakEnergyKwh = 0, offpeakEnergyKwh = 0;

  for (let i = 0; i < n; i++) {
    const kw = loadKw[i];
    const kwh = kw * hoursPerStep;
    totalEnergyKwh += kwh;

    // Determine time from timestamp
    let dt;
    if (timestamps && timestamps[i]) {
      dt = new Date(timestamps[i]);
    } else {
      // Reconstruct from index
      const totalMinutes = i * intervalMinutes;
      dt = new Date(2025, 0, 1, 0, totalMinutes);
    }
    const hour = dt.getHours();
    const dayOfWeek = dt.getDay(); // 0=Sun
    const month = dt.getMonth(); // 0=Jan
    const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);

    // Distribution rate + energy active rate (PLN/MWh) based on zone
    let distRate, eaRate;
    if (tariffType === 'flat') {
      distRate = touRates.flatRate || distPeak;
      eaRate = eaFlat;
    } else if (isWeekend) {
      if (tariffType === 'four_zone' && weekendIsValley) {
        distRate = distValley;
        eaRate = eaValley;
      } else {
        distRate = distOffPeak;
        eaRate = eaOffPeak;
      }
    } else if (tariffType === 'four_zone' && hour >= vStart && hour < vEnd) {
      distRate = distValley;
      eaRate = eaValley;
    } else if ((hour >= p1s && hour < p1e) || (hour >= p2s && hour < p2e)) {
      distRate = distPeak;
      eaRate = eaPeak;
      peakEnergyKwh += kwh;
    } else if (tariffType === 'three_zone' || tariffType === 'four_zone') {
      if (hour >= 6 && hour < 22) {
        distRate = distPartial;
        eaRate = eaPartial;
      } else {
        distRate = distOffPeak;
        eaRate = eaOffPeak;
      }
    } else {
      // two_zone
      if (hour >= 6 && hour < 22) {
        distRate = distPeak;
        eaRate = eaPeak;
      } else {
        distRate = distOffPeak;
        eaRate = eaOffPeak;
      }
    }

    if (!isWeekend && !((hour >= p1s && hour < p1e) || (hour >= p2s && hour < p2e))) {
      offpeakEnergyKwh += kwh;
    }

    // Distribution cost (PLN/MWh, kwh is kWh)
    totalDistCost += kwh * distRate / 1000;

    // Energy active cost — sprzedawca, per zone (PLN/MWh)
    totalEnergyCostSprzedawca += kwh * eaRate / 1000;

    // Fixed per-MWh fees (quality, OZE, cogen, excise)
    totalFixedPerMwhCost += kwh * fixedPerMwh / 1000;

    // Capacity fee (only 7-22 workdays)
    if (isCapacityFeeHour(hour, month, dayOfWeek)) {
      totalCapacityFeeCost += kwh * somRate;
    }
  }
  const totalCost = totalDistCost + totalEnergyCostSprzedawca + totalCapacityFeeCost + totalFixedPerMwhCost + annualFixed;
  const totalMwh = totalEnergyKwh / 1000;
  const avgRate = totalCost / Math.max(totalEnergyKwh, 1);

  return {
    total_cost_pln: totalCost,
    avg_rate_pln_kwh: avgRate,
    total_energy_mwh: totalMwh,
    breakdown: {
      energy_active_pln: Math.round(totalEnergyCostSprzedawca),
      distribution_variable_pln: Math.round(totalDistCost),
      capacity_fee_pln: Math.round(totalCapacityFeeCost),
      quality_oze_cogen_excise_pln: Math.round(totalFixedPerMwhCost),
      fixed_monthly_pln: Math.round(annualFixed),
    },
    peak_energy_kwh: peakEnergyKwh,
    offpeak_energy_kwh: offpeakEnergyKwh,
  };
}

async function runTariffComparison() {
  const btn = document.getElementById('btnRunTariffComparison');
  const status = document.getElementById('tariffCompStatus');
  const tbody = document.getElementById('tariffComparisonTableBody');

  const hourlyData = consumptionData?.hourlyData;
  if (!consumptionData || !hourlyData || !hourlyData.values || hourlyData.values.length === 0) {
    status.textContent = 'Brak danych zuzycia! Najpierw wgraj dane w zakladce Konfiguracja.';
    status.style.color = '#f44336';
    return;
  }

  btn.disabled = true;
  btn.textContent = '⏳ Obliczam...';
  status.textContent = 'Ladowanie presetow taryfowych...';
  status.style.color = '#2196F3';

  try {
    const presets = await loadTariffPresets();
    if (!presets || !presets.operators) {
      throw new Error('Nie udalo sie zaladowac tariff_presets.json');
    }

    const loadKw = hourlyData.values;
    const timestamps = hourlyData.timestamps || null;
    const interval = 60; // hourly data
    const commonFees = presets.commonFees || {};
    const energyActiveByVoltage = presets.energyActiveByVoltage || {};

    status.textContent = `Obliczam ${Object.keys(presets.operators).length} OSD...`;

    const results = [];
    for (const [opName, opData] of Object.entries(presets.operators)) {
      for (const [tariffId, tariff] of Object.entries(opData.tariffs || {})) {
        const fullId = `${opName}_${tariffId}`;
        const calc = calculateFullTariffCost(tariff, commonFees, loadKw, timestamps, interval, energyActiveByVoltage);
        results.push({
          tariff_id: fullId,
          tariff_name: `${opData.label || opName} ${tariffId}`,
          osd: opName,
          group: tariffId,
          tariff_type: tariff.tariffType,
          voltage: tariff.voltage || '?',
          annual_cost_pln: calc.total_cost_pln,
          avg_rate_pln_kwh: calc.avg_rate_pln_kwh,
          total_energy_mwh: calc.total_energy_mwh,
          breakdown: calc.breakdown,
        });
      }
    }

    results.sort((a, b) => a.annual_cost_pln - b.annual_cost_pln);

    // Get current tariff cost from existing analysis
    const currentTariffCost = getCurrentTariffAnnualCost();
    const totalMwh = results[0]?.total_energy_mwh || 0;

    const data = {
      results,
      rdn_result: null, // RDN will be fetched from backend
      total_energy_mwh: totalMwh,
      cheapest: results[0]?.tariff_id,
      most_expensive: results[results.length - 1]?.tariff_id,
    };

    // Also fetch RDN from backend
    try {
      const startDate = new Date().getFullYear() + '-01-01';
      const rdnResp = await fetch(`${API_URLS.bessDispatch}/tariff-cost-comparison`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ load_kw: loadKw, start_date: startDate, interval_minutes: interval }),
      });
      if (rdnResp.ok) {
        const rdnData = await rdnResp.json();
        if (rdnData.rdn_result) {
          // Add fixed fees to RDN too (capacity fee + quality + monthly fixed)
          const capFeeCfg = getCapacityFeeConfig();
          // Approximate: use same capacity fee + fixed fees as cheapest tariff
          const cheapestBreakdown = results[0]?.breakdown || {};
          const rdnTotal = rdnData.rdn_result.annual_cost_pln +
            (cheapestBreakdown.capacity_fee_pln || 0) +
            (cheapestBreakdown.quality_oze_cogen_excise_pln || 0) +
            (cheapestBreakdown.fixed_monthly_pln || 0);
          rdnData.rdn_result.annual_cost_pln = rdnTotal;
          rdnData.rdn_result.avg_rate_pln_kwh = rdnTotal / Math.max(totalMwh * 1000, 1);
          data.rdn_result = rdnData.rdn_result;
        }
      }
    } catch (e) { console.warn('RDN fetch failed:', e); }

    console.log('📊 Full tariff comparison:', data);

    renderTariffComparisonTable(data, currentTariffCost);
    renderTariffComparisonChart(data);
    renderRdnComparisonBox(data.rdn_result, currentTariffCost);

    status.textContent = `Gotowe! ${results.length} taryf (pelny koszt: energia + dystrybucja + mocowa + OZE + stale). Zuzycie: ${totalMwh.toFixed(1)} MWh`;
    status.style.color = '#4CAF50';

  } catch (err) {
    console.error('Tariff comparison error:', err);
    status.textContent = `Blad: ${err.message}`;
    status.style.color = '#f44336';
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:20px;color:#f44336;">${err.message}</td></tr>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Przelicz dla wszystkich taryf';
  }
}

function getCurrentTariffAnnualCost() {
  const el = document.getElementById('tariffTotalCost');
  if (!el) return null;
  const text = el.textContent.replace(/\s/g, '').replace(',', '.').replace('PLN', '');
  const val = parseFloat(text);
  return isNaN(val) ? null : val;
}

function renderTariffComparisonTable(data, currentCost) {
  const tbody = document.getElementById('tariffComparisonTableBody');
  if (!data.results || data.results.length === 0) {
    tbody.innerHTML = '<tr><td colspan="13" style="text-align:center">Brak wynikow</td></tr>';
    return;
  }

  const allResults = [...data.results];
  if (data.rdn_result) {
    allResults.push(data.rdn_result);
  }
  allResults.sort((a, b) => a.annual_cost_pln - b.annual_cost_pln);

  const refCost = currentCost || allResults[0].annual_cost_pln;
  const fmtK = (v) => formatNumberEU((v || 0) / 1000, 1); // tys. PLN

  let html = '';
  allResults.forEach((r, i) => {
    const diff = r.annual_cost_pln - refCost;
    const diffPct = refCost > 0 ? (diff / refCost * 100) : 0;
    const isRdn = r.tariff_id === 'rdn_spot';
    const isCheapest = i === 0;
    const isMostExp = i === allResults.length - 1;
    const bd = r.breakdown || {};

    let rowStyle = '';
    if (isCheapest) rowStyle = 'background:rgba(76,175,80,0.12);font-weight:600;';
    else if (isMostExp) rowStyle = 'background:rgba(244,67,54,0.08);';
    else if (isRdn) rowStyle = 'background:rgba(33,150,243,0.08);';

    const diffColor = diff < -500 ? '#4CAF50' : diff > 500 ? '#f44336' : '#666';
    const badge = isCheapest ? ' 🏆' : isMostExp ? ' ⚠️' : isRdn ? ' 💹' : '';

    html += `<tr style="${rowStyle}">
      <td style="padding:4px 6px;">${i + 1}</td>
      <td style="padding:4px 6px;white-space:nowrap;">${r.tariff_name}${badge}</td>
      <td style="padding:4px 6px;">${r.osd}</td>
      <td style="padding:4px 6px;">${r.group}</td>
      <td style="padding:4px 6px;text-align:right;">${fmtK(bd.energy_active_pln)}</td>
      <td style="padding:4px 6px;text-align:right;">${fmtK(bd.distribution_variable_pln)}</td>
      <td style="padding:4px 6px;text-align:right;">${fmtK(bd.capacity_fee_pln)}</td>
      <td style="padding:4px 6px;text-align:right;">${fmtK(bd.quality_oze_cogen_excise_pln)}</td>
      <td style="padding:4px 6px;text-align:right;">${fmtK(bd.fixed_monthly_pln)}</td>
      <td style="padding:4px 6px;text-align:right;font-weight:700;">${fmtK(r.annual_cost_pln)}</td>
      <td style="padding:4px 6px;text-align:right;">${r.avg_rate_pln_kwh.toFixed(4)}</td>
      <td style="padding:4px 6px;text-align:right;color:${diffColor};font-weight:500;">${diff > 0 ? '+' : ''}${fmtK(diff)}</td>
      <td style="padding:4px 6px;text-align:right;color:${diffColor};">${diffPct > 0 ? '+' : ''}${diffPct.toFixed(1)}%</td>
    </tr>`;
  });

  tbody.innerHTML = html;
}

function renderTariffComparisonChart(data) {
  const canvas = document.getElementById('tariffComparisonChart');
  if (!canvas) return;

  if (tariffCompChart) {
    tariffCompChart.destroy();
    tariffCompChart = null;
  }

  const items = [...data.results].sort((a, b) => a.annual_cost_pln - b.annual_cost_pln);
  const top = items.slice(0, 20);
  if (data.rdn_result) top.push(data.rdn_result);

  const labels = top.map(r => r.tariff_name.replace(' Dystrybucja', '').replace(' Operator', ''));

  tariffCompChart = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Energia czynna',
          data: top.map(r => (r.breakdown?.energy_active_pln || 0) / 1000),
          backgroundColor: 'rgba(255,152,0,0.7)',
        },
        {
          label: 'Dystrybucja zmienna',
          data: top.map(r => (r.breakdown?.distribution_variable_pln || 0) / 1000),
          backgroundColor: 'rgba(33,150,243,0.7)',
        },
        {
          label: 'Oplata mocowa',
          data: top.map(r => (r.breakdown?.capacity_fee_pln || 0) / 1000),
          backgroundColor: 'rgba(244,67,54,0.7)',
        },
        {
          label: 'Jakosc+OZE+Kogen+Akcyza',
          data: top.map(r => (r.breakdown?.quality_oze_cogen_excise_pln || 0) / 1000),
          backgroundColor: 'rgba(156,39,176,0.5)',
        },
        {
          label: 'Oplaty stale',
          data: top.map(r => (r.breakdown?.fixed_monthly_pln || 0) / 1000),
          backgroundColor: 'rgba(96,125,139,0.5)',
        },
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top', labels: { font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${formatNumberEU(ctx.raw, 1)} tys. PLN`
          }
        }
      },
      scales: {
        x: {
          stacked: true,
          title: { display: true, text: 'Roczny koszt [tys. PLN]' },
          ticks: { callback: v => formatNumberEU(v, 0) }
        },
        y: { stacked: true }
      }
    }
  });
}

function renderRdnComparisonBox(rdnResult, currentCost) {
  const box = document.getElementById('rdnComparisonBox');
  const content = document.getElementById('rdnComparisonContent');
  if (!box || !content) return;

  if (!rdnResult) {
    box.style.display = 'none';
    return;
  }

  box.style.display = 'block';
  const stats = rdnResult.zone_breakdown?.stats || {};
  const diff = currentCost ? (rdnResult.annual_cost_pln - currentCost) : 0;
  const diffColor = diff < -100 ? '#4CAF50' : diff > 100 ? '#f44336' : '#666';

  content.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:12px;">
      <div style="background:white;border-radius:8px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#666;">Roczny koszt RDN</div>
        <div style="font-size:20px;font-weight:700;color:#1565C0;">${formatNumberEU(rdnResult.annual_cost_pln, 0)} PLN</div>
      </div>
      <div style="background:white;border-radius:8px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#666;">Sr. cena RDN</div>
        <div style="font-size:20px;font-weight:700;">${(rdnResult.avg_rate_pln_kwh * 1000).toFixed(0)} PLN/MWh</div>
      </div>
      <div style="background:white;border-radius:8px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#666;">Min / Max</div>
        <div style="font-size:16px;font-weight:600;">${((stats.min_pln_kwh || 0) * 1000).toFixed(0)} / ${((stats.max_pln_kwh || 0) * 1000).toFixed(0)} PLN/MWh</div>
      </div>
      ${currentCost ? `<div style="background:white;border-radius:8px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#666;">Roznica vs obecna taryfa</div>
        <div style="font-size:20px;font-weight:700;color:${diffColor};">${diff > 0 ? '+' : ''}${formatNumberEU(diff, 0)} PLN</div>
      </div>` : ''}
    </div>
    <div style="font-size:12px;color:#666;">
      P25 = ${((stats.p25_pln_kwh || 0) * 1000).toFixed(0)} PLN/MWh |
      P75 = ${((stats.p75_pln_kwh || 0) * 1000).toFixed(0)} PLN/MWh |
      Spread P25-P75 = ${(((stats.p75_pln_kwh || 0) - (stats.p25_pln_kwh || 0)) * 1000).toFixed(0)} PLN/MWh
    </div>
  `;
}

