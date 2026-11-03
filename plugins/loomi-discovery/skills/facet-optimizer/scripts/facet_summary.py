#!/usr/bin/env python3
"""Summarise and flag the facets in saved Loomi Connect product grid responses.

Usage:
  python3 facet_summary.py grid1.json [grid2.json ...] [--attributes attrs.json]

Each gridN.json is a saved `search_discovery_product_grid_insights` response
(the full tool envelope, or just its `data` object). The optional attrs.json is
a saved `list_facet_attributes` response; with it the script also lists
facetable attributes that never appeared, and facetable attributes that look
internal.

For every response it prints one JSON object with:
  - numFound and, per facet in the order returned: name, type, number of
    values, the top values by count, and flags;
  - the facet rules that applied (from debug["customizations.explain"]).

Flags:
  empty            the facet returned no values (often an always-show facet)
  too_many_values  more than 30 values: hard to use, often raw data
  unbucketed_number a numeric facet with many distinct values (e.g. a rating
                   of 4.17, 4.18, ...) that needs ranges or buckets
  dominant_value   one value covers over 25% of results in a numeric facet,
                   which often means a default or placeholder (e.g. rating 1.0)
  internal_name    the field name looks internal (scores, margin, cluster ...)
  code_values      most values look like codes (c12, c69 ...)
  merge_candidates values that differ only by case, spacing or punctuation,
                   or are known variants (gray/grey); not checked on the
                   category facet, where same names in different branches
                   (men/pants, women/pants) are different categories
  test_values      values that look like test or internal data
  single_value     only one value: the facet can't narrow anything
  low_coverage     the values add up to under 20% of the results, so most
                   products lack this attribute (e.g. size on 52 of 1,170)

Standard library only; no network access.
"""
import json
import re
import sys
from collections import defaultdict

MANY_VALUES = 30
NUMERIC_DISTINCT = 15
DOMINANT_SHARE = 0.25
LOW_COVERAGE = 0.2
INTERNAL_RE = re.compile(
    r"(^br_|^sku_|omni_|score|margin|cluster|_id$|^id$|image|url|decayed|days_since|cost|internal)",
    re.I,
)
CODE_RE = re.compile(r"^[a-z]{0,3}\d+$", re.I)
TEST_RE = re.compile(r"(test|demo|example|xyz|dummy|sample|landing page|do not use|tmp)", re.I)
KNOWN_VARIANTS = [{"gray", "grey"}, {"colour", "color"}, {"denim", "denium"}]


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def load(path):
    with open(path, encoding="utf-8") as f:
        data = check(json.load(f), path)
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]  # some clients wrap tool output once more
    return data.get("data", data) if isinstance(data, dict) else {}


def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def value_name(v):
    return v.get("cat_name") or v.get("name") or ""


def merge_candidates(values):
    groups = defaultdict(list)
    for v in values:
        groups[norm(value_name(v))].append(value_name(v))
    out = [names for names in groups.values() if len(names) > 1]
    lowered = {value_name(v).strip().lower(): value_name(v) for v in values}
    for pair in KNOWN_VARIANTS:
        hits = [lowered[p] for p in pair if p in lowered]
        if len(hits) > 1:
            out.append(hits)
    trailing = [value_name(v) for v in values if value_name(v) != value_name(v).strip()]
    return out, trailing


