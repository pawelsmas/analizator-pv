"""
Energy Prices Service - pobieranie i analiza cen energii z ENTSO-E
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import os
import json
from pathlib import Path

# Próba importu entsoe-py
try:
    from entsoe import EntsoePandasClient
    ENTSOE_AVAILABLE = True
except ImportError:
    ENTSOE_AVAILABLE = False
    print("⚠️ entsoe-py not installed. Run: pip install entsoe-py")

app = FastAPI(title="Energy Prices Service", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Konfiguracja
ENTSOE_API_KEY = os.environ.get("ENTSOE_API_KEY", "")
CACHE_DIR = Path("/app/cache")
CACHE_DIR.mkdir(exist_ok=True)

# Polska strefa cenowa
POLAND_CODE = "PL"
TIMEZONE = "Europe/Warsaw"

# Kurs EUR/PLN - domyślny i cache
DEFAULT_EUR_PLN = 4.32  # Fallback kurs
_eur_pln_cache = {"rate": None, "timestamp": None}


def get_eur_pln_rate() -> float:
    """
    Pobierz aktualny kurs EUR/PLN z NBP API
    Cache na 1 godzinę
    """
    global _eur_pln_cache

    # Sprawdź cache (ważny 1 godzinę)
    if _eur_pln_cache["rate"] and _eur_pln_cache["timestamp"]:
        age = (datetime.now() - _eur_pln_cache["timestamp"]).total_seconds()
        if age < 3600:  # 1 godzina
            return _eur_pln_cache["rate"]

    try:
        import requests
        # NBP API - tabela A (średnie kursy walut)
        response = requests.get(
            "https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json",
            timeout=5
        )
        if response.ok:
            data = response.json()
            rate = data["rates"][0]["mid"]
            _eur_pln_cache["rate"] = rate
            _eur_pln_cache["timestamp"] = datetime.now()
            print(f"✓ Pobrano kurs EUR/PLN z NBP: {rate}")
            return rate
    except Exception as e:
        print(f"⚠️ Nie udało się pobrać kursu NBP: {e}")

    # Fallback do domyślnego kursu
    return DEFAULT_EUR_PLN


# ============== Models ==============

class PricePoint(BaseModel):
    timestamp: str
    price_eur_mwh: float
    price_pln_mwh: Optional[float] = None


class DailyStats(BaseModel):
    date: str
    min_price: float
    max_price: float
    avg_price: float
    median_price: float
    std_price: float
    peak_hour: int
    offpeak_avg: float
    peak_avg: float
    # Ceny w PLN
    min_price_pln: Optional[float] = None
    max_price_pln: Optional[float] = None
    avg_price_pln: Optional[float] = None
    offpeak_avg_pln: Optional[float] = None
    peak_avg_pln: Optional[float] = None


class MonthlyStats(BaseModel):
    month: str
    avg_price: float
    min_price: float
    max_price: float
    volatility: float
    total_hours: int


class YearlyStats(BaseModel):
    year: int
    avg_price: float
    min_price: float
    max_price: float
    median_price: float
    volatility: float
    baseload_avg: float
    peakload_avg: float


class PriceDataResponse(BaseModel):
    period: str
    start_date: str
    end_date: str
    currency: str
    timezone: str
    total_hours: int
    prices: List[PricePoint]
    daily_stats: List[DailyStats]
    summary: Dict[str, Any]


class HistoricalPricesResponse(BaseModel):
    years: List[int]
    yearly_stats: List[YearlyStats]
    monthly_stats: List[MonthlyStats]
    price_trend: List[Dict[str, Any]]


# ============== Helper Functions ==============

def get_cache_path(start: str, end: str) -> Path:
    """Generuj ścieżkę cache dla danego zakresu dat"""
    return CACHE_DIR / f"prices_{start}_{end}.json"


def load_from_cache(start: str, end: str) -> Optional[pd.Series]:
    """Załaduj dane z cache jeśli istnieją"""
    cache_path = get_cache_path(start, end)
    if cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                data = json.load(f)
            # Konwertuj z powrotem do Series
            series = pd.Series(data['prices'])
            series.index = pd.to_datetime(series.index)
            return series
        except Exception as e:
            print(f"Cache load error: {e}")
    return None


def save_to_cache(start: str, end: str, prices: pd.Series):
    """Zapisz dane do cache"""
    try:
        cache_path = get_cache_path(start, end)
        data = {
            'prices': {str(k): v for k, v in prices.items()},
            'cached_at': datetime.now().isoformat()
        }
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Cache save error: {e}")


def fetch_day_ahead_prices(start_date: str, end_date: str) -> pd.Series:
    """
    Pobierz ceny Day-Ahead z ENTSO-E dla Polski

    Args:
        start_date: Data początkowa (YYYY-MM-DD)
        end_date: Data końcowa (YYYY-MM-DD)

    Returns:
        pd.Series z cenami godzinowymi (EUR/MWh)
    """
    if not ENTSOE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="entsoe-py library not available"
        )

    if not ENTSOE_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ENTSOE_API_KEY not configured. Get your key from https://transparency.entsoe.eu/"
        )

    # Sprawdź cache
    cached = load_from_cache(start_date, end_date)
    if cached is not None:
        print(f"✓ Loaded from cache: {start_date} to {end_date}")
        return cached

    try:
        client = EntsoePandasClient(api_key=ENTSOE_API_KEY)

        start = pd.Timestamp(start_date, tz=TIMEZONE)
        end = pd.Timestamp(end_date, tz=TIMEZONE) + timedelta(days=1)

        print(f"📡 Fetching ENTSO-E prices: {start_date} to {end_date}")
        prices = client.query_day_ahead_prices(POLAND_CODE, start=start, end=end)

        # Zapisz do cache
        save_to_cache(start_date, end_date, prices)

        return prices

    except Exception as e:
        print(f"ENTSO-E API error: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch data from ENTSO-E: {str(e)}"
        )


def calculate_daily_stats(prices: pd.Series, eur_pln: float = None) -> List[DailyStats]:
    """Oblicz statystyki dzienne"""
    daily_stats = []

    # Grupuj po dniach
    prices_df = prices.to_frame('price')
    prices_df['date'] = prices_df.index.date
    prices_df['hour'] = prices_df.index.hour

    for date, group in prices_df.groupby('date'):
        # Peak hours: 8-20, Off-peak: 0-7, 21-23
        peak_mask = (group['hour'] >= 8) & (group['hour'] < 20)

        min_p = float(group['price'].min())
        max_p = float(group['price'].max())
        avg_p = float(group['price'].mean())
        offpeak = float(group.loc[~peak_mask, 'price'].mean()) if (~peak_mask).any() else 0
        peak = float(group.loc[peak_mask, 'price'].mean()) if peak_mask.any() else 0

        stats = DailyStats(
            date=str(date),
            min_price=min_p,
            max_price=max_p,
            avg_price=avg_p,
            median_price=float(group['price'].median()),
            std_price=float(group['price'].std()),
            peak_hour=int(group.loc[group['price'].idxmax(), 'hour']),
            offpeak_avg=offpeak,
            peak_avg=peak,
            # Ceny w PLN (jeśli podano kurs)
            min_price_pln=min_p * eur_pln if eur_pln else None,
            max_price_pln=max_p * eur_pln if eur_pln else None,
            avg_price_pln=avg_p * eur_pln if eur_pln else None,
            offpeak_avg_pln=offpeak * eur_pln if eur_pln else None,
            peak_avg_pln=peak * eur_pln if eur_pln else None
        )
        daily_stats.append(stats)

    return daily_stats


def calculate_monthly_stats(prices: pd.Series) -> List[MonthlyStats]:
    """Oblicz statystyki miesięczne"""
    monthly_stats = []

    prices_df = prices.to_frame('price')
    prices_df['month'] = prices_df.index.to_period('M')

    for month, group in prices_df.groupby('month'):
        stats = MonthlyStats(
            month=str(month),
            avg_price=float(group['price'].mean()),
            min_price=float(group['price'].min()),
            max_price=float(group['price'].max()),
            volatility=float(group['price'].std() / group['price'].mean() * 100),
            total_hours=len(group)
        )
        monthly_stats.append(stats)

    return monthly_stats


def calculate_yearly_stats(prices: pd.Series) -> List[YearlyStats]:
    """Oblicz statystyki roczne"""
    yearly_stats = []

    prices_df = prices.to_frame('price')
    prices_df['year'] = prices_df.index.year
    prices_df['hour'] = prices_df.index.hour

    for year, group in prices_df.groupby('year'):
        # Peak hours: 8-20 w dni robocze
        peak_mask = (group['hour'] >= 8) & (group['hour'] < 20)

        stats = YearlyStats(
            year=int(year),
            avg_price=float(group['price'].mean()),
            min_price=float(group['price'].min()),
            max_price=float(group['price'].max()),
            median_price=float(group['price'].median()),
            volatility=float(group['price'].std()),
            baseload_avg=float(group['price'].mean()),
            peakload_avg=float(group.loc[peak_mask, 'price'].mean()) if peak_mask.any() else 0
        )
        yearly_stats.append(stats)

    return yearly_stats


# ============== Demo Data (gdy brak API key) ==============

def generate_demo_prices(start_date: str, end_date: str) -> pd.Series:
    """
    Generuj realistyczne dane demo cen energii
    Oparte na typowych wzorcach rynku polskiego
    """
    start = pd.Timestamp(start_date, tz=TIMEZONE)
    end = pd.Timestamp(end_date, tz=TIMEZONE) + timedelta(days=1)

    # Generuj indeks godzinowy
    idx = pd.date_range(start=start, end=end, freq='h', tz=TIMEZONE)[:-1]

    # Bazowa cena (EUR/MWh) - typowa dla Polski 2023-2024
    base_price = 85.0

    prices = []
    for ts in idx:
        hour = ts.hour
        month = ts.month
        weekday = ts.weekday()

        # Sezonowość miesięczna (zima droższa)
        if month in [12, 1, 2]:
            seasonal = 1.25
        elif month in [6, 7, 8]:
            seasonal = 0.85
        else:
            seasonal = 1.0

        # Profil dobowy
        if 7 <= hour <= 9:  # Poranny szczyt
            hourly = 1.3
        elif 17 <= hour <= 20:  # Wieczorny szczyt
            hourly = 1.4
        elif 0 <= hour <= 5:  # Noc
            hourly = 0.7
        else:
            hourly = 1.0

        # Weekend tańszy
        if weekday >= 5:
            weekend = 0.85
        else:
            weekend = 1.0

        # Losowa zmienność
        noise = np.random.normal(0, 10)

        # Okazjonalne skoki cenowe (5% szans)
        if np.random.random() < 0.05:
            spike = np.random.uniform(1.5, 3.0)
        else:
            spike = 1.0

        price = base_price * seasonal * hourly * weekend * spike + noise
        price = max(0, price)  # Cena nie może być ujemna

        prices.append(price)

    return pd.Series(prices, index=idx)


def generate_historical_demo(years: List[int]) -> pd.Series:
    """Generuj dane historyczne dla wielu lat"""
    all_prices = []

    # Trend cenowy (wzrost w czasie)
    base_prices = {
        2020: 45,
        2021: 75,
        2022: 180,  # Kryzys energetyczny
        2023: 110,
        2024: 85,
    }

    for year in years:
        start = f"{year}-01-01"
        end = f"{year}-12-31"

        prices = generate_demo_prices(start, end)

        # Dostosuj do historycznego poziomu
        if year in base_prices:
            factor = base_prices[year] / 85.0
            prices = prices * factor

        all_prices.append(prices)

    return pd.concat(all_prices)


# ============== Endpoints ==============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "entsoe_available": ENTSOE_AVAILABLE,
        "api_key_configured": bool(ENTSOE_API_KEY),
        "demo_mode": not bool(ENTSOE_API_KEY)
    }


@app.get("/prices/current", response_model=PriceDataResponse)
async def get_current_prices(
    days: int = Query(default=7, ge=1, le=90, description="Liczba dni wstecz")
):
    """
    Pobierz aktualne ceny Day-Ahead dla ostatnich N dni
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Użyj danych demo jeśli brak API key
    if not ENTSOE_API_KEY:
        prices = generate_demo_prices(start_date, end_date)
        print("📊 Using demo data (no API key)")
    else:
        prices = fetch_day_ahead_prices(start_date, end_date)

    # Pobierz kurs EUR/PLN
    eur_pln = get_eur_pln_rate()

    # Oblicz statystyki
    daily_stats = calculate_daily_stats(prices, eur_pln)

    # Przygotuj response
    price_points = [
        PricePoint(
            timestamp=str(ts),
            price_eur_mwh=float(price),
            price_pln_mwh=float(price * eur_pln)
        )
        for ts, price in prices.items()
    ]

    summary = {
        "avg_price_eur": float(prices.mean()),
        "min_price_eur": float(prices.min()),
        "max_price_eur": float(prices.max()),
        "median_price_eur": float(prices.median()),
        "avg_price_pln": float(prices.mean() * eur_pln),
        "min_price_pln": float(prices.min() * eur_pln),
        "max_price_pln": float(prices.max() * eur_pln),
        "median_price_pln": float(prices.median() * eur_pln),
        "volatility_pct": float(prices.std() / prices.mean() * 100),
        "eur_pln_rate": eur_pln,
        "data_source": "demo" if not ENTSOE_API_KEY else "ENTSO-E"
    }

    return PriceDataResponse(
        period=f"Last {days} days",
        start_date=start_date,
        end_date=end_date,
        currency="EUR/MWh (PLN/MWh)",
        timezone=TIMEZONE,
        total_hours=len(prices),
        prices=price_points,
        daily_stats=daily_stats,
        summary=summary
    )


