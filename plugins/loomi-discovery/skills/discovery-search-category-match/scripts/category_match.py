#!/usr/bin/env python3
"""Compare Bloomreach Discovery search results with the category page a query names.

Two steps, each reading results the assistant has already saved from Loomi Connect:

  find     Match the busiest search queries to categories by name, department word or synonym.
           python3 category_match.py find --queries queries.json --categories categories.json
                  [--synonyms synonyms.json] [--top 50] [--min-sessions 200] [--out pairs.json]

  compare  Compare each query's search page one with its category page one, and recommend an action.
           python3 category_match.py compare --pair "dress|21200|search_dress.json|cat_21200.json" [--pair ...]
                  [--queries queries.json] [--category-perf category_perf.json] [--categories categories.json]
                  [--page-size 24] [--out compare.json]

Inputs: --queries is get_discovery_query_performance, --categories is list_categories, --synonyms is
list_synonyms_user, --category-perf is get_discovery_category_performance_table, and each --pair names
the query, the category ID, then a saved search_discovery_product_grid_insights result for the query
(search_by="query") and one for the category (search_by="category"). Thresholds are in
references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    return doc


def unwrap(doc):
    while isinstance(doc, dict) and isinstance(doc.get("result"), (dict, list)):
        doc = doc["result"]
    if isinstance(doc, dict) and "data" in doc and "response" not in doc:
        doc = doc["data"]
    return doc


def rows(path):
    doc = unwrap(load(path))
    if isinstance(doc, dict):
        doc = doc.get("rows") or doc.get("data") or []
    return [r for r in doc if isinstance(r, dict)] if isinstance(doc, list) else []


def num(v):
    """A number from 21.43, "21.43%" or "$20.62"; None when missing."""
    if v in (None, ""):
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return None


def singular(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokens(text):
    text = str(text or "").lower().replace("&", " and ").replace("'", "")
    return tuple(singular(w) for w in re.findall(r"[a-z0-9]+", text))


DEPARTMENTS = {dept: {singular(w) for w in words} | {singular(dept)} for dept, words in RULES["department_words"].items()}


def department_of(word):
    return next((d for d, words in DEPARTMENTS.items() if word in words), None)


# ----------------------------------------------------------------------------------------------
# find

def categories(path):
    out = []
    for c in rows(path):
        cpath = str(c.get("categoryPaths") or "")
        top = cpath.strip("/").split("/")[0] if cpath else ""
        out.append({"cat_id": str(c.get("categoryId") or c.get("id") or ""),
                    "grid_id": str(c.get("originalCategoryId") or c.get("categoryId") or ""),
                    "path": cpath, "name": c.get("displayName") or "",
                    "leaf": tokens(c.get("displayName")), "dept": department_of(singular(top.lower().strip()))})
    return out


def synonym_terms(path):
    """query term -> other terms it's expanded to (one-way: source to targets; group: all ways)."""
    expand = {}
    for s in rows(path) if path else []:
        if s.get("enabled") is False:
            continue
        src = str(s.get("sourceSynonym") or "").strip()
        targets = [t.strip() for t in str(s.get("targetSynonym") or "").split(",") if t.strip()]
        for t in targets:
            expand.setdefault(" ".join(tokens(src)), {})[t] = tokens(t)
        if s.get("groupSynonym"):
            group = [src] + targets
            for a in group:
                expand.setdefault(" ".join(tokens(a)), {}).update({b: tokens(b) for b in group if b != a})
    return expand


def match(query, cats, expand):
    q = tokens(query)
    found = []
    for c in cats:
        if not c["leaf"]:
            continue
        if q == c["leaf"]:
            found.append(dict(c, via="name"))
        elif len(q) > 1 and q[1:] == c["leaf"] and department_of(q[0]) and department_of(q[0]) == c["dept"]:
            found.append(dict(c, via="department"))
        elif len(q) > 1 and q[:-1] == c["leaf"] and department_of(q[-1]) and department_of(q[-1]) == c["dept"]:
            found.append(dict(c, via="department"))
        else:
            for term, term_tokens in expand.get(" ".join(q), {}).items():
                if term_tokens == c["leaf"]:
                    found.append(dict(c, via=f"synonym '{term}'"))
                    break
    if any(f["via"] == "department" for f in found):  # "mens pants" names its department: keep only those
        found = [f for f in found if f["via"] == "department"]
    return [{k: f[k] for k in ("cat_id", "grid_id", "path", "name", "via")} for f in found]


