/**
 * Profile Analysis Module v2.0
 *
 * Advanced hourly analysis of PV + Load profiles for optimal BESS sizing
 * with multi-objective optimization (NPV vs Cycles), Pareto frontier,
 * heatmap visualization, and variant comparison.
 */

(function() {
    'use strict';

    // Module state
    let analysisResult = null;
    let hourlyChart = null;
    let monthlyChart = null;
    let quarterlyChart = null;
    let paretoChart = null;

    // Initialize module
    function init() {
        console.log('📊 Profile Analysis module v2.0 initializing...');
        setupEventListeners();
        loadDataFromShell();
    }

    function setupEventListeners() {
        // Analyze button
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.addEventListener('click', runAnalysis);
        }

        // Tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });
    }

    function loadDataFromShell() {
        // Request analysis results from shell
        window.parent.postMessage({
            type: 'REQUEST_ANALYSIS_RESULTS'
        }, '*');

        // Listen for results
        window.addEventListener('message', (event) => {
            if (event.data?.type === 'ANALYSIS_RESULTS') {
                const results = event.data.data;
                if (results) {
                    populateCurrentConfig(results);
                }
            }
        });
    }

    function populateCurrentConfig(results) {
        // Populate form with current analysis data
        if (results.scenarios && results.scenarios.length > 0) {
            const scenario = results.scenarios[0];

            document.getElementById('pvCapacity').value = scenario.capacity || '';
            document.getElementById('bessEnergy').value = scenario.bess_energy_kwh || '';
            document.getElementById('bessPower').value = scenario.bess_power_kw || '';
        }
    }

    async function runAnalysis() {
        const btn = document.getElementById('analyzeBtn');
        btn.disabled = true;
        btn.textContent = 'Analizuję (PyPSA)...';

        showLoading(true, 'Uruchamiam optymalizację PyPSA...');

        try {
            // Get data from shell
            const pvData = await getPvDataFromShell();
            const loadData = await getLoadDataFromShell();

            if (!pvData || !loadData) {
                showError('Brak danych PV lub zużycia. Najpierw wykonaj analizę w module konfiguracji.');
                return;
            }

            const request = {
                pv_generation_kwh: pvData.hourly_generation || [],
                load_kwh: loadData.hourly_consumption || [],
                pv_capacity_kwp: parseFloat(document.getElementById('pvCapacity').value) || 1000,
                bess_energy_kwh: parseFloat(document.getElementById('bessEnergy').value) || null,
                bess_power_kw: parseFloat(document.getElementById('bessPower').value) || null,
                energy_price_plnmwh: parseFloat(document.getElementById('energyPrice').value) || 800,
                bess_capex_per_kwh: parseFloat(document.getElementById('bessCapexKwh').value) || 1500,
                bess_capex_per_kw: parseFloat(document.getElementById('bessCapexKw').value) || 300,
                bess_efficiency: parseFloat(document.getElementById('bessEfficiency').value) / 100 || 0.90,
                discount_rate: parseFloat(document.getElementById('discountRate').value) / 100 || 0.08,
                project_years: parseInt(document.getElementById('projectYears').value) || 15,
                strategy: document.getElementById('strategy').value || 'balanced',
                min_cycles: parseInt(document.getElementById('minCycles').value) || 200,
                max_cycles: parseInt(document.getElementById('maxCycles').value) || 365
            };

            showLoading(true, 'Generuję front Pareto...');

            const response = await fetch('/api/profile/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${await response.text()}`);
            }

            analysisResult = await response.json();
            displayResults(analysisResult);

        } catch (error) {
            console.error('Analysis failed:', error);
            showError(`Błąd analizy: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.textContent = '🔬 Analizuj profil (PyPSA)';
            showLoading(false);
        }
    }

    async function getPvDataFromShell() {
        return new Promise((resolve) => {
            const handler = (event) => {
                if (event.data?.type === 'PV_DATA_RESPONSE') {
                    window.removeEventListener('message', handler);
                    resolve(event.data.data);
                }
            };
            window.addEventListener('message', handler);
            window.parent.postMessage({ type: 'REQUEST_PV_DATA' }, '*');

            // Timeout after 5s
            setTimeout(() => {
                window.removeEventListener('message', handler);
                resolve(null);
            }, 5000);
        });
    }

    async function getLoadDataFromShell() {
        return new Promise((resolve) => {
            const handler = (event) => {
                if (event.data?.type === 'LOAD_DATA_RESPONSE') {
                    window.removeEventListener('message', handler);
                    resolve(event.data.data);
                }
            };
            window.addEventListener('message', handler);
            window.parent.postMessage({ type: 'REQUEST_LOAD_DATA' }, '*');

            setTimeout(() => {
                window.removeEventListener('message', handler);
                resolve(null);
            }, 5000);
        });
    }

    function displayResults(result) {
        // Show results section
        document.getElementById('results').style.display = 'block';

        // Summary
        displaySummary(result);

        // Strategy badge
        displaySelectedStrategy(result.selected_strategy);

        // Pareto Front
        displayParetoFront(result.pareto_frontier);

        // Heatmap
        displayHeatmap(result.heatmap_data);

        // Variants comparison
        displayVariantsComparison(result.variant_comparison);

        // Hourly patterns
        displayHourlyChart(result.hourly_patterns);

        // Monthly analysis
        displayMonthlyTable(result.monthly_analysis);
        displayMonthlyChart(result.monthly_analysis);

        // Quarterly
        displayQuarterlySummary(result.quarterly_cycles, result.quarterly_surplus_mwh);

        // Recommendations
        displayBessRecommendations(result.bess_recommendations);
        displayPvRecommendations(result.pv_recommendations);

        // Insights
        displayInsights(result.insights);

        // Switch to summary tab
        switchTab('summary');
    }

    function displaySummary(result) {
        const html = `
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-label">Roczna produkcja PV</div>
                    <div class="summary-value">${result.annual_pv_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Roczne zużycie</div>
                    <div class="summary-value">${result.annual_load_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card highlight-green">
                    <div class="summary-label">Nadwyżka (surplus)</div>
                    <div class="summary-value">${result.annual_surplus_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card highlight-red">
                    <div class="summary-label">Deficyt</div>
                    <div class="summary-value">${result.annual_deficit_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Autokonsumpcja bezpośrednia</div>
                    <div class="summary-value">${result.direct_consumption_pct.toFixed(1)}%</div>
                </div>
                ${result.current_bess_annual_cycles ? `
                <div class="summary-card highlight-blue">
                    <div class="summary-label">Obecne cykle BESS/rok</div>
                    <div class="summary-value">${result.current_bess_annual_cycles.toFixed(0)}</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Wykorzystanie BESS</div>
                    <div class="summary-value">${result.current_bess_utilization_pct.toFixed(0)}%</div>
                </div>
                <div class="summary-card highlight-orange">
                    <div class="summary-label">Curtailment ratio</div>
                    <div class="summary-value">${(result.current_curtailment_ratio * 100).toFixed(0)}%</div>
                </div>
                ` : ''}
            </div>
        `;
        document.getElementById('summaryContent').innerHTML = html;
    }

    function displaySelectedStrategy(strategy) {
        const container = document.getElementById('selectedStrategy');
        if (!container || !strategy) return;

        const strategyNames = {
            'npv_max': 'NPV Max',
            'cycles_max': 'Cycles Max',
            'balanced': 'Balanced'
        };

        const strategyDescs = {
            'npv_max': 'Maksymalizacja wartości NPV - najlepszy zwrot z inwestycji',
            'cycles_max': 'Maksymalizacja liczby cykli BESS - pełne wykorzystanie magazynu',
            'balanced': 'Równowaga między NPV a liczbą cykli (optimum Pareto)'
        };

        container.innerHTML = `
            <div class="strategy-name">Wybrana strategia: ${strategyNames[strategy] || strategy}</div>
            <div class="strategy-desc">${strategyDescs[strategy] || ''}</div>
        `;
    }

    function displayParetoFront(paretoPoints) {
        const chartCtx = document.getElementById('paretoChart');
        const tableContainer = document.getElementById('paretoTable');

        if (!chartCtx || !paretoPoints || !paretoPoints.length) {
            if (tableContainer) tableContainer.innerHTML = '<p class="no-data">Brak danych Pareto</p>';
            return;
        }

        // Destroy existing chart
        if (paretoChart) paretoChart.destroy();

        // Prepare data
        const selectedPoint = paretoPoints.find(p => p.is_selected);
        const otherPoints = paretoPoints.filter(p => !p.is_selected);

        paretoChart = new Chart(chartCtx, {
            type: 'scatter',
            data: {
                datasets: [
                    {
                        label: 'Pareto-optymalne',
                        data: otherPoints.map(p => ({
                            x: p.annual_cycles,
                            y: p.npv_mln_pln
                        })),
                        backgroundColor: 'rgba(25, 118, 210, 0.7)',
                        borderColor: 'rgba(25, 118, 210, 1)',
                        pointRadius: 8,
                        pointHoverRadius: 10
                    },
                    {
                        label: 'Wybrany wariant',
                        data: selectedPoint ? [{
                            x: selectedPoint.annual_cycles,
                            y: selectedPoint.npv_mln_pln
                        }] : [],
                        backgroundColor: 'rgba(156, 39, 176, 1)',
                        borderColor: 'rgba(156, 39, 176, 1)',
                        pointRadius: 12,
                        pointHoverRadius: 14,
                        pointStyle: 'star'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Pareto Front: NPV vs Cykle roczne',
                        font: { size: 14 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const point = paretoPoints[ctx.dataIndex] || selectedPoint;
                                return [
                                    `Moc: ${point?.power_kw?.toFixed(0) || '?'} kW`,
                                    `Pojemność: ${point?.energy_kwh?.toFixed(0) || '?'} kWh`,
                                    `NPV: ${point?.npv_mln_pln?.toFixed(2) || '?'} mln PLN`,
                                    `Cykle: ${point?.annual_cycles?.toFixed(0) || '?'}/rok`,
                                    `Payback: ${point?.payback_years?.toFixed(1) || '?'} lat`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Cykle roczne' },
                        min: 0
                    },
                    y: {
                        title: { display: true, text: 'NPV [mln PLN]' }
                    }
                }
            }
        });

        // Table
        let tableHtml = `
            <table class="pareto-table">
                <thead>
                    <tr>
                        <th>Moc [kW]</th>
                        <th>Pojemność [kWh]</th>
                        <th>NPV [mln PLN]</th>
                        <th>Cykle/rok</th>
                        <th>Payback [lat]</th>
                    </tr>
                </thead>
                <tbody>
        `;

        paretoPoints.forEach(p => {
            const npvClass = p.npv_mln_pln >= 0 ? 'npv-positive' : 'npv-negative';
            const rowClass = p.is_selected ? 'selected' : '';
            tableHtml += `
                <tr class="${rowClass}">
                    <td>${p.power_kw.toFixed(0)}</td>
                    <td>${p.energy_kwh.toFixed(0)}</td>
                    <td class="${npvClass}">${p.npv_mln_pln.toFixed(2)}</td>
                    <td>${p.annual_cycles.toFixed(0)}</td>
                    <td>${p.payback_years.toFixed(1)}</td>
                </tr>
            `;
        });

        tableHtml += '</tbody></table>';
        tableContainer.innerHTML = tableHtml;
    }

    function displayHeatmap(heatmapData) {
        const container = document.getElementById('heatmapContainer');
        if (!container || !heatmapData || !heatmapData.length) {
            if (container) container.innerHTML = '<p class="no-data">Brak danych heatmapy</p>';
            return;
        }

        const monthNames = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru'];

        // Group by month
        const dataByMonth = {};
        heatmapData.forEach(cell => {
            if (!dataByMonth[cell.month]) dataByMonth[cell.month] = {};
            dataByMonth[cell.month][cell.hour] = cell;
        });

        // Find max absolute value for scaling
        let maxVal = 0;
        heatmapData.forEach(cell => {
            maxVal = Math.max(maxVal, Math.abs(cell.avg_surplus_kwh), Math.abs(cell.avg_deficit_kwh));
        });

        let html = '<div class="heatmap-grid">';

        // Header row
        html += '<div class="heatmap-header"></div>';
        for (let h = 0; h < 24; h++) {
            html += `<div class="heatmap-header">${h}</div>`;
        }

        // Data rows
        for (let m = 1; m <= 12; m++) {
            html += `<div class="heatmap-month-label">${monthNames[m-1]}</div>`;

            for (let h = 0; h < 24; h++) {
                const cell = dataByMonth[m]?.[h];
                if (cell) {
                    const netValue = cell.avg_surplus_kwh - cell.avg_deficit_kwh;
                    const intensity = Math.min(Math.abs(netValue) / maxVal, 1);
                    let bgColor;

                    if (netValue > 0) {
                        // Surplus - green
                        const g = Math.round(150 + 105 * intensity);
                        bgColor = `rgb(76, ${g}, 80)`;
                    } else if (netValue < 0) {
                        // Deficit - red
                        const r = Math.round(150 + 94 * intensity);
                        bgColor = `rgb(${r}, 67, 54)`;
                    } else {
                        bgColor = '#9e9e9e';
                    }

                    const tooltipText = `${monthNames[m-1]} ${h}:00\nNadwyżka: ${cell.avg_surplus_kwh.toFixed(0)} kWh\nDeficyt: ${cell.avg_deficit_kwh.toFixed(0)} kWh`;

                    html += `<div class="heatmap-cell" style="background:${bgColor}" title="${tooltipText}"></div>`;
                } else {
                    html += `<div class="heatmap-cell" style="background:#e0e0e0"></div>`;
                }
            }
        }

        html += '</div>';
        container.innerHTML = html;
    }

    function displayVariantsComparison(comparison) {
        const container = document.getElementById('variantsContent');
        if (!container || !comparison) {
            if (container) container.innerHTML = '<p class="no-data">Brak danych porównawczych</p>';
            return;
        }

        const baseline = comparison.baseline;
        const recommended = comparison.recommended;

        const formatPln = (val) => {
            if (Math.abs(val) >= 1e6) return (val / 1e6).toFixed(2) + ' mln';
            if (Math.abs(val) >= 1e3) return (val / 1e3).toFixed(0) + ' tys';
            return val.toFixed(0);
        };

        let html = `
            <div class="variant-card">
                <h4>Bez BESS (baseline)</h4>
                <div class="variant-metrics">
                    <div class="variant-row">
                        <span>Autokonsumpcja:</span>
                        <strong>${baseline.self_consumption_pct.toFixed(1)}%</strong>
                    </div>
                    <div class="variant-row">
                        <span>Nadwyżka tracona:</span>
                        <strong>${baseline.surplus_lost_mwh.toFixed(1)} MWh/rok</strong>
                    </div>
                    <div class="variant-row">
                        <span>Zakup z sieci:</span>
                        <strong>${baseline.grid_import_mwh.toFixed(1)} MWh/rok</strong>
                    </div>
                    <div class="variant-row">
                        <span>Koszt energii/rok:</span>
                        <strong>${formatPln(baseline.annual_energy_cost_pln)} PLN</strong>
                    </div>
                </div>
            </div>

            <div class="variant-card selected">
                <h4>Z BESS (rekomendowany) <span class="badge">WYBÓR</span></h4>
                <div class="variant-metrics">
                    <div class="variant-row">
                        <span>Konfiguracja BESS:</span>
                        <strong>${recommended.bess_power_kw.toFixed(0)} kW / ${recommended.bess_energy_kwh.toFixed(0)} kWh</strong>
                    </div>
                    <div class="variant-row">
                        <span>Autokonsumpcja:</span>
                        <strong>${recommended.self_consumption_pct.toFixed(1)}%</strong>
                    </div>
                    <div class="variant-row">
                        <span>Cykle BESS/rok:</span>
                        <strong>${recommended.annual_cycles.toFixed(0)}</strong>
                    </div>
                    <div class="variant-row">
                        <span>Zakup z sieci:</span>
                        <strong>${recommended.grid_import_mwh.toFixed(1)} MWh/rok</strong>
                    </div>
                    <div class="variant-row">
                        <span>CAPEX:</span>
                        <strong>${formatPln(recommended.capex_pln)} PLN</strong>
                    </div>
                    <div class="variant-row highlight">
                        <span>Oszczędności/rok:</span>
                        <strong>+${formatPln(recommended.annual_savings_pln)} PLN</strong>
                    </div>
                    <div class="variant-row highlight">
                        <span>NPV (${comparison.project_years} lat):</span>
                        <strong>${(recommended.npv_pln / 1e6).toFixed(2)} mln PLN</strong>
                    </div>
                    <div class="variant-row">
                        <span>Payback:</span>
                        <strong>${recommended.payback_years.toFixed(1)} lat</strong>
                    </div>
                </div>
            </div>
        `;

        container.innerHTML = html;
    }

    function displayHourlyChart(patterns) {
        const ctx = document.getElementById('hourlyChart');
        if (!ctx) return;

        if (hourlyChart) hourlyChart.destroy();

        const labels = patterns.map(p => `${p.hour}:00`);

        hourlyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Średnia produkcja PV (kWh)',
                        data: patterns.map(p => p.avg_pv_kwh),
                        backgroundColor: 'rgba(255, 193, 7, 0.7)',
                        borderColor: 'rgba(255, 193, 7, 1)',
                        borderWidth: 1,
                        order: 2
                    },
                    {
                        label: 'Średnie zużycie (kWh)',
                        data: patterns.map(p => p.avg_load_kwh),
                        backgroundColor: 'rgba(33, 150, 243, 0.7)',
                        borderColor: 'rgba(33, 150, 243, 1)',
                        borderWidth: 1,
                        order: 2
                    },
                    {
                        label: 'Nadwyżka (kWh)',
                        data: patterns.map(p => p.avg_surplus_kwh),
                        type: 'line',
                        borderColor: 'rgba(76, 175, 80, 1)',
                        backgroundColor: 'rgba(76, 175, 80, 0.2)',
                        fill: true,
                        order: 1
                    },
                    {
                        label: 'Deficyt (kWh)',
                        data: patterns.map(p => -p.avg_deficit_kwh),
                        type: 'line',
                        borderColor: 'rgba(244, 67, 54, 1)',
                        backgroundColor: 'rgba(244, 67, 54, 0.2)',
                        fill: true,
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Średni profil godzinowy (cały rok)'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                },
                scales: {
                    y: {
                        title: { display: true, text: 'Energia (kWh)' }
                    }
                }
            }
        });
    }

    function displayMonthlyTable(monthly) {
        const tbody = document.getElementById('monthlyTableBody');
        if (!tbody) return;

        let html = '';
        monthly.forEach(m => {
            const cyclesClass = m.current_bess_cycles < m.days * 0.5 ? 'low-cycles' : '';
            html += `
                <tr class="${cyclesClass}">
                    <td>${m.month_name}</td>
                    <td>${m.total_pv_mwh.toFixed(1)}</td>
                    <td>${m.total_load_mwh.toFixed(1)}</td>
                    <td class="surplus">${m.total_surplus_mwh.toFixed(1)}</td>
                    <td class="deficit">${m.total_deficit_mwh.toFixed(1)}</td>
                    <td>${m.avg_daily_surplus_kwh.toFixed(0)}</td>
                    <td>${m.surplus_hours_per_day.toFixed(1)}</td>
                    <td>${m.optimal_bess_kwh.toFixed(0)}</td>
                    <td class="cycles">${m.current_bess_cycles?.toFixed(1) || '-'}</td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    }

    function displayMonthlyChart(monthly) {
        const ctx = document.getElementById('monthlyChart');
        if (!ctx) return;

        if (monthlyChart) monthlyChart.destroy();

        monthlyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: monthly.map(m => m.month_name),
                datasets: [
                    {
                        label: 'Nadwyżka (MWh)',
                        data: monthly.map(m => m.total_surplus_mwh),
                        backgroundColor: 'rgba(76, 175, 80, 0.7)'
                    },
                    {
                        label: 'Deficyt (MWh)',
                        data: monthly.map(m => -m.total_deficit_mwh),
                        backgroundColor: 'rgba(244, 67, 54, 0.7)'
                    },
                    {
                        label: 'Cykle BESS',
                        data: monthly.map(m => m.current_bess_cycles || 0),
                        type: 'line',
                        borderColor: 'rgba(33, 150, 243, 1)',
                        backgroundColor: 'transparent',
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Miesięczny bilans energii i cykle BESS'
                    }
                },
                scales: {
                    y: {
                        title: { display: true, text: 'Energia (MWh)' },
                        position: 'left'
                    },
                    y1: {
                        title: { display: true, text: 'Cykle' },
                        position: 'right',
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }

    function displayQuarterlySummary(cycles, surplus) {
        const container = document.getElementById('quarterlyContent');
        if (!container) return;

        const quarters = ['Q1', 'Q2', 'Q3', 'Q4'];
        const quarterNames = {
            'Q1': 'Sty-Mar',
            'Q2': 'Kwi-Cze',
            'Q3': 'Lip-Wrz',
            'Q4': 'Paź-Gru'
        };
        const icons = {
            'Q1': '❄️',
            'Q2': '🌸',
            'Q3': '☀️',
            'Q4': '🍂'
        };

        let html = '<div class="quarterly-grid">';
        quarters.forEach(q => {
            const qCycles = cycles[q] || 0;
            const qSurplus = surplus[q] || 0;
            const cyclesClass = qCycles < 20 ? 'low' : qCycles > 40 ? 'high' : 'medium';

            html += `
                <div class="quarterly-card ${cyclesClass}">
                    <div class="quarterly-icon">${icons[q]}</div>
                    <div class="quarterly-name">${q} (${quarterNames[q]})</div>
                    <div class="quarterly-cycles">${qCycles.toFixed(0)} cykli</div>
                    <div class="quarterly-surplus">${qSurplus.toFixed(1)} MWh surplus</div>
                </div>
            `;
        });
        html += '</div>';

        container.innerHTML = html;
    }

    function displayBessRecommendations(recommendations) {
        const container = document.getElementById('bessRecommendations');
        if (!container || !recommendations.length) return;

        let html = '<div class="recommendations-grid">';
        recommendations.forEach(rec => {
            const paybackClass = rec.simple_payback_years < 10 ? 'good' :
                                 rec.simple_payback_years < 15 ? 'medium' : 'poor';
            const paretoClass = rec.is_pareto_optimal ? 'pareto-optimal' : '';

            html += `
                <div class="recommendation-card ${paretoClass}">
                    <h4>${rec.scenario}${rec.is_pareto_optimal ? ' ⭐' : ''}</h4>
                    <div class="rec-specs">
                        <strong>${rec.power_kw.toFixed(0)} kW / ${rec.energy_kwh.toFixed(0)} kWh</strong>
                        <span>(${rec.duration_h}h)</span>
                    </div>
                    <div class="rec-details">
                        <div class="rec-row">
                            <span>Cykle/rok:</span>
                            <strong>${rec.estimated_annual_cycles.toFixed(0)}</strong>
                        </div>
                        <div class="rec-row">
                            <span>Rozładowanie:</span>
                            <strong>${rec.estimated_annual_discharge_mwh.toFixed(0)} MWh</strong>
                        </div>
                        <div class="rec-row">
                            <span>Curtailment:</span>
                            <strong>${rec.estimated_curtailment_mwh.toFixed(0)} MWh</strong>
                        </div>
                        <div class="rec-row">
                            <span>CAPEX:</span>
                            <strong>${(rec.capex_pln / 1e6).toFixed(2)} M PLN</strong>
                        </div>
                        <div class="rec-row">
                            <span>Oszczędności/rok:</span>
                            <strong>${(rec.annual_savings_pln / 1000).toFixed(0)} tys PLN</strong>
                        </div>
                        ${rec.npv_mln_pln !== undefined ? `
                        <div class="rec-row ${rec.npv_mln_pln >= 0 ? 'good' : 'poor'}">
                            <span>NPV:</span>
                            <strong>${rec.npv_mln_pln.toFixed(2)} mln PLN</strong>
                        </div>
                        ` : ''}
                        <div class="rec-row ${paybackClass}">
                            <span>Payback:</span>
                            <strong>${rec.simple_payback_years.toFixed(1)} lat</strong>
                        </div>
                    </div>
                    <div class="utilization-bar">
                        <div class="utilization-fill" style="width: ${rec.utilization_score}%"></div>
                        <span>Wykorzystanie: ${rec.utilization_score}%</span>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    function displayPvRecommendations(recommendations) {
        const container = document.getElementById('pvRecommendations');
        if (!container || !recommendations.length) {
            if (container) container.innerHTML = '<p class="no-data">Brak rekomendacji przewymiarowania PV</p>';
            return;
        }

        let html = '<div class="recommendations-grid">';
        recommendations.forEach(rec => {
            html += `
                <div class="recommendation-card pv-rec">
                    <h4>${rec.scenario}</h4>
                    <div class="rec-specs">
                        <strong>${rec.pv_capacity_kwp.toFixed(0)} kWp</strong>
                        <span>(${rec.oversizing_ratio.toFixed(1)}x obecnego)</span>
                    </div>
                    <div class="rec-details">
                        <div class="rec-row">
                            <span>Wzrost nadwyżki:</span>
                            <strong>+${rec.estimated_surplus_increase_pct.toFixed(0)}%</strong>
                        </div>
                        <div class="rec-row">
                            <span>Dodatkowe cykle BESS:</span>
                            <strong>+${rec.additional_bess_cycles.toFixed(0)}</strong>
                        </div>
                        <div class="rec-row">
                            <span>Dodatkowy CAPEX:</span>
                            <strong>${(rec.additional_capex_pln / 1e6).toFixed(2)} M PLN</strong>
                        </div>
                        <div class="rec-row">
                            <span>Dodatkowe oszczędności:</span>
                            <strong>${(rec.additional_annual_savings_pln / 1000).toFixed(0)} tys PLN/rok</strong>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    function displayInsights(insights) {
        const container = document.getElementById('insightsContent');
        if (!container) return;

        if (!insights.length) {
            container.innerHTML = '<p class="no-data">Brak szczególnych obserwacji</p>';
            return;
        }

        let html = '<div class="insights-list">';
        insights.forEach((insight, i) => {
            html += `
                <div class="insight-card">
                    <div class="insight-number">${i + 1}</div>
                    <div class="insight-text">${insight}</div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    function switchTab(tabId) {
        // Update buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });

        // Update panels
        document.querySelectorAll('.tab-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === tabId + 'Tab');
        });
    }

    function showLoading(show, text) {
        const loader = document.getElementById('loading');
        const loadingText = document.getElementById('loadingText');
        if (loader) {
            loader.style.display = show ? 'flex' : 'none';
        }
        if (loadingText && text) {
            loadingText.textContent = text;
        }
    }

    function showError(message) {
        const container = document.getElementById('errorMessage');
        if (container) {
            container.textContent = message;
            container.style.display = 'block';
            setTimeout(() => {
                container.style.display = 'none';
            }, 10000);
        }
    }

    // Initialize on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
