# PEŁNA DOKUMENTACJA ALGORYTMU: Peak Shaving BESS vs Kara

## Wersja: 1.0 | Data: 2026-01-08

---

# CZĘŚĆ 1: DANE WEJŚCIOWE

## 1.1 Źródło danych

Dane pochodzą z analizy zużycia energii elektrycznej (moduł ZUŻYCIE).

```
Plik źródłowy: consumption.js
Zmienna globalna: peakShavingExportData
Funkcja generująca: analyzePeakShaving(data, intervalMinutes)
```

## 1.2 Format danych wejściowych

### Dane surowe (z pliku CSV/Excel)

```javascript
// Tablica obiektów z timestampem i wartością mocy
rawData = [
  { timestamp: "2024-01-01T00:00:00", value: 850 },   // kW
  { timestamp: "2024-01-01T01:00:00", value: 920 },   // kW
  { timestamp: "2024-01-01T02:00:00", value: 780 },   // kW
  // ... 8760 rekordów dla danych godzinowych
  // ... 35040 rekordów dla danych 15-minutowych
]
```

### Parametr interwału

```javascript
intervalMinutes = 60   // dane godzinowe
// lub
intervalMinutes = 15   // dane kwadransowe (15-minutowe)
```

## 1.3 Struktura peakShavingExportData

Po analizie `analyzePeakShaving()` powstaje obiekt:

```javascript
peakShavingExportData = {
  // Metadane
  intervalMinutes: 60,                    // Interwał danych [min]
  resolutionInfo: "godzinowa",           // Opis rozdzielczości

  // Progi mocy (do wykresu)
  thresholds: [
    { label: "P100", powerKW: 1245, color: "#e74c3c" },
    { label: "P99.5", powerKW: 968, color: "#e67e22" },
    { label: "P99", powerKW: 932, color: "#f1c40f" },
    { label: "P98", powerKW: 900, color: "#2ecc71" }
  ],

  // Pełna tabela wszystkich poziomów
  tableRows: [
    {
      name: "P100 (Szczyt)",
      percentile: 100,
      powerKW: 1245,                      // Moc na tym percentylu
      hoursAbove: 0,                      // Godziny powyżej (dla P100 = 0)
      exactHours: 0,
      energyToShave: 0,                   // Energia do ścięcia [kWh]
      peakReductionPct: 0,                // % redukcji szczytu
      rating: "Możliwe",
      ratingCode: "mozliwe",
      exceedanceEvents: []                // Zdarzenia przekroczenia
    },
    {
      name: "P99.5",
      percentile: 99.5,
      powerKW: 968,
      hoursAbove: 42,                     // ~43.8 godz. (0.5% z 8760)
      exactHours: 43.8,
      energyToShave: 3310,                // kWh do ścięcia rocznie
      peakReductionPct: -22.3,            // Redukcja mocy o 22.3%
      rating: "Bardzo opłacalne",
      ratingCode: "bardzo_oplacalne",
      exceedanceEvents: [
        {
          timestamp: "2024-01-15T14:00:00",
          value: 1150,                    // Moc w tej godzinie [kW]
          originalIndex: 1234             // Indeks w oryginalnych danych
        },
        {
          timestamp: "2024-01-15T15:00:00",
          value: 1120,
          originalIndex: 1235
        },
        // ... wszystkie godziny gdzie moc > 968 kW
      ]
    },
    // ... kolejne poziomy: P99, P98, P97, P95
  ],

  // Rekomendowany poziom (pierwszy "bardzo_oplacalne" lub "oplacalne")
  recommended: { /* obiekt jak w tableRows */ },

  // Poziomy do eksportu (bardzo_oplacalne + oplacalne + mozliwe)
  exportableLevels: [ /* tablica obiektów jak w tableRows */ ],

  // Wstępna rekomendacja BESS
  bessRecommendation: {
    capacityKWh: 750,
    powerKW: 280,
    annualCycles: 5.5,
    largestBlockKWh: 450,
    largestBlockHours: 5
  }
}
```

---

# CZĘŚĆ 2: ALGORYTM ANALIZY PEAK SHAVING

## 2.1 Funkcja analyzePeakShaving()

Lokalizacja: `consumption.js`, linia ~700

### Krok 1: Sortowanie danych

```javascript
// Sortuj dane malejąco po mocy (krzywa uporządkowana obciążenia)
const sortedData = [...rawData].sort((a, b) => b.value - a.value);

// Wynik: [1245, 1220, 1200, 1180, ..., 450, 420, 380] kW
```

### Krok 2: Definicja poziomów PXX

```javascript
const thresholdConfigs = [
  { name: 'P100 (Szczyt)', percentile: 100, color: '#e74c3c' },
  { name: 'P99.5', percentile: 99.5, color: '#e67e22' },
  { name: 'P99', percentile: 99, color: '#f1c40f' },
  { name: 'P98', percentile: 98, color: '#2ecc71' },
  { name: 'P97', percentile: 97, color: '#3498db' },
  { name: 'P95', percentile: 95, color: '#9b59b6' }
];
```

