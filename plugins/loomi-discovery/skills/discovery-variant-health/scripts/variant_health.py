#!/usr/bin/env python3
"""Check variant (SKU) and stock health for the Discovery products that matter.

Usage:
  python3 variant_health.py --grid "dress=grid_dress.json" [--grid "category:21200=grid_cat.json" ...]
         [--products perf.json ...] [--catalog products.json ...] [--variants "101280=variants_101280.json" ...]
         [--queries queries.json] [--out report.json]

  --grid       LABEL=FILE: a saved search_discovery_product_grid_insights result for one query or category,
               fetched with rows = page_size (references/rules.json). LABEL is the query, or category:<id>.
  --products   a saved get_discovery_product_performance_table result (sort by revenue). Its top
               top_sellers rows are checked even when they aren't on a saved page one.
  --catalog    a saved search_discovery_catalog_products result (one product by product_id, or a list page):
               product-level stock, prices and thumbnail.
  --variants   PID=FILE: a saved search_discovery_catalog_product_variants result for one product: per-variant
               stock, colour, prices and images. Without it, the grid's inline variants are used (no stock).
  --queries    a saved get_discovery_query_performance result, to show each query's revenue next to a finding.

The products checked are those on a saved page one, plus the top sellers. For each it reports, with priority
high / medium / low: out of stock on page one or as a top seller, zero or missing prices, sale price above
price, a product price outside its variants' prices, duplicate SKUs, variants without a swatch or thumbnail,
broken or placeholder image URLs (static checks only), and a colour with a single variant. In-grid banner rows
(docType "content", no pid) are skipped. Never outputs margin, cost or other catalog attributes.

Rules and word lists: references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = ("high", "medium", "low")
ACCOUNT_LIST = ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")


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
    if s.lower() in MISSING:
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


def tool_error(err):
    """A Loomi Connect error, safe to show: never a list of account names."""
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):  # these errors can list every account the user can access
        return ACCOUNT_LIST
    return text[:200]


def load(path):
    """Read a saved tool result and return its data, unwrapping {"result": ...} layers."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    while isinstance(data, dict):
        if data.get("success") is False:
            fail(f"{path}: {tool_error(data.get('error'))} This check couldn't run; don't treat it as 'nothing found'.")
        if "result" in data and isinstance(data["result"], (dict, list)):
            data = data["result"]
        elif "data" in data and isinstance(data["data"], (dict, list)):
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


def rows_of(data, path, key="rows"):
    rows = data.get(key) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        fail(f"{path}: no {key} list found; is this the right tool result?")
    return rows


# ---------------------------------------------------------------------------------------------
# Field helpers

def first(attrs, fields):
    """The first of fields present (not None) in attrs, as (field, value)."""
    for f in fields:
        if f in attrs and attrs[f] is not None:
            return f, attrs[f]
    return None, None


def stock_state(attrs):
    """'in', 'out', 'unknown', or None when the record has no stock field."""
    field, value = first(attrs, RULES["stock_fields"])
    if field is None:
        return None
    if isinstance(value, bool):
        return "in" if value else "out"
    text = str(value).strip().lower()
    if text in RULES["unknown_stock_values"]:
        return "unknown"
    if text in RULES["out_of_stock_values"]:
        return "out"
    n = number(value)
    if n is not None and isinstance(value, (int, float)):
        return "out" if n <= 0 else "in"
    return "in"


