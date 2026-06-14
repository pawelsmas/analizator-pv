"""
Curate Polish OSD tariff presets from PAGRA-Galileo 2026 data.

Reads:
  - PAGRA JSON files (variable distribution rates, hourly schedules)
  - Fixed fees hardcoded from _taryfy_2025.py (decompiled source)

Outputs:
  - services/frontend-settings/tariff_presets.json

Usage:
  python scripts/curate_tariffs.py
"""

import json
import os
import sys

# Path to PAGRA 2026 tariff JSON files
PAGRA_BASE = os.path.join(
    os.path.expanduser("~"),
    "PROGRAMY", "pagra-galileo", "zip_extracted",
    "kalkulatorMEE_pagra.exe_extracted", "data", "distribution_cost", "2026"
)

# Output path
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services", "frontend-settings", "tariff_presets.json"
)

# Business tariff groups to include (no G-household, no VAT variants, no em variants)
INCLUDE_GROUPS = {
    "PGE": ["A23", "A24", "B21", "B22", "B23", "B24", "C21", "C22a", "C22b", "C23", "C24"],
    "Tauron": ["A21", "A22", "A23", "B21", "B22", "B23", "C21", "C22a", "C22b", "C23"],
    "Enea": ["A21", "A23", "B21", "B22", "B23", "C21", "C22a", "C22b", "C22w"],
    "Energa": ["A23", "B21", "B22", "B23", "C21", "C22a", "C22b", "C23"],
}

OPERATOR_LABELS = {
    "PGE": "PGE Dystrybucja",
    "Tauron": "Tauron Dystrybucja",
    "Enea": "Enea Operator",
    "Energa": "Energa Operator",
}

# Voltage group labels
VOLTAGE_LABELS = {
    "A": "WN (wysokie napiecie)",
    "B": "SN (srednie napiecie)",
    "C": "nn (niskie napiecie)",
}

# Tariff group descriptions
TARIFF_DESCRIPTIONS = {
    "A21": "WN, 1-strefowa",
    "A22": "WN, 2-strefowa",
    "A23": "WN, 3-strefowa",
    "A24": "WN, 4-strefowa",
    "B11": "SN, 1-strefowa (bez pomiaru mocy)",
    "B21": "SN, 1-strefowa",
    "B22": "SN, 2-strefowa",
    "B23": "SN, 3-strefowa",
    "B24": "SN, 4-strefowa",
    "C21": "nn, 1-strefowa",
    "C22a": "nn, 2-strefowa (szczytowa)",
    "C22b": "nn, 2-strefowa (dzienna)",
    "C22w": "nn, 2-strefowa (weekendowa)",
    "C23": "nn, 3-strefowa",
    "C24": "nn, 4-strefowa",
}

# Fixed fees from _taryfy_2025.py (PLN/MW/month for staly, PLN/kW/month for przejsciowa)
# Format: (staly_PLN_MW_month, przejsciowa_PLN_kW_month, jakosc_PLN_MWh, abonament_PLN_month)
FIXED_FEES = {
    "PGE": {
        "A23": (14850, 0.20, 32.12, 15.00),
        "A24": (14850, 0.20, 32.12, 15.00),
        "B21": (18430, 0.19, 32.13, 15.00),
        "B22": (19410, 0.19, 32.12, 15.00),
        "B23": (20390, 0.19, 32.12, 15.00),
        "B24": (20390, 0.19, 32.12, 15.00),
        "C21": (26040, 0.08, 32.10, 9.50),
        "C22a": (27860, 0.08, 32.10, 9.50),
        "C22b": (27860, 0.08, 32.10, 9.50),
        "C23": (29800, 0.08, 32.10, 9.50),
        "C24": (29800, 0.08, 32.10, 9.50),
    },
    "Tauron": {
        "A21": (16780, 0.20, 32.12, 18.00),
        "A22": (16440, 0.20, 32.12, 18.00),
        "A23": (16440, 0.20, 32.12, 18.00),
        "B21": (17490, 0.19, 32.12, 18.00),
        "B22": (17490, 0.19, 32.12, 18.00),
        "B23": (17930, 0.19, 32.12, 18.00),
        "C21": (16690, 0.08, 32.10, 9.50),
        "C22a": (16690, 0.08, 32.10, 9.50),
        "C22b": (16690, 0.08, 32.10, 9.50),
        "C23": (16690, 0.08, 32.10, 9.50),
    },
    "Enea": {
        "A21": (21086, 0.20, 32.12, 14.59),
        "A23": (21086, 0.20, 32.12, 14.59),
        "B21": (25436, 0.19, 32.12, 14.59),
        "B22": (25436, 0.19, 32.12, 14.59),
        "B23": (25436, 0.19, 32.12, 14.59),
        "C21": (24190, 0.08, 32.10, 10.00),
        "C22a": (24190, 0.08, 32.10, 10.00),
        "C22b": (24190, 0.08, 32.10, 10.00),
        "C22w": (29490, 0.08, 32.10, 10.00),
    },
    "Energa": {
        "A23": (19490, 0.20, 32.12, 14.50),
        "B21": (23320, 0.19, 32.12, 14.50),
        "B22": (23320, 0.19, 32.12, 14.50),
        "B23": (25050, 0.19, 32.12, 14.50),
        "C21": (34160, 0.08, 32.10, 7.25),
        "C22a": (34160, 0.08, 32.10, 7.25),
        "C22b": (34160, 0.08, 32.10, 7.25),
        "C23": (34160, 0.08, 32.10, 7.25),
    },
}


