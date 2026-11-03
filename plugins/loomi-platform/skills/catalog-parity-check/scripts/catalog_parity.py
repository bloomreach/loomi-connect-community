#!/usr/bin/env python3
"""Compare a Bloomreach Discovery catalog with the Engagement catalog behind recommendations and emails.

Usage:
  python3 catalog_parity.py [--products perf.json] [--grid "dress=grid_dress.json" ...]
         [--discovery d_lookup.json ...] [--discovery-random d_page7.json ...]
         [--engagement e_lookup.json ...] [--engagement-random e_skip300.json ...]
         [--not-in-engagement ID,ID] [--not-in-discovery ID,ID]
         [--discovery-key pid] [--engagement-key item_id] [--field price=price:price_eur]
         [--top 30] [--out report.json]

  --products           a saved get_discovery_product_performance_table result, sorted by revenue. Its first
                       top_sellers rows are tagged top_seller, and every row gives a product's revenue at stake.
  --grid               LABEL=FILE: a saved search_discovery_product_grid_insights result for a top search or
                       category. Its first page_size products are tagged page_one.
  --discovery          a saved search_discovery_catalog_products result: a lookup by product_id or a list page
                       (the priority sample).
  --discovery-random   a saved search_discovery_catalog_products list page fetched at a random page number
                       (the random sample, used for the rates).
  --engagement         a saved search_catalog_items or get_catalog_item result. A get_catalog_item "not found"
                       error saved as JSON counts as missing from Engagement.
  --engagement-random  a saved search_catalog_items page fetched at a random skip (the random sample from the
                       Engagement side).
  --not-in-engagement  product IDs Engagement didn't have (comma-separated; repeatable).
  --not-in-discovery   product IDs Discovery didn't have, for example a 404 from search_discovery_catalog_products.
  --discovery-key      the Discovery attribute that holds the shared ID (default: the record ID, which is pid).
  --engagement-key     the Engagement property that holds the shared ID (default: the item ID).
  --field              NAME=DFIELD:EFIELD, to compare NAME using these two fields for this run.

Checks each sampled product in both catalogs: present in one and not the other, and whether price, sale price,
stock, URL, image and title agree. Reports the mismatch rate of each on the random sample, with its size and a
Wilson confidence interval, and lists the products with findings, priority high / medium / low, ranked by the
Discovery revenue at stake. Reads only the compared fields: never outputs margin, cost or other attributes.

Rules: references/rules.json. Standard library only; no network access.
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
FIELDS = ("price", "sale_price", "availability", "url", "image", "title")
NOT_FOUND_RE = re.compile(r"Item '(.+?)' not found", re.S)


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


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def unwrap(data, path, allow_not_found=False):
    """The data of a saved tool result, unwrapping {"result": ...} and {"data": ...} layers.

    Returns ("not_found", id) for a get_catalog_item not-found error when allow_not_found is set."""
    while isinstance(data, dict):
        if data.get("success") is False:
            err = str(data.get("error") or "no error text")
            m = NOT_FOUND_RE.search(err)
            if allow_not_found and m:
                return ("not_found", m.group(1))
            fail(f"{path}: Loomi Connect returned an error: {err[:200]} This check couldn't run; "
                 "don't treat it as 'nothing found'.")
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


NEVER_FIELDS = re.compile(r"margin|cost|profit|wholesale|markup", re.I)


def field_override(text):
    name, sep, rest = text.partition("=")
    dfield, sep2, efield = rest.partition(":")
    if not sep or not sep2 or name.strip() not in FIELDS or not dfield.strip() or not efield.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=DFIELD:EFIELD with NAME one of {', '.join(FIELDS)}, got {text!r}")
    if NEVER_FIELDS.search(dfield) or NEVER_FIELDS.search(efield):
        raise argparse.ArgumentTypeError(f"{text!r}: margin, cost and similar commercial fields are never compared or output")
    return name.strip(), dfield.strip(), efield.strip()


SHOWN = {}  # normalised ID -> the ID as first seen, for the report


def norm_id(v):
    s = str(v).strip()
    k = s.lower() if RULES["id_case_insensitive"] else s
    SHOWN.setdefault(k, s)
    return k


# ---------------------------------------------------------------------------------------------
# Reading the saved results

def discovery_records(path):
    data = unwrap(read_json(path), path)
    recs = data if isinstance(data, list) else [data]
    out = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        attrs = dict(r.get("attributes") or {})
        rid = r.get("id") if r.get("id") is not None else attrs.get("pid")
        out.append((rid, attrs))
    return out


def engagement_records(path):
    """[(item_id, properties)] and a list of IDs reported not found."""
    data = unwrap(read_json(path), path, allow_not_found=True)
    if isinstance(data, tuple):
        return [], [data[1]]
    recs = data if isinstance(data, list) else [data]
    out = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        props = {k: v for k, v in r.items() if k not in ("properties", "catalog_id")}
        props.update(r.get("properties") or {})
        out.append((r.get("_id", r.get("item_id")), props))
    return out, []


def table_rows(path):
    data = unwrap(read_json(path), path)
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        fail(f"{path}: no rows list found; is this a get_discovery_product_performance_table result?")
    return rows


def grid_pids(path):
    data = unwrap(read_json(path), path)
    docs = ((data.get("response") or {}).get("docs") if isinstance(data, dict) else None)
    if not isinstance(docs, list):
        fail(f"{path}: no response.docs list found; is this a search_discovery_product_grid_insights result?")
    return [d.get("pid") for d in docs if isinstance(d, dict) and d.get("pid") is not None
            and d.get("docType") != "content"][:RULES["page_size"]]


# ---------------------------------------------------------------------------------------------
# Comparing values

def first_value(attrs, fields):
    for f in fields:
        v = attrs.get(f)
        if isinstance(v, list):
            v = next((x for x in v if x not in (None, "")), None)
        if v is None or (isinstance(v, str) and v.strip().lower() in MISSING):
            continue
        return f, v
    return None, None


def stock_state(v):
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "in" if v else "out"
    if isinstance(v, (int, float)):
        return "in" if v > 0 else "out"
    text = str(v).strip().lower()
    if text in RULES["unknown_stock_values"]:
        return "unknown"
    if text in RULES["out_of_stock_values"]:
        return "out"
    if text in RULES["in_stock_values"]:
        return "in"
    n = number(text)
    if n is not None:
        return "in" if n > 0 else "out"
    return "unknown"


def prices_match(a, b):
    diff = abs(a - b)
    return diff <= RULES["price_abs_tolerance"] or diff <= max(abs(a), abs(b)) * RULES["price_rel_tolerance_pct"] / 100


def norm_url(v):
    s = str(v).strip()
    if not s:
        return ""
    parts = urlsplit(s if "//" in s else "//" + s if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", s, re.I) else s)
    host = (parts.netloc or "").lower()
    if RULES["url_ignore_www"] and host.startswith("www."):
        host = host[4:]
    scheme = "" if RULES["url_ignore_scheme"] else (parts.scheme or "").lower()
    path = parts.path.rstrip("/")
    tail = "" if RULES["url_ignore_query"] else (("?" + parts.query if parts.query else "") +
                                                 ("#" + parts.fragment if parts.fragment else ""))
    return f"{scheme}//{host}{path}{tail}" if host else f"{path}{tail}"


def basename(v):
    path = urlsplit(str(v).strip()).path
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return name.rsplit(".", 1)[0] if "." in name else name


def norm_title(v):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(v).casefold())).strip()


def compare(field, dv, ev, dattrs, eattrs, fields):
    """None when the field can't be compared, else (matches, detail)."""
    if field == "availability":
        ds, es = stock_state(dv), stock_state(ev)
        if "unknown" in (ds, es):
            return None
        if ds == es:
            return True, None
        return False, "out_of_stock_on_site" if ds == "out" else "out_of_stock_in_engagement"
    if field == "sale_price":
        def effective(v, attrs, side):
            sale = number(v)
            price = number(first_value(attrs, fields["price"][side])[1])
            if sale is None or sale <= 0 or (price is not None and sale >= price):
                return None  # no discount
            return sale
        ds, es = effective(dv, dattrs, "discovery"), effective(ev, eattrs, "engagement")
        if ds is None and es is None:
            return True, None
        if ds is None or es is None:
            return False, "sale price only in " + ("engagement" if ds is None else "discovery")
        return (True, None) if prices_match(ds, es) else (False, None)
    if dv is None and ev is None:
        return None
    if dv is None or ev is None:
        return False, "missing in " + ("discovery" if dv is None else "engagement")
    if field == "price":
        dn, en = number(dv), number(ev)
        if dn is None or en is None:
            return False, "not a number in " + ("discovery" if dn is None else "engagement")
        return (True, None) if prices_match(dn, en) else (False, None)
    if field == "url":
        return (True, None) if norm_url(dv) == norm_url(ev) else (False, None)
    if field == "image":
        if norm_url(dv) == norm_url(ev):
            return True, None
        if basename(dv) and basename(dv) == basename(ev):
            return True, "same file name on a different host or size"
        return False, None
    return (True, None) if norm_title(dv) == norm_title(ev) else (False, None)


