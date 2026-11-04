#!/usr/bin/env python3
"""Plan Bloomreach Discovery facet rule changes before writing them, and check the writes afterwards.

Usage:
  python3 facet_rule_plan.py plan --changes changes.json --account NAME --environment staging|production
         [--rules list.json ...] [--rule ID=detail.json ...] [--experiments experiments.json]
         [--attributes attributes.json ...] [--categories categories.json] [--site-group-id ID] [--out plan.json]
  python3 facet_rule_plan.py verify --plan plan.json --readback N=readback.json [--readback ...] [--out result.json]

plan: --changes lists the facet changes wanted (references/change-format.md), from facet-optimizer or the user.
--rules are saved list_facets_global, list_site_search_facets and list_category_facets results (to find a rule
that already covers a target). Each --rule ID=FILE is a saved get_facet_rule result: the current state of a rule
the plan touches or might update. --experiments is a saved search_discovery_experiments listing. --attributes are
saved list_facet_attributes pages, --categories a saved list_categories result. Prints the plan in the shared
shape (docs/skill-authoring.md, "Plan files for write skills"): each change with its status (ready, blocked or
no_change), kind, before and after, the exact tool and payload, the undo, live impact, problems and warnings, and
the batches to confirm. A request for a target that already has a rule becomes an update of that rule, not a
duplicate. A new rule is created switched off and switched on as a separate change; every switch-on and every
delete is a batch of its own.

verify: --readback N=FILE is the get_facet_rule result read back after writing change N (for a create, by the ID
the create returned; for a delete, of the deleted rule). A call that errored is saved as
{"success": false, "error": "<the error text>"}, or as the bare error text. Reports each change as in_place,
not_in_place or gone. An error about the account, site, environment or access, or a 401, 403 or 429, stops.

It never calls Loomi Connect: the assistant makes each write, after confirmation. Standard library only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
KINDS = ("boost", "bury", "hide", "always_show")
PARAM = {"boost": "boosted_facets", "bury": "buried_facets", "hide": "excluded_facets",
         "always_show": "always_included_facets"}
SHOWS = ("boost", "bury", "always_show")
SCOPES = {"global": "global", "search": "sitesearch", "sitesearch": "sitesearch", "category": "category"}
MATCH_TYPES = ("EXACT_MATCH", "PHRASE_MATCH")
DASHBOARD_ONLY = ("merge", "rename", "ranges", "value_order", "aliases_facets", "value_configs_facets")
ACTIONS = ("set", "update", "enable", "disable", "delete")
URL = re.compile(r"https?://\S+|\b[\w-]+(?:\.[\w-]+)+/\S*", re.I)
CONTEXT_ERROR = re.compile(r"account|organi[sz]ation|project|access|permission|forbidden|unauthori[sz]ed|"
                           r"\b40[13]\b|\b429\b|rate.?limit|too many requests|site.?group|environment|merchant", re.I)
NOT_FOUND = re.compile(r"not.?found|\b404\b|does not exist|doesn't exist|no such", re.I)
ACCOUNT_ERROR = ("Loomi Connect returned an error about the account, site, environment or access; it isn't repeated "
                 "because it can list other accounts. Check the account name and access, then read again.")


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
        for key in ("rows", "items", "categories", "experiments"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data] if data else []
    if not isinstance(data, list):
        fail(f"{path}: expected a list of records.")
    return [r for r in data if isinstance(r, dict)]


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


QUERY_TYPES = {"global": "global", "sitesearch": "sitesearch", "search": "sitesearch", "keyword": "sitesearch",
               "query": "sitesearch", "category": "category", "categories": "category", "browse": "category"}


def key_of(query_type, query):
    raw = re.sub(r"[^a-z]", "", str(query_type or "").lower())
    qt = QUERY_TYPES.get(raw, raw)
    if qt == "global":
        return "global:*"
    return f"{qt}:{str(query or '').strip() if qt == 'category' else norm(query)}"


def as_rule_id(value, where):
    try:
        if isinstance(value, bool):
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        fail(f"{where}: expected a numeric rule ID, got {value!r}.")


def ordered(value):
    """A stored facet action as an ordered list: {facet: position} sorted by position, or a list as it is."""
    if isinstance(value, dict):
        def pos(kv):
            try:
                return (0, float(kv[1]), kv[0])
            except (TypeError, ValueError):
                return (1, 0.0, kv[0])
        return [k for k, _ in sorted(value.items(), key=pos)]
    if isinstance(value, list):
        return [str(x) for x in value if isinstance(x, str) and x]
    return []


def state(rec, path):
    """A rule's state from get_facet_rule detail or a list row. Editor names (user, lastModifiedBy) are never kept."""
    if not isinstance(rec, dict) or rec.get("id") is None:
        fail(f"{path}: not a facet rule record (no id). Save the whole get_facet_rule or list result.")
    rtype = str(rec.get("ruleType") or "facet").lower()
    queries = []
    for q in rec.get("queries") or []:
        if not isinstance(q, dict):
            fail(f"{path}: queries must be objects.")
        queries.append({k: q[k] for k in ("query", "queryType", "matchType") if k in q})
    items = rec.get("customizationItems")
    detail = isinstance(items, dict)
    facets = {k: ordered((items or {}).get(PARAM[k])) for k in KINDS}
    extra = {k: v for k, v in sorted((items or {}).items()) if k not in PARAM.values() and v not in (None, {}, [], "")}
    audiences = [a.get("id") for a in rec.get("audiences") or [] if isinstance(a, dict) and a.get("id") not in (None, -1)]
    return {"id": as_rule_id(rec["id"], path), "rule_type": rtype, "detail": detail, "name": rec.get("name"),
            "enabled": rec.get("enabled"), "queries": queries,
            "keys": sorted({key_of(q.get("queryType"), q.get("query")) for q in queries}),
            "facets": facets, "extra_items": extra, "audience_id": audiences[0] if audiences else None,
            "in_test": bool(rec.get("isLive") or rec.get("isAbTestLive")),
            "editable": rec.get("isEditable") is not False, "started_at": rec.get("startedAt"),
            "ended_at": rec.get("endedAt"), "sync_status": rec.get("syncStatus")}


