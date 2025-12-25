/**
 * Monte Carlo Simulation Frontend Module
 * Handles UI interactions and API calls for Monte Carlo risk analysis
 * Version: 1.1.0 - Added progress indicator
 */

// API endpoint - uses nginx proxy
const ECONOMICS_API_URL = '/api/economics';

// Chart instance for histogram
let mcHistogramChart = null;

// Progress animation state
let mcProgressInterval = null;

// Store last simulation data for export
let lastMcSimulationData = null;
let lastMcSimulationResult = null;

/**
 * Start animated progress indicator
 * Estimates completion based on number of simulations
 */
function startProgressAnimation(nSimulations, statusEl, runButton) {
    // Estimate time based on simulation count (approximately 1ms per 100 simulations)
    const estimatedTimeMs = Math.max(500, nSimulations * 0.02);
    const startTime = Date.now();
    let progress = 0;

    // Update status with progress bar
    const updateProgress = () => {
        const elapsed = Date.now() - startTime;
        // Progress accelerates initially, then slows down (never reaches 100% before response)
        progress = Math.min(95, 100 * (1 - Math.exp(-elapsed / (estimatedTimeMs * 0.5))));

        const progressBar = '█'.repeat(Math.floor(progress / 5)) + '░'.repeat(20 - Math.floor(progress / 5));
        statusEl.innerHTML = `
            <div style="display:flex;align-items:center;gap:12px">
                <span style="font-family:monospace;color:#1565c0">[${progressBar}]</span>
                <span>${progress.toFixed(0)}%</span>
                <span style="color:#888">~${Math.round(elapsed / 1000)}s</span>
            </div>
        `;

        // Update button text with percentage
        runButton.textContent = `⏳ ${progress.toFixed(0)}% - Symulacja...`;
    };

    // Start interval
    mcProgressInterval = setInterval(updateProgress, 100);
    updateProgress(); // Initial call

    return {
        stop: () => {
            if (mcProgressInterval) {
                clearInterval(mcProgressInterval);
                mcProgressInterval = null;
            }
        }
    };
}

/**
 * Main function to run Monte Carlo simulation
 */
async function runMonteCarlo() {
    const runButton = document.getElementById('mcRunButton');
    const statusEl = document.getElementById('mcStatus');
    const resultsEl = document.getElementById('mcResults');
    const noDataEl = document.getElementById('mcNoData');

    // Check if we have economics data
    const economicsData = getEconomicsDataForMonteCarlo();
    if (!economicsData) {
        statusEl.innerHTML = `
            <span style="color:#e74c3c">
                ❌ Brak danych ekonomicznych.<br>
                <small>Wykonaj najpierw analizę w module <b>Konfiguracja</b> i upewnij się, że masz wybraną moc instalacji.</small>
            </span>`;
        return;
    }

    // Validate economics data has required fields
    const variant = economicsData.variant || {};
    if (!variant.capacity || variant.capacity <= 0) {
        statusEl.innerHTML = `<span style="color:#e74c3c">❌ Brak mocy instalacji (capacity=0). Wybierz wariant w module Konfiguracja.</span>`;
        return;
    }
    if ((!variant.production || variant.production <= 0) && (!variant.self_consumed || variant.self_consumed <= 0)) {
        statusEl.innerHTML = `
            <span style="color:#e74c3c">
                ❌ Brak danych produkcji (production=0, self_consumed=0).<br>
                <small>Upewnij się, że analiza PV została wykonana poprawnie.</small>
            </span>`;
        console.error('🎲 MC: Invalid variant data:', variant);
        return;
    }

    // Get simulation parameters
    const nSimulations = parseInt(document.getElementById('mcSimulations').value);
    const preset = document.getElementById('mcPreset').value;
    const priceUncertainty = parseFloat(document.getElementById('mcPriceUncertainty').value);
    const productionUncertainty = parseFloat(document.getElementById('mcProductionUncertainty').value);

    // Disable button and start progress animation
    runButton.disabled = true;
    const progressAnim = startProgressAnimation(nSimulations, statusEl, runButton);

    try {
        console.log('🎲 MC: Starting simulation with', nSimulations, 'iterations');
        console.log('🎲 MC: Economics data:', economicsData);

        // Build request with bankable defaults
        // Sources: NREL P50/P90, SolarGIS, FfE 2024, IMF volatility study
        const request = {
            n_simulations: nSimulations,
            electricity_price_uncertainty_pct: priceUncertainty,  // Default: 12% (bankable)
            production_uncertainty_pct: productionUncertainty,    // Default: 8% (NREL standard)
            capex_uncertainty_pct: 8.0,    // Post-EPC bid: 8% (bankable)
            inflation_uncertainty_pct: 1.5, // NBP target ±1.5pp (bankable)
            use_default_correlations: true,
            base_economics: economicsData,
            return_distributions: true  // Return full distributions for Excel export
        };

        // Call API
        const response = await fetch(`${ECONOMICS_API_URL}/monte-carlo/quick`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(request),
        });

        // Stop progress animation
        progressAnim.stop();

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        const result = await response.json();

        // Store data for export
        lastMcSimulationData = {
            request: request,
            economicsData: economicsData,
            settings: {
                nSimulations: nSimulations,
                preset: preset,
                priceUncertainty: priceUncertainty,
                productionUncertainty: productionUncertainty
            }
        };
        lastMcSimulationResult = result;

        // Display base parameters panel
        displayBaseParameters(economicsData);

        // Display results
        displayMonteCarloResults(result);

        // Show results, hide no-data message
        resultsEl.style.display = 'block';
        noDataEl.style.display = 'none';

        // Show completion status with green checkmark
        statusEl.innerHTML = `
            <span style="color:#27ae60;font-weight:600">
                ✓ Symulacja zakończona w ${result.computation_time_ms.toFixed(0)} ms
                (${nSimulations.toLocaleString()} scenariuszy)
            </span>
        `;

    } catch (error) {
        progressAnim.stop();
        console.error('Monte Carlo error:', error);
        statusEl.innerHTML = `<span style="color:#e74c3c">✗ Błąd: ${error.message}</span>`;
    } finally {
        runButton.disabled = false;
        runButton.textContent = '🎲 URUCHOM SYMULACJĘ MONTE CARLO';
    }
}

