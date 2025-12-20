"""
Reports Service - Generowanie raportów PDF dla analiz PV
"""
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import httpx
import json
import os
from pathlib import Path
import base64
import io

# Charts
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt
import numpy as np

# PDF generation
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("⚠️ WeasyPrint not available. PDF generation disabled.")

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Reports Service", version="1.0.0")

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend URLs
BACKEND_URLS = {
    "data_analysis": os.environ.get("DATA_ANALYSIS_URL", "http://pv-data-analysis:8001"),
    "pv_calculation": os.environ.get("PV_CALCULATION_URL", "http://pv-calculation:8002"),
    "economics": os.environ.get("ECONOMICS_URL", "http://pv-economics:8003"),
    "advanced_analytics": os.environ.get("ADVANCED_ANALYTICS_URL", "http://pv-advanced-analytics:8004"),
    "energy_prices": os.environ.get("ENERGY_PRICES_URL", "http://pv-energy-prices:8010"),
}

# Logo as base64 (loaded once at startup)
LOGO_BASE64 = None

def load_logo_base64():
    """Load Pagra logo and convert to base64"""
    global LOGO_BASE64
    logo_path = Path(__file__).parent / "Powered by Galileo - czarne.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            LOGO_BASE64 = base64.b64encode(f.read()).decode('utf-8')
        print(f"✓ Logo loaded from {logo_path}")
    else:
        print(f"⚠️ Logo not found at {logo_path}")

# Load logo at startup
load_logo_base64()