def analyze_schedule(pagra_json):
    """
    Analyze PAGRA JSON schedule to determine tariff type and extract rates.
    Uses January workday as representative pattern.
    """
    jan = pagra_json.get("January", {})
    workday = jan.get("workday", [[], [0]])

    hours = workday[0]  # hour boundaries
    rates = workday[1]  # rate values (len = len(hours) + 1)

    unique_rates = sorted(set(rates))

    if len(hours) == 0:
        # Flat tariff - single rate all day
        return {
            "tariffType": "flat",
            "flatRate": rates[0],
            "dayRate": rates[0],
            "nightRate": rates[0],
            "peakRate": rates[0],
            "partialRate": rates[0],
            "offPeakRate": rates[0],
            "distribution": rates[0],
            "weekday": {},
            "weekend": {},
        }

    if len(hours) == 2 and len(unique_rates) == 2:
        # Two-zone tariff (day/night) e.g. C22b: [6, 21] / [86.8, 259.3, 86.8]
        day_start = hours[0]
        day_end = hours[1]
        night_rate = rates[0]  # before first boundary
        day_rate = rates[1]    # between boundaries

        # Check weekend pattern
        sat = jan.get("saturday", [[], rates])
        wknd_hours = sat[0] if sat[0] else []

        if wknd_hours:
            wknd_start = wknd_hours[0]
            wknd_end = wknd_hours[1] if len(wknd_hours) > 1 else wknd_hours[0]
        else:
            wknd_start = day_start
            wknd_end = day_end

        avg_rate = round((day_rate * (day_end - day_start) + night_rate * (24 - (day_end - day_start))) / 24, 1)

        return {
            "tariffType": "two_zone",
            "flatRate": avg_rate,
            "dayRate": day_rate,
            "nightRate": night_rate,
            "peakRate": day_rate,
            "partialRate": night_rate,
            "offPeakRate": night_rate,
            "distribution": night_rate,  # base/off-peak rate
            "weekday": {
                "dayStart": day_start,
                "dayEnd": day_end,
            },
            "weekend": {
                "dayStart": wknd_start,
                "dayEnd": wknd_end,
            },
        }

    if len(hours) == 4:
        # Three-zone or two-peak tariff
        # Pattern: [h1, h2, h3, h4] / [r0, r1, r2, r3, r4]
        # Common patterns:
        #   C22a: [8,11,16,21] / [187.1, 279.9, 187.1, 279.9, 187.1] - 2 peaks, same rate
        #   C23:  [7,13,16,21] / [84.7, 236.9, 84.7, 347.8, 84.7] - 3 distinct rates

        base_rate = rates[0]  # off-peak (night)
        peak1_rate = rates[1]
        mid_rate = rates[2]
        peak2_rate = rates[3]

        peak1_start = hours[0]
        peak1_end = hours[1]
        peak2_start = hours[2]
        peak2_end = hours[3]

        # Check weekend
        sat = jan.get("saturday", [[], [base_rate]])
        wknd_hours = sat[0] if sat[0] else []

        if len(unique_rates) == 2:
            # Two distinct rates but with two peak windows -> three_zone with partial=offpeak
            return {
                "tariffType": "three_zone",
                "flatRate": round(sum(rates) / len(rates), 1),
                "dayRate": peak1_rate,
                "nightRate": base_rate,
                "peakRate": max(peak1_rate, peak2_rate),
                "partialRate": min(peak1_rate, peak2_rate) if peak1_rate != peak2_rate else base_rate,
                "offPeakRate": base_rate,
                "distribution": base_rate,
                "weekday": {
                    "peak1Start": peak1_start,
                    "peak1End": peak1_end,
                    "peak2Start": peak2_start,
                    "peak2End": peak2_end,
                },
                "weekend": {
                    "peak1Start": wknd_hours[0] if len(wknd_hours) >= 2 else 0,
                    "peak1End": wknd_hours[1] if len(wknd_hours) >= 2 else 0,
                    "peak2Start": wknd_hours[2] if len(wknd_hours) >= 4 else 0,
                    "peak2End": wknd_hours[3] if len(wknd_hours) >= 4 else 0,
                },
            }
        else:
            # Three or more distinct rates -> three_zone
            return {
                "tariffType": "three_zone",
                "flatRate": round(sum(rates) / len(rates), 1),
                "dayRate": max(peak1_rate, peak2_rate),
                "nightRate": base_rate,
                "peakRate": max(peak1_rate, peak2_rate),
                "partialRate": min(peak1_rate, peak2_rate),
                "offPeakRate": base_rate,
                "distribution": base_rate,
                "weekday": {
                    "peak1Start": peak1_start,
                    "peak1End": peak1_end,
                    "peak2Start": peak2_start,
                    "peak2End": peak2_end,
                },
                "weekend": {
                    "peak1Start": wknd_hours[0] if len(wknd_hours) >= 2 else 0,
                    "peak1End": wknd_hours[1] if len(wknd_hours) >= 2 else 0,
                    "peak2Start": wknd_hours[2] if len(wknd_hours) >= 4 else 0,
                    "peak2End": wknd_hours[3] if len(wknd_hours) >= 4 else 0,
                },
            }

    if len(hours) >= 6:
        # Complex 4+ zone tariff (e.g. A24: [1,5,7,13,16,21])
        # Map to three_zone by finding the two most important peaks
        # and base rate (most common or first/last rate)
        rate_hours = []
        prev = 0
        for i, h in enumerate(hours):
            rate_hours.append((rates[i], h - prev))
            prev = h
        rate_hours.append((rates[-1], 24 - prev))

        # Base rate = most common rate by hours
        rate_hour_map = {}
        for r, h in rate_hours:
            rate_hour_map[r] = rate_hour_map.get(r, 0) + h
        base_rate = max(rate_hour_map, key=rate_hour_map.get)

        # Find peak segments (rates above base)
        peak_segments = []
        prev = 0
        for i, h in enumerate(hours):
            if rates[i] != base_rate:
                peak_segments.append((prev, h, rates[i]))
            prev = h
        if rates[-1] != base_rate:
            peak_segments.append((prev, 24, rates[-1]))

        # Sort by rate descending to get the two highest peaks
        peak_segments.sort(key=lambda x: x[2], reverse=True)

        if len(peak_segments) >= 2:
            # Two peaks
            p1 = peak_segments[0]
            p2 = peak_segments[1]
            # Sort by start hour
            if p1[0] > p2[0]:
                p1, p2 = p2, p1
            return {
                "tariffType": "three_zone",
                "flatRate": round(sum(r * h for r, h in rate_hours) / 24, 1),
                "dayRate": p1[2],
                "nightRate": base_rate,
                "peakRate": max(p1[2], p2[2]),
                "partialRate": min(p1[2], p2[2]),
                "offPeakRate": base_rate,
                "distribution": base_rate,
                "weekday": {
                    "peak1Start": p1[0],
                    "peak1End": p1[1],
                    "peak2Start": p2[0],
                    "peak2End": p2[1],
                },
                "weekend": {
                    "peak1Start": 0,
                    "peak1End": 0,
                    "peak2Start": 0,
                    "peak2End": 0,
                },
            }
        elif len(peak_segments) == 1:
            p = peak_segments[0]
            return {
                "tariffType": "two_zone",
                "flatRate": round(sum(r * h for r, h in rate_hours) / 24, 1),
                "dayRate": p[2],
                "nightRate": base_rate,
                "peakRate": p[2],
                "partialRate": base_rate,
                "offPeakRate": base_rate,
                "distribution": base_rate,
                "weekday": {"dayStart": p[0], "dayEnd": p[1]},
                "weekend": {"dayStart": 0, "dayEnd": 0},
            }

    # Fallback: treat as flat with average rate
    avg = round(sum(rates) / len(rates), 1)
    return {
        "tariffType": "flat",
        "flatRate": avg,
        "dayRate": avg,
        "nightRate": avg,
        "peakRate": avg,
        "partialRate": avg,
        "offPeakRate": avg,
        "distribution": avg,
        "weekday": {},
        "weekend": {},
    }