/**
 * Get economics data for Monte Carlo from global state
 * Tries multiple sources: economics.js globals, localStorage, UI values
 */
function getEconomicsDataForMonteCarlo() {
    console.log('🎲 MC: Looking for economics data...');

    // Source 1: Try to get from economics.js global variables (same script scope)
    // These are defined in economics.js: economicData, variants, currentVariant, systemSettings
    if (typeof economicData !== 'undefined' && economicData &&
        typeof variants !== 'undefined' && variants &&
        typeof currentVariant !== 'undefined' && currentVariant) {

        const variant = variants[currentVariant];
        if (variant) {
            console.log('🎲 MC: Using economics.js global data for variant:', currentVariant);
            const data = buildEconomicsDataFromGlobals(variant, economicData, systemSettings);
            if (data) return data;
        }
    }

    // Source 2: Try window.currentEconomicsData (explicit export)
    if (window.currentEconomicsData) {
        console.log('🎲 MC: Using window.currentEconomicsData');
        return window.currentEconomicsData;
    }

    // Source 3: Try localStorage (persisted from previous session)
    try {
        const storedVariants = localStorage.getItem('analysisResults');
        const storedEconomic = localStorage.getItem('economicData');

        if (storedVariants && storedEconomic) {
            const parsedResults = JSON.parse(storedVariants);
            const parsedEconomic = JSON.parse(storedEconomic);

            // Try to get key_variants from localStorage
            if (parsedResults.key_variants) {
                const variantKey = localStorage.getItem('currentVariant') || 'B';
                const variant = parsedResults.key_variants[variantKey];
                if (variant) {
                    console.log('🎲 MC: Using localStorage data for variant:', variantKey);
                    return buildEconomicsDataFromStoredVariant(variant, parsedEconomic);
                }
            }
        }
    } catch (e) {
        console.warn('🎲 MC: Could not read from localStorage:', e);
    }

    // Source 4: Try to construct from current UI values
    const capacityEl = document.getElementById('selectedVariantCapacity');
    let capacity = 0;

    if (capacityEl && capacityEl.textContent) {
        const match = capacityEl.textContent.match(/([\d\s,\.]+)/);
        if (match) {
            capacity = parseFloat(match[1].replace(/[\s,]/g, '').replace(',', '.'));
        }
    }

    // Fallback: try dataInfo element
    if (!capacity) {
        const dataInfoEl = document.getElementById('dataInfo');
        if (dataInfoEl && dataInfoEl.textContent) {
            const match = dataInfoEl.textContent.match(/(\d+(?:[\s,]\d+)*(?:[.,]\d+)?)\s*kWp/i);
            if (match) {
                capacity = parseFloat(match[1].replace(/[\s,]/g, '').replace(',', '.'));
            }
        }
    }

    if (capacity > 0) {
        console.log('🎲 MC: Building data from UI, capacity:', capacity, 'kWp');
        return buildEconomicsDataFromUI(capacity);
    }

    console.warn('🎲 MC: No economics data found');
    return null;
}

/**
 * Build Monte Carlo economics data from economics.js global variables
 * CRITICAL: Must match exactly how economics.js calculates NPV/IRR
 */