def index_rules(list_paths, detail_pairs):
    rules = {}
    for p in list_paths:
        for r in rows(p):
            s = state(r, p)
            if s["rule_type"] != "facet":
                continue
            rules.setdefault(s["id"], s)
    for rid, p in detail_pairs:
        rec = unwrap(load(p))
        s = state(rec, p)
        if s["id"] != rid:
            fail(f"{p}: holds rule {s['id']}, not {rid}.")
        if s["rule_type"] != "facet":
            fail(f"{p}: rule {rid} is a {s['rule_type']} rule, not a facet rule.")
        if not s["detail"]:
            fail(f"{p}: rule {rid} has no customizationItems. Save the get_facet_rule result, not a list row.")
        rules[rid] = s
    return rules


def attributes(paths):
    if not paths:
        return None
    out = {}
    for p in paths:
        for r in rows(p):
            if r.get("name"):
                out[str(r["name"])] = r.get("facetable") is not False
    return out


def category_ids(path):
    if not path:
        return None
    ids = set()
    for r in rows(path):
        for k in ("categoryId", "category_id", "id"):
            if r.get(k) not in (None, ""):
                ids.add(str(r[k]).strip())
    return ids


def running_experiments(path):
    """Experiments that aren't known to be finished (status missing, or not in finished_statuses): each with its
    name, rule IDs and target keys."""
    if not path:
        return None
    finished = {norm(x) for x in RULES["finished_statuses"]}
    out = []
    for e in rows(path):
        status = norm(e.get("experimentStatus") or e.get("status"))
        if status and status in finished:
            continue  # anything else, or no status at all, may be running
        ids, keys = set(), set()
        for b in e.get("buckets") or []:
            info = (b or {}).get("ruleIdentifierInfo") or {}
            if info.get("id") is not None:
                ids.add(str(info["id"]))
            for q in info.get("query") or info.get("queries") or []:
                if isinstance(q, dict):
                    keys.add(key_of(q.get("queryType"), q.get("query")))
        out.append({"name": str(e.get("experimentName") or e.get("name") or e.get("id")), "ids": ids, "keys": keys})
    return sorted(out, key=lambda x: x["name"])


class Req:
    def __init__(self, n, raw):
        self.n, self.raw, self.problems, self.warnings = n, raw, [], []

    def block(self, msg):
        self.problems.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def base(a):
    p = {"account_name": a.account, "environment": a.environment}
    if a.site_group_id:
        p["site_group_id"] = a.site_group_id
    return p


def names_of(entries, where):
    out = []
    for e in entries or []:
        name = e.get("facet") if isinstance(e, dict) else e
        if not isinstance(name, str) or not name.strip():
            fail(f"{where}: facet names must be non-empty strings, got {e!r}.")
        out.append(name.strip())
    return out


