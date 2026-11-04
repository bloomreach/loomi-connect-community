#!/usr/bin/env python3
"""Split an Engagement revenue change into buyers x orders per buyer x order value, from saved EQL results.

Usage:
  python3 revenue_split.py --previous K_PREV.json --current K_CUR.json
      [--status VALUE ...] [--previous-days N --current-days N]
      [--buyer-groups PREV.json,CUR.json] [--breakdown NAME=PREV.json,CUR.json ...]
      [--order-ids U.json] [--out split.json]

Inputs are execute_analytics_eql results saved as JSON, from the patterns in references/eql-patterns.md:
  --previous, --current   pattern K for each period: rows by order status, values =
                          [sum of order value, count of purchase events, count first event purchase].
                          The completed rows (--status, default from rules.json) give revenue, orders
                          and buyers; the other rows are reported as left out.
  --buyer-groups          pattern R for each period: values = [retained, reactivated, new] per row;
                          every row is added up and checked against that period's buyers.
  --breakdown NAME=...    pattern B for each period on one dimension: rows by segment, values =
                          [revenue, orders, buyers] of completed orders. Each segment gets its change
                          and share of the total revenue change, and the segments are checked to add
                          up to the total.
  --order-ids             pattern U: purchase events by order ID (grouping top 3). Reports how many
                          events the most repeated IDs have. Order IDs are never printed.

Prints JSON (or writes it to --out): both periods' revenue, orders, buyers, orders per buyer and AOV;
the four ratios and the check that they multiply back; the main driver; the log-mean money split
whose parts add up to the change to the cent; and any breakdowns. Values that don't parse ("NA")
are treated as missing, never as 0, and listed under missing_values. Thresholds come from
references/rules.json.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING_TEXT = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
MISSING = []


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def number(v):
    """A number from a tool value ("$1,000.00", "(12.00)"), or None when missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.lower() in MISSING_TEXT:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s[:1] in ("−", "–"):
        s = "-" + s[1:]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    s = re.sub(r"[$£€,\s]", "", s)
    if not re.fullmatch(r"[+]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
        return None
    x = float(s)
    if not math.isfinite(x):
        return None
    return -x if negative else x


def load(path):
    """The report body (a dict with rows) of a saved execute_analytics_eql result."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        fail(f"{path}: can't read the file ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"{path}: not valid JSON ({e}).")
    for _ in range(3):
        if isinstance(data, dict) and isinstance(data.get("result"), dict) and len(data) == 1:
            data = data["result"]
        if isinstance(data, dict) and data.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {data.get('error') or 'no error text'}. "
                 "This query didn't run; don't treat it as 'nothing found'.")
        if isinstance(data, dict) and isinstance(data.get("data"), dict) and not isinstance(data.get("rows"), list):
            data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        fail(f"{path}: no EQL rows found; save the execute_analytics_eql result.")
    return data


def label(row):
    heads = row.get("headers") or []
    parts = []
    for h in heads:
        if isinstance(h, dict):
            parts.append("other" if h.get("type") == "other" else ("null" if h.get("value") is None else str(h.get("value"))))
        else:
            parts.append("null" if h is None else str(h))
    return " / ".join(parts) if parts else "total"


def rows(path, width):
    """[(label, [values...])] with each value a number or None (missing values are noted)."""
    out = []
    for i, r in enumerate(load(path)["rows"]):
        if not isinstance(r, dict):
            continue
        vals = list(r.get("values") or [])
        if len(vals) < width:
            fail(f"{path}: row {i + 1} has {len(vals)} values, expected {width}. Use the query shape in references/eql-patterns.md.")
        nums = []
        for j, v in enumerate(vals[:width]):
            x = number(v)
            if x is None:
                MISSING.append(f"{path}: row {i + 1} ({label(r)}), value {j + 1}")
            nums.append(x)
        out.append((label(r), nums))
    return out


def period(path, statuses):
    """Revenue, orders and buyers from the completed rows of pattern K; the other rows as left out."""
    done, left = [], []
    for name, vals in rows(path, 3):
        (done if name.lower() in statuses else left).append((name, vals))
    if not done:
        seen = ", ".join(n for n, _ in left) or "none"
        fail(f"{path}: no row with a completed status ({', '.join(sorted(statuses))}). Statuses found: {seen}. "
             "Pass --status with the project's completed value.")
    totals = []
    for k, what in enumerate(("revenue", "orders", "buyers")):
        vals = [v[k] for _, v in done]
        if any(x is None for x in vals):
            fail(f"{path}: the completed {what} is missing or not a number. Rerun the query or fix the value.")
        totals.append(sum(vals))
    revenue, orders, buyers = totals
    left_events = sum(v[1] for _, v in left if v[1] is not None)
    all_events = orders + left_events
    out = {"revenue": round(revenue, 2), "orders": orders, "buyers": buyers,
           "orders_per_buyer": orders / buyers if buyers else None,
           "aov": revenue / orders if orders else None,
           "completed_statuses_used": [n for n, _ in done],
           "left_out": [{"status": n, "orders": v[1], "revenue": v[0]} for n, v in left],
           "left_out_share_of_events": round(left_events / all_events, 4) if all_events else None}
    if len(done) > 1:
        out["note"] = ("buyers added up over several completed statuses: a customer in two of them is counted twice, "
                       "so buyers may be too high")
    return out


def logmean(a, b):
    if a <= 0 or b <= 0:
        return None
    return a if math.isclose(a, b) else (a - b) / (math.log(a) - math.log(b))


def split(r0, b0, o0, r1, b1, o1):
    """Split the revenue change into buyers, orders-per-buyer and order-value parts (LMDI).

    revenue = buyers x (orders / buyers) x (revenue / orders). The three parts add up exactly
    to r1 - r0 when every value is positive. Otherwise the whole change is reported as 'unsplit'.
    """
    delta = r1 - r0
    L = logmean(r1, r0)
    if L is None or min(b0, b1, o0, o1) <= 0:
        return {"buyers": None, "orders_per_buyer": None, "order_value": None, "unsplit": round(delta, 2)}
    buyers = round(L * math.log(b1 / b0), 2)
    per_buyer = round(L * math.log((o1 / b1) / (o0 / b0)), 2)
    # The order-value part takes the rounding, so the three rounded parts add up to the change to the cent.
    return {"buyers": buyers, "orders_per_buyer": per_buyer,
            "order_value": round(round(delta, 2) - buyers - per_buyer, 2), "unsplit": 0.0}


def ratio(cur, prev):
    return cur / prev if cur is not None and prev else None


def share(part, whole):
    return round(part / whole, 4) if part is not None and whole else None


def two_files(text, flag):
    a, sep, b = text.partition(",")
    if not sep or not a.strip() or not b.strip():
        fail(f"{flag}: expected PREVIOUS.json,CURRENT.json, got {text!r}.")
    return a.strip(), b.strip()


def buyer_groups(spec, prev, cur):
    p_path, c_path = two_files(spec, "--buyer-groups")
    names = ("retained", "reactivated", "new")
    out = {}
    for which, path, per in (("previous", p_path, prev), ("current", c_path, cur)):
        cols = [0.0, 0.0, 0.0]
        for _, vals in rows(path, 3):
            for k in range(3):
                cols[k] += vals[k] or 0.0
        total = sum(cols)
        out[which] = dict(zip(names, cols), total=total, matches_buyers=abs(total - per["buyers"]) < 0.5)
    change = cur["buyers"] - prev["buyers"]
    out["change"] = {n: out["current"][n] - out["previous"][n] for n in names}
    out["share_of_buyer_change"] = {n: share(out["change"][n], change) for n in names}
    if not (out["previous"]["matches_buyers"] and out["current"]["matches_buyers"]):
        out["warning"] = ("retained + reactivated + new doesn't equal the buyers from pattern K: check the windows "
                          "and the status filter before using this split")
    return out


def breakdown(spec, prev, cur):
    name, sep, files = spec.partition("=")
    if not sep or not name.strip():
        fail(f"--breakdown: expected NAME=PREVIOUS.json,CURRENT.json, got {spec!r}.")
    p_path, c_path = two_files(files, f"--breakdown {name.strip()}")
    segs = {}
    for which, path in (("previous", p_path), ("current", c_path)):
        for seg, vals in rows(path, 3):
            s = segs.setdefault(seg, {"segment": seg})
            s[which] = {"revenue": vals[0], "orders": vals[1], "buyers": vals[2]}
    total_change = cur["revenue"] - prev["revenue"]
    total_ratio = ratio(cur["revenue"], prev["revenue"])
    out, added, sums = [], 0.0, {"previous": 0.0, "current": 0.0}
    for s in segs.values():
        p = s.get("previous", {}).get("revenue")
        c = s.get("current", {}).get("revenue")
        p_val = 0.0 if "previous" not in s else p
        c_val = 0.0 if "current" not in s else c
        if p_val is None or c_val is None:
            change = None
        else:
            change = c_val - p_val
            added += change
            sums["previous"] += p_val
            sums["current"] += c_val
        seg_ratio = ratio(c_val, p_val) if change is not None else None
        mix = None
        if seg_ratio is not None and total_ratio:
            rel = seg_ratio / total_ratio
            mix = "gained share" if rel > 1.05 else "lost share" if rel < 0.95 else "kept its share"
        out.append({"segment": s["segment"], "previous": s.get("previous"), "current": s.get("current"),
                    "revenue_change": round(change, 2) if change is not None else None,
                    "share_of_change": share(change, total_change), "revenue_ratio": seg_ratio, "mix": mix})
    out.sort(key=lambda x: -abs(x["revenue_change"] or 0))
    gap = round(total_change - added, 2)
    return {"name": name.strip(), "segments": out,
            "segments_change_total": round(added, 2), "total_change": round(total_change, 2),
            "left_over": gap, "adds_up": abs(gap) <= RULES["add_up_tolerance"],
            "note": "revenue and orders add up across segments; buyers don't (one customer can be in several rows)",
            **({} if abs(gap) <= RULES["add_up_tolerance"] else {
                "warning": "the segments don't add up to the total change: a row is missing (use grouping top N with null), "
                           "a value is missing, or the status filter differs from pattern K"})}


def order_ids(path):
    counts, other = [], None
    for seg, vals in rows(path, 1):
        if seg == "other":
            other = vals[0]
        elif vals[0] is not None:
            counts.append(vals[0])
    most = max(counts) if counts else None
    repeating = [c for c in counts if c > 1]
    return {"ids_read": len(counts), "most_events_per_id": most,
            "ids_repeating": len(repeating), "surplus_events": sum(c - 1 for c in repeating),
            "events_in_other_row": other,
            "verdict": "no order ID repeats" if most is not None and most <= 1 else
                       "order IDs repeat: count completed orders only and report the surplus" if most else "no rows",
            "note": "order IDs are not printed"}


def build(a):
    statuses = {s.lower() for s in (a.status or RULES["completed_statuses"])}
    prev, cur = period(a.previous, statuses), period(a.current, statuses)
    r0, r1 = prev["revenue"], cur["revenue"]
    ratios = {"revenue": ratio(r1, r0), "orders": ratio(cur["orders"], prev["orders"]),
              "buyers": ratio(cur["buyers"], prev["buyers"]),
              "orders_per_buyer": ratio(cur["orders_per_buyer"], prev["orders_per_buyer"]),
              "aov": ratio(cur["aov"], prev["aov"])}
    out = {"ok": True, "previous": prev, "current": cur, "change": round(r1 - r0, 2),
           "change_pct": round((ratios["revenue"] - 1) * 100, 2) if ratios["revenue"] else None,
           "ratios": {k: round(v, 6) if v is not None else None for k, v in ratios.items()}}
    parts3 = [ratios["buyers"], ratios["orders_per_buyer"], ratios["aov"]]
    if all(parts3) and ratios["revenue"]:
        product = parts3[0] * parts3[1] * parts3[2]
        out["ratio_check"] = {"product": round(product, 6),
                              "matches": abs(product / ratios["revenue"] - 1) <= RULES["ratio_check_tolerance"]}
        logs = {k: abs(math.log(ratios[k])) for k in ("buyers", "orders_per_buyer", "aov")}
        out["main_driver"] = max(logs, key=logs.get) if max(logs.values()) > 0 else "no change"
    else:
        out["ratio_check"] = None
        out["main_driver"] = "new or gone (no orders or buyers in one period)"
    parts = split(r0, prev["buyers"], prev["orders"], r1, cur["buyers"], cur["orders"])
    named = [v for k, v in parts.items() if k != "unsplit" and v is not None]
    out["money_split"] = parts
    out["money_split_share"] = {k: share(v, r1 - r0) for k, v in parts.items() if k != "unsplit" and v is not None}
    out["money_split_adds_up"] = abs(sum(named) + parts["unsplit"] - (r1 - r0)) <= RULES["add_up_tolerance"]
    if a.previous_days or a.current_days:
        if not (a.previous_days and a.current_days) or a.previous_days <= 0 or a.current_days <= 0:
            fail("--previous-days and --current-days: give both, as whole days above 0.")
        per0, per1 = r0 / a.previous_days, r1 / a.current_days
        pr = ratio(per1, per0)
        out["per_day"] = {"previous": round(per0, 2), "current": round(per1, 2),
                          "ratio": round(pr, 6) if pr else None,
                          "lengths_differ": a.previous_days != a.current_days,
                          "change_is_the_extra_days": bool(pr) and a.previous_days != a.current_days
                          and abs(pr - 1) < RULES["per_day_tolerance"]}
    if a.buyer_groups:
        out["buyer_groups"] = buyer_groups(a.buyer_groups, prev, cur)
    if a.breakdown:
        limit = RULES["max_breakdowns"]
        out["breakdowns"] = [breakdown(s, prev, cur) for s in a.breakdown[:limit]]
        if len(a.breakdown) > limit:
            out["breakdowns_skipped"] = (f"{len(a.breakdown) - limit} more breakdown(s) given; only {limit} are read "
                                         "(max_breakdowns). Ask the user before running more.")
    if a.order_ids:
        out["order_ids"] = order_ids(a.order_ids)
    if MISSING:
        out["missing_values"] = {"left_out_of_sums": MISSING,
                                 "note": "these values were missing or not numbers (for example NA) and were treated as missing, not 0"}
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # segment names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--previous", required=True, help="saved pattern K result for the previous period")
    ap.add_argument("--current", required=True, help="saved pattern K result for the current period")
    ap.add_argument("--status", action="append", help="status value of a completed order (repeat for several); "
                    "default: completed_statuses in references/rules.json")
    ap.add_argument("--previous-days", type=int, help="days in the previous period, for revenue per day")
    ap.add_argument("--current-days", type=int, help="days in the current period, for revenue per day")
    ap.add_argument("--buyer-groups", help="saved pattern R results: PREVIOUS.json,CURRENT.json")
    ap.add_argument("--breakdown", action="append", default=[],
                    help="saved pattern B results for one dimension: NAME=PREVIOUS.json,CURRENT.json (repeatable)")
    ap.add_argument("--order-ids", help="saved pattern U result (purchase events by order ID)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()
    result = build(a)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except OSError as e:
            fail(f"{a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "change": result["change"], "main_driver": result["main_driver"]}))
    else:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
