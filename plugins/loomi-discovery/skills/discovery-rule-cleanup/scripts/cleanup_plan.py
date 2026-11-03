#!/usr/bin/env python3
"""Turn a rule cleanup request into a safe, reviewable change plan, and check the result after writing.

Usage:
  python3 cleanup_plan.py plan --request request.json --rule 123=rule_123.json [--rule ...]
         --environment staging|production --account NAME [--experiments experiments.json]
         [--site-group-id ID] [--today YYYY-MM-DD] [--out plan.json]
  python3 cleanup_plan.py verify --plan plan.json --rule 123=after_123.json [--rule ...] [--out verify.json]

plan
  request.json lists the changes wanted, from discovery-rule-audit's cleanup list or the user
  (format: references/change-request.md). Each --rule is a saved detail result read just now
  (get_ranking_rule, get_facet_rule or get_discovery_media_rule) giving the rule's current state.
  --experiments is a saved search_discovery_experiments listing (all statuses).

  Prints a plan in the shared shape (docs/skill-authoring.md, "Plan files for write skills"): every
  change with its status (ready, blocked with the reasons in problems, or no_change), kind, before
  and after state, write tool and exact payload, and undo. batches lists the ready changes to ask
  about, at most max_changes_per_batch per batch; each delete is a batch of its own, because each
  needs its own "yes". Changes the skill won't make are blocked: running test, protected name, no
  write tool, delete of a rule that isn't disabled and expired, and so on.

verify
  Each --rule is the detail read back after the writes; every ready change needs one, deletes too
  (a not-found response means the rule is gone). Prints, per ready change, in_place, not_in_place
  or gone.

Limits are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
WRITE_TOOLS = {"ranking": ("update_ranking_rule", "delete_ranking_rule"),
               "facet": ("update_facet_rule", "delete_facet_rule")}
ACTIONS = ("disable", "delete", "set_end_date", "set_queries")
PRIORITY = {"high": 0, "medium": 1, "low": 2}
DAY_MS = 86_400_000


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat: anything about the account is never echoed, because it can list
    every account the user can access."""
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


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
        fail(f"{path}: Loomi Connect returned an error: {tool_error(err)}. "
             "This step couldn't run; don't treat it as 'nothing found'.")
    return data


def unwrap(data):
    """The record inside {"result": ...}, {"data": ...} and the double {"data": {"data": ...}} of rule detail."""
    for _ in range(4):
        if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
            data = data["result"]
        elif isinstance(data, dict) and isinstance(data.get("data"), (dict, list)) and "id" not in data:
            data = data["data"]
        else:
            break
    return data


def name_file(text):
    """argparse type for ID=FILE (split on the first '=')."""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"expected <rule id>=<file>, got {text!r}")
    rid, path = text.split("=", 1)
    if not rid.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected <rule id>=<file>, got {text!r}")
    return rid.strip(), path.strip()


def day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}")


def as_int(value, where):
    try:
        return int(value)
    except (TypeError, ValueError):
        fail(f"{where}: expected a whole number, got {value!r}.")


def state(rec, path):
    """The fields this skill reads and changes. Editor names (user, lastModifiedBy) are never kept."""
    if not isinstance(rec, dict) or rec.get("id") is None:
        fail(f"{path}: not a rule detail (no id). Save the whole get_ranking_rule, get_facet_rule or "
             "get_discovery_media_rule result.")
    queries = []
    for q in rec.get("queries") or []:
        if not isinstance(q, dict):
            fail(f"{path}: queries must be objects.")
        queries.append({k: q[k] for k in ("query", "queryType", "matchType") if k in q})
    rtype = str(rec.get("ruleType") or "").lower()
    return {"id": str(rec["id"]), "ruleType": "media" if rtype == "campaign" else rtype or "unknown",
            "name": rec.get("name"), "enabled": rec.get("enabled"), "durationTag": rec.get("durationTag"),
            "startedAt": rec.get("startedAt"), "endedAt": rec.get("endedAt"), "queries": queries,
            "isLive": bool(rec.get("isLive") or rec.get("isAbTestLive")),
            "isEditable": rec.get("isEditable") is not False,
            "modifiedAt": rec.get("modifiedAt") or rec.get("lastModifiedAt")}


