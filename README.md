# PV Optimizer Pro - Microservices Edition

**Wersja 1.9** - Zaawansowane narzedzie do optymalizacji systemow fotowoltaicznych z architektura mikroserwisow.

## 🏗️ Architektura

Aplikacja zbudowana jest w architekturze micro-frontend z modularnym backendem:

### Backend Services (Python/FastAPI)
| Serwis | Port | Opis |
|--------|------|------|
| **data-analysis** | 8001 | Przetwarzanie i analiza danych zuzycia |
| **pv-calculation** | 8002 | Symulacje produkcji PV (pvlib) |
| **economics** | 8003 | Analizy ekonomiczne i modelowanie finansowe |
| **advanced-analytics** | 8004 | Zaawansowana analityka |
| **typical-days** | 8005 | Analiza dni typowych |
| **energy-prices** | 8010 | Pobieranie cen energii (TGE/ENTSO-E) |
| **reports** | 8011 | Generowanie raportow PDF |
| **geo-service** | 8021 | Geokodowanie lokalizacji (Nominatim) |
| **projects-db** | 8022 | Baza danych projektow |

### Frontend Modules (HTML/JS/Nginx)
| Modul | Port | Opis |
|-------|------|------|
| **Shell** | 80 (9000) | Glowna powloka aplikacji, routing |
| **Admin** | 9001 | Panel administracyjny |
| **Config** | 9002 | Konfiguracja instalacji PV |
| **Consumption** | 9003 | Analiza danych zuzycia energii |
| **Production** | 9004 | Produkcja PV z scenariuszami P50/P75/P90 |
| **Comparison** | 9005 | Porownanie wariantow |
| **Economics** | 9006 | Analiza ekonomiczna EaaS/Wlasnosc |
| **Settings** | 9007 | Ustawienia systemowe |
| **ESG** | 9008 | Wskazniki srodowiskowe (CO2, drzewa) |
| **Energy Prices** | 9009 | Ceny energii elektrycznej |
| **Reports** | 9010 | Generowanie raportow PDF |
| **Projects** | 9011 | Zarzadzanie projektami |
| **Estimator** | 9012 | Szybka wycena PV |

## 🌟 Glowne Funkcjonalnosci

### Szybka Wycena (Estimator) - NOWE!
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

- **Glowna aplikacja**: http://localhost (lub http://localhost:80)
- **API Documentation**:
  - Data Analysis: http://localhost:8001/docs
  - PV Calculation: http://localhost:8002/docs
  - Economics: http://localhost:8003/docs
  - Energy Prices: http://localhost:8010/docs
  - Reports: http://localhost:8011/docs
  - Geo Service: http://localhost:8021/docs
  - Projects DB: http://localhost:8022/docs

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
│   └── frontend-estimator/     # Szybka wycena
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
curl http://localhost:8021/health  # Geo Service
curl http://localhost:8022/health  # Projects DB
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

### v1.9 (Aktualna)
- **System Projektow** - zarzadzanie projektami z geolokalizacja
- **Szybka Wycena (Estimator)** - szybka kalkulacja PV
- **Geo Service** - geokodowanie z baza polskich lokalizacji
- Presety mocy w Estimatorze (50kWp - 1MWp)
- Naprawy ESG i synchronizacji danych

### v1.8
- Selektor scenariuszy P50/P75/P90 w module Produkcja PV
- Modul ESG ze wskaznikami srodowiskowymi
- Dynamiczne obliczenia autokonsumpcji z danych godzinowych
- Synchronizacja scenariuszy miedzy modulami
- Naprawy formatowania liczb (format europejski)

### v1.7
- Zarzadzanie DC/AC Ratio
- Naprawy modulu Ekonomia

### v1.6
- Integracja PVGIS dla scenariuszy P50/P75/P90

### v1.5
- Globalny selektor scenariuszy

### v1.4
- Modul Raportow PDF
- Integracja Economics z Reports

## 🔐 Bezpieczenstwo

- Serwisy uruchamiane jako non-root w kontenerach
- CORS skonfigurowany dla srodowiska deweloperskiego
- Stateless design - brak przechowywania danych wrazliwych
- Health checks dla monitorowania dostepnosci

## 👥 Autorzy

PV Optimizer Development Team ;)

---

**v1.9** - PV Optimizer Pro Microservices Edition