def wilson(k, n, z):
    if not n:
        return None, None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k, n):
    lo, hi = wilson(k, n, RULES["confidence_z"])
    return {"mismatches": k, "compared": n, "rate_pct": round(k / n * 100, 1) if n else None,
            "interval_pct": [round(lo * 100, 1), round(hi * 100, 1)] if n else None}


def display(field, v):
    if v is None:
        return None
    if field in ("price", "sale_price"):
        n = number(v)
        return n if n is not None else str(v)[:40]
    if isinstance(v, (bool, int, float)):
        return v
    return str(v)[:200]


# ---------------------------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", help="get_discovery_product_performance_table, sorted by revenue: top sellers and revenue at stake")
    ap.add_argument("--grid", action="append", default=[], type=pair, help="LABEL=FILE: a saved product grid for a top search or category (repeatable)")
    ap.add_argument("--discovery", action="append", default=[], help="search_discovery_catalog_products lookups or pages for the priority sample (repeatable)")
    ap.add_argument("--discovery-random", action="append", default=[], help="search_discovery_catalog_products list pages at random page numbers (repeatable)")
    ap.add_argument("--engagement", action="append", default=[], help="search_catalog_items or get_catalog_item results, including not-found errors (repeatable)")
    ap.add_argument("--engagement-random", action="append", default=[], help="search_catalog_items pages at spread skip values (repeatable)")
    ap.add_argument("--not-in-engagement", action="append", default=[], help="comma-separated IDs Engagement didn't have (repeatable)")
    ap.add_argument("--not-in-discovery", action="append", default=[], help="comma-separated IDs Discovery didn't have, e.g. a 404 (repeatable)")
    ap.add_argument("--discovery-key", help="Discovery attribute holding the shared ID (default: the record ID)")
    ap.add_argument("--engagement-key", help="Engagement property holding the shared ID (default: the item ID)")
    ap.add_argument("--field", action="append", default=[], type=field_override, help="NAME=DFIELD:EFIELD: compare NAME with these fields for this run (repeatable)")
    ap.add_argument("--top", type=int, default=RULES["max_findings_listed"], help="products with findings to list in full (default: rules.json)")
    ap.add_argument("--out", help="write the JSON here instead of printing it")
    a = ap.parse_args()

    fields = {k: dict(v) for k, v in RULES["fields"].items()}
    for name, dfield, efield in a.field:
        fields[name] = {"discovery": [dfield], "engagement": [efield]}

    def dkey(rid, attrs):
        v = attrs.get(a.discovery_key) if a.discovery_key else rid
        return None if v in (None, "") else norm_id(v)

    def ekey(rid, props):
        v = props.get(a.engagement_key) if a.engagement_key else rid
        return None if v in (None, "") else norm_id(v)

    D, E = {}, {}
    tags, revenue, titles = {}, {}, {}
    random_d, random_e, priority = set(), set(), []

    def tag(pid, t):
        tags.setdefault(pid, [])
        if t not in tags[pid]:
            tags[pid].append(t)

    if a.products:
        for i, r in enumerate(table_rows(a.products)):
            pid = r.get("prod_id")
            if pid in (None, ""):
                continue
            pid = norm_id(pid)
            revenue[pid] = revenue.get(pid, 0.0) + (number(r.get("revenue")) or 0.0)
            titles.setdefault(pid, r.get("product_title"))
            if i < RULES["top_sellers"]:
                tag(pid, "top_seller")
                priority.append(pid)
    for label, path in a.grid:
        for pid in grid_pids(path):
            pid = norm_id(pid)
            tag(pid, f"page_one:{label}")
            priority.append(pid)
    for path in a.discovery:
        for rid, attrs in discovery_records(path):
            k = dkey(rid, attrs)
            if k:
                D[k] = attrs
                priority.append(k)
    for path in a.discovery_random:
        for rid, attrs in discovery_records(path):
            k = dkey(rid, attrs)
            if k:
                D[k] = attrs
                random_d.add(k)
                tag(k, "random")
    not_in_e = {norm_id(x) for s in a.not_in_engagement for x in s.split(",") if x.strip()}
    not_in_d = {norm_id(x) for s in a.not_in_discovery for x in s.split(",") if x.strip()}
    for is_random, paths in ((False, a.engagement), (True, a.engagement_random)):
        for path in paths:
            recs, missing = engagement_records(path)
            not_in_e.update(norm_id(x) for x in missing)
            for rid, props in recs:
                k = ekey(rid, props)
                if k:
                    E[k] = props
                    if is_random:
                        random_e.add(k)
                        tag(k, "random")

    # Every product in a sample, once, in a stable order.
    sampled = list(dict.fromkeys(priority + sorted(random_d) + sorted(random_e)))
    findings, unchecked = [], {"not_looked_up_in_engagement": [], "not_looked_up_in_discovery": []}
    stats = {g: {f: [0, 0] for f in FIELDS} for g in ("random", "engagement_side", "priority")}
    presence = {"discovery_to_engagement": [0, 0], "engagement_to_discovery": [0, 0],
                "priority_discovery_to_engagement": [0, 0]}

    for pid in sampled:
        in_d, in_e = pid in D, pid in E
        checks = []
        title = titles.get(pid) or (first_value(D.get(pid, {}), fields["title"]["discovery"])[1] if in_d else None) \
            or (first_value(E.get(pid, {}), fields["title"]["engagement"])[1] if in_e else None)
        from_d_side = pid in random_d or pid in priority
        # Presence
        if from_d_side and not in_e:
            if pid in not_in_e:
                checks.append({"check": "missing_in_engagement", "priority": RULES["priority"]["missing_in_engagement"],
                               "detail": "on the site but not in the Engagement catalog, so recommendations and emails can't show it"})
            else:
                unchecked["not_looked_up_in_engagement"].append(pid)
        if pid in random_d and (in_e or pid in not_in_e):
            presence["discovery_to_engagement"][1] += 1
            presence["discovery_to_engagement"][0] += 0 if in_e else 1
        if pid in priority and (in_e or pid in not_in_e):
            presence["priority_discovery_to_engagement"][1] += 1
            presence["priority_discovery_to_engagement"][0] += 0 if in_e else 1
        if pid in random_e and not in_d:
            if pid in not_in_d:
                estock = stock_state(first_value(E[pid], fields["availability"]["engagement"])[1])
                prio = "low" if estock == "out" else RULES["priority"]["missing_in_discovery"]
                checks.append({"check": "missing_in_discovery", "priority": prio,
                               "detail": "in the Engagement catalog but not on the site: recommendations can link to a "
                                         "product shoppers can't find" + (" (already out of stock in Engagement)" if estock == "out" else "")})
            else:
                unchecked["not_looked_up_in_discovery"].append(pid)
        if pid in random_e and (in_d or pid in not_in_d):
            presence["engagement_to_discovery"][1] += 1
            presence["engagement_to_discovery"][0] += 0 if in_d else 1
        # Fields
        if in_d and in_e:
            for f in FIELDS:
                dfield, dv = first_value(D[pid], fields[f]["discovery"])
                efield, ev = first_value(E[pid], fields[f]["engagement"])
                result = compare(f, dv, ev, D[pid], E[pid], fields)
                if result is None:
                    continue
                ok, detail = result
                for group, member in (("random", pid in random_d), ("engagement_side", pid in random_e),
                                      ("priority", pid in priority)):
                    if member:
                        stats[group][f][1] += 1
                        stats[group][f][0] += 0 if ok else 1
                if ok:
                    continue
                if f == "availability":
                    key = "stock_out_on_site_in_engagement" if detail == "out_of_stock_on_site" else "stock_in_on_site_out_in_engagement"
                    detail = ("out of stock on the site but in stock in Engagement: recommendations and emails can "
                              "send shoppers to a product they can't buy") if key.startswith("stock_out") else \
                             "in stock on the site but out of stock in Engagement: recommendations leave it out"
                    check, prio = key, RULES["priority"][key]
                else:
                    check, prio = f + "_mismatch", RULES["priority"][f]
                checks.append({"check": check, "priority": prio, "detail": detail,
                               "discovery": display(f, dv), "engagement": display(f, ev),
                               "fields": f"{dfield or '-'} / {efield or '-'}"})
        if checks:
            checks.sort(key=lambda c: PRIORITY.index(c["priority"]))
            findings.append({"product_id": SHOWN.get(pid, pid), "title": str(title)[:120] if title else None,
                             "sample": tags.get(pid, ["lookup"]), "revenue_at_stake": round(revenue.get(pid, 0.0), 2),
                             "priority": checks[0]["priority"], "checks": checks})

    findings.sort(key=lambda f: (PRIORITY.index(f["priority"]), -f["revenue_at_stake"], str(f["product_id"]).lower()))
    by_check = {}
    for f in findings:
        for c in f["checks"]:
            b = by_check.setdefault(c["check"], {"products": 0, "revenue_at_stake": 0.0, "priority": c["priority"]})
            if PRIORITY.index(c["priority"]) < PRIORITY.index(b["priority"]):
                b["priority"] = c["priority"]
            b["products"] += 1
            b["revenue_at_stake"] = round(b["revenue_at_stake"] + f["revenue_at_stake"], 2)
    out = {
        "ok": True,
        "id_mapping": f"Discovery {a.discovery_key or 'product ID (pid)'} = Engagement {a.engagement_key or 'item ID'}"
                      + (", trimmed and compared case-insensitively" if RULES["id_case_insensitive"] else ", trimmed"),
        "fields_compared": {f: {"discovery": fields[f]["discovery"], "engagement": fields[f]["engagement"]} for f in FIELDS},
        "sample": {"products": len(sampled), "priority": len(set(priority)), "random_from_discovery": len(random_d),
                   "random_from_engagement": len(random_e),
                   "top_sellers": sum(1 for t in tags.values() if "top_seller" in t),
                   "page_one": sum(1 for t in tags.values() if any(x.startswith("page_one:") for x in t))},
        "rates_random_sample": {
            "note": "the random sample from Discovery: use these for the headline rates. The interval assumes "
                    "independent draws, so it is too narrow if the sample is a few pages of adjacent products",
            "missing_in_engagement": rate(*presence["discovery_to_engagement"]),
            **{f: rate(*stats["random"][f]) for f in FIELDS}},
        "rates_engagement_sample": {
            "note": "items spread over the first 1,000 of the Engagement catalog: not a random sample of the "
                    "whole catalog; report separately",
            "missing_in_discovery": rate(*presence["engagement_to_discovery"]),
            **{f: rate(*stats["engagement_side"][f]) for f in FIELDS}},
        "rates_priority_sample": {
            "note": "top sellers and page-one products only: not representative of the whole catalog",
            "missing_in_engagement": rate(*presence["priority_discovery_to_engagement"]),
            **{f: rate(*stats["priority"][f]) for f in FIELDS}},
        "by_check": dict(sorted(by_check.items(), key=lambda kv: (PRIORITY.index(kv[1]["priority"]), -kv[1]["revenue_at_stake"]))),
        "findings": findings[:a.top],
        "findings_total": len(findings),
        "unchecked": {k: sorted({SHOWN.get(x, x) for x in v}) for k, v in unchecked.items() if v},
    }
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            fail(f"{a.out}: can't write it ({e}).")
        print(json.dumps({"ok": True, "out": a.out, "findings_total": len(findings)}))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
