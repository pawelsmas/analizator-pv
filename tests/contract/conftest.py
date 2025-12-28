"""
Pytest configuration for contract tests.
These tests verify API contracts between services, not exact numerical values.
"""
import pytest
import requests
import time
import os

# Service URLs - configurable via environment
BESS_DISPATCH_URL = os.getenv("BESS_DISPATCH_URL", "http://localhost:8031")
PV_CALCULATION_URL = os.getenv("PV_CALCULATION_URL", "http://localhost:8002")
DATA_ANALYSIS_URL = os.getenv("DATA_ANALYSIS_URL", "http://localhost:8001")

# Timeout for service readiness
SERVICE_TIMEOUT = int(os.getenv("SERVICE_TIMEOUT", "60"))


@pytest.fixture(scope="session")
def bess_dispatch_url():
    """Return BESS dispatch service URL."""
    return BESS_DISPATCH_URL


@pytest.fixture(scope="session")
def pv_calculation_url():
    """Return PV calculation service URL."""
    return PV_CALCULATION_URL


@pytest.fixture(scope="session")
def data_analysis_url():
    """Return data analysis service URL."""
    return DATA_ANALYSIS_URL


@pytest.fixture(scope="session")
def wait_for_services(bess_dispatch_url, pv_calculation_url):
    """Wait for all services to be ready before running tests."""
    services = [
        (bess_dispatch_url, "/health"),
        (pv_calculation_url, "/health"),
    ]

    start_time = time.time()
    for base_url, health_path in services:
        url = f"{base_url}{health_path}"
        while True:
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass

            if time.time() - start_time > SERVICE_TIMEOUT:
                pytest.fail(f"Service {base_url} not ready after {SERVICE_TIMEOUT}s")

            time.sleep(2)

    return True


@pytest.fixture
def sample_consumption_hourly():
    """Generate sample hourly consumption data (24 hours)."""
    # Industrial profile: low at night, peak during day
    base_profile = [
        250, 230, 220, 210, 220, 280,  # 00:00-05:00
        450, 580, 650, 720, 780, 800,  # 06:00-11:00
        750, 720, 700, 680, 620, 550,  # 12:00-17:00
        480, 420, 380, 340, 300, 270,  # 18:00-23:00
    ]
    return base_profile


@pytest.fixture
def sample_consumption_annual(sample_consumption_hourly):
    """Generate sample annual consumption data (8760 hours)."""
    # Repeat daily pattern for full year
    annual_data = []
    for day in range(365):
        # Add some seasonal variation
        seasonal_factor = 1.0 + 0.1 * (abs(day - 182) / 182)  # Higher in winter
        for hour_val in sample_consumption_hourly:
            annual_data.append(hour_val * seasonal_factor)
    return annual_data


@pytest.fixture
def sample_pv_generation_annual():
    """Generate sample annual PV generation data (8760 hours)."""
    import math

    generation = []
    for day in range(365):
        # Day of year affects sun hours
        day_length_factor = 0.5 + 0.5 * math.sin(2 * math.pi * (day - 80) / 365)

        for hour in range(24):
            if 6 <= hour <= 20:  # Daylight hours
                # Bell curve centered at noon
                hour_factor = math.exp(-((hour - 13) ** 2) / 18)
                # Peak generation ~800 kW for 1000 kWp system
                generation.append(800 * hour_factor * day_length_factor)
            else:
                generation.append(0)

    return generation


@pytest.fixture
def minimal_sizing_request(sample_consumption_annual, sample_pv_generation_annual):
    """Create minimal valid sizing request for contract tests."""
    load = sample_consumption_annual[:168]  # 1 week
    peak_load = max(load) if load else 800.0

    return {
        "load_kw": load,
        "pv_generation_kw": sample_pv_generation_annual[:168],
        "mode": "stacked",  # DispatchMode: pv_surplus, peak_shaving, stacked, arbitrage, load_only
        "durations_h": [1.0, 2.0, 4.0],
        "interval_minutes": 60,
        # Required for stacked mode
        "peak_limit_kw": peak_load * 0.7,  # Target 30% peak reduction
        # Economic params
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "capex_pln_per_kw": 0.0,
        # Pricing
        "tariff_type": "two_zone",
        "day_rate_pln_mwh": 510.0,
        "night_rate_pln_mwh": 310.0,
        "other_fees_pln_mwh": 451.0,
    }