function buildEconomicsDataFromGlobals(variant, economicData, systemSettings) {
    try {
        // CRITICAL: Validate variant has required data
        console.log('🎲 MC: buildEconomicsDataFromGlobals - variant:', JSON.stringify(variant, null, 2));
        console.log('🎲 MC: buildEconomicsDataFromGlobals - economicData:', JSON.stringify(economicData, null, 2));
        console.log('🎲 MC: buildEconomicsDataFromGlobals - systemSettings:', JSON.stringify(systemSettings, null, 2));

        const capacity = variant.capacity || 0;
        const production = variant.production || 0;
        const selfConsumed = variant.self_consumed || 0;

        // Validate minimum required data
        if (capacity <= 0) {
            console.error('🎲 MC: Invalid capacity:', capacity);
            return null;
        }
        if (production <= 0 && selfConsumed <= 0) {
            console.error('🎲 MC: No production data - production:', production, 'self_consumed:', selfConsumed);
            return null;
        }

        // === ENERGY PRICE (with capacity fee!) ===
        // Must match economics.js calculateTotalEnergyPrice() + calculateCapacityFeeForConsumption()
        let energyPrice = 450; // default PLN/MWh
        let capacityFee = 219; // default PLN/MWh

        // Priority 1: Use economicData.metrics.total_energy_price (already includes capacity fee)
        if (economicData?.metrics?.total_energy_price > 0) {
            energyPrice = economicData.metrics.total_energy_price;
            console.log('🎲 MC: Using total_energy_price from economicData.metrics:', energyPrice, 'PLN/MWh');
        }
        // Priority 2: Use economicData.parameters.energy_price (from backend params)
        else if (economicData?.parameters?.energy_price > 0) {
            energyPrice = economicData.parameters.energy_price;
            console.log('🎲 MC: Using energy_price from economicData.parameters:', energyPrice, 'PLN/MWh');
        }
        // Priority 3: Calculate from systemSettings (matching economics.js)
        else if (systemSettings) {
            const ea = systemSettings.energyActive || parseFloat(document.getElementById('energyActive')?.value) || 550;
            const dist = systemSettings.distribution || parseFloat(document.getElementById('distribution')?.value) || 200;
            const qf = systemSettings.qualityFee || parseFloat(document.getElementById('qualityFee')?.value) || 10;
            const oze = systemSettings.ozeFee || parseFloat(document.getElementById('ozeFee')?.value) || 7;
            const cogen = systemSettings.cogenerationFee || parseFloat(document.getElementById('cogenerationFee')?.value) || 10;
            const excise = systemSettings.exciseTax || parseFloat(document.getElementById('exciseTax')?.value) || 5;
            capacityFee = systemSettings.capacityFee || parseFloat(document.getElementById('capacityFee')?.value) || 219;

            // CRITICAL: Include capacity fee in total price (like economics.js does)
            energyPrice = ea + dist + qf + oze + cogen + excise + capacityFee;
            console.log('🎲 MC: Calculated energy price from settings:',
                `${ea}+${dist}+${qf}+${oze}+${cogen}+${excise}+${capacityFee}=${energyPrice}`, 'PLN/MWh');
        }

        // === INVESTMENT COST (tiered CAPEX) ===
        // Must match economics.js getCapexForCapacity()
        let investmentCost = 3500;

        // Priority 1: Use economicData.parameters.investment_cost (already calculated by economics.js)
        if (economicData?.parameters?.investment_cost > 0) {
            investmentCost = economicData.parameters.investment_cost;
            console.log('🎲 MC: Using investment_cost from economicData.parameters:', investmentCost, 'PLN/kWp');
        }
        // Priority 2: Calculate from total investment
        else if (economicData?.investment > 0 && capacity > 0) {
            investmentCost = economicData.investment / capacity;
            console.log('🎲 MC: Calculated investment_cost from total investment:', investmentCost, 'PLN/kWp');
        }
        // Priority 3: Use tiered pricing from systemSettings (matching getCapexForCapacity)
        else if (systemSettings?.capexTiers && systemSettings.capexTiers.length > 0 && capacity > 0) {
            // Find correct tier for capacity (matching getCapexForCapacity logic)
            const tiers = systemSettings.capexTiers;
            for (let i = 0; i < tiers.length; i++) {
                if (capacity <= tiers[i].maxCapacity || i === tiers.length - 1) {
                    investmentCost = tiers[i].costPerKwp;
                    break;
                }
            }
            console.log('🎲 MC: Using tiered CAPEX for', capacity, 'kWp:', investmentCost, 'PLN/kWp');
        }
        // Priority 4: UI input fallback
        else {
            investmentCost = parseFloat(document.getElementById('investmentCost')?.value) || 3500;
            console.log('🎲 MC: Using investmentCost from UI:', investmentCost, 'PLN/kWp');
        }

        // === OTHER PARAMETERS (match economics.js exactly) ===
        // Discount rate: economics.js uses window.economicsSettings.discountRate
        const discountRate = window.economicsSettings?.discountRate || 0.07;

        // Degradation rate: economics.js uses params.degradation_rate (from systemSettings as %)
        const degradationRate = (systemSettings?.degradationRate || 0.5) / 100;

        // OPEX per kWp
        const opexPerKwp = systemSettings?.opexPerKwp || parseFloat(document.getElementById('opexPerKwp')?.value) || 15;

        // Analysis period
        const analysisPeriod = systemSettings?.analysisPeriod || parseFloat(document.getElementById('analysisPeriod')?.value) || 25;

        // Inflation rate (only if useInflation is enabled)
        const useInflation = window.economicsSettings?.useInflation || false;
        const inflationRate = useInflation ? (window.economicsSettings?.inflationRate || 0.025) : 0;

        console.log('🎲 MC: Final parameters:', {
            energy_price: energyPrice,
            investment_cost: investmentCost,
            discount_rate: discountRate,
            degradation_rate: degradationRate,
            opex_per_kwp: opexPerKwp,
            analysis_period: analysisPeriod,
            inflation_rate: inflationRate
        });

        return {
            variant: {
                capacity: variant.capacity || 0,
                production: variant.production || 0,
                self_consumed: variant.self_consumed || variant.autoconsumption || 0,
                exported: variant.exported || variant.grid_export || 0,
                auto_consumption_pct: variant.auto_consumption_pct || variant.autoconsumption_pct || 50,
                coverage_pct: variant.coverage_pct || 30,
            },
            parameters: {
                energy_price: energyPrice,
                feed_in_tariff: 0,
                investment_cost: investmentCost,
                export_mode: 'zero',
                discount_rate: discountRate,
                degradation_rate: degradationRate,
                opex_per_kwp: opexPerKwp,
                analysis_period: analysisPeriod,
                inflation_rate: inflationRate,
            }
        };
    } catch (e) {
        console.error('🎲 MC: Error building data from globals:', e);
        return null;
    }
}

/**
 * Build Monte Carlo economics data from localStorage variant
 * CRITICAL: Must include capacity fee and match economics.js
 */
