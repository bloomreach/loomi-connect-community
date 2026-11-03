#!/usr/bin/env python3
"""Build a brand scorecard for a Discovery account from data the assistant has already fetched.

Usage:
  python3 brand_scorecard.py --brands brands.json [--products products.json ...]
      [--queries queries.json] [--shelf grid1.json grid2.json ...] [--ignore "AND,Basics"]
      [--min-visits 500] [--limit 15] [--markdown]

Inputs (raw JSON responses, saved to files):
  --brands    get_discovery_brand_performance, all pages (required).
  --products  get_discovery_product_performance_table, all pages. Used for product counts and
              for previous-period figures (see "Trends" below). Optional but recommended.
  --queries   get_discovery_query_performance sorted by browse_sessions, as many rows as you
              can (500-1000). Used to find searches that contain a brand name. Optional.
  --shelf     product grid responses (rows=24) for the account's top queries. Used to measure
              each brand's share of first-page slots, weighted by the query's sessions (taken
              from --queries; each grid's query is read from the response). Optional.
  --ignore    brand names that are also everyday words (for example "AND", "Basics"), which
              would otherwise match unrelated searches.

Measures per brand:
  revenue share, view share (product-page visits), and the exposure index =
  revenue share / view share (= brand RPV / account RPV). Above 1, the brand earns more per
  view than average; below 1, less. Shelf share = share of first-page slots on the top queries.

Flags (a brand with fewer than --min-visits visits is not judged on exposure):
  under_exposed   exposure index >= 1.25 AND conversion index (brand CR / account CR) >= 1.10
  over_exposed    exposure index <= 0.75 AND conversion index <= 0.85
  premium / budget  exposure index far from 1 only because of price (conversion is normal);
                  reported, but not a ranking problem
  rising/falling  revenue change at least 20% above/below the account's own trend
  brand_search    searches containing the brand name convert at under 75% of the baseline
                  (pooled conversion of all queries in --queries)
  thin_range      brand searches per product in the catalog >= 100

Revenue at stake (upper bounds for the period):
  under/over-exposed  shift = visits x |index - 1| / 2 (half-way to parity);
                      at stake = shift x |brand CR - account CR| x brand AOV
                      (valued on conversion, not RPV, so price level alone adds nothing)
  falling             previous revenue x (1 + account trend) - current revenue
  brand_search        brand-search visits x (baseline CR - their CR) x their AOV

Trends: get_discovery_brand_performance has returned previous-period totals that disagree
with the product table and products overview (30-day window). When --products is given,
previous-period figures are rebuilt from the product table and a warning shows any gap.
Standard library only; no network access.
"""
import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

MARKDOWN = False  # set from --markdown: errors print as text to stderr


