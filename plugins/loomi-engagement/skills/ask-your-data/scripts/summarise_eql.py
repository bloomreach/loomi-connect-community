#!/usr/bin/env python3
"""Summarise an execute_analytics_eql response: totals, sorted rows, funnel conversion.

Usage:
    python3 scripts/summarise_eql.py response.json [--top N]
    cat response.json | python3 scripts/summarise_eql.py -

Standard library only. No network. It only reshapes a response the assistant
already fetched. Handles the usual traps: rows sorted by header rather than value,
`null` / "" / "other" rows that must be counted in the total, empty rows meaning
zero, and funnel step counts. Numbers sent as strings ("1,234", "$5.00", "12%")
are counted; values that aren't numbers are left out of totals and said so.
"""
import argparse
import json
import math
import sys


def header_label(h):
    if isinstance(h, dict):
        if h.get("type") == "other":
            return "(other)"
        v = h.get("value")
    else:
        v = h
    if v is None:
        return "(null)"
    if v == "":
        return '("")'
    return str(v)


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


def fmt(v):
    if v is None:
        return "null"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.2f}"
    return f"{int(v):,}"


def summarise_report(data, top):
    rows = data.get("rows") or []
    metrics = (data.get("generated_names") or {}).get("metrics") or ["value"]
    if not rows:
        print("No rows: treat the result as zero.")
        return
    parsed = []
    for r in rows:
        label = " / ".join(header_label(h) for h in r.get("headers", [])) or "(total)"
        vals = r.get("values") or []
        parsed.append((label, vals))
    n_metrics = max(len(v) for _, v in parsed) if parsed else 0
    for i in range(n_metrics):
        name = metrics[i] if i < len(metrics) else f"metric_{i}"
        items = [(label, num(vals[i]) if i < len(vals) else None) for label, vals in parsed]
        total = sum(v for _, v in items if v is not None)
        missing = sum(1 for _, v in items if v is None)
        print(f"Metric: {name}")
        is_additive = not any(k in name.lower() for k in ("avg", "average", "mean", "min", "max", "median"))
        if is_additive:
            print(f"  Total (all rows, including null/empty/other): {fmt(total)}")
        else:
            print("  Not additive (average/min/max): don't add rows; weight by counts if combining.")
        if missing:
            print(f"  {missing} row(s) had no numeric value and are left out of the total.")
        items.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))
        for label, v in items[:top]:
            share = f"  {100 * v / total:5.1f}%" if is_additive and v is not None and total else ""
            print(f"  {label:<40} {fmt(v):>15}{share}")
        if len(items) > top:
            print(f"  ... {len(items) - top} more row(s)")
        if 0 < n_metrics - 1 != i:
            print()


def summarise_funnel(data):
    total = data.get("total") or {}
    counts = [num(c) for c in total.get("counts") or []]
    times = total.get("times") or []
    if not counts:
        print("Funnel returned no counts: treat as zero.")
        return
    print("Funnel (unique customers reaching each step in order):")
    first = counts[0] or 0
    prev = None
    for i, c in enumerate(counts):
        step = f"  Step {i + 1}: {fmt(c)}"
        if c is None:
            step += "  (missing: not a number)"
        elif prev:
            step += f"  ({100 * c / prev:.1f}% of previous"
            step += f", {100 * c / first:.1f}% of step 1)" if first else ")"
        t = num(times[i]) if i < len(times) else None
        if t is not None and t >= 0:
            step += f"  avg time from previous: {t / 3600:.1f} h"
        print(step)
        prev = c


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="JSON file with the execute_analytics_eql response, or - for stdin")
    ap.add_argument("--top", type=int, default=20, help="rows to show (default 20)")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.path == "-" else open(args.path, encoding="utf-8").read()
    resp = json.loads(raw)
    if isinstance(resp, dict) and "result" in resp and "data" not in resp:
        resp = resp["result"]
    if resp.get("success") is False:
        name = "stdin" if args.path == "-" else args.path
        print(f"{name}: Loomi Connect returned an error: {resp.get('error') or 'no error text'}. "
              "This check couldn't run; don't treat it as 'nothing found'.", file=sys.stderr)
        return 1
    data = resp.get("data") or {}
    if "query" in resp:
        print(f"Query: {resp['query']}")
    cost = resp.get("cost_estimate") or {}
    if cost.get("level"):
        print(f"Cost: {cost['level']} (score {cost.get('score')})")
    kind = resp.get("analysis_type") or ("funnel" if "total" in data else "report")
    if kind == "funnel":
        summarise_funnel(data)
    else:
        summarise_report(data, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
