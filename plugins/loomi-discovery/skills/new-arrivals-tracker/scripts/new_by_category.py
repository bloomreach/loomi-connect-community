#!/usr/bin/env python3
"""Where new arrivals sit in the category tree, from two saved product grid responses.

Usage:
  python3 new_by_category.py --all all.json --new new.json [--min-products 10] [--markdown]

all.json: search_discovery_product_grid_insights with query "*", rows=1, fl="pid", facets ON
          (no fq). Its "category" facet counts every product per category.
new.json: the same call with the release filter, for example fq='days_since_release:[0 TO 30]'
          or fq='released_since:"New this week" OR released_since:"1-4 weeks"'. Its "category"
          facet counts new arrivals per category (facets on a field you did not filter are
          filtered, so these are new-only counts).

Prints, per category (by its tree path): products, new arrivals, the new share, and an index
against the catalog-wide new share (1.0 = the same mix as the catalog). Flags:
  no_new        a category with at least --min-products products and no new arrivals
  low_new       index at or below 0.5 (new arrivals under-represented)
  high_new      index at or above 1.5 (a category that is mostly new: check it is in navigation)
Dynamic categories (IDs starting brg_dyn_) are listed separately.
Standard library only; no network access.
"""
import argparse
import json
import sys

MARKDOWN = False  # set from --markdown: errors print as text to stderr


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


def load(path):
    with open(path, encoding="utf-8") as f:
        grid = unwrap(check(json.load(f), path))
    cats = {}
    for fc in (grid.get("facet_counts") or {}).get("facets", []) or []:
        if fc.get("name") == "category":
            for v in fc.get("value", []):
                cid = str(v.get("cat_id"))
                path = ",".join(p.split(",", 1)[-1] for p in str(v.get("tree_path", "")).split("/") if p)
                cats[cid] = {"name": (v.get("cat_name") or "").strip(),
                             "path": "/" + path.replace(",", "/") if path else v.get("crumb"),
                             "count": v.get("count", 0)}
    return grid.get("response", {}).get("numFound") or 0, cats


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--min-products", type=int, default=10)
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    global MARKDOWN
    MARKDOWN = a.markdown

    total, all_c = load(a.all)
    total_new, new_c = load(a.new)
    if not all_c:
        sys.exit("No category facet in --all. Run the grid with facets on.")
    base = total_new / total if total else 0
    rows = []
    for cid, c in all_c.items():
        n = (new_c.get(cid) or {}).get("count", 0)
        share = n / c["count"] if c["count"] else 0
        idx = share / base if base else None
        flags = []
        if n == 0 and c["count"] >= a.min_products:
            flags.append("no_new")
        elif idx is not None and idx <= 0.5 and c["count"] >= a.min_products:
            flags.append("low_new")
        elif idx is not None and idx >= 1.5 and c["count"] >= a.min_products:
            flags.append("high_new")
        rows.append({"category_id": cid, "path": c["path"], "dynamic": cid.startswith("brg_dyn_"),
                     "products": c["count"], "new": n, "new_share": round(share, 4),
                     "index": round(idx, 2) if idx is not None else None, "flags": flags})
    uncategorised = None
    top_level_new = sum(r["new"] for r in rows if not r["dynamic"] and r["path"] and r["path"].count("/") == 1)
    if total_new:
        uncategorised = max(total_new - top_level_new, 0)
    rows.sort(key=lambda r: (r["dynamic"], -r["products"]))
    out = {"catalog_products": total, "new_arrivals": total_new, "catalog_new_share": round(base, 4),
           "new_without_top_level_category": uncategorised,
           "note_uncategorised": "Products can sit in more than one top-level category, so this is a lower bound; 0 can still hide a few.",
           "categories": rows}
    if a.markdown:
        print(f"Catalog: {total:,} products, {total_new:,} new ({base:.1%}). "
              f"New arrivals with no top-level category (lower bound): {uncategorised}.\n")
        print("| Category | Dynamic | Products | New | New share | Index | Flags |")
        print("|---|---|---|---|---|---|---|")
        for r in rows:
            print(f"| {r['path']} | {'yes' if r['dynamic'] else ''} | {r['products']:,} | {r['new']:,} | "
                  f"{r['new_share']:.0%} | {r['index']} | {', '.join(r['flags'])} |")
    else:
        json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
