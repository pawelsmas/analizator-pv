"""
Modele danych dla symulacji Monte Carlo.

Obsługiwane rozkłady:
- normal: Rozkład normalny (ceny energii, degradacja)
- triangular: Rozkład trójkątny (szacunki ekspertowe)
- uniform: Rozkład jednostajny (brak wiedzy)
- lognormal: Rozkład log-normalny (CAPEX, ceny - tylko dodatnie)
"""

from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator


class DistributionType(str, Enum):
    """Typy rozkładów prawdopodobieństwa."""
    NORMAL = "normal"
    TRIANGULAR = "triangular"
    UNIFORM = "uniform"
    LOGNORMAL = "lognormal"


class ParameterDistribution(BaseModel):
    """Definicja rozkładu dla pojedynczego parametru."""

    name: str = Field(..., description="Nazwa parametru (np. 'electricity_price')")
    dist_type: DistributionType = Field(
        default=DistributionType.NORMAL,
        description="Typ rozkładu prawdopodobieństwa"
    )
    base_value: float = Field(..., description="Wartość bazowa parametru")

    # Parametry dla rozkładu normalnego
    std_dev: Optional[float] = Field(
        None,
        description="Odchylenie standardowe (dla normal/lognormal)"
    )
    std_dev_pct: Optional[float] = Field(
        None,
        description="Odchylenie standardowe jako % wartości bazowej"
    )

    # Parametry dla triangular/uniform
    min_val: Optional[float] = Field(
        None,
        description="Wartość minimalna (dla triangular/uniform)"
    )
    max_val: Optional[float] = Field(
        None,
        description="Wartość maksymalna (dla triangular/uniform)"
    )
    mode_val: Optional[float] = Field(
        None,
        description="Wartość modalna (dla triangular, domyślnie base_value)"
    )

    # Granice wartości (clipping)
    clip_min: Optional[float] = Field(
        None,
        description="Minimalna dopuszczalna wartość (obcięcie rozkładu)"
    )
    clip_max: Optional[float] = Field(
        None,
        description="Maksymalna dopuszczalna wartość (obcięcie rozkładu)"
    )

    @field_validator('std_dev_pct')
    @classmethod
    def validate_std_dev_pct(cls, v):
        if v is not None and v < 0:
            raise ValueError("std_dev_pct musi być >= 0")
        return v

    def get_effective_std_dev(self) -> float:
        """Zwraca efektywne odchylenie standardowe."""
        if self.std_dev is not None:
            return self.std_dev
        if self.std_dev_pct is not None:
            return self.base_value * (self.std_dev_pct / 100.0)
        # Domyślnie 10% wartości bazowej
        return abs(self.base_value) * 0.10


class CorrelationPair(BaseModel):
    """Korelacja między dwoma parametrami."""

    param1: str = Field(..., description="Nazwa pierwszego parametru")
    param2: str = Field(..., description="Nazwa drugiego parametru")
    correlation: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="Współczynnik korelacji [-1, 1]"
    )


class MonteCarloRequest(BaseModel):
    """Żądanie pełnej symulacji Monte Carlo."""

    n_simulations: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Liczba symulacji (100-100000)"
    )

    parameters: List[ParameterDistribution] = Field(
        ...,
        min_length=1,
        description="Lista parametrów z rozkładami"
    )

    correlations: Optional[List[CorrelationPair]] = Field(
        None,
        description="Lista korelacji między parametrami"
    )

    # Dane bazowe do obliczeń ekonomicznych
    base_economics: Dict[str, Any] = Field(
        ...,
        description="Bazowe dane ekonomiczne (variant + parameters)"
    )

    # Opcje wyjściowe
    return_distributions: bool = Field(
        default=False,
        description="Czy zwracać pełne rozkłady (może być duże)"
    )

    histogram_bins: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Liczba przedziałów histogramu"
    )

    random_seed: Optional[int] = Field(
        None,
        description="Ziarno generatora losowego (dla powtarzalności)"
    )


