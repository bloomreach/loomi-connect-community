#!/usr/bin/env python3
"""Plan Bloomreach Discovery ranking algorithm fixes before writing them, and check the writes afterwards.

Usage:
  python3 algorithm_fix_plan.py plan --changes changes.json --algorithms list.json [--algorithms list2.json]
         --detail detail.json [--detail ...] --account NAME --environment staging|production --out plan.json
         [--review review.json] [--grid grid.json ...] [--rule ID=rule.json ...] [--experiments experiments.json]
         [--site-group-id ID]
  python3 algorithm_fix_plan.py verify --plan plan.json --readback N=readback.json [--readback ...] [--out result.json]

plan: --changes lists the fixes wanted (references/change-format.md): weight changes, renames, corrected copies and
deletes, from discovery-ranking-algorithm-review findings or the user. --algorithms are saved search_ranking_algorithms
lists (KEYWORD and CATEGORY). Each --detail is a saved search_ranking_algorithms detail (algorithm_id + family) of an
algorithm the plan touches. --review is algorithm_review.py's output (where each algorithm was seen in use);
--grid are saved search_discovery_product_grid_insights results whose customizations.explain shows algorithm
assignments; each --rule ID=FILE is a saved get_ranking_rule result (an assignment rule, or a running experiment's
bucket rule). --experiments is a saved search_discovery_experiments listing.

Writes the full plan (every payload and undo) to --out, which is required: the undo of a delete is only there. Prints
the same plan with the min and max of margin and cost-type signals hidden. The plan has the shared shape
(docs/skill-authoring.md, "Plan files for write skills").

verify: --readback N=FILE is the search_ranking_algorithms detail read back after writing change N (for a create,
by the ID the create returned; for a delete, of the deleted algorithm). A call that errored is saved as
{"success": false, "error": "<the error text>"}, or as the bare error text. Reports each change as in_place,
not_in_place or gone. An error about the account, site, environment or access, or a 401, 403 or 429, stops; only a
not-found that names this algorithm's own ID counts as gone.

It never calls Loomi Connect: the assistant makes each write, after confirmation. Standard library only.
"""
import argparse
import copy
import json
import math
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
URL = re.compile(r"https?://\S+|\b[\w-]+(?:\.[\w-]+)+/\S*", re.I)
CONTEXT_ERROR = re.compile(r"account|organi[sz]ation|project|access|permission|forbidden|unauthori[sz]ed|"
                           r"\b40[13]\b|\b429\b|rate.?limit|too many requests|site.?group|environment|merchant", re.I)
NOT_FOUND = re.compile(r"not.?found|\b404\b|does not exist|doesn't exist|no such", re.I)
ACCOUNT_ERROR = ("Loomi Connect returned an error about the account, site, environment or access; it isn't repeated "
                 "because it can list other accounts. Check the account name and access, then read again.")
ACTIONS = ("update", "create", "delete")
EDITOR_KEYS = {"createdBy", "lastModifiedBy", "modifiedBy", "user", "userEmail", "email"}
HIDDEN = "<hidden: in the plan file>"
SCOPE_OF = {"sitesearch": "KEYWORD", "sitesearch_global": "KEYWORD", "category": "CATEGORY",
            "category_global": "CATEGORY", "global": None}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text):
    """Error text safe to repeat: URLs stripped (they can carry internal hosts and account numbers), cut short."""
    return URL.sub("<url>", str(text or "no error text")).strip()[:200]


def classify(text):
    """'context' (stop the run), 'not_found' (the item itself isn't there) or 'other'."""
    clean = redact(text)
    if CONTEXT_ERROR.search(clean):
        return "context"
    return "not_found" if NOT_FOUND.search(clean) else "other"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({type(e).__name__}).")


def error_of(data):
    """The error text when Loomi Connect returned success: false (as data), else None."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or "no error text")
    return None


def load(path):
    data = read_json(path)
    err = error_of(data)
    if err is not None:
        msg = ACCOUNT_ERROR if classify(err) == "context" else redact(err)
        fail(f"{path}: {msg} This step couldn't run; don't treat it as 'nothing found'.")
    return data


def unwrap(data):
    """The payload inside {"result": ...}, {"data": ...} and the double {"data": {"data": ...}} of rule detail."""
    for _ in range(4):
        if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
            data = data["result"]
        elif isinstance(data, dict) and isinstance(data.get("data"), (dict, list)) and "id" not in data:
            data = data["data"]
        else:
            break
    return data


def rows(path):
    data = unwrap(load(path))
    if isinstance(data, dict):
        data = data.get("rows") if isinstance(data.get("rows"), list) else [data] if data else []
    if not isinstance(data, list):
        fail(f"{path}: expected a list of records.")
    return [r for r in data if isinstance(r, dict)]


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def as_id(value, where):
    if isinstance(value, bool):
        fail(f"{where}: {value!r} isn't a numeric algorithm ID.")
    try:
        return int(value)
    except (TypeError, ValueError):
        fail(f"{where}: {value!r} isn't a numeric algorithm ID (the 'id' from search_ranking_algorithms, not the br- algoId).")


def dec(value):
    """A weight as an exact Decimal, or None if it isn't a finite number (strings and booleans are refused)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def show(d):
    """A weight for display only: rounded, never used in a payload."""
    return None if d is None else float(Decimal(d).quantize(Decimal("0.0001"), ROUND_HALF_UP))


def sensitive(name):
    low = str(name or "").lower()
    return any(w in low for w in RULES["sensitive_signal_words"])


def commercial(name, feature_type=None):
    """A margin or cost-type signal: its name says so, or it's a custom catalog attribute (featureType CUSTOM)."""
    return sensitive(name) or str(feature_type or "").upper() == "CUSTOM"