def running_rule_ids(path):
    if not path:
        return None
    data = unwrap(load(path))
    rows = data if isinstance(data, list) else (data.get("data") or data.get("experiments") or []) if isinstance(data, dict) else []
    running = {str(x).lower() for x in RULES["running_statuses"]}
    ids = set()
    for e in rows:
        if not isinstance(e, dict):
            fail(f"{path}: experiments must be objects.")
        status = str(e.get("experimentStatus") or e.get("status") or "").strip().lower()
        if status and status not in running:
            continue  # a missing status counts as running
        for b in e.get("buckets") or []:
            rid = ((b or {}).get("ruleIdentifierInfo") or {}).get("id")
            if rid is not None:
                ids.add(str(rid))
    return ids


def end_of_day_ms(text, where):
    try:
        d = date.fromisoformat(str(text))
    except ValueError:
        fail(f"{where}: end_date must be YYYY-MM-DD, got {text!r}.")
    return int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)


def base_payload(rid, a):
    p = {"rule_id": int(rid) if str(rid).isdigit() else rid, "environment": a.environment, "account_name": a.account}
    if a.site_group_id:
        p["site_group_id"] = a.site_group_id
    return p


KIND = {"disable": "disable", "delete": "delete", "set_end_date": "update", "set_queries": "update",
        "enable": "enable"}


def change(head, status, kind, tool=None, payload=None, before=None, after=None, undo=(), problems=(),
           warnings=(), **extra):
    """One change in the shared plan shape (docs/skill-authoring.md, "Plan files for write skills")."""
    return dict(head, status=status, kind=kind, tool=tool, payload=payload, before=before, after=after,
                undo=list(undo), live_impact="live" if status == "ready" else "none",
                problems=list(problems), warnings=list(warnings), **extra)


def plan_one(req, before, a, running, today_ms):
    """One request against the rule's current state, as a change in the shared plan shape."""
    rid, action = before["id"], req["action"]
    head = {"target": f"{before['ruleType']} rule {rid} {before['name']!r}", "rule_id": rid,
            "rule_type": before["ruleType"], "name": before["name"], "queries": before["queries"],
            "requested": action, "reason": req.get("reason"), "priority": req.get("priority", "medium")}

    def blocked(why):
        return change(head, "blocked", KIND[action], before=before, problems=[why])

    if before["ruleType"] == "media":
        return blocked("Media rules have no write tool in Loomi Connect: make this change in the Discovery "
                       "dashboard (the plan gives the steps).")
    if before["ruleType"] == "redirect":
        return blocked("Redirects are handled by discovery-redirect-fixer.")
    if before["ruleType"] not in WRITE_TOOLS:
        return blocked(f"Unknown rule type {before['ruleType']!r}.")
    if before["isLive"] or (running is not None and rid in running):
        return blocked("The rule is in a running A/B test. End the test first (discovery-experiment-readout), "
                       "then plan this again.")
    if not before["isEditable"]:
        return blocked("The rule is marked not editable.")
    if re.search(RULES["protected_name_pattern"], str(before["name"] or ""), re.I) and not req.get("owner_confirmed"):
        return blocked("The rule's name says not to touch it. Ask its owner, then set owner_confirmed: true in "
                       "the request.")
    update, delete = WRITE_TOOLS[before["ruleType"]]
    after = {k: before[k] for k in ("enabled", "startedAt", "endedAt", "queries")}
    payload, undo, undo_note, warnings = base_payload(rid, a), base_payload(rid, a), None, []

    if action == "delete":
        disabled_days = (today_ms - before["modifiedAt"]) / DAY_MS if isinstance(before["modifiedAt"], (int, float)) else 0
        if before["enabled"]:
            action = "disable"
            warnings.append("Deleting an enabled rule can't be undone, so this plans a disable instead. Delete it "
                            "later, once it has stayed off.")
        elif before["durationTag"] == "expired" or disabled_days >= RULES["delete_min_disabled_days"]:
            return change(head, "ready", "delete", tool=delete, payload=payload, before=before, after=None,
                          undo_note="A delete can't be undone. The before state is saved here so the rule could be "
                                    "rebuilt by hand in the dashboard.",
                          qa="Preview the results without the rule (discovery-change-qa) for its top queries.")
        else:
            return blocked(f"Disabled less than delete_min_disabled_days ({RULES['delete_min_disabled_days']}) days "
                           "ago and not expired: keep it disabled for now.")
    if action == "disable":
        if before["enabled"] is False:
            return change(head, "no_change", "disable", before=before, after=after, warnings=["Already disabled."])
        after["enabled"], payload["enabled"], undo["enabled"] = False, False, True
        qa = "Preview the results without the rule (discovery-change-qa) for its top queries."
    elif action == "set_end_date":
        new_end = end_of_day_ms(req.get("end_date"), f"request rule {rid}")
        if new_end <= today_ms:
            return blocked("The end date isn't in the future; plan a disable instead.")
        if before["endedAt"] == new_end:
            return change(head, "no_change", "update", before=before, after=after, warnings=["Already ends then."])
        after["endedAt"], payload["ended_at"] = new_end, new_end
        if before["endedAt"] is None:
            undo, undo_note = None, ("The rule had no end date. The update tool can't clear one (null means keep), "
                                     "so undoing this means clearing the end date in the dashboard.")
        else:
            undo["ended_at"] = before["endedAt"]
        qa = "Schedule check (discovery-change-qa): the new end date against the queries' seasonality."
    elif action == "set_queries":
        new = req.get("queries")
        if not isinstance(new, list) or not new or not all(isinstance(q, dict) and q.get("query") and q.get("queryType")
                                                           for q in new):
            fail(f"request rule {rid}: set_queries needs queries: [{{query, queryType, matchType}}, ...].")
        new = [dict(q, matchType=q.get("matchType") or "EXACT_MATCH") for q in new]
        if new == before["queries"]:
            return change(head, "no_change", "update", before=before, after=after,
                          warnings=["Already targets those queries."])
        if not all("matchType" in q for q in before["queries"]):
            return blocked("The saved rule has no matchType on its queries, so the undo can't be exact. Save the "
                           "rule detail (not the list) and plan again.")
        after["queries"], payload["queries"], undo["queries"] = new, new, before["queries"]
        qa = "Before/after preview of the new scope (discovery-change-qa), including longer searches a phrase match catches."
    return change(head, "ready", KIND[action], tool=update, payload=payload, before=before, after=after,
                  undo=[{"tool": update, "payload": undo}] if undo else [], warnings=warnings,
                  undo_note=undo_note, qa=qa)


