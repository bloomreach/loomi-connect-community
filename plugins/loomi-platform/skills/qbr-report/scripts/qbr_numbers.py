#!/usr/bin/env python3
"""Work out the numbers for a quarterly business review from saved Loomi Connect output.

Usage:
  python3 qbr_numbers.py --qoq overall=o.json [--qoq search=s.json --qoq category=c.json --qoq mobile=m.json ...]
         [--yoy overall=o_ly.json --yoy search=s_ly.json ...]
         [--queries q.json] [--categories cats.json] [--products p.json] [--brands b.json]
         [--dead-ends nr.json,nrev.json]
         [--experiments exps.json ...] [--rules "search ranking=rr.json" ...] [--start 2026-07-01 --end 2026-09-30]
         [--min-visits N] [--min-sessions N] [--top N] [--list-top N] [--issue-top N] [--out qbr.json]
         (defaults: references/rules.json)

Inputs are raw Loomi Connect responses, saved to files:
  --qoq NAME=FILE   a KPI card (get_discovery_overall_performance, _search_performance, _category_performance,
                    or the overall card with device_type) for the quarter, with compare_start_date and
                    compare_end_date set to the previous quarter. NAME: overall, search, category, desktop,
                    mobile or tablet.
  --yoy NAME=FILE   the same card for the same quarter, compared with the same quarter last year.
  tables            get_discovery_query_performance, get_discovery_category_performance_table,
                    get_discovery_product_performance_table, get_discovery_brand_performance for the quarter
                    against the previous quarter. Comma-separate several pages of one table.
  --experiments     search_discovery_experiments list pages.
  --rules NAME=FILE a Discovery rule list (ranking, media, facet rules or redirects); NAME labels the type.

Prints JSON with:
  kpis:            revenue, revenue per visit, conversion and average order value for overall, search,
                   category, other and each device: this quarter, the previous quarter and the same quarter last
                   year, with the changes (conversion in percentage points);
  top_and_issues:  the top searches and categories by revenue, and those with problems ranked by revenue at stake
                   (the weekly-ecommerce-briefing method, with quarter-sized thresholds);
  movers:          queries against overall search growth, and categories, products and brands by revenue change;
  work_done:       experiments that ran in the quarter and rules created or changed in it, by type.
Never outputs editor names or emails. Standard library only; no network access.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING_TEXT = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
CARD_NAMES = ("overall", "search", "category", "desktop", "mobile", "tablet")
DEVICES = ("desktop", "mobile", "tablet")
MISSING = set()


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def number(v):
    """A number from a tool value ("$1,000.00", "2.50%", "(12.00)"), or None when missing or not a number."""
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
    s = re.sub(r"[$£€,%\s]", "", s)
    m = re.match(r"[+]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    if not m:
        return None
    x = float(m.group(0))
    if not math.isfinite(x):
        return None
    return -x if negative else x


def num(v, where=None):
    """number(v), with a missing value counted as 0; `where` names it in the output's missing_values."""
    x = number(v)
    if x is None:
        if where:
            MISSING.add(where)
        return 0.0
    return x


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    while isinstance(data, dict):
        if data.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {str(data.get('error') or 'no error text')[:200]} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        if "result" in data and isinstance(data["result"], (dict, list)):
            data = data["result"]
        elif "data" in data and isinstance(data["data"], (dict, list)) and "rows" not in data and "current" not in data:
            data = data["data"]
        else:
            break
    return data


def pair(text):
    """NAME=FILE, split on the first "="."""
    name, sep, path = text.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE, got {text!r}")
    return name.strip(), path.strip()


def card_pair(text):
    name, path = pair(text)
    if name.lower() not in CARD_NAMES:
        raise argparse.ArgumentTypeError(f"card name must be one of {', '.join(CARD_NAMES)}, got {name!r}")
    return name.lower(), path


def pct(a, b):
    return (a / b - 1) * 100 if b else None


def r2(x):
    return None if x is None else round(x, 2)


# ---------------------------------------------------------------------------------------------
# KPIs