### Krok 3: Obliczenie progu mocy dla każdego PXX

```javascript
for (config of thresholdConfigs) {
  // Indeks w posortowanej tablicy
  // Dla P99.5: index = (100 - 99.5) / 100 * 8760 = 43.8 → 44
  const index = Math.floor((100 - config.percentile) / 100 * sortedData.length);

  // Moc na tym indeksie = próg
  const powerAtPercentile = sortedData[index].value;  // np. 968 kW dla P99.5
}
```

### Krok 4: Zliczenie godzin i energii powyżej progu

```javascript
// Dla każdego progu (np. P99.5 = 968 kW)
let hoursAbove = 0;
let energyToShave = 0;
const exceedanceEvents = [];

for (dataPoint of rawData) {
  if (dataPoint.value > threshold) {
    hoursAbove += intervalMinutes / 60;  // 1 dla godzinowych, 0.25 dla 15-min

    // Energia nadwyżki = (moc - próg) × czas
    const excessPower = dataPoint.value - threshold;
    const excessEnergy = excessPower * (intervalMinutes / 60);  // kWh
    energyToShave += excessEnergy;

    // Zapisz zdarzenie
    exceedanceEvents.push({
      timestamp: dataPoint.timestamp,
      value: dataPoint.value,
      originalIndex: dataPoint.index
    });
  }
}

// Przykład dla P99.5:
// hoursAbove = 42 godziny
// energyToShave = 3310 kWh
// exceedanceEvents = [42 obiekty]
```

### Krok 5: Ocena opłacalności (rating)

```javascript
function getRating(hoursAbove, energyToShave, peakReductionPct) {
  if (hoursAbove <= 50 && peakReductionPct >= 20) {
    return { rating: "Bardzo opłacalne", code: "bardzo_oplacalne" };
  }
  if (hoursAbove <= 100 && peakReductionPct >= 15) {
    return { rating: "Opłacalne", code: "oplacalne" };
  }
  if (hoursAbove <= 500 && peakReductionPct >= 10) {
    return { rating: "Możliwe", code: "mozliwe" };
  }
  return { rating: "Nieopłacalne", code: "nieoplacalne" };
}
```

---

# CZĘŚĆ 3: GRUPOWANIE ZDARZEŃ W BLOKI

## 3.1 Cel grupowania

Pojedyncze godziny przekroczenia nie mają sensu dla BESS - magazyn musi pokryć **ciągłe bloki** przekroczeń. Np. 5 kolejnych godzin przekroczenia = 1 blok.

## 3.2 Funkcja groupConsecutiveEvents()

Lokalizacja: `consumption.js`, linia ~1130

```javascript
function groupConsecutiveEvents(events, intervalMinutes = 60) {
  if (!events || events.length === 0) return [];

  const intervalMs = intervalMinutes * 60 * 1000;  // Interwał w ms
  const hoursPerInterval = intervalMinutes / 60;   // 0.25 dla 15-min, 1.0 dla godz.
  const toleranceMs = intervalMs * 1.5;            // Tolerancja na przerwy (1.5x)

  // Sortuj zdarzenia chronologicznie
  const sortedEvents = [...events].sort((a, b) =>
    new Date(a.timestamp) - new Date(b.timestamp)
  );

  const blocks = [];
  let currentBlock = null;

  for (const event of sortedEvents) {
    const eventTime = new Date(event.timestamp).getTime();
    const eventPower = event.value || event.power || 0;

    if (!currentBlock) {
      // Rozpocznij nowy blok
      currentBlock = {
        startTime: event.timestamp,
        endTime: event.timestamp,
        maxPowerKW: eventPower,
        intervalCount: 1,
        events: [event]
      };
    } else {
      const lastEventTime = new Date(currentBlock.endTime).getTime();
      const gap = eventTime - lastEventTime;

      if (gap <= toleranceMs) {
        // Kontynuuj blok
        currentBlock.endTime = event.timestamp;
        currentBlock.maxPowerKW = Math.max(currentBlock.maxPowerKW, eventPower);
        currentBlock.intervalCount++;
        currentBlock.events.push(event);
      } else {
        // Zamknij bieżący blok, rozpocznij nowy
        blocks.push(finalizeBlock(currentBlock, hoursPerInterval, threshold));
        currentBlock = {
          startTime: event.timestamp,
          endTime: event.timestamp,
          maxPowerKW: eventPower,
          intervalCount: 1,
          events: [event]
        };
      }
    }
  }

  // Dodaj ostatni blok
  if (currentBlock) {
    blocks.push(finalizeBlock(currentBlock, hoursPerInterval, threshold));
  }

  return blocks;
}
```

## 3.3 Finalizacja bloku

```javascript
function finalizeBlock(block, hoursPerInterval, threshold) {
  // Czas trwania bloku
  block.durationHours = block.intervalCount * hoursPerInterval;

  // Energia nadwyżki w bloku
  block.totalExcessKWh = block.events.reduce((sum, e) => {
    const power = e.value || e.power || 0;
    const excess = Math.max(0, power - threshold);
    return sum + excess * hoursPerInterval;
  }, 0);

  return block;
}
```

