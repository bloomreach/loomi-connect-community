#!/usr/bin/env python3
"""Break a Bloomreach Discovery revenue change into parts that add up exactly.

Reads raw JSON saved from Loomi Connect tools (current period plus previous period)
and prints a JSON report:

  * drivers:  traffic x conversion x average order value (log-mean split, so the
              three parts sum exactly to the revenue change);
  * channels: search, category and "other" (overall minus search minus category);
  * devices:  one entry per --device file, plus an "unexplained" remainder;
  * tables:   the rows that moved revenue most in each table, each split into
              traffic / conversion / order value, plus the long-tail remainder
              so every table adds up to its parent total;
  * trend:    daily gaps, the most likely start date of the change, and how big
              the change is compared with normal day-to-day noise.

Usage:
  python3 decompose_change.py --overall overall.json \
      [--search search.json] [--category category.json] \
      [--device mobile=mobile.json --device desktop=desktop.json --device tablet=tablet.json] \
      [--table queries=q1.json,q2.json] [--table categories=cats.json] \
      [--table products=p_by_rev.json,p_by_prev_rev.json] [--table brands=brands.json] \
      [--trend trend.json --offset-days 7] [--top N]

Inputs:
  overall / search / category / device files: get_discovery_overall_performance,
    get_discovery_search_performance, get_discovery_category_performance (each
    response has data.current and data.previous with revenue, visits, conversions).
  table files: get_discovery_query_performance, get_discovery_category_performance_table,
    get_discovery_product_performance_table, get_discovery_brand_performance
    (data.rows with revenue/prev_revenue, visits/prev_visits, conversions/prev_conversions).
    Several files for one table are merged and de-duplicated by key.
  trend file: get_discovery_trend with metric="revenue" (data.current / data.previous lists).
    Days are aligned by date, not position, because the tool leaves out days with no data.
    Missing and $0 days are listed under trend.data_gaps.

Parent totals: queries -> search card; categories -> category card;
products and brands -> overall card. If the parent card isn't given, the table's own
row total is used and coverage is reported as unknown.

The thresholds (list length, trend outliers, concentration, step changes and noise) live in
references/rules.json, shared with apps that compute the same numbers.

Standard library only; no network access.
"""
import argparse
import datetime
import json
import math
import statistics
import sys
from pathlib import Path

# The thresholds live in references/rules.json, shared with apps that compute the same numbers.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))

KEYS = {"queries": "query", "categories": "category", "products": "product_title", "brands": "brand"}
ID_KEYS = {"categories": "cat_id", "products": "prod_id"}
PARENT = {"queries": "search", "categories": "category", "products": "overall", "brands": "overall"}


def num(v):
    """A number from a tool value, or None when it is missing or not a number."""
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


MISSING = set()


def val(v, where):
    """num(v), counting a missing value as 0 and noting where it was."""
    x = num(v)
    if x is None:
        MISSING.add(where)
        return 0.0
    return x


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            print(json.dumps({"ok": False, "error": f"{path}: Loomi Connect returned an error: "
                              f"{d.get('error') or d.get('message') or 'no error text'}. This check couldn't run; "
                              "don't treat it as 'nothing found'."}))
            sys.exit(1)
    # Some tools wrap the payload in {"result": {...}}.
    if isinstance(data, dict) and "result" in data and "data" not in data:
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else data


def card(path):
    d = load(path)
    out = {}
    for period in ("current", "previous"):
        p = d[period]
        out[period] = {k: val(p.get(src), f"{path} {period}.{src}")
                       for k, src in (("revenue", "revenue"), ("visits", "visits"), ("orders", "conversions"))}
    return out


def logmean(a, b):
    if a <= 0 or b <= 0:
        return None
    return a if math.isclose(a, b) else (a - b) / (math.log(a) - math.log(b))


def split(r0, v0, o0, r1, v1, o1):
    """Split revenue change into traffic, conversion and order-value parts (LMDI).

    revenue = visits x (orders / visits) x (revenue / orders). The three parts
    add up exactly to r1 - r0 when every value is positive. Otherwise the whole
    change is reported as 'unsplit'.
    """
    delta = r1 - r0
    L = logmean(r1, r0)
    if L is None or min(v0, v1, o0, o1) <= 0:
        return {"traffic": None, "conversion": None, "order_value": None, "unsplit": round(delta, 2)}
    cr0, cr1 = o0 / v0, o1 / v1
    aov0, aov1 = r0 / o0, r1 / o1
    parts = {
        "traffic": L * math.log(v1 / v0),
        "conversion": L * math.log(cr1 / cr0),
        "order_value": L * math.log(aov1 / aov0),
    }
    # The order-value part takes the rounding, so the three rounded parts add up to the change to the cent.
    traffic, conversion = round(parts["traffic"], 2), round(parts["conversion"], 2)
    return {"traffic": traffic, "conversion": conversion,
            "order_value": round(round(delta, 2) - traffic - conversion, 2), "unsplit": 0.0}


