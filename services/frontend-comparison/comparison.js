// Chart.js instances
let productionChart, economicsChart, monthlyChart, kpiChart;

// Data storage
let variants = [];
let selectedVariants = { A: null, B: null, C: null };
let systemSettings = null; // Settings from pv_system_settings

// Check for data on load
document.addEventListener('DOMContentLoaded', () => {
  requestSettings();
  // Wait a bit for settings to arrive before loading variants
  setTimeout(() => {
    if (!systemSettings) {
      console.warn('Settings not received, using defaults');
    }
    loadVariants();
  }, 500);
  requestSharedData();
});

// Request settings from shell
function requestSettings() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
    console.log('Requested settings from shell');
  }
}

// Request shared data from shell
function requestSharedData() {
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
  }
}

// Listen for messages from shell
window.addEventListener('message', (event) => {
  console.log('🔵 Comparison received message:', event.data.type);
  switch (event.data.type) {
    case 'VARIANT_ADDED':
    case 'VARIANT_UPDATED':
    case 'DATA_AVAILABLE':
    case 'ANALYSIS_RESULTS':
      loadVariants();
      break;
    case 'SHARED_DATA_RESPONSE':
      if (event.data.data && event.data.data.analysisResults) {
        localStorage.setItem('pv_analysis_results', JSON.stringify(event.data.data.analysisResults));
        loadVariants();
      }
      break;
    case 'SETTINGS_UPDATED':
      // Apply settings received from shell
      systemSettings = event.data.data;
      console.log('✅ System settings received! CAPEX tiers:', systemSettings?.capexTiers);
      // Reload variants with new CAPEX values
      loadVariants();
      break;
    case 'DATA_CLEARED':
      clearComparison();
      break;
    case 'PROJECT_LOADED':
      // Project was loaded - request shared data to refresh
      console.log('📂 Comparison: Project loaded, requesting shared data');
      if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
      }
      break;
  }
});

// Get CAPEX for given capacity from tier table
function getCapexForCapacity(capacityKw) {
  // Default tiers if systemSettings not available
  const defaultTiers = [
    { min: 150, max: 500, capex: 4200 },
    { min: 501, max: 1000, capex: 3800 },
    { min: 1001, max: 2500, capex: 3500 },
    { min: 2501, max: 5000, capex: 3200 },
    { min: 5001, max: 10000, capex: 3000 },
    { min: 10001, max: 15000, capex: 2850 },
    { min: 15001, max: 50000, capex: 2700 }
  ];

  const tiers = (systemSettings && systemSettings.capexTiers) ? systemSettings.capexTiers : defaultTiers;
  console.log(`💰 CAPEX for ${capacityKw} kW: using ${systemSettings ? 'SETTINGS' : 'DEFAULTS'}`, tiers);

  // Find matching tier
  for (let tier of tiers) {
    if (capacityKw >= tier.min && capacityKw <= tier.max) {
      return tier.capex;
    }
  }

  // Fallback: if above max, use last tier
  if (capacityKw > 50000) {
    return tiers[tiers.length - 1].capex;
  }

  // Fallback: if below min, use first tier
  if (capacityKw < 150) {
    return tiers[0].capex;
  }

  // Default fallback
  return 3500;
}

