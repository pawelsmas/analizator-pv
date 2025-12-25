/**
 * Profile Analysis Module v2.0
 *
 * Advanced hourly analysis of PV + Load profiles for optimal BESS sizing
 * with multi-objective optimization (NPV vs Cycles), Pareto frontier,
 * heatmap visualization, and variant comparison.
 */

// ============================================
// CROSS-MODULE NAVIGATION (global scope)
// ============================================

/**
 * Navigate to another module via parent shell
 * @param {string} moduleName - module name (bess, economics, config, etc.)
 */
function navigateToModule(moduleName) {
    console.log(`🔗 Profile: Navigating to module: ${moduleName}`);

    // Send navigation request to parent shell
    window.parent.postMessage({
        type: 'NAVIGATE_TO_MODULE',
        module: moduleName
    }, '*');
}

/**
 * Load shared BESS config from localStorage (set by BESS module)
 */
function loadSharedBessConfig() {
    try {
        const saved = localStorage.getItem('pv_shared_bess_config');
        if (saved) {
            const config = JSON.parse(saved);
            console.log('📥 Profile: Loaded shared BESS config:', config);

            // Update display
            const el = document.getElementById('sharedBessConfig');
            if (el && config.power_kw > 0 && config.energy_kwh > 0) {
                el.textContent = `BESS: ${config.power_kw} kW / ${config.energy_kwh} kWh`;
            }

            // Optionally pre-fill form fields
            if (config.power_kw > 0) {
                const powerInput = document.getElementById('bessPower');
                if (powerInput) powerInput.value = config.power_kw;
            }
            if (config.energy_kwh > 0) {
                const energyInput = document.getElementById('bessEnergy');
                if (energyInput) energyInput.value = config.energy_kwh;
            }
            if (config.pv_capacity_kwp > 0) {
                const pvInput = document.getElementById('pvCapacity');
                if (pvInput) pvInput.value = config.pv_capacity_kwp;
            }

            return config;
        }
    } catch (e) {
        console.warn('⚠️ Profile: Could not load shared BESS config:', e);
    }
    return null;
}

