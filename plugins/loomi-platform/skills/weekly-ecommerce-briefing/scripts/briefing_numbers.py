#!/usr/bin/env python3
"""Work out the numbers for a weekly ecommerce briefing from saved Loomi Connect output.

Usage:
  python3 briefing_numbers.py --overall overall.json [--search search.json] [--category category.json] \
      [--device mobile=m.json --device desktop=d.json --device tablet=t.json] \
      [--queries q.json[,q2.json]] [--categories cats.json] [--products p.json[,p2.json]] [--brands b.json] \
      [--min-visits N] [--min-sessions N] [--top N]   (defaults: references/rules.json)

Inputs are the raw JSON responses (or files the client saved them to):
  cards:  get_discovery_overall_performance / _search_performance / _category_performance
          (data.current and data.previous with revenue, visits, conversions);
  tables: get_discovery_query_performance, get_discovery_category_performance_table,
          get_discovery_product_performance_table, get_discovery_brand_performance.

Prints JSON with:
  kpis:    revenue, revenue per visit, conversion rate and average order value, this
           period vs last, for overall / search / category / other and each device;
  movers:  top rising and falling queries (sessions measured against overall search
           growth, the discovery-trending-searches method), and categories, products and
           brands ranked by revenue change in money, with small rows filtered out.

Standard library only; no network access.
"""
import argparse
import json
import math
import sys
from pathlib import Path

# The thresholds live in references/rules.json, shared with apps that compute the same numbers.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))


def number(v):
    """A number from a tool value ("$1,000.00", "2.50%"), or None when missing or not a number."""
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


def num(v, where=None):
    """number(v), with a missing value counted as 0; `where` names it in the output's missing_values."""
    x = number(v)
    if x is None:
        if where:
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
    if isinstance(data, dict) and "result" in data and "data" not in data:
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else data


def pct(a, b):
    return round((a / b - 1) * 100, 1) if b else None


def kpi_block(rev, visits, orders, prev_rev, prev_visits, prev_orders):
    def rates(r, v, o):
        return {"revenue": round(r, 2), "visits": int(v), "orders": int(o),
                "rpv": round(r / v, 2) if v else None,
                "conversion_pct": round(o / v * 100, 2) if v else None,
                "aov": round(r / o, 2) if o else None}
    cur, prev = rates(rev, visits, orders), rates(prev_rev, prev_visits, prev_orders)
    change = {k: pct(cur[k], prev[k]) for k in ("revenue", "visits", "orders", "rpv", "aov")
              if cur[k] is not None and prev[k]}
    if cur["conversion_pct"] is not None and prev["conversion_pct"] is not None:
        change["conversion_pts"] = round(cur["conversion_pct"] - prev["conversion_pct"], 2)
    return {"this": cur, "last": prev, "change_pct": change, "revenue_delta": round(rev - prev_rev, 2)}


def card(path):
    d = load(path)
    c, p = d["current"], d["previous"]
    vals = tuple(num(x.get(k), f"{path} {when}.{k}") for when, x in (("current", c), ("previous", p))
                 for k in ("revenue", "visits", "conversions"))
    return vals + (d.get("trends", {}),)


def rows_of(paths, idkey):
    seen = {}
    for p in paths.split(","):
        if p:
            for r in load(p).get("rows", []):
                seen[str(r.get(idkey) or "").lower()] = r
    return [r for k, r in seen.items() if k]


def money_movers(rows, label, min_visits, top, extra=()):
    items = []
    for r in rows:
        v, v0 = num(r.get("visits")), num(r.get("prev_visits"))
        if max(v, v0) < min_visits:
            continue
        where = f"{label} {r.get(label)!r}"
        r1, r0 = num(r.get("revenue"), where), num(r.get("prev_revenue"), where)
        item = {"name": r.get(label), "revenue": r1, "prev_revenue": r0, "delta": round(r1 - r0, 2),
                "change_pct": pct(r1, r0), "visits": int(v), "prev_visits": int(v0),
                "conversion_rate": r.get("conversion_rate"), "prev_conversion_rate": r.get("prev_conversion_rate")}
        for k in extra:
            item[k] = r.get(k)
        items.append(item)
    up = sorted([i for i in items if i["delta"] > 0], key=lambda i: -i["delta"])[:top]
    down = sorted([i for i in items if i["delta"] < 0], key=lambda i: i["delta"])[:top]
    return {"considered": len(items), "rising": up, "falling": down}


