// Global state
let consumptionData = null;
let analysisResults = null;
let selectedMonth = 0;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  await checkServices();
  setupEventListeners();
});

// Check service health
async function checkServices() {
  try {
    const statuses = await apiClient.checkHealth();

    const statusHTML = Object.entries(statuses)
      .map(([name, status]) => {
        const color = status === 'healthy' ? '#00ff88' : '#ff0088';
        const icon = status === 'healthy' ? '✓' : '✗';
        return `<span style="color:${color}">${icon} ${name}</span>`;
      })
      .join(' • ');

    document.getElementById('servicesStatus').innerHTML = `Services: ${statusHTML}`;
  } catch (error) {
    console.error('Failed to check services:', error);
    document.getElementById('servicesStatus').innerHTML =
      '<span style="color:#ff0088">⚠️ Cannot connect to services</span>';
  }
}

// Setup event listeners
function setupEventListeners() {
  document.getElementById('loadFile').addEventListener('change', handleFileUpload);
}

// Tab switching
function switchMainTab(tabName) {
  document.querySelectorAll('.main-tab').forEach(tab => {
    tab.classList.remove('active');
  });
  event.target.classList.add('active');

  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });
  document.getElementById('tab-' + tabName).classList.add('active');

  // Load data for specific tabs
  if (tabName === 'consumption' && consumptionData) {
    updateConsumptionTab();
  } else if (tabName === 'production' && analysisResults) {
    updateProductionTab();
  } else if (tabName === 'comparison' && analysisResults) {
    updateComparisonTab();
  } else if (tabName === 'economics' && analysisResults) {
    updateEconomicsTab();
  }
}

// File upload
async function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    document.getElementById('loadStatus').innerHTML =
      '<div style="color:#ffaa00">Uploading...</div>';

    let result;
    if (file.name.endsWith('.csv')) {
      result = await apiClient.uploadCSV(file);
    } else {
      result = await apiClient.uploadExcel(file);
    }

    document.getElementById('loadStatus').innerHTML = `
      <div class="success">
        ✓ ${result.message}<br>
        ${result.data_points} hours loaded<br>
        Year: ${result.year}
      </div>
    `;

    // Update statistics
    await updateStatistics();
    consumptionData = await apiClient.getHourlyData();

  } catch (error) {
    document.getElementById('loadStatus').innerHTML =
      `<div style="color:#ff0088">Error: ${error.message}</div>`;
  }
}

// Update statistics
async function updateStatistics() {
  try {
    const stats = await apiClient.getStatistics();

    document.getElementById('statConsumption').textContent =
      stats.total_consumption_gwh.toFixed(1);
    document.getElementById('statPeak').textContent =
      stats.peak_power_mw.toFixed(1);
    document.getElementById('statDays').textContent =
      stats.days;
    document.getElementById('statAvg').textContent =
      stats.avg_daily_mwh.toFixed(1);

  } catch (error) {
    console.error('Failed to update statistics:', error);
  }
}

// ============= CONSUMPTION ANALYSIS TAB =============
async function updateConsumptionTab() {
  try {
    const dailyData = await apiClient.getDailyConsumption(selectedMonth);
    const heatmapData = await apiClient.getHeatmapData(selectedMonth);

    // Plot daily consumption
    plotDailyConsumption(dailyData);

    // Plot heatmaps
    plotHeatmaps(heatmapData);

  } catch (error) {
    console.error('Failed to update consumption tab:', error);
  }
}

function plotDailyConsumption(data) {
  const layout = {
    title: selectedMonth === 0 ? 'Daily Consumption - Full Year' : `Daily Consumption - Month ${selectedMonth}`,
    xaxis: {title: 'Date', gridcolor: '#1a1a1a'},
    yaxis: {title: 'Energy [kWh/day]', gridcolor: '#1a1a1a'},
    paper_bgcolor: '#0a0a0a',
    plot_bgcolor: '#0a0a0a',
    font: {color: '#888'}
  };

  Plotly.newPlot('consumptionCharts', [{
    x: data.dates,
    y: data.values,
    type: 'scatter',
    mode: 'lines',
    line: {color: '#ff0088', width: 2},
    fill: 'tozeroy',
    fillcolor: 'rgba(255,0,136,0.2)'
  }], layout);
}

