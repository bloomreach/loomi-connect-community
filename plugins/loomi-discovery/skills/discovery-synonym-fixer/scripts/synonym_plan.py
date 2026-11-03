#!/usr/bin/env python3
"""Turn requested Bloomreach Discovery synonym fixes into a checked change plan, before anything is written.

Usage:
  python3 synonym_plan.py --request request.json --existing synonyms.json [--existing page2.json ...]
         [--experiments running.json ...] [--qa-dir qa] [--out plan.json]

request.json is written by the assistant from the user's request or another skill's findings:

  {"account_name": "<account>", "environment": "staging", "site_group_id": null,
   "changes": [
     {"action": "create", "source": "tshirt", "targets": ["t-shirt", "tee"], "two_way": false, "reason": "..."},
     {"action": "create", "source": "kids", "targets": ["children", "toddler"], "two_way": true},
     {"action": "update", "id": 101, "targets": ["maxi dress"]},
     {"action": "disable", "id": 102}, {"action": "enable", "id": 103},
     {"action": "delete", "id": 104}]}

--existing is the saved list_synonyms_user result (page=-1, or every page). --experiments is the saved
search_discovery_experiments result for running experiments.

For every change the plan gives the exact write payload (always complete: the update tool defaults to
one-way and enabled, so a partial update would silently change a synonym), the state before and after,
the undo, and any problems. Creates, updates, enables and disables are grouped into batches of
max_changes_per_batch; deletes and reverts are planned one at a time. --qa-dir writes one
discovery-change-qa change file per create, update or enable. Rules are in references/rules.json.
Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
ACTIONS = ("create", "update", "enable", "disable", "delete")
ACCOUNT_LIST_MESSAGE = ("Loomi Connect returned an error about the account name; it isn't repeated because it can "
                        "list other accounts. Ask the user to check the account name.")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    text = str(err or "no error text")
    if re.search(r"account", text, re.I) and text.count(",") >= 3:
        return ACCOUNT_LIST_MESSAGE
    return text[:200]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({type(e).__name__}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: {tool_error(d.get('error'))} This check couldn't run; don't treat it as 'nothing found'.")
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
        return frozenset(s["source"])
    return (s["source"], frozenset(s["targets"]))


def all_terms(s):
    return set(s["source"]) if s["two_way"] else {s["source"], *s["targets"]}


def payload_of(s, request, synonym_id=None):
    p = {}
    if synonym_id is not None:
        p["synonym_id"] = synonym_id
    p["source_synonym"] = ",".join(s["source"]) if s["two_way"] else s["source"]
    p["target_synonym"] = "" if s["two_way"] else ",".join(s["targets"])
    p["group_synonym"] = s["two_way"]
    p["enabled"] = s["enabled"]
    return dict(p, **scope(request))


def scope(request):
    out = {"account_name": request.get("account_name"), "environment": request.get("environment") or "production"}
    if request.get("site_group_id") not in (None, ""):
        out["site_group_id"] = request["site_group_id"]
    return out


def term_problems(s):
    problems = []
    terms = list(all_terms(s))
    for t in terms:
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


def running_terms(experiments):
    """The text of every running experiment, lower-cased, for term matching."""
    texts = []
    for e in experiments:
        status = norm(e.get("status") or e.get("experimentStatus") or "")
        if status in RULES["running_statuses"]:
            texts.append((e.get("name") or e.get("id"), norm(json.dumps(e, ensure_ascii=False))))
    return texts


def requested_state(change, before):
    """The after state for a create or update: the change's fields over the existing record."""
    s = dict(before) if before else {"source": "", "targets": [], "two_way": False, "enabled": True}
    two_way = change.get("two_way", s["two_way"])
    if not isinstance(two_way, bool):
        raise ValueError("two_way must be true or false")
    src = change.get("source", s["source"])
    tgt = change.get("targets", s["targets"])
    src_terms, tgt_terms = terms_of(src), terms_of(tgt)
    if src_terms is None or tgt_terms is None:
        raise ValueError("source and targets must be text or lists of text")
    if two_way:
        merged = []
        for t in src_terms + tgt_terms:
            if t not in merged:
                merged.append(t)
        return {"source": merged, "targets": [], "two_way": True, "enabled": change.get("enabled", s["enabled"]) is not False}
    return {"source": src_terms[0] if src_terms else "", "targets": tgt_terms, "two_way": False,
            "enabled": change.get("enabled", s["enabled"]) is not False}