def strip_editors(obj):
    """A copy without editor names or emails (createdBy, lastModifiedBy, user)."""
    if isinstance(obj, dict):
        return {k: strip_editors(v) for k, v in obj.items() if k not in EDITOR_KEYS}
    if isinstance(obj, list):
        return [strip_editors(v) for v in obj]
    return obj


SIGNAL_KEEP = ("feature_key", "display_weight", "weight", "featureType", "type")


def mask(obj):
    """The plan as printed: every signal keeps its name, type and weight; its min, max and any other values are
    hidden (for a margin or cost signal they are the catalog's commercial values, and they're never needed for
    display). The --out file keeps them for the undo."""
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    if not isinstance(obj, dict):
        return obj
    if "feature_key" in obj or (("weight" in obj or "featureType" in obj) and ("min" in obj or "max" in obj)):
        return {k: (v if k in SIGNAL_KEEP else HIDDEN) for k, v in obj.items()}
    return {k: mask(v) for k, v in obj.items()}


# ---------------------------------------------------------------------------------------------
# Inputs

def default_status(alg):
    """Whether an algorithm is the default for its page type (status compared case-insensitively)."""
    return norm(alg.get("status")) == "default"


def family_of(alg):
    return "abr" if str(alg.get("type") or "").upper().startswith("ABR_") else "legacy"


def load_algorithms(list_paths, detail_paths):
    """{id: record}: list fields, overlaid with the detail (weights) where one was saved."""
    algos = {}
    for p in list_paths:
        for r in rows(p):
            if r.get("id") is not None:
                algos[as_id(r["id"], p)] = dict(r)
    for p in detail_paths:
        d = unwrap(load(p))
        if not isinstance(d, dict) or d.get("id") is None:
            fail(f"{p}: not a search_ranking_algorithms detail (fetch one algorithm with algorithm_id and family).")
        aid = as_id(d["id"], p)
        algos[aid] = dict(algos.get(aid, {}), **d, _detail=True)
    if not algos:
        fail("No algorithms in the --algorithms files. Save search_ranking_algorithms for KEYWORD and CATEGORY.")
    return algos


def weight_table(alg):
    """(kind, {signal: Decimal}, text signal names): 'combined' for legacy, 'abr' for ABR, None when it has none."""
    if family_of(alg) == "abr":
        table = {}
        for w in alg.get("weights") or []:
            if isinstance(w, dict) and w.get("feature_key"):
                table[str(w["feature_key"])] = dec(w.get("display_weight", w.get("weight")))
        return ("abr" if table else None), table, []
    meta = alg.get("modelMetaData") or {}
    table = {str(k): dec(v.get("weight")) for k, v in (meta.get("combined") or {}).items() if isinstance(v, dict)}
    text = sorted(str(k) for k in (meta.get("text") or {}))
    return ("combined" if table else None), table, text


def algo_id_of_rule(rec):
    """The br-... algoId a ranking rule assigns, or None."""
    items = rec.get("customizationItems")
    if isinstance(items, dict):
        v = items.get("ranking_algo")
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                return v.strip() or None
        if isinstance(v, dict):
            return v.get("id")
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("type") == "ranking_algo":
                try:
                    return (json.loads(it.get("value") or "{}") or {}).get("id")
                except (ValueError, AttributeError):
                    return None
    return None


def rule_scope(rec):
    """KEYWORD, CATEGORY or None (both) from a rule's query types."""
    kinds = {SCOPE_OF.get(str(q.get("queryType") or q.get("type") or "").lower())
             for q in rec.get("queries") or [] if isinstance(q, dict)}
    return next(iter(kinds)) if len(kinds) == 1 else None  # global, mixed or unknown: both page types


def load_rules(pairs):
    """{rule id: {"algo": algoId or None, "scope": KEYWORD/CATEGORY/None, "audiences": bool}} from get_ranking_rule."""
    out = {}
    for rid, path in pairs:
        rec = unwrap(load(path))
        if not isinstance(rec, dict) or rec.get("id") is None:
            fail(f"{path}: not a get_ranking_rule result.")
        if as_id(rec["id"], path) != rid:
            fail(f"{path}: holds rule {rec['id']}, not rule {rid}.")
        out[rid] = {"algo": algo_id_of_rule(rec), "scope": rule_scope(rec), "enabled": rec.get("enabled"),
                    "audiences": bool([a for a in rec.get("audiences") or [] if isinstance(a, dict) and a.get("id") not in (None, -1)])}
    return out


def matches(alg, algo_ref, scope):
    """Whether an assignment of algo_ref on a scope (KEYWORD, CATEGORY or None for both) points at this algorithm.
    br-standard is the algoId of both classic rankers, so the page type has to agree."""
    return bool(algo_ref) and algo_ref == alg.get("algoId") and scope in (None, alg.get("searchType"))


def grid_assignments(paths):
    """Algorithm assignments seen in saved product grids: [{algo, scope, rule_id, in_test}]."""
    seen = []
    for p in paths:
        d = unwrap(load(p))
        debug = d.get("debug") if isinstance(d, dict) else None
        if not isinstance(debug, dict) or "customizations.explain" not in debug:
            fail(f"{p}: no debug output. Fetch the grid with simple_debug left at its default (true).")
        for rule in debug.get("customizations.explain") or []:
            if not isinstance(rule, dict):
                continue
            ref = algo_id_of_rule({"customizationItems": rule.get("customizationItems")})
            if ref:
                seen.append({"algo": ref, "scope": rule_scope(rule), "rule_id": rule.get("id"),
                             "in_test": bool(rule.get("liveInTest"))})
    return seen


