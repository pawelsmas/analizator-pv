/**
 * Monte Carlo BESS Frontend Module
 * Stochastic investment analysis with Cholesky-correlated sampling.
 *
 * Features:
 * - Async job polling with real progress bar (from backend convergence)
 * - NPV probability curves per battery size
 * - Tornado sensitivity chart
 * - Size comparison heatmap
 * - Fan chart (NPV over time with P10-P90 bands)
 * - Polish-language insights
 *
 * Version: 1.0.0
 */

const BESS_API_URL = '/api/bess-dispatch';
let mcBessChart = null;
let mcBessTornadoChart = null;
let mcBessJobId = null;
let mcBessPollInterval = null;
let lastMcBessResult = null;

// ============================================================================
// UI Rendering
// ============================================================================

function renderMcBessSection() {
    const container = document.getElementById('mcBessContainer');
    if (!container) return;

    container.innerHTML = `
    <div class="mc-bess-panel" style="background:#f8f9fa;border-radius:12px;padding:24px;margin-top:16px;border:1px solid #e0e0e0;">
        <h3 style="margin:0 0 16px 0;color:#1a237e;font-size:18px;display:flex;align-items:center;gap:8px;">
            MONTE CARLO BESS — Analiza Stochastyczna Inwestycji
        </h3>
        <p style="color:#666;font-size:13px;margin-bottom:16px;">
            Symulacja wieloscenariuszowa z korelacjami Cholesky'ego: ceny RDN, opłata mocowa, degradacja baterii, profil zużycia.
        </p>

        <!-- Config Row -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px;">
            <div>
                <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">Tryb symulacji</label>
                <select id="mcBessMode" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:13px;">
                    <option value="quick">Quick (500 iter, ~30s)</option>
                    <option value="standard" selected>Standard (2000 iter, ~2min)</option>
                    <option value="full">Full (5000 iter, ~5min)</option>
                </select>
            </div>
            <div>
                <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">CAPEX [PLN/kWh]</label>
                <input type="number" id="mcBessCapex" value="2000" min="500" max="10000" step="100"
                       style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:13px;box-sizing:border-box;">
            </div>
            <div>
                <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">Horyzont [lata]</label>
                <input type="number" id="mcBessYears" value="15" min="5" max="30"
                       style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:13px;box-sizing:border-box;">
            </div>
            <div>
                <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">Stopa dyskonta [%]</label>
                <input type="number" id="mcBessDiscount" value="8" min="1" max="30" step="0.5"
                       style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:13px;box-sizing:border-box;">
            </div>
        </div>

        <!-- Battery Sizes -->
        <div style="margin-bottom:16px;">
            <label style="font-size:12px;color:#555;display:block;margin-bottom:4px;">Rozmiary magazynow do analizy</label>
            <div id="mcBessSizes" style="display:flex;flex-wrap:wrap;gap:8px;">
                <span class="mc-size-tag" data-kw="50" data-kwh="100" style="background:#e3f2fd;border:1px solid #90caf9;border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;">50kW/100kWh</span>
                <span class="mc-size-tag active" data-kw="100" data-kwh="200" style="background:#1565c0;color:white;border:1px solid #1565c0;border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;">100kW/200kWh</span>
                <span class="mc-size-tag active" data-kw="100" data-kwh="400" style="background:#1565c0;color:white;border:1px solid #1565c0;border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;">100kW/400kWh</span>
                <span class="mc-size-tag" data-kw="200" data-kwh="400" style="background:#e3f2fd;border:1px solid #90caf9;border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;">200kW/400kWh</span>
                <span class="mc-size-tag" data-kw="200" data-kwh="800" style="background:#e3f2fd;border:1px solid #90caf9;border-radius:16px;padding:4px 12px;font-size:12px;cursor:pointer;">200kW/800kWh</span>
            </div>
        </div>

        <!-- Run Button + Status -->
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;">
            <button id="mcBessRunBtn" onclick="runMcBess()" style="background:linear-gradient(135deg,#1565c0,#0d47a1);color:white;border:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;min-width:280px;">
                URUCHOM MONTE CARLO BESS
            </button>
            <div id="mcBessStatus" style="flex:1;font-size:13px;color:#666;"></div>
        </div>

        <!-- Progress Bar -->
        <div id="mcBessProgressBar" style="display:none;margin-bottom:16px;">
            <div style="background:#e0e0e0;border-radius:4px;height:8px;overflow:hidden;">
                <div id="mcBessProgressFill" style="background:linear-gradient(90deg,#1565c0,#42a5f5);height:100%;width:0%;transition:width 0.5s ease;border-radius:4px;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px;">
                <span id="mcBessProgressText" style="font-size:11px;color:#888;">0%</span>
                <span id="mcBessConvergence" style="font-size:11px;color:#888;"></span>
            </div>
        </div>

        <!-- Results Container (hidden initially) -->
        <div id="mcBessResults" style="display:none;">

            <!-- Insights -->
            <div id="mcBessInsights" style="background:#e8f5e9;border-radius:8px;padding:16px;margin-bottom:16px;border-left:4px solid #4caf50;"></div>

            <!-- Size Comparison Heatmap -->
            <div style="margin-bottom:24px;">
                <h4 style="color:#1a237e;margin:0 0 12px 0;">Porownanie rozmiarow</h4>
                <div id="mcBessSizeTable"></div>
            </div>

            <!-- NPV Histogram -->
            <div style="margin-bottom:24px;">
                <h4 style="color:#1a237e;margin:0 0 12px 0;">Rozklad NPV</h4>
                <canvas id="mcBessHistogramCanvas" width="700" height="300"></canvas>
            </div>

            <!-- Tornado Chart -->
            <div style="margin-bottom:24px;">
                <h4 style="color:#1a237e;margin:0 0 12px 0;">Analiza wrazliwosci (Tornado)</h4>
                <canvas id="mcBessTornadoCanvas" width="700" height="250"></canvas>
            </div>

            <!-- Convergence Info -->
            <div id="mcBessConvergenceInfo" style="background:#fff3e0;border-radius:8px;padding:12px;font-size:12px;color:#e65100;"></div>
        </div>
    </div>`;

    // Add click handlers for size tags
    document.querySelectorAll('.mc-size-tag').forEach(tag => {
        tag.addEventListener('click', () => {
            tag.classList.toggle('active');
            if (tag.classList.contains('active')) {
                tag.style.background = '#1565c0';
                tag.style.color = 'white';
                tag.style.borderColor = '#1565c0';
            } else {
                tag.style.background = '#e3f2fd';
                tag.style.color = '#333';
                tag.style.borderColor = '#90caf9';
            }
        });
    });
}