// Load variants from localStorage or backend
async function loadVariants() {
  // Try to load analysis results with key_variants
  const storedAnalysis = localStorage.getItem('pv_analysis_results');

  if (storedAnalysis) {
    try {
      const analysisResults = JSON.parse(storedAnalysis);
      if (analysisResults && analysisResults.key_variants) {
        // Convert key_variants object to array format
        variants = Object.entries(analysisResults.key_variants).map(([name, data]) => {
          // Calculate CAPEX based on capacity tier
          const unitCost = getCapexForCapacity(data.capacity);
          const investmentCost = data.capacity * unitCost; // kW * PLN/kW = PLN

          return {
            name: `Wariant ${name}`,
            installedCapacity: data.capacity / 1000, // kW -> MWp
            dcacRatio: data.dcac_ratio || 1.2, // DC/AC ratio used
            annualProduction: data.production / 1000000, // kWh -> GWh
            selfConsumed: data.self_consumed / 1000000,
            exported: data.exported / 1000000,
            autoConsumption: data.auto_consumption_pct,
            coverage: data.coverage_pct,
            threshold: data.threshold,
            meetsThreshold: data.meets_threshold,
            specificYield: data.production / data.capacity, // kWh/kWp
            investmentCost: investmentCost, // PLN (calculated from CAPEX tiers)
            unitCost: unitCost, // PLN/kWp (from CAPEX tiers)
            // BESS data
            bessPowerKw: data.bess_power_kw || 0,
            bessEnergyKwh: data.bess_energy_kwh || 0,
            bessFromBattery: (data.bess_discharged_kwh || data.bess_self_consumed_from_bess_kwh || 0) / 1000, // kWh -> MWh
            bessCurtailed: (data.bess_curtailed_kwh || 0) / 1000, // kWh -> MWh
            bessCycles: data.bess_cycles_equivalent || 0
          };
        });

        if (variants.length > 0) {
          populateVariantSelectors();
          hideNoData();
          updateDataInfo();
          return;
        }
      }
    } catch (error) {
      console.error('Błąd ładowania wariantów z localStorage:', error);
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

    // Try to get analysis results from localStorage or backend
    let analysisResults = null;
    const storedAnalysis = localStorage.getItem('pv_analysis_results');

    if (storedAnalysis) {
      try {
        analysisResults = JSON.parse(storedAnalysis);
      } catch (e) {
        console.error('Błąd parsowania wyników analizy:', e);
      }
    }

    // If no analysis results, try to get from analyzer
    if (!analysisResults) {
      try {
        const analyzeResponse = await fetch('http://localhost:8002/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        if (analyzeResponse.ok) {
          analysisResults = await analyzeResponse.json();
          localStorage.setItem('pv_analysis_results', JSON.stringify(analysisResults));
        }
      } catch (e) {
        console.error('Błąd pobierania analizy z backendu:', e);
      }
    }

    // Build production data from analysis results
    if (analysisResults && analysisResults.hourly_production) {
      const productionData = {
        filename: 'Dane z backendu',
        hourlyProduction: analysisResults.hourly_production,
        dataPoints: analysisResults.hourly_production.length
      };
      localStorage.setItem('pvProductionData', JSON.stringify(productionData));
      localStorage.setItem('analysisResults', JSON.stringify(analysisResults));
    }

    // Extract variants from analysis results
    if (analysisResults && analysisResults.key_variants) {
      // Convert key_variants object to array format
      variants = Object.entries(analysisResults.key_variants).map(([name, data]) => {
        // Calculate CAPEX based on capacity tier
        const unitCost = getCapexForCapacity(data.capacity);
        const investmentCost = data.capacity * unitCost; // kW * PLN/kW = PLN

        return {
          name: `Wariant ${name}`,
          installedCapacity: data.capacity / 1000, // kW -> MWp
          dcacRatio: data.dcac_ratio || 1.2, // DC/AC ratio used
          annualProduction: data.production / 1000000, // kWh -> GWh
          selfConsumed: data.self_consumed / 1000000,
          exported: data.exported / 1000000,
          autoConsumption: data.auto_consumption_pct,
          coverage: data.coverage_pct,
          threshold: data.threshold,
          meetsThreshold: data.meets_threshold,
          specificYield: data.production / data.capacity, // kWh/kWp
          investmentCost: investmentCost, // PLN (calculated from CAPEX tiers)
          unitCost: unitCost, // PLN/kWp (from CAPEX tiers)
          // BESS data
          bessPowerKw: data.bess_power_kw || 0,
          bessEnergyKwh: data.bess_energy_kwh || 0,
          bessFromBattery: (data.bess_discharged_kwh || data.bess_self_consumed_from_bess_kwh || 0) / 1000, // kWh -> MWh
          bessCurtailed: (data.bess_curtailed_kwh || 0) / 1000, // kWh -> MWh
          bessCycles: data.bess_cycles_equivalent || 0
        };
      });
    }

    // If no variants exist, show no data
    if (!variants || variants.length === 0) {
      showNoData();
      return;
    }

    populateVariantSelectors();
    hideNoData();
    updateDataInfo();
  } catch (error) {
    console.error('Błąd ładowania danych z backendu:', error);
    showNoData();
  }
}

// Show "no data" message
function showNoData() {
  document.querySelector('.content-grid').classList.add('hidden');
  document.getElementById('noDataMessage').classList.add('active');
  document.getElementById('dataInfo').textContent = 'Brak wariantów';
}

// Hide "no data" message
function hideNoData() {
  document.querySelector('.content-grid').classList.remove('hidden');
  document.getElementById('noDataMessage').classList.remove('active');
}

// Populate variant selectors
function populateVariantSelectors() {
  const selectors = ['variantA', 'variantB', 'variantC'];

  selectors.forEach(selectorId => {
    const select = document.getElementById(selectorId);
    const currentValue = select.value;

    select.innerHTML = '<option value="">Wybierz wariant...</option>';

    variants.forEach((variant, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = variant.name || `Wariant ${index + 1}`;
      select.appendChild(option);
    });

    // Restore selection if valid
    if (currentValue !== '' && variants[currentValue]) {
      select.value = currentValue;
    }
  });
}

// Update comparison when selection changes
function updateComparison() {
  const variantAIndex = document.getElementById('variantA').value;
  const variantBIndex = document.getElementById('variantB').value;
  const variantCIndex = document.getElementById('variantC').value;

  selectedVariants.A = variantAIndex !== '' ? variants[variantAIndex] : null;
  selectedVariants.B = variantBIndex !== '' ? variants[variantBIndex] : null;
  selectedVariants.C = variantCIndex !== '' ? variants[variantCIndex] : null;

  updateComparisonTable();
  updateCharts();
  updateRanking();
  updateRecommendations();
}

// Update comparison table
function updateComparisonTable() {
  const tableBody = document.getElementById('tableBody');
  const headerA = document.getElementById('headerA');
  const headerB = document.getElementById('headerB');
  const headerC = document.getElementById('headerC');

  // Update headers
  headerA.textContent = selectedVariants.A?.name || 'Wariant A';
  headerB.textContent = selectedVariants.B?.name || 'Wariant B';
  headerC.textContent = selectedVariants.C?.name || 'Wariant C';

  // Check if any variant selected
  if (!selectedVariants.A && !selectedVariants.B && !selectedVariants.C) {
    tableBody.innerHTML = '<tr><td colspan="4" class="no-data-row">Wybierz warianty do porównania</td></tr>';
    return;
  }

  // Check if any variant has BESS
  const hasBess = ['A', 'B', 'C'].some(key => {
    const v = selectedVariants[key];
    return v && v.bessPowerKw > 0;
  });

  // Build comparison rows
  const parameters = [
    { label: 'Moc instalacji [MWp]', key: 'installedCapacity', format: (v) => v.toFixed(2) },
    { label: 'DC/AC Ratio', key: 'dcacRatio', format: (v) => v.toFixed(2) },
    { label: 'Produkcja roczna [GWh]', key: 'annualProduction', format: (v) => v.toFixed(2) },
    { label: 'Autokonsumpcja [GWh]', key: 'selfConsumed', format: (v) => v.toFixed(2) },
    { label: 'Eksport [GWh]', key: 'exported', format: (v) => v.toFixed(2) },
    { label: 'Wydajność spec. [kWh/kWp]', key: 'specificYield', format: (v) => v.toFixed(0) },
    { label: 'Autokonsumpcja [%]', key: 'autoConsumption', format: (v) => v.toFixed(1) },
    { label: 'Pokrycie [%]', key: 'coverage', format: (v) => v.toFixed(1) },
    { label: 'Próg pokrycia [%]', key: 'threshold', format: (v) => v.toFixed(0) },
    { label: 'Koszt inwestycji [mln PLN]', key: 'investmentCost', format: (v) => (v / 1000000).toFixed(2) },
    { label: 'Koszt jednostkowy [PLN/kWp]', key: 'unitCost', format: (v) => v.toFixed(0) }
  ];

  // Add BESS parameters if any variant has BESS
  if (hasBess) {
    parameters.push(
      { label: '🔋 BESS Moc [kW]', key: 'bessPowerKw', format: (v) => v > 0 ? v.toFixed(0) : '-' },
      { label: '🔋 BESS Pojemność [kWh]', key: 'bessEnergyKwh', format: (v) => v > 0 ? v.toFixed(0) : '-' },
      { label: '🔋 Z baterii [MWh]', key: 'bessFromBattery', format: (v) => v > 0 ? v.toFixed(1) : '-' },
      { label: '🔋 Curtailment [MWh]', key: 'bessCurtailed', format: (v) => v > 0 ? v.toFixed(1) : '-' },
      { label: '🔋 Cykle/rok', key: 'bessCycles', format: (v) => v > 0 ? v.toFixed(0) : '-' }
    );
  }

  let html = '';
  parameters.forEach(param => {
    html += '<tr>';
    html += `<td><strong>${param.label}</strong></td>`;

    ['A', 'B', 'C'].forEach(variant => {
      const v = selectedVariants[variant];
      if (v && v[param.key] !== undefined) {
        const value = param.format ? param.format(v[param.key]) : v[param.key];
        html += `<td>${value}</td>`;
      } else {
        html += `<td>-</td>`;
      }
    });

    html += '</tr>';
  });

  tableBody.innerHTML = html;
}

// Update charts
function updateCharts() {
  updateProductionChart();
  updateEconomicsChart();
  updateMonthlyChart();
  updateKPIChart();
}

// Update production comparison chart
function updateProductionChart() {
  const ctx = document.getElementById('productionComparison').getContext('2d');

  if (productionChart) productionChart.destroy();

  const labels = [];
  const data = [];
  const colors = ['#3498db', '#e74c3c', '#2ecc71'];

  ['A', 'B', 'C'].forEach((key, index) => {
    const variant = selectedVariants[key];
    if (variant) {
      labels.push(variant.name || `Wariant ${key}`);
      data.push(variant.annualProduction); // Real annual production in GWh
    }
  });

  if (data.length === 0) {
    data.push(0);
    labels.push('Brak danych');
  }

  productionChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Produkcja [GWh/rok]',
        data: data,
        backgroundColor: colors.slice(0, data.length),
        borderColor: colors.slice(0, data.length),
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
          title: { display: true, text: 'Produkcja [GWh]' }
        }
      }
    }
  });
}

