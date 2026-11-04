#!/usr/bin/env python3
"""Explain where one product ranks for a Discovery search or category, or why it's missing.

Usage:
  python3 visibility_explain.py --pid 12345 --grid page1.json [--grid page2.json ...]
         [--match-check fq_rules_on.json] [--rules-off fq_rules_off.json] [--lookup product_id.json]
         [--catalog catalog_product.json] [--query 'dress' | --query-file query.txt] [--page-size 24] [--out result.json]

Every input is a saved search_discovery_product_grid_insights (or search_discovery_catalog_products) result:
  --grid         the query's (or category's) normal grid, rules on. Repeat for more pages (start=0, 200, ...).
  --match-check  the same query with fq pid:"<pid>", rules on: does the product match at all?
  --rules-off    the same query with fq pid:"<pid>" and every ranking rule ID in disabled_customization_ids.
  --lookup       search_by="product_id" for the pid: is it in the search index?
  --catalog      search_discovery_catalog_products with product_id: availability, categories, title, description.
  --query-file   a text file holding the search terms exactly as typed (one trailing newline is stripped); use it
                 for any query that isn't only letters, digits, spaces and hyphens. Give --query or --query-file.

Prints JSON with the product's status (ranked, matched_not_fetched, excluded_by_rule, not_matching,
not_in_index or unknown), its position, the causes found (recall, merchandising, ranking, data), each with
evidence, and what couldn't be checked. Thresholds are in references/rules.json. Debug URLs that carry
keys (feUrl, sqApiUrl) are never output. Standard library only; no network access.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
TITLE_FIELDS = ("product_name", "title")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error, safe to repeat: an error about the account can list every account the user can
    access, so it's never echoed; anything else is cut to 200 characters."""
    text = str(err or "no error text")
    if "account" in text.lower():  # these errors can list every account the user can access
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def load(path):
    """The data object of a saved grid or catalog result, after checking for errors returned as data."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    data = doc.get("data", doc) if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        fail(f"{path}: not a product grid or catalog product result.")
    return data


def products(grid):
    """Product rows only: banner rows (docType content, no pid) aren't products."""
    docs = (grid.get("response") or {}).get("docs") or []
    if not isinstance(docs, list):
        return []
    return [d for d in docs if isinstance(d, dict) and d.get("docType") != "content" and d.get("pid") not in (None, "")]


def num_found(grid):
    return (grid.get("response") or {}).get("numFound")


def explain(grid, pid):
    """The summary entry (the one with totalNormalizedScore) and the matched fields for one product."""
    entries = ((grid.get("debug") or {}).get("explain.structured") or {}).get(str(pid)) or []
    summary = next((e for e in reversed(entries) if isinstance(e, dict) and "totalNormalizedScore" in e), {})
    fields = sorted({e["field"] for e in entries if isinstance(e, dict) and e.get("field") and e.get("match")})
    return summary, fields


def merch_effects(summary):
    """Rule effects on a product, e.g. {"hardBoost": [...]} -> {"boost": n, "bury": n, "pin": n}."""
    out = {"boost": 0, "bury": 0, "pin": 0}
    for k, v in (summary.get("merchandisingRulesApplied") or {}).items():
        n = len(v) if isinstance(v, list) else 1
        kind = "bury" if "bury" in k.lower() else "pin" if ("pin" in k.lower() or "slot" in k.lower()) else "boost"
        out[kind] += n
    return out


def rules_in_play(grid):
    """Ranking rules from customizations.explain: their type, the products they push up, and exclusions."""
    out = []
    for c in (grid.get("debug") or {}).get("customizations.explain") or []:
        if c.get("ruleType") not in ("ranking", "redirect"):
            continue
        rule = {"id": str(c.get("id")), "type": c.get("ruleType"),
                "queries": [q.get("query") for q in c.get("queries") or []], "boosted_pids": [], "exclusions": []}
        for item in c.get("customizationItems") or []:
            try:
                value = json.loads(item.get("value") or "null")
            except ValueError:
                value = None
            if item.get("type") in ("boost_top_products", "slot_products", "pin_products") and isinstance(value, list):
                rule["boosted_pids"] += [str(p.get("product_id")) for p in value if isinstance(p, dict)]
            if item.get("type") == "explicit_filters" and isinstance(value, list):
                for f in value:
                    if f.get("filter_type") == "exclude":
                        for op in ((f.get("rule") or {}).get("operands") or []):
                            rule["exclusions"].append({"attribute": op.get("name"), "values": op.get("operands") or []})
        out.append(rule)
    return out


def rewrites(grid):
    found = {k: grid.get(k) for k in ("autoCorrectQuery", "relaxedQuery") if grid.get(k)}
    if grid.get("did_you_mean"):
        found["did_you_mean"] = grid["did_you_mean"]
    redirect = grid.get("keywordRedirect")
    if redirect:
        found["redirect"] = {k: v for k, v in redirect.items() if "url" in k.lower() or "query" in k.lower()}
    return found