def main():
    if not os.path.isdir(PAGRA_BASE):
        print(f"ERROR: PAGRA data directory not found: {PAGRA_BASE}")
        sys.exit(1)

    result = {
        "version": "2026-Q1",
        "source": "PAGRA-Galileo 2026 + _taryfy_2025.py",
        "commonFees": {
            "ozeFee": 7.0,
            "cogenerationFee": 10.0,
            "exciseTax": 5.0
        },
        "operators": {}
    }

    total_tariffs = 0

    for operator in ["PGE", "Tauron", "Enea", "Energa"]:
        groups = INCLUDE_GROUPS[operator]
        operator_dir = os.path.join(PAGRA_BASE, operator)

        if not os.path.isdir(operator_dir):
            print(f"WARNING: Operator directory not found: {operator_dir}")
            continue

        tariffs = {}

        for group in groups:
            json_path = os.path.join(operator_dir, f"{group}.json")

            if not os.path.isfile(json_path):
                print(f"WARNING: Tariff file not found: {json_path}")
                continue

            # Read PAGRA JSON
            with open(json_path, "r", encoding="utf-8") as f:
                pagra_data = json.load(f)

            # Analyze schedule
            schedule = analyze_schedule(pagra_data)

            # Get fixed fees
            voltage = group[0]
            fees = FIXED_FEES.get(operator, {}).get(group)
            if not fees:
                print(f"WARNING: No fixed fees for {operator}/{group}, skipping")
                continue

            staly_pln_mw, przej_pln_kw, jakosc, abonament = fees

            # Convert staly from PLN/MW/month to PLN/kW/month
            staly_pln_kw = round(staly_pln_mw / 1000, 2)

            desc = TARIFF_DESCRIPTIONS.get(group, group)

            tariff_entry = {
                "label": f"{group} \u2014 {desc}",
                "voltage": voltage,
                "tariffType": schedule["tariffType"],
                "fixedFees": {
                    "distFixedRatePerKwMonth": staly_pln_kw,
                    "transitionFeeMonth": przej_pln_kw,
                    "osdSubscriptionFeeMonth": abonament
                },
                "variableFees": {
                    "qualityFee": jakosc,
                    "distribution": schedule["distribution"]
                },
                "touRates": {
                    "flatRate": schedule["flatRate"],
                    "dayRate": schedule["dayRate"],
                    "nightRate": schedule["nightRate"],
                    "peakRate": schedule["peakRate"],
                    "partialRate": schedule["partialRate"],
                    "offPeakRate": schedule["offPeakRate"],
                    "weekday": schedule["weekday"],
                    "weekend": schedule["weekend"]
                }
            }

            tariffs[group] = tariff_entry
            total_tariffs += 1
            print(f"  {operator}/{group}: {schedule['tariffType']}, "
                  f"dist={schedule['distribution']}, peak={schedule['peakRate']}, "
                  f"staly={staly_pln_kw} PLN/kW/mc")

        result["operators"][operator] = {
            "label": OPERATOR_LABELS[operator],
            "tariffs": tariffs
        }

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated {OUTPUT_PATH}")
    print(f"Total tariffs: {total_tariffs}")


if __name__ == "__main__":
    main()
