#!/usr/bin/env python3
"""Turn repeat-purchase cohort counts into a cohort matrix, a time-to-second-order curve and approximate quartiles.

Standard library only. No network access. It only reshapes aggregate counts the
assistant has already fetched with EQL. Thresholds are in references/rules.json.

Usage:
  python3 cohort_matrix.py matrix.json --cutoffs 2026-04-01,2026-05-01,2026-06-01 [--period month]
                           [--data-end 2026-08-19] [--min-cohort 100] [--drop-share 0.5] [--out summary.json]
  python3 cohort_matrix.py cohorts.json [--out summary.json]
  python3 cohort_matrix.py --example        # print an example cohorts.json

Input is either:

1. The execute_analytics_eql response of the matrix query (pattern C1 in references/eql-patterns.md):
   one row per first-purchase month, whose header is the month start in Unix seconds, and whose
   values are [cohort size, repeaters by cutoff 1, repeaters by cutoff 2, ...]. Give the cutoff
   dates with --cutoffs, in the same order as the metrics. Wrapped responses ({"result": ...}) are fine.

2. A JSON file you put together from one query per cohort (pattern C2):
   {"period": "month",
    "cutoffs": ["2026-04-01", "2026-05-01", "2026-06-01"],
    "cohorts": [{"start": "2026-03-01", "size": 8429, "repeaters": [657, 1794, 2711]}]}
   A cohort may carry its own "cutoffs" list. Counts may be strings ("8,429"); use null for a cutoff not run.

"repeaters" are customers in the cohort with at least two orders by the cutoff (exclusive), counted
from the cohort's start, so they only ever grow. --period is the cohort length: month (calendar
months) or week (7 days from the start). Cutoffs must fall on a period boundary after the cohort
period ends (the first of a month, or a whole number of weeks) to enter the matrix; any other cutoff,
such as the last day with data, is reported as a partial cell and left out of the curve.

The pooled curve chains the second orders in each bucket across every cohort that has both ends of
the bucket, weighted by cohort size, so younger cohorts still count for the months they have.
Time to second order is measured from the middle of the cohort period, so the quartiles are
approximate: about half a period either way (about 15 days for monthly cohorts, 3.5 for weekly).

Row headers are local midnight in the project's time zone, which can be up to 14 hours either side
of UTC midnight. Monthly headers are shifted by two days and read as the 1st of that month, so every
zone from UTC-12 to UTC+14 lands in the right month. Weekly and daily headers are read as the date
13 hours later, which is right from UTC-10 to UTC+13; in other zones use a cohorts file instead.

Errors are printed as one line naming the file, with exit code 1.
"""
import argparse
import calendar
import datetime as dt
import json
import math
import sys
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
MISSING = {"", "null", "none", "n/a", "na", "nan", "-", "\u2212", "\u2013", "\u2014"}
# A monthly header is local midnight on the 1st, up to 14 hours either side of UTC midnight.
# Two days later is always inside the right month.
MONTH_SHIFT_SECONDS = 2 * 86400
# A weekly or daily header: 13 hours later lands on the right date from UTC-10 to UTC+13.
DAY_SHIFT_SECONDS = 13 * 3600


def fail(msg):
    """Stop with a one-line message on stderr and exit code 1, never a traceback."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_rules():
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        return rules, {"month": float(rules["days_per_month"]), "week": 7.0}
    except (OSError, ValueError, KeyError, TypeError) as e:
        fail(f"{RULES_PATH}: can't read the rules ({e}).")


RULES, PERIOD_DAYS = load_rules()

EXAMPLE = {
    "period": "month",
    "cutoffs": ["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"],
    "cohorts": [
        {"start": "2026-03-01", "size": 1200, "repeaters": [90, 250, 330, 380]},
        {"start": "2026-04-01", "size": 1000, "cutoffs": ["2026-05-01", "2026-06-01", "2026-07-01"],
         "repeaters": [80, 210, 280]},
    ],
}


def num(x):
    """Number or None. Strings may carry thousands commas."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        if s.lower() in MISSING:
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def parse_date(s, where):
    """YYYY-MM-DD, YYYY-MM or an ISO datetime (the date part is used, as UTC). `where` names the source in errors."""
    s = str(s).strip()
    if len(s) == 7:
        s += "-01"
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        fail(f"{where}: can't read the date {s!r}; use YYYY-MM-DD.")


