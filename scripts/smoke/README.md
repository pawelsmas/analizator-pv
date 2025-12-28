# Smoke requests

Gotowe payloady do szybkiego sprawdzenia sizingu BESS.

## Użycie

Ustaw BASE_URL (port z docker-compose):

```bash
export BASE_URL="http://localhost:8031"
```

### No arbitrage (podstawowy scenariusz)
```bash
curl -sS "$BASE_URL/sizing" \
  -H "Content-Type: application/json" \
  --data-binary @scripts/smoke/sizing_stacked_no_arbitrage.json \
  | python -m json.tool
```

### With arbitrage (z konfiguracją ToU)
```bash
curl -sS "$BASE_URL/sizing" \
  -H "Content-Type: application/json" \
  --data-binary @scripts/smoke/sizing_stacked_with_arbitrage.json \
  | python -m json.tool
```

## Pliki

| Plik | Opis |
|------|------|
| `sizing_stacked_no_arbitrage.json` | Stacked mode, 168h, bez arbitrażu |
| `sizing_stacked_with_arbitrage.json` | Stacked mode, 168h, z ToU arbitrage (C12a/PGE) |
| `sizing_no_arb.json` | Surowy output z poprzedniego smoke testu |
| `sizing_with_arb.json` | Surowy output z poprzedniego smoke testu |

## Weryfikacja SSoT

Po wykonaniu curl, sprawdź:
```bash
# annual_savings_pln == net_savings_pln
jq '.variants[0] | {annual: .annual_savings_pln, net: .savings_breakdown.net_savings_pln}' /tmp/result.json

# period_info exists
jq '.period_info' /tmp/result.json
```
