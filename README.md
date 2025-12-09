# Pagra ENERGY Studio

**PRODUCE. STORE. PERFORM.**

**Wersja 3.1** - Zaawansowane narzedzie do optymalizacji systemow fotowoltaicznych i magazynow energii (BESS) z architektura mikroserwisow.

## 🏗️ Architektura

Aplikacja zbudowana jest w architekturze micro-frontend z modularnym backendem:

### Backend Services (Python/FastAPI)
| Serwis | Port | Opis |
|--------|------|------|
| **data-analysis** | 8001 | Przetwarzanie i analiza danych zuzycia |
| **pv-calculation** | 8002 | Symulacje produkcji PV (pvlib), symulacja BESS |
| **economics** | 8003 | Analizy ekonomiczne i modelowanie finansowe (PV + BESS) |
| **advanced-analytics** | 8004 | Zaawansowana analityka |
| **typical-days** | 8005 | Analiza dni typowych |
| **energy-prices** | 8010 | Pobieranie cen energii (TGE/ENTSO-E) |
| **reports** | 8011 | Generowanie raportow PDF |
| **projects-db** | 8012 | Baza danych projektow (SQLite) |
| **pvgis-proxy** | 8020 | Proxy do PVGIS API |
| **geo-service** | 8021 | Geokodowanie lokalizacji (Nominatim) |

### Frontend Modules (HTML/JS/Nginx)
| Modul | Port | Opis |
|-------|------|------|
| **Shell** | 80 | Glowna powloka, nginx reverse proxy, routing |
| **Admin** | 9001 | Panel administracyjny |
| **Config** | 9002 | Konfiguracja instalacji PV |
| **Consumption** | 9003 | Analiza danych zuzycia energii |
| **Production** | 9004 | Produkcja PV z scenariuszami P50/P75/P90 |
| **Comparison** | 9005 | Porownanie wariantow |
| **Economics** | 9006 | Analiza ekonomiczna EaaS/Wlasnosc |
| **Settings** | 9007 | Ustawienia systemowe (+ konfiguracja BESS) |
| **ESG** | 9008 | Wskazniki srodowiskowe (CO2, drzewa) |
| **Energy Prices** | 9009 | Ceny energii elektrycznej |
| **Reports** | 9010 | Generowanie raportow PDF |
| **Projects** | 9011 | Zarzadzanie projektami |
| **Estimator** | 9012 | Szybka wycena PV |
| **BESS** | 9013 | Magazyny energii (Battery Energy Storage) |

## 🌟 Glowne Funkcjonalnosci

### Magazyny Energii (BESS) - NOWE w v2.4+
- Tryby: OFF / LIGHT (0-export)
- Automatyczne dobor mocy i pojemnosci
- Symulacja 8760 godzin rocznie
- Analiza degradacji baterii (rok 1: 3%, lata 2+: 2%/rok)
- Ekonomika BESS (CAPEX, OPEX, wymiana po 15 latach)
- Porownanie scenariuszy PV vs PV+BESS

### Szybka Wycena (Estimator)
- Szybkie oszacowanie mocy i kosztow instalacji PV
- Presety mocy: 50kWp, 100kWp, 200kWp, 500kWp, 1MWp
- Wybor typu instalacji (grunt/dach/carport)
- Scenariusze finansowe P50/P75/P90
- Analiza oplacalnosci w czasie rzeczywistym

### System Projektow - NOWE!
- Tworzenie i zarzadzanie projektami PV
- Geolokalizacja automatyczna (kod pocztowy/miasto)
- Baza danych polskich lokalizacji (offline)
- Import/eksport projektow

### Analiza Zuzycia
- Import danych z plikow CSV/Excel
- Automatyczne wykrywanie formatu danych
- Analiza profilu godzinowego/dobowego/miesiecznego
- Identyfikacja szczytow zuzycia