// ============================================================================
// Run Simulation
// ============================================================================

async function runMcBess() {
    const btn = document.getElementById('mcBessRunBtn');
    const status = document.getElementById('mcBessStatus');
    const progressBar = document.getElementById('mcBessProgressBar');
    const progressFill = document.getElementById('mcBessProgressFill');
    const progressText = document.getElementById('mcBessProgressText');
    const convergenceText = document.getElementById('mcBessConvergence');
    const results = document.getElementById('mcBessResults');

    // Collect selected sizes
    const sizes = [];
    document.querySelectorAll('.mc-size-tag.active').forEach(tag => {
        sizes.push({
            power_kw: parseFloat(tag.dataset.kw),
            energy_kwh: parseFloat(tag.dataset.kwh),
            label: tag.textContent.trim(),
        });
    });

    if (sizes.length === 0) {
        status.innerHTML = '<span style="color:#e74c3c;">Wybierz co najmniej jeden rozmiar magazynu</span>';
        return;
    }

    // Get load/PV data from BESS module globals
    let loadKw, pvKw, startDate;
    try {
        const bessData = getBessDataForMonteCarlo();
        loadKw = bessData.loadKw;
        pvKw = bessData.pvKw;
        startDate = bessData.startDate;
    } catch (e) {
        status.innerHTML = `<span style="color:#e74c3c;">Brak danych: ${e.message}. Uruchom najpierw sizing BESS.</span>`;
        return;
    }

    // Build request
    const mode = document.getElementById('mcBessMode').value;
    const capex = parseFloat(document.getElementById('mcBessCapex').value);
    const years = parseInt(document.getElementById('mcBessYears').value);
    const discount = parseFloat(document.getElementById('mcBessDiscount').value) / 100;

    const payload = {
        mode: mode,
        battery_sizes: sizes,
        load_kw: loadKw,
        pv_kw: pvKw,
        start_date: startDate,
        capex_pln_per_kwh: capex,
        analysis_years: years,
        discount_rate: discount,
        histogram_bins: 40,
    };

    // UI: start
    btn.disabled = true;
    btn.textContent = 'Uruchamianie...';
    progressBar.style.display = 'block';
    progressFill.style.width = '0%';
    results.style.display = 'none';
    status.innerHTML = '<span style="color:#1565c0;">Wysylanie zadania...</span>';

    try {
        // Start async job
        const startResp = await fetch(`${BESS_API_URL}/monte-carlo/start`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });

        if (!startResp.ok) {
            const err = await startResp.json();
            throw new Error(err.detail || `HTTP ${startResp.status}`);
        }

        const startData = await startResp.json();
        mcBessJobId = startData.job_id;
        status.innerHTML = `<span style="color:#1565c0;">Job: ${mcBessJobId}</span>`;

        // Poll for status
        mcBessPollInterval = setInterval(async () => {
            try {
                const pollResp = await fetch(`${BESS_API_URL}/monte-carlo/status/${mcBessJobId}`);
                const pollData = await pollResp.json();

                const pct = pollData.progress_pct || 0;
                progressFill.style.width = `${pct}%`;
                progressText.textContent = `${pct.toFixed(0)}%`;
                btn.textContent = `${pct.toFixed(0)}% — Symulacja...`;
                convergenceText.textContent = pollData.message || '';

                if (pollData.state === 'done') {
                    clearInterval(mcBessPollInterval);
                    mcBessPollInterval = null;

                    lastMcBessResult = pollData.result;
                    progressFill.style.width = '100%';
                    progressText.textContent = '100%';
                    status.innerHTML = `<span style="color:#27ae60;font-weight:600;">Zakonczone w ${(pollData.elapsed_ms/1000).toFixed(1)}s</span>`;

                    displayMcBessResults(pollData.result);
                    btn.disabled = false;
                    btn.textContent = 'URUCHOM MONTE CARLO BESS';
                } else if (pollData.state === 'failed') {
                    clearInterval(mcBessPollInterval);
                    mcBessPollInterval = null;
                    status.innerHTML = `<span style="color:#e74c3c;">Blad: ${pollData.error}</span>`;
                    btn.disabled = false;
                    btn.textContent = 'URUCHOM MONTE CARLO BESS';
                }
            } catch (e) {
                // Ignore transient poll errors
            }
        }, 1500);

    } catch (e) {
        status.innerHTML = `<span style="color:#e74c3c;">Blad: ${e.message}</span>`;
        btn.disabled = false;
        btn.textContent = 'URUCHOM MONTE CARLO BESS';
        progressBar.style.display = 'none';
    }
}


