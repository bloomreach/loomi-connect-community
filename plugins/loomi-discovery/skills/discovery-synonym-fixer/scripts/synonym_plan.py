#!/usr/bin/env python3
"""Plan Bloomreach Discovery synonym fixes before anything is written, and check them after.

Usage:
  python3 synonym_plan.py plan --account <account> --environment staging [--site-group-id <id>]
         --request request.json --existing synonyms.json [--existing page2.json ...]
         [--experiments running.json ...] [--qa-dir qa] [--out plan.json]
  python3 synonym_plan.py verify --plan plan.json --readback synonyms_after.json [--readback ...]
         [--changes 1,2] [--out verify.json]

request.json holds only the changes, written by the assistant from the user's request or another skill's
findings (the account, environment and site come from the options):

  {"changes": [
     {"action": "create", "source": "tshirt", "targets": ["t-shirt", "tee"], "two_way": false},
     {"action": "create", "source": "kids", "targets": ["children", "toddler"], "two_way": true},
     {"action": "update", "id": 101, "targets": ["maxi dress"]},
     {"action": "disable", "id": 102}, {"action": "enable", "id": 103},
     {"action": "delete", "id": 104}]}

--existing is the saved list_synonyms_user result (page=-1, or every page). --experiments is the saved
search_discovery_experiments result.

plan prints the plan in the shape docs/skill-authoring.md describes ("Plan files for write skills"): for
every change its status (ready, blocked or no_change), the exact payload (update payloads are always
complete: the update tool defaults to one-way and enabled, so a partial update would silently change a
synonym), the state before and after, the undo, and its live impact. New synonyms are created switched off,
with a separate change that switches them on. Ready changes are grouped into batches of at most
max_changes_per_batch; every delete and every change that switches a synonym on is a batch of its own.
--qa-dir writes one discovery-change-qa change file per ready create, update or enable.

verify compares fresh list_synonyms_user results with the plan and reports each ready change as in_place,
not_in_place or gone. Rules are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
ACTIONS = ("create", "update", "enable", "disable", "delete")
ENVIRONMENTS = ("staging", "production")
ACCOUNT_LIST_MESSAGE = ("Loomi Connect returned an error about the account name; it isn't repeated because it can "
                        "list other accounts. Ask the user to check the account name.")
NOT_FOUND = re.compile(r"not found|404|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"account|site|catalog|domain|environment|workspace", re.I)  # a "not found" about these isn't the item


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):
        return ACCOUNT_LIST_MESSAGE
    return text[:200]


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({type(e).__name__}).")


def error_of(data):
    """The error text when Loomi Connect returned an error as data (success: false), else None."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or "no error text")
    return None


def load(path):
    data = read_json(path)
    err = error_of(data)
    if err is not None:
        fail(f"{path}: {tool_error(err)} This check couldn't run; don't treat it as 'nothing found'.")
    return data


def records(data, path):
    """The list inside a saved list result: {"data": [...]}, {"result": {"data": [...]}} or a bare list."""
    for _ in range(3):
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            data = data.get("data", data.get("result", data.get("items")))
    fail(f"{path}: no list of records found.")