def plan_change(n, change, request, existing, experiments):
    action = change.get("action")
    item = {"n": n, "action": action, "reason": change.get("reason"), "problems": [], "warnings": []}
    if action not in ACTIONS:
        item.update(status="blocked", problems=[f"Unknown action '{action}' (use {', '.join(ACTIONS)})."])
        return item
    before = None
    if action != "create":
        sid = change.get("id")
        rec = existing.get(str(sid))
        if rec is None:
            item.update(status="blocked", id=sid, problems=[
                f"Synonym {sid} isn't in the user synonym list. Bloomreach-generated synonyms can't be changed with "
                "these tools: disable it in the Discovery dashboard (it then becomes 'User Modified' and appears in "
                "the user list), or add a user synonym, which applies alongside it."])
            return item
        before = state(rec)
        item["id"] = sid
        item["before"] = before
    try:
        if action in ("create", "update"):
            after = requested_state(change, before)
        elif action in ("enable", "disable"):
            after = dict(before, enabled=(action == "enable"))
        else:
            after = None
    except ValueError as e:
        item.update(status="blocked", problems=[f"Change {n}: {e}."])
        return item

    if after is not None:
        after.pop("id", None)
        after.pop("type", None)
        item["after"] = after
        item["problems"] += term_problems(after)
    if action == "update" and before and after and term_set(after) == term_set(before) and after["enabled"] == before["enabled"]:
        item["problems"].append("No change: the update leaves the synonym as it is.")
    if action in ("enable", "disable") and before and before["enabled"] == after["enabled"]:
        item["problems"].append(f"Synonym {before['id']} is already {'enabled' if before['enabled'] else 'disabled'}.")
    if action == "update" and before and before["type"] != "User Created" and after and after["two_way"] != before["two_way"]:
        item["problems"].append("Only 'User Created' synonyms can change direction (one-way or two-way).")

    if action == "create":
        for rec in existing.values():
            other = state(rec)
            if term_set(other) == term_set(after):
                if other["enabled"]:
                    item["problems"].append(f"Duplicate of synonym {other['id']}, which is already enabled.")
                else:
                    item["problems"].append(f"Same as disabled synonym {other['id']}: enable that one instead.")
            elif not after["two_way"] and not other["two_way"] and other["source"] == after["source"] and other["enabled"]:
                item["warnings"].append(f"Enabled one-way synonym {other['id']} also expands '{after['source']}'. "
                                        "Both apply; consider updating that one instead.")
            elif not after["two_way"] and not other["two_way"] and other["enabled"] and \
                    other["source"] in after["targets"] and after["source"] in other["targets"]:
                item["warnings"].append(f"Synonym {other['id']} maps the other way; a two-way group may be clearer.")

    touched = all_terms(after or before)
    for name, text in running_terms(experiments):
        hit = sorted(t for t in touched if f'"{t}"' in text)
        if hit:
            item["problems"].append(f"Running experiment '{name}' covers {', '.join(hit)}: wait for it to end.")

    sc = scope(request)
    if action == "create":
        item.update(tool="create_synonym", payload=payload_of(after, request), undo={
            "tool": "delete_synonym", "payload": dict(sc, synonym_id="<id create_synonym returns>"),
            "note": "Deletes the new synonym (User Created, so the delete is permanent and complete)."})
    elif action in ("update", "enable", "disable"):
        prev = dict(before)
        item.update(tool="update_synonym", payload=payload_of(after, request, before["id"]),
                    undo={"tool": "update_synonym", "payload": payload_of(prev, request, before["id"])})
    else:
        item["tool"] = "delete_synonym"
        item["payload"] = dict(sc, synonym_id=before["id"])
        if before["type"] == "User Created":
            item["kind"] = "delete"
            item["undo"] = {"tool": "create_synonym", "payload": payload_of(before, request),
                            "note": "Recreates it with a new ID."}
        else:
            item["kind"] = "revert"
            item["warnings"].append(
                f"Synonym {before['id']} is '{before['type']}': deleting it doesn't remove it. It moves back to the "
                "Bloomreach-generated list and is re-enabled with its generated terms. To switch it off, disable it instead.")
            item["undo"] = {"manual": "Can't be undone with these tools: disable it again in the Discovery dashboard."}
    if action in ("create", "update", "enable") and after:
        terms = after["source"] if after["two_way"] else [after["source"]] + after["targets"]
        item["qa_change"] = {"type": "synonym", "id": item.get("id"), "source": terms[0], "targets": terms[1:],
                             "two_way": after["two_way"]}
    item["status"] = "blocked" if item["problems"] else "planned"
    return item