function plotHeatmaps(data) {
  const weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const layout1 = {
    title: 'Week x Hour Heatmap',
    xaxis: {title: 'Hour', gridcolor: '#1a1a1a'},
    yaxis: {
      title: 'Day of Week',
      ticktext: weekDays,
      tickvals: [0,1,2,3,4,5,6],
      gridcolor: '#1a1a1a'
    },
    paper_bgcolor: '#0a0a0a',
    plot_bgcolor: '#0a0a0a',
    font: {color: '#888'}
  };

  const heatmapContainer = document.getElementById('consumptionCharts');
  if (heatmapContainer) {
    heatmapContainer.innerHTML += '<div id="heatmapWeek" style="height:300px;margin-top:20px"></div>';

    Plotly.newPlot('heatmapWeek', [{
      z: data.week_hour_matrix,
      type: 'heatmap',
      colorscale: [[0,'#0a0a0a'],[0.5,'#0088ff'],[1,'#ff0088']],
      colorbar: {title: 'kW'}
    }], layout1);
  }
}

// ============= PRODUCTION TAB =============
async function updateProductionTab() {
  if (!analysisResults || !analysisResults.key_variants.B) {
    document.getElementById('productionCharts').innerHTML =
      '<p style="color:#ff0088">Run analysis first!</p>';
    return;
  }

  const variant = analysisResults.key_variants.B;

  let html = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">${(variant.capacity/1000).toFixed(1)}</div>
        <div class="stat-label">PV Power [MWp]</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${(variant.production/1e6).toFixed(2)}</div>
        <div class="stat-label">Annual Production [GWh]</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${variant.auto_consumption_pct.toFixed(1)}</div>
        <div class="stat-label">Self-Consumption [%]</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${variant.coverage_pct.toFixed(1)}</div>
        <div class="stat-label">Coverage [%]</div>
      </div>
    </div>
    <div class="chart-container">
      <div id="chartAnnualProduction" style="height:400px"></div>
    </div>
  `;

  document.getElementById('productionCharts').innerHTML = html;

  // Plot annual production from PV profile
  plotAnnualProduction(analysisResults.pv_profile, variant.capacity);
}

function plotAnnualProduction(pvProfile, capacity) {
  const dailyProduction = [];
  const dates = [];

  for (let d = 0; d < 365; d++) {
    let daySum = 0;
    for (let h = 0; h < 24; h++) {
      const idx = d * 24 + h;
      if (idx < pvProfile.length) {
        daySum += pvProfile[idx] * capacity;
      }
    }
    dailyProduction.push(daySum);
    dates.push(d);
  }

  const layout = {
    title: 'Annual PV Production Profile',
    xaxis: {title: 'Day of Year', gridcolor: '#1a1a1a'},
    yaxis: {title: 'Energy [kWh/day]', gridcolor: '#1a1a1a'},
    paper_bgcolor: '#0a0a0a',
    plot_bgcolor: '#0a0a0a',
    font: {color: '#888'}
  };

  Plotly.newPlot('chartAnnualProduction', [{
    x: dates,
    y: dailyProduction,
    type: 'scatter',
    mode: 'lines',
    line: {color: '#00ff88', width: 2},
    fill: 'tozeroy',
    fillcolor: 'rgba(0,255,136,0.1)'
  }], layout);
}

// ============= COMPARISON TAB =============
async function updateComparisonTab() {
  if (!analysisResults || !analysisResults.key_variants.B) {
    document.getElementById('comparisonCharts').innerHTML =
      '<p style="color:#ff0088">Run analysis first!</p>';
    return;
  }

  const variantB = analysisResults.key_variants.B;
  const variantC = analysisResults.key_variants.C;

  let html = `
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Variant B</div>
        <div class="stat-value" style="font-size:18px">${(variantB.capacity/1000).toFixed(1)} MWp</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Variant C</div>
        <div class="stat-value" style="font-size:18px">${(variantC.capacity/1000).toFixed(1)} MWp</div>
      </div>
    </div>
    <div class="chart-container">
      <div id="chartComparison" style="height:400px"></div>
    </div>
    <table>
      <tr>
        <th>Metric</th>
        <th>Variant B</th>
        <th>Variant C</th>
        <th>Difference</th>
      </tr>
      <tr>
        <td>Power [MWp]</td>
        <td>${(variantB.capacity/1000).toFixed(1)}</td>
        <td>${(variantC.capacity/1000).toFixed(1)}</td>
        <td>${((variantB.capacity-variantC.capacity)/1000).toFixed(1)}</td>
      </tr>
      <tr>
        <td>Production [GWh]</td>
        <td>${(variantB.production/1e6).toFixed(2)}</td>
        <td>${(variantC.production/1e6).toFixed(2)}</td>
        <td>${((variantB.production-variantC.production)/1e6).toFixed(2)}</td>
      </tr>
      <tr>
        <td>Self-Consumption [%]</td>
        <td>${variantB.auto_consumption_pct.toFixed(1)}</td>
        <td>${variantC.auto_consumption_pct.toFixed(1)}</td>
        <td>${(variantB.auto_consumption_pct-variantC.auto_consumption_pct).toFixed(1)}</td>
      </tr>
    </table>
  `;

  document.getElementById('comparisonCharts').innerHTML = html;

  // Plot comparison chart
  plotComparisonChart([variantB, variantC]);
}

function plotComparisonChart(variants) {
  const data = variants.map((v, i) => ({
    x: [`Variant ${String.fromCharCode(66+i)}`],
    y: [v.capacity/1000],
    name: `Variant ${String.fromCharCode(66+i)}`,
    type: 'bar',
    marker: {color: i === 0 ? '#0088ff' : '#ffaa00'}
  }));

  const layout = {
    title: 'PV Power Comparison',
    yaxis: {title: 'Power [MWp]', gridcolor: '#1a1a1a'},
    paper_bgcolor: '#0a0a0a',
    plot_bgcolor: '#0a0a0a',
    font: {color: '#888'}
  };

  Plotly.newPlot('chartComparison', data, layout);
}

// ============= ECONOMICS TAB =============
async function updateEconomicsTab() {
  if (!analysisResults || !analysisResults.key_variants.B) {
    document.getElementById('economicsResults').innerHTML =
      '<p style="color:#ff0088">Run analysis first!</p>';
    return;
  }

  const variant = analysisResults.key_variants.B;

  const economicsRequest = {
    variant: {
      capacity: variant.capacity,
      production: variant.production,
      self_consumed: variant.self_consumed,
      exported: variant.exported,
      auto_consumption_pct: variant.auto_consumption_pct,
      coverage_pct: variant.coverage_pct
    },
    parameters: {
      energy_price: 450,
      feed_in_tariff: 0,
      investment_cost: 3500,
      export_mode: "zero",
      discount_rate: 0.07,
      degradation_rate: 0.005,
      opex_per_kwp: 15,
      analysis_period: 25
    }
  };

  try {
    const result = await apiClient.analyzeEconomics(economicsRequest);

    let html = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value" style="color:#ff0088">${(result.investment/1e6).toFixed(2)}</div>
          <div class="stat-label">Investment [M PLN]</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#00ff88">${result.simple_payback.toFixed(1)}</div>
          <div class="stat-label">Payback [years]</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:${result.npv > 0 ? '#00ff88' : '#ff0088'}">${(result.npv/1e6).toFixed(2)}</div>
          <div class="stat-label">NPV [M PLN]</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#ffaa00">${(result.irr*100).toFixed(1)}%</div>
          <div class="stat-label">IRR</div>
        </div>
      </div>

      <div class="chart-container">
        <h3 style="color:#00ff88;margin-bottom:12px">Financial Summary</h3>
        <table>
          <tr>
            <th>Metric</th>
            <th>Value</th>
          </tr>
          <tr>
            <td>Total Investment</td>
            <td style="color:#ff0088">${(result.investment/1e6).toFixed(3)} M PLN</td>
          </tr>
          <tr>
            <td>Annual Savings</td>
            <td style="color:#00ff88">${(result.annual_savings/1e6).toFixed(3)} M PLN</td>
          </tr>
          <tr>
            <td>Annual Export Revenue</td>
            <td style="color:#0088ff">${(result.annual_export_revenue/1e6).toFixed(3)} M PLN</td>
          </tr>
          <tr>
            <td>Total Annual Revenue</td>
            <td style="color:#ffaa00">${(result.annual_total_revenue/1e6).toFixed(3)} M PLN</td>
          </tr>
          <tr>
            <td>Simple Payback</td>
            <td>${result.simple_payback.toFixed(2)} years</td>
          </tr>
          <tr>
            <td>NPV (25y, 7%)</td>
            <td style="color:${result.npv > 0 ? '#00ff88' : '#ff0088'}">${(result.npv/1e6).toFixed(3)} M PLN</td>
          </tr>
          <tr>
            <td>IRR</td>
            <td style="color:#ffaa00">${(result.irr*100).toFixed(2)}%</td>
          </tr>
          <tr>
            <td>LCOE</td>
            <td>${(result.lcoe*1000).toFixed(2)} PLN/MWh</td>
          </tr>
        </table>
      </div>
    `;

    document.getElementById('economicsResults').innerHTML = html;

  } catch (error) {
    document.getElementById('economicsResults').innerHTML =
      `<p style="color:#ff0088">Error: ${error.message}</p>`;
  }
}

