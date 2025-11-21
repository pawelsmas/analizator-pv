console.log('💡 insights.js LOADED - timestamp:', new Date().toISOString());

// Backend URLs
const ADVANCED_ANALYTICS_URL = 'http://localhost:8004';
const TYPICAL_DAYS_URL = 'http://localhost:8005';

// Chart instances
let charts = {};

// Stored variant data
let currentVariantData = null;

// Main initialization
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Initializing Insights module...');

    updateStatus('⏳', 'Oczekiwanie na dane wariantu...');

    // Request data from shell
    requestSharedData();
});

// Request shared data from shell
function requestSharedData() {
    if (window.parent !== window) {
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
        console.log('📡 Requested shared data from shell');
    }
}

// Listen for messages from shell
window.addEventListener('message', async (event) => {
    console.log('🔵 Insights received message:', event.data.type);

    switch (event.data.type) {
        case 'VARIANT_ADDED':
        case 'VARIANT_UPDATED':
        case 'DATA_AVAILABLE':
        case 'ANALYSIS_RESULTS':
            console.log('📦 Received variant update, requesting fresh data...');
            requestSharedData();
            break;

        case 'SHARED_DATA_RESPONSE':
            console.log('📦 Received SHARED_DATA_RESPONSE:', event.data.data);
            if (event.data.data && event.data.data.analysisResults) {
                console.log('✅ Received analysis results from shell');
                // Pass both analysisResults AND hourlyData from sharedData
                await handleAnalysisResults(event.data.data.analysisResults, event.data.data.hourlyData);
            } else {
                // Shell doesn't have data yet
                console.log('⚠️ No data from shell yet');
                updateStatus('⚠️', 'Brak danych wariantu - proszę skonfigurować wariant w zakładce KONFIGURACJA', 'error');
            }
            break;

        case 'DATA_CLEARED':
            clearAllData();
            break;
    }
});

async function handleAnalysisResults(analysisResults, hourlyData) {
    try {
        updateStatus('⏳', 'Przetwarzanie danych...');

        console.log('🔍 DEBUG analysisResults:', analysisResults);
        console.log('🔍 DEBUG analysisResults keys:', Object.keys(analysisResults || {}));
        console.log('🔍 DEBUG hourlyData from sharedData:', hourlyData);

        // Variants are in key_variants object
        const variants = analysisResults.key_variants || {};
        console.log('🔍 DEBUG key_variants:', variants);

        // Find master variant among A, B, C, D
        const variantKeys = ['A', 'B', 'C', 'D'];
        let variantData = null;
        let variantKey = null;

        // First, try to find master variant
        for (const key of variantKeys) {
            console.log(`🔍 Checking variant ${key}:`, variants[key]);
            if (variants[key] && variants[key].isMaster) {
                variantKey = key;
                variantData = variants[key];
                console.log(`✅ Found master variant: ${key}`);
                break;
            }
        }

        // If no master found, use first available variant
        if (!variantData) {
            for (const key of variantKeys) {
                if (variants[key]) {
                    variantKey = key;
                    variantData = variants[key];
                    console.log(`✅ Using first available variant: ${key}`);
                    break;
                }
            }
        }

        if (!variantData) {
            console.error('❌ No variants found. Available keys:', Object.keys(variants || {}));
            throw new Error('Brak dostępnych wariantów (A, B, C lub D)');
        }

        console.log(`📊 Using variant: ${variantKey}`, variantData);

        // Hourly consumption is in sharedData.hourlyData (passed as parameter)
        // PV production profile is in analysisResults.pv_profile

        // hourlyData is an object with {timestamps: [], values: []}
        // We need the values array
        let hourlyConsumption = [];
        if (hourlyData && hourlyData.values && Array.isArray(hourlyData.values)) {
            hourlyConsumption = hourlyData.values;
            console.log('✅ Extracted consumption values from hourlyData.values');
        } else if (Array.isArray(hourlyData)) {
            // Fallback: if it's already an array, use it directly
            hourlyConsumption = hourlyData;
            console.log('✅ Using hourlyData directly (already array)');
        } else {
            console.warn('⚠️ hourlyData has unexpected format:', hourlyData);
        }

        let pvProfile = analysisResults.pv_profile || [];

        // Validate that data is actually an array
        console.log('🔍 Raw hourlyData:', hourlyData);
        console.log('🔍 Raw pv_profile:', analysisResults.pv_profile);
        console.log('🔍 Extracted consumption array length:', hourlyConsumption.length);
        console.log('🔍 pv_profile type:', typeof pvProfile, 'isArray:', Array.isArray(pvProfile));

        // Ensure arrays
        if (!Array.isArray(pvProfile)) {
            console.warn('⚠️ pvProfile is not an array, converting...');
            pvProfile = [];
        }

        console.log('🔍 Hourly data lengths:', {
            consumption: hourlyConsumption.length,
            pvProfile: pvProfile.length
        });

        // Validate we have data
        if (hourlyConsumption.length === 0 || pvProfile.length === 0) {
            throw new Error(`Brak danych godzinowych: consumption=${hourlyConsumption.length}, production=${pvProfile.length}`);
        }

        // Store variant data
        currentVariantData = {
            consumption: hourlyConsumption,
            production: pvProfile,
            params: {
                capacityKWp: variantData.capacity || 10.0,
                batteryCapacityKWh: 0.0
            }
        };

        // Load data from backends
        await loadAllData();

    } catch (error) {
        console.error('❌ Error handling analysis results:', error);
        showError('Błąd podczas przetwarzania danych: ' + error.message);
    }
}

