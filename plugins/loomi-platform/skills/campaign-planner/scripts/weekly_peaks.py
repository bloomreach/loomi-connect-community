#!/usr/bin/env python3
"""Roll daily figures into weeks and find the peak weeks.

Standard library only. No network access. Prints Markdown, or JSON with --json.

Accepts either of these, saved to a file by the assistant:

1. An Engagement EQL response for a daily breakdown, e.g.
     select count event purchase by event purchase timestamp grouping top 60
       format year month day since <start>Z until <end>Z
   Rows look like {"headers": [{"value": <unix seconds>}], "values": [n]}.
   The whole tool response, or just its "data" object, is fine.

2. A Discovery get_discovery_trend response. Rows look like
   {"cdate": "20251128", "revenue": "$1,149,791.88"}. Use --series previous
   to read the comparison series instead of the current one.

Usage:
  python3 weekly_peaks.py purchases.json [--week-start mon] [--label "Purchases"]
  python3 weekly_peaks.py trend.json --metric revenue
  python3 weekly_peaks.py purchases.json --moments moments.json

--moments takes the JSON output of retail_dates.py (--json) and tags each week
with the moments that fall in it.

Engagement day buckets are in the project's reporting timezone, so their
timestamps can sit an hour or two either side of UTC midnight (and shift at
daylight saving). This script rounds each bucket to the nearest calendar date
before grouping, which handles that.

A week's "index" is its total divided by the median week in the input
(1.00 = a typical week). Partial weeks at either end are flagged, and are
not used for the median or the peaks. A week in the middle with days missing
(no row, or a value such as "NA") is still used, and its missing days are
shown; missing values are never counted as 0.
"""

import argparse
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

WEEKDAYS = {"mon": 0, "sun": 6, "sat": 5}


def to_number(v):
    """A number from a tool value ("$1,149,791.88"), or None when missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().translate({ord(c): None for c in "$£€,"})
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def nearest_date(ts):
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc) + timedelta(hours=12)
    return dt.date()


def tool_error(data):
    """The error text when a saved response says success: false, else None."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or d.get("message") or "no error text")
    return None


def parse(data, metric, series, missing):
    """Daily totals by date. Days whose value is missing or not a number go in `missing`."""
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    daily = {}
    if isinstance(data, dict) and "rows" in data:
        for row in data["rows"]:
            h = row.get("headers") or [{}]
            v = h[0].get("value")
            if v is None or h[0].get("type") == "other":
                continue
            d = nearest_date(v)
            x = to_number((row.get("values") or [None])[0])
            if x is None:
                missing.add(d)
                continue
            daily[d] = daily.get(d, 0.0) + x
        return daily, "EQL"
    if isinstance(data, dict) and series in data:
        for row in data[series]:
            d = datetime.strptime(str(row["cdate"]), "%Y%m%d").date()
            key = metric or next(k for k in row if k != "cdate")
            x = to_number(row.get(key))
            if x is None:
                missing.add(d)
                continue
            daily[d] = daily.get(d, 0.0) + x
        return daily, "Discovery trend"
    raise SystemExit("Unrecognised input: expected EQL 'rows' or a Discovery trend 'current' series.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--week-start", default="mon", choices=sorted(WEEKDAYS))
    p.add_argument("--metric", help="Discovery trend metric key (default: the first non-date key)")
    p.add_argument("--series", default="current", choices=["current", "previous"])
    p.add_argument("--label", default="Value")
    p.add_argument("--moments", help="retail_dates.py --json output, to tag weeks")
    p.add_argument("--top", type=int, default=3, help="how many peak weeks to name")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    with open(a.file, encoding="utf-8") as fh:
        data = json.load(fh)
    err = tool_error(data)
    if err:
        msg = (f"{a.file}: Loomi Connect returned an error: {err}. "
               "This check couldn't run; don't treat it as 'nothing found'.")
        if a.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 1
    missing = set()
    daily, source = parse(data, a.metric, a.series, missing)
    missing -= set(daily)
    if not daily:
        print("No data in the window (empty rows). Treat last year's evidence as unavailable.")
        return

    first, last = min(daily), max(daily)
    ws = WEEKDAYS[a.week_start]
    weeks = {}
    for d, v in daily.items():
        start = d - timedelta((d.weekday() - ws) % 7)
        w = weeks.setdefault(start, {"total": 0.0, "days": 0, "peak_day": None, "peak": -1})
        w["total"] += v
        w["days"] += 1
        if v > w["peak"]:
            w["peak"], w["peak_day"] = v, d

    moments = []
    if a.moments:
        with open(a.moments, encoding="utf-8") as fh:
            moments = [m for m in json.load(fh).get("moments", []) if m.get("date")]

    # Only the first and last weeks can be cut off by the window. A short week in the middle
    # has missing days (no row, or a value that isn't a number): it still counts, and is flagged.
    edge = {min(weeks), max(weeks)}

    def is_partial(start):
        return start in edge and weeks[start]["days"] < 7

    full = [w["total"] for s, w in weeks.items() if not is_partial(s)] or [w["total"] for w in weeks.values()]
    median = statistics.median(full) if full else 0
    rows = []
    for start in sorted(weeks):
        w = weeks[start]
        end = start + timedelta(6)
        tags = [m["name"] for m in moments if start.isoformat() <= m["date"] <= end.isoformat()]
        rows.append({
            "week_start": start.isoformat(),
            "total": round(w["total"], 2),
            "days": w["days"],
            "partial": is_partial(start),
            "missing_days": 0 if is_partial(start) else 7 - w["days"],
            "index": round(w["total"] / median, 2) if median else None,
            "peak_day": w["peak_day"].isoformat(),
            "moments": tags,
        })
    peaks = sorted((r for r in rows if not r["partial"]), key=lambda r: r["total"], reverse=True)[: a.top]

    if a.json:
        print(json.dumps({"source": source, "first_day": first.isoformat(), "last_day": last.isoformat(),
                          "days_without_a_number": sorted(d.isoformat() for d in missing),
                          "median_week": median, "weeks": rows, "peaks": [r["week_start"] for r in peaks]}, indent=2))
        return

    print(f"**{a.label} by week** ({source}, {first} to {last}; median full week = {median:,.0f})\n")
    print(f"| Week starting | {a.label} | Index | Peak day | Moments that week |")
    print("|---|---|---|---|---|")
    for r in rows:
        flag = " (partial)" if r["partial"] else (f" ({r['missing_days']} day(s) missing)" if r["missing_days"] else "")
        idx = "-" if r["index"] is None else f"{r['index']:.2f}"
        print(f"| {r['week_start']}{flag} | {r['total']:,.0f} | {idx} | {r['peak_day']} | {', '.join(r['moments']) or '-'} |")
    if missing:
        print(f"\n**No number for:** {', '.join(sorted(d.isoformat() for d in missing))} (left out, not counted as 0).")
    if peaks:
        print("\n**Peak weeks:** " + "; ".join(f"{r['week_start']} (index {r['index']:.2f})" for r in peaks))


if __name__ == "__main__":
    sys.exit(main())