// Update economics comparison chart
function updateEconomicsChart() {
  const ctx = document.getElementById('economicsComparison').getContext('2d');

  if (economicsChart) economicsChart.destroy();

  const labels = [];
  const investmentData = [];
  const paybackData = [];
  const colors = ['#3498db', '#e74c3c', '#2ecc71'];

  ['A', 'B', 'C'].forEach((key, index) => {
    const variant = selectedVariants[key];
    if (variant) {
      labels.push(variant.name || `Wariant ${key}`);
      investmentData.push((variant.investmentCost / 1000000).toFixed(2)); // PLN -> mln PLN
      paybackData.push(12); // Simulated payback period
    }
  });

  if (investmentData.length === 0) {
    investmentData.push(0);
    paybackData.push(0);
    labels.push('Brak danych');
  }

  economicsChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Inwestycja [mln PLN]',
          data: investmentData,
          backgroundColor: 'rgba(231, 76, 60, 0.7)',
          borderColor: '#e74c3c',
          borderWidth: 2,
          yAxisID: 'y'
        },
        {
          label: 'Okres zwrotu [lat]',
          data: paybackData,
          backgroundColor: 'rgba(46, 204, 113, 0.7)',
          borderColor: '#2ecc71',
          borderWidth: 2,
          yAxisID: 'y1'
        }
      ]
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
          position: 'left',
          title: { display: true, text: 'Inwestycja [mln PLN]' }
        },
        y1: {
          beginAtZero: true,
          position: 'right',
          title: { display: true, text: 'Okres zwrotu [lat]' },
          grid: { drawOnChartArea: false }
        }
      }
    }
  });
}