def score(value):
    """A number from a score field, or None when it's missing or not a number."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def median(values):
    values = [v for v in (score(x) for x in values) if v is not None]
    return statistics.median(values) if values else None


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) > 2}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", required=True, help="the product ID to explain")
    ap.add_argument("--grid", action="append", default=[], help="saved grid page for the query or category, rules on")
    ap.add_argument("--match-check", help="saved grid for the query with fq pid:\"<pid>\", rules on")
    ap.add_argument("--rules-off", help="saved grid for the query with fq pid:\"<pid>\" and ranking rules disabled")
    ap.add_argument("--lookup", help="saved grid with search_by=product_id for the pid")
    ap.add_argument("--catalog", help="saved search_discovery_catalog_products result for the pid")
    ap.add_argument("--query", help="the search terms (for the data check), only if letters, digits, spaces and hyphens")
    ap.add_argument("--query-file", help="a text file holding the search terms exactly as typed (for the data check)")
    ap.add_argument("--page-size", type=int, default=RULES["page_size"], help="products on page one (default: rules)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if a.query is not None and a.query_file is not None:
        fail("Give at most one of --query and --query-file.")
    if a.query_file is not None:
        try:
            with open(a.query_file, encoding="utf-8", newline="") as f:
                a.query = f.read()
        except (OSError, UnicodeDecodeError) as e:
            fail(f"{a.query_file}: can't read the query ({e}).")
        if a.query.endswith("\r\n"):
            a.query = a.query[:-2]
        elif a.query.endswith("\n"):
            a.query = a.query[:-1]
    pid = str(a.pid).strip()
    if not pid:
        fail("--pid is empty.")

    pages = sorted((load(p) for p in a.grid), key=lambda g: (g.get("response") or {}).get("start") or 0)
    ranked, seen = [], set()
    for g in pages:
        for d in products(g):
            if d["pid"] not in seen:
                seen.add(d["pid"])
                ranked.append((d, g))
    total = num_found(pages[0]) if pages else None
    causes, not_checked = [], []

    def cause(kind, finding, evidence=None, fix=None):
        causes.append({"kind": kind, "finding": finding, "evidence": evidence, "fix": fix})

    position = next((i for i, (d, _) in enumerate(ranked, 1) if d["pid"] == pid), None)
    rules = rules_in_play(pages[0]) if pages else []
    target = None
    status = "unknown"

    if position:
        status = "ranked"
        doc, grid = ranked[position - 1]
        target, fields = explain(grid, pid)
        target_fx = merch_effects(target)
        above = ranked[max(0, position - 1 - RULES["compare_window"]):position - 1]
        above_summ = [explain(g, d["pid"])[0] for d, g in above]
        boosted_above = [d["pid"] for (d, g), s in zip(above, above_summ) if merch_effects(s)["boost"] + merch_effects(s)["pin"]]
        if target_fx["bury"]:
            cause("merchandising", "A rule buries this product.", target.get("merchandisingRulesApplied"),
                  "Find the bury rule (rules below) and narrow or remove it; check it with discovery-change-qa first.")
        if boosted_above:
            cause("merchandising", f"{len(boosted_above)} product(s) above it are boosted or pinned by a rule.",
                  {"pids": boosted_above[:10], "rules": [r["id"] for r in rules if set(r["boosted_pids"]) & set(boosted_above)]},
                  "If this product should be above them, add it to the rule's boosted products (discovery-change-qa first).")
        rel, perf = score(target.get("relevance")), score(target.get("performance"))
        med_rel = median([s.get("relevance") for s in above_summ])
        med_perf = median([s.get("performance") for s in above_summ])
        if rel is not None and med_rel and rel < RULES["relevance_gap_ratio"] * med_rel:
            title_hit = any(any(t in f.lower() for t in TITLE_FIELDS) for f in fields)
            cause("data" if not title_hit else "ranking",
                  f"Weaker text match than the products above it (relevance {rel:.1f} against a median of {med_rel:.1f}).",
                  {"matched_fields": fields, "title_matches": title_hit},
                  "Put the shopper's words in the title or category (product-data-enhancer)" if not title_hit
                  else "The title matches; check the description, attributes and category for the query's words.")
        if perf is not None and med_perf and perf < RULES["performance_gap_ratio"] * med_perf:
            cause("ranking", f"Lower performance score than the products above it ({perf:.1f} against a median of "
                  f"{med_perf:.1f}): fewer views, add-to-carts, orders or revenue.",
                  None, "Expected for new or slow products. To lift it anyway, boost it with a rule (discovery-change-qa first).")
        if position > a.page_size and not causes:
            cause("ranking", "It isn't held back by a rule or a weak match: the products above simply score higher.",
                  {"score": target.get("totalNormalizedScore")}, "Boost it with a rule if it matters (discovery-change-qa first).")
    elif a.match_check:
        mc = load(a.match_check)
        if any(d["pid"] == pid for d in products(mc)):
            status = "matched_not_fetched"
            not_checked.append(f"It matches, but it's deeper than the {len(ranked)} products fetched; fetch more pages "
                               f"(rows up to {RULES['max_rows_per_call']}, then start in steps of {RULES['max_rows_per_call']}, up to "
                               f"{RULES['max_results_paged']} results) to find its position.")
        elif a.rules_off:
            ro = load(a.rules_off)
            if any(d["pid"] == pid for d in products(ro)):
                status = "excluded_by_rule"
                excl = [{"rule": r["id"], **x} for r in rules for x in r["exclusions"]]
                cause("merchandising", "A ranking rule removes it: it matches with the rules switched off, not with them on.",
                      {"exclusions": excl} if excl else None,
                      "Narrow the rule's exclusion, or accept it. Disable one rule at a time to find which, and check "
                      "any change with discovery-change-qa.")
            else:
                status = "not_matching"
        else:
            status = "not_matching"
            not_checked.append("Rules weren't ruled out: fetch the same check with every ranking rule disabled (--rules-off).")
    else:
        not_checked.append("It isn't in the pages fetched, and no --match-check was given, so it can't be told whether "
                           "it matches deeper down or not at all.")

    if status == "not_matching":
        if a.lookup:
            lk = load(a.lookup)
            if not any(d["pid"] == pid for d in products(lk)):
                status = "not_in_index"
                cause("recall", "The product isn't in the search index at all.", None,
                      "Check it's in the catalog feed and not filtered out of indexing (data-feed-health).")
            else:
                cause("recall", "The product is in the index but doesn't match this query.", None,
                      "Add the shopper's words to its title, category or attributes (product-data-enhancer), or add a "
                      "synonym; a rule can also add it to recall (discovery-change-qa first).")
        else:
            cause("recall", "The product doesn't match this query (or isn't in the index).", None,
                  "Check the index with search_by=product_id (--lookup), then the product's text.")

    cat = load(a.catalog) if a.catalog else None
    if cat:
        attrs = cat.get("attributes") or {}
        if attrs.get("availability") is False:
            cause("recall", "The catalog marks it unavailable.", {"availability": False},
                  "Out-of-stock products usually drop or vanish; fix the stock data in the feed.")
        cats = [c.get("id") for path in attrs.get("category_paths") or [] for c in path if isinstance(c, dict)]
        hit = [{"rule": r["id"], "attribute": x["attribute"], "values": sorted(set(map(str, x["values"])) & set(map(str, cats)))}
               for r in rules for x in r["exclusions"] if x["attribute"] in ("category", "category_id")
               and set(map(str, x["values"])) & set(map(str, cats))]
        if hit:
            cause("merchandising", "A rule excludes one of its categories.", {"exclusions": hit},
                  "Narrow the exclusion if this product belongs here (discovery-change-qa first).")
        if a.query:
            text = words(attrs.get("title")) | words(attrs.get("description"))
            text |= {w for path in attrs.get("category_paths") or [] for c in path if isinstance(c, dict) for w in words(c.get("name"))}
            missing = sorted(words(a.query) - text)
            if missing:
                cause("data", f"Its title, description and categories don't contain: {', '.join(missing)}.",
                      None, "Add the shopper's words to the product text (product-data-enhancer), or add a synonym.")
    else:
        not_checked.append("Catalog record not given (--catalog): availability and category exclusions not checked.")

    rw = rewrites(pages[0]) if pages else {}
    if rw.get("redirect"):
        cause("merchandising", "The search redirects to another page, so shoppers never see this grid.", rw["redirect"],
              "Check the redirect is wanted (discovery-redirect-audit).")
    if rw.get("autoCorrectQuery") or rw.get("relaxedQuery"):
        cause("recall", "The query was rewritten before searching.", {k: rw[k] for k in ("autoCorrectQuery", "relaxedQuery") if k in rw},
              "If the rewrite is wrong, add a synonym for the original wording.")

    result = {"ok": True, "pid": pid, "query": a.query, "status": status, "position": position, "on_page_one": bool(position and position <= a.page_size),
              "results_total": total, "products_fetched": len(ranked),
              "scores": {k: target.get(k) for k in ("totalNormalizedScore", "relevance", "performance", "keyword_score", "vector_score")
                         if target and k in target},
              "causes": causes, "rules_in_play": rules, "rewrites": {k: v for k, v in rw.items() if k != "redirect"},
              "not_checked": not_checked}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
