/**
 * Energy Prices Frontend - Analiza cen energii SPOT
 */

const API_BASE = 'http://localhost:8010';

// Chart instances
let hourlyChart = null;
let dailyChart = null;
let trendChart = null;
let hourlyProfileChart = null;
let monthlyChart = null;

// ============== Initialization ==============

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    checkConnection();
    setupEventListeners();

    // Set default dates
    const today = new Date();
    const yearAgo = new Date(today);
    yearAgo.setFullYear(yearAgo.getFullYear() - 1);

    document.getElementById('analysis-start').value = formatDate(yearAgo);
    document.getElementById('analysis-end').value = formatDate(today);
    document.getElementById('compare-start').value = formatDate(yearAgo);
    document.getElementById('compare-end').value = formatDate(today);

    // Load initial data
    loadCurrentPrices();
});

function formatDate(date) {
    return date.toISOString().split('T')[0];
}

// ============== Tab Management ==============

function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;

            // Update buttons
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(`${tabId}-tab`).classList.add('active');
        });
    });
}

// ============== Connection Check ==============

async function checkConnection() {
    const statusIndicator = document.querySelector('.status-indicator');
    const statusText = document.querySelector('.status-text');

    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();

        statusIndicator.classList.add('connected');
        statusIndicator.classList.remove('error');

        if (data.demo_mode) {
            statusText.textContent = 'Połączono (tryb DEMO - brak klucza API ENTSO-E)';
        } else {
            statusText.textContent = 'Połączono z ENTSO-E API';
        }
    } catch (error) {
        statusIndicator.classList.add('error');
        statusIndicator.classList.remove('connected');
        statusText.textContent = 'Błąd połączenia z serwisem cen energii';
    }
}

// ============== Event Listeners ==============

function setupEventListeners() {
    document.getElementById('load-current').addEventListener('click', loadCurrentPrices);
    document.getElementById('load-historical').addEventListener('click', loadHistoricalPrices);
    document.getElementById('load-analysis').addEventListener('click', loadAnalysisPrices);
    document.getElementById('load-comparison').addEventListener('click', loadComparison);
}

// ============== Current Prices ==============

async function loadCurrentPrices() {
    const days = document.getElementById('current-days').value;
    const btn = document.getElementById('load-current');

    btn.disabled = true;
    btn.textContent = 'Ładowanie...';

    try {
        const response = await fetch(`${API_BASE}/prices/current?days=${days}`);
        const data = await response.json();

        updateCurrentSummary(data.summary);
        renderHourlyChart(data.prices);
        renderDailyChart(data.daily_stats);
        renderDailyTable(data.daily_stats);

    } catch (error) {
        console.error('Error loading current prices:', error);
        alert('Błąd podczas ładowania danych');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Załaduj dane';
    }
}

function updateCurrentSummary(summary) {
    const avgEur = summary.avg_price_eur.toFixed(2);
    const avgPln = summary.avg_price_pln ? summary.avg_price_pln.toFixed(2) : '-';
    document.getElementById('avg-price').innerHTML = `${avgEur} EUR<br><span class="pln-price">${avgPln} PLN</span>`;

    const minEur = summary.min_price_eur.toFixed(0);
    const maxEur = summary.max_price_eur.toFixed(0);
    const minPln = summary.min_price_pln ? summary.min_price_pln.toFixed(0) : '-';
    const maxPln = summary.max_price_pln ? summary.max_price_pln.toFixed(0) : '-';
    document.getElementById('minmax-price').innerHTML = `${minEur} / ${maxEur} EUR<br><span class="pln-price">${minPln} / ${maxPln} PLN</span>`;

    document.getElementById('volatility').textContent = `${summary.volatility_pct.toFixed(1)}%`;

    const rate = summary.eur_pln_rate ? `(1 EUR = ${summary.eur_pln_rate.toFixed(4)} PLN)` : '';
    document.getElementById('data-source').innerHTML = `${summary.data_source.toUpperCase()}<br><span class="rate-info">${rate}</span>`;
}

function renderHourlyChart(prices) {
    const ctx = document.getElementById('hourly-chart').getContext('2d');

    if (hourlyChart) {
        hourlyChart.destroy();
    }

    // Reduce data points for performance (show every 4th point)
    const reducedPrices = prices.filter((_, i) => i % 4 === 0);

    hourlyChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: reducedPrices.map(p => new Date(p.timestamp)),
            datasets: [{
                label: 'Cena EUR/MWh',
                data: reducedPrices.map(p => p.price_eur_mwh),
                borderColor: '#3498db',
                backgroundColor: 'rgba(52, 152, 219, 0.1)',
                fill: true,
                tension: 0.2,
                pointRadius: 0,
                borderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day',
                        displayFormats: { day: 'dd.MM' }
                    },
                    grid: { display: false }
                },
                y: {
                    title: { display: true, text: 'EUR/MWh' },
                    grid: { color: '#f0f0f0' }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        }
    });
}

