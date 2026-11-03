#!/usr/bin/env python3
"""Find where products rank in a saved Discovery product grid response.

Usage:
  python3 grid_positions.py grid.json [--pids 123,456] [--brand "Brand"] [--top 24]

grid.json is the raw JSON from search_discovery_product_grid_insights (any search_by mode),
ideally with fl=pid,title,brand,price and rows up to about 200.

Prints JSON with:
  - num_found and how many ranked rows the file holds;
  - positions: the 1-based rank of each --pids product (null if not in the rows fetched);
  - brand: for each --brand, its product count in the brand facet, how many of its products
    are in the first --top positions, and its best and median positions;
  - top_brands: the brand mix of the first --top positions;
  - ranking_rules: rule IDs applied (customizations_priority.value.ranking);
  - ab_test_buckets: non-empty when an A/B test is running for this request.
Standard library only; no network access.
"""
import argparse
import json
import statistics
import sys
from collections import Counter


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


def experiments(grid):
    dbg = grid.get("debug", {}) or {}
    exps = dbg.get("experiments") or (dbg.get("request") or {}).get("experiments") or []
    return {e.get("name"): e.get("value") for e in exps if isinstance(e, dict)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grid")
    ap.add_argument("--pids", default="")
    ap.add_argument("--brand", action="append", default=[])
    ap.add_argument("--top", type=int, default=24)
    a = ap.parse_args()

    with open(a.grid, encoding="utf-8") as f:
        grid = unwrap(check(json.load(f), a.grid))
    docs = grid.get("response", {}).get("docs", [])
    pos = {}
    for i, d in enumerate(docs):
        pos.setdefault(str(d.get("pid")), i + 1)
    by_pid = {str(d.get("pid")): d for d in docs}

    facet = {}
    for fc in (grid.get("facet_counts") or {}).get("facets", []) or []:
        if fc.get("name") == "brand":
            facet = {str(v.get("name")).strip(): v.get("count") for v in fc.get("value", [])}

    brands = {}
    for b in a.brand:
        ranks = [i + 1 for i, d in enumerate(docs) if str(d.get("brand") or "").strip().lower() == b.strip().lower()]
        brands[b] = {
            "in_facet": next((c for n, c in facet.items() if n.lower() == b.strip().lower()), None),
            "in_rows_fetched": len(ranks), "in_top": sum(1 for r in ranks if r <= a.top),
            "best_position": min(ranks) if ranks else None,
            "median_position": statistics.median(ranks) if ranks else None,
        }

    exps = experiments(grid)
    pids = [p.strip() for p in a.pids.split(",") if p.strip()]
    json.dump({
        "num_found": grid.get("response", {}).get("numFound"),
        "rows_fetched": len(docs),
        "positions": {p: {"position": pos.get(p), "title": (by_pid.get(p) or {}).get("title")} for p in pids},
        "brand": brands,
        "top_brands": Counter(str(d.get("brand") or "(none)").strip() for d in docs[: a.top]).most_common(),
        "ranking_rules": ((exps.get("customizations_priority") or {}).get("ranking")),
        "ab_test_buckets": exps.get("ab_test_buckets"),
        "note": "A null position means the product is below the rows fetched, or not returned for this query.",
    }, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