def apply_edits(r, before):
    """The facet lists after the request's replace, remove and add edits."""
    raw, f = r.raw, {k: list(before[k]) for k in KINDS}
    for section in ("facets", "add", "remove"):
        val = raw.get(section)
        if val is None:
            continue
        if not isinstance(val, dict) or set(val) - set(KINDS) - ({"all"} if section == "remove" else set()):
            fail(f"change {r.n}: {section} must be an object with keys from {', '.join(KINDS)}"
                 + (" or all" if section == "remove" else "") + ".")
    for k, v in (raw.get("facets") or {}).items():
        f[k] = list(dict.fromkeys(names_of(v, f"change {r.n} facets.{k}")))
    remove = raw.get("remove") or {}
    for k, v in remove.items():
        gone = set(names_of(v, f"change {r.n} remove.{k}"))
        for kind in (KINDS if k == "all" else (k,)):
            f[kind] = [x for x in f[kind] if x not in gone]
    for k in KINDS:
        for e in (raw.get("add") or {}).get(k) or []:
            name = names_of([e], f"change {r.n} add.{k}")[0]
            pos = e.get("position") if isinstance(e, dict) else None
            others = {"hide": SHOWS, "boost": ("bury", "hide"), "bury": ("boost", "hide"), "always_show": ("hide",)}[k]
            for o in others:
                if name in f[o]:
                    f[o] = [x for x in f[o] if x != name]
                    r.warn(f"'{name}' is taken out of {o} because it's now in {k}.")
            if k in ("boost", "bury"):
                f[k] = [x for x in f[k] if x != name]
                if pos is not None and (not isinstance(pos, int) or isinstance(pos, bool) or pos < 1):
                    fail(f"change {r.n} add.{k}: position must be a whole number from 1, got {pos!r}.")
                f[k].insert(len(f[k]) if pos is None else min(pos - 1, len(f[k])), name)
            elif name not in f[k]:
                f[k].append(name)
    for k in ("boost", "bury"):
        for name in before[k]:
            if name not in f[k] and name not in f["hide"] and name in f["always_show"] and k not in (raw.get("facets") or {}) \
                    and name not in set(names_of((raw.get("remove") or {}).get("always_show"), "remove")):
                r.warn(f"'{name}' is no longer {'boosted' if k == 'boost' else 'buried'} but stays in always_show; "
                       "add it to remove.always_show to drop it.")
    return f


def check_facets(r, before, after, attrs):
    for name in sorted(set(after["hide"]) & set(after["boost"] + after["bury"] + after["always_show"])):
        r.block(f"'{name}' is both hidden and shown. Pick one.")
    for name in sorted(set(after["boost"]) & set(after["bury"])):
        r.block(f"'{name}' is both boosted and buried. Pick one.")
    for k in KINDS:
        new = [x for x in after[k] if x not in before[k]]
        for name in new:
            low = name.lower()
            if k in SHOWS and any(w in low for w in RULES["never_show_words"]):
                r.block(f"'{name}' looks commercial or internal (never_show_words): it can be hidden, never shown.")
            if attrs is None:
                continue
            if name not in attrs:
                (r.warn if k == "hide" else r.block)(
                    f"'{name}' isn't in list_facet_attributes" + (": hiding it does nothing yet, but is harmless."
                                                                   if k == "hide" else ": check the exact name."))
            elif k in SHOWS and not attrs[name]:
                r.block(f"'{name}' isn't facetable, so it can't be shown.")
    if attrs is None and any(x not in before[k] for k in KINDS for x in after[k]):
        r.warn("Facet names weren't checked: pass the saved list_facet_attributes pages with --attributes.")


def check_tests(r, rid, keys, rule, exps):
    if rule and rule["in_test"]:
        r.block(f"Rule {rid} is in a running A/B test (isLive): Discovery blocks the change. End the test first.")
    for e in exps or []:
        hits = []
        if rid is not None and str(rid) in e["ids"]:
            hits.append(f"rule {rid}")
        hits += [label([k]) for k in keys if k in e["keys"]]
        if "global:*" in e["keys"] and "global:*" not in keys and keys:
            hits.append("every page (it tests a global rule)")
        if "global:*" in keys:
            hits.append("pages a global change affects")
        if hits:
            r.block(f"Running experiment '{e['name']}' covers {', '.join(sorted(set(hits)))}: wait for the test to end "
                    "(discovery-experiment-readout), then plan again.")