def from_epoch(value, period):
    """A bucket header in Unix seconds (local midnight in the project's time zone) as a date."""
    v = num(value)
    if v is None:
        return None
    try:
        if period == "month":
            d = dt.datetime.fromtimestamp(v + MONTH_SHIFT_SECONDS, dt.timezone.utc).date()
            return d.replace(day=1)
        return dt.datetime.fromtimestamp(v + DAY_SHIFT_SECONDS, dt.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def period_end(start, period):
    return add_months(start, 1) if period == "month" else start + dt.timedelta(days=7)


def offset_of(start, cutoff, period):
    """Whole periods from the end of the cohort period to the cutoff, or None if not on a boundary."""
    end = period_end(start, period)
    if cutoff < end:
        return "early"
    if period == "week":
        days = (cutoff - end).days
        return days // 7 if days % 7 == 0 else None
    if cutoff.day != start.day:
        return None
    return (cutoff.year - end.year) * 12 + cutoff.month - end.month


def check_error(data, path):
    for o in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "The cohort counts couldn't be read; don't treat this as 'no repeat buyers'.")


def load(path, cutoffs_arg, period_arg):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        fail(f"{path}: can't read the file ({e.strerror or e}).")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fail(f"{path}: not valid JSON ({e}).")
    check_error(data, path)
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    warnings = []
    if isinstance(data, dict) and "cohorts" in data:
        period = period_arg or data.get("period") or "month"
        if period not in PERIOD_DAYS:
            fail(f"{path}: period {period!r} isn't one of {', '.join(sorted(PERIOD_DAYS))}.")
        if not isinstance(data["cohorts"], list) or not isinstance(data.get("cutoffs") or [], list):
            fail(f"{path}: \"cohorts\" and \"cutoffs\" must be lists (see --example).")
        shared = [parse_date(c, path) for c in (data.get("cutoffs") or [])]
        cohorts = []
        for c in data["cohorts"]:
            if not isinstance(c, dict) or c.get("start") is None:
                fail(f"{path}: every cohort needs a \"start\" date (see --example).")
            own = c.get("cutoffs")
            if own is not None and not isinstance(own, list):
                fail(f"{path}: cohort {c['start']}: \"cutoffs\" must be a list.")
            cuts = [parse_date(x, path) for x in own] if own else shared
            reps = c.get("repeaters") or []
            if not isinstance(reps, list):
                fail(f"{path}: cohort {c['start']}: \"repeaters\" must be a list.")
            if len(reps) != len(cuts):
                fail(f"{path}: cohort {c['start']}: {len(reps)} repeater counts but {len(cuts)} cutoffs.")
            cohorts.append({"start": parse_date(c["start"], path), "size": num(c.get("size")),
                            "cells": list(zip(cuts, (num(r) for r in reps)))})
        return period, cohorts, warnings
    rows = ((data.get("data") or {}).get("rows") if isinstance(data, dict) and isinstance(data.get("data"), dict)
            else None)
    if not isinstance(rows, list):
        fail(f"{path}: neither an execute_analytics_eql report response nor a cohorts file (see --help).")
    if not cutoffs_arg:
        fail(f"{path}: a raw EQL response needs --cutoffs: the cutoff dates, in the same order as the repeater metrics.")
    cuts = [parse_date(x, "--cutoffs") for x in cutoffs_arg.split(",") if x.strip()]
    period = period_arg or "month"
    cohorts = []
    for row in rows:
        if not isinstance(row, dict):
            fail(f"{path}: a row isn't an object; is this an execute_analytics_eql report response?")
        headers = row.get("headers") or [{}]
        header = headers[0] if isinstance(headers, list) and isinstance(headers[0], dict) else {}
        start = from_epoch(header.get("value"), period) if header.get("type") == "single" else None
        values = row.get("values") or []
        if not isinstance(values, list):
            fail(f"{path}: a row's \"values\" isn't a list.")
        if start is None:
            if any((num(v) or 0) for v in values):
                warnings.append("A row without a first-purchase date (null or 'other') was left out.")
            continue
        if len(values) != len(cuts) + 1:
            fail(f"{path}: row {start}: {len(values)} values, but expected 1 cohort size + {len(cuts)} cutoffs. "
                 "Check --cutoffs against the query's metrics.")
        if period == "month" and start.day != 1:
            warnings.append(f"Cohort {start} doesn't start on the 1st; check the time zone of the row headers.")
        cohorts.append({"start": start, "size": num(values[0]), "cells": list(zip(cuts, (num(v) for v in values[1:])))})
    return period, cohorts, warnings