def card(path):
    d = load(path)
    if not isinstance(d, dict) or "current" not in d or "previous" not in d:
        fail(f"{path}: no current and previous values found; is this a Discovery KPI card?")
    out = {}
    for when in ("current", "previous"):
        x = d[when] or {}
        out[when] = tuple(num(x.get(k), f"{path} {when}.{k}") for k in ("revenue", "visits", "conversions"))
    out["trends"] = d.get("trends") or {}
    return out


def rates(t):
    rev, visits, orders = t
    return {"revenue": round(rev, 2), "visits": int(visits), "orders": int(orders),
            "rpv": r2(rev / visits) if visits else None,
            "conversion_pct": r2(orders / visits * 100) if visits else None,
            "aov": r2(rev / orders) if orders else None}


def changes(cur, base):
    rev, visits, orders = cur
    brev, bvisits, borders = base
    out = {"revenue_pct": r2(pct(rev, brev)), "visits_pct": r2(pct(visits, bvisits)),
           "orders_pct": r2(pct(orders, borders)), "revenue_delta": round(rev - brev, 2)}
    if visits and bvisits:
        out["rpv_pct"] = r2(pct(rev / visits, brev / bvisits))
        out["conversion_pts"] = r2((orders / visits - borders / bvisits) * 100)
    if orders and borders:
        out["aov_pct"] = r2(pct(rev / orders, brev / borders))
    return out


def kpis(qoq, yoy):
    out, warnings = {}, []
    for name in CARD_NAMES:
        if name not in qoq:
            continue
        cur, prev = qoq[name]["current"], qoq[name]["previous"]
        block = {"this_quarter": rates(cur), "previous_quarter": rates(prev), "vs_previous_quarter": changes(cur, prev)}
        if prev[1] == 0:
            block["vs_previous_quarter"] = None
            block["note_previous"] = "no data for the previous quarter"
        if name in yoy:
            ycur, ly = yoy[name]["current"], yoy[name]["previous"]
            if cur[0] and abs(ycur[0] - cur[0]) / cur[0] * 100 > RULES["same_period_tolerance_pct"]:
                warnings.append(f"{name}: this quarter's revenue differs between the --qoq and --yoy cards "
                                f"({cur[0]:.2f} vs {ycur[0]:.2f}); the two calls covered different dates")
            if ly[1] == 0:
                block["same_quarter_last_year"] = None
                block["vs_same_quarter_last_year"] = None
                block["note_last_year"] = "no data for the same quarter last year (the tool returns zeros, not an error)"
            else:
                block["same_quarter_last_year"] = rates(ly)
                block["vs_same_quarter_last_year"] = changes(cur, ly)
        out[name] = block
    if "overall" in qoq and "search" in qoq and "category" in qoq:
        o, s, c = qoq["overall"], qoq["search"], qoq["category"]
        other = o["current"][0] - s["current"][0] - c["current"][0]
        other_prev = o["previous"][0] - s["previous"][0] - c["previous"][0]
        block = {"revenue": round(other, 2), "previous_quarter_revenue": round(other_prev, 2),
                 "revenue_pct": r2(pct(other, other_prev)),
                 "note": "overall minus search minus category (approximate: visits overlap)"}
        if all(k in yoy for k in ("overall", "search", "category")) and yoy["overall"]["previous"][1]:
            ly = yoy["overall"]["previous"][0] - yoy["search"]["previous"][0] - yoy["category"]["previous"][0]
            block["same_quarter_last_year_revenue"] = round(ly, 2)
            block["vs_same_quarter_last_year_pct"] = r2(pct(other, ly))
        out["other"] = block
        total = o["current"][0] - o["previous"][0]
        if total:
            out["share_of_revenue_change_pct"] = {
                "search": r2((s["current"][0] - s["previous"][0]) / total * 100),
                "category": r2((c["current"][0] - c["previous"][0]) / total * 100),
                "other": r2((other - other_prev) / total * 100)}
    devs = [d for d in DEVICES if d in qoq]
    if devs and "overall" in qoq and qoq["overall"]["current"][0]:
        out["devices_cover_overall_pct"] = r2(sum(qoq[d]["current"][0] for d in devs) / qoq["overall"]["current"][0] * 100)
    return out, warnings