// ============================================================================
// Data Extraction (from BESS module globals)
// ============================================================================

function getBessDataForMonteCarlo() {
    // Try multiple sources for load/PV data
    // 1. BESS module cached data (from sizing)
    if (typeof cachedHourlyConsumption !== 'undefined' && cachedHourlyConsumption &&
        cachedHourlyConsumption.values && cachedHourlyConsumption.values.length >= 8760) {
        const loadKw = cachedHourlyConsumption.values.slice(0, 8760);
        let pvKw = null;
        if (typeof cachedHourlyProduction !== 'undefined' && cachedHourlyProduction &&
            cachedHourlyProduction.values && cachedHourlyProduction.values.length >= 8760) {
            pvKw = cachedHourlyProduction.values.slice(0, 8760);
        }
        const startDate = cachedHourlyConsumption.timestamps?.[0]?.slice(0, 10) || '2025-01-01';
        return { loadKw, pvKw, startDate };
    }

    // 2. localStorage fallback
    const stored = localStorage.getItem('bessSharedData');
    if (stored) {
        try {
            const data = JSON.parse(stored);
            if (data.hourlyConsumption && data.hourlyConsumption.length >= 8760) {
                return {
                    loadKw: data.hourlyConsumption.slice(0, 8760),
                    pvKw: data.hourlyProduction ? data.hourlyProduction.slice(0, 8760) : null,
                    startDate: data.startDate || '2025-01-01',
                };
            }
        } catch (e) {}
    }

    throw new Error('Brak profilu godzinowego (min. 8760 wartosci)');
}


// ============================================================================
// Display Results
// ============================================================================

function displayMcBessResults(result) {
    const container = document.getElementById('mcBessResults');
    container.style.display = 'block';

    // Insights
    displayMcBessInsights(result.insights);

    // Size comparison table
    displayMcBessSizeTable(result.size_results, result.size_comparison);

    // NPV histogram (for optimal size)
    const optIdx = result.size_comparison.optimal_size_index;
    displayMcBessHistogram(result.size_results[optIdx]);

    // Tornado
    displayMcBessTornado(result.tornado);

    // Convergence info
    displayMcBessConvergence(result.convergence);
}


function displayMcBessInsights(insights) {
    const el = document.getElementById('mcBessInsights');
    el.innerHTML = insights.map(i =>
        `<div style="margin-bottom:8px;font-size:13px;line-height:1.5;">${i}</div>`
    ).join('');
}