function buildEconomicsDataFromStoredVariant(variant, economicData) {
    try {
        // Get energy price - prefer total_energy_price which includes capacity fee
        let energyPrice = economicData?.metrics?.total_energy_price ||
                          economicData?.parameters?.energy_price ||
                          economicData?.energy_price || 450;

        // If energy price seems too low (missing capacity fee), add it
        if (energyPrice < 600) {
            const capacityFee = parseFloat(document.getElementById('capacityFee')?.value) || 219;
            energyPrice += capacityFee;
            console.log('🎲 MC: Added capacity fee to energy price:', energyPrice, 'PLN/MWh');
        }

        // Get investment cost per kWp
        let investmentCost = 3500;
        if (economicData?.parameters?.investment_cost > 0) {
            investmentCost = economicData.parameters.investment_cost;
        } else if (economicData?.investment && variant.capacity) {
            investmentCost = economicData.investment / variant.capacity;
        }

        // Get discount rate from window.economicsSettings (where economics.js stores it)
        const discountRate = window.economicsSettings?.discountRate || economicData?.discount_rate || 0.07;

        console.log('🎲 MC: buildEconomicsDataFromStoredVariant - energyPrice:', energyPrice,
                    'investmentCost:', investmentCost, 'discountRate:', discountRate);

        return {
            variant: {
                capacity: variant.capacity || 0,
                production: variant.production || 0,
                self_consumed: variant.self_consumed || variant.autoconsumption || 0,
                exported: variant.exported || variant.grid_export || 0,
                auto_consumption_pct: variant.auto_consumption_pct || variant.autoconsumption_pct || 50,
                coverage_pct: variant.coverage_pct || 30,
            },
            parameters: {
                energy_price: energyPrice,
                feed_in_tariff: 0,
                investment_cost: investmentCost,
                export_mode: 'zero',
                discount_rate: discountRate,
                degradation_rate: economicData?.degradation_rate || 0.005,
                opex_per_kwp: economicData?.opex_per_kwp || 15,
                analysis_period: economicData?.analysis_period || 25,
                inflation_rate: economicData?.inflation_rate || 0.025,
            }
        };
    } catch (e) {
        console.error('🎲 MC: Error building data from stored variant:', e);
        return null;
    }
}

/**
 * Build economics data structure from UI inputs
 * CRITICAL: Must include capacity fee (like economics.js)
 */
function buildEconomicsDataFromUI(capacity) {
    const energyActive = parseFloat(document.getElementById('energyActive')?.value || 550);
    const distribution = parseFloat(document.getElementById('distribution')?.value || 200);
    const qualityFee = parseFloat(document.getElementById('qualityFee')?.value || 10);
    const ozeFee = parseFloat(document.getElementById('ozeFee')?.value || 7);
    const cogenerationFee = parseFloat(document.getElementById('cogenerationFee')?.value || 10);
    const capacityFee = parseFloat(document.getElementById('capacityFee')?.value || 219);
    const exciseTax = parseFloat(document.getElementById('exciseTax')?.value || 5);

    // CRITICAL: Include capacity fee in total price (like economics.js totalEnergyPriceWithCapacity)
    const totalEnergyPrice = energyActive + distribution + qualityFee + ozeFee + cogenerationFee + exciseTax + capacityFee;
    const investmentCost = parseFloat(document.getElementById('investmentCost')?.value || 3500);
    const opexPerKwp = parseFloat(document.getElementById('opexPerKwp')?.value || 15);
    const degradationRate = parseFloat(document.getElementById('degradationRate')?.value || 0.5) / 100;
    const analysisPeriod = parseInt(document.getElementById('analysisPeriod')?.value || 25);

    // Get discount rate from window.economicsSettings
    const discountRate = window.economicsSettings?.discountRate || 0.07;

    console.log('🎲 MC: buildEconomicsDataFromUI - totalEnergyPrice:', totalEnergyPrice,
                '(includes capacityFee:', capacityFee, ')');

    // Estimate production (1000 kWh/kWp typical for Poland)
    const annualProduction = capacity * 1000;
    const selfConsumed = annualProduction * 0.7;  // 70% self-consumption assumption

    return {
        variant: {
            capacity: capacity,
            production: annualProduction,
            self_consumed: selfConsumed,
            exported: annualProduction - selfConsumed,
            auto_consumption_pct: 70,
            coverage_pct: 50,
        },
        parameters: {
            energy_price: totalEnergyPrice,
            feed_in_tariff: 0,
            investment_cost: investmentCost,
            export_mode: 'zero',
            discount_rate: discountRate,
            degradation_rate: degradationRate,
            opex_per_kwp: opexPerKwp,
            analysis_period: analysisPeriod,
            inflation_rate: 0.025,
        }
    };
}

/**
 * Display Monte Carlo simulation results
 */