// Run analysis
async function runAnalysis() {
  try {
    // Check if data is loaded first (global state)
    if (!consumptionData) {
      alert('⚠️ Please upload consumption data first!\n\nGo to "DATA UPLOAD" section and select your Excel or CSV file.');
      return;
    }

    // Get consumption data from backend
    const hourlyData = await apiClient.getHourlyData();

    if (!hourlyData || !hourlyData.values || hourlyData.values.length === 0) {
      alert('⚠️ No data available!\n\nPlease upload consumption data first.');
      return;
    }

    // Get configuration
    const pvConfig = {
      pv_type: document.getElementById('pvType').value,
      yield_target: parseFloat(document.getElementById('yield').value),
      dc_ac_ratio: parseFloat(document.getElementById('dcac').value),
      latitude: 52.0
    };

    const analysisRequest = {
      pv_config: pvConfig,
      consumption: hourlyData.values,
      capacity_min: parseFloat(document.getElementById('capMin').value),
      capacity_max: parseFloat(document.getElementById('capMax').value),
      capacity_step: parseFloat(document.getElementById('capStep').value),
      thresholds: {
        A: parseFloat(document.getElementById('thrA').value),
        B: parseFloat(document.getElementById('thrB').value),
        C: parseFloat(document.getElementById('thrC').value),
        D: parseFloat(document.getElementById('thrD').value)
      }
    };

    // Show loading
    document.getElementById('variantResults').innerHTML =
      '<div style="color:#ffaa00">Running analysis...</div>';

    // Run analysis
    analysisResults = await apiClient.runPVAnalysis(analysisRequest);

    // Plot results
    plotSelfConsumptionCurve(analysisResults);
    showVariantResults(analysisResults);

    alert('Analysis complete! Check other tabs for detailed results.');

  } catch (error) {
    alert('Analysis failed: ' + error.message);
    console.error(error);
  }
}