# ---------------------------------------------------------------------------------------------
# Tables: top, issues and movers (the weekly-ecommerce-briefing method, quarter thresholds)

def rows_of(paths, idkey):
    seen = {}
    for p in paths.split(","):
        p = p.strip()
        if not p:
            continue
        d = load(p)
        rows = d.get("rows") if isinstance(d, dict) else d
        if not isinstance(rows, list):
            fail(f"{p}: no rows list found; is this a Discovery performance table?")
        for r in rows:
            key = str(r.get(idkey) or "").strip().lower()
            if key:
                seen[key] = r
    return list(seen.values())


def median(values):
    s = sorted(values)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if n else 0.0


def money_movers(rows, label, min_visits, top, extra=()):
    items = []
    for r in rows:
        v, v0 = num(r.get("visits")), num(r.get("prev_visits"))
        if max(v, v0) < min_visits:
            continue
        where = f"{label} {str(r.get(label)).strip()!r}"
        r1, r0 = num(r.get("revenue"), where), num(r.get("prev_revenue"), where)
        item = {"name": str(r.get(label) or "").strip(), "revenue": round(r1, 2), "previous_quarter_revenue": round(r0, 2),
                "delta": round(r1 - r0, 2), "change_pct": r2(pct(r1, r0)), "visits": int(v), "previous_visits": int(v0)}
        for k in extra:
            item[k] = r.get(k)
        items.append(item)
    up = sorted([i for i in items if i["delta"] > 0], key=lambda i: (-i["delta"], i["name"]))[:top]
    down = sorted([i for i in items if i["delta"] < 0], key=lambda i: (i["delta"], i["name"]))[:top]
    return {"considered": len(items), "rising": up, "falling": down}


def query_movers(rows, baseline_pct, min_sessions, top):
    growth = 1 + (baseline_pct or 0) / 100
    items = []
    for r in rows:
        cur, prev = num(r.get("browse_sessions")), num(r.get("prev_browse_sessions"))
        if max(cur, prev) < min_sessions:
            continue
        expected = prev * growth
        rev, rev0 = num(r.get("revenue")), num(r.get("prev_revenue"))
        items.append({"query": r.get("query"), "sessions": int(cur), "previous_sessions": int(prev),
                      "vs_baseline_pct": r2((cur / expected - 1) * 100) if expected else None,
                      "trend_score": round((cur - expected) / math.sqrt(max(expected, 1)), 2),
                      "revenue": round(rev, 2), "revenue_delta": round(rev - rev0, 2),
                      "conversion_rate": r.get("conversion_rate"), "bounce_rate": r.get("bounce_rate"),
                      "new": prev == 0})
    key = lambda i: str(i["query"])
    rising = sorted([i for i in items if i["trend_score"] > 0], key=lambda i: (-i["trend_score"], key(i)))[:top]
    falling = sorted([i for i in items if i["trend_score"] < 0], key=lambda i: (i["trend_score"], key(i)))[:top]
    by_money = sorted(items, key=lambda i: (i["revenue_delta"], key(i)))
    return {"considered": len(items), "baseline_sessions_change_pct": baseline_pct, "rising": rising,
            "falling": falling, "biggest_revenue_drop": [i for i in by_money if i["revenue_delta"] < 0][:top],
            "biggest_revenue_gain": [i for i in by_money[::-1] if i["revenue_delta"] > 0][:top]}