function displayMonteCarloResults(result) {
    // Key metrics
    const probPositive = (result.risk_metrics.probability_positive * 100).toFixed(1);
    document.getElementById('mcProbPositive').textContent = probPositive;

    // NPV percentiles
    const npvP10 = result.npv_percentiles.p10 / 1000000;
    const npvP50 = result.npv_percentiles.p50 / 1000000;
    const npvP90 = result.npv_percentiles.p90 / 1000000;

    document.getElementById('mcNpvP10').textContent = npvP10.toFixed(2);
    document.getElementById('mcNpvMedian').textContent = npvP50.toFixed(2);
    document.getElementById('mcNpvP90').textContent = npvP90.toFixed(2);

    // VaR
    const var95 = result.risk_metrics.var_95 / 1000000;
    document.getElementById('mcVar95').textContent = var95.toFixed(2);

    // IRR percentiles (if available)
    if (result.irr_percentiles) {
        document.getElementById('mcIrrP10').textContent = (result.irr_percentiles.p10 * 100).toFixed(1) + '%';
        document.getElementById('mcIrrMedian').textContent = (result.irr_percentiles.p50 * 100).toFixed(1) + '%';
        document.getElementById('mcIrrP90').textContent = (result.irr_percentiles.p90 * 100).toFixed(1) + '%';
    }

    // Payback percentiles (if available)
    if (result.payback_percentiles) {
        document.getElementById('mcPaybackP10').textContent = result.payback_percentiles.p10.toFixed(1);
        document.getElementById('mcPaybackMedian').textContent = result.payback_percentiles.p50.toFixed(1);
        document.getElementById('mcPaybackP90').textContent = result.payback_percentiles.p90.toFixed(1);
    }

    // Computation info
    document.getElementById('mcSimCount').textContent = result.n_simulations.toLocaleString();
    document.getElementById('mcCompTime').textContent = result.computation_time_ms.toFixed(0);

    // Insights
    const insightsList = document.getElementById('mcInsights');
    insightsList.innerHTML = '';
    if (result.insights && result.insights.length > 0) {
        result.insights.forEach(insight => {
            const li = document.createElement('li');
            li.textContent = insight;
            insightsList.appendChild(li);
        });
    } else {
        const li = document.createElement('li');
        li.textContent = 'Brak dodatkowych wniosków';
        insightsList.appendChild(li);
    }

    // Scenario comparison table
    if (result.scenario_pessimistic) {
        document.getElementById('mcScenP10Npv').textContent = (result.scenario_pessimistic.npv / 1000000).toFixed(2);
        document.getElementById('mcScenP10Irr').textContent = result.scenario_pessimistic.irr ?
            (result.scenario_pessimistic.irr * 100).toFixed(1) : '-';
        document.getElementById('mcScenP10Payback').textContent = result.scenario_pessimistic.payback ?
            result.scenario_pessimistic.payback.toFixed(1) : '-';
    }

    if (result.scenario_base) {
        document.getElementById('mcScenBaseNpv').textContent = (result.scenario_base.npv / 1000000).toFixed(2);
        document.getElementById('mcScenBaseIrr').textContent = result.scenario_base.irr ?
            (result.scenario_base.irr * 100).toFixed(1) : '-';
        document.getElementById('mcScenBasePayback').textContent = result.scenario_base.payback ?
            result.scenario_base.payback.toFixed(1) : '-';
    }

    if (result.scenario_optimistic) {
        document.getElementById('mcScenP90Npv').textContent = (result.scenario_optimistic.npv / 1000000).toFixed(2);
        document.getElementById('mcScenP90Irr').textContent = result.scenario_optimistic.irr ?
            (result.scenario_optimistic.irr * 100).toFixed(1) : '-';
        document.getElementById('mcScenP90Payback').textContent = result.scenario_optimistic.payback ?
            result.scenario_optimistic.payback.toFixed(1) : '-';
    }

    // Draw histogram
    drawNpvHistogram(result.npv_histogram, result.risk_metrics);
}

/**
 * Draw NPV histogram chart
 */
