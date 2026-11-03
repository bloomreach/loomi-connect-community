#!/usr/bin/env python3
"""Plan and verify changes to Bloomreach Discovery autosuggest exclusion rules.

Usage:
  python3 exclusion_plan.py plan --request request.json --rules rules.json [--rules page2.json]
         [--suggestions before.json] [--queries queries.json ...] --account NAME
         --environment staging|production [--site-group-id ID] [--out plan.json]
  python3 exclusion_plan.py verify --plan plan.json --rules rules_after.json [--rules ...]
         [--suggestions after.json] [--applied 1,2] [--created 6=106 ...] [--out verify.json]

request.json lists what to change, as {"changes": [...]} or a plain list. Each change is one of:
  {"action": "exclude",   "keyword": "dress fabric", "reason": "..."}   hide a suggestion
  {"action": "unexclude", "keyword": "scharf", "reason": "..."}         stop hiding one
  {"action": "disable" | "enable" | "delete", "rule_id": 12, "reason": "..."}
Optional top-level keys: "rule_name" for new rules, "domain_key" to scope new rules to one catalog,
and "add_to_rule_id" to add new keywords to an existing rule instead of creating one.

--rules are saved search_autosuggest_exclusion_rules results (list pages or one rule's detail): the state
before the change. --suggestions maps each prefix to what get_autosuggest_results returned for it
({"dr": ["dress", "dress fabric"]}). --queries are saved get_discovery_query_performance results, used to
warn before excluding a search shoppers really use.

plan prints the plan file every write skill in this repo uses (docs/skill-authoring.md, "Plan files for
write skills"): each change with its status (ready, blocked or no_change), kind, tool, exact payload,
before, after, undo, live impact, problems and warnings; and the batches of ready changes to confirm one
at a time. New rules are created disabled and switched on by a separate enable; enables and deletes are
each a batch of their own. Removing a keyword from a rule that would be left empty disables the rule
rather than deleting it. It also gives a before/after preview of the suggestions.

verify compares a fresh read of the rules (and suggestions) with the plan and reports each ready change
as in_place, not_in_place or gone. New rules are matched by the ID their create returned (--created
N=ID), never by name. A not-found read-back counts as gone.

Thresholds are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
TOOLS = {"create": "create_autosuggest_exclusion_rule", "update": "update_autosuggest_exclusion_rule",
         "delete": "delete_autosuggest_exclusion_rule"}
NOT_FOUND = re.compile(r"not.?found|404|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"account|site|catalog|domain|environment|workspace", re.I)  # a "not found" about these isn't the item
SYNCED = ("", "synced", "success", "completed", "none")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat. An unknown account_name makes some Discovery tools list every
    account the user can access, so any error about an account is replaced, never echoed."""
    text = str(err or "no error text")
    if "account" in text.lower():
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


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


