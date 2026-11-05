#!/usr/bin/env python3
"""Keep a playbook's hand-off file: the context, the stages, the findings and the change log.

The hand-off file (docs/hand-off-format.md) is how one skill's result reaches the next, and how a
playbook picks up again in a later session (an A/B test runs for weeks). This script is the only
thing that writes it, so its shape stays the same. It never calls the network.

  new       start a hand-off file for one playbook run
  findings  add findings from a saved discovery-query-rule-impact result
  choose    mark a finding chosen, dismissed or done
  changes   add the changes from any write skill's plan file (and its verify result)
  change    add one change a skill made without a plan file (discovery-experiment-setup)
  stage     record that a stage started, finished or was skipped
  status    print what's done, what's next and the earliest date for it
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FORMAT = "loomi-handoff/1"
RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
PLAIN = re.compile(r"^[A-Za-z0-9 _.:-]{1,120}$")
RESULTS = ("in_place", "not_in_place", "gone", "not_checked", "unverified")
KINDS = ("create", "update", "enable", "disable", "delete", "end", "archive", "start")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(f"Can't read {what} {path}: {e}")
    except ValueError as e:
        fail(f"{what} {path} isn't valid JSON: {e}")


RULES = load_json(RULES_PATH, "rules file")


def day_arg(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} isn't a YYYY-MM-DD date")


def plain_arg(s):
    if not PLAIN.match(s):
        raise argparse.ArgumentTypeError(f"{s!r}: use letters, digits, spaces, hyphens, dots or colons only "
                                         "(put anything else in a file and pass --subject-file)")
    return s


def today(a):
    return a.today or datetime.now(timezone.utc).date()


def read_handoff(path):
    h = load_json(path, "hand-off file")
    if not isinstance(h, dict) or h.get("format") != FORMAT:
        fail(f"{path} isn't a {FORMAT} hand-off file.")
    if h.get("playbook") not in RULES["playbooks"]:
        fail(f"{path} is for playbook {h.get('playbook')!r}, which this script doesn't know.")
    for k in ("context", "subject"):
        if not isinstance(h.get(k), dict):
            fail(f"{path} has no {k}.")
    for k in ("stages", "findings", "changes"):
        if not isinstance(h.setdefault(k, []), list):
            fail(f"{path}: {k} must be a list.")
    # A file kept by hand may list only the stages it has reached: add the rest, in playbook order.
    have = {s.get("name"): s for s in h["stages"] if isinstance(s, dict)}
    h["stages"] = [dict({"name": r["name"], "skill": r["skill"], "status": "not_started", "outcome": None,
                         "started_on": None, "done_on": None, "files": []}, **have.get(r["name"], {}))
                   for r in stages_for(h["playbook"])]
    return h


def write_json(path, data):
    """Write next to the target and rename, so a failed write never leaves half a file."""
    path = Path(path)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent if str(path.parent) else ".", prefix=".handoff-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        fail(f"Can't write {path}: {e}")


def stages_for(playbook):
    return RULES["playbooks"][playbook]["stages"]


def stage_record(h, name):
    return next(s for s in h["stages"] if s["name"] == name)


def next_id(items, prefix):
    nums = [int(i["id"][1:]) for i in items if re.match(rf"^{prefix}\d+$", str(i.get("id", "")))]
    return f"{prefix}{max(nums, default=0) + 1}"


# --- new -------------------------------------------------------------------------------------------

def cmd_new(a):
    if Path(a.out).exists():
        fail(f"{a.out} already exists. Continue that run (status), or choose another file name.")
    if a.playbook not in RULES["playbooks"]:
        fail(f"Unknown playbook {a.playbook!r}. Known: {', '.join(sorted(RULES['playbooks']))}.")
    if (a.subject is None) == (a.subject_file is None):
        fail("Give the subject with --subject (plain text) or --subject-file, not both.")
    subject = a.subject
    if a.subject_file:
        try:
            with open(a.subject_file, encoding="utf-8") as f:
                subject = f.read().rstrip("\r\n")
        except OSError as e:
            fail(f"Can't read {a.subject_file}: {e}")
        if not subject.strip():
            fail(f"{a.subject_file} is empty.")
    pb = RULES["playbooks"][a.playbook]
    if pb["product"] == "discovery":
        if not a.account or not a.environment:
            fail("A Discovery playbook needs --account and --environment.")
        context = {"product": "discovery", "account": a.account, "environment": a.environment,
                   "site_group_id": a.site_group_id}
    else:
        if not a.project_id:
            fail("An Engagement playbook needs --project-id.")
        context = {"product": "engagement", "project_id": a.project_id}
    h = {
        "format": FORMAT, "playbook": a.playbook, "started_on": today(a).isoformat(),
        "context": context,
        "subject": {"kind": a.subject_kind, "value": subject},
        "stages": [{"name": s["name"], "skill": s["skill"], "status": "not_started", "outcome": None,
                    "started_on": None, "done_on": None, "files": []} for s in pb["stages"]],
        "findings": [], "changes": [],
    }
    write_json(a.out, h)
    print(json.dumps({"ok": True, "handoff": a.out, "playbook": a.playbook,
                      "stages": [s["name"] for s in h["stages"]]}, indent=2))


# --- findings ----------------------------------------------------------------------------------------

def evidence_text(r):
    """A short, data-free description: counts only, never product titles or rule names."""
    parts = []
    if r.get("applied"):
        parts.append(f"pins or boosts {len(r['applied'])} product(s)")
    if r.get("moves"):
        parts.append(f"moves {len(r['moves'])} product(s) on page one")
    if r.get("hidden_count"):
        parts.append(f"hides {r['hidden_count']} product(s)")
    share = r.get("share_of_query_revenue")
    if share is not None:
        parts.append(f"estimated {r.get('estimated_effect')} ({share} of the query's revenue)")
    return "; ".join(parts) or "no visible effect"


def cmd_findings(a):
    h = read_handoff(a.handoff)
    ri = load_json(a.from_rule_impact, "rule impact result")
    if not isinstance(ri, dict) or not ri.get("ok") or not isinstance(ri.get("results"), list):
        fail(f"{a.from_rule_impact} isn't a successful rule_impact.py result (it needs ok: true and results).")
    wanted = set(RULES["finding_verdicts"])
    source = "discovery-query-rule-impact"
    have = {(f["source"], f["target"]) for f in h["findings"]}
    added, skipped = [], []
    for r in ri["results"]:
        name = str(r.get("name", ""))
        per_rule = name not in ("all", "all_algo")
        if not a.all and (not per_rule or r.get("verdict") not in wanted):
            continue
        target = f"ranking rule {name}" if per_rule else r.get("label") or name
        if (source, target) in have:
            skipped.append(target)
            continue
        fid = next_id(h["findings"], "F")
        h["findings"].append({
            "id": fid, "source": source, "target": target, "rule_id": name if per_rule else None,
            "verdict": r.get("verdict"), "priority": r.get("priority"),
            "money_at_stake": r.get("estimated_effect"), "currency": ri.get("currency"),
            "evidence": evidence_text(r), "warnings": sorted(r.get("flags") or []),
            "next_skill": RULES["next_skill"].get(r.get("verdict"), RULES["next_skill"]["default"]) if per_rule
            else "discovery-rule-audit",
            "status": "open", "found_on": today(a).isoformat(),
        })
        added.append(fid)
    order = {"high": 0, "medium": 1, "low": 2}
    h["findings"].sort(key=lambda f: (f["status"] != "open", order.get(f["priority"], 3), int(f["id"][1:])))
    write_json(a.handoff, h)
    print(json.dumps({"ok": True, "added": added, "already_there": sorted(skipped),
                      "left_out": "only verdicts in finding_verdicts (use --all for every rule)" if not a.all else None},
                     indent=2))


def cmd_choose(a):
    h = read_handoff(a.handoff)
    f = next((x for x in h["findings"] if x["id"] == a.finding), None)
    if f is None:
        fail(f"No finding {a.finding} in {a.handoff}.")
    if a.status == "chosen" and any(x["status"] == "chosen" and x["id"] != a.finding for x in h["findings"]):
        fail("Another finding is already chosen. A run tests one change at a time: mark that one done or "
             "dismissed first, or start a new run.")
    f["status"] = a.status
    write_json(a.handoff, h)
    print(json.dumps({"ok": True, "finding": a.finding, "status": a.status}))


# --- changes -----------------------------------------------------------------------------------------

def check_context(h, plan, path):
    ctx = h["context"]
    if ctx["product"] == "discovery":
        for k in ("account", "environment"):
            if plan.get(k) is not None and str(plan.get(k)) != str(ctx.get(k)):
                fail(f"{path} is for {k} {plan.get(k)!r}, but this run is for {ctx.get(k)!r}. "
                     "Record it in the hand-off file of the run it belongs to.")
    elif plan.get("project_id") is not None and str(plan["project_id"]) != str(ctx.get("project_id")):
        fail(f"{path} is for another project. Record it in the hand-off file of the run it belongs to.")


def finding_arg(h, fid):
    if fid is None:
        chosen = [f["id"] for f in h["findings"] if f["status"] == "chosen"]
        return chosen[0] if len(chosen) == 1 else None
    if not any(f["id"] == fid for f in h["findings"]):
        fail(f"No finding {fid} in the hand-off file.")
    return fid


def upsert_change(h, entry):
    for c in h["changes"]:
        if c["source"] == entry["source"] and c.get("plan_n") == entry.get("plan_n") \
                and c.get("plan_file") == entry.get("plan_file") and c["target"] == entry["target"] \
                and entry.get("plan_n") is not None:
            entry["id"] = c["id"]
            if entry["result"] == "unverified":  # re-adding a plan without its verify result keeps the checked one
                entry["result"] = c["result"]
            c.update(entry)
            return c["id"], False
    entry["id"] = next_id(h["changes"], "C")
    h["changes"].append(entry)
    return entry["id"], True


def cmd_changes(a):
    h = read_handoff(a.handoff)
    plan = load_json(a.plan, "plan file")
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan} isn't a plan file (it needs a changes list; see docs/skill-authoring.md).")
    if plan.get("refused"):
        fail(f"{a.plan} was refused, so nothing in it was made.")
    check_context(h, plan, a.plan)
    verified = {}
    if a.verify:
        v = load_json(a.verify, "verify result")
        if not isinstance(v, dict) or not isinstance(v.get("results"), list):
            fail(f"{a.verify} isn't a verify result (it needs a results list).")
        verified = {r.get("n"): r for r in v["results"]}
    fid = finding_arg(h, a.finding)
    live_on = (a.live_on or today(a)).isoformat()
    added, updated = [], []
    for c in sorted(plan["changes"], key=lambda c: c.get("n", 0)):
        if c.get("status") != "ready":
            continue
        result = verified.get(c.get("n"), {}).get("result", "unverified")
        if result not in RESULTS:
            result = "unverified"
        entry = {
            "source": a.source, "finding": fid, "plan_file": Path(a.plan).name, "plan_n": c.get("n"),
            "kind": c.get("kind"), "target": str(c.get("target")), "tool": c.get("tool"),
            "live_impact": c.get("live_impact"), "result": result, "live_on": live_on,
            "undo": c.get("undo") or [], "undo_note": c.get("undo_note"),
        }
        cid, new = upsert_change(h, entry)
        (added if new else updated).append(cid)
    write_json(a.handoff, h)
    print(json.dumps({"ok": True, "added": added, "updated": updated,
                      "made": sum(c["result"] == "in_place" for c in h["changes"])}, indent=2))


def cmd_change(a):
    h = read_handoff(a.handoff)
    entry = {"source": a.source, "finding": finding_arg(h, a.finding), "plan_file": None, "plan_n": None,
             "kind": a.kind, "target": a.target, "tool": a.tool, "live_impact": a.live_impact,
             "result": a.result, "live_on": (a.live_on or today(a)).isoformat(), "undo": [],
             "undo_note": a.undo_note}
    cid, _ = upsert_change(h, entry)
    write_json(a.handoff, h)
    print(json.dumps({"ok": True, "added": cid}))


# --- stages ------------------------------------------------------------------------------------------

def cmd_stage(a):
    h = read_handoff(a.handoff)
    names = [s["name"] for s in h["stages"]]
    if a.name not in names:
        fail(f"No stage {a.name!r} in the {h['playbook']} playbook. Stages: {', '.join(names)}.")
    rule = next(s for s in stages_for(h["playbook"]) if s["name"] == a.name)
    if a.outcome is not None and a.outcome not in rule.get("outcomes", []):
        fail(f"Stage {a.name} outcomes are: {', '.join(rule.get('outcomes', [])) or 'none'}.")
    s = stage_record(h, a.name)
    d = today(a).isoformat()
    s["status"] = a.status
    if a.outcome is not None:
        s["outcome"] = a.outcome
    if a.status in ("in_progress", "done") and not s["started_on"]:
        s["started_on"] = d
    s["done_on"] = d if a.status in ("done", "skipped") else None
    for f in a.file:
        name = Path(f).name
        if name not in s["files"]:
            s["files"].append(name)
    s["files"].sort()
    write_json(a.handoff, h)
    print(json.dumps({"ok": True, "stage": a.name, "status": a.status, "outcome": s["outcome"]}))


# --- status ------------------------------------------------------------------------------------------

def earliest(h, rule):
    nb = rule.get("not_before")
    if not nb:
        return None
    after = stage_record(h, nb["after_stage"])
    if not after.get("done_on"):
        return None
    return date.fromisoformat(after["done_on"]) + timedelta(days=int(RULES[nb["days"]]))


def next_step(h, now):
    """The first stage not finished, with why and when."""
    for rule in stages_for(h["playbook"]):
        s = stage_record(h, rule["name"])
        if s["status"] in ("done", "skipped"):
            continue
        skip = None
        for cond in rule.get("skip_when", []):
            other = stage_record(h, cond["stage"])
            if other["outcome"] in cond["outcomes"]:
                skip = cond["reason"]
        when = earliest(h, rule)
        return {"stage": rule["name"], "skill": rule["skill"], "writes": rule["writes"], "do": rule["do"],
                "status": s["status"], "not_before": when.isoformat() if when else None,
                "ready": when is None or now >= when, "suggest_skip": skip}
    return None


def cmd_status(a):
    h = read_handoff(a.handoff)
    now = today(a)
    nxt = next_step(h, now)
    out = {"ok": True, "playbook": h["playbook"], "subject": h["subject"], "context": h["context"],
           "stages": h["stages"], "next": nxt,
           "open_findings": [f for f in h["findings"] if f["status"] in ("open", "chosen")],
           "changes": h["changes"]}
    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    title = RULES["playbooks"][h["playbook"]]["title"]
    print(f"## {title}: {h['subject']['kind']} (started {h['started_on']})\n")
    print("| Stage | Skill | Status | Outcome | Done |")
    print("|---|---|---|---|---|")
    for s in h["stages"]:
        print(f"| {s['name']} | {s['skill']} | {s['status'].replace('_', ' ')} | {s['outcome'] or ''} | {s['done_on'] or ''} |")
    if out["open_findings"]:
        print("\n**Findings to act on:**")
        for f in out["open_findings"]:
            print(f"- {f['id']} ({f['status']}, {f['priority']}): {f['target']} {f['verdict']}; {f['evidence']}. "
                  f"Next: {f['next_skill']}")
    if h["changes"]:
        print("\n**Changes made in this run:**")
        for c in h["changes"]:
            print(f"- {c['id']}: {c['kind']} {c['target']} on {c['live_on']} ({c['result'].replace('_', ' ')}"
                  f"{', live' if c.get('live_impact') == 'live' else ''})")
    print()
    if nxt is None:
        print("**All stages are finished.**")
    elif nxt["suggest_skip"]:
        print(f"**Next:** {nxt['stage']} can be skipped: {nxt['suggest_skip']}")
    elif not nxt["ready"]:
        print(f"**Next:** {nxt['stage']} with {nxt['skill']}, not before {nxt['not_before']}. {nxt['do']}")
    else:
        print(f"**Next:** {nxt['stage']} with {nxt['skill']}"
              f"{' (writes, after you confirm each step)' if nxt['writes'] else ''}. {nxt['do']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="start a hand-off file for one playbook run")
    p.add_argument("--playbook", required=True, help="playbook name, a key of playbooks in references/rules.json")
    p.add_argument("--subject-kind", required=True, choices=["query", "category"], help="what the run is about")
    p.add_argument("--subject", type=plain_arg, help="the query or category ID, if it is plain text")
    p.add_argument("--subject-file", help="a text file holding the query or category ID exactly as typed")
    p.add_argument("--account", type=plain_arg, help="Discovery account name")
    p.add_argument("--environment", choices=["production", "staging"], help="Discovery environment")
    p.add_argument("--site-group-id", type=plain_arg, help="Discovery site group ID, when the account has sites")
    p.add_argument("--project-id", type=plain_arg, help="Engagement project ID")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.add_argument("--out", required=True, help="the hand-off file to create, in your working folder")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("findings", help="add findings from a saved rule_impact.py result")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--from-rule-impact", required=True, help="rule_impact.py output saved with --out")
    p.add_argument("--all", action="store_true", help="add every measured rule, not only finding_verdicts")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_findings)

    p = sub.add_parser("choose", help="mark a finding chosen, dismissed or done")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--finding", required=True, help="finding ID, such as F1")
    p.add_argument("--status", required=True, choices=["chosen", "dismissed", "done", "open"], help="new status")
    p.set_defaults(fn=cmd_choose)

    p = sub.add_parser("changes", help="add the changes from a write skill's plan file")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--plan", required=True, help="the write skill's plan file")
    p.add_argument("--verify", help="the write skill's verify result for that plan")
    p.add_argument("--source", required=True, type=plain_arg, help="the skill that made the changes")
    p.add_argument("--finding", help="the finding the changes act on (default: the chosen one)")
    p.add_argument("--live-on", type=day_arg, help="date the changes went live, YYYY-MM-DD (default: today)")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_changes)

    p = sub.add_parser("change", help="add one change made without a plan file")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--source", required=True, type=plain_arg, help="the skill that made the change")
    p.add_argument("--kind", required=True, choices=KINDS, help="what kind of change")
    p.add_argument("--target", required=True, type=plain_arg, help="what changed, by type and ID, e.g. 'experiment 12345'")
    p.add_argument("--tool", required=True, type=plain_arg, help="the Loomi Connect tool that made it")
    p.add_argument("--live-impact", required=True, choices=["none", "live"], help="whether shoppers see it")
    p.add_argument("--result", default="in_place", choices=RESULTS, help="read-back result (default in_place)")
    p.add_argument("--undo-note", type=plain_arg, help="how a person undoes it, in plain words")
    p.add_argument("--finding", help="the finding it acts on (default: the chosen one)")
    p.add_argument("--live-on", type=day_arg, help="date it went live, YYYY-MM-DD (default: today)")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_change)

    p = sub.add_parser("stage", help="record a stage's progress")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--name", required=True, help="stage name")
    p.add_argument("--status", required=True, choices=["in_progress", "done", "skipped"], help="new status")
    p.add_argument("--outcome", help="the stage's outcome, one of its outcomes in references/rules.json")
    p.add_argument("--file", action="append", default=[], help="a file the stage saved in the working folder; repeat")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_stage)

    p = sub.add_parser("status", help="print what's done and what's next")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