def top_and_issues(rows, label, vol_key, min_vol, top, issue_top, dead_names=()):
    items = []
    for r in rows:
        vol, vol0 = num(r.get(vol_key)), num(r.get("prev_" + vol_key))
        if max(vol, vol0) < min_vol:
            continue
        visits = num(r.get("visits")) or vol
        where = f"{label} {str(r.get(label)).strip()!r}"
        items.append({"name": str(r.get(label) or "").strip(), "id": r.get("cat_id"), "volume": int(vol),
                      "previous_volume": int(vol0), "revenue": num(r.get("revenue"), where),
                      "previous_revenue": num(r.get("prev_revenue"), where),
                      "conversion_pct": number(r.get("conversion_rate")), "bounce_pct": number(r.get("bounce_rate")),
                      "views_per_visit": num(r.get("product_page_views")) / visits if visits else 0.0,
                      "aov": num(r.get("aov")), "rpv": num(r.get("rpv"))})
    if not items:
        return {"considered": 0, "top": [], "issues": [], "issues_total": 0}
    peers = sorted(items, key=lambda i: (-i["volume"], i["name"]))[:RULES["peers"]]
    base = {k: median([p[k] for p in peers if p[k] is not None]) for k in ("conversion_pct", "bounce_pct", "rpv")}
    base_aov = median([p["aov"] for p in peers if p["aov"]])
    dead = {str(n).strip().lower() for n in dead_names}
    issues, dead_ends = [], []
    for i in items:
        if i["volume"] < min_vol:
            continue  # only the previous quarter had traffic
        conv, bounce = i["conversion_pct"], i["bounce_pct"]
        is_dead = i["name"].lower() in dead or (i["views_per_visit"] == 0 and bounce is not None
                                                 and bounce >= RULES["dead_end_bounce_pct"])
        if is_dead and label == "query":
            dead_ends.append({**i, "revenue_at_stake": i["volume"] * base["rpv"]})
            continue
        reasons = []
        if i["revenue"] == 0:
            reasons.append("no revenue")
        if conv is not None and base["conversion_pct"] and conv < RULES["low_conversion_ratio"] * base["conversion_pct"]:
            reasons.append(f"conversion {conv:.1f}% vs {base['conversion_pct']:.1f}% typical")
        if (bounce is not None and bounce > RULES["high_bounce_ratio"] * base["bounce_pct"]
                and bounce - base["bounce_pct"] >= RULES["high_bounce_min_points"]):
            reasons.append(f"bounce {bounce:.0f}% vs {base['bounce_pct']:.0f}% typical")
        if (i["previous_revenue"] and i["revenue"] < RULES["revenue_drop_ratio"] * i["previous_revenue"]
                and i["previous_revenue"] - i["revenue"] >= RULES["revenue_drop_min"]):
            reasons.append(f"revenue {pct(i['revenue'], i['previous_revenue']):.1f}% vs previous quarter")
        if not reasons:
            continue
        gap = max(base["conversion_pct"] - conv, 0) / 100 if conv is not None else 0.0
        at_stake = i["volume"] * gap * (i["aov"] or base_aov)
        at_stake = max(at_stake, i["previous_revenue"] - i["revenue"])
        issues.append({**i, "reasons": reasons, "revenue_at_stake": at_stake})

    def tidy(i):
        out = dict(i)
        for k in ("revenue", "previous_revenue", "revenue_at_stake"):
            if k in out:
                out[k] = round(out[k], 2)
        out["views_per_visit"] = round(out["views_per_visit"], 2)
        return out

    issues.sort(key=lambda i: (-i["revenue_at_stake"], i["name"]))
    dead_ends.sort(key=lambda i: (-i["volume"], i["name"]))
    top_rows = sorted(items, key=lambda i: (-i["revenue"], i["name"]))[:top]
    out = {"considered": len(items),
           "typical_top_median": {k: r2(v) for k, v in {**base, "aov": base_aov}.items()},
           "top": [{**tidy(t), "revenue_change_pct": r2(pct(t["revenue"], t["previous_revenue"]))} for t in top_rows],
           "issues": [tidy(i) for i in issues[:issue_top]], "issues_total": len(issues)}
    if label == "query":
        out["dead_ends"] = {"count": len(dead_ends), "sessions": sum(i["volume"] for i in dead_ends),
                            "revenue_at_stake": round(sum(i["revenue_at_stake"] for i in dead_ends), 2),
                            "names": [i["name"] for i in dead_ends][:20]}
    return out


# ---------------------------------------------------------------------------------------------
# Work done in the quarter