def terms_of(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return None
    return [re.sub(r"\s+", " ", str(t)).strip().lower() for t in value if str(t).strip()]


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def state(rec):
    """A synonym record reduced to what matters (no editor names or emails)."""
    terms = terms_of(rec.get("sourceSynonym")) or []
    two_way = bool(rec.get("groupSynonym"))
    return {"id": rec.get("id"), "source": terms if two_way else (terms[0] if terms else ""),
            "targets": [] if two_way else (terms_of(rec.get("targetSynonym")) or []),
            "two_way": two_way, "enabled": rec.get("enabled") is not False,
            "type": rec.get("synonymType") or "unknown"}


def term_set(s):
    if s["two_way"]:
        return ("two_way", tuple(sorted(set(s["source"]))))
    return ("one_way", s["source"], tuple(sorted(set(s["targets"]))))


def all_terms(s):
    return sorted(set(s["source"])) if s["two_way"] else sorted({s["source"], *s["targets"]})


def describe(s):
    if s["two_way"]:
        return " ↔ ".join(s["source"])
    return f"{s['source']} → {', '.join(s['targets'])}"


def bare(s):
    """A state without its ID and type, as written to the plan's before and after."""
    return {k: s[k] for k in ("source", "targets", "two_way", "enabled")}


def payload_of(s, ctx, synonym_id=None, enabled=None):
    p = {}
    if synonym_id is not None:
        p["synonym_id"] = synonym_id
    p["source_synonym"] = ",".join(s["source"]) if s["two_way"] else s["source"]
    p["target_synonym"] = "" if s["two_way"] else ",".join(s["targets"])
    p["group_synonym"] = s["two_way"]
    p["enabled"] = s["enabled"] if enabled is None else enabled
    return dict(p, **ctx)


def term_problems(s):
    problems = []
    for t in all_terms(s):
        if len(t.split()) > RULES["max_words_per_term"]:
            problems.append(f"'{t}' has more than {RULES['max_words_per_term']} words (max_words_per_term).")
        if any(c in t for c in RULES["forbidden_characters"]):
            problems.append(f"'{t}' contains a quote character, which synonym terms can't.")
    if s["two_way"]:
        if len(set(s["source"])) < 2:
            problems.append("A two-way synonym needs at least two different terms.")
    else:
        if not s["source"]:
            problems.append("A one-way synonym needs a source term.")
        if not s["targets"]:
            problems.append("A one-way synonym needs at least one target term.")
        elif set(s["targets"]) <= {s["source"]}:
            problems.append(f"No-op: '{s['source']}' only maps to itself.")
    return problems


def running_tests(experiments):
    """(name, text) for every running experiment. A missing status counts as running."""
    running = {str(s).lower() for s in RULES["running_statuses"]}
    out = []
    for e in experiments:
        status = norm(e.get("status") or e.get("experimentStatus") or "")
        if not status or status in running:
            out.append((e.get("name") or e.get("id"), norm(json.dumps(e, ensure_ascii=False))))
    return out


def requested_state(change, before):
    """The after state for a create or update: the change's fields over the existing record."""
    s = dict(before) if before else {"source": "", "targets": [], "two_way": False, "enabled": True}
    two_way = change.get("two_way", s["two_way"])
    if not isinstance(two_way, bool):
        raise ValueError("two_way must be true or false")
    enabled = change.get("enabled", s["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    src_terms, tgt_terms = terms_of(change.get("source", s["source"])), terms_of(change.get("targets", s["targets"]))
    if src_terms is None or tgt_terms is None:
        raise ValueError("source and targets must be text or lists of text")
    if two_way:
        merged = []
        for t in src_terms + tgt_terms:
            if t not in merged:
                merged.append(t)
        return {"source": merged, "targets": [], "two_way": True, "enabled": enabled}
    return {"source": src_terms[0] if src_terms else "", "targets": tgt_terms, "two_way": False, "enabled": enabled}


def new_change(kind, target):
    return {"n": None, "status": "ready", "kind": kind, "target": target, "tool": None, "payload": None,
            "before": None, "after": None, "undo": [], "live_impact": "none", "problems": [], "warnings": []}


def plan_request(rn, change, ctx, existing, tests):
    """The plan changes for request change rn: one, or two for a create that is switched on afterwards.
    Returns (changes, qa_change, synonym_id)."""
    action = change.get("action")
    if action not in ACTIONS:
        c = new_change("update", f"request change {rn}")
        c.update(status="blocked", problems=[f"Unknown action '{action}' (use {', '.join(ACTIONS)})."])
        return [c], None, None
    before = None
    sid = None
    if action != "create":
        sid = change.get("id")
        rec = existing.get(str(sid))
        if rec is None:
            c = new_change(action, f"synonym {sid}")
            c.update(status="blocked", problems=[
                f"Synonym {sid} isn't in the user synonym list. Bloomreach-generated synonyms can't be changed with "
                "these tools: disable it in the Discovery dashboard (it then becomes 'User Modified' and appears in "
                "the user list), or add a user synonym, which applies alongside it."])
            return [c], None, sid
        before = state(rec)
    try:
        if action in ("create", "update"):
            after = requested_state(change, before)
        elif action in ("enable", "disable"):
            after = dict(before, enabled=(action == "enable"))
        else:
            after = None
    except ValueError as e:
        c = new_change(action, f"request change {rn}" if sid is None else f"synonym {sid}")
        c.update(status="blocked", problems=[f"Request change {rn}: {e}."])
        return [c], None, sid

    target = f"new synonym {describe(after)}" if action == "create" else f"synonym {sid} ({describe(before)})"
    c = new_change(action, target)
    if before:
        c["before"] = bare(before)
    if after is not None:
        c["after"] = bare(after)
        c["problems"] += term_problems(after)
    no_change = False
    if action == "update" and term_set(after) == term_set(before) and after["enabled"] == before["enabled"]:
        c["problems"].append("No change: the update leaves the synonym as it is.")
        no_change = True
    if action in ("enable", "disable") and before["enabled"] == after["enabled"]:
        c["problems"].append(f"Synonym {sid} is already {'enabled' if before['enabled'] else 'disabled'}.")
        no_change = True
    if action == "update" and before["type"] != "User Created" and after["two_way"] != before["two_way"]:
        c["problems"].append("Only 'User Created' synonyms can change direction (one-way or two-way).")

    if action == "create":
        for key in sorted(existing):
            other = state(existing[key])
            if term_set(other) == term_set(after):
                if other["enabled"]:
                    c["problems"].append(f"Duplicate of synonym {other['id']}, which is already enabled.")
                else:
                    c["problems"].append(f"Same as disabled synonym {other['id']}: enable that one instead.")
            elif not after["two_way"] and not other["two_way"] and other["source"] == after["source"] and other["enabled"]:
                c["warnings"].append(f"Enabled one-way synonym {other['id']} also expands '{after['source']}'. "
                                     "Both apply; consider updating that one instead.")
            elif not after["two_way"] and not other["two_way"] and other["enabled"] and \
                    other["source"] in after["targets"] and after["source"] in other["targets"]:
                c["warnings"].append(f"Synonym {other['id']} maps the other way; a two-way group may be clearer.")

    touched = all_terms(after or before)
    for name, text in running_tests(tests):
        hit = [t for t in touched if f'"{t}"' in text]
        if hit:
            c["problems"].append(f"Running experiment '{name}' covers {', '.join(hit)}: wait for it to end.")

    enable_step = None
    if action == "create":
        # Created switched off; a separate change switches it on, with its own yes.
        c.update(tool="create_synonym", payload=payload_of(after, ctx, enabled=False), live_impact="none",
                 undo=[{"tool": "delete_synonym", "payload": dict(ctx, synonym_id="<id create_synonym returns>")}])
        c["after"] = dict(bare(after), enabled=False)
        if after["enabled"]:
            enable_step = new_change("enable", f"switch on the new synonym {describe(after)}")
            placeholder = "<id from the create change>"
            enable_step.update(tool="update_synonym", payload=payload_of(after, ctx, placeholder, enabled=True),
                               before=dict(bare(after), enabled=False), after=bare(after), live_impact="live",
                               undo=[{"tool": "update_synonym", "payload": payload_of(after, ctx, placeholder, enabled=False)}])
    elif action in ("update", "enable", "disable"):
        c.update(tool="update_synonym", payload=payload_of(after, ctx, sid),
                 undo=[{"tool": "update_synonym", "payload": payload_of(before, ctx, sid)}],
                 live_impact="live" if (before["enabled"] or after["enabled"]) else "none")
    else:
        c.update(tool="delete_synonym", payload=dict(ctx, synonym_id=sid))
        if before["type"] == "User Created":
            undo = [{"tool": "create_synonym", "payload": payload_of(before, ctx, enabled=False)}]
            if before["enabled"]:
                undo.append({"tool": "update_synonym",
                             "payload": payload_of(before, ctx, "<id the undo create returns>", enabled=True)})
            c.update(undo=undo, live_impact="live" if before["enabled"] else "none")
            c["warnings"].append("Deleting is permanent; the undo recreates it with a new ID. Disabling is reversible.")
        else:
            c.update(undo=[], live_impact="live")
            c["warnings"].append(
                f"Synonym {sid} is '{before['type']}': deleting it doesn't remove it. It moves back to the "
                "Bloomreach-generated list and is re-enabled with its generated terms, and that can't be undone "
                "with these tools (disable it again in the Discovery dashboard). To switch it off, disable it instead.")

    if c["problems"]:
        c["status"] = "no_change" if no_change and len(c["problems"]) == 1 else "blocked"
    changes = [c]
    if enable_step and c["status"] == "ready":  # nothing to switch on if the create can't go ahead
        changes.append(enable_step)
    qa = None
    if c["status"] == "ready" and action in ("create", "update", "enable"):
        terms = after["source"] if after["two_way"] else [after["source"]] + after["targets"]
        qa = {"type": "synonym", "id": sid, "source": terms[0], "targets": terms[1:], "two_way": after["two_way"]}
    return changes, qa, sid


def switches_on(c):
    return c["kind"] == "enable" or (c["kind"] == "update" and c["before"] and c["after"]
                                     and not c["before"]["enabled"] and c["after"]["enabled"])


def batches(changes):
    """Ready changes only. Deletes and switch-ons are batches of one, after the others."""
    cap = RULES["max_changes_per_batch"]
    ready = [c for c in changes if c["status"] == "ready"]
    normal = [c["n"] for c in ready if c["kind"] != "delete" and not switches_on(c)]
    out = [normal[k:k + cap] for k in range(0, len(normal), cap)]
    out += [[c["n"]] for c in ready if switches_on(c)]
    out += [[c["n"]] for c in ready if c["kind"] == "delete"]
    return out


def environment(text):
    if text not in ENVIRONMENTS:
        raise argparse.ArgumentTypeError("use staging or production")
    return text


def int_list(text):
    try:
        return sorted({int(x) for x in text.split(",") if x.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError("use comma-separated change numbers, e.g. 1,2")


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({type(e).__name__}).")


def cmd_plan(a):
    request = load(a.request)
    if not isinstance(request, dict) or not isinstance(request.get("changes"), list):
        fail(f"{a.request}: needs a 'changes' list.")
    for key, option, value in (("account_name", "--account", a.account), ("account", "--account", a.account),
                               ("environment", "--environment", a.environment),
                               ("site_group_id", "--site-group-id", a.site_group_id)):
        if request.get(key) not in (None, "") and str(request[key]) != str(value):
            fail(f"{a.request}: its {key} doesn't match the {option} option. "
                 "Give the account, environment and site only as options.")
    ctx = {"account_name": a.account, "environment": a.environment}
    if a.site_group_id not in (None, ""):
        ctx["site_group_id"] = a.site_group_id
    existing = {}
    for path in a.existing:
        for rec in records(load(path), path):
            if not rec.get("deleted"):
                existing[str(rec.get("id"))] = rec
    tests = []
    for path in a.experiments:
        tests += records(load(path), path)

    changes, qa_files, seen = [], {}, {}
    for rn, change in enumerate(request["changes"], 1):
        if not isinstance(change, dict):
            fail(f"{a.request}: change {rn} isn't an object.")
        planned, qa, sid = plan_request(rn, change, ctx, existing, tests)
        if sid is not None and change.get("action") != "create":
            if str(sid) in seen:
                for c in planned:
                    c["problems"].append(f"Change {seen[str(sid)]} already changes synonym {sid}: "
                                         "one change per synonym per plan.")
                    c["status"] = "blocked"
                qa = None
            elif planned[0]["status"] == "ready":
                seen[str(sid)] = len(changes) + 1
        first = len(changes) + 1
        for c in planned:
            changes.append(c)
            c["n"] = len(changes)
        if len(planned) == 2:
            planned[1]["target"] += f" (created by change {first})"
        if qa:
            qa_files[first] = qa

    out = {"ok": True, "account": a.account, "environment": a.environment,
           "site_group_id": a.site_group_id if a.site_group_id not in (None, "") else None,
           "changes": changes, "batches": batches(changes)}
    if a.qa_dir:
        qa_dir = Path(a.qa_dir)
        try:
            qa_dir.mkdir(parents=True, exist_ok=True)
            for n in sorted(qa_files):
                with open(qa_dir / f"change-{n}.json", "w", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(qa_files[n], indent=2, ensure_ascii=False) + "\n")
        except OSError as e:
            fail(f"{a.qa_dir}: can't write the change files ({type(e).__name__}).")
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    print(text)


def readback(paths):
    """Records from fresh list_synonyms_user results. A not-found error for a synonym counts as an empty result;
    an error about the account ("account not found" included) stops the check: it says nothing about the synonym."""
    found = {}
    for path in paths:
        data = read_json(path)
        err = error_of(data)
        if err is not None:
            if re.search(r"account", err, re.I):
                fail(f"{path}: {ACCOUNT_LIST_MESSAGE} The read-back failed, so the writes can't be checked.")
            if NOT_FOUND.search(err) and not CONTEXT_ERROR.search(err):
                continue
            fail(f"{path}: {tool_error(err)} The read-back failed, so the writes can't be checked.")
        for rec in records(data, path):
            if not rec.get("deleted"):
                found[str(rec.get("id"))] = state(rec)
    return found


def cmd_verify(a):
    plan = read_json(a.plan)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: isn't a synonym plan (no 'changes' list).")
    found = readback(a.readback)
    by_terms = {}
    for s in found.values():
        by_terms.setdefault(term_set(s), s)
    results = []
    for c in plan["changes"]:
        if not isinstance(c, dict) or c.get("status") != "ready" or (a.changes and c.get("n") not in a.changes):
            continue
        kind, after = c.get("kind"), c.get("after")
        try:
            if kind == "delete":
                sid = str(c["payload"]["synonym_id"])
                rec = found.get(sid)
            elif kind == "create" or (kind == "enable" and str(c["payload"].get("synonym_id", "")).startswith("<")):
                rec = by_terms.get(term_set(after))
            else:
                rec = found.get(str(c["payload"]["synonym_id"]))
        except (KeyError, TypeError):
            fail(f"{a.plan}: change {c.get('n')} is missing its payload or after state.")
        if rec is None:
            result = "gone"
        elif kind == "delete":
            result = "not_in_place"
        elif kind == "create":
            result = "in_place"  # the create's enabled state is checked by the enable change after it
        else:
            result = "in_place" if (term_set(rec) == term_set(after) and rec["enabled"] == after["enabled"]) else "not_in_place"
        expected = "gone" if kind == "delete" else "in_place"
        entry = {"n": c.get("n"), "kind": kind, "target": c.get("target"), "result": result, "expected": expected,
                 "ok": result == expected}
        if rec is not None and kind != "delete":
            entry["now"] = bare(rec)
            if kind == "create":
                entry["new_id"] = rec["id"]
        results.append(entry)
    out = {"ok": True, "results": results, "all_ok": all(r["ok"] for r in results)}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    print(text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # terms can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="plan the changes before writing")
    p.add_argument("--account", required=True, help="the account name the user confirmed")
    p.add_argument("--environment", required=True, type=environment, help="staging or production")
    p.add_argument("--site-group-id", help="the site, for a site-level synonym (default: account level)")
    p.add_argument("--request", required=True, help="the requested changes (see above)")
    p.add_argument("--existing", action="append", required=True, help="saved list_synonyms_user result (repeat per page)")
    p.add_argument("--experiments", action="append", default=[], help="saved search_discovery_experiments result")
    p.add_argument("--qa-dir", help="write one discovery-change-qa change file per ready create, update or enable here")
    p.add_argument("--out", help="also write the plan to this file (save it before writing: it holds the undo)")
    v = sub.add_parser("verify", help="check the writes against the plan")
    v.add_argument("--plan", required=True, help="the plan file the writes were made from")
    v.add_argument("--readback", action="append", required=True, help="fresh list_synonyms_user result (repeat per page)")
    v.add_argument("--changes", type=int_list, help="only these change numbers (default: every ready change)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    cmd_plan(a) if a.cmd == "plan" else cmd_verify(a)


if __name__ == "__main__":
    main()