@app.get("/prices/range", response_model=PriceDataResponse)
async def get_prices_for_range(
    start_date: str = Query(..., description="Data początkowa (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Data końcowa (YYYY-MM-DD)")
):
    """
    Pobierz ceny Day-Ahead dla określonego zakresu dat
    """
    # Walidacja dat
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if end < start:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    if (end - start).days > 365:
        raise HTTPException(status_code=400, detail="Maximum range is 365 days")

    # Pobierz dane
    if not ENTSOE_API_KEY:
        prices = generate_demo_prices(start_date, end_date)
    else:
        prices = fetch_day_ahead_prices(start_date, end_date)

    # Pobierz kurs EUR/PLN
    eur_pln = get_eur_pln_rate()

    daily_stats = calculate_daily_stats(prices, eur_pln)

    price_points = [
        PricePoint(
            timestamp=str(ts),
            price_eur_mwh=float(price),
            price_pln_mwh=float(price * eur_pln)
        )
        for ts, price in prices.items()
    ]

    summary = {
        "avg_price_eur": float(prices.mean()),
        "min_price_eur": float(prices.min()),
        "max_price_eur": float(prices.max()),
        "median_price_eur": float(prices.median()),
        "avg_price_pln": float(prices.mean() * eur_pln),
        "min_price_pln": float(prices.min() * eur_pln),
        "max_price_pln": float(prices.max() * eur_pln),
        "median_price_pln": float(prices.median() * eur_pln),
        "volatility_pct": float(prices.std() / prices.mean() * 100),
        "eur_pln_rate": eur_pln,
        "data_source": "demo" if not ENTSOE_API_KEY else "ENTSO-E"
    }

    return PriceDataResponse(
        period=f"{start_date} to {end_date}",
        start_date=start_date,
        end_date=end_date,
        currency="EUR/MWh (PLN/MWh)",
        timezone=TIMEZONE,
        total_hours=len(prices),
        prices=price_points,
        daily_stats=daily_stats,
        summary=summary
    )