def build(period, cohorts, data_end, min_cohort, drop_share):
    warnings, out_cohorts = [], []
    pdays = PERIOD_DAYS[period]
    for c in sorted(cohorts, key=lambda c: c["start"]):
        label = c["start"].strftime("%Y-%m") if period == "month" else c["start"].isoformat()
        if c["size"] is None:
            warnings.append(f"Cohort {label}: the cohort size is missing or not a number; the cohort was left out.")
            continue
        size = c["size"]
        cells, partial, last = {}, [], None
        for cut, rep in sorted(c["cells"], key=lambda x: x[0]):
            if rep is None:
                continue
            if data_end and cut > data_end:
                warnings.append(f"Cohort {label}: cutoff {cut} is after the data end ({data_end}); left out.")
                continue
            if last is not None and rep < last:
                warnings.append(f"Cohort {label}: repeaters fall from {last:g} to {rep:g} at {cut}. "
                                "Counts must be cumulative: check the metric order and the cutoffs.")
            if rep > size:
                warnings.append(f"Cohort {label}: {rep:g} repeaters by {cut} but only {size:g} in the cohort.")
            last = rep
            k = offset_of(c["start"], cut, period)
            if k == "early":
                continue
            if k is None:
                days = (cut - period_end(c["start"], period)).days
                partial.append({"cutoff": cut.isoformat(), "days_after_period": days, "repeaters": rep,
                                "rate": rep / size if size else None})
            else:
                cells[k] = rep
        if size < min_cohort:
            warnings.append(f"Cohort {label} has {size:g} customers (under {min_cohort:g}): its rates are noisy.")
        out_cohorts.append({"cohort": label, "start": c["start"].isoformat(), "size": size, "small": size < min_cohort,
                            "cumulative": {str(k): {"repeaters": v, "rate": v / size if size else None}
                                           for k, v in sorted(cells.items())},
                            "partial": partial, "_cells": cells})
    offsets = sorted({k for c in out_cohorts for k in c["_cells"]})
    curve, cum, prev = [], 0.0, None
    for k in offsets:
        sizes = reps = 0.0
        n = 0
        for c in out_cohorts:
            if k in c["_cells"] and (prev is None or prev in c["_cells"]) and c["size"]:
                sizes += c["size"]
                reps += c["_cells"][k] - (c["_cells"][prev] if prev is not None else 0)
                n += 1
        if not sizes:
            break
        inc = reps / sizes
        cum += inc
        length = (k - prev) if prev is not None else k + 0.5
        curve.append({"offset": k, "cohorts": n, "customers": sizes, "thin": sizes < min_cohort,
                      "second_orders_share": inc, "cumulative_rate": cum,
                      "rate_per_period": inc / length if length else None,
                      "days_since_first_order": round((k + 0.5) * pdays, 1)})
        prev = k
    result = {"period": period, "cohorts": [{k: v for k, v in c.items() if k != "_cells"} for c in out_cohorts],
              "curve": curve, "warnings": warnings,
              "rules": {"min_cohort_size": min_cohort, "drop_share_of_peak": drop_share}}
    if curve and curve[-1]["cumulative_rate"] > 0:
        total = curve[-1]["cumulative_rate"]
        for b in curve:
            b["share_of_repeaters"] = b["second_orders_share"] / total
        points = [(0.0, 0.0)] + [(b["days_since_first_order"], b["cumulative_rate"]) for b in curve]
        result["time_to_second_order_days"] = {
            q: round(quantile_days(points, total * share), 0) for q, share in (("p25", .25), ("median", .5), ("p75", .75))}
        result["horizon_days"] = curve[-1]["days_since_first_order"]
        result["precision_days"] = round(pdays / 2, 1)
        usable = [b for b in curve if not b["thin"] and b["rate_per_period"] is not None]
        if usable:
            peak = max(usable, key=lambda b: b["rate_per_period"])
            result["peak"] = {"offset": peak["offset"], "rate_per_period": peak["rate_per_period"]}
            after = [b for b in usable if b["offset"] > peak["offset"]]
            drop = next((b for b in after if b["rate_per_period"] <= drop_share * peak["rate_per_period"]), None)
            result["drop"] = None if drop is None else {
                "offset": drop["offset"], "rate_per_period": drop["rate_per_period"],
                "from_days": round(curve[curve.index(drop) - 1]["days_since_first_order"], 0)}
    return result


def quantile_days(points, target):
    for (d0, c0), (d1, c1) in zip(points, points[1:]):
        if c1 >= target:
            return d0 + (d1 - d0) * ((target - c0) / (c1 - c0) if c1 > c0 else 0)
    return points[-1][0]


def pct(x):
    return "" if x is None else f"{100 * x:.1f}%"