def pct(a, b):
    return round((a / b - 1) * 100, 2) if b else None


def share(part, whole):
    return round(part / whole * 100, 1) if whole else None


def summarise_card(c):
    cur, prev = c["current"], c["previous"]
    delta = cur["revenue"] - prev["revenue"]
    parts = split(prev["revenue"], prev["visits"], prev["orders"], cur["revenue"], cur["visits"], cur["orders"])
    return {
        "revenue": cur["revenue"], "prev_revenue": prev["revenue"], "delta": round(delta, 2),
        "change_pct": pct(cur["revenue"], prev["revenue"]),
        "visits_change_pct": pct(cur["visits"], prev["visits"]),
        "conversion_change_pct": pct(cur["orders"] / cur["visits"], prev["orders"] / prev["visits"])
        if cur["visits"] and prev["visits"] else None,
        "aov_change_pct": pct(cur["revenue"] / cur["orders"], prev["revenue"] / prev["orders"])
        if cur["orders"] and prev["orders"] else None,
        "parts": parts,
        "parts_share_of_delta_pct": {k: share(v, delta) for k, v in parts.items() if v is not None},
    }


def load_table(name, paths):
    key, idk = KEYS[name], ID_KEYS.get(name)
    rows = {}
    for p in paths:
        for r in load(p).get("rows", []):
            k = str(r.get(idk) or r.get(key) or "").strip().lower()
            if k:
                rows[k] = r
    return list(rows.values())


def table_report(name, rows, parent_delta, top):
    key = KEYS[name]
    items = []
    for r in rows:
        where = f"{name} row {r.get(key)!r}"
        r0, r1 = val(r.get("prev_revenue"), where), val(r.get("revenue"), where)
        v0, v1 = val(r.get("prev_visits"), where), val(r.get("visits"), where)
        o0, o1 = val(r.get("prev_conversions"), where), val(r.get("conversions"), where)
        delta = r1 - r0
        item = {
            "name": r.get(key),
            "revenue": r1, "prev_revenue": r0, "delta": round(delta, 2),
            "change_pct": pct(r1, r0), "visits": v1, "prev_visits": v0,
            "parts": split(r0, v0, o0, r1, v1, o1),
        }
        if name in ID_KEYS:
            item["id"] = r.get(ID_KEYS[name])
        if name == "products":
            item["brand"] = r.get("brand")
        items.append(item)
    covered = sum(i["delta"] for i in items)
    for i in items:
        i["share_of_parent_delta_pct"] = share(i["delta"], parent_delta) if parent_delta is not None else None
        i["main_driver"] = main_driver(i["parts"])
    falling = sorted([i for i in items if i["delta"] < 0], key=lambda i: i["delta"])[:top]
    rising = sorted([i for i in items if i["delta"] > 0], key=lambda i: -i["delta"])[:top]
    return {
        "rows_read": len(items),
        "parent_delta": parent_delta,
        "rows_delta_total": round(covered, 2),
        "long_tail_remainder": round(parent_delta - covered, 2) if parent_delta is not None else None,
        "falling": falling,
        "rising": rising,
    }


def main_driver(parts):
    named = {k: v for k, v in parts.items() if k != "unsplit" and v is not None}
    if not named:
        return "new or gone (no previous or current orders)"
    k = max(named, key=lambda x: abs(named[x]))
    return k


