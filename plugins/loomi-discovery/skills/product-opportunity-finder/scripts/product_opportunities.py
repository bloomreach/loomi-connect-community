#!/usr/bin/env python3
"""Sort Discovery products into actionable opportunity groups.

Usage:
  python3 product_opportunities.py [options] products1.json [products2.json ...]

Each products file is the raw JSON from get_discovery_product_performance_table (all pages,
any sort). Options:
  --catalog-pids FILE [FILE ...]
                        optional: product grid responses (query "*", fl=pid, paged with start)
                        or plain text files with one product ID per line. Catalog products missing from the
                        performance table are reported as dead weight (no views).
  --min-visits N        products with fewer visits are too small to judge (default 30)
  --high-pct P          "high visibility" = visits at or above this percentile (default 90)
  --low-pct P           "low visibility" = visits at or below this percentile (default 50)
  --winner-pct P        "previous winner" = previous revenue at or above this percentile (default 90)
  --decline PCT         trend-adjusted revenue fall that counts as declining (default 20)
  --gem-target-pct P    hidden gems are valued as if they reached this visits percentile (default 75)
  --gap F               how far from the median counts as "well below/above" (default 0.15)
  --limit N             rows per group in the output (default 15)
  --markdown            print Markdown tables instead of JSON

Groups (a product appears once, in the group with the most revenue at stake):
  fix_product_page  high visits, add-to-cart rate well below the median product
  over_exposed      high visits, add-to-cart normal, conversion rate well below the median
  hidden_gem        low visits, conversion rate well above the median
  declining_winner  a top earner last period whose revenue fell, after allowing for the
                    account's overall trend (checked whatever its visits now, even 0)
  dead_weight       no views (in the catalog but not in the report, or 0 visits and not a
                    declining winner)

"Well below/above" means at least --gap (15%) from the median AND the 90% Wilson interval for the
product's rate excludes the median, so small products with noisy rates aren't flagged.

Revenue at stake (an upper bound for the period, not a forecast):
  fix_product_page  visits x (median ATC rate - ATC rate) x orders per ATC x AOV
  over_exposed      visits x (median CR - CR) x AOV
  hidden_gem        (target visits - visits) x ((CR + median CR) / 2) x AOV
  declining_winner  previous revenue x (1 + account revenue trend) - current revenue
  dead_weight       none; reported as a count
Standard library only; no network access.
"""
import argparse
import json
import math
import statistics
import sys

