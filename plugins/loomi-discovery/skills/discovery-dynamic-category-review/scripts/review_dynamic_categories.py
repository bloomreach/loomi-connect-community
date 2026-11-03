#!/usr/bin/env python3
"""Review Bloomreach Discovery dynamic categories from saved Loomi Connect responses.

Reads data the assistant has already fetched and prints a Markdown inventory and a
prioritised list of findings. It never calls the network. Standard library only.

Usage:
    python3 scripts/review_dynamic_categories.py \
        --definitions def_26344.json def_22116.json ... \
        --grids grid_brg_dyn_abc.json grid_70300.json ... \
        [--table category_table.json] [--categories list_categories.json] \
        [--today 2026-10-08] [--min-sessions 100] [--thin 24] [--overlap 0.8] [--threshold 25]

--definitions  search_dynamic_categories responses fetched BY ID (category_id=<numeric id>),
               one per file, or a JSON list of such definitions. The list view has no
               conditions, so it isn't enough on its own.
--grids        search_discovery_product_grid_insights responses with search_by="category",
               rows=1, fl="pid" and facets left on. One per dynamic category; add grids for
               static categories too when you want their sizes for duplicate checks. The
               category ID is read from the response's debug section, or from the file name
               (for example grid_brg_dyn_abc123.json, grid_70300.json or
               grid_womens-sneakers.json; a leading "grid_" is dropped).
--table        get_discovery_category_performance_table response (all pages, or one big page).
--categories   list_categories response, for static category paths and navigation checks.
"""
import argparse
import datetime as dt
import json
import math
import re
import statistics
import sys
from pathlib import Path

ID_ATTRS = {"pid", "product_id", "productid", "sku", "sku_id", "skuid", "id", "item_id", "itemid",
            "variant_id", "style_id", "item_group_id"}
SEASONAL_ATTRS = {"season", "collection", "campaign", "tag", "tags", "special_offer", "promo",
                  "promotion", "event", "label", "labels", "badge", "badges", "is_new", "released_since",
                  "theme", "occasion"}
SEASONAL_WORDS = re.compile(
    r"sale|black ?friday|cyber|halloween|christmas|xmas|holiday|summer|winter|spring|autumn|\bfall\b|"
    r"valentine|easter|mother'?s day|father'?s day|back to school|promo|campaign|launch|clearance|"
    r"new this week|limited|\b20\d\d\b|bogo|buy 1|buy one", re.I)
TEST_WORDS = re.compile(r"\btest|demo|example|sample|tmp|temp\b|do not use|copy of|xyz", re.I)
DATE_ATTR = re.compile(r"date|_at$|time|expir|start|end", re.I)
SEVERITY = {"high": 0, "medium": 1, "low": 2, "info": 3}


def unwrap(doc):
    while isinstance(doc, dict):
        if isinstance(doc.get("result"), dict):
            doc = doc["result"]
        elif "data" in doc and not isinstance(doc.get("rows"), list) and not isinstance(doc.get("response"), dict):
            doc = doc["data"]
        else:
            break
    return doc


def load(path):
    with open(path, encoding="utf-8") as f:
        return check(json.load(f), path)


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    return doc


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


def leaf_rules(cfg):
    """Flatten conditionConfig into leaf conditions; tolerate nested groups."""
    out = []
    if not isinstance(cfg, dict):
        return out
    for r in cfg.get("rules") or []:
        if isinstance(r, dict) and r.get("rules"):
            out.extend(leaf_rules(r))
        elif isinstance(r, dict):
            out.append(r)
    return out


def as_date(value, today):
    s = str(value).strip()
    if re.fullmatch(r"\d{10}(\d{3})?", s):
        ts = int(s) / (1000 if len(s) == 13 else 1)
        try:
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def grid_id(doc, path):
    data = unwrap(doc)
    dbg = (data or {}).get("debug") or {}
    intents = (dbg.get("synonym.explain") or {}).get("queryIntents") or []
    if intents:
        return str(intents[0]).lower()
    stem = Path(path).stem
    m = re.search(r"(brg_dyn_[a-z0-9]+)", stem, re.I)
    if m:
        return m[1].lower()
    # grid_70300.json -> 70300; grid_womens-sneakers.json -> womens-sneakers (IDs aren't always numeric)
    return re.sub(r"^grid_", "", stem, flags=re.I).lower()


