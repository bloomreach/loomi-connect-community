#!/usr/bin/env python3
"""Build a one-product report for Bloomreach Discovery from saved Loomi Connect results.

Usage:
  python3 product_report.py --pid 110726 --performance perf.json [--table table.json ...]
         [--peer peer1.json ...] [--catalog catalog.json] [--variants variants.json ...]
         [--grid "dress=grid-dress.json" ...] [--category-grid "21200=grid-cat.json" ...]
         [--queries queries.json] [--page-size 24] [--out report.json]

Inputs (each a saved tool result):
  --performance  get_discovery_product_performance for the product (30-day totals).
  --table        get_discovery_product_performance_table pages; the product's row adds the previous
                 period, and other rows count as peers if they're in a --category-grid.
  --peer         get_discovery_product_performance for peer products (repeat).
  --catalog      search_discovery_catalog_products with product_id.
  --variants     search_discovery_catalog_product_variants pages (repeat).
  --grid         QUERY=FILE: search_discovery_product_grid_insights for a search query (repeat).
  --category-grid  CATEGORY=FILE: the same tool with search_by="category" (repeat).
  --queries      get_discovery_query_performance, to weight each query by its revenue.

Prints JSON: the product's performance against the median of its category peers, its position on
every grid given, the merchandising rules that boost, pin, bury or exclude it, its catalog and
stock state, and up to max_actions next actions (high, medium, low) with the skill to hand off to.
Thresholds are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
METRICS = ("visits", "atc_rate", "conversion_rate", "rpv", "revenue")
PRIORITY = {"high": 0, "medium": 1, "low": 2}
ACCOUNT_ERROR = ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
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
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):  # these errors can list every account the user can access
        return ACCOUNT_ERROR
    return text[:200]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: {tool_error(d.get('error'))} This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data


def name_file(text):
    """QUERY=FILE or CATEGORY=FILE, split on the first '='."""
    name, sep, path = text.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE, got {text!r}")
    return name.strip(), path.strip()


def today_arg(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}")


# ----------------------------------------------------------------------------------------------
# Performance

def perf_record(data, path):
    """Metrics from get_discovery_product_performance (atcRate, cvr in percent) as one shape."""
    if not isinstance(data, dict):
        fail(f"{path}: not a get_discovery_product_performance result.")
    pid = data.get("productId") or data.get("prod_id") or data.get("pid")
    if pid is None:
        fail(f"{path}: no productId in the performance result.")
    return str(pid), {"visits": number(data.get("visits")), "atc_rate": number(data.get("atcRate")),
                      "conversion_rate": number(data.get("cvr")), "rpv": number(data.get("rpv")),
                      "revenue": number(data.get("revenue"))}


def table_rows(paths):
    rows = {}
    for p in paths:
        data = load(p)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            fail(f"{p}: not a get_discovery_product_performance_table result (no rows).")
        for r in data["rows"]:
            if not isinstance(r, dict) or r.get("prod_id") is None:
                fail(f"{p}: a row has no prod_id.")
            rows[str(r["prod_id"])] = {
                "visits": number(r.get("visits")), "atc_rate": number(r.get("atc_rate")),
                "conversion_rate": number(r.get("conversion_rate")), "rpv": number(r.get("rpv")),
                "revenue": number(r.get("revenue")),
                "prev": {"visits": number(r.get("prev_visits")), "atc_rate": number(r.get("prev_atc_rate")),
                         "conversion_rate": number(r.get("prev_conversion_rate")), "rpv": number(r.get("prev_rpv")),
                         "revenue": number(r.get("prev_revenue"))}}
    return rows


def compare(target, peers):
    out = {}
    for m in METRICS:
        vals = [p[m] for p in peers if p.get(m) is not None]
        med = statistics.median(vals) if len(vals) >= RULES["min_peers"] else None
        mine = target.get(m)
        ratio = round(mine / med, 2) if mine is not None and med else None
        level = None
        if ratio is not None:
            level = "weak" if ratio < RULES["weak_ratio"] else "strong" if ratio > RULES["strong_ratio"] else "typical"
        out[m] = {"value": mine, "peer_median": med, "ratio": ratio, "level": level}
    return out


# ----------------------------------------------------------------------------------------------
# Grids and rules

def product_rows(data, path):
    if not isinstance(data, dict) or not isinstance((data.get("response") or {}).get("docs"), list):
        fail(f"{path}: not a search_discovery_product_grid_insights result (no response.docs).")
    rows = data["response"]["docs"]
    return [d for d in rows if isinstance(d, dict) and d.get("docType") != "content" and d.get("pid") not in (None, "")]


def product_ids(value):
    """Product IDs named in a rule item's value (a JSON string or object): product_id, pid or productId
    fields, and plain strings in lists."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return set()
    ids = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("product_id", "pid", "productId") and isinstance(v, (str, int)):
                ids.add(str(v))
            else:
                ids |= product_ids(v)
    elif isinstance(value, list):
        for v in value:
            ids |= {str(v)} if isinstance(v, (str, int)) and not isinstance(v, bool) else product_ids(v)
    return ids