## 3.4 Przykład grupowania

```
Dane wejściowe (P99.5 = 968 kW):
- 14:00 → 1150 kW (nadwyżka 182 kW)
- 15:00 → 1120 kW (nadwyżka 152 kW)
- 16:00 → 1080 kW (nadwyżka 112 kW)
- 17:00 → 1050 kW (nadwyżka 82 kW)
- 18:00 → 990 kW (nadwyżka 22 kW)
[przerwa 3 godziny]
- 22:00 → 1020 kW (nadwyżka 52 kW)

Wynik grupowania:
Blok 1: {
  startTime: "14:00",
  endTime: "18:00",
  durationHours: 5,
  maxPowerKW: 1150,
  totalExcessKWh: 182 + 152 + 112 + 82 + 22 = 550 kWh,
  intervalCount: 5
}

Blok 2: {
  startTime: "22:00",
  endTime: "22:00",
  durationHours: 1,
  maxPowerKW: 1020,
  totalExcessKWh: 52 kWh,
  intervalCount: 1
}
```

---

# CZĘŚĆ 4: OBLICZENIE KARY ZA PRZEKROCZENIE MOCY

## 4.1 Podstawa prawna

Kara za przekroczenie mocy umownej jest naliczana zgodnie z taryfą OSD (Operatora Systemu Dystrybucyjnego).

**Wzór taryfowy:**
```
Opłata = C_ss × S

gdzie S = suma 10 największych nadwyżek mocy ponad moc umowną w okresie rozliczeniowym (miesiąc)
```

## 4.2 Parametry

```javascript
// Składnik stały stawki sieciowej [zł/kW/mies.]
const C_ss = 40;

// Typowe wartości C_ss (2024):
// TAURON B21: 35-40 zł/kW/mies.
// TAURON C21: 40-45 zł/kW/mies.
// PGE B21: 30-35 zł/kW/mies.
// PGE C21: 35-40 zł/kW/mies.
// ENEA B21: 32-38 zł/kW/mies.
// ENEA C21: 38-42 zł/kW/mies.
```

## 4.3 Algorytm obliczenia kary

Lokalizacja: `consumption.js`, funkcja `buildBessVsPenaltyAnalysis()`, linia ~2207

```javascript
// ==========================================
// ALGORYTM OBLICZENIA KARY WG POLSKIEJ TARYFY
// ==========================================

// WEJŚCIE:
// - events: tablica zdarzeń przekroczenia [{timestamp, value}, ...]
// - P_um: moc umowna (próg dla danego PXX) [kW]
// - C_ss: składnik stały stawki sieciowej [zł/kW/mies.]

// KROK 1: Oblicz nadwyżkę dla każdego zdarzenia
const hourlyExcesses = events.map(e => ({
  timestamp: e.timestamp,
  powerKw: e.value,
  excessKw: Math.max(0, e.value - P_um)  // nadwyżka = moc - próg
})).filter(e => e.excessKw > 0);  // tylko dodatnie nadwyżki

// Przykład:
// e.value = 1150 kW, P_um = 968 kW
// excessKw = max(0, 1150 - 968) = 182 kW
```

```javascript
// KROK 2: Grupuj nadwyżki po miesiącach
const monthlyData = {};

hourlyExcesses.forEach(e => {
  const d = new Date(e.timestamp);
  // Klucz: "2024-01", "2024-02", etc.
  const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;

  if (!monthlyData[key]) {
    monthlyData[key] = [];
  }
  monthlyData[key].push(e.excessKw);
});

// Przykład wyniku:
// monthlyData = {
//   "2024-01": [182, 152, 112, 82, 22, 52, 45, 38, 30, 25, 20, 15],
//   "2024-02": [95, 75, 60, 45, 30],
//   "2024-07": [200, 180, 160, 140, 120, 100, 80, 60, 40, 20, 15, 10, 5],
//   ...
// }
```

```javascript
// KROK 3: Dla każdego miesiąca oblicz karę
let annualPenalty = 0;      // Suma kar rocznych
let totalTop10Sum = 0;       // Suma wszystkich TOP10

Object.entries(monthlyData).forEach(([month, excesses]) => {
  // 3a. Sortuj nadwyżki malejąco
  const sorted = [...excesses].sort((a, b) => b - a);

  // Przykład dla "2024-01":
  // sorted = [182, 152, 112, 82, 52, 45, 38, 30, 25, 22, 20, 15]

  // 3b. Weź TOP10 (lub mniej jeśli nie ma 10)
  const top10 = sorted.slice(0, 10);

  // Przykład:
  // top10 = [182, 152, 112, 82, 52, 45, 38, 30, 25, 22]

  // 3c. Zsumuj TOP10
  const sumTop10 = top10.reduce((s, v) => s + v, 0);

  // Przykład:
  // sumTop10 = 182 + 152 + 112 + 82 + 52 + 45 + 38 + 30 + 25 + 22 = 740 kW

  // 3d. Oblicz karę za miesiąc
  const monthlyPenalty = C_ss * sumTop10;

  // Przykład:
  // monthlyPenalty = 40 × 740 = 29 600 zł

  // 3e. Dodaj do sumy rocznej
  annualPenalty += monthlyPenalty;
  totalTop10Sum += sumTop10;
});

// WYNIK:
// annualPenalty = suma kar ze wszystkich miesięcy [zł/rok]
// totalTop10Sum = suma wszystkich TOP10 nadwyżek [kW]
```