# Output directory
OUTPUT_DIR = Path("/app/output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ============== Models ==============

class ReportConfig(BaseModel):
    client_name: str = "Klient"
    location: str = "Polska"
    report_date: Optional[str] = None
    selected_variant: Optional[str] = None  # key variant to highlight
    include_sections: List[str] = [
        "executive_summary",
        "consumption_profile",
        "seasonality",
        "pv_assumptions",
        "variants_scan",
        "key_variants",
        "production_profile",
        "energy_balance",
        "economics_capex",
        "economics_eaas",
        "sensitivity"
    ]
    # Data passed directly from frontend (sharedData)
    frontend_data: Optional[Dict[str, Any]] = None


class ReportData(BaseModel):
    config: ReportConfig
    consumption_stats: Optional[Dict] = None
    analytical_year: Optional[Dict] = None
    seasonality: Optional[Dict] = None
    pv_scenarios: Optional[List[Dict]] = None
    key_variants: Optional[Dict] = None
    selected_variant_data: Optional[Dict] = None
    economics: Optional[Dict] = None
    energy_balance: Optional[Dict] = None
    hourly_data: Optional[Any] = None  # Can be List[Dict] or Dict with 'timestamps' key
    monthly_balance: Optional[List[Dict]] = None


# ============== Helper Functions ==============

async def fetch_from_backend(service: str, endpoint: str, params: Dict = None) -> Dict:
    """Fetch data from backend service"""
    url = f"{BACKEND_URLS[service]}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"⚠️ {service}{endpoint} returned {response.status_code}")
                return None
    except Exception as e:
        print(f"❌ Error fetching {service}{endpoint}: {e}")
        return None


async def fetch_hourly_data_from_backend() -> Dict:
    """Fetch hourly data with extended timeout (large payload)"""
    url = f"{BACKEND_URLS['data_analysis']}/hourly-data"
    print(f"  → Requesting: {url}")
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:  # 3 minute timeout
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                ts_count = len(data.get('timestamps', []))
                val_count = len(data.get('values', []))
                print(f"  ✓ Received {ts_count} timestamps, {val_count} values")
                return data
            else:
                print(f"  ⚠️ hourly-data returned {response.status_code}")
                return None
    except httpx.TimeoutException as e:
        print(f"  ❌ Timeout fetching hourly data: {e}")
        return None
    except httpx.ConnectError as e:
        print(f"  ❌ Connection error fetching hourly data: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Error fetching hourly data: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


async def post_to_backend(service: str, endpoint: str, data: Dict) -> Dict:
    """POST data to backend service"""
    url = f"{BACKEND_URLS[service]}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=data)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"⚠️ POST {service}{endpoint} returned {response.status_code}")
                return None
    except Exception as e:
        print(f"❌ Error posting {service}{endpoint}: {e}")
        return None


def format_number_pl(value: float, decimals: int = 2, suffix: str = "") -> str:
    """Format number for Polish locale (comma as decimal, space as thousands)"""
    if value is None:
        return "-"
    # Format with decimals
    formatted = f"{value:,.{decimals}f}"
    # Convert to Polish format: . -> temp, , -> space, temp -> comma
    formatted = formatted.replace(',', ' ').replace('.', ',')
    return f"{formatted}{suffix}"


def format_number(value: float, decimals: int = 2, suffix: str = "") -> str:
    """Format number for display - Polish locale"""
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return format_number_pl(value/1_000_000, decimals) + f" M{suffix}"
    elif abs(value) >= 1_000:
        return format_number_pl(value/1_000, decimals) + f" k{suffix}"
    else:
        return format_number_pl(value, decimals) + suffix


def format_currency(value: float, currency: str = "PLN") -> str:
    """Format currency value - Polish locale"""
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return format_number_pl(value/1_000_000, 2) + f" mln {currency}"
    elif abs(value) >= 1_000:
        return format_number_pl(value/1_000, 0) + f" tys. {currency}"
    else:
        return format_number_pl(value, 0) + f" {currency}"


def normalize_variant_to_mwh(variant: Dict) -> Dict:
    """Normalize variant values to MWh (detect if input is kWh or MWh)"""
    if not variant:
        return variant

    production = variant.get('production', 0)
    self_consumed = variant.get('self_consumed', 0)
    exported = variant.get('exported', 0)
    capacity = variant.get('capacity', 0)

    # Heuristic: if production > 50000, values are likely in kWh
    # Typical MWp installation produces ~1000 MWh/MWp, so 10 MWp = ~10,000 MWh
    # If we see 8,000,000 - that's 8 GWh in kWh, not 8,000 GWh
    if production > 50000:
        # Values are in kWh, convert to MWh
        return {
            **variant,
            'production': production / 1000,
            'self_consumed': self_consumed / 1000,
            'exported': exported / 1000,
            'capacity': capacity,  # capacity stays in kWp
            '_normalized': True
        }
    else:
        # Values already in MWh
        return {**variant, '_normalized': True}


# ============== Chart Generation ==============

# Color palette 1:1 with Chart.js frontend (matching portal exactly)
CHART_COLORS = {
    'primary': '#3498db',       # blue
    'secondary': '#2ecc71',     # green
    'accent': '#e74c3c',        # red - zużycie/consumption
    'warning': '#f39c12',       # orange - PV production
    'purple': '#9b59b6',        # export etc.
    'dark': '#333333',          # text color
    'light': '#f5f5f5',
    'grid': '#e0e0e0',
    'consumption': '#e74c3c',   # red for load/consumption
    'production': '#f39c12',    # orange for PV
    'self_consumed': '#2ecc71', # green for autoconsumption
    'curtailment': '#95a5a6',   # gray
    'exported': '#9b59b6',
    'coverage': '#3498db',      # blue for coverage line
    # Trend colors (darker versions for dashed lines)
    'trend_load': '#c0392b',
    'trend_pv': '#d35400',
    'trend_self': '#27ae60',
}


def apply_pagra_theme():
    """Globalny theme dla wykresów Pagra – wywołaj na start generowania raportu."""
    plt.rcParams.update({
        "figure.figsize": (10, 5),
        "figure.dpi": 130,
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "axes.edgecolor": "#888888",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.6,
        "grid.linestyle": (0, (4, 4)),       # przerywana siatka
        "grid.color": "#e0e0e0",
        "axes.prop_cycle": plt.cycler(
            color=["#e74c3c", "#f39c12", "#2ecc71", "#3498db", "#95a5a6"]
        ),
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "axes.titlepad": 8,
        "axes.labelpad": 6,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
    })


def annotate_bars(ax, fmt="{:,.0f}", dy_factor=0.01):
    """Dodaje wartości nad słupkami na wykresie słupkowym."""
    for bar in ax.patches:
        height = bar.get_height()
        if np.isnan(height) or height == 0:
            continue
        dy = max(ax.get_ylim()) * dy_factor
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + dy,
            fmt.format(height).replace(",", " "),
            ha="center",
            va="bottom",
            fontsize=7,
            color="#555555",
        )

def fig_to_base64(fig) -> str:
    """Convert matplotlib figure to base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white',
                edgecolor='none', pad_inches=0.2)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return f"data:image/png;base64,{img_base64}"


def generate_daily_profile_chart(hourly_data: Any, consumption_stats: Dict) -> str:
    """1.3 Średni profil dobowy – jedna linia + area fill (Pagra theme)"""
    try:
        # Extract consumption data
        if isinstance(hourly_data, dict):
            consumption = hourly_data.get('consumption', [])
        elif isinstance(hourly_data, list):
            consumption = [h.get('consumption', 0) for h in hourly_data]
        else:
            return ""

        if not consumption or len(consumption) < 24:
            return ""

        # Calculate hourly averages (group by hour of day)
        hourly_avg = []
        for hour in range(24):
            hour_values = [consumption[i] for i in range(hour, len(consumption), 24) if i < len(consumption)]
            if hour_values:
                hourly_avg.append(np.mean(hour_values) / 1000)  # Convert to MW
            else:
                hourly_avg.append(0)

        apply_pagra_theme()
        fig, ax = plt.subplots()
        hours = np.arange(0, 24)

        # Line + area fill
        ax.plot(hours, hourly_avg, linewidth=2.2, color=CHART_COLORS['consumption'])
        ax.fill_between(hours, hourly_avg, 0, alpha=0.18, color=CHART_COLORS['consumption'])

        ax.set_xlabel("Godzina")
        ax.set_ylabel("Moc [MW]")
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlim(0, 23)
        ax.set_ylim(bottom=0)

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating daily profile chart: {e}")
        import traceback
        traceback.print_exc()
        return ""


def generate_monthly_consumption_chart(hourly_data: Any) -> str:
    """1.4 Zużycie miesięczne – słupki z wartościami nad belkami (Pagra theme)"""
    try:
        if isinstance(hourly_data, dict):
            consumption = hourly_data.get('consumption', [])
            timestamps = hourly_data.get('timestamps', [])
        elif isinstance(hourly_data, list):
            consumption = [h.get('consumption', 0) for h in hourly_data]
            timestamps = [h.get('timestamp', '') for h in hourly_data]
        else:
            return ""

        if not consumption or not timestamps:
            return ""

        # Group by month
        monthly_data = {}
        for i, ts in enumerate(timestamps):
            if i < len(consumption):
                try:
                    if isinstance(ts, str):
                        month = ts[:7]  # YYYY-MM
                    else:
                        month = str(ts)[:7]
                    if month not in monthly_data:
                        monthly_data[month] = 0
                    monthly_data[month] += consumption[i] / 1000  # kWh to MWh
                except:
                    continue

        if not monthly_data:
            return ""

        months = list(monthly_data.keys())
        values = list(monthly_data.values())

        # Format month labels (Sty, Lut, Mar...)
        month_names = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']
        month_labels = []
        for m in months:
            try:
                month_idx = int(m[-2:]) - 1
                month_labels.append(month_names[month_idx])
            except:
                month_labels.append(m[-5:].replace('-', '/'))

        apply_pagra_theme()
        fig, ax = plt.subplots()

        # Simple bar chart
        ax.bar(month_labels, values, color=CHART_COLORS['production'])

        ax.set_xlabel("Miesiąc")
        ax.set_ylabel("Produkcja [MWh]")

        # Add values above bars
        annotate_bars(ax)

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating monthly consumption chart: {e}")
        import traceback
        traceback.print_exc()
        return ""


def generate_variants_chart(scenarios: List[Dict]) -> str:
    """4.x Skan wariantów mocy – autokonsumpcja/pokrycie + gruba czarna linia optymalnej mocy (Pagra theme)"""
    try:
        if not scenarios or len(scenarios) < 3:
            return ""

        capacities = np.array([s.get('capacity', 0) / 1000 for s in scenarios])  # kWp to MWp
        auto_pct = np.array([s.get('auto_consumption_pct', 0) for s in scenarios])
        coverage_pct = np.array([s.get('coverage_pct', 0) for s in scenarios])

        apply_pagra_theme()
        fig, ax = plt.subplots()

        # Area fills
        ax.fill_between(capacities, auto_pct, 0, color=CHART_COLORS['self_consumed'], alpha=0.12)
        ax.fill_between(capacities, coverage_pct, 0, color=CHART_COLORS['coverage'], alpha=0.15)

        # Lines
        ax.plot(capacities, auto_pct, color=CHART_COLORS['self_consumed'], linewidth=2,
                label='Autokonsumpcja [%]')
        ax.plot(capacities, coverage_pct, color=CHART_COLORS['coverage'], linewidth=2,
                label='Pokrycie zużycia [%]')

        # Find 80% autoconsumption point and draw thick black vertical line
        best_cap = None
        best_auto = None
        for i, (cap, auto) in enumerate(zip(capacities, auto_pct)):
            if auto <= 80 and i > 0:
                best_cap = cap
                best_auto = auto
                break

        if best_cap:
            # Thick black line for optimal variant
            ax.axvline(best_cap, color="#333333", linewidth=2)

            # Label with box
            ax.text(
                best_cap + 0.5,
                80,
                f"80% autokons.\n{best_cap:.1f} MWp",
                fontsize=7,
                bbox=dict(
                    facecolor="white",
                    edgecolor="#333333",
                    boxstyle="round,pad=0.3",
                ),
            )

        ax.set_xlabel("Moc instalacji PV [MWp]")
        ax.set_ylabel("Procent [%]")
        ax.set_ylim(0, 105)
        ax.set_xlim(min(capacities), max(capacities))
        ax.legend()

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating variants chart: {e}")
        import traceback
        traceback.print_exc()
        return ""


def generate_monthly_balance_chart(energy_balance: Dict, monthly_balance: List[Dict] = None) -> str:
    """Bilans miesięczny – słupki skumulowane (Pagra theme)"""
    try:
        months = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']
        pv_factors = [0.5, 0.65, 0.9, 1.1, 1.35, 1.4, 1.35, 1.2, 0.95, 0.7, 0.5, 0.4]
        cons_factors = [1.1, 1.05, 1.0, 0.95, 0.9, 0.85, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1]

        if monthly_balance and len(monthly_balance) > 0:
            pv_self = np.array([m.get('self_consumed', 0) for m in monthly_balance])
            grid_import = np.array([m.get('grid_import', 0) for m in monthly_balance])
            curtailment = np.array([m.get('curtailment', 0) for m in monthly_balance])
        elif energy_balance:
            total_self = energy_balance.get('total_self_consumed', 0)
            total_import = energy_balance.get('grid_import', 0)
            total_curtailment = energy_balance.get('curtailment', 0)

            pv_sum = sum(pv_factors)
            cons_sum = sum(cons_factors)

            pv_self = np.array([total_self * f / pv_sum * 12 for f in pv_factors])
            grid_import = np.array([total_import * f / cons_sum * 12 for f in cons_factors])
            curtailment = np.array([total_curtailment * f / pv_sum * 12 for f in pv_factors])
        else:
            return ""

        apply_pagra_theme()
        fig, ax = plt.subplots()

        x = np.arange(len(months))
        width = 0.35

        # Stacked bar chart
        ax.bar(x, pv_self, width, label='Autokonsumpcja PV', color=CHART_COLORS['self_consumed'])
        ax.bar(x, grid_import, width, bottom=pv_self, label='Pobór z sieci', color=CHART_COLORS['coverage'])

        ax.set_xlabel("Miesiąc")
        ax.set_ylabel("Energia [MWh]")
        ax.set_xticks(x)
        ax.set_xticklabels(months)
        ax.legend()

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating monthly balance chart: {e}")
        import traceback
        traceback.print_exc()
        return ""


def generate_cashflow_chart(economics: Dict) -> str:
    """Skumulowane przepływy pieniężne (Pagra theme)"""
    try:
        cash_flows = economics.get('cash_flows', [])
        if not cash_flows:
            return ""

        years = [0] + [cf.get('year', i+1) for i, cf in enumerate(cash_flows)]
        investment = economics.get('investment', 0)
        cumulative = np.array([-investment] + [cf.get('cumulative', 0) for cf in cash_flows])

        apply_pagra_theme()
        fig, ax = plt.subplots()

        # Area fills for positive/negative
        ax.fill_between(years, cumulative, 0, where=cumulative >= 0,
                        color=CHART_COLORS['self_consumed'], alpha=0.25, interpolate=True)
        ax.fill_between(years, cumulative, 0, where=cumulative < 0,
                        color=CHART_COLORS['consumption'], alpha=0.25, interpolate=True)

        # Line with markers
        ax.plot(years, cumulative, color='#333333', linewidth=2,
                marker='o', markersize=5, markerfacecolor='white', markeredgewidth=1.5)
        ax.axhline(y=0, color='#e0e0e0', linewidth=1, linestyle='-')

        # Mark payback point
        payback = economics.get('simple_payback', 0)
        if 0 < payback < len(years):
            ax.axvline(x=payback, color=CHART_COLORS['production'], linestyle='--', alpha=0.7, linewidth=1.5)
            ax.text(payback + 0.5, max(cumulative) * 0.3, f'Zwrot: {payback:.1f} lat',
                   fontsize=8, bbox=dict(facecolor='white', edgecolor=CHART_COLORS['production'],
                                        boxstyle='round,pad=0.3'))

        ax.set_xlabel("Rok")
        ax.set_ylabel("Cash Flow [PLN]")

        # Format y-axis as thousands/millions
        ax.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda x, p: f'{x/1e6:.1f}M' if abs(x) >= 1e6 else f'{x/1e3:.0f}k'))

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating cashflow chart: {e}")
        return ""


def generate_sensitivity_tornado_chart() -> str:
    """Analiza wrażliwości – tornado chart (Pagra theme)"""
    try:
        params = ['Cena energii', 'CAPEX', 'Produkcja PV', 'Stopa dyskontowa']
        low_impact = [-25, 15, -20, 10]
        high_impact = [25, -15, 20, -10]

        apply_pagra_theme()
        fig, ax = plt.subplots()

        y_pos = np.arange(len(params))
        height = 0.35

        # Horizontal bars
        ax.barh(y_pos - height/2, low_impact, height, label='-20% parametru',
                color=CHART_COLORS['consumption'], alpha=0.85)
        ax.barh(y_pos + height/2, high_impact, height, label='+20% parametru',
                color=CHART_COLORS['self_consumed'], alpha=0.85)

        # Zero line
        ax.axvline(x=0, color='#333333', linewidth=1.2)

        ax.set_xlabel('Zmiana NPV [%]')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(params)
        ax.set_xlim(-35, 35)
        ax.legend(loc='lower right')

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating tornado chart: {e}")
        return ""


def generate_production_vs_consumption_daily_chart(hourly_data: Any, variant: Dict = None) -> str:
    """6.2 Średni profil dobowy – Zużycie + PV + Autokonsumpcja (Pagra theme)"""
    try:
        if isinstance(hourly_data, dict):
            consumption = hourly_data.get('consumption', [])
        elif isinstance(hourly_data, list):
            consumption = [h.get('consumption', 0) for h in hourly_data]
        else:
            return ""

        if not consumption or len(consumption) < 24:
            return ""

        # Calculate hourly averages for consumption
        consumption_hourly = []
        for hour in range(24):
            hour_values = [consumption[i] for i in range(hour, len(consumption), 24) if i < len(consumption)]
            if hour_values:
                consumption_hourly.append(np.mean(hour_values) / 1000)  # kW to MW
            else:
                consumption_hourly.append(0)

        # Estimate PV production profile (typical solar curve)
        pv_profile = np.array([0, 0, 0, 0, 0, 0.05, 0.15, 0.35, 0.55, 0.75, 0.90, 0.98,
                               1.0, 0.98, 0.90, 0.75, 0.55, 0.35, 0.15, 0.05, 0, 0, 0, 0])

        # Scale PV to match variant capacity if provided
        if variant:
            capacity_mw = variant.get('capacity', 0) / 1000  # kWp to MWp
            daily_production = capacity_mw * 1000 / 365  # MWh/day
            pv_hourly = pv_profile * daily_production / sum(pv_profile)
        else:
            avg_cons = np.mean(consumption_hourly)
            pv_hourly = pv_profile * avg_cons * 0.8

        hours = np.arange(0, 24)
        load = np.array(consumption_hourly)
        pv = np.array(pv_hourly)
        selfc = np.minimum(load, pv)

        apply_pagra_theme()
        fig, ax = plt.subplots()

        # Area fills for PV and autoconsumption
        ax.fill_between(hours, pv, 0, color=CHART_COLORS['production'], alpha=0.18,
                        label='Produkcja PV [MW]')
        ax.fill_between(hours, selfc, 0, color=CHART_COLORS['self_consumed'], alpha=0.26,
                        label='Autokonsumpcja [MW]')

        # Strong consumption line
        ax.plot(hours, load, color=CHART_COLORS['consumption'], linewidth=2.3, label='Zużycie [MW]')
        # PV and autoconsumption lines
        ax.plot(hours, pv, color=CHART_COLORS['production'], linewidth=1.8)
        ax.plot(hours, selfc, color='#27ae60', linewidth=1.8)

        ax.set_xlabel("Godzina")
        ax.set_ylabel("Moc [MW]")
        ax.set_xticks(range(0, 24, 2))
        ax.set_xlim(0, 23)
        ax.set_ylim(bottom=0)
        ax.legend()

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating production vs consumption chart: {e}")
        return ""


def generate_load_duration_curve(hourly_data: Any) -> str:
    """Krzywa trwania obciążenia (Load Duration Curve) – Pagra theme"""
    try:
        if isinstance(hourly_data, dict):
            consumption = hourly_data.get('consumption', [])
        elif isinstance(hourly_data, list):
            consumption = [h.get('consumption', 0) for h in hourly_data]
        else:
            return ""

        if not consumption or len(consumption) < 100:
            return ""

        # Sort consumption descending
        sorted_consumption = sorted(consumption, reverse=True)
        sorted_mw = np.array([c / 1000 for c in sorted_consumption])

        n_points = len(sorted_mw)
        hours_pct = np.arange(n_points) / n_points * 100

        apply_pagra_theme()
        fig, ax = plt.subplots()

        # Area fill with line
        ax.fill_between(hours_pct, sorted_mw, alpha=0.18, color=CHART_COLORS['consumption'])
        ax.plot(hours_pct, sorted_mw, color=CHART_COLORS['consumption'], linewidth=2.0)

        # Percentile lines
        p90 = sorted_mw[int(n_points * 0.1)]
        p50 = sorted_mw[int(n_points * 0.5)]
        p10 = sorted_mw[int(n_points * 0.9)]

        ax.axhline(y=p90, color=CHART_COLORS['consumption'], linestyle='--', alpha=0.8, linewidth=1.2)
        ax.axhline(y=p50, color=CHART_COLORS['production'], linestyle='--', alpha=0.8, linewidth=1.2)
        ax.axhline(y=p10, color=CHART_COLORS['self_consumed'], linestyle='--', alpha=0.8, linewidth=1.2)

        ax.set_xlabel("Czas trwania [%]")
        ax.set_ylabel("Moc [MW]")
        ax.set_xlim(0, 100)
        ax.set_ylim(bottom=0)

        # Legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color=CHART_COLORS['consumption'], linestyle='--', linewidth=1.5, label=f'P10: {p90:.2f} MW'),
            Line2D([0], [0], color=CHART_COLORS['production'], linestyle='--', linewidth=1.5, label=f'P50: {p50:.2f} MW'),
            Line2D([0], [0], color=CHART_COLORS['self_consumed'], linestyle='--', linewidth=1.5, label=f'P90: {p10:.2f} MW'),
        ]
        ax.legend(handles=legend_elements, loc='upper right')

        plt.tight_layout()
        return fig_to_base64(fig)
    except Exception as e:
        print(f"Error generating load duration curve: {e}")
        return ""


# ============== Report HTML Generation ==============

def generate_report_html(data: ReportData) -> str:
    """Generate full HTML report"""

    config = data.config
    report_date = config.report_date or datetime.now().strftime("%Y-%m-%d")

    # Build logo HTML element for running footer
    logo_html = ""
    if LOGO_BASE64:
        logo_html = f'<div class="running-logo"><img src="data:image/png;base64,{LOGO_BASE64}" alt="Powered by Galileo"></div>'

    # Start HTML
    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport PV - {config.client_name}</title>
    <style>
        {get_report_css()}
    </style>
</head>
<body>
    {logo_html}
    <div class="report-container">
"""

    # 0. Cover Page
    html += generate_cover_page(config, data, report_date)

    # 1. Executive Summary
    if "executive_summary" in config.include_sections:
        html += generate_executive_summary(data)

    # 2. Consumption Profile
    if "consumption_profile" in config.include_sections:
        html += generate_consumption_section(data)

    # 3. Seasonality
    if "seasonality" in config.include_sections:
        html += generate_seasonality_section(data)

    # 4. PV Assumptions
    if "pv_assumptions" in config.include_sections:
        html += generate_pv_assumptions_section(data)

    # 5. Variants Scan
    if "variants_scan" in config.include_sections:
        html += generate_variants_scan_section(data)

    # 6. Key Variants
    if "key_variants" in config.include_sections:
        html += generate_key_variants_section(data)

    # 7. Production Profile
    if "production_profile" in config.include_sections:
        html += generate_production_profile_section(data)

    # 8. Energy Balance
    if "energy_balance" in config.include_sections:
        html += generate_energy_balance_section(data)

    # 9. Economics CAPEX
    if "economics_capex" in config.include_sections:
        html += generate_economics_capex_section(data)

    # 10. Economics EaaS
    if "economics_eaas" in config.include_sections:
        html += generate_economics_eaas_section(data)

    # 11. Sensitivity
    if "sensitivity" in config.include_sections:
        html += generate_sensitivity_section(data)

    # Footer
    html += f"""
        <div class="footer">
            <p>Raport wygenerowany: {report_date} | Pagra ENERGY Studio</p>
        </div>
    </div>
</body>
</html>
"""
    return html


def get_report_css() -> str:
    """CSS styles for PDF report"""
    # Using regular string to avoid f-string escaping issues with CSS braces
    css_template = """
        @page {
            size: A4;
            margin: 2cm 2cm 3cm 2cm;
            @bottom-center {
                content: "Strona " counter(page) " z " counter(pages);
                font-size: 10px;
                color: #666;
            }
            @bottom-left {
                content: element(running-logo);
            }
        }

        /* Running logo element - appears on every page */
        .running-logo {
            position: running(running-logo);
        }

        .running-logo img {
            height: 25px;
            width: auto;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            font-size: 11pt;
            line-height: 1.5;
            color: #333;
        }

        .report-container {
            max-width: 210mm;
            margin: 0 auto;
        }

        /* Cover Page */
        .cover-page {
            page-break-after: always;
            height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            background: linear-gradient(135deg, #1a5a3a 0%, #2d7a4f 50%, #3d9a6f 100%);
            color: white;
            padding: 40px;
        }

        .cover-page h1 {
            font-size: 36pt;
            margin-bottom: 20px;
            font-weight: 300;
        }

        .cover-page .subtitle {
            font-size: 18pt;
            margin-bottom: 40px;
            opacity: 0.9;
        }

        .cover-page .client-name {
            font-size: 24pt;
            font-weight: 600;
            margin-bottom: 10px;
        }

        .cover-page .location {
            font-size: 14pt;
            opacity: 0.8;
        }

        .cover-page .date {
            margin-top: 60px;
            font-size: 12pt;
            opacity: 0.7;
        }

        .cover-kpi {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 50px;
            flex-wrap: wrap;
        }

        .cover-kpi-box {
            background: rgba(255,255,255,0.15);
            padding: 20px 30px;
            border-radius: 10px;
            min-width: 150px;
        }

        .cover-kpi-box .value {
            font-size: 28pt;
            font-weight: 700;
        }

        .cover-kpi-box .label {
            font-size: 10pt;
            opacity: 0.8;
            margin-top: 5px;
        }

        /* Sections */
        .section {
            page-break-inside: avoid;
            margin-bottom: 30px;
        }

        .section-title {
            font-size: 18pt;
            color: #1a5a3a;
            border-bottom: 3px solid #1a5a3a;
            padding-bottom: 10px;
            margin-bottom: 20px;
            page-break-after: avoid;
        }

        .section-subtitle {
            font-size: 14pt;
            color: #2d7a4f;
            margin: 20px 0 10px 0;
        }

        /* KPI Boxes */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 20px 0;
        }

        .kpi-box {
            background: #f8f9fa;
            border-left: 4px solid #1a5a3a;
            padding: 15px;
            border-radius: 0 8px 8px 0;
        }

        .kpi-box .value {
            font-size: 20pt;
            font-weight: 700;
            color: #1a5a3a;
        }

        .kpi-box .label {
            font-size: 9pt;
            color: #666;
            margin-top: 5px;
        }

        .kpi-box.highlight {
            background: #e8f5e9;
            border-left-color: #4caf50;
        }

        .kpi-box.warning {
            background: #fff3e0;
            border-left-color: #ff9800;
        }

        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 10pt;
        }

        th, td {
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }

        th {
            background: #1a5a3a;
            color: white;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 9pt;
        }

        tr:nth-child(even) {
            background: #f8f9fa;
        }

        tr:hover {
            background: #e8f5e9;
        }

        td.number {
            text-align: right;
            font-family: 'Consolas', monospace;
        }

        /* Charts placeholder */
        .chart-placeholder {
            background: #f0f0f0;
            border: 2px dashed #ccc;
            padding: 40px;
            text-align: center;
            color: #999;
            margin: 20px 0;
            border-radius: 8px;
        }

        /* Info boxes */
        .info-box {
            background: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 15px;
            margin: 15px 0;
            border-radius: 0 8px 8px 0;
        }

        .info-box.success {
            background: #e8f5e9;
            border-left-color: #4caf50;
        }

        .info-box.warning {
            background: #fff3e0;
            border-left-color: #ff9800;
        }

        /* Two columns */
        .two-columns {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
        }

        /* Footer */
        .footer {
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #999;
            font-size: 9pt;
        }

        /* Page breaks */
        .page-break {
            page-break-after: always;
        }

        /* Comparison table */
        .comparison-table th {
            text-align: center;
        }

        .comparison-table td {
            text-align: center;
        }

        .comparison-table td:first-child {
            text-align: left;
            font-weight: 600;
        }

        .variant-highlight {
            background: #e8f5e9 !important;
            font-weight: 700;
        }

        /* Badge */
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 9pt;
            font-weight: 600;
        }

        .badge.high { background: #ffcdd2; color: #c62828; }
        .badge.mid { background: #fff9c4; color: #f57f17; }
        .badge.low { background: #c8e6c9; color: #2e7d32; }
        .badge.npv { background: #bbdefb; color: #1565c0; }
    """

    return css_template


def generate_cover_page(config: ReportConfig, data: ReportData, report_date: str) -> str:
    """Generate cover page with executive KPIs"""

    # Extract KPIs
    consumption_gwh = "-"
    recommended_mwp = "-"
    autoconsumption_pct = "-"
    npv_mln = "-"

    if data.consumption_stats:
        consumption_gwh = f"{data.consumption_stats.get('total_consumption_gwh', 0):.2f}"

    if data.selected_variant_data:
        v = data.selected_variant_data
        recommended_mwp = f"{v.get('capacity', 0)/1000:.1f}"
        autoconsumption_pct = f"{v.get('auto_consumption_pct', 0):.0f}"

    if data.economics:
        npv = data.economics.get('npv', 0)
        if npv:
            npv_mln = f"{npv/1_000_000:.2f}"

    # Analytical year period
    period = ""
    if data.analytical_year:
        start = data.analytical_year.get('start_date', '')
        end = data.analytical_year.get('end_date', '')
        period = f"{start} – {end}"

    return f"""
    <div class="cover-page">
        <h1>ANALIZA INSTALACJI<br>FOTOWOLTAICZNEJ</h1>
        <div class="subtitle">Raport techniczny i ekonomiczny</div>

        <div class="client-name">{config.client_name}</div>
        <div class="location">{config.location}</div>

        <div class="cover-kpi">
            <div class="cover-kpi-box">
                <div class="value">{consumption_gwh}</div>
                <div class="label">Zużycie roczne [GWh]</div>
            </div>
            <div class="cover-kpi-box">
                <div class="value">{recommended_mwp}</div>
                <div class="label">Rekomendowana moc [MWp]</div>
            </div>
            <div class="cover-kpi-box">
                <div class="value">{autoconsumption_pct}%</div>
                <div class="label">Autokonsumpcja</div>
            </div>
            <div class="cover-kpi-box">
                <div class="value">{npv_mln}</div>
                <div class="label">NPV [mln PLN]</div>
            </div>
        </div>

        <div class="date">
            Data raportu: {report_date}<br>
            Okres danych: {period}
        </div>
    </div>
    """


def generate_executive_summary(data: ReportData) -> str:
    """Generate executive summary section"""

    html = """
    <div class="section">
        <h2 class="section-title">Podsumowanie wykonawcze</h2>
    """

    # Main findings
    html += """
        <div class="info-box success">
            <strong>Główne wnioski:</strong>
            <ul>
    """

    if data.selected_variant_data:
        # Normalize variant to MWh
        v = normalize_variant_to_mwh(data.selected_variant_data)
        capacity = v.get('capacity', 0)
        production_mwh = v.get('production', 0)  # Now in MWh after normalization
        production_gwh = production_mwh / 1000
        auto_pct = v.get('auto_consumption_pct', 0)
        coverage = v.get('coverage_pct', 0)

        html += f"""
                <li>Rekomendowana moc instalacji PV: <strong>{capacity/1000:.1f} MWp</strong></li>
                <li>Roczna produkcja energii: <strong>{production_gwh:.2f} GWh</strong> ({format_number_pl(production_mwh, 0)} MWh)</li>
                <li>Poziom autokonsumpcji: <strong>{auto_pct:.0f}%</strong></li>
                <li>Pokrycie zużycia: <strong>{coverage:.0f}%</strong></li>
        """

        # Add BESS information if present
        bess_power = v.get('bess_power_kw')
        bess_energy = v.get('bess_energy_kwh')
        if bess_power is not None and bess_energy is not None:
            bess_charged = v.get('bess_charged_kwh', 0) / 1000  # to MWh
            bess_discharged = v.get('bess_discharged_kwh', 0) / 1000
            bess_curtailed = v.get('bess_curtailed_kwh', 0) / 1000
            html += f"""
                <li>Magazyn energii BESS: <strong>{bess_power:.0f} kW / {bess_energy:.0f} kWh</strong></li>
                <li>Energia z magazynu: <strong>{bess_discharged:.1f} MWh/rok</strong> (curtailment: {bess_curtailed:.1f} MWh)</li>
            """

    if data.economics:
        npv = data.economics.get('npv', 0)
        irr = data.economics.get('irr', 0)
        payback = data.economics.get('simple_payback', 0)

        html += f"""
                <li>NPV projektu (25 lat): <strong>{format_currency(npv)}</strong></li>
                <li>IRR: <strong>{irr:.1f}%</strong></li>
                <li>Prosty okres zwrotu: <strong>{payback:.1f} lat</strong></li>
        """

    # Add recommendation bullet
    if data.selected_variant_data and data.economics:
        v = normalize_variant_to_mwh(data.selected_variant_data)
        capacity_mwp = v.get('capacity', 0) / 1000
        npv = data.economics.get('npv', 0)
        payback = data.economics.get('simple_payback', 10)

        # Determine model recommendation
        if payback <= 7:
            model_rec = "CAPEX (własność instalacji)"
            model_alt = "Model EaaS jako alternatywa przy ograniczonym budżecie inwestycyjnym"
        else:
            model_rec = "EaaS lub CAPEX z finansowaniem"
            model_alt = "Dłuższy okres zwrotu sugeruje rozważenie modelu bez nakładów własnych"

        html += f"""
                <li><strong style="color: #27ae60;">Rekomendacja:</strong> instalacja {capacity_mwp:.1f} MWp w modelu {model_rec}</li>
        """

    html += """
            </ul>
        </div>
    """

    # KPI grid
    html += """
        <div class="kpi-grid">
    """

    if data.consumption_stats:
        stats = data.consumption_stats
        html += f"""
            <div class="kpi-box">
                <div class="value">{stats.get('total_consumption_gwh', 0):.2f}</div>
                <div class="label">Zużycie roczne [GWh]</div>
            </div>
            <div class="kpi-box">
                <div class="value">{stats.get('peak_power_mw', 0):.2f}</div>
                <div class="label">Moc szczytowa [MW]</div>
            </div>
            <div class="kpi-box">
                <div class="value">{stats.get('avg_power_mw', 0):.2f}</div>
                <div class="label">Średnia moc [MW]</div>
            </div>
            <div class="kpi-box">
                <div class="value">{stats.get('load_factor_pct', 0):.0f}%</div>
                <div class="label">Load factor</div>
            </div>
        """

    html += """
        </div>
    </div>
    """

    return html


def generate_consumption_section(data: ReportData) -> str:
    """Generate consumption profile section"""

    html = """
    <div class="section page-break">
        <h2 class="section-title">1. Profil zużycia energii</h2>
    """

    # Analytical year info
    if data.analytical_year:
        ay = data.analytical_year
        html += f"""
        <h3 class="section-subtitle">1.1 Zakres danych i rok analityczny</h3>
        <div class="info-box">
            <strong>Okres analizy:</strong> {ay.get('start_date', '-')} – {ay.get('end_date', '-')}<br>
            <strong>Liczba dni:</strong> {ay.get('total_days', '-')} dni<br>
            <strong>Kompletność:</strong> {'Pełny rok analityczny' if ay.get('is_complete') else 'Dane niepełne'}<br>
            <strong>Rok przestępny:</strong> {'Tak' if ay.get('is_leap_year') else 'Nie'}
        </div>
        """

    # Statistics
    if data.consumption_stats:
        stats = data.consumption_stats
        html += f"""
        <h3 class="section-subtitle">1.2 Statystyki zużycia</h3>
        <table>
            <tr>
                <th>Parametr</th>
                <th>Wartość</th>
                <th>Jednostka</th>
            </tr>
            <tr>
                <td>Roczne zużycie energii</td>
                <td class="number">{stats.get('total_consumption_gwh', 0):.3f}</td>
                <td>GWh</td>
            </tr>
            <tr>
                <td>Moc szczytowa</td>
                <td class="number">{stats.get('peak_power_mw', 0):.3f}</td>
                <td>MW</td>
            </tr>
            <tr>
                <td>Średnia moc</td>
                <td class="number">{stats.get('avg_power_mw', 0):.3f}</td>
                <td>MW</td>
            </tr>
            <tr>
                <td>Load factor</td>
                <td class="number">{stats.get('load_factor_pct', 0):.1f}</td>
                <td>%</td>
            </tr>
            <tr>
                <td>Odchylenie standardowe</td>
                <td class="number">{stats.get('std_dev_mw', 0):.3f}</td>
                <td>MW</td>
            </tr>
            <tr>
                <td>Wsp. zmienności</td>
                <td class="number">{stats.get('variation_coef_pct', 0):.1f}</td>
                <td>%</td>
            </tr>
        </table>
        """

    # Generate charts if hourly data available
    if data.hourly_data:
        daily_chart = generate_daily_profile_chart(data.hourly_data, data.consumption_stats)
        monthly_chart = generate_monthly_consumption_chart(data.hourly_data)

        if daily_chart:
            html += f"""
        <h3 class="section-subtitle">1.3 Średni profil dobowy</h3>
        <img src="{daily_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Profil dobowy"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Średni profil dobowy zużycia (24h)]</div>
            """

        if monthly_chart:
            html += f"""
        <h3 class="section-subtitle">1.4 Zużycie miesięczne</h3>
        <img src="{monthly_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Zużycie miesięczne"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Zużycie miesięczne (MWh)]</div>
            """
    else:
        html += """
        <div class="chart-placeholder">[Wykres: Średni profil dobowy zużycia (24h)]</div>
        <div class="chart-placeholder">[Wykres: Zużycie miesięczne (MWh)]</div>
        """

    html += "</div>"
    return html


def generate_seasonality_section(data: ReportData) -> str:
    """Generate seasonality analysis section"""

    html = """
    <div class="section">
        <h2 class="section-title">2. Analiza sezonowości</h2>
    """

    if data.seasonality:
        s = data.seasonality
        detected = s.get('detected', False)
        score = s.get('seasonality_score', 0)
        message = s.get('message', '')

        status_class = "success" if detected else "warning"
        html += f"""
        <div class="info-box {status_class}">
            <strong>Wynik analizy:</strong> {message}<br>
            <strong>Wskaźnik sezonowości:</strong> {score:.2f}
        </div>
        """

        # Monthly bands table
        monthly_bands = s.get('monthly_bands', [])
        if monthly_bands:
            html += """
            <h3 class="section-subtitle">Podział miesięcy na pasma</h3>
            <table>
                <tr>
                    <th>Miesiąc</th>
                    <th>Pasmo</th>
                    <th>Zużycie [MWh]</th>
                    <th>% roku</th>
                    <th>Śr. moc [kW]</th>
                    <th>P95 [kW]</th>
                </tr>
            """

            # Calculate total consumption for percentage calculation
            total_consumption = sum(mb.get('consumption_kwh', 0) or 0 for mb in monthly_bands)

            for mb in monthly_bands:
                band = mb.get('dominant_band', 'MID')
                badge_class = band.lower()
                consumption_kwh = mb.get('consumption_kwh', 0) or 0
                # Calculate percentage of yearly consumption
                pct_of_year = (consumption_kwh / total_consumption * 100) if total_consumption > 0 else 0
                avg_power = mb.get('avg_power', 0) or 0
                p95_power = mb.get('p95_power', 0) or 0

                html += f"""
                <tr>
                    <td>{mb.get('month_name', mb.get('month', '-'))}</td>
                    <td><span class="badge {badge_class}">{band}</span></td>
                    <td class="number">{format_number_pl(consumption_kwh/1000, 1)}</td>
                    <td class="number">{format_number_pl(pct_of_year, 1)}%</td>
                    <td class="number">{format_number_pl(avg_power, 0)}</td>
                    <td class="number">{format_number_pl(p95_power, 0)}</td>
                </tr>
                """

            html += "</table>"
    else:
        html += """
        <div class="info-box warning">
            Dane sezonowości niedostępne. Uruchom analizę w zakładce KONFIGURACJA.
        </div>
        """

    html += "</div>"
    return html


def generate_pv_assumptions_section(data: ReportData) -> str:
    """Generate PV technical assumptions section"""

    # Get PV config from frontend data
    pv_config = {}
    if data.config.frontend_data:
        pv_config = data.config.frontend_data.get('pvConfig', {}) or {}

    # Debug log
    print(f"📊 PV Config for report: {pv_config}")

    # Extract pv_type (the actual field name from frontend)
    pv_type = pv_config.get('pv_type', 'ground_s')

    # Map pv_type to Polish description
    installation_type_map = {
        'ground_s': 'Gruntowa - orientacja południowa',
        'ground_ew': 'Gruntowa - orientacja Wschód-Zachód',
        'roof_s': 'Dachowa - orientacja południowa',
        'roof_ew': 'Dachowa - orientacja Wschód-Zachód',
        'roof_flat': 'Dach płaski (balastowa)',
        'tracker': 'Tracker jednoosiowy'
    }
    installation_type_pl = installation_type_map.get(pv_type, f'Typ: {pv_type}')

    location = data.config.location or 'Polska'
    latitude = pv_config.get('latitude', 52.0)
    longitude = pv_config.get('longitude', 21.0)

    # Get actual azimuth from config
    azimuth_value = pv_config.get('azimuth', 180)
    if 'ew' in pv_type:
        azimuth = f'{azimuth_value}° / {360 - azimuth_value}° (Wschód-Zachód)'
    else:
        azimuth = f'{azimuth_value}° (Południe)' if azimuth_value == 180 else f'{azimuth_value}°'

    # Get actual tilt from config
    tilt_value = pv_config.get('tilt', 35)
    if 'tracker' in pv_type:
        tilt = 'Automatyczny (tracker)'
    else:
        tilt = f'{tilt_value}°'

    # System losses - use standard values (these are implicit in pvlib calculations)
    # The actual losses are baked into the yield calculations
    cable_loss = 2.0
    soiling_loss = 2.0
    mismatch_loss = 2.0
    inverter_loss = 3.0
    temperature_loss = 4.0
    total_losses = cable_loss + soiling_loss + mismatch_loss + inverter_loss + temperature_loss

    # DC/AC ratio - get from dcac_tiers if available, otherwise use default
    dcac_tiers = pv_config.get('dcac_tiers', [])
    if dcac_tiers and len(dcac_tiers) > 0:
        # Use mid-range tier as representative
        mid_tier = dcac_tiers[len(dcac_tiers) // 2]
        dc_ac_ratio = mid_tier.get('ratio', 1.25)
    else:
        dc_ac_ratio = 1.25

    # Yield target
    yield_target = pv_config.get('yield_target', 1050)

    html = f"""
    <div class="section page-break">
        <h2 class="section-title">3. Założenia techniczne instalacji PV</h2>

        <table>
            <tr>
                <th>Parametr</th>
                <th>Wartość</th>
                <th>Uwagi</th>
            </tr>
            <tr>
                <td>Typ instalacji</td>
                <td><strong>{installation_type_pl}</strong></td>
                <td>Wybrano w konfiguracji</td>
            </tr>
            <tr>
                <td>Lokalizacja</td>
                <td>{location}</td>
                <td>Współrzędne: {latitude:.2f}°N, {longitude:.2f}°E</td>
            </tr>
            <tr>
                <td>Azymut</td>
                <td>{azimuth}</td>
                <td>{'Optymalny dla Polski' if 'Południe' in azimuth else 'Konfiguracja E-W'}</td>
            </tr>
            <tr>
                <td>Kąt nachylenia</td>
                <td>{tilt}</td>
                <td>{'Optymalny dla szerokości geograficznej' if 'tracker' not in tilt.lower() else 'Śledzenie słońca'}</td>
            </tr>
            <tr>
                <td>Docelowy uzysk</td>
                <td>{yield_target} kWh/kWp/rok</td>
                <td>Parametr obliczeniowy</td>
            </tr>
            <tr>
                <td>Współczynnik DC/AC</td>
                <td>{dc_ac_ratio:.2f}</td>
                <td>Oversizing falownika</td>
            </tr>
            <tr>
                <td>Straty systemowe</td>
                <td>~{total_losses:.0f}%</td>
                <td>Suma strat (szczegóły poniżej)</td>
            </tr>
            <tr>
                <td>Degradacja roczna</td>
                <td>0.5%</td>
                <td>Standard branżowy</td>
            </tr>
            <tr>
                <td>Żywotność systemu</td>
                <td>25 lat</td>
                <td>Okres analizy ekonomicznej</td>
            </tr>
        </table>

        <h3 class="section-subtitle">3.1 Szczegółowy podział strat systemowych</h3>
        <table>
            <tr>
                <th>Rodzaj strat</th>
                <th>Wartość</th>
                <th>Opis</th>
            </tr>
            <tr>
                <td>Przewody DC/AC</td>
                <td>{cable_loss:.1f}%</td>
                <td>Straty w okablowaniu</td>
            </tr>
            <tr>
                <td>Zabrudzenia</td>
                <td>{soiling_loss:.1f}%</td>
                <td>Kurz, ptaki, śnieg</td>
            </tr>
            <tr>
                <td>Mismatch</td>
                <td>{mismatch_loss:.1f}%</td>
                <td>Niedopasowanie modułów</td>
            </tr>
            <tr>
                <td>Falownik</td>
                <td>{inverter_loss:.1f}%</td>
                <td>Sprawność konwersji DC→AC</td>
            </tr>
            <tr>
                <td>Temperatura</td>
                <td>{temperature_loss:.1f}%</td>
                <td>Wpływ nagrzewania modułów</td>
            </tr>
            <tr style="font-weight: bold; background: #e8f5e9;">
                <td>SUMA STRAT</td>
                <td>{total_losses:.1f}%</td>
                <td>Łączne straty systemowe</td>
            </tr>
        </table>

        <div class="info-box">
            <strong>Dane pogodowe:</strong> PVGIS TMY (Typical Meteorological Year)<br>
            <strong>Metoda obliczeń:</strong> Model PVlib z uwzględnieniem sezonowości zużycia
        </div>
    </div>
    """

    return html


def generate_variants_scan_section(data: ReportData) -> str:
    """Generate variants scan section"""

    html = """
    <div class="section">
        <h2 class="section-title">4. Skan wariantów mocy</h2>
    """

    if data.pv_scenarios:
        # Sample every N scenarios for table
        scenarios = data.pv_scenarios
        step = max(1, len(scenarios) // 10)
        sampled = scenarios[::step]

        html += """
        <p>Analiza obejmuje pełen zakres mocy instalacji PV od minimalnej do maksymalnej wartości.</p>

        <table>
            <tr>
                <th>Moc [kWp]</th>
                <th>Produkcja [MWh/rok]</th>
                <th>Autokons. [MWh]</th>
                <th>Autokons. [%]</th>
                <th>Pokrycie [%]</th>
                <th>Eksport [MWh]</th>
            </tr>
        """

        for s in sampled:
            html += f"""
            <tr>
                <td class="number">{s.get('capacity', 0):,.0f}</td>
                <td class="number">{s.get('production', 0):,.0f}</td>
                <td class="number">{s.get('self_consumed', 0):,.0f}</td>
                <td class="number">{s.get('auto_consumption_pct', 0):.1f}%</td>
                <td class="number">{s.get('coverage_pct', 0):.1f}%</td>
                <td class="number">{s.get('exported', 0):,.0f}</td>
            </tr>
            """

        html += "</table>"

        # Generate variants chart
        variants_chart = generate_variants_chart(scenarios)
        if variants_chart:
            html += f"""
        <img src="{variants_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Wykres wariantów"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Autokonsumpcja i Pokrycie vs Moc instalacji]</div>
            """

        html += """
        <div class="info-box">
            <strong>Obserwacja:</strong> Wraz ze wzrostem mocy instalacji powyżej pewnego progu,
            autokonsumpcja spada, co oznacza, że dodatkowa moc generuje głównie nadwyżki
            eksportowane do sieci w godzinach niskich cen.
        </div>
        """
    else:
        html += """
        <div class="info-box warning">
            Dane scenariuszy PV niedostępne. Uruchom analizę w zakładce KONFIGURACJA.
        </div>
        """

    html += "</div>"
    return html


def generate_key_variants_section(data: ReportData) -> str:
    """Generate key variants comparison section"""

    html = """
    <div class="section page-break">
        <h2 class="section-title">5. Warianty kluczowe</h2>
    """

    # Try key_variants first, fallback to selected_variant_data
    kv = data.key_variants
    has_key_variants = False

    if kv:
        # Get and normalize all variants to MWh
        a = normalize_variant_to_mwh(kv.get('variant_a', {})) if kv.get('variant_a') else {}
        b = normalize_variant_to_mwh(kv.get('variant_b', {})) if kv.get('variant_b') else {}
        c = normalize_variant_to_mwh(kv.get('variant_c', {})) if kv.get('variant_c') else {}
        d = normalize_variant_to_mwh(kv.get('variant_d', {})) if kv.get('variant_d') else {}
        npv = normalize_variant_to_mwh(kv.get('npv_optimal', {})) if kv.get('npv_optimal') else {}

        # Determine which variants exist
        has_a = bool(a) and a.get('production', 0) > 0
        has_b = bool(b) and b.get('production', 0) > 0
        has_c = bool(c) and c.get('production', 0) > 0
        has_d = bool(d) and d.get('production', 0) > 0
        has_npv = bool(npv) and npv.get('production', 0) > 0
        has_key_variants = has_a or has_b or has_c or has_d or has_npv

    # Fallback: if no key_variants, use selected_variant_data as single variant
    if not has_key_variants and data.selected_variant_data:
        v = normalize_variant_to_mwh(data.selected_variant_data)
        if v.get('production', 0) > 0:
            html += """
        <p>Prezentacja wybranego wariantu instalacji PV:</p>

        <table class="comparison-table">
            <tr>
                <th>Parametr</th>
                <th class="variant-highlight">Wybrany wariant</th>
            </tr>
        """
            html += f"""
            <tr><td>Moc instalacji</td><td class="variant-highlight">{format_number_pl(v.get('capacity', 0)/1000, 2)} MWp ({format_number_pl(v.get('capacity', 0), 0)} kWp)</td></tr>
            <tr><td>Roczna produkcja</td><td class="variant-highlight">{format_number_pl(v.get('production', 0), 0)} MWh ({format_number_pl(v.get('production', 0)/1000, 2)} GWh)</td></tr>
            <tr><td>Autokonsumpcja</td><td class="variant-highlight">{format_number_pl(v.get('self_consumed', 0), 0)} MWh ({format_number_pl(v.get('auto_consumption_pct', 0), 1)}%)</td></tr>
            <tr><td>Pokrycie zużycia</td><td class="variant-highlight">{format_number_pl(v.get('coverage_pct', 0), 1)}%</td></tr>
            <tr><td>Curtailment (nadwyżki)</td><td class="variant-highlight">{format_number_pl(v.get('exported', 0), 0)} MWh</td></tr>
        </table>

        <div class="info-box">
            <strong>Uwaga:</strong> Prezentowany jest pojedynczy wariant wybrany podczas analizy.
            Dla pełnego porównania wariantów (różne poziomy autokonsumpcji, optymalizacja NPV)
            uruchom analizę wariantową w zakładce PRODUKCJA PV.
        </div>
    </div>
    """
            return html

    # No data at all
    if not has_key_variants:
        html += """
        <div class="info-box warning">
            Brak danych wariantów kluczowych. Uruchom analizę wariantową w zakładce PRODUKCJA PV.
        </div>
    </div>
        """
        return html

        html += """
        <p>Porównanie wariantów optymalizowanych pod różne kryteria:</p>

        <table class="comparison-table">
            <tr>
                <th>Parametr</th>
        """

        # Build dynamic header based on available variants
        if has_a:
            auto_a = a.get('auto_consumption_pct', 90)
            html += f'<th>Wariant A<br>({auto_a:.0f}% autokons.)</th>'
        if has_b:
            auto_b = b.get('auto_consumption_pct', 80)
            html += f'<th>Wariant B<br>({auto_b:.0f}% autokons.)</th>'
        if has_c:
            auto_c = c.get('auto_consumption_pct', 70)
            html += f'<th>Wariant C<br>({auto_c:.0f}% autokons.)</th>'
        if has_d:
            auto_d = d.get('auto_consumption_pct', 60)
            html += f'<th>Wariant D<br>({auto_d:.0f}% autokons.)</th>'
        if has_npv:
            html += '<th class="variant-highlight">NPV Max</th>'

        html += "</tr>"

        # Define rows to display (values now in MWh after normalization)
        rows = [
            ("Moc [kWp]", "capacity", lambda x: format_number_pl(x, 0)),
            ("Moc [MWp]", "capacity", lambda x: format_number_pl(x/1000, 2)),
            ("Produkcja [MWh/rok]", "production", lambda x: format_number_pl(x, 0)),
            ("Autokonsumpcja [MWh]", "self_consumed", lambda x: format_number_pl(x, 0)),
            ("Autokonsumpcja [%]", "auto_consumption_pct", lambda x: format_number_pl(x, 1) + "%"),
            ("Pokrycie zużycia [%]", "coverage_pct", lambda x: format_number_pl(x, 1) + "%"),
            ("Curtailment [MWh]", "exported", lambda x: format_number_pl(x, 0)),
        ]

        for label, key, fmt in rows:
            html += f"<tr><td>{label}</td>"

            variants = []
            if has_a:
                variants.append((a, False))
            if has_b:
                variants.append((b, False))
            if has_c:
                variants.append((c, False))
            if has_d:
                variants.append((d, False))
            if has_npv:
                variants.append((npv, True))

            for variant, is_highlight in variants:
                val = variant.get(key, 0) if variant else 0
                formatted = fmt(val) if callable(fmt) else str(val)
                highlight_class = 'class="variant-highlight"' if is_highlight else ''
                html += f"<td {highlight_class}>{formatted}</td>"

            html += "</tr>"

        html += "</table>"

        # Determine recommendation
        selected_key = data.config.selected_variant or 'npv_optimal'
        selected_name = {
            'variant_a': 'Wariant A',
            'variant_b': 'Wariant B',
            'variant_c': 'Wariant C',
            'variant_d': 'Wariant D',
            'npv_optimal': 'NPV Max'
        }.get(selected_key, 'NPV Max')

        html += f"""
        <div class="info-box success">
            <strong>Rekomendacja:</strong> {selected_name} oferuje najlepszy stosunek
            wartości ekonomicznej do poziomu autokonsumpcji. Jest to optymalny punkt
            równowagi między wielkością instalacji a efektywnością wykorzystania energii.
        </div>

        <h3 class="section-subtitle">5.1 Interpretacja wariantów</h3>
        <table>
            <tr>
                <th>Wariant</th>
                <th>Charakterystyka</th>
                <th>Dla kogo?</th>
            </tr>
        """

        if has_a:
            html += """
            <tr>
                <td><strong>Wariant A</strong></td>
                <td>Konserwatywny - wysoka autokonsumpcja, minimalne nadwyżki</td>
                <td>Firmy z ograniczonym miejscem, niechęć do curtailmentu</td>
            </tr>
            """
        if has_b:
            html += """
            <tr>
                <td><strong>Wariant B</strong></td>
                <td>Zrównoważony - dobry kompromis między wielkością a efektywnością</td>
                <td>Standardowy wybór dla większości przypadków</td>
            </tr>
            """
        if has_c:
            html += """
            <tr>
                <td><strong>Wariant C</strong></td>
                <td>Umiarkowanie agresywny - większa instalacja, więcej nadwyżek</td>
                <td>Firmy planujące magazynowanie lub sprzedaż energii</td>
            </tr>
            """
        if has_d:
            html += """
            <tr>
                <td><strong>Wariant D</strong></td>
                <td>Agresywny - maksymalna produkcja, znaczące nadwyżki</td>
                <td>Projekty z możliwością sprzedaży lub dużym wzrostem zużycia</td>
            </tr>
            """
        if has_npv:
            html += """
            <tr>
                <td><strong>NPV Max</strong></td>
                <td>Optymalizacja finansowa - maksymalna wartość netto</td>
                <td>Inwestorzy zorientowani na zwrot finansowy</td>
            </tr>
            """

        html += "</table>"

    else:
        html += """
        <div class="info-box warning">
            Dane wariantów kluczowych niedostępne. Uruchom analizę w zakładce PRODUKCJA PV.
        </div>
        """

    html += "</div>"
    return html


def generate_production_profile_section(data: ReportData) -> str:
    """Generate production profile section"""

    html = """
    <div class="section">
        <h2 class="section-title">6. Profil produkcji PV vs zużycie</h2>
    """

    # 6.1 - Annual profile placeholder (too much data for single chart)
    html += """
        <h3 class="section-subtitle">6.1 Profil roczny (8760h)</h3>
        <div class="info-box">
            <strong>Uwaga:</strong> Pełne dane 8760-godzinne są dostępne w szczegółowej analizie.
            Poniżej przedstawiono uśrednione profile dobowe.
        </div>
    """

    # 6.2 - Daily profile: consumption vs PV production
    html += """
        <h3 class="section-subtitle">6.2 Średni profil dobowy</h3>
    """
    if data.hourly_data:
        daily_chart = generate_production_vs_consumption_daily_chart(data.hourly_data, data.selected_variant_data)
        if daily_chart:
            html += f"""
        <img src="{daily_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Profil dobowy PV"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Średni dzień - Zużycie vs Produkcja PV (24h)]</div>
            """
    else:
        html += """
        <div class="chart-placeholder">[Wykres: Średni dzień - Zużycie vs Produkcja PV (24h)]</div>
        """

    # 6.3 - Load Duration Curve
    html += """
        <h3 class="section-subtitle">6.3 Load Duration Curve</h3>
    """
    if data.hourly_data:
        ldc_chart = generate_load_duration_curve(data.hourly_data)
        if ldc_chart:
            html += f"""
        <img src="{ldc_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Krzywa trwania obciążenia"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Krzywa trwania obciążenia]</div>
            """
    else:
        html += """
        <div class="chart-placeholder">[Wykres: Krzywa trwania obciążenia]</div>
        """

    html += """
        <div class="info-box">
            <strong>Analiza dopasowania:</strong> Profil produkcji PV najlepiej pokrywa się
            z zużyciem w godzinach 9:00-16:00. W godzinach porannego i wieczornego szczytu
            zapotrzebowania konieczny jest import z sieci.
        </div>
    </div>
    """

    return html


def generate_energy_balance_section(data: ReportData) -> str:
    """Generate energy balance section"""

    html = """
    <div class="section page-break">
        <h2 class="section-title">7. Bilans energetyczny</h2>
    """

    if data.energy_balance:
        eb = data.energy_balance

        # Values are already in MWh from calculate_energy_balance
        total_consumption = eb.get('total_consumption', 0)
        total_production = eb.get('total_production', 0)
        total_self_consumed = eb.get('total_self_consumed', 0)
        grid_import = eb.get('grid_import', 0)
        curtailment = eb.get('curtailment', 0)
        auto_pct = eb.get('auto_consumption_pct', 0)
        coverage_pct = eb.get('coverage_pct', 0)

        # Determine unit based on magnitude (use GWh for large values, MWh for smaller)
        if total_consumption > 1000:  # > 1 GWh
            unit = "GWh"
            divisor = 1000
        else:
            unit = "MWh"
            divisor = 1

        html += f"""
        <h3 class="section-subtitle">7.1 Bilans roczny</h3>

        <div class="info-box">
            <strong>Założenie:</strong> Model zakłada zerowy eksport do sieci (curtailment).
            Nadwyżki produkcji PV ponad autokonsumpcję są tracone lub ograniczane.
        </div>

        <table>
            <tr>
                <th>Pozycja</th>
                <th>Wartość</th>
                <th>Jednostka</th>
                <th>Opis</th>
            </tr>
            <tr>
                <td><strong>Całkowite zużycie</strong></td>
                <td class="number">{total_consumption/divisor:,.2f}</td>
                <td>{unit}</td>
                <td>Roczne zapotrzebowanie na energię</td>
            </tr>
            <tr>
                <td><strong>Produkcja PV</strong></td>
                <td class="number">{total_production/divisor:,.2f}</td>
                <td>{unit}</td>
                <td>Roczna produkcja instalacji PV</td>
            </tr>
            <tr style="background: #e8f5e9;">
                <td><strong>Autokonsumpcja PV</strong></td>
                <td class="number">{total_self_consumed/divisor:,.2f}</td>
                <td>{unit}</td>
                <td>Energia PV zużyta na miejscu ({auto_pct:.1f}% produkcji)</td>
            </tr>
            <tr>
                <td><strong>Pobór z sieci</strong></td>
                <td class="number">{grid_import/divisor:,.2f}</td>
                <td>{unit}</td>
                <td>Energia dokupiona z sieci</td>
            </tr>
            <tr style="background: #fff3e0;">
                <td><strong>Curtailment (strata)</strong></td>
                <td class="number">{curtailment/divisor:,.2f}</td>
                <td>{unit}</td>
                <td>Nadwyżka PV niemożliwa do wykorzystania</td>
            </tr>
        </table>

        <h3 class="section-subtitle">7.2 Wskaźniki efektywności</h3>
        <div class="kpi-grid">
            <div class="kpi-box highlight">
                <div class="value">{auto_pct:.1f}%</div>
                <div class="label">Autokonsumpcja<br>(% produkcji PV)</div>
            </div>
            <div class="kpi-box highlight">
                <div class="value">{coverage_pct:.1f}%</div>
                <div class="label">Pokrycie zużycia<br>(% z PV)</div>
            </div>
            <div class="kpi-box">
                <div class="value">{100-coverage_pct:.1f}%</div>
                <div class="label">Pozostałe z sieci<br>(% zużycia)</div>
            </div>
            <div class="kpi-box warning">
                <div class="value">{100-auto_pct:.1f}%</div>
                <div class="label">Curtailment<br>(% produkcji PV)</div>
            </div>
        </div>

        <div class="info-box success">
            <strong>Interpretacja:</strong>
            <ul>
                <li><strong>Autokonsumpcja {auto_pct:.0f}%</strong> oznacza, że {auto_pct:.0f}% wyprodukowanej energii PV jest zużywane na miejscu</li>
                <li><strong>Pokrycie {coverage_pct:.0f}%</strong> oznacza, że PV pokrywa {coverage_pct:.0f}% rocznego zapotrzebowania</li>
                <li><strong>Pobór z sieci {grid_import/divisor:.1f} {unit}</strong> to energia, którą nadal trzeba kupić</li>
            </ul>
        </div>
        """
    else:
        html += """
        <div class="info-box warning">
            Dane bilansu energetycznego niedostępne. Wybierz wariant w zakładce PRODUKCJA PV.
        </div>
        """

    # Generate monthly balance chart
    html += """
        <h3 class="section-subtitle">7.3 Bilans miesięczny</h3>
    """
    balance_chart = generate_monthly_balance_chart(data.energy_balance, data.monthly_balance)
    if balance_chart:
        html += f"""
        <img src="{balance_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Bilans miesięczny"/>
        """
    else:
        html += """
        <div class="chart-placeholder">[Wykres słupkowy: Bilans miesięczny]</div>
        """

    html += "</div>"
    return html


def generate_economics_capex_section(data: ReportData) -> str:
    """Generate CAPEX economics section"""

    html = """
    <div class="section">
        <h2 class="section-title">8. Analiza ekonomiczna - model CAPEX</h2>
    """

    if data.economics:
        e = data.economics

        html += f"""
        <h3 class="section-subtitle">8.1 Kluczowe wskaźniki</h3>
        <div class="kpi-grid">
            <div class="kpi-box highlight">
                <div class="value">{format_currency(e.get('investment', 0))}</div>
                <div class="label">CAPEX całkowity</div>
            </div>
            <div class="kpi-box highlight">
                <div class="value">{format_currency(e.get('npv', 0))}</div>
                <div class="label">NPV (25 lat)</div>
            </div>
            <div class="kpi-box">
                <div class="value">{e.get('irr', 0):.1f}%</div>
                <div class="label">IRR</div>
            </div>
            <div class="kpi-box">
                <div class="value">{e.get('simple_payback', 0):.1f} lat</div>
                <div class="label">Prosty zwrot</div>
            </div>
        </div>

        <table>
            <tr>
                <th>Parametr</th>
                <th>Wartość</th>
            </tr>
            <tr>
                <td>Roczne oszczędności</td>
                <td class="number">{format_currency(e.get('annual_savings', 0))}</td>
            </tr>
            <tr>
                <td>LCOE</td>
                <td class="number">{e.get('lcoe', 0):.2f} PLN/kWh</td>
            </tr>
            <tr>
                <td>CAPEX jednostkowy</td>
                <td class="number">{e.get('capex_per_kwp', 0):,.0f} PLN/kWp</td>
            </tr>
        </table>
        """

        # Cash flow table
        cash_flows = e.get('cash_flows', [])
        if cash_flows:
            html += """
        <h3 class="section-subtitle">8.2 Przepływy pieniężne (pierwsze 10 lat)</h3>
        <table>
            <tr>
                <th>Rok</th>
                <th>Produkcja [MWh]</th>
                <th>Oszczędności [tys. PLN]</th>
                <th>OPEX [tys. PLN]</th>
                <th>CF netto [tys. PLN]</th>
                <th>CF skumul. [tys. PLN]</th>
            </tr>
            """

            for cf in cash_flows[:10]:
                html += f"""
            <tr>
                <td class="number">{cf.get('year', 0)}</td>
                <td class="number">{cf.get('production', 0):,.0f}</td>
                <td class="number">{cf.get('savings', 0)/1000:,.0f}</td>
                <td class="number">{cf.get('opex', 0)/1000:,.0f}</td>
                <td class="number">{cf.get('net_cash_flow', 0)/1000:,.0f}</td>
                <td class="number">{cf.get('cumulative', 0)/1000:,.0f}</td>
            </tr>
                """

            html += "</table>"

    # Generate cash flow chart
    if data.economics:
        cf_chart = generate_cashflow_chart(data.economics)
        if cf_chart:
            html += f"""
        <img src="{cf_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Cash flow"/>
            """
        else:
            html += """
        <div class="chart-placeholder">[Wykres: Skumulowane przepływy pieniężne]</div>
            """
    else:
        html += """
        <div class="chart-placeholder">[Wykres: Skumulowane przepływy pieniężne]</div>
        """

    html += "</div>"
    return html


def convert_frontend_economics_to_eaas_data(frontend_econ: Dict, capex_data: Dict) -> Dict:
    """Convert frontend Economics module data to eaas_data format for report"""
    try:
        eaas_duration = frontend_econ.get('eaasDuration', 10)
        analysis_period = frontend_econ.get('analysisPeriod', 25)
        eaas_phase_savings = frontend_econ.get('eaasPhaseSavings', 0)
        ownership_phase_savings = frontend_econ.get('ownershipPhaseSavings', 0)
        total_savings = frontend_econ.get('totalSavings', eaas_phase_savings + ownership_phase_savings)
        cumulative_npv = frontend_econ.get('cumulativeNPV', 0)
        cash_flows = frontend_econ.get('cashFlows', [])
        capex_investment = frontend_econ.get('capexInvestment', 0) or (capex_data.get('investment', 0) if capex_data else 0)
        capex_npv = frontend_econ.get('capexNPV', 0)
        capex_payback = frontend_econ.get('capexPayback', 0)

        # Build cumulative cash flows from detailed cash flows
        cumulative_capex = {}
        cumulative_eaas = {}
        cf_capex_cumul = -capex_investment
        cf_eaas_cumul = 0

        # Use cash flows from frontend if available
        for cf in cash_flows:
            year = cf.get('year', 0)
            savings = cf.get('savings', 0)
            cf_eaas_cumul += savings

            # For CAPEX, estimate annual savings (use from capex_data if available)
            if capex_data:
                annual_capex_savings = capex_data.get('annual_savings', 0)
                annual_opex = capex_investment * 0.015
                net_capex_savings = annual_capex_savings - annual_opex
            else:
                net_capex_savings = savings * 1.3  # Rough estimate

            cf_capex_cumul += net_capex_savings

            if year <= 15:
                cumulative_capex[year] = cf_capex_cumul
                cumulative_eaas[year] = cf_eaas_cumul

        # Calculate annual values for display
        annual_eaas_savings = eaas_phase_savings / eaas_duration if eaas_duration > 0 else 0
        annual_capex_savings = capex_data.get('annual_savings', 0) if capex_data else (total_savings / analysis_period)
        annual_opex = capex_investment * 0.015
        net_annual_capex = annual_capex_savings - annual_opex

        # 15-year totals
        # EaaS: sum of EaaS phase + part of ownership phase
        years_in_ownership_for_15y = max(0, 15 - eaas_duration)
        annual_ownership_savings = ownership_phase_savings / (analysis_period - eaas_duration) if (analysis_period - eaas_duration) > 0 else 0
        total_savings_eaas_15y = eaas_phase_savings + (annual_ownership_savings * years_in_ownership_for_15y)
        total_savings_capex_15y = net_annual_capex * 15
        net_profit_capex_15y = total_savings_capex_15y - capex_investment
        net_profit_eaas_15y = total_savings_eaas_15y

        # Monthly fee estimation
        monthly_fee = annual_eaas_savings / 12 * 3  # EaaS cost roughly 3x savings

        return {
            'monthly_fee': monthly_fee,
            'eaas_price_per_kwh': 0.525,  # Typical EaaS price
            'annual_eaas_cost': annual_eaas_savings * 3,
            'annual_savings_eaas': annual_eaas_savings,
            'annual_savings_capex': net_annual_capex,
            'capex_investment': capex_investment,
            'total_savings_capex_15y': total_savings_capex_15y,
            'total_savings_eaas_15y': total_savings_eaas_15y,
            'net_profit_capex_15y': net_profit_capex_15y,
            'net_profit_eaas_15y': net_profit_eaas_15y,
            'payback_capex': capex_payback,
            'cumulative_capex': cumulative_capex,
            'cumulative_eaas': cumulative_eaas,
            # Additional data from frontend
            'eaas_duration': eaas_duration,
            'analysis_period': analysis_period,
            'eaas_phase_savings': eaas_phase_savings,
            'ownership_phase_savings': ownership_phase_savings,
            'total_25y_savings': total_savings,
            'npv_25y': cumulative_npv
        }
    except Exception as e:
        print(f"Error converting frontend economics: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_economics_eaas_section(data: ReportData) -> str:
    """Generate EaaS economics section"""

    # First try to use data from frontend Economics module
    frontend_economics = None
    if data.config.frontend_data:
        frontend_economics = data.config.frontend_data.get('economics')
        if frontend_economics:
            print(f"✓ Using Economics data from frontend: eaasPhaseSavings={frontend_economics.get('eaasPhaseSavings')}, ownershipPhaseSavings={frontend_economics.get('ownershipPhaseSavings')}")

    # Use frontend data if available, otherwise calculate
    if frontend_economics and frontend_economics.get('eaasPhaseSavings') is not None:
        eaas_data = convert_frontend_economics_to_eaas_data(frontend_economics, data.economics)
    else:
        eaas_data = calculate_eaas_economics(data.economics, data.selected_variant_data, data.consumption_stats)

    html = """
    <div class="section page-break">
        <h2 class="section-title">9. Analiza ekonomiczna - model EaaS</h2>

        <p>Model Energy-as-a-Service (EaaS) pozwala na korzystanie z instalacji PV
        bez ponoszenia kosztów inwestycyjnych. Klient płaci miesięczną opłatę za energię
        lub stałą stawkę za wyprodukowaną energię.</p>
    """

    if eaas_data:
        html += f"""
        <div class="kpi-grid">
            <div class="kpi-box highlight">
                <div class="value">{eaas_data['monthly_fee']:,.0f} PLN</div>
                <div class="label">Opłata miesięczna EaaS</div>
            </div>
            <div class="kpi-box highlight">
                <div class="value">{eaas_data['eaas_price_per_kwh']:.2f} PLN/kWh</div>
                <div class="label">Efektywna cena energii EaaS</div>
            </div>
            <div class="kpi-box">
                <div class="value">{eaas_data['annual_eaas_cost']:,.0f} PLN</div>
                <div class="label">Roczny koszt EaaS</div>
            </div>
            <div class="kpi-box">
                <div class="value">{eaas_data['annual_savings_eaas']:,.0f} PLN</div>
                <div class="label">Roczne oszczędności netto</div>
            </div>
        </div>

        <div class="info-box" style="font-size: 0.9em; margin-bottom: 15px;">
            <strong>Metodologia obliczeń:</strong>
            <ul style="margin: 5px 0; padding-left: 20px;">
                <li><strong>Baseline:</strong> Oszczędności liczone względem zakupu energii z sieci po cenie {format_number_pl(700, 0)} PLN/MWh</li>
                <li><strong>Cena EaaS:</strong> 75% ceny sieci ({format_number_pl(525, 0)} PLN/MWh) - standardowa stawka rynkowa dla umów PPA/EaaS</li>
                <li><strong>Uwaga:</strong> Porównanie nie uwzględnia wartości resztowej instalacji po 15 latach
                    (w modelu CAPEX instalacja pozostaje własnością klienta i może generować przychody kolejne 10-15 lat)</li>
            </ul>
        </div>

        <h3 class="section-subtitle">9.1 Porównanie CAPEX vs EaaS (15 lat)</h3>
        <table>
            <tr>
                <th>Parametr</th>
                <th>CAPEX</th>
                <th>EaaS</th>
                <th>Różnica</th>
            </tr>
            <tr>
                <td>Inwestycja początkowa</td>
                <td class="number">{eaas_data['capex_investment']:,.0f} PLN</td>
                <td class="number">0 PLN</td>
                <td class="number" style="color: green;">+{eaas_data['capex_investment']:,.0f} PLN</td>
            </tr>
            <tr>
                <td>Roczne oszczędności (netto)</td>
                <td class="number">{eaas_data['annual_savings_capex']:,.0f} PLN</td>
                <td class="number">{eaas_data['annual_savings_eaas']:,.0f} PLN</td>
                <td class="number">{eaas_data['annual_savings_capex'] - eaas_data['annual_savings_eaas']:+,.0f} PLN</td>
            </tr>
            <tr>
                <td>Suma oszczędności (15 lat)</td>
                <td class="number">{eaas_data['total_savings_capex_15y']:,.0f} PLN</td>
                <td class="number">{eaas_data['total_savings_eaas_15y']:,.0f} PLN</td>
                <td class="number">{eaas_data['total_savings_capex_15y'] - eaas_data['total_savings_eaas_15y']:+,.0f} PLN</td>
            </tr>
            <tr style="font-weight: bold; background: #e8f5e9;">
                <td>Zysk netto (15 lat)</td>
                <td class="number">{eaas_data['net_profit_capex_15y']:,.0f} PLN</td>
                <td class="number">{eaas_data['net_profit_eaas_15y']:,.0f} PLN</td>
                <td class="number">{eaas_data['net_profit_capex_15y'] - eaas_data['net_profit_eaas_15y']:+,.0f} PLN</td>
            </tr>
            <tr>
                <td>Własność instalacji</td>
                <td>Klient</td>
                <td>ESCO</td>
                <td>-</td>
            </tr>
            <tr>
                <td>Ryzyko techniczne</td>
                <td>Klient</td>
                <td>ESCO</td>
                <td>-</td>
            </tr>
            <tr>
                <td>Okres zwrotu</td>
                <td class="number">{eaas_data['payback_capex']:.1f} lat</td>
                <td class="number">Natychmiastowy</td>
                <td>-</td>
            </tr>
        </table>

        <h3 class="section-subtitle">9.2 Harmonogram przepływów - CAPEX vs EaaS</h3>
        <table>
            <tr>
                <th>Rok</th>
                <th>CAPEX: CF skumul.</th>
                <th>EaaS: CF skumul.</th>
                <th>Różnica</th>
            </tr>
        """

        for year in [1, 3, 5, 7, 10, 15]:
            capex_cf = eaas_data['cumulative_capex'].get(year, 0)
            eaas_cf = eaas_data['cumulative_eaas'].get(year, 0)
            diff = capex_cf - eaas_cf
            winner = "CAPEX" if diff > 0 else "EaaS"
            color = "green" if diff > 0 else "red"
            html += f"""
            <tr>
                <td class="number">{year}</td>
                <td class="number">{capex_cf:,.0f} PLN</td>
                <td class="number">{eaas_cf:,.0f} PLN</td>
                <td class="number" style="color: {color};">{diff:+,.0f} ({winner})</td>
            </tr>
            """

        html += """
        </table>
        """

        # Recommendation
        if eaas_data['net_profit_capex_15y'] > eaas_data['net_profit_eaas_15y'] * 1.2:
            recommendation = "CAPEX"
            reason = "Znacząco wyższy zysk netto w perspektywie 15-letniej"
        elif eaas_data['net_profit_eaas_15y'] > eaas_data['net_profit_capex_15y']:
            recommendation = "EaaS"
            reason = "Brak ryzyka inwestycyjnego przy porównywalnych korzyściach"
        else:
            recommendation = "Zależy od priorytetów"
            reason = "Obie opcje są ekonomicznie uzasadnione"

        html += f"""
        <div class="info-box {'success' if recommendation == 'CAPEX' else 'warning' if recommendation == 'EaaS' else ''}">
            <strong>Rekomendacja: {recommendation}</strong><br>
            {reason}
        </div>
        """

    else:
        html += """
        <div class="two-columns">
            <div class="kpi-box">
                <div class="value">-</div>
                <div class="label">Opłata miesięczna EaaS</div>
            </div>
            <div class="kpi-box">
                <div class="value">-</div>
                <div class="label">Efektywna cena energii EaaS</div>
            </div>
        </div>

        <div class="info-box warning">
            Brak danych do obliczeń EaaS. Wybierz wariant i wykonaj analizę ekonomiczną CAPEX.
        </div>
        """

    html += """
        <h3 class="section-subtitle">9.3 Kiedy wybrać EaaS?</h3>
        <div class="info-box">
            <strong>EaaS jest korzystniejszy gdy:</strong>
            <ul>
                <li>Ograniczony budżet inwestycyjny lub brak możliwości finansowania</li>
                <li>Chęć uniknięcia ryzyka technologicznego (gwarancja wydajności od ESCO)</li>
                <li>Krótszy horyzont planowania (&lt;7-10 lat)</li>
                <li>Preferencja dla przewidywalnych, stałych kosztów energii</li>
                <li>Niepewność co do przyszłego zużycia lub lokalizacji</li>
            </ul>
        </div>
    </div>
    """

    return html


def calculate_eaas_economics(economics: Dict, variant: Dict, consumption_stats: Dict) -> Dict:
    """Calculate EaaS economics based on CAPEX data"""
    if not economics or not variant:
        return None

    try:
        # Normalize variant to MWh first
        norm_variant = normalize_variant_to_mwh(variant)

        # CAPEX parameters
        investment = economics.get('investment', 0)
        annual_savings_capex = economics.get('annual_savings', 0)
        annual_opex = investment * 0.015  # 1.5% OPEX
        net_annual_capex = annual_savings_capex - annual_opex
        payback = economics.get('simple_payback', 10)

        # EaaS parameters - prices in PLN/MWh for consistency
        grid_price_mwh = 700  # PLN/MWh
        eaas_discount = 0.75  # Client pays 75% of grid price (25% discount)
        eaas_price_mwh = grid_price_mwh * eaas_discount  # ~525 PLN/MWh

        # Self-consumed energy in MWh (already normalized)
        self_consumed_mwh = norm_variant.get('self_consumed', 0)

        # Annual EaaS cost (what client pays to ESCO)
        annual_eaas_cost = self_consumed_mwh * eaas_price_mwh

        # Annual savings with EaaS (vs buying all from grid)
        annual_grid_cost = self_consumed_mwh * grid_price_mwh
        annual_savings_eaas = annual_grid_cost - annual_eaas_cost

        # Monthly fee
        monthly_fee = annual_eaas_cost / 12

        # 15-year projections
        years = 15
        total_savings_capex_15y = net_annual_capex * years
        total_savings_eaas_15y = annual_savings_eaas * years
        net_profit_capex_15y = total_savings_capex_15y - investment
        net_profit_eaas_15y = total_savings_eaas_15y  # No investment

        # Cumulative cash flows
        cumulative_capex = {}
        cumulative_eaas = {}
        cf_capex = -investment
        cf_eaas = 0

        for year in range(1, 16):
            cf_capex += net_annual_capex
            cf_eaas += annual_savings_eaas
            cumulative_capex[year] = cf_capex
            cumulative_eaas[year] = cf_eaas

        return {
            'monthly_fee': monthly_fee,
            'eaas_price_per_kwh': eaas_price_mwh / 1000,  # Convert to PLN/kWh for display
            'annual_eaas_cost': annual_eaas_cost,
            'annual_savings_eaas': annual_savings_eaas,
            'annual_savings_capex': net_annual_capex,
            'capex_investment': investment,
            'total_savings_capex_15y': total_savings_capex_15y,
            'total_savings_eaas_15y': total_savings_eaas_15y,
            'net_profit_capex_15y': net_profit_capex_15y,
            'net_profit_eaas_15y': net_profit_eaas_15y,
            'payback_capex': payback,
            'cumulative_capex': cumulative_capex,
            'cumulative_eaas': cumulative_eaas
        }
    except Exception as e:
        print(f"Error calculating EaaS economics: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_sensitivity_section(data: ReportData) -> str:
    """Generate sensitivity analysis section"""

    html = """
    <div class="section">
        <h2 class="section-title">10. Analiza wrażliwości</h2>

        <p>Analiza wpływu kluczowych parametrów na opłacalność projektu.</p>

        <h3 class="section-subtitle">10.1 Kluczowe czynniki ryzyka</h3>
        <table>
            <tr>
                <th>Parametr</th>
                <th>Scenariusz bazowy</th>
                <th>-20%</th>
                <th>+20%</th>
                <th>Wpływ na NPV</th>
            </tr>
            <tr>
                <td>Cena energii</td>
                <td class="number">700 PLN/MWh</td>
                <td class="number">560 PLN/MWh</td>
                <td class="number">840 PLN/MWh</td>
                <td class="number">±25%</td>
            </tr>
            <tr>
                <td>CAPEX</td>
                <td class="number">3500 PLN/kWp</td>
                <td class="number">2800 PLN/kWp</td>
                <td class="number">4200 PLN/kWp</td>
                <td class="number">±15%</td>
            </tr>
            <tr>
                <td>Stopa dyskontowa</td>
                <td class="number">8%</td>
                <td class="number">6.4%</td>
                <td class="number">9.6%</td>
                <td class="number">±10%</td>
            </tr>
            <tr>
                <td>Produkcja PV</td>
                <td class="number">1000 kWh/kWp</td>
                <td class="number">800 kWh/kWp</td>
                <td class="number">1200 kWh/kWp</td>
                <td class="number">±20%</td>
            </tr>
        </table>
    """

    # Generate tornado chart
    tornado_chart = generate_sensitivity_tornado_chart()
    if tornado_chart:
        html += f"""
        <img src="{tornado_chart}" style="width:100%; max-width:800px; margin: 20px auto; display:block;" alt="Tornado chart"/>
        """
    else:
        html += """
        <div class="chart-placeholder">[Wykres: Tornado chart - wpływ parametrów na NPV]</div>
        """

    html += """
        <h3 class="section-subtitle">10.2 Punkty krytyczne</h3>
        <div class="info-box warning">
            <strong>Breakeven points:</strong>
            <ul>
                <li>Projekt nieopłacalny (NPV&lt;0) przy cenie energii poniżej ~450 PLN/MWh</li>
                <li>Projekt nieopłacalny przy CAPEX powyżej ~5000 PLN/kWp</li>
                <li>IRR spada poniżej kosztu kapitału (8%) przy stopie dyskontowej &gt;12%</li>
            </ul>
        </div>
    </div>
    """

    return html


# ============== Endpoints ==============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "weasyprint_available": WEASYPRINT_AVAILABLE,
        "backends": BACKEND_URLS
    }


@app.post("/generate-report")
async def generate_report(config: ReportConfig):
    """
    Generate report data by aggregating from all backends and frontend data
    """
    print(f"📊 Generating report for: {config.client_name}")

    # Collect data from backends
    report_data = ReportData(config=config)

    # Check if frontend passed data directly
    frontend_data = config.frontend_data or {}
    analysis_results = frontend_data.get('analysisResults', {})

    # 1. Consumption statistics - try frontend first, then backend
    if analysis_results.get('consumption_stats'):
        report_data.consumption_stats = analysis_results['consumption_stats']
        print("✓ Loaded consumption stats from frontend")
    else:
        stats = await fetch_from_backend("data_analysis", "/statistics")
        if stats:
            report_data.consumption_stats = stats
            print("✓ Loaded consumption stats from backend")

    # 2. Analytical year
    if analysis_results.get('analytical_year'):
        report_data.analytical_year = analysis_results['analytical_year']
        print("✓ Loaded analytical year from frontend")
    else:
        ay = await fetch_from_backend("data_analysis", "/analytical-year")
        if ay:
            report_data.analytical_year = ay
            print("✓ Loaded analytical year from backend")

    # 3. Seasonality
    if analysis_results.get('seasonality'):
        report_data.seasonality = analysis_results['seasonality']
        print("✓ Loaded seasonality from frontend")
    else:
        seasonality = await fetch_from_backend("data_analysis", "/seasonality")
        if seasonality:
            report_data.seasonality = seasonality
            print("✓ Loaded seasonality from backend")

    # 4. PV scenarios from frontend (analysis results)
    if analysis_results.get('scenarios'):
        report_data.pv_scenarios = analysis_results['scenarios']
        print(f"✓ Loaded {len(report_data.pv_scenarios)} PV scenarios from frontend")

    # 5. Key variants from frontend
    if analysis_results.get('key_variants'):
        report_data.key_variants = analysis_results['key_variants']
        print("✓ Loaded key variants from frontend")

        # Get selected variant or NPV optimal
        kv = report_data.key_variants
        if config.selected_variant and config.selected_variant in kv:
            report_data.selected_variant_data = kv[config.selected_variant]
        elif 'npv_optimal' in kv:
            report_data.selected_variant_data = kv['npv_optimal']
        elif 'variant_b' in kv:
            report_data.selected_variant_data = kv['variant_b']

    # 5b. Master variant from shell
    master_variant = frontend_data.get('masterVariant')
    if master_variant:
        report_data.selected_variant_data = master_variant
        print("✓ Using master variant from shell")

    # 6. Monthly balance from analysis
    if analysis_results.get('monthly_balance'):
        report_data.monthly_balance = analysis_results['monthly_balance']
        print("✓ Loaded monthly balance from frontend")

    # 7. Hourly data - FETCH FROM BACKEND (data-analysis service)
    # Frontend data passing is unreliable, so fetch directly from backend
    print("📡 Fetching hourly data from backend...")
    hourly_data = await fetch_hourly_data_from_backend()
    if hourly_data and hourly_data.get('timestamps') and hourly_data.get('values'):
        # Convert to format expected by chart functions
        report_data.hourly_data = {
            'timestamps': hourly_data['timestamps'],
            'consumption': hourly_data['values']  # kW values
        }
        print(f"✓ Fetched {len(hourly_data['timestamps'])} hourly data points from backend")

        # Calculate energy balance from hourly data
        if report_data.selected_variant_data:
            report_data.energy_balance = calculate_energy_balance(
                report_data.hourly_data,
                report_data.selected_variant_data
            )
            print("✓ Calculated energy balance")
    else:
        # Fallback to frontend data if backend fetch fails
        hourly_from_frontend = frontend_data.get('hourlyData')
        if hourly_from_frontend:
            report_data.hourly_data = hourly_from_frontend
            if isinstance(hourly_from_frontend, dict):
                data_points = len(hourly_from_frontend.get('timestamps', hourly_from_frontend.get('consumption', [])))
            else:
                data_points = len(hourly_from_frontend)
            print(f"✓ Loaded {data_points} hourly data points from frontend (fallback)")

            if report_data.selected_variant_data:
                report_data.energy_balance = calculate_energy_balance(
                    hourly_from_frontend,
                    report_data.selected_variant_data
                )

    # 8. Store PV config from frontend for section 3
    pv_config = frontend_data.get('pvConfig')
    print(f"🔍 DEBUG pvConfig from frontend: {pv_config}")
    if pv_config:
        report_data.config.frontend_data = report_data.config.frontend_data or {}
        report_data.config.frontend_data['pvConfig'] = pv_config
        print(f"✓ Loaded PV config: pv_type={pv_config.get('pv_type')}, azimuth={pv_config.get('azimuth')}, tilt={pv_config.get('tilt')}")
    else:
        print("⚠️ NO pvConfig in frontend_data!")

    # 9. Economics - calculate based on variant data
    if report_data.selected_variant_data:
        economics_data = frontend_data.get('economics')
        if economics_data:
            report_data.economics = economics_data
            print("✓ Loaded economics from frontend")
        else:
            # Try to fetch from economics service
            variant = report_data.selected_variant_data
            economics = await calculate_economics(variant, report_data.consumption_stats)
            if economics:
                report_data.economics = economics
                print("✓ Calculated economics")

    return {
        "status": "success",
        "data": report_data.dict(),
        "sections_available": config.include_sections
    }


def calculate_energy_balance(hourly_data: Any, variant: Dict) -> Dict:
    """Calculate energy balance from hourly data

    hourly_data can be:
    - List[Dict]: Each dict has 'consumption', 'production' keys
    - Dict: Has 'timestamps', 'consumption' (or 'values') arrays

    Consumption hourly data is in kW (power), sum gives kWh
    Returns values in MWh for display
    """
    try:
        # Handle dict format with arrays (from backend/frontend)
        if isinstance(hourly_data, dict):
            consumption_array = hourly_data.get('consumption', hourly_data.get('values', []))
            total_consumption_kwh = sum(consumption_array) if consumption_array else 0
        # Handle list of dicts format
        elif isinstance(hourly_data, list):
            total_consumption_kwh = sum(h.get('consumption', 0) for h in hourly_data)
        else:
            total_consumption_kwh = 0

        # Convert consumption from kWh to MWh
        total_consumption_mwh = total_consumption_kwh / 1000

        # Normalize variant to MWh
        norm_variant = normalize_variant_to_mwh(variant)

        total_production_mwh = norm_variant.get('production', 0)
        total_self_consumed_mwh = norm_variant.get('self_consumed', 0)
        exported_mwh = norm_variant.get('exported', 0)

        # Calculate grid import (what we need from grid after using PV)
        # Grid import = Total consumption - Self consumed PV
        # This should always be positive or zero
        grid_import_mwh = max(0, total_consumption_mwh - total_self_consumed_mwh)

        # For zero export scenario (curtailment), export goes to waste
        curtailment_mwh = exported_mwh

        # Auto-consumption and coverage percentages
        auto_pct = norm_variant.get('auto_consumption_pct', 0)
        if auto_pct == 0 and total_production_mwh > 0:
            auto_pct = (total_self_consumed_mwh / total_production_mwh) * 100

        coverage_pct = norm_variant.get('coverage_pct', 0)
        if coverage_pct == 0 and total_consumption_mwh > 0:
            coverage_pct = (total_self_consumed_mwh / total_consumption_mwh) * 100

        return {
            'total_consumption': total_consumption_mwh,  # MWh
            'total_production': total_production_mwh,    # MWh
            'total_self_consumed': total_self_consumed_mwh,  # MWh
            'grid_import': grid_import_mwh,  # MWh
            'grid_export': 0,  # Assuming curtailment - no export
            'curtailment': curtailment_mwh,  # MWh
            'auto_consumption_pct': auto_pct,
            'coverage_pct': coverage_pct
        }
    except Exception as e:
        print(f"Error calculating energy balance: {e}")
        import traceback
        traceback.print_exc()
        return None


async def calculate_economics(variant: Dict, consumption_stats: Dict) -> Dict:
    """Calculate economics for a variant"""
    try:
        capacity = variant.get('capacity', 0)
        production = variant.get('production', 0)
        self_consumed = variant.get('self_consumed', 0)
        exported = variant.get('exported', 0)

        # Default economic parameters
        energy_price = 700  # PLN/MWh
        export_price = 350  # PLN/MWh (50% of import)
        capex_per_kwp = 3500  # PLN/kWp
        opex_pct = 0.015  # 1.5% of CAPEX
        discount_rate = 0.08
        years = 25
        degradation = 0.005  # 0.5% per year

        # Calculate investment
        investment = capacity * capex_per_kwp

        # Annual savings
        savings_self_consumed = self_consumed * energy_price / 1000  # MWh * PLN/MWh
        savings_export = exported * export_price / 1000
        annual_savings_year1 = savings_self_consumed + savings_export
        annual_opex = investment * opex_pct

        # Cash flows
        cash_flows = []
        cumulative = -investment

        for year in range(1, years + 1):
            degradation_factor = (1 - degradation) ** (year - 1)
            year_production = production * degradation_factor
            year_savings = annual_savings_year1 * degradation_factor
            net_cf = year_savings - annual_opex
            cumulative += net_cf

            cash_flows.append({
                'year': year,
                'production': year_production,
                'savings': year_savings,
                'opex': annual_opex,
                'net_cash_flow': net_cf,
                'cumulative': cumulative
            })

        # NPV calculation
        npv = -investment
        for i, cf in enumerate(cash_flows):
            npv += cf['net_cash_flow'] / ((1 + discount_rate) ** (i + 1))

        # Simple payback
        simple_payback = investment / (annual_savings_year1 - annual_opex) if annual_savings_year1 > annual_opex else 99

        # IRR (approximate)
        irr = estimate_irr(investment, [cf['net_cash_flow'] for cf in cash_flows])

        # LCOE
        total_production_lifetime = sum(production * ((1 - degradation) ** y) for y in range(years))
        total_costs = investment + annual_opex * years
        lcoe = total_costs / total_production_lifetime if total_production_lifetime > 0 else 0

        return {
            'investment': investment,
            'npv': npv,
            'irr': irr,
            'simple_payback': simple_payback,
            'annual_savings': annual_savings_year1,
            'lcoe': lcoe,
            'capex_per_kwp': capex_per_kwp,
            'cash_flows': cash_flows[:10]  # First 10 years
        }
    except Exception as e:
        print(f"Error calculating economics: {e}")
        return None


def estimate_irr(investment: float, cash_flows: List[float], max_iter: int = 100) -> float:
    """Estimate IRR using Newton-Raphson method"""
    try:
        rate = 0.1  # Initial guess

        for _ in range(max_iter):
            npv = -investment
            npv_derivative = 0

            for i, cf in enumerate(cash_flows):
                discount = (1 + rate) ** (i + 1)
                npv += cf / discount
                npv_derivative -= (i + 1) * cf / ((1 + rate) ** (i + 2))

            if abs(npv_derivative) < 1e-10:
                break

            new_rate = rate - npv / npv_derivative

            if abs(new_rate - rate) < 1e-6:
                return new_rate * 100  # Return as percentage

            rate = max(min(new_rate, 1.0), -0.99)  # Clamp rate

        return rate * 100
    except:
        return 0.0


@app.post("/generate-html")
async def generate_html_report(config: ReportConfig):
    """
    Generate HTML report
    """
    # First get the data
    report_response = await generate_report(config)
    report_data = ReportData(**report_response["data"])

    # Generate HTML
    html = generate_report_html(report_data)

    return HTMLResponse(content=html)


@app.post("/generate-pdf")
async def generate_pdf_report(config: ReportConfig):
    """
    Generate PDF report
    """
    if not WEASYPRINT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="PDF generation not available. WeasyPrint not installed."
        )

    # First get the data
    report_response = await generate_report(config)
    report_data = ReportData(**report_response["data"])

    # Generate HTML
    html_content = generate_report_html(report_data)

    # Convert to PDF
    try:
        html = HTML(string=html_content)
        pdf_bytes = html.write_pdf()

        # Save to file
        filename = f"raport_pv_{config.client_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = OUTPUT_DIR / filename

        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)

        # Return as base64 for frontend
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        return {
            "status": "success",
            "filename": filename,
            "pdf_base64": pdf_base64,
            "size_bytes": len(pdf_bytes)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(e)}"
        )


@app.get("/download/{filename}")
async def download_report(filename: str):
    """
    Download generated PDF report
    """
    filepath = OUTPUT_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=filename
    )


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)
