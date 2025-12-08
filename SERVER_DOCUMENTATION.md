# PV Optimizer Pro v3.0 - Server & Deployment Documentation

## Informacje o Serwerze Produkcyjnym

### Dane serwera Hetzner
| Parametr | Wartość |
|----------|---------|
| **Dostawca** | Hetzner (Server Auction) |
| **Lokalizacja** | Helsinki, Finlandia (hel1) |
| **Nazwa hosta** | ubuntu-32gb-hel1-1 |
| **System** | Ubuntu |
| **RAM** | 64 GB |
| **Dyski** | 2x 512GB NVMe SSD |
| **Koszt** | ~€30.70/miesiąc |
| **IP Publiczne** | 77.42.45.253 |
| **IP Tailscale (VPN)** | 100.79.226.117 |

### Dostęp do serwera

#### SSH (tylko przez klucz)
```bash
# Z komputera z kluczem SSH
ssh -p 2222 root@77.42.45.253

# Lub przez Tailscale (bezpieczniejsze)
ssh -p 2222 root@100.79.226.117
```

#### Aplikacja webowa
```
http://100.79.226.117
```
**UWAGA**: Aplikacja jest dostępna TYLKO przez Tailscale VPN. Publiczny IP (77.42.45.253) jest zablokowany przez firewall.

---

## Zabezpieczenia serwera

### 1. Tailscale VPN
- Serwer i klient muszą być w tej samej sieci Tailscale
- Panel administracyjny: https://login.tailscale.com/admin
- Konto: pagra.eu

### 2. UFW Firewall
```bash
# Sprawdź status
ufw status verbose

# Aktualne reguły:
# - Port 2222/tcp (SSH) - otwarty
# - Interfejs tailscale0 - otwarty
# - Reszta - zablokowana (deny incoming)
```

### 3. SSH zabezpieczenia
- Port zmieniony z 22 na **2222**
- Logowanie hasłem **wyłączone** (tylko klucz SSH)
- Klucz: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH797xyHnDu7td06ToNz6NFTRiw59G6pNIw/XUGr5xuI BOSS`

### 4. Fail2ban
- Automatycznie blokuje IP po nieudanych próbach logowania
```bash
# Status
systemctl status fail2ban

# Zablokowane IP
fail2ban-client status sshd
```

### 5. Automatyczne aktualizacje
- Pakiet `unattended-upgrades` zainstalowany
- Automatycznie instaluje łatki bezpieczeństwa

---

## Docker - Komendy

### Podstawowe operacje

```bash
# Przejdź do katalogu projektu
cd /opt/analizator-pv

# Status wszystkich kontenerów
docker-compose ps

# Uruchom wszystkie kontenery
docker-compose up -d

# Zatrzymaj wszystkie kontenery
docker-compose down

# Zrestartuj wszystkie kontenery
docker-compose restart

# Przebuduj i uruchom (po zmianach w kodzie)
docker-compose up -d --build

# Przebuduj konkretny serwis
docker-compose build frontend-production
docker-compose up -d frontend-production
```

### Logi

```bash
# Logi wszystkich kontenerów
docker-compose logs

# Logi konkretnego serwisu (ostatnie 100 linii)
docker-compose logs --tail=100 frontend-shell

# Logi na żywo (follow)
docker-compose logs -f frontend-economics

# Logi z backendu
docker-compose logs -f data-analysis
docker-compose logs -f pv-calculation
docker-compose logs -f economics-service
```

### Debugowanie

```bash
# Wejdź do kontenera
docker exec -it pv-frontend-shell sh

# Sprawdź zużycie zasobów
docker stats

# Wyczyść nieużywane obrazy/wolumeny
docker system prune -f

