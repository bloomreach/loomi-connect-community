#!/usr/bin/env python3
"""Find price anomalies across a whole catalog, compared like for like within each product group.

Usage:
  python3 price_anomalies.py PRODUCTS [PRODUCTS ...] [--performance perf.json ...]
         [--rank "QUERY=grid.json" ...] [--group-field product_type] [--csv findings.csv] [--out report.json]

  PRODUCTS       saved product pages, one tool response per file: search_discovery_product_grid_insights
                 (data.response.docs), search_discovery_catalog_products records, or Engagement
                 search_catalog_items results; or .jsonl files with one product per line. Write LABEL=FILE
                 to group every product in FILE under LABEL (for pages fetched one category at a time).
  --performance  a saved get_discovery_product_performance_table result: revenue and views per product,
                 for the exposure ranking.
  --rank         QUERY=FILE: a saved page-one grid for a top query; products on it count as exposed.
  --group-field  the attribute to group by (default: the first of group_fields in references/rules.json).
  --csv          also write every finding to this CSV file for the feed and pricing teams.
  --out          also write the JSON result to this file.

Checks, each with a priority (high / medium / low) raised by exposure (revenue, views or a page-one place):
  price_missing             no price, or a zero or negative price (or sale price)
  unit_error                an outlier whose price / 10, 100 or 1000 (or x) lands in the group's typical range
  category_outlier          far from the group median on a log scale (robust z from the median absolute
                            deviation, never mean or standard deviation) and at least min_ratio times off
  sale_not_below_price      a sale price above, or equal to, the regular price
  discount_too_deep         a sale price more than max_discount below the regular price
  variant_price_spread      variants of one product priced very differently (with a likely unit error named)
  duplicate_price_conflict  the same product ID, or the same brand and folded title, at different prices

All price maths uses Decimal; numbers are rounded only for display. Margin, cost and similar fields are never
read or output. Rules: references/rules.json. Standard library only; no network access.
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import unicodedata
from decimal import Decimal, getcontext
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
getcontext().prec = 28
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = ("high", "medium", "low")
ACCOUNT_LIST = ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
MAD_SCALE = Decimal("1.4826")
CENT = Decimal("0.01")
OWNER_FEED = "feed team"
OWNER_PRICING = "pricing team (confirm the price), then feed team"


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


def dec(v):
    """number() as an exact Decimal: ints exactly, floats and strings by their shortest decimal form."""
    if isinstance(v, int) and not isinstance(v, bool):
        return Decimal(v)
    x = number(v)
    return None if x is None else Decimal(repr(x))


def money(d):
    return None if d is None else str(d.quantize(CENT))


def tool_error(err):
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):  # these errors can list every account the user can access
        return ACCOUNT_LIST
    return text[:200]


def unwrap(data, path):
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


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        fail(f"{path}: can't read it ({e.strerror or e}).")
    try:
        data = json.loads(text)
    except ValueError:
        start = text.find("{")  # some clients save a wrapper line before the JSON
        try:
            data = json.loads(text[start:]) if start >= 0 else None
        except ValueError as e:
            fail(f"{path}: can't read it as JSON ({e}).")
    return unwrap(data, path)


def flatten(rec):
    """One product as a flat dict: catalog records keep attributes, Engagement items keep properties."""
    for key in ("attributes", "properties"):
        if isinstance(rec.get(key), dict):
            out = dict(rec[key])
            for k in ("id", "_id", "item_id", "pid"):
                if rec.get(k) not in (None, ""):
                    out.setdefault("pid", rec[k])
            return out
    return rec


def records_of(data):
    if isinstance(data, dict):
        resp = data.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("docs"), list):
            return [d for d in resp["docs"] if isinstance(d, dict) and d.get("docType") != "content"]
        for key in ("items", "products", "docs"):
            if isinstance(data.get(key), list):
                return records_of(data[key])
        if isinstance(data.get("attributes"), dict) or isinstance(data.get("properties"), dict):
            return [flatten(data)]
        return []
    if isinstance(data, list):
        return [flatten(x) for x in data if isinstance(x, dict) and x.get("docType") != "content"]
    return []


def input_spec(text):
    """FILE, or LABEL=FILE split on the first '=' (a path that exists is never split)."""
    if os.path.exists(text):
        return None, text
    label, sep, path = text.partition("=")
    if sep and label.strip() and path.strip():
        return label.strip(), path.strip()
    return None, text


def pair(text):
    name, sep, path = text.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE, got {text!r}")
    return name.strip(), path.strip()


def iter_products(specs):
    """Yield (label, flat record) from every input."""
    for label, path in specs:
        if path.endswith(".jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError as e:
                fail(f"{path}: can't read it ({e.strerror or e}).")
            for n, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    obj = unwrap(json.loads(line), f"{path}:{n}")
                except ValueError:
                    fail(f"{path}:{n}: malformed JSON line.")
                for rec in (records_of(obj) or ([flatten(obj)] if isinstance(obj, dict) else [])):
                    yield label, rec
        else:
            recs = records_of(load(path))
            if not recs:
                fail(f"{path}: no product records found; save a product grid page, catalog products or catalog items.")
            for rec in recs:
                yield label, rec


def first(rec, fields):
    for f in fields:
        v = rec.get(f)
        if v not in (None, "", []):
            return f, v
    return None, None


def text_of(v):
    if isinstance(v, list):
        v = v[0] if v else None
    return None if v is None else str(v).strip()


def group_of(value):
    s = text_of(value)
    if not s:
        return None
    for sep in RULES["group_value_separators"]:  # several values packed into one: keep the first
        s = s.split(sep)[0].strip() or s
    parts = [s]
    for sep in RULES["group_path_separators"]:  # a breadcrumb path: keep the leaf (or the top level)
        parts = [x.strip() for part in parts for x in part.split(sep) if x.strip()]
    if not parts:
        return None
    return parts[0] if RULES["group_level"] == "top" else parts[-1]


def fold_title(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def parse_price(rec):
    """(regular, sale, state): state is 'ok', 'missing' or 'unparsable' for the regular price."""
    pf, pv = first(rec, RULES["price_fields"])
    rf, rv = first(rec, RULES["regular_price_fields"])
    sf, sv = first(rec, RULES["sale_price_fields"])
    current = dec(text_of(pv) if isinstance(pv, list) else pv) if pf else None
    sale = dec(text_of(sv) if isinstance(sv, list) else sv) if sf else None
    if rf:
        regular = dec(rv)
        if sale is None:
            sale = current
        raw = rv
    else:
        regular, raw = current, pv
    if regular is None:
        return None, sale, ("missing" if raw in (None, "", []) else "unparsable")
    return regular, sale, "ok"


def variants_of(rec):
    out = []
    for i, v in enumerate(rec.get("variants") or []):
        if not isinstance(v, dict):
            continue
        _, p = first(v, RULES["variant_price_fields"])
        _, s = first(v, RULES["variant_sale_price_fields"])
        out.append({"id": str(v.get("skuid") or v.get("sku_id") or v.get("id") or i), "price": dec(p), "sale": dec(s)})
    return out


# ---------------------------------------------------------------------------------------------
# Statistics (exact Decimal maths)

def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def percentile(values, p):
    """Linear-interpolated percentile (p in 0-100) of Decimals."""
    s = sorted(values)
    pos = Decimal(len(s) - 1) * Decimal(p) / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def group_stats(prices):
    logs = [p.log10() for p in prices]
    m_log = median(logs)
    mad = median([abs(x - m_log) for x in logs])
    band = Decimal(str(RULES["typical_band"]))
    q1, q3 = percentile(prices, 25), percentile(prices, 75)
    return {"n": len(prices), "median": median(prices), "median_log": m_log, "mad_log": mad,
            "q1": q1, "q3": q3, "typical_low": q1 / band, "typical_high": q3 * band}


def judge(price, st):
    """(is_outlier, ratio, z, unit) for one positive price against its group's stats."""
    ratio = price / st["median"]
    min_ratio = Decimal(str(RULES["min_ratio"]))
    far = ratio >= min_ratio or ratio <= 1 / min_ratio
    if st["mad_log"] == 0:
        z = None
        out = far
    else:
        z = (price.log10() - st["median_log"]) / (MAD_SCALE * st["mad_log"])
        out = far and abs(z) >= Decimal(str(RULES["robust_z"]))
    unit = None
    if out:
        for f in RULES["unit_factors"]:
            fd = Decimal(f)
            fixed = price / fd if ratio > 1 else price * fd
            if st["typical_low"] <= fixed <= st["typical_high"]:
                unit = (f, fixed)
                break
    return out, ratio, z, unit


