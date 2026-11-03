#!/usr/bin/env python3
"""Preview a Bloomreach Discovery merchandising change before it goes live, and rate it.

Usage:
  python3 change_preview.py --change change.json [--grid "QUERY=grid.json" ...]
      [--grid-after "QUERY=grid.json" ...] [--target-grid "TERM=grid.json" ...]
      [--queries query_perf.json ...] [--categories category_perf.json ...]
      [--products product_perf.json ...] [--existing rule_list.json ...]
      [--experiments running.json ...] [--synonyms synonym_list.json ...]
      [--now 2026-11-03T12:00:00Z] [--page-size 24] [--out result.json]

--change is the proposed change: either a saved get_ranking_rule or search_redirects detail, a
synonym record from list_synonyms_user, or a JSON object written by hand (see
references/change-format.md). --grid is the live product grid (search_discovery_product_grid_insights)
for an affected query or category ID; --grid-after is a real "after" grid, for example the same
query with an existing rule in disabled_customization_ids. Without --grid-after the after grid is
simulated as the strongest possible version of the rule (a hard sort), so the real effect of an
attribute boost is milder. --target-grid is the grid for a synonym's target term.

Prints JSON: the verdict (GO, GO WITH CAUTION or NO-GO), the affected queries and their revenue,
a before and after first page per previewed query, and findings by severity. Thresholds and word
lists are in references/rules.json. Standard library only; no network access.
"""
import argparse
import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# The thresholds live in references/rules.json, so a rule changes in one place.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
SEVERITY = ("blocker", "warning", "nitpick")
# Rule list ruleType values that are the same kind of change (media rules show up as "campaign").
SAME_TYPE = {"ranking": ("ranking",), "redirect": ("redirect",), "media": ("campaign", "media", "banner"),
             "facet": ("facet",)}
STOP = set(RULES["stop_words"])


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read JSON ({e})")
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    return doc


def unwrap(doc):
    """Strip the result/data wrappers Loomi Connect puts around records."""
    while isinstance(doc, dict):
        if "result" in doc and isinstance(doc["result"], dict):
            doc = doc["result"]
        elif "data" in doc and isinstance(doc["data"], (dict, list)) and not any(
                k in doc for k in ("customizationItems", "sourceSynonym", "type", "response")):
            doc = doc["data"]
        else:
            break
    return doc


def records(path):
    """List records from a list tool's saved result (rules, synonyms, experiments, performance rows)."""
    doc = unwrap(load(path))
    if isinstance(doc, dict):
        doc = doc.get("rows") or doc.get("data") or []
    return doc if isinstance(doc, list) else []


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", norm(text)) if w not in STOP}


def overlaps(a, b):
    """True when two word sets share a word, allowing plurals ("dress" and "dresses")."""
    return any(x == y or (min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x))) for x in a for y in b)


def money(v):
    if v in (None, ""):
        return 0.0
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)) or 0)
    except ValueError:
        return 0.0