# Pełne czyszczenie (UWAGA: usuwa wszystko!)
docker system prune -a --volumes
```

---

## Struktura projektu

```
/opt/analizator-pv/
├── docker-compose.yml          # Orchestracja kontenerów
├── services/
│   ├── frontend-shell/         # Port 9000 - główna aplikacja
│   │   ├── index.html
│   │   ├── shell.js            # Hub komunikacji między modułami
│   │   └── Dockerfile
│   ├── frontend-config/        # Port 9002 - konfiguracja PV
│   ├── frontend-consumption/   # Port 9003 - analiza zużycia
│   ├── frontend-production/    # Port 9004 - produkcja PV
│   ├── frontend-comparison/    # Port 9005 - porównanie wariantów
│   ├── frontend-economics/     # Port 9006 - analiza ekonomiczna
│   ├── frontend-settings/      # Port 9007 - ustawienia
│   ├── frontend-esg/           # Port 9008 - raport ESG
│   ├── frontend-energy-prices/ # Port 9009 - ceny energii
│   ├── frontend-reports/       # Port 9010 - raporty PDF
│   ├── frontend-projects/      # Port 9011 - zarządzanie projektami
│   ├── frontend-admin/         # Port 9001 - administracja
│   ├── frontend-bess/          # Port 9012 - magazyny energii (BESS)
│   ├── data-analysis/          # Port 8001 - analiza danych (Python)
│   ├── pv-calculation/         # Port 8002 - obliczenia PV (Python + pvlib)
│   ├── economics-service/      # Port 8003 - ekonomia (Python)
│   ├── advanced-analytics/     # Port 8004 - zaawansowana analityka
│   ├── typical-days/           # Port 8005 - typowe dni
│   ├── energy-prices/          # Port 8010 - pobieranie cen
│   ├── reports-service/        # Port 8011 - generowanie raportów
│   ├── projects-db/            # Port 8012 - baza projektów (SQLite)
│   └── pvgis-proxy/            # Port 8020 - proxy PVGIS
```

---

## Porty serwisów

### Frontend (Nginx)
| Serwis | Port | Opis |
|--------|------|------|
| Shell | 9000 | Główna aplikacja, hub komunikacji |
| Admin | 9001 | Panel administracyjny |
| Config | 9002 | Konfiguracja systemu PV |
| Consumption | 9003 | Wizualizacja zużycia |
| Production | 9004 | Analiza produkcji PV |
| Comparison | 9005 | Porównanie wariantów |
| Economics | 9006 | Analiza ekonomiczna |
| Settings | 9007 | Ustawienia systemu |
| ESG | 9008 | Raport środowiskowy |
| Energy Prices | 9009 | Ceny energii |
| Reports | 9010 | Generowanie raportów |
| Projects | 9011 | Zarządzanie projektami |
| BESS | 9012 | Magazyny energii |

### Backend (Python/FastAPI)
| Serwis | Port | Technologia |
|--------|------|-------------|
| Data Analysis | 8001 | FastAPI + Pandas |
| PV Calculation | 8002 | FastAPI + pvlib |
| Economics | 8003 | FastAPI + NumPy |
| Advanced Analytics | 8004 | FastAPI |
| Typical Days | 8005 | FastAPI |
| Energy Prices | 8010 | FastAPI |
| Reports | 8011 | FastAPI + ReportLab |
| Projects DB | 8012 | FastAPI + SQLite |
| PVGIS Proxy | 8020 | FastAPI |
| API Gateway | 80 | Nginx (reverse proxy) |

---

## API Endpoints

### Data Analysis (8001)
```bash
POST /upload/csv          # Upload pliku CSV
POST /upload/excel        # Upload pliku Excel
POST /restore-data        # Przywróć dane z projektu
GET  /statistics          # Statystyki zużycia
GET  /hourly-data         # Dane godzinowe
GET  /heatmap             # Dane do heatmapy
GET  /health              # Health check
```

### PV Calculation (8002)
```bash
POST /analyze             # Pełna analiza PV
POST /generate-profile    # Generuj profil produkcji
GET  /monthly-production  # Produkcja miesięczna
GET  /health              # Health check (+ wersja pvlib)
```

### Economics (8003)
```bash
POST /analyze                      # Analiza ekonomiczna
POST /comprehensive-sensitivity    # Analiza wrażliwości
GET  /default-parameters           # Domyślne parametry
GET  /health                       # Health check
```

### Projects DB (8012)
```bash
POST   /projects              # Utwórz projekt
GET    /projects              # Lista projektów
GET    /projects/{id}         # Szczegóły projektu
GET    /projects/{id}/load-full  # Załaduj pełny projekt
POST   /projects/{id}/data    # Zapisz dane projektu
DELETE /projects/{id}         # Usuń projekt
GET    /health                # Health check
```

### Health check wszystkich serwisów
```bash
# Na serwerze
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8010/health
curl http://localhost:8011/health
curl http://localhost:8012/health
```

---

## Komunikacja między modułami (postMessage)

### Typy wiadomości

```javascript
// Wysyłanie danych do modułu
parent.postMessage({
    type: 'SHARED_DATA_UPDATE',
    payload: { analysisResults: data }
}, '*');

// Zmiana scenariusza (P50/P75/P90)
parent.postMessage({
    type: 'PRODUCTION_SCENARIO_CHANGED',
    payload: { scenario: 'P75', source: 'production' }
}, '*');

// Analiza zakończona
parent.postMessage({
    type: 'ANALYSIS_COMPLETE',
    payload: { analysisResults: results }
}, '*');

// Żądanie danych
parent.postMessage({
    type: 'REQUEST_SHARED_DATA',
    payload: {}
}, '*');
```

### Nasłuchiwanie w module
```javascript
window.addEventListener('message', (event) => {
    if (event.data.type === 'SHARED_DATA_UPDATE') {
        const data = event.data.payload;
        // obsłuż dane
    }
});
```

---

## Git - Komendy

### Podstawowe operacje

```bash
# Status zmian
git status