// Update monthly comparison chart
function updateMonthlyChart() {
  const ctx = document.getElementById('monthlyComparison').getContext('2d');

  if (monthlyChart) monthlyChart.destroy();

  const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];
  const datasets = [];
  const colors = ['#3498db', '#e74c3c', '#2ecc71'];

  ['A', 'B', 'C'].forEach((key, index) => {
    const variant = selectedVariants[key];
    if (variant) {
      // Simulate monthly production based on capacity
      const monthlyData = monthNames.map((_, month) => {
        const seasonal = 0.5 + 0.5 * Math.sin((month - 2) * Math.PI / 6);
        return ((variant.installedCapacity * 100 * seasonal) / 1000).toFixed(2);
      });

      datasets.push({
        label: variant.name || `Wariant ${key}`,
        data: monthlyData,
        borderColor: colors[index],
        backgroundColor: `${colors[index]}33`,
        borderWidth: 2,
        fill: false,
        tension: 0.4
      });
    }
  });

  if (datasets.length === 0) {
    datasets.push({
      label: 'Brak danych',
      data: new Array(12).fill(0),
      borderColor: '#95a5a6',
      borderWidth: 2
    });
  }

  monthlyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: monthNames,
      datasets: datasets
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
          title: { display: true, text: 'Produkcja [MWh]' }
        }
      }
    }
  });
}