class QuickMonteCarloRequest(BaseModel):
    """
    Uproszczone żądanie Monte Carlo z domyślnymi parametrami.

    Wartości domyślne zgodne ze standardami branżowymi (bankable):
    - Cena energii: 12% (FfE European Prices 2024, IMF volatility)
    - Produkcja: 8% (NREL P50/P90: GHI 3.5% + PV sim 5%)
    - CAPEX: 8% (post-EPC bid standard)
    - Inflacja: 1.5pp (NBP target ±1pp + margin)
    """

    n_simulations: int = Field(default=5000, ge=100, le=50000)

    # Bazowe dane ekonomiczne
    base_economics: Dict[str, Any] = Field(
        ...,
        description="Bazowe dane ekonomiczne"
    )

    # Uproszczone ustawienia niepewności (jako % odchylenia)
    # Bankable defaults based on industry standards
    electricity_price_uncertainty_pct: float = Field(
        default=12.0,  # FfE, IMF 2024: Poland volatility ~12-15%
        ge=0,
        le=30,  # Reduced max - beyond 30% not credible
        description="Niepewność ceny energii [%] (standard: 12%)"
    )
    production_uncertainty_pct: float = Field(
        default=8.0,  # NREL/SolarGIS: sqrt(3.5²+5²) ≈ 6.1% + buffer
        ge=0,
        le=20,  # Reduced max - beyond 20% not realistic
        description="Niepewność produkcji PV [%] (standard: 8%)"
    )
    capex_uncertainty_pct: float = Field(
        default=8.0,  # Post-EPC bid: 5-8%
        ge=0,
        le=20,  # Reduced max
        description="Niepewność CAPEX [%] (standard: 8%)"
    )
    inflation_uncertainty_pct: float = Field(
        default=1.5,  # NBP target 2.5% ±1pp + margin
        ge=0,
        le=5,  # Reduced max - beyond 5pp unrealistic
        description="Niepewność inflacji [pp] (standard: 1.5pp)"
    )

    # Preset korelacji
    use_default_correlations: bool = Field(
        default=True,
        description="Użyj domyślnych korelacji"
    )

    # Return full distributions for Excel export
    return_distributions: bool = Field(
        default=False,
        description="Zwróć pełne rozkłady NPV/IRR/Payback (dla eksportu do Excel)"
    )


class HistogramData(BaseModel):
    """Dane histogramu dla wizualizacji."""

    bins: List[float] = Field(..., description="Granice przedziałów")
    counts: List[int] = Field(..., description="Liczności w przedziałach")
    bin_centers: List[float] = Field(..., description="Środki przedziałów")


class RiskMetrics(BaseModel):
    """Metryki ryzyka finansowego."""

    probability_positive: float = Field(
        ...,
        ge=0,
        le=1,
        description="Prawdopodobieństwo zysku (NPV > 0)"
    )

    var_95: float = Field(
        ...,
        description="Value at Risk 95% (5-ty percentyl NPV)"
    )

    var_99: float = Field(
        ...,
        description="Value at Risk 99% (1-szy percentyl NPV)"
    )

    cvar_95: float = Field(
        ...,
        description="Conditional VaR 95% (Expected Shortfall)"
    )

    expected_value: float = Field(
        ...,
        description="Wartość oczekiwana NPV"
    )

    standard_deviation: float = Field(
        ...,
        description="Odchylenie standardowe NPV"
    )

    coefficient_of_variation: float = Field(
        ...,
        description="Współczynnik zmienności (std/mean)"
    )

    downside_risk: float = Field(
        ...,
        description="Semi-odchylenie (tylko ujemne odchylenia)"
    )

    sharpe_ratio: Optional[float] = Field(
        None,
        description="Sharpe ratio (jeśli dostępna stopa wolna od ryzyka)"
    )


class PercentileResults(BaseModel):
    """Wyniki dla kluczowych percentyli."""

    p5: float = Field(..., description="5-ty percentyl (pesymistyczny)")
    p10: float = Field(..., description="10-ty percentyl")
    p25: float = Field(..., description="25-ty percentyl (Q1)")
    p50: float = Field(..., description="50-ty percentyl (mediana)")
    p75: float = Field(..., description="75-ty percentyl (Q3)")
    p90: float = Field(..., description="90-ty percentyl")
    p95: float = Field(..., description="95-ty percentyl (optymistyczny)")


