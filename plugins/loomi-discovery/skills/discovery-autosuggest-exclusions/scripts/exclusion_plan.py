#!/usr/bin/env python3
"""Plan and verify changes to Bloomreach Discovery autosuggest exclusion rules.

Usage:
  python3 exclusion_plan.py plan --request request.json --rules rules.json [--rules page2.json]
         [--suggestions before.json] [--queries queries.json ...] --account NAME
         [--environment staging] [--out plan.json]
  python3 exclusion_plan.py verify --plan plan.json --rules rules_after.json [--rules ...]
         [--suggestions after.json] [--applied C1,C2] [--out verify.json]

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

plan prints JSON with every change (tool, exact payload, before, after, undo, live impact, warnings),
the batches to confirm one at a time (no live impact, live, irreversible), what was skipped and why, and
a before/after preview of the suggestions. New rules are created disabled and enabled in a separate,
live batch. Removing a keyword from a rule that would be left empty disables the rule rather than
deleting it. Deletes are only planned when asked for, and always in their own batch.

verify compares a fresh read of the rules (and suggestions) with the plan: which changes are in place,
which aren't, which rules are still syncing, and which excluded suggestions still show.

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
BATCH_ORDER = ("no live impact", "live", "irreversible")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat. An unknown account_name makes some Discovery tools list every
    account the user can access, so an account error that looks like a list is replaced, never echoed."""
    text = str(err or "no error text")
    if "account" in text.lower() and text.count(",") >= 3:
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