async function loadAllData() {
    if (!currentVariantData) {
        throw new Error('Brak danych wariantu');
    }

    updateStatus('⏳', 'Ładowanie analiz z backendu...');

    try {
        // Load typical days analysis
        console.log('📊 Fetching typical days analysis...');
        const typicalDaysData = await fetchTypicalDays(currentVariantData);

        // Load advanced KPIs
        console.log('📈 Fetching advanced KPIs...');
        const kpiData = await fetchAdvancedKPIs(currentVariantData);

        // Render all sections
        renderKPIs(kpiData);
        renderSeasonalPatterns(typicalDaysData.seasonal_patterns);
        // Skip workday/weekend - not useful
        // renderWorkdayWeekend(typicalDaysData.typical_workday, typicalDaysData.typical_weekend);
        renderBestWorstDays(typicalDaysData.best_day, typicalDaysData.worst_day);
        // Skip insights - not useful
        // renderInsights(typicalDaysData.insights, kpiData.insights);

        updateStatus('✅', 'Dane załadowane pomyślnie', 'success');

    } catch (error) {
        console.error('❌ Error loading data:', error);
        updateStatus('❌', 'Błąd: ' + error.message, 'error');
        throw error;
    }
}

function clearAllData() {
    console.log('🗑️ Clearing all data');
    currentVariantData = null;

    // Destroy all charts
    Object.values(charts).forEach(chart => {
        if (chart) chart.destroy();
    });
    charts = {};

    updateStatus('⏳', 'Oczekiwanie na dane wariantu...');
}

async function fetchTypicalDays(variantData) {
    try {
        console.log('🔍 Sending to typical-days API:', {
            consumption_length: variantData.consumption?.length,
            production_length: variantData.production?.length,
            consumption_sample: variantData.consumption?.slice(0, 3),
            production_sample: variantData.production?.slice(0, 3)
        });

        const response = await fetch(`${TYPICAL_DAYS_URL}/analyze-typical-days`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                consumption: variantData.consumption,
                pv_production: variantData.production,
                start_date: "2023-01-01"
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('❌ Backend error response:', errorText);
            throw new Error(`Typical Days API error: ${response.status} - ${errorText}`);
        }

        const data = await response.json();
        console.log('✅ Typical days data received:', data);
        return data;
    } catch (error) {
        console.error('❌ Error fetching typical days:', error);
        throw error;
    }
}

async function fetchAdvancedKPIs(variantData) {
    try {
        const capacity = variantData.params?.capacityKWp || 10.0;

        console.log('🔍 Sending to advanced-analytics API:', {
            consumption_length: variantData.consumption?.length,
            production_length: variantData.production?.length,
            capacity: capacity
        });

        // Capacity must be a query parameter, not in body
        const url = `${ADVANCED_ANALYTICS_URL}/analyze-kpi?capacity=${capacity}&include_curtailment=true&include_weekend=true`;

        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                consumption: variantData.consumption,
                pv_production: variantData.production
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('❌ Advanced Analytics error response:', errorText);
            throw new Error(`Advanced Analytics API error: ${response.status} - ${errorText}`);
        }

        const data = await response.json();
        console.log('✅ Advanced KPI data received:', data);
        return data;
    } catch (error) {
        console.error('❌ Error fetching advanced KPIs:', error);
        throw error;
    }
}