def rule_effects(data, pid):
    """Rules in the grid's customizations.explain that name the product, with what they do to it."""
    found = []
    for c in ((data.get("debug") or {}).get("customizations.explain") or []):
        if not isinstance(c, dict):
            continue
        for item in c.get("customizationItems") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if pid not in product_ids(item.get("value")):
                continue
            if "bury" in kind:
                effect = "buried"
            elif "slot" in kind or "pin" in kind:
                effect = "pinned"
            elif "exclude" in kind:
                effect = "excluded"
            elif "boost" in kind:
                effect = "boosted"
            else:
                effect = kind or "named"
            found.append({"rule_id": c.get("id"), "rule_type": c.get("ruleType"), "effect": effect, "item": kind,
                          "audiences": c.get("audienceNames") or [], "in_test": bool(c.get("liveInTest"))})
    return found


def grid_entry(kind, name, path, pid, query_revenue):
    data = load(path)
    docs = product_rows(data, path)
    pids = [str(d.get("pid")) for d in docs]
    position = pids.index(pid) + 1 if pid in pids else None
    explain = ((data.get("debug") or {}).get("explain.structured") or {})
    entry = explain.get(pid) if isinstance(explain, dict) else None
    last = entry[-1] if isinstance(entry, list) and entry and isinstance(entry[-1], dict) else {}
    applied = last.get("merchandisingRulesApplied") or {}
    found = number((data.get("response") or {}).get("numFound"))
    return {"kind": kind, "name": name, "num_found": int(found) if found is not None else None,
            "rows_fetched": len(docs), "position": position,
            "on_page_one": position is not None and position <= RULES["page_size"],
            "query_revenue": query_revenue.get(name.lower()) if kind == "search" else None,
            "scores": {k: last.get(k) for k in ("totalNormalizedScore", "relevance", "performance") if k in last},
            "rules_applied": sorted(applied) if isinstance(applied, dict) else [],
            "rules": rule_effects(data, pid),
            "redirect": bool(data.get("keywordRedirect"))}


# ----------------------------------------------------------------------------------------------
# Catalog and variants

def catalog_state(path):
    data = load(path)
    attrs = (data or {}).get("attributes") if isinstance(data, dict) else None
    if not isinstance(attrs, dict):
        fail(f"{path}: not a search_discovery_catalog_products result for one product (no attributes).")
    paths = []
    for cp in attrs.get("category_paths") or []:
        if isinstance(cp, list):
            paths.append(" > ".join(str(n.get("name")) for n in cp if isinstance(n, dict)))
    low = {v.lower() for v in RULES["low_stock_values"]}
    stock = attrs.get("stock_level")
    avail = attrs.get("availability")
    return {"title": attrs.get("title"), "brand": attrs.get("brand"),
            "price": number(attrs.get("price")), "sale_price": number(attrs.get("sale_price")),
            "available": avail if isinstance(avail, bool) else (str(avail).lower() not in low if avail is not None else None),
            "stock_level": stock,
            "low_stock": (stock is not None and str(stock).lower() in low) or avail is False,
            "category_paths": paths,
            "missing_fields": [f for f in RULES["required_fields"] if attrs.get(f) in (None, "", [])],
            "variant_count": int(number(data.get("variant_record_count")) or 0) or None}