# ---------------------------------------------------------------------------------------------

def csv_safe(v):
    """Stop spreadsheets running a cell as a formula: prefix =, +, -, @, tab or CR with '."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def read_performance(paths):
    perf = {}
    for path in paths:
        data = load(path)
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            fail(f"{path}: no rows list found; save the get_discovery_product_performance_table result.")
        for r in rows:
            if not isinstance(r, dict):
                continue
            pid = str(r.get("prod_id") or r.get("pid") or "")
            if pid and pid not in perf:
                _, views = first(r, RULES["views_fields"])
                perf[pid] = {"revenue": dec(r.get("revenue")), "views": dec(views)}
    return perf


def read_ranks(pairs):
    ranks = {}
    for query, path in pairs:
        data = load(path)
        resp = data.get("response") if isinstance(data, dict) else None
        if not isinstance(resp, dict) or not isinstance(resp.get("docs"), list):
            fail(f"{path}: no response.docs found; save the search_discovery_product_grid_insights result.")
        pos = 0
        for d in resp["docs"]:
            if not isinstance(d, dict) or d.get("docType") == "content" or d.get("pid") in (None, ""):
                continue
            pos += 1
            if pos <= RULES["page_size"]:
                ranks.setdefault(str(d["pid"]), []).append({"query": query, "position": pos})
    return ranks


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("products", nargs="+", help="saved product pages: FILE or LABEL=FILE")
    ap.add_argument("--performance", action="append", default=[], help="a saved product performance table")
    ap.add_argument("--rank", action="append", type=pair, default=[], help="QUERY=FILE: a saved page-one grid")
    ap.add_argument("--group-field", help="attribute to group by (default: first of group_fields in rules.json)")
    ap.add_argument("--csv", help="also write every finding to this CSV file")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()

    group_fields = [a.group_field] if a.group_field else RULES["group_fields"]
    secret = set(RULES["never_output_fields"])
    products, conflicts, order = {}, [], []
    for label, rec in iter_products([input_spec(p) for p in a.products]):
        rec = {k: v for k, v in rec.items() if k not in secret}
        _, pid = first(rec, RULES["id_fields"])
        if pid is None:
            continue
        pid = str(pid)
        regular, sale, state = parse_price(rec)
        _, title = first(rec, RULES["title_fields"])
        _, brand = first(rec, RULES["brand_fields"])
        group = label or group_of(first(rec, group_fields)[1])
        p = {"pid": pid, "title": text_of(title), "brand": text_of(brand), "group": group, "regular": regular,
             "sale": sale, "state": state, "variants": variants_of(rec)}
        if pid in products:
            prev = products[pid]
            if prev["regular"] is not None and regular is not None and prev["regular"] != regular:
                conflicts.append((pid, prev["regular"], regular))
            continue
        products[pid] = p
        order.append(pid)

    perf = read_performance(a.performance)
    ranks = read_ranks(a.rank)
    min_views = Decimal(RULES["min_views"])

    def exposure(pid):
        pr = perf.get(pid) or {}
        rev, views = pr.get("revenue"), pr.get("views")
        where = sorted(ranks.get(pid, []), key=lambda w: (w["position"], w["query"]))
        exposed = bool((rev and rev > 0) or (views is not None and views >= min_views) or where)
        return {"revenue": rev, "views": views, "page_one": where, "exposed": exposed}

    findings = []

    def add(pid, check, high_if_exposed, issue, fix, owner, **extra):
        p = products.get(pid, {})
        ex = exposure(pid)
        hi, lo = high_if_exposed
        findings.append({"priority": hi if ex["exposed"] else lo, "check": check, "pid": pid,
                         "title": p.get("title"), "group": p.get("group"),
                         "price": money(p.get("regular")), "sale_price": money(p.get("sale")),
                         "revenue": money(ex["revenue"]), "views": None if ex["views"] is None else str(ex["views"]),
                         "page_one": ex["page_one"], "issue": issue, "fix": fix, "owner": owner,
                         "see_also": extra.pop("see_also", None), **extra})

    # Groups and their statistics
    groups = {}
    for pid in order:
        p = products[pid]
        if p["group"] and p["regular"] is not None and p["regular"] > 0:
            groups.setdefault(p["group"], []).append(p["regular"])
    stats = {g: group_stats(v) for g, v in groups.items() if len(v) >= RULES["min_group_size"]}
    small = sorted(g for g, v in groups.items() if len(v) < RULES["min_group_size"])
    ungrouped = sum(1 for pid in order if not products[pid]["group"])

    # Sale = price everywhere means a default-filled sale_price, not thousands of findings
    priced = [products[pid] for pid in order if products[pid]["regular"] is not None and products[pid]["regular"] > 0]
    equal = [p for p in priced if p["sale"] is not None and p["sale"] == p["regular"]]
    equal_default = bool(priced) and Decimal(len(equal)) / Decimal(len(priced)) >= Decimal(str(RULES["sale_equal_default_share"]))
    max_discount = Decimal(str(RULES["max_discount"]))
    page_one_note = "discovery-variant-health (page-one and top-seller view)"

    for pid in order:
        p = products[pid]
        reg, sale = p["regular"], p["sale"]
        if reg is None:
            add(pid, "price_missing", ("medium", "low"),
                "No price" if p["state"] == "missing" else "The price isn't a number",
                "Send a price for this product in the feed.", OWNER_FEED, see_also=page_one_note)
        elif reg <= 0:
            add(pid, "price_missing", ("high", "medium"), f"Price is {money(reg)}",
                "Fix the price in the feed (a zero price shows as free or hides the product).", OWNER_FEED,
                see_also=page_one_note)
        if sale is not None and sale <= 0 and (reg is None or reg > 0):
            add(pid, "price_missing", ("high", "medium"), f"Sale price is {money(sale)}",
                "Remove the sale price or fix it in the feed.", OWNER_FEED, see_also=page_one_note)
        if reg is not None and reg > 0 and sale is not None and sale > 0:
            if sale > reg:
                add(pid, "sale_not_below_price", ("high", "medium"),
                    f"Sale price {money(sale)} is above the regular price {money(reg)}",
                    "Fix sale_price in the feed, or swap the two fields.", OWNER_FEED, see_also=page_one_note)
            elif sale == reg and not equal_default:
                add(pid, "sale_not_below_price", ("low", "low"),
                    f"Sale price equals the regular price ({money(reg)})",
                    "Leave sale_price empty when there's no discount, so 'on sale' badges and filters stay true.",
                    OWNER_FEED)
            elif (reg - sale) / reg > max_discount:
                off = (reg - sale) / reg * 100
                add(pid, "discount_too_deep", ("medium", "low"),
                    f"Sale price {money(sale)} is {off.quantize(Decimal('1'))}% below the regular price {money(reg)}",
                    "Confirm the discount; a missing digit in either price often looks like this.", OWNER_PRICING)
        # Like-for-like comparison
        st = stats.get(p["group"])
        if st and reg is not None and reg > 0:
            out, ratio, z, unit = judge(reg, st)
            if out:
                zt = "" if z is None else f", robust z {z.quantize(Decimal('0.1'))}"
                base = (f"Price {money(reg)} is {ratio.quantize(CENT)}x the {p['group']} median of "
                        f"{money(st['median'])} (typical {money(st['q1'])}-{money(st['q3'])}, n={st['n']}{zt})")
                if unit:
                    f, fixed = unit
                    op = "÷" if ratio > 1 else "×"
                    add(pid, "unit_error", ("high", "medium"),
                        f"{base}; {op}{f} gives {money(fixed)}, inside the typical range: likely a unit or decimal error",
                        f"Check the feed's price unit (cents vs whole currency, a shifted decimal point) and send {money(fixed)} if that's the real price.",
                        OWNER_FEED)
                else:
                    add(pid, "category_outlier", ("medium", "low"), base,
                        "Confirm the price; if it's right, check the product is in the right category.", OWNER_PRICING)
        # Variants
        vp = [v for v in p["variants"] if v["price"] is not None and v["price"] > 0]
        for v in p["variants"]:
            if v["price"] is not None and v["sale"] is not None and v["sale"] > v["price"] > 0:
                add(pid, "sale_not_below_price", ("high", "medium"),
                    f"Variant {v['id']} sale price {money(v['sale'])} is above its price {money(v['price'])}",
                    "Fix the variant's sale price in the feed.", OWNER_FEED, see_also=page_one_note)
        if len(vp) >= 2:
            lo_v = min(vp, key=lambda v: (v["price"], v["id"]))
            hi_v = max(vp, key=lambda v: (v["price"], v["id"]))
            spread = hi_v["price"] / lo_v["price"]
            if spread >= Decimal(str(RULES["variant_spread_ratio"])):
                mid = median([v["price"] for v in vp])
                odd = max(vp, key=lambda v: (abs(v["price"].log10() - mid.log10()), v["id"]))
                hint = ""
                for f in RULES["unit_factors"]:
                    fd = Decimal(f)
                    if fd / Decimal(str(RULES["typical_band"])) <= spread <= fd * Decimal(str(RULES["typical_band"])):
                        hint = f"; the gap is about ×{f}, so variant {odd['id']} may have a unit or decimal error"
                        break
                add(pid, "variant_price_spread", ("medium", "low"),
                    f"Variant prices run from {money(lo_v['price'])} ({lo_v['id']}) to {money(hi_v['price'])} "
                    f"({hi_v['id']}), {spread.quantize(CENT)}x{hint}",
                    "Check the variant prices in the feed; split the product if the variants are really different items.",
                    OWNER_FEED)

    # The same product ID at different prices
    for pid, before, after in sorted(conflicts, key=lambda c: (c[0], c[1], c[2])):
        hi_p, lo_p = max(before, after), min(before, after)
        if (hi_p - lo_p) / hi_p > Decimal(str(RULES["duplicate_price_tolerance"])):
            add(pid, "duplicate_price_conflict", ("medium", "low"),
                f"Product ID {pid} appears more than once, at {money(before)} and {money(after)}",
                "Send each product once in the feed, with one price.", OWNER_FEED)
    # The same brand and folded title at different prices
    by_title = {}
    for pid in order:
        p = products[pid]
        if p["title"] and p["regular"] is not None and p["regular"] > 0:
            by_title.setdefault((fold_title(p["brand"]), fold_title(p["title"])), []).append(pid)
    for key in sorted(by_title):
        pids = sorted(by_title[key])
        if len(pids) < 2:
            continue
        prices = sorted({products[x]["regular"] for x in pids})
        if (prices[-1] - prices[0]) / prices[-1] > Decimal(str(RULES["duplicate_price_tolerance"])):
            listing = ", ".join(f"{x} at {money(products[x]['regular'])}" for x in pids[:6])
            for x in pids:
                add(x, "duplicate_price_conflict", ("medium", "low"),
                    f"Same brand and title as {len(pids) - 1} other product(s) at a different price: {listing}",
                    "Check whether these are the same item; if so, merge them or align the price.", OWNER_PRICING)

    def sort_key(f):
        best = min((w["position"] for w in f["page_one"]), default=10 ** 6)
        return (PRIORITY.index(f["priority"]), -(Decimal(f["revenue"]) if f["revenue"] else 0),
                -(Decimal(f["views"]) if f["views"] else 0), best, f["pid"], f["check"], f["issue"])
    findings.sort(key=sort_key)
    for f in findings:
        if f["see_also"] is None:
            del f["see_also"]

    counts = {p: sum(1 for f in findings if f["priority"] == p) for p in PRIORITY}
    by_check = {}
    for f in findings:
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
    by_owner = {}
    for f in findings:
        by_owner[f["owner"]] = by_owner.get(f["owner"], 0) + 1
    stake = {}
    for pr in PRIORITY:
        seen = {f["pid"]: Decimal(f["revenue"]) for f in findings if f["priority"] == pr and f["revenue"]}
        stake[pr] = money(sum(seen.values(), Decimal(0)))

    notes, not_checked = [], []
    if equal_default:
        notes.append(f"{len(equal)} of {len(priced)} priced products have a sale price equal to the regular price: the "
                     "feed fills sale_price by default. One feed fix (leave it empty when there's no discount), so they "
                     "aren't listed one by one.")
    if small:
        not_checked.append(f"Outliers and unit errors not judged for {len(small)} group(s) with fewer than "
                           f"{RULES['min_group_size']} priced products: {', '.join(small[:10])}"
                           + (" …" if len(small) > 10 else ""))
    if ungrouped:
        not_checked.append(f"{ungrouped} product(s) have no group ({', '.join(group_fields[:3])} …): only the checks "
                           "that don't need a group ran on them. Pass LABEL=FILE or --group-field.")
    if not a.performance and not a.rank:
        not_checked.append("Exposure: no --performance or --rank files, so priorities ignore revenue, views and rank.")

    group_table = sorted(({"group": g, "products": s["n"], "median": money(s["median"]), "q1": money(s["q1"]),
                           "q3": money(s["q3"])} for g, s in stats.items()), key=lambda r: (-r["products"], r["group"]))
    cap = RULES["max_findings_listed"]
    out = {"ok": True, "products_read": len(order), "products_priced": len(priced), "groups_judged": len(stats),
           "counts": counts, "by_check": dict(sorted(by_check.items())), "by_owner": dict(sorted(by_owner.items())),
           "revenue_at_stake": stake, "catalog_notes": notes, "groups": group_table[:30],
           "findings": findings[:cap], "findings_not_listed": max(0, len(findings) - cap), "not_checked": not_checked}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    try:
        if a.csv:
            cols = ["priority", "check", "pid", "title", "group", "price", "sale_price", "revenue", "views",
                    "issue", "fix", "owner"]
            with open(a.csv, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(cols)
                for row in findings:
                    w.writerow([csv_safe(row.get(c)) for c in cols])
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
    except OSError as e:
        fail(f"Can't write the output: {e.strerror or e}")
    print(text)


if __name__ == "__main__":
    main()
