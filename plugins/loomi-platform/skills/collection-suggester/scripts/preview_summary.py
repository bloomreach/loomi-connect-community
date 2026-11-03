#!/usr/bin/env python3
"""Summarise saved Loomi Connect `search_discovery_product_grid_insights` responses
as collection previews or query profiles.

Usage:
  python3 preview_summary.py [--thin 12] [--broad 500] [--dominant 0.3] [--out profiles.jsonl] grid1.json [grid2.json ...]

Each input is a product grid response saved by the client (the full tool envelope or
just its `data` object). For each file, prints one JSON line (and, with --out, also writes
the lines to that file, ready for group_themes.py --profiles) with:

  source        what was searched: the query or category ID, the search type and every fq
  numFound      products matching
  size_flag     "thin" (< --thin), "one_screen" (< 24), "ok", or "broad" (> --broad)
  top_titles    the first 10 titles returned
  duplicate_title_rate   share of returned rows whose title repeats an earlier row
  brands        number of brands, top brand and its share (from the brand facet,
                or from the returned rows when facets were switched off)
  dominant      facet values held by at least --dominant of the matching products,
                for example "colors=multi" or "category=/men/pants". Use these to group
                queries by what their products share.
  existing_overlap   dynamic categories (brg_dyn_*) that already hold some of these
                products, with the share of numFound. A high share means a near-duplicate.
  filtered_facets    facets named in fq. Their counts are NOT filtered (the grid treats
                them as multi-select), so they are left out of `dominant`.

Facets are only present when the call left facets on (no extra_params facet=false).
Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from urllib.parse import parse_qs, urlsplit


# Facets that describe stock or ranking state rather than what the product is.
LOW_SIGNAL = {"rating", "cluster", "product_size", "onSale", "released_since", "price", "sale_price"}


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            print(json.dumps({"ok": False, "error": f"{path}: Loomi Connect returned an error: "
                              f"{d.get('error') or d.get('message') or 'no error text'}. This check couldn't run; "
                              "don't treat it as 'nothing found'."}))
            sys.exit(1)
    if isinstance(data, dict) and isinstance(data.get("result"), dict) and "data" not in data:
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def source(debug):
    url = debug.get("feUrl") or ""
    params = parse_qs(urlsplit(url).query, keep_blank_values=True)
    fqs = [v for v in params.get("fq", []) if v]
    return {
        "query": (params.get("q") or params.get("l") or [None])[0],
        "search_type": (params.get("search_type") or [None])[0],
        "search_mode": (params.get("query.search_mode") or [None])[0],
        "fq": fqs,
    }


def fq_fields(fqs):
    fields = set()
    for fq in fqs:
        fields.update(re.findall(r"([A-Za-z_][\w.]*):", fq))
    return fields


def category_label(entry, category_map):
    crumb = entry.get("crumb") or ""
    parts = [category_map.get(p, p) for p in crumb.strip("/").split("/") if p]
    return "/" + "/".join(parts) if parts else entry.get("cat_name") or entry.get("cat_id")


def summarise(data, thin, broad, dominant_share):
    response = data.get("response") or {}
    docs = response.get("docs") or []
    found = response.get("numFound") or 0
    src = source(data.get("debug") or {})
    filtered = fq_fields(src["fq"])
    browsing = src["search_type"] == "category"
    facets = {f.get("name"): f.get("value") or [] for f in (data.get("facet_counts") or {}).get("facets") or []}
    category_map = data.get("category_map") or {}

    titles = [d.get("title") for d in docs if d.get("title")]
    seen, repeats = set(), 0
    for t in titles:
        key = t.strip().lower()
        repeats += key in seen
        seen.add(key)

    if facets.get("brand") and "brand" not in filtered:
        counts = sorted(((v.get("name", "").strip(), v.get("count", 0)) for v in facets["brand"]), key=lambda x: -x[1])
        brand_info = {"source": "facet", "count": len(counts),
                      "top": counts[0][0] if counts else None,
                      "top_share": round(counts[0][1] / found, 2) if counts and found else None}
    else:
        names = [(d.get("brand") or "").strip() for d in docs if d.get("brand")]
        top = max(set(names), key=names.count) if names else None
        brand_info = {"source": "returned rows", "count": len(set(names)), "top": top,
                      "top_share": round(names.count(top) / len(names), 2) if names else None}

    dominant, overlap = [], []
    for name, values in facets.items():
        if name in LOW_SIGNAL or name in filtered:
            continue
        for v in values:
            count = v.get("count") or 0
            if name == "category":
                cat_id = str(v.get("cat_id", ""))
                if cat_id.startswith("brg_dyn_"):
                    if found:
                        overlap.append({"id": cat_id, "name": v.get("cat_name"), "products": count,
                                        "share": round(count / found, 2)})
                    continue
                if browsing:
                    continue  # every product is in the browsed category; not a useful signal
                label = category_label(v, category_map)
            else:
                label = str(v.get("name", "")).strip()
            if found and count / found >= dominant_share:
                dominant.append({"value": f"{name}={label}", "share": round(count / found, 2)})
    dominant.sort(key=lambda d: -d["share"])
    overlap.sort(key=lambda d: -d["share"])

    if found < thin:
        size = "thin"
    elif found < 24:
        size = "one_screen"
    elif found > broad:
        size = "broad"
    else:
        size = "ok"

    return {
        "source": src,
        "numFound": found,
        "size_flag": size,
        "top_titles": titles[:10],
        "rows_returned": len(docs),
        "duplicate_title_rate": round(repeats / len(titles), 2) if titles else None,
        "brands": brand_info,
        "dominant": dominant,
        "existing_overlap": overlap,
        "filtered_facets": sorted(filtered),
        "facets_present": bool(facets),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--thin", type=int, default=12, help="fewer products than this is too thin (default 12)")
    ap.add_argument("--broad", type=int, default=500, help="more products than this is too broad (default 500)")
    ap.add_argument("--dominant", type=float, default=0.3, help="share of products for a dominant value (default 0.3)")
    ap.add_argument("--out", help="also write the JSON lines to this file (e.g. profiles.jsonl for group_themes.py)")
    a = ap.parse_args()
    lines = []
    for path in a.files:
        try:
            out = summarise(load(path), a.thin, a.broad, a.dominant)
            lines.append(json.dumps({"file": path, **out}, ensure_ascii=False))
        except (OSError, ValueError) as e:
            lines.append(json.dumps({"file": path, "error": str(e)}))
        print(lines[-1])
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