### Symulacja Produkcji PV
- Integracja z PVGIS dla danych nasloniecznienia
- Scenariusze produkcji P50/P75/P90
- Zarzadzanie DC/AC Ratio
- Obliczanie autokonsumpcji i samowystarczalnosci
- Eksport/Import z sieci

### Analiza Ekonomiczna
- Model EaaS (Energy as a Service)
- Model wlasnosci instalacji
- Analiza NPV, IRR, LCOE
- Prognozowanie oszczednosci 25-letnich
- Integracja z cenami rynkowymi TGE

### Wskazniki ESG
- Redukcja emisji CO2
- Ekwiwalent posadzonych drzew
- Oszczednosci wody
- Raportowanie srodowiskowe

### Raporty
- Generowanie PDF z pelna analiza
- Wykresy i wizualizacje
- Eksport danych do Excel

## 📋 Wymagania

### Docker Deployment
- Docker 20.10+
- Docker Compose 2.0+
- 8 GB RAM (zalecane)

## 🚀 Szybki Start

### 1. Uruchomienie aplikacji

```bash
# Zbuduj i uruchom wszystkie serwisy
docker-compose up -d --build

# Lub tylko uruchom (jesli juz zbudowane)
docker-compose up -d
```

### 2. Dostep do aplikacji

- **Glowna aplikacja**: http://localhost
- **Produkcja (Hetzner via VPN)**: http://100.79.226.117
- **API Documentation**:
  - Data Analysis: http://localhost:8001/docs
  - PV Calculation: http://localhost:8002/docs
  - Economics: http://localhost:8003/docs
  - Energy Prices: http://localhost:8010/docs
  - Reports: http://localhost:8011/docs
  - Projects DB: http://localhost:8012/docs
  - PVGIS Proxy: http://localhost:8020/docs
  - Geo Service: http://localhost:8021/docs

## 📁 Struktura Projektu

```
ANALIZATOR PV/
├── services/
│   ├── data-analysis/          # Analiza danych zuzycia
│   ├── pv-calculation/         # Obliczenia PV (pvlib)
│   ├── economics/              # Analizy ekonomiczne
│   ├── advanced-analytics/     # Zaawansowana analityka
│   ├── typical-days/           # Dni typowe
│   ├── energy-prices/          # Ceny energii
│   ├── reports/                # Generowanie PDF
│   ├── geo-service/            # Geokodowanie lokalizacji
│   ├── projects-db/            # Baza projektow
│   ├── frontend-shell/         # Glowna powloka (Classic UX)
│   ├── frontend-admin/         # Panel admina
│   ├── frontend-config/        # Konfiguracja PV
│   ├── frontend-consumption/   # Zuzycie energii
│   ├── frontend-production/    # Produkcja PV
│   ├── frontend-comparison/    # Porownanie wariantow
│   ├── frontend-economics/     # Ekonomia
│   ├── frontend-settings/      # Ustawienia
│   ├── frontend-esg/           # Wskazniki ESG
│   ├── frontend-energy-prices/ # Ceny energii UI
│   ├── frontend-reports/       # Raporty UI
│   ├── frontend-projects/      # Zarzadzanie projektami
│   ├── frontend-estimator/     # Szybka wycena
│   ├── frontend-bess/          # Magazyny energii (BESS)
│   ├── pvgis-proxy/            # Proxy PVGIS API
│   └── projects-db/            # Baza projektow SQLite
├── docker-compose.yml
└── README.md
```

## 🐳 Komendy Docker

### Logi serwisow
```bash
# Wszystkie serwisy
docker-compose logs -f

# Konkretny serwis
docker-compose logs -f frontend-production
docker-compose logs -f pv-calculation
```

### Restart serwisow
```bash
# Wszystkie
docker-compose restart

# Konkretny
docker-compose restart frontend-production
```

### Przebudowa po zmianach
```bash
# Pojedynczy serwis
docker-compose build frontend-production
docker-compose up -d frontend-production

# Wszystkie
docker-compose up -d --build
```