function drawNpvHistogram(histogramData, riskMetrics) {
    const ctx = document.getElementById('mcNpvHistogram');
    if (!ctx) return;

    // Destroy existing chart
    if (mcHistogramChart) {
        mcHistogramChart.destroy();
    }

    // Prepare data
    const labels = histogramData.bin_centers.map(v => (v / 1000000).toFixed(2));
    const data = histogramData.counts;

    // Color bars based on NPV value (green for positive, red for negative)
    const colors = histogramData.bin_centers.map(v =>
        v >= 0 ? 'rgba(46, 125, 50, 0.7)' : 'rgba(198, 40, 40, 0.7)'
    );
    const borderColors = histogramData.bin_centers.map(v =>
        v >= 0 ? 'rgba(46, 125, 50, 1)' : 'rgba(198, 40, 40, 1)'
    );

    mcHistogramChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Liczba scenariuszy',
                data: data,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 1,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false,
                },
                title: {
                    display: false,
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.raw} scenariuszy`;
                        },
                        title: function(context) {
                            return `NPV: ${context[0].label} mln PLN`;
                        }
                    }
                },
                annotation: {
                    annotations: {
                        zeroLine: {
                            type: 'line',
                            xMin: findClosestIndex(histogramData.bin_centers, 0),
                            xMax: findClosestIndex(histogramData.bin_centers, 0),
                            borderColor: 'rgba(0, 0, 0, 0.5)',
                            borderWidth: 2,
                            borderDash: [5, 5],
                            label: {
                                content: 'NPV = 0',
                                enabled: true,
                                position: 'start',
                            }
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'NPV [mln PLN]',
                        font: { size: 11 }
                    },
                    ticks: {
                        maxTicksLimit: 10,
                        font: { size: 10 }
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Liczba scenariuszy',
                        font: { size: 11 }
                    },
                    beginAtZero: true,
                    ticks: {
                        font: { size: 10 }
                    }
                }
            }
        }
    });
}

/**
 * Find closest index in array to target value
 */
function findClosestIndex(arr, target) {
    let minDiff = Infinity;
    let closestIndex = 0;

    arr.forEach((val, idx) => {
        const diff = Math.abs(val - target);
        if (diff < minDiff) {
            minDiff = diff;
            closestIndex = idx;
        }
    });

    return closestIndex;
}

/**
 * Display base scenario parameters in the panel
 */
function displayBaseParameters(economicsData) {
    if (!economicsData) return;

    const variant = economicsData.variant || {};
    const params = economicsData.parameters || {};

    // Format number with Polish locale
    const formatNum = (val, decimals = 0) => {
        if (val === null || val === undefined || isNaN(val)) return '-';
        return val.toLocaleString('pl-PL', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    };

    // Variant data
    const capacity = variant.capacity || 0;
    const production = (variant.production || 0) / 1000; // kWh -> MWh
    const selfConsumed = (variant.self_consumed || 0) / 1000; // kWh -> MWh
    const autoPct = production > 0 ? (selfConsumed / production * 100) : 0;

    document.getElementById('mcBaseCapacity').textContent = formatNum(capacity);
    document.getElementById('mcBaseProduction').textContent = formatNum(production, 1);
    document.getElementById('mcBaseSelfConsumed').textContent = formatNum(selfConsumed, 1);
    document.getElementById('mcBaseAutoPct').textContent = formatNum(autoPct, 1);

    // Economic parameters
    const energyPrice = params.energy_price || 0;
    const investmentCost = params.investment_cost || 0;
    const totalCapex = (capacity * investmentCost) / 1000000; // PLN -> mln PLN
    const discountRate = (params.discount_rate || 0) * 100;

    document.getElementById('mcBaseEnergyPrice').textContent = formatNum(energyPrice);
    document.getElementById('mcBaseCapex').textContent = formatNum(investmentCost);
    document.getElementById('mcBaseTotalCapex').textContent = formatNum(totalCapex, 2);
    document.getElementById('mcBaseDiscount').textContent = formatNum(discountRate, 1);

    // Additional params
    const opex = params.opex_per_kwp || 0;
    const degradation = (params.degradation_rate || 0) * 100;
    const period = params.analysis_period || 25;
    const inflation = (params.inflation_rate || 0) * 100;

    document.getElementById('mcBaseOpex').textContent = formatNum(opex);
    document.getElementById('mcBaseDegradation').textContent = formatNum(degradation, 2);
    document.getElementById('mcBasePeriod').textContent = formatNum(period);
    document.getElementById('mcBaseInflation').textContent = formatNum(inflation, 1);

    console.log('🎲 MC: Base parameters displayed:', {
        capacity, production, selfConsumed, autoPct,
        energyPrice, investmentCost, totalCapex, discountRate,
        opex, degradation, period, inflation
    });
}

/**
 * Export Monte Carlo results to Excel
 * Uses numeric values (not strings) for proper Excel handling
 * Excel will use system locale (Polish: comma as decimal separator)
 */
function exportMonteCarloToExcel() {
    if (!lastMcSimulationData || !lastMcSimulationResult) {
        alert('Brak danych do eksportu. Najpierw uruchom symulację Monte Carlo.');
        return;
    }

    const data = lastMcSimulationData;
    const result = lastMcSimulationResult;
    const variant = data.economicsData.variant || {};
    const params = data.economicsData.parameters || {};

    // Create workbook
    const wb = XLSX.utils.book_new();

    // Helper: round to N decimal places (returns number, not string)
    const round = (val, decimals = 2) => {
        if (val === null || val === undefined || isNaN(val)) return null;
        return Math.round(val * Math.pow(10, decimals)) / Math.pow(10, decimals);
    };

    // ========== SHEET 1: Summary ==========
    const summaryData = [
        ['ANALIZA MONTE CARLO - RAPORT'],
        ['Data eksportu:', new Date().toLocaleString('pl-PL')],
        [''],
        ['=== PARAMETRY SCENARIUSZA BAZOWEGO ==='],
        [''],
        ['DANE INSTALACJI'],
        ['Moc instalacji [kWp]', round(variant.capacity || 0, 2)],
        ['Roczna produkcja [MWh]', round((variant.production || 0) / 1000, 1)],
        ['Autokonsumpcja [MWh]', round((variant.self_consumed || 0) / 1000, 1)],
        ['% autokonsumpcji', variant.production > 0 ? round((variant.self_consumed / variant.production) * 100, 1) : null],
        [''],
        ['PARAMETRY EKONOMICZNE'],
        ['Cena energii (z opł. mocową) [PLN/MWh]', round(params.energy_price || 0, 2)],
        ['CAPEX jednostkowy [PLN/kWp]', round(params.investment_cost || 0, 2)],
        ['CAPEX całkowity [PLN]', round((variant.capacity || 0) * (params.investment_cost || 0), 0)],
        ['Stopa dyskontowa [%]', round((params.discount_rate || 0) * 100, 1)],
        ['OPEX [PLN/kWp/rok]', round(params.opex_per_kwp || 0, 2)],
        ['Degradacja [%/rok]', round((params.degradation_rate || 0) * 100, 2)],
        ['Okres analizy [lat]', params.analysis_period || 25],
        ['Inflacja [%]', round((params.inflation_rate || 0) * 100, 1)],
        [''],
        ['USTAWIENIA SYMULACJI'],
        ['Liczba symulacji', result.n_simulations],
        ['Czas obliczeń [ms]', round(result.computation_time_ms, 0)],
        ['Niepewność ceny energii [%]', data.settings.priceUncertainty],
        ['Niepewność produkcji [%]', data.settings.productionUncertainty],
        ['Profil ryzyka', data.settings.preset],
        [''],
        ['=== WYNIKI SYMULACJI ==='],
        [''],
        ['GŁÓWNE METRYKI'],
        ['Prawdopodobieństwo zysku (NPV>0) [%]', round(result.risk_metrics.probability_positive * 100, 2)],
        ['Wartość oczekiwana NPV [PLN]', round(result.risk_metrics.expected_value, 0)],
        ['Odchylenie standardowe NPV [PLN]', round(result.risk_metrics.standard_deviation, 0)],
        ['Współczynnik zmienności', round(result.risk_metrics.coefficient_of_variation, 4)],
        [''],
        ['PERCENTYLE NPV [PLN]'],
        ['P5 (pesymistyczny)', round(result.npv_percentiles.p5, 0)],
        ['P10', round(result.npv_percentiles.p10, 0)],
        ['P25 (Q1)', round(result.npv_percentiles.p25, 0)],
        ['P50 (mediana)', round(result.npv_percentiles.p50, 0)],
        ['P75 (Q3)', round(result.npv_percentiles.p75, 0)],
        ['P90', round(result.npv_percentiles.p90, 0)],
        ['P95 (optymistyczny)', round(result.npv_percentiles.p95, 0)],
        [''],
        ['METRYKI RYZYKA'],
        ['VaR 95% (Value at Risk) [PLN]', round(result.risk_metrics.var_95, 0)],
        ['VaR 99% [PLN]', round(result.risk_metrics.var_99, 0)],
        ['CVaR 95% (Expected Shortfall) [PLN]', round(result.risk_metrics.cvar_95, 0)],
        ['Downside Risk [PLN]', round(result.risk_metrics.downside_risk, 0)],
    ];

    // Add IRR if available
    if (result.irr_percentiles) {
        summaryData.push(['']);
        summaryData.push(['PERCENTYLE IRR [%]']);
        summaryData.push(['P10', round(result.irr_percentiles.p10 * 100, 2)]);
        summaryData.push(['P50 (mediana)', round(result.irr_percentiles.p50 * 100, 2)]);
        summaryData.push(['P90', round(result.irr_percentiles.p90 * 100, 2)]);
        summaryData.push(['Średnie IRR [%]', result.irr_mean ? round(result.irr_mean * 100, 2) : null]);
        summaryData.push(['% symulacji z prawidłowym IRR', round(result.irr_valid_pct, 1)]);
    }

    // Add Payback if available
    if (result.payback_percentiles) {
        summaryData.push(['']);
        summaryData.push(['PERCENTYLE PAYBACK [lat]']);
        summaryData.push(['P10 (najszybszy)', round(result.payback_percentiles.p10, 2)]);
        summaryData.push(['P50 (mediana)', round(result.payback_percentiles.p50, 2)]);
        summaryData.push(['P90 (najwolniejszy)', round(result.payback_percentiles.p90, 2)]);
    }

    // Add insights
    if (result.insights && result.insights.length > 0) {
        summaryData.push(['']);
        summaryData.push(['=== WNIOSKI Z ANALIZY ===']);
        result.insights.forEach((insight, i) => {
            summaryData.push([`${i + 1}. ${insight}`]);
        });
    }

    const wsSummary = XLSX.utils.aoa_to_sheet(summaryData);
    wsSummary['!cols'] = [{ wch: 45 }, { wch: 25 }];
    XLSX.utils.book_append_sheet(wb, wsSummary, 'Podsumowanie');

    // ========== SHEET 2: Histogram data ==========
    const histogramData = [
        ['HISTOGRAM NPV'],
        [''],
        ['Przedział od [mln PLN]', 'Przedział do [mln PLN]', 'Środek [mln PLN]', 'Liczba scenariuszy', '% scenariuszy']
    ];

    const histogram = result.npv_histogram;
    const totalScenarios = histogram.counts.reduce((a, b) => a + b, 0);

    for (let i = 0; i < histogram.bin_centers.length; i++) {
        const binStart = i === 0 ? histogram.bins[0] : histogram.bins[i];
        const binEnd = histogram.bins[i + 1];
        const count = histogram.counts[i];
        const pct = count / totalScenarios * 100;

        histogramData.push([
            round(binStart / 1000000, 4),
            round(binEnd / 1000000, 4),
            round(histogram.bin_centers[i] / 1000000, 4),
            count,
            round(pct, 2)
        ]);
    }

    const wsHistogram = XLSX.utils.aoa_to_sheet(histogramData);
    wsHistogram['!cols'] = [{ wch: 20 }, { wch: 20 }, { wch: 18 }, { wch: 18 }, { wch: 15 }];
    XLSX.utils.book_append_sheet(wb, wsHistogram, 'Histogram NPV');

    // ========== SHEET 3: Scenarios comparison ==========
    const scenariosData = [
        ['PORÓWNANIE SCENARIUSZY'],
        [''],
        ['Scenariusz', 'NPV [PLN]', 'NPV [mln PLN]', 'IRR [%]', 'Payback [lat]', 'Interpretacja'],
        [
            'Pesymistyczny (P10)',
            round(result.scenario_pessimistic.npv, 0),
            round(result.scenario_pessimistic.npv / 1000000, 4),
            result.scenario_pessimistic.irr ? round(result.scenario_pessimistic.irr * 100, 2) : null,
            result.scenario_pessimistic.payback ? round(result.scenario_pessimistic.payback, 2) : null,
            '10% scenariuszy jest gorszych'
        ],
        [
            'Bazowy (Mediana)',
            round(result.scenario_base.npv, 0),
            round(result.scenario_base.npv / 1000000, 4),
            result.scenario_base.irr ? round(result.scenario_base.irr * 100, 2) : null,
            result.scenario_base.payback ? round(result.scenario_base.payback, 2) : null,
            'Najbardziej prawdopodobny wynik'
        ],
        [
            'Optymistyczny (P90)',
            round(result.scenario_optimistic.npv, 0),
            round(result.scenario_optimistic.npv / 1000000, 4),
            result.scenario_optimistic.irr ? round(result.scenario_optimistic.irr * 100, 2) : null,
            result.scenario_optimistic.payback ? round(result.scenario_optimistic.payback, 2) : null,
            '90% scenariuszy jest gorszych'
        ],
    ];

    const wsScenarios = XLSX.utils.aoa_to_sheet(scenariosData);
    wsScenarios['!cols'] = [{ wch: 22 }, { wch: 15 }, { wch: 15 }, { wch: 10 }, { wch: 12 }, { wch: 30 }];
    XLSX.utils.book_append_sheet(wb, wsScenarios, 'Scenariusze');

    // ========== SHEET 4: Uncertainty parameters ==========
    const uncertaintyData = [
        ['PARAMETRY NIEPEWNOŚCI (standardy branżowe)'],
        [''],
        ['Parametr', 'Wartość bazowa', 'Jednostka', 'Niepewność [%]', 'Zakres min', 'Zakres max', 'Źródło'],
        [
            'Cena energii',
            round(params.energy_price, 2),
            'PLN/MWh',
            data.settings.priceUncertainty,
            round(params.energy_price * 0.5, 0),
            round(params.energy_price * 1.8, 0),
            'FfE European Prices 2024, IMF volatility'
        ],
        [
            'Produkcja PV',
            100,
            '%',
            data.settings.productionUncertainty,
            75,
            125,
            'NREL P50/P90, SolarGIS'
        ],
        [
            'CAPEX',
            round(params.investment_cost, 2),
            'PLN/kWp',
            8,
            round(params.investment_cost * 0.7, 0),
            round(params.investment_cost * 1.4, 0),
            'Post-EPC bid standard'
        ],
        [
            'Inflacja',
            round((params.inflation_rate || 0.025) * 100, 2),
            '%',
            1.5,
            0,
            10,
            'NBP target ±1pp + margin'
        ],
        [''],
        ['KORELACJE'],
        ['Para parametrów', 'Korelacja', '', '', '', '', 'Uzasadnienie'],
        ['Cena energii - Inflacja', 0.5, '', '', '', '', 'Energia ~15% koszyka CPI'],
    ];

    const wsUncertainty = XLSX.utils.aoa_to_sheet(uncertaintyData);
    wsUncertainty['!cols'] = [{ wch: 22 }, { wch: 15 }, { wch: 12 }, { wch: 15 }, { wch: 12 }, { wch: 12 }, { wch: 35 }];
    XLSX.utils.book_append_sheet(wb, wsUncertainty, 'Niepewności');

    // ========== SHEET 5: All scenarios (full export) ==========
    if (result.npv_distribution && result.npv_distribution.length > 0) {
        const allScenariosData = [
            ['WSZYSTKIE SCENARIUSZE MONTE CARLO'],
            ['Liczba scenariuszy:', result.n_simulations],
            [''],
            [
                'Scenariusz #',
                'Cena energii [PLN/MWh]',
                'Wsp. produkcji',
                'CAPEX [PLN/kWp]',
                'Inflacja [%]',
                'NPV [PLN]',
                'NPV [mln PLN]',
                'IRR [%]',
                'Payback [lat]'
            ]
        ];

        const n = result.npv_distribution.length;
        const hasElecPrices = result.sampled_electricity_prices && result.sampled_electricity_prices.length === n;
        const hasProdFactors = result.sampled_production_factors && result.sampled_production_factors.length === n;
        const hasCapex = result.sampled_investment_costs && result.sampled_investment_costs.length === n;
        const hasInflation = result.sampled_inflation_rates && result.sampled_inflation_rates.length === n;
        const hasIrr = result.irr_distribution && result.irr_distribution.length === n;
        const hasPayback = result.payback_distribution && result.payback_distribution.length === n;

        console.log('🎲 MC: Exporting', n, 'scenarios to Excel (numeric format)');
        console.log('🎲 MC: Available data:', {
            hasElecPrices, hasProdFactors, hasCapex, hasInflation, hasIrr, hasPayback
        });

        for (let i = 0; i < n; i++) {
            const row = [
                i + 1,  // Scenario number (integer)
                hasElecPrices ? round(result.sampled_electricity_prices[i], 2) : null,
                hasProdFactors ? round(result.sampled_production_factors[i], 4) : null,
                hasCapex ? round(result.sampled_investment_costs[i], 2) : null,
                hasInflation ? round(result.sampled_inflation_rates[i] * 100, 2) : null,
                round(result.npv_distribution[i], 0),  // NPV in PLN (integer)
                round(result.npv_distribution[i] / 1000000, 4),  // NPV in mln PLN
                hasIrr && result.irr_distribution[i] !== null ? round(result.irr_distribution[i] * 100, 2) : null,
                hasPayback && result.payback_distribution[i] !== null ? round(result.payback_distribution[i], 2) : null
            ];
            allScenariosData.push(row);
        }

        const wsAllScenarios = XLSX.utils.aoa_to_sheet(allScenariosData);
        wsAllScenarios['!cols'] = [
            { wch: 12 },  // Scenario #
            { wch: 22 },  // Electricity price
            { wch: 16 },  // Production factor
            { wch: 18 },  // CAPEX
            { wch: 12 },  // Inflation
            { wch: 15 },  // NPV PLN
            { wch: 15 },  // NPV mln
            { wch: 10 },  // IRR
            { wch: 12 }   // Payback
        ];
        XLSX.utils.book_append_sheet(wb, wsAllScenarios, 'Wszystkie Scenariusze');

        console.log('🎲 MC: All scenarios sheet added with', n, 'rows');
    } else {
        console.warn('🎲 MC: No distribution data available for full export');
    }

    // Generate filename with date
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
    const timeStr = now.toTimeString().slice(0, 5).replace(':', '');
    const filename = `MonteCarlo_${Math.round(variant.capacity || 0)}kWp_${dateStr}_${timeStr}.xlsx`;

    // Save file
    XLSX.writeFile(wb, filename);

    console.log('🎲 MC: Excel exported:', filename);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Monte Carlo module initialized');

    // Check if we have data and show/hide no-data message
    const economicsData = getEconomicsDataForMonteCarlo();
    const noDataEl = document.getElementById('mcNoData');

    if (economicsData && noDataEl) {
        noDataEl.style.display = 'none';
    }
});

// Make function globally available
window.runMonteCarlo = runMonteCarlo;
window.exportMonteCarloToExcel = exportMonteCarloToExcel;