## 4.4 Pełny przykład obliczenia kary

```
DANE:
- Poziom: P99.5
- P_um (moc umowna): 968 kW
- C_ss: 40 zł/kW/mies.
- Rok: 2024

ZDARZENIA PRZEKROCZENIA (fragment):

Styczeń 2024:
  15.01 14:00 → 1150 kW → nadwyżka: 182 kW
  15.01 15:00 → 1120 kW → nadwyżka: 152 kW
  15.01 16:00 → 1080 kW → nadwyżka: 112 kW
  15.01 17:00 → 1050 kW → nadwyżka: 82 kW
  15.01 18:00 → 990 kW → nadwyżka: 22 kW
  20.01 10:00 → 1020 kW → nadwyżka: 52 kW
  20.01 11:00 → 1010 kW → nadwyżka: 42 kW
  25.01 14:00 → 995 kW → nadwyżka: 27 kW

  Wszystkie nadwyżki: [182, 152, 112, 82, 22, 52, 42, 27]
  Posortowane malejąco: [182, 152, 112, 82, 52, 42, 27, 22]
  TOP10 (mamy tylko 8): [182, 152, 112, 82, 52, 42, 27, 22]
  Suma TOP10: 671 kW

  KARA ZA STYCZEŃ = 40 × 671 = 26 840 zł

Lipiec 2024 (gorący miesiąc, więcej przekroczeń):
  05.07 13:00 → 1200 kW → nadwyżka: 232 kW
  05.07 14:00 → 1180 kW → nadwyżka: 212 kW
  05.07 15:00 → 1150 kW → nadwyżka: 182 kW
  05.07 16:00 → 1120 kW → nadwyżka: 152 kW
  05.07 17:00 → 1080 kW → nadwyżka: 112 kW
  06.07 13:00 → 1100 kW → nadwyżka: 132 kW
  06.07 14:00 → 1090 kW → nadwyżka: 122 kW
  06.07 15:00 → 1050 kW → nadwyżka: 82 kW
  10.07 14:00 → 1030 kW → nadwyżka: 62 kW
  10.07 15:00 → 1010 kW → nadwyżka: 42 kW
  15.07 14:00 → 995 kW → nadwyżka: 27 kW
  15.07 15:00 → 985 kW → nadwyżka: 17 kW

  Wszystkie nadwyżki: [232, 212, 182, 152, 112, 132, 122, 82, 62, 42, 27, 17]
  Posortowane malejąco: [232, 212, 182, 152, 132, 122, 112, 82, 62, 42, 27, 17]
  TOP10: [232, 212, 182, 152, 132, 122, 112, 82, 62, 42]
  Suma TOP10: 1330 kW

  KARA ZA LIPIEC = 40 × 1330 = 53 200 zł

SUMA ROCZNA (przykład):
  Styczeń:   26 840 zł
  Luty:       8 500 zł
  Marzec:     5 200 zł
  Kwiecień:   3 800 zł
  Maj:       12 400 zł
  Czerwiec:  28 600 zł
  Lipiec:    53 200 zł
  Sierpień:  45 800 zł
  Wrzesień:  18 200 zł
  Październik: 6 400 zł
  Listopad:   4 200 zł
  Grudzień:  15 600 zł
  ─────────────────────
  RAZEM:    228 940 zł/rok

KARA ZA 15 LAT = 228 940 × 15 = 3 434 100 zł
```

---

# CZĘŚĆ 5: DOBÓR WIELKOŚCI MAGAZYNU BESS

## 5.1 Cel

Magazyn BESS musi:
1. Pomieścić wystarczająco dużo energii by ściąć największy blok przekroczenia
2. Mieć wystarczającą moc by pokryć maksymalną nadwyżkę

## 5.2 Parametry BESS

```javascript
const capexPerKwh = 1500;    // PLN/kWh - koszt pojemności
const capexPerKw = 500;      // PLN/kW - koszt mocy (inwerter)
const opexPct = 0.015;       // 1.5% CAPEX rocznie - koszty operacyjne
const dod = 0.8;             // 80% - głębokość rozładowania (Depth of Discharge)
const efficiency = 0.9;      // 90% - sprawność round-trip
const safetyMargin = 1.2;    // 20% - margines bezpieczeństwa
const lifetimeYears = 15;    // Horyzont analizy
```

## 5.3 Algorytm doboru BESS dla każdego PXX

Lokalizacja: `consumption.js`, funkcja `buildBessVsPenaltyAnalysis()`, linia ~2245

