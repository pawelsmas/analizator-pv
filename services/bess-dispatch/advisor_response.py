"""
BESS Advisor Response Generator
===============================

Generates intelligent, human-readable recommendations based on sizing results.
Implements the "BESS Advisor" system prompt logic directly in backend.

Version: 2.0.0

Zasady:
1) Nie gwarantuje oszczędności - wszystko to "szacunki na bazie danych i założeń"
2) Pilnuje jednostek (kW_avg, kWh)
3) Pokazuje warnings z API
4) Używa snap-to-SKU dla realnych produktów
5) Format: markdown + strukturalny JSON
6) Waliduje dane wejściowe przed przetworzeniem (KROK 0)
7) Re-ewaluuje ekonomię po snap-to-SKU (KROK 2C-D)
8) Analizuje oszczędności PV vs BESS vs Arbitraż (KROK 3)
9) Rekomenduje taryfę C11/C12a/C12b (KROK 4)
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sku_catalog import (
    snap_to_sku,
    get_alternative_skus,
    format_sku_for_display,
    SnappedSKU,
    DEFAULT_CAPEX_PER_KWH,
    DEFAULT_CAPEX_PER_KW,
)


# =============================================================================
# KROK 0: WALIDACJA WEJŚCIA
# =============================================================================

class ValidationErrorCode(str, Enum):
    """Error codes for input validation"""
    PROFILE_LENGTH_MISMATCH = "PROFILE_LENGTH_MISMATCH"
    PROFILE_EMPTY = "PROFILE_EMPTY"
    INVALID_INTERVAL = "INVALID_INTERVAL"
    MISSING_PEAK_LIMIT = "MISSING_PEAK_LIMIT"
    INVALID_CAPEX = "INVALID_CAPEX"
    INVALID_ANALYSIS_YEARS = "INVALID_ANALYSIS_YEARS"
    INVALID_DISCOUNT_RATE = "INVALID_DISCOUNT_RATE"
    INVALID_EFFICIENCY = "INVALID_EFFICIENCY"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"


@dataclass
class ValidationError:
    """Single validation error"""
    code: ValidationErrorCode
    message: str
    field: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ValidationResult:
    """Result of input validation"""
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [
                {"code": e.code.value, "message": e.message, "field": e.field}
                for e in self.errors
            ],
            "warnings": [
                {"code": w.code.value, "message": w.message, "field": w.field}
                for w in self.warnings
            ],
        }


def validate_advisor_input(
    pv_generation_kw: Optional[List[float]] = None,
    load_kw: Optional[List[float]] = None,
    interval_minutes: int = 60,
    mode: str = "self_consumption",
    peak_limit_kw: Optional[float] = None,
    capex_per_kwh: float = DEFAULT_CAPEX_PER_KWH,
    capex_per_kw: float = DEFAULT_CAPEX_PER_KW,
    analysis_years: int = 15,
    discount_rate: float = 0.10,
    roundtrip_efficiency: float = 0.90,
) -> ValidationResult:
    """
    Validate all input parameters before calling sizing API.

    KROK 0: Input validations - bez pominięcia tego wywołanie /sizing NIE powinno
    zostać wykonane.

    Args:
        pv_generation_kw: PV generation profile [kW_avg]
        load_kw: Load profile [kW_avg]
        interval_minutes: Data interval (60 or 15)
        mode: Sizing mode (self_consumption, stacked, peak_shaving)
        peak_limit_kw: Peak limit for stacked/peak_shaving modes
        capex_per_kwh: CAPEX per kWh (must be > 0)
        capex_per_kw: CAPEX per kW (can be >= 0)
        analysis_years: Years for analysis (must be > 0)
        discount_rate: Discount rate (must be >= 0)
        roundtrip_efficiency: Battery efficiency (must be in (0, 1])

    Returns:
        ValidationResult with is_valid flag, errors, and warnings
    """
    errors = []
    warnings = []

    # 1. Profile length validation
    if pv_generation_kw is None or len(pv_generation_kw) == 0:
        errors.append(ValidationError(
            code=ValidationErrorCode.PROFILE_EMPTY,
            message="PV generation profile jest pusty lub nie został podany",
            field="pv_generation_kw",
        ))

    if load_kw is None or len(load_kw) == 0:
        errors.append(ValidationError(
            code=ValidationErrorCode.PROFILE_EMPTY,
            message="Load profile jest pusty lub nie został podany",
            field="load_kw",
        ))

    # 2. Profile length match
    if pv_generation_kw and load_kw:
        if len(pv_generation_kw) != len(load_kw):
            errors.append(ValidationError(
                code=ValidationErrorCode.PROFILE_LENGTH_MISMATCH,
                message=f"Długość profili się nie zgadza: PV={len(pv_generation_kw)}, Load={len(load_kw)}",
                field="pv_generation_kw,load_kw",
            ))

    # 3. Interval validation
    if interval_minutes not in (60, 15):
        errors.append(ValidationError(
            code=ValidationErrorCode.INVALID_INTERVAL,
            message=f"interval_minutes musi być 60 lub 15, podano: {interval_minutes}",
            field="interval_minutes",
        ))

    # 4. Peak limit for stacked/peak_shaving modes
    if mode in ("stacked", "peak_shaving") and (peak_limit_kw is None or peak_limit_kw <= 0):
        errors.append(ValidationError(
            code=ValidationErrorCode.MISSING_PEAK_LIMIT,
            message=f"Tryb '{mode}' wymaga peak_limit_kw > 0",
            field="peak_limit_kw",
        ))

    # 5. CAPEX validation
    if capex_per_kwh <= 0:
        errors.append(ValidationError(
            code=ValidationErrorCode.INVALID_CAPEX,
            message=f"capex_per_kwh musi być > 0, podano: {capex_per_kwh}",
            field="capex_per_kwh",
        ))

    if capex_per_kw < 0:
        warnings.append(ValidationError(
            code=ValidationErrorCode.INVALID_CAPEX,
            message=f"capex_per_kw jest ujemne: {capex_per_kw}",
            field="capex_per_kw",
            severity="warning",
        ))

    # 6. Analysis years validation
    if analysis_years <= 0:
        errors.append(ValidationError(
            code=ValidationErrorCode.INVALID_ANALYSIS_YEARS,
            message=f"analysis_years musi być > 0, podano: {analysis_years}",
            field="analysis_years",
        ))
    elif analysis_years > 30:
        warnings.append(ValidationError(
            code=ValidationErrorCode.INVALID_ANALYSIS_YEARS,
            message=f"analysis_years={analysis_years} jest bardzo długi (>30 lat)",
            field="analysis_years",
            severity="warning",
        ))

    # 7. Discount rate validation
    if discount_rate < 0:
        errors.append(ValidationError(
            code=ValidationErrorCode.INVALID_DISCOUNT_RATE,
            message=f"discount_rate musi być >= 0, podano: {discount_rate}",
            field="discount_rate",
        ))
    elif discount_rate > 0.20:
        warnings.append(ValidationError(
            code=ValidationErrorCode.INVALID_DISCOUNT_RATE,
            message=f"discount_rate={discount_rate*100:.0f}% jest bardzo wysoka (>20%)",
            field="discount_rate",
            severity="warning",
        ))

    # 8. Roundtrip efficiency validation
    if roundtrip_efficiency <= 0 or roundtrip_efficiency > 1:
        errors.append(ValidationError(
            code=ValidationErrorCode.INVALID_EFFICIENCY,
            message=f"roundtrip_efficiency musi być w (0, 1], podano: {roundtrip_efficiency}",
            field="roundtrip_efficiency",
        ))
    elif roundtrip_efficiency < 0.80:
        warnings.append(ValidationError(
            code=ValidationErrorCode.INVALID_EFFICIENCY,
            message=f"roundtrip_efficiency={roundtrip_efficiency*100:.0f}% jest niskie (<80%)",
            field="roundtrip_efficiency",
            severity="warning",
        ))

    # 9. Profile data validation (check for negative values, NaN, etc.)
    if pv_generation_kw:
        neg_count = sum(1 for v in pv_generation_kw if v < 0)
        if neg_count > 0:
            warnings.append(ValidationError(
                code=ValidationErrorCode.INVALID_NUMERIC_VALUE,
                message=f"PV profile zawiera {neg_count} ujemnych wartości",
                field="pv_generation_kw",
                severity="warning",
            ))

    if load_kw:
        neg_count = sum(1 for v in load_kw if v < 0)
        if neg_count > 0:
            warnings.append(ValidationError(
                code=ValidationErrorCode.INVALID_NUMERIC_VALUE,
                message=f"Load profile zawiera {neg_count} ujemnych wartości",
                field="load_kw",
                severity="warning",
            ))

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
    )


@dataclass
class SavingsBreakdownAdvisor:
    """Breakdown of savings for advisor display"""
    energy_savings_pln: float = 0.0
    arbitrage_savings_pln: float = 0.0
    capacity_fee_savings_pln: float = 0.0
    demand_charge_savings_pln: float = 0.0
    degradation_cost_pln: float = 0.0
    net_savings_pln: float = 0.0


@dataclass
class EconomicsAdvisor:
    """Economics summary for advisor display"""
    capex_pln: float = 0.0
    annual_savings_pln: float = 0.0
    npv_pln: float = 0.0
    irr_pct: Optional[float] = None
    simple_payback_years: float = 0.0


@dataclass
class RecommendedVariantAdvisor:
    """
    Recommended variant for advisor display.

    OUTPUT CONTRACT rules:
    - variant: "small"|"medium"|"large" dla klasy, lub "custom" jeśli SKU-snapped
    - variant_label: np. "Medium (2h class) SKU-snapped" gdy snap zmienił parametry
    - sku: ZAWSZE wypełnione po snap-to-market (nigdy None w produkcji)
    """
    variant: str  # "small", "medium", "large", "custom"
    variant_label: str  # "Medium (2h)" lub "Medium (2h class) SKU-snapped"
    duration_h: float
    # Continuous (optimized) values - pre-snap
    power_kw: float
    energy_kwh: float
    c_rate: float
    # Snapped SKU values - ALWAYS filled after snap-to-market
    sku: Optional[Dict[str, Any]] = None
    # Flag indicating if SKU differs significantly from optimization
    is_sku_snapped: bool = False
    sku_mismatch_warning: Optional[str] = None


@dataclass
class TariffRecommendation:
    """Tariff recommendation for advisor display (KROK 4)"""
    current_tariff: str
    recommended_tariff: str
    annual_savings_delta_pln: float
    min_spread_for_profitability_pln_mwh: float
    recommendation: str
    confidence: str  # "high", "medium", "low"
    # Detailed tariff comparison (new in v2.0.0)
    c11_cost_pln: float = 0.0
    c12a_cost_pln: float = 0.0
    c12b_cost_pln: float = 0.0
    c11_with_bess_pln: float = 0.0
    c12a_with_bess_pln: float = 0.0
    c12b_with_bess_pln: float = 0.0


@dataclass
class SavingsComparison:
    """
    KROK 3: Porównanie scenariuszy oszczędności

    Analizuje 3 scenariusze:
    1. PV-only (bez BESS) - baseline
    2. PV + BESS (self-consumption) - autokonsumpcja
    3. PV + BESS + Arbitraż - z aktywnym handlem ToU
    """
    # Scenario 1: PV-only baseline
    pv_only_savings_pln: float = 0.0
    pv_only_self_consumption_pct: float = 0.0
    pv_only_exported_kwh: float = 0.0
    pv_only_export_revenue_pln: float = 0.0

    # Scenario 2: PV + BESS (self-consumption only)
    pv_bess_savings_pln: float = 0.0
    pv_bess_self_consumption_pct: float = 0.0
    pv_bess_stored_kwh: float = 0.0
    pv_bess_additional_savings_pln: float = 0.0  # vs PV-only

    # Scenario 3: PV + BESS + Arbitrage
    pv_bess_arb_savings_pln: float = 0.0
    arbitrage_cycles_per_year: float = 0.0
    arbitrage_revenue_pln: float = 0.0
    arbitrage_additional_savings_pln: float = 0.0  # vs PV+BESS

    # Summary
    best_scenario: str = ""  # "pv_only", "pv_bess", "pv_bess_arbitrage"
    incremental_bess_value_pln: float = 0.0
    incremental_arbitrage_value_pln: float = 0.0


@dataclass
class ReEvaluatedEconomics:
    """
    KROK 2C-D: Re-ewaluacja ekonomii po snap-to-SKU

    Przechowuje wyniki przed i po snap, pokazując różnicę.
    """
    # Pre-snap (continuous optimization)
    pre_snap_power_kw: float = 0.0
    pre_snap_energy_kwh: float = 0.0
    pre_snap_capex_pln: float = 0.0
    pre_snap_npv_pln: float = 0.0
    pre_snap_irr_pct: Optional[float] = None

    # Post-snap (market SKU)
    post_snap_power_kw: float = 0.0
    post_snap_energy_kwh: float = 0.0
    post_snap_capex_pln: float = 0.0
    post_snap_npv_pln: float = 0.0
    post_snap_irr_pct: Optional[float] = None

    # Delta
    capex_increase_pln: float = 0.0
    capex_increase_pct: float = 0.0
    npv_change_pln: float = 0.0
    irr_change_pct: Optional[float] = None

    # Flag for economics re-evaluation quality
    re_evaluated: bool = False
    re_evaluation_note: str = ""


@dataclass
class AdvisorAssumptions:
    """Assumptions used in calculations"""
    discount_rate: float
    analysis_years: int
    capex_per_kwh: float
    capex_per_kw: float
    roundtrip_efficiency: float
    degradation_year1_pct: float  # First year degradation [%]
    degradation_years2plus_pct: float  # Years 2+ degradation [%/year]
    soc_window: str  # "10%-90%"


@dataclass
class AdvisorResponse:
    """
    Complete advisor response structure.

    This is returned as part of SizingResult for frontend consumption.
    Contains both markdown text and structured JSON.

    Version 2.0.0 OUTPUT CONTRACT:
    - recommended_variant: ma być "SKU-snapped" jeśli używasz snap-to-market
    - alternatives: top 3 warianty SKU (po snap i re-ewaluacji) - NIGDY raw optimization
    - tariff_recommendation: dodaj tylko jeśli user pyta o taryfy lub włączony arbitraż
    - assumptions: ZAWSZE wypełnij (buduje zaufanie)
    - warnings: zlep walidacje + API warnings + "model vs SKU mismatch"

    Version 2.0.0 additions:
    - input_validation: Result of KROK 0 validation
    - re_evaluated_economics: KROK 2C-D post-snap economics
    - savings_comparison: KROK 3 scenario analysis
    - Enhanced tariff_recommendation: KROK 4 with C11/C12a/C12b comparison
    """
    # Markdown text for UI
    markdown_text: str

    # Structured data - ALWAYS SKU-snapped values
    recommended_variant: RecommendedVariantAdvisor
    economics: EconomicsAdvisor
    savings_breakdown: SavingsBreakdownAdvisor

    # Alternatives (top 3 SKUs) - MUST be post-snap and re-evaluated
    alternatives: List[Dict[str, Any]] = field(default_factory=list)

    # KROK 0: Input validation result
    input_validation: Optional[Dict[str, Any]] = None

    # KROK 2C-D: Re-evaluated economics post-snap
    re_evaluated_economics: Optional[ReEvaluatedEconomics] = None

    # KROK 3: Savings comparison (PV-only vs PV+BESS vs PV+BESS+Arb)
    savings_comparison: Optional[SavingsComparison] = None

    # Tariff recommendation - only if arbitrage enabled or user asks
    tariff_recommendation: Optional[TariffRecommendation] = None

    # Assumptions - ALWAYS filled (builds trust)
    assumptions: Optional[AdvisorAssumptions] = None

    # Warnings - merged: validation + API + SKU mismatch
    warnings: List[str] = field(default_factory=list)

    # Metadata
    generated_at: str = ""
    advisor_version: str = "2.0.0"


# =============================================================================
# MARKDOWN GENERATORS
# =============================================================================

def _generate_recommendation_header(
    variant_label: str,
    power_kw: float,
    energy_kwh: float,
    sku: Optional[SnappedSKU] = None,
) -> str:
    """Generate recommendation header with SKU info"""

    if sku:
        return f"""## 🔋 Rekomendacja: {variant_label} - {sku.power_kw:.0f} kW / {sku.energy_kwh:.0f} kWh