def review_usage(path):
    """({algorithm id: [used_on entries]}, sampled pages) from algorithm_review.py output."""
    if not path:
        return None, 0
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("ok") is not True or not isinstance(doc.get("algorithms"), list):
        fail(f"{path}: not an algorithm_review.py result (run discovery-ranking-algorithm-review's script with --out).")
    usage = {}
    for a in doc["algorithms"]:
        if isinstance(a, dict) and a.get("id") is not None:
            usage[as_id(a["id"], path)] = {"used_on": [u for u in a.get("used_on") or [] if isinstance(u, dict)],
                                           "visits": dec(a.get("visits_served")) or Decimal(0)}
    s = doc.get("summary") or {}
    return usage, int(s.get("sampled_queries") or 0) + int(s.get("sampled_categories") or 0)


def running_experiments(path):
    """Experiments that aren't known to be finished (status missing, or not in finished_statuses):
    [{name, rule_ids}]."""
    if not path:
        return None
    finished = {norm(x) for x in RULES["finished_statuses"]}
    out = []
    for e in rows(path):
        status = norm(e.get("experimentStatus") or e.get("status"))
        if status and status in finished:
            continue  # anything else, or no status at all, may be running
        ids = set()
        for b in e.get("buckets") or []:
            info = (b or {}).get("ruleIdentifierInfo") if isinstance(b, dict) else None
            if isinstance(info, dict) and info.get("id") not in (None, ""):
                ids.add(as_id(info["id"], path))
        ids = sorted(ids)
        out.append({"name": str(e.get("experimentName") or e.get("name") or e.get("id")), "rule_ids": ids})
    return sorted(out, key=lambda x: x["name"])


# ---------------------------------------------------------------------------------------------
# Planning

class Req:
    def __init__(self, n, raw):
        self.n, self.raw, self.problems, self.warnings = n, raw, [], []

    def block(self, msg):
        self.problems.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


class Context:
    def __init__(self, a):
        self.a = a
        self.algos = load_algorithms(a.algorithms, a.detail)
        self.usage, self.sampled = review_usage(a.review)
        self.grids = grid_assignments(a.grid)
        self.rules = load_rules(a.rule)
        self.exps = running_experiments(a.experiments)
        self.has_usage = bool(self.usage is not None and self.sampled) or bool(a.grid)

    def base(self):
        args = {"account_name": self.a.account, "environment": self.a.environment}
        if self.a.site_group_id:
            args["site_group_id"] = self.a.site_group_id
        return args

    def label(self, alg):
        return f"{alg.get('name') or alg.get('algoId')} ({alg.get('algoId')}, {alg.get('searchType')})"

    def seen_in_use(self, aid):
        """Where the algorithm was seen assigned: review used_on entries, grid assignments and rule files."""
        alg = self.algos[aid]
        hits = []
        for u in (self.usage or {}).get(aid, {}).get("used_on", []):
            hits.append({"where": f"{str(u.get('scope_kind') or '').lower()} '{u.get('scope')}'",
                         "rule_id": u.get("rule_id"), "in_test": bool(u.get("in_test"))})
        for g in self.grids:
            if matches(alg, g["algo"], g["scope"]):
                hits.append({"where": "a sampled product grid", "rule_id": g["rule_id"], "in_test": g["in_test"]})
        for rid, r in sorted(self.rules.items()):
            if matches(alg, r["algo"], r["scope"]):
                hits.append({"where": f"the pages rule {rid} targets", "rule_id": None, "in_test": False})
        return hits

    def test_problems(self, aid):
        """Why a change to this algorithm is blocked by a possibly running experiment (empty if it isn't)."""
        alg, out = self.algos[aid], []
        for e in self.exps or []:
            for rid in e["rule_ids"]:
                r = self.rules.get(rid)
                if r is None:
                    out.append(f"Experiment '{e['name']}' may be running and its bucket rule {rid} wasn't read: fetch it "
                               "with get_ranking_rule and pass it with --rule, so the plan can tell whether it uses "
                               "this algorithm.")
                elif matches(alg, r["algo"], r["scope"]):
                    out.append(f"Experiment '{e['name']}' may be running and its bucket rule {rid} uses this algorithm: "
                               "a change would muddy the test. Wait for it to end (discovery-experiment-readout).")
        if any(h["in_test"] for h in self.seen_in_use(aid)):
            out.append("An assignment of this algorithm is live in an A/B test: wait for the test to end.")
        return sorted(set(out))


def change(r, kind, target, tool, payload, before, after, undo, live, note, **extra):
    return dict({"request": r.n, "reason": r.raw.get("reason"), "kind": kind, "target": target, "tool": tool,
                 "payload": payload, "before": before, "after": after, "undo": undo, "live_impact": live,
                 "impact_note": note, "problems": r.problems, "warnings": r.warnings}, **extra)


def blocked(r, kind, target, tool):
    return [change(r, kind, target, tool, None, None, None, [], "none", None)]