def variant_state(paths):
    variants, total = {}, None
    for p in paths:
        data = load(p)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            total, data = number(data.get("count")), data["data"]
        if not isinstance(data, list):
            fail(f"{p}: not a search_discovery_catalog_product_variants result (no list of variants).")
        for v in data:
            if isinstance(v, dict) and v.get("id") is not None:
                variants[str(v["id"])] = (v.get("attributes") or {})
    if not variants:
        return None
    in_stock = sum(1 for a in variants.values() if a.get("availability") is not False)
    return {"fetched": len(variants), "total": int(total) if total else len(variants), "in_stock": in_stock,
            "all_out_of_stock": in_stock == 0,
            "missing_images": sum(1 for a in variants.values() if not (a.get("swatch_image") or a.get("thumb_image")))}


# ----------------------------------------------------------------------------------------------
# Actions

def actions(perf, grids, catalog, variants):
    acts = []
    stocked_out = (catalog or {}).get("low_stock") or (variants or {}).get("all_out_of_stock")
    for g in grids:
        effects = {r["effect"] for r in g["rules"]}
        if stocked_out and effects & {"boosted", "pinned"}:
            acts.append(("high", f"It's low on stock or unavailable but {', '.join(sorted(effects & {'boosted', 'pinned'}))} "
                         f"on {g['kind']} '{g['name']}', so shoppers may be sent to a product that sells out.",
                         "discovery-change-qa", "Remove it from the rule, or swap in an in-stock product, and check "
                                                "the change before switching it on."))
        if "buried" in effects and (perf.get("conversion_rate") or {}).get("level") in ("typical", "strong"):
            acts.append(("high", f"A rule buries it on {g['kind']} '{g['name']}' although it converts "
                         f"{perf['conversion_rate']['level']}ly against its peers.",
                         "discovery-change-qa", "Review the bury rule; check the change before switching it on."))
    strong = any((perf.get(m) or {}).get("level") == "strong" for m in ("conversion_rate", "rpv"))
    for g in sorted((g for g in grids if g["kind"] == "search"), key=lambda g: -(g["query_revenue"] or 0)):
        if not g["on_page_one"] and not g["redirect"]:
            where = f"#{g['position']}" if g["position"] else "not in the rows fetched"
            acts.append(("high" if strong else "medium",
                         f"Off page one for '{g['name']}' ({where})" + (" although it converts well." if strong else "."),
                         "discovery-product-visibility", f"Explain its position for '{g['name']}' and get the smallest fix."))
            break
    weak = [m for m in ("atc_rate", "conversion_rate") if (perf.get(m) or {}).get("level") == "weak"]
    if weak:
        acts.append(("medium", f"{' and '.join(m.replace('_', ' ') for m in weak)} below its peers: shoppers see it "
                     "but don't buy.", "product-data-enhancer", "Improve its title, description, images and attributes."))
    if variants and not variants["all_out_of_stock"] and variants["in_stock"] < variants["fetched"]:
        acts.append(("low", f"{variants['fetched'] - variants['in_stock']} of {variants['fetched']} variants fetched are "
                     "out of stock.", "discovery-product-visibility", "Check it still ranks sensibly while sizes are missing."))
    if catalog and catalog["missing_fields"]:
        acts.append(("low", f"Catalog fields missing: {', '.join(catalog['missing_fields'])}.",
                     "product-data-enhancer", "Fill in the missing fields."))
    seen, out = set(), []
    for pr, finding, skill, fix in sorted(acts, key=lambda a: PRIORITY[a[0]]):
        if (finding, skill) not in seen:
            seen.add((finding, skill))
            out.append({"priority": pr, "finding": finding, "hand_off": skill, "fix": fix})
    return out[:RULES["max_actions"]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", required=True, help="the product ID")
    ap.add_argument("--performance", required=True, help="get_discovery_product_performance for the product")
    ap.add_argument("--table", action="append", default=[], help="get_discovery_product_performance_table page")
    ap.add_argument("--peer", action="append", default=[], help="get_discovery_product_performance for a peer")
    ap.add_argument("--catalog", help="search_discovery_catalog_products with product_id")
    ap.add_argument("--variants", action="append", default=[], help="search_discovery_catalog_product_variants page")
    ap.add_argument("--grid", action="append", default=[], type=name_file, help="QUERY=FILE search grid")
    ap.add_argument("--category-grid", action="append", default=[], type=name_file, help="CATEGORY=FILE category grid")
    ap.add_argument("--queries", help="get_discovery_query_performance result, for query revenue")
    ap.add_argument("--page-size", type=int, default=RULES["page_size"], help="products on page one (default: rules)")
    ap.add_argument("--today", type=today_arg, help="YYYY-MM-DD for the report date (default: today, UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    RULES["page_size"] = a.page_size
    pid = a.pid.strip()

    got, mine = perf_record(load(a.performance), a.performance)
    if got != pid:
        fail(f"{a.performance}: performance is for product {got}, not {pid}.")
    table = table_rows(a.table)
    peers = []
    for p in a.peer:
        ppid, rec = perf_record(load(p), p)
        if ppid != pid:
            peers.append(rec)
    query_revenue = {}
    if a.queries:
        data = load(a.queries)
        for r in (data.get("rows") if isinstance(data, dict) else None) or []:
            if isinstance(r, dict) and r.get("query"):
                query_revenue[str(r["query"]).lower()] = number(r.get("revenue"))
    grids = [grid_entry("search", n, p, pid, query_revenue) for n, p in a.grid]
    grids += [grid_entry("category", n, p, pid, query_revenue) for n, p in a.category_grid]
    category_pids = set()
    for n, p in a.category_grid:
        category_pids |= {str(d.get("pid")) for d in product_rows(load(p), p)[:a.page_size]}
    peers += [r for k, r in table.items() if k != pid and k in category_pids]
    catalog = catalog_state(a.catalog) if a.catalog else None
    variants = variant_state(a.variants) if a.variants else None
    perf = compare(mine, peers)
    trend = None
    if pid in table:
        prev = table[pid]["prev"]
        trend = {m: {"now": mine.get(m), "before": prev.get(m)} for m in METRICS}

    not_checked = []
    if len(peers) < RULES["min_peers"]:
        not_checked.append(f"Peer comparison: {len(peers)} peers with performance data (need min_peers).")
    if not grids:
        not_checked.append("Positions: no search or category grid was given.")
    if not a.catalog:
        not_checked.append("Catalog data and stock: no catalog record was given.")
    if not a.variants:
        not_checked.append("Variant stock: no variants were given.")
    if trend is None:
        not_checked.append("Trend: the product isn't in the performance table pages given.")
    rules = {}
    for g in grids:
        for r in g["rules"]:
            rules.setdefault(r["rule_id"], dict(r, where=[]))["where"].append(f"{g['kind']} '{g['name']}'")
    out = {"ok": True, "pid": pid, "date": str(a.today or datetime.now(timezone.utc).date()),
           "page_size": a.page_size, "performance": perf, "peers": len(peers), "trend": trend,
           "positions": grids, "rules": sorted(rules.values(), key=lambda r: str(r["rule_id"])),
           "catalog": catalog, "variants": variants, "actions": actions(perf, grids, catalog, variants),
           "not_checked": not_checked}
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