def query_movers(rows, baseline_pct, min_sessions, top):
    growth = 1 + (baseline_pct or 0) / 100
    items = []
    for r in rows:
        cur, prev = num(r.get("browse_sessions")), num(r.get("prev_browse_sessions"))
        if max(cur, prev) < min_sessions:
            continue
        expected = prev * growth
        extra = cur - expected
        items.append({
            "query": r.get("query"), "sessions": int(cur), "prev_sessions": int(prev),
            "vs_baseline_pct": round((cur / expected - 1) * 100, 1) if expected else None,
            "trend_score": round(extra / math.sqrt(max(expected, 1)), 2),
            "revenue": num(r.get("revenue")), "revenue_delta": round(num(r.get("revenue")) - num(r.get("prev_revenue")), 2),
            "conversion_rate": r.get("conversion_rate"), "bounce_rate": r.get("bounce_rate"),
            "new": prev == 0,
        })
    rising = sorted([i for i in items if i["trend_score"] > 0], key=lambda i: -i["trend_score"])[:top]
    falling = sorted([i for i in items if i["trend_score"] < 0], key=lambda i: i["trend_score"])[:top]
    by_money = sorted(items, key=lambda i: i["revenue_delta"])
    return {"considered": len(items), "baseline_sessions_change_pct": baseline_pct,
            "rising": rising, "falling": falling,
            "biggest_revenue_drop": by_money[:top], "biggest_revenue_gain": by_money[::-1][:top]}


def median(values):
    s = sorted(values)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if n else 0.0


