#!/usr/bin/env python3
"""Turn win-back EQL counts into a revenue-at-stake table.

Standard library only. No network access. It only reshapes numbers the
assistant has already fetched with aggregate EQL queries.

Usage:
    python3 winback_calc.py grid.json
    python3 winback_calc.py --example        # print an example input file

Input JSON:
{
  "aov": 80.0,
  "currency": "$",
  "aov_source": "EQL 30-day average",            # optional
  "bands": [
    {"band": "0-30",    "total": 25000, "tier_2_3": 6000, "tier_4_plus": 3000},
    {"band": "31-90",   "total": 18000, "tier_2_3": 4000, "tier_4_plus": 1500, "coverage": "covered"},
    {"band": "91-180",  "total": 10000, "tier_2_3": 2200, "tier_4_plus": 800},
    {"band": "181-365", "total": 15000, "tier_2_3": 2500, "tier_4_plus": 600},
    {"band": "365+",    "total": 60000, "tier_2_3": 7000, "tier_4_plus": 1200}
  ],
  "assumptions": {                                 # all optional overrides
    "orders_for_value": [1, 2.5, 5],
    "orders_per_year_if_retained": [0.5, 1, 2],
    "winback_rate": {"31-90": 0.12, "91-180": 0.07, "181-365": 0.04, "365+": 0.015}
  }
}

"coverage" is one of "covered", "partly covered" or "uncovered" (the default).
Any row whose band starts at 0 is treated as active and gets no revenue at stake.
Band labels match the win-back rates whatever the dash ("31-90", "31–90",
"31 – 90"). Counts may be strings ("18,000").
"""
import argparse
import json
import math
import re
import sys

DEFAULTS = {
    "orders_for_value": [1, 2.5, 5],
    "orders_per_year_if_retained": [0.5, 1, 2],
    "winback_rate": {"31-90": 0.12, "91-180": 0.07, "181-365": 0.04, "365+": 0.015},
}

EXAMPLE = {
    "aov": 80.0,
    "currency": "$",
    "aov_source": "illustrative",
    "bands": [
        {"band": "0-30", "total": 25000, "tier_2_3": 6000, "tier_4_plus": 3000},
        {"band": "31-90", "total": 18000, "tier_2_3": 4000, "tier_4_plus": 1500, "coverage": "covered"},
        {"band": "91-180", "total": 10000, "tier_2_3": 2200, "tier_4_plus": 800},
        {"band": "181-365", "total": 15000, "tier_2_3": 2500, "tier_4_plus": 600},
        {"band": "365+", "total": 60000, "tier_2_3": 7000, "tier_4_plus": 1200},
    ],
}


NA = {"", "na", "n/a", "-", "—", "null"}


def num(x):
    """Number or None. Strings may carry $ £ €, thousands commas or a trailing %."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    if not isinstance(x, str):
        return None
    s = x.strip()
    if s.lower() in NA:
        return None
    for ch in ",$£€":
        s = s.replace(ch, "")
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def band_key(band):
    """Normalise a band label so "31–90", "31 - 90" and "31-90" match."""
    return re.sub(r"\s+", "", re.sub(r"[\u2010-\u2015\u2212]", "-", str(band)))


def money(x, cur):
    if x is None:
        return "—"
    # Round first, then pick the unit, so 999,600 shows as 1.0M rather than 1000k.
    if round(x / 1000) >= 1000:
        return f"{cur}{round(x / 1_000_000, 1):,.1f}M"
    if round(x) >= 10_000:
        return f"{cur}{round(x / 1000):,.0f}k"
    return f"{cur}{x:,.0f}"


def count(n):
    if n >= 10_000:
        return f"~{round(n, -2):,.0f}"
    return f"{n:,}"


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description="Turn win-back EQL counts into a revenue-at-stake table (Markdown).",
                                 epilog="Run with --example to see the input format.")
    ap.add_argument("grid", nargs="?", help="JSON file of counts per recency band")
    ap.add_argument("--example", action="store_true", help="print an example input file and exit")
    args = ap.parse_args(argv[1:])
    if args.example:
        print(json.dumps(EXAMPLE, indent=2))
        return 0
    if not args.grid:
        ap.error("give a grid JSON file, or --example")
    with open(args.grid, encoding="utf-8") as f:
        data = json.load(f)

    a = dict(DEFAULTS)
    a.update(data.get("assumptions") or {})
    rates = dict(DEFAULTS["winback_rate"])
    rates.update((data.get("assumptions") or {}).get("winback_rate") or {})
    rates = {band_key(k): num(v) for k, v in rates.items()}
    ov, oy = a["orders_for_value"], a["orders_per_year_if_retained"]
    aov = num(data.get("aov"))
    if aov is None:
        sys.exit("aov is missing or not a number: ask the user for their average order value")
    cur = data.get("currency", "")

    print("| Days since last purchase | Customers | 1 order | 2–3 | 4+ | Avg historical value | "
          "Revenue at stake (12 mo) | Win-back rate | Recoverable | Coverage |")
    print("|---|---|---|---|---|---|---|---|---|---|")

    all_buyers = 0
    open_total = covered_total = 0.0
    warnings = []
    for row in data["bands"]:
        band = row["band"]
        n = int(num(row.get("total")) or 0)
        t23 = int(num(row.get("tier_2_3")) or 0)
        t4 = int(num(row.get("tier_4_plus")) or 0)
        for key in ("total", "tier_2_3", "tier_4_plus"):
            if num(row.get(key)) is None:
                warnings.append(f"{band}: {key} is missing; counted as 0")
        t1 = n - t23 - t4
        all_buyers += n
        if t1 < 0:
            warnings.append(f"{band}: tiers add up to more than the band total; check the queries")
            t1 = 0
        active = band.strip().startswith("0")
        value = aov * (t1 * ov[0] + t23 * ov[1] + t4 * ov[2]) / n if n else None
        at_stake = None if active else aov * (t1 * oy[0] + t23 * oy[1] + t4 * oy[2])
        rate = None if active else rates.get(band_key(band))
        if not active and rate is None:
            warnings.append(f"{band}: no win-back rate given; add it under assumptions.winback_rate")
        recoverable = at_stake * rate if (at_stake is not None and rate is not None) else None
        coverage = "active" if active else row.get("coverage", "uncovered")
        if recoverable:
            if coverage == "covered":
                covered_total += recoverable
            else:
                open_total += recoverable
        print(f"| {band} | {count(n)} | {count(t1)} | {count(t23)} | {count(t4)} | {money(value, cur)} | "
              f"{money(at_stake, cur)} | {'—' if rate is None else f'{rate:.1%}'} | "
              f"{money(recoverable, cur)} | {coverage} |")

    print()
    print(f"All buyers (sum of bands): {all_buyers:,}")
    print(f"Recoverable in uncovered or partly covered bands: {money(open_total, cur)}")
    print(f"Recoverable in bands already covered: {money(covered_total, cur)}")
    print()
    print("Assumptions:")
    print(f"- AOV {cur}{aov:,.2f} ({data.get('aov_source', 'source not given')})")
    print(f"- Orders per customer for historical value (1 / 2–3 / 4+ tiers): {ov}")
    print(f"- Orders per year if retained (1 / 2–3 / 4+ tiers): {oy}")
    print(f"- Win-back rates: {', '.join(f'{k} {v:.1%}' for k, v in rates.items())}")
    print("- Estimates built on these assumptions, not forecasts.")
    for w in warnings:
        print(f"WARNING: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