def label(keys):
    out = []
    for k in keys:
        qt, q = k.split(":", 1)
        out.append("all pages (global)" if qt == "global" else f"search '{q}'" if qt == "sitesearch" else f"category {q}")
    return ", ".join(out)


def change(r, kind, target, tool, payload, before, after, undo, live, **extra):
    return dict({"request": r.n, "reason": r.raw.get("reason"), "kind": kind, "target": target, "tool": tool,
                 "payload": payload, "before": before, "after": after, "undo": undo, "live_impact": live,
                 "problems": r.problems, "warnings": r.warnings}, **extra)


def shown(rule, facets=None):
    return {"enabled": rule.get("enabled"), "name": rule.get("name"), "audience_id": rule.get("audience_id"),
            "targets": rule.get("keys"), "facets": facets if facets is not None else rule["facets"]}


def requested_keys(r, cats):
    raw = r.raw
    scope = SCOPES.get(str(raw.get("scope") or "").lower())
    if not scope:
        fail(f"change {r.n}: scope must be global, search or category.")
    if scope == "global":
        return scope, [{"query": "*", "queryType": "global", "matchType": "EXACT_MATCH"}], ["global:*"]
    targets = raw.get("targets", [raw["target"]] if "target" in raw else None)
    if not isinstance(targets, list) or not targets or not all(isinstance(t, (str, int)) and str(t).strip() for t in targets):
        fail(f"change {r.n}: a {raw.get('scope')} change needs targets (a list of queries or category IDs).")
    match = str(raw.get("match_type") or "EXACT_MATCH").upper()
    if match not in MATCH_TYPES:
        fail(f"change {r.n}: match_type must be EXACT_MATCH or PHRASE_MATCH.")
    queries = [{"query": str(t).strip(), "queryType": scope, "matchType": match if scope == "sitesearch" else "EXACT_MATCH"}
               for t in targets]
    if scope == "category" and cats is not None:
        for q in queries:
            if q["query"] not in cats and not q["query"].startswith("brg_dyn_"):
                r.warn(f"Category {q['query']} isn't in list_categories: the rule would match no page. Check the ID.")
    return scope, queries, sorted({key_of(q["queryType"], q["query"]) for q in queries})


def plan_set(r, a, rules, exps, attrs, cats, claimed):
    raw = r.raw
    for k in DASHBOARD_ONLY:
        if k in raw:
            r.block(f"'{k}' (value merges, renames, ranges and value order) can't be set through the API: make it in "
                    "the Discovery dashboard.")
    rid = raw.get("rule_id")
    rule = None
    if rid is not None:
        rid = as_rule_id(rid, f"change {r.n} rule_id")
        rule = rules.get(rid)
        if not rule or not rule["detail"]:
            r.block(f"Read rule {rid} with get_facet_rule and pass it with --rule {rid}=<file>: the plan needs its "
                    "current facets for the change and the undo.")
            return [change(r, "update", f"facet rule {rid}", "update_facet_rule", None, None, None, [], "none")]
        keys = rule["keys"]
        if raw.get("scope"):
            _, _, want_keys = requested_keys(r, cats)
            if want_keys != keys:
                r.block(f"Rule {rid} covers {label(keys)}, not {label(want_keys)}. This skill doesn't retarget rules "
                        "(discovery-rule-cleanup does): leave out scope and targets, or drop rule_id.")
    else:
        if raw.get("action") == "update":
            fail(f"change {r.n}: update needs a rule_id; use set to find or create the rule for a target.")
        scope, queries, keys = requested_keys(r, cats)
        audience = raw.get("audience_id")
        overlap = sorted((x for x in rules.values() if set(x["keys"]) & set(keys)), key=lambda x: x["id"])
        no_detail = [x["id"] for x in overlap if not x["detail"]]
        if no_detail:
            r.block("Rule(s) " + ", ".join(map(str, no_detail)) + f" already cover {label(keys)}: read each with "
                    "get_facet_rule and pass it with --rule, so the plan can update it instead of adding a duplicate.")
            return [change(r, "update", label(keys), "update_facet_rule", None, None, None, [], "none")]
        same_aud = [x for x in overlap if x["audience_id"] == audience]
        for x in overlap:
            if x not in same_aud:
                r.warn(f"Rule {x['id']} also covers {label(sorted(set(x['keys']) & set(keys)))} for a different audience.")
        exact = [x for x in same_aud if x["keys"] == keys]
        if len(same_aud) == 1 and exact:
            rule, rid = exact[0], exact[0]["id"]
            r.warn(f"Rule {rid} already covers {label(keys)}: the plan updates it rather than adding a duplicate.")
        elif same_aud:
            r.block("Rule(s) " + ", ".join(str(x["id"]) for x in same_aud) + f" already cover part or all of "
                    f"{label(keys)} for the same audience. Update one by rule_id, change the targets to match it, or "
                    "clean up duplicates first (discovery-rule-cleanup).")
            return [change(r, "update", label(keys), "update_facet_rule", None, None, None, [], "none")]
    if rule is None:
        return plan_create(r, a, keys, queries, exps, attrs, claimed)
    return plan_update(r, a, rid, rule, exps, attrs, claimed)