def cmd_find(a):
    qrows = []
    for p in a.queries:
        qrows += rows(p)
    qrows.sort(key=lambda r: -(num(r.get("browse_sessions")) or num(r.get("visits")) or 0))
    cats = categories(a.categories)
    expand = synonym_terms(a.synonyms)
    pairs, low = [], 0
    for r in qrows[:a.top]:
        sessions = num(r.get("browse_sessions")) or num(r.get("visits")) or 0
        if sessions < a.min_sessions:
            low += 1
            continue
        m = match(r.get("query"), cats, expand)
        if m:
            pairs.append({"query": r.get("query"), "sessions": int(sessions),
                          "status": "single" if len(m) == 1 else "ambiguous", "categories": m})
    return {"ok": True, "checked": min(len(qrows), a.top), "skipped_low_traffic": low, "matched": len(pairs),
            "ambiguous": sum(p["status"] == "ambiguous" for p in pairs), "pairs": pairs}


# ----------------------------------------------------------------------------------------------
# compare

def grid(path):
    doc = load(path)
    while isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    data = doc.get("data", doc) if isinstance(doc, dict) else {"response": {"docs": doc}}
    if isinstance(data, list):
        data = {"response": {"docs": data, "numFound": len(data)}}
    resp = data.get("response") or {}
    docs = [d for d in resp.get("docs") or [] if isinstance(d, dict)
            and d.get("docType") != "content" and d.get("pid") not in (None, "")]
    return {"docs": docs, "found": resp.get("numFound", len(docs)),
            "redirect": data.get("keywordRedirect") or None}


def price(d):
    for k in ("sale_price", "price"):
        v = num(d.get(k)[0] if isinstance(d.get(k), list) and d.get(k) else d.get(k))
        if v and v > 0:
            return v
    return None


def stock(d):
    for k in RULES["stock_fields"]:
        if k in d:
            v = d[k]
            if isinstance(v, list):
                v = v[0] if v else None
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return v > 0
            s = str(v).strip().lower()
            if s in ("true", "yes", "in stock", "instock", "in_stock", "available", "1"):
                return True
            if s in ("false", "no", "out of stock", "outofstock", "out_of_stock", "unavailable", "sold out", "0"):
                return False
            n = num(s)
            return None if n is None else n > 0
    return None


def brand_mix(docs):
    counts = {}
    for d in docs:
        b = str(d.get("brand") or "?").strip() or "?"
        counts[b] = counts.get(b, 0) + 1
    total = sum(counts.values()) or 1
    return {b: c / total for b, c in counts.items()}


def page_stats(g, n):
    page = g["docs"][:n]
    prices = [p for p in (price(d) for d in page) if p]
    stocks = [s for s in (stock(d) for d in page) if s is not None]
    mix = brand_mix(page)
    top = max(mix.items(), key=lambda kv: kv[1]) if mix else (None, 0)
    return {"found": g["found"], "page": len(page), "median_price": round(statistics.median(prices), 2) if prices else None,
            "in_stock_share": round(sum(stocks) / len(stocks), 2) if stocks else None,
            "top_brand": top[0], "top_brand_share": round(top[1], 2), "_mix": mix, "_ids": [str(d["pid"]) for d in page]}


def perf(row):
    if not row:
        return None
    return {"sessions": int(num(row.get("browse_sessions")) or 0), "conversion_rate": num(row.get("conversion_rate")),
            "rpv": num(row.get("rpv")), "revenue": num(row.get("revenue"))}


def compare_perf(q, c):
    """'category' if the category converts better by perf_gap, 'search' if search does, 'even', or None."""
    if not q or not c:
        return None
    for k in ("conversion_rate", "rpv"):
        if q.get(k) is not None and c.get(k) is not None and (q[k] or c[k]):
            gap = RULES["perf_gap"]
            if c[k] >= q[k] * (1 + gap):
                return "category"
            if q[k] >= c[k] * (1 + gap):
                return "search"
            return "even"
    return None