**Konfiguracja rynkowa (snap-to-SKU):**
- PCS: {sku.pcs_model}
- Bateria: {sku.battery_config}
- Duration: {sku.duration_h:.1f}h | C-rate: {sku.c_rate:.2f}C
"""
    else:
        return f"""## 🔋 Rekomendacja: {variant_label} - {power_kw:.0f} kW / {energy_kwh:.0f} kWh
"""


def _generate_economics_table(economics: EconomicsAdvisor) -> str:
    """Generate economics summary table"""

    irr_str = f"{economics.irr_pct:.1f}%" if economics.irr_pct else "N/A"

    return f"""### Ekonomia (szacunek)

| Wskaźnik | Wartość |
|----------|---------|
| CAPEX | {economics.capex_pln:,.0f} PLN |
| Roczne oszczędności | {economics.annual_savings_pln:,.0f} PLN |
| NPV ({15} lat) | {economics.npv_pln:,.0f} PLN |
| IRR | {irr_str} |
| Prosty zwrot | {economics.simple_payback_years:.1f} lat |

⚠️ *Powyższe wartości to szacunki oparte na założeniach i danych historycznych. Rzeczywiste wyniki mogą się różnić.*
"""


def _generate_savings_breakdown(breakdown: SavingsBreakdownAdvisor) -> str:
    """Generate savings breakdown section"""

    total = breakdown.net_savings_pln
    if total <= 0:
        return """### Podział oszczędności
