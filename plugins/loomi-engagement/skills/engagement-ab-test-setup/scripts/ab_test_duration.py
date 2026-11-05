#!/usr/bin/env python3
"""Estimate how many customers, and how many days, an A/B split in an Engagement scenario needs.

Uses the two-proportion sample-size formula (two-sided significance and power from references/rules.json, the
same approach as discovery-experiment-setup's estimate_duration.py), generalised to an uneven split such as a
90/10 holdout. The metric is a rate: conversion, click or purchase within the attribution window. Revenue metrics
are noisier, so treat the result as a minimum for them.

Usage:
  python3 ab_test_duration.py --baseline-rate 0.04 --entrants 12600 --days 30 [--control-share 50]
         [--variant-share 50] [--relative-lift 0.10 ...] [--out result.json]

--entrants and --days give how many customers reached the split point in a recent period (for example 12,600 in
30 days). --baseline-rate is the control's rate (0.04 = 4%). Shares are percentages and must add up to 100.

Standard library only. No network access.
"""
import argparse
import json
import math
import sys
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"{RULES_PATH}: can't read the rules ({e}).")


def total_needed(p, lift, w_control, w_variant, z_alpha, z_beta):
    """Customers needed in total, split w_control / w_variant (fractions adding to 1), to detect a relative lift."""
    p2 = p * (1 + lift)
    if not (0 < p < 1 and 0 < p2 < 1):
        return None
    pbar = w_control * p + w_variant * p2
    spread = math.sqrt(pbar * (1 - pbar) * (1 / w_control + 1 / w_variant))
    noise = math.sqrt(p * (1 - p) / w_control + p2 * (1 - p2) / w_variant)
    return math.ceil((z_alpha * spread + z_beta * noise) ** 2 / (p2 - p) ** 2)


def estimate(a, rules):
    if not 0 < a.baseline_rate < 1:
        fail("--baseline-rate must be between 0 and 1 (0.04 for 4%).")
    if a.entrants < 0 or a.days <= 0:
        fail("--entrants must be 0 or more and --days more than 0.")
    if abs(a.control_share + a.variant_share - 100) > 1e-9:
        fail("--control-share and --variant-share must add up to 100.")
    floor = rules["min_variant_percentage"]
    if min(a.control_share, a.variant_share) < floor:
        fail(f"Each share must be at least min_variant_percentage ({floor}) in references/rules.json.")
    wc, wv = a.control_share / 100, a.variant_share / 100
    daily = a.entrants / a.days
    lifts = sorted(set(a.relative_lift or rules["relative_lifts"]))
    rows = []
    for lift in lifts:
        if lift <= 0:
            fail("--relative-lift must be more than 0 (0.10 for +10%).")
        n = total_needed(a.baseline_rate, lift, wc, wv, rules["z_alpha"], rules["z_beta"])
        if n is None:
            rows.append({"lift": lift, "total": None, "control": None, "variant": None, "days": None,
                         "note": "the lifted rate would reach 100%"})
            continue
        days = math.ceil(n / daily) if daily else None
        rec = None if days is None else max(rules["min_test_days"], math.ceil(days / 7) * 7)
        rows.append({"lift": lift, "total": n, "control": math.ceil(n * wc), "variant": math.ceil(n * wv),
                     "days": days, "recommended_days": rec})
    sized = [r for r in rows if r["days"] is not None]
    practical = bool(sized) and min(r["days"] for r in sized) <= rules["max_test_weeks"] * 7
    return {"ok": True, "baseline_rate": a.baseline_rate, "entrants_per_day": round(daily, 2),
            "control_share": a.control_share, "variant_share": a.variant_share, "rows": rows,
            "practical": practical, "min_test_days": rules["min_test_days"], "max_test_weeks": rules["max_test_weeks"]}


def render(r):
    out = [f"Customers reaching the split: about {r['entrants_per_day']:,.0f} a day; split "
           f"{r['control_share']:g}/{r['variant_share']:g}; control rate {r['baseline_rate']:.2%}.", "",
           "| Lift to detect | Customers needed (control / variant) | Days needed | Run for |", "|---|---|---|---|"]
    for row in r["rows"]:
        if row["total"] is None:
            out.append(f"| +{row['lift']:.0%} | {row['note']} | | |")
        elif row["days"] is None:
            out.append(f"| +{row['lift']:.0%} | {row['total']:,} ({row['control']:,} / {row['variant']:,}) | "
                       "never: no customers reach the split | |")
        else:
            out.append(f"| +{row['lift']:.0%} | {row['total']:,} ({row['control']:,} / {row['variant']:,}) | "
                       f"{row['days']:,} | {row['recommended_days']:,} days |")
    out.append("")
    out.append(f"Run for at least {r['min_test_days']} days, in whole weeks.")
    if not r["practical"]:
        out.append(f"Even the largest lift needs more than {r['max_test_weeks']} weeks: too few customers reach this "
                   "step for a test. Test earlier in the flow, use an even split, or decide without a test.")
    return "\n".join(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    rules = load_rules()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline-rate", type=float, required=True, help="the control's rate, e.g. 0.04 for 4%%")
    ap.add_argument("--entrants", type=float, required=True, help="customers who reached the split point in the period")
    ap.add_argument("--days", type=float, required=True, help="length of that period in days")
    ap.add_argument("--control-share", type=float, default=50, help="control's share of traffic, percent (default 50)")
    ap.add_argument("--variant-share", type=float, default=50,
                    help="the variant's (or holdout's) share, percent (default 50)")
    ap.add_argument("--relative-lift", type=float, action="append",
                    help="lift to detect, e.g. 0.10 for +10%% (repeatable; default relative_lifts in rules.json)")
    ap.add_argument("--out", help="also write the result as JSON to this file")
    a = ap.parse_args()
    r = estimate(a, rules)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(r, indent=2, ensure_ascii=False) + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write it ({e}).")
    print(render(r))


if __name__ == "__main__":
    main()