def ms_window(start, end):
    try:
        s = dt.datetime.combine(dt.date.fromisoformat(start), dt.time(), dt.timezone.utc)
        e = dt.datetime.combine(dt.date.fromisoformat(end), dt.time(), dt.timezone.utc) + dt.timedelta(days=1)
    except ValueError as e:
        fail(f"--start and --end must be dates like 2026-07-01 ({e}).")
    return int(s.timestamp() * 1000), int(e.timestamp() * 1000) - 1


def day(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() if ms else None


def records(path):
    d = load(path)
    recs = d if isinstance(d, list) else (d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), list) else None)
    if recs is None and isinstance(d, dict):
        recs = d.get("rules") or d.get("items") or ([d] if "id" in d else None)
    if not isinstance(recs, list):
        fail(f"{path}: no list of records found; is this a Discovery experiment or rule list?")
    return [r for r in recs if isinstance(r, dict)]


def work_done(exp_paths, rule_pairs, start_ms, end_ms):
    seen, ran = set(), []
    for p in exp_paths:
        for r in records(p):
            if r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            s, e = number(r.get("startedAt")), number(r.get("endedAt"))
            if not s or s > end_ms or (e and e < start_ms):
                continue
            ran.append({"id": r.get("id"), "name": r.get("experimentName"), "status": r.get("experimentStatus"),
                        "type": r.get("experimentType"), "started": day(s), "ended": day(e),
                        "started_in_quarter": start_ms <= s <= end_ms, "ended_in_quarter": bool(e and start_ms <= e <= end_ms)})
    ran.sort(key=lambda x: (x["started"] or "", str(x["id"])))
    rules = {}
    for label, p in rule_pairs:
        b = rules.setdefault(label, {"listed": 0, "created_in_quarter": 0, "changed_in_quarter": 0,
                                     "enabled_now": 0, "expired_but_enabled": 0})
        for r in records(p):
            b["listed"] += 1
            c, m = number(r.get("createdAt")), number(r.get("lastModifiedAt"))
            if c and start_ms <= c <= end_ms:
                b["created_in_quarter"] += 1
            elif m and start_ms <= m <= end_ms:
                b["changed_in_quarter"] += 1
            if r.get("enabled") is True:
                b["enabled_now"] += 1
                if str(r.get("durationTag") or "").lower() == "expired":
                    b["expired_but_enabled"] += 1
    return {"experiments": {"ran_in_quarter": len(ran),
                            "started_in_quarter": sum(1 for x in ran if x["started_in_quarter"]),
                            "ended_in_quarter": sum(1 for x in ran if x["ended_in_quarter"]),
                            "still_running": sum(1 for x in ran if str(x["status"]).upper() == "RUNNING"),
                            "list": ran[:RULES["work_listed"]],
                            "note": "winners and lift are only in each experiment's detail and report: read them out with discovery-experiment-readout"},
            "rules": rules,
            "rules_note": "changed_in_quarter counts rules last edited in the quarter and created before it; an edit after the quarter hides an earlier one"}