```javascript
// Dla każdego poziomu PXX (P99.5, P99, P98, P97, P95)
analysis.exportableLevels.forEach(level => {

  // ==========================================
  // KROK 1: Pobierz dane dla tego poziomu
  // ==========================================
  const P_um = level.powerKW;           // Próg mocy (moc umowna)
  const pxxLabel = level.name;           // np. "P99.5"
  const events = level.exceedanceEvents; // Zdarzenia przekroczenia

  // ==========================================
  // KROK 2: Grupuj zdarzenia w bloki
  // ==========================================
  const blocks = groupConsecutiveEvents(events, intervalMin);

  // Przykład wyniku:
  // blocks = [
  //   { durationHours: 5, maxPowerKW: 1150, totalExcessKWh: 550 },
  //   { durationHours: 1, maxPowerKW: 1020, totalExcessKWh: 52 },
  //   { durationHours: 8, maxPowerKW: 1200, totalExcessKWh: 920 },
  //   ...
  // ]

  // ==========================================
  // KROK 3: Oblicz nadwyżkę mocy dla każdego bloku
  // ==========================================
  const blocksWithExcess = blocks.map(b => ({
    ...b,
    // Nadwyżka = moc szczytowa bloku - próg (P_um)
    excessPowerKw: Math.max(0, b.maxPowerKW - P_um)
  }));

  // Przykład dla P99.5 (P_um = 968 kW):
  // blocksWithExcess = [
  //   { ..., maxPowerKW: 1150, excessPowerKw: 182 },  // 1150 - 968 = 182
  //   { ..., maxPowerKW: 1020, excessPowerKw: 52 },   // 1020 - 968 = 52
  //   { ..., maxPowerKW: 1200, excessPowerKw: 232 },  // 1200 - 968 = 232
  // ]

  // ==========================================
  // KROK 4: Znajdź największy blok (po energii)
  // ==========================================
  const sortedBlocks = [...blocksWithExcess].sort(
    (a, b) => b.totalExcessKWh - a.totalExcessKWh
  );
  const largestBlock = sortedBlocks[0];

  // Przykład:
  // largestBlock = { totalExcessKWh: 920, maxPowerKW: 1200, excessPowerKw: 232 }

  // ==========================================
  // KROK 5: Oblicz wymaganą POJEMNOŚĆ BESS
  // ==========================================
  // Wzór: E_bess = (E_max / (DOD × η)) × margines
  //
  // Gdzie:
  // E_max = energia największego bloku [kWh]
  // DOD = głębokość rozładowania (0.8)
  // η = sprawność (0.9)
  // margines = współczynnik bezpieczeństwa (1.2)

  const bessCapacityKwh = (largestBlock.totalExcessKWh / (dod * efficiency)) * safetyMargin;

  // Przykład:
  // bessCapacityKwh = (920 / (0.8 × 0.9)) × 1.2
  //                 = (920 / 0.72) × 1.2
  //                 = 1277.78 × 1.2
  //                 = 1533 kWh

  // ==========================================
  // KROK 6: Oblicz wymaganą MOC BESS
  // ==========================================
  // Wzór: P_bess = max(nadwyżka mocy) × margines
  //
  // WAŻNE: Bierzemy NADWYŻKĘ (moc - próg), NIE moc absolutną!

  const maxExcessPowerKw = Math.max(...blocksWithExcess.map(b => b.excessPowerKw));
  const bessPowerKw = maxExcessPowerKw * safetyMargin;

  // Przykład:
  // maxExcessPowerKw = max(182, 52, 232, ...) = 232 kW
  // bessPowerKw = 232 × 1.2 = 278 kW

  // ==========================================
  // KROK 7: Oblicz liczbę cykli rocznie
  // ==========================================
  // Wzór: Cykle = suma(energia wszystkich bloków) / (pojemność × DOD)

  const totalAnnualEnergyKwh = blocks.reduce(
    (sum, b) => sum + b.totalExcessKWh, 0
  );
  const usableCapacity = bessCapacityKwh * dod;
  const annualCycles = totalAnnualEnergyKwh / usableCapacity;

  // Przykład:
  // totalAnnualEnergyKwh = 550 + 52 + 920 + ... = 3310 kWh
  // usableCapacity = 1533 × 0.8 = 1226 kWh
  // annualCycles = 3310 / 1226 = 2.7 cykli/rok

  // ==========================================
  // KROK 8: Oblicz CAPEX
  // ==========================================
  const capex = bessCapacityKwh * capexPerKwh + bessPowerKw * capexPerKw;

  // Przykład:
  // capex = 1533 × 1500 + 278 × 500
  //       = 2 299 500 + 139 000
  //       = 2 438 500 PLN

  // ==========================================
  // KROK 9: Oblicz OPEX roczny
  // ==========================================
  const annualOpex = capex * opexPct;

  // Przykład:
  // annualOpex = 2 438 500 × 0.015 = 36 578 PLN/rok

  // ==========================================
  // KROK 10: Oblicz całkowity koszt BESS przez N lat
  // ==========================================
  const totalCost15y = capex + (annualOpex * lifetimeYears);

  // Przykład:
  // totalCost15y = 2 438 500 + (36 578 × 15)
  //              = 2 438 500 + 548 670
  //              = 2 987 170 PLN
});
```

## 5.4 Pełny przykład doboru BESS dla P99.5