def plan_create(r, a, keys, queries, exps, attrs, claimed):
    raw = r.raw
    empty = {k: [] for k in KINDS}
    after = apply_edits(r, empty)
    check_facets(r, empty, after, attrs)
    check_tests(r, None, keys, None, exps)
    if tuple(keys) in claimed:
        r.block(f"Another change in this plan already targets {label(keys)}. Plan one change per target.")
    claimed.add(tuple(keys))
    if not any(after.values()):
        r.block("The new rule would have no facet actions: give facets or add.")
    payload = dict(base(a), queries=queries, enabled=False)
    for k, v in (("name", raw.get("name")), ("audience_id", raw.get("audience_id"))):
        if v not in (None, ""):
            payload[k] = v
    for k in KINDS:
        if after[k]:
            payload[PARAM[k]] = after[k]
    target = "new facet rule for " + label(keys)
    new = {"enabled": False, "name": raw.get("name"), "audience_id": raw.get("audience_id"), "targets": keys,
           "facets": after}
    out = [change(r, "create", target, "create_facet_rule", payload, None, new,
                  [{"tool": "delete_facet_rule", "payload": dict(base(a), rule_id="<id returned by the create>"),
                    "note": "Deleting the new rule removes it completely."}], "none")]
    if raw.get("enabled") is not False:
        on = Req(r.n, r.raw)  # its own change and yes; the create carries the checks
        out.append(change(on, "enable", target, "update_facet_rule",
                          dict(base(a), rule_id="<id returned by the create>", enabled=True),
                          {"enabled": False}, dict(new, enabled=True),
                          [{"tool": "update_facet_rule", "payload": dict(base(a), rule_id="<id returned by the create>",
                                                                          enabled=False)}],
                          "live", needs="create"))
    return out


def guard(r, rid, rule, exps, claimed):
    check_tests(r, rid, rule["keys"], rule, exps)
    if not rule["editable"]:
        r.block(f"Rule {rid} is marked not editable.")
    if rid in claimed:
        r.block(f"Rule {rid} already has a change in this plan: plan one change per rule (replace a delete with a "
                "disable, don't add both).")
    claimed.add(rid)


def plan_update(r, a, rid, rule, exps, attrs, claimed):
    raw = r.raw
    after_f = apply_edits(r, rule["facets"])
    check_facets(r, rule["facets"], after_f, attrs)
    guard(r, rid, rule, exps, claimed)
    target = f"facet rule {rid} ({label(rule['keys'])})"
    payload, undo, notes = dict(base(a), rule_id=rid), dict(base(a), rule_id=rid), []
    for k in KINDS:
        if after_f[k] != rule["facets"][k]:
            payload[PARAM[k]], undo[PARAM[k]] = after_f[k], rule["facets"][k]
            if not after_f[k]:
                r.warn(f"Empties {PARAM[k]}: the tool replaces the list, but sending an empty one hasn't been tested. "
                       "verify shows whether it cleared.")
            if not rule["facets"][k]:
                notes.append(f"{PARAM[k]} was empty before; the undo sends an empty list, which hasn't been tested. "
                             "If it doesn't clear, remove the entries in the dashboard.")
    after = dict(shown(rule, after_f))
    if raw.get("name") not in (None, "") and raw["name"] != rule["name"]:
        payload["name"], undo["name"], after["name"] = raw["name"], rule["name"], raw["name"]
        if rule["name"] is None:
            notes.append("The rule had no name: update_facet_rule can't clear one (null keeps it).")
    if raw.get("audience_id") is not None and raw["audience_id"] != rule["audience_id"]:
        payload["audience_id"], after["audience_id"] = raw["audience_id"], raw["audience_id"]
        if rule["audience_id"] is None:
            notes.append("The rule had no audience: update_facet_rule can't clear one, so undo it in the dashboard.")
        else:
            undo["audience_id"] = rule["audience_id"]
    switch_on = raw.get("enabled") is True and rule["enabled"] is not True
    if raw.get("enabled") is False and rule["enabled"] is not False:
        payload["enabled"], undo["enabled"], after["enabled"] = False, True, False
    changed = set(payload) - set(base(a)) - {"rule_id"}
    out = []
    if changed:
        kind = "disable" if changed == {"enabled"} else "update"
        live = "live" if rule["enabled"] or kind == "disable" else "none"
        undo_steps = [{"tool": "update_facet_rule", "payload": undo}] if set(undo) - set(base(a)) - {"rule_id"} else []
        extra = {"undo_note": " ".join(notes)} if notes else {}
        out.append(change(r, kind, target, "update_facet_rule", payload, shown(rule), after, undo_steps, live, **extra))
    if switch_on:
        on = Req(r.n, r.raw) if out else r
        if out:
            on.problems = r.problems
        out.append(change(on, "enable", target, "update_facet_rule", dict(base(a), rule_id=rid, enabled=True),
                          {"enabled": rule["enabled"]}, dict(after, enabled=True),
                          [{"tool": "update_facet_rule", "payload": dict(base(a), rule_id=rid, enabled=False)}], "live"))
    if not out:
        r.warn("The rule already has these settings.")
        out.append(change(r, "update", target, "update_facet_rule", None, shown(rule), shown(rule), [], "none",
                          no_change=True))
    return out