def to_date(s):
    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def trend_report(path, offset_days=None):
    """Compare each current day with the matching previous day, aligned by date.

    get_discovery_trend leaves out days with no data and can return $0.00 days, so
    the two lists can't be paired by position. The offset between the periods is
    inferred (or given with --offset-days); every date in the range is reported, and
    missing or zero days are listed as data gaps.
    """
    d = load(path)
    metric = d.get("metric", "revenue")
    cur = {to_date(x["cdate"]): num(x.get(metric)) for x in d.get("current", [])}
    prev = {to_date(x["cdate"]): num(x.get(metric)) for x in d.get("previous", [])}
    if not cur or not prev:
        return {"error": "empty trend"}
    if offset_days is None:
        # A missing first or last day makes neighbouring offsets match equally well. Break
        # ties toward the period length (the longer of the two spans), then a whole number
        # of weeks, so each day is still compared with the same weekday.
        length = max((max(cur) - min(cur)).days, (max(prev) - min(prev)).days) + 1
        candidates = {(min(cur) - min(prev)).days, (max(cur) - max(prev)).days, length}
        offset_days = max(candidates, key=lambda o: (
            sum(1 for c in cur if c - datetime.timedelta(days=o) in prev), o == length, o % 7 == 0, -o))
    off = datetime.timedelta(days=offset_days)
    start, end = min(min(cur), min(prev) + off), max(max(cur), max(prev) + off)
    days, gaps_in_data = [], []
    day = start
    while day <= end:
        c, p = cur.get(day), prev.get(day - off)
        for when, val, label in ((day, c, "current"), (day - off, p, "previous")):
            if val is None or val == 0:
                gaps_in_data.append({"date": when.strftime("%Y%m%d"), "period": label,
                                     "issue": "missing" if val is None else "zero"})
        days.append({"date": day.strftime("%Y%m%d"), "compare_date": (day - off).strftime("%Y%m%d"),
                     "value": c or 0.0, "compare_value": p or 0.0,
                     "gap": round((c or 0.0) - (p or 0.0), 2)})
        day += datetime.timedelta(days=1)
    n = len(days)
    prev_vals = [x["compare_value"] for x in days if x["compare_value"]]
    gaps = [x["gap"] for x in days]
    total_gap = sum(gaps)
    # One-day outliers: a day whose gap sits far from the typical daily gap.
    med = statistics.median(gaps)
    spread = statistics.median([abs(g - med) for g in gaps]) or (statistics.pstdev(gaps) or 1)
    outliers = []
    for x in days:
        if abs(x["gap"] - med) > RULES["outlier_spread_multiple"] * spread and abs(x["gap"]) > 0:
            o = dict(x)
            o["share_of_total_gap_pct"] = share(x["gap"], total_gap)
            outliers.append(o)
    # Concentration: the fewest days that make up most of the total gap (concentrated_share).
    share_needed = RULES["concentrated_share"]
    concentrated = []
    if total_gap:
        sign = 1 if total_gap > 0 else -1
        acc = 0.0
        for x in sorted(days, key=lambda x: -sign * x["gap"]):
            if sign * x["gap"] <= 0:
                break
            concentrated.append(x["date"])
            acc += x["gap"]
            if acc / total_gap >= share_needed:
                break
        if acc / total_gap < share_needed or len(concentrated) > max(1, n // RULES["concentrated_max_days_divisor"]):
            concentrated = []
        else:
            concentrated = {"dates": concentrated, "share_of_total_gap_pct": share(acc, total_gap)}
    # Where does the gap shift? Best split point with at least step_min_side_days on each side.
    best = None
    side = RULES["step_min_side_days"]
    for k in range(side, n - side + 1):
        before, after = gaps[:k], gaps[k:]
        diff = statistics.mean(after) - statistics.mean(before)
        sse = sum((g - statistics.mean(before)) ** 2 for g in before) + sum((g - statistics.mean(after)) ** 2 for g in after)
        if best is None or sse < best["sse"]:
            pooled = math.sqrt(sse / max(n - 2, 1))
            best = {"starts": days[k]["date"], "mean_gap_before": round(statistics.mean(before), 2),
                    "mean_gap_after": round(statistics.mean(after), 2), "shift": round(diff, 2),
                    "within_sd": round(pooled, 2), "sse": sse}
    # Noise: how much the previous period's days vary. The period total would wobble by
    # about sd x sqrt(n) by chance. Day-of-week patterns inflate this, which is conservative.
    # Days with no data are left out of the noise estimate.
    sd = statistics.stdev(prev_vals) if len(prev_vals) >= max(RULES["noise_min_days"], 2) else None
    noise = sd * math.sqrt(n) if sd else None
    ratio = abs(total_gap) / noise if noise else None
    if ratio is None:
        verdict = "unknown"
    elif ratio < RULES["noise_normal_ratio"]:
        verdict = "within normal day-to-day variation"
    elif ratio < RULES["noise_borderline_ratio"]:
        verdict = "borderline: could be noise"
    else:
        verdict = "larger than normal variation"
    step = None
    # A step must be large compared with the scatter of days on each side of it.
    if (best and n >= RULES["step_min_days"]
            and abs(best["shift"]) >= RULES["step_shift_sd_multiple"] * max(best["within_sd"], 1e-9)):
        step = {k: v for k, v in best.items() if k != "sse"}
    if gaps_in_data:
        shape = (f"unreliable: {len(gaps_in_data)} day(s) missing or zero; compare complete days only "
                 "or choose a period without gaps")
        verdict = "not assessed: data gaps"
    elif step:
        shape = f"step change from {step['starts']}"
    elif concentrated:
        shape = "concentrated on " + ", ".join(concentrated["dates"])
    elif outliers:
        shape = "one-off day(s): " + ", ".join(o["date"] for o in outliers)
    else:
        shape = "spread evenly across the period"
    return {
        "metric": metric, "offset_days": offset_days, "days": days, "total_gap": round(total_gap, 2),
        "data_gaps": gaps_in_data,
        "daily_sd_previous": round(sd, 2) if sd else None,
        "noise_band_for_total": round(noise, 2) if noise else None,
        "change_vs_noise": round(ratio, 2) if ratio is not None else None,
        "verdict": verdict,
        "shape": shape,
        "step_change": step,
        "concentrated_days": concentrated or None,
        "outlier_days": outliers,
        "worst_day": min(days, key=lambda x: x["gap"]),
        "best_day": max(days, key=lambda x: x["gap"]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overall", required=True)
    ap.add_argument("--search")
    ap.add_argument("--category")
    ap.add_argument("--device", action="append", default=[], help="name=file")
    ap.add_argument("--table", action="append", default=[], help="queries|categories|products|brands=file[,file]")
    ap.add_argument("--trend")
    ap.add_argument("--top", type=int, default=RULES["top"], help="rows in each table's rising and falling lists")
    ap.add_argument("--offset-days", type=int, help="days between a current day and its comparison day "
                    "(default: inferred; pass it when using custom comparison dates)")
    a = ap.parse_args()

    cards = {"overall": card(a.overall)}
    if a.search:
        cards["search"] = card(a.search)
    if a.category:
        cards["category"] = card(a.category)
    overall = summarise_card(cards["overall"])
    out = {"overall": overall}
    total = overall["delta"]

    if a.search and a.category:
        s, c = summarise_card(cards["search"]), summarise_card(cards["category"])
        other = total - s["delta"] - c["delta"]
        other_rev = overall["revenue"] - s["revenue"] - c["revenue"]
        out["channels"] = {
            "search": s, "category": c,
            "other": {"revenue": round(other_rev, 2), "delta": round(other, 2),
                      "note": "overall minus search minus category; search and category visits overlap, "
                              "so treat this as an approximate remainder"},
            "share_of_delta_pct": {"search": share(s["delta"], total), "category": share(c["delta"], total),
                                   "other": share(other, total)},
        }
        if other_rev < 0:
            out["channels"]["warning"] = "search + category revenue exceeds overall; attribution overlaps"

    if a.device:
        devs = {}
        for spec in a.device:
            name, _, path = spec.partition("=")
            devs[name] = summarise_card(card(path))
        dsum = sum(d["delta"] for d in devs.values())
        rsum = sum(d["revenue"] for d in devs.values())
        out["devices"] = {
            "by_device": devs,
            "share_of_delta_pct": {k: share(v["delta"], total) for k, v in devs.items()},
            "unexplained_delta": round(total - dsum, 2),
            "device_revenue_vs_overall_pct": share(rsum, overall["revenue"]),
        }

    tables = {}
    for spec in a.table:
        name, _, paths = spec.partition("=")
        if name not in KEYS:
            sys.exit(f"unknown table {name!r}; use one of {sorted(KEYS)}")
        rows = load_table(name, [p for p in paths.split(",") if p])
        parent = PARENT[name]
        parent_delta = summarise_card(cards[parent])["delta"] if parent in cards else None
        tables[name] = table_report(name, rows, parent_delta, a.top)
        if parent_delta is None:
            tables[name]["note"] = f"pass --{parent} to measure coverage against the {parent} total"
    if tables:
        out["tables"] = tables

    if a.trend:
        out["trend"] = trend_report(a.trend, a.offset_days)
    if MISSING:
        out["missing_values"] = {"counted_as_zero": sorted(MISSING),
                                 "note": "these values were missing or not numbers (e.g. NA) and were counted as 0"}

    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