*Brak dodatnich oszczędności netto.*
"""

    # Calculate percentages
    def pct(value: float) -> str:
        if total > 0:
            return f"({value/total*100:.0f}%)"
        return ""

    lines = ["### Podział oszczędności rocznych\n"]

    if breakdown.energy_savings_pln > 0:
        lines.append(f"- Autokonsumpcja: {breakdown.energy_savings_pln:,.0f} PLN {pct(breakdown.energy_savings_pln)}")

    if breakdown.capacity_fee_savings_pln > 0:
        lines.append(f"- Opłata mocowa: {breakdown.capacity_fee_savings_pln:,.0f} PLN {pct(breakdown.capacity_fee_savings_pln)}")

    if breakdown.arbitrage_savings_pln > 0:
        lines.append(f"- Arbitraż ToU: {breakdown.arbitrage_savings_pln:,.0f} PLN {pct(breakdown.arbitrage_savings_pln)}")

    if breakdown.demand_charge_savings_pln > 0:
        lines.append(f"- Peak shaving: {breakdown.demand_charge_savings_pln:,.0f} PLN {pct(breakdown.demand_charge_savings_pln)}")

    if breakdown.degradation_cost_pln > 0:
        lines.append(f"- Koszt degradacji: -{breakdown.degradation_cost_pln:,.0f} PLN")

    return "\n".join(lines)


def _generate_alternatives_table(alternatives: List[Dict[str, Any]]) -> str:
    """Generate alternatives comparison table"""

    if not alternatives:
        return ""

    lines = [
        "\n### Alternatywne konfiguracje\n",
        "| Wariant | Moc | Pojemność | Duration | CAPEX (szac.) |",
        "|---------|-----|-----------|----------|---------------|",
    ]

    for alt in alternatives:
        power = alt.get("power_kw", 0)
        energy = alt.get("energy_kwh", 0)
        duration = alt.get("duration_h", 0)
        # Estimate CAPEX
        capex = energy * 1500 + power * 300

        lines.append(
            f"| {alt.get('pcs_model', 'N/A')} | {power:.0f} kW | {energy:.0f} kWh | {duration:.1f}h | {capex:,.0f} PLN |"
        )

    return "\n".join(lines)


def _generate_warnings_section(warnings: List[str]) -> str:
    """Generate warnings section"""

    if not warnings:
        return ""

    lines = ["\n### ⚠️ Uwagi\n"]
    for w in warnings:
        lines.append(f"- {w}")

    return "\n".join(lines)


def _generate_tariff_recommendation(tariff_rec: Optional[TariffRecommendation]) -> str:
    """Generate tariff recommendation section"""

    if not tariff_rec:
        return ""

    emoji = "✅" if tariff_rec.confidence == "high" else "⚡" if tariff_rec.confidence == "medium" else "❓"

    return f"""
### 📊 Rekomendacja taryfowa

**Aktualna taryfa:** {tariff_rec.current_tariff}
**Proponowana:** {tariff_rec.recommended_tariff}

{emoji} {tariff_rec.recommendation}

- Dodatkowe oszczędności: ~{tariff_rec.annual_savings_delta_pln:,.0f} PLN/rok
- Min. spread dla opłacalności: {tariff_rec.min_spread_for_profitability_pln_mwh:.0f} PLN/MWh
"""


def _generate_assumptions_footnote(assumptions: Optional[AdvisorAssumptions]) -> str:
    """Generate assumptions footnote"""

    if not assumptions:
        return ""

    return f"""
---
<details>
<summary>Założenia kalkulacji</summary>

- Stopa dyskontowa: {assumptions.discount_rate*100:.1f}%
- Horyzont analizy: {assumptions.analysis_years} lat
- CAPEX: {assumptions.capex_per_kwh} PLN/kWh + {assumptions.capex_per_kw} PLN/kW
- Sprawność roundtrip: {assumptions.roundtrip_efficiency*100:.0f}%
- Degradacja rok 1: {assumptions.degradation_year1_pct}%
- Degradacja lata 2+: {assumptions.degradation_years2plus_pct}%/rok
- SOC window: {assumptions.soc_window}

