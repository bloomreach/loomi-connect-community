#!/usr/bin/env python3
"""Turn a rule cleanup request into a safe, reviewable change plan, and check the result after writing.

Usage:
  python3 cleanup_plan.py plan --request request.json --rule 123=rule_123.json [--rule ...]
         [--experiments experiments.json] [--environment production|staging] [--account NAME]
         [--site-group-id ID] [--today YYYY-MM-DD] [--out plan.json]
  python3 cleanup_plan.py verify --plan plan.json --rule 123=after_123.json [--rule ...] [--out verify.json]

plan
  request.json lists the changes wanted, from discovery-rule-audit's cleanup list or the user
  (format: references/change-request.md). Each --rule is a saved detail result read just now
  (get_ranking_rule, get_facet_rule or get_discovery_media_rule) giving the rule's current state.
  --experiments is a saved search_discovery_experiments listing (all statuses).

  Prints a plan: per change, the before state, the after state, the write tool and exact payload,
  and the undo payload. Deletes are listed apart, because each needs its own "yes". Changes the
  skill won't make are listed under refused with the reason (running test, protected name, no
  write tool, delete of a rule that isn't disabled and expired, and so on), and changes over the
  batch limits under next_batch.

verify
  Each --rule is the detail read back after the writes. Prints, per planned change, whether the
  rule now matches the planned after state.

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
    """A Loomi Connect error safe to repeat: an account-name list is never echoed."""
    text = str(err or "no error text")
    if re.search(r"account", text, re.I) and text.count(",") >= 3:
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({type(e).__name__}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))}. "
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
    ids = set()
    for e in rows:
        status = str(e.get("experimentStatus") or e.get("status") or "").upper()
        if status not in RULES["running_experiment_statuses"]:
            continue
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
    p = {"rule_id": int(rid) if str(rid).isdigit() else rid, "environment": a.environment}
    if a.account:
        p["account_name"] = a.account
    if a.site_group_id:
        p["site_group_id"] = a.site_group_id
    return p


def plan_one(req, before, a, running, today_ms):
    """Returns (kind, entry): kind is change, delete, refused or noop."""
    rid, action = before["id"], req["action"]
    head = {"rule_id": rid, "rule_type": before["ruleType"], "name": before["name"], "queries": before["queries"],
            "requested": action, "reason": req.get("reason"), "priority": req.get("priority", "medium")}
    if before["ruleType"] == "media":
        return "refused", dict(head, why="Media rules have no write tool in Loomi Connect: make this change in the "
                                         "Discovery dashboard (the plan gives the steps).")
    if before["ruleType"] == "redirect":
        return "refused", dict(head, why="Redirects are handled by discovery-redirect-fixer.")
    if before["ruleType"] not in WRITE_TOOLS:
        return "refused", dict(head, why=f"Unknown rule type {before['ruleType']!r}.")
    if before["isLive"] or (running is not None and rid in running):
        return "refused", dict(head, why="The rule is in a running A/B test. End the test first "
                                         "(discovery-experiment-readout), then plan this again.")
    if not before["isEditable"]:
        return "refused", dict(head, why="The rule is marked not editable.")
    if re.search(RULES["protected_name_pattern"], str(before["name"] or ""), re.I) and not req.get("owner_confirmed"):
        return "refused", dict(head, why="The rule's name says not to touch it. Ask its owner, then set "
                                         "owner_confirmed: true in the request.")
    update, delete = WRITE_TOOLS[before["ruleType"]]
    after = {k: before[k] for k in ("enabled", "startedAt", "endedAt", "queries")}
    payload, undo, undo_note, qa = base_payload(rid, a), base_payload(rid, a), None, None

    if action == "delete":
        disabled_days = (today_ms - before["modifiedAt"]) / DAY_MS if isinstance(before["modifiedAt"], (int, float)) else 0
        if before["enabled"]:
            action, head["converted"] = "disable", ("Deleting an enabled rule can't be undone, so this plans a "
                                                    "disable instead. Delete it later, once it has stayed off.")
        elif before["durationTag"] == "expired" or disabled_days >= RULES["delete_min_disabled_days"]:
            return "delete", dict(head, action="delete", tool=delete, payload=payload, before=before, after=None, undo=None,
                                  undo_note="A delete can't be undone. The before state is saved here so the rule "
                                            "could be rebuilt by hand in the dashboard.",
                                  qa="Preview the results without the rule (discovery-change-qa) for its top queries.")
        else:
            return "refused", dict(head, why=f"Disabled less than {RULES['delete_min_disabled_days']} days ago and "
                                             "not expired: keep it disabled for now (delete_min_disabled_days).")
    if action == "disable":
        if before["enabled"] is False:
            return "noop", dict(head, why="Already disabled.")
        after["enabled"], payload["enabled"], undo["enabled"] = False, False, True
        qa = "Preview the results without the rule (discovery-change-qa) for its top queries."
    elif action == "set_end_date":
        new_end = end_of_day_ms(req.get("end_date"), f"request rule {rid}")
        if new_end <= today_ms:
            return "refused", dict(head, why="The end date isn't in the future; plan a disable instead.")
        if before["endedAt"] == new_end:
            return "noop", dict(head, why="Already ends then.")
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
            return "noop", dict(head, why="Already targets those queries.")
        if not all("matchType" in q for q in before["queries"]):
            return "refused", dict(head, why="The saved rule has no matchType on its queries, so the undo can't be "
                                             "exact. Save the rule detail (not the list) and plan again.")
        after["queries"], payload["queries"], undo["queries"] = new, new, before["queries"]
        qa = "Before/after preview of the new scope (discovery-change-qa), including longer searches a phrase match catches."
    entry = dict(head, action=action, tool=update, payload=payload, before=before, after=after,
                 undo=dict(tool=update, payload=undo) if undo else None, undo_note=undo_note, qa=qa)
    return "change", entry


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
    out = {"changes": [], "deletes": [], "refused": [], "noop": [], "next_batch": [], "missing": []}
    for i, r in enumerate(reqs):
        if not isinstance(r, dict):
            fail(f"{a.request}: change {i + 1} isn't an object.")
        rid = str(as_int(r.get("rule_id"), f"{a.request}: change {i + 1} rule_id"))
        if r.get("action") not in ACTIONS:
            out["refused"].append({"rule_id": rid, "requested": r.get("action"),
                                   "why": f"This skill only plans {', '.join(ACTIONS)}. Switching rules on, or other "
                                          "changes, go through discovery-change-qa and the dashboard."})
            continue
        if r.get("priority", "medium") not in PRIORITY:
            fail(f"{a.request}: change {i + 1} priority must be high, medium or low.")
        if rid not in rules:
            out["missing"].append({"rule_id": rid, "why": "No --rule detail for this rule: read it with the get_* "
                                                          "tool now and pass it, so the plan starts from its real state."})
            continue
        kind, entry = plan_one(r, rules[rid], a, running, today_ms)
        out[{"change": "changes", "delete": "deletes", "refused": "refused", "noop": "noop"}[kind]].append(entry)
    order = lambda e: (PRIORITY.get(e.get("priority"), 1), e["rule_id"])
    for key, cap in (("changes", RULES["max_changes_per_batch"]), ("deletes", RULES["max_deletes_per_batch"])):
        items = sorted(out[key], key=order)
        out[key], extra = items[:cap], items[cap:]
        out["next_batch"] += [dict(e, batch_limit=key) for e in extra]
    for n, e in enumerate(out["changes"] + out["deletes"], 1):
        e["n"] = n
    result = {"ok": True, "environment": a.environment, "today": today.isoformat(),
              "experiments_checked": running is not None,
              "summary": {k: len(v) for k, v in out.items()}, **out}
    if running is None:
        result["warning"] = ("No --experiments file: running tests were only checked through each rule's isLive "
                             "flag. Read search_discovery_experiments before writing.")
    emit(result, a.out)


def cmd_verify(a):
    plan = load(a.plan)
    after = {}
    for rid, path in a.rule:
        after[rid] = state(unwrap(load(path)), path)
    results = []
    for e in plan.get("changes", []) + plan.get("deletes", []):
        rid, got = str(e["rule_id"]), after.get(str(e["rule_id"]))
        if e.get("action") == "delete":
            ok = got is None
            results.append({"rule_id": rid, "action": "delete", "ok": ok,
                            "detail": "gone" if ok else "the rule still exists: read it again in a minute, then report"})
            continue
        if got is None:
            results.append({"rule_id": rid, "action": e.get("action"), "ok": False,
                            "detail": "not read back: read the rule with its get_* tool and pass it"})
            continue
        diffs = [k for k in ("enabled", "endedAt", "queries") if e["after"].get(k) != got.get(k)]
        results.append({"rule_id": rid, "action": e.get("action"), "ok": not diffs,
                        "detail": "matches the plan" if not diffs else "differs from the plan: " + ", ".join(diffs)})
    emit({"ok": True, "all_match": all(r["ok"] for r in results), "results": results}, a.out)


def emit(obj, out):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="build the change plan")
    p.add_argument("--request", required=True, help="the changes wanted (references/change-request.md)")
    p.add_argument("--rule", action="append", default=[], type=name_file, help="<rule id>=<saved rule detail>")
    p.add_argument("--experiments", help="saved search_discovery_experiments listing (all statuses)")
    p.add_argument("--environment", choices=("production", "staging"), default="staging",
                   help="where to write (default staging; production needs its own plan and yes)")
    p.add_argument("--account", help="Discovery account name, copied into each payload")
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