def new_weights(r, table, text_signals, edits, rebalance):
    """The full weight table to send ({signal: Decimal}, every weight rounded to weight_decimals and adding up to
    exactly weight_total) and why each signal changed ({signal: reason}), or (None, {})."""
    if edits is not None and (not isinstance(edits, dict) or not edits):
        r.block("weights must be an object of {signal: new weight}.")
        return None, {}
    lo, hi = Decimal(str(RULES["weight_min"])), Decimal(str(RULES["weight_max"]))
    total, tol = Decimal(str(RULES["weight_total"])), Decimal(str(RULES["weight_sum_tolerance"]))
    q = Decimal(1).scaleb(-RULES["weight_decimals"])
    n = RULES["max_listed"]
    want = {}
    for sig in sorted(edits or {}):
        if sig not in table:
            if sig in text_signals:
                r.block(f"'{sig}' is a text-matching signal inside text_score; only the top-level (combined) weights "
                        "can be changed here. Change text matching in Ranking Studio.")
            else:
                r.block(f"'{sig}' isn't a signal of this algorithm (its signals: {', '.join(sorted(table)[:n])}"
                        f"{'…' if len(table) > n else ''}). Adding a signal means a new algorithm, built in Ranking Studio.")
            continue
        v = dec(edits[sig])
        if v is None:
            r.block(f"The new weight for '{sig}' isn't a number.")
        elif not lo <= v <= hi:
            r.block(f"The new weight for '{sig}' ({edits[sig]}) is outside the allowed range {RULES['weight_min']} to "
                    f"{RULES['weight_max']}.")
        else:
            want[sig] = v
    if r.problems:
        return None, {}
    if not table or any(table[s] is None for s in table):
        r.block("Some of this algorithm's saved weights aren't numbers, so the change can't be checked.")
        return None, {}
    after = dict(table, **want)
    if rebalance and want:
        others = sorted(s for s in table if s not in want)
        rest, old_rest = total - sum(want.values(), Decimal(0)), sum((table[s] for s in others), Decimal(0))
        if rest < 0:
            r.block(f"The new weights add up to {sum(want.values())}, more than weight_total ({RULES['weight_total']}).")
            return None, {}
        if not others or old_rest == 0:
            r.block("There are no other weighted signals to rebalance: give every weight.")
            return None, {}
        for s in others:
            after[s] = table[s] * rest / old_rest
    elif abs(sum(after.values(), Decimal(0)) - total) > tol:
        r.block(f"The weights would add up to {show(sum(after.values(), Decimal(0)))}, not weight_total "
                f"({RULES['weight_total']}). Set \"rebalance\": true to scale the other signals to fit, or give "
                "every weight.")
        return None, {}
    # Round every weight and put the remainder on the biggest, so the total is exactly weight_total.
    after = {s: v.quantize(q, ROUND_HALF_UP) for s, v in after.items()}
    biggest = max(after, key=lambda s: (after[s], s))
    after[biggest] += total - sum(after.values(), Decimal(0))
    bad = sorted(s for s, v in after.items() if not lo <= v <= hi)
    if bad:
        r.block(f"After rebalancing and rounding, {', '.join(bad[:n])} would be outside the allowed range "
                f"{RULES['weight_min']} to {RULES['weight_max']}: give the weights in full instead.")
        return None, {}
    why = {}
    for s in sorted(after):
        if after[s] != table[s]:
            why[s] = ("requested" if s in want and after[s] == want[s] else
                      "rebalanced" if rebalance and want and s not in want else
                      "rounded so the weights add up to exactly weight_total")
    return after, why


def float_weights(after, order):
    """{signal: float} in payload order whose plain left-to-right float sum is exactly weight_total: the Decimal
    values add up exactly, but their floats may not, so the biggest takes the float difference."""
    out = {s: float(after[s]) for s in order}
    if not order:
        return out
    target = float(RULES["weight_total"])
    biggest = max(order, key=lambda s: (after[s], s))
    for _ in range(4):
        running = 0.0
        for s in order:  # plain left-to-right addition, as a server would; sum() compensates on Python 3.12+
            running += out[s]
        if running == target:
            break
        out[biggest] = math.nextafter(out[biggest], math.inf if running < target else -math.inf)
    return out


def apply_weights(alg, kind, after):
    """The model_metadata (legacy) or weights list (ABR) with every top-level weight rewritten from `after`."""
    if kind == "abr":
        out = copy.deepcopy(alg.get("weights") or [])
        entries = [w for w in out if isinstance(w, dict) and w.get("feature_key") in after]
        floats = float_weights(after, [w["feature_key"] for w in entries])
        for w in entries:
            w["display_weight" if "display_weight" in w or "weight" not in w else "weight"] = floats[w["feature_key"]]
        return out
    meta = copy.deepcopy(alg.get("modelMetaData") or {})
    combined = meta["combined"]
    floats = float_weights(after, [s for s in combined if s in after])
    for sig, v in floats.items():
        combined[sig]["weight"] = v
    return meta


def signal_types(alg):
    """{signal: featureType} for the top-level signals."""
    if family_of(alg) == "abr":
        return {str(w.get("feature_key")): str(w.get("featureType") or w.get("type") or "")
                for w in alg.get("weights") or [] if isinstance(w, dict)}
    combined = (alg.get("modelMetaData") or {}).get("combined") or {}
    return {str(k): str(v.get("featureType") or "") for k, v in combined.items() if isinstance(v, dict)}


def weight_rows(alg, table, after, why):
    types = signal_types(alg)
    return [{"signal": s, "before": show(table[s]), "after": show(after[s]), "why": why[s],
             "margin_or_cost": commercial(s, types.get(s))} for s in sorted(why)]


def weight_warnings(r, alg, why, trained=True):
    types = signal_types(alg)
    touched = sorted(s for s in why if commercial(s, types.get(s)))
    if touched:
        r.warn(f"This changes the weight of margin, cost or custom catalog signal(s) {', '.join(touched)}: how much "
               "commercial data drives the order. A/B test it before it ranks for everyone; the signals' values are "
               "never shown.")
    if trained and str(alg.get("type") or "").upper().startswith("ML_") and why:
        r.warn("This is a trained model: hand-set weights replace what training learned. A corrected MANUAL copy "
               "keeps the original to compare against.")


def expected(after):
    return {s: float(v) for s, v in sorted(after.items())}


def find_algo(r, ctx, key="algorithm_id"):
    aid = r.raw.get(key)
    if aid is None or isinstance(aid, bool):
        r.block(f"{key} is required (the numeric 'id' from search_ranking_algorithms).")
        return None, None
    try:
        aid = int(aid)
    except (TypeError, ValueError):
        r.block(f"{key} {aid!r} isn't the numeric 'id' from search_ranking_algorithms (not the br- algoId).")
        return None, None
    alg = ctx.algos.get(aid)
    if alg is None:
        r.block(f"Algorithm {aid} isn't in the saved search_ranking_algorithms lists: list both search types first.")
        return aid, None
    if not alg.get("_detail"):
        r.block(f"Fetch algorithm {aid} with search_ranking_algorithms algorithm_id={aid} family={family_of(alg)} "
                "first: the list has no weights, so the change and its undo can't be planned.")
    return aid, alg


