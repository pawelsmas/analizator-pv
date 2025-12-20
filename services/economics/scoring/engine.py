"""
Scoring Engine
==============
Multi-criteria scoring engine using actual economic KPIs.

Key features:
1. Uses REAL economic KPIs from Economics module (NPV, Payback, LCOE, IRR)
2. Piecewise threshold scoring with linear interpolation
3. Penalties for oversizing (low auto-consumption)
4. Missing data handling (exclude & rescale weights)
5. Auto-generated justification reasons
"""

from typing import List, Optional
from .models import (
    OfferInputs,
    ScoringParameters,
    ThresholdConfig,
    KPIRaw,
    BucketScores,
    PointsBreakdown,
    CompletenessInfo,
    Flag,
    ScoreResult,
    ScoringRequest,
    ScoringResponse,
)


class ScoringEngine:
    """
    Multi-criteria scoring engine for PV offers.

    Scoring buckets:
    1. VALUE (40%): NPV, Payback - direct economic benefit
    2. ROBUSTNESS (30%): IRR, LCOE - investment quality & energy cost security
    3. TECH (20%): Auto-consumption, Coverage - sizing efficiency
    4. ESG (10%): CO2 reduction

    Key insight: Higher NPV with lower auto-consumption means oversizing.
    The engine balances value with efficiency.
    """

    def __init__(self, parameters: Optional[ScoringParameters] = None):
        self.params = parameters or ScoringParameters()

    def score_offers(self, request: ScoringRequest) -> ScoringResponse:
        """Score multiple offers and return ranked results"""
        self.params = request.parameters
        results: List[ScoreResult] = []

        for offer in request.offers:
            result = self._score_single_offer(offer)
            results.append(result)

        # Rank by total_score (descending)
        results.sort(key=lambda r: r.total_score, reverse=True)
        for i, result in enumerate(results):
            result.rank = i + 1

        # Generate comparison reasons if multiple offers
        if len(results) >= 2:
            self._add_comparison_reasons(results)

        return ScoringResponse(
            results=results,
            rules_used=self.params.thresholds,
            profile_used=self.params.profile,
            parameters_used=self.params,
            comparison_available=len(results) >= 2,
        )

    def _score_single_offer(self, offer: OfferInputs) -> ScoreResult:
        """Calculate complete score for a single offer"""
        # Step 1: Extract raw KPIs
        kpi_raw = self._extract_kpi_raw(offer)

        # Step 2: Apply threshold scoring to get points
        points, completeness = self._apply_threshold_scoring(kpi_raw, offer)

        # Step 3: Calculate bucket scores (with weights)
        bucket_scores = self._calculate_bucket_scores(points, completeness)

        # Step 4: Calculate total score (0-100)
        total_score = self._calculate_total_score(bucket_scores)

        # Step 5: Generate flags and reasons
        flags = self._generate_flags(offer, kpi_raw)
        reasons = self._generate_reasons(kpi_raw, points, bucket_scores, offer)

        return ScoreResult(
            offer_id=offer.offer_id,
            offer_name=offer.name,
            total_score=total_score,
            bucket_scores=bucket_scores,
            kpi_raw=kpi_raw,
            points_breakdown=points,
            completeness=completeness,
            flags=flags,
            reasons=reasons,
        )

    def _extract_kpi_raw(self, offer: OfferInputs) -> KPIRaw:
        """Extract raw KPIs from offer"""
        # Auto-consumption and coverage
        auto_consumption = offer.get_auto_consumption_pct()
        coverage = offer.get_coverage_pct()

        # Exported percentage
        exported_pct = 0.0
        if offer.annual_production_kwh > 0:
            exported_pct = offer.exported_kwh / offer.annual_production_kwh

        # CO2 reduction (estimate if not provided)
        co2_reduction = offer.co2_reduction_tons or 0.0
        if co2_reduction == 0 and offer.self_consumed_kwh > 0:
            # Estimate: 0.7 kg CO2 / kWh from Polish grid
            co2_reduction = (offer.self_consumed_kwh * 0.7) / 1000  # tonnes

        return KPIRaw(
            npv_mln=offer.npv_pln / 1_000_000,  # Convert to millions
            payback_years=offer.payback_years,
            irr_pct=offer.irr_pct or 0.0,
            lcoe_pln_mwh=offer.lcoe_pln_mwh or 0.0,
            auto_consumption_pct=auto_consumption,
            coverage_pct=coverage,
            exported_pct=exported_pct,
            co2_reduction_tons=co2_reduction,
        )

    def _apply_threshold_scoring(
        self, kpi_raw: KPIRaw, offer: OfferInputs
    ) -> tuple[PointsBreakdown, CompletenessInfo]:
        """Apply piecewise threshold scoring"""
        thresholds = self.params.thresholds
        available_kpis = []
        missing_kpis = []

        # VALUE bucket
        npv_pts = thresholds.npv_mln.score(kpi_raw.npv_mln)
        payback_pts = thresholds.payback_years.score(kpi_raw.payback_years)
        available_kpis.extend(["npv", "payback"])

        # ROBUSTNESS bucket
        if offer.irr_pct is not None and offer.irr_pct > 0:
            irr_pts = thresholds.irr_pct.score(kpi_raw.irr_pct)
            available_kpis.append("irr")
        else:
            irr_pts = 0
            missing_kpis.append("irr")

        if offer.lcoe_pln_mwh is not None and offer.lcoe_pln_mwh > 0:
            lcoe_pts = thresholds.lcoe_pln_mwh.score(kpi_raw.lcoe_pln_mwh)
            available_kpis.append("lcoe")
        else:
            lcoe_pts = 0
            missing_kpis.append("lcoe")

        # TECH bucket
        auto_consumption_pts = thresholds.auto_consumption_pct.score(kpi_raw.auto_consumption_pct)
        coverage_pts = thresholds.coverage_pct.score(kpi_raw.coverage_pct)
        available_kpis.extend(["auto_consumption", "coverage"])

        # ESG bucket
        if kpi_raw.co2_reduction_tons > 0:
            co2_pts = thresholds.co2_reduction_tons.score(kpi_raw.co2_reduction_tons)
            available_kpis.append("co2")
        else:
            co2_pts = 0
            missing_kpis.append("co2")

        points = PointsBreakdown(
            npv_pts=npv_pts,
            payback_pts=payback_pts,
            irr_pts=irr_pts,
            lcoe_pts=lcoe_pts,
            auto_consumption_pts=auto_consumption_pts,
            coverage_pts=coverage_pts,
            co2_pts=co2_pts,
        )

        completeness = CompletenessInfo(
            available_kpis=available_kpis,
            missing_kpis=missing_kpis,
            weight_adjustment=1.0,
        )

        return points, completeness

    def _calculate_bucket_scores(
        self, points: PointsBreakdown, completeness: CompletenessInfo
    ) -> BucketScores:
        """Calculate weighted bucket scores"""
        profile = self.params.profile

        # VALUE bucket: NPV (20 max) + Payback (20 max) = 40 max raw
        value_raw = points.npv_pts + points.payback_pts
        value_max = 40
        value_score = (value_raw / value_max) * 100 * profile.value_weight

        # ROBUSTNESS bucket: IRR (20 max) + LCOE (10 max) = 30 max raw
        # Handle missing IRR/LCOE
        robustness_max = 30
        if "irr" in completeness.missing_kpis and "lcoe" in completeness.missing_kpis:
            # Both missing - redistribute weight
            robustness_score = 0
            redistribute = profile.robustness_weight * 100 / 2
            value_score += redistribute * 0.6  # 60% to value
            # Tech gets the rest below
        elif "irr" in completeness.missing_kpis:
            robustness_raw = points.lcoe_pts * 3  # Scale up LCOE
            robustness_score = (robustness_raw / robustness_max) * 100 * profile.robustness_weight
        elif "lcoe" in completeness.missing_kpis:
            robustness_raw = points.irr_pts * 1.5  # Scale up IRR
            robustness_score = (robustness_raw / robustness_max) * 100 * profile.robustness_weight
        else:
            robustness_raw = points.irr_pts + points.lcoe_pts
            robustness_score = (robustness_raw / robustness_max) * 100 * profile.robustness_weight

        # TECH bucket: Auto-consumption (10 max) + Coverage (10 max) = 20 max raw
        tech_raw = points.auto_consumption_pts + points.coverage_pts
        tech_max = 20
        tech_score = (tech_raw / tech_max) * 100 * profile.tech_weight

        # ESG bucket: CO2 (10 max)
        if "co2" in completeness.missing_kpis:
            esg_score = 0
            # Redistribute ESG weight
            redistribute = profile.esg_weight * 100 / 3
            value_score += redistribute * 0.4
            tech_score += redistribute * 0.6
        else:
            esg_raw = points.co2_pts
            esg_max = 10
            esg_score = (esg_raw / esg_max) * 100 * profile.esg_weight

        return BucketScores(
            value=round(value_score, 2),
            robustness=round(robustness_score, 2),
            tech=round(tech_score, 2),
            esg=round(esg_score, 2),
        )

    def _calculate_total_score(self, bucket_scores: BucketScores) -> float:
        """Calculate final total score (0-100)"""
        total = (
            bucket_scores.value +
            bucket_scores.robustness +
            bucket_scores.tech +
            bucket_scores.esg
        )
        return round(min(100, max(0, total)), 1)

    def _generate_flags(self, offer: OfferInputs, kpi_raw: KPIRaw) -> List[Flag]:
        """Generate warning/info flags"""
        flags = []

        # Negative NPV
        if offer.npv_pln < 0:
            flags.append(Flag(
                type="warning",
                code="NPV_NEGATIVE",
                message=f"Ujemne NPV ({kpi_raw.npv_mln:.2f} mln PLN) - inwestycja nierentowna"
            ))

        # Very long payback
        if offer.payback_years > 12:
            flags.append(Flag(
                type="warning",
                code="LONG_PAYBACK",
                message=f"Dlugi okres zwrotu ({offer.payback_years:.1f} lat)"
            ))

        # Low auto-consumption = oversized
        if kpi_raw.auto_consumption_pct < 0.5:
            flags.append(Flag(
                type="warning",
                code="LOW_AUTOCONSUMPTION",
                message=f"Niska autokonsumpcja ({kpi_raw.auto_consumption_pct:.0%}) - instalacja moze byc przewymiarowana"
            ))

        # High exported percentage
        if kpi_raw.exported_pct > 0.4:
            flags.append(Flag(
                type="warning",
                code="HIGH_EXPORT",
                message=f"Wysoki eksport ({kpi_raw.exported_pct:.0%} produkcji) - nadprodukcja niewykorzystana"
            ))

        # Good auto-consumption
        if kpi_raw.auto_consumption_pct > 0.85:
            flags.append(Flag(
                type="success",
                code="OPTIMAL_SIZING",
                message=f"Optymalne dopasowanie mocy (autokonsumpcja {kpi_raw.auto_consumption_pct:.0%})"
            ))

        # Good payback
        if offer.payback_years < 5:
            flags.append(Flag(
                type="success",
                code="FAST_PAYBACK",
                message=f"Szybki zwrot ({offer.payback_years:.1f} lat)"
            ))

        return flags

    def _generate_reasons(
        self,
        kpi_raw: KPIRaw,
        points: PointsBreakdown,
        bucket_scores: BucketScores,
        offer: OfferInputs
    ) -> List[str]:
        """Generate human-readable reasons"""
        reasons = []

        # Top performers
        if points.npv_pts >= 15:
            reasons.append(f"Wysokie NPV: {kpi_raw.npv_mln:.2f} mln PLN")

        if points.payback_pts >= 15:
            reasons.append(f"Krotki okres zwrotu: {kpi_raw.payback_years:.1f} lat")

        if points.irr_pts >= 15:
            reasons.append(f"Wysoki IRR: {kpi_raw.irr_pct:.1f}%")

        if points.auto_consumption_pts >= 7.5:
            reasons.append(f"Wysoka autokonsumpcja: {kpi_raw.auto_consumption_pct:.0%}")

        # Problem areas
        if points.npv_pts < 5:
            reasons.append(f"Niskie NPV: {kpi_raw.npv_mln:.2f} mln PLN")

        if points.payback_pts < 5:
            reasons.append(f"Dlugi zwrot: {kpi_raw.payback_years:.1f} lat")

        if points.auto_consumption_pts < 2.5:
            reasons.append(f"Niska autokonsumpcja ({kpi_raw.auto_consumption_pct:.0%}) - przewymiarowanie?")

        # Balance insight
        if kpi_raw.npv_mln > 1 and kpi_raw.auto_consumption_pct < 0.6:
            reasons.append("Wysokie NPV ale niska autokonsumpcja - rozwaz mniejsza moc dla lepszej efektywnosci")

        return reasons

    def _add_comparison_reasons(self, results: List[ScoreResult]) -> None:
        """Add comparison-based reasons to top offers"""
        if len(results) < 2:
            return

        top = results[0]
        second = results[1]
        diff = top.total_score - second.total_score

        top.reasons.insert(0, f"LIDER rankingu (+{diff:.1f} pkt vs {second.offer_name})")

        # Identify differentiating factors
        if top.bucket_scores.value - second.bucket_scores.value > 3:
            top.reasons.append(f"Lepsza wartosc ekonomiczna (+{top.bucket_scores.value - second.bucket_scores.value:.1f} pkt)")

        if top.bucket_scores.tech - second.bucket_scores.tech > 3:
            top.reasons.append(f"Lepsza efektywnosc techniczna (+{top.bucket_scores.tech - second.bucket_scores.tech:.1f} pkt)")

        if top.kpi_raw.auto_consumption_pct > second.kpi_raw.auto_consumption_pct + 0.1:
            top.reasons.append(f"Wyzsza autokonsumpcja ({top.kpi_raw.auto_consumption_pct:.0%} vs {second.kpi_raw.auto_consumption_pct:.0%})")


def score_offers(
    offers: List[OfferInputs],
    parameters: Optional[ScoringParameters] = None
) -> ScoringResponse:
    """
    Score multiple offers with given parameters.

    Example:
        from scoring.engine import score_offers
        from scoring.models import OfferInputs

        offers = [
            OfferInputs(
                offer_id="A",
                name="Wariant A - 500 kWp",
                capacity_kwp=500,
                npv_pln=1_500_000,
                payback_years=5.2,
                irr_pct=15.3,
                lcoe_pln_mwh=180,
                annual_production_kwh=500_000,
                self_consumed_kwh=425_000,
                exported_kwh=75_000,
                annual_consumption_kwh=600_000,
            ),
        ]

        response = score_offers(offers)
        for result in response.results:
            print(f"{result.rank}. {result.offer_name}: {result.total_score} pkt")
    """
    request = ScoringRequest(
        offers=offers,
        parameters=parameters or ScoringParameters(),
    )
    engine = ScoringEngine()
    return engine.score_offers(request)
