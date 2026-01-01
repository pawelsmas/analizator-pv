# BESS Dispatch API Deprecations

This document tracks deprecated API fields and provides migration guidance.

## Overview

The BESS Dispatch API follows a structured deprecation process:

1. **Announcement** - Field marked deprecated in `docs/api/deprecations.json`
2. **Warning Period** - API returns `Deprecation` header when deprecated fields are used
3. **Sunset** - Deprecated fields are removed after the sunset date

## Current Sunset Date

**2026-03-01** - All deprecated fields will be removed after this date.

## Deprecated Fields

### Response Fields

| Field | Replacement | Since | Notes |
|-------|-------------|-------|-------|
| `export_revenue_pln` | `export_savings_pln` | v0.3.2 | Field renamed for clarity |
| `savings_pln` | `total_savings_pln` | v0.3.2 | Field renamed for clarity |
| `interval_minutes` | `dt_minutes` | v0.3.2 | Standardized naming |

### Request Fields

| Field | Replacement | Since | Notes |
|-------|-------------|-------|-------|
| `include_battery_trace` | `battery_trace_mode` | v2.5.0 | Use mode='full'\|'preview'\|'none' |
| `include_price_timeseries` | `price_timeseries_mode` | v2.5.0 | Use mode='full'\|'preview'\|'none' |
| `include_ledger_timeseries` | `ledger_timeseries_mode` | v2.5.0 | Use mode='full'\|'preview'\|'none' |

## Migration Guide

### 1. Update API Calls to Use `compat=clean`

Add `?compat=clean` to your sizing API calls to receive the new clean response format:

```javascript
// Before
fetch('/api/bess-dispatch/sizing', { ... });

// After
fetch('/api/bess-dispatch/sizing?compat=clean', { ... });
```

### 2. Replace Deprecated Request Fields

**Before:**
```json
{
  "include_battery_trace": true,
  "include_price_timeseries": true,
  "include_ledger_timeseries": true
}
```

**After:**
```json
{
  "battery_trace_mode": "full",
  "price_timeseries_mode": "full",
  "ledger_timeseries_mode": "full"
}
```

The new mode parameters support:
- `"none"` - Don't include timeseries (default)
- `"preview"` - Include first N rows only
- `"full"` - Include all rows

### 3. Update Response Field References

**Before:**
```javascript
const revenue = result.export_revenue_pln;
const savings = result.savings_pln;
const interval = result.interval_minutes;
```

**After:**
```javascript
const revenue = result.export_savings_pln;
const savings = result.total_savings_pln;
const interval = result.dt_minutes;
```

## Detecting Deprecated Usage

### Response Headers

When deprecated fields are used, the API returns:

```
Deprecation: true
Link: </api/bess-dispatch/deprecations>; rel="deprecation"
Sunset: 2026-03-01
```

### Response Body Warnings

The response includes a warnings block:

```json
{
  "warnings": {
    "deprecations_used": ["include_battery_trace", "include_price_timeseries"]
  }
}
```

### Deprecations Endpoint

Query the deprecations endpoint for the full list:

```
GET /api/bess-dispatch/deprecations
```

## Compatibility Mode

Use the `compat` query parameter to control response format:

| Mode | Behavior |
|------|----------|
| `clean` (default) | Returns only new field names |
| `legacy` | Returns both old and new field names |

**Important:** `compat=legacy` is temporary and will be removed at sunset date.

## Tooling

### Generate Deprecations Report

```bash
# Text report
python scripts/deprecations/report.py

# Markdown report
python scripts/deprecations/report.py --format markdown

# JSON report
python scripts/deprecations/report.py --format json

# CI check mode
python scripts/deprecations/report.py --check
```

### CI Validation

The CI pipeline validates deprecations.json on every PR to ensure:
- Valid JSON structure
- Required fields present
- No duplicate entries
- Valid status values

## Timeline

| Date | Milestone |
|------|-----------|
| 2026-01-01 | v2.7.0 released with deprecation warnings |
| 2026-02-01 | 30 days before sunset - increased warning visibility |
| 2026-03-01 | **Sunset** - deprecated fields removed |

## Questions?

If you have questions about migrating your integration, please:

1. Check this documentation
2. Review `docs/api/deprecations.json` for the full SSoT
3. Open an issue on GitHub