// Update KPI comparison chart
function updateKPIChart() {
  const ctx = document.getElementById('kpiComparison').getContext('2d');

  if (kpiChart) kpiChart.destroy();

  const labels = [];
  const prData = [];
  const specificYieldData = [];
  const colors = ['#3498db', '#e74c3c', '#2ecc71'];

  ['A', 'B', 'C'].forEach((key, index) => {
    const variant = selectedVariants[key];
    if (variant) {
      labels.push(variant.name || `Wariant ${key}`);
      prData.push(82); // Simulated PR
      specificYieldData.push(1000); // Simulated specific yield
    }
  });

  if (prData.length === 0) {
    prData.push(0);
    specificYieldData.push(0);
    labels.push('Brak danych');
  }

  kpiChart = new Chart(ctx, {
    type: 'radar',
    data: {
      labels: ['PR [%]', 'Wydajność [kWh/kWp]', 'Opłacalność', 'Niezawodność', 'Środowisko'],
      datasets: labels.map((label, index) => ({
        label: label,
        data: [82, 85, 90, 88, 95], // Simulated KPIs
        borderColor: colors[index] || '#95a5a6',
        backgroundColor: `${colors[index] || '#95a5a6'}33`,
        borderWidth: 2
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: true }
      },
      scales: {
        r: {
          beginAtZero: true,
          max: 100
        }
      }
    }
  });
}

// Update ranking
function updateRanking() {
  const rankingList = document.getElementById('rankingList');

  const rankedVariants = [];
  ['A', 'B', 'C'].forEach(key => {
    const variant = selectedVariants[key];
    if (variant) {
      // Calculate efficiency score: Annual production (GWh) per million PLN invested
      // Higher score = better (more energy per investment)
      const investmentMln = variant.investmentCost / 1000000; // PLN -> mln PLN
      const score = variant.annualProduction / investmentMln; // GWh/mln PLN

      rankedVariants.push({
        name: variant.name || `Wariant ${key}`,
        score: score,
        scoreFormatted: score.toFixed(3),
        variant: variant
      });
    }
  });

  rankedVariants.sort((a, b) => b.score - a.score);

  if (rankedVariants.length === 0) {
    rankingList.innerHTML = `
      <div class="ranking-item">
        <span class="rank-badge">1</span>
        <div class="rank-content">
          <div class="rank-name">Wybierz warianty</div>
          <div class="rank-score">-</div>
        </div>
      </div>
    `;
    return;
  }

  let html = '';
  rankedVariants.forEach((item, index) => {
    html += `
      <div class="ranking-item">
        <span class="rank-badge">${index + 1}</span>
        <div class="rank-content">
          <div class="rank-name">${item.name}</div>
          <div class="rank-score">Wskaźnik: ${item.scoreFormatted} GWh/mln PLN</div>
        </div>
      </div>
    `;
  });

  rankingList.innerHTML = html;
}

// Update recommendations
function updateRecommendations() {
  const recommendations = document.getElementById('recommendations');

  const activeVariants = ['A', 'B', 'C'].filter(key => selectedVariants[key]).length;

  if (activeVariants === 0) {
    recommendations.innerHTML = '<p>Dodaj warianty do porównania, aby zobaczyć rekomendacje.</p>';
    return;
  }

  let html = '<div class="recommendation-highlight">';
  html += '<p><strong>Rekomendacje:</strong></p>';

  if (activeVariants >= 2) {
    html += '<p>Na podstawie analizy porównawczej:</p>';
    html += '<ul style="margin-left: 20px; margin-top: 8px;">';
    html += '<li>Najlepsza opłacalność: Wariant z najniższym kosztem jednostkowym</li>';
    html += '<li>Najwyższa produkcja: Wariant z największą mocą instalacji</li>';
    html += '<li>Kompromis: Rozważ stosunek produkcji do kosztów</li>';
    html += '</ul>';
  } else {
    html += '<p>Dodaj co najmniej 2 warianty, aby otrzymać szczegółowe rekomendacje.</p>';
  }

  html += '</div>';
  recommendations.innerHTML = html;
}

// Update data info
function updateDataInfo() {
  const info = `${variants.length} wariantów dostępnych`;
  document.getElementById('dataInfo').textContent = info;
}

// Export comparison
function exportComparison() {
  if (variants.length === 0) {
    alert('Brak wariantów do eksportu');
    return;
  }

  const report = {
    exportedAt: new Date().toISOString(),
    selectedVariants: selectedVariants,
    allVariants: variants
  };

  const dataStr = JSON.stringify(report, null, 2);
  const dataBlob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(dataBlob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `porownanie-wariantow-${new Date().toISOString().split('T')[0]}.json`;
  link.click();

  URL.revokeObjectURL(url);
}

// Add new variant
function addVariant() {
  alert('Funkcja dodawania wariantów dostępna w module Configuration');
  window.parent.postMessage({ type: 'NAVIGATE_TO', module: 'config' }, '*');
}

// Refresh data
function refreshData() {
  loadVariants();
  updateComparison();
}

// Clear comparison
function clearComparison() {
  variants = [];
  selectedVariants = { A: null, B: null, C: null };

  if (productionChart) productionChart.destroy();
  if (economicsChart) economicsChart.destroy();
  if (monthlyChart) monthlyChart.destroy();
  if (kpiChart) kpiChart.destroy();

  showNoData();
}
