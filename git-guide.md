# 📚 Przewodnik Git - Przywracanie Wersji

## 🎯 Podstawowe Komendy

### Sprawdzanie historii commitów
```bash
# Zobacz wszystkie commity
git log --oneline

# Zobacz szczegóły ostatniego commita
git show HEAD

# Zobacz co się zmieniło w pliku
git log -p services/frontend-production/production.js
```

### Tworzenie nowych commitów
```bash
# Sprawdź status
git status

# Dodaj wszystkie zmienione pliki
git add .

# Stwórz commit
git commit -m "Opis zmian"

# Zobacz historię
git log --oneline
```

### Przywracanie poprzednich wersji

#### Opcja 1: Wrócić do konkretnego commita (BEZPIECZNE)
```bash
# 1. Zobacz listę commitów
git log --oneline

# 2. Stwórz nową gałąź z konkretnego commita
git checkout -b backup-branch a7fdb17

# 3. Wróć na główną gałąź
git checkout master
```

#### Opcja 2: Przywróć konkretny plik z poprzedniego commita
```bash
# Przywróć plik z konkretnego commita
git checkout a7fdb17 -- services/frontend-production/production.js

# Zatwierdź zmianę
git commit -m "Przywrócono production.js z commita a7fdb17"
```

#### Opcja 3: Cofnij ostatni commit (ZACHOWAJ ZMIANY)
```bash
# Cofnij commit, ale zostaw zmiany w plikach
git reset --soft HEAD~1

# Lub cofnij commit i usuń zmiany
git reset --hard HEAD~1
```

#### Opcja 4: Stwórz nowy commit cofający zmiany
```bash
# Bezpieczne cofnięcie - tworzy nowy commit
git revert HEAD
```

### Praca z gałęziami (branches)

```bash
# Zobacz wszystkie gałęzie
git branch -a

# Stwórz nową gałąź
git branch feature-roi

# Przełącz się na gałąź
git checkout feature-roi

# Lub stwórz i przełącz w jednej komendzie
git checkout -b feature-k1-k4

# Wróć na master
git checkout master

# Usuń gałąź
git branch -d feature-roi
```

## 🔄 Przykładowe Scenariusze

### Scenariusz 1: Chcę zapisać obecny stan przed eksperymentem
```bash
# Stwórz gałąź z obecnym stanem
git checkout -b backup-20251121

# Wróć na master i eksperymentuj
git checkout master
# ... wprowadź zmiany ...
git add .
git commit -m "Eksperyment z nową funkcją"

# Jeśli coś poszło nie tak, wróć do backupu
git checkout backup-20251121
git checkout -b master-new
git branch -D master
git branch -m master
```

### Scenariusz 2: Chcę zobaczyć jak wyglądał kod wczoraj
```bash
# Zobacz commity z datami
git log --since="2 days ago" --pretty=format:"%h %ad %s" --date=short

# Przełącz się na konkretny commit (read-only)
git checkout a7fdb17

# Wróć do najnowszej wersji
git checkout master
```

### Scenariusz 3: Chcę przywrócić tylko moduł Economics
```bash
# Przywróć cały katalog z poprzedniego commita
git checkout a7fdb17 -- services/frontend-economics/

# Zatwierdź
git commit -m "Przywrócono moduł Economics z commita a7fdb17"
```

### Scenariusz 4: Zapisuję punkty kontrolne podczas pracy
```bash
# Co godzinę lub po większych zmianach
git add .
git commit -m "WIP: Dodano funkcję X"

# Po skończeniu funkcjonalności
git add .
git commit -m "✅ Zaimplementowano ROI analysis

- Dodano wykres ROI
- Obliczenia payback period
- Eksport do Excel"
```

## 🎨 Dobre Praktyki

### Formatowanie wiadomości commit
```
Krótki opis (max 50 znaków)

Dłuższy opis jeśli potrzebny:
- Co zostało zmienione
- Dlaczego to zrobiono
- Jakie są efekty

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>
```

