"""
Report PDF Renderer (v2.4.0)

Generates PDF reports from ReportData using reportlab.

PDF Sections:
1. Header: Title, branding, run info
2. Executive Summary: Recommended variant, NPV/Payback/IRR
3. Money Ledger: Annual costs breakdown
4. Flows & Constraints: Energy flows summary
5. Engineering (optional): Cycles, invariants, debug events
6. Warnings: Any extraction warnings
"""

import io
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from report_data import ReportData
from report_models import ReportProfile


def render_pdf(report_data: ReportData) -> bytes:
    """
    Render ReportData to PDF bytes.

    Args:
        report_data: ReportData object with all sections

    Returns:
        PDF file as bytes
    """
    buffer = io.BytesIO()

    # Create document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    # Build story (content)
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=6 * mm,
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=4 * mm,
        spaceBefore=6 * mm,
    )
    subheading_style = ParagraphStyle(
        'CustomSubheading',
        parent=styles['Heading3'],
        fontSize=12,
        spaceAfter=3 * mm,
        spaceBefore=4 * mm,
    )
    body_style = styles['Normal']

    # 1. Header
    _add_header(story, report_data, title_style, body_style)

    # 2. Executive Summary
    _add_executive_summary(story, report_data, heading_style, body_style)

    # 3. Money Ledger
    _add_money_ledger(story, report_data, heading_style, subheading_style)

    # 4. Flows & Constraints
    _add_flows_constraints(story, report_data, heading_style)

    # 5. Engineering (if profile=engineering)
    options = report_data.options
    if options and options.profile == ReportProfile.ENGINEERING:
        _add_engineering_section(story, report_data, heading_style, subheading_style)

    # 6. Warnings
    if report_data.warnings:
        _add_warnings(story, report_data, heading_style, body_style)

    # Build PDF
    doc.build(story)

    return buffer.getvalue()


def _add_header(story, report_data: ReportData, title_style, body_style):
    """Add header section with title and branding."""
    meta = report_data.meta
    options = report_data.options
    branding = options.branding if options else None

    # Title
    title = "BESS Sizing Report"
    if branding and branding.report_title:
        title = branding.report_title
    story.append(Paragraph(title, title_style))

    # Branding info
    info_lines = []
    if branding:
        if branding.client_name:
            info_lines.append(f"<b>Client:</b> {branding.client_name}")
        if branding.site_name:
            info_lines.append(f"<b>Site:</b> {branding.site_name}")
        if branding.prepared_by:
            info_lines.append(f"<b>Prepared By:</b> {branding.prepared_by}")
        if branding.prepared_for:
            info_lines.append(f"<b>Prepared For:</b> {branding.prepared_for}")

    # Run info
    info_lines.append(f"<b>Run ID:</b> {meta.run_id}")
    info_lines.append(f"<b>Created:</b> {meta.created_at}")
    if meta.schema_version:
        info_lines.append(f"<b>Schema Version:</b> {meta.schema_version}")
    if meta.assumptions_version:
        info_lines.append(f"<b>Assumptions:</b> {meta.assumptions_version}")

    # Period info
    if meta.period_start and meta.period_end:
        info_lines.append(f"<b>Period:</b> {meta.period_start} to {meta.period_end}")
    if meta.period_hours:
        full_year = "Yes" if meta.is_full_year else "No"
        info_lines.append(f"<b>Hours:</b> {meta.period_hours:.0f} (Full Year: {full_year})")

    for line in info_lines:
        story.append(Paragraph(line, body_style))

    story.append(Spacer(1, 10 * mm))


def _add_executive_summary(story, report_data: ReportData, heading_style, body_style):
    """Add executive summary with KPIs."""
    story.append(Paragraph("Executive Summary", heading_style))

    rec = report_data.recommended

    # KPI table
    data = [
        ["Metric", "Value"],
        ["Recommended Variant", rec.recommended_variant or "N/A"],
        ["Objective Used", rec.objective_used or "N/A"],
        ["NPV", f"{rec.npv_pln:,.0f} PLN" if rec.npv_pln else "N/A"],
        ["Payback Period", f"{rec.payback_years:.1f} years" if rec.payback_years else "N/A"],
        ["IRR", f"{rec.irr_pct:.1f}%" if rec.irr_pct else "N/A"],
        ["Annual Net Savings", f"{rec.net_savings_pln:,.0f} PLN" if rec.net_savings_pln else "N/A"],
    ]

    table = Table(data, colWidths=[80 * mm, 80 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
    ]))

    story.append(table)
    story.append(Spacer(1, 6 * mm))