function renderDailyChart(dailyStats) {
    const ctx = document.getElementById('daily-chart').getContext('2d');

    if (dailyChart) {
        dailyChart.destroy();
    }

    dailyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: dailyStats.map(d => d.date),
            datasets: [
                {
                    label: 'Peak (8-20)',
                    data: dailyStats.map(d => d.peak_avg),
                    backgroundColor: '#e74c3c',
                    barPercentage: 0.8
                },
                {
                    label: 'Off-peak',
                    data: dailyStats.map(d => d.offpeak_avg),
                    backgroundColor: '#27ae60',
                    barPercentage: 0.8
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        maxTicksLimit: 15,
                        callback: function(val, index) {
                            const label = this.getLabelForValue(val);
                            return label.substring(5); // Remove year
                        }
                    }
                },
                y: {
                    title: { display: true, text: 'EUR/MWh' },
                    grid: { color: '#f0f0f0' }
                }
            }
        }
    });
}

function renderDailyTable(dailyStats) {
    const tbody = document.querySelector('#daily-table tbody');
    tbody.innerHTML = '';

    // Show last 14 days
    const recentStats = dailyStats.slice(-14).reverse();

    recentStats.forEach(day => {
        const avgPln = day.avg_price_pln ? day.avg_price_pln.toFixed(2) : '-';
        const peakPln = day.peak_avg_pln ? day.peak_avg_pln.toFixed(2) : '-';
        const offpeakPln = day.offpeak_avg_pln ? day.offpeak_avg_pln.toFixed(2) : '-';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${day.date}</td>
            <td>${day.avg_price.toFixed(2)}<br><span class="pln-small">${avgPln}</span></td>
            <td>${day.min_price.toFixed(2)}</td>
            <td>${day.max_price.toFixed(2)}</td>
            <td>${day.peak_avg.toFixed(2)}<br><span class="pln-small">${peakPln}</span></td>
            <td>${day.offpeak_avg.toFixed(2)}<br><span class="pln-small">${offpeakPln}</span></td>
            <td>${day.peak_hour}:00</td>
        `;
        tbody.appendChild(row);
    });
}

// ============== Historical Prices ==============

async function loadHistoricalPrices() {
    const years = document.getElementById('historical-years').value;
    const btn = document.getElementById('load-historical');

    btn.disabled = true;
    btn.textContent = 'Ładowanie...';

    try {
        const response = await fetch(`${API_BASE}/prices/historical?years=${years}`);
        const data = await response.json();

        renderTrendChart(data.price_trend);
        renderYearlySummary(data.yearly_stats);
        renderYearlyTable(data.yearly_stats);

    } catch (error) {
        console.error('Error loading historical prices:', error);
        alert('Błąd podczas ładowania danych historycznych');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Załaduj dane';
    }
}

function renderTrendChart(priceTrend) {
    const ctx = document.getElementById('trend-chart').getContext('2d');

    if (trendChart) {
        trendChart.destroy();
    }

    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: priceTrend.map(p => p.month),
            datasets: [{
                label: 'Średnia miesięczna (EUR/MWh)',
                data: priceTrend.map(p => p.avg_price),
                borderColor: '#9b59b6',
                backgroundColor: 'rgba(155, 89, 182, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 12 }
                },
                y: {
                    title: { display: true, text: 'EUR/MWh' },
                    grid: { color: '#f0f0f0' }
                }
            }
        }
    });
}

function renderYearlySummary(yearlyStats) {
    const container = document.getElementById('yearly-summary');
    container.innerHTML = '';

    yearlyStats.forEach(year => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <h3>${year.year}</h3>
            <div class="value">${year.avg_price.toFixed(1)} EUR</div>
            <small style="color: #7f8c8d">Średnia roczna</small>
        `;
        container.appendChild(card);
    });
}