### Zatrzymanie
```bash
docker-compose down
```

## 🔍 Health Checks

Wszystkie serwisy posiadaja endpointy health check:

```bash
curl http://localhost:8001/health  # Data Analysis
curl http://localhost:8002/health  # PV Calculation (+ pvlib version)
curl http://localhost:8003/health  # Economics
curl http://localhost:8010/health  # Energy Prices
curl http://localhost:8011/health  # Reports
curl http://localhost:8012/health  # Projects DB
curl http://localhost:8020/health  # PVGIS Proxy
curl http://localhost:8021/health  # Geo Service
```

## 📊 Komunikacja Miedzymodulowa

Moduly frontendowe komunikuja sie przez Shell za pomoca postMessage API:

| Event | Opis |
|-------|------|
| `DATA_UPLOADED` | Dane zuzycia zaladowane |
| `ANALYSIS_COMPLETE` | Analiza PV zakonczona |
| `MASTER_VARIANT_SELECTED` | Wybrany wariant glowny |
| `SCENARIO_CHANGED` | Zmiana scenariusza P50/P75/P90 |
| `SETTINGS_UPDATED` | Ustawienia zaktualizowane |
| `ECONOMICS_CALCULATED` | Obliczenia ekonomiczne gotowe |
| `PROJECT_LOADED` | Projekt zaladowany |
| `PROJECT_SAVED` | Projekt zapisany |
| `VARIANT_CHANGED` | Zmiana wariantu (A/B/C/D) |
| `BESS_DATA_UPDATED` | Dane BESS zaktualizowane |

## 🛠️ Rozwiazywanie Problemow

### Serwisy nie startuja
```bash
docker-compose logs
docker-compose ps
```

### Cache przegladarki
Po aktualizacji kodu frontend, wyczysc cache lub:
```bash
docker-compose build frontend-production --no-cache
docker-compose up -d frontend-production
```

### Konflikty portow
Zmodyfikuj mapowania portow w `docker-compose.yml` jesli porty sa zajete.

### Geolokalizacja nie dziala
Serwis geo-service wymaga dostepu do internetu dla Nominatim API.
Dla polskich lokalizacji dziala offline dzieki wbudowanej bazie kodow pocztowych.

## 📝 Historia Wersji

### v3.1 (Aktualna)
- **Pagra ENERGY Studio** - nowy branding i logo
- **Nginx Reverse Proxy** - ujednolicony routing modulow i API
- **USE_PROXY mode** - produkcja przez nginx proxy
- Naprawy routingu (BESS, Projects health, X-Frame-Options)
- Deploy na Hetzner z Tailscale VPN

### v2.4
- **Modul BESS** - magazyny energii (Battery Energy Storage)
- Symulacja 8760h z logika 0-export
- Degradacja baterii (3% rok 1, 2%/rok potem)
- Ekonomika BESS (CAPEX/OPEX/wymiana)

### v2.3
- BESS Light/Auto Mode
- Automatyczny dobor pojemnosci BESS

### v1.9
- **System Projektow** - zarzadzanie projektami z geolokalizacja
- **Szybka Wycena (Estimator)** - szybka kalkulacja PV
- **Geo Service** - geokodowanie z baza polskich lokalizacji

### v1.8
- Selektor scenariuszy P50/P75/P90 w module Produkcja PV
- Modul ESG ze wskaznikami srodowiskowymi
- Synchronizacja scenariuszy miedzy modulami

## 🔐 Bezpieczenstwo

- Serwisy uruchamiane jako non-root w kontenerach
- CORS skonfigurowany dla srodowiska deweloperskiego
- Stateless design - brak przechowywania danych wrazliwych
- Health checks dla monitorowania dostepnosci

## 👥 Autorzy

Pagra ENERGY Development Team

---

**v3.1** - Pagra ENERGY Studio
