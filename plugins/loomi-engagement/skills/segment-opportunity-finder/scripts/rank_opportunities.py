#!/usr/bin/env python3
"""Rank audience opportunities from Bloomreach Engagement by value x reachability.

Usage:
    python3 rank_opportunities.py opportunities.json [--format markdown|json]

opportunities.json:
{
  "as_of": "2026-10-08",
  "aov": 95.0,                       # default order value, used when a row has none
  "opportunities": [
    {
      "id": "P6",                    # pattern ID from references/opportunity-patterns.md
      "name": "Cart abandoners not contacted (7 days)",
      "size": 10000,                 # aggregate EQL count (all rows added up)
      "reachable": 200,              # optional: count that can be messaged (contact + consent)
      "onsite": true,                # optional: can be reached on-site (web layer) when not messageable
      "value_per_conversion": 110.0, # optional: overrides the pattern's default value basis (below)
      "avg_cart_value": 110.0,       # optional, P6: average cart value
      "category_aov": 80.0,          # optional, P1 and P5: the category's AOV
      "discount_depth": 0.2,         # P4: discount moved away from (0.2 or "20%")
      "response_rate": 0.05,         # optional: overrides the pattern default
      "period_multiplier": 4.3,      # optional: e.g. a weekly audience refills ~4.3 times a month
      "coverage": "none",            # none | partial | covered | inactive
      "kind": "revenue"              # revenue (default) | margin | long_term
    }
  ]
}

Default value per conversion, by pattern (references/value-and-ranking.md):
    P1, P5  category_aov (store AOV if not given, noted)
    P2, P7  AOV
    P3      AOV x 1.5
    P4      AOV x discount_depth (margin protected; no value without discount_depth)
    P6      avg_cart_value (store AOV if not given, noted)
    P8      0.5 x AOV (12-month value of a messageable customer)
    other   AOV
Numbers may be strings ("1,200", "$95", "20%").

For each row:
    reach         = reachable / size (1.0 if "reachable" is missing; flagged as an assumption)
    value         = size x response_rate x value_per_conversion x period_multiplier
    reachable_val = value x reach, plus an on-site share for the unreachable rest
    score         = reachable_val x coverage factor

The on-site share uses onsite_rate_factor (default 0.2): on-site messages convert at
about a fifth of the rate of email in the default assumptions. Coverage factors:
none 1.0, inactive 0.9 (a flow exists but is off), partial 0.5, covered 0.1.

All values are estimates over the next 30 days unless a period_multiplier says
otherwise. Standard library only; no network access.
"""
import argparse
import json
import math
import sys

DEFAULT_RATES = {
    "P1": 0.02,   # browsed a category, never bought it
    "P2": 0.05,   # one-time buyers in their repeat window
    "P3": 0.10,   # VIP slowdown
    "P4": 0.10,   # discount-led buyers: share moved to a smaller or no discount
    "P5": 0.03,   # category affinity x trending search demand
    "P6": 0.05,   # cart abandoners not contacted
    "P7": 0.08,   # new customers without a second purchase
    "P8": 0.10,   # consent capture rate
}
COVERAGE = {"none": 1.0, "inactive": 0.9, "partial": 0.5, "covered": 0.1}

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


def default_value(pid, o, aov, notes):
    """Value per conversion from the pattern's value basis, when the row gives none."""
    def given(key, label):
        v = num(o.get(key))
        if v is None:
            notes.append(f"store AOV ({label} not given)")
            return aov
        return v

    if pid in ("P1", "P5"):
        return given("category_aov", "category AOV")
    if pid == "P6":
        return given("avg_cart_value", "average cart value")
    if pid == "P3":
        notes.append("AOV × 1.5")
        return aov * 1.5
    if pid == "P4":
        depth = num(o.get("discount_depth"))
        if depth is None:
            notes.append("no value: discount_depth missing")
            return 0.0
        depth = depth / 100 if depth > 1 else depth
        notes.append(f"AOV × {depth:.0%} discount")
        return aov * depth
    if pid == "P8":
        notes.append("0.5 × AOV per consent")
        return aov * 0.5
    notes.append("store AOV")
    return aov


def money(x):
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def sig2(n):
    if not n:
        return 0
    digits = 2 - int(math.floor(math.log10(abs(n)))) - 1
    return round(n, digits)


def score_row(o, default_aov, onsite_factor):
    notes = []
    size = int(num(o.get("size")) or 0)
    pid = str(o.get("id", "")).upper()
    rate = num(o.get("response_rate"))
    if rate is not None and rate > 1:
        rate /= 100  # "5%" or 5 means 5%
    if rate is None:
        rate = DEFAULT_RATES.get(pid, 0.03)
        notes.append(f"default rate {rate:.0%}")
    vpc = num(o.get("value_per_conversion"))
    if vpc is None:
        vpc = default_value(pid, o, default_aov, notes)
    mult = num(o.get("period_multiplier"))
    mult = 1.0 if mult is None else mult
    reachable = num(o.get("reachable"))
    if reachable is not None and size:
        reach = max(0.0, min(1.0, reachable / size))
    else:
        reach = 1.0 if size else 0.0
        notes.append("reachability not measured")
    coverage = str(o.get("coverage", "none")).lower()
    cov = COVERAGE.get(coverage, 1.0)
    value = size * rate * float(vpc or 0) * mult
    onsite_share = (1 - reach) * onsite_factor if o.get("onsite") else 0.0
    reachable_val = value * (reach + onsite_share)
    score = reachable_val * cov
    if size < 100:
        notes.append("under 100 customers: treat as indicative")
    return {
        "id": pid,
        "name": o.get("name", pid),
        "size": size,
        "reach": reach,
        "value": value,
        "reachable_value": reachable_val,
        "coverage": coverage,
        "score": score,
        "kind": o.get("kind", "revenue"),
        "notes": notes,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--onsite-rate-factor", type=float, default=0.2)
    args = ap.parse_args()
    with open(args.path, encoding="utf-8") as f:
        d = json.load(f)
    aov = num(d.get("aov"))
    if aov is None:
        print("Warning: no store AOV given; values that need it count as 0.", file=sys.stderr)
        aov = 0.0
    rows = [score_row(o, aov, args.onsite_rate_factor) for o in d.get("opportunities", [])]
    rows.sort(key=lambda r: r["score"], reverse=True)

    if args.format == "json":
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0

    print(f"Opportunities ranked by value x reachability (as of {d.get('as_of', 'unknown')})\n")
    print("| Rank | ID | Opportunity | Size | Reachable | Est. value (30 days) | Reachable value | Coverage | Score | Notes |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        label = {"margin": " (margin)", "long_term": " (12-month, consent)"}.get(r["kind"], "")
        print(
            f"| {i} | {r['id']} | {r['name']}{label} | ~{sig2(r['size']):,} | {r['reach']:.0%} | "
            f"{money(sig2(r['value']))} | {money(sig2(r['reachable_value']))} | {r['coverage']} | {money(sig2(r['score']))} | "
            f"{'; '.join(r['notes']) or '—'} |"
        )
    print("\nEstimates, not forecasts: size x response rate x value per conversion, "
          "scaled by the reachable share. Coverage factors: none 1.0, inactive 0.9, partial 0.5, covered 0.1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
