#!/usr/bin/env python3
"""Review Bloomreach Discovery Ranking Studio algorithms: status, where each is used, weights, overlap.

Usage:
  python3 algorithm_review.py --algorithms keyword_list.json --algorithms category_list.json
      [--detail algo_detail.json ...] [--query-grid "QUERY=grid.json" ...]
      [--category-grid "CATEGORY_ID=grid.json" ...] [--queries query_perf.json]
      [--categories category_perf.json] [--today 2026-11-03] [--out review.json]

--algorithms is a saved search_ranking_algorithms list (one per search_type, KEYWORD and CATEGORY).
--detail is a saved search_ranking_algorithms detail (algorithm_id + family) for one algorithm.
--query-grid and --category-grid are saved search_discovery_product_grid_insights results for a
sampled search query or category ID (search_by="category"). Algorithm assignments are rules of type
"ranking_algo", which the ranking rule list tools leave out; the grid's customizations.explain is the
only place that shows which algorithm a query or category uses.
--queries and --categories are saved get_discovery_query_performance and
get_discovery_category_performance_table results, used to weigh and compare the sampled scopes.

Prints JSON: each algorithm with its status, where it was seen in use and the traffic it serves, a
weight summary, and prioritised findings. It never prints editor names. Thresholds are in
references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, so a rule changes in one place.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
PRIORITY = ("fix now", "review", "clean up")
PERF_TYPES = {"PERF", "SEG_PERF"}
TRAINED_PREFIXES = ("ML_", "ABR_")
CUSTOM_TYPES = {"MANUAL", "ML_LINEAR_CUSTOM", "ABR_MANUAL", "ABR_CATALOG"}
# How specific an assignment is: a query or category rule beats a type-wide rule, which beats "global".
SPECIFICITY = {"sitesearch": 3, "category": 3, "sitesearch_global": 2, "category_global": 2, "global": 1}
SCOPE_FOR = {"sitesearch": "KEYWORD", "sitesearch_global": "KEYWORD", "category": "CATEGORY",
             "category_global": "CATEGORY", "global": None}


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
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    return doc


def data_of(doc):
    return doc.get("data") if isinstance(doc, dict) and "data" in doc else doc


def rows_of(path):
    d = data_of(load(path))
    if isinstance(d, dict):
        d = d.get("rows") or d.get("data") or []
    return d if isinstance(d, list) else []


def number(v):
    """A number from 1234, "$1,234.50" or "10.00%"; None when missing or unreadable."""
    if v in (None, ""):
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return None


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def pair(arg, flag):
    if "=" not in arg:
        fail(f"{flag} takes NAME=FILE, got {arg!r}")
    name, path = arg.rsplit("=", 1)
    return norm(name), path


def day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else None


# ---------------------------------------------------------------------------------------------
# Inputs

def load_algorithms(paths, detail_paths):
    algos = {}
    for p in paths:
        d = data_of(load(p))
        for a in d if isinstance(d, list) else []:
            algos[a.get("id")] = dict(a)
    for p in detail_paths:
        d = data_of(load(p))
        if not isinstance(d, dict) or d.get("id") is None:
            fail(f"{p}: not a search_ranking_algorithms detail (fetch one algorithm with algorithm_id and family)")
        algos[d["id"]] = dict(algos.get(d["id"], {}), **d, _detail=True)
    if not algos:
        fail("No algorithms in the --algorithms files. Save the search_ranking_algorithms list for KEYWORD and CATEGORY.")
    return algos


def assignments(grid_path, scope_kind, scope):
    """(algorithm assignments seen in a grid's customizations.explain, rankingAlgorithmName)."""
    d = data_of(load(grid_path))
    debug = (d or {}).get("debug") if isinstance(d, dict) else None
    if not isinstance(debug, dict) or "customizations.explain" not in debug:
        fail(f"{grid_path}: no debug output. Fetch the grid with simple_debug left at its default (true).")
    seen = []
    for rule in debug.get("customizations.explain") or []:
        for item in rule.get("customizationItems") or []:
            if item.get("type") != "ranking_algo":
                continue
            try:
                algo_id = json.loads(item.get("value") or "{}").get("id")
            except (ValueError, AttributeError):
                algo_id = None
            types = [q.get("type") for q in rule.get("queries") or []]
            best = max(types, key=lambda t: SPECIFICITY.get(t, 0)) if types else "global"
            seen.append({"scope": scope, "scope_kind": scope_kind, "algo_id": algo_id, "rule_id": rule.get("id"),
                         "rule_type": rule.get("ruleType"), "query_type": best,
                         "audiences": rule.get("audienceNames") or [], "in_test": bool(rule.get("liveInTest"))})
    return seen, (debug.get("rankingAlgorithmName") or "").strip()


def perf_index(path, key_fields):
    out = {}
    for r in rows_of(path) if path else []:
        for k in key_fields:
            if r.get(k) not in (None, ""):
                out.setdefault(norm(r[k]), r)
    return out


# ---------------------------------------------------------------------------------------------
# Weights

def weight_table(a):
    """{feature: (weight, featureType, min, max)} from a legacy combined section or an ABR weights list."""
    meta = a.get("modelMetaData") or {}
    table = {}
    for name, f in (meta.get("combined") or {}).items():
        if isinstance(f, dict):
            table[name] = (abs(number(f.get("weight")) or 0.0), f.get("featureType") or "", f.get("min"), f.get("max"))
    for w in a.get("weights") or []:  # ABR models
        if isinstance(w, dict):
            name = w.get("feature_key") or w.get("name") or w.get("key")
            value = w.get("display_weight", w.get("weight"))
            if name:
                table[name] = (abs(number(value) or 0.0), w.get("featureType") or w.get("type") or "", None, None)
    return table


def zero_range_text(a):
    text = ((a.get("modelMetaData") or {}).get("text") or {})
    return sorted(n for n, f in text.items() if isinstance(f, dict) and f.get("min") == f.get("max")
                  and (number(f.get("weight")) or 0) > RULES["zero_weight"])


def is_perf(name, ftype):
    return ftype in PERF_TYPES or (not ftype and re.search(r"view|atc|conversion|revenue|order", name))


def weight_summary(a):
    table = weight_table(a)
    total = sum(w for w, *_ in table.values())
    if not total:
        return None
    shares = sorted(((n, w / total, t) for n, (w, t, *_r) in table.items()), key=lambda x: -x[1])
    perf = sum(s for n, s, t in shares if is_perf(n, t))
    revenue = [s for n, s, t in shares if "revenue" in n.lower() and is_perf(n, t)]
    return {"signals": len(table), "top": [{"signal": n, "share": round(s, 3)} for n, s, _ in shares[:RULES["max_listed"]]],
            "performance_share": round(perf, 3),
            "revenue_share": round(sum(revenue), 3) if revenue else None,
            "custom": [{"signal": n, "share": round(s, 3)} for n, s, t in shares if t == "CUSTOM"],
            "zero_range_text_signals": zero_range_text(a), "_vector": {n: w for n, (w, *_r) in table.items()}}


def cosine(a, b):
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------------------------
# Review

class Findings:
    def __init__(self):
        self.items = []

    def add(self, priority, check, algo, detail, action):
        item = {"priority": priority, "check": check, "algorithm": algo, "detail": detail, "action": action}
        if item not in self.items:  # a global rule shows up on every sampled page
            self.items.append(item)


def label(a):
    return f"{a.get('name') or a.get('algoId')} ({a.get('algoId')}, {a.get('searchType')})"


def effective(seen, scope_kind):
    """The assignment that sets the algorithm for everyone on a scope: no audience, most specific type."""
    general = [s for s in seen if not s["audiences"] and (SCOPE_FOR.get(s["query_type"]) in (None, scope_kind))]
    return max(general, key=lambda s: SPECIFICITY.get(s["query_type"], 0)) if general else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--algorithms", action="append", default=[], required=True,
                    help="saved search_ranking_algorithms list (repeat for KEYWORD and CATEGORY)")
    ap.add_argument("--detail", action="append", default=[], help="saved search_ranking_algorithms detail (repeat)")
    ap.add_argument("--query-grid", action="append", default=[], help="QUERY=saved product grid for that query (repeat)")
    ap.add_argument("--category-grid", action="append", default=[],
                    help="CATEGORY_ID=saved product grid with search_by=category (repeat)")
    ap.add_argument("--queries", help="saved get_discovery_query_performance result")
    ap.add_argument("--categories", help="saved get_discovery_category_performance_table result")
    ap.add_argument("--today", help="YYYY-MM-DD to judge ages against (default: today, UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    try:
        today = datetime.strptime(a.today, "%Y-%m-%d").replace(tzinfo=timezone.utc) if a.today else datetime.now(timezone.utc)
    except ValueError:
        fail("--today must be YYYY-MM-DD")
    now_ms = today.timestamp() * 1000

    algos = load_algorithms(a.algorithms, a.detail)
    by_ref = {}
    for al in algos.values():
        by_ref.setdefault(al.get("algoId"), []).append(al)
    qperf = perf_index(a.queries, ("query",))
    cperf = perf_index(a.categories, ("cat_id", "category"))
    f = Findings()
    not_checked = []

    # ---- where each algorithm is used, from the sampled grids
    usage = {al_id: [] for al_id in algos}
    scopes = []
    for kind, args, perf in (("KEYWORD", a.query_grid, qperf), ("CATEGORY", a.category_grid, cperf)):
        for arg in args:
            scope, path = pair(arg, "--query-grid" if kind == "KEYWORD" else "--category-grid")
            seen, shown_name = assignments(path, kind, scope)
            eff = effective(seen, kind)
            if eff:
                candidates = [al for al in by_ref.get(eff["algo_id"], []) if al.get("searchType") == kind] \
                    or by_ref.get(eff["algo_id"], [])
            else:  # no assignment rule: the account default for this scope applies
                candidates = [al for al in algos.values() if al.get("searchType") == kind and al.get("status") == "Default"]
                if not candidates and shown_name:
                    candidates = [al for al in algos.values() if al.get("searchType") == kind and norm(al.get("name")) == norm(shown_name)]
            row = perf.get(scope) or {}
            visits, revenue, conv = number(row.get("visits")), number(row.get("revenue")), number(row.get("conversion_rate"))
            scopes.append({"scope": scope, "kind": kind, "algorithm": candidates[0]["id"] if candidates else None,
                           "via": eff, "visits": visits, "revenue": revenue,
                           "conversions": (visits or 0) * conv / 100 if visits is not None and conv is not None else None})
            for s in seen:
                refs = by_ref.get(s["algo_id"])
                if not refs:
                    f.add("fix now", "missing algorithm", s["algo_id"],
                          f"Rule {s['rule_id']} on {kind.lower()} '{scope}' applies algorithm {s['algo_id']}, which isn't in "
                          "Ranking Studio's list (deleted, or in another catalog).",
                          "Point the rule at an existing algorithm, or remove it (discovery-change-qa first).")
                    continue
                match = [al for al in refs if al.get("searchType") == kind]
                target = match[0] if match else refs[0]
                usage[target["id"]].append(dict(s, effective=bool(eff and eff["rule_id"] == s["rule_id"])))
                if s["query_type"] == "global":
                    other = "CATEGORY" if target.get("searchType") == "KEYWORD" else "KEYWORD"
                    f.add("review", "cross-type", label(target),
                          f"Global rule {s['rule_id']} applies this {target.get('searchType')} algorithm to both search and "
                          f"category pages, so {other.lower()} pages get an algorithm built for the other kind of page.",
                          "Use a sitesearch_global and a category_global rule, each with a matching algorithm.")
                elif not match:
                    f.add("fix now", "cross-type", label(target),
                          f"Rule {s['rule_id']} applies this {target.get('searchType')} algorithm to {kind.lower()} '{scope}'.",
                          f"Apply a {kind} algorithm instead (discovery-change-qa first).")
            if not candidates and not eff:
                not_checked.append(f"{kind.lower()} '{scope}': couldn't tell which algorithm applies (no assignment rule and no "
                                   "algorithm marked Default).")
            for al_id in [c["id"] for c in candidates[:1]] if not eff else []:
                usage[al_id].append({"scope": scope, "scope_kind": kind, "algo_id": algos[al_id].get("algoId"),
                                     "rule_id": None, "rule_type": "default", "query_type": None, "audiences": [],
                                     "in_test": False, "effective": True})
    if not a.query_grid and not a.category_grid:
        not_checked.append("Usage: no product grids were given, so nothing shows which algorithm each query or category uses.")

    # ---- per-algorithm checks
    out_algos, summaries = [], {}
    for al_id, al in sorted(algos.items(), key=lambda kv: (kv[1].get("searchType") or "", norm(kv[1].get("name")))):
        lab, status = label(al), al.get("status") or ""
        changed = al.get("lastModifiedAt") or al.get("createdAt")
        age_days = (now_ms - changed) / 86_400_000 if changed else None
        used = usage[al_id]
        in_use = bool(used) or status == "Default"
        if status == "Error" or al.get("failureMessage"):
            f.add("fix now" if in_use else "review", "error", lab,
                  "Status Error" + (f": {al['failureMessage']}" if al.get("failureMessage") else "") +
                  (" and it's in use, so those pages may fall back or rank badly." if in_use else "."),
                  "Retrain or repair it in Ranking Studio; if it's not needed, stop using it and remove it.")
        if status == "In Training" and age_days is not None and age_days >= RULES["training_stuck_days"]:
            f.add("review", "stuck training", lab, f"In Training for about {age_days:.0f} days.",
                  "Check the training in Ranking Studio; trained models usually finish in 24-48 hours.")
        if status == "Syncing" and age_days is not None and age_days * 24 >= RULES["syncing_stuck_hours"]:
            f.add("review", "stuck sync", lab, f"Syncing for about {age_days * 24:.0f} hours.",
                  "Check the weight sync in Ranking Studio; it usually takes about 20 minutes.")
        if not used and status != "Default" and (a.query_grid or a.category_grid):
            f.add("clean up", "not seen in use", lab,
                  "No sampled query or category uses it. It may still serve other queries, categories or audiences.",
                  "Check its rules in Ranking Studio before removing it; Discovery refuses to delete an algorithm a rule still uses.")
        if in_use and (al.get("type") or "") in CUSTOM_TYPES and age_days is not None and age_days >= RULES["stale_days"]:
            f.add("review", "stale", lab, f"In use, and unchanged for about {age_days / 365:.1f} years.",
                  "Check its weights still suit today's catalog, or A/B test it against the default (discovery-experiment-setup).")
        ws = weight_summary(al) if al.get("_detail") else None
        if al.get("_detail") is None and (al.get("type") or "").startswith(TRAINED_PREFIXES + ("MANUAL",)) and in_use:
            not_checked.append(f"Weights of {lab}: no detail fetched.")
        if ws:
            summaries[al_id] = ws
            top = ws["top"][0]
            if top["share"] >= RULES["dominance_share"]:
                f.add("review", "dominant signal", lab, f"{top['signal']} has {top['share']:.0%} of the weight.",
                      "Confirm one signal should drive the ranking; test a more balanced version first.")
            if in_use and ws["performance_share"] < RULES["min_performance_share"]:
                f.add("review", "ignores shoppers", lab,
                      f"Shopper-behaviour signals have only {ws['performance_share']:.0%} of the weight.",
                      "Confirm it's meant to ignore views, add-to-carts and sales (for example a text-only algorithm).")
            if ws["revenue_share"] is not None and ws["revenue_share"] <= RULES["zero_weight"] and ws["performance_share"] > RULES["min_performance_share"]:
                f.add("review", "revenue at zero", lab, "Revenue signals are weighted to zero while other shopper signals count.",
                      "Confirm leaving out revenue is deliberate.")
            for c in ws["custom"]:
                if c["share"] >= RULES["custom_signal_share"]:
                    f.add("review", "custom signal", lab, f"Custom signal {c['signal']} has {c['share']:.0%} of the weight.",
                          "Confirm a catalog attribute should drive the ranking this much; A/B test it first.")
            if ws["zero_range_text_signals"]:
                n = ws["zero_range_text_signals"]
                f.add("clean up", "flat signals", lab,
                      f"{len(n)} text signal(s) never varied in training, e.g. {', '.join(n[:RULES['max_listed']])}.",
                      "The field may be missing or unmapped in the catalog; check the feed (product-data-audit).")
        served = [s for s in scopes if s["algorithm"] == al_id]
        out_algos.append({
            "id": al_id, "algoId": al.get("algoId"), "name": al.get("name"), "type": al.get("type"),
            "searchType": al.get("searchType"), "status": status, "last_changed": day(changed),
            "training": al.get("modelTrainingStatus"), "weights_synced": al.get("weightFileStatus"),
            "used_on": [{k: u[k] for k in ("scope", "scope_kind", "rule_id", "rule_type", "query_type", "audiences", "in_test", "effective")}
                        for u in used][:RULES["max_listed"] * 4],
            "served_scopes": len(served),
            "visits_served": sum(s["visits"] or 0 for s in served),
            "revenue_served": round(sum(s["revenue"] or 0 for s in served), 2),
            "weights": {k: v for k, v in (ws or {}).items() if not k.startswith("_")} or None})

    # ---- duplicates and performance comparisons
    ids = [i for i in summaries]
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            ax, ay = algos[x], algos[y]
            if ax.get("searchType") != ay.get("searchType"):
                continue
            sim = cosine(summaries[x]["_vector"], summaries[y]["_vector"])
            if sim >= RULES["near_duplicate_similarity"]:
                f.add("clean up", "near-duplicate", f"{label(ax)} and {label(ay)}",
                      f"Their weights are {sim:.1%} similar.", "Keep one, and point the other's rules at it.")
    names = {}
    for al in algos.values():
        names.setdefault((al.get("searchType"), norm(al.get("name"))), []).append(al)
    for (st, n), group in names.items():
        if n and len(group) > 1:
            f.add("clean up", "same name", f"'{group[0].get('name')}' ({st})",
                  f"{len(group)} algorithms share this name: {', '.join(g.get('algoId') or '?' for g in group)}.",
                  "Rename them so rules point at the one people mean.")
    for kind in ("KEYWORD", "CATEGORY"):
        pool = [s for s in scopes if s["kind"] == kind and s["visits"] and s["conversions"] is not None and s["algorithm"]]
        for al_id in {s["algorithm"] for s in pool}:
            mine = [s for s in pool if s["algorithm"] == al_id]
            rest = [s for s in pool if s["algorithm"] != al_id]
            mv, rv = sum(s["visits"] for s in mine), sum(s["visits"] for s in rest)
            if mv < RULES["min_visits"] or rv < RULES["min_visits"]:
                continue
            mc, rc = sum(s["conversions"] for s in mine) / mv, sum(s["conversions"] for s in rest) / rv
            if rc and mc < rc * RULES["underperform_ratio"]:
                f.add("review", "converts less", label(algos[al_id]),
                      f"Its sampled {kind.lower()} scopes convert at {mc:.1%} against {rc:.1%} for the others "
                      f"({len(mine)} vs {len(rest)} scopes). Queries differ, so this is a lead, not proof.",
                      "A/B test it against the default before changing anything (discovery-experiment-setup).")

    defaults = {kind: [label(al) for al in algos.values() if al.get("searchType") == kind and al.get("status") == "Default"]
                for kind in ("KEYWORD", "CATEGORY")}
    for kind, labs in defaults.items():
        if not labs and any(al.get("searchType") == kind for al in algos.values()):
            not_checked.append(f"No {kind} algorithm is marked Default; pages without an assignment rule use the account's "
                               "built-in ranking, which the list doesn't name.")
    order = {p: i for i, p in enumerate(PRIORITY)}
    findings = sorted(f.items, key=lambda x: order[x["priority"]])
    result = {"ok": True,
              "summary": {"algorithms": len(algos),
                          "by_search_type": {k: sum(1 for al in algos.values() if al.get("searchType") == k) for k in ("KEYWORD", "CATEGORY")},
                          "sampled_queries": len(a.query_grid), "sampled_categories": len(a.category_grid),
                          "findings": {p: sum(1 for x in findings if x["priority"] == p) for p in PRIORITY}},
              "defaults": defaults, "algorithms": out_algos,
              "scopes": [{k: s[k] for k in ("scope", "kind", "visits", "revenue")} | {
                  "algorithm": label(algos[s["algorithm"]]) if s["algorithm"] else None,
                  "via_rule": s["via"]["rule_id"] if s["via"] else None} for s in scopes],
              "findings": findings, "not_checked": not_checked}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