Z = 1.645  # 90% two-sided


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
    """Stop when Loomi Connect returned an error as data (success: false) instead of rows."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            print(json.dumps({"ok": False, "error": msg}), file=sys.__stdout__)
            sys.exit(1)
    return doc


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else data


def wilson(successes, n):
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    d = 1 + Z * Z / n
    c = p + Z * Z / (2 * n)
    m = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def pct(values, p):
    v = sorted(values)
    if not v:
        return 0
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def load_catalog(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = unwrap(check(json.loads(text), path))
        docs = data.get("response", {}).get("docs", [])
        return {str(d.get("pid")) for d in docs if d.get("pid") is not None}
    except (ValueError, AttributeError):
        return {line.strip() for line in text.splitlines() if line.strip()}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("products", nargs="+")
    ap.add_argument("--catalog-pids", nargs="+")
    ap.add_argument("--min-visits", type=int, default=30)
    ap.add_argument("--high-pct", type=float, default=90)
    ap.add_argument("--low-pct", type=float, default=50)
    ap.add_argument("--winner-pct", type=float, default=90)
    ap.add_argument("--decline", type=float, default=20)
    ap.add_argument("--gem-target-pct", type=float, default=75)
    ap.add_argument("--gap", type=float, default=0.15)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out", help="write the output to this file instead of printing it (for clients that refuse shell redirects)")
    a = ap.parse_args()
    if a.out:
        sys.stdout = open(a.out, "w", encoding="utf-8")

    rows, seen, incomplete = [], set(), 0
    for p in a.products:
        with open(p, encoding="utf-8") as f:
            for r in unwrap(check(json.load(f), p)).get("rows", []):
                pid = str(r.get("prod_id"))
                if pid in seen:
                    continue
                seen.add(pid)
                if any(num(r.get(k)) is None for k in ("visits", "prev_visits", "revenue", "prev_revenue")):
                    incomplete += 1
                rows.append({
                    "pid": pid, "title": r.get("product_title"), "brand": (r.get("brand") or "").strip() or "(none)",
                    "visits": num(r.get("visits")) or 0, "prev_visits": num(r.get("prev_visits")) or 0,
                    "atc": num(r.get("atc")) or 0, "conversions": num(r.get("conversions")) or 0,
                    "revenue": num(r.get("revenue")) or 0, "prev_revenue": num(r.get("prev_revenue")) or 0,
                    "aov": num(r.get("aov")) or 0, "prev_conversions": num(r.get("prev_conversions")) or 0,
                })

    tot_rev = sum(r["revenue"] for r in rows)
    tot_prev = sum(r["prev_revenue"] for r in rows)
    trend = (tot_rev / tot_prev - 1) if tot_prev else 0.0
    tot_v = sum(r["visits"] for r in rows)
    tot_pv = sum(r["prev_visits"] for r in rows)
    visit_trend = (tot_v / tot_pv - 1) if tot_pv else 0.0
    lo_gap, hi_gap = 1 - a.gap, 1 + a.gap

    judged = [r for r in rows if r["visits"] >= a.min_visits]
    for r in rows:
        v = r["visits"]
        r["atc_rate"] = r["atc"] / v if v else 0
        r["cr"] = r["conversions"] / v if v else 0
        r["rpv"] = r["revenue"] / v if v else 0
    med_atc = statistics.median([r["atc_rate"] for r in judged]) if judged else 0
    med_cr = statistics.median([r["cr"] for r in judged]) if judged else 0
    med_rpv = statistics.median([r["rpv"] for r in judged]) if judged else 0
    otc_list = [r["conversions"] / r["atc"] for r in judged if r["atc"]]
    orders_per_atc = statistics.median(otc_list) if otc_list else 0
    visits_list = [r["visits"] for r in judged]
    hi_v = pct(visits_list, a.high_pct)
    lo_v = pct(visits_list, a.low_pct)
    target_v = pct(visits_list, a.gem_target_pct)
    win_rev = pct([r["prev_revenue"] for r in rows], a.winner_pct)

    def aov(r):
        return r["aov"] or (r["revenue"] / r["conversions"] if r["conversions"] else 0)

    candidates = []
    # Rates are judged only on products with --min-visits visits; a former winner is checked
    # for decline whatever its visits now (a best seller that dropped to 0 visits is the worst case).
    for r in rows:
        v = r["visits"]
        is_judged = v >= a.min_visits
        flags = []
        atc_lo, atc_hi = wilson(r["atc"], v)
        cr_lo, cr_hi = wilson(r["conversions"], v)
        if is_judged and v >= hi_v and r["atc_rate"] <= lo_gap * med_atc and atc_hi < med_atc:
            otc = r["conversions"] / r["atc"] if r["atc"] else orders_per_atc
            stake = v * (med_atc - r["atc_rate"]) * otc * aov(r)
            flags.append(("fix_product_page", stake,
                          f"{v:.0f} visits x ({med_atc:.1%} - {r['atc_rate']:.1%}) ATC x {otc:.2f} orders/ATC x ${aov(r):,.2f}"))
        elif is_judged and v >= hi_v and r["cr"] <= lo_gap * med_cr and cr_hi < med_cr:
            stake = v * (med_cr - r["cr"]) * aov(r)
            flags.append(("over_exposed", stake,
                          f"{v:.0f} visits x ({med_cr:.1%} - {r['cr']:.1%}) CR x ${aov(r):,.2f}"))
        if is_judged and v <= lo_v and r["conversions"] >= 5 and r["cr"] >= hi_gap * med_cr and cr_lo > med_cr:
            blended = (r["cr"] + med_cr) / 2
            stake = max(target_v - v, 0) * blended * aov(r)
            flags.append(("hidden_gem", stake,
                          f"({target_v:.0f} - {v:.0f}) visits x {blended:.1%} CR (halfway to median) x ${aov(r):,.2f}"))
        if r["prev_revenue"] >= win_rev and r["prev_revenue"] > 0:
            expected = r["prev_revenue"] * (1 + trend)
            adj_change = r["revenue"] / expected - 1 if expected else 0
            if adj_change <= -a.decline / 100:
                stake = expected - r["revenue"]
                flags.append(("declining_winner", stake,
                              f"${r['prev_revenue']:,.0f} prev x (1 {trend:+.1%} account trend) - ${r['revenue']:,.0f} now"))
                r["trend_adjusted_change"] = adj_change
                exp_v = r["prev_visits"] * (1 + visit_trend)
                v_change = v / exp_v - 1 if exp_v else 0
                prev_cr = r.get("prev_conversions", 0) / r["prev_visits"] if r["prev_visits"] else 0
                cr_change = r["cr"] / prev_cr - 1 if prev_cr else 0
                if cr_change <= -0.10 and v_change <= -0.10:
                    driver = "both"
                elif cr_change <= -0.10:
                    driver = "conversion"
                elif v_change <= -0.10:
                    driver = "visibility"
                else:
                    driver = "order value or mix"
                r["decline"] = {"driver": driver, "visits_vs_account_trend": round(v_change, 4),
                                "conversion_rate_change": round(cr_change, 4),
                                "absolute_revenue_change": round(r["revenue"] / r["prev_revenue"] - 1, 4)}
        if flags:
            flags.sort(key=lambda f: -f[1])
            g, stake, how = flags[0]
            candidates.append({
                "group": g, "pid": r["pid"], "title": r["title"], "brand": r["brand"],
                "visits": int(v), "prev_visits": int(r["prev_visits"]),
                "atc_rate": round(r["atc_rate"], 4), "conversion_rate": round(r["cr"], 4),
                "rpv": round(r["rpv"], 2), "aov": round(aov(r), 2),
                "revenue": round(r["revenue"], 2), "prev_revenue": round(r["prev_revenue"], 2),
                "trend_adjusted_change": round(r.get("trend_adjusted_change", 0), 4) if "trend_adjusted_change" in r else None,
                "decline": r.get("decline"),
                "revenue_at_stake": round(stake, 2), "working": how,
                "also": [f[0] for f in flags[1:]],
            })

    declining = {c["pid"] for c in candidates if c["group"] == "declining_winner"}
    dead = [r for r in rows if r["visits"] == 0 and r["pid"] not in declining]
    missing = []
    catalog_size = None
    if a.catalog_pids:
        cat = set()
        for path in a.catalog_pids:
            cat |= load_catalog(path)
        catalog_size = len(cat)
        missing = sorted(cat - seen)
    near_dead = sorted([r for r in rows if r["pid"] not in declining and 0 < r["visits"] < 0.1 * (statistics.median(visits_list) if visits_list else 0)],
                       key=lambda r: r["visits"])

    groups = {}
    for g in ("fix_product_page", "hidden_gem", "declining_winner", "over_exposed"):
        items = sorted([c for c in candidates if c["group"] == g], key=lambda c: -c["revenue_at_stake"])
        groups[g] = {"count": len(items), "revenue_at_stake": round(sum(c["revenue_at_stake"] for c in items), 2),
                     "products": items[: a.limit]}
    groups["dead_weight"] = {
        "count": len(dead) + len(missing),
        "zero_visit_rows": [{"pid": r["pid"], "title": r["title"], "brand": r["brand"]} for r in dead[: a.limit]],
        "catalog_not_in_report": missing[: a.limit * 4],
        "near_dead": [{"pid": r["pid"], "title": r["title"], "brand": r["brand"], "visits": int(r["visits"])}
                      for r in near_dead[: a.limit]],
        "near_dead_count": len(near_dead),
        "note": None if a.catalog_pids else "Pass --catalog-pids to find catalog products with no views at all; the report only lists products that were viewed.",
    }

    out = {
        "products_in_report": len(rows), "products_judged": len(judged), "catalog_size": catalog_size,
        "rows_with_missing_figures": incomplete,
        "missing_figures_note": (f"{incomplete} rows had a missing or unreadable visits or revenue figure, "
                                 "counted as 0." if incomplete else None),
        "baselines": {
            "median_atc_rate": round(med_atc, 4), "median_conversion_rate": round(med_cr, 4),
            "median_rpv": round(med_rpv, 2), "median_orders_per_atc": round(orders_per_atc, 3),
            "high_visibility_visits": round(hi_v), "low_visibility_visits": round(lo_v),
            "gem_target_visits": round(target_v), "previous_winner_revenue": round(win_rev, 2),
            "account_revenue_trend": round(trend, 4), "account_visits_trend": round(visit_trend, 4),
            "total_revenue": round(tot_rev, 2), "total_prev_revenue": round(tot_prev, 2),
        },
        "groups": groups,
    }
    if a.markdown:
        print_markdown(out)
    else:
        json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
        print()


def drv(c):
    d = c.get("decline")
    if not d:
        return ""
    return (f"; driver: {d['driver']} (visits {d['visits_vs_account_trend']:+.0%} vs trend, "
            f"CR {d['conversion_rate_change']:+.0%}, revenue {d['absolute_revenue_change']:+.0%} unadjusted)")


def print_markdown(out):
    b = out["baselines"]
    print(f"Products in report: {out['products_in_report']} (judged: {out['products_judged']}); "
          f"catalog: {out['catalog_size'] or 'not checked'}")
    print(f"Medians: ATC {b['median_atc_rate']:.1%}, CR {b['median_conversion_rate']:.1%}, RPV ${b['median_rpv']:.2f}. "
          f"High visibility >= {b['high_visibility_visits']} visits; low <= {b['low_visibility_visits']}. "
          f"Account revenue trend {b['account_revenue_trend']:+.1%}.\n")
    titles = {"fix_product_page": "Fix the product page", "hidden_gem": "Hidden gems",
              "declining_winner": "Declining winners", "over_exposed": "Over-exposed"}
    for g, t in titles.items():
        grp = out["groups"][g]
        print(f"### {t}: {grp['count']} products, up to ${grp['revenue_at_stake']:,.0f} at stake\n")
        if not grp["products"]:
            print("None found.\n")
            continue
        print("| PID | Title | Brand | Visits | ATC | CR | Revenue (prev) | At stake | Working |")
        print("|---|---|---|---|---|---|---|---|---|")
        for c in grp["products"]:
            print(f"| {c['pid']} | {(c['title'] or '')[:45]} | {c['brand']} | {c['visits']:,} | {c['atc_rate']:.1%} | "
                  f"{c['conversion_rate']:.1%} | ${c['revenue']:,.0f} (${c['prev_revenue']:,.0f}) | "
                  f"${c['revenue_at_stake']:,.0f} | {c['working']}{drv(c)} |")
        print()
    d = out["groups"]["dead_weight"]
    print(f"### Dead weight: {d['count']} products with no views; {d['near_dead_count']} with under 10% of median visits\n")
    if d["note"]:
        print(d["note"] + "\n")
    if out["missing_figures_note"]:
        print(out["missing_figures_note"] + "\n")


if __name__ == "__main__":
    main()
