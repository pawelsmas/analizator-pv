# Dokumentacja: Analiza BESS vs Kara za przekroczenie mocy

## Spis treści
1. [Wprowadzenie](#wprowadzenie)
2. [Źródła danych](#źródła-danych)
3. [Obliczenie kary za przekroczenie mocy](#obliczenie-kary-za-przekroczenie-mocy)
4. [Dobór wielkości magazynu BESS](#dobór-wielkości-magazynu-bess)
5. [Analiza ekonomiczna](#analiza-ekonomiczna)
6. [Prezentacja wyników](#prezentacja-wyników)
7. [Parametry i założenia](#parametry-i-założenia)

---

## Wprowadzenie

Moduł analizy Peak Shaving porównuje dwie strategie zarządzania przekroczeniami mocy umownej:

1. **Strategia BESS** - instalacja magazynu energii, który ścina szczyty mocy
2. **Strategia Kara** - płacenie kar za przekroczenie mocy umownej zgodnie z taryfą OSD

Celem jest określenie, która strategia jest bardziej opłacalna ekonomicznie w horyzoncie 15 lat.

---

## Źródła danych

### Dane wejściowe

```
Źródło: peakShavingExportData (analiza krzywej uporządkowanej obciążenia)

Struktura danych dla każdego poziomu PXX:
{
  name: "P99.5",              // Nazwa poziomu
  powerKW: 968,               // Próg mocy = P_um (moc umowna) [kW]
  hoursAbove: 42,             // Liczba godzin przekroczenia w roku
  energyToShave: 3310,        // Energia do ścięcia [kWh]
  exceedanceEvents: [         // Lista zdarzeń przekroczenia
    {
      timestamp: "2024-01-15T14:00:00",
      value: 1150,            // Moc w tej godzinie [kW]
      originalIndex: 1234
    },
    ...
  ]
}
```

### Poziomy PXX

| Poziom | Znaczenie |
|--------|-----------|
| P100 (Szczyt) | Maksymalna moc w roku (brak przekroczeń) |
| P99.5 | Moc przekroczona przez 0.5% czasu (~44 godz./rok) |
| P99 | Moc przekroczona przez 1% czasu (~88 godz./rok) |
| P98 | Moc przekroczona przez 2% czasu (~175 godz./rok) |
| P97 | Moc przekroczona przez 3% czasu (~263 godz./rok) |
| P95 | Moc przekroczona przez 5% czasu (~438 godz./rok) |

---

## Obliczenie kary za przekroczenie mocy

### Podstawa prawna

Kara za przekroczenie mocy umownej jest naliczana zgodnie z taryfą Operatora Systemu Dystrybucyjnego (OSD). Wzór wynika z przepisów prawa energetycznego i taryf zatwierdzanych przez URE.

### Wzór na karę

```
Kara_miesięczna = C_ss × suma(TOP10 nadwyżek godzinowych w miesiącu)
```

Gdzie:
- **C_ss** - składnik stały stawki sieciowej [zł/kW/mies.]
- **TOP10** - 10 największych godzinowych nadwyżek mocy ponad moc umowną

### Algorytm obliczenia

```javascript
// Krok 1: Dla każdego zdarzenia oblicz nadwyżkę godzinową
nadwyżka_h = max(P_h - P_um, 0)

// Gdzie:
// P_h   = moc pobrana w godzinie h [kW]
// P_um  = moc umowna (próg dla danego PXX) [kW]

// Krok 2: Grupuj nadwyżki po miesiącach
monthlyData = {
  "2024-01": [nadwyżka_1, nadwyżka_2, ...],
  "2024-02": [...],
  ...
}

// Krok 3: Dla każdego miesiąca
for (month in monthlyData) {
  // Sortuj malejąco
  sorted = monthlyData[month].sort(descending)

  // Weź TOP10 (lub mniej jeśli nie ma 10)
  top10 = sorted.slice(0, 10)

  // Oblicz karę za miesiąc
  kara_miesiąc = C_ss × suma(top10)
}

// Krok 4: Suma roczna
kara_roczna = suma(wszystkich kar miesięcznych)
```

### Przykład obliczenia

```
Dane:
- P_um = 968 kW (P99.5)
- C_ss = 40 zł/kW/mies.
- Styczeń 2024: przekroczenia w godzinach [1150, 1120, 1100, 1080, 1050, 1030, 1010, 990, 985, 980, 975, 970] kW

Obliczenie:
1. Nadwyżki: [182, 152, 132, 112, 82, 62, 42, 22, 17, 12, 7, 2] kW
2. TOP10: [182, 152, 132, 112, 82, 62, 42, 22, 17, 12] kW
3. Suma TOP10: 815 kW
4. Kara za styczeń: 40 × 815 = 32 600 zł

Jeśli podobne przekroczenia w innych miesiącach:
Kara roczna ≈ 32 600 × 12 = 391 200 zł/rok
```

### Typowe wartości C_ss (2024)

| OSD | Grupa taryfowa | C_ss [zł/kW/mies.] |
|-----|----------------|-------------------|
| TAURON Dystrybucja | B21 | ~35-40 |
| TAURON Dystrybucja | C21 | ~40-45 |
| PGE Dystrybucja | B21 | ~30-35 |
| PGE Dystrybucja | C21 | ~35-40 |
| ENEA Operator | B21 | ~32-38 |
| ENEA Operator | C21 | ~38-42 |
| Energa Operator | B21 | ~33-38 |
| Energa Operator | C21 | ~38-43 |

**Uwaga:** Wartości orientacyjne. Aktualne stawki należy sprawdzić w obowiązującej taryfie OSD.

---

## Dobór wielkości magazynu BESS

### Cel

Magazyn BESS musi być zdolny do:
1. **Pokrycia energii** - zgromadzić wystarczającą ilość energii do ścięcia wszystkich szczytów
2. **Dostarczenia mocy** - rozładować się z wystarczającą mocą by pokryć nadwyżkę

### Grupowanie zdarzeń w bloki

Pojedyncze zdarzenia przekroczenia są grupowane w ciągłe bloki czasowe:

```javascript
// Blok = ciągłe zdarzenia przekroczenia (z tolerancją 1.5 × interwał)
{
  startTime: "2024-01-15T13:00:00",
  endTime: "2024-01-15T18:00:00",
  durationHours: 5,
  maxPowerKW: 1150,           // Max moc w bloku
  totalExcessKWh: 450,        // Całkowita energia nadwyżki
  intervalCount: 5            // Liczba interwałów (godzin)
}
```

### Wzory na dobór BESS

#### Pojemność (kWh)

```
E_bess = (E_max_bloku / (DOD × η)) × margines
```

Gdzie:
- **E_max_bloku** - energia największego bloku przekroczenia [kWh]
- **DOD** - Depth of Discharge (głębokość rozładowania) = 0.8 (80%)
- **η** - sprawność round-trip = 0.9 (90%)
- **margines** - współczynnik bezpieczeństwa = 1.2 (20%)

#### Moc (kW)

```
P_bess = max(P_h - P_um) × margines
```

Gdzie:
- **max(P_h - P_um)** - maksymalna nadwyżka mocy ponad próg [kW]
- **margines** = 1.2

**WAŻNE:** Moc BESS to różnica ponad próg, NIE moc absolutna!

#### Przykład

```
Dane:
- Największy blok: E_max = 450 kWh
- Max przekroczenie: 1150 kW - 968 kW = 182 kW
- DOD = 0.8, η = 0.9, margines = 1.2

Obliczenie:
E_bess = (450 / (0.8 × 0.9)) × 1.2 = 450 / 0.72 × 1.2 = 750 kWh
P_bess = 182 × 1.2 = 218 kW

Wymagany BESS: 750 kWh / 218 kW
```

### Liczba cykli rocznie

```
Cykle/rok = suma(energia wszystkich bloków) / (E_bess × DOD)
```

Przykład:
```
Suma energii bloków: 3310 kWh/rok
E_bess = 750 kWh, DOD = 0.8

Cykle/rok = 3310 / (750 × 0.8) = 5.5 cykli/rok
```

---

## Analiza ekonomiczna

### Koszt BESS

#### CAPEX (koszt inwestycji)

```
CAPEX = E_bess × cena_kWh + P_bess × cena_kW
```

Przyjęte wartości (2024):
- **cena_kWh** = 1500 PLN/kWh
- **cena_kW** = 500 PLN/kW

Przykład:
```
CAPEX = 750 × 1500 + 218 × 500 = 1 125 000 + 109 000 = 1 234 000 PLN
```

#### OPEX (koszty operacyjne)

```
OPEX_roczny = CAPEX × 1.5%
```

Przykład:
```
OPEX = 1 234 000 × 0.015 = 18 510 PLN/rok
```

#### Całkowity koszt BESS przez N lat

```
Koszt_BESS_Nlat = CAPEX + (OPEX_roczny × N)
```

Przykład (15 lat):
```
Koszt_BESS_15lat = 1 234 000 + (18 510 × 15) = 1 234 000 + 277 650 = 1 511 650 PLN
```

### Koszt kar przez N lat

```
Koszt_kar_Nlat = Kara_roczna × N
```

Przykład:
```
Kara_roczna = 391 200 PLN
Koszt_kar_15lat = 391 200 × 15 = 5 868 000 PLN
```

### Porównanie i decyzja

```
Jeśli Koszt_BESS_Nlat < Koszt_kar_Nlat:
    → BESS się opłaca
    → Oszczędność = Koszt_kar_Nlat - Koszt_BESS_Nlat

Jeśli Koszt_kar_Nlat < Koszt_BESS_Nlat:
    → Lepiej płacić kary
    → Nie inwestować w BESS
```

---

## Prezentacja wyników

### Tabela porównawcza

| Kolumna | Jednostka | Opis |
|---------|-----------|------|
| **PXX** | - | Poziom percentyla (P99.5, P99, ...) |
| **P_um** | kW | Moc umowna (próg) dla tego poziomu |
| **Godz.** | h/rok | Liczba godzin przekroczenia |
| **Pojemność** | kWh | Wymagana pojemność BESS |
| **Moc** | kW | Wymagana moc BESS (nadwyżka × margines) |
| **Cykle** | /rok | Szacowana liczba cykli rocznie |
| **CAPEX BESS** | tys. PLN | Koszt inwestycji w BESS |
| **Kara/rok** | PLN | Roczna kara wg wzoru TOP10 |
| **BESS 15lat** | tys. PLN | Całkowity koszt BESS przez 15 lat |
| **Kara 15lat** | tys. PLN | Całkowity koszt kar przez 15 lat |

### Kolorowanie

- **Zielony** w kolumnie "BESS 15lat" = BESS jest tańszy
- **Zielony** w kolumnie "Kara 15lat" = Kara jest tańsza
- **Czerwony** = droższa opcja

### Rekomendowany poziom

Poziom oznaczony ✅ to rekomendowany poziom PXX wybrany na podstawie analizy opłacalności peak shavingu (rating "bardzo opłacalne" lub "opłacalne").

---

## Parametry i założenia

### Parametry BESS

| Parametr | Wartość | Opis |
|----------|---------|------|
| CAPEX kWh | 1500 PLN/kWh | Koszt pojemności magazynu |
| CAPEX kW | 500 PLN/kW | Koszt mocy magazynu |
| OPEX | 1.5%/rok | Koszty operacyjne jako % CAPEX |
| DOD | 80% | Głębokość rozładowania |
| Sprawność | 90% | Sprawność round-trip |
| Margines | 20% | Współczynnik bezpieczeństwa |
| Żywotność | 15 lat | Horyzont analizy |

### Parametry kary

| Parametr | Wartość | Opis |
|----------|---------|------|
| C_ss | 40 zł/kW/mies. | Składnik stały stawki sieciowej |
| TOP N | 10 | Liczba największych nadwyżek w miesiącu |

### Ograniczenia modelu

1. **Uproszczenie kary** - model zakłada stałą stawkę C_ss; rzeczywista stawka zależy od OSD i grupy taryfowej
2. **Brak inflacji** - ceny BESS i kar przyjęte jako stałe przez 15 lat
3. **Brak degradacji** - nie uwzględniono spadku pojemności BESS w czasie
4. **Dane roczne** - analiza oparta na 1 roku danych; wzorce mogą się zmieniać
5. **Uproszczony CAPEX** - nie uwzględnia kosztów instalacji, przyłącza, systemu BMS

---

## Przykład kompletnej analizy

### Dane wejściowe

```
Obiekt: Zakład produkcyjny
Dane: 8760 godzin (rok 2024)
Moc szczytowa: 1245 kW
Interwał: godzinowy
```

### Wyniki dla P99.5

```
P_um = 968 kW
Godziny przekroczenia: 42 h/rok
Energia do ścięcia: 3310 kWh/rok

BESS:
- Pojemność: 750 kWh
- Moc: 218 kW
- Cykle/rok: 5.5
- CAPEX: 1 234 000 PLN
- OPEX: 18 510 PLN/rok
- Koszt 15 lat: 1 512 tys. PLN

Kara:
- Suma TOP10 (średnio): 815 kW/mies.
- Kara/mies.: 32 600 PLN
- Kara/rok: 391 200 PLN
- Koszt 15 lat: 5 868 tys. PLN

Decyzja: BESS się opłaca
Oszczędność 15 lat: 4 356 tys. PLN
```

### Podsumowanie dla wszystkich poziomów

| PXX | P_um | BESS 15lat | Kara 15lat | Decyzja |
|-----|------|------------|------------|---------|
| P99.5 | 968 kW | 1 512 tys. | 5 868 tys. | BESS |
| P99 | 932 kW | 2 100 tys. | 4 200 tys. | BESS |
| P98 | 900 kW | 2 800 tys. | 3 100 tys. | BESS |
| P97 | 882 kW | 3 200 tys. | 2 400 tys. | KARA |
| P95 | 862 kW | 3 800 tys. | 1 800 tys. | KARA |

**Wniosek:** Dla tego obiektu optymalny jest poziom P98 - BESS pokrywający przekroczenia do tego poziomu, z akceptacją kar za rzadsze, większe przekroczenia.

---

## Historia zmian

| Data | Wersja | Opis |
|------|--------|------|
| 2026-01-08 | 1.0 | Pierwsza wersja dokumentacji |

---

## Kontakt

W przypadku pytań dotyczących metodologii lub parametrów, skontaktuj się z zespołem analitycznym.
