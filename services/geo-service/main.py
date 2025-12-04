"""
Geo Service - Geocoding and Elevation API
Resolves city/postal code to lat/lon coordinates and elevation.
Uses OpenStreetMap Nominatim for geocoding and Open-Elevation API for altitude.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import httpx
import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib

app = FastAPI(
    title="PV Optimizer Geo Service",
    description="Geocoding and elevation resolution for PV installations",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# CACHE
# ============================================

# In-memory cache with TTL (Time To Live)
# TODO: Replace with Redis for production
class GeoCache:
    def __init__(self, ttl_hours: int = 24 * 7):  # 7 days default
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = timedelta(hours=ttl_hours)

    def _make_key(self, country: str, postal_code: str, city: str) -> str:
        """Create cache key from location components."""
        raw = f"{country.upper()}:{postal_code}:{city.lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, country: str, postal_code: str, city: str) -> Optional[Dict]:
        """Get cached result if valid."""
        key = self._make_key(country, postal_code, city)
        if key in self._cache:
            entry = self._cache[key]
            if datetime.now() < entry['expires']:
                return entry['data']
            else:
                del self._cache[key]
        return None

    def set(self, country: str, postal_code: str, city: str, data: Dict):
        """Cache result with TTL."""
        key = self._make_key(country, postal_code, city)
        self._cache[key] = {
            'data': data,
            'expires': datetime.now() + self._ttl,
            'created': datetime.now().isoformat()
        }

    def stats(self) -> Dict:
        """Return cache statistics."""
        now = datetime.now()
        valid = sum(1 for e in self._cache.values() if now < e['expires'])
        return {
            'total_entries': len(self._cache),
            'valid_entries': valid,
            'expired_entries': len(self._cache) - valid
        }

    def clear(self):
        """Clear all cache entries."""
        self._cache.clear()

geo_cache = GeoCache()

# ============================================
# MODELS
# ============================================

class GeoLocation(BaseModel):
    """Resolved geographic location."""
    latitude: float = Field(..., description="Latitude in decimal degrees")
    longitude: float = Field(..., description="Longitude in decimal degrees")
    elevation: Optional[float] = Field(None, description="Elevation in meters above sea level")
    display_name: str = Field(..., description="Full display name from geocoder")
    country: str = Field(..., description="Country code")
    postal_code: Optional[str] = Field(None, description="Postal code")
    city: Optional[str] = Field(None, description="City name")
    source: str = Field(default="nominatim", description="Geocoding source")
    cached: bool = Field(default=False, description="Whether result was from cache")

class GeoResolveRequest(BaseModel):
    """Request to resolve location."""
    country: str = Field(default="PL", description="ISO country code")
    postal_code: Optional[str] = Field(None, description="Postal code")
    city: Optional[str] = Field(None, description="City name")

# ============================================
# GEOCODING FUNCTIONS
# ============================================

def format_polish_postal_code(postal_code: str) -> str:
    """Format Polish postal code to XX-XXX format for better Nominatim results."""
    if not postal_code:
        return postal_code
    # Remove all non-digit characters
    digits = ''.join(c for c in postal_code if c.isdigit())
    # If we have exactly 5 digits, format as XX-XXX
    if len(digits) == 5:
        return f"{digits[:2]}-{digits[2:]}"
    return postal_code


async def geocode_nominatim(country: str, postal_code: str = None, city: str = None) -> Optional[Dict]:
    """
    Geocode using OpenStreetMap Nominatim API.
    Free, no API key required, but rate limited (1 req/sec).
    Uses structured query parameters for better accuracy.
    """
    # Format Polish postal codes for better results
    if country.upper() == "PL" and postal_code:
        postal_code = format_polish_postal_code(postal_code)

    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "PV-Optimizer/1.0 (contact@example.com)"  # Required by Nominatim ToS
    }

    # Use structured query parameters for better accuracy
    params = {
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
        "country": country
    }

    if postal_code:
        params["postalcode"] = postal_code
    if city:
        params["city"] = city

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            response.raise_for_status()
            results = response.json()

            if results and len(results) > 0:
                result = results[0]
                return {
                    "latitude": float(result["lat"]),
                    "longitude": float(result["lon"]),
                    "display_name": result.get("display_name", ""),
                    "address": result.get("address", {})
                }

            # Fallback: try free-form query if structured didn't work
            query_parts = []
            if postal_code:
                query_parts.append(postal_code)
            if city:
                query_parts.append(city)
            query_parts.append(country)

            params_fallback = {
                "q": ", ".join(query_parts),
                "format": "json",
                "limit": 1,
                "addressdetails": 1
            }

            response = await client.get(url, params=params_fallback, headers=headers, timeout=10.0)
            response.raise_for_status()
            results = response.json()

            if results and len(results) > 0:
                result = results[0]
                return {
                    "latitude": float(result["lat"]),
                    "longitude": float(result["lon"]),
                    "display_name": result.get("display_name", ""),
                    "address": result.get("address", {})
                }
        except Exception as e:
            print(f"Nominatim geocoding error: {e}")

    return None

async def get_elevation(lat: float, lon: float) -> Optional[float]:
    """
    Get elevation using Open-Elevation API.
    Free, no API key required.
    """
    url = "https://api.open-elevation.com/api/v1/lookup"
    params = {"locations": f"{lat},{lon}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            if data.get("results") and len(data["results"]) > 0:
                return data["results"][0].get("elevation")
        except Exception as e:
            print(f"Elevation API error: {e}")

    return None

async def resolve_location(country: str, postal_code: str = None, city: str = None) -> Optional[GeoLocation]:
    """
    Resolve location to coordinates and elevation.
    Uses cache if available.
    """
    # Check cache first
    cached = geo_cache.get(country, postal_code or "", city or "")
    if cached:
        return GeoLocation(**cached, cached=True)

    # Geocode
    geo_result = await geocode_nominatim(country, postal_code, city)
    if not geo_result:
        return None

    lat = geo_result["latitude"]
    lon = geo_result["longitude"]

    # Get elevation (separate call)
    elevation = await get_elevation(lat, lon)

    # Build result
    result = {
        "latitude": lat,
        "longitude": lon,
        "elevation": elevation,
        "display_name": geo_result["display_name"],
        "country": country,
        "postal_code": postal_code,
        "city": city,
        "source": "nominatim"
    }

    # Cache result
    geo_cache.set(country, postal_code or "", city or "", result)

    return GeoLocation(**result, cached=False)

# ============================================
# POLISH CITY DATABASE (Preloaded)
# ============================================

# Polish postal code prefixes to approximate locations
# Format: first 2 digits -> region center coordinates
POLISH_POSTAL_REGIONS = {
    "00": {"lat": 52.23, "lon": 21.01, "city": "Warszawa", "elev": 100},
    "01": {"lat": 52.23, "lon": 21.01, "city": "Warszawa", "elev": 100},
    "02": {"lat": 52.19, "lon": 21.00, "city": "Warszawa", "elev": 100},
    "03": {"lat": 52.27, "lon": 21.04, "city": "Warszawa", "elev": 100},
    "04": {"lat": 52.21, "lon": 21.09, "city": "Warszawa", "elev": 100},
    "05": {"lat": 52.20, "lon": 20.85, "city": "Pruszków", "elev": 95},
    "06": {"lat": 52.82, "lon": 20.15, "city": "Płock", "elev": 60},
    "07": {"lat": 52.66, "lon": 21.55, "city": "Wyszków", "elev": 95},
    "08": {"lat": 52.17, "lon": 22.29, "city": "Siedlce", "elev": 150},
    "09": {"lat": 52.41, "lon": 20.31, "city": "Sochaczew", "elev": 70},
    "10": {"lat": 53.78, "lon": 20.48, "city": "Olsztyn", "elev": 130},
    "11": {"lat": 53.85, "lon": 20.02, "city": "Ostróda", "elev": 100},
    "12": {"lat": 53.25, "lon": 20.49, "city": "Szczytno", "elev": 140},
    "13": {"lat": 53.48, "lon": 19.70, "city": "Iława", "elev": 110},
    "14": {"lat": 54.02, "lon": 21.75, "city": "Ełk", "elev": 130},
    "15": {"lat": 53.13, "lon": 23.16, "city": "Białystok", "elev": 150},
    "16": {"lat": 53.44, "lon": 23.87, "city": "Augustów", "elev": 120},
    "17": {"lat": 52.72, "lon": 23.18, "city": "Bielsk Podlaski", "elev": 145},
    "18": {"lat": 53.74, "lon": 22.36, "city": "Grajewo", "elev": 125},
    "19": {"lat": 52.84, "lon": 22.32, "city": "Zambrów", "elev": 140},
    "20": {"lat": 51.25, "lon": 22.57, "city": "Lublin", "elev": 200},
    "21": {"lat": 51.22, "lon": 22.97, "city": "Świdnik", "elev": 190},
    "22": {"lat": 50.87, "lon": 23.86, "city": "Zamość", "elev": 220},
    "23": {"lat": 50.82, "lon": 22.77, "city": "Biłgoraj", "elev": 210},
    "24": {"lat": 51.52, "lon": 21.96, "city": "Puławy", "elev": 120},
    "25": {"lat": 50.87, "lon": 20.63, "city": "Kielce", "elev": 260},
    "26": {"lat": 51.39, "lon": 20.65, "city": "Radom", "elev": 180},
    "27": {"lat": 50.90, "lon": 21.40, "city": "Starachowice", "elev": 240},
    "28": {"lat": 50.56, "lon": 20.44, "city": "Jędrzejów", "elev": 275},
    "29": {"lat": 51.21, "lon": 21.45, "city": "Skarżysko-Kam.", "elev": 250},
    "30": {"lat": 50.06, "lon": 19.94, "city": "Kraków", "elev": 220},
    "31": {"lat": 50.08, "lon": 19.90, "city": "Kraków", "elev": 220},
    "32": {"lat": 50.05, "lon": 19.88, "city": "Kraków", "elev": 220},
    "33": {"lat": 49.88, "lon": 19.49, "city": "Myślenice", "elev": 310},
    "34": {"lat": 49.99, "lon": 20.42, "city": "Bochnia", "elev": 210},
    "35": {"lat": 50.04, "lon": 21.99, "city": "Rzeszów", "elev": 220},
    "36": {"lat": 50.26, "lon": 22.72, "city": "Stalowa Wola", "elev": 165},
    "37": {"lat": 49.78, "lon": 22.76, "city": "Przemyśl", "elev": 250},
    "38": {"lat": 49.49, "lon": 20.68, "city": "Nowy Sącz", "elev": 290},
    "39": {"lat": 50.30, "lon": 22.16, "city": "Tarnobrzeg", "elev": 150},
    "40": {"lat": 50.26, "lon": 19.02, "city": "Katowice", "elev": 280},
    "41": {"lat": 50.30, "lon": 18.93, "city": "Zabrze", "elev": 265},
    "42": {"lat": 50.21, "lon": 19.08, "city": "Tychy", "elev": 245},
    "43": {"lat": 49.94, "lon": 19.21, "city": "Bielsko-Biała", "elev": 330},
    "44": {"lat": 50.30, "lon": 18.67, "city": "Gliwice", "elev": 230},
    "45": {"lat": 50.67, "lon": 17.92, "city": "Opole", "elev": 155},
    "46": {"lat": 50.27, "lon": 17.38, "city": "Nysa", "elev": 195},
    "47": {"lat": 50.64, "lon": 18.28, "city": "Strzelce Opolskie", "elev": 200},
    "48": {"lat": 50.01, "lon": 17.87, "city": "Racibórz", "elev": 200},
    "49": {"lat": 50.46, "lon": 18.16, "city": "Tarnowskie Góry", "elev": 295},
    "50": {"lat": 51.11, "lon": 17.04, "city": "Wrocław", "elev": 120},
    "51": {"lat": 51.08, "lon": 17.08, "city": "Wrocław", "elev": 120},
    "52": {"lat": 51.12, "lon": 16.98, "city": "Wrocław", "elev": 115},
    "53": {"lat": 51.14, "lon": 17.02, "city": "Wrocław", "elev": 115},
    "54": {"lat": 51.15, "lon": 16.93, "city": "Wrocław", "elev": 115},
    "55": {"lat": 51.29, "lon": 16.90, "city": "Oborniki Śląskie", "elev": 135},
    "56": {"lat": 51.45, "lon": 16.28, "city": "Głogów", "elev": 80},
    "57": {"lat": 50.78, "lon": 16.28, "city": "Kłodzko", "elev": 320},
    "58": {"lat": 50.90, "lon": 15.72, "city": "Jelenia Góra", "elev": 350},
    "59": {"lat": 51.10, "lon": 16.15, "city": "Legnica", "elev": 115},
    "60": {"lat": 52.41, "lon": 16.93, "city": "Poznań", "elev": 60},
    "61": {"lat": 52.40, "lon": 16.87, "city": "Poznań", "elev": 65},
    "62": {"lat": 52.17, "lon": 17.08, "city": "Swarzędz", "elev": 75},
    "63": {"lat": 51.73, "lon": 17.47, "city": "Kalisz", "elev": 105},
    "64": {"lat": 52.01, "lon": 16.07, "city": "Leszno", "elev": 90},
    "65": {"lat": 51.94, "lon": 15.51, "city": "Zielona Góra", "elev": 80},
    "66": {"lat": 52.31, "lon": 14.55, "city": "Słubice", "elev": 20},
    "67": {"lat": 51.72, "lon": 14.99, "city": "Żary", "elev": 110},
    "68": {"lat": 52.11, "lon": 14.84, "city": "Świebodzin", "elev": 55},
    "69": {"lat": 51.60, "lon": 15.78, "city": "Żagań", "elev": 105},
    "70": {"lat": 53.43, "lon": 14.55, "city": "Szczecin", "elev": 25},
    "71": {"lat": 53.45, "lon": 14.55, "city": "Szczecin", "elev": 25},
    "72": {"lat": 53.90, "lon": 14.76, "city": "Świnoujście", "elev": 5},
    "73": {"lat": 53.17, "lon": 14.60, "city": "Gryfino", "elev": 20},
    "74": {"lat": 53.69, "lon": 15.79, "city": "Drawsko Pomorskie", "elev": 90},
    "75": {"lat": 54.17, "lon": 16.05, "city": "Koszalin", "elev": 30},
    "76": {"lat": 54.46, "lon": 17.03, "city": "Słupsk", "elev": 25},
    "77": {"lat": 53.77, "lon": 17.05, "city": "Szczecinek", "elev": 135},
    "78": {"lat": 53.98, "lon": 15.42, "city": "Kołobrzeg", "elev": 5},
    "79": {"lat": 53.57, "lon": 16.82, "city": "Wałcz", "elev": 110},
    "80": {"lat": 54.35, "lon": 18.65, "city": "Gdańsk", "elev": 10},
    "81": {"lat": 54.52, "lon": 18.53, "city": "Gdynia", "elev": 15},
    "82": {"lat": 54.09, "lon": 19.04, "city": "Malbork", "elev": 10},
    "83": {"lat": 54.22, "lon": 18.20, "city": "Tczew", "elev": 15},
    "84": {"lat": 54.61, "lon": 18.22, "city": "Wejherowo", "elev": 30},
    "85": {"lat": 53.12, "lon": 18.00, "city": "Bydgoszcz", "elev": 60},
    "86": {"lat": 53.42, "lon": 18.57, "city": "Grudziądz", "elev": 35},
    "87": {"lat": 53.01, "lon": 18.60, "city": "Toruń", "elev": 65},
    "88": {"lat": 52.92, "lon": 17.58, "city": "Inowrocław", "elev": 90},
    "89": {"lat": 53.75, "lon": 17.93, "city": "Chojnice", "elev": 160},
    "90": {"lat": 51.76, "lon": 19.46, "city": "Łódź", "elev": 200},
    "91": {"lat": 51.74, "lon": 19.48, "city": "Łódź", "elev": 200},
    "92": {"lat": 51.78, "lon": 19.52, "city": "Łódź", "elev": 200},
    "93": {"lat": 51.72, "lon": 19.41, "city": "Łódź", "elev": 195},
    "94": {"lat": 51.80, "lon": 19.38, "city": "Łódź", "elev": 195},
    "95": {"lat": 51.91, "lon": 19.82, "city": "Skierniewice", "elev": 125},
    "96": {"lat": 51.93, "lon": 19.00, "city": "Sieradz", "elev": 150},
    "97": {"lat": 51.46, "lon": 19.64, "city": "Piotrków Tryb.", "elev": 195},
    "98": {"lat": 51.59, "lon": 18.93, "city": "Wieluń", "elev": 200},
    "99": {"lat": 51.66, "lon": 20.48, "city": "Tomaszów Maz.", "elev": 185},
}

def lookup_polish_postal_code(postal_code: str) -> Optional[Dict]:
    """
    Lookup Polish postal code to get approximate coordinates.
    Uses first 2 digits to determine region.
    """
    if not postal_code:
        return None
    # Get first 2 digits
    digits = ''.join(c for c in postal_code if c.isdigit())
    if len(digits) < 2:
        return None
    prefix = digits[:2]
    if prefix in POLISH_POSTAL_REGIONS:
        data = POLISH_POSTAL_REGIONS[prefix]
        return {
            "latitude": data["lat"],
            "longitude": data["lon"],
            "elevation": data["elev"],
            "city": data["city"]
        }
    return None


# Major Polish cities with coordinates and elevations
# Used as fallback when Nominatim is slow/unavailable
POLISH_CITIES = {
    "warszawa": {"lat": 52.2297, "lon": 21.0122, "elev": 100},
    "krakow": {"lat": 50.0647, "lon": 19.9450, "elev": 219},
    "kraków": {"lat": 50.0647, "lon": 19.9450, "elev": 219},
    "lodz": {"lat": 51.7592, "lon": 19.4560, "elev": 200},
    "łódź": {"lat": 51.7592, "lon": 19.4560, "elev": 200},
    "wroclaw": {"lat": 51.1079, "lon": 17.0385, "elev": 120},
    "wrocław": {"lat": 51.1079, "lon": 17.0385, "elev": 120},
    "poznan": {"lat": 52.4064, "lon": 16.9252, "elev": 60},
    "poznań": {"lat": 52.4064, "lon": 16.9252, "elev": 60},
    "gdansk": {"lat": 54.3520, "lon": 18.6466, "elev": 10},
    "gdańsk": {"lat": 54.3520, "lon": 18.6466, "elev": 10},
    "szczecin": {"lat": 53.4285, "lon": 14.5528, "elev": 25},
    "bydgoszcz": {"lat": 53.1235, "lon": 18.0084, "elev": 60},
    "lublin": {"lat": 51.2465, "lon": 22.5684, "elev": 200},
    "bialystok": {"lat": 53.1325, "lon": 23.1688, "elev": 150},
    "białystok": {"lat": 53.1325, "lon": 23.1688, "elev": 150},
    "katowice": {"lat": 50.2649, "lon": 19.0238, "elev": 280},
    "czestochowa": {"lat": 50.8118, "lon": 19.1203, "elev": 260},
    "częstochowa": {"lat": 50.8118, "lon": 19.1203, "elev": 260},
    "radom": {"lat": 51.4027, "lon": 21.1471, "elev": 180},
    "torun": {"lat": 53.0138, "lon": 18.5984, "elev": 65},
    "toruń": {"lat": 53.0138, "lon": 18.5984, "elev": 65},
    "kielce": {"lat": 50.8661, "lon": 20.6286, "elev": 260},
    "rzeszow": {"lat": 50.0412, "lon": 21.9991, "elev": 220},
    "rzeszów": {"lat": 50.0412, "lon": 21.9991, "elev": 220},
    "olsztyn": {"lat": 53.7784, "lon": 20.4801, "elev": 130},
    "opole": {"lat": 50.6751, "lon": 17.9213, "elev": 155},
    "gorzow": {"lat": 52.7368, "lon": 15.2288, "elev": 40},
    "gorzów": {"lat": 52.7368, "lon": 15.2288, "elev": 40},
    "zielona gora": {"lat": 51.9356, "lon": 15.5062, "elev": 80},
    "zielona góra": {"lat": 51.9356, "lon": 15.5062, "elev": 80},
}

def lookup_polish_city(city: str) -> Optional[Dict]:
    """Quick lookup for Polish cities."""
    if not city:
        return None
    city_lower = city.lower().strip()
    if city_lower in POLISH_CITIES:
        data = POLISH_CITIES[city_lower]
        return {
            "latitude": data["lat"],
            "longitude": data["lon"],
            "elevation": data["elev"]
        }
    return None

# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
async def root():
    return {
        "service": "PV Optimizer Geo Service",
        "version": "1.0.0",
        "endpoints": ["/geo/resolve", "/geo/elevation", "/geo/cache/stats"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "geo-service",
        "cache": geo_cache.stats()
    }

@app.get("/geo/resolve", response_model=GeoLocation)
async def resolve_geo(
    country: str = Query(default="PL", description="ISO country code"),
    postal_code: Optional[str] = Query(default=None, description="Postal code"),
    city: Optional[str] = Query(default=None, description="City name"),
    use_cache: bool = Query(default=True, description="Use cached results")
):
    """
    Resolve location to geographic coordinates and elevation.

    For Poland (PL), major cities have preloaded coordinates for faster response.
    Other locations use OpenStreetMap Nominatim for geocoding.

    Example:
    - /geo/resolve?country=PL&city=Warszawa
    - /geo/resolve?country=PL&postal_code=00-001&city=Warszawa
    """
    if not postal_code and not city:
        raise HTTPException(
            status_code=400,
            detail="At least postal_code or city must be provided"
        )

    # Check cache if enabled
    if use_cache:
        cached = geo_cache.get(country, postal_code or "", city or "")
        if cached:
            return GeoLocation(**cached, cached=True)

    # For Poland, try quick lookups first (no external API needed)
    if country.upper() == "PL":
        # Try city lookup first
        if city:
            quick_result = lookup_polish_city(city)
            if quick_result:
                result = {
                    "latitude": quick_result["latitude"],
                    "longitude": quick_result["longitude"],
                    "elevation": quick_result["elevation"],
                    "display_name": f"{city}, Polska",
                    "country": "PL",
                    "postal_code": postal_code,
                    "city": city,
                    "source": "preloaded"
                }
                geo_cache.set(country, postal_code or "", city or "", result)
                return GeoLocation(**result, cached=False)

        # Try postal code lookup (uses regional database)
        if postal_code:
            postal_result = lookup_polish_postal_code(postal_code)
            if postal_result:
                formatted_postal = format_polish_postal_code(postal_code)
                result = {
                    "latitude": postal_result["latitude"],
                    "longitude": postal_result["longitude"],
                    "elevation": postal_result["elevation"],
                    "display_name": f"{formatted_postal}, {postal_result['city']}, Polska",
                    "country": "PL",
                    "postal_code": formatted_postal,
                    "city": postal_result["city"],
                    "source": "postal_database"
                }
                geo_cache.set(country, postal_code or "", city or "", result)
                return GeoLocation(**result, cached=False)

    # Full geocoding via Nominatim (fallback)
    result = await resolve_location(country, postal_code, city)

    if not result:
        # For Poland, return error with suggestion
        if country.upper() == "PL":
            raise HTTPException(
                status_code=404,
                detail=f"Nie znaleziono lokalizacji: {city or ''} {postal_code or ''}, {country}. Spróbuj podać nazwę miasta."
            )
        raise HTTPException(
            status_code=404,
            detail=f"Location not found: {city or ''} {postal_code or ''}, {country}"
        )

    return result

@app.get("/geo/elevation")
async def get_elevation_only(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude")
):
    """
    Get elevation for given coordinates.
    """
    elevation = await get_elevation(lat, lon)

    if elevation is None:
        raise HTTPException(
            status_code=404,
            detail="Could not retrieve elevation for given coordinates"
        )

    return {
        "latitude": lat,
        "longitude": lon,
        "elevation": elevation,
        "unit": "meters"
    }

@app.post("/geo/resolve-batch")
async def resolve_batch(locations: list[GeoResolveRequest]):
    """
    Resolve multiple locations in batch.
    Limited to 10 locations per request.
    """
    if len(locations) > 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum 10 locations per batch request"
        )

    results = []
    for loc in locations:
        try:
            result = await resolve_location(loc.country, loc.postal_code, loc.city)
            results.append(result.dict() if result else {"error": "Not found"})
        except Exception as e:
            results.append({"error": str(e)})

        # Rate limiting - wait between requests
        await asyncio.sleep(1.1)  # Nominatim requires 1 req/sec

    return {"results": results}

@app.get("/geo/cache/stats")
async def cache_stats():
    """Get cache statistics."""
    return geo_cache.stats()

@app.post("/geo/cache/clear")
async def cache_clear():
    """Clear the cache."""
    geo_cache.clear()
    return {"status": "Cache cleared"}

@app.get("/geo/cities/pl")
async def get_polish_cities():
    """Get list of preloaded Polish cities."""
    return {
        "count": len(POLISH_CITIES),
        "cities": list(set(c.title() for c in POLISH_CITIES.keys()))
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021)