def batches(items):
    cap = RULES["max_changes_per_batch"]
    normal = [i["n"] for i in items if i["status"] == "planned" and i["action"] != "delete"]
    deletes = [i["n"] for i in items if i["status"] == "planned" and i["action"] == "delete"]
    kinds = {i["n"]: i.get("kind") for i in items}
    out = [{"kind": "changes", "changes": normal[k:k + cap]} for k in range(0, len(normal), cap)]
    out += [{"kind": kinds[d], "changes": [d]} for d in deletes]
    return [dict(b, batch=k) for k, b in enumerate(out, 1)]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # terms can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--request", required=True, help="the requested changes (see above)")
    ap.add_argument("--existing", action="append", required=True, help="saved list_synonyms_user result (repeat per page)")
    ap.add_argument("--experiments", action="append", default=[], help="saved search_discovery_experiments result")
    ap.add_argument("--qa-dir", help="write one discovery-change-qa change file per create, update or enable here")
    ap.add_argument("--out", help="also write the plan to this file (save it before writing: it holds the undo)")
    a = ap.parse_args()

    request = load(a.request)
    if not isinstance(request, dict) or not isinstance(request.get("changes"), list):
        fail(f"{a.request}: needs a 'changes' list.")
    if not request.get("account_name"):
        fail(f"{a.request}: needs the account_name the user confirmed.")
    if (request.get("environment") or "production") not in ("production", "staging"):
        fail(f"{a.request}: environment must be production or staging.")
    existing = {}
    for path in a.existing:
        for rec in records(load(path), path):
            if rec.get("deleted"):
                continue
            existing[str(rec.get("id"))] = rec
    experiments = []
    for path in a.experiments:
        experiments += records(load(path), path)

    items, seen = [], {}
    for n, change in enumerate(request["changes"], 1):
        if not isinstance(change, dict):
            fail(f"{a.request}: change {n} isn't an object.")
        item = plan_change(n, change, request, existing, experiments)
        sid = str(change.get("id")) if change.get("action") != "create" else None
        if sid and sid in seen:
            item["problems"].append(f"Change {seen[sid]} already changes synonym {sid}: one change per synonym per plan.")
            item["status"] = "blocked"
        elif sid and item["status"] == "planned":
            seen[sid] = n
        items.append(item)
    planned = [i for i in items if i["status"] == "planned"]
    out = {"ok": True, "account_name": request["account_name"], "environment": request.get("environment") or "production",
           "site_group_id": request.get("site_group_id"),
           "summary": {"requested": len(items), "planned": len(planned), "blocked": len(items) - len(planned),
                       "deletes": sum(1 for i in planned if i.get("kind") == "delete"),
                       "reverts": sum(1 for i in planned if i.get("kind") == "revert")},
           "batches": batches(items), "changes": items,
           "sync_note": "Synonym changes sync about once an hour in production: check search results after the next sync."}
    if a.qa_dir:
        qa = Path(a.qa_dir)
        try:
            qa.mkdir(parents=True, exist_ok=True)
            for i in planned:
                if i.get("qa_change"):
                    with open(qa / f"change-{i['n']}.json", "w", encoding="utf-8", newline="\n") as f:
                        f.write(json.dumps(i["qa_change"], indent=2, ensure_ascii=False) + "\n")
        except OSError as e:
            fail(f"{a.qa_dir}: can't write the change files ({type(e).__name__}).")
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the plan ({type(e).__name__}).")
    print(text)


if __name__ == "__main__":
    main()