def images(value):
    """A field value as a list of image URL strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def image_problem(url):
    """Why an image URL looks broken, or None."""
    low = url.lower()
    if low.startswith("http://"):
        return "uses http://, which browsers block on an https page"
    if not low.startswith("https://") and not low.startswith("//"):
        return "has no https:// scheme"
    try:
        p = urlsplit(url if not low.startswith("//") else "https:" + url)
        host = (p.hostname or "").lower()
    except ValueError:
        return "isn't a valid URL"
    if not host:
        return "has no host"
    if any(host == h or host.endswith("." + h) for h in RULES["placeholder_hosts"]):
        return "points at a placeholder host"
    words = set(re.split(r"[^a-z0-9]+", (p.path + " " + p.query).lower()))
    hit = sorted(words & set(RULES["placeholder_words"]))
    if hit:
        return "looks like a placeholder (" + ", ".join(hit) + ")"
    return None


# ---------------------------------------------------------------------------------------------
# Inputs

def read_grids(pairs):
    """{pid: [{"where": label, "position": n}]}, plus {pid: {"title", "price", "sale_price", "thumb", "variants"}}."""
    positions, grid_products = {}, {}
    for label, path in pairs:
        data = load(path)
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
            fail(f"{path}: no response.docs found; save the search_discovery_product_grid_insights result.")
        rank = 0
        for d in response["docs"]:
            if not isinstance(d, dict) or d.get("docType") == "content" or d.get("pid") in (None, ""):
                continue
            rank += 1
            pid = str(d["pid"])
            positions.setdefault(pid, []).append({"where": label, "position": rank})
            g = grid_products.setdefault(pid, {"title": d.get("title"), "price": d.get("price"),
                                               "sale_price": d.get("sale_price"), "thumb": d.get("thumb_image"),
                                               "variants": []})
            if not g["variants"] and isinstance(d.get("variants"), list):
                g["variants"] = [dict(v, _id=str(v.get("skuid") or i)) for i, v in enumerate(d["variants"])
                                 if isinstance(v, dict)]
    return positions, grid_products


def read_performance(paths):
    perf = {}
    for path in paths:
        for r in rows_of(load(path), path):
            if not isinstance(r, dict):
                continue
            pid = str(r.get("prod_id") or r.get("pid") or "")
            if pid and pid not in perf:
                perf[pid] = {"title": r.get("product_title") or r.get("title"), "revenue": number(r.get("revenue"))}
    return perf


def read_catalog(paths):
    catalog = {}
    for path in paths:
        data = load(path)
        records = data if isinstance(data, list) else [data]
        for r in records:
            if not isinstance(r, dict) or "attributes" not in r:
                fail(f"{path}: expected catalog product records with an attributes object.")
            pid = str(r.get("id") or (r.get("attributes") or {}).get("pid") or "")
            if pid:
                catalog[pid] = {"attributes": r.get("attributes") or {}, "variant_count": r.get("variant_record_count")}
    return catalog


def read_variants(pairs):
    variants = {}
    for pid, path in pairs:
        data = load(path)
        records = data if isinstance(data, list) else [data]
        out = []
        for i, r in enumerate(records):
            if not isinstance(r, dict):
                fail(f"{path}: variant record {i} isn't an object.")
            attrs = dict(r.get("attributes") or {})
            attrs["_id"] = str(r.get("id") or attrs.get("skuid") or i)
            out.append(attrs)
        variants[str(pid)] = out
    return variants


def read_queries(path):
    if not path:
        return {}
    out = {}
    for r in rows_of(load(path), path):
        if isinstance(r, dict) and r.get("query") is not None:
            out[str(r["query"]).strip().lower()] = number(r.get("revenue"))
    return out


# ---------------------------------------------------------------------------------------------
# Checks

def check_product(pid, info, add):
    """Run every check on one product. info has page_one, where, title, revenue, catalog, variants, source."""
    attrs = (info["catalog"] or {}).get("attributes") or {}
    grid = info["grid"] or {}
    variants = info["variants"]
    on_page = info["page_one"]
    sev = "medium" if on_page else "low"

    # Stock
    states = [stock_state(v) for v in variants] if info["source"] == "catalog" else []
    known = [s for s in states if s is not None]
    product_state = stock_state(attrs) if attrs else None
    stock_checked = bool(known) or product_state is not None
    all_out = (known and all(s == "out" for s in known)) or product_state == "out"
    if all_out:
        add("high" if on_page else "medium", "out_of_stock",
            ("Out of stock but on page one" if on_page else "Out of stock but a top seller") +
            (" (every variant)" if known and all(s == "out" for s in known) else " (product record)"),
            "Bury it on the pages where it ranks, or fix the stock feed if it's wrong.",
            "discovery-change-qa (check a bury rule), data-feed-health (stock feed)")

    # Prices
    price = number(attrs.get("price") if attrs.get("price") is not None else grid.get("price"))
    sale = number(attrs.get("sale_price") if attrs.get("sale_price") is not None else grid.get("sale_price"))
    if price is None or price <= 0:
        add("high" if on_page else "medium", "price_missing",
            "Product price is missing or zero" if price is None else f"Product price is {price:g}",
            "Fix the price in the product feed.", "data-feed-health")
    elif sale is not None and sale > price:
        add(sev, "sale_above_price", f"Sale price {sale:g} is above the price {price:g}",
            "Fix sale_price in the feed (or swap the two fields).", "data-feed-health")
    vprices = []
    zero_variants = []
    for v in variants:
        vp = number(v.get("price") if v.get("price") is not None else v.get("sku_price"))
        vs = number(v.get("sale_price") if v.get("sale_price") is not None else v.get("sku_sale_price"))
        if vp is None and vs is None:
            continue
        if (vp is not None and vp <= 0) or (vs is not None and vs <= 0):
            zero_variants.append(v["_id"])
        if vp is not None and vs is not None and vs > vp:
            add(sev, "sale_above_price", f"Variant {v['_id']} sale price {vs:g} is above its price {vp:g}",
                "Fix the variant's sale price in the feed.", "data-feed-health")
        vprices += [x for x in (vp, vs) if x is not None and x > 0]
    if zero_variants:
        add("high" if on_page else "medium", "price_missing",
            f"{len(zero_variants)} variant(s) with a zero price: {', '.join(zero_variants[:5])}",
            "Fix the variant prices in the feed.", "data-feed-health")
    if price and vprices and not (min(vprices) - 0.005 <= price <= max(vprices) + 0.005):
        add(sev, "price_outside_variants",
            f"Product price {price:g} is outside its variants' prices ({min(vprices):g}-{max(vprices):g})",
            "Align the product price with its variants, so the grid shows the price shoppers pay.", "data-feed-health")

    # SKUs
    ids = [str(v.get("skuid") or v["_id"]) for v in variants]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        add(sev, "duplicate_sku", f"Duplicate SKU IDs in this product: {', '.join(dup[:5])}",
            "Give each variant its own SKU ID in the feed.", "data-feed-health")

    # Images
    no_swatch = [v["_id"] for v in variants if not any(images(v.get(f)) for f in RULES["swatch_fields"])]
    no_thumb = [v["_id"] for v in variants if not any(images(v.get(f)) for f in RULES["thumb_fields"])]
    if len(variants) > 1 and no_swatch:
        add(sev, "missing_swatch", f"{len(no_swatch)} of {len(variants)} variants have no swatch image",
            "Add swatch images, so shoppers can tell the variants apart.", "product-data-enhancer")
    if no_thumb:
        add(sev, "missing_thumbnail", f"{len(no_thumb)} of {len(variants)} variants have no thumbnail",
            "Add variant thumbnails to the feed.", "product-data-enhancer")
    thumb = attrs.get("thumb_image") if attrs.get("thumb_image") is not None else grid.get("thumb")
    urls = [("product thumbnail", u) for u in images(thumb)]
    if not urls and (attrs or grid):
        add("high" if on_page else "medium", "missing_thumbnail", "The product has no thumbnail image",
            "Add a thumbnail to the feed.", "product-data-enhancer")
    for v in variants:
        for f in RULES["swatch_fields"] + RULES["thumb_fields"]:
            urls += [(f"variant {v['_id']} {f}", u) for u in images(v.get(f))]
    seen = set()
    for where, u in urls:
        problem = image_problem(u)
        if problem and (where, u) not in seen:
            seen.add((where, u))
            add(sev, "bad_image_url", f"The {where} URL {problem}", "Use a working https image URL.",
                "product-data-enhancer", evidence=u[:200])

    # Colours
    by_colour = {}
    for v in variants:
        _, colour = first(v, RULES["colour_fields"])
        if colour not in (None, ""):
            by_colour.setdefault(str(colour).strip().lower(), []).append(v["_id"])
    if len(by_colour) > 1:
        full = sum(1 for ids_ in by_colour.values() if len(ids_) >= RULES["min_variants_per_colour"])
        thin = sorted(c for c, ids_ in by_colour.items() if len(ids_) == 1)
        if thin and full > len(by_colour) / 2:
            add("low", "single_variant_colour",
                f"Colour(s) with a single variant while others have a size range: {', '.join(thin[:5])}",
                "Check the feed has every size for these colours.", "data-feed-health")
    return stock_checked


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", action="append", type=pair, default=[], help="LABEL=FILE: a saved page-one grid")
    ap.add_argument("--products", action="append", default=[], help="a saved product performance table")
    ap.add_argument("--catalog", action="append", default=[], help="a saved catalog products result")
    ap.add_argument("--variants", action="append", type=pair, default=[], help="PID=FILE: a saved variants result")
    ap.add_argument("--queries", help="a saved query performance table")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if not a.grid and not a.products:
        fail("Give at least one --grid or --products file.")

    positions, grid_products = read_grids(a.grid)
    perf = read_performance(a.products)
    catalog = read_catalog(a.catalog)
    variants = read_variants(a.variants)
    query_revenue = read_queries(a.queries)

    ranked = sorted((p for p in perf if perf[p]["revenue"] is not None), key=lambda p: -perf[p]["revenue"])
    top = set(ranked[:RULES["top_sellers"]])
    page_size = RULES["page_size"]
    on_page = {p for p, ws in positions.items() if any(w["position"] <= page_size for w in ws)}
    targets = sorted(on_page | top)

    findings, not_checked, stock_checked_any = [], [], False
    stock_unchecked = []
    for pid in targets:
        where = [dict(w, query_revenue=query_revenue.get(w["where"].strip().lower()))
                 for w in positions.get(pid, []) if w["position"] <= page_size]
        info = {"page_one": bool(where), "where": where, "grid": grid_products.get(pid), "catalog": catalog.get(pid),
                "variants": variants.get(pid) or (grid_products.get(pid) or {}).get("variants") or [],
                "source": "catalog" if pid in variants else "grid"}
        title = ((info["catalog"] or {}).get("attributes") or {}).get("title") or (info["grid"] or {}).get("title") \
            or (perf.get(pid) or {}).get("title")
        revenue = (perf.get(pid) or {}).get("revenue")
        cnt = (info["catalog"] or {}).get("variant_count")
        if pid in variants and isinstance(cnt, int) and cnt > len(variants[pid]):
            not_checked.append(f"{pid}: {len(variants[pid])} of {cnt} variants fetched; fetch the next page.")

        def add(priority, check, issue, fix, handoff, evidence=None):
            findings.append({"priority": priority, "check": check, "pid": pid, "title": title,
                             "page_one": info["where"], "top_seller": pid in top,
                             "revenue": None if revenue is None else round(revenue, 2),
                             "issue": issue, "fix": fix, "handoff": handoff,
                             **({"evidence": evidence} if evidence else {})})
        if check_product(pid, info, add):
            stock_checked_any = True
        else:
            stock_unchecked.append(pid)

    sku_owner = {}
    for pid, vs in variants.items():
        for v in vs:
            sku_owner.setdefault(str(v.get("skuid") or v["_id"]), set()).add(pid)
    for sku, owners in sorted(sku_owner.items()):
        if len(owners) > 1:
            findings.append({"priority": "medium", "check": "duplicate_sku", "pid": ", ".join(sorted(owners)),
                             "title": None, "page_one": [], "top_seller": False, "revenue": None,
                             "issue": f"SKU {sku} belongs to more than one product",
                             "fix": "Give each variant a unique SKU ID across the catalog.", "handoff": "data-feed-health"})

    if not stock_checked_any:
        not_checked.append("Stock: no stock field (" + ", ".join(RULES["stock_fields"]) + ") on any catalog or "
                           "variant record given. Save search_discovery_catalog_products and variants results.")
    elif stock_unchecked:
        not_checked.append(f"Stock not checked for {len(stock_unchecked)} product(s) with no catalog or variant "
                           f"record: {', '.join(stock_unchecked[:10])}.")
    if not a.variants:
        not_checked.append("Per-variant stock and colours: no --variants files; the grid's inline variants carry "
                           "prices and images only.")

    findings.sort(key=lambda f: (PRIORITY.index(f["priority"]), -(f["revenue"] or 0), str(f["pid"]), f["check"]))
    counts = {p: sum(1 for f in findings if f["priority"] == p) for p in PRIORITY}
    by_check = {}
    for f in findings:
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
    stake = {p: round(sum(r for r in {f["pid"]: f["revenue"] or 0 for f in findings if f["priority"] == p}.values()), 2)
             for p in PRIORITY}
    cap = RULES["max_findings_listed"]
    out = {"ok": True, "products_checked": len(targets), "on_page_one": len(on_page), "top_sellers": len(top),
           "counts": counts, "by_check": by_check, "revenue_at_stake": stake,
           "findings": findings[:cap], "findings_not_listed": max(0, len(findings) - cap), "not_checked": not_checked}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"Can't write {a.out}: {e.strerror or e}")
    print(text)


if __name__ == "__main__":
    main()