### Częste commitowanie
- ✅ Commit po każdej znaczącej zmianie (nawet co 30 min)
- ✅ Commit przed eksperymentami
- ✅ Commit przed cofnięciem do poprzednich wersji
- ❌ NIE czekaj do końca dnia

### Używanie gałęzi
- `master` - stabilna wersja produkcyjna
- `feature-roi` - nowa funkcja ROI
- `feature-k1-k4` - nowa funkcja K1-K4
- `bugfix-economics` - naprawa błędu
- `backup-YYYYMMDD` - backup przed dużymi zmianami

## 🚨 Ratunkowe Komendy

### Zepsuło się wszystko - chcę wrócić do ostatniego działającego stanu
```bash
# UWAGA: To usunie wszystkie niezapisane zmiany!
git reset --hard HEAD

# Lub do konkretnego commita
git reset --hard a7fdb17
```

### Przypadkowo usunąłem pliki
```bash
# Przywróć wszystkie pliki z ostatniego commita
git checkout HEAD -- .

# Przywróć konkretny plik
git checkout HEAD -- services/frontend-production/production.js
```

### Chcę zobaczyć co się zmieniło przed commitowaniem
```bash
git diff
git diff services/frontend-production/production.js
```

## 📊 Pierwszy Commit

**Commit ID:** `a7fdb17`
**Data:** 2025-11-21
**Opis:** Initial commit - PV Analyzer base version

**Stan systemu:**
- ✅ Wszystkie moduły działają
- ❌ Bez K1-K4 capacity fees
- ❌ Bez CPH218 pricing
- ❌ Bez ROI analysis
- ❌ Bez cost breakdown w Consumption

**Jak wrócić do tego stanu:**
```bash
git checkout a7fdb17 -- .
git commit -m "Przywrócono stan z initial commit"
```

## 🏷️ Wersje (Tags)

### Sprawdzanie wersji
```bash
# Zobacz wszystkie wersje
git tag -l

# Zobacz szczegóły konkretnej wersji
git show A_PV_1.1
```

### Przywracanie konkretnej wersji
```bash
# Przełącz się na wersję (read-only)
git checkout A_PV_1.1

# Wróć do najnowszej wersji
git checkout master

# Stwórz nową gałąź z konkretnej wersji
git checkout -b fix-from-1.1 A_PV_1.1
```

### Tworzenie nowych wersji
```bash
# Stwórz tag z obecnego stanu
git tag -a A_PV_1.2 -m "Opis wersji 1.2"

# Stwórz tag z konkretnego commita
git tag -a A_PV_1.2 3c33c3f -m "Opis wersji"

# Usuń tag (jeśli się pomyliłeś)
git tag -d A_PV_1.2
```

## 📋 Historia Wersji

### A_PV 1.1 (2025-11-21) - BASELINE ✅
**Commit:** `3c33c3f`
**Status:** STABLE

**Co zawiera:**
- ✅ Wszystkie moduły działają
- ✅ Production analysis
- ✅ Consumption analysis  
- ✅ Economics calculations
- ✅ Settings management

**Czego NIE ma:**
- ❌ K1-K4 capacity fee groups
- ❌ CPH218 pricing data
- ❌ ROI analysis
- ❌ Cost breakdown

**Jak wrócić:**
```bash
git checkout A_PV_1.1
# lub
git checkout A_PV_1.1 -- .
git commit -m "Przywrócono wersję A_PV 1.1"
```

---

### Planowane wersje:

**A_PV 1.2** - K1-K4 Capacity Fees
- K1-K4 classification
- Polish holiday calendar
- Peak hours detection

**A_PV 1.3** - CPH218 Pricing
- CPH218 tariff data
- Automatic price loading

**A_PV 1.4** - ROI Analysis
- ROI calculations
- Payback period
- 25-year projections

**A_PV 1.5** - Cost Breakdown
- Energy cost visualization
- Component breakdown charts