def _add_money_ledger(story, report_data: ReportData, heading_style, subheading_style):
    """Add money ledger section."""
    story.append(Paragraph("Annual Cost Breakdown", heading_style))

    ledger = report_data.money_ledger_annual

    # Cost categories table
    data = [
        ["Category", "Baseline (PLN)", "Project (PLN)", "Savings (PLN)"],
        [
            "Import Energy",
            f"{ledger.baseline.import_energy_cost_pln:,.0f}",
            f"{ledger.project.import_energy_cost_pln:,.0f}",
            f"{ledger.delta.import_energy_cost_pln:,.0f}",
        ],
        [
            "Export Revenue",
            f"{ledger.baseline.export_revenue_pln:,.0f}",
            f"{ledger.project.export_revenue_pln:,.0f}",
            f"{ledger.delta.export_revenue_pln:,.0f}",
        ],
        [
            "Capacity Fee",
            f"{ledger.baseline.capacity_fee_pln:,.0f}",
            f"{ledger.project.capacity_fee_pln:,.0f}",
            f"{ledger.delta.capacity_fee_pln:,.0f}",
        ],
        [
            "Demand Charge",
            f"{ledger.baseline.demand_charge_pln:,.0f}",
            f"{ledger.project.demand_charge_pln:,.0f}",
            f"{ledger.delta.demand_charge_pln:,.0f}",
        ],
        [
            "Total Cost",
            f"{ledger.baseline.total_cost_pln:,.0f}",
            f"{ledger.project.total_cost_pln:,.0f}",
            f"{ledger.delta.total_cost_pln:,.0f}",
        ],
    ]

    table = Table(data, colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#ECF0F1')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#BDC3C7')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
    ]))

    story.append(table)
    story.append(Spacer(1, 6 * mm))


def _add_flows_constraints(story, report_data: ReportData, heading_style):
    """Add flows and constraints section."""
    story.append(Paragraph("Energy Flows & Constraints", heading_style))

    flows = report_data.flows_annual
    constraints = report_data.constraints

    # Flows table
    data = [
        ["Energy Flows", "Value"],
        ["Grid Import", f"{flows.grid_import_mwh:,.1f} MWh"],
        ["Grid Export", f"{flows.grid_export_mwh:,.1f} MWh"],
        ["PV Curtailment", f"{flows.pv_curtail_mwh:,.1f} MWh"],
        ["Unserved Load", f"{flows.unserved_load_kwh:,.1f} kWh"],
    ]

    table = Table(data, colWidths=[80 * mm, 80 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27AE60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(table)
    story.append(Spacer(1, 4 * mm))

    # Constraints table
    data = [
        ["Constraints", "Value"],
        ["Max Import", f"{constraints.max_import_kw:,.0f} kW" if constraints.max_import_kw else "N/A"],
        ["Max Export", f"{constraints.max_export_kw:,.0f} kW" if constraints.max_export_kw else "N/A"],
        ["Export Limited Steps", f"{constraints.export_limited_steps:,}"],
        ["Import Limited Steps", f"{constraints.import_limited_steps:,}"],
    ]

    table = Table(data, colWidths=[80 * mm, 80 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E74C3C')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(table)
    story.append(Spacer(1, 6 * mm))


def _add_engineering_section(story, report_data: ReportData, heading_style, subheading_style):
    """Add engineering details section."""
    story.append(Paragraph("Engineering Details", heading_style))

    dispatch = report_data.dispatch_summary
    if not dispatch:
        story.append(Paragraph("No engineering data available.", getSampleStyleSheet()['Normal']))
        return

    # Cycle Summary
    if dispatch.cycle_summary:
        story.append(Paragraph("Cycle Summary", subheading_style))
        cycle = dispatch.cycle_summary
        data = [
            ["Metric", "Value"],
            ["Total EFC", f"{cycle.efc_total:,.1f}" if cycle.efc_total else "N/A"],
            ["Avg Daily EFC", f"{cycle.cycles_per_day_avg:.2f}" if cycle.cycles_per_day_avg else "N/A"],
            ["Max Daily EFC", f"{cycle.cycles_per_day_max:.2f}" if cycle.cycles_per_day_max else "N/A"],
            ["Total Throughput", f"{cycle.total_throughput_kwh:,.0f} kWh" if cycle.total_throughput_kwh else "N/A"],
            ["Cycle Limit Hit", "Yes" if cycle.cycle_limit_hit else "No"],
        ]

        table = Table(data, colWidths=[80 * mm, 80 * mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9B59B6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        story.append(table)
        story.append(Spacer(1, 4 * mm))

    # Invariants
    if dispatch.invariants:
        story.append(Paragraph("Invariant Checks", subheading_style))
        inv = dispatch.invariants
        status = lambda ok: "PASS" if ok else "FAIL"
        data = [
            ["Check", "Status"],
            ["All OK", status(inv.all_ok)],
            ["SOC Bounds", status(inv.soc_bounds_ok)],
            ["Power Limits", status(inv.power_limits_ok)],
            ["No Simultaneous", status(inv.no_simultaneous_ok)],
            ["Energy Balance", status(inv.energy_balance_ok)],
        ]

        table = Table(data, colWidths=[80 * mm, 80 * mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        story.append(table)
        story.append(Spacer(1, 4 * mm))


def _add_warnings(story, report_data: ReportData, heading_style, body_style):
    """Add warnings section."""
    story.append(Paragraph("Warnings", heading_style))

    for i, warning in enumerate(report_data.warnings, 1):
        story.append(Paragraph(f"{i}. {warning}", body_style))
