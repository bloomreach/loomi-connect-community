#!/usr/bin/env python3
"""Find strong products ranked low on a Discovery category page.

Usage:
  python3 buried_products.py --grid grid.json [--fold 48] [--top 24] products1.json [products2.json ...]

--grid is the raw JSON from search_discovery_product_grid_insights with search_by="category",
fl including pid,title,brand,price and a large rows value (about 200).
Each products file is the raw JSON from get_discovery_product_performance_table (sorted by
revenue; one or more pages). That report has no category filter, so products are matched to
the category by product ID.

Prints JSON with:
  - top_window: brand mix and repeated titles in the first --top positions;
  - brands_missing_from_top: brands with many products in the category but none in the top;
  - buried: products ranked below --fold whose revenue per visit or conversion rate is at
    least the median of the matched products in the top window;
  - weak_top: products in the top window with views but conversion well below that median.
Standard library only; no network access.
"""
import argparse
import json
import math
import statistics
import sys
from collections import Counter


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
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else data


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", required=True)
    ap.add_argument("--fold", type=int, default=48, help="positions above this count as visible (default 48)")
    ap.add_argument("--top", type=int, default=24, help="size of the first screen or page (default 24)")
    ap.add_argument("products", nargs="*")
    a = ap.parse_args()

    with open(a.grid, encoding="utf-8") as f:
        grid = unwrap(check(json.load(f), a.grid))
    docs = grid.get("response", {}).get("docs", [])
    num_found = grid.get("response", {}).get("numFound")
    pos = {str(d.get("pid")): i + 1 for i, d in enumerate(docs)}

    top = docs[: a.top]
    # Some brand names carry trailing spaces ("Pacific "); trim on both sides before comparing.
    brand_top = Counter(str(d.get("brand") or "").strip() or "(none)" for d in top)
    repeated = {t: n for t, n in Counter(d.get("title") for d in top).items() if n > 1}
    brand_facet = {}
    for fc in grid.get("facet_counts", {}).get("facets", []):
        if fc.get("name") == "brand":
            for v in fc.get("value", []):
                b = str(v.get("name") or "").strip()
                brand_facet[b] = brand_facet.get(b, 0) + (num(v.get("count")) or 0)
    missing = sorted(([b, int(c)] for b, c in brand_facet.items() if b and c >= 10 and b not in brand_top),
                     key=lambda x: -x[1])[:10]

    perf = {}
    for p in a.products:
        with open(p, encoding="utf-8") as f:
            for r in unwrap(check(json.load(f), p)).get("rows", []):
                perf[str(r.get("prod_id"))] = r

    matched = []
    for pid, rank in pos.items():
        r = perf.get(pid)
        if not r:
            continue
        visits = num(r.get("visits")) or 0
        matched.append({"rank": rank, "pid": pid, "title": r.get("product_title"),
                        "brand": str(r.get("brand") or "").strip() or None,
                        "visits": visits, "revenue": num(r.get("revenue")),
                        "rpv": num(r.get("rpv")), "conversion_rate": num(r.get("conversion_rate"))})
    matched.sort(key=lambda x: x["rank"])
    in_top = [m for m in matched if m["rank"] <= a.top]
    rpvs = [m["rpv"] for m in in_top if m["rpv"] is not None]
    cvrs = [m["conversion_rate"] for m in in_top if m["conversion_rate"] is not None]
    med_rpv = statistics.median(rpvs) if rpvs else None
    med_cvr = statistics.median(cvrs) if cvrs else None

    buried = [m for m in matched if m["rank"] > a.fold and m["visits"] >= 50
              and ((med_rpv is not None and m["rpv"] is not None and m["rpv"] >= med_rpv)
                   or (med_cvr is not None and m["conversion_rate"] is not None and m["conversion_rate"] >= med_cvr))]
    weak_top = [m for m in in_top if m["visits"] >= 50 and med_cvr and (m["conversion_rate"] or 0) < 0.75 * med_cvr]

    json.dump({
        "num_found": num_found, "ranked_rows_checked": len(docs), "products_with_metrics": len(matched),
        "top_window": {"size": a.top, "brands": brand_top.most_common(), "repeated_titles": repeated,
                       "median_rpv": med_rpv, "median_conversion_rate": med_cvr},
        "brands_missing_from_top": missing,
        "buried": buried[:20],
        "weak_top": weak_top,
        "note": "Products without metrics are either new, low-traffic or outside the product report pages you passed."
                + ("" if med_rpv is not None or med_cvr is not None else
                   " No top-window product had a revenue per visit or conversion rate, so buried products weren't judged."),
    }, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