def parse_grid(doc):
    data = unwrap(doc) or {}
    resp = data.get("response") or {}
    found = resp.get("numFound")
    cats, onsale = {}, None
    for facet in (data.get("facet_counts") or {}).get("facets") or []:
        if facet.get("name") == "category":
            for v in facet.get("value") or []:
                cid = str(v.get("cat_id") or "").lower()
                if cid:
                    cats[cid] = {"count": v.get("count") or 0, "name": v.get("cat_name"),
                                 "crumb": v.get("crumb") or "", "tree_path": v.get("tree_path") or ""}
        elif facet.get("name", "").lower() in ("onsale", "on_sale", "sale"):
            onsale = {str(v.get("name")).lower(): v.get("count") or 0 for v in facet.get("value") or []}
    return found, cats, onsale


def pretty_path(entry, static):
    if entry and entry.get("tree_path"):
        return "/" + "/".join(p.split(",", 1)[-1] for p in entry["tree_path"].strip("/").split("/"))
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--definitions", nargs="+", required=True)
    ap.add_argument("--grids", nargs="*", default=[])
    ap.add_argument("--table")
    ap.add_argument("--categories")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--min-sessions", type=int, default=100)
    ap.add_argument("--thin", type=int, default=24)
    ap.add_argument("--overlap", type=float, default=0.8)
    ap.add_argument("--threshold", type=float, default=25.0, help="percent gap from the dynamic median")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today)

    # Definitions
    defs = {}
    for p in a.definitions:
        d = unwrap(load(p))
        for item in d if isinstance(d, list) else [d]:
            if isinstance(item, dict) and item.get("categoryId"):
                defs[str(item["categoryId"]).lower()] = item

    # Grids
    grids = {}
    for p in a.grids:
        found, cats, onsale = parse_grid(load(p))
        grids[grid_id(load(p), p)] = {"found": found, "cats": cats, "onsale": onsale}

    # Static categories
    static = {}
    if a.categories:
        cl = unwrap(load(a.categories))
        for c in cl if isinstance(cl, list) else []:
            cid = str(c.get("originalCategoryId") or c.get("categoryId") or "").lower()
            if cid:
                static[cid] = c

    # Performance
    perf = {}
    if a.table:
        t = unwrap(load(a.table))
        for r in (t or {}).get("rows", []):
            cid = str(r.get("cat_id") or "").lower()
            if cid.startswith("brg_dyn_"):
                perf[cid] = r

    findings = []

    def add(sev, cid, issue, evidence, action):
        findings.append((sev, cid, issue, evidence, action))

    def name_of(cid):
        d = defs.get(cid)
        if d:
            return (d.get("categoryName") or "").strip() or cid
        r = perf.get(cid)
        return (r or {}).get("category") or cid

    # Dynamic medians for performance
    eligible = [r for r in perf.values() if (num(r.get("browse_sessions")) or 0) >= a.min_sessions]
    def med(key):
        vals = [num(r.get(key)) for r in eligible if num(r.get(key)) is not None]
        return statistics.median(vals) if vals else None
    m_conv, m_bounce, m_rpv = med("conversion_rate"), med("bounce_rate"), med("rpv")
    thr = a.threshold / 100

    rows_out = []
    seen_pairs = set()
    for cid, d in sorted(defs.items(), key=lambda kv: -(num((perf.get(kv[0]) or {}).get("browse_sessions")) or 0)):
        name = name_of(cid)
        rules = leaf_rules(d.get("conditionConfig"))
        top_op = (d.get("conditionConfig") or {}).get("operator") or "-"
        desc = f" {top_op} ".join(
            f"{r.get('attribute')} {r.get('operator')} {', '.join(map(str, (r.get('values') or [])[:5]))}"
            + (f" (+{len(r.get('values') or []) - 5} more)" if len(r.get("values") or []) > 5 else "")
            for r in rules) or "(no conditions)"
        g = grids.get(cid)
        found = g["found"] if g else None
        pr = perf.get(cid) or {}
        sessions = num(pr.get("browse_sessions")) or 0
        conv, bounce, aov = num(pr.get("conversion_rate")), num(pr.get("bounce_rate")), num(pr.get("aov"))
        rows_out.append((name, cid, desc, found, int(sessions) if pr else None, conv, bounce))
        busy = sessions >= a.min_sessions

        # Size
        if found is not None:
            if found == 0:
                add("high" if sessions else "medium", cid, "Empty",
                    f"0 products; {int(sessions)} sessions", "Correct the conditions (check the values exist in the catalog), or retire it and remove links")
            elif found < a.thin:
                add("high" if busy else "low", cid, "Near-empty",
                    f"{found} products (under one screen of {a.thin}); {int(sessions)} sessions",
                    "Widen the conditions so the page fills at least one screen with on-theme products")

        # Fragility
        id_rules = [r for r in rules if str(r.get("attribute", "")).lower() in ID_ATTRS]
        hard_ids = sum(len(r.get("values") or []) for r in id_rules) + len(d.get("productIds") or [])
        if hard_ids:
            add("medium" if busy else "low", cid, "Hard-coded product IDs",
                f"{hard_ids} product IDs listed in the definition",
                "Replace with an attribute condition (brand, collection, tag) so new and replacement products join automatically")
        if len(rules) == 1 and len(rules[0].get("values") or []) == 1 and not id_rules:
            r = rules[0]
            add("medium" if busy else "low", cid, "Single-value definition",
                f"Only condition: {r.get('attribute')} = {r.get('values')[0]}",
                "Add a fallback (OR a second attribute or value) or monitor the value in the feed; one feed change empties the page")
        seasonal = [r for r in rules if str(r.get("attribute", "")).lower() in SEASONAL_ATTRS
                    or any(SEASONAL_WORDS.search(str(v)) for v in r.get("values") or [])]
        if seasonal:
            r = seasonal[0]
            add("medium" if busy else "low", cid, "Seasonal or campaign tag",
                f"{r.get('attribute')} {r.get('operator')} {', '.join(map(str, r.get('values') or []))}",
                "Confirm the tag is still maintained in the feed; plan an end date or a replacement definition")
        for r in rules:
            if DATE_ATTR.search(str(r.get("attribute", ""))):
                dates = [as_date(v, today) for v in r.get("values") or []]
                dates = [x for x in dates if x]
                if dates and max(dates) < today:
                    add("high" if busy else "medium", cid, "Fixed date in the past",
                        f"{r.get('attribute')} {r.get('operator')} {max(dates).isoformat()}",
                        "Update or remove the date condition; use a relative attribute such as days_since_release")
        if rules and all(str(r.get("attribute", "")).lower() in ("category_id", "category", "categories") for r in rules):
            add("medium" if busy else "low", cid, "Re-slices static categories only",
                desc, "Check whether shoppers need it; if it equals a static category, link to that instead")
        if not rules and not d.get("productIds"):
            add("high" if sessions else "medium", cid, "No conditions", "conditionConfig has no rules", "Add conditions or retire it")

        # Naming
        if TEST_WORDS.search(name):
            add("high" if busy else "low", cid, "Test or demo name",
                f"Name '{name}'; {int(sessions)} sessions", "Remove from live links, or rename and make it a real collection")
        if SEASONAL_WORDS.search(name) and not seasonal and found:
            add("low", cid, "Seasonal name, evergreen definition",
                f"Name '{name}'; conditions: {desc}", "Rename it, or tie it to the season and give it an end plan")
        if g and g.get("onsale") is not None and re.search(r"sale|offer|deal|discount|clearance|bogo", name, re.I):
            on = g["onsale"].get("true", 0)
            if found and on == 0:
                add("high" if busy else "medium", cid, "Name promises a sale, products aren't on sale",
                    f"0 of {found} products have onSale=true", "Add an onSale or price condition, or rename it")

        # Navigation
        paths = d.get("paths")
        if not paths and (not static or cid not in static):
            add("info", cid, "Not in navigation tree", "No paths; reachable only by direct link or campaign",
                "Fine for campaign landing pages; otherwise add it to the navigation")

        # Overlap
        if g and found:
            statics = [(oid, e) for oid, e in g["cats"].items() if oid != cid and not oid.startswith("brg_dyn_")]
            contained = [(oid, e) for oid, e in statics if e["count"] / found >= a.overlap]
            if contained:
                oid, e = max(contained, key=lambda x: (x[1]["crumb"].count("/"), x[1]["count"]))
                path = (static.get(oid) or {}).get("categoryPaths") or pretty_path(e, static) or oid
                other = grids.get(oid)
                if other and other["found"]:
                    jac = e["count"] / (found + other["found"] - e["count"])
                    if jac >= a.overlap:
                        add("medium", cid, "Duplicates a static category",
                            f"{e['count']}/{found} products shared with {path} ({other['found']} products); overlap {jac:.0%}",
                            f"Retire it and link to {path}, or make it distinct (add a filter that matches its purpose)")
                    else:
                        add("info", cid, "Subset of a static category",
                            f"{e['count'] / found:.0%} of its products are in {path} ({other['found']} products)",
                            "Fine if intended as a filtered view")
                else:
                    add("info", cid, "Subset of a static category",
                        f"{e['count'] / found:.0%} of its products are in {path}",
                        f"Fetch {path}'s size (grid, rows=1) to check for a duplicate")
            for oid, e in g["cats"].items():
                if oid == cid or not oid.startswith("brg_dyn_"):
                    continue
                pair = tuple(sorted((cid, oid)))
                if pair in seen_pairs:
                    continue
                other = grids.get(oid)
                if other and other["found"]:
                    jac = e["count"] / (found + other["found"] - e["count"])
                    if jac >= a.overlap:
                        seen_pairs.add(pair)
                        add("medium", cid, "Overlaps another dynamic category",
                            f"{e['count']} shared with '{name_of(oid)}' ({found} vs {other['found']} products); overlap {jac:.0%}",
                            "Merge them, or sharpen one definition so each page has a distinct purpose")
                elif e["count"] / found >= a.overlap and e["count"] >= a.thin:
                    seen_pairs.add(pair)
                    add("low", cid, "Mostly inside another dynamic category",
                        f"{e['count']}/{found} products also in '{name_of(oid)}'",
                        "Fetch the other category's size to confirm")

        # Performance
        if pr and busy and m_conv:
            reasons = []
            if conv is not None and conv < m_conv * (1 - thr):
                reasons.append(f"conversion {conv:.1f}% vs {m_conv:.1f}% dynamic median")
            if bounce is not None and m_bounce and bounce > m_bounce * (1 + thr):
                reasons.append(f"bounce {bounce:.1f}% vs {m_bounce:.1f}%")
            if reasons:
                impact = ""
                if conv is not None and aov:
                    impact = f"; upper-bound impact ${sessions * (m_conv - conv) / 100 * aov:,.0f} per period"
                add("high", cid, "Traffic but poor performance",
                    f"{int(sessions)} sessions; " + "; ".join(reasons) + impact,
                    "Check the products match the name and purpose; then hand ranking to discovery-category-health")
            ch = num(pr.get("change_revenue"))
            if ch is not None and abs(ch) >= 100 and d.get("lastModifiedAt"):
                mod = dt.datetime.fromtimestamp(d["lastModifiedAt"] / 1000, dt.timezone.utc).date()
                if (today - mod).days <= 90:
                    add("info", cid, "Big swing after an edit",
                        f"Revenue {ch:+.0f}% vs previous period; definition edited {mod.isoformat()}",
                        "Confirm the change before reporting it as a win or loss")
        if not pr and a.table:
            add("low", cid, "No tracked traffic", "Not in the category performance table for the period",
                "Retire it if nothing links to it; check pixel tracking if it should have traffic")

    if a.table:
        for cid, r in perf.items():
            if cid not in defs:
                add("high" if (num(r.get("browse_sessions")) or 0) >= a.min_sessions else "low", cid,
                    "Traffic to a category with no definition",
                    f"{r.get('category')}: {int(num(r.get('browse_sessions')) or 0)} sessions",
                    "Fetch it by ID; if it was deleted, fix the links that still point to it")

    print("## Dynamic category inventory\n")
    if m_conv:
        print(f"Dynamic medians ({len(eligible)} categories with {a.min_sessions}+ sessions): conversion {m_conv:.1f}%, "
              f"bounce {m_bounce:.1f}%" + (f", RPV ${m_rpv:.2f}" if m_rpv else "") + "\n")
    print("| Category | ID | Definition | Products | Sessions | Conversion | Bounce |")
    print("|---|---|---|---|---|---|---|")
    for name, cid, desc, found, sess, conv, bounce in rows_out:
        f = lambda v, s="": "-" if v is None else f"{v:g}{s}"
        print(f"| {name} | {cid} | {desc} | {f(found)} | {f(sess)} | {f(conv, '%')} | {f(bounce, '%')} |")

    print("\n## Findings\n")
    print("| Priority | Category | Issue | Evidence | Suggested action |")
    print("|---|---|---|---|---|")
    for sev, cid, issue, ev, act in sorted(findings, key=lambda x: (SEVERITY[x[0]], x[1])):
        print(f"| {sev} | {name_of(cid)} ({cid}) | {issue} | {ev} | {act} |")
    missing = [cid for cid in defs if cid not in grids]
    if missing:
        print(f"\nNo grid response for: {', '.join(missing)} (product counts and overlaps not checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