function renderYearlyTable(yearlyStats) {
    const tbody = document.querySelector('#yearly-table tbody');
    tbody.innerHTML = '';

    yearlyStats.forEach(year => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${year.year}</strong></td>
            <td>${year.avg_price.toFixed(2)}</td>
            <td>${year.min_price.toFixed(2)}</td>
            <td>${year.max_price.toFixed(2)}</td>
            <td>${year.median_price.toFixed(2)}</td>
            <td>${year.volatility.toFixed(1)}</td>
            <td>${year.baseload_avg.toFixed(2)}</td>
            <td>${year.peakload_avg.toFixed(2)}</td>
        `;
        tbody.appendChild(row);
    });
}

// ============== Analysis Period ==============

async function loadAnalysisPrices() {
    const startDate = document.getElementById('analysis-start').value;
    const endDate = document.getElementById('analysis-end').value;
    const btn = document.getElementById('load-analysis');

    btn.disabled = true;
    btn.textContent = 'Analizowanie...';

    try {
        const response = await fetch(`${API_BASE}/prices/analysis-period?start_date=${startDate}&end_date=${endDate}`);
        const data = await response.json();

        renderAnalysisSummary(data.summary);
        renderHourlyProfileChart(data.hourly_profile);
        renderPVCorrelation(data.pv_correlation);
        renderMonthlyChart(data.monthly_stats);

    } catch (error) {
        console.error('Error loading analysis:', error);
        alert('Błąd podczas analizy okresu');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Analizuj okres';
    }
}

function renderAnalysisSummary(summary) {
    const avgPln = summary.avg_price_pln ? summary.avg_price_pln.toFixed(2) : '-';
    const minPln = summary.min_price_pln ? summary.min_price_pln.toFixed(2) : '-';
    const maxPln = summary.max_price_pln ? summary.max_price_pln.toFixed(2) : '-';

    const container = document.getElementById('analysis-summary');
    container.innerHTML = `
        <div class="card">
            <h3>Średnia cena</h3>
            <div class="value">${summary.avg_price_eur.toFixed(2)} EUR</div>
            <div class="pln-value">${avgPln} PLN</div>
        </div>
        <div class="card">
            <h3>Minimum</h3>
            <div class="value">${summary.min_price_eur.toFixed(2)} EUR</div>
            <div class="pln-value">${minPln} PLN</div>
        </div>
        <div class="card">
            <h3>Maksimum</h3>
            <div class="value">${summary.max_price_eur.toFixed(2)} EUR</div>
            <div class="pln-value">${maxPln} PLN</div>
        </div>
        <div class="card">
            <h3>Zmienność</h3>
            <div class="value">${summary.volatility_pct.toFixed(1)}%</div>
        </div>
    `;
}

function renderHourlyProfileChart(hourlyProfile) {
    const ctx = document.getElementById('hourly-profile-chart').getContext('2d');

    if (hourlyProfileChart) {
        hourlyProfileChart.destroy();
    }

    hourlyProfileChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: hourlyProfile.map(h => `${h.hour}:00`),
            datasets: [{
                label: 'Średnia cena',
                data: hourlyProfile.map(h => h.avg_price),
                backgroundColor: hourlyProfile.map(h =>
                    (h.hour >= 10 && h.hour <= 16) ? 'rgba(241, 196, 15, 0.8)' : 'rgba(52, 152, 219, 0.8)'
                ),
                borderColor: hourlyProfile.map(h =>
                    (h.hour >= 10 && h.hour <= 16) ? '#f1c40f' : '#3498db'
                ),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: function(context) {
                            const h = hourlyProfile[context.dataIndex];
                            return `Min: ${h.min_price.toFixed(1)} | Max: ${h.max_price.toFixed(1)}`;
                        }
                    }
                }
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    title: { display: true, text: 'EUR/MWh' },
                    grid: { color: '#f0f0f0' }
                }
            }
        }
    });
}

function renderPVCorrelation(pvCorr) {
    const text = document.getElementById('pv-correlation-text');
    const discount = pvCorr.pv_discount_pct;

    // Obsługa nowego formatu z _eur i _pln
    const pvHoursEur = pvCorr.pv_hours_avg_eur || pvCorr.pv_hours_avg || 0;
    const nonPvHoursEur = pvCorr.non_pv_hours_avg_eur || pvCorr.non_pv_hours_avg || 0;
    const pvHoursPln = pvCorr.pv_hours_avg_pln ? pvCorr.pv_hours_avg_pln.toFixed(2) : '-';
    const nonPvHoursPln = pvCorr.non_pv_hours_avg_pln ? pvCorr.non_pv_hours_avg_pln.toFixed(2) : '-';

    if (discount > 0) {
        text.innerHTML = `
            <strong>Ceny w godzinach szczytu PV (10:00-16:00)</strong> są średnio
            <strong style="color: #27ae60">${discount.toFixed(1)}% niższe</strong> niż w pozostałych godzinach.<br><br>
            Średnia cena PV: <strong>${pvHoursEur.toFixed(2)} EUR/MWh</strong> <span class="pln-inline">(${pvHoursPln} PLN)</span><br>
            Średnia cena poza PV: <strong>${nonPvHoursEur.toFixed(2)} EUR/MWh</strong> <span class="pln-inline">(${nonPvHoursPln} PLN)</span><br><br>
            <em>${pvCorr.insight}</em>
        `;
    } else {
        text.innerHTML = `
            <strong>Ceny w godzinach szczytu PV (10:00-16:00)</strong> są średnio
            <strong style="color: #e74c3c">${Math.abs(discount).toFixed(1)}% wyższe</strong> niż w pozostałych godzinach.<br><br>
            Średnia cena PV: <strong>${pvHoursEur.toFixed(2)} EUR/MWh</strong> <span class="pln-inline">(${pvHoursPln} PLN)</span><br>
            Średnia cena poza PV: <strong>${nonPvHoursEur.toFixed(2)} EUR/MWh</strong> <span class="pln-inline">(${nonPvHoursPln} PLN)</span><br><br>
            <em>${pvCorr.insight}</em>
        `;
    }
}

function renderMonthlyChart(monthlyStats) {
    const ctx = document.getElementById('monthly-chart').getContext('2d');

    if (monthlyChart) {
        monthlyChart.destroy();
    }

    monthlyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: monthlyStats.map(m => m.month),
            datasets: [{
                label: 'Średnia cena',
                data: monthlyStats.map(m => m.avg_price),
                backgroundColor: 'rgba(155, 89, 182, 0.8)',
                borderColor: '#9b59b6',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { grid: { display: false } },
                y: {
                    title: { display: true, text: 'EUR/MWh' },
                    grid: { color: '#f0f0f0' }
                }
            }
        }
    });
}

// ============== SPOT vs Fixed Comparison ==============

async function loadComparison() {
    const startDate = document.getElementById('compare-start').value;
    const endDate = document.getElementById('compare-end').value;
    const fixedPrice = document.getElementById('fixed-price').value;
    const btn = document.getElementById('load-comparison');

    btn.disabled = true;
    btn.textContent = 'Porównywanie...';

    try {
        const response = await fetch(
            `${API_BASE}/prices/spot-vs-fixed?start_date=${startDate}&end_date=${endDate}&fixed_price_eur=${fixedPrice}`
        );
        const data = await response.json();

        renderComparisonResult(data);

    } catch (error) {
        console.error('Error loading comparison:', error);
        alert('Błąd podczas porównania');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Porównaj';
    }
}

function renderComparisonResult(data) {
    // SPOT values - EUR i PLN
    const spotAvgPln = data.spot_avg_pln ? data.spot_avg_pln.toFixed(2) : '-';
    const spotMinPln = data.spot_min_pln ? data.spot_min_pln.toFixed(0) : '-';
    const spotMaxPln = data.spot_max_pln ? data.spot_max_pln.toFixed(0) : '-';

    document.getElementById('spot-avg').innerHTML = `${data.spot_avg_eur.toFixed(2)} EUR/MWh<br><span class="pln-price">${spotAvgPln} PLN/MWh</span>`;
    document.getElementById('spot-min').innerHTML = `${data.spot_min_eur.toFixed(0)} EUR<br><span class="pln-small">${spotMinPln} PLN</span>`;
    document.getElementById('spot-max').innerHTML = `${data.spot_max_eur.toFixed(0)} EUR<br><span class="pln-small">${spotMaxPln} PLN</span>`;

    // Fixed value - EUR i PLN
    const fixedPln = data.fixed_price_pln ? data.fixed_price_pln.toFixed(2) : '-';
    document.getElementById('fixed-value').innerHTML = `${data.fixed_price_eur.toFixed(2)} EUR/MWh<br><span class="pln-price">${fixedPln} PLN/MWh</span>`;

    // Savings
    const savingsCard = document.getElementById('savings-card');
    const savingsPct = data.savings_on_spot_pct;

    document.getElementById('savings-pct').textContent = `${savingsPct > 0 ? '+' : ''}${savingsPct.toFixed(1)}%`;
    document.getElementById('recommendation').textContent = data.recommendation;

    if (savingsPct > 0) {
        savingsCard.classList.remove('loss');
        document.getElementById('savings-pct').style.color = '#27ae60';
    } else {
        savingsCard.classList.add('loss');
        document.getElementById('savings-pct').style.color = '#e74c3c';
    }

    // Risk analysis
    const risk = data.risk_analysis;
    const maxSpikeEur = risk.max_spike_above_fixed_eur !== undefined ? risk.max_spike_above_fixed_eur : risk.max_spike_above_fixed;
    const maxSpikePln = risk.max_spike_above_fixed_pln ? risk.max_spike_above_fixed_pln.toFixed(2) : '-';

    document.getElementById('time-cheaper').textContent = `${risk.pct_time_spot_cheaper.toFixed(1)}%`;
    document.getElementById('hours-above').textContent = risk.hours_spot_above_fixed.toLocaleString();
    document.getElementById('max-spike').innerHTML = `${maxSpikeEur.toFixed(2)} EUR<br><span class="pln-small">${maxSpikePln} PLN</span>`;
}