def name_clash(r, ctx, name, search_type, skip=None):
    for aid, other in sorted(ctx.algos.items()):
        if aid != skip and other.get("searchType") == search_type and norm(other.get("name")) == norm(name):
            r.block(f"Algorithm {aid} already has the name '{other.get('name')}' for {str(search_type).lower()} "
                    "pages; pick a name nobody can mix up.")
            return


def plan_update(r, ctx):
    aid, alg = find_algo(r, ctx)
    if alg is None or r.problems:
        return blocked(r, "update", f"algorithm {aid}" if alg is None else ctx.label(alg), "update_ranking_algorithm")
    target, fam = ctx.label(alg), family_of(alg)
    typ = str(alg.get("type") or "").upper()
    payload = dict(ctx.base(), algorithm_id=aid, family=fam)
    undo = dict(ctx.base(), algorithm_id=aid, family=fam)
    before, after_shown, extra = {}, {}, {}
    for k in ("name", "description"):
        if r.raw.get(k) is not None and str(r.raw[k]) != str(alg.get(k) or ""):
            payload[k], undo[k] = str(r.raw[k]), str(alg.get(k) or "")
            before[k], after_shown[k] = alg.get(k), str(r.raw[k])
    if "name" in payload:
        name_clash(r, ctx, payload["name"], alg.get("searchType"), skip=aid)
    weights = r.raw.get("weights")
    live, note = "none", "None: only the name or description changes."
    if weights is not None:
        kind, table, text = weight_table(alg)
        if typ in [t.upper() for t in RULES["trained_abr_types"]]:
            r.block(f"{typ} is a trained ABR model: update_ranking_algorithm turns it into ABR_MANUAL for good when "
                    "weights are passed, and the undo can't make it trained again. Create a corrected copy instead "
                    "(action create, copy_of) and A/B test it (discovery-experiment-setup).")
        elif kind is None:
            r.block(f"{typ or 'This algorithm'} has no editable weights (classic and non-linear rankers don't).")
        else:
            after, why = new_weights(r, table, text, weights, bool(r.raw.get("rebalance")))
            changed = sorted(why)
            if after is not None and changed:
                new = apply_weights(alg, kind, after)
                old = copy.deepcopy(alg.get("weights") if kind == "abr" else alg.get("modelMetaData"))
                payload["weights" if kind == "abr" else "model_metadata"] = new
                undo["weights" if kind == "abr" else "model_metadata"] = old
                before["weights"] = {s: show(table[s]) for s in changed}
                after_shown["weights"] = {s: show(after[s]) for s in changed}
                extra["signals"] = weight_rows(alg, table, after, why)
                extra["expected_weights"] = expected(after)
                weight_warnings(r, alg, why)
                hits = ctx.seen_in_use(aid)
                usage = (ctx.usage or {}).get(aid, {})
                is_default = default_status(alg)
                busy = is_default or usage.get("visits", Decimal(0)) >= RULES["high_traffic_visits"]
                if not ctx.has_usage:
                    r.block("No usage check: pass the review (--review) or product grids (--grid), so the plan knows "
                            "which pages this weight change would reach.")
                elif busy and not r.raw.get("skip_test"):
                    r.block(("It's the default algorithm" if is_default else
                             f"It ranks high-traffic pages (at least {RULES['high_traffic_visits']} visits in the "
                             "review's sample)") + ": make a corrected copy (action create, copy_of) and A/B test it "
                            "against this one with discovery-experiment-setup. Add \"skip_test\": true only if the "
                            "user chooses to change it in place anyway.")
                elif busy:
                    r.warn("Changed in place on high-traffic pages without an A/B test, as the user chose.")
                live = "live"
                where = ", ".join(sorted({h["where"] for h in hits})[:RULES["max_listed"]])
                note = ((f"Live at once on every page this algorithm ranks ({'the default; ' if is_default else ''}"
                         f"seen on {where})" if hits or is_default else
                         "Live at once on any page a rule assigns it to (none seen on the sampled pages)") +
                        (". Legacy weights re-sync, so its status shows Syncing for about 20 minutes." if kind != "abr" else "."))
            elif after is not None:
                r.warn("The weights already have these values.")
    if len(payload) > len(dict(ctx.base(), algorithm_id=aid, family=fam)):
        # Any change, a rename included, waits for a running test that uses the algorithm to end.
        r.problems.extend(p for p in ctx.test_problems(aid) if p not in r.problems)
    else:
        if not r.problems:
            return [change(r, "update", target, "update_ranking_algorithm", None, None, None, [], "none", None,
                           no_change=True)]
        return blocked(r, "update", target, "update_ranking_algorithm")
    return [change(r, "update", target, "update_ranking_algorithm", payload, before, after_shown,
                   [{"tool": "update_ranking_algorithm", "payload": undo,
                     "note": "Puts back the saved name, description and weights."}], live, note,
                   **dict(extra, algorithm_id=aid))]