def report(r):
    unit = "M" if r["period"] == "month" else "W"
    word = "month" if r["period"] == "month" else "week"
    offsets = [b["offset"] for b in r["curve"]]
    print(f"Cumulative share of each cohort with a 2nd order by the end of {word} k after its first-order {word}:")
    head = f"{'cohort':<11}{'size':>9}" + "".join(f"{unit + str(k):>8}" for k in offsets)
    print(head)
    for c in r["cohorts"]:
        cells = "".join(f"{pct(c['cumulative'].get(str(k), {}).get('rate')):>8}" for k in offsets)
        print(f"{c['cohort']:<11}{c['size']:>9,.0f}{cells}" + ("  (small)" if c["small"] else ""))
        for p in c["partial"]:
            print(f"{'':<11}partial: {p['repeaters']:,.0f} ({pct(p['rate'])}) by {p['cutoff']}, "
                  f"{p['days_after_period']} days after the cohort {word}")
    if not r["curve"]:
        print("\nNo cutoff falls on a whole period after a cohort; nothing to pool.")
    else:
        print(f"\nPooled curve (weighted by cohort size):")
        print(f"{'bucket':<8}{'cohorts':>8}{'customers':>11}{'2nd orders':>12}{'cumulative':>12}{'per ' + word:>11}"
              f"{'of repeaters':>14}")
        for b in r["curve"]:
            print(f"{unit + str(b['offset']):<8}{b['cohorts']:>8}{b['customers']:>11,.0f}{pct(b['second_orders_share']):>12}"
                  f"{pct(b['cumulative_rate']):>12}{pct(b['rate_per_period']):>11}{pct(b.get('share_of_repeaters')):>14}"
                  + ("  (thin)" if b["thin"] else ""))
    if "time_to_second_order_days" in r:
        t = r["time_to_second_order_days"]
        print(f"\nTime to 2nd order, among customers who placed one within about {r['horizon_days']:.0f} days "
              f"(approximate, +/- {r['precision_days']:g} days): 25% by day {t['p25']:.0f}, "
              f"median day {t['median']:.0f}, 75% by day {t['p75']:.0f}.")
    if r.get("peak"):
        print(f"Peak: {unit}{r['peak']['offset']} ({pct(r['peak']['rate_per_period'])} of the cohort per {word}).")
        d = r.get("drop")
        if d:
            print(f"Drop: from {unit}{d['offset']} (after about day {d['from_days']:.0f}) the rate is "
                  f"{pct(d['rate_per_period'])} per {word}, at or below {r['rules']['drop_share_of_peak']:g} of the peak.")
        else:
            print("Drop: none within the horizon; second orders keep coming at a similar pace.")
    for w in r["warnings"]:
        print(f"WARNING: {w}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="execute_analytics_eql response or cohorts JSON")
    ap.add_argument("--cutoffs", help="comma-separated cutoff dates (YYYY-MM-DD), in metric order, for a raw EQL response")
    ap.add_argument("--period", choices=sorted(PERIOD_DAYS), help="cohort length (default month)")
    ap.add_argument("--data-end", help="first day with no data (YYYY-MM-DD); later cutoffs are left out")
    ap.add_argument("--min-cohort", type=float, default=RULES["min_cohort_size"],
                    help="cohorts (and pooled buckets) with fewer customers are marked small or thin "
                         "(default: min_cohort_size in references/rules.json)")
    ap.add_argument("--drop-share", type=float, default=RULES["drop_share_of_peak"],
                    help="the drop is the first bucket after the peak at or below this share of the peak pace "
                         "(default: drop_share_of_peak in references/rules.json)")
    ap.add_argument("--out", help="also write the summary as JSON to this path")
    ap.add_argument("--example", action="store_true", help="print an example cohorts.json and exit")
    a = ap.parse_args()
    if a.example:
        print(json.dumps(EXAMPLE, indent=2))
        return 0
    if not a.input:
        ap.error("give an input file, or --example")
    period, cohorts, warnings = load(a.input, a.cutoffs, a.period)
    if not cohorts:
        fail(f"{a.input}: no cohorts with a first-purchase date.")
    r = build(period, cohorts, parse_date(a.data_end, "--data-end") if a.data_end else None, a.min_cohort, a.drop_share)
    r["warnings"] = warnings + r["warnings"]
    if not r["cohorts"]:
        fail(f"{a.input}: no cohort has a usable size. " + " ".join(r["warnings"]))
    report(r)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(r, indent=2) + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the file ({e.strerror or e}).")
        print(f"\nWrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