// Plot self-consumption curve
function plotSelfConsumptionCurve(results) {
  const x = results.scenarios.map(s => s.capacity / 1000);
  const y = results.scenarios.map(s => s.auto_consumption_pct);

  // Add markers for key variants
  const variantMarkers = {
    x: Object.values(results.key_variants).map(v => v.capacity / 1000),
    y: Object.values(results.key_variants).map(v => v.auto_consumption_pct),
    text: Object.keys(results.key_variants),
    mode: 'markers+text',
    type: 'scatter',
    textposition: 'top center',
    marker: {
      size: 12,
      color: ['#ff0088', '#0088ff', '#ffaa00', '#ff00ff']
    },
    name: 'Variants'
  };

  const layout = {
    title: 'Self-Consumption vs PV Power',
    xaxis: {title: 'PV Power [MWp]', gridcolor: '#1a1a1a'},
    yaxis: {title: 'Self-Consumption [%]', range: [0,105], gridcolor: '#1a1a1a'},
    paper_bgcolor: '#0a0a0a',
    plot_bgcolor: '#0a0a0a',
    font: {color: '#888'},
    showlegend: false
  };

  Plotly.newPlot('chartSelfConsumption', [
    {
      x: x,
      y: y,
      type: 'scatter',
      mode: 'lines',
      line: {color: '#00ff88', width: 3},
      name: 'Self-Consumption'
    },
    variantMarkers
  ], layout);
}