def read_raw(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def error_of(data):
    """The error record of a success:false result, or None."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return d
    return None


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def read(path):
    """A saved tool result, unwrapped from {"result": ...} and checked for success: false."""
    data = read_raw(path)
    err = error_of(data)
    if err:
        fail(f"{path}: Loomi Connect returned an error: {tool_error(err.get('error'))} "
             "This check couldn't run; don't treat it as 'nothing found'.")
    return unwrap(data)


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def rule_record(r, path):
    """One exclusion rule in a fixed shape, whatever the tool called its fields."""
    rid = r.get("id", r.get("ruleId", r.get("rule_id")))
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        fail(f"{path}: an exclusion rule has no numeric id (field 'id').")
    kw = r.get("keywords", r.get("keyword", []))
    if isinstance(kw, str):
        kw = [k for k in (x.strip() for x in kw.split(",")) if k]
    if not isinstance(kw, list):
        fail(f"{path}: rule {rid} has keywords that aren't a list (field 'keywords').")
    enabled = r.get("enabled", r.get("isEnabled", r.get("active")))
    return {"id": rid, "name": r.get("name") or r.get("ruleName") or r.get("rule_name") or "",
            "keywords": [str(k) for k in kw], "enabled": bool(enabled),
            "domain_key": r.get("domainKey", r.get("domain_key")), "note": r.get("note") or "",
            "sync_status": r.get("syncStatus", r.get("sync_status"))}


def rules_from(data, path, rules):
    """Add the rules in one unwrapped result to `rules`; True when the result was a list."""
    items = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = items.get("rules", items.get("items", [items]))
    if not isinstance(items, list):
        fail(f"{path}: not an exclusion rule list or detail (field 'data').")
    for r in items:
        if isinstance(r, dict) and r:
            rec = rule_record(r, path)
            rules[rec["id"]] = rec
    return isinstance(data, dict) and isinstance(data.get("data"), list) or isinstance(data, list)


def load_rules(paths):
    rules = {}
    for p in paths:
        rules_from(read(p), p, rules)
    return rules


def load_readback(paths):
    """Rules read after the writes. A not-found response counts as an empty read (the rule is gone);
    any other error stops. Returns (rules, whether any file was a full list, whether any was not found)."""
    rules, listed, not_found = {}, False, False
    for p in paths:
        data = read_raw(p)
        err = error_of(data)
        if err:
            text = str(err.get("error") or "")
            if NOT_FOUND.search(text) and not CONTEXT_ERROR.search(text):  # an unknown account or site isn't a deleted rule
                not_found = True
                continue
            fail(f"{p}: Loomi Connect returned an error: {tool_error(err.get('error'))} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        body = unwrap(data)
        is_list = rules_from(body, p, rules)
        # A list only proves a rule is gone when it's the whole list: one page of several proves nothing.
        if is_list and not complete_list(body):
            fail(f"{p}: this is one page of the exclusion rule list. Read every page (or the deleted rule's own "
                 "detail) so a delete can be checked.")
        listed = is_list or listed
    return rules, listed, not_found


def complete_list(body):
    """True unless the list response says there are more pages or more rules than it holds."""
    if not isinstance(body, dict):
        return True
    items = body.get("data") if isinstance(body.get("data"), list) else []
    if body.get("has_more") or body.get("next_offset") not in (None, "", 0) and body.get("has_more") is not False:
        return False
    for key in ("total", "count", "total_count"):
        if isinstance(body.get(key), int) and body[key] > len(items):
            return False
    return True


def load_suggestions(path):
    if not path:
        return {}
    data = read(path)
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        fail(f"{path}: expected {{\"prefix\": [suggestions, ...]}}, one list per prefix.")
    return {str(k): [str(s) for s in v] for k, v in data.items()}


def load_queries(paths):
    rows = {}
    for p in paths:
        data = read(p)
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("rows", [])
        if not isinstance(items, list):
            fail(f"{p}: not a query performance result (field 'rows').")
        for r in items:
            if isinstance(r, dict) and r.get("query"):
                s = number(r.get("browse_sessions"))
                rows[norm(r["query"])] = {"query": r["query"], "sessions": s if s is not None else number(r.get("visits")),
                                          "revenue": number(r.get("revenue"))}
    return rows


def load_request(path):
    data = read(path)
    if isinstance(data, list):
        data = {"changes": data}
    if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
        fail(f"{path}: expected {{\"changes\": [...]}} or a list of changes.")
    for i, c in enumerate(data["changes"], 1):
        if not isinstance(c, dict) or c.get("action") not in ("exclude", "unexclude", "disable", "enable", "delete"):
            fail(f"{path}: change {i} needs 'action': exclude, unexclude, disable, enable or delete.")
        if c["action"] in ("exclude", "unexclude") and not str(c.get("keyword") or "").strip():
            fail(f"{path}: change {i} ({c['action']}) needs a 'keyword'.")
        if c["action"] in ("disable", "enable", "delete"):
            try:
                c["rule_id"] = int(c.get("rule_id"))
            except (TypeError, ValueError):
                fail(f"{path}: change {i} ({c['action']}) needs a numeric 'rule_id'.")
    return data


# ----------------------------------------------------------------------------------------------
# Planning

def keyword_warnings(kw, queries, suggestions):
    out = []
    q = queries.get(norm(kw))
    if q and ((q["sessions"] or 0) >= RULES["warn_sessions"] or (q["revenue"] or 0) >= RULES["warn_revenue"]):
        out.append({"priority": "high", "warning": f"'{kw}' is itself a search with {q['sessions'] or 0:g} sessions and "
                    f"{q['revenue'] or 0:g} revenue. Excluding it hides it from autosuggest for every shopper."})
    if len(kw.strip()) < RULES["min_keyword_chars"]:
        out.append({"priority": "medium", "warning": f"'{kw}' is very short; short suggestions are often legitimate "
                    "(sizes, brand initials)."})
    if re.search(r"[*?%\\^$|]", kw):
        out.append({"priority": "medium", "warning": f"'{kw}' contains a wildcard or pattern character. Keywords are "
                    "exact suggestions, so it's matched literally."})
    if " " not in kw.strip():
        word = norm(kw)
        texts = set(queries) | {norm(s) for v in suggestions.values() for s in v}
        hits = sorted(t for t in texts if t != word and word in t.split())
        if len(hits) >= RULES["word_match_warn_count"]:
            out.append({"priority": "medium", "warning": f"'{kw}' is a word in {len(hits)} other searches or suggestions "
                        f"(for example {', '.join(hits[:3])}). Exclusions are documented as exact, but check after "
                        "sync that only the exact suggestion disappeared."})
    return out


def plan(args):
    req = load_request(args.request)
    rules = load_rules(args.rules)
    sugg = load_suggestions(args.suggestions)
    queries = load_queries(args.queries)
    acc, env, site = args.account, args.environment, args.site_group_id

    def payload(**kw):
        p = {"account_name": acc, "environment": env}
        if site is not None:
            p["site_group_id"] = site
        p.update(kw)
        return p

    by_kw = {}
    for r in rules.values():
        for k in r["keywords"]:
            by_kw.setdefault(norm(k), []).append(r)
    changes = []

    def add(status, kind, target, rule_id=None, tool=None, pay=None, before=None, after=None, undo=None,
            impact="none", reasons=None, problems=None, warnings=None, **extra):
        c = {"n": len(changes) + 1, "status": status, "kind": kind, "target": target, "rule_id": rule_id,
             "tool": tool, "payload": pay, "before": before, "after": after, "undo": undo or [],
             "live_impact": impact, "problems": problems or [], "warnings": warnings or [],
             "reasons": [x for x in (reasons or []) if x]}
        c.update(extra)
        changes.append(c)
        return c

    def state(r):
        return {k: r[k] for k in ("id", "name", "keywords", "enabled", "domain_key", "note")}

    def label(r):
        return f"rule {r['id']} '{r['name']}'"

    # Rule-level actions first: enable, disable, delete.
    for c in req["changes"]:
        if c["action"] not in ("disable", "enable", "delete"):
            continue
        r = rules.get(c["rule_id"])
        if not r:
            add("blocked", c["action"], f"rule {c['rule_id']}", c["rule_id"], reasons=[c.get("reason")],
                problems=[f"rule {c['rule_id']} isn't in the rules read before the change"])
            continue
        if c["action"] == "delete":
            # Deleting can't be undone: the undo recreates the rule disabled, with a new ID, and switches it on
            # separately if it was on.
            undo = [{"tool": TOOLS["create"], "payload": payload(rule_name=r["name"], keywords=r["keywords"],
                                                                 domain_key=r["domain_key"], note=r["note"] or None,
                                                                 enabled=False)}]
            if r["enabled"]:
                undo.append({"tool": TOOLS["update"], "payload": payload(rule_id="<id returned by the undo create>",
                                                                         enabled=True)})
            add("ready", "delete", label(r), r["id"], TOOLS["delete"], payload(rule_id=r["id"]), state(r), None, undo,
                "live" if r["enabled"] else "none", [c.get("reason")],
                warnings=[{"priority": "high", "warning": "Delete is permanent. Disabling the rule has the same effect "
                           "on shoppers and can be undone."}],
                undo_note="Deleting can't be undone: this recreates the rule, disabled, with a new ID.",
                keywords_shown=r["keywords"] if r["enabled"] else [])
            continue
        want = c["action"] == "enable"
        if r["enabled"] == want:
            add("no_change", c["action"], label(r), r["id"], before=state(r), reasons=[c.get("reason")],
                problems=[f"rule {r['id']} is already {'enabled' if want else 'disabled'}"])
            continue
        add("ready", c["action"], label(r), r["id"], TOOLS["update"], payload(rule_id=r["id"], enabled=want), state(r),
            dict(state(r), enabled=want), [{"tool": TOOLS["update"], "payload": payload(rule_id=r["id"], enabled=not want)}],
            "live", [c.get("reason")], keywords_hidden=r["keywords"] if want else [],
            keywords_shown=[] if want else r["keywords"])

    # Keywords to stop hiding: remove them from every rule that has them.
    removing = {}
    for c in req["changes"]:
        if c["action"] != "unexclude":
            continue
        hits = by_kw.get(norm(c["keyword"]), [])
        if not hits:
            add("no_change", "update", f"keyword '{c['keyword']}'", reasons=[c.get("reason")],
                problems=[f"no exclusion rule contains '{c['keyword']}'"])
        for r in hits:
            removing.setdefault(r["id"], {"keywords": set(), "reasons": []})
            removing[r["id"]]["keywords"].add(norm(c["keyword"]))
            removing[r["id"]]["reasons"].append(c.get("reason"))
    touched = {c["rule_id"] for c in changes if c["status"] == "ready"}
    for rid, rem in sorted(removing.items()):
        r = rules[rid]
        gone = [k for k in r["keywords"] if norm(k) in rem["keywords"]]
        if rid in touched:  # one change per rule per run keeps the plan and its undo unambiguous
            add("blocked", "update", label(r), rid, before=state(r), reasons=rem["reasons"],
                problems=[f"rule {rid} already has a rule-level change in this request; run the keyword change "
                          "separately afterwards"])
            continue
        keep = [k for k in r["keywords"] if norm(k) not in rem["keywords"]]
        if not keep:  # keywords can't be empty: disable instead of deleting
            if not r["enabled"]:
                add("no_change", "disable", label(r), rid, before=state(r), reasons=rem["reasons"],
                    problems=[f"rule {rid} is already disabled, so these keywords aren't hidden"])
                continue
            add("ready", "disable", label(r), rid, TOOLS["update"], payload(rule_id=rid, enabled=False), state(r),
                dict(state(r), enabled=False), [{"tool": TOOLS["update"], "payload": payload(rule_id=rid, enabled=True)}],
                "live", rem["reasons"], keywords_shown=gone,
                note="Every keyword in this rule is being unexcluded, so the rule is disabled rather than deleted.")
        else:
            add("ready", "update", label(r), rid, TOOLS["update"], payload(rule_id=rid, keywords=keep), state(r),
                dict(state(r), keywords=keep),
                [{"tool": TOOLS["update"], "payload": payload(rule_id=rid, keywords=r["keywords"])}],
                "live" if r["enabled"] else "none", rem["reasons"], keywords_shown=gone if r["enabled"] else [])

    # Keywords to hide.
    new_kw, reasons, seen = [], [], set()
    for c in req["changes"]:
        if c["action"] != "exclude":
            continue
        kw, k = str(c["keyword"]).strip(), norm(c["keyword"])
        if k in seen:
            continue
        seen.add(k)
        hits = by_kw.get(k, [])
        if any(r["enabled"] for r in hits):
            add("no_change", "update", f"keyword '{kw}'", reasons=[c.get("reason")],
                problems=[f"already excluded by enabled rule {[r['id'] for r in hits if r['enabled']][0]}"])
            continue
        if hits:
            add("blocked", "update", f"keyword '{kw}'", hits[0]["id"], reasons=[c.get("reason")],
                problems=[f"already in disabled rule {hits[0]['id']}: enable that rule instead "
                          f"(it holds {len(hits[0]['keywords'])} keyword(s) in all)"])
            continue
        new_kw.append((kw, keyword_warnings(kw, queries, sugg)))
        reasons.append(c.get("reason"))
    target = req.get("add_to_rule_id")
    if new_kw and target is not None:
        r = rules.get(int(target)) if str(target).lstrip("-").isdigit() else None
        kws = [k for k, _ in new_kw]
        warnings = [w for _, ws in new_kw for w in ws]
        if not r:
            add("blocked", "update", f"rule {target} (add {len(kws)} keyword(s))", reasons=reasons, warnings=warnings,
                problems=[f"add_to_rule_id {target} isn't in the rules read before the change"], keywords=kws)
        elif r["id"] in {c["rule_id"] for c in changes if c["status"] == "ready"}:
            add("blocked", "update", label(r), r["id"], before=state(r), reasons=reasons, warnings=warnings,
                problems=[f"rule {r['id']} already has another change in this request; add keywords to it in a "
                          "separate run"], keywords=kws)
        elif len(r["keywords"]) + len(kws) > RULES["max_keywords_per_rule"]:
            add("blocked", "update", label(r), r["id"], before=state(r), reasons=reasons, warnings=warnings,
                problems=[f"rule {r['id']} would hold {len(r['keywords']) + len(kws)} keywords, over "
                          "max_keywords_per_rule"], keywords=kws)
        else:
            after_kw = r["keywords"] + kws
            add("ready", "update", label(r), r["id"], TOOLS["update"], payload(rule_id=r["id"], keywords=after_kw),
                state(r), dict(state(r), keywords=after_kw),
                [{"tool": TOOLS["update"], "payload": payload(rule_id=r["id"], keywords=r["keywords"])}],
                "live" if r["enabled"] else "none", reasons, warnings=warnings,
                keywords_hidden=kws if r["enabled"] else [])
    elif new_kw:
        size = RULES["max_keywords_per_rule"]
        groups = [new_kw[i:i + size] for i in range(0, len(new_kw), size)]
        base = (req.get("rule_name") or RULES["default_rule_name"]).strip()
        for g, group in enumerate(groups, 1):
            name = base if len(groups) == 1 else f"{base} {g}"
            warnings = [w for _, ws in group for w in ws]
            if len(name) > RULES["max_text_chars"]:
                name = name[:RULES["max_text_chars"]]
                warnings.append({"priority": "low", "warning": "The rule name was cut to max_text_chars."})
            kws = [k for k, _ in group]
            note = "; ".join(sorted({str(x) for x in reasons if x}))[:RULES["max_text_chars"]] or None
            create = add("ready", "create", f"new rule '{name}'", None, TOOLS["create"],
                         payload(rule_name=name, keywords=kws, domain_key=req.get("domain_key"), note=note, enabled=False),
                         None, {"name": name, "keywords": kws, "enabled": False, "domain_key": req.get("domain_key")},
                         [], "none", reasons, warnings=warnings)
            create["undo"] = [{"tool": TOOLS["delete"],
                               "payload": payload(rule_id=f"<id returned by change {create['n']}>")}]
            create["undo_note"] = "The rule didn't exist before, so deleting it restores the old state."
            add("ready", "enable", f"new rule '{name}'", None, TOOLS["update"],
                payload(rule_id=f"<id returned by change {create['n']}>", enabled=True),
                {"name": name, "enabled": False}, {"name": name, "enabled": True},
                [{"tool": TOOLS["update"], "payload": payload(rule_id=f"<id returned by change {create['n']}>",
                                                              enabled=False)}],
                "live", reasons, depends_on=create["n"], keywords_hidden=kws)

    batches = make_batches(changes)
    ready = [c for c in changes if c["status"] == "ready"]
    hidden = {norm(k) for c in ready for k in c.get("keywords_hidden", [])}
    shown = {norm(k) for c in ready for k in c.get("keywords_shown", [])}
    preview = {p: {"before": s, "after_expected": [x for x in s if norm(x) not in hidden],
                   "hidden": [x for x in s if norm(x) in hidden]} for p, s in sorted(sugg.items())}
    by_n = {c["n"]: c for c in changes}
    out = {"ok": True, "account": acc, "environment": env, "site_group_id": site, "changes": changes,
           "batches": batches, "batch_confirm": [confirm_text([by_n[n] for n in b]) for b in batches],
           "preview": preview, "may_reappear": sorted(shown),
           "counts": {s: sum(c["status"] == s for c in changes) for s in ("ready", "blocked", "no_change")}}
    if site is not None:
        out["site_group_id_note"] = ("Exclusion rules are account-level: the write tools accept site_group_id, but it "
                                     "doesn't limit a rule to one site.")
    if not sugg:
        out["preview_note"] = "No suggestions file given: fetch get_autosuggest_results for the affected prefixes first."
    return out


def switches_on(c):
    return c["kind"] == "enable" or (c.get("payload") or {}).get("enabled") is True


def make_batches(changes):
    """Ready changes only. No-live-impact changes first, then other live changes, each capped at
    max_changes_per_batch; then every switch-on and every delete as a batch of its own."""
    ready = [c for c in changes if c["status"] == "ready"]
    alone = [c for c in ready if c["kind"] == "delete" or switches_on(c)]
    rest = [c for c in ready if c not in alone]
    cap = RULES["max_changes_per_batch"]
    batches = []
    for impact in ("none", "live"):
        group = [c["n"] for c in rest if c["live_impact"] == impact]
        batches += [group[i:i + cap] for i in range(0, len(group), cap)]
    batches += [[c["n"]] for c in alone if c["kind"] != "delete"]
    batches += [[c["n"]] for c in alone if c["kind"] == "delete"]
    return batches


def confirm_text(part):
    what = {"create": "create disabled", "enable": "switch on", "disable": "disable", "update": "update keywords of",
            "delete": "PERMANENTLY DELETE"}
    items = [f"{what[c['kind']]} {c['target']}" for c in part]
    warned = sum(len(c["warnings"]) for c in part)
    if any(c["kind"] == "delete" for c in part):
        lead = "This can't be undone."
    elif any(c["live_impact"] == "live" for c in part):
        lead = "Live at once for every shopper once it syncs (seconds to minutes)."
    else:
        lead = "No shopper sees a change yet."
    note = f" Read the {warned} warning(s) first." if warned else ""
    return f"{lead}{note} Shall I " + "; ".join(items) + "?"


# ----------------------------------------------------------------------------------------------
# Verification

def verify(args):
    p = read(args.plan)
    if not isinstance(p, dict) or not isinstance(p.get("changes"), list) or \
            not all(isinstance(c, dict) and isinstance(c.get("n"), int) and "status" in c for c in p["changes"]):
        fail(f"{args.plan}: not a plan from exclusion_plan.py (field 'changes').")
    rules, listed, not_found = load_readback(args.rules)
    sugg = load_suggestions(args.suggestions)
    applied = args.applied
    created = dict(args.created)
    results, still = [], []
    for c in p["changes"]:
        if c["status"] != "ready" or (applied is not None and c["n"] not in applied):
            continue
        after = c.get("after") or {}
        rid, note = c.get("rule_id"), None
        if c["kind"] == "create" or (c["kind"] == "enable" and rid is None):
            source = c["n"] if c["kind"] == "create" else c.get("depends_on")
            rid = created.get(source)
            if rid is None:
                results.append({"n": c["n"], "kind": c["kind"], "rule_id": None, "status": "not_in_place",
                                "note": f"Pass the ID change {source}'s create returned (--created {source}=ID); "
                                        "new rules are never matched by name."})
                continue
        r = rules.get(rid)
        if c["kind"] == "delete":
            if r is not None:
                status = "not_in_place"
            elif listed or not_found:
                status = "gone"
            else:
                status, note = "not_in_place", f"no read-back covers rule {rid}: read the full rule list"
        elif r is None:
            status = "not_in_place"
        elif c["kind"] == "create":
            want = {norm(k) for k in (c["payload"] or {}).get("keywords") or after.get("keywords") or []}
            status = "in_place" if {norm(k) for k in r["keywords"]} == want else "not_in_place"
        elif c["kind"] == "update":
            status = "in_place" if [norm(k) for k in r["keywords"]] == [norm(k) for k in after.get("keywords", [])] \
                else "not_in_place"
        else:
            status = "in_place" if r["enabled"] == after.get("enabled") else "not_in_place"
        res = {"n": c["n"], "kind": c["kind"], "rule_id": rid, "status": status}
        if status == "in_place" and r and str(r.get("sync_status") or "").lower() not in SYNCED:
            res["syncing"] = True
        if note:
            res["note"] = note
        results.append(res)
    hidden = {norm(k) for c in p["changes"] if c.get("status") == "ready" and (applied is None or c["n"] in applied)
              for k in c.get("keywords_hidden", [])}
    for prefix, s in sorted(sugg.items()):
        for x in s:
            if norm(x) in hidden:
                still.append({"prefix": prefix, "suggestion": x})
    expected = {"delete": "gone"}
    ok = all(r["status"] == expected.get(r["kind"], "in_place") for r in results)
    return {"ok": True, "all_in_place": ok, "results": results, "still_suggested": still,
            "note": ("Excluded suggestions can take a few minutes to disappear after a rule syncs; check again "
                     "before calling it a failure.") if still else None}


def number_list(text):
    try:
        return {int(x) for x in text.split(",") if x.strip()}
    except ValueError:
        raise argparse.ArgumentTypeError("use comma-separated change numbers, e.g. 1,2,5")


def created_pair(text):
    """N=ID: change N's create returned rule ID. Splits on the first '='."""
    n, sep, rid = text.partition("=")
    try:
        if not sep:
            raise ValueError
        return int(n), int(rid)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected N=ID with numbers, e.g. 6=106 (got {text!r})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # suggestions can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="build the change plan")
    pl.add_argument("--request", required=True, help="the changes to make (JSON)")
    pl.add_argument("--rules", action="append", default=[], required=True,
                    help="saved search_autosuggest_exclusion_rules result, before the change (repeat per page)")
    pl.add_argument("--suggestions", help="prefix -> get_autosuggest_results list, before the change")
    pl.add_argument("--queries", action="append", default=[], help="saved get_discovery_query_performance result")
    pl.add_argument("--account", required=True, help="the Discovery account name the user confirmed")
    pl.add_argument("--environment", required=True, choices=["staging", "production"],
                    help="where to write (staging first; production needs its own plan and yes)")
    pl.add_argument("--site-group-id", help="copied into every payload when given (it doesn't scope exclusion rules)")
    pl.add_argument("--out", help="also write the JSON result to this file (save it before writing)")
    ve = sub.add_parser("verify", help="check a fresh read against the plan")
    ve.add_argument("--plan", required=True, help="the plan JSON from the plan step")
    ve.add_argument("--rules", action="append", default=[], required=True,
                    help="saved rules (or a not-found response), read after the change")
    ve.add_argument("--suggestions", help="prefix -> get_autosuggest_results list, read after the change")
    ve.add_argument("--applied", type=number_list, help="comma-separated change numbers that were run (default: all)")
    ve.add_argument("--created", type=created_pair, action="append", default=[],
                    help="N=ID: the rule ID change N's create returned (repeat per create)")
    ve.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    out = plan(a) if a.cmd == "plan" else verify(a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the result there ({e}).")
    print(text)


if __name__ == "__main__":
    main()