def plan_create(r, ctx):
    src_id, src = find_algo(r, ctx, "copy_of")
    name = str(r.raw.get("name") or "").strip()
    if not name:
        r.block("A copy needs a name.")
    if src is None or r.problems:
        return blocked(r, "create", f"new algorithm '{name}'", None)
    kind, table, text = weight_table(src)
    if kind is None:
        r.block(f"Algorithm {src_id} ({src.get('type')}) has no weights to copy.")
        return blocked(r, "create", f"new algorithm '{name}'", None)
    st, domain = src.get("searchType"), src.get("domainKey") or src.get("catalog")
    name_clash(r, ctx, name, st)
    customs = {t.upper() for t in RULES["custom_types"]}
    count = sum(1 for x in ctx.algos.values() if x.get("searchType") == st and str(x.get("type") or "").upper() in customs
                and (x.get("domainKey") or x.get("catalog")) == domain)
    if count >= RULES["max_custom_per_catalog"]:
        r.block(f"The catalog already has {count} custom {str(st).lower()} algorithms and Discovery allows "
                f"{RULES['max_custom_per_catalog']}: delete one first (its own plan), then plan this copy.")
    if not domain:
        r.block(f"Algorithm {src_id} has no domainKey or catalog, so the copy's catalog is unknown.")
    # A manual copy's weights must add up to exactly weight_total, so they're always rounded and normalised.
    after, why = new_weights(r, table, text, r.raw.get("weights"), bool(r.raw.get("rebalance")))
    if after is None or r.problems:
        return blocked(r, "create", f"new algorithm '{name}'", None)
    weight_warnings(r, src, why, trained=False)
    payload = dict(ctx.base(), name=name, search_type=st)
    if r.raw.get("description"):
        payload["description"] = str(r.raw["description"])
    if kind == "abr":
        if not src.get("algoId"):
            r.block(f"Algorithm {src_id} has no algoId to clone from.")
        tool, fam, new_type = "create_abr_algorithm", "abr", "ABR_MANUAL"
        payload.update(type=new_type, catalog=domain, base_algo_id=src.get("algoId"),
                       weights=apply_weights(src, kind, after))
    else:
        tool, fam, new_type = "create_ranking_algorithm", "legacy", "MANUAL"
        payload.update(type=new_type, domain_key=domain, model_metadata=apply_weights(src, kind, after))
    target = f"new algorithm '{name}' ({str(st).lower()}, copy of {ctx.label(src)})"
    return [change(r, "create", target, tool, payload, None,
                   {"name": name, "type": new_type, "search_type": st,
                    "weights": {s: show(after[s]) for s in sorted(why)}},
                   [{"tool": "delete_ranking_algorithm",
                     "payload": dict(ctx.base(), algorithm_id="<id returned by the create>", family=fam),
                     "note": "Deleting the copy removes it; nothing points at it."}],
                   "none", "None: a new algorithm ranks nothing until a ranking_algo rule assigns it (that is "
                   "discovery-experiment-setup's job, as an A/B test).",
                   signals=weight_rows(src, table, after, why), expected_weights=expected(after),
                   expected_type=new_type, expected_search_type=st, copy_of=src_id)]


def recreate(ctx, alg):
    """(undo steps, undo_note) for a delete: recreate from the saved definition, with a new ID."""
    typ, fam = str(alg.get("type") or "").upper(), family_of(alg)
    domain = alg.get("domainKey") or alg.get("catalog")
    base = dict(ctx.base(), name=alg.get("name"), search_type=alg.get("searchType"))
    if alg.get("description"):
        base["description"] = alg["description"]
    note = ("Recreated with a new id and algoId and no edit history. Nothing was assigned to the old one, so "
            "nothing needs repointing.")
    if fam == "legacy" and (alg.get("modelMetaData") or {}).get("combined"):
        kind, table, text = weight_table(alg)
        probe = Req(0, {})
        after, why = new_weights(probe, table, text, None, False)
        meta = apply_weights(alg, kind, after) if after is not None else copy.deepcopy(alg["modelMetaData"])
        payload = dict(base, type="MANUAL", domain_key=domain, model_metadata=meta)
        extra = "" if typ == "MANUAL" else (f" It comes back as MANUAL with the saved weights; as {typ} it would "
                                            "retrain and learn new ones.")
        if why:
            extra += (" Its weights are rounded so they add up to exactly weight_total, as a MANUAL algorithm needs "
                      f"({len(why)} signal(s) moved by rounding).")
        elif after is None:
            extra += " Its saved weights don't add up to weight_total, so Discovery may refuse the recreate."
        return [{"tool": "create_ranking_algorithm", "payload": payload, "note": note + extra}], None
    if typ == "ABR_MANUAL" and alg.get("baseAlgoId"):
        payload = dict(base, type="ABR_MANUAL", catalog=domain, base_algo_id=alg["baseAlgoId"],
                       weights=copy.deepcopy(alg.get("weights") or []))
        return [{"tool": "create_abr_algorithm", "payload": payload, "note": note}], None
    return [], (f"No tool call can bring back a {typ or 'this'} algorithm as it was: recreate it in Ranking Studio "
                "from the definition saved in this plan" + (" (it retrains, 24-48 hours, and learns new weights)."
                                                             if typ.startswith(("ABR_", "ML_")) else "."))


