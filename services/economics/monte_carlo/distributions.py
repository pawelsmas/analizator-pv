"""
Funkcje rozkładów prawdopodobieństwa dla symulacji Monte Carlo.

Obsługuje:
- Generowanie próbek z różnych rozkładów
- Korelacje między parametrami (dekompozycja Cholesky'ego)
- Domyślne konfiguracje niepewności dla PV/BESS
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from scipy import stats

from .models import (
    ParameterDistribution,
    CorrelationPair,
    DistributionType,
)


def sample_distribution(
    param: ParameterDistribution,
    n_samples: int,
    random_state: Optional[np.random.Generator] = None
) -> np.ndarray:
    """
    Generuje próbki z określonego rozkładu.

    Args:
        param: Definicja parametru z rozkładem
        n_samples: Liczba próbek do wygenerowania
        random_state: Generator liczb losowych (opcjonalny)

    Returns:
        Tablica numpy z próbkami
    """
    rng = random_state or np.random.default_rng()

    if param.dist_type == DistributionType.NORMAL:
        std = param.get_effective_std_dev()
        samples = rng.normal(param.base_value, std, n_samples)

    elif param.dist_type == DistributionType.LOGNORMAL:
        # Dla lognormal: mean i sigma to parametry rozkładu ln(X)
        # Chcemy E[X] = base_value, Std[X] = std_dev
        std = param.get_effective_std_dev()
        mu = param.base_value
        sigma = std

        # Przekształcenie parametrów
        # E[X] = exp(mu_ln + sigma_ln^2/2)
        # Var[X] = (exp(sigma_ln^2) - 1) * exp(2*mu_ln + sigma_ln^2)
        if mu > 0 and sigma > 0:
            sigma_ln_sq = np.log(1 + (sigma / mu) ** 2)
            mu_ln = np.log(mu) - sigma_ln_sq / 2
            sigma_ln = np.sqrt(sigma_ln_sq)
            samples = rng.lognormal(mu_ln, sigma_ln, n_samples)
        else:
            # Fallback to normal if invalid parameters
            samples = rng.normal(param.base_value, std, n_samples)
            samples = np.maximum(samples, 0)  # Ensure non-negative

    elif param.dist_type == DistributionType.TRIANGULAR:
        left = param.min_val if param.min_val is not None else param.base_value * 0.8
        right = param.max_val if param.max_val is not None else param.base_value * 1.2
        mode = param.mode_val if param.mode_val is not None else param.base_value

        # Ensure mode is within [left, right]
        mode = np.clip(mode, left, right)
        samples = rng.triangular(left, mode, right, n_samples)

    elif param.dist_type == DistributionType.UNIFORM:
        left = param.min_val if param.min_val is not None else param.base_value * 0.8
        right = param.max_val if param.max_val is not None else param.base_value * 1.2
        samples = rng.uniform(left, right, n_samples)

    else:
        raise ValueError(f"Nieobsługiwany typ rozkładu: {param.dist_type}")

    # Apply clipping if specified
    if param.clip_min is not None:
        samples = np.maximum(samples, param.clip_min)
    if param.clip_max is not None:
        samples = np.minimum(samples, param.clip_max)

    return samples


def generate_correlated_samples(
    parameters: List[ParameterDistribution],
    correlations: Optional[List[CorrelationPair]],
    n_samples: int,
    random_seed: Optional[int] = None
) -> Dict[str, np.ndarray]:
    """
    Generuje skorelowane próbki dla wielu parametrów.

    Używa dekompozycji Cholesky'ego do wprowadzenia korelacji
    między niezależnymi próbkami z rozkładu normalnego,
    następnie transformuje do docelowych rozkładów.

    Args:
        parameters: Lista parametrów z rozkładami
        correlations: Lista par korelacji
        n_samples: Liczba próbek
        random_seed: Ziarno generatora

    Returns:
        Słownik {nazwa_parametru: tablica_próbek}
    """
    rng = np.random.default_rng(random_seed)
    n_params = len(parameters)
    param_names = [p.name for p in parameters]

    # Build correlation matrix
    corr_matrix = np.eye(n_params)

    if correlations:
        name_to_idx = {name: i for i, name in enumerate(param_names)}

        for corr_pair in correlations:
            if corr_pair.param1 in name_to_idx and corr_pair.param2 in name_to_idx:
                i = name_to_idx[corr_pair.param1]
                j = name_to_idx[corr_pair.param2]
                corr_matrix[i, j] = corr_pair.correlation
                corr_matrix[j, i] = corr_pair.correlation

    # Ensure positive semi-definite (fix numerical issues)
    try:
        # Cholesky decomposition
        L = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        # Matrix not positive definite - use nearest PSD matrix
        eigenvalues, eigenvectors = np.linalg.eigh(corr_matrix)
        eigenvalues = np.maximum(eigenvalues, 1e-8)
        corr_matrix = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        # Normalize to correlation matrix
        d = np.sqrt(np.diag(corr_matrix))
        corr_matrix = corr_matrix / np.outer(d, d)
        L = np.linalg.cholesky(corr_matrix)

    # Generate independent standard normal samples
    z_independent = rng.standard_normal((n_params, n_samples))

    # Apply correlation via Cholesky
    z_correlated = L @ z_independent

    # Transform to target distributions
    samples = {}

    for i, param in enumerate(parameters):
        # Transform from standard normal to uniform [0,1]
        u = stats.norm.cdf(z_correlated[i, :])

        # Transform to target distribution using inverse CDF
        if param.dist_type == DistributionType.NORMAL:
            std = param.get_effective_std_dev()
            samples[param.name] = stats.norm.ppf(u, loc=param.base_value, scale=std)

        elif param.dist_type == DistributionType.LOGNORMAL:
            std = param.get_effective_std_dev()
            mu = param.base_value
            if mu > 0 and std > 0:
                sigma_ln_sq = np.log(1 + (std / mu) ** 2)
                mu_ln = np.log(mu) - sigma_ln_sq / 2
                sigma_ln = np.sqrt(sigma_ln_sq)
                samples[param.name] = stats.lognorm.ppf(u, s=sigma_ln, scale=np.exp(mu_ln))
            else:
                samples[param.name] = stats.norm.ppf(u, loc=mu, scale=std)
                samples[param.name] = np.maximum(samples[param.name], 0)

        elif param.dist_type == DistributionType.TRIANGULAR:
            left = param.min_val if param.min_val is not None else param.base_value * 0.8
            right = param.max_val if param.max_val is not None else param.base_value * 1.2
            mode = param.mode_val if param.mode_val is not None else param.base_value
            mode = np.clip(mode, left, right)

            # Scipy triangular uses c = (mode - left) / (right - left)
            c = (mode - left) / (right - left) if right > left else 0.5
            scale = right - left
            samples[param.name] = stats.triang.ppf(u, c, loc=left, scale=scale)

        elif param.dist_type == DistributionType.UNIFORM:
            left = param.min_val if param.min_val is not None else param.base_value * 0.8
            right = param.max_val if param.max_val is not None else param.base_value * 1.2
            samples[param.name] = stats.uniform.ppf(u, loc=left, scale=right - left)

        # Apply clipping
        if param.clip_min is not None:
            samples[param.name] = np.maximum(samples[param.name], param.clip_min)
        if param.clip_max is not None:
            samples[param.name] = np.minimum(samples[param.name], param.clip_max)

    return samples


def get_default_distributions() -> Tuple[List[ParameterDistribution], List[CorrelationPair]]:
    """
    Zwraca domyślne rozkłady i korelacje dla typowych parametrów PV/BESS.

    Wartości zgodne ze standardami branżowymi dla analiz bankowych:
    - Produkcja: ±8% (NREL, SolarGIS - kombinacja GHI ±3.5% + symulacja ±5%)
    - Cena energii: ±12% (FfE European Prices 2024, IMF volatility study)
    - CAPEX: ±8% (po ofertach EPC)
    - Inflacja: ±1.5pp (cel NBP ±1pp + margines)

    Sources:
    - NREL: docs.nrel.gov/docs/fy12osti/54488.pdf
    - SolarGIS: solargis.com/resources/blog/best-practices
    - FfE: ffe.de/en/publications/european-day-ahead-electricity-prices-in-2024
    - IMF: imf.org/en/Publications/WP/Issues/2025/01/11/Shocked-Electricity-Price-Volatility-Spillovers

    Returns:
        Tuple (lista_parametrów, lista_korelacji)
    """
    parameters = [
        # Cena energii elektrycznej [PLN/MWh]
        # Zmienność w Polsce 2024: €50-100/MWh względnie ~12-15%
        ParameterDistribution(
            name="electricity_price",
            dist_type=DistributionType.NORMAL,
            base_value=450.0,
            std_dev_pct=12.0,  # Bankable: 12% (FfE, IMF 2024)
            clip_min=250.0,   # ~-45% (3.5σ protection)
            clip_max=750.0,   # ~+65% (3.5σ protection)
        ),
        # Produkcja PV [kWh/kWp/rok] - jako mnożnik
        # NREL/SolarGIS: GHI ±3.5% + PV sim ±5% = sqrt(3.5²+5²) ≈ 6.1%, +buffer = 8%
        ParameterDistribution(
            name="production_factor",
            dist_type=DistributionType.NORMAL,
            base_value=1.0,
            std_dev_pct=8.0,   # Bankable: 8% (NREL P50/P90 standard)
            clip_min=0.75,    # P99 protection
            clip_max=1.25,    # P99 protection
        ),
        # Degradacja paneli [%/rok]
        # IEC 61215: gwarancja 0.5-0.7%/rok, Tier-1: 0.4-0.55%
        ParameterDistribution(
            name="degradation_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.005,  # 0.5% (standard gwarancyjny)
            min_val=0.003,     # 0.3% (best-case Tier-1)
            max_val=0.007,     # 0.7% (conservative)
            mode_val=0.005,
        ),
        # Koszt inwestycji [PLN/kWp]
        # Po ofertach EPC: ±5-8%, wstępna wycena: ±15-20%
        ParameterDistribution(
            name="investment_cost",
            dist_type=DistributionType.LOGNORMAL,
            base_value=3500.0,
            std_dev_pct=8.0,   # Bankable: 8% (post-EPC bid)
            clip_min=2800.0,   # -20% hard floor
            clip_max=4500.0,   # +30% hard ceiling
        ),
        # Stopa inflacji [%/rok]
        # NBP target: 2.5% ±1pp, historical variance ~1.5pp
        ParameterDistribution(
            name="inflation_rate",
            dist_type=DistributionType.NORMAL,
            base_value=0.025,  # 2.5% (NBP target)
            std_dev=0.015,     # ±1.5pp (conservative)
            clip_min=0.0,      # No deflation assumption
            clip_max=0.08,     # 8% cap (crisis scenario)
        ),
        # Stopa dyskontowa [%/rok]
        # WACC PV Poland: 6-8% (equity 8-12%, debt 4-6%)
        ParameterDistribution(
            name="discount_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.07,   # 7% (typical WACC)
            min_val=0.055,     # 5.5% (low-risk)
            max_val=0.09,      # 9% (high-risk)
            mode_val=0.07,
        ),
    ]

    correlations = [
        # Cena energii dodatnio skorelowana z inflacją
        # Empirical: 0.5-0.7 (energy is ~15% of CPI basket)
        CorrelationPair(
            param1="electricity_price",
            param2="inflation_rate",
            correlation=0.5,  # Reduced from 0.6 - more conservative
        ),
        # Koszt inwestycji ujemnie skorelowany z wielkością (efekt skali)
        CorrelationPair(
            param1="investment_cost",
            param2="production_factor",
            correlation=-0.15,  # Weak negative correlation
        ),
        # Produkcja ujemnie skorelowana z degradacją
        # Higher initial output may indicate manufacturing variability
        CorrelationPair(
            param1="production_factor",
            param2="degradation_rate",
            correlation=-0.1,  # Very weak correlation
        ),
    ]

    return parameters, correlations


def get_conservative_distributions() -> Tuple[List[ParameterDistribution], List[CorrelationPair]]:
    """
    Zwraca konserwatywne rozkłady (wyższa niepewność, gorsze założenia).

    Wartości dla analiz bankowych z podwyższonym ryzykiem:
    - Cena energii: 15% (górna granica bankowa)
    - Produkcja: 10% (konserwatywne P90)
    - CAPEX: 12% (wstępna wycena)
    - Inflacja: 2pp (wyższa niepewność)
    """
    parameters = [
        ParameterDistribution(
            name="electricity_price",
            dist_type=DistributionType.NORMAL,
            base_value=420.0,  # Niższa cena bazowa (-7%)
            std_dev_pct=15.0,  # Bankable conservative
            clip_min=200.0,
            clip_max=700.0,
        ),
        ParameterDistribution(
            name="production_factor",
            dist_type=DistributionType.NORMAL,
            base_value=0.97,   # P75 assumption (conservative)
            std_dev_pct=10.0,  # Higher uncertainty
            clip_min=0.70,
            clip_max=1.20,
        ),
        ParameterDistribution(
            name="degradation_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.006,  # 0.6% (conservative)
            min_val=0.004,
            max_val=0.008,
            mode_val=0.006,
        ),
        ParameterDistribution(
            name="investment_cost",
            dist_type=DistributionType.LOGNORMAL,
            base_value=3700.0,  # +6% CAPEX buffer
            std_dev_pct=12.0,   # Pre-EPC: higher uncertainty
            clip_min=2800.0,
            clip_max=5000.0,
        ),
        ParameterDistribution(
            name="inflation_rate",
            dist_type=DistributionType.NORMAL,
            base_value=0.030,  # 3% (above NBP target)
            std_dev=0.020,     # ±2pp
            clip_min=0.0,
            clip_max=0.10,
        ),
        ParameterDistribution(
            name="discount_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.08,   # 8% (higher risk premium)
            min_val=0.06,
            max_val=0.10,
            mode_val=0.08,
        ),
    ]

    correlations = [
        CorrelationPair(param1="electricity_price", param2="inflation_rate", correlation=0.6),
        CorrelationPair(param1="investment_cost", param2="production_factor", correlation=-0.2),
        CorrelationPair(param1="production_factor", param2="degradation_rate", correlation=-0.15),
    ]

    return parameters, correlations


def get_optimistic_distributions() -> Tuple[List[ParameterDistribution], List[CorrelationPair]]:
    """
    Zwraca optymistyczne rozkłady (niższa niepewność, lepsze założenia).

    Wartości dla projektów z niskim ryzykiem:
    - Cena energii: 10% (stabilny rynek)
    - Produkcja: 6% (dobre dane historyczne)
    - CAPEX: 5% (podpisana umowa EPC)
    - Inflacja: 1pp (stabilne otoczenie)
    """
    parameters = [
        ParameterDistribution(
            name="electricity_price",
            dist_type=DistributionType.NORMAL,
            base_value=480.0,  # Wyższa cena bazowa (+7%)
            std_dev_pct=10.0,  # Stabilny rynek
            clip_min=300.0,
            clip_max=800.0,
        ),
        ParameterDistribution(
            name="production_factor",
            dist_type=DistributionType.NORMAL,
            base_value=1.02,   # Slightly above P50
            std_dev_pct=6.0,   # Dobre dane GHI/TMY
            clip_min=0.80,
            clip_max=1.20,
        ),
        ParameterDistribution(
            name="degradation_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.004,  # 0.4% (Tier-1 panels)
            min_val=0.003,
            max_val=0.006,
            mode_val=0.004,
        ),
        ParameterDistribution(
            name="investment_cost",
            dist_type=DistributionType.LOGNORMAL,
            base_value=3300.0,  # -6% CAPEX (competitive bid)
            std_dev_pct=5.0,    # Signed EPC: low uncertainty
            clip_min=2800.0,
            clip_max=4000.0,
        ),
        ParameterDistribution(
            name="inflation_rate",
            dist_type=DistributionType.NORMAL,
            base_value=0.022,  # 2.2% (at NBP target)
            std_dev=0.010,     # ±1pp
            clip_min=0.0,
            clip_max=0.06,
        ),
        ParameterDistribution(
            name="discount_rate",
            dist_type=DistributionType.TRIANGULAR,
            base_value=0.065,  # 6.5% (lower risk premium)
            min_val=0.05,
            max_val=0.08,
            mode_val=0.065,
        ),
    ]

    correlations = [
        CorrelationPair(param1="electricity_price", param2="inflation_rate", correlation=0.4),
        CorrelationPair(param1="investment_cost", param2="production_factor", correlation=-0.1),
        CorrelationPair(param1="production_factor", param2="degradation_rate", correlation=-0.05),
    ]

    return parameters, correlations


# Słownik presetów
DISTRIBUTION_PRESETS = {
    "moderate": get_default_distributions,
    "conservative": get_conservative_distributions,
    "optimistic": get_optimistic_distributions,
}
