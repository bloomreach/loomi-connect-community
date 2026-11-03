#!/usr/bin/env python3
"""Summarise a saved get_discovery_experiment_report response.

The report response is large (often 150,000+ characters), because it has a
day-by-day series for every metric. This script reads the saved JSON and prints
a short Markdown summary: per-bucket totals, lift, confidence, how many days have
data, how confidence moved over time, and a verdict for the success metric.

Standard library only. No network access.

Usage:
    python3 scripts/summarise_report.py REPORT.json --control "Test Bucket A" \
        --metric rpv [--threshold 0.95]

--metric is one of: cr, rpv, aov, atc_rate. It accepts the experiment's
successMetric text too, for example "RPV - Revenue Per Visit", and plain
wording such as "Conversion Rate" or "add-to-cart rate".
"""
import argparse
import json
import math
import re
import sys

METRICS = {
    "cr": "Conversion rate",
    "rpv": "Revenue per visit",
    "aov": "Average order value",
    "atc_rate": "Add-to-cart rate",
}
PROPORTION_METRICS = {"cr", "atc_rate"}


def load(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, dict) and "result" in doc and "data" not in doc:
        doc = doc["result"]
    if isinstance(doc, dict) and doc.get("success") is False:
        sys.exit(f"{path}: Loomi Connect returned an error: {doc.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    return doc["data"]


PLAIN = {
    "conversionrate": "cr", "conversion": "cr", "cvr": "cr",
    "revenuepervisit": "rpv", "revenuepervisitor": "rpv",
    "averageordervalue": "aov", "ordervalue": "aov",
    "addtocartrate": "atc_rate", "addtocart": "atc_rate", "atcrate": "atc_rate", "cartrate": "atc_rate",
}


def metric_key(text):
    t = text.strip().lower()
    for key in ("atc_rate", "rpv", "aov", "cr"):
        if t == key or t.startswith(key.replace("_rate", "") + " ") or t.startswith(key + " "):
            return key
    if t.startswith("atc"):
        return "atc_rate"
    plain = re.sub(r"[^a-z]", "", t)
    if plain in PLAIN:
        return PLAIN[plain]
    sys.exit(f"Unknown metric {text!r}; use one of {', '.join(METRICS)} (or plain wording such as 'Conversion Rate')")


def pct(x):
    return "n/a" if x is None else f"{x * 100:.2f}%"


def money(x):
    return "n/a" if x is None else f"{x:,.2f}"


def required_per_bucket(p, rel_lift, z_alpha=1.96, z_beta=0.84):
    """Visits per bucket to detect a relative lift in a rate (two-sided 5%, 80% power)."""
    if not p or not rel_lift:
        return None
    p2 = p * (1 + rel_lift)
    if not 0 < p2 < 1:
        return None
    pbar = (p + p2) / 2
    num = (z_alpha * math.sqrt(2 * pbar * (1 - pbar)) + z_beta * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p) ** 2)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--control", required=True, help="control bucket name")
    ap.add_argument("--metric", required=True, help="success metric: cr, rpv, aov or atc_rate")
    ap.add_argument("--threshold", type=float, default=0.95, help="confidence needed to call a result (default 0.95)")
    args = ap.parse_args()

    data = load(args.report)
    key = metric_key(args.metric)
    buckets = data.get("overalldata", {}).get("buckets", {})
    if args.control not in buckets:
        sys.exit(f"Control bucket {args.control!r} not found; buckets are {list(buckets)}")

    daily = data.get("dayWisedata", {}).get("dailyMetrics", {})
    visits_series = daily.get("visits", [])
    days_with_data = sum(1 for d in visits_series if any(v for v in d["values"]["dailyValues"].values()))
    total_visits = sum(b.get("visits", 0) for b in buckets.values())

    print(f"## Report summary (success metric: {METRICS[key]})\n")
    if total_visits == 0:
        print("**No data.** Every bucket has 0 visits for this date range. Check the dates and the session type "
              "(SEARCH, CATEGORY or GLOBAL), and note that old experiments may be outside the data retention window.")
        return

    first = visits_series[0]["date"] if visits_series else "?"
    last = visits_series[-1]["date"] if visits_series else "?"
    print(f"Dates in the report: {first} to {last}; {days_with_data} of {len(visits_series)} days have visits.\n")

    print("| Bucket | Visits | Orders | Conv. rate | ATC rate | AOV | RPV | Lift on metric | Confidence |")
    print("|---|---|---|---|---|---|---|---|---|")
    order = [args.control] + [b for b in buckets if b != args.control]
    for name in order:
        b = buckets[name]
        lift = b.get("lift", {}).get(key)
        conf = b.get("confidenceValues", {}).get(key)
        label = f"{name} (control)" if name == args.control else name
        print(f"| {label} | {b.get('visits', 0):,} | {b.get('orders', 0):,} | {pct(b.get('cr'))} | {pct(b.get('atc_rate'))} "
              f"| {money(b.get('aov'))} | {money(b.get('rpv'))} | {'—' if name == args.control else pct(lift)} "
              f"| {'n/a' if conf is None else f'{conf:.0%}'} |")

    # Confidence trend for the success metric.
    series = daily.get(key, [])
    with_conf = [d for d in series if d["values"].get("cumulativeConfidence")]
    if with_conf:
        print("\nConfidence over time (cumulative, test buckets):")
        n = len(with_conf)
        for frac in (0.25, 0.5, 0.75, 1.0):
            d = with_conf[max(0, math.ceil(n * frac) - 1)]
            cc = d["values"]["cumulativeConfidence"]
            parts = ", ".join(f"{k} {v:.0%}" for k, v in cc.items() if k != args.control)
            print(f"- {d['date']}: {parts}")

    # Verdict.
    confs = {n: buckets[n].get("confidenceValues", {}).get(key) for n in buckets}
    print("\n### Verdict")
    if all(not c for c in confs.values()):
        print("Confidence was **not calculated** (all values are 0 or missing). This usually means too little data. "
              "Treat the result as inconclusive.")
    else:
        best = max(confs, key=lambda n: confs[n] or 0)
        if (confs[best] or 0) >= args.threshold:
            print(f"**Conclusive:** {best} is best on {METRICS[key].lower()} with {confs[best]:.0%} confidence "
                  f"(threshold {args.threshold:.0%}).")
        else:
            print(f"**Inconclusive:** the leading bucket is {best} at {confs[best]:.0%} confidence, "
                  f"below the {args.threshold:.0%} threshold.")

    # Sample size for rate metrics.
    if key in PROPORTION_METRICS:
        ctrl = buckets[args.control]
        p = ctrl.get(key)
        for name in order[1:]:
            lift = buckets[name].get("lift", {}).get(key)
            need = required_per_bucket(p, lift) if lift else None
            have = buckets[name].get("visits", 0)
            if need and need > 20 * max(have, 1):
                print(f"- The observed {pct(lift)} lift for {name} is too small to confirm at this traffic: it would "
                      f"need more than 20 times the visits collected so far. Treat it as no real difference.")
            elif need:
                print(f"- To detect the observed {pct(lift)} lift for {name} reliably needs about {need:,} visits per "
                      f"bucket; it has {have:,} ({have / need:.0%} of that).")
        need10 = required_per_bucket(p, 0.10)
        if need10:
            print(f"- For reference, detecting a 10% relative lift needs about {need10:,} visits per bucket.")


if __name__ == "__main__":
    main()