def top_and_issues(rows, label, vol_key, min_vol, top, issue_top, dead_end_names=()):
    """Top rows by revenue, plus rows with problems ranked by revenue at stake.

    The baseline is the median of the highest-volume rows (RULES["peers"]), so a row is judged against its peers.
    Revenue at stake = volume x (baseline conversion - conversion) x order value, or
    volume x baseline revenue per visit for dead ends. It is an upper bound for the week, not a forecast.
    """
    items = []
    for r in rows:
        vol, vol0 = num(r.get(vol_key)), num(r.get("prev_" + vol_key))
        if max(vol, vol0) < min_vol:
            continue
        visits = num(r.get("visits")) or vol
        items.append({
            "name": r.get(label), "id": r.get("cat_id"), "volume": int(vol), "prev_volume": int(vol0),
            "revenue": num(r.get("revenue"), f"{label} {r.get(label)!r}"),
            "prev_revenue": num(r.get("prev_revenue"), f"{label} {r.get(label)!r}"),
            "conversion_pct": number(r.get("conversion_rate")), "bounce_pct": number(r.get("bounce_rate")),
            "views_per_visit": round(num(r.get("product_page_views")) / visits, 2) if visits else 0.0,
            "aov": num(r.get("aov")), "rpv": num(r.get("rpv")),
        })
    if not items:
        return {"considered": 0, "top": [], "issues": []}
    peers = sorted(items, key=lambda i: -i["volume"])[:RULES["peers"]]
    base = {k: median([p[k] for p in peers if p[k] is not None])
            for k in ("conversion_pct", "bounce_pct", "views_per_visit", "rpv")}
    base_aov = median([p["aov"] for p in peers if p["aov"]])
    dead = {str(n).lower() for n in dead_end_names}

    issues = []
    for i in items:
        if i["volume"] < min_vol:
            continue  # only the previous period had volume
        reasons = []
        at_stake = 0.0
        conv, bounce = i["conversion_pct"], i["bounce_pct"]
        if str(i["name"]).lower() in dead or (i["views_per_visit"] == 0 and bounce is not None and bounce >= RULES["dead_end_bounce_pct"]):
            reasons.append("dead end: no product views" + (", no results" if str(i["name"]).lower() in dead else ""))
            at_stake = i["volume"] * base["rpv"]
        else:
            if i["revenue"] == 0:
                reasons.append("no revenue")
            if conv is not None and base["conversion_pct"] and conv < RULES["low_conversion_ratio"] * base["conversion_pct"]:
                reasons.append(f"conversion {conv:.1f}% vs {base['conversion_pct']:.1f}% typical")
            if (bounce is not None and bounce > RULES["high_bounce_ratio"] * base["bounce_pct"]
                    and bounce - base["bounce_pct"] >= RULES["high_bounce_min_points"]):
                reasons.append(f"bounce {bounce:.0f}% vs {base['bounce_pct']:.0f}% typical")
            if (i["prev_revenue"] and i["revenue"] < RULES["revenue_drop_ratio"] * i["prev_revenue"]
                    and i["prev_revenue"] - i["revenue"] >= RULES["revenue_drop_min"]):
                reasons.append(f"revenue {pct(i['revenue'], i['prev_revenue'])}% vs last week")
            gap = max(base["conversion_pct"] - conv, 0) / 100 if conv is not None else 0.0
            at_stake = i["volume"] * gap * (i["aov"] or base_aov)
            if i["prev_revenue"] > i["revenue"]:
                at_stake = max(at_stake, i["prev_revenue"] - i["revenue"])
        if reasons:
            issues.append({**i, "reasons": reasons, "revenue_at_stake": round(at_stake, 2)})
    dead_ends = [i for i in issues if i["reasons"][0].startswith("dead end")]
    issues = [i for i in issues if not i["reasons"][0].startswith("dead end")]
    issues.sort(key=lambda i: -i["revenue_at_stake"])
    dead_ends.sort(key=lambda i: -i["volume"])
    top_rows = sorted(items, key=lambda i: -i["revenue"])[:top]
    for t in top_rows:
        t["revenue_change_pct"] = pct(t["revenue"], t["prev_revenue"])
    return {"considered": len(items), "baseline_top20_median": {**base, "aov": base_aov},
            "top": top_rows, "issues": issues[:issue_top], "issues_total": len(issues),
            "dead_ends": {"count": len(dead_ends), "volume": sum(i["volume"] for i in dead_ends),
                          "revenue_at_stake": round(sum(i["revenue_at_stake"] for i in dead_ends), 2),
                          "names": [i["name"] for i in dead_ends]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overall", required=True)
    ap.add_argument("--search")
    ap.add_argument("--category")
    ap.add_argument("--device", action="append", default=[], help="name=file")
    ap.add_argument("--queries")
    ap.add_argument("--categories")
    ap.add_argument("--products")
    ap.add_argument("--brands")
    ap.add_argument("--min-visits", type=int, default=RULES["min_visits"])
    ap.add_argument("--min-sessions", type=int, default=RULES["min_sessions"])
    ap.add_argument("--top", type=int, default=RULES["movers_top"])
    ap.add_argument("--dead-ends", help="comma-separated query files from the no_search_results / no_revenue presets")
    ap.add_argument("--list-top", type=int, default=RULES["list_top"], help="rows in the top searches / top categories lists")
    ap.add_argument("--issue-top", type=int, default=RULES["issue_top"], help="rows in the searches / categories with issues lists")
    a = ap.parse_args()

    o = card(a.overall)
    kpis = {"overall": kpi_block(*o[:6])}
    search_trends = {}
    if a.search:
        s = card(a.search)
        kpis["search"] = kpi_block(*s[:6])
        search_trends = s[6]
    if a.category:
        kpis["category"] = kpi_block(*card(a.category)[:6])
    if a.search and a.category:
        other_rev = kpis["overall"]["this"]["revenue"] - kpis["search"]["this"]["revenue"] - kpis["category"]["this"]["revenue"]
        other_prev = kpis["overall"]["last"]["revenue"] - kpis["search"]["last"]["revenue"] - kpis["category"]["last"]["revenue"]
        kpis["other"] = {"revenue": round(other_rev, 2), "prev_revenue": round(other_prev, 2),
                         "change_pct": pct(other_rev, other_prev),
                         "note": "overall minus search minus category (approximate: visits overlap)"}
        total = kpis["overall"]["revenue_delta"]
        if total:
            kpis["share_of_revenue_change_pct"] = {
                "search": round(kpis["search"]["revenue_delta"] / total * 100, 1),
                "category": round(kpis["category"]["revenue_delta"] / total * 100, 1),
                "other": round((other_rev - other_prev) / total * 100, 1)}
    if a.device:
        kpis["devices"] = {}
        for spec in a.device:
            name, _, path = spec.partition("=")
            kpis["devices"][name] = kpi_block(*card(path)[:6])
        dsum = sum(d["this"]["revenue"] for d in kpis["devices"].values())
        kpis["devices_cover_overall_pct"] = round(dsum / kpis["overall"]["this"]["revenue"] * 100, 1) \
            if kpis["overall"]["this"]["revenue"] else None

    movers = {}
    if a.queries:
        baseline = num(search_trends.get("browse_sessions")) if search_trends.get("browse_sessions") else None
        if baseline is None:
            print("warning: no --search card, so query trends are not adjusted for overall search growth",
                  file=sys.stderr)
        movers["queries"] = query_movers(rows_of(a.queries, "query"), baseline, a.min_sessions, a.top)
    if a.categories:
        movers["categories"] = money_movers(rows_of(a.categories, "cat_id"), "category", a.min_visits, a.top, ("cat_id",))
    if a.products:
        movers["products"] = money_movers(rows_of(a.products, "prod_id"), "product_title", a.min_visits, a.top,
                                          ("prod_id", "brand"))
    if a.brands:
        movers["brands"] = money_movers(rows_of(a.brands, "brand"), "brand", a.min_visits, a.top)

    lists = {}
    if a.queries:
        query_rows = rows_of(a.queries, "query")
        dead_names = []
        if a.dead_ends:
            dead_rows = rows_of(a.dead_ends, "query")
            known = {str(r.get("query")).lower() for r in query_rows}
            query_rows += [r for r in dead_rows if str(r.get("query")).lower() not in known]
            dead_names = [r.get("query") for r in dead_rows
                          if num(r.get("product_page_views")) == 0 and num(r.get("browse_sessions")) > 0]
        lists["searches"] = top_and_issues(query_rows, "query", "browse_sessions", a.min_sessions,
                                           a.list_top, a.issue_top, dead_names)
    if a.categories:
        lists["categories"] = top_and_issues(rows_of(a.categories, "cat_id"), "category", "visits", a.min_visits,
                                             a.list_top, a.issue_top)

    out = {"kpis": kpis, "movers": movers, "top_and_issues": lists}
    if MISSING:
        out["missing_values"] = {"counted_as_zero": sorted(MISSING)[:50], "count": len(MISSING),
                                 "note": "these values were missing or not numbers (e.g. NA) and were counted as 0; "
                                         "missing conversion and bounce rates were left out of the medians and checks"}
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
