#!/usr/bin/env python3
"""Summarise a saved Loomi Connect `search_discovery_product_grid_insights` response.

Usage:
  python3 grid_summary.py response.json [response2.json ...]

Product grid responses are often 70,000-260,000 characters, even with `fl` and a
small `rows`, because the debug block explains every product's score. Clients
usually save them to a file. This script prints only the fields the triage needs,
as one JSON object per file:

  numFound, the first 10 titles, did_you_mean, autoCorrectQuery, applied precision,
  synonym expansions (with source type and direction), query-specific rules
  (anything not targeting "*"), active ranking rule IDs and any A/B test buckets.

Standard library only; no network access.
"""
import json
import sys


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
    # Accept the full tool envelope, its `data` object, or call_tool's {"result": ...} wrapper.
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data.get("data", data) if isinstance(data, dict) else {}


def experiments(debug):
    out = {}
    for exp in debug.get("experiments") or (debug.get("request") or {}).get("experiments") or []:
        if isinstance(exp, dict):
            out[exp.get("name")] = exp.get("value")
    return out


def synonyms(debug):
    explain = debug.get("synonym.explain") or {}
    smap = explain.get("synonyms_map") or {}
    chains = []
    for chain in explain.get("directSynonymsV3") or []:
        steps = []
        for step in chain:
            ids = step.get("ids") or []
            meta = smap.get(str(ids[0]), {}) if ids else {}
            steps.append({
                "from": step.get("source"),
                "to": step.get("target"),
                "via": step.get("type"),  # "dashboard" = a synonym entry, "lemma" = automatic word form
                "synonym_type": meta.get("type"),
                "two_way": meta.get("is_bidirectional"),
            })
        chains.append(steps)
    return chains


def query_rules(debug):
    # Rules passed in disabled_customization_ids are still listed in the explain block.
    disabled = {str(i) for i in debug.get("disabled_customizations.ids") or []}
    rules = []
    for rule in debug.get("customizations.explain") or []:
        queries = [q.get("query") for q in rule.get("queries") or []]
        if queries and all(q == "*" for q in queries):
            continue  # global defaults; not specific to this query
        items = {}
        for item in rule.get("customizationItems") or []:
            value = item.get("value")
            try:
                value = json.loads(value)
                if isinstance(value, dict) and set(value) == {"value"}:
                    value = value["value"]
            except (TypeError, ValueError):
                pass
            items[item.get("type")] = value
        rules.append({
            "id": rule.get("id"),
            "rule_type": rule.get("ruleType"),
            "disabled_in_this_call": str(rule.get("id")) in disabled,
            "queries": queries,
            "match": [q.get("matchType") for q in rule.get("queries") or []],
            "settings": items,
        })
    return rules


def summarise(data):
    debug = data.get("debug") or {}
    response = data.get("response") or {}
    meta = (data.get("metadata") or {}).get("query") or {}
    exps = experiments(debug)
    return {
        "numFound": response.get("numFound"),
        "titles": [d.get("title") for d in (response.get("docs") or [])[:10]],
        "did_you_mean": data.get("did_you_mean"),
        "autoCorrectQuery": data.get("autoCorrectQuery"),
        "precision_applied": ((meta.get("precision") or {}).get("applied") or {}).get("value"),
        "synonyms": synonyms(debug),
        "query_specific_rules": query_rules(debug),
        "ranking_rule_ids": (exps.get("customizations_priority") or {}).get("ranking"),
        "ab_test_buckets": exps.get("ab_test_buckets"),
        "disabled_ids": debug.get("disabled_customizations.ids"),
    }


def main(paths):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    if paths and paths[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    for path in paths:
        try:
            print(json.dumps({"file": path, **summarise(load(path))}, ensure_ascii=False))
        except (OSError, ValueError) as e:
            print(json.dumps({"file": path, "error": str(e)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