@app.get("/prices/historical", response_model=HistoricalPricesResponse)
async def get_historical_prices(
    years: str = Query(default="2022,2023,2024", description="Lata do analizy (comma-separated)")
):
    """
    Pobierz historyczne dane cenowe dla wybranych lat
    """
    try:
        year_list = [int(y.strip()) for y in years.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid years format")

    current_year = datetime.now().year
    year_list = [y for y in year_list if 2015 <= y <= current_year]

    if not year_list:
        raise HTTPException(status_code=400, detail="No valid years provided")

    # Generuj/pobierz dane dla każdego roku
    if not ENTSOE_API_KEY:
        all_prices = generate_historical_demo(year_list)
    else:
        # Pobierz dane dla każdego roku
        all_data = []
        for year in year_list:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            try:
                prices = fetch_day_ahead_prices(start, end)
                all_data.append(prices)
            except Exception as e:
                print(f"Failed to fetch {year}: {e}")

        if all_data:
            all_prices = pd.concat(all_data)
        else:
            all_prices = generate_historical_demo(year_list)

    # Oblicz statystyki
    yearly_stats = calculate_yearly_stats(all_prices)
    monthly_stats = calculate_monthly_stats(all_prices)

    # Trend cenowy (średnia miesięczna)
    prices_df = all_prices.to_frame('price')
    prices_df['month'] = prices_df.index.to_period('M')
    price_trend = [
        {"month": str(month), "avg_price": float(group['price'].mean())}
        for month, group in prices_df.groupby('month')
    ]

    return HistoricalPricesResponse(
        years=year_list,
        yearly_stats=yearly_stats,
        monthly_stats=monthly_stats,
        price_trend=price_trend
    )


@app.get("/prices/analysis-period")
async def get_analysis_period_prices(
    start_date: str = Query(..., description="Data początkowa okresu analitycznego"),
    end_date: str = Query(..., description="Data końcowa okresu analitycznego")
):
    """
    Pobierz ceny dla okresu analitycznego (dopasowane do danych zużycia)
    """
    if not ENTSOE_API_KEY:
        prices = generate_demo_prices(start_date, end_date)
    else:
        prices = fetch_day_ahead_prices(start_date, end_date)

    # Pobierz kurs EUR/PLN
    eur_pln = get_eur_pln_rate()

    # Statystyki godzinowe (profil dobowy)
    prices_df = prices.to_frame('price')
    prices_df['hour'] = prices_df.index.hour

    hourly_profile = []
    for hour in range(24):
        hour_prices = prices_df[prices_df['hour'] == hour]['price']
        avg_p = float(hour_prices.mean())
        min_p = float(hour_prices.min())
        max_p = float(hour_prices.max())
        hourly_profile.append({
            "hour": hour,
            "avg_price_eur": avg_p,
            "min_price_eur": min_p,
            "max_price_eur": max_p,
            "avg_price_pln": avg_p * eur_pln,
            "min_price_pln": min_p * eur_pln,
            "max_price_pln": max_p * eur_pln
        })

    # Statystyki miesięczne
    monthly_stats = calculate_monthly_stats(prices)

    # Korelacja z typowym profilem PV
    # (wysoka produkcja PV w godz. 10-16, sprawdzamy czy ceny są niższe)
    pv_hours = prices_df[(prices_df['hour'] >= 10) & (prices_df['hour'] <= 16)]['price'].mean()
    non_pv_hours = prices_df[(prices_df['hour'] < 10) | (prices_df['hour'] > 16)]['price'].mean()

    return {
        "period": f"{start_date} to {end_date}",
        "total_hours": len(prices),
        "eur_pln_rate": eur_pln,
        "summary": {
            "avg_price_eur": float(prices.mean()),
            "min_price_eur": float(prices.min()),
            "max_price_eur": float(prices.max()),
            "avg_price_pln": float(prices.mean() * eur_pln),
            "min_price_pln": float(prices.min() * eur_pln),
            "max_price_pln": float(prices.max() * eur_pln),
            "volatility_pct": float(prices.std() / prices.mean() * 100)
        },
        "hourly_profile": hourly_profile,
        "monthly_stats": [s.dict() for s in monthly_stats],
        "pv_correlation": {
            "pv_hours_avg_eur": float(pv_hours),
            "non_pv_hours_avg_eur": float(non_pv_hours),
            "pv_hours_avg_pln": float(pv_hours * eur_pln),
            "non_pv_hours_avg_pln": float(non_pv_hours * eur_pln),
            "pv_discount_pct": float((non_pv_hours - pv_hours) / non_pv_hours * 100) if non_pv_hours > 0 else 0,
            "insight": "Ceny w godzinach PV są niższe" if pv_hours < non_pv_hours else "Ceny w godzinach PV są wyższe"
        },
        "data_source": "demo" if not ENTSOE_API_KEY else "ENTSO-E"
    }


@app.get("/prices/spot-vs-fixed")
async def compare_spot_vs_fixed(
    start_date: str = Query(...),
    end_date: str = Query(...),
    fixed_price_eur: float = Query(default=100.0, description="Stała cena energii (EUR/MWh)")
):
    """
    Porównaj cenę SPOT z ceną stałą dla danego okresu
    """
    if not ENTSOE_API_KEY:
        prices = generate_demo_prices(start_date, end_date)
    else:
        prices = fetch_day_ahead_prices(start_date, end_date)

    # Pobierz kurs EUR/PLN
    eur_pln = get_eur_pln_rate()

    avg_spot = prices.mean()
    fixed_price_pln = fixed_price_eur * eur_pln

    # Ile zaoszczędziłbyś/straciłbyś na SPOT vs fixed
    savings_pct = (fixed_price_eur - avg_spot) / fixed_price_eur * 100

    # Analiza ryzyka - ile godzin cena SPOT > fixed
    hours_above_fixed = (prices > fixed_price_eur).sum()
    hours_below_fixed = (prices <= fixed_price_eur).sum()

    return {
        "period": f"{start_date} to {end_date}",
        "eur_pln_rate": eur_pln,
        "fixed_price_eur": fixed_price_eur,
        "fixed_price_pln": fixed_price_pln,
        "spot_avg_eur": float(avg_spot),
        "spot_avg_pln": float(avg_spot * eur_pln),
        "spot_min_eur": float(prices.min()),
        "spot_min_pln": float(prices.min() * eur_pln),
        "spot_max_eur": float(prices.max()),
        "spot_max_pln": float(prices.max() * eur_pln),
        "savings_on_spot_pct": float(savings_pct),
        "recommendation": "SPOT korzystniejszy" if avg_spot < fixed_price_eur else "Cena stała korzystniejsza",
        "risk_analysis": {
            "hours_spot_above_fixed": int(hours_above_fixed),
            "hours_spot_below_fixed": int(hours_below_fixed),
            "pct_time_spot_cheaper": float(hours_below_fixed / len(prices) * 100),
            "max_spike_above_fixed_eur": float(prices.max() - fixed_price_eur),
            "max_spike_above_fixed_pln": float((prices.max() - fixed_price_eur) * eur_pln)
        },
        "data_source": "demo" if not ENTSOE_API_KEY else "ENTSO-E"
    }


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
