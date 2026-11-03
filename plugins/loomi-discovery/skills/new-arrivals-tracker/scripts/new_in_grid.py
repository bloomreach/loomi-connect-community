#!/usr/bin/env python3
"""How well new arrivals are placed in a saved Discovery product grid (a query or a category page).

Usage:
  python3 new_in_grid.py grid.json --new new_p*.json [--new-values "New this week,1-4 weeks"]
                         [--facet released_since] [--top 24] [--pids 123,456]

grid.json is the raw JSON from search_discovery_product_grid_insights (search_by "query" or
"category"), with fl including pid,title,brand and rows up to about 200. Leave facets on if you
want the share of new products among ALL matches (read from the release facet).

--new takes the same new-arrival list as new_arrivals.py: saved grid pages filtered on the
release attribute, or text files with one product ID (optionally ",days") per line.

Prints JSON with:
  - num_found and rows fetched;
  - new_in_results: new products among all matches, from the release facet (--facet and
    --new-values), or null if facets were off;
  - new_in_rows_fetched and new_in_top: how many new products appear in the rows fetched and in
    the first --top positions;
  - share_of_results vs share_of_top: if new products are, say, 30% of matches but 4% of the
    first page, they are under-placed (a placement index well below 1);
  - best_new_positions: the highest-ranked new products;
  - positions of any --pids (null = below the rows fetched or not matched);
  - ranking_rules applied and ab_test_buckets (an A/B test is running if non-empty).
Standard library only; no network access.
"""
import argparse
import json
import sys


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


def load_new(paths):
    out = set()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            data = unwrap(check(json.loads(text), path))
            out |= {str(d["pid"]) for d in data.get("response", {}).get("docs", []) if d.get("pid") is not None}
        except (ValueError, AttributeError):
            out |= {line.split(",")[0].strip() for line in text.splitlines() if line.strip()}
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grid")
    ap.add_argument("--new", nargs="+", required=True)
    ap.add_argument("--facet", default="released_since")
    ap.add_argument("--new-values", default="New this week,1-4 weeks")
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--pids", default="")
    a = ap.parse_args()

    with open(a.grid, encoding="utf-8") as f:
        grid = unwrap(check(json.load(f), a.grid))
    new = load_new(a.new)
    docs = grid.get("response", {}).get("docs", []) or []
    num_found = grid.get("response", {}).get("numFound") or 0
    ranks = [(i + 1, d) for i, d in enumerate(docs) if str(d.get("pid")) in new]
    in_top = [r for r in ranks if r[0] <= a.top]

    new_in_results = None
    wanted = {v.strip().lower() for v in a.new_values.split(",") if v.strip()}
    for fc in (grid.get("facet_counts") or {}).get("facets", []) or []:
        if fc.get("name") == a.facet:
            new_in_results = sum(v.get("count", 0) for v in fc.get("value", [])
                                 if str(v.get("name", "")).strip().lower() in wanted)
    top_n = min(a.top, len(docs))
    share_results = (new_in_results / num_found) if (new_in_results is not None and num_found) else (
        len(ranks) / len(docs) if docs else None)
    share_top = len(in_top) / top_n if top_n else None

    dbg = grid.get("debug", {}) or {}
    exps = dbg.get("experiments") or (dbg.get("request") or {}).get("experiments") or []
    exps = {e.get("name"): e.get("value") for e in exps if isinstance(e, dict)}
    pos = {str(d.get("pid")): i + 1 for i, d in reversed(list(enumerate(docs)))}
    pids = [p.strip() for p in a.pids.split(",") if p.strip()]

    json.dump({
        "num_found": num_found, "rows_fetched": len(docs),
        "new_in_results": new_in_results,
        "new_in_results_source": "release facet" if new_in_results is not None else "rows fetched only (facets off)",
        "new_in_rows_fetched": len(ranks), "new_in_top": len(in_top), "top": a.top,
        "share_of_results": round(share_results, 4) if share_results is not None else None,
        "share_of_top": round(share_top, 4) if share_top is not None else None,
        "placement_index": round(share_top / share_results, 2) if share_results and share_top is not None else None,
        "best_new_positions": [{"position": r, "pid": str(d.get("pid")), "title": d.get("title"), "brand": d.get("brand")}
                               for r, d in ranks[:10]],
        "positions": {p: pos.get(p) for p in pids},
        "ranking_rules": (exps.get("customizations_priority") or {}).get("ranking"),
        "ab_test_buckets": exps.get("ab_test_buckets"),
        "note": "A null position means below the rows fetched, or not matched at all.",
    }, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