```
DANE WEJŚCIOWE:
- Poziom: P99.5
- P_um (próg): 968 kW
- Liczba zdarzeń: 42 godziny
- Energia do ścięcia: 3310 kWh/rok

BLOKI PRZEKROCZEŃ (po grupowaniu):
┌────┬─────────────────────┬──────────┬───────────┬─────────────┬────────────┐
│ Nr │ Okres               │ Czas [h] │ Max [kW]  │ Nadwyżka[kW]│ Energia[kWh]│
├────┼─────────────────────┼──────────┼───────────┼─────────────┼────────────┤
│ 1  │ 15.01 14:00-18:00   │ 5        │ 1150      │ 182         │ 550        │
│ 2  │ 20.01 10:00-11:00   │ 2        │ 1020      │ 52          │ 94         │
│ 3  │ 05.07 13:00-17:00   │ 5        │ 1200      │ 232         │ 690        │
│ 4  │ 06.07 13:00-15:00   │ 3        │ 1100      │ 132         │ 336        │
│ 5  │ 10.07 14:00-15:00   │ 2        │ 1030      │ 62          │ 104        │
│ ... │ ...                │ ...      │ ...       │ ...         │ ...        │
└────┴─────────────────────┴──────────┴───────────┴─────────────┴────────────┘

NAJWIĘKSZY BLOK: Nr 3 (05.07)
- Energia: 690 kWh
- Max nadwyżka: 232 kW

OBLICZENIA:

1. POJEMNOŚĆ BESS:
   E_bess = (690 / (0.8 × 0.9)) × 1.2
          = (690 / 0.72) × 1.2
          = 958.3 × 1.2
          = 1150 kWh

2. MOC BESS:
   P_bess = 232 × 1.2 = 278 kW

3. CYKLE ROCZNE:
   Suma energii = 550 + 94 + 690 + 336 + 104 + ... = 3310 kWh
   Pojemność użytkowa = 1150 × 0.8 = 920 kWh
   Cykle = 3310 / 920 = 3.6 cykli/rok

4. CAPEX:
   CAPEX = 1150 × 1500 + 278 × 500
        = 1 725 000 + 139 000
        = 1 864 000 PLN

5. OPEX:
   OPEX = 1 864 000 × 0.015 = 27 960 PLN/rok

6. KOSZT 15 LAT:
   Koszt = 1 864 000 + (27 960 × 15)
        = 1 864 000 + 419 400
        = 2 283 400 PLN

WYMAGANY BESS DLA P99.5:
┌─────────────────┬─────────────┐
│ Parametr        │ Wartość     │
├─────────────────┼─────────────┤
│ Pojemność       │ 1 150 kWh   │
│ Moc             │ 278 kW      │
│ Cykle/rok       │ 3.6         │
│ CAPEX           │ 1 864 tys.  │
│ Koszt 15 lat    │ 2 283 tys.  │
└─────────────────┴─────────────┘
```

---

# CZĘŚĆ 6: PORÓWNANIE BESS vs KARA

## 6.1 Logika porównania

```javascript
// Dla każdego poziomu PXX mamy:
// - totalCost15y: całkowity koszt BESS przez 15 lat
// - totalPenaltyCost15y: całkowity koszt kar przez 15 lat

const totalPenaltyCost15y = annualPenalty * lifetimeYears;

// Decyzja:
if (totalCost15y < totalPenaltyCost15y) {
  // BESS jest tańszy → opłaca się inwestować
  decision = "BESS";
  savings = totalPenaltyCost15y - totalCost15y;
} else {
  // Kara jest tańsza → lepiej płacić karę
  decision = "KARA";
  savings = totalCost15y - totalPenaltyCost15y;
}
```

## 6.2 Przykład porównania dla wszystkich PXX

```
┌────────┬────────┬────────┬──────────┬────────┬────────┬───────────┬───────────┬───────────┬───────────┬──────────┐
│ PXX    │ P_um   │ Godz.  │ Pojemność│ Moc    │ Cykle  │ CAPEX     │ Kara/rok  │ BESS 15lat│ Kara 15lat│ Decyzja  │
│        │ [kW]   │ /rok   │ [kWh]    │ [kW]   │ /rok   │ [tys.PLN] │ [PLN]     │ [tys.PLN] │ [tys.PLN] │          │
├────────┼────────┼────────┼──────────┼────────┼────────┼───────────┼───────────┼───────────┼───────────┼──────────┤
│ P99.5  │ 968    │ 42     │ 1 150    │ 278    │ 3.6    │ 1 864     │ 228 940   │ 2 283     │ 3 434     │ ✅ BESS  │
│ P99    │ 932    │ 88     │ 1 580    │ 320    │ 4.2    │ 2 530     │ 185 600   │ 3 099     │ 2 784     │ ❌ KARA  │
│ P98    │ 900    │ 175    │ 2 100    │ 380    │ 5.1    │ 3 340     │ 142 400   │ 4 091     │ 2 136     │ ❌ KARA  │
│ P97    │ 882    │ 263    │ 2 450    │ 420    │ 5.8    │ 3 885     │ 112 800   │ 4 763     │ 1 692     │ ❌ KARA  │
│ P95    │ 862    │ 438    │ 2 900    │ 480    │ 6.5    │ 4 590     │ 78 200    │ 5 629     │ 1 173     │ ❌ KARA  │
└────────┴────────┴────────┴──────────┴────────┴────────┴───────────┴───────────┴───────────┴───────────┴──────────┘

INTERPRETACJA:
- Dla P99.5: BESS (2 283 tys.) < Kara (3 434 tys.) → BESS się opłaca, oszczędność 1 151 tys.
- Dla P99-P95: Kara jest tańsza niż BESS → lepiej płacić karę

OPTYMALNA STRATEGIA:
Zainstalować BESS dobrany dla P99.5 (1150 kWh / 278 kW) i płacić karę za rzadsze przekroczenia.
```