def cmd_plan(a):
    today = a.today or datetime.now(timezone.utc).date()
    today_ms = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp() * 1000)
    req_data = load(a.request)
    reqs = req_data.get("changes") if isinstance(req_data, dict) else req_data
    if not isinstance(reqs, list):
        fail(f"{a.request}: expected a list of changes, or {{\"changes\": [...]}}.")
    rules = {}
    for rid, path in a.rule:
        rec = state(unwrap(load(path)), path)
        if rec["id"] != rid:
            fail(f"{path}: holds rule {rec['id']}, not {rid}.")
        rules[rid] = rec
    running = running_rule_ids(a.experiments)
    planned = []
    for i, r in enumerate(reqs):
        if not isinstance(r, dict):
            fail(f"{a.request}: change {i + 1} isn't an object.")
        rid = str(as_int(r.get("rule_id"), f"{a.request}: change {i + 1} rule_id"))
        if r.get("priority", "medium") not in PRIORITY:
            fail(f"{a.request}: change {i + 1} priority must be high, medium or low.")
        head = {"target": f"rule {rid}", "rule_id": rid, "requested": r.get("action"), "reason": r.get("reason"),
                "priority": r.get("priority", "medium")}
        if r.get("action") not in ACTIONS:
            e = change(head, "blocked", KIND.get(r.get("action"), "update"),
                       problems=[f"This skill only plans {', '.join(ACTIONS)}. Switching rules on, or other changes, "
                                 "go through discovery-change-qa and the dashboard."])
        elif rid not in rules:
            e = change(head, "blocked", KIND[r["action"]],
                       problems=["No --rule detail for this rule: read it with the get_* tool now and pass it, so "
                                 "the plan starts from its real state."])
        else:
            e = plan_one(r, rules[rid], a, running, today_ms)
        planned.append((PRIORITY[e["priority"]], int(rid), i, e))
    changes = [t[3] for t in sorted(planned, key=lambda t: t[:3])]
    for n, e in enumerate(changes, 1):
        e["n"] = n
    ready = [e for e in changes if e["status"] == "ready"]
    cap = RULES["max_changes_per_batch"]
    others = [e["n"] for e in ready if e["kind"] != "delete"]
    batches = [others[i:i + cap] for i in range(0, len(others), cap)]
    batches += [[e["n"]] for e in ready if e["kind"] == "delete"]  # each delete is its own batch and yes
    result = {"ok": True, "account": a.account, "environment": a.environment, "site_group_id": a.site_group_id,
              "today": today.isoformat(), "experiments_checked": running is not None,
              "summary": {s: sum(1 for e in changes if e["status"] == s) for s in ("ready", "blocked", "no_change")},
              "changes": changes, "batches": batches}
    if running is None:
        result["warning"] = ("No --experiments file: running tests were only checked through each rule's isLive "
                             "flag. Read search_discovery_experiments before writing.")
    emit(result, a.out)


