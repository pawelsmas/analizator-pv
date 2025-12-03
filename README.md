# PV Optimizer Pro - Microservices Edition

**Wersja 1.8** - Zaawansowane narzedzie do optymalizacji systemow fotowoltaicznych z architektura mikroserwisow.

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

### Frontend Modules (HTML/JS/Nginx)
| Modul | Port | Opis |
|-------|------|------|
| **Shell** | 9000 | Glowna powloka aplikacji, routing |
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

## 🌟 Glowne Funkcjonalnosci

### Analiza Zuzycia
- Import danych z plikow CSV/Excel
- Automatyczne wykrywanie formatu danych
- Analiza profilu godzinowego/dobowego/miesiecznego
- Identyfikacja szczytow zuzycia

### Symulacja Produkcji PV
- Integracja z PVGIS dla danych naslonienia
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

- **Glowna aplikacja**: http://localhost:9000
- **API Documentation**:
  - Data Analysis: http://localhost:8001/docs
  - PV Calculation: http://localhost:8002/docs
  - Economics: http://localhost:8003/docs
  - Energy Prices: http://localhost:8010/docs
  - Reports: http://localhost:8011/docs

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
│   ├── frontend-shell/         # Glowna powloka
│   ├── frontend-admin/         # Panel admina
│   ├── frontend-config/        # Konfiguracja PV
│   ├── frontend-consumption/   # Zuzycie energii
│   ├── frontend-production/    # Produkcja PV
│   ├── frontend-comparison/    # Porownanie wariantow
│   ├── frontend-economics/     # Ekonomia
│   ├── frontend-settings/      # Ustawienia
│   ├── frontend-esg/           # Wskazniki ESG
│   ├── frontend-energy-prices/ # Ceny energii UI
│   └── frontend-reports/       # Raporty UI
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
Zmodyfikuj mapowania portow w `docker-compose.yml` jesli porty 8001-8011 lub 9000-9010 sa zajete.

## 📝 Historia Wersji

### v1.8 (Aktualna)
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

PV Optimizer Development Team

---

**v1.8** - PV Optimizer Pro Microservices Edition