def read(path):
    """A saved tool result, unwrapped from {"result": ...} and checked for success: false."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


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


def load_rules(paths):
    rules = {}
    for p in paths:
        data = read(p)
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("rules", items.get("items", [items]))
        if not isinstance(items, list):
            fail(f"{p}: not an exclusion rule list or detail (field 'data').")
        for r in items:
            if isinstance(r, dict) and r:
                rec = rule_record(r, p)
                rules[rec["id"]] = rec
    return rules


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


def payload(account, environment, **kw):
    return dict({"account_name": account, "environment": environment}, **kw)


def plan(args):
    req = load_request(args.request)
    rules = load_rules(args.rules)
    sugg = load_suggestions(args.suggestions)
    queries = load_queries(args.queries)
    acc, env = args.account, args.environment
    by_kw = {}
    for r in rules.values():
        for k in r["keywords"]:
            by_kw.setdefault(norm(k), []).append(r)
    changes, skipped = [], []

    def add(kind, rid, before, after, undo, impact, reason, **extra):
        c = {"id": f"C{len(changes) + 1}", "kind": kind, "rule_id": rid, "before": before, "after": after,
             "undo": undo, "live_impact": impact, "reasons": reason, "warnings": []}
        c.update(extra)
        changes.append(c)
        return c

    def state(r):
        return {k: r[k] for k in ("id", "name", "keywords", "enabled", "domain_key", "note")}

    # Rule-level actions first: enable, disable, delete.
    for c in req["changes"]:
        if c["action"] not in ("disable", "enable", "delete"):
            continue
        r = rules.get(c["rule_id"])
        if not r:
            skipped.append({"change": c, "why": f"rule {c['rule_id']} isn't in the rules read before the change"})
            continue
        if c["action"] == "delete":
            ch = add("delete", r["id"], state(r), None,
                     {"tool": TOOLS["create"], "payload": payload(acc, env, rule_name=r["name"], keywords=r["keywords"],
                      domain_key=r["domain_key"], note=r["note"] or None, enabled=r["enabled"]),
                      "note": "Deleting can't be undone: this recreates the rule with a new ID."},
                     "irreversible", [c.get("reason")], tool=TOOLS["delete"],
                     payload=payload(acc, env, rule_id=r["id"]), separate_yes=True)
            ch["warnings"].append({"priority": "high", "warning": "Delete is permanent. Disabling the rule has the same "
                                   "effect on shoppers and can be undone."})
            continue
        want = c["action"] == "enable"
        if r["enabled"] == want:
            skipped.append({"change": c, "why": f"rule {r['id']} is already {'enabled' if want else 'disabled'}"})
            continue
        add(c["action"], r["id"], state(r), dict(state(r), enabled=want),
            {"tool": TOOLS["update"], "payload": payload(acc, env, rule_id=r["id"], enabled=not want)},
            "live", [c.get("reason")], tool=TOOLS["update"], payload=payload(acc, env, rule_id=r["id"], enabled=want),
            keywords_hidden=r["keywords"] if want else [], keywords_shown=[] if want else r["keywords"])

    # Keywords to stop hiding: remove them from every rule that has them.
    removing = {}
    for c in req["changes"]:
        if c["action"] != "unexclude":
            continue
        hits = by_kw.get(norm(c["keyword"]), [])
        if not hits:
            skipped.append({"change": c, "why": f"no exclusion rule contains '{c['keyword']}'"})
        for r in hits:
            removing.setdefault(r["id"], {"keywords": set(), "reasons": []})
            removing[r["id"]]["keywords"].add(norm(c["keyword"]))
            removing[r["id"]]["reasons"].append(c.get("reason"))
    touched = {c["rule_id"] for c in changes}
    for rid, rem in sorted(removing.items()):
        r = rules[rid]
        if rid in touched:  # one change per rule per run keeps the plan and its undo unambiguous
            skipped.append({"change": {"rule_id": rid, "keywords": sorted(rem["keywords"])},
                            "why": f"rule {rid} already has a rule-level change in this request; run the keyword change "
                                   "separately afterwards"})
            continue
        keep = [k for k in r["keywords"] if norm(k) not in rem["keywords"]]
        gone = [k for k in r["keywords"] if norm(k) in rem["keywords"]]
        impact = "live" if r["enabled"] else "no live impact"
        if not keep:  # keywords can't be empty: disable instead of deleting
            if not r["enabled"]:
                skipped.append({"change": {"rule_id": rid, "keywords": gone},
                                "why": f"rule {rid} is already disabled, so these keywords aren't hidden"})
                continue
            add("disable", rid, state(r), dict(state(r), enabled=False),
                {"tool": TOOLS["update"], "payload": payload(acc, env, rule_id=rid, enabled=True)}, "live", rem["reasons"],
                tool=TOOLS["update"], payload=payload(acc, env, rule_id=rid, enabled=False), keywords_shown=gone,
                note="Every keyword in this rule is being unexcluded, so the rule is disabled rather than deleted.")
        else:
            add("update", rid, state(r), dict(state(r), keywords=keep),
                {"tool": TOOLS["update"], "payload": payload(acc, env, rule_id=rid, keywords=r["keywords"])}, impact,
                rem["reasons"], tool=TOOLS["update"], payload=payload(acc, env, rule_id=rid, keywords=keep),
                keywords_shown=gone if r["enabled"] else [])

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
            skipped.append({"change": c, "why": f"already excluded by enabled rule {[r['id'] for r in hits if r['enabled']][0]}"})
            continue
        if hits:
            skipped.append({"change": c, "why": f"already in disabled rule {hits[0]['id']}: enable that rule instead "
                            f"(it holds {len(hits[0]['keywords'])} keyword(s) in all)"})
            continue
        new_kw.append((kw, keyword_warnings(kw, queries, sugg)))
        reasons.append(c.get("reason"))
    target = req.get("add_to_rule_id")
    if new_kw and target is not None:
        r = rules.get(int(target)) if str(target).lstrip("-").isdigit() else None
        if not r:
            fail(f"{args.request}: add_to_rule_id {target} isn't in the rules read before the change.")
        if r["id"] in {c["rule_id"] for c in changes}:
            fail(f"{args.request}: rule {r['id']} already has another change in this request; add keywords to it "
                 "in a separate run.")
        after_kw = r["keywords"] + [k for k, _ in new_kw]
        if len(after_kw) > RULES["max_keywords_per_rule"]:
            fail(f"{args.request}: rule {r['id']} would hold {len(after_kw)} keywords, over max_keywords_per_rule.")
        ch = add("update", r["id"], state(r), dict(state(r), keywords=after_kw),
                 {"tool": TOOLS["update"], "payload": payload(acc, env, rule_id=r["id"], keywords=r["keywords"])},
                 "live" if r["enabled"] else "no live impact", reasons, tool=TOOLS["update"],
                 payload=payload(acc, env, rule_id=r["id"], keywords=after_kw),
                 keywords_hidden=[k for k, _ in new_kw] if r["enabled"] else [])
        ch["warnings"] = [w for _, ws in new_kw for w in ws]
    elif new_kw:
        size = RULES["max_keywords_per_rule"]
        groups = [new_kw[i:i + size] for i in range(0, len(new_kw), size)]
        base = (req.get("rule_name") or RULES["default_rule_name"]).strip()
        for n, group in enumerate(groups, 1):
            name = base if len(groups) == 1 else f"{base} {n}"
            warnings = [w for _, ws in group for w in ws]
            if len(name) > RULES["max_text_chars"]:
                name = name[:RULES["max_text_chars"]]
                warnings.append({"priority": "low", "warning": "The rule name was cut to max_text_chars."})
            kws = [k for k, _ in group]
            note = "; ".join(sorted({str(x) for x in reasons if x}))[:RULES["max_text_chars"]] or None
            create = add("create", None, None, {"name": name, "keywords": kws, "enabled": False,
                         "domain_key": req.get("domain_key")},
                         {"tool": TOOLS["delete"], "payload": payload(acc, env, rule_id="<id returned by this create>"),
                          "note": "The rule didn't exist before, so deleting it restores the old state."},
                         "no live impact", reasons, tool=TOOLS["create"],
                         payload=payload(acc, env, rule_name=name, keywords=kws, domain_key=req.get("domain_key"),
                                         note=note, enabled=False))
            create["warnings"] = warnings
            add("enable", None, {"name": name, "enabled": False}, {"name": name, "enabled": True},
                {"tool": TOOLS["update"], "payload": payload(acc, env, rule_id=f"<id returned by {create['id']}>",
                 enabled=False)}, "live", reasons, tool=TOOLS["update"],
                payload=payload(acc, env, rule_id=f"<id returned by {create['id']}>", enabled=True),
                depends_on=create["id"], keywords_hidden=kws)

    # Batches: no live impact first, then live, then deletes; each capped and confirmed on its own.
    batches = []
    for kind in BATCH_ORDER:
        group = [c for c in changes if c["live_impact"] == kind]
        cap = 1 if kind == "irreversible" else RULES["max_changes_per_batch"]
        for i in range(0, len(group), cap):
            part = group[i:i + cap]
            batches.append({"batch": len(batches) + 1, "live_impact": kind, "changes": [c["id"] for c in part],
                            "confirm": confirm_text(kind, part)})

    hidden = {norm(k) for c in changes for k in c.get("keywords_hidden", [])}
    shown = {norm(k) for c in changes for k in c.get("keywords_shown", [])}
    preview = {p: {"before": s, "after_expected": [x for x in s if norm(x) not in hidden],
                   "hidden": [x for x in s if norm(x) in hidden]} for p, s in sugg.items()}
    out = {"ok": True, "account": acc, "environment": env, "changes": changes, "batches": batches, "skipped": skipped,
           "preview": preview, "may_reappear": sorted(shown),
           "counts": {k: sum(c["live_impact"] == k for c in changes) for k in BATCH_ORDER}}
    if not sugg:
        out["preview_note"] = "No suggestions file given: fetch get_autosuggest_results for the affected prefixes first."
    return out


def confirm_text(kind, part):
    what = {"create": "create disabled rule", "enable": "enable", "disable": "disable", "update": "update keywords of",
            "delete": "PERMANENTLY DELETE"}
    items = []
    for c in part:
        label = (c.get("after") or c.get("before") or {}).get("name") or f"rule {c['rule_id']}"
        items.append(f"{what[c['kind']]} '{label}'" + (f" (rule {c['rule_id']})" if c["rule_id"] is not None else ""))
    warned = sum(len(c["warnings"]) for c in part)
    lead = {"no live impact": "No shopper sees a change yet.",
            "live": "Live at once for every shopper once it syncs (seconds to minutes).",
            "irreversible": "This can't be undone."}[kind]
    note = f" Read the {warned} warning(s) first." if warned else ""
    return f"{lead}{note} Shall I " + "; ".join(items) + "?"


# ----------------------------------------------------------------------------------------------
# Verification

def verify(args):
    p = read(args.plan)
    if not isinstance(p, dict) or not isinstance(p.get("changes"), list):
        fail(f"{args.plan}: not a plan from exclusion_plan.py (field 'changes').")
    rules = load_rules(args.rules)
    sugg = load_suggestions(args.suggestions)
    applied = {x.strip() for x in args.applied.split(",") if x.strip()} if args.applied else None
    results, still = [], []
    for c in p["changes"]:
        if applied is not None and c.get("id") not in applied:
            continue
        after = c.get("after") or {}
        if c["kind"] == "create" or (c["kind"] == "enable" and c.get("rule_id") is None):
            match = [r for r in rules.values() if r["name"] == after.get("name")
                     and {norm(k) for k in r["keywords"]} == {norm(k) for k in (c["payload"].get("keywords") or after.get("keywords") or [])}] \
                if c["kind"] == "create" else [r for r in rules.values() if r["name"] == after.get("name")]
            r = match[0] if match else None
            # A create only has to exist (the enable that follows it checks its state); an enable must be on.
            ok = bool(r) and (c["kind"] == "create" or r["enabled"] == after.get("enabled"))
        else:
            r = rules.get(c.get("rule_id"))
            if c["kind"] == "delete":
                ok = r is None
            elif r is None:
                ok = False
            elif c["kind"] == "update":
                ok = [norm(k) for k in r["keywords"]] == [norm(k) for k in after.get("keywords", [])]
            else:
                ok = r["enabled"] == after.get("enabled")
        status = "in place" if ok else "not in place"
        if ok and r and str(r.get("sync_status") or "").lower() not in ("", "synced", "success", "completed", "none"):
            status = "in place, still syncing"
        results.append({"id": c["id"], "kind": c["kind"], "rule_id": r["id"] if r else c.get("rule_id"), "status": status})
    hidden = {norm(k) for c in p["changes"] if applied is None or c.get("id") in applied for k in c.get("keywords_hidden", [])}
    for prefix, s in sugg.items():
        for x in s:
            if norm(x) in hidden:
                still.append({"prefix": prefix, "suggestion": x})
    ok = all(r["status"].startswith("in place") for r in results)
    return {"ok": True, "all_in_place": ok, "results": results, "still_suggested": still,
            "note": ("Excluded suggestions can take a few minutes to disappear after a rule syncs; check again "
                     "before calling it a failure.") if still else None}


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
    pl.add_argument("--environment", choices=["staging", "production"], default="staging",
                    help="where to write (default staging; production needs its own yes)")
    pl.add_argument("--out", help="also write the JSON result to this file (save it before writing)")
    ve = sub.add_parser("verify", help="check a fresh read against the plan")
    ve.add_argument("--plan", required=True, help="the plan JSON from the plan step")
    ve.add_argument("--rules", action="append", default=[], required=True, help="saved rules, read after the change")
    ve.add_argument("--suggestions", help="prefix -> get_autosuggest_results list, read after the change")
    ve.add_argument("--applied", help="comma-separated change IDs that were run (default: all)")
    ve.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    out = plan(a) if a.cmd == "plan" else verify(a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