def plan_toggle(r, a, rules, exps, claimed):
    raw, on = r.raw, r.raw["action"] == "enable"
    rid = as_rule_id(raw.get("rule_id"), f"change {r.n} rule_id")
    rule = rules.get(rid)
    kind, target = raw["action"], f"facet rule {rid}"
    if not rule or not rule["detail"]:
        r.block(f"Read rule {rid} with get_facet_rule and pass it with --rule {rid}=<file>.")
        return [change(r, kind, target, "update_facet_rule", None, None, None, [], "none")]
    target = f"facet rule {rid} ({label(rule['keys'])})"
    guard(r, rid, rule, exps, claimed)
    if rule["enabled"] is on:
        r.warn(f"Already {'on' if on else 'off'}.")
        return [change(r, kind, target, "update_facet_rule", None, shown(rule), shown(rule), [], "none", no_change=True)]
    return [change(r, kind, target, "update_facet_rule", dict(base(a), rule_id=rid, enabled=on), shown(rule),
                   dict(shown(rule), enabled=on),
                   [{"tool": "update_facet_rule", "payload": dict(base(a), rule_id=rid, enabled=not on)}], "live")]


def recreate(a, rule):
    """Undo of a delete: recreate switched off from the saved state, then switch on (its own yes) if it was on."""
    args = dict(base(a), queries=rule["queries"], enabled=False)
    for k in KINDS:
        if rule["facets"][k]:
            args[PARAM[k]] = rule["facets"][k]
    for k, v in (("name", rule["name"]), ("audience_id", rule["audience_id"]), ("started_at", rule["started_at"]),
                 ("ended_at", rule["ended_at"])):
        if v not in (None, ""):
            args[k] = v
    if rule["extra_items"]:
        args["facet_items"] = [{"customizationType": k, "customizationValue": json.dumps(v, sort_keys=True)}
                               for k, v in rule["extra_items"].items()]
    steps = [{"tool": "create_facet_rule", "payload": args,
              "note": "Recreated switched off, with a new ID. facet_items carries value merges, renames and ranges; "
                      "check them in the dashboard afterwards."}]
    if rule["enabled"]:
        steps.append({"tool": "update_facet_rule", "payload": dict(base(a), rule_id="<id returned by the recreate>",
                                                                   enabled=True),
                      "note": "Switches it back on: confirm it separately, as for any switch-on."})
    return steps


def plan_delete(r, a, rules, exps, claimed):
    rid = as_rule_id(r.raw.get("rule_id"), f"change {r.n} rule_id")
    rule = rules.get(rid)
    if not rule or not rule["detail"]:
        r.block(f"Read rule {rid} with get_facet_rule and pass it with --rule {rid}=<file>: its full state is the "
                "only way to rebuild it after a delete.")
        return [change(r, "delete", f"facet rule {rid}", "delete_facet_rule", None, None, None, [], "none")]
    guard(r, rid, rule, exps, claimed)
    r.warn("Deletes are permanent. The undo recreates the rule switched off, with a new ID. Switching it off is the "
           "reversible alternative.")
    if rule["enabled"]:
        r.warn("The rule is on: shoppers lose its facet settings at once. Consider a disable first.")
    before = dict(shown(rule), queries=rule["queries"], extra_items=rule["extra_items"],
                  started_at=rule["started_at"], ended_at=rule["ended_at"])
    return [change(r, "delete", f"facet rule {rid} ({label(rule['keys'])})", "delete_facet_rule",
                   dict(base(a), rule_id=rid), before, None, recreate(a, rule), "live" if rule["enabled"] else "none")]