def ts(v):
    """Epoch milliseconds, epoch seconds or an ISO date -> aware datetime."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def pair(value, flag):
    key, sep, path = value.partition("=")
    if not sep or not key.strip() or not path.strip():
        fail(f"{flag} needs QUERY=path, got {value!r}")
    return norm(key), path.strip()


# ---------------------------------------------------------------------------------------------
# The change

def attr_operands(rule, out):
    """Flatten attribute operands out of a (possibly nested) attribute_boost_bury clause."""
    if not isinstance(rule, dict):
        return out
    if rule.get("type") == "attribute":
        out.append((rule.get("name"), [str(x) for x in rule.get("operands") or []]))
    for op in rule.get("operands") or []:
        if isinstance(op, dict):
            attr_operands(op, out)
    return out


def from_rule(r):
    items = r.get("customizationItems") or {}
    queries = [{"query": q.get("query"), "queryType": q.get("queryType"), "matchType": q.get("matchType")}
               for q in r.get("queries") or []]
    base = {"id": r.get("id"), "name": r.get("name"), "enabled": r.get("enabled"), "queries": queries,
            "startedAt": r.get("startedAt"), "endedAt": r.get("endedAt"), "audiences": r.get("audiences") or []}
    if "redirect" in items:
        red = items["redirect"] or {}
        return {**base, "type": "redirect", "name": base["name"] or red.get("ruleName"), "url": red.get("url"),
                "queries": [{**q, "matchType": q.get("matchType") or red.get("matchType")} for q in queries]}
    if r.get("ruleType") == "facet":
        def facets(key):
            v = items.get(key) or []
            return json.loads(v) if isinstance(v, str) else v  # stored as a JSON string in some responses
        return {**base, "type": "facet", "always_included": facets("always_included_facets"),
                "excluded": facets("excluded_facets")}
    attrs = []
    for a in items.get("attribute_boost_bury") or []:
        rule = a.get("rule") or {}
        for name, values in attr_operands(rule, []):
            attrs.append({"type": a.get("type") or "boost", "name": name, "values": values,
                          "strength": rule.get("strength")})
    ids = lambda key: [str(p.get("product_id")) for p in items.get(key) or [] if p.get("product_id") is not None]
    return {**base, "type": "ranking", "boost_product_ids": ids("boost_top_products"),
            "bury_product_ids": ids("buried_products"), "add_to_recall": ids("add_to_recall"),
            "product_slots": [{"product_id": str(p.get("product_id")), "slot": p.get("slot")}
                              for p in items.get("product_slots") or []],
            "attribute_boost_bury": attrs}


def load_change(path):
    doc = unwrap(load(path))
    if isinstance(doc, dict) and isinstance(doc.get("data"), dict) and "customizationItems" in doc["data"]:
        doc = doc["data"]
    if not isinstance(doc, dict):
        fail(f"{path}: expected a JSON object describing one change")
    if "customizationItems" in doc:
        c = from_rule(doc)
    elif "sourceSynonym" in doc:
        c = {"type": "synonym", "id": doc.get("id"), "source": doc.get("sourceSynonym"),
             "targets": [t.strip() for t in str(doc.get("targetSynonym") or "").split(",") if t.strip()],
             "two_way": bool(doc.get("groupSynonym")), "enabled": doc.get("enabled"),
             "queries": [{"query": doc.get("sourceSynonym"), "queryType": "sitesearch", "matchType": "EXACT_MATCH"}]}
    elif doc.get("type") in ("ranking", "synonym", "redirect", "facet", "media"):
        c = dict(doc)
        if c["type"] == "synonym" and not c.get("queries"):
            c["queries"] = [{"query": c.get("source"), "queryType": "sitesearch", "matchType": "EXACT_MATCH"}]
    else:
        fail(f"{path}: not a ranking rule, redirect or synonym record, and no 'type' "
             "(ranking, synonym, redirect, facet or media); see references/change-format.md")
    for key in ("queries", "boost_product_ids", "bury_product_ids", "add_to_recall", "product_slots",
                "attribute_boost_bury", "targets", "slots"):
        c.setdefault(key, [])
    c["boost_product_ids"] = [str(x) for x in c["boost_product_ids"]]
    c["bury_product_ids"] = [str(x) for x in c["bury_product_ids"]]
    c["add_to_recall"] = [str(x) for x in c["add_to_recall"]]
    return c


# ---------------------------------------------------------------------------------------------
# Grids

def grid_docs(path):
    doc = load(path)
    if isinstance(doc, list):
        return doc, len(doc), []
    d = doc.get("result", doc) if isinstance(doc, dict) else {}
    d = d.get("data", d)
    resp = (d or {}).get("response") or {}
    if "docs" not in resp:
        fail(f"{path}: couldn't find data.response.docs; is this a product grid response?")
    docs = resp.get("docs") or []
    products = [x for x in docs if x.get("docType", "product") == "product"]
    content = [x for x in docs if x.get("docType") == "content"]
    return products, int(resp.get("numFound") or len(products)), content


def field_values(doc, name):
    v = doc.get(name)
    if v is None:
        return None
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def value_matches(values, wanted):
    for w in wanted:
        m = re.fullmatch(r"\[\s*(\*|-?[\d.]+)\s+TO\s+(\*|-?[\d.]+)\s*\]", w.strip(), re.I)
        for v in values:
            if m:
                try:
                    x = float(v)
                except ValueError:
                    continue
                lo, hi = m.groups()
                if (lo == "*" or x >= float(lo)) and (hi == "*" or x <= float(hi)):
                    return True
            elif norm(v) == norm(w):
                return True
    return False


def simulate(change, docs):
    """The strongest version of a ranking rule: pins, then boosts, normal, attribute buries, buries."""
    boost = {p: i for i, p in enumerate(change["boost_product_ids"])}
    bury = set(change["bury_product_ids"])
    have = {str(d.get("pid")) for d in docs}
    docs = list(docs) + [{"pid": p, "title": None, "brand": None, "_placeholder": True}
                         for p in change["add_to_recall"] if p not in have]
    keyed = []
    for rank, d in enumerate(docs, 1):
        pid = str(d.get("pid"))
        why = []
        if pid in bury:
            tier = 4; why.append("buried")
        elif pid in boost:
            tier = 0; why.append("boosted")
        else:
            tier = 2
            for a in change["attribute_boost_bury"]:
                vals = field_values(d, a.get("name"))
                if vals and value_matches(vals, a.get("values") or []):
                    if a.get("type") == "bury":
                        tier = max(tier, 3); why.append(f"{a.get('name')} buried")
                    elif tier != 3:
                        tier = 1; why.append(f"{a.get('name')} boosted")
        keyed.append((tier, boost.get(pid, 0) if tier == 0 else rank, d, why))
    order = sorted(keyed, key=lambda k: (k[0], k[1]))
    out = [(d, why) for _, _, d, why in order]
    for s in sorted(change["product_slots"], key=lambda s: s.get("slot") or 0):
        pid = str(s.get("product_id"))
        hit = next((x for x in out if str(x[0].get("pid")) == pid), None)
        if hit:
            out.remove(hit)
        else:
            hit = ({"pid": pid, "title": None, "brand": None, "_placeholder": True}, [])
        out.insert(max(0, int(s.get("slot") or 1) - 1), (hit[0], hit[1] + [f"pinned to slot {s.get('slot')}"]))
    return out


def brand_mix(docs, n):
    c = collections.Counter((d.get("brand") or "?").strip() for d in docs[:n])
    return [{"brand": b, "products": k} for b, k in c.most_common()]


def out_of_stock(doc):
    for f in RULES["stock_fields"]:
        v = doc.get(f)
        if v is not None and norm(v) in RULES["out_of_stock_values"]:
            return f"{f}={v}"
    return None


# ---------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--change", required=True)
    for flag in ("grid", "grid-after", "target-grid", "queries", "categories", "products", "existing",
                 "experiments", "synonyms"):
        ap.add_argument("--" + flag, action="append", default=[])
    ap.add_argument("--now", help="ISO time to judge schedules against (default: current UTC time)")
    ap.add_argument("--page-size", type=int, default=RULES["page_size"],
                    help="products on the first page (default: references/rules.json)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()

    now = ts(a.now) if a.now else datetime.now(timezone.utc)
    n = a.page_size
    change = load_change(a.change)
    kind = change["type"]
    findings, not_checked = [], []

    def add(sev, check, issue, fix, query=None, evidence=None):
        findings.append({"severity": sev, "check": check, "query": query, "issue": issue,
                         "evidence": evidence, "fix": fix})

    queries = [q for q in change["queries"] if norm(q.get("query"))]
    qnames = [norm(q.get("query")) for q in queries]

    # ---- scope
    if not queries and kind != "facet":
        add("blocker", "scope", "The change targets no query or category.", "Add the query or category it's for.")
    for q in queries:
        qt, mt, qn = norm(q.get("queryType")), norm(q.get("matchType")), norm(q.get("query"))
        if qn == "*" or "global" in qt:
            add("warning", "scope", f"Applies to every {'category' if 'category' in qt else 'search'} (global).",
                "Confirm it should apply everywhere; scope it to the queries or categories it's for if not.", qn)
        elif "phrase" in mt and len(qn.split()) <= RULES["broad_query_max_words"]:
            add("warning", "scope", f"Phrase match on the one-word query '{qn}' also fires on every longer search containing it.",
                "Use exact match unless the longer searches should get it too.", qn)

    # ---- schedule
    start, end = ts(change.get("startedAt")), ts(change.get("endedAt"))
    if end and end <= now:
        add("blocker", "schedule", f"The end date {end:%Y-%m-%d %H:%M} UTC has already passed, so it would never apply.",
            "Set a future end date, or don't make the change.")
    if start and end and start >= end:
        add("blocker", "schedule", "The start date isn't before the end date.", "Fix the dates.")
    name = norm(change.get("name"))
    promo = change.get("promotional")
    if promo is None:
        promo = any(w in name for w in RULES["promo_words"])
    if promo and not end and kind in ("ranking", "redirect", "media"):
        add("warning", "schedule", "A promotional change with no end date stays live after the promotion.",
            "Set an end date.")

    # ---- ranking rule mechanics
    if kind == "ranking":
        both = sorted(set(change["boost_product_ids"]) & set(change["bury_product_ids"]))
        if both:
            add("blocker", "contradiction", f"Products both boosted and buried: {', '.join(both)}.",
                "Keep each product in one list.")
        slots = collections.Counter(s.get("slot") for s in change["product_slots"])
        dup = sorted(s for s, k in slots.items() if k > 1)
        if dup:
            add("blocker", "pins", f"More than one product pinned to slot {', '.join(map(str, dup))}.",
                "Give each pinned product its own slot.")
        deep = sorted(s.get("slot") for s in change["product_slots"] if (s.get("slot") or 0) > n)
        if deep:
            add("nitpick", "pins", f"Pinned below the first page (slot {', '.join(map(str, deep))} of {n}).",
                "Pin within the first page, or drop the pin.")
        for at in change["attribute_boost_bury"]:
            if (at.get("strength") or 0) >= RULES["hard_sort_strength"]:
                add("nitpick", "strength", f"{at.get('type')} on {at.get('name')} at strength {at.get('strength')} "
                    "behaves like a hard sort.", "Start at 30-50 and raise it if the effect is too small.")

    # ---- facet and media rules
    if kind == "facet":
        clash = sorted(set(map(str, change.get("always_included") or [])) & set(map(str, change.get("excluded") or [])))
        if clash:
            add("blocker", "facets", f"Facets both always shown and excluded: {', '.join(clash)}.",
                "Keep each facet in one list.")
    if kind == "media":
        slots = [s for s in change.get("slots") or []]
        dup = sorted(s for s, k in collections.Counter(slots).items() if k > 1)
        if dup:
            add("blocker", "media", f"More than one banner in grid slot {', '.join(map(str, dup))}.", "Use one banner per slot.")
        img = str(change.get("image_url") or "")
        if img.lower().startswith("http://"):
            add("warning", "media", "The banner image uses http, not https; browsers may block it.", "Use an https URL.")

    # ---- affected queries and revenue at stake
    rows = []
    for p in a.queries:
        rows += [dict(r, _kind="query", _name=norm(r.get("query"))) for r in records(p)]
    for p in a.categories:
        rows += [dict(r, _kind="category", _name=norm(r.get("cat_id") or r.get("category")),
                      _alt=norm(r.get("category") or r.get("cat_name"))) for r in records(p)]

    def touches(row, q):
        qn, qt, mt = norm(q.get("query")), norm(q.get("queryType")), norm(q.get("matchType"))
        if qn == "*":
            # "global" covers searches and categories; "sitesearch_global" only searches.
            return qt in ("", "*", "global") or ("category" in qt) == (row["_kind"] == "category")
        if ("category" in qt) != (row["_kind"] == "category"):
            return False
        if row["_kind"] == "category":
            return qn in (row["_name"], row.get("_alt"))
        if "phrase" in mt or (kind == "redirect" and "exact" not in mt and mt):
            return re.search(r"(^| )" + re.escape(qn) + r"( |$)", row["_name"]) is not None
        return row["_name"] == qn

    affected = {}
    for r in rows:
        if any(touches(r, q) for q in queries):
            affected[(r["_kind"], r["_name"])] = {
                "kind": r["_kind"], "key": r["_name"], "name": r.get("query") or r.get("category") or r.get("cat_id"),
                "visits": int(money(r.get("visits"))), "revenue": round(money(r.get("revenue")), 2),
                "conversion_rate": r.get("conversion_rate")}
    affected = sorted(affected.values(), key=lambda r: (-r["revenue"], -r["visits"]))
    if not rows:
        not_checked.append("Traffic and revenue: no query or category performance table was given.")
    elif not affected and kind != "facet":
        add("nitpick", "traffic", "No traffic found for the targeted queries in the performance table.",
            "Check the query spelling; a change on a query nobody searches does nothing.")

    # ---- product revenue for "top seller"
    prows = []
    for p in a.products:
        prows += records(p)
    prows.sort(key=lambda r: -money(r.get("revenue")))
    seller = {str(r.get("prod_id") or r.get("pid")): (i, money(r.get("revenue")))
              for i, r in enumerate(prows, 1)}

    # ---- previews (ranking and media rules, and anything with a real after grid)
    grids = dict(pair(g, "--grid") for g in a.grid)
    after_grids = dict(pair(g, "--grid-after") for g in a.grid_after)
    previews = []
    for qn, path in grids.items():
        docs, found, content = grid_docs(path)
        before = docs[:n]
        if qn in after_grids:
            after_docs, _, after_content = grid_docs(after_grids[qn])
            after = [(d, []) for d in after_docs]
            simulated = False
        elif kind == "ranking":
            after, simulated, after_content = simulate(change, docs), True, content
        else:
            continue
        if found == 0 and kind != "synonym":
            add("warning", "zero results", f"'{qn}' returns no results, so a ranking change does nothing.",
                "Fix recall first (a synonym; see discovery-zero-results-triage).", qn)
        top_after = [d for d, _ in after[:n]]
        before_ids = [str(d.get("pid")) for d in before]
        after_ids = [str(d.get("pid")) for d in top_after]
        old_rank = {str(d.get("pid")): i for i, d in enumerate(docs, 1)}
        pushed = [d for d in before if str(d.get("pid")) not in after_ids]
        hurt = [(d, seller[str(d.get("pid"))]) for d in pushed
                if str(d.get("pid")) in seller and seller[str(d.get("pid"))][0] <= RULES["top_seller_rank"]]
        if hurt:
            add("warning", "top sellers", f"{len(hurt)} top-selling product(s) pushed off page one for '{qn}'.",
                "Lower the strength, or pin the top sellers you want to keep.", qn,
                [{"pid": str(d.get("pid")), "title": d.get("title"), "revenue_rank": r, "revenue": round(v, 2)}
                 for d, (r, v) in hurt])
        if kind == "ranking":
            moved = {**{p: "boosted" for p in change["boost_product_ids"]},
                     **{str(s.get("product_id")): "pinned" for s in change["product_slots"]},
                     **{p: "added to recall" for p in change["add_to_recall"]}}
            qwords = words(qn) | {w for r in affected if r["key"] == qn for w in words(r["name"])}
            for pid, how in moved.items():
                doc = next((d for d in docs if str(d.get("pid")) == pid), None)
                if doc is None and how != "added to recall":
                    add("warning", "not in results", f"Product {pid} is {how} but isn't in the results for '{qn}'.",
                        "Check the product ID, or add it to recall too.", qn)
                elif doc is not None and qwords and doc.get("title") and not overlaps(words(doc.get("title")), qwords):
                    add("warning", "relevance", f"{how.capitalize()} product '{doc.get('title')}' doesn't look like a match for '{qn}'.",
                        "Check it belongs on this page.", qn, {"pid": pid})
            for at in change["attribute_boost_bury"] if docs else []:
                field = at.get("name")
                vals = [field_values(d, field) for d in docs]
                if not any(v is not None for v in vals):
                    not_checked.append(f"'{qn}': {field} isn't in the saved grid, so its {at.get('type')} wasn't simulated "
                                       f"(add {field} to fl).")
                elif not any(v and value_matches(v, at.get("values") or []) for v in vals):
                    add("warning", "attribute values", f"No product in the results for '{qn}' has {field} = "
                        f"{', '.join(at.get('values') or [])}.", "Copy the exact facet value (they can have trailing spaces).", qn)
        for d in top_after:
            if str(d.get("pid")) not in before_ids:
                oos = out_of_stock(d)
                if oos:
                    add("warning", "stock", f"Out-of-stock product '{d.get('title')}' moves onto page one for '{qn}'.",
                        "Leave it out of the boost or pin.", qn, {"pid": str(d.get("pid")), "stock": oos})
        mix_before, mix_after = brand_mix(before, n), brand_mix(top_after, n)
        if mix_after and top_after:
            share = mix_after[0]["products"] / len(top_after)
            share_before = (mix_before[0]["products"] / len(before)) if before else 0
            if share >= RULES["brand_share_warning"] and share > share_before:
                add("warning", "brand mix", f"{mix_after[0]['brand']} would hold {share:.0%} of page one for '{qn}'.",
                    "Lower the boost strength so other brands stay visible.", qn)
        if len(after_content) < len(content):
            add("nitpick", "banners", f"{len(content) - len(after_content)} in-grid banner(s) disappear for '{qn}'.",
                "Confirm that's intended.", qn)
        previews.append({
            "query": qn, "results": found, "simulated": simulated,
            "before": [{"rank": i, "pid": str(d.get("pid")), "title": d.get("title"), "brand": d.get("brand")}
                       for i, d in enumerate(before, 1)],
            "after": [{"rank": i, "was": old_rank.get(str(d.get("pid"))), "pid": str(d.get("pid")),
                       "title": d.get("title"), "brand": d.get("brand"), "why": why}
                      for i, (d, why) in enumerate(after[:n], 1)],
            "pushed_off": [{"pid": str(d.get("pid")), "title": d.get("title"), "was": old_rank.get(str(d.get("pid")))}
                           for d in pushed],
            "brand_mix_before": mix_before, "brand_mix_after": mix_after})
    if kind == "ranking":
        previewed = {p["query"] for p in previews}
        for r in affected[:RULES["top_queries"]]:
            if r["key"] not in previewed:
                not_checked.append(f"No grid preview for {r['kind']} '{r['name']}' (revenue {r['revenue']:.2f}).")
        if not previews and not affected:
            not_checked.append("No grid preview was given for any query.")

    # ---- synonyms
    if kind == "synonym":
        src = norm(change.get("source"))
        targets = [norm(t) for t in change["targets"]]
        if not targets or targets == [src]:
            add("nitpick", "no-op", "The synonym maps the term to itself.", "Drop it.", src)
        tgrids = dict(pair(g, "--target-grid") for g in a.target_grid)
        src_docs, src_found, _ = grid_docs(grids[src]) if src in grids else ([], None, [])
        # What the source search already finds: words in at least two of its titles (or any, if few).
        title_words = collections.Counter(w for d in src_docs[:RULES["synonym_sample"]] for w in words(d.get("title")))
        vocab = {w for w, k in title_words.items() if k >= 2} or set(title_words)
        for t in [t for t in targets if t != src]:
            if t not in tgrids:
                not_checked.append(f"Synonym target '{t}': no grid given.")
                continue
            tdocs, tfound, _ = grid_docs(tgrids[t])
            if tfound == 0:
                if src_found:
                    add("warning", "direction", f"'{t}' returns nothing but '{src}' does: the synonym adds nothing "
                        "and may be the wrong way round.", f"Make it '{t}' -> '{src}' instead.", src)
                else:
                    add("warning", "no results", f"'{t}' returns no results, so the synonym adds nothing.",
                        "Use a term the catalog contains.", src)
                continue
            sample = [d for d in tdocs[:RULES["synonym_sample"]] if d.get("title")]
            if not vocab:
                not_checked.append(f"Synonym target '{t}': '{src}' has no results of its own to compare with; "
                                   "look at the first results for the target by eye.")
            elif sample:
                overlap = sum(1 for d in sample if overlaps(words(d.get("title")), vocab)) / len(sample)
                if overlap < RULES["synonym_overlap_warning"]:
                    add("warning", "broadening", f"Only {overlap:.0%} of the first results for '{t}' look like what "
                        f"'{src}' finds today, so the synonym would mix in different products.",
                        "Check them in the grid; use a narrower target or a one-way synonym.", src,
                        [d.get("title") for d in sample[:5]])
        for p in a.synonyms:
            for s in records(p):
                if (s.get("enabled") is not False and norm(s.get("sourceSynonym")) == src
                        and str(s.get("id")) != str(change.get("id"))):
                    add("warning", "duplicate", f"An enabled synonym for '{src}' already exists (id {s.get('id')}).",
                        "Edit that one instead of adding another.", src)

    # ---- redirects
    if kind == "redirect":
        url = str(change.get("url") or "").strip()
        low = url.lower()
        if not url:
            add("blocker", "url", "The redirect has no destination URL.", "Add the URL.")
        else:
            if re.search(r"\s", url):
                add("blocker", "url", "The URL contains spaces.", "Remove or encode them.")
            nonweb = re.match(r"^(javascript|data|mailto|file|tel):", low) is not None
            if nonweb:
                add("blocker", "url", "The URL isn't a web page.", "Use an https page URL.")
            parts = urlsplit(low if "://" in low else "https://" + low.lstrip("/"))
            rest = parts.path + "?" + parts.query  # host names are left alone: a .test domain isn't a placeholder
            if any(w in rest for w in RULES["placeholder_url_words"]) or "example.com" in parts.netloc:
                add("blocker", "url", f"The URL looks unfinished: {url}.", "Use the real page URL.")
            if low.startswith("http://"):
                add("warning", "url", "The URL uses http, not https.", "Use https.")
            elif not nonweb and not low.startswith(("https://", "/")):
                add("warning", "url", "The URL has no scheme, so it relies on the site to add one.",
                    "Write it in full with https://.")
        for r in affected:
            if r["revenue"] >= RULES["redirect_min_revenue"]:
                exact = norm(r["name"]) in qnames
                add("warning", "hijack" if not exact else "revenue",
                    (f"'{r['name']}' earns {r['revenue']:.2f} from product results; the redirect would take those shoppers away."
                     if exact else f"The phrase match also catches '{r['name']}', which earns {r['revenue']:.2f}."),
                    "Use exact match, or don't redirect a search that sells products.", r["name"])

    # ---- existing rules on the same queries
    for p in a.existing:
        for r in records(p):
            if str(r.get("id")) == str(change.get("id")) or r.get("enabled") is False:
                continue
            if norm(r.get("durationTag")) == "expired":
                continue
            rq = {norm(q.get("query")) for q in r.get("queries") or []}
            shared = sorted(rq & set(qnames))
            if not shared:
                continue
            rs, re_ = ts(r.get("startedAt")), ts(r.get("endedAt"))
            if (re_ and start and re_ <= start) or (end and rs and rs >= end):
                continue
            rtype = norm(r.get("ruleType"))
            label = f"{rtype or 'rule'} {r.get('id')}"
            if r.get("isAbTestLive"):
                add("blocker", "a/b test", f"Enabled {label} on '{', '.join(shared)}' is in a running A/B test.",
                    "Wait for the test to end (discovery-experiment-readout); changes are blocked or muddy it.", shared[0])
            elif kind == "redirect" and rtype != "redirect":
                add("nitpick", "conflict", f"The redirect would hide enabled {label} on '{', '.join(shared)}'.",
                    "Retire that rule if the redirect goes live.", shared[0])
            elif kind != "redirect" and rtype == "redirect":
                add("warning", "conflict", f"Enabled {label} sends '{', '.join(shared)}' to another page, so shoppers "
                    "never see this change there.", "Check the redirect is still wanted (discovery-redirect-audit).", shared[0])
            elif rtype in SAME_TYPE.get(kind, ()):
                add("warning", "conflict", f"Enabled {label} already targets '{', '.join(shared)}' and would stack with this change "
                    "(it may be audience-targeted; rule lists hide audiences).",
                    "Edit that rule instead, or check with get_ranking_rule that they don't fight.", shared[0])

    # ---- running experiments
    for p in a.experiments:
        for e in records(p):
            if norm(e.get("status") or e.get("experimentStatus") or "running") != "running":
                continue
            text = norm(json.dumps(e))
            hit = [q for q in qnames if q != "*" and f'"{q}"' in text]
            rid = str(change.get("id") or "")
            if len(rid) >= 5 and rid in re.findall(r"\d+", text):
                hit.append(f"rule {change.get('id')}")
            if hit:
                add("blocker", "a/b test", f"Running experiment '{e.get('name')}' covers {', '.join(hit)}.",
                    "Wait for it to end; writes are blocked during a running test and the change would muddy it.")
            else:
                add("nitpick", "a/b test", f"Experiment '{e.get('name')}' is running on this account.",
                    "Confirm it doesn't cover these queries.")

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY}
    verdict = "NO-GO" if counts["blocker"] else "GO WITH CAUTION" if counts["warning"] or not_checked else "GO"
    findings.sort(key=lambda f: SEVERITY.index(f["severity"]))
    result = {"ok": True, "verdict": verdict, "counts": counts, "page_size": n,
              "change": {k: change.get(k) for k in ("type", "id", "name", "queries", "startedAt", "endedAt", "url",
                                                    "source", "targets", "two_way") if change.get(k) not in (None, [])},
              "affected": {"rows": affected[:RULES["top_queries"]], "count": len(affected),
                           "revenue": round(sum(r["revenue"] for r in affected), 2),
                           "visits": sum(r["visits"] for r in affected)},
              "previews": previews, "findings": findings, "not_checked": not_checked}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