function renderKPIs(kpiData) {
    console.log('📊 Rendering KPIs...');

    // Self consumption rate
    const selfConsumptionRate = kpiData.energy_balance?.self_consumption_rate || 0;
    document.getElementById('selfConsumptionRate').textContent = `${(selfConsumptionRate * 100).toFixed(1)}%`;

    // Self sufficiency rate
    const selfSufficiencyRate = kpiData.energy_balance?.self_sufficiency_rate || 0;
    document.getElementById('selfSufficiencyRate').textContent = `${(selfSufficiencyRate * 100).toFixed(1)}%`;

    // Load factor
    const loadFactor = kpiData.load_factor || 0;
    document.getElementById('loadFactor').textContent = loadFactor.toFixed(3);

    // Curtailment
    const curtailmentTotal = kpiData.curtailment?.total_curtailment || 0;
    document.getElementById('curtailment').textContent = curtailmentTotal.toFixed(0);

    // Grid import/export
    const gridImport = kpiData.energy_balance?.total_grid_import || 0;
    const gridExport = kpiData.energy_balance?.total_grid_export || 0;
    document.getElementById('gridImport').textContent = gridImport.toFixed(0);
    document.getElementById('gridExport').textContent = gridExport.toFixed(0);
}

function renderSeasonalPatterns(seasonalPatterns) {
    console.log('🌍 Rendering seasonal patterns...');

    if (!seasonalPatterns || seasonalPatterns.length === 0) {
        console.warn('⚠️ No seasonal patterns data');
        return;
    }

    const seasonMap = {
        'winter': { id: 'winter', icon: '❄️' },
        'spring': { id: 'spring', icon: '🌸' },
        'summer': { id: 'summer', icon: '☀️' },
        'fall': { id: 'fall', icon: '🍂' }
    };

    seasonalPatterns.forEach(season => {
        const seasonInfo = seasonMap[season.season];
        if (!seasonInfo) return;

        // Update stats
        document.getElementById(`${seasonInfo.id}Consumption`).textContent =
            `${season.avg_consumption.toFixed(1)} kWh`;
        document.getElementById(`${seasonInfo.id}Production`).textContent =
            `${season.avg_production.toFixed(1)} kWh`;
        document.getElementById(`${seasonInfo.id}SelfConsumption`).textContent =
            `${(season.avg_self_consumption_rate * 100).toFixed(1)}%`;

        // Create chart
        createDayChart(
            `${seasonInfo.id}Chart`,
            season.typical_day.hourly_consumption,
            season.typical_day.hourly_production,
            `${seasonInfo.icon} ${season.season.toUpperCase()}`
        );
    });
}

function renderWorkdayWeekend(workdayProfile, weekendProfile) {
    console.log('📅 Rendering workday vs weekend...');

    if (!workdayProfile || !weekendProfile) {
        console.warn('⚠️ No workday/weekend data');
        return;
    }

    // Workday stats
    document.getElementById('workdayConsumption').textContent =
        `${workdayProfile.consumption_total.toFixed(1)} kWh`;
    document.getElementById('workdayProduction').textContent =
        `${workdayProfile.production_total.toFixed(1)} kWh`;
    document.getElementById('workdaySelfConsumption').textContent =
        `${(workdayProfile.self_consumption_rate * 100).toFixed(1)}%`;
    document.getElementById('workdayImport').textContent =
        `${workdayProfile.grid_import.toFixed(1)} kWh`;
    document.getElementById('workdayExport').textContent =
        `${workdayProfile.grid_export.toFixed(1)} kWh`;

    // Weekend stats
    document.getElementById('weekendConsumption').textContent =
        `${weekendProfile.consumption_total.toFixed(1)} kWh`;
    document.getElementById('weekendProduction').textContent =
        `${weekendProfile.production_total.toFixed(1)} kWh`;
    document.getElementById('weekendSelfConsumption').textContent =
        `${(weekendProfile.self_consumption_rate * 100).toFixed(1)}%`;
    document.getElementById('weekendImport').textContent =
        `${weekendProfile.grid_import.toFixed(1)} kWh`;
    document.getElementById('weekendExport').textContent =
        `${weekendProfile.grid_export.toFixed(1)} kWh`;

    // Create charts
    createDayChart(
        'workdayChart',
        workdayProfile.hourly_consumption,
        workdayProfile.hourly_production,
        '💼 Typowy Dzień Roboczy'
    );

    createDayChart(
        'weekendChart',
        weekendProfile.hourly_consumption,
        weekendProfile.hourly_production,
        '🏖️ Typowy Weekend'
    );
}