def build_batches(changes):
    """Ordinary ready changes in batches of at most max_changes_per_batch; each switch-on and delete on its own."""
    ready = [c for c in changes if c["status"] == "ready"]
    alone = [c for c in ready if c["kind"] in ("enable", "delete")]
    main = [c["n"] for c in ready if c not in alone]
    cap = RULES["max_changes_per_batch"]
    out = [main[i:i + cap] for i in range(0, len(main), cap)]
    return out + [[c["n"]] for c in sorted(alone, key=lambda c: (c["kind"] == "delete", c["n"]))]


ORDER = ("n", "request", "status", "kind", "target", "tool", "payload", "before", "after", "undo", "live_impact",
         "problems", "warnings")


def cmd_plan(a):
    reqs = load(a.changes)
    if isinstance(reqs, dict) and isinstance(reqs.get("changes"), list):
        reqs = reqs["changes"]
    if not isinstance(reqs, list) or not all(isinstance(x, dict) for x in reqs):
        fail(f"{a.changes}: expected a JSON list of change objects, or {{\"changes\": [...]}}.")
    rules = index_rules(a.rules, a.rule)
    exps = running_experiments(a.experiments)
    attrs = attributes(a.attributes)
    cats = category_ids(a.categories)
    changes, claimed = [], set()
    for i, raw in enumerate(reqs, 1):
        r = Req(i, raw)
        action = raw.get("action")
        if action not in ACTIONS:
            fail(f"change {i}: action must be one of {', '.join(ACTIONS)}.")
        if action in ("set", "update"):
            outs = plan_set(r, a, rules, exps, attrs, cats, claimed)
        elif action in ("enable", "disable"):
            outs = plan_toggle(r, a, rules, exps, claimed)
        else:
            outs = plan_delete(r, a, rules, exps, claimed)
        if r.problems:
            outs = [o for o in outs if not o.get("needs")]  # a blocked create has nothing to switch on
        for o in outs:
            o["status"] = "blocked" if o["problems"] else "no_change" if o.pop("no_change", False) else "ready"
            if o["status"] != "ready":
                o["live_impact"] = "none"
        changes.extend(outs)
    for n, c in enumerate(changes, 1):
        c["n"] = n
    for c in changes:
        if c["kind"] == "create":
            for u in c["undo"]:
                u["payload"]["rule_id"] = f"<id returned by change {c['n']}>"
        if c.pop("needs", None) == "create":
            first = next(x["n"] for x in changes if x["request"] == c["request"] and x["kind"] == "create")
            c["after_change"] = first
            for p in [c["payload"]] + [u["payload"] for u in c["undo"]]:
                p["rule_id"] = f"<id returned by change {first}>"
    changes = [dict({k: c.get(k) for k in ORDER}, **{k: v for k, v in c.items() if k not in ORDER}) for c in changes]
    result = {"ok": True, "account": a.account, "environment": a.environment, "site_group_id": a.site_group_id,
              "experiments_checked": exps is not None, "attributes_checked": attrs is not None,
              "counts": {s: sum(1 for c in changes if c["status"] == s) for s in ("ready", "blocked", "no_change")},
              "changes": changes, "batches": build_batches(changes)}
    if exps is None:
        if result["counts"]["ready"]:
            fail("No --experiments file: read search_discovery_experiments (all statuses, every page), save it and "
                 "pass it with --experiments. A plan with ready changes needs it.")
        result["warning"] = "No --experiments file: running tests weren't checked."
    return result


def readback(path):
    """(rule state or None, error text or None) for a read-back file, which may hold a JSON error or bare text."""
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
        return None, "the read-back holds no rule"
    return state(rec, path), None


def comparable(f):
    """Facet lists as verify compares them: order matters for boost and bury; always_show leaves out boosted and
    buried facets (Discovery stores 'boost and always show' in both lists)."""
    shown_ = set(f["boost"]) | set(f["bury"])
    return {"boost": list(f["boost"]), "bury": list(f["bury"]), "hide": sorted(set(f["hide"])),
            "always_show": sorted(set(f["always_show"]) - shown_)}


