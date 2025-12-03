// Chart.js instances
let dailyChart, weeklyChart, monthlyChart, loadDurationChart, seasonalityChart;

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

// Perform consumption analysis - fetch stats from backend
async function performAnalysis() {
  hideNoData();

  if (!consumptionData || !consumptionData.hourlyData) {
    showNoData();
    return;
  }

  try {
    // Fetch statistics from backend (all calculations done server-side)
    const statsResponse = await fetch('http://localhost:8001/statistics');
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
    generateLoadDurationCurve(consumptionData.hourlyData.values);

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
    generateLoadDurationCurve(values);
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
  document.getElementById('dataPoints').textContent = stats.hours.toLocaleString('pl-PL');
  document.getElementById('dataPeriod').textContent = `${stats.days} dni (${stats.date_start} - ${stats.date_end})`;
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
    const response = await fetch('http://localhost:8001/seasonality');
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