function displayMcBessSizeTable(sizeResults, comparison) {
    const el = document.getElementById('mcBessSizeTable');
    const optIdx = comparison.optimal_size_index;

    let html = `<table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
            <tr style="background:#e3f2fd;border-bottom:2px solid #1565c0;">
                <th style="padding:10px 8px;text-align:left;">Rozmiar</th>
                <th style="padding:10px 8px;text-align:right;">CAPEX</th>
                <th style="padding:10px 8px;text-align:right;">P(NPV>0)</th>
                <th style="padding:10px 8px;text-align:right;">NPV P50</th>
                <th style="padding:10px 8px;text-align:right;">NPV P10</th>
                <th style="padding:10px 8px;text-align:right;">CVaR 95%</th>
                <th style="padding:10px 8px;text-align:right;">Payback P50</th>
                <th style="padding:10px 8px;text-align:right;">Cykle/rok</th>
                <th style="padding:10px 8px;text-align:left;">Rekomendacja</th>
            </tr>
        </thead>
        <tbody>`;

    sizeResults.forEach((sr, i) => {
        const isOpt = i === optIdx;
        const rowBg = isOpt ? 'background:#e8f5e9;font-weight:600;' : (i % 2 ? 'background:#fafafa;' : '');
        const probColor = sr.risk_metrics.prob_positive_npv >= 0.8 ? '#27ae60' :
                         sr.risk_metrics.prob_positive_npv >= 0.5 ? '#f39c12' : '#e74c3c';

        const payback = sr.breakeven.payback_p50_years != null ?
            `${sr.breakeven.payback_p50_years.toFixed(1)} lat` : 'n/d';

        html += `<tr style="${rowBg}border-bottom:1px solid #eee;">
            <td style="padding:8px;">${sr.label || sr.power_kw + '/' + sr.energy_kwh}</td>
            <td style="padding:8px;text-align:right;">${formatPLN(sr.capex_pln)}</td>
            <td style="padding:8px;text-align:right;color:${probColor};font-weight:700;">${(sr.risk_metrics.prob_positive_npv * 100).toFixed(0)}%</td>
            <td style="padding:8px;text-align:right;">${formatPLN(sr.npv_percentiles.p50)}</td>
            <td style="padding:8px;text-align:right;color:#e74c3c;">${formatPLN(sr.npv_percentiles.p10)}</td>
            <td style="padding:8px;text-align:right;">${formatPLN(sr.risk_metrics.cvar_95)}</td>
            <td style="padding:8px;text-align:right;">${payback}</td>
            <td style="padding:8px;text-align:right;">${sr.mean_annual_cycles?.toFixed(0) || '-'}</td>
            <td style="padding:8px;font-size:12px;">${sr.recommendation || ''}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    el.innerHTML = html;
}


function displayMcBessHistogram(sizeResult) {
    const canvas = document.getElementById('mcBessHistogramCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const hist = sizeResult.npv_histogram;
    if (!hist || !hist.counts || hist.counts.length === 0) return;

    const maxCount = Math.max(...hist.counts);
    const barWidth = (canvas.width - 80) / hist.counts.length;
    const chartHeight = canvas.height - 50;

    // Draw bars
    hist.counts.forEach((count, i) => {
        const x = 60 + i * barWidth;
        const h = (count / maxCount) * (chartHeight - 20);
        const npvMid = (hist.bin_edges[i] + hist.bin_edges[i + 1]) / 2;

        // Color based on NPV value
        ctx.fillStyle = npvMid >= 0 ? 'rgba(76, 175, 80, 0.7)' : 'rgba(244, 67, 54, 0.5)';
        ctx.fillRect(x, chartHeight - h, barWidth - 1, h);
    });

    // Zero line
    const zeroX = 60 + ((0 - hist.bin_edges[0]) / (hist.bin_edges[hist.bin_edges.length - 1] - hist.bin_edges[0])) * (canvas.width - 80);
    if (zeroX > 60 && zeroX < canvas.width - 20) {
        ctx.strokeStyle = '#333';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(zeroX, 5);
        ctx.lineTo(zeroX, chartHeight);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#333';
        ctx.font = '11px sans-serif';
        ctx.fillText('NPV=0', zeroX + 4, 15);
    }

    // P50 line
    const p50 = sizeResult.npv_percentiles.p50;
    const p50X = 60 + ((p50 - hist.bin_edges[0]) / (hist.bin_edges[hist.bin_edges.length - 1] - hist.bin_edges[0])) * (canvas.width - 80);
    if (p50X > 60 && p50X < canvas.width - 20) {
        ctx.strokeStyle = '#1565c0';
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(p50X, 5);
        ctx.lineTo(p50X, chartHeight);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#1565c0';
        ctx.font = 'bold 11px sans-serif';
        ctx.fillText(`P50: ${formatPLN(p50)}`, p50X + 4, 30);
    }

    // X-axis labels
    ctx.fillStyle = '#666';
    ctx.font = '10px sans-serif';
    const nLabels = 5;
    for (let i = 0; i <= nLabels; i++) {
        const val = hist.bin_edges[0] + (hist.bin_edges[hist.bin_edges.length - 1] - hist.bin_edges[0]) * i / nLabels;
        const x = 60 + (canvas.width - 80) * i / nLabels;
        ctx.fillText(formatPLN(val), x - 20, chartHeight + 15);
    }

    // Title
    ctx.fillStyle = '#333';
    ctx.font = '12px sans-serif';
    ctx.fillText(`${sizeResult.label} — P(NPV>0): ${(sizeResult.risk_metrics.prob_positive_npv * 100).toFixed(0)}%`, 60, chartHeight + 35);

    // Y-axis label
    ctx.save();
    ctx.translate(15, chartHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = '#888';
    ctx.font = '11px sans-serif';
    ctx.fillText('Liczba scenariuszy', 0, 0);
    ctx.restore();
}


function displayMcBessTornado(tornado) {
    const canvas = document.getElementById('mcBessTornadoCanvas');
    if (!canvas || !tornado || tornado.length === 0) return;
    const ctx = canvas.getContext('2d');

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const leftMargin = 160;
    const rightMargin = 20;
    const chartWidth = canvas.width - leftMargin - rightMargin;
    const barHeight = 30;
    const barGap = 8;
    const topMargin = 20;

    // Find global range
    let minVal = Infinity, maxVal = -Infinity;
    tornado.forEach(t => {
        minVal = Math.min(minVal, t.npv_low);
        maxVal = Math.max(maxVal, t.npv_high);
    });
    const range = maxVal - minVal || 1;

    tornado.forEach((t, i) => {
        const y = topMargin + i * (barHeight + barGap);

        // Label
        ctx.fillStyle = '#333';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(t.label_pl, leftMargin - 10, y + barHeight / 2 + 4);

        // Low bar (red)
        const lowX = leftMargin + ((t.npv_low - minVal) / range) * chartWidth;
        const midX = leftMargin + ((t.npv_low + t.impact / 2 - minVal) / range) * chartWidth;

        ctx.fillStyle = 'rgba(244, 67, 54, 0.6)';
        ctx.fillRect(lowX, y, midX - lowX, barHeight);

        // High bar (green)
        const highX = leftMargin + ((t.npv_high - minVal) / range) * chartWidth;
        ctx.fillStyle = 'rgba(76, 175, 80, 0.6)';
        ctx.fillRect(midX, y, highX - midX, barHeight);

        // Impact label
        ctx.fillStyle = '#333';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`${formatPLN(t.impact)}`, highX + 6, y + barHeight / 2 + 4);
    });

    ctx.textAlign = 'left';
}


function displayMcBessConvergence(conv) {
    const el = document.getElementById('mcBessConvergenceInfo');
    el.innerHTML = `
        <strong>Konwergencja:</strong>
        ${conv.converged ? 'TAK' : 'NIE (osiagnieto max iteracji)'} |
        Iteracji: ${conv.iterations_run} |
        P50 delta: ${conv.p50_change_pct.toFixed(3)}% |
        CVaR95 delta: ${conv.cvar95_change_pct.toFixed(3)}% |
        Burn-in: ${conv.burn_in_iterations} |
        Stabilne batche: ${conv.stable_batches}
    `;
}


// ============================================================================
// Helpers
// ============================================================================

function formatPLN(val) {
    if (val == null || isNaN(val)) return '-';
    const abs = Math.abs(val);
    let formatted;
    if (abs >= 1000000) {
        formatted = (val / 1000000).toFixed(2) + 'M';
    } else if (abs >= 1000) {
        formatted = (val / 1000).toFixed(0) + 'k';
    } else {
        formatted = val.toFixed(0);
    }
    return formatted + ' PLN';
}


// ============================================================================
// Init — call after DOM ready
// ============================================================================

function initMcBess() {
    // Create container in BESS page if not exists
    let container = document.getElementById('mcBessContainer');
    if (!container) {
        // Find a good insertion point (after sizing results, before footer)
        const bessContainer = document.querySelector('.bess-container');
        if (bessContainer) {
            container = document.createElement('div');
            container.id = 'mcBessContainer';
            bessContainer.appendChild(container);
        }
    }
    if (container) {
        renderMcBessSection();
    }
}

// Auto-init when script loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMcBess);
} else {
    initMcBess();
}
