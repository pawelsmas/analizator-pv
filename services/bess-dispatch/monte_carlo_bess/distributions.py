"""
BESS-specific probability distributions with Cholesky-correlated sampling.

Key distributions:
- RDN prices: Shifted lognormal (allows negatives via P = X - shift)
- SOM rate: Triangular (expert estimate with bounds)
- Degradation: Beta (naturally bounded [0,1])
- Consumption: Truncated normal (seasonal profile ± noise)
- PV production: Truncated normal (non-negative)
- Inflation: Normal (symmetric around target)
- Discount rate: Triangular (expert estimate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Default correlation matrix
# ---------------------------------------------------------------------------

# Variables: rdn_prices, som_rate, consumption, pv_production, inflation
# Order matters — must match VARIABLE_ORDER
VARIABLE_ORDER = [
    "rdn_prices",
    "som_rate",
    "consumption",
    "pv_production",
    "inflation",
]

DEFAULT_CORRELATION_MATRIX = np.array([
    #  RDN    SOM    Cons   PV     Infl
    [ 1.00,  0.60,  0.20, -0.10,  0.30],  # RDN
    [ 0.60,  1.00,  0.15, -0.05,  0.25],  # SOM
    [ 0.20,  0.15,  1.00,  0.10,  0.05],  # Consumption
    [-0.10, -0.05,  0.10,  1.00,  0.00],  # PV
    [ 0.30,  0.25,  0.05,  0.00,  1.00],  # Inflation
], dtype=np.float64)


# ---------------------------------------------------------------------------
# Distribution specifications
# ---------------------------------------------------------------------------

@dataclass
class DistSpec:
    """Specification for one random variable."""
    name: str
    label_pl: str
    std_dev_pct: float         # Default σ as % of base value
    floor: Optional[float] = None
    cap: Optional[float] = None
    dist_type: str = "normal"  # normal, shifted_lognormal, triangular, beta


DEFAULT_DIST_SPECS: Dict[str, DistSpec] = {
    "rdn_prices": DistSpec(
        name="rdn_prices",
        label_pl="Ceny RDN",
        std_dev_pct=20.0,
        floor=-50.0,    # PLN/MWh — negative prices possible
        cap=2000.0,     # PLN/MWh — extreme spike cap
        dist_type="shifted_lognormal",
    ),
    "som_rate": DistSpec(
        name="som_rate",
        label_pl="Stawka SOM (opłata mocowa)",
        std_dev_pct=15.0,
        floor=0.05,     # PLN/kWh
        cap=0.50,       # PLN/kWh
        dist_type="triangular",
    ),
    "consumption": DistSpec(
        name="consumption",
        label_pl="Profil zużycia",
        std_dev_pct=10.0,
        floor=0.0,
        dist_type="normal",
    ),
    "pv_production": DistSpec(
        name="pv_production",
        label_pl="Produkcja PV",
        std_dev_pct=8.0,
        floor=0.0,
        dist_type="normal",
    ),
    "inflation": DistSpec(
        name="inflation",
        label_pl="Inflacja",
        std_dev_pct=1.5,  # Absolute pp, not relative
        floor=-2.0,
        cap=15.0,
        dist_type="normal",
    ),
}


# ---------------------------------------------------------------------------
# Cholesky-correlated sampling
# ---------------------------------------------------------------------------

def _ensure_positive_definite(C: np.ndarray) -> np.ndarray:
    """Fix near-PSD matrix via eigenvalue repair."""
    eigenvalues, eigenvectors = np.linalg.eigh(C)
    eigenvalues = np.maximum(eigenvalues, 1e-8)
    C_fixed = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    # Re-normalize to correlation matrix (diag = 1)
    d = np.sqrt(np.diag(C_fixed))
    C_fixed = C_fixed / np.outer(d, d)
    np.fill_diagonal(C_fixed, 1.0)
    return C_fixed


def generate_correlated_annual_factors(
    n_scenarios: int,
    dist_specs: Dict[str, DistSpec],
    correlation_matrix: Optional[np.ndarray] = None,
    rng: Optional[np.random.Generator] = None,
) -> Dict[str, np.ndarray]:
    """
    Generate correlated annual multiplier factors for each variable.

    Returns dict of {variable_name: array of shape (n_scenarios,)}.
    Each value is a multiplicative factor around 1.0 (e.g., 0.85 = -15%).

    For inflation, returns absolute values (e.g., 0.035 = 3.5%).
    """
    if rng is None:
        rng = np.random.default_rng()

    if correlation_matrix is None:
        correlation_matrix = DEFAULT_CORRELATION_MATRIX.copy()

    n_vars = len(VARIABLE_ORDER)
    C = _ensure_positive_definite(correlation_matrix)
    L = np.linalg.cholesky(C)

    # Generate uncorrelated standard normals: (n_vars, n_scenarios)
    U = rng.standard_normal((n_vars, n_scenarios))

    # Apply Cholesky: Z = L @ U → correlated standard normals
    Z = L @ U  # shape: (n_vars, n_scenarios)

    # Transform to target distributions
    factors: Dict[str, np.ndarray] = {}

    for i, var_name in enumerate(VARIABLE_ORDER):
        spec = dist_specs.get(var_name)
        if spec is None:
            factors[var_name] = np.ones(n_scenarios)
            continue

        z = Z[i]  # correlated standard normal for this variable

        if var_name == "inflation":
            # Inflation: absolute value centered on base (not multiplicative)
            # Will be added to base inflation later
            noise = z * (spec.std_dev_pct / 100.0)
            if spec.floor is not None:
                noise = np.maximum(noise, spec.floor / 100.0 - 0.035)
            factors[var_name] = noise  # additive, not multiplicative
        elif spec.dist_type == "shifted_lognormal":
            # Shifted lognormal: X ~ Lognormal, P = X - shift
            # For multiplicative factor: factor = exp(σ*z - σ²/2)
            # This ensures E[factor] = 1.0
            sigma = spec.std_dev_pct / 100.0
            factor = np.exp(sigma * z - 0.5 * sigma**2)
            factors[var_name] = factor
        elif spec.dist_type == "triangular":
            # Transform correlated normal → uniform → triangular
            u = norm.cdf(z)  # uniform [0,1]
            # Triangular with mode at 1.0, spread ±std_dev_pct%
            low = 1.0 - 2.0 * spec.std_dev_pct / 100.0
            high = 1.0 + 2.0 * spec.std_dev_pct / 100.0
            mode = 1.0
            # Inverse CDF of triangular
            c_tri = (mode - low) / (high - low)
            factor = np.where(
                u < c_tri,
                low + np.sqrt(u * (high - low) * (mode - low)),
                high - np.sqrt((1 - u) * (high - low) * (high - mode)),
            )
            factors[var_name] = factor
        else:
            # Normal: factor = 1 + σ*z (truncated if floor/cap set)
            sigma = spec.std_dev_pct / 100.0
            factor = 1.0 + sigma * z
            factors[var_name] = factor

        # Apply floor/cap as multiplicative bounds
        if var_name != "inflation" and spec.floor is not None:
            # Floor/cap are absolute values — we'll apply them at the point of use
            # Here we just ensure the factor doesn't go negative
            factors[var_name] = np.maximum(factors[var_name], 0.01)

    return factors


def apply_overrides(
    dist_specs: Dict[str, DistSpec],
    corr_matrix: np.ndarray,
    dist_overrides: Optional[list] = None,
    corr_overrides: Optional[list] = None,
) -> Tuple[Dict[str, DistSpec], np.ndarray]:
    """Apply user overrides to distribution specs and correlation matrix."""
    specs = {k: DistSpec(**{f.name: getattr(v, f.name) for f in v.__dataclass_fields__.values()})
             for k, v in dist_specs.items()}
    C = corr_matrix.copy()

    if dist_overrides:
        for ovr in dist_overrides:
            if ovr.variable in specs:
                if ovr.std_dev_pct is not None:
                    specs[ovr.variable].std_dev_pct = ovr.std_dev_pct
                if ovr.min_val is not None:
                    specs[ovr.variable].floor = ovr.min_val
                if ovr.max_val is not None:
                    specs[ovr.variable].cap = ovr.max_val

    if corr_overrides:
        for ovr in corr_overrides:
            try:
                i = VARIABLE_ORDER.index(ovr.var1)
                j = VARIABLE_ORDER.index(ovr.var2)
                C[i, j] = ovr.correlation
                C[j, i] = ovr.correlation
            except ValueError:
                pass

    return specs, C