def plan_delete(r, ctx):
    aid, alg = find_algo(r, ctx)
    if alg is None or r.problems:
        return blocked(r, "delete", f"algorithm {aid}" if alg is None else ctx.label(alg), "delete_ranking_algorithm")
    target, typ = ctx.label(alg), str(alg.get("type") or "").upper()
    if default_status(alg):
        r.block("It's the default algorithm for its page type: everything without an assignment uses it.")
    if typ in [t.upper() for t in RULES["protected_types"]] or alg.get("algoId") == "br-standard":
        r.block(f"{typ} is one of Bloomreach's own rankers; it can't be recreated as it was.")
    if not ctx.has_usage:
        r.block("No usage check: pass the review (--review) or product grids (--grid), and any ranking_algo rules "
                "(--rule), so the plan can check nothing assigns it.")
    for h in ctx.seen_in_use(aid):
        r.block(f"In use: it ranks {h['where']}" + (f" (rule {h['rule_id']})" if h["rule_id"] is not None else "") +
                ". Repoint or remove the rule that assigns it first (discovery-change-qa, Ranking Studio); this skill "
                "doesn't change rules.")
    r.problems.extend(p for p in ctx.test_problems(aid) if p not in r.problems)
    r.problems[:] = sorted(set(r.problems), key=r.problems.index)
    undo, undo_note = recreate(ctx, alg)
    r.warn("Deletes can't be reversed in Discovery. The undo recreates it from the saved definition, with a new ID.")
    if ctx.usage is not None and ctx.sampled:
        r.warn(f"'Not in use' covers the review's {ctx.sampled} sampled pages and the rules given; Discovery itself "
               "refuses to delete an algorithm a rule still uses.")
    elif ctx.has_usage:
        r.warn(f"Only {len(ctx.a.grid)} product grid(s) and the rules given were checked, not the review's sample of "
               "top pages: run discovery-ranking-algorithm-review and pass --review before deleting, unless the user "
               "accepts this. Discovery itself refuses to delete an algorithm a rule still uses.")
    definition = strip_editors({k: v for k, v in alg.items() if not k.startswith("_")})
    before = {"id": aid, "algoId": alg.get("algoId"), "name": alg.get("name"), "type": alg.get("type"),
              "status": alg.get("status"), "search_type": alg.get("searchType"), "definition": definition}
    extra = {"algorithm_id": aid}
    if undo_note:
        extra["undo_note"] = undo_note
    return [change(r, "delete", target, "delete_ranking_algorithm",
                   dict(ctx.base(), algorithm_id=aid, family=family_of(alg)), before, None, undo, "none",
                   "None if nothing assigns it; Discovery rejects the delete if a rule still does.", **extra)]


def build_batches(changes):
    """Creates and renames in batches of at most max_changes_per_batch; each live weight change and each delete on
    its own."""
    ready = [c for c in changes if c["status"] == "ready"]
    alone = [c for c in ready if c["kind"] == "delete" or c["live_impact"] == "live"]
    main = [c["n"] for c in ready if c not in alone]
    cap = RULES["max_changes_per_batch"]
    out = [main[i:i + cap] for i in range(0, len(main), cap)]
    return out + [[c["n"]] for c in sorted(alone, key=lambda c: (c["kind"] == "delete", c["n"]))]


ORDER = ("n", "request", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
         "impact_note", "problems", "warnings")


def cmd_plan(a):
    reqs = load(a.changes)
    if isinstance(reqs, dict) and isinstance(reqs.get("changes"), list):
        reqs = reqs["changes"]
    if not isinstance(reqs, list) or not all(isinstance(x, dict) for x in reqs):
        fail(f"{a.changes}: expected a JSON list of change objects, or {{\"changes\": [...]}}.")
    ctx = Context(a)
    changes, claimed = [], set()
    for i, raw in enumerate(reqs, 1):
        r = Req(i, raw)
        action = raw.get("action")
        if action not in ACTIONS:
            fail(f"change {i}: action must be one of {', '.join(ACTIONS)}.")
        key = raw.get("algorithm_id")
        if action != "create" and key is not None:
            if str(key) in claimed:
                r.block(f"Algorithm {key} already has a change in this plan: plan one change per algorithm.")
            claimed.add(str(key))
        outs = {"update": plan_update, "create": plan_create, "delete": plan_delete}[action](r, ctx)
        for o in outs:
            o["status"] = "blocked" if o["problems"] else "no_change" if o.pop("no_change", False) else "ready"
            if o["status"] != "ready":
                o["live_impact"] = "none"
        changes.extend(outs)
    for n, c in enumerate(changes, 1):
        c["n"] = n
        if c["kind"] == "create":
            for u in c["undo"]:
                u["payload"]["algorithm_id"] = f"<id returned by change {n}>"
    changes = [dict({k: c.get(k) for k in ORDER}, **{k: v for k, v in c.items() if k not in ORDER}) for c in changes]
    if ctx.exps is None and any(c["kind"] in ("update", "delete") for c in changes):
        fail("No --experiments file: read search_discovery_experiments (every page), save it and pass it with "
             "--experiments. A plan that changes or deletes an algorithm needs it.")
    return {"ok": True, "account": a.account, "environment": a.environment, "site_group_id": a.site_group_id,
            "usage_checked": ctx.has_usage, "usage_pages_checked": ctx.sampled + len(a.grid),
            "experiments_checked": ctx.exps is not None,
            "counts": {s: sum(1 for c in changes if c["status"] == s) for s in ("ready", "blocked", "no_change")},
            "changes": changes, "batches": build_batches(changes)}


# ---------------------------------------------------------------------------------------------
# Verify

