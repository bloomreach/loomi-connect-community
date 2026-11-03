#!/usr/bin/env python3
"""Estimate how long a Discovery A/B test needs to run.

Uses the standard two-proportion sample-size formula (two-sided 5% significance,
80% power) for a rate metric such as conversion rate or add-to-cart rate.
Revenue metrics (RPV, AOV) are noisier, so treat the result as a minimum for them.

Standard library only. No network access.

Usage:
    python3 scripts/estimate_duration.py --baseline-rate 0.105 --visits 14790 --days 90 \
        [--relative-lift 0.10] [--buckets 2] [--traffic 100]

--visits and --days give the query's recent traffic (from
get_discovery_query_performance), for example 14,790 visits over 90 days.
"""
import argparse
import math
import sys


def per_bucket(p, rel_lift, z_alpha=1.96, z_beta=0.84):
    p2 = p * (1 + rel_lift)
    if not (0 < p < 1 and 0 < p2 < 1):
        raise SystemExit("baseline rate and lifted rate must both be between 0 and 1")
    pbar = (p + p2) / 2
    num = (z_alpha * math.sqrt(2 * pbar * (1 - pbar)) + z_beta * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p) ** 2)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline-rate", type=float, required=True, help="e.g. 0.105 for a 10.5%% conversion rate")
    ap.add_argument("--visits", type=float, required=True, help="visits to the query in the period")
    ap.add_argument("--days", type=float, required=True, help="length of that period in days")
    ap.add_argument("--buckets", type=int, default=2)
    ap.add_argument("--traffic", type=float, default=100, help="percentage of eligible traffic in the test")
    ap.add_argument("--relative-lift", type=float, action="append",
                    help="lift to detect, e.g. 0.10 for +10%% (repeatable; default 0.05, 0.10, 0.20)")
    args = ap.parse_args()

    lifts = args.relative_lift or [0.05, 0.10, 0.20]
    daily = args.visits / args.days * args.traffic / 100 / args.buckets
    print(f"Visits per bucket per day: about {daily:,.0f} "
          f"({args.buckets} buckets, {args.traffic:g}% of traffic in the test).\n")
    print("| Lift to detect | Visits per bucket | Days needed |")
    print("|---|---|---|")
    for lift in lifts:
        n = per_bucket(args.baseline_rate, lift)
        days = n / daily if daily else float("inf")
        print(f"| +{lift:.0%} | {n:,} | {math.ceil(days):,} |")
    print("\nRun for at least 14 days, and in whole weeks, so weekday and weekend shoppers are both covered.")


if __name__ == "__main__":
    main()