def cmd_verify(a):
    plan = read_json(a.plan)
    if not isinstance(plan, dict) or plan.get("ok") is not True or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan from facet_rule_plan.py plan.")
    by_n = {c.get("n"): c for c in plan["changes"] if isinstance(c, dict) and isinstance(c.get("n"), int)}
    results = []
    for n, path in sorted(dict(a.readback).items()):
        c = by_n.get(n)
        if c is None or c.get("status") != "ready" or not isinstance(c.get("payload"), dict):
            fail(f"--readback {n}: the plan has no ready change {n}.")
        got, err = readback(path)
        rid = c["payload"].get("rule_id")
        row = {"n": n, "kind": c.get("kind"), "target": c.get("target")}
        if err is not None:
            kind = classify(err)
            if kind == "context":
                fail(f"{path}: {ACCOUNT_ERROR} Nothing was checked; stop here.")
            if kind != "not_found" or not (isinstance(rid, int) and re.search(r"(?<!\d)%d(?!\d)" % rid, str(err))):
                fail(f"{path}: the read-back failed ({redact(err)}) and doesn't say rule {rid} is missing, so change "
                     f"{n} can't be checked. Read the rule again with get_facet_rule.")
            ok = c["kind"] == "delete"
            results.append(dict(row, result="gone", ok=ok,
                                detail="deleted, as planned" if ok else "the rule is gone, but this change didn't delete it"))
            continue
        if got["rule_type"] != "facet":
            fail(f"{path}: the read-back is a {got['rule_type']} rule, not a facet rule.")
        if isinstance(rid, int) and got["id"] != rid:
            fail(f"{path}: the read-back is rule {got['id']}, not rule {rid}.")
        if not got["detail"]:
            fail(f"{path}: the read-back has no customizationItems; read it with get_facet_rule.")
        if c["kind"] == "delete":
            results.append(dict(row, result="not_in_place", ok=False,
                                detail="the rule still exists: read it again in a minute"))
            continue
        want = c.get("after") or {}
        bad = []
        if want.get("enabled") is not None and want["enabled"] != got["enabled"]:
            bad.append("enabled")
        if want.get("facets"):
            w, g = comparable(want["facets"]), comparable(got["facets"])
            bad += [k for k in KINDS if w[k] != g[k]]
        if want.get("targets") and want["targets"] != got["keys"]:
            bad.append("targets")
        for k in ("name", "audience_id"):
            if want.get(k) is not None and want[k] != got[k]:
                bad.append(k)
        res = dict(row, result="not_in_place" if bad else "in_place", ok=not bad, sync_status=got["sync_status"],
                   detail="matches the plan" if not bad else "differs from the plan: " + ", ".join(bad))
        if not isinstance(rid, int):
            res["rule_id"] = got["id"]
        results.append(res)
    unchecked = sorted(n for n, c in by_n.items() if c.get("status") == "ready" and n not in dict(a.readback))
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


def emit(obj, out):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        try:
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{out}: can't write it ({type(e).__name__}).")
    print(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # facet and query names can hold any character
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="turn the requested facet changes into a plan")
    p.add_argument("--changes", required=True, help="JSON list of changes (references/change-format.md)")
    p.add_argument("--rules", action="append", default=[],
                   help="saved list_facets_global, list_site_search_facets or list_category_facets result (repeat)")
    p.add_argument("--rule", action="append", default=[], type=numbered_file,
                   help="ID=FILE: a saved get_facet_rule result for a rule the plan touches (repeat)")
    p.add_argument("--experiments", help="saved search_discovery_experiments listing (all statuses)")
    p.add_argument("--attributes", action="append", default=[], help="saved list_facet_attributes page (repeat)")
    p.add_argument("--categories", help="saved list_categories result, to check category IDs")
    p.add_argument("--account", required=True, help="the Discovery account name the user confirmed")
    p.add_argument("--environment", required=True, choices=["staging", "production"],
                   help="where to write: staging first where the account has it; production needs its own plan")
    p.add_argument("--site-group-id", help="site group ID or site name, copied into every payload and undo")
    p.add_argument("--out", help="also write the plan to this file (keep it: it holds the undo)")
    v = sub.add_parser("verify", help="check the rules read back after writing")
    v.add_argument("--plan", required=True, help="the plan file written by plan --out")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the get_facet_rule result read back after writing change N (repeat)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    emit(cmd_plan(a) if a.cmd == "plan" else cmd_verify(a), a.out)


if __name__ == "__main__":
    main()