def cmd_compare(a):
    qperf = {" ".join(tokens(r.get("query"))): r for p in a.queries for r in rows(p)}
    cperf = {str(r.get("cat_id") or "").lower(): r for p in a.category_perf for r in rows(p)}
    paths = {c["cat_id"].lower(): c["path"] for c in categories(a.categories)} if a.categories else {}
    out = []
    for spec in a.pair:
        parts = spec.split("|")
        if len(parts) != 4 or not all(p.strip() for p in parts):
            fail(f"--pair needs four parts, 'query|category id|search grid file|category grid file': {spec!r}")
        query, cat_id, sfile, cfile = (p.strip() for p in parts)
        s, c = grid(sfile), grid(cfile)
        ss, cs = page_stats(s, a.page_size), page_stats(c, a.page_size)
        shared = set(ss["_ids"]) & set(cs["_ids"])
        overlap = round(len(shared) / len(cs["_ids"]), 2) if cs["_ids"] else None
        both = ss["page"] and cs["page"]  # brand, price and stock only compare two non-empty pages
        brands = set(ss["_mix"]) | set(cs["_mix"])
        tvd = round(sum(abs(ss["_mix"].get(b, 0) - cs["_mix"].get(b, 0)) for b in brands) / 2, 2) if both else None
        qp, cp = perf(qperf.get(" ".join(tokens(query)))), perf(cperf.get(cat_id.lower()))
        better = compare_perf(qp, cp)
        broader = bool(cs["found"]) and ss["found"] >= RULES["broader_ratio"] * cs["found"]
        flags = []
        if tvd is not None and tvd >= RULES["brand_shift"]:
            flags.append(f"brand mix differs ({tvd:.0%}): search top brand {ss['top_brand']}, category {cs['top_brand']}")
        if both and ss["median_price"] and cs["median_price"]:
            ratio = max(ss["median_price"], cs["median_price"]) / min(ss["median_price"], cs["median_price"])
            if ratio >= RULES["price_ratio"]:
                flags.append(f"median price differs {ratio:.1f}x (search {ss['median_price']}, category {cs['median_price']})")
        if ss["in_stock_share"] is not None and cs["in_stock_share"] is not None \
                and cs["in_stock_share"] - ss["in_stock_share"] >= RULES["stock_gap"]:
            flags.append(f"fewer in-stock products on search ({ss['in_stock_share']:.0%} vs {cs['in_stock_share']:.0%})")
        if cat_id.lower().startswith("brg_dyn_"):
            flags.append("the category is a dynamic (rule-based) category")
        not_checked = []
        if both and (ss["in_stock_share"] is None or cs["in_stock_share"] is None):
            not_checked.append("stock: no stock field in the grids (add one of rules.json stock_fields to fl)")
        if not qp:
            not_checked.append("query performance: query not found in the saved table")
        if not cp:
            not_checked.append("category performance: category not found in the saved table")

        if s["redirect"]:
            verdict, why = "already_redirected", "the search already redirects; check it with discovery-redirect-audit"
        elif not cs["found"]:
            verdict, why = "review", "the category page is empty"
        elif overlap is not None and overlap >= RULES["overlap_aligned"]:
            verdict, why = "aligned", f"{overlap:.0%} of the category's page one is on the search page one"
        elif better is None:
            verdict, why = "review", "pages differ but there's no performance data to say which works better"
        elif better == "category" and overlap < RULES["overlap_low"] and broader:
            verdict, why = "redirect", ("search is much broader, shares little with the category page, and the category "
                                        "converts better")
        elif better == "category":
            verdict, why = "align_ranking", ("the category converts better with a similar product set; rank search like "
                                             "the category")
        else:
            verdict, why = "leave", ("search is broader and converts as well or better" if broader
                                     else "search converts as well or better")
        for d in (ss, cs):
            d.pop("_mix")
            d.pop("_ids")
        out.append({"query": query, "cat_id": cat_id, "path": paths.get(cat_id.lower()), "verdict": verdict, "why": why,
                    "overlap": overlap, "brand_difference": tvd, "search_broader": broader, "better": better,
                    "search": ss, "category": cs, "performance": {"query": qp, "category": cp},
                    "flags": flags, "not_checked": not_checked})
    order = ["redirect", "align_ranking", "review", "already_redirected", "leave", "aligned"]
    out.sort(key=lambda r: (order.index(r["verdict"]), -((r["performance"]["query"] or {}).get("sessions") or 0)))
    return {"ok": True, "pairs": out, "counts": {v: sum(r["verdict"] == v for r in out) for v in order}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles and brands can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="match top queries to categories")
    f.add_argument("--queries", action="append", required=True, help="saved get_discovery_query_performance (repeat per page)")
    f.add_argument("--categories", required=True, help="saved list_categories")
    f.add_argument("--synonyms", help="saved list_synonyms_user (optional)")
    f.add_argument("--top", type=int, default=RULES["top_queries"], help="queries to check (default: rules)")
    f.add_argument("--min-sessions", type=int, default=RULES["min_sessions"], help="skip quieter queries (default: rules)")
    f.add_argument("--out", help="also write the JSON result to this file")
    c = sub.add_parser("compare", help="compare search and category page one for each pair")
    c.add_argument("--pair", action="append", required=True,
                   help="'query|category id|search grid file|category grid file' (repeat per pair)")
    c.add_argument("--queries", action="append", default=[], help="saved get_discovery_query_performance")
    c.add_argument("--category-perf", action="append", default=[], help="saved get_discovery_category_performance_table")
    c.add_argument("--categories", help="saved list_categories, for category paths")
    c.add_argument("--page-size", type=int, default=RULES["page_size"], help="products on page one (default: rules)")
    c.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    result = cmd_find(a) if a.cmd == "find" else cmd_compare(a)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