---

# CZĘŚĆ 7: PREZENTACJA WYNIKÓW W UI

## 7.1 Tabela wynikowa

Lokalizacja: `consumption.js`, linia ~2308

```html
<table>
  <thead>
    <tr>
      <th>PXX</th>        <!-- Poziom percentyla -->
      <th>P_um</th>       <!-- Moc umowna [kW] -->
      <th>Godz.</th>      <!-- Godziny przekroczenia /rok -->
      <th>Pojemność</th>  <!-- Wymagana pojemność BESS [kWh] -->
      <th>Moc</th>        <!-- Wymagana moc BESS [kW] -->
      <th>Cykle</th>      <!-- Cykle /rok -->
      <th>CAPEX BESS</th> <!-- Koszt inwestycji [tys. PLN] -->
      <th>Kara/rok</th>   <!-- Roczna kara [PLN] -->
      <th>BESS 15lat</th> <!-- Koszt BESS przez 15 lat [tys. PLN] -->
      <th>Kara 15lat</th> <!-- Koszt kar przez 15 lat [tys. PLN] -->
    </tr>
  </thead>
  <tbody>
    <!-- Wiersz dla każdego PXX -->
  </tbody>
</table>
```

## 7.2 Kolorowanie wyników

```javascript
// BESS jest lepszy gdy jego koszt < koszt kar
const bessBetter = d.totalCost15y < d.totalPenaltyCost15y;

// Kolumna "BESS 15lat"
if (bessBetter) {
  style = "color: #27ae60; font-weight: bold;";  // Zielony = tańszy
} else {
  style = "";  // Domyślny
}

// Kolumna "Kara 15lat"
if (!bessBetter) {
  style = "color: #27ae60; font-weight: bold;";  // Zielony = tańszy
} else {
  style = "color: #e74c3c;";  // Czerwony = droższy
}
```

## 7.3 Legenda i wyjaśnienia

```html
<div class="legend">
  <h4>Wzór na karę (wg taryfy OSD)</h4>
  <code>Kara = C_ss × suma(TOP10 nadwyżek/mies.)</code>
  <ul>
    <li>C_ss = 40 zł/kW/mies. (składnik stały stawki sieciowej)</li>
    <li>TOP10 = 10 największych godzinowych nadwyżek ponad P_um w miesiącu</li>
    <li>Nadwyżka_h = max(P_h - P_um, 0)</li>
  </ul>
</div>

<div class="legend">
  <h4>BESS Sizing</h4>
  <ul>
    <li>Pojemność = E_max_bloku / (DOD × sprawność) × margines</li>
    <li>Moc = max(P_h - P_um) × margines</li>
    <li>Cykle/rok = suma energii bloków / pojemność użytkowa</li>
    <li>DOD=80%, Sprawność=90%, Margines=20%</li>
  </ul>
</div>

<div class="interpretation">
  <h4>Interpretacja</h4>
  <p>Zielony = tańsza opcja przez 15 lat.</p>
  <p>Jeśli BESS 15lat < Kara 15lat → magazyn się opłaca.</p>
  <p>Jeśli kara jest niższa → lepiej płacić karę za przekroczenie.</p>
</div>
```

---

# CZĘŚĆ 8: PARAMETRY KONFIGURACYJNE

## 8.1 Wszystkie parametry w kodzie

```javascript
// Lokalizacja: consumption.js, funkcja buildBessVsPenaltyAnalysis()

// === PARAMETRY BESS ===
const capexPerKwh = 1500;    // [PLN/kWh] Koszt pojemności magazynu
const capexPerKw = 500;      // [PLN/kW] Koszt mocy (inwerter, przyłącze)
const opexPct = 0.015;       // [%] Koszty operacyjne jako % CAPEX rocznie
const dod = 0.8;             // [-] Depth of Discharge (80%)
const efficiency = 0.9;      // [-] Sprawność round-trip (90%)
const safetyMargin = 1.2;    // [-] Margines bezpieczeństwa (20%)
const lifetimeYears = 15;    // [lata] Horyzont analizy ekonomicznej

// === PARAMETRY KARY ===
const C_ss = 40;             // [zł/kW/mies.] Składnik stały stawki sieciowej
```

## 8.2 Typowe zakresy parametrów

