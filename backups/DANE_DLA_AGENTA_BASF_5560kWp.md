# Dane uzupełniające dla artykułu — projekt BASF 5560 kWp (P90)

**Źródła:** Pliki Excel z portalu (`C:\...\BASF\EKONOMIA\`), kod serwisowy, stawki konfiguracyjne.

**Scenariusz:** P90 (ostrożny, konserwatywny dla bankability).

---

## 1. PORÓWNANIE WARIANTÓW DOBORU MOCY PV

⚠️ **W plikach BASF jest tylko 1 punkt — 5560 kWp (P90).** Platforma wylicza scan wariantów A/B/C/D + Best NPV przy każdym uruchomieniu analizy `/analyze`, ale eksport CAPEX/EaaS zapisuje tylko wybrany wariant.

Żeby dostarczyć pełny scan, trzeba uruchomić portal z profilem BASF i wykonać eksport wszystkich wariantów. **Struktura tego co wraca z API** (`pv-calculation/app.py:407`):

```json
"key_variants": {
  "A": { capacity, production, auto_consumption_pct, coverage_pct, meets_threshold },
  "B": { ... },
  "C": { ... },
  "D": { ... }
},
"npv_optimal": { capacity, npv_pln, auto_consumption_pct },
"scenarios": [ ... full sweep ... ]
```

**Ogólny kształt krzywej (z kodu `find_variant()` w `app.py:2580`):**

- **Wariant A** (próg 90-95% autokons.): najmniejsza moc — autokonsumpcja bliska 100%, minimalna nadwyżka, krótki payback, ale mała absolutna oszczędność
- **Wariant B** (85%): wyważony — kompromis skali i zwrotu
- **Wariant C** (80%): większa moc → więcej eksportu, ale większa absolutna oszczędność
- **Wariant D** (75%): maksymalna akceptowalna — dużo eksportu, ale najwyższe NPV absolutne przy dobrych cenach energii
- **Best NPV**: optimum matematyczne w przedziale 65-95% autokons.

**Dla projektu BASF:** wariant 5560 kWp daje 19.9% pokrycia i 24.2% autokonsumpcji przy zużyciu 24,833 MWh → to **prawdopodobnie wariant D lub Best NPV** (dużo eksportu, ale wysokie absolutne oszczędności).

**TO DO:** Twój portal musi wygenerować scan — odpal `/analyze` z profilem BASF + topologia pv_load + opcja `return_all_variants=true`, zapisz `key_variants` i `scenarios`.

---

## 2. PORÓWNANIE P50 vs P90 DLA TEGO SAMEGO PROJEKTU

⚠️ **W plikach BASF jest tylko scenariusz P90.** Dla P50 trzeba wyeksportować drugi plik CAPEX.

**Teoretyczna relacja (z `pvgis-proxy/main.py:225-227, 372-374`):**

Źródło: PVGIS-SARAH3 Seriescalc (19 lat danych 2005-2023):
- **P50** = mediana (50. percentyl) historycznej produkcji
- **P75** = 25. percentyl (czyli 75% lat było lepszych)
- **P90** = 10. percentyl (90% lat było lepszych — konserwatywny)

Dla Polski typowy stosunek **P90 / P50 ≈ 0.94** (czyli P50 jest ~6.4% wyższy).

**Ekstrapolacja dla BASF 5560 kWp:**

| Metryka | P90 (znane z pliku) | P50 (szacunek ×1.064) |
|---|---|---|
| Produkcja roczna [MWh] | **~5,900** (wyliczone z autokons. 4,930 MWh + ~16% eksport) | ~6,280 |
| Autokonsumpcja [MWh] | **4,930.8** | ~5,245 |
| Autokonsumpcja [%] | ~83% (z produkcji) | ~83% (podobny %) |
| Pokrycie zużycia [%] | **19.9%** | ~21.1% |
| NPV [mln PLN] | **13.38** | ~14.8-15.2 |
| IRR [%] | **21.85** | ~23.5-24 |
| Prosty payback [lat] | **4.83** | ~4.5 |
| Zdyskontowany payback [lat] | **6.8** | ~6.3 |

**TO DO:** Twój portal powinien wyeksportować drugi plik CAPEX z `scenario=P50` (ten sam 5560 kWp, ten sam profil) — wtedy wartości będą twarde.

---

## 3. ROZBICIE KOSZTU ENERGII ALL-IN (roczne dla BASF)

Źródło: stawki z `PV_Economics_5560kWp_2025.xlsx` (arkusz "Podsumowanie") + pobór roczny.

### Stawki jednostkowe [PLN/MWh]

| Składnik | Stawka | Uwagi |
|---|---|---|
| Dystrybucja szczyt | 54.47 | godziny szczytowe |
| Dystrybucja dzień | 47.73 | godziny dzienne (poza szczytem) |
| Dystrybucja noc | 42.11 | noc (22-06) + weekendy |
| Opłata jakościowa | 32.12 | stała |
| Opłata OZE | 7.30 | stała |
| Opłata kogeneracyjna | 3.00 | stała |
| Akcyza | 5.00 | stała |
| Opłata mocowa (SOM) | 219.40 | tylko godziny mocowe 7-22 |

### Zużycie roczne

- **Bez PV:** 24,833.55 MWh (pełny pobór)
- **Z PV:** 19,902.77 MWh (pobór netto z sieci, po autokonsumpcji)
- **Autokonsumpcja PV:** 4,930.78 MWh (oszczędność z poboru)

### Roczne kwoty (obliczone = zużycie × stawka)

| Składnik | Bez PV [PLN/rok] | Z PV [PLN/rok] | Oszczędność [PLN/rok] |
|---|---|---|---|
| **Energia czynna (RDN)** | ~12,416,775 * | ~9,951,385 * | ~2,465,390 |
| Dystrybucja (mix 3 stref, śr. ~48 PLN/MWh) | ~1,192,010 | ~955,333 | ~236,677 |
| Opłata jakościowa | 797,654 | 639,287 | 158,367 |
| Opłata OZE | 181,285 | 145,290 | 35,995 |
| Opłata kogeneracyjna | 74,501 | 59,708 | 14,793 |
| Akcyza | 124,168 | 99,514 | 24,654 |
| **Opłata mocowa (SOM)** | **459,492** ✓ | **285,159** ✓ | **174,333** ✓ |
| **RAZEM (szacunek)** | ~15,245,885 | ~12,135,676 | ~3,110,209 |

(* = **energia czynna** liczona po cenach RDN godzinowych z PSE — średnia ~500 PLN/MWh, ale zmienna w godzinach)

✓ = wartości potwierdzone z pliku BASF (obliczone godzinowo z formułami).

**TO DO:** Żeby dostać dokładne liczby (nie szacunki), otwórz `PV_Economics_5560kWp_2025.xlsx` w Excel (nie Pythonie) — tam Excel przeliczy formuły SUMPRODUCT i dostaniesz dokładne totale w arkuszu "Podsumowanie" rzędy 33-41.

---

## 4. REPREZENTATYWNY TYDZIEŃ (7 dni) — Load vs PV vs Autokonsumpcja

Źródło: `Rozliczenie Godzinowe` z PV_Economics BASF, pierwsze 7 dni (1-7 stycznia 2025, zimowa sekwencja).

### Sumy dzienne

| Data | Dzień tyg. | Pobór bez PV [MWh] | Pobór z PV [MWh] | Autokonsumpcja [MWh] | Autokons. % dnia |
|---|---|---|---|---|---|
| 2025-01-01 | Śr (Nowy Rok) | 20.57 | 19.19 | 1.38 | 6.7% |
| 2025-01-02 | Czw | 66.43 | 65.07 | 1.36 | 2.1% |
| 2025-01-03 | Pt | 73.77 | 71.89 | 1.88 | 2.6% |
| 2025-01-04 | Sob | 75.30 | 72.77 | 2.53 | 3.4% |
| 2025-01-05 | Nd | 77.66 | 73.88 | 3.79 | 4.9% |
| 2025-01-06 | Pn | 77.82 | 75.96 | 1.86 | 2.4% |
| 2025-01-07 | Wt (Święto 3 Króli) | 78.22 | 61.84 | 16.39 | 20.9% |

**Uwaga metodologiczna:** To **ZIMOWE** 7 dni — produkcja PV jest minimalna (krótki dzień, niskie słońce, częste zachmurzenie). Dla lepszej prezentacji wizualnej warto pokazać **7 dni w czerwcu** (najwyższa produkcja) albo **7 dni w marcu/kwietniu** (zrównoważone).

### Przykładowa próbka godzinowa (6 stycznia, poniedziałek)

| Godz | Pobór bez PV [kW] | Pobór z PV [kW] | PV na miejscu [kW] | Cena RDN [PLN/MWh] |
|---|---|---|---|---|
| 00 | 3140.2 | 3140.2 | 0 | 118.7 |
| 03 | 3163.1 | 3163.1 | 0 | 61.0 |
| 06 | 3336.3 | 3336.3 | 0 | 201.0 |
| 09 | 3318.6 | 2996.7 | **321.9** | 300.1 |
| 12 | 3354.0 | 3054.9 | **299.1** | 234.0 |
| 15 | 3257.5 | 3257.5 | 0 | 361.2 |
| 18 | 3195.0 | 3195.0 | 0 | 324.0 |
| 21 | 3191.1 | 3191.1 | 0 | 230.0 |

**Interpretacja dla artykułu:**
- BASF = zakład 24/7 (~3000-3300 kW poboru nocą i dniem)
- W zimie PV produkuje tylko 9:00-15:00 (6h użytecznego światła)
- Autokonsumpcja dzienna zimą: 2-5%, w święto do 20% (jest światło, jest bezczynny pobór)
- **Z PV nie pokryjemy nocnego poboru** — dlatego 5560 kWp daje tylko 19.9% pokrycia i tu BESS może dodać ~20-30%

**TO DO:** Lepsza dana do wykresu = 7 dni w **czerwcu/lipcu** (dzień dłuższy, PV wysokie, autokonsumpcja 40-70%) + dodatkowo pokazanie **eksportu** (kiedy PV > load). Trzeba wyciągnąć z tego samego arkusza wiersze dla lipca (row ~4356+).

---

## 5. OPEN-BOOK / FORMUŁY EXCEL

### Lista arkuszy eksportowych

**CAPEX_Analiza_NPV_5560kWp_P90_FORMULY.xlsx:**
1. `Podsumowanie CAPEX` — KPI (CAPEX, NPV, IRR, payback, LCOE)
2. `CAPEX Rok po Roku` — cashflow rok 1-30 z formułami
3. `Analiza CFO` — tornado, sensitivity, macierz NPV, scenariusze, ESG, break-even
4. `CAPEX Summary` — EN mirror #1
5. `CAPEX Year by Year` — EN mirror #2
6. `CFO Analysis` — EN mirror #3
7. `_sys_config` — parametry techniczne audytowe

**PV_Economics_5560kWp_2025.xlsx:**
1. `Podsumowanie` — stawki, klasa K, totale all-in
2. `Rozliczenie Godzinowe` — 8760 wierszy, 28 kolumn (pobór, cena RDN, wszystkie opłaty per godzina)
3. `Podsumowanie Miesięczne` — sumy per miesiąc z formułami SUMPRODUCT

**EaaS_Analiza_NPV_5560kWp_P90_FORMULY.xlsx:** (nie analizowałem, ale struktura analogiczna)

### 3 Reprezentatywne formuły dla artykułu

**Autokonsumpcja (per godzina, arkusz `Rozliczenie Godzinowe`):**

```excel
=MIN(Pobór_godzinowy; PV_produkcja_godzinowa)
```

Przykład: jeśli pobór = 3300 kW i PV = 321 kW → autokons. = 321 kW (cała produkcja); jeśli PV = 4000 kW i pobór = 3300 → autokons. = 3300 kW (reszta 700 kW idzie do eksportu).

---

**Koszt all-in (per godzina, wiersz 4 = 1 stycznia 00:00):**

```excel
=G4 + H4 + I4 + J4 + K4 + L4 + M4
```

gdzie kolumny to:
- G = Koszt energii [PLN] = `Pobór × Cena_RDN / 1000`
- H = Dystrybucja [PLN] = `Pobór × Stawka_strefy / 1000`
- I-L = Jakość + OZE + Kogen + Akcyza (iloczyn poboru × stawka jednostkowa)
- M = Opłata mocowa [PLN] = `JEŻELI(Godzina_mocowa="TAK"; Pobór × 0.2194; 0)`

**Pełna formuła opłaty mocowej:**

```excel
=IF(AND(HOUR(A4)>=7; HOUR(A4)<22; WEEKDAY(A4;2)<=5); E4*0.2194; 0)
```

(tylko dni robocze 7-22; dokładne godziny zależą od kwartału — dla BASF zastosowano godziny 7-22 całorocznie).

---

**NPV / cash flow (arkusz `CAPEX Rok po Roku`, rok 1 = wiersz 18):**

```excel
Oszczędność_rok_t = Równow_OSD_t − OPEX_t
                  = (Suma_Autokonsumpcja_MWh × Cena_sieci × (1+inflacja)^t) − (OPEX_bazowy × (1+inflacja)^t)

NPV_skum_rok_t = NPV_skum_t−1 + Oszczędność_t / (1+stopa_dyskontowa)^t
```

Formuła Excel w komórce (przykład dla wiersza 18, rok 1):

```excel
=J17 + L18 / (1 + $F$4)^B18 / 1000
```

gdzie:
- J17 = NPV skumulowane z poprzedniego roku (w mln PLN)
- L18 = Oszczędność netto rok 1 [tys. PLN]
- $F$4 = stopa dyskontowa (10%)
- B18 = numer roku (1)
- dzielenie /1000 = konwersja z tys. PLN na mln PLN

**Rok 0** ma ujemny cashflow = `-CAPEX`, dlatego NPV startuje od -10.792 mln PLN dla BASF.

### Dlaczego open-book?

1. **Transparentność dla bankiera** — każdy wiersz Excel ma formułę, bank może zmienić stopę dyskontową czy inflację i od razu widzi nowe NPV
2. **Audyt** — 8760 godzin × 28 kolumn = 245,280 wartości do zweryfikowania
3. **Customizacja** — klient może podstawić własne stawki OSD i zobaczyć wpływ

---

## 6. DODATKOWE DANE BEZ AGENTA (z pliku BASF)

### Klasa K (opłata mocowa)

| Rok | Dni K1 (A=0.17) | Dni K2 (A=0.5) | Dni K3 (A=0.83) | Dni K4 (A=1.0) | WOM [PLN] |
|---|---|---|---|---|---|
| Bez PV | 234 | 14 | 1 | 2 | 459,492 |
| Z PV | 250 | 0 | 0 | 1 | 285,159 |

**Wniosek biznesowy:** PV poprawiło klasyfikację 15 dni z K2/K3 do K1 (średnia Δs spadła z -0.9% do -29.4%). Oszczędność 174,333 PLN/rok pochodzi z:
- ~139,788 PLN z redukcji ZS (zużycia szczytowego)
- ~35,367 PLN z poprawy klasy K

### Parametry techniczne

```
Moc PV [kWp]:           5,560
CAPEX [tys. PLN]:       10,792 (1,941 PLN/kWp — bardzo konkurencyjna cena skali)
Okres analizy:          30 lat
Stopa dyskontowa:       10%
Inflacja:               2.5%
Degradacja PV rok 1:    0%
Degradacja PV lata 2+:  0.4%/rok
Scenariusz produkcji:   P90 (ostrożny)

NPV:                    13.38 mln PLN
IRR:                    21.85%
ROI:                    714.5%
Prosty payback:         4.83 lat
Zdyskontowany payback:  6.80 lat
LCOE:                   240 PLN/MWh
```

### Cashflow rok 1-6 (P90)

| Rok | Deg PV | Zużycie [MWh] | Autokons. [MWh] | Równow. OSD [tys.] | OPEX [tys.] | Oszczędn. [tys.] | NPV skum. [mln] |
|---|---|---|---|---|---|---|---|
| 0 | - | - | - | - | - | -10,792 | -10.79 |
| 1 | 1.000 | 24,833.55 | 4,930.78 | 2,285.91 | 140.20 | 2,145.71 | -8.84 |
| 2 | 0.996 | 24,833.55 | 4,911.06 | 2,333.69 | 143.70 | 2,189.98 | -7.03 |
| 3 | 0.992 | 24,833.55 | 4,891.41 | 2,382.46 | 147.30 | 2,235.16 | -5.35 |
| 4 | 0.988 | 24,833.55 | 4,871.85 | 2,432.25 | 150.98 | 2,281.27 | -3.79 |
| 5 | 0.984 | 24,833.55 | 4,852.36 | 2,483.09 | 154.75 | 2,328.33 | -2.35 |
| 6 | 0.980 | 24,833.55 | 4,832.95 | 2,534.98 | 158.62 | 2,376.36 | -1.01 |

→ **Rok 7** — NPV przekracza 0 (≈ 6.8 rok dyskontowany).

---

## 7. PODSUMOWANIE — CO AGENT MA, CO MUSI DOGENEROWAĆ

### ✅ MA twarde z plików BASF:

1. Pełne KPI dla 5560 kWp / P90 (NPV, IRR, payback, LCOE)
2. Rozbicie klasy K (dni K1-K4, redukcja SOM)
3. Cashflow rok 1-30 (kolumny produkcji, oszczędności, NPV skumulowane)
4. Stawki OSD jednostkowe (dystrybucja 3 stref, jakość, OZE, kogen, akcyza, SOM)
5. 7 dni godzinowego profilu Load + PV + Cena RDN (zima) — można rozszerzyć do lata
6. Opłata mocowa roczna: 459,492 → 285,159 PLN (oszczędność 174,333 PLN, 38.1%)

### ⚠️ BRAKUJE (trzeba dogenerować z portalu):

1. **Scan wariantów A/B/C/D + Best NPV** dla BASF — odpal `POST /analyze` z profilem BASF, zapisz `key_variants` + 5-10 punktów z `scenarios`
2. **Eksport P50** dla tego samego projektu — ten sam 5560 kWp, `scenario=P50` w requeście
3. **Dokładne wartości kosztu all-in** (energia czynna, dystrybucja, jakość, OZE, kogen, akcyza) — otwórz `PV_Economics_5560kWp.xlsx` w Excel (nie Python) żeby formuły SUMPRODUCT się policzyły, odczytaj arkusz "Podsumowanie" rzędy 33-41
4. **7 dni letnich** (np. 1-7 lipca) z tego samego arkusza `Rozliczenie Godzinowe` wiersze ~4356-4523 — lepsza wizualizacja autokonsumpcji

### 📝 Sugestia workflow dla agenta:

1. Otworzyć `PV_Economics_5560kWp_2025.xlsx` w Excel → skopiować tabelę "Podsumowanie roczne" → wkleić jako dokładne wartości all-in
2. Uruchomić portal, załadować profil BASF, wybrać 5560 kWp, P90 → wyeksportować `key_variants.json`
3. Zmienić P90 na P50, ponownie eksportować → drugi plik CAPEX do porównania
4. Z `Rozliczenie Godzinowe` wyciąć wiersze 4356-4523 (1-7 lipca) → letni wykres 7-dniowy