(function() {
    'use strict';

    // Module state
    let analysisResult = null;
    let hourlyChart = null;
    let monthlyChart = null;
    let quarterlyChart = null;
    let paretoChart = null;
    let cachedShellData = null;  // Cache data from shell for later use
    let cachedSettings = null;   // Cache settings for BESS degradation parameters

    // Initialize module
    function init() {
        console.log('📊 Profile Analysis module v2.0 initializing...');
        setupEventListeners();
        setupMessageListener();
        loadDataFromShell();

        // Load shared BESS config from localStorage (cross-module sharing)
        loadSharedBessConfig();
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

    function setupMessageListener() {
        window.addEventListener('message', (event) => {
            const { type, data } = event.data || {};

            if (type === 'ANALYSIS_RESULTS') {
                console.log('📥 Received ANALYSIS_RESULTS:', data);
                if (data) {
                    cachedShellData = data;
                    populateCurrentConfig(data);
                }
            } else if (type === 'SHARED_DATA_RESPONSE') {
                console.log('📥 Received SHARED_DATA_RESPONSE');
                if (data) {
                    cachedShellData = data;
                    populateCurrentConfig(data);
                }
            } else if (type === 'SETTINGS_UPDATED' && data) {
                console.log('📥 Received SETTINGS_UPDATED');
                applySettings(data);
            }
        });
    }

    function loadDataFromShell() {
        // Request analysis results from shell
        window.parent.postMessage({ type: 'REQUEST_ANALYSIS_RESULTS' }, '*');
        window.parent.postMessage({ type: 'REQUEST_SHARED_DATA' }, '*');
        window.parent.postMessage({ type: 'REQUEST_SETTINGS' }, '*');
    }

    /**
     * Send profile analysis results to shell for propagation to Economics module.
     * This includes BESS sizing recommendations and energy flow data.
     *
     * IMPORTANT: Uses recommended_* fields from backend which contain
     * hourly simulation data for Best NPV BESS - this is the SINGLE SOURCE OF TRUTH!
     */
    function notifyShellProfileAnalysis(result) {
        if (!result) return;

        // ============================================================
        // USE RECOMMENDED BESS DATA FROM BACKEND (Best NPV from Pareto)
        // This is the SINGLE SOURCE OF TRUTH for EKONOMIA and Excel!
        // ============================================================
        const hasRecommendedBess = result.recommended_bess_power_kw && result.recommended_bess_energy_kwh;

        if (hasRecommendedBess) {
            console.log('📊 Using RECOMMENDED BESS from backend (Best NPV):',
                        result.recommended_bess_power_kw, 'kW /',
                        result.recommended_bess_energy_kwh, 'kWh,',
                        result.recommended_bess_annual_discharge_mwh?.toFixed(2), 'MWh/year');
        } else {
            console.warn('⚠️ No recommended BESS data from backend - falling back to Pareto search');
        }

        // Fallback: Find best NPV from Pareto if backend didn't provide recommended_*
        let fallbackPower = 0, fallbackEnergy = 0, fallbackCycles = 0, fallbackDischarge = 0;
        if (!hasRecommendedBess && result.pareto_frontier?.length > 0) {
            const bestVariant = result.pareto_frontier.reduce((best, current) => {
                const currentNpv = current.npv_mln_pln || 0;
                const bestNpv = best?.npv_mln_pln || -Infinity;
                return currentNpv > bestNpv ? current : best;
            }, null);
            if (bestVariant) {
                fallbackPower = bestVariant.power_kw || 0;
                fallbackEnergy = bestVariant.energy_kwh || 0;
                fallbackCycles = bestVariant.annual_cycles || 0;
                fallbackDischarge = bestVariant.annual_discharge_mwh || 0;
            }
        }

        const variantComparison = result.variant_comparison;

        const bessData = {
            // Recommended BESS sizing (BEST NPV) - from backend or fallback
            bess_power_kw: result.recommended_bess_power_kw || fallbackPower,
            bess_energy_kwh: result.recommended_bess_energy_kwh || fallbackEnergy,

            // Annual energy flows from REAL HOURLY SIMULATION
            annual_cycles: result.recommended_bess_annual_cycles || fallbackCycles,
            annual_discharge_mwh: result.recommended_bess_annual_discharge_mwh || fallbackDischarge,

            // Hourly data for Excel export (SINGLE SOURCE OF TRUTH!)
            recommended_hourly_bess_charge: result.recommended_hourly_bess_charge,
            recommended_hourly_bess_discharge: result.recommended_hourly_bess_discharge,
            recommended_hourly_bess_soc: result.recommended_hourly_bess_soc,

            // NPV and payback from profile analysis
            npv_pln: (result.pareto_frontier?.find(p =>
                Math.abs(p.power_kw - (result.recommended_bess_power_kw || 0)) < 10)?.npv_mln_pln || 0) * 1_000_000,
            payback_years: result.pareto_frontier?.find(p =>
                Math.abs(p.power_kw - (result.recommended_bess_power_kw || 0)) < 10)?.payback_years || 0,
            capex_pln: variantComparison?.recommended?.capex_pln || 0,
            annual_savings_pln: variantComparison?.recommended?.annual_savings_pln || 0,

            // Energy balance
            annual_surplus_mwh: result.annual_surplus_mwh,
            annual_deficit_mwh: result.annual_deficit_mwh,
            direct_consumption_mwh: result.direct_consumption_mwh,  // PV direct without BESS!
            direct_consumption_pct: result.direct_consumption_pct,
            annual_load_mwh: result.annual_load_mwh,  // CRITICAL: Total plant consumption for economics!

            // Strategy used
            strategy: result.selected_strategy,

            // Full recommendations array for reference
            all_recommendations: result.bess_recommendations,
            pareto_frontier: result.pareto_frontier
        };

        console.log('📤 Profile: Sending PROFILE_ANALYSIS_COMPLETE to shell:', {
            bess_power_kw: bessData.bess_power_kw,
            bess_energy_kwh: bessData.bess_energy_kwh,
            annual_discharge_mwh: bessData.annual_discharge_mwh,
            annual_load_mwh: bessData.annual_load_mwh,  // CRITICAL: Total plant consumption
            has_hourly_data: !!bessData.recommended_hourly_bess_discharge?.length
        });

        window.parent.postMessage({
            type: 'PROFILE_ANALYSIS_COMPLETE',
            data: {
                bessData: bessData,
                fullResult: result
            }
        }, '*');
    }

    function applySettings(settings) {
        // Cache settings for later use (BESS degradation params, etc.)
        cachedSettings = settings;

        // Apply settings from shell to form
        if (settings.energyPrice) {
            document.getElementById('energyPrice').value = settings.energyPrice;
        }
        if (settings.bessCapexPerKwh) {
            document.getElementById('bessCapexKwh').value = settings.bessCapexPerKwh;
        }
        if (settings.bessCapexPerKw) {
            document.getElementById('bessCapexKw').value = settings.bessCapexPerKw;
        }
        // bessRoundtripEfficiency comes as decimal (0.90), convert to percentage (90)
        if (settings.bessRoundtripEfficiency) {
            document.getElementById('bessEfficiency').value = settings.bessRoundtripEfficiency * 100;
        }
        // discountRate already comes as percentage (7), no conversion needed
        if (settings.discountRate) {
            document.getElementById('discountRate').value = settings.discountRate;
        }
        // analysisPeriod - project years
        if (settings.analysisPeriod) {
            document.getElementById('projectYears').value = settings.analysisPeriod;
        }
        console.log('⚙️ Applied settings from shell (including BESS degradation params)');
    }

    function populateCurrentConfig(data) {
        console.log('📋 Populating config from data:', Object.keys(data || {}));

        // Try to get PV capacity from various sources
        let pvCapacity = null;
        let bessEnergy = null;
        let bessPower = null;

        // PRIORITY 1: Use masterVariant directly (the user's selected variant!)
        if (data.masterVariant) {
            pvCapacity = data.masterVariant.capacity;
            bessEnergy = data.masterVariant.bess_energy_kwh;
            bessPower = data.masterVariant.bess_power_kw;
            console.log('  ✓ Using masterVariant:', {
                capacity: pvCapacity,
                bess_energy: bessEnergy,
                bess_power: bessPower,
                variant: data.masterVariantKey
            });
        }

        // PRIORITY 2: Check sharedData.masterVariant
        if (!pvCapacity && data.sharedData?.masterVariant) {
            pvCapacity = data.sharedData.masterVariant.capacity;
            bessEnergy = data.sharedData.masterVariant.bess_energy_kwh;
            bessPower = data.sharedData.masterVariant.bess_power_kw;
            console.log('  ✓ Using sharedData.masterVariant:', {
                capacity: pvCapacity,
                bess_energy: bessEnergy,
                bess_power: bessPower
            });
        }

        // PRIORITY 3: Check key_variants with masterVariantKey
        if (!pvCapacity && data.sharedData?.masterVariantKey && data.fullResults?.key_variants) {
            const masterData = data.fullResults.key_variants[data.sharedData.masterVariantKey];
            if (masterData) {
                pvCapacity = masterData.capacity;
                bessEnergy = masterData.bess_energy_kwh;
                bessPower = masterData.bess_power_kw;
                console.log('  ✓ Using key_variants[' + data.sharedData.masterVariantKey + ']:', {
                    capacity: pvCapacity,
                    bess_energy: bessEnergy,
                    bess_power: bessPower
                });
            }
        }

        // FALLBACK: Check pvConfig (less reliable)
        if (!pvCapacity && data.pvConfig?.capacity) {
            pvCapacity = data.pvConfig.capacity;
            console.log('  - Fallback to pvConfig.capacity:', pvCapacity);
        }

        // LAST RESORT: First scenario (should not be used normally)
        if (!pvCapacity && data.scenarios && data.scenarios.length > 0) {
            const scenario = data.scenarios[0];
            pvCapacity = scenario.capacity;
            bessEnergy = bessEnergy || scenario.bess_energy_kwh;
            bessPower = bessPower || scenario.bess_power_kw;
            console.log('  ⚠️ WARNING: Fallback to first scenario (not master variant!):', pvCapacity);
        }

        // Apply values to form (round to whole numbers for practical use)
        if (pvCapacity) {
            const roundedPv = Math.round(pvCapacity);
            document.getElementById('pvCapacity').value = roundedPv;
            console.log('  ✓ Set PV capacity:', roundedPv, 'kWp');
        }
        if (bessEnergy) {
            const roundedEnergy = Math.round(bessEnergy);
            document.getElementById('bessEnergy').value = roundedEnergy;
            console.log('  ✓ Set BESS energy:', roundedEnergy, 'kWh');
        }
        if (bessPower) {
            const roundedPower = Math.round(bessPower);
            document.getElementById('bessPower').value = roundedPower;
            console.log('  ✓ Set BESS power:', roundedPower, 'kW');
        }
    }

    async function runAnalysis() {
        const btn = document.getElementById('analyzeBtn');
        btn.disabled = true;
        btn.textContent = 'Analizuję (PyPSA)...';

        showLoading(true, 'Pobieranie danych...');

        try {
            // Get data from shell
            const pvData = await getPvDataFromShell();
            const loadData = await getLoadDataFromShell();

            // Get hourly generation - try multiple sources
            let hourlyGeneration = pvData?.hourly_generation || [];
            let hourlyConsumption = loadData?.hourly_consumption || [];

            console.log('📊 Data from shell:');
            console.log('  - PV generation:', hourlyGeneration.length, 'values');
            console.log('  - Load consumption:', hourlyConsumption.length, 'values');

            // If PV data is empty, try to get from cached shell data
            if (hourlyGeneration.length === 0 && cachedShellData) {
                console.log('  ⚠️ PV data empty, trying cached data...');

                // Try fullResults.hourly_production
                if (cachedShellData.fullResults?.hourly_production) {
                    hourlyGeneration = cachedShellData.fullResults.hourly_production;
                    console.log('  ✓ Using fullResults.hourly_production:', hourlyGeneration.length);
                }
                // Try sharedData.analysisResults.hourly_production
                else if (cachedShellData.sharedData?.analysisResults?.hourly_production) {
                    hourlyGeneration = cachedShellData.sharedData.analysisResults.hourly_production;
                    console.log('  ✓ Using sharedData.analysisResults.hourly_production:', hourlyGeneration.length);
                }
                // Try key_variants master
                else if (cachedShellData.fullResults?.key_variants) {
                    const variants = Object.values(cachedShellData.fullResults.key_variants);
                    const withProduction = variants.find(v => v.hourly_production?.length > 0);
                    if (withProduction) {
                        hourlyGeneration = withProduction.hourly_production;
                        console.log('  ✓ Using key_variant hourly_production:', hourlyGeneration.length);
                    }
                }
            }

            // If load data is empty, try cached
            if (hourlyConsumption.length === 0 && cachedShellData) {
                if (cachedShellData.hourlyData?.values) {
                    hourlyConsumption = cachedShellData.hourlyData.values;
                    console.log('  ✓ Using cached hourlyData.values:', hourlyConsumption.length);
                } else if (cachedShellData.sharedData?.hourlyData?.values) {
                    hourlyConsumption = cachedShellData.sharedData.hourlyData.values;
                    console.log('  ✓ Using sharedData.hourlyData.values:', hourlyConsumption.length);
                }
            }

            // Validate data
            if (hourlyGeneration.length === 0) {
                showError('Brak danych produkcji PV. Najpierw wykonaj analizę w module KONFIGURACJA.');
                return;
            }
            if (hourlyConsumption.length === 0) {
                showError('Brak danych zużycia. Najpierw wgraj profil zużycia w module KONFIGURACJA.');
                return;
            }

            console.log('✅ Data ready:', hourlyGeneration.length, 'PV values,', hourlyConsumption.length, 'load values');

            // Cache PV and Load data for Excel export (in case localStorage fails with large data)
            if (!cachedShellData) cachedShellData = {};
            cachedShellData.cachedPvGeneration = hourlyGeneration;
            cachedShellData.cachedLoadConsumption = hourlyConsumption;
            console.log('💾 Cached PV and Load data for Excel export');

            // Get timestamps for correct month mapping
            // CRITICAL: This ensures monthly data is correctly assigned to calendar months
            // Analytical year may start from any month (e.g., July 2024 to June 2025)
            let timestamps = null;

            // Debug: show all possible sources
            console.log('📅 Looking for timestamps...');
            console.log('   cachedShellData.hourlyData:', cachedShellData?.hourlyData);
            console.log('   cachedShellData.hourlyData?.timestamps:', cachedShellData?.hourlyData?.timestamps?.length || 'N/A');
            console.log('   cachedShellData.sharedData?.hourlyData?.timestamps:', cachedShellData?.sharedData?.hourlyData?.timestamps?.length || 'N/A');
            console.log('   cachedShellData.sharedData?.analyticalYear:', cachedShellData?.sharedData?.analyticalYear);

            // PRIORITY 1: Try to get timestamps directly from hourlyData
            if (cachedShellData?.hourlyData?.timestamps?.length > 0) {
                timestamps = cachedShellData.hourlyData.timestamps;
                console.log('📅 Using timestamps from hourlyData:', timestamps.length, 'values');
                console.log('   First timestamp:', timestamps[0]);
                console.log('   Last timestamp:', timestamps[timestamps.length - 1]);
            }
            // PRIORITY 2: Try sharedData.hourlyData.timestamps
            else if (cachedShellData?.sharedData?.hourlyData?.timestamps?.length > 0) {
                timestamps = cachedShellData.sharedData.hourlyData.timestamps;
                console.log('📅 Using timestamps from sharedData.hourlyData:', timestamps.length, 'values');
                console.log('   First timestamp:', timestamps[0]);
            }
            // PRIORITY 3: Try fullResults or sharedData.analysisResults for timestamps
            else if (cachedShellData?.fullResults?.timestamps?.length > 0) {
                timestamps = cachedShellData.fullResults.timestamps;
                console.log('📅 Using timestamps from fullResults:', timestamps.length, 'values');
            }
            // PRIORITY 4: Generate from analyticalYear.start_date
            else {
                const analyticalYear = cachedShellData?.sharedData?.analyticalYear ||
                                       cachedShellData?.analyticalYear ||
                                       cachedShellData?.fullResults?.analytical_year;

                if (analyticalYear?.start_date) {
                    console.log('📅 Generating timestamps from analytical year:', analyticalYear.start_date);
                    timestamps = [];
                    const startDate = new Date(analyticalYear.start_date);
                    for (let i = 0; i < hourlyConsumption.length; i++) {
                        const ts = new Date(startDate.getTime() + i * 3600000); // Add hours
                        timestamps.push(ts.toISOString());
                    }
                    console.log(`   Generated ${timestamps.length} timestamps, starting from ${timestamps[0]}`);
                } else {
                    console.warn('⚠️ No timestamps or analytical year found - monthly analysis may be incorrect!');
                    console.warn('   cachedShellData keys:', Object.keys(cachedShellData || {}));
                    console.warn('   hourlyData type:', typeof cachedShellData?.hourlyData);
                    console.warn('   hourlyData keys:', cachedShellData?.hourlyData ? Object.keys(cachedShellData.hourlyData) : 'N/A');
                }
            }

            // Get BESS degradation params from Settings (CENTRALIZED SOURCE OF TRUTH)
            // These come from frontend-settings and apply to ALL modules: Profile, Economics, BESS
            const bessDegradationYear1 = cachedSettings?.bessDegradationYear1 || 3.0;  // First year: higher degradation
            const bessDegradationPctPerYear = cachedSettings?.bessDegradationPctPerYear || 2.0;  // Years 2+
            const bessAuxiliaryLossPctPerDay = cachedSettings?.bessAuxiliaryLossPctPerDay || 0.1;  // Standby losses

            console.log('🔋 BESS degradation params from Settings:', {
                year1: bessDegradationYear1 + '%',
                years2plus: bessDegradationPctPerYear + '%/yr',
                auxiliaryLoss: bessAuxiliaryLossPctPerDay + '%/day'
            });

            // Get Peak Shaving and Arbitrage params from UI or Settings
            const peakShavingEnabled = document.getElementById('peakShavingEnabled')?.checked ||
                                       cachedSettings?.bessPeakShavingEnabled || false;
            const peakShavingMode = document.getElementById('peakShavingMode')?.value ||
                                    cachedSettings?.bessPeakShavingMode || 'auto';
            const peakShavingTargetKw = parseFloat(document.getElementById('peakShavingTargetKw')?.value) ||
                                        cachedSettings?.bessPeakShavingTargetKw || 0;
            const powerChargePlnPerKwMonth = parseFloat(document.getElementById('powerChargePlnPerKwMonth')?.value) ||
                                              cachedSettings?.bessPowerChargePlnPerKwMonth || 50;

            const priceArbitrageEnabled = document.getElementById('priceArbitrageEnabled')?.checked ||
                                          cachedSettings?.bessPriceArbitrageEnabled || false;
            const arbitrageSource = document.getElementById('arbitrageSource')?.value ||
                                    cachedSettings?.bessPriceArbitrageSource || 'manual';
            const arbitrageBuyThreshold = parseFloat(document.getElementById('arbitrageBuyThreshold')?.value) ||
                                          cachedSettings?.bessPriceArbitrageBuyThreshold || 300;
            const arbitrageSellThreshold = parseFloat(document.getElementById('arbitrageSellThreshold')?.value) ||
                                           cachedSettings?.bessPriceArbitrageSellThreshold || 600;

            console.log('📉 Peak Shaving params:', {
                enabled: peakShavingEnabled,
                mode: peakShavingMode,
                targetKw: peakShavingTargetKw,
                powerCharge: powerChargePlnPerKwMonth
            });
            console.log('💹 Arbitrage params:', {
                enabled: priceArbitrageEnabled,
                source: arbitrageSource,
                buyThreshold: arbitrageBuyThreshold,
                sellThreshold: arbitrageSellThreshold
            });

            const request = {
                pv_generation_kwh: hourlyGeneration,
                load_kwh: hourlyConsumption,
                timestamps: timestamps,  // IMPORTANT: For correct month mapping
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
                max_cycles: parseInt(document.getElementById('maxCycles').value) || 365,
                // BESS degradation params from Settings (CENTRALIZED)
                bess_degradation_year1_pct: bessDegradationYear1,
                bess_degradation_pct_per_year: bessDegradationPctPerYear,
                bess_auxiliary_loss_pct_per_day: bessAuxiliaryLossPctPerDay,
                // Peak Shaving params
                peak_shaving_enabled: peakShavingEnabled,
                peak_shaving_mode: peakShavingMode,
                peak_shaving_target_kw: peakShavingTargetKw,
                power_charge_pln_per_kw_month: powerChargePlnPerKwMonth,
                // Price Arbitrage params
                price_arbitrage_enabled: priceArbitrageEnabled,
                price_arbitrage_source: arbitrageSource,
                price_arbitrage_buy_threshold: arbitrageBuyThreshold,
                price_arbitrage_sell_threshold: arbitrageSellThreshold,
                // 🐙 Kraken Protocol: PyPSA + HiGHS optimizer
                use_pypsa_optimizer: document.getElementById('usePypsaOptimizer')?.checked || false
            };

            const usePypsa = request.use_pypsa_optimizer;
            showLoading(true, usePypsa ? '🐙 Kraken: Optymalizacja PyPSA + HiGHS...' : 'Generuję front Pareto...');

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

            // Persist analysisResult to localStorage for Excel export after page reload
            try {
                localStorage.setItem('profileAnalysisResult', JSON.stringify(analysisResult));
                console.log('💾 Profile analysis result saved to localStorage');
            } catch (e) {
                console.warn('Could not save analysis result to localStorage:', e);
            }

            // Send BESS analysis results to shell for Economics module
            notifyShellProfileAnalysis(analysisResult);

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

        // Peak Shaving Tab (detailed analysis)
        displayPeakShavingTab(result);

        // Insights
        displayInsights(result.insights);

        // Switch to summary tab
        switchTab('summary');
    }

    function displaySummary(result) {
        // BESS degradation model info (from v2.1, updated v2.2 with Year1 param)
        // Parameters come from Settings (centralized source of truth)
        const hasDegradationModel = result.bess_degradation_pct_per_year !== undefined &&
                                     result.bess_degradation_pct_per_year !== null;
        const degradationHtml = hasDegradationModel ? `
            <div class="summary-section-header">Model degradacji BESS (z Ustawień)</div>
            <div class="summary-card highlight-purple">
                <div class="summary-label">Degradacja rok 1 <span class="tooltip-icon" data-tooltip="Pierwszy rok bateria traci więcej pojemności z powodu stabilizacji chemicznej ogniw. Typowo 2-5% dla Li-ion.">?</span></div>
                <div class="summary-value">${(result.bess_degradation_year1_pct || 3.0).toFixed(1)}%</div>
                <div class="summary-unit">początkowa stabilizacja</div>
            </div>
            <div class="summary-card highlight-purple">
                <div class="summary-label">Degradacja lata 2+ <span class="tooltip-icon" data-tooltip="Roczny spadek pojemności baterii w kolejnych latach. Typowo 1-3% dla Li-ion przy umiarkowanym cyklowaniu.">?</span></div>
                <div class="summary-value">${result.bess_degradation_pct_per_year.toFixed(1)}%</div>
                <div class="summary-unit">spadek pojemności/rok</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Straty pomocnicze <span class="tooltip-icon" data-tooltip="Stałe zużycie energii przez BMS, system chłodzenia, monitoring. Typowo 0.05-0.2% pojemności dziennie.">?</span></div>
                <div class="summary-value">${(result.bess_auxiliary_loss_pct_per_day || 0.1).toFixed(2)}%</div>
                <div class="summary-unit">pojemności/dzień (BMS, chłodzenie)</div>
            </div>
            <div class="summary-card highlight-orange">
                <div class="summary-label">Pojemność po ${result.project_years || 15} latach <span class="tooltip-icon" data-tooltip="Pozostała pojemność baterii na koniec projektu. Obliczenie: (1-deg_rok1) × (1-deg_rocznie)^(lata-1). Przy 3% rok1 + 2%/rok przez 15 lat = ~72%.">?</span></div>
                <div class="summary-value">${result.bess_capacity_at_project_end_pct?.toFixed(0) || '-'}%</div>
                <div class="summary-unit">pozostała pojemność</div>
            </div>
        ` : '';

        // Peak Shaving results section
        const peakShavingHtml = result.peak_shaving_enabled ? `
            <div class="summary-section-header">📉 Peak Shaving - Redukcja szczytów mocy</div>
            <div class="summary-card">
                <div class="summary-label">Szczyt przed <span class="tooltip-icon" data-tooltip="Maksymalna moc pobierana z sieci przed zastosowaniem BESS. To wartość, od której naliczane są opłaty mocowe.">?</span></div>
                <div class="summary-value">${result.peak_shaving_original_peak_kw?.toLocaleString('pl-PL') || '-'} kW</div>
                <div class="summary-unit">moc szczytowa historyczna</div>
            </div>
            <div class="summary-card highlight-green">
                <div class="summary-label">Szczyt po <span class="tooltip-icon" data-tooltip="Nowa moc szczytowa po rozładowaniu BESS w godzinach szczytu. Im niższa, tym większe oszczędności na opłatach mocowych.">?</span></div>
                <div class="summary-value">${result.peak_shaving_reduced_peak_kw?.toLocaleString('pl-PL') || '-'} kW</div>
                <div class="summary-unit">po redukcji przez BESS</div>
            </div>
            <div class="summary-card highlight-blue">
                <div class="summary-label">Redukcja <span class="tooltip-icon" data-tooltip="Procentowa redukcja szczytu mocy. Przykład: z 1000 kW na 850 kW = 15% redukcji.">?</span></div>
                <div class="summary-value">${result.peak_shaving_reduction_pct?.toFixed(1) || '-'}%</div>
                <div class="summary-unit">obcięcie szczytu</div>
            </div>
            <div class="summary-card highlight-green">
                <div class="summary-label">Oszczędności roczne <span class="tooltip-icon" data-tooltip="Roczne oszczędności na opłatach mocowych. Wzór: (Pmax_przed - Pmax_po) × opłata_mocowa × 12 miesięcy. Przykład: 150 kW × 50 PLN/kW × 12 = 90,000 PLN/rok.">?</span></div>
                <div class="summary-value">${result.peak_shaving_annual_savings_pln?.toLocaleString('pl-PL') || '-'} PLN</div>
                <div class="summary-unit">na opłatach mocowych</div>
            </div>
            <div class="summary-card highlight-orange">
                <div class="summary-label">NPV poprawa <span class="tooltip-icon" data-tooltip="Dodatkowa wartość NPV z tytułu peak shaving. Oszczędności zdyskontowane przez okres projektu.">?</span></div>
                <div class="summary-value">${result.peak_shaving_npv_improvement_mln_pln?.toFixed(2) || '-'} mln PLN</div>
                <div class="summary-unit">dodatkowe NPV</div>
            </div>
        ` : '';

        // Price Arbitrage results section
        const arbitrageHtml = result.price_arbitrage_enabled ? `
            <div class="summary-section-header">💹 Arbitraż Cenowy RDN</div>
            <div class="summary-card">
                <div class="summary-label">Godziny kupna <span class="tooltip-icon" data-tooltip="Liczba godzin w roku, gdy BESS ładował się z sieci (cena < próg kupna). Im więcej, tym więcej taniej energii zakupiono.">?</span></div>
                <div class="summary-value">${result.price_arbitrage_buy_hours?.toLocaleString('pl-PL') || '-'} h</div>
                <div class="summary-unit">ładowanie z sieci</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Godziny sprzedaży <span class="tooltip-icon" data-tooltip="Liczba godzin w roku, gdy BESS rozładowywał się do sieci (cena > próg sprzedaży). Im więcej, tym więcej drogiej energii sprzedano.">?</span></div>
                <div class="summary-value">${result.price_arbitrage_sell_hours?.toLocaleString('pl-PL') || '-'} h</div>
                <div class="summary-unit">rozładowanie do sieci</div>
            </div>
            <div class="summary-card highlight-red">
                <div class="summary-label">Śr. cena kupna <span class="tooltip-icon" data-tooltip="Średnia cena energii podczas ładowania BESS. Niższa = lepiej (taniej kupujemy).">?</span></div>
                <div class="summary-value">${result.price_arbitrage_avg_buy_price_pln?.toLocaleString('pl-PL') || '-'} PLN/MWh</div>
                <div class="summary-unit">podczas ładowania</div>
            </div>
            <div class="summary-card highlight-green">
                <div class="summary-label">Śr. cena sprzedaży <span class="tooltip-icon" data-tooltip="Średnia cena energii podczas rozładowywania BESS. Wyższa = lepiej (drożej sprzedajemy).">?</span></div>
                <div class="summary-value">${result.price_arbitrage_avg_sell_price_pln?.toLocaleString('pl-PL') || '-'} PLN/MWh</div>
                <div class="summary-unit">podczas rozładowywania</div>
            </div>
            <div class="summary-card highlight-blue">
                <div class="summary-label">Spread <span class="tooltip-icon" data-tooltip="Różnica między ceną sprzedaży a kupna. Zysk brutto na MWh. Przykład: sprzedaż 600 - kupno 300 = spread 300 PLN/MWh.">?</span></div>
                <div class="summary-value">${result.price_arbitrage_spread_pln?.toLocaleString('pl-PL') || '-'} PLN/MWh</div>
                <div class="summary-unit">różnica cen</div>
            </div>
            <div class="summary-card highlight-green">
                <div class="summary-label">Zysk roczny <span class="tooltip-icon" data-tooltip="Roczny zysk netto z arbitrażu cenowego. Wzór: Σ(energia_sprzedana × cena_sprzedaży) - Σ(energia_kupiona × cena_kupna) - straty sprawności.">?</span></div>
                <div class="summary-value">${result.price_arbitrage_annual_profit_pln?.toLocaleString('pl-PL') || '-'} PLN</div>
                <div class="summary-unit">netto po stratach</div>
            </div>
            <div class="summary-card highlight-orange">
                <div class="summary-label">NPV poprawa <span class="tooltip-icon" data-tooltip="Dodatkowa wartość NPV z tytułu arbitrażu cenowego. Zyski zdyskontowane przez okres projektu.">?</span></div>
                <div class="summary-value">${result.price_arbitrage_npv_improvement_mln_pln?.toFixed(2) || '-'} mln PLN</div>
                <div class="summary-unit">dodatkowe NPV</div>
            </div>
        ` : '';

        // Info about disabled features
        const disabledFeaturesHtml = (!result.peak_shaving_enabled || !result.price_arbitrage_enabled) ? `
            <div class="summary-section-header" style="color: #888;">ℹ️ Funkcje zaawansowane</div>
            ${!result.peak_shaving_enabled ? `
            <div class="summary-card" style="opacity: 0.6;">
                <div class="summary-label">Peak Shaving <span class="tooltip-icon" data-tooltip="Włącz w sekcji 'Zaawansowane funkcje BESS' powyżej, aby zobaczyć potencjalne oszczędności na opłatach mocowych.">?</span></div>
                <div class="summary-value">Wyłączone</div>
                <div class="summary-unit">włącz aby zobaczyć oszczędności</div>
            </div>
            ` : ''}
            ${!result.price_arbitrage_enabled ? `
            <div class="summary-card" style="opacity: 0.6;">
                <div class="summary-label">Arbitraż Cenowy <span class="tooltip-icon" data-tooltip="Włącz w sekcji 'Zaawansowane funkcje BESS' powyżej, aby zobaczyć potencjalne zyski z różnic cen energii.">?</span></div>
                <div class="summary-value">Wyłączony</div>
                <div class="summary-unit">włącz aby zobaczyć zyski RDN</div>
            </div>
            ` : ''}
        ` : '';

        const html = `
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-label">Roczna produkcja PV <span class="tooltip-icon" data-tooltip="Całkowita roczna produkcja energii z instalacji PV. Źródło: dane godzinowe z PVGIS lub własne.">?</span></div>
                    <div class="summary-value">${result.annual_pv_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Roczne zużycie <span class="tooltip-icon" data-tooltip="Całkowite roczne zużycie energii przez obiekt. Źródło: wgrany profil zużycia godzinowego.">?</span></div>
                    <div class="summary-value">${result.annual_load_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card highlight-green">
                    <div class="summary-label">Nadwyżka (surplus) <span class="tooltip-icon" data-tooltip="Energia PV, która przekracza bieżące zużycie i może być: 1) magazynowana w BESS, 2) eksportowana do sieci, 3) curtailowana (stracona).">?</span></div>
                    <div class="summary-value">${result.annual_surplus_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card highlight-red">
                    <div class="summary-label">Deficyt <span class="tooltip-icon" data-tooltip="Energia potrzebna, gdy zużycie > produkcja PV. Pokrywana przez: 1) rozładowanie BESS, 2) zakup z sieci.">?</span></div>
                    <div class="summary-value">${result.annual_deficit_mwh.toFixed(1)} MWh</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Autokonsumpcja bezpośrednia <span class="tooltip-icon" data-tooltip="% energii PV zużywanej bezpośrednio (bez magazynowania). Wzór: min(PV, Load) / PV. Wyższa = lepsza synchronizacja produkcji ze zużyciem.">?</span></div>
                    <div class="summary-value">${result.direct_consumption_pct.toFixed(1)}%</div>
                </div>
                ${result.current_bess_annual_cycles ? `
                <div class="summary-card highlight-blue">
                    <div class="summary-label">Obecne cykle BESS/rok <span class="tooltip-icon" data-tooltip="Liczba pełnych cykli baterii rocznie. 1 cykl = rozładowanie 100% użytecznej pojemności. Typowo 200-400 cykli/rok dla autokonsumpcji.">?</span></div>
                    <div class="summary-value">${result.current_bess_annual_cycles.toFixed(0)}</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">Wykorzystanie BESS <span class="tooltip-icon" data-tooltip="Stosunek rzeczywistych cykli do maksymalnych możliwych (365 cykli/rok = 1 cykl/dzień). Wyższe = lepsze wykorzystanie inwestycji.">?</span></div>
                    <div class="summary-value">${result.current_bess_utilization_pct.toFixed(0)}%</div>
                </div>
                <div class="summary-card highlight-orange">
                    <div class="summary-label">Curtailment ratio <span class="tooltip-icon" data-tooltip="% nadwyżki PV, która nie mogła być zmagazynowana (BESS pełny). 0% = idealne wykorzystanie, >50% = BESS za mały lub PV za duże.">?</span></div>
                    <div class="summary-value">${(result.current_curtailment_ratio * 100).toFixed(0)}%</div>
                </div>
                ` : ''}
                ${degradationHtml}
                ${peakShavingHtml}
                ${arbitrageHtml}
                ${disabledFeaturesHtml}
            </div>
        `;
        document.getElementById('summaryContent').innerHTML = html;

        // Initialize tooltips
        initTooltips();
    }

    // Initialize tooltip functionality
    function initTooltips() {
        document.querySelectorAll('.tooltip-icon').forEach(icon => {
            icon.addEventListener('mouseenter', showTooltip);
            icon.addEventListener('mouseleave', hideTooltip);
            icon.addEventListener('click', toggleTooltip);
        });
    }

    function showTooltip(e) {
        const icon = e.target;
        const text = icon.dataset.tooltip;
        if (!text) return;

        // Remove existing tooltip
        hideTooltip();

        // Create tooltip element
        const tooltip = document.createElement('div');
        tooltip.className = 'custom-tooltip';
        tooltip.innerHTML = text;
        document.body.appendChild(tooltip);

        // Position tooltip
        const rect = icon.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();

        let left = rect.left + window.scrollX - tooltipRect.width / 2 + rect.width / 2;
        let top = rect.top + window.scrollY - tooltipRect.height - 10;

        // Keep within viewport
        if (left < 10) left = 10;
        if (left + tooltipRect.width > window.innerWidth - 10) {
            left = window.innerWidth - tooltipRect.width - 10;
        }
        if (top < 10) {
            top = rect.bottom + window.scrollY + 10; // Show below instead
        }

        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
        tooltip.style.opacity = '1';
    }

    function hideTooltip() {
        document.querySelectorAll('.custom-tooltip').forEach(t => t.remove());
    }

    function toggleTooltip(e) {
        e.stopPropagation();
        const existing = document.querySelector('.custom-tooltip');
        if (existing) {
            hideTooltip();
        } else {
            showTooltip(e);
        }
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
                    <td><button class="export-btn" onclick="exportMonthByNumber(${m.month})" title="Eksportuj ${m.month_name} do Excel">📥</button></td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    }

    /**
     * Quick export for specific month (called from table row button)
     */
    function exportMonthByNumber(monthNum) {
        const monthSelect = document.getElementById('exportMonthSelect');
        if (monthSelect) {
            monthSelect.value = monthNum;
        }
        exportMonthlyHourlyData();
    }

    // Expose for onclick
    window.exportMonthByNumber = exportMonthByNumber;

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

    // ============================================
    // EXCEL EXPORT - Monthly Hourly Data
    // ============================================

    /**
     * Export hourly data for selected month to Excel
     * Columns: Date, Hour, Load [kWh], PV [kWh], Surplus [kWh], Deficit [kWh],
     *          BESS Charge [kWh], BESS Discharge [kWh], SoC [%]
     */
    function exportMonthlyHourlyData() {
        const monthSelect = document.getElementById('exportMonthSelect');
        const selectedMonth = parseInt(monthSelect.value);

        const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                           'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

        // 0 = full year, 1-12 = specific month
        const isFullYear = selectedMonth === 0;
        const monthName = isFullYear ? 'Cały_rok' : monthNames[selectedMonth - 1];

        console.log(`📊 Exporting hourly data for ${isFullYear ? 'full year' : `month ${selectedMonth} (${monthName})`}`);
        console.log('📊 cachedShellData structure:', {
            hasHourlyData: !!cachedShellData?.hourlyData,
            hourlyDataKeys: cachedShellData?.hourlyData ? Object.keys(cachedShellData.hourlyData) : [],
            hasSharedData: !!cachedShellData?.sharedData,
            sharedDataKeys: cachedShellData?.sharedData ? Object.keys(cachedShellData.sharedData) : [],
            hasFullResults: !!cachedShellData?.fullResults,
            hasAnalysisResults: !!cachedShellData?.analysisResults
        });

        // Get data from cached shell data
        if (!cachedShellData) {
            alert('Brak danych do eksportu. Najpierw wykonaj analizę.');
            return;
        }

        // Get hourly consumption and production
        let hourlyConsumption = null;
        let hourlyGeneration = null;
        let timestamps = null;

        // ============================================
        // TRY TO RESTORE analysisResult FROM LOCALSTORAGE IF NULL
        // This handles page reload / module switch scenarios
        // ============================================
        let effectiveAnalysisResult = analysisResult;
        if (!effectiveAnalysisResult) {
            try {
                const stored = localStorage.getItem('profileAnalysisResult');
                if (stored) {
                    effectiveAnalysisResult = JSON.parse(stored);
                    console.log('📊 Restored analysisResult from localStorage');
                }
            } catch (e) {
                console.warn('Could not restore analysisResult from localStorage:', e);
            }
        }

        // ============================================
        // BEST SOURCE: Direct from profile-analysis API response
        // This ensures exact match with backend calculations
        // ============================================
        console.log('📊 Checking analysisResult for hourly data:', {
            hasAnalysisResult: !!effectiveAnalysisResult,
            hourly_pv_kwh_length: effectiveAnalysisResult?.hourly_pv_kwh?.length || 0,
            hourly_load_kwh_length: effectiveAnalysisResult?.hourly_load_kwh?.length || 0
        });
        if (effectiveAnalysisResult?.hourly_load_kwh?.length > 0 && effectiveAnalysisResult?.hourly_pv_kwh?.length > 0) {
            hourlyConsumption = effectiveAnalysisResult.hourly_load_kwh;
            hourlyGeneration = effectiveAnalysisResult.hourly_pv_kwh;
            // Generate timestamps for 8760 hours (one year)
            const startDate = new Date(cachedShellData?.hourlyData?.timestamps?.[0] || '2024-01-01T00:00:00');
            timestamps = [];
            for (let h = 0; h < hourlyConsumption.length; h++) {
                const d = new Date(startDate.getTime() + h * 3600000);
                timestamps.push(d.toISOString());
            }
            console.log('📊 ✅ Using PROFILE-ANALYSIS API data (hourly_pv_kwh & hourly_load_kwh):', hourlyConsumption.length);
        }

        // Try to get consumption data from multiple sources (fallbacks)
        // Source 1: Direct hourlyData.values
        if (!hourlyConsumption && cachedShellData.hourlyData?.values?.length > 0) {
            hourlyConsumption = cachedShellData.hourlyData.values;
            timestamps = cachedShellData.hourlyData.timestamps;
            console.log('📊 Found consumption in hourlyData.values:', hourlyConsumption.length);
        }
        // Source 2: sharedData.hourlyData.values
        else if (cachedShellData.sharedData?.hourlyData?.values?.length > 0) {
            hourlyConsumption = cachedShellData.sharedData.hourlyData.values;
            timestamps = cachedShellData.sharedData.hourlyData.timestamps;
            console.log('📊 Found consumption in sharedData.hourlyData.values:', hourlyConsumption.length);
        }
        // Source 3: Direct analysisResults.hourlyData (from ANALYSIS_RESULTS message)
        else if (cachedShellData.analysisResults?.hourlyData?.values?.length > 0) {
            hourlyConsumption = cachedShellData.analysisResults.hourlyData.values;
            timestamps = cachedShellData.analysisResults.hourlyData.timestamps;
            console.log('📊 Found consumption in analysisResults.hourlyData:', hourlyConsumption.length);
        }
        // Source 4: Try localStorage as last resort
        else {
            try {
                const stored = localStorage.getItem('consumptionData');
                if (stored) {
                    const parsed = JSON.parse(stored);
                    if (parsed.hourlyData?.values?.length > 0) {
                        hourlyConsumption = parsed.hourlyData.values;
                        timestamps = parsed.hourlyData.timestamps;
                        console.log('📊 Found consumption in localStorage:', hourlyConsumption.length);
                    }
                }
            } catch (e) {
                console.warn('Could not load from localStorage:', e);
            }
        }

        // Try to get PV production data from MASTER VARIANT
        // IMPORTANT: Must use same variant as EKONOMIA (masterVariantKey)
        // NOTE: If we already have data from profile-analysis API above, skip these fallbacks
        const masterVariantKey = cachedShellData.masterVariantKey
            || cachedShellData.sharedData?.masterVariantKey
            || localStorage.getItem('masterVariantKey')
            || 'D';
        console.log('📊 Using master variant for PV export:', masterVariantKey);

        // Source 1: key_variants[masterVariantKey] in analysisResults (PREFERRED - same as EKONOMIA)
        if (!hourlyGeneration && cachedShellData.analysisResults?.key_variants?.[masterVariantKey]?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.analysisResults.key_variants[masterVariantKey].hourly_production;
            console.log(`📊 Found PV in analysisResults.key_variants[${masterVariantKey}]:`, hourlyGeneration.length);
        }
        // Source 2: key_variants[masterVariantKey] in fullResults
        else if (!hourlyGeneration && cachedShellData.fullResults?.key_variants?.[masterVariantKey]?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.fullResults.key_variants[masterVariantKey].hourly_production;
            console.log(`📊 Found PV in fullResults.key_variants[${masterVariantKey}]:`, hourlyGeneration.length);
        }
        // Source 3: key_variants[masterVariantKey] in sharedData
        else if (cachedShellData.sharedData?.analysisResults?.key_variants?.[masterVariantKey]?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.sharedData.analysisResults.key_variants[masterVariantKey].hourly_production;
            console.log(`📊 Found PV in sharedData.key_variants[${masterVariantKey}]:`, hourlyGeneration.length);
        }
        // Source 4: fullResults.hourly_production (generic fallback)
        else if (cachedShellData.fullResults?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.fullResults.hourly_production;
            console.log('📊 FALLBACK: Found PV in fullResults.hourly_production:', hourlyGeneration.length);
        }
        // Source 5: analysisResults.hourly_production (generic fallback)
        else if (cachedShellData.analysisResults?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.analysisResults.hourly_production;
            console.log('📊 FALLBACK: Found PV in analysisResults.hourly_production:', hourlyGeneration.length);
        }
        // Source 6: sharedData.analysisResults.hourly_production
        else if (cachedShellData.sharedData?.analysisResults?.hourly_production?.length > 0) {
            hourlyGeneration = cachedShellData.sharedData.analysisResults.hourly_production;
            console.log('📊 FALLBACK: Found PV in sharedData.analysisResults.hourly_production:', hourlyGeneration.length);
        }
        // Source 7: Try localStorage as last resort (use masterVariantKey)
        else {
            try {
                const stored = localStorage.getItem('pv_analysis_results');
                if (stored) {
                    const parsed = JSON.parse(stored);
                    // Try master variant first
                    if (parsed.key_variants?.[masterVariantKey]?.hourly_production?.length > 0) {
                        hourlyGeneration = parsed.key_variants[masterVariantKey].hourly_production;
                        console.log(`📊 Found PV in localStorage key_variants[${masterVariantKey}]:`, hourlyGeneration.length);
                    } else if (parsed.hourly_production?.length > 0) {
                        hourlyGeneration = parsed.hourly_production;
                        console.log('📊 FALLBACK: Found PV in localStorage hourly_production:', hourlyGeneration.length);
                    }
                }
            } catch (e) {
                console.warn('Could not load PV from localStorage:', e);
            }
        }

        // ============================================
        // FINAL FALLBACK: Use cached data from runAnalysis()
        // This ensures data is available even if localStorage fails
        // ============================================
        if (!hourlyGeneration && cachedShellData?.cachedPvGeneration?.length > 0) {
            hourlyGeneration = cachedShellData.cachedPvGeneration;
            console.log('📊 ✅ Using CACHED PV data from runAnalysis:', hourlyGeneration.length);
        }
        if (!hourlyConsumption && cachedShellData?.cachedLoadConsumption?.length > 0) {
            hourlyConsumption = cachedShellData.cachedLoadConsumption;
            console.log('📊 ✅ Using CACHED Load data from runAnalysis:', hourlyConsumption.length);
        }

        if (!hourlyConsumption || !hourlyGeneration || !timestamps) {
            console.error('Missing data for export:', {
                hasConsumption: !!hourlyConsumption,
                consumptionLength: hourlyConsumption?.length || 0,
                hasGeneration: !!hourlyGeneration,
                generationLength: hourlyGeneration?.length || 0,
                hasTimestamps: !!timestamps,
                timestampsLength: timestamps?.length || 0
            });
            alert('Brak kompletnych danych godzinowych. Upewnij się, że wykonałeś analizę w module KONFIGURACJA i masz wgrane dane zużycia.');
            return;
        }

        console.log(`📊 Data available: ${hourlyConsumption.length} load values, ${hourlyGeneration.length} PV values, ${timestamps.length} timestamps`);

        // Get BESS parameters from UI
        const bessEnergyKwh = parseFloat(document.getElementById('bessEnergy')?.value) || 2000;

        // ============================================
        // USE RECOMMENDED BESS DATA FROM BACKEND (Best NPV from Pareto)
        // This ensures Excel export matches EKONOMIA module exactly!
        // Priority: 1) recommended_hourly_* (Best NPV), 2) hourly_* (form BESS), 3) zeros
        // ============================================
        const hasRecommendedBessData = analysisResult?.recommended_hourly_bess_charge?.length > 0 &&
                                       analysisResult?.recommended_hourly_bess_discharge?.length > 0 &&
                                       analysisResult?.recommended_hourly_bess_soc?.length > 0;

        const hasFormBessData = analysisResult?.hourly_bess_charge?.length > 0 &&
                                analysisResult?.hourly_bess_discharge?.length > 0 &&
                                analysisResult?.hourly_bess_soc?.length > 0;

        // Select BESS data source - prefer recommended (Best NPV)
        let bessChargeArray, bessDischargeArray, bessSocArray, bessSourceName, annualDischargeMwh;
        let bessPowerKw, bessEnergyKwhExport;  // For summary sheet

        if (hasRecommendedBessData) {
            bessChargeArray = analysisResult.recommended_hourly_bess_charge;
            bessDischargeArray = analysisResult.recommended_hourly_bess_discharge;
            bessSocArray = analysisResult.recommended_hourly_bess_soc;
            annualDischargeMwh = analysisResult.recommended_bess_annual_discharge_mwh || 0;
            bessPowerKw = analysisResult.recommended_bess_power_kw || 0;
            bessEnergyKwhExport = analysisResult.recommended_bess_energy_kwh || bessEnergyKwh;
            bessSourceName = `RECOMMENDED (Best NPV: ${bessPowerKw}kW / ${bessEnergyKwhExport}kWh)`;
            console.log('✅ Using RECOMMENDED BESS data from backend (Best NPV - SINGLE SOURCE OF TRUTH!)');
            console.log(`   Recommended BESS: ${bessPowerKw} kW / ${bessEnergyKwhExport} kWh`);
            console.log(`   Annual discharge: ${annualDischargeMwh.toFixed(2)} MWh`);
        } else if (hasFormBessData) {
            bessChargeArray = analysisResult.hourly_bess_charge;
            bessDischargeArray = analysisResult.hourly_bess_discharge;
            bessSocArray = analysisResult.hourly_bess_soc;
            annualDischargeMwh = analysisResult.current_bess_annual_discharge_mwh || 0;
            bessPowerKw = parseFloat(document.getElementById('bessPower')?.value) || 500;
            bessEnergyKwhExport = bessEnergyKwh;
            bessSourceName = 'FORM BESS (not recommended - values may differ from EKONOMIA!)';
            console.warn('⚠️ Using FORM BESS data - no recommended BESS available');
            console.warn('   This may not match EKONOMIA module values!');
            console.log(`   Annual discharge: ${annualDischargeMwh.toFixed(2)} MWh`);
        } else {
            bessChargeArray = null;
            bessDischargeArray = null;
            bessSocArray = null;
            annualDischargeMwh = 0;
            bessPowerKw = parseFloat(document.getElementById('bessPower')?.value) || 500;
            bessEnergyKwhExport = bessEnergyKwh;
            bessSourceName = 'NONE (no backend data)';
            console.warn('⚠️ No backend BESS data available - Excel will have zeros for BESS');
        }

        console.log(`📊 BESS source for Excel: ${bessSourceName}`);

        // Filter data for selected month (or all months if isFullYear)
        const monthData = [];

        for (let i = 0; i < Math.min(timestamps.length, hourlyConsumption.length, hourlyGeneration.length); i++) {
            const ts = timestamps[i];
            const date = new Date(ts);
            const month = date.getMonth() + 1; // 1-12

            // Include data if: full year export OR matching month
            if (isFullYear || month === selectedMonth) {
                const load = hourlyConsumption[i] || 0;
                const pv = hourlyGeneration[i] || 0;
                const surplus = Math.max(0, pv - load);
                const deficit = Math.max(0, load - pv);

                // Get BESS data from selected source (recommended > form > zeros)
                const bessCharge = bessChargeArray ? (bessChargeArray[i] || 0) : 0;
                const bessDischarge = bessDischargeArray ? (bessDischargeArray[i] || 0) : 0;
                const soc = bessSocArray ? (bessSocArray[i] || 50) : 50;

                // Use standard dot decimal format (Excel compatible)
                monthData.push({
                    'Data': date.toLocaleDateString('pl-PL'),
                    'Dzień tygodnia': date.toLocaleDateString('pl-PL', { weekday: 'long' }),
                    'Miesiąc': monthNames[month - 1],
                    'Godzina': date.getHours(),
                    'Load [kWh]': parseFloat(load.toFixed(2)),
                    'PV [kWh]': parseFloat(pv.toFixed(2)),
                    'Nadwyżka [kWh]': parseFloat(surplus.toFixed(2)),
                    'Deficyt [kWh]': parseFloat(deficit.toFixed(2)),
                    'BESS Ładowanie [kWh]': parseFloat(bessCharge.toFixed(2)),
                    'BESS Rozładowanie [kWh]': parseFloat(bessDischarge.toFixed(2)),
                    'SoC [%]': parseFloat(soc.toFixed(1)),
                    'Bilans netto [kWh]': parseFloat((pv - load).toFixed(2))
                });
            }
        }

        if (monthData.length === 0) {
            const errorMsg = isFullYear
                ? 'Brak danych do eksportu. Sprawdź czy dane są załadowane.'
                : `Brak danych dla miesiąca ${monthName}. Sprawdź czy dane obejmują ten miesiąc.`;
            alert(errorMsg);
            return;
        }

        console.log(`📊 Found ${monthData.length} hourly records for ${isFullYear ? 'full year' : monthName}`);

        // Calculate summary statistics (values are already numbers, not strings)
        const totalLoad = monthData.reduce((sum, row) => sum + row['Load [kWh]'], 0);
        const totalPV = monthData.reduce((sum, row) => sum + row['PV [kWh]'], 0);
        const totalSurplus = monthData.reduce((sum, row) => sum + row['Nadwyżka [kWh]'], 0);
        const totalDeficit = monthData.reduce((sum, row) => sum + row['Deficyt [kWh]'], 0);
        const totalCharge = monthData.reduce((sum, row) => sum + row['BESS Ładowanie [kWh]'], 0);
        const totalDischarge = monthData.reduce((sum, row) => sum + row['BESS Rozładowanie [kWh]'], 0);

        // Create summary sheet with standard dot formatting
        const periodLabel = isFullYear ? 'Cały rok' : monthName;
        const summaryData = [
            { 'Parametr': 'Okres', 'Wartość': periodLabel },
            { 'Parametr': 'Liczba godzin', 'Wartość': monthData.length },
            { 'Parametr': 'Całkowite zużycie [MWh]', 'Wartość': parseFloat((totalLoad / 1000).toFixed(2)) },
            { 'Parametr': 'Całkowita produkcja PV [MWh]', 'Wartość': parseFloat((totalPV / 1000).toFixed(2)) },
            { 'Parametr': 'Całkowita nadwyżka [MWh]', 'Wartość': parseFloat((totalSurplus / 1000).toFixed(2)) },
            { 'Parametr': 'Całkowity deficyt [MWh]', 'Wartość': parseFloat((totalDeficit / 1000).toFixed(2)) },
            { 'Parametr': 'BESS - energia załadowana [MWh]', 'Wartość': parseFloat((totalCharge / 1000).toFixed(2)) },
            { 'Parametr': 'BESS - energia rozładowana [MWh]', 'Wartość': parseFloat((totalDischarge / 1000).toFixed(2)) },
            { 'Parametr': 'BESS - ekw. cykli', 'Wartość': parseFloat((totalDischarge / bessEnergyKwhExport / 0.8).toFixed(1)) },
            { 'Parametr': '', 'Wartość': '' },
            { 'Parametr': 'Parametry BESS', 'Wartość': '' },
            { 'Parametr': 'Moc BESS [kW]', 'Wartość': bessPowerKw },
            { 'Parametr': 'Pojemność BESS [kWh]', 'Wartość': bessEnergyKwhExport },
            { 'Parametr': 'Sprawność round-trip [%]', 'Wartość': Math.round(bessEfficiency * 100) },
            { 'Parametr': 'DoD [%]', 'Wartość': 80 }
        ];

        // Create workbook with two sheets
        const wb = XLSX.utils.book_new();

        // Summary sheet
        const wsSummary = XLSX.utils.json_to_sheet(summaryData);
        wsSummary['!cols'] = [{ wch: 35 }, { wch: 15 }];
        XLSX.utils.book_append_sheet(wb, wsSummary, 'Podsumowanie');

        // Hourly data sheet
        const wsData = XLSX.utils.json_to_sheet(monthData);
        wsData['!cols'] = [
            { wch: 12 }, // Data
            { wch: 14 }, // Dzień tygodnia
            { wch: 10 }, // Miesiąc
            { wch: 8 },  // Godzina
            { wch: 12 }, // Load
            { wch: 12 }, // PV
            { wch: 14 }, // Nadwyżka
            { wch: 12 }, // Deficyt
            { wch: 18 }, // BESS Ładowanie
            { wch: 20 }, // BESS Rozładowanie
            { wch: 10 }, // SoC
            { wch: 16 }  // Bilans netto
        ];

        // Sheet name (max 31 chars for Excel)
        const sheetName = isFullYear ? 'Dane godzinowe rok' : `Dane ${monthName}`;
        XLSX.utils.book_append_sheet(wb, wsData, sheetName.substring(0, 31));

        // Generate filename
        const filename = `Analiza_profilu_${monthName}_${new Date().toISOString().slice(0, 10)}.xlsx`;

        // Download file
        XLSX.writeFile(wb, filename);
        console.log(`✅ Excel file exported: ${filename}`);
    }

    // Expose export function globally for onclick handler
    window.exportMonthlyHourlyData = exportMonthlyHourlyData;

    // ============================================
    // PEAK SHAVING TAB - Detailed Analysis
    // ============================================

    let peakShavingChart = null;
    let peakShavingData = null;  // Store for export

    function displayPeakShavingTab(result) {
        const disabledDiv = document.getElementById('peakShavingDisabled');
        const resultsDiv = document.getElementById('peakShavingResults');

        if (!result.peak_shaving_enabled) {
            disabledDiv.style.display = 'block';
            resultsDiv.style.display = 'none';
            return;
        }

        disabledDiv.style.display = 'none';
        resultsDiv.style.display = 'block';

        // Store data for export
        peakShavingData = {
            result: result,
            powerCharge: parseFloat(document.getElementById('powerChargePlnPerKwMonth')?.value) || 50,
            projectYears: parseFloat(document.getElementById('projectYears')?.value) || 15,
            discountRate: parseFloat(document.getElementById('discountRate')?.value) || 8
        };

        // Summary cards
        const peakBefore = result.peak_shaving_original_peak_kw || 0;
        const peakAfter = result.peak_shaving_reduced_peak_kw || 0;
        const reductionKw = peakBefore - peakAfter;
        const reductionPct = result.peak_shaving_reduction_pct || 0;
        const threshold = result.peak_shaving_threshold_kw || peakAfter;

        document.getElementById('psPeakBefore').textContent = peakBefore.toLocaleString('pl-PL');
        document.getElementById('psPeakAfter').textContent = peakAfter.toLocaleString('pl-PL');
        document.getElementById('psReduction').textContent = `${reductionKw.toLocaleString('pl-PL')} / ${reductionPct.toFixed(1)}%`;
        document.getElementById('psThreshold').textContent = threshold.toLocaleString('pl-PL');

        // Detailed calculations
        displayPeakShavingCalculations(result);

        // Chart
        displayPeakShavingChart(result);

        // Monthly breakdown (if available from hourly data)
        displayPeakShavingMonthly(result);
    }

    function displayPeakShavingCalculations(result) {
        const container = document.getElementById('psCalculations');
        if (!container) return;

        const peakBefore = result.peak_shaving_original_peak_kw || 0;
        const peakAfter = result.peak_shaving_reduced_peak_kw || 0;
        const reductionKw = peakBefore - peakAfter;
        const powerCharge = peakShavingData?.powerCharge || 50;
        const annualSavings = result.peak_shaving_annual_savings_pln || (reductionKw * powerCharge * 12);
        const projectYears = peakShavingData?.projectYears || 15;
        const discountRate = (peakShavingData?.discountRate || 8) / 100;

        // Calculate NPV of savings
        let npvSavings = 0;
        for (let year = 1; year <= projectYears; year++) {
            npvSavings += annualSavings / Math.pow(1 + discountRate, year);
        }

        container.innerHTML = `
            <div style="background: #fff; padding: 15px; border-radius: 8px;">
                <h5 style="margin: 0 0 10px 0; color: #333;">📊 Dane wejściowe</h5>
                <table style="width: 100%; font-size: 0.9rem;">
                    <tr><td style="padding: 4px 0;">Moc szczytowa (przed):</td><td style="text-align: right; font-weight: 600;">${peakBefore.toLocaleString('pl-PL')} kW</td></tr>
                    <tr><td style="padding: 4px 0;">Próg Peak Shaving (P95):</td><td style="text-align: right; font-weight: 600;">${(result.peak_shaving_threshold_kw || peakAfter).toLocaleString('pl-PL')} kW</td></tr>
                    <tr><td style="padding: 4px 0;">Opłata mocowa:</td><td style="text-align: right; font-weight: 600;">${powerCharge} PLN/kW/m-c</td></tr>
                    <tr><td style="padding: 4px 0;">Okres analizy:</td><td style="text-align: right; font-weight: 600;">${projectYears} lat</td></tr>
                    <tr><td style="padding: 4px 0;">Stopa dyskontowa:</td><td style="text-align: right; font-weight: 600;">${(discountRate * 100).toFixed(1)}%</td></tr>
                </table>
            </div>

            <div style="background: #fff; padding: 15px; border-radius: 8px;">
                <h5 style="margin: 0 0 10px 0; color: #4CAF50;">💰 Obliczenia oszczędności</h5>
                <table style="width: 100%; font-size: 0.9rem;">
                    <tr style="border-bottom: 1px dashed #ddd;"><td style="padding: 8px 0;">Redukcja mocy szczytowej:</td><td style="text-align: right; font-weight: 700; color: #4CAF50;">${reductionKw.toLocaleString('pl-PL')} kW</td></tr>
                    <tr><td style="padding: 4px 0; font-size: 0.85rem; color: #666;">Wzór: ${peakBefore.toLocaleString()} - ${peakAfter.toLocaleString()} = ${reductionKw.toLocaleString()} kW</td><td></td></tr>

                    <tr style="border-bottom: 1px dashed #ddd; margin-top: 10px;"><td style="padding: 8px 0;">Oszczędność roczna:</td><td style="text-align: right; font-weight: 700; color: #4CAF50;">${annualSavings.toLocaleString('pl-PL')} PLN</td></tr>
                    <tr><td style="padding: 4px 0; font-size: 0.85rem; color: #666;">Wzór: ${reductionKw.toLocaleString()} kW × ${powerCharge} PLN × 12 m-cy</td><td></td></tr>

                    <tr style="border-bottom: 1px dashed #ddd;"><td style="padding: 8px 0;">NPV oszczędności (${projectYears} lat):</td><td style="text-align: right; font-weight: 700; color: #1976d2;">${(npvSavings / 1e6).toFixed(2)} mln PLN</td></tr>
                    <tr><td style="padding: 4px 0; font-size: 0.85rem; color: #666;">Suma zdyskontowanych rocznych oszczędności</td><td></td></tr>
                </table>
            </div>
        `;
    }

    function displayPeakShavingChart(result) {
        const canvas = document.getElementById('peakShavingChart');
        if (!canvas) return;

        // Destroy existing chart
        if (peakShavingChart) {
            peakShavingChart.destroy();
        }

        // Generate Load Duration Curve data (simulated from available data)
        const peakBefore = result.peak_shaving_original_peak_kw || 1000;
        const peakAfter = result.peak_shaving_reduced_peak_kw || 800;
        const threshold = result.peak_shaving_threshold_kw || peakAfter;

        // Create simulated LDC (sorted load from highest to lowest)
        const hours = 8760;
        const labels = [];
        const originalLoad = [];
        const shavedLoad = [];
        const thresholdLine = [];

        // Generate realistic LDC curve
        for (let i = 0; i < 100; i++) {
            const pct = i / 100;
            labels.push(`${(pct * 100).toFixed(0)}%`);

            // Exponential decay curve for load
            const load = peakBefore * Math.exp(-3 * pct) + (peakBefore * 0.3);
            originalLoad.push(Math.max(load, peakBefore * 0.2));

            // Shaved load capped at threshold
            shavedLoad.push(Math.min(originalLoad[i], threshold));
            thresholdLine.push(threshold);
        }

        peakShavingChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Oryginalne zużycie',
                        data: originalLoad,
                        borderColor: '#F44336',
                        backgroundColor: 'rgba(244, 67, 54, 0.1)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: 'Po Peak Shaving',
                        data: shavedLoad,
                        borderColor: '#4CAF50',
                        backgroundColor: 'rgba(76, 175, 80, 0.2)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: `Próg (${threshold.toLocaleString()} kW)`,
                        data: thresholdLine,
                        borderColor: '#FF9800',
                        borderDash: [10, 5],
                        borderWidth: 2,
                        fill: false,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Krzywa uporządkowana mocy (Load Duration Curve)'
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: ${ctx.raw.toLocaleString('pl-PL')} kW`
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: '% czasu' }
                    },
                    y: {
                        title: { display: true, text: 'Moc [kW]' },
                        beginAtZero: true
                    }
                }
            }
        });
    }

    function displayPeakShavingMonthly(result) {
        const tbody = document.getElementById('psMonthlyTableBody');
        if (!tbody) return;

        const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                           'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

        // Use monthly data if available, otherwise simulate
        const powerCharge = peakShavingData?.powerCharge || 50;
        const peakBefore = result.peak_shaving_original_peak_kw || 1000;
        const peakAfter = result.peak_shaving_reduced_peak_kw || 800;
        const reductionPct = (peakBefore - peakAfter) / peakBefore;

        let html = '';
        let totalSavings = 0;

        // If we have monthly peaks from result
        const monthlyPeaks = result.peak_shaving_monthly_peaks || null;

        for (let m = 0; m < 12; m++) {
            // Simulate seasonal variation (higher in winter)
            const seasonalFactor = 1 + 0.15 * Math.cos((m - 6) * Math.PI / 6);
            const monthPeakBefore = monthlyPeaks ? monthlyPeaks[m]?.before : Math.round(peakBefore * seasonalFactor);
            const monthPeakAfter = monthlyPeaks ? monthlyPeaks[m]?.after : Math.round(monthPeakBefore * (1 - reductionPct));
            const monthReduction = monthPeakBefore - monthPeakAfter;
            const monthSavings = monthReduction * powerCharge;
            totalSavings += monthSavings;

            html += `
                <tr>
                    <td style="text-align: left;">${monthNames[m]}</td>
                    <td>${monthPeakBefore.toLocaleString('pl-PL')}</td>
                    <td style="color: #4CAF50; font-weight: 600;">${monthPeakAfter.toLocaleString('pl-PL')}</td>
                    <td style="color: #1976d2;">${monthReduction.toLocaleString('pl-PL')}</td>
                    <td style="color: #4CAF50; font-weight: 600;">${monthSavings.toLocaleString('pl-PL')}</td>
                </tr>
            `;
        }

        // Total row
        html += `
            <tr style="background: #e3f2fd; font-weight: 700;">
                <td style="text-align: left;">RAZEM ROCZNIE</td>
                <td>-</td>
                <td>-</td>
                <td>-</td>
                <td style="color: #1976d2;">${totalSavings.toLocaleString('pl-PL')} PLN</td>
            </tr>
        `;

        tbody.innerHTML = html;
    }

    // Export Peak Shaving report to Excel
    function exportPeakShavingReport() {
        if (!peakShavingData || !peakShavingData.result) {
            alert('Brak danych Peak Shaving do eksportu. Najpierw włącz Peak Shaving i uruchom analizę.');
            return;
        }

        const result = peakShavingData.result;
        const powerCharge = peakShavingData.powerCharge;
        const projectYears = peakShavingData.projectYears;
        const discountRate = peakShavingData.discountRate / 100;

        const peakBefore = result.peak_shaving_original_peak_kw || 0;
        const peakAfter = result.peak_shaving_reduced_peak_kw || 0;
        const reductionKw = peakBefore - peakAfter;
        const annualSavings = result.peak_shaving_annual_savings_pln || (reductionKw * powerCharge * 12);

        // Create workbook
        const wb = XLSX.utils.book_new();

        // Sheet 1: Summary
        const summaryData = [
            ['RAPORT PEAK SHAVING'],
            [''],
            ['Data eksportu:', new Date().toLocaleString('pl-PL')],
            [''],
            ['DANE WEJŚCIOWE'],
            ['Moc szczytowa przed [kW]:', peakBefore],
            ['Próg Peak Shaving [kW]:', result.peak_shaving_threshold_kw || peakAfter],
            ['Opłata mocowa [PLN/kW/m-c]:', powerCharge],
            ['Okres analizy [lat]:', projectYears],
            ['Stopa dyskontowa [%]:', discountRate * 100],
            [''],
            ['WYNIKI'],
            ['Moc szczytowa po redukcji [kW]:', peakAfter],
            ['Redukcja mocy [kW]:', reductionKw],
            ['Redukcja mocy [%]:', ((reductionKw / peakBefore) * 100).toFixed(1)],
            ['Oszczędność roczna [PLN]:', annualSavings],
            [''],
            ['OBLICZENIE OSZCZĘDNOŚCI'],
            ['Wzór:', `${reductionKw} kW × ${powerCharge} PLN/kW × 12 m-cy = ${annualSavings} PLN/rok`]
        ];

        // Add NPV calculation
        summaryData.push(['']);
        summaryData.push(['ANALIZA NPV']);
        let npvTotal = 0;
        for (let year = 1; year <= projectYears; year++) {
            const discountedSavings = annualSavings / Math.pow(1 + discountRate, year);
            npvTotal += discountedSavings;
            summaryData.push([`Rok ${year}:`, Math.round(discountedSavings)]);
        }
        summaryData.push(['']);
        summaryData.push(['NPV ŁĄCZNE [PLN]:', Math.round(npvTotal)]);
        summaryData.push(['NPV ŁĄCZNE [mln PLN]:', (npvTotal / 1e6).toFixed(3)]);

        const ws1 = XLSX.utils.aoa_to_sheet(summaryData);
        ws1['!cols'] = [{ wch: 35 }, { wch: 20 }];
        XLSX.utils.book_append_sheet(wb, ws1, 'Podsumowanie');

        // Sheet 2: Monthly breakdown
        const monthNames = ['Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
                           'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień'];

        const monthlyData = [
            ['ROZKŁAD MIESIĘCZNY PEAK SHAVING'],
            [''],
            ['Miesiąc', 'Szczyt PRZED [kW]', 'Szczyt PO [kW]', 'Redukcja [kW]', 'Oszczędność [PLN]']
        ];

        const reductionPct = reductionKw / peakBefore;
        let totalMonthlySavings = 0;

        for (let m = 0; m < 12; m++) {
            const seasonalFactor = 1 + 0.15 * Math.cos((m - 6) * Math.PI / 6);
            const monthPeakBefore = Math.round(peakBefore * seasonalFactor);
            const monthPeakAfter = Math.round(monthPeakBefore * (1 - reductionPct));
            const monthReduction = monthPeakBefore - monthPeakAfter;
            const monthSavings = monthReduction * powerCharge;
            totalMonthlySavings += monthSavings;

            monthlyData.push([monthNames[m], monthPeakBefore, monthPeakAfter, monthReduction, monthSavings]);
        }

        monthlyData.push(['']);
        monthlyData.push(['RAZEM ROCZNIE', '', '', '', totalMonthlySavings]);

        const ws2 = XLSX.utils.aoa_to_sheet(monthlyData);
        ws2['!cols'] = [{ wch: 14 }, { wch: 18 }, { wch: 16 }, { wch: 14 }, { wch: 18 }];
        XLSX.utils.book_append_sheet(wb, ws2, 'Miesięczny rozkład');

        // Generate filename
        const filename = `Peak_Shaving_Raport_${new Date().toISOString().slice(0, 10)}.xlsx`;
        XLSX.writeFile(wb, filename);
        console.log(`✅ Peak Shaving report exported: ${filename}`);
    }

    // Expose export function globally
    window.exportPeakShavingReport = exportPeakShavingReport;

    // Initialize on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