def num(v):
    """A number from a Loomi Connect value ("$1,234.50", "12%", 7); None if missing or unreadable."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for ch in "$£€,":
        s = s.replace(ch, "")
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    if s.lower() in ("", "na", "n/a", "-", "—", "null"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            if MARKDOWN:
                print(msg, file=sys.stderr)
            else:
                print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else data


def rows_of(paths):
    out = []
    for p in paths or []:
        with open(p, encoding="utf-8") as f:
            out.extend(unwrap(check(json.load(f), p)).get("rows", []))
    return out


def key(name):
    return (name or "").strip().lower()


def grid_query(grid):
    dbg = grid.get("debug") or {}
    url = dbg.get("feUrl") or ""
    q = parse_qs(urlparse(url).query).get("q")
    return q[0] if q else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brands", nargs="+", required=True)
    ap.add_argument("--products", nargs="*")
    ap.add_argument("--queries", nargs="*")
    ap.add_argument("--shelf", nargs="*")
    ap.add_argument("--ignore", default="")
    ap.add_argument("--min-visits", type=int, default=500)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    global MARKDOWN
    MARKDOWN = a.markdown
    ignore = {key(x) for x in a.ignore.split(",") if x.strip()}
    warnings = []

    brands = {}
    for r in rows_of(a.brands):
        k = key(r.get("brand"))
        if not k:
            continue
        b = brands.setdefault(k, {"brand": (r.get("brand") or "").strip(), "visits": 0, "prev_visits": 0, "atc": 0,
                                  "conversions": 0, "revenue": 0.0, "prev_revenue": 0.0, "products": None})
        b["visits"] += num(r.get("visits")) or 0
        b["prev_visits"] += num(r.get("prev_visits")) or 0
        b["atc"] += num(r.get("atc")) or 0
        b["conversions"] += num(r.get("conversions")) or 0
        b["revenue"] += num(r.get("revenue")) or 0
        b["prev_revenue"] += num(r.get("prev_revenue")) or 0

    tot_v = sum(b["visits"] for b in brands.values())
    tot_r = sum(b["revenue"] for b in brands.values())
    tot_pr_brand = sum(b["prev_revenue"] for b in brands.values())
    prev_source = "brand table"

    prods = rows_of(a.products)
    if prods:
        agg = defaultdict(lambda: {"n": 0, "prev_revenue": 0.0, "prev_visits": 0.0})
        for r in prods:
            g = agg[key(r.get("brand"))]
            g["n"] += 1
            g["prev_revenue"] += num(r.get("prev_revenue")) or 0
            g["prev_visits"] += num(r.get("prev_visits")) or 0
        tot_pr_prod = sum(g["prev_revenue"] for g in agg.values())
        if tot_pr_brand and abs(tot_pr_prod / tot_pr_brand - 1) > 0.05:
            warnings.append(f"Previous-period revenue differs: brand table ${tot_pr_brand:,.0f} vs product table "
                            f"${tot_pr_prod:,.0f}. Trends use the product table.")
        for k, b in brands.items():
            g = agg.get(k)
            b["products"] = g["n"] if g else 0
            b["prev_revenue"] = g["prev_revenue"] if g else 0
            b["prev_visits"] = g["prev_visits"] if g else 0
        prev_source = "product table"
    tot_pr = sum(b["prev_revenue"] for b in brands.values())
    trend = tot_r / tot_pr - 1 if tot_pr else 0
    acct_rpv = tot_r / tot_v if tot_v else 0
    tot_c = sum(b["conversions"] for b in brands.values())
    acct_cr = tot_c / tot_v if tot_v else 0

    # Brand-name searches
    queries = rows_of(a.queries)
    q_base = None
    if queries:
        qv = sum(num(q.get("visits")) or 0 for q in queries)
        qc = sum(num(q.get("conversions")) or 0 for q in queries)
        q_base = qc / qv if qv else None
        patterns = {k: re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
                    for k in brands if len(k) >= 3 and k not in ignore}
        bq = defaultdict(lambda: {"visits": 0.0, "conversions": 0.0, "revenue": 0.0, "queries": []})
        for q in queries:
            text = key(q.get("query"))
            hits = [k for k, p in patterns.items() if p.search(text)]
            # keep the longest brand name only ("zalora basics" beats "basics")
            hits = [h for h in hits if not any(h != o and h in o for o in hits)]
            for h in hits:
                g = bq[h]
                g["visits"] += num(q.get("visits")) or 0
                g["conversions"] += num(q.get("conversions")) or 0
                g["revenue"] += num(q.get("revenue")) or 0
                g["queries"].append((q.get("query"), int(num(q.get("browse_sessions")) or 0)))
        for k, g in bq.items():
            if k in brands:
                g["queries"].sort(key=lambda x: -x[1])
                brands[k]["brand_search"] = g

    # First-page shelf share
    shelf_tot = 0.0
    shelf_queries = []
    if a.shelf:
        sess = {key(q.get("query")): num(q.get("browse_sessions")) or 0 for q in queries}
        slots = defaultdict(float)
        for p in a.shelf:
            with open(p, encoding="utf-8") as f:
                grid = unwrap(check(json.load(f), p))
            qtext = grid_query(grid) or p
            w = sess.get(key(qtext), 0) or 1
            docs = grid.get("response", {}).get("docs", [])[:24]
            shelf_queries.append([qtext, int(w), len(docs)])
            for d in docs:
                slots[key(d.get("brand"))] += w
                shelf_tot += w
        for k, b in brands.items():
            b["shelf_share"] = slots.get(k, 0) / shelf_tot if shelf_tot else None
        if not queries:
            warnings.append("No --queries file, so every shelf query has the same weight.")

    cards = []
    for k, b in brands.items():
        v, r = b["visits"], b["revenue"]
        vs = v / tot_v if tot_v else 0
        rs = r / tot_r if tot_r else 0
        idx = rs / vs if vs else None
        rpv = r / v if v else 0
        exp = b["prev_revenue"] * (1 + trend)
        adj = r / exp - 1 if exp else None
        c = {
            "brand": b["brand"], "products": b["products"], "visits": int(v), "revenue": round(r, 2),
            "revenue_share": round(rs, 5), "view_share": round(vs, 5),
            "exposure_index": round(idx, 3) if idx is not None else None,
            "conversion_rate": round(b["conversions"] / v, 4) if v else None,
            "aov": round(r / b["conversions"], 2) if b["conversions"] else None, "rpv": round(rpv, 2),
            "prev_revenue": round(b["prev_revenue"], 2),
            "revenue_change": round(r / b["prev_revenue"] - 1, 4) if b["prev_revenue"] else None,
            "trend_adjusted_change": round(adj, 4) if adj is not None else None,
            "shelf_share": round(b["shelf_share"], 4) if b.get("shelf_share") is not None else None,
            "flags": [],
        }
        cr = b["conversions"] / v if v else 0
        cr_idx = cr / acct_cr if acct_cr else None
        c["conversion_index"] = round(cr_idx, 3) if cr_idx is not None else None
        baov = r / b["conversions"] if b["conversions"] else 0
        if v >= a.min_visits and idx is not None and cr_idx is not None:
            if idx >= 1.25 and cr_idx >= 1.10:
                shift = v * (idx - 1) / 2
                c["flags"].append({"flag": "under_exposed", "at_stake": round(shift * (cr - acct_cr) * baov, 2),
                                   "working": f"index {idx:.2f}; {shift:,.0f} more visits x ({cr:.1%} - {acct_cr:.1%}) CR x ${baov:,.2f} AOV"})
            elif idx <= 0.75 and cr_idx <= 0.85:
                shift = v * (1 - idx) / 2
                c["flags"].append({"flag": "over_exposed", "at_stake": round(shift * (acct_cr - cr) * baov, 2),
                                   "working": f"index {idx:.2f}; {shift:,.0f} visits moved x ({acct_cr:.1%} - {cr:.1%}) CR x ${baov:,.2f} AOV"})
            elif idx >= 1.25:
                c["flags"].append({"flag": "premium", "at_stake": 0,
                                   "working": f"index {idx:.2f} from a ${baov:,.0f} AOV; conversion {cr:.1%} vs {acct_cr:.1%}"})
            elif idx <= 0.75:
                c["flags"].append({"flag": "budget", "at_stake": 0,
                                   "working": f"index {idx:.2f} from a ${baov:,.0f} AOV; conversion {cr:.1%} vs {acct_cr:.1%}"})
        if b["prev_revenue"] >= 0.001 * tot_pr and adj is not None:
            if adj >= 0.20:
                c["flags"].append({"flag": "rising", "at_stake": 0,
                                   "working": f"{adj:+.0%} vs the account trend ({trend:+.0%})"})
            elif adj <= -0.20:
                c["flags"].append({"flag": "falling", "at_stake": round(exp - r, 2),
                                   "working": f"${b['prev_revenue']:,.0f} prev x (1 {trend:+.1%}) - ${r:,.0f} now"})
        g = b.get("brand_search")
        if g:
            bcr = g["conversions"] / g["visits"] if g["visits"] else 0
            baov = g["revenue"] / g["conversions"] if g["conversions"] else (c["aov"] or 0)
            sessions = sum(s for _, s in g["queries"])
            c["brand_search"] = {"sessions": sessions, "visits": int(g["visits"]), "conversion_rate": round(bcr, 4),
                                 "top_queries": g["queries"][:5]}
            if q_base and sessions >= 200 and bcr < 0.75 * q_base:
                c["flags"].append({"flag": "brand_search", "at_stake": round(g["visits"] * (q_base - bcr) * baov, 2),
                                   "working": f"{g['visits']:,.0f} visits x ({q_base:.1%} - {bcr:.1%}) CR x ${baov:,.2f}"})
            if b["products"] is not None and b["products"] > 0 and sessions / b["products"] >= 100:
                c["flags"].append({"flag": "thin_range", "at_stake": 0,
                                   "working": f"{sessions:,} brand searches for {b['products']} product{'s' if b['products'] != 1 else ''}"})
            elif b["products"] == 0 and sessions >= 100:
                c["flags"].append({"flag": "thin_range", "at_stake": 0,
                                   "working": f"{sessions:,} brand searches; no products with views"})
        for f in c["flags"]:
            if f["flag"] == "under_exposed" and c["shelf_share"] is not None and c["shelf_share"] >= rs:
                f["working"] += (f"; already prominent on the top queries (shelf share {c['shelf_share']:.1%} vs "
                                 f"revenue share {rs:.1%}), so look at categories and long-tail queries first")
        c["at_stake"] = round(sum(f["at_stake"] for f in c["flags"]), 2)
        cards.append(c)

    cards.sort(key=lambda c: -c["revenue"])
    groups = {}
    for name in ("under_exposed", "over_exposed", "premium", "budget", "rising", "falling", "brand_search", "thin_range"):
        items = [c for c in cards if any(f["flag"] == name for f in c["flags"])]
        sk = (lambda c, n=name: -next(f["at_stake"] for f in c["flags"] if f["flag"] == n))
        if name in ("rising", "premium", "budget"):
            sk = (lambda c: -(c["trend_adjusted_change"] or 0)) if name == "rising" else (lambda c: -c["visits"])
        if name == "thin_range":
            sk = lambda c: -(c.get("brand_search", {}).get("sessions", 0))
        items.sort(key=sk)
        groups[name] = [{"brand": c["brand"], **next(f for f in c["flags"] if f["flag"] == name)} for c in items[: a.limit]]
        groups[name + "_count"] = len(items)

    out = {
        "brands": len(cards), "account": {
            "visits": int(tot_v), "revenue": round(tot_r, 2), "rpv": round(acct_rpv, 2), "conversion_rate": round(acct_cr, 4),
            "revenue_trend": round(trend, 4), "previous_period_source": prev_source,
            "query_baseline_conversion_rate": round(q_base, 4) if q_base else None,
            "shelf_queries": shelf_queries,
        },
        "warnings": warnings,
        "scorecard": cards[: max(a.limit, 20)],
        "groups": groups,
    }
    if a.markdown:
        print_markdown(out)
    else:
        json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
        print()


def pct(v, signed=False):
    if v is None:
        return "—"
    return f"{v:+.0%}" if signed else f"{v:.1%}"


def print_markdown(out):
    acc = out["account"]
    print(f"Account: {out['brands']} brands, {acc['visits']:,} visits, ${acc['revenue']:,.0f} revenue, RPV ${acc['rpv']:.2f}, "
          f"CR {acc['conversion_rate']:.1%}, revenue trend {acc['revenue_trend']:+.1%} (previous period from the {acc['previous_period_source']}).")
    if acc["query_baseline_conversion_rate"]:
        print(f"Search baseline conversion: {acc['query_baseline_conversion_rate']:.1%}.")
    if acc["shelf_queries"]:
        print("Shelf queries: " + ", ".join(f"{q} ({w:,})" for q, w, _ in acc["shelf_queries"]))
    for w in out["warnings"]:
        print(f"WARNING: {w}")
    print("\n### Scorecard (top brands by revenue)\n")
    print("| Brand | Products | Revenue | Rev share | View share | Index | Shelf share | CR | RPV | Change (vs trend) | Flags |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in out["scorecard"]:
        flags = ", ".join(f["flag"] for f in c["flags"]) or "—"
        idx = f"{c['exposure_index']:.2f}" if c["exposure_index"] is not None else "—"
        print(f"| {c['brand']} | {c['products'] if c['products'] is not None else '—'} | ${c['revenue']:,.0f} | "
              f"{pct(c['revenue_share'])} | {pct(c['view_share'])} | {idx} | {pct(c['shelf_share'])} | "
              f"{pct(c['conversion_rate'])} | ${c['rpv']:.2f} | {pct(c['revenue_change'], True)} "
              f"({pct(c['trend_adjusted_change'], True)}) | {flags} |")
    titles = {"under_exposed": "Under-exposed", "over_exposed": "Over-exposed",
              "premium": "Premium (high RPV from price, not a ranking issue)",
              "budget": "Budget (low RPV from price, not a ranking issue)", "rising": "Rising",
              "falling": "Falling", "brand_search": "Searched by name, converts badly",
              "thin_range": "Brand demand larger than the range"}
    for g, t in titles.items():
        items = out["groups"][g]
        print(f"\n### {t}: {out['groups'][g + '_count']}\n")
        for i in items:
            stake = f" At stake: up to ${i['at_stake']:,.0f}." if i["at_stake"] else ""
            print(f"- **{i['brand']}**: {i['working']}.{stake}")


if __name__ == "__main__":
    main()