# Dodaj wszystkie zmiany
git add .

# Commit ze szczegółowym opisem
git commit -m "feat: opis zmiany"

# Push na GitHub
git push origin master
```

### Konwencja commitów
```
feat:     Nowa funkcjonalność
fix:      Naprawa błędu
refactor: Refaktoryzacja kodu
docs:     Dokumentacja
style:    Formatowanie
test:     Testy
chore:    Inne (konfiguracja, etc.)
```

### Aktualizacja serwera z GitHub

```bash
# Na serwerze (przez SSH)
cd /opt/analizator-pv
git pull origin master
docker-compose up -d --build
```

---

## Aktualizacja aplikacji

### Szybka aktualizacja (bez przebudowy)
```bash
cd /opt/analizator-pv
git pull origin master
docker-compose restart
```

### Pełna aktualizacja (z przebudową)
```bash
cd /opt/analizator-pv
git pull origin master
docker-compose down
docker-compose up -d --build
```

### Aktualizacja pojedynczego modułu
```bash
# Przykład: frontend-economics
docker-compose build frontend-economics
docker-compose up -d frontend-economics
```

---

## Rozwiązywanie problemów

### Aplikacja nie ładuje się
```bash
# Sprawdź czy kontenery działają
docker-compose ps

# Sprawdź logi
docker-compose logs --tail=50

# Zrestartuj
docker-compose restart
```

### Moduł nie odpowiada
```bash
# Sprawdź konkretny kontener
docker-compose logs frontend-economics

# Zrestartuj konkretny moduł
docker-compose restart frontend-economics
```

### Błędy API (CORS, timeout)
```bash
# Sprawdź logi backendu
docker-compose logs data-analysis
docker-compose logs pv-calculation

# Sprawdź health
curl http://localhost:8001/health
curl http://localhost:8002/health
```

### Brak miejsca na dysku
```bash
# Sprawdź miejsce
df -h

# Wyczyść Docker
docker system prune -f
docker image prune -a -f
```

### Problem z Tailscale
```bash
# Status
tailscale status

# Restart
systemctl restart tailscaled

# Ponowne logowanie
tailscale up
```

### Brak połączenia SSH
1. Sprawdź czy używasz portu 2222: `ssh -p 2222 root@77.42.45.253`
2. Sprawdź czy masz prawidłowy klucz SSH
3. Połącz się przez panel Hetzner (VNC console)

---

## Backup i przywracanie

### Backup bazy projektów
```bash
# Na serwerze
docker cp pv-projects-db:/app/projects.db /root/backup/projects_$(date +%Y%m%d).db
```

### Backup całego projektu
```bash
# Na serwerze
tar -czf /root/backup/analizator-pv_$(date +%Y%m%d).tar.gz /opt/analizator-pv
```

### Przywracanie
```bash
# Przywróć bazę
docker cp /root/backup/projects_20241208.db pv-projects-db:/app/projects.db
docker-compose restart projects-db
```

---

## Monitoring

### Sprawdzenie zużycia zasobów
```bash
# CPU, RAM, I/O dla kontenerów
docker stats

# Ogólne zużycie systemu
htop

# Miejsce na dysku
df -h
```

### Automatyczne sprawdzenie health
```bash
# Skrypt do sprawdzenia wszystkich serwisów
for port in 8001 8002 8003 8010 8011 8012; do
  echo "Port $port: $(curl -s http://localhost:$port/health | head -c 50)"
done
```

---

## Ważne pliki konfiguracyjne

| Plik | Ścieżka | Opis |
|------|---------|------|
| Docker Compose | `/opt/analizator-pv/docker-compose.yml` | Definicja wszystkich kontenerów |
| SSH Config | `/etc/ssh/sshd_config` | Konfiguracja SSH (port 2222) |
| UFW Rules | `/etc/ufw/` | Reguły firewall |
| Docker Daemon | `/etc/docker/daemon.json` | Konfiguracja Dockera |
| Tailscale | `/var/lib/tailscale/` | Dane Tailscale |

---

## Kontakty i wsparcie

- **GitHub Repo**: https://github.com/pawelsmas/analizator-pv
- **Hetzner Panel**: https://console.hetzner.cloud/
- **Tailscale Panel**: https://login.tailscale.com/admin

---

## Historia wersji

| Wersja | Data | Zmiany |
|--------|------|--------|
| v3.0 | 2024-12 | Deploy na Hetzner, Tailscale VPN |
| v2.4 | 2024-12 | Moduł BESS (magazyny energii) |
| v2.3 | 2024-12 | BESS Light/Auto Mode |
| v2.2 | 2024-12 | CAPEX per typ instalacji |
| v2.1 | 2024-12 | Ujednolicone tabele ekonomiczne |

---

**Dokumentacja utworzona**: 2024-12-08