def readback(path):
    """(record or None, error text or None): the read-back may hold a JSON error or bare error text."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        fail(f"{path}: can't read it ({type(e).__name__}).")
    try:
        data = json.loads(text)
    except ValueError:
        return None, text.strip() or "empty read-back"
    err = error_of(data)
    if err is not None:
        return None, err
    rec = unwrap(data)
    if not isinstance(rec, dict) or rec.get("id") is None:
        return None, "the read-back holds no algorithm"
    return rec, None


def weights_match(rec, want):
    _, table, _ = weight_table(rec)
    tol = Decimal(str(RULES["verify_tolerance"]))
    bad = sorted(s for s, v in want.items() if table.get(s) is None or abs(table[s] - dec(v)) > tol)
    extra = sorted(set(table) - set(want))
    return bad + extra


def cmd_verify(a):
    plan = read_json(a.plan)
    if not isinstance(plan, dict) or plan.get("ok") is not True or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan from algorithm_fix_plan.py plan.")
    by_n = {c.get("n"): c for c in plan["changes"] if isinstance(c, dict) and isinstance(c.get("n"), int)}
    files = dict(a.readback)
    results = []
    for n, path in sorted(files.items()):
        c = by_n.get(n)
        if c is None or c.get("status") != "ready" or not isinstance(c.get("payload"), dict):
            fail(f"--readback {n}: the plan has no ready change {n}.")
        rec, err = readback(path)
        aid = c.get("algorithm_id")
        row = {"n": n, "kind": c.get("kind"), "target": c.get("target")}
        if err is not None:
            kind = classify(err)
            if kind == "context":
                fail(f"{path}: {ACCOUNT_ERROR} Nothing was checked; stop here.")
            own = isinstance(aid, int) and re.search(r"(?<!\d)%d(?!\d)" % aid, str(err))
            if kind != "not_found" or not own:
                fail(f"{path}: the read-back failed ({redact(err)}) and doesn't say algorithm {aid} is missing, so "
                     f"change {n} can't be checked. Read it again with search_ranking_algorithms.")
            ok = c["kind"] == "delete"
            results.append(dict(row, result="gone", ok=ok,
                                detail="deleted, as planned" if ok else "the algorithm is gone, but this change didn't delete it"))
            continue
        if isinstance(aid, int) and int(rec["id"]) != aid:
            fail(f"{path}: the read-back is algorithm {rec['id']}, not algorithm {aid}.")
        if rec.get("deleted") is True:
            ok = c["kind"] == "delete"
            results.append(dict(row, result="gone", ok=ok, detail="marked deleted" + ("" if ok else ", but this change didn't delete it")))
            continue
        if c["kind"] == "delete":
            results.append(dict(row, result="not_in_place", ok=False, detail="the algorithm still exists: read it again in a minute"))
            continue
        bad = []
        p = c["payload"]
        for k in ("name", "description"):
            if k in p and str(rec.get(k) or "") != str(p[k]):
                bad.append(k)
        if c.get("expected_weights"):
            if c["kind"] == "create" or "weights" in p or "model_metadata" in p:
                bad += [f"weight {s}" for s in weights_match(rec, c["expected_weights"])]
        if c["kind"] == "create":
            if str(rec.get("type") or "").upper() != c.get("expected_type"):
                bad.append("type")
            if rec.get("searchType") != c.get("expected_search_type"):
                bad.append("search type")
            if default_status(rec):
                bad.append("status (the copy became the Default)")
        res = dict(row, result="not_in_place" if bad else "in_place", ok=not bad, status=rec.get("status"),
                   weights_synced=rec.get("weightFileStatus"),
                   detail="matches the plan" if not bad else "differs from the plan: " + ", ".join(bad))
        if c["kind"] == "create":
            res.update(algorithm_id=rec.get("id"), algoId=rec.get("algoId"))
        results.append(res)
    unchecked = sorted(n for n, c in by_n.items() if c.get("status") == "ready" and n not in files)
    return {"ok": True, "all_match": all(x["ok"] for x in results), "results": results, "not_checked": unchecked,
            "note": "A delete counts as gone only with a read-back; the changes in not_checked have none."}


def numbered_file(text):
    """N=FILE, split on the first '='."""
    n, sep, path = text.partition("=")
    if not sep or not path.strip():
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 3=readback-3.json")
    try:
        return int(n), path.strip()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a number")


def account_name(a):
    """The account name from --account-file (written by the assistant), or a plain --account."""
    if a.account_file:
        try:
            name = Path(a.account_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            fail(f"{a.account_file}: can't read it ({type(e).__name__}).")
    else:
        name = a.account.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            fail("--account takes only letters, digits, hyphens and underscores; write the name to a file and pass "
                 "--account-file instead.")
    if not name or "\n" in name:
        fail("The account name is empty or spans several lines.")
    return name


def write_out(path, obj):
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    except OSError as e:
        fail(f"{path}: can't write it ({type(e).__name__}).")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # algorithm and signal names can hold any character
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="turn the requested algorithm fixes into a plan")
    p.add_argument("--changes", required=True, help="JSON list of changes (references/change-format.md)")
    p.add_argument("--algorithms", action="append", required=True,
                   help="saved search_ranking_algorithms list, one per search_type (repeat)")
    p.add_argument("--detail", action="append", default=[],
                   help="saved search_ranking_algorithms detail of an algorithm the plan touches (repeat)")
    p.add_argument("--review", help="algorithm_review.py output from discovery-ranking-algorithm-review")
    p.add_argument("--grid", action="append", default=[], help="saved search_discovery_product_grid_insights result (repeat)")
    p.add_argument("--rule", action="append", default=[], type=numbered_file,
                   help="ID=FILE: a saved get_ranking_rule result (assignment or experiment bucket rule; repeat)")
    p.add_argument("--experiments", help="saved search_discovery_experiments listing (every page)")
    acct = p.add_mutually_exclusive_group(required=True)
    acct.add_argument("--account-file", help="a text file holding the Discovery account name the user confirmed")
    acct.add_argument("--account", help="the account name, only if it is plain letters, digits, hyphens and underscores")
    p.add_argument("--environment", required=True, choices=["staging", "production"],
                   help="where to write: staging first where the account has it; production needs its own plan")
    p.add_argument("--site-group-id", help="site group ID or site name, copied into every payload and undo")
    p.add_argument("--out", required=True, help="write the full plan here (keep it: it holds every undo)")
    v = sub.add_parser("verify", help="check the algorithms read back after writing")
    v.add_argument("--plan", required=True, help="the plan file written by plan --out")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_ranking_algorithms detail read back after writing change N (repeat)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    if a.cmd == "plan":
        a.account = account_name(a)
        result = cmd_plan(a)
        write_out(a.out, result)
        print(json.dumps(mask(result), indent=2, ensure_ascii=False))
    else:
        result = cmd_verify(a)
        if a.out:
            write_out(a.out, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
