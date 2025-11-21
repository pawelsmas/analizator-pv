// Chart.js instances
let dailyChart, weeklyChart, monthlyChart, loadDurationChart;

// Data storage
let consumptionData = null;

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
    const healthResponse = await fetch('http://localhost:8001/health');
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
    const dataResponse = await fetch('http://localhost:8001/hourly-data');
    if (!dataResponse.ok) {
      showNoData();
      return;
    }

    const hourlyData = await dataResponse.json();

    // Get statistics for metadata
    const statsResponse = await fetch('http://localhost:8001/statistics');
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

// Perform consumption analysis
function performAnalysis() {
  hideNoData();

  if (!consumptionData || !consumptionData.hourlyData) {
    showNoData();
    return;
  }

  const hourlyData = consumptionData.hourlyData;
  const values = hourlyData.values;

  // Calculate statistics
  const stats = calculateStatistics(values);

  // Update UI
  updateStatistics(stats);
  updateDataInfo(consumptionData);

  // Generate charts
  generateDailyProfile(hourlyData);
  generateWeeklyProfile(hourlyData);
  generateMonthlyProfile(hourlyData);
  generateLoadDurationCurve(values);
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

// Update statistics display
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

// Update data info
function updateDataInfo(data) {
  const info = `${data.filename} • ${data.dataPoints} punktów • ${data.year}`;
  document.getElementById('dataInfo').textContent = info;
}

// Generate daily profile chart
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

// Generate weekly profile chart
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

// Generate monthly profile chart
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

// Generate load duration curve
function generateLoadDurationCurve(values) {
  // Sort values descending
  const sorted = [...values].sort((a, b) => b - a);

  // Convert to MW and sample every 100th point for performance
  const sampleRate = Math.max(1, Math.floor(sorted.length / 500));
  const sampled = sorted.filter((_, i) => i % sampleRate === 0).map(v => (v / 1000).toFixed(2));

  const ctx = document.getElementById('loadDurationCurve').getContext('2d');

  if (loadDurationChart) loadDurationChart.destroy();

  loadDurationChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array.from({ length: sampled.length }, (_, i) => i),
      datasets: [{
        label: 'Moc [MW]',
        data: sampled,
        borderColor: '#e74c3c',
        backgroundColor: 'rgba(231, 76, 60, 0.1)',
        borderWidth: 2,
        fill: true,
        pointRadius: 0
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
          title: { display: true, text: 'Uporządkowane godziny' },
          ticks: { display: false }
        }
      }
    }
  });
}

// Export analysis
function exportAnalysis() {
  if (!consumptionData) {
    alert('Brak danych do eksportu');
    return;
  }

  const stats = calculateStatistics(consumptionData.hourlyData.values);

  const report = {
    filename: consumptionData.filename,
    analyzedAt: new Date().toISOString(),
    statistics: stats,
    dataSource: consumptionData
  };

  const dataStr = JSON.stringify(report, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(dataBlob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `analiza-zuzycia-${new Date().toISOString().split('T')[0]}.json`;
  link.click();

  URL.revokeObjectURL(url);
}

// Refresh data
function refreshData() {
  loadConsumptionData();
}