// Show variant results
function showVariantResults(results) {
  let html = `
    <table>
      <tr>
        <th>Variant</th>
        <th>Threshold</th>
        <th>Power [MWp]</th>
        <th>Production [GWh]</th>
        <th>Self-Cons [%]</th>
        <th>Coverage [%]</th>
        <th>Export [GWh]</th>
        <th>Status</th>
      </tr>
  `;

  for (const [key, v] of Object.entries(results.key_variants)) {
    const statusIcon = v.meets_threshold ? '✓' : '✗';
    const statusColor = v.meets_threshold ? '#00ff88' : '#ff0088';

    html += `<tr>
      <td>Variant ${key}</td>
      <td>≥${v.threshold}%</td>
      <td style="color:#0088ff">${(v.capacity/1000).toFixed(1)}</td>
      <td style="color:#00ff88">${(v.production/1e6).toFixed(1)}</td>
      <td style="color:${v.meets_threshold ? '#ffaa00' : '#ff0088'}">${v.auto_consumption_pct.toFixed(1)}</td>
      <td style="color:#ff00ff">${v.coverage_pct.toFixed(1)}</td>
      <td style="color:#666">${(v.exported/1e6).toFixed(1)}</td>
      <td style="color:${statusColor}">${statusIcon}</td>
    </tr>`;
  }

  html += `</table>`;

  document.getElementById('variantResults').innerHTML = html;
}

// Export results
async function exportResults() {
  if (!analysisResults) {
    alert('Run analysis first!');
    return;
  }

  const wb = XLSX.utils.book_new();

  // Sheet 1: Scenarios
  const scenariosData = analysisResults.scenarios.map(s => ({
    'Power [MWp]': (s.capacity/1000).toFixed(2),
    'Production [GWh]': (s.production/1e6).toFixed(3),
    'Self-Consumed [GWh]': (s.self_consumed/1e6).toFixed(3),
    'Exported [GWh]': (s.exported/1e6).toFixed(3),
    'Self-Consumption [%]': s.auto_consumption_pct.toFixed(1),
    'Coverage [%]': s.coverage_pct.toFixed(1)
  }));

  const ws1 = XLSX.utils.json_to_sheet(scenariosData);
  XLSX.utils.book_append_sheet(wb, ws1, 'All Scenarios');

  // Sheet 2: Key Variants
  const variantsData = Object.entries(analysisResults.key_variants).map(([key, v]) => ({
    'Variant': key,
    'Threshold [%]': v.threshold,
    'Power [MWp]': (v.capacity/1000).toFixed(2),
    'Production [GWh]': (v.production/1e6).toFixed(3),
    'Self-Consumed [GWh]': (v.self_consumed/1e6).toFixed(3),
    'Exported [GWh]': (v.exported/1e6).toFixed(3),
    'Self-Consumption [%]': v.auto_consumption_pct.toFixed(1),
    'Coverage [%]': v.coverage_pct.toFixed(1),
    'Meets Threshold': v.meets_threshold ? 'Yes' : 'No'
  }));

  const ws2 = XLSX.utils.json_to_sheet(variantsData);
  XLSX.utils.book_append_sheet(wb, ws2, 'Key Variants');

  XLSX.writeFile(wb, 'pv_analysis_microservices.xlsx');
}