| Parametr | Min | Typowy | Max | Jednostka | Uwagi |
|----------|-----|--------|-----|-----------|-------|
| capexPerKwh | 1000 | 1500 | 2500 | PLN/kWh | Zależy od technologii (LFP, NMC) |
| capexPerKw | 300 | 500 | 800 | PLN/kW | Koszt inwertera |
| opexPct | 0.01 | 0.015 | 0.02 | %/rok | Serwis, ubezpieczenie |
| dod | 0.7 | 0.8 | 0.9 | - | Głębsze rozładowanie = krótszy życie |
| efficiency | 0.85 | 0.90 | 0.95 | - | Round-trip |
| safetyMargin | 1.1 | 1.2 | 1.3 | - | Zapas na degradację |
| lifetimeYears | 10 | 15 | 20 | lata | Gwarancja producenta |
| C_ss | 30 | 40 | 50 | zł/kW/mies. | Zależy od OSD i taryfy |

---

# CZĘŚĆ 9: OGRANICZENIA I ZAŁOŻENIA MODELU

## 9.1 Uproszczenia

1. **Stała stawka C_ss** - w rzeczywistości różni się między OSD i grupami taryfowymi
2. **Brak inflacji** - ceny przyjęte jako stałe przez 15 lat
3. **Brak degradacji BESS** - nie uwzględniono spadku pojemności w czasie (~2-3%/rok)
4. **Dane roczne** - analiza oparta na 1 roku; wzorce mogą się zmieniać
5. **Uproszczony CAPEX** - nie uwzględnia kosztów instalacji, pozwoleń, BMS

## 9.2 Co NIE jest uwzględnione

- Koszty finansowania (odsetki, leasing)
- Wartość rezydualna BESS po 15 latach
- Możliwość arbitrażu cenowego (dodatkowe przychody z BESS)
- Zmiany taryf OSD w czasie
- Dotacje i ulgi podatkowe
- Koszty wymiany baterii po ~10 latach

## 9.3 Rekomendacje

Przed podjęciem decyzji inwestycyjnej:
1. Zweryfikuj aktualną stawkę C_ss u swojego OSD
2. Uzyskaj oferty od dostawców BESS
3. Uwzględnij lokalne warunki (temperatura, dostęp, przyłącze)
4. Rozważ dodatkowe zastosowania BESS (arbitraż, backup)

---

# CZĘŚĆ 10: STRUKTURA KODU

## 10.1 Plik: consumption.js

```
Lokalizacja: services/frontend-consumption/consumption.js

Kluczowe funkcje:

Linia ~700:  analyzePeakShaving(data, intervalMinutes)
             → Analiza krzywej uporządkowanej, obliczenie progów PXX

Linia ~1130: groupConsecutiveEvents(events, intervalMinutes)
             → Grupowanie zdarzeń w ciągłe bloki czasowe

Linia ~2139: buildBessVsPenaltyAnalysis(result)
             → Główna funkcja obliczająca BESS vs Kara dla wszystkich PXX

Zmienne globalne:

Linia ~38:   peakShavingExportData
             → Przechowuje wyniki analizy peak shaving
```

## 10.2 Przepływ danych

```
┌─────────────────┐
│ Dane CSV/Excel  │
│ (timestamp,kW)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ loadConsumption │
│ Data()          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ analyzePeak     │
│ Shaving()       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ peakShaving     │  ← Globalna zmienna z wynikami
│ ExportData      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ buildBessVs     │  ← Wywołane po kliknięciu "Optymalizuj"
│ PenaltyAnalysis │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Tabela HTML     │
│ w UI            │
└─────────────────┘
```

---

# CZĘŚĆ 11: WZORY - PODSUMOWANIE

## Kara za przekroczenie mocy

```
Kara_miesięczna = C_ss × suma(TOP10)

gdzie:
  C_ss = składnik stały stawki sieciowej [zł/kW/mies.]
  TOP10 = 10 największych nadwyżek godzinowych w miesiącu [kW]
  nadwyżka_h = max(P_h - P_um, 0) [kW]

Kara_roczna = suma(Kara_miesięczna dla wszystkich miesięcy)
Kara_15lat = Kara_roczna × 15
```

## Dobór BESS

```
Pojemność [kWh]:
  E_bess = (E_max_bloku / (DOD × η)) × margines

Moc [kW]:
  P_bess = max(P_h - P_um) × margines

Cykle/rok:
  Cykle = suma(E_wszystkich_bloków) / (E_bess × DOD)
```

## Ekonomia BESS

```
CAPEX [PLN]:
  CAPEX = E_bess × cena_kWh + P_bess × cena_kW

OPEX [PLN/rok]:
  OPEX = CAPEX × 0.015

Koszt_15lat [PLN]:
  Koszt = CAPEX + (OPEX × 15)
```

## Decyzja

```
if (Koszt_BESS_15lat < Kara_15lat):
  → Inwestuj w BESS
else:
  → Płać karę
```

---

# KONIEC DOKUMENTACJI

Autor: System ANALIZATOR PV
Wersja: 1.0
Data: 2026-01-08