function renderBestWorstDays(bestDay, worstDay) {
    console.log('🏆 Rendering best/worst days...');

    if (!bestDay || !worstDay) {
        console.warn('⚠️ No best/worst day data');
        return;
    }

    // Best day
    document.getElementById('bestDayDate').textContent = bestDay.date;
    document.getElementById('bestDaySelfConsumption').textContent =
        `${(bestDay.self_consumption_rate * 100).toFixed(1)}%`;
    document.getElementById('bestDayBalance').textContent =
        `${bestDay.net_balance.toFixed(1)} kWh`;

    createDayChart(
        'bestDayChart',
        bestDay.hourly_consumption,
        bestDay.hourly_production,
        '🌟 Najlepszy Dzień'
    );

    // Worst day
    document.getElementById('worstDayDate').textContent = worstDay.date;
    document.getElementById('worstDaySelfConsumption').textContent =
        `${(worstDay.self_consumption_rate * 100).toFixed(1)}%`;
    document.getElementById('worstDayBalance').textContent =
        `${worstDay.net_balance.toFixed(1)} kWh`;

    createDayChart(
        'worstDayChart',
        worstDay.hourly_consumption,
        worstDay.hourly_production,
        '⚠️ Najgorszy Dzień'
    );
}

function renderInsights(typicalDaysInsights, kpiInsights) {
    console.log('💡 Rendering insights...');

    const container = document.getElementById('insightsContainer');
    container.innerHTML = '';

    const allInsights = [];

    // Add typical days insights
    if (typicalDaysInsights && Array.isArray(typicalDaysInsights)) {
        allInsights.push(...typicalDaysInsights.map(insight => ({
            text: insight,
            type: detectInsightType(insight)
        })));
    }

    // Add KPI insights
    if (kpiInsights && Array.isArray(kpiInsights)) {
        allInsights.push(...kpiInsights.map(insight => ({
            text: insight,
            type: detectInsightType(insight)
        })));
    }

    if (allInsights.length === 0) {
        container.innerHTML = `
            <div class="insight-card neutral">
                <span class="insight-icon">ℹ️</span>
                <span class="insight-text">Brak dostępnych insights dla tego wariantu.</span>
            </div>
        `;
        return;
    }

    allInsights.forEach(insight => {
        const card = document.createElement('div');
        card.className = `insight-card ${insight.type}`;

        const icon = getInsightIcon(insight.type);

        card.innerHTML = `
            <span class="insight-icon">${icon}</span>
            <span class="insight-text">${insight.text}</span>
        `;

        container.appendChild(card);
    });
}

function detectInsightType(text) {
    const lowerText = text.toLowerCase();

    if (lowerText.includes('świetnie') || lowerText.includes('dobrze') ||
        lowerText.includes('wysoka') || lowerText.includes('efektywn')) {
        return 'positive';
    }

    if (lowerText.includes('niska') || lowerText.includes('słaba') ||
        lowerText.includes('rozważ') || lowerText.includes('można')) {
        return 'warning';
    }

    if (lowerText.includes('różnica') || lowerText.includes('weekend') ||
        lowerText.includes('sezon')) {
        return 'info';
    }

    return 'neutral';
}

function getInsightIcon(type) {
    const icons = {
        'positive': '✅',
        'warning': '⚠️',
        'info': 'ℹ️',
        'neutral': '💭'
    };
    return icons[type] || '💭';
}

function createDayChart(canvasId, consumption, production, title) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        console.warn(`⚠️ Canvas ${canvasId} not found`);
        return;
    }

    // Destroy existing chart if it exists
    if (charts[canvasId]) {
        charts[canvasId].destroy();
    }

    const hours = Array.from({length: 24}, (_, i) => `${i}:00`);

    charts[canvasId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: hours,
            datasets: [
                {
                    label: 'Zużycie',
                    data: consumption,
                    borderColor: '#f44336',
                    backgroundColor: 'rgba(244, 67, 54, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'Produkcja PV',
                    data: production,
                    borderColor: '#4caf50',
                    backgroundColor: 'rgba(76, 175, 80, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                title: {
                    display: false
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            label += context.parsed.y.toFixed(2) + ' kWh';
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: 'Godzina'
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                },
                y: {
                    display: true,
                    title: {
                        display: true,
                        text: 'Energia (kWh)'
                    },
                    beginAtZero: true
                }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

function updateStatus(icon, text, type = '') {
    const statusCard = document.getElementById('loadingStatus');
    const statusIcon = statusCard.querySelector('.status-icon');
    const statusText = statusCard.querySelector('.status-text');

    statusIcon.textContent = icon;
    statusText.textContent = text;

    statusCard.className = `status-card ${type}`;
}

function showError(message) {
    updateStatus('❌', message, 'error');

    // Show error in insights section
    const container = document.getElementById('insightsContainer');
    container.innerHTML = `
        <div class="insight-card warning">
            <span class="insight-icon">⚠️</span>
            <span class="insight-text">${message}</span>
        </div>
    `;
}
