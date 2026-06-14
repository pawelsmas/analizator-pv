# Customer Portal UX - Smoke Test

## Cel
Weryfikacja, że Energy Studio (ES) publikuje TYLKO to, co wybrane w Portfolio, z jasnymi blokerami i guardrails.

## Wymagania wstępne
- Docker containers running: `docker-compose ps`
- Projekt zapisany w bazie danych z firmą
- Dostęp do: http://localhost:9000 (Energy Studio)

---

## Test 1: Banner pokazuje dane z Portfolio

**Kroki:**
1. Otwórz Energy Studio -> Analiza Ekonomiczna
2. Zapisz projekt do bazy (💾 Zapisz projekt)
3. Sprawdź banner pod nagłówkiem "ANALIZA EKONOMICZNA INSTALACJI PV"

**Oczekiwany rezultat:**
- Banner widoczny z 4 sekcjami:
  - 🔗 INTEGRACJA: Offer ID, Wersja, HubSpot
  - ✅ WYBRANA OPCJA (Portfolio): Wariant, Snapshot
  - 📊 WARUNKI KREDYTOWE: Max EaaS, Depozyt, Klasa ryzyka
  - Status: READY/NOT READY + przyciski

**Weryfikacja:**
```
Wariant: NIE WYBRANO (czerwony) lub Wariant A/B/C/D (zielony)
Snapshot: BRAK (czerwony) lub #123 (biały)
```

---

## Test 2: NOT READY z konkretnymi blokerami

**Kroki:**
1. Upewnij się, że projekt NIE ma `selected_option_key` i `selected_snapshot_id`
2. Kliknij "📤 Publikuj" w bannerze

**Oczekiwany rezultat:**
- Modal pokazuje blokady:
  - 🚫 "Brak wybranej opcji w Portfolio"
  - 🚫 "Brak snapshotu ekonomicznego"
- Każda blokada ma "💡 fix" z instrukcją
- Przycisk "Potwierdź publikację" jest disabled

**Weryfikacja:**
```
Status badge: NOT READY (czerwony)
Blockers: minimum 2
Fix instructions: "Otwórz Portfolio Management..."
```

---

## Test 3: Zmiana selected_option w Portfolio -> ES aktualizuje banner

**Kroki:**
1. W Portfolio Management wybierz Wariant B dla projektu
2. Zapisz (ustaw `selected_option_key = 'B'`, `selected_snapshot_id = 123`)
3. Odśwież Economics (F5) lub zapisz projekt ponownie

**Oczekiwany rezultat:**
- Banner pokazuje: "Wariant B" (zielony)
- Banner pokazuje: "#123" (snapshot ID)
- Status zmienia się na READY (jeśli nie ma innych blokerów)

**Weryfikacja:**
```
[CustomerPortal] Project loaded: { selectedOption: 'B', selectedSnapshot: 123 }
```

---

## Test 4: Publish publikuje TYLKO selected (mismatch blokowany)

**Kroki:**
1. Ustaw w Portfolio: `selected_option_key = 'A'`, `selected_snapshot_id = 50`
2. W ES kliknij "📤 Publikuj"
3. Modal pokazuje: Wariant A, Snapshot #50
4. Potwierdź publikację

**Oczekiwany rezultat:**
- Publikacja używa TYLKO wartości z Portfolio
- Toast: "✅ Opublikowano: OFFER-2026-XXXX v1"
- Historia publikacji pokazuje nowy wpis

**Weryfikacja backend (jeśli ktoś próbuje obejść):**
```bash
curl -X POST http://localhost:8050/projects/1/publish-to-customer-portal \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer admin_energy_studio" \
  -d '{"snapshot_id": 999, "option_key": "D"}'
# Powinno zwrócić błąd INTEGRATION_MISMATCH jeśli to nie jest selected
```

---

## Test 5: Customer Preview zawsze CUSTOMER_SAFE

**Kroki:**
1. Kliknij "👁️ Podgląd" w bannerze
2. Sprawdź guard status na górze modalu

**Oczekiwany rezultat:**
- Guard: "✅ PASS: Dane bezpieczne dla klienta (CUSTOMER_SAFE)"
- Preview pokazuje:
  - Instalacja (moc, typ, BESS)
  - Model CAPEX (Inwestycja, NPV, IRR, Payback)
  - Model EaaS (Rata roczna, Okres)
- NIE pokazuje: direct_cost, gross_margin, investor_irr

**Weryfikacja (jeśli guard FAIL):**
```
Guard: "🚫 FAIL: Wykryto X zabronionych pól!"
Console: [SECURITY] DATA_LEAK_PREVENTED: { violations: [...] }
Publish button: disabled
```

---

## Test 6: Access control działa zgodnie z backendem

**Kroki:**
1. Zmień token na `internal_energy_studio`:
   ```javascript
   localStorage.setItem('authToken', 'internal_energy_studio');
   location.reload();
   ```
2. Sprawdź banner

**Oczekiwany rezultat:**
- Przycisk "📤 Publikuj" jest ukryty (data-admin-only)
- Przycisk "📋 Historia" jest widoczny (data-internal-only)

**Weryfikacja dla customer:**
```javascript
localStorage.setItem('authToken', 'customer_xyz');
location.reload();
// Oba przyciski ukryte, tylko "Podgląd" widoczny
```

---

## Test 7: NOT READY z drift warning

**Kroki:**
1. Ustaw `selected_snapshot_id = 50` w Portfolio
2. Wygeneruj nowy snapshot w Economics (ID = 51)
3. Sprawdź banner

**Oczekiwany rezultat:**
- Warning w sekcji "WYBRANA OPCJA":
  - "⚠️ Snapshot nieaktualny (latest: #51)"
- Status: nadal READY (drift to warning, nie blocker)
- Modal Publish pokazuje warning z sugestią

---

## Test 8: Historia publikacji (internal-only)

**Kroki:**
1. Kliknij "📋" (Historia) w bannerze
2. Sprawdź listę publikacji

**Oczekiwany rezultat:**
- Modal "Historia publikacji (internal-only)"
- Lista wpisów z:
  - OFFER-ID vN
  - Wariant X
  - Data publikacji
  - Snapshot ID
  - Klasa ryzyka (jeśli była)

**Weryfikacja bez tokena:**
```bash
curl http://localhost:8050/projects/1/publication-history
# 403 Forbidden
```

---

## Podsumowanie DoD

| Kryterium | Status |
|-----------|--------|
| Zmiana selected w Portfolio -> ES pokazuje nowy selected | ✅ |
| Publish publikuje TYLKO selected (mismatch blokowany) | ✅ |
| Preview zawsze CUSTOMER_SAFE, redaction guard blokuje przy FAIL | ✅ |
| NOT READY pokazuje blokery i mówi "napraw w Portfolio" | ✅ |

---

## Troubleshooting

### Banner nie widoczny
```bash
# Sprawdź czy JS się ładuje
curl -s http://localhost:9006/customer-portal.js | head -5
# Powinno pokazać "HARD BUSINESS RULES"

# Przebuduj kontener
docker-compose build --no-cache frontend-economics
docker-compose up -d frontend-economics
```

### Dane nie ładują się
```bash
# Sprawdź database-api
curl http://localhost:8050/health

# Sprawdź projekt
curl http://localhost:8050/projects/1
```

### Console errors
```javascript
// W DevTools sprawdź logi
// Powinno być: [CustomerPortal] Initialized, role: admin
// Powinno być: [CustomerPortal] Project loaded: { ... }
```