NOT_FOUND = re.compile(r"not found|404|doesn'?t exist|does not exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"account|site|catalog|domain|environment|workspace", re.I)  # a "not found" about these isn't the item


def read_back(path, rid):
    """A rule read back after writing: its state, or None when Loomi Connect says the rule isn't there (deleted).
    A "not found" about the account, site or catalog, an empty read-back, or a read-back of another rule stops."""
    data = read_json(path)
    err = error_of(data)
    if err is not None:
        if NOT_FOUND.search(err) and not CONTEXT_ERROR.search(err):
            return None
        fail(f"{path}: Loomi Connect returned an error: {tool_error(err)}. Read the rule again.")
    rec = unwrap(data)
    if rec in (None, {}, []):
        fail(f"{path}: the read-back is empty, so it doesn't show whether rule {rid} exists. Read the rule again.")
    got = rec.get("id") if isinstance(rec, dict) else None
    if got is not None and str(got) != str(rid):
        fail(f"{path}: the read-back is rule {got}, not rule {rid}.")
    return state(rec, path)


def cmd_verify(a):
    plan = read_json(a.plan)
    if not isinstance(plan, dict) or plan.get("ok") is not True or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan from cleanup_plan.py plan (no ok or changes).")
    after = {rid: read_back(path, rid) for rid, path in a.rule}
    results = []
    for i, e in enumerate(plan["changes"]):
        if not isinstance(e, dict) or not {"n", "status", "kind", "rule_id"} <= set(e):
            fail(f"{a.plan}: change {i + 1} is missing n, status, kind or rule_id.")
        if e["status"] != "ready":
            continue
        rid = str(e["rule_id"])
        row = {"n": e["n"], "rule_id": rid, "kind": e["kind"]}
        if rid not in after:
            results.append(dict(row, result="not_in_place", ok=False,
                                detail="not read back: read the rule with its get_* tool and pass it"))
            continue
        got = after[rid]
        if e["kind"] == "delete":
            ok = got is None
            results.append(dict(row, result="gone" if ok else "not_in_place", ok=ok,
                                detail="gone" if ok else "the rule still exists: read it again in a minute"))
            continue
        if got is None:
            results.append(dict(row, result="gone", ok=False, detail="the rule is gone, but this change didn't delete it"))
            continue
        want = e.get("after")
        if not isinstance(want, dict):
            fail(f"{a.plan}: change {e['n']} has no after state.")
        diffs = [k for k in ("enabled", "endedAt", "queries") if want.get(k) != got.get(k)]
        results.append(dict(row, result="in_place" if not diffs else "not_in_place", ok=not diffs,
                            detail="matches the plan" if not diffs else "differs from the plan: " + ", ".join(diffs)))
    emit({"ok": True, "all_match": all(r["ok"] for r in results), "results": results}, a.out)


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
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="build the change plan")
    p.add_argument("--request", required=True, help="the changes wanted (references/change-request.md)")
    p.add_argument("--rule", action="append", default=[], type=name_file, help="<rule id>=<saved rule detail>")
    p.add_argument("--experiments", help="saved search_discovery_experiments listing (all statuses)")
    p.add_argument("--environment", choices=("production", "staging"), required=True,
                   help="where to write: staging first; production needs its own plan and yes")
    p.add_argument("--account", required=True, help="Discovery account name, copied into each payload")
    p.add_argument("--site-group-id", help="site group ID or name, copied into each payload")
    p.add_argument("--today", type=day, help="YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--out", help="also write the plan to this file (keep it: it holds the undo)")
    v = sub.add_parser("verify", help="check the rules read back after writing")
    v.add_argument("--plan", required=True, help="the plan file written by plan --out")
    v.add_argument("--rule", action="append", default=[], type=name_file, help="<rule id>=<rule detail read back>")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    cmd_plan(a) if a.cmd == "plan" else cmd_verify(a)


if __name__ == "__main__":
    main()