class MonteCarloResult(BaseModel):
    """Pełny wynik symulacji Monte Carlo."""

    # Informacje o symulacji
    n_simulations: int = Field(..., description="Wykonana liczba symulacji")
    parameters_analyzed: List[str] = Field(..., description="Analizowane parametry")
    computation_time_ms: float = Field(..., description="Czas obliczeń [ms]")

    # Wyniki NPV
    npv_mean: float = Field(..., description="Średnie NPV")
    npv_std: float = Field(..., description="Odchylenie standardowe NPV")
    npv_percentiles: PercentileResults = Field(..., description="Percentyle NPV")
    npv_histogram: HistogramData = Field(..., description="Histogram NPV")

    # Wyniki IRR
    irr_mean: Optional[float] = Field(None, description="Średnie IRR")
    irr_std: Optional[float] = Field(None, description="Odchylenie standardowe IRR")
    irr_percentiles: Optional[PercentileResults] = Field(None, description="Percentyle IRR")
    irr_histogram: Optional[HistogramData] = Field(None, description="Histogram IRR")
    irr_valid_pct: float = Field(
        default=100.0,
        description="% symulacji z prawidłowym IRR"
    )

    # Wyniki Payback
    payback_mean: Optional[float] = Field(None, description="Średni payback")
    payback_std: Optional[float] = Field(None, description="Odchylenie standardowe payback")
    payback_percentiles: Optional[PercentileResults] = Field(None, description="Percentyle payback")
    payback_histogram: Optional[HistogramData] = Field(None, description="Histogram payback")

    # Metryki ryzyka
    risk_metrics: RiskMetrics = Field(..., description="Metryki ryzyka")

    # Pełne rozkłady (opcjonalne)
    npv_distribution: Optional[List[float]] = Field(
        None,
        description="Pełny rozkład NPV (jeśli return_distributions=True)"
    )
    irr_distribution: Optional[List[float]] = Field(
        None,
        description="Pełny rozkład IRR (jeśli return_distributions=True)"
    )
    payback_distribution: Optional[List[float]] = Field(
        None,
        description="Pełny rozkład Payback (jeśli return_distributions=True)"
    )

    # Próbkowane parametry wejściowe (opcjonalne, dla pełnego eksportu)
    sampled_electricity_prices: Optional[List[float]] = Field(
        None,
        description="Próbkowane ceny energii [PLN/MWh] dla każdego scenariusza"
    )
    sampled_production_factors: Optional[List[float]] = Field(
        None,
        description="Próbkowane współczynniki produkcji (1.0 = bazowa) dla każdego scenariusza"
    )
    sampled_investment_costs: Optional[List[float]] = Field(
        None,
        description="Próbkowane koszty inwestycji [PLN/kWp] dla każdego scenariusza"
    )
    sampled_inflation_rates: Optional[List[float]] = Field(
        None,
        description="Próbkowane stopy inflacji dla każdego scenariusza"
    )

    # Wnioski i insights
    insights: List[str] = Field(
        default_factory=list,
        description="Automatycznie wygenerowane wnioski"
    )

    # Breakeven analysis
    breakeven_price: Optional[float] = Field(
        None,
        description="Cena energii przy której NPV=0"
    )

    # Scenariusze (payback może być None gdy zwrot nie następuje w okresie analizy)
    scenario_base: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Wynik scenariusza bazowego"
    )
    scenario_pessimistic: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Wynik scenariusza pesymistycznego (P10)"
    )
    scenario_optimistic: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Wynik scenariusza optymistycznego (P90)"
    )


class ParameterPreset(BaseModel):
    """Preset konfiguracji parametrów."""

    name: str = Field(..., description="Nazwa presetu")
    description: str = Field(..., description="Opis presetu")
    parameters: List[ParameterDistribution] = Field(
        ...,
        description="Lista parametrów z rozkładami"
    )
    correlations: Optional[List[CorrelationPair]] = Field(
        None,
        description="Korelacje między parametrami"
    )
    risk_profile: str = Field(
        default="moderate",
        description="Profil ryzyka: conservative, moderate, optimistic"
    )
