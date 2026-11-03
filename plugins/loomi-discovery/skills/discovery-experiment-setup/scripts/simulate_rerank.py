#!/usr/bin/env python3
"""Approximate the effect of a brand boost and a duplicate bury on a product grid.

Discovery can't preview a ranking rule before it exists. This script gives a
rough, offline preview from the baseline grid you already fetched with
search_discovery_product_grid_insights. It:

1. moves products from the boosted brands up, keeping their relative order;
2. moves repeated titles (every copy after the first) to the bottom;
3. prints the new top N, the brand mix before and after, and the product IDs
   to bury, ready for create_ranking_rule's bury_product_ids.

This is the STRONGEST possible version of the rule (a hard sort). A real
attribute boost blends with relevance according to its strength (0-100), so the
real effect is milder. Say so when you show the result.

Standard library only. No network access.

Usage:
    python3 scripts/simulate_rerank.py GRID.json --boost-brand "Tommy Hilfiger" \
        --boost-brand Pacific --bury-duplicates [--top 24]

GRID.json is either the saved grid response or a JSON list of
{"pid", "title", "brand"} objects in ranked order. Banner rows (docType
"content", no pid) are left out: they aren't products and rules don't move them.
"""
import argparse
import collections
import json
import re
import sys


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    return doc


def is_product(d):
    """Grids also hold banner rows (docType "content", no pid, a slots list); they aren't products."""
    return d.get("docType") != "content" and d.get("pid") not in (None, "")


def load_docs(path):
    """Return (product rows in ranked order, number of banner rows left out)."""
    with open(path, encoding="utf-8") as f:
        doc = check(json.load(f), path)
    if not isinstance(doc, list):
        if "result" in doc and "data" not in doc:
            doc = doc["result"]
        try:
            doc = doc["data"]["response"]["docs"]
        except (KeyError, TypeError):
            sys.exit("Couldn't find data.response.docs in the file")
    products = [d for d in doc if is_product(d)]
    return products, len(doc) - len(products)


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def brand_mix(docs, n):
    c = collections.Counter((d.get("brand") or "?").strip() for d in docs[:n])
    return ", ".join(f"{b} {k}" for b, k in c.most_common())


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grid")
    ap.add_argument("--boost-brand", action="append", default=[], help="brand to boost (repeatable, exact facet value)")
    ap.add_argument("--bury-duplicates", action="store_true", help="bury every repeat of a title after the first")
    ap.add_argument("--top", type=int, default=24)
    args = ap.parse_args()

    docs, banners = load_docs(args.grid)
    boost = {norm(b) for b in args.boost_brand}
    seen, dup_pids = set(), []
    keyed = []
    for rank, d in enumerate(docs, 1):
        t = norm(d.get("title"))
        is_dup = args.bury_duplicates and t in seen
        seen.add(t)
        if is_dup:
            dup_pids.append(str(d.get("pid")))
        tier = 2 if is_dup else (0 if norm(d.get("brand")) in boost else 1)
        keyed.append((tier, rank, d))
    new = [d for _, _, d in sorted(keyed, key=lambda x: (x[0], x[1]))]
    old_rank = {str(d.get("pid")): i for i, d in enumerate(docs, 1)}

    n = args.top
    print(f"Results: {len(docs)} products. Showing the top {n}.\n")
    if banners:
        print(f"Left out {banners} banner row(s): they aren't products, and the rule doesn't move them.\n")
    print(f"Brand mix before: {brand_mix(docs, n)}")
    print(f"Brand mix after:  {brand_mix(new, n)}\n")
    if boost:
        for b in args.boost_brand:
            ranks = [i for i, d in enumerate(docs, 1) if norm(d.get("brand")) == norm(b)]
            if not ranks:
                print(f"WARNING: no products with brand {b!r} in these results. Check the exact facet value.")
            else:
                print(f"{b}: {len(ranks)} products; best baseline position {ranks[0]}; "
                      f"{sum(1 for r in ranks if r <= n)} in the baseline top {n}.")
        print()
    print("| New | Was | Brand | Title |")
    print("|---|---|---|---|")
    for i, d in enumerate(new[:n], 1):
        print(f"| {i} | {old_rank[str(d.get('pid'))]} | {(d.get('brand') or '').strip()} | {d.get('title')} |")
    if args.bury_duplicates:
        print(f"\nDuplicate listings to bury ({len(dup_pids)} product IDs):")
        print(json.dumps(dup_pids))


if __name__ == "__main__":
    main()