def flag_facet(facet, num_found):
    name = facet.get("name", "")
    ftype = facet.get("type", "")
    values = facet.get("value") or []
    n = len(values)
    flags = []
    detail = {}
    if n == 0:
        flags.append("empty")
    elif n == 1:
        flags.append("single_value")
    if n > MANY_VALUES:
        flags.append("too_many_values")
    if ftype == "number" and n > NUMERIC_DISTINCT:
        flags.append("unbucketed_number")
    if ftype == "number" and num_found and values:
        top = max(values, key=lambda v: v.get("count", 0))
        if top.get("count", 0) / num_found > DOMINANT_SHARE:
            flags.append("dominant_value")
            detail["dominant_value"] = {"value": value_name(top), "count": top.get("count")}
    total = sum(v.get("count", 0) for v in values)
    if num_found and values and name != "category":
        detail["coverage"] = round(min(total / num_found, 1.0), 2)
        # Long value lists may be cut off (brand stopped at about 200 values in
        # testing), so their counts undercount coverage: don't flag those.
        if total / num_found < LOW_COVERAGE and n < 100:
            flags.append("low_coverage")
    if INTERNAL_RE.search(name):
        flags.append("internal_name")
    names = [value_name(v) for v in values]
    if names and sum(1 for x in names if CODE_RE.match(str(x))) / len(names) > 0.6 and ftype != "number":
        flags.append("code_values")
    if ftype != "number" and name != "category":
        merges, trailing = merge_candidates(values)
        if merges or trailing:
            flags.append("merge_candidates")
            if merges:
                detail["merge"] = merges
            if trailing:
                detail["trailing_spaces"] = trailing
    tests = [x for x in names if TEST_RE.search(str(x))]
    if tests:
        flags.append("test_values")
        detail["test_values"] = tests
    top_values = sorted(values, key=lambda v: -v.get("count", 0))[:8]
    return {
        "name": name,
        "type": ftype,
        "values": n,
        "top": [f"{value_name(v)} ({v.get('count')})" for v in top_values],
        "flags": flags,
        **detail,
    }


def facet_rules(debug):
    rules = []
    for rule in debug.get("customizations.explain") or []:
        if rule.get("ruleType") != "facet":
            continue
        items = {}
        for item in rule.get("customizationItems") or []:
            value = item.get("value")
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                pass
            if value in ({}, [], "", None):
                continue
            items[item.get("type")] = value
        rules.append({
            "id": rule.get("id"),
            "scope": [f"{q.get('type')}:{q.get('query')}" for q in rule.get("queries") or []],
            "audiences": rule.get("audienceNames") or [],
            "settings": items,
        })
    return rules


def summarise(path):
    data = load(path)
    resp = data.get("response") or {}
    num_found = resp.get("numFound") or 0
    facets = (data.get("facet_counts") or {}).get("facets") or []
    debug = data.get("debug") or {}
    out = {
        "file": path,
        "numFound": num_found,
        "facets": [flag_facet(f, num_found) for f in facets],
        "facet_rules": facet_rules(debug),
    }
    if not facets:
        out["note"] = "no facet block: was the call made with facet=false?"
    shown = {f.get("name") for f in facets}
    always = set()
    for rule in out["facet_rules"]:
        always.update(rule["settings"].get("always_included_facets") or [])
    out["always_show_but_missing_or_empty"] = sorted(
        a for a in always
        if a not in shown or not next((f.get("value") for f in facets if f.get("name") == a), None)
    )
    return out, shown


def attribute_report(path, seen):
    with open(path, encoding="utf-8") as f:
        data = check(json.load(f), path)
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    attrs = data.get("data", data) if isinstance(data, dict) else data
    facetable = [a for a in attrs if a.get("facetable")]
    return {
        "facetable_attributes": len(facetable),
        "never_shown": sorted(a["name"] for a in facetable if a["name"] not in seen),
        "internal_looking_but_facetable": sorted(
            a["name"] for a in facetable if INTERNAL_RE.search(a["name"])
        ),
    }


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    attrs = None
    files = []
    it = iter(argv)
    for arg in it:
        if arg == "--attributes":
            attrs = next(it, None)
        else:
            files.append(arg)
    if not files:
        print(__doc__)
        return 1
    seen = set()
    for path in files:
        try:
            out, shown = summarise(path)
        except (OSError, ValueError) as e:
            print(json.dumps({"file": path, "error": str(e)}))
            continue
        seen |= shown
        print(json.dumps(out, ensure_ascii=False))
    if attrs:
        print(json.dumps({"attributes": attribute_report(attrs, seen)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
