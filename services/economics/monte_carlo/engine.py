"""
Silnik symulacji Monte Carlo dla analizy ryzyka finansowego PV/BESS.

Wykorzystuje wektoryzowane operacje NumPy dla wydajności.
10,000 symulacji wykonuje się w ~100-200ms.
"""

import time
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from scipy import stats

from .models import (
    ParameterDistribution,
    CorrelationPair,
    MonteCarloRequest,
    QuickMonteCarloRequest,
    MonteCarloResult,
    HistogramData,
    RiskMetrics,
    PercentileResults,
    DistributionType,
)
from .distributions import (
    generate_correlated_samples,
    get_default_distributions,
    get_conservative_distributions,
    get_optimistic_distributions,
)


class MonteCarloEngine:
    """
    Silnik symulacji Monte Carlo dla analiz finansowych PV/BESS.

    Cechy:
    - Wektoryzowane obliczenia (NumPy)
    - Obsługa korelacji (dekompozycja Cholesky'ego)
    - Automatyczne generowanie insights
    - Metryki ryzyka (VaR, CVaR, Sharpe ratio)
    """

    def __init__(self, n_simulations: int = 10000, random_seed: Optional[int] = None):
        """
        Inicjalizuje silnik Monte Carlo.

        Args:
            n_simulations: Liczba symulacji
            random_seed: Ziarno generatora (dla powtarzalności)
        """
        self.n = n_simulations
        self.seed = random_seed
        self.rng = np.random.default_rng(random_seed)

    def run_simulation(
        self,
        request: MonteCarloRequest,
    ) -> MonteCarloResult:
        """
        Wykonuje pełną symulację Monte Carlo.

        Args:
            request: Żądanie z parametrami i danymi ekonomicznymi

        Returns:
            Wynik symulacji z rozkładami i metrykami
        """
        start_time = time.perf_counter()

        # Generate correlated samples
        samples = generate_correlated_samples(
            parameters=request.parameters,
            correlations=request.correlations,
            n_samples=request.n_simulations,
            random_seed=request.random_seed,
        )

        # Extract base economics data
        base_econ = request.base_economics
        variant = base_econ.get("variant", {})
        params = base_econ.get("parameters", {})

        # Run vectorized NPV/IRR calculations
        npv_results, irr_results, payback_results = self._calculate_economics_vectorized(
            samples=samples,
            variant=variant,
            params=params,
            n_simulations=request.n_simulations,
        )

        # Compute statistics
        npv_percentiles = self._compute_percentiles(npv_results)
        npv_histogram = self._compute_histogram(npv_results, request.histogram_bins)

        # IRR statistics (may have NaN values)
        irr_valid = irr_results[~np.isnan(irr_results)]
        irr_valid_pct = len(irr_valid) / len(irr_results) * 100

        irr_percentiles = None
        irr_histogram = None
        irr_mean = None
        irr_std = None

        if len(irr_valid) > 0:
            irr_mean = float(np.mean(irr_valid))
            irr_std = float(np.std(irr_valid))
            irr_percentiles = self._compute_percentiles(irr_valid)
            irr_histogram = self._compute_histogram(irr_valid, request.histogram_bins)

        # Payback statistics
        payback_valid = payback_results[~np.isinf(payback_results)]
        payback_percentiles = None
        payback_histogram = None
        payback_mean = None
        payback_std = None

        if len(payback_valid) > 0:
            payback_mean = float(np.mean(payback_valid))
            payback_std = float(np.std(payback_valid))
            payback_percentiles = self._compute_percentiles(payback_valid)
            payback_histogram = self._compute_histogram(payback_valid, request.histogram_bins)

        # Risk metrics
        risk_metrics = self._compute_risk_metrics(npv_results, params.get("discount_rate", 0.07))

        # Generate insights
        insights = self._generate_insights(
            npv_results=npv_results,
            irr_results=irr_results,
            payback_results=payback_results,
            risk_metrics=risk_metrics,
            samples=samples,
        )

        # Scenario extraction
        scenario_base = {
            "npv": float(np.median(npv_results)),
            "irr": float(np.median(irr_valid)) if len(irr_valid) > 0 else None,
            "payback": float(np.median(payback_valid)) if len(payback_valid) > 0 else None,
        }

        scenario_pessimistic = {
            "npv": float(np.percentile(npv_results, 10)),
            "irr": float(np.percentile(irr_valid, 10)) if len(irr_valid) > 0 else None,
            "payback": float(np.percentile(payback_valid, 90)) if len(payback_valid) > 0 else None,
        }

        scenario_optimistic = {
            "npv": float(np.percentile(npv_results, 90)),
            "irr": float(np.percentile(irr_valid, 90)) if len(irr_valid) > 0 else None,
            "payback": float(np.percentile(payback_valid, 10)) if len(payback_valid) > 0 else None,
        }

        # Breakeven price analysis
        breakeven_price = self._estimate_breakeven_price(
            samples, npv_results, variant, params
        )

        computation_time_ms = (time.perf_counter() - start_time) * 1000

        result = MonteCarloResult(
            n_simulations=request.n_simulations,
            parameters_analyzed=[p.name for p in request.parameters],
            computation_time_ms=computation_time_ms,
            npv_mean=float(np.mean(npv_results)),
            npv_std=float(np.std(npv_results)),
            npv_percentiles=npv_percentiles,
            npv_histogram=npv_histogram,
            irr_mean=irr_mean,
            irr_std=irr_std,
            irr_percentiles=irr_percentiles,
            irr_histogram=irr_histogram,
            irr_valid_pct=irr_valid_pct,
            payback_mean=payback_mean,
            payback_std=payback_std,
            payback_percentiles=payback_percentiles,
            payback_histogram=payback_histogram,
            risk_metrics=risk_metrics,
            insights=insights,
            breakeven_price=breakeven_price,
            scenario_base=scenario_base,
            scenario_pessimistic=scenario_pessimistic,
            scenario_optimistic=scenario_optimistic,
        )

        # Optionally include full distributions
        if request.return_distributions:
            result.npv_distribution = npv_results.tolist()
            result.irr_distribution = irr_results.tolist()
            result.payback_distribution = payback_results.tolist()

            # Also include sampled input parameters for full export
            if "electricity_price" in samples:
                result.sampled_electricity_prices = samples["electricity_price"].tolist()
            if "production_factor" in samples:
                result.sampled_production_factors = samples["production_factor"].tolist()
            if "investment_cost" in samples:
                result.sampled_investment_costs = samples["investment_cost"].tolist()
            if "inflation_rate" in samples:
                result.sampled_inflation_rates = samples["inflation_rate"].tolist()

        return result

    def run_quick_simulation(
        self,
        request: QuickMonteCarloRequest,
    ) -> MonteCarloResult:
        """
        Szybka symulacja z domyślnymi parametrami.

        Args:
            request: Uproszczone żądanie

        Returns:
            Wynik symulacji
        """
        # Build parameters from simplified inputs
        base_econ = request.base_economics
        params = base_econ.get("parameters", {})

        # Bankable clip ranges based on industry standards
        # Sources: NREL, SolarGIS, FfE, IMF (2024)
        base_price = params.get("energy_price", 450.0)
        base_capex = params.get("investment_cost", 3500.0)

        parameters = [
            ParameterDistribution(
                name="electricity_price",
                dist_type=DistributionType.NORMAL,
                base_value=base_price,
                std_dev_pct=request.electricity_price_uncertainty_pct,
                clip_min=max(150.0, base_price * 0.5),   # -50% hard floor
                clip_max=min(1200.0, base_price * 1.8),  # +80% hard ceiling
            ),
            ParameterDistribution(
                name="production_factor",
                dist_type=DistributionType.NORMAL,
                base_value=1.0,
                std_dev_pct=request.production_uncertainty_pct,
                clip_min=0.75,  # P99 protection (bankable)
                clip_max=1.25,  # P99 protection (bankable)
            ),
            ParameterDistribution(
                name="investment_cost",
                dist_type=DistributionType.LOGNORMAL,
                base_value=base_capex,
                std_dev_pct=request.capex_uncertainty_pct,
                clip_min=max(2000.0, base_capex * 0.7),  # -30% floor
                clip_max=min(6000.0, base_capex * 1.4),  # +40% ceiling
            ),
            ParameterDistribution(
                name="inflation_rate",
                dist_type=DistributionType.NORMAL,
                base_value=params.get("inflation_rate", 0.025),
                std_dev=request.inflation_uncertainty_pct / 100.0,
                clip_min=0.0,   # No deflation
                clip_max=0.10,  # 10% cap (crisis scenario)
            ),
        ]

        # Default correlations (empirically grounded)
        correlations = None
        if request.use_default_correlations:
            correlations = [
                CorrelationPair(
                    param1="electricity_price",
                    param2="inflation_rate",
                    correlation=0.5,  # Energy ~15% of CPI basket
                ),
            ]

        # Create full request and run
        # Use return_distributions from quick request if specified
        full_request = MonteCarloRequest(
            n_simulations=request.n_simulations,
            parameters=parameters,
            correlations=correlations,
            base_economics=request.base_economics,
            return_distributions=getattr(request, 'return_distributions', False),
            histogram_bins=50,
        )

        return self.run_simulation(full_request)

    def _calculate_economics_vectorized(
        self,
        samples: Dict[str, np.ndarray],
        variant: Dict[str, Any],
        params: Dict[str, Any],
        n_simulations: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Wektoryzowane obliczenia NPV, IRR i Payback.

        Args:
            samples: Słownik próbek dla każdego parametru
            variant: Dane wariantu (capacity, production, etc.)
            params: Parametry ekonomiczne
            n_simulations: Liczba symulacji

        Returns:
            Tuple (npv_array, irr_array, payback_array)
        """
        # Extract parameters with defaults
        capacity = variant.get("capacity", 100.0)
        base_production = variant.get("production", 0)
        self_consumed = variant.get("self_consumed", 0)
        exported = variant.get("exported", 0)

        # Validate: if no production data, use defaults based on capacity
        if base_production <= 0 and self_consumed <= 0:
            # Use typical values: 1000 kWh/kWp/year, 70% self-consumption
            base_production = capacity * 1000  # kWh
            self_consumed = base_production * 0.7  # kWh
            exported = base_production * 0.3  # kWh
            import logging
            logging.warning(
                f"Monte Carlo: No production data provided (production={variant.get('production')}, "
                f"self_consumed={variant.get('self_consumed')}). Using defaults: "
                f"production={base_production} kWh, self_consumed={self_consumed} kWh"
            )
        elif self_consumed <= 0 and base_production > 0:
            # Production exists but no self_consumed - assume 70%
            self_consumed = base_production * 0.7
            exported = base_production * 0.3

        analysis_period = params.get("analysis_period", 25)
        base_discount_rate = params.get("discount_rate", 0.07)
        base_degradation_rate = params.get("degradation_rate", 0.005)
        base_opex_per_kwp = params.get("opex_per_kwp", 15.0)
        export_mode = params.get("export_mode", "zero")
        feed_in_tariff = params.get("feed_in_tariff", 0.0)

        # Get sampled values (or use defaults if not sampled)
        electricity_prices = samples.get(
            "electricity_price",
            np.full(n_simulations, params.get("energy_price", 450.0))
        )
        production_factors = samples.get(
            "production_factor",
            np.ones(n_simulations)
        )
        investment_costs = samples.get(
            "investment_cost",
            np.full(n_simulations, params.get("investment_cost", 3500.0))
        )
        inflation_rates = samples.get(
            "inflation_rate",
            np.full(n_simulations, params.get("inflation_rate", 0.025))
        )
        degradation_rates = samples.get(
            "degradation_rate",
            np.full(n_simulations, base_degradation_rate)
        )
        discount_rates = samples.get(
            "discount_rate",
            np.full(n_simulations, base_discount_rate)
        )

        # Calculate investments (vectorized)
        investments = capacity * investment_costs

        # Initialize result arrays
        npv_results = np.zeros(n_simulations)
        irr_results = np.full(n_simulations, np.nan)
        payback_results = np.full(n_simulations, np.inf)

        # Calculate cash flows for each simulation
        # Using vectorized operations where possible

        # Year 0: Investment
        npv_results -= investments

        # Prepare cumulative cash flows for payback
        cumulative_cf = -investments.copy()
        payback_found = np.zeros(n_simulations, dtype=bool)

        # Cache for IRR calculation
        cash_flows_matrix = np.zeros((n_simulations, analysis_period + 1))
        cash_flows_matrix[:, 0] = -investments

        for year in range(1, analysis_period + 1):
            # Degradation factor
            degrad_factors = (1 - degradation_rates) ** year

            # Production this year (with degradation and production factor)
            production_year = base_production * degrad_factors * production_factors

            # Energy prices (with inflation)
            inflation_factors = (1 + inflation_rates) ** year
            energy_prices_year = electricity_prices * inflation_factors

            # Savings from self-consumption (scaled by production factor and degradation)
            self_consumed_year = (self_consumed * degrad_factors * production_factors)
            savings = (self_consumed_year / 1000) * energy_prices_year

            # Export revenue (if enabled)
            export_revenue = np.zeros(n_simulations)
            if export_mode != "zero":
                exported_year = exported * degrad_factors * production_factors
                export_revenue = (exported_year / 1000) * (feed_in_tariff * inflation_factors)

            # OPEX (with inflation)
            opex = capacity * base_opex_per_kwp * inflation_factors

            # Net cash flow
            net_cf = savings + export_revenue - opex

            # Store for IRR
            cash_flows_matrix[:, year] = net_cf

            # Discount factor
            discount_factors = (1 + discount_rates) ** year

            # NPV contribution
            npv_results += net_cf / discount_factors

            # Payback tracking
            cumulative_cf += net_cf
            newly_paid = (cumulative_cf >= 0) & (~payback_found)
            payback_results[newly_paid] = year
            payback_found = payback_found | newly_paid

        # Calculate IRR for each simulation (this is the slow part)
        # Use vectorized approach for simple NPV-based IRR estimation
        irr_results = self._estimate_irr_vectorized(cash_flows_matrix)

        return npv_results, irr_results, payback_results

    def _estimate_irr_vectorized(
        self,
        cash_flows_matrix: np.ndarray,
        max_iterations: int = 50,
        tolerance: float = 1e-4,
    ) -> np.ndarray:
        """
        Szybka estymacja IRR dla wielu symulacji.

        Używa metody Newtona-Raphsona z wektoryzacją.

        Args:
            cash_flows_matrix: Macierz przepływów (n_simulations x years)
            max_iterations: Max iteracji
            tolerance: Tolerancja zbieżności

        Returns:
            Tablica IRR dla każdej symulacji
        """
        n_simulations, n_years = cash_flows_matrix.shape
        irr = np.full(n_simulations, 0.1)  # Initial guess

        years = np.arange(n_years)

        for _ in range(max_iterations):
            # Calculate NPV at current IRR guess
            discount_factors = (1 + irr[:, np.newaxis]) ** years
            npv = np.sum(cash_flows_matrix / discount_factors, axis=1)

            # Calculate derivative of NPV
            dnpv = np.sum(
                -years * cash_flows_matrix / ((1 + irr[:, np.newaxis]) ** (years + 1)),
                axis=1
            )

            # Avoid division by zero
            dnpv = np.where(np.abs(dnpv) < 1e-10, 1e-10, dnpv)

            # Newton-Raphson step
            irr_new = irr - npv / dnpv

            # Clamp to reasonable range
            irr_new = np.clip(irr_new, -0.99, 10.0)

            # Check convergence
            converged = np.abs(npv) < tolerance

            # Update only non-converged
            irr = np.where(converged, irr, irr_new)

            if np.all(converged):
                break

        # Mark invalid IRRs as NaN
        invalid = (irr < -0.99) | (irr > 5.0) | np.isnan(irr)
        irr[invalid] = np.nan

        return irr

    def _compute_percentiles(self, data: np.ndarray) -> PercentileResults:
        """Oblicza percentyle dla danych."""
        return PercentileResults(
            p5=float(np.percentile(data, 5)),
            p10=float(np.percentile(data, 10)),
            p25=float(np.percentile(data, 25)),
            p50=float(np.percentile(data, 50)),
            p75=float(np.percentile(data, 75)),
            p90=float(np.percentile(data, 90)),
            p95=float(np.percentile(data, 95)),
        )

    def _compute_histogram(self, data: np.ndarray, n_bins: int) -> HistogramData:
        """Oblicza histogram dla wizualizacji."""
        counts, bin_edges = np.histogram(data, bins=n_bins)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        return HistogramData(
            bins=bin_edges.tolist(),
            counts=counts.tolist(),
            bin_centers=bin_centers.tolist(),
        )

    def _compute_risk_metrics(
        self,
        npv_results: np.ndarray,
        risk_free_rate: float = 0.03,
    ) -> RiskMetrics:
        """
        Oblicza metryki ryzyka finansowego.

        Args:
            npv_results: Tablica wyników NPV
            risk_free_rate: Stopa wolna od ryzyka (dla Sharpe ratio)

        Returns:
            RiskMetrics z wszystkimi metrykami
        """
        n = len(npv_results)
        mean_npv = float(np.mean(npv_results))
        std_npv = float(np.std(npv_results))

        # Probability of positive NPV
        prob_positive = float(np.sum(npv_results > 0) / n)

        # Value at Risk
        var_95 = float(np.percentile(npv_results, 5))
        var_99 = float(np.percentile(npv_results, 1))

        # Conditional VaR (Expected Shortfall)
        cvar_95 = float(np.mean(npv_results[npv_results <= var_95]))

        # Coefficient of variation
        cv = abs(std_npv / mean_npv) if mean_npv != 0 else float('inf')

        # Downside risk (semi-deviation)
        negative_deviations = np.minimum(npv_results - mean_npv, 0)
        downside_risk = float(np.sqrt(np.mean(negative_deviations ** 2)))

        # Sharpe ratio (using NPV normalized by investment)
        # Simplified: (mean - risk_free * investment) / std
        sharpe = None
        if std_npv > 0:
            sharpe = float((mean_npv) / std_npv)  # Simplified Sharpe-like ratio

        return RiskMetrics(
            probability_positive=prob_positive,
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            expected_value=mean_npv,
            standard_deviation=std_npv,
            coefficient_of_variation=cv,
            downside_risk=downside_risk,
            sharpe_ratio=sharpe,
        )

    def _generate_insights(
        self,
        npv_results: np.ndarray,
        irr_results: np.ndarray,
        payback_results: np.ndarray,
        risk_metrics: RiskMetrics,
        samples: Dict[str, np.ndarray],
    ) -> List[str]:
        """
        Generuje automatyczne wnioski z symulacji.

        Returns:
            Lista wniosków w języku polskim
        """
        insights = []

        # Probability of profit
        prob = risk_metrics.probability_positive * 100
        if prob >= 95:
            insights.append(f"Bardzo wysoka pewność zysku: {prob:.1f}% symulacji daje dodatnie NPV")
        elif prob >= 80:
            insights.append(f"Wysoka pewność zysku: {prob:.1f}% symulacji daje dodatnie NPV")
        elif prob >= 50:
            insights.append(f"Umiarkowane ryzyko: {prob:.1f}% symulacji daje dodatnie NPV")
        else:
            insights.append(f"UWAGA: Wysokie ryzyko straty - tylko {prob:.1f}% symulacji daje dodatnie NPV")

        # NPV variability
        cv = risk_metrics.coefficient_of_variation
        if cv < 0.3:
            insights.append("Niska zmienność NPV - wyniki są stabilne")
        elif cv < 0.6:
            insights.append("Umiarkowana zmienność NPV")
        else:
            insights.append("Wysoka zmienność NPV - duża niepewność wyniku")

        # VaR interpretation
        var_95 = risk_metrics.var_95
        if var_95 > 0:
            insights.append(f"VaR 95%: W najgorszych 5% scenariuszy NPV nadal dodatnie ({var_95/1000:.0f} tys. PLN)")
        else:
            insights.append(f"VaR 95%: W najgorszych 5% scenariuszy strata do {abs(var_95)/1000:.0f} tys. PLN")

        # IRR analysis
        irr_valid = irr_results[~np.isnan(irr_results)]
        if len(irr_valid) > 0:
            irr_median = np.median(irr_valid) * 100
            irr_p10 = np.percentile(irr_valid, 10) * 100
            irr_p90 = np.percentile(irr_valid, 90) * 100

            insights.append(f"IRR: mediana {irr_median:.1f}% (zakres P10-P90: {irr_p10:.1f}% - {irr_p90:.1f}%)")

            if irr_p10 > 7:
                insights.append("Nawet w pesymistycznym scenariuszu (P10) IRR przekracza typową stopę dyskontową 7%")

        # Payback analysis
        payback_valid = payback_results[~np.isinf(payback_results)]
        if len(payback_valid) > 0:
            payback_median = np.median(payback_valid)
            payback_p90 = np.percentile(payback_valid, 90)

            insights.append(f"Zwrot inwestycji: mediana {payback_median:.1f} lat (90% przypadków < {payback_p90:.1f} lat)")

        # Parameter sensitivity (correlation with NPV)
        for param_name, param_samples in samples.items():
            corr = np.corrcoef(param_samples, npv_results)[0, 1]
            if abs(corr) > 0.5:
                direction = "dodatnio" if corr > 0 else "ujemnie"
                insights.append(f"{param_name} silnie {direction} skorelowany z NPV (r={corr:.2f})")

        return insights

    def _estimate_breakeven_price(
        self,
        samples: Dict[str, np.ndarray],
        npv_results: np.ndarray,
        variant: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Optional[float]:
        """
        Szacuje cenę energii przy której NPV = 0.

        Używa regresji liniowej z próbek.
        """
        if "electricity_price" not in samples:
            return None

        prices = samples["electricity_price"]

        # Simple linear regression
        try:
            slope, intercept, _, _, _ = stats.linregress(prices, npv_results)
            if slope != 0:
                breakeven = -intercept / slope
                if 0 < breakeven < 2000:  # Reasonable range
                    return float(breakeven)
        except Exception:
            pass

        return None