# ---------------------------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qoq", action="append", default=[], type=card_pair, help="NAME=FILE: a KPI card for the quarter compared with the previous quarter (repeatable)")
    ap.add_argument("--yoy", action="append", default=[], type=card_pair, help="NAME=FILE: the same card compared with the same quarter last year (repeatable)")
    ap.add_argument("--queries", help="get_discovery_query_performance (comma-separate pages)")
    ap.add_argument("--categories", help="get_discovery_category_performance_table (comma-separate pages)")
    ap.add_argument("--products", help="get_discovery_product_performance_table (comma-separate pages)")
    ap.add_argument("--brands", help="get_discovery_brand_performance (comma-separate pages)")
    ap.add_argument("--dead-ends", help="comma-separated query files from the no_search_results / no_revenue presets")
    ap.add_argument("--experiments", action="append", default=[], help="a search_discovery_experiments list page (repeatable)")
    ap.add_argument("--rules", action="append", default=[], type=pair, help="NAME=FILE: a Discovery rule or redirect list, NAME labels its type (repeatable)")
    ap.add_argument("--start", help="first day of the quarter, YYYY-MM-DD (for work done)")
    ap.add_argument("--end", help="last day of the quarter, YYYY-MM-DD (for work done)")
    ap.add_argument("--min-visits", type=int, default=RULES["min_visits"], help="minimum visits for categories, products and brands (default: rules.json)")
    ap.add_argument("--min-sessions", type=int, default=RULES["min_sessions"], help="minimum sessions for searches (default: rules.json)")
    ap.add_argument("--top", type=int, default=RULES["movers_top"], help="rows per movers list (default: rules.json)")
    ap.add_argument("--list-top", type=int, default=RULES["list_top"], help="rows in the top lists (default: rules.json)")
    ap.add_argument("--issue-top", type=int, default=RULES["issue_top"], help="rows in the problem lists (default: rules.json)")
    ap.add_argument("--out", help="write the JSON here instead of printing it")
    a = ap.parse_args()

    qoq = {n: card(p) for n, p in a.qoq}
    yoy = {n: card(p) for n, p in a.yoy}
    if yoy and not qoq:
        fail("--yoy cards need the matching --qoq cards for this quarter.")
    out = {"ok": True}
    k, warnings = kpis(qoq, yoy)
    if k:
        out["kpis"] = k

    lists, movers = {}, {}
    if a.queries:
        qrows = rows_of(a.queries, "query")
        # As in weekly-ecommerce-briefing: the search card's own browse_sessions trend is the baseline.
        baseline = None
        if "search" in qoq:
            baseline = number(qoq["search"]["trends"].get("browse_sessions"))
            if baseline is None and qoq["search"]["previous"][1]:
                baseline = pct(qoq["search"]["current"][1], qoq["search"]["previous"][1])
                warnings.append("the search card has no browse_sessions trend, so query trends are adjusted "
                                "for the change in search visits instead")
        if baseline is None:
            warnings.append("no --qoq search card, so query trends are not adjusted for overall search growth")
        movers["queries"] = query_movers(qrows, r2(baseline), a.min_sessions, a.top)
        dead_names = []
        if a.dead_ends:
            drows = rows_of(a.dead_ends, "query")
            known = {str(r.get("query")).strip().lower() for r in qrows}
            qrows += [r for r in drows if str(r.get("query")).strip().lower() not in known]
            dead_names = [r.get("query") for r in drows
                          if num(r.get("product_page_views")) == 0 and num(r.get("browse_sessions")) > 0]
        lists["searches"] = top_and_issues(qrows, "query", "browse_sessions", a.min_sessions, a.list_top,
                                           a.issue_top, dead_names)
    if a.categories:
        crows = rows_of(a.categories, "cat_id")
        movers["categories"] = money_movers(crows, "category", a.min_visits, a.top, ("cat_id",))
        lists["categories"] = top_and_issues(crows, "category", "visits", a.min_visits, a.list_top, a.issue_top)
    if a.products:
        movers["products"] = money_movers(rows_of(a.products, "prod_id"), "product_title", a.min_visits, a.top,
                                          ("prod_id", "brand"))
    if a.brands:
        movers["brands"] = money_movers(rows_of(a.brands, "brand"), "brand", a.min_visits, a.top)
    if lists:
        out["top_and_issues"] = lists
    if movers:
        out["movers"] = movers
    if a.experiments or a.rules:
        if not (a.start and a.end):
            fail("--experiments and --rules need --start and --end (the quarter's first and last day).")
        start_ms, end_ms = ms_window(a.start, a.end)
        out["work_done"] = {"quarter": f"{a.start} to {a.end} (UTC)",
                            **work_done(a.experiments, a.rules, start_ms, end_ms)}
    if MISSING:
        out["missing_values"] = {"counted_as_zero": sorted(MISSING)[:50], "count": len(MISSING),
                                 "note": "these values were missing or not numbers (e.g. NA) and were counted as 0"}
    if warnings:
        out["warnings"] = warnings
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            fail(f"{a.out}: can't write it ({e}).")
        print(json.dumps({"ok": True, "out": a.out}))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