</details>
"""


# =============================================================================
# MAIN GENERATOR
# =============================================================================

def generate_advisor_response(
    sizing_result: Dict[str, Any],
    capex_per_kwh: float = 1500.0,
    capex_per_kw: float = 300.0,
    include_tariff_recommendation: bool = False,  # Changed: only when arbitrage/user asks
    current_tariff: Optional[str] = "C11",
    include_savings_comparison: bool = True,
    include_re_evaluation: bool = True,
    energy_price_pln_kwh: float = 0.80,
    export_price_pln_kwh: float = 0.30,
    arbitrage_enabled: bool = False,  # New: explicit arbitrage flag
) -> AdvisorResponse:
    """
    Generate complete advisor response from sizing result.

    This is the main entry point for the advisor module.
    Version 2.0.0 with full KROK 0-5 implementation.

    OUTPUT CONTRACT (v2.0.0):
    - recommended_variant.variant: "small"|"medium"|"large" for class, "custom" if SKU significantly differs
    - recommended_variant.variant_label: adds "SKU-snapped" suffix when snap changed parameters
    - alternatives[]: ALWAYS post-snap and re-evaluated (never raw optimization values)
    - tariff_recommendation: only included when arbitrage_enabled=True or include_tariff_recommendation=True
    - assumptions: ALWAYS filled (builds trust with customer)
    - warnings: merged from validation + API + SKU mismatch

    Args:
        sizing_result: Raw SizingResult dict from run_sizing()
        capex_per_kwh: For SKU CAPEX calculation
        capex_per_kw: For SKU CAPEX calculation
        include_tariff_recommendation: Force include tariff advice (KROK 4)
        current_tariff: Current tariff for comparison
        include_savings_comparison: Whether to include PV vs BESS comparison (KROK 3)
        include_re_evaluation: Whether to include post-snap economics (KROK 2C-D)
        energy_price_pln_kwh: Energy price for savings calculations
        export_price_pln_kwh: Export price for PV-only scenario
        arbitrage_enabled: If True, auto-include tariff recommendation

    Returns:
        AdvisorResponse with markdown text and structured JSON
    """
    warnings = list(sizing_result.get("warnings", []))

    # Extract recommended variant
    variants = sizing_result.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), variants[0] if variants else {})

    # Get continuous values (pre-snap optimization)
    power_kw = recommended.get("power_kw", 0)
    energy_kwh = recommended.get("energy_kwh", 0)
    variant_name = recommended.get("variant", "medium")
    variant_label = recommended.get("variant_label", "Medium (2h)")
    duration_h = recommended.get("duration_h", 2.0)

    # Snap to SKU
    sku = snap_to_sku(power_kw, energy_kwh, capex_per_kwh, capex_per_kw)
    sku_dict = format_sku_for_display(sku)
    warnings.extend(sku.warnings)

    # === OUTPUT CONTRACT: Detect significant SKU mismatch ===
    # Threshold: >5% power delta or >10% energy delta = "custom" variant
    POWER_THRESHOLD_PCT = 5.0
    ENERGY_THRESHOLD_PCT = 10.0

    is_sku_snapped = False
    sku_mismatch_warning = None
    final_variant_name = variant_name
    final_variant_label = variant_label

    power_delta_pct = abs(sku.power_delta_pct)
    energy_delta_pct = abs(sku.energy_delta_pct)

    if power_delta_pct > POWER_THRESHOLD_PCT or energy_delta_pct > ENERGY_THRESHOLD_PCT:
        is_sku_snapped = True
        final_variant_name = "custom"
        final_variant_label = f"{variant_label} SKU-snapped"

        # Build mismatch warning
        mismatch_parts = []
        if power_delta_pct > POWER_THRESHOLD_PCT:
            mismatch_parts.append(f"moc {sku.power_delta_pct:+.1f}%")
        if energy_delta_pct > ENERGY_THRESHOLD_PCT:
            mismatch_parts.append(f"pojemność {sku.energy_delta_pct:+.1f}%")

        sku_mismatch_warning = (
            f"SKU rynkowe różni się od optymalizacji: {', '.join(mismatch_parts)}. "
            f"Przed snap: {power_kw:.0f}kW/{energy_kwh:.0f}kWh → "
            f"Po snap: {sku.power_kw:.0f}kW/{sku.energy_kwh:.0f}kWh"
        )
        warnings.append(sku_mismatch_warning)
    elif power_delta_pct > 0 or energy_delta_pct > 0:
        # Minor snap adjustment - note but don't change variant
        final_variant_label = f"{variant_label} (SKU)"

    # Get alternatives - MUST be post-snap (OUTPUT CONTRACT requirement)
    alt_skus = get_alternative_skus(power_kw, energy_kwh, 3, capex_per_kwh, capex_per_kw)
    alternatives = [format_sku_for_display(s) for s in alt_skus]

    # Build economics
    economics = EconomicsAdvisor(
        capex_pln=recommended.get("capex_pln", 0),
        annual_savings_pln=recommended.get("annual_savings_pln", 0),
        npv_pln=recommended.get("npv_pln", 0),
        irr_pct=recommended.get("irr_pct"),
        simple_payback_years=recommended.get("simple_payback_years", 0),
    )

    # Build savings breakdown
    sb = recommended.get("savings_breakdown", {})
    savings_breakdown = SavingsBreakdownAdvisor(
        energy_savings_pln=sb.get("energy_savings_pln", 0),
        arbitrage_savings_pln=sb.get("arbitrage_savings_pln", 0),
        capacity_fee_savings_pln=sb.get("capacity_fee_savings_pln", 0),
        demand_charge_savings_pln=sb.get("demand_charge_savings_pln", 0),
        degradation_cost_pln=sb.get("degradation_cost_pln", 0),
        net_savings_pln=sb.get("net_savings_pln", 0),
    )

    # Build assumptions - ALWAYS filled (OUTPUT CONTRACT requirement)
    applied = sizing_result.get("applied_parameters", {})
    # BESS analysis horizon is capped at 10 years
    analysis_years = min(applied.get("analysis_years", 15), 10)
    assumptions = AdvisorAssumptions(
        discount_rate=applied.get("discount_rate", 0.10),
        analysis_years=analysis_years,
        capex_per_kwh=capex_per_kwh,
        capex_per_kw=capex_per_kw,
        roundtrip_efficiency=applied.get("roundtrip_efficiency", 0.90),
        degradation_year1_pct=applied.get("bess_degradation_year1_pct", 3.0),
        degradation_years2plus_pct=applied.get("annual_degradation_pct", 2.0),
        soc_window=f"{applied.get('soc_min', 0.1)*100:.0f}%-{applied.get('soc_max', 0.9)*100:.0f}%",
    )

    # === KROK 2C-D: Re-evaluate economics post-snap ===
    re_evaluated_economics = None
    if include_re_evaluation:
        re_evaluated_economics = calculate_re_evaluated_economics(
            sizing_result, sku, capex_per_kwh, capex_per_kw
        )
        if re_evaluated_economics.re_evaluation_note:
            warnings.append(re_evaluated_economics.re_evaluation_note)

    # === KROK 3: Savings comparison ===
    savings_comparison = None
    if include_savings_comparison:
        savings_comparison = calculate_savings_comparison(
            sizing_result, energy_price_pln_kwh, export_price_pln_kwh
        )

    # === KROK 4: Enhanced tariff recommendation ===
    # OUTPUT CONTRACT: only when arbitrage enabled OR user explicitly asks
    tariff_rec = None
    should_include_tariff = include_tariff_recommendation or arbitrage_enabled
    # Also auto-include if arbitrage savings are significant (>1000 PLN/year)
    if savings_breakdown.arbitrage_savings_pln > 1000:
        should_include_tariff = True

    if should_include_tariff and current_tariff:
        total_load_mwh = sizing_result.get("total_load_mwh", 0)
        annual_load_kwh = total_load_mwh * 1000  # MWh to kWh
        tariff_rec = calculate_enhanced_tariff_recommendation(
            sizing_result, current_tariff, savings_breakdown, energy_kwh, annual_load_kwh
        )

    # Build recommended variant structure with OUTPUT CONTRACT fields
    recommended_variant = RecommendedVariantAdvisor(
        variant=final_variant_name,
        variant_label=final_variant_label,
        duration_h=duration_h,
        power_kw=power_kw,
        energy_kwh=energy_kwh,
        c_rate=power_kw / energy_kwh if energy_kwh > 0 else 0,
        sku=sku_dict,
        is_sku_snapped=is_sku_snapped,
        sku_mismatch_warning=sku_mismatch_warning,
    )

    # Add context warnings
    total_pv_mwh = sizing_result.get("total_pv_mwh", 0)
    total_load_mwh = sizing_result.get("total_load_mwh", 0)
    annual_surplus_mwh = sizing_result.get("annual_surplus_mwh", 0)

    if total_pv_mwh > 0 and annual_surplus_mwh / total_pv_mwh < 0.1:
        warnings.append(
            f"PV surplus jest niski ({annual_surplus_mwh:.0f} MWh/rok = {annual_surplus_mwh/total_pv_mwh*100:.0f}% produkcji). "
            "Rozważ zwiększenie instalacji PV dla lepszego ROI z BESS."
        )

    if economics.npv_pln < 0:
        warnings.append(
            "NPV jest ujemne - inwestycja może nie być opłacalna przy obecnych założeniach."
        )

    if economics.simple_payback_years > 10:
        warnings.append(
            f"Okres zwrotu ({economics.simple_payback_years:.1f} lat) przekracza 10 lat."
        )

    # === KROK 5: Generate markdown text with all sections ===
    markdown_parts = [
        _generate_recommendation_header(variant_label, power_kw, energy_kwh, sku),
        _generate_economics_table(economics),
        _generate_re_evaluation_markdown(re_evaluated_economics),
        _generate_savings_breakdown(savings_breakdown),
        _generate_savings_comparison_markdown(savings_comparison),
        _generate_alternatives_table(alternatives),
        _generate_enhanced_tariff_markdown(tariff_rec),
        _generate_warnings_section(warnings),
        _generate_assumptions_footnote(assumptions),
    ]

    markdown_text = "\n".join(part for part in markdown_parts if part)

    return AdvisorResponse(
        markdown_text=markdown_text,
        recommended_variant=recommended_variant,
        economics=economics,
        savings_breakdown=savings_breakdown,
        alternatives=alternatives,
        input_validation=None,  # Filled by caller if validation was done
        re_evaluated_economics=re_evaluated_economics,
        savings_comparison=savings_comparison,
        tariff_recommendation=tariff_rec,
        assumptions=assumptions,
        warnings=warnings,
        generated_at=datetime.utcnow().isoformat() + "Z",
        advisor_version="2.0.0",
    )


def _generate_tariff_advice(
    sizing_result: Dict[str, Any],
    current_tariff: str,
    savings_breakdown: SavingsBreakdownAdvisor,
) -> Optional[TariffRecommendation]:
    """
    Generate tariff recommendation based on profile analysis.

    This is a simplified heuristic. Full implementation would require
    running simulations with different tariffs.
    """

    # Simple heuristic: if arbitrage savings > 0, ToU tariff makes sense
    arb_savings = savings_breakdown.arbitrage_savings_pln

    if current_tariff == "C11":
        # Flat tariff - check if switching to ToU would help
        if arb_savings > 1000:  # Significant arbitrage opportunity
            return TariffRecommendation(
                current_tariff=current_tariff,
                recommended_tariff="C12a",
                annual_savings_delta_pln=arb_savings * 1.5,  # Estimate
                min_spread_for_profitability_pln_mwh=50.0,
                recommendation="Zmiana na C12a w połączeniu z BESS może zwiększyć oszczędności z arbitrażu.",
                confidence="medium",
            )
        else:
            return TariffRecommendation(
                current_tariff=current_tariff,
                recommended_tariff=current_tariff,
                annual_savings_delta_pln=0,
                min_spread_for_profitability_pln_mwh=50.0,
                recommendation="Pozostanie przy C11 jest uzasadnione - profil zużycia nie sprzyja arbitrażowi.",
                confidence="medium",
            )

    elif current_tariff == "C12a":
        # Already on 2-zone, check if 3-zone would help
        if arb_savings > 2000:
            return TariffRecommendation(
                current_tariff=current_tariff,
                recommended_tariff="C12b",
                annual_savings_delta_pln=arb_savings * 0.3,  # Marginal improvement
                min_spread_for_profitability_pln_mwh=100.0,
                recommendation="Rozważ C12b dla dodatkowych oszczędności w strefie nocnej.",
                confidence="low",
            )

    return None


# =============================================================================
# JSON SERIALIZATION
# =============================================================================

def advisor_response_to_dict(response: AdvisorResponse) -> Dict[str, Any]:
    """
    Convert AdvisorResponse to JSON-serializable dict.

    This is used for inclusion in API response.

    OUTPUT CONTRACT (v2.0.0):
    - recommended_variant includes is_sku_snapped and sku_mismatch_warning
    - alternatives[] are ALWAYS post-snap values
    - assumptions is ALWAYS present (never None)
    - warnings includes all merged warnings
    """
    result = {
        "markdown_text": response.markdown_text,
        "recommended_variant": {
            "variant": response.recommended_variant.variant,
            "variant_label": response.recommended_variant.variant_label,
            "duration_h": response.recommended_variant.duration_h,
            "power_kw": response.recommended_variant.power_kw,
            "energy_kwh": response.recommended_variant.energy_kwh,
            "c_rate": round(response.recommended_variant.c_rate, 2),
            "sku": response.recommended_variant.sku,
            # OUTPUT CONTRACT: SKU mismatch tracking
            "is_sku_snapped": response.recommended_variant.is_sku_snapped,
            "sku_mismatch_warning": response.recommended_variant.sku_mismatch_warning,
        },
        "economics": {
            "capex_pln": response.economics.capex_pln,
            "annual_savings_pln": response.economics.annual_savings_pln,
            "npv_pln": response.economics.npv_pln,
            "irr_pct": response.economics.irr_pct,
            "simple_payback_years": response.economics.simple_payback_years,
        },
        "savings_breakdown": {
            "energy_savings_pln": response.savings_breakdown.energy_savings_pln,
            "arbitrage_savings_pln": response.savings_breakdown.arbitrage_savings_pln,
            "capacity_fee_savings_pln": response.savings_breakdown.capacity_fee_savings_pln,
            "demand_charge_savings_pln": response.savings_breakdown.demand_charge_savings_pln,
            "degradation_cost_pln": response.savings_breakdown.degradation_cost_pln,
            "net_savings_pln": response.savings_breakdown.net_savings_pln,
        },
        "alternatives": response.alternatives,
        "warnings": response.warnings,
        "generated_at": response.generated_at,
        "advisor_version": response.advisor_version,
    }

    # Add optional fields only if present
    if response.tariff_recommendation:
        result["tariff_recommendation"] = {
            "current_tariff": response.tariff_recommendation.current_tariff,
            "recommended_tariff": response.tariff_recommendation.recommended_tariff,
            "annual_savings_delta_pln": response.tariff_recommendation.annual_savings_delta_pln,
            "min_spread_for_profitability_pln_mwh": response.tariff_recommendation.min_spread_for_profitability_pln_mwh,
            "recommendation": response.tariff_recommendation.recommendation,
            "confidence": response.tariff_recommendation.confidence,
        }

    if response.assumptions:
        result["assumptions"] = {
            "discount_rate": response.assumptions.discount_rate,
            "analysis_years": response.assumptions.analysis_years,
            "capex_per_kwh": response.assumptions.capex_per_kwh,
            "capex_per_kw": response.assumptions.capex_per_kw,
            "roundtrip_efficiency": response.assumptions.roundtrip_efficiency,
            "degradation_year1_pct": response.assumptions.degradation_year1_pct,
            "degradation_years2plus_pct": response.assumptions.degradation_years2plus_pct,
            "soc_window": response.assumptions.soc_window,
        }

    # Add v2.0.0 fields
    if response.input_validation:
        result["input_validation"] = response.input_validation

    if response.re_evaluated_economics:
        re = response.re_evaluated_economics
        result["re_evaluated_economics"] = {
            "pre_snap": {
                "power_kw": re.pre_snap_power_kw,
                "energy_kwh": re.pre_snap_energy_kwh,
                "capex_pln": re.pre_snap_capex_pln,
                "npv_pln": re.pre_snap_npv_pln,
                "irr_pct": re.pre_snap_irr_pct,
            },
            "post_snap": {
                "power_kw": re.post_snap_power_kw,
                "energy_kwh": re.post_snap_energy_kwh,
                "capex_pln": re.post_snap_capex_pln,
                "npv_pln": re.post_snap_npv_pln,
                "irr_pct": re.post_snap_irr_pct,
            },
            "delta": {
                "capex_increase_pln": re.capex_increase_pln,
                "capex_increase_pct": re.capex_increase_pct,
                "npv_change_pln": re.npv_change_pln,
                "irr_change_pct": re.irr_change_pct,
            },
            "re_evaluated": re.re_evaluated,
            "re_evaluation_note": re.re_evaluation_note,
        }

    if response.savings_comparison:
        sc = response.savings_comparison
        result["savings_comparison"] = {
            "pv_only": {
                "savings_pln": sc.pv_only_savings_pln,
                "self_consumption_pct": sc.pv_only_self_consumption_pct,
                "exported_kwh": sc.pv_only_exported_kwh,
                "export_revenue_pln": sc.pv_only_export_revenue_pln,
            },
            "pv_bess": {
                "savings_pln": sc.pv_bess_savings_pln,
                "self_consumption_pct": sc.pv_bess_self_consumption_pct,
                "stored_kwh": sc.pv_bess_stored_kwh,
                "additional_savings_pln": sc.pv_bess_additional_savings_pln,
            },
            "pv_bess_arbitrage": {
                "savings_pln": sc.pv_bess_arb_savings_pln,
                "arbitrage_cycles_per_year": sc.arbitrage_cycles_per_year,
                "arbitrage_revenue_pln": sc.arbitrage_revenue_pln,
                "additional_savings_pln": sc.arbitrage_additional_savings_pln,
            },
            "summary": {
                "best_scenario": sc.best_scenario,
                "incremental_bess_value_pln": sc.incremental_bess_value_pln,
                "incremental_arbitrage_value_pln": sc.incremental_arbitrage_value_pln,
            },
        }

    # Enhanced tariff recommendation (v2.0.0)
    if response.tariff_recommendation:
        tr = response.tariff_recommendation
        result["tariff_recommendation"]["tariff_costs"] = {
            "c11_base_pln": tr.c11_cost_pln,
            "c12a_base_pln": tr.c12a_cost_pln,
            "c12b_base_pln": tr.c12b_cost_pln,
            "c11_with_bess_pln": tr.c11_with_bess_pln,
            "c12a_with_bess_pln": tr.c12a_with_bess_pln,
            "c12b_with_bess_pln": tr.c12b_with_bess_pln,
        }

    return result


# =============================================================================
# KROK 2C-D: RE-EWALUACJA EKONOMII PO SNAP-TO-SKU
# =============================================================================

def calculate_re_evaluated_economics(
    sizing_result: Dict[str, Any],
    sku: SnappedSKU,
    capex_per_kwh: float = DEFAULT_CAPEX_PER_KWH,
    capex_per_kw: float = DEFAULT_CAPEX_PER_KW,
) -> ReEvaluatedEconomics:
    """
    KROK 2C-D: Calculate economics impact of snap-to-SKU.

    This compares the continuous optimization result with the snapped SKU values.
    In a full implementation, this would re-run the simulation with fixed SKU sizes.

    For now, we estimate the impact based on:
    - CAPEX delta (direct from snap)
    - Adjusted NPV/IRR based on capacity increase
    """
    # Extract pre-snap values from sizing result
    variants = sizing_result.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), variants[0] if variants else {})

    pre_power = recommended.get("power_kw", 0)
    pre_energy = recommended.get("energy_kwh", 0)
    pre_capex = recommended.get("capex_pln", 0)
    pre_npv = recommended.get("npv_pln", 0)
    pre_irr = recommended.get("irr_pct")

    # Post-snap values
    post_power = sku.power_kw
    post_energy = sku.energy_kwh
    post_capex = post_energy * capex_per_kwh + post_power * capex_per_kw

    # CAPEX delta
    capex_increase = post_capex - pre_capex
    capex_increase_pct = (capex_increase / pre_capex * 100) if pre_capex > 0 else 0

    # Estimate NPV impact
    # Assumption: Higher capacity gives proportionally more savings (simplified)
    energy_ratio = post_energy / pre_energy if pre_energy > 0 else 1.0
    # But CAPEX increase reduces NPV
    annual_savings = recommended.get("annual_savings_pln", 0)
    # Scaled savings based on energy increase
    scaled_annual_savings = annual_savings * min(energy_ratio, 1.2)  # Cap at 20% increase
    # NPV approximation: NPV = sum of discounted savings - CAPEX
    # Simplified: NPV delta ≈ CAPEX delta (since savings scale less than CAPEX)
    post_npv = pre_npv - capex_increase * 0.8  # 80% of CAPEX increase impacts NPV

    # IRR estimation (simplified)
    post_irr = None
    irr_change = None
    if pre_irr and pre_irr > 0:
        # IRR decreases roughly proportionally to CAPEX increase
        irr_factor = pre_capex / post_capex if post_capex > 0 else 1.0
        post_irr = pre_irr * irr_factor
        irr_change = post_irr - pre_irr

    re_evaluation_note = ""
    if capex_increase_pct > 15:
        re_evaluation_note = (
            f"Snap-to-SKU zwiększył CAPEX o {capex_increase_pct:.1f}%. "
            "Rozważ mniejszą konfigurację lub negocjacje cenowe z dostawcą."
        )
    elif capex_increase_pct > 5:
        re_evaluation_note = (
            f"Snap-to-SKU zwiększył CAPEX o {capex_increase_pct:.1f}%. "
            "To standardowa delta dla dostępnych SKU."
        )
    else:
        re_evaluation_note = "Snap-to-SKU miał minimalny wpływ na ekonomię."

    return ReEvaluatedEconomics(
        pre_snap_power_kw=pre_power,
        pre_snap_energy_kwh=pre_energy,
        pre_snap_capex_pln=pre_capex,
        pre_snap_npv_pln=pre_npv,
        pre_snap_irr_pct=pre_irr,
        post_snap_power_kw=post_power,
        post_snap_energy_kwh=post_energy,
        post_snap_capex_pln=post_capex,
        post_snap_npv_pln=post_npv,
        post_snap_irr_pct=post_irr,
        capex_increase_pln=capex_increase,
        capex_increase_pct=capex_increase_pct,
        npv_change_pln=post_npv - pre_npv,
        irr_change_pct=irr_change,
        re_evaluated=True,
        re_evaluation_note=re_evaluation_note,
    )


def _generate_re_evaluation_markdown(re_eval: Optional[ReEvaluatedEconomics]) -> str:
    """Generate markdown section for re-evaluated economics"""
    if not re_eval or not re_eval.re_evaluated:
        return ""

    delta_emoji = "📈" if re_eval.capex_increase_pct > 10 else "📊"

    lines = [
        f"\n### {delta_emoji} Wpływ snap-to-SKU na ekonomię\n",
        "| Parametr | Przed snap | Po snap | Delta |",
        "|----------|------------|---------|-------|",
        f"| Moc | {re_eval.pre_snap_power_kw:.0f} kW | {re_eval.post_snap_power_kw:.0f} kW | +{re_eval.post_snap_power_kw - re_eval.pre_snap_power_kw:.0f} kW |",
        f"| Pojemność | {re_eval.pre_snap_energy_kwh:.0f} kWh | {re_eval.post_snap_energy_kwh:.0f} kWh | +{re_eval.post_snap_energy_kwh - re_eval.pre_snap_energy_kwh:.0f} kWh |",
        f"| CAPEX | {re_eval.pre_snap_capex_pln:,.0f} PLN | {re_eval.post_snap_capex_pln:,.0f} PLN | +{re_eval.capex_increase_pln:,.0f} PLN ({re_eval.capex_increase_pct:+.1f}%) |",
        f"| NPV | {re_eval.pre_snap_npv_pln:,.0f} PLN | {re_eval.post_snap_npv_pln:,.0f} PLN | {re_eval.npv_change_pln:+,.0f} PLN |",
    ]

    if re_eval.pre_snap_irr_pct and re_eval.post_snap_irr_pct:
        lines.append(
            f"| IRR | {re_eval.pre_snap_irr_pct:.1f}% | {re_eval.post_snap_irr_pct:.1f}% | {re_eval.irr_change_pct:+.1f}% |"
        )

    if re_eval.re_evaluation_note:
        lines.append(f"\n*{re_eval.re_evaluation_note}*")

    return "\n".join(lines)


# =============================================================================
# KROK 3: ANALIZA PORÓWNAWCZA OSZCZĘDNOŚCI
# =============================================================================

def calculate_savings_comparison(
    sizing_result: Dict[str, Any],
    energy_price_pln_kwh: float = 0.80,
    export_price_pln_kwh: float = 0.30,
) -> SavingsComparison:
    """
    KROK 3: Calculate savings comparison between scenarios.

    Analyzes:
    1. PV-only: Baseline with direct self-consumption + export
    2. PV + BESS: Additional self-consumption from storage
    3. PV + BESS + Arbitrage: ToU trading on top

    Uses data from sizing_result to derive these scenarios.
    """
    # Extract totals
    total_pv_mwh = sizing_result.get("total_pv_mwh", 0) * 1000  # to kWh
    total_load_mwh = sizing_result.get("total_load_mwh", 0) * 1000  # to kWh
    annual_surplus_mwh = sizing_result.get("annual_surplus_mwh", 0) * 1000  # to kWh

    # Extract recommended variant data
    variants = sizing_result.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), variants[0] if variants else {})
    sb = recommended.get("savings_breakdown", {})

    # === Scenario 1: PV-only ===
    # Direct self-consumption = PV used directly by load
    direct_self_consumption = min(total_pv_mwh, total_load_mwh)
    pv_only_self_consumption_pct = (direct_self_consumption / total_pv_mwh * 100) if total_pv_mwh > 0 else 0
    pv_only_exported = max(0, total_pv_mwh - direct_self_consumption)
    pv_only_export_revenue = pv_only_exported * export_price_pln_kwh
    pv_only_savings = direct_self_consumption * energy_price_pln_kwh + pv_only_export_revenue

    # === Scenario 2: PV + BESS (self-consumption) ===
    energy_savings = sb.get("energy_savings_pln", 0)
    # Total PV+BESS savings (excluding arbitrage)
    pv_bess_savings = pv_only_savings + energy_savings
    # How much was stored
    stored_kwh = annual_surplus_mwh * 0.8  # Estimate: 80% of surplus can be stored
    # New self-consumption
    pv_bess_self_consumption_pct = min(95, pv_only_self_consumption_pct + (stored_kwh / total_pv_mwh * 100) if total_pv_mwh > 0 else 0)
    pv_bess_additional = pv_bess_savings - pv_only_savings

    # === Scenario 3: PV + BESS + Arbitrage ===
    arbitrage_savings = sb.get("arbitrage_savings_pln", 0)
    capacity_fee_savings = sb.get("capacity_fee_savings_pln", 0)
    demand_charge_savings = sb.get("demand_charge_savings_pln", 0)
    total_bess_benefit = energy_savings + arbitrage_savings + capacity_fee_savings + demand_charge_savings

    pv_bess_arb_savings = pv_only_savings + total_bess_benefit
    # Estimate cycles based on arbitrage revenue and spread
    avg_spread = 0.20  # PLN/kWh assumed
    energy_kwh = recommended.get("energy_kwh", 100)
    cycles_per_year = arbitrage_savings / (energy_kwh * avg_spread) if energy_kwh > 0 and avg_spread > 0 else 0
    arbitrage_additional = arbitrage_savings

    # Determine best scenario
    scenarios = {
        "pv_only": pv_only_savings,
        "pv_bess": pv_bess_savings,
        "pv_bess_arbitrage": pv_bess_arb_savings,
    }
    best_scenario = max(scenarios, key=scenarios.get)

    return SavingsComparison(
        # PV-only
        pv_only_savings_pln=pv_only_savings,
        pv_only_self_consumption_pct=pv_only_self_consumption_pct,
        pv_only_exported_kwh=pv_only_exported,
        pv_only_export_revenue_pln=pv_only_export_revenue,
        # PV + BESS
        pv_bess_savings_pln=pv_bess_savings,
        pv_bess_self_consumption_pct=pv_bess_self_consumption_pct,
        pv_bess_stored_kwh=stored_kwh,
        pv_bess_additional_savings_pln=pv_bess_additional,
        # PV + BESS + Arb
        pv_bess_arb_savings_pln=pv_bess_arb_savings,
        arbitrage_cycles_per_year=cycles_per_year,
        arbitrage_revenue_pln=arbitrage_savings,
        arbitrage_additional_savings_pln=arbitrage_additional,
        # Summary
        best_scenario=best_scenario,
        incremental_bess_value_pln=pv_bess_additional,
        incremental_arbitrage_value_pln=arbitrage_additional,
    )


def _generate_savings_comparison_markdown(comparison: Optional[SavingsComparison]) -> str:
    """Generate markdown section for savings comparison"""
    if not comparison:
        return ""

    # Determine best scenario emoji
    best_emoji = {
        "pv_only": "☀️",
        "pv_bess": "🔋",
        "pv_bess_arbitrage": "💹",
    }.get(comparison.best_scenario, "📊")

    lines = [
        "\n### 📊 Porównanie scenariuszy oszczędności\n",
        "| Scenariusz | Roczne oszczędności | Self-consumption | Delta vs PV-only |",
        "|------------|--------------------:|:----------------:|:----------------:|",
        f"| ☀️ PV-only | {comparison.pv_only_savings_pln:,.0f} PLN | {comparison.pv_only_self_consumption_pct:.0f}% | - |",
        f"| 🔋 PV + BESS | {comparison.pv_bess_savings_pln:,.0f} PLN | {comparison.pv_bess_self_consumption_pct:.0f}% | +{comparison.pv_bess_additional_savings_pln:,.0f} PLN |",
        f"| 💹 PV + BESS + Arb | {comparison.pv_bess_arb_savings_pln:,.0f} PLN | - | +{comparison.pv_bess_arb_savings_pln - comparison.pv_only_savings_pln:,.0f} PLN |",
        "",
        f"**{best_emoji} Najlepszy scenariusz:** {comparison.best_scenario.replace('_', ' ').title()}",
        "",
    ]

    if comparison.incremental_bess_value_pln > 0:
        lines.append(f"- Dodatkowa wartość BESS: **{comparison.incremental_bess_value_pln:,.0f} PLN/rok**")

    if comparison.incremental_arbitrage_value_pln > 0:
        lines.append(f"- Wartość arbitrażu: **{comparison.incremental_arbitrage_value_pln:,.0f} PLN/rok** (~{comparison.arbitrage_cycles_per_year:.0f} cykli/rok)")

    return "\n".join(lines)


# =============================================================================
# KROK 4: ROZBUDOWANA REKOMENDACJA TARYFOWA
# =============================================================================

def calculate_enhanced_tariff_recommendation(
    sizing_result: Dict[str, Any],
    current_tariff: str,
    savings_breakdown: SavingsBreakdownAdvisor,
    energy_kwh: float,
    annual_load_kwh: float,
) -> TariffRecommendation:
    """
    KROK 4: Enhanced tariff recommendation with C11/C12a/C12b comparison.

    Calculates estimated costs under each tariff:
    - C11: Flat rate (~0.75 PLN/kWh)
    - C12a: 2-zone (peak ~0.85, off-peak ~0.55 PLN/kWh)
    - C12b: 3-zone (peak ~0.90, day ~0.70, night ~0.45 PLN/kWh)

    With and without BESS optimization.
    """
    # Tariff rates (simplified averages)
    C11_RATE = 0.75  # PLN/kWh flat
    C12A_PEAK = 0.85
    C12A_OFFPEAK = 0.55
    C12A_AVG = 0.70  # Weighted average
    C12B_PEAK = 0.90
    C12B_DAY = 0.70
    C12B_NIGHT = 0.45
    C12B_AVG = 0.68  # Weighted average

    # Estimate consumption split (rough assumptions)
    # For C12a: ~60% peak, 40% off-peak
    # For C12b: ~30% peak, 50% day, 20% night

    # Base costs without BESS
    c11_base = annual_load_kwh * C11_RATE
    c12a_base = annual_load_kwh * C12A_AVG
    c12b_base = annual_load_kwh * C12B_AVG

    # BESS optimization potential by tariff
    arb_savings = savings_breakdown.arbitrage_savings_pln
    energy_savings = savings_breakdown.energy_savings_pln

    # C11 with BESS: Only self-consumption benefits, no arbitrage
    c11_with_bess = c11_base - energy_savings

    # C12a with BESS: Self-consumption + arbitrage (shift peak to off-peak)
    # Assume BESS can shift ~50% more load to off-peak
    c12a_arb_potential = arb_savings * 1.2  # 20% more arbitrage on ToU
    c12a_with_bess = c12a_base - energy_savings - c12a_arb_potential

    # C12b with BESS: Best arbitrage (3-zone spread)
    c12b_arb_potential = arb_savings * 1.5  # 50% more arbitrage on 3-zone
    c12b_with_bess = c12b_base - energy_savings - c12b_arb_potential

    # Find best combination
    options = {
        ("C11", False): c11_base,
        ("C11", True): c11_with_bess,
        ("C12a", False): c12a_base,
        ("C12a", True): c12a_with_bess,
        ("C12b", False): c12b_base,
        ("C12b", True): c12b_with_bess,
    }

    # Best option
    best_option = min(options, key=options.get)
    best_tariff = best_option[0]
    best_cost = options[best_option]

    # Current tariff cost with BESS
    current_with_bess = options.get((current_tariff, True), c11_with_bess)

    # Savings delta
    savings_delta = current_with_bess - best_cost

    # Generate recommendation text
    if best_tariff == current_tariff:
        recommendation = f"Obecna taryfa {current_tariff} jest optymalna dla tej konfiguracji BESS."
        confidence = "high"
    elif savings_delta > 5000:
        recommendation = (
            f"Zmiana z {current_tariff} na {best_tariff} może przynieść "
            f"~{savings_delta:,.0f} PLN/rok dodatkowych oszczędności."
        )
        confidence = "high"
    elif savings_delta > 1000:
        recommendation = (
            f"Rozważ zmianę na {best_tariff} - potencjalne oszczędności "
            f"~{savings_delta:,.0f} PLN/rok."
        )
        confidence = "medium"
    else:
        recommendation = (
            f"Różnica między taryfami jest niewielka ({savings_delta:,.0f} PLN/rok). "
            "Pozostań przy obecnej taryfie."
        )
        confidence = "low"

    # Min spread for profitability
    if energy_kwh > 0:
        cycles_per_year = 250  # Assume
        min_spread = (savings_breakdown.arbitrage_savings_pln / (energy_kwh * cycles_per_year)) * 1000  # PLN/MWh
    else:
        min_spread = 50.0

    return TariffRecommendation(
        current_tariff=current_tariff,
        recommended_tariff=best_tariff,
        annual_savings_delta_pln=savings_delta,
        min_spread_for_profitability_pln_mwh=min_spread,
        recommendation=recommendation,
        confidence=confidence,
        c11_cost_pln=c11_base,
        c12a_cost_pln=c12a_base,
        c12b_cost_pln=c12b_base,
        c11_with_bess_pln=c11_with_bess,
        c12a_with_bess_pln=c12a_with_bess,
        c12b_with_bess_pln=c12b_with_bess,
    )


def _generate_enhanced_tariff_markdown(tariff_rec: Optional[TariffRecommendation]) -> str:
    """Generate enhanced tariff recommendation markdown"""
    if not tariff_rec:
        return ""

    emoji = "✅" if tariff_rec.confidence == "high" else "⚡" if tariff_rec.confidence == "medium" else "❓"

    lines = [
        "\n### 📊 Rekomendacja taryfowa\n",
        f"**Aktualna taryfa:** {tariff_rec.current_tariff}",
        f"**Rekomendowana:** {tariff_rec.recommended_tariff}",
        "",
        "#### Porównanie kosztów rocznych",
        "",
        "| Taryfa | Bez BESS | Z BESS | Oszczędność |",
        "|--------|----------:|-------:|-----------:|",
        f"| C11 | {tariff_rec.c11_cost_pln:,.0f} PLN | {tariff_rec.c11_with_bess_pln:,.0f} PLN | {tariff_rec.c11_cost_pln - tariff_rec.c11_with_bess_pln:,.0f} PLN |",
        f"| C12a | {tariff_rec.c12a_cost_pln:,.0f} PLN | {tariff_rec.c12a_with_bess_pln:,.0f} PLN | {tariff_rec.c12a_cost_pln - tariff_rec.c12a_with_bess_pln:,.0f} PLN |",
        f"| C12b | {tariff_rec.c12b_cost_pln:,.0f} PLN | {tariff_rec.c12b_with_bess_pln:,.0f} PLN | {tariff_rec.c12b_cost_pln - tariff_rec.c12b_with_bess_pln:,.0f} PLN |",
        "",
        f"{emoji} **{tariff_rec.recommendation}**",
        "",
        f"Min. spread dla opłacalności arbitrażu: {tariff_rec.min_spread_for_profitability_pln_mwh:.0f} PLN/MWh",
    ]

    return "\n".join(lines)
