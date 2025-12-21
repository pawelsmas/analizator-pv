// Production mode - use nginx reverse proxy routes
const USE_PROXY = true;

// Backend API URLs
const API_URLS = USE_PROXY ? {
  dataAnalysis: '/api/data',
  economics: '/api/economics'
} : {
  dataAnalysis: 'http://localhost:8001',
  economics: 'http://localhost:8003'
};

// Chart.js instances
let dailyChart, weeklyChart, monthlyChart, loadDurationChart, seasonalityChart;

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
let currentIntervalMinutes = 60; // Data interval: 15 for quarter-hourly, 60 for hourly

// Check for data on load
document.addEventListener('DOMContentLoaded', () => {
  loadConsumptionData();
});

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
  const resolutionLabel = resolution === '15-min' ? ' (15-min)' : '';
  document.getElementById('dataPoints').textContent = measurements.toLocaleString('pl-PL') + resolutionLabel;

  document.getElementById('dataPeriod').textContent = `${stats.days} dni (${stats.date_start} - ${stats.date_end})`;

  // Log data resolution for debugging
  console.log(`📊 Statistics resolution: ${resolution}, measurements: ${measurements}`);
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

