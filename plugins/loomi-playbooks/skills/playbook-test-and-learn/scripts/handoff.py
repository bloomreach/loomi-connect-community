#!/usr/bin/env python3
"""Keep a playbook's hand-off file: the context, the stages, the findings and the change log.

The hand-off file (docs/hand-off-format.md) is how one skill's result reaches the next, and how a
playbook picks up again in a later session (an A/B test runs for weeks). This script is the only
thing that writes it, so its shape stays the same. It never calls the network.

Every playbook skill ships the same copy of this script; its own references/rules.json defines its stages.

  new       start a hand-off file for one playbook run
  findings  add findings: from a findings file any skill's result was written into, or a saved
            discovery-query-rule-impact result
  choose    mark a finding chosen, dismissed or done
  changes   add the changes from any write skill's plan file (and its verify result)
  change    add one change a skill made without a plan file
  stage     record that a stage started, finished or was skipped
  status    print what's done, what's next and the earliest date for it
  list      list every run in a folder (any playbook): what's due, and the changes made
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FORMAT = "loomi-handoff/1"
RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
PLAIN = re.compile(r"^[A-Za-z0-9 _.:-]{1,120}$")
RESULTS = ("in_place", "not_in_place", "gone", "not_checked", "not_needed", "unverified")
FINDING_STATUSES = ("open", "chosen", "dismissed", "done")
STAGE_STATUSES = ("not_started", "in_progress", "done", "skipped")
SUBJECT_KINDS = ("query", "category", "product", "brand", "collection", "flow", "campaign", "segment", "event",
                 "account", "project", "period")
PRIORITIES = ("high", "medium", "low")
SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
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
    return getattr(a, "today", None) or datetime.now(timezone.utc).date()


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
    # The skill and the allowed values always come from rules.json, never from the file.
    have = {s.get("name"): s for s in h["stages"] if isinstance(s, dict)}
    stages = []
    for r in stages_for(h["playbook"]):
        got = have.get(r["name"], {})
        st = {"name": r["name"], "skill": r["skill"], "status": got.get("status", "not_started"),
              "outcome": got.get("outcome"), "started_on": got.get("started_on"), "done_on": got.get("done_on"),
              "files": got.get("files") or [], "not_before": got.get("not_before")}
        if st["status"] not in STAGE_STATUSES:
            fail(f"{path}: stage {r['name']} has status {st['status']!r}; allowed: {', '.join(STAGE_STATUSES)}.")
        if st["outcome"] is not None and st["outcome"] not in r.get("outcomes", []):
            fail(f"{path}: stage {r['name']} has outcome {st['outcome']!r}; allowed: {', '.join(r.get('outcomes', []))}.")
        for k in ("started_on", "done_on", "not_before"):
            if st[k] is not None:
                try:
                    date.fromisoformat(str(st[k]))
                except ValueError:
                    fail(f"{path}: stage {r['name']} {k} {st[k]!r} isn't a YYYY-MM-DD date.")
        if not isinstance(st["files"], list) or not all(isinstance(f, str) for f in st["files"]):
            fail(f"{path}: stage {r['name']} files must be a list of file names.")
        stages.append(st)
    h["stages"] = stages
    h["findings"] = [checked(f, FINDING_DEFAULTS, path, "finding") for f in h["findings"]]
    h["changes"] = [checked(c, CHANGE_DEFAULTS, path, "change") for c in h["changes"]]
    for f in h["findings"]:
        if f["status"] not in FINDING_STATUSES:
            fail(f"{path}: finding {f['id']} has status {f['status']!r}; allowed: {', '.join(FINDING_STATUSES)}.")
    for c in h["changes"]:
        if c["result"] not in RESULTS:
            fail(f"{path}: change {c['id']} has result {c['result']!r}; allowed: {', '.join(RESULTS)}.")
        if c["live_on"] is not None:
            try:
                date.fromisoformat(str(c["live_on"]))
            except ValueError:
                fail(f"{path}: change {c['id']} live_on {c['live_on']!r} isn't a YYYY-MM-DD date.")
    return h


FINDING_DEFAULTS = {"source": "", "target": "", "rule_id": None, "verdict": None, "priority": None, "money_at_stake": None,
                    "currency": None, "evidence": "", "warnings": [], "next_skill": None, "status": "open", "found_on": None}
CHANGE_DEFAULTS = {"source": "", "finding": None, "plan_file": None, "plan_n": None, "kind": None, "target": "",
                   "tool": None, "live_impact": None, "result": "unverified", "live_on": None, "undo": [], "undo_note": None}


def checked(item, defaults, path, what):
    """A finding or change from the file, with every key present (a file kept by hand may leave some out)."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        fail(f"{path}: every {what} needs an id.")
    return {"id": item["id"], **{k: item.get(k, v) for k, v in defaults.items()}}


def made(c):
    """A change counts as made when its read-back shows it in place (or gone, for a delete)."""
    return c["result"] == "in_place" or (c.get("kind") == "delete" and c["result"] == "gone")


def write_json(path, data):
    """Write next to the target and rename, so a failed write never leaves half a file."""
    path = Path(path)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".handoff-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        fail(f"Can't write {path}: {e}")


def save(h, path, a):
    """Write the file with its next step worked out, so `list` can show it without this playbook's rules."""
    nxt = next_step(h, today(a))
    h["next"] = None if nxt is None else {k: nxt[k] for k in ("stage", "skill", "writes", "not_before", "suggest_skip")}
    write_json(path, h)


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
    context = {"product": pb["product"]}
    if pb["product"] in ("discovery", "both"):
        if not a.account or not a.environment:
            fail("This playbook works on Discovery: it needs --account and --environment.")
        context.update(account=a.account, environment=a.environment, site_group_id=a.site_group_id)
    if pb["product"] in ("engagement", "both"):
        if not a.project_id:
            fail("This playbook works on Engagement: it needs --project-id.")
        context.update(project_id=a.project_id)
    h = {
        "format": FORMAT, "playbook": a.playbook, "started_on": today(a).isoformat(),
        "context": context,
        "subject": {"kind": a.subject_kind, "value": subject},
        "stages": [{"name": s["name"], "skill": s["skill"], "status": "not_started", "outcome": None,
                    "started_on": None, "done_on": None, "files": [], "not_before": None} for s in pb["stages"]],
        "findings": [], "changes": [],
    }
    save(h, a.out, a)
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
    if (a.from_file is None) == (a.from_rule_impact is None):
        fail("Give --from-file (with --source) or --from-rule-impact, not both.")
    if a.from_file is not None:
        return findings_from_file(a)
    h = read_handoff(a.handoff)
    ri = load_json(a.from_rule_impact, "rule impact result")
    if not isinstance(ri, dict) or not ri.get("ok") or not isinstance(ri.get("results"), list):
        fail(f"{a.from_rule_impact} isn't a successful rule_impact.py result (it needs ok: true and results).")
    wanted = set(RULES.get("finding_verdicts", ["hurts", "hides sellers"]))
    next_skills = RULES.get("next_skill", {"default": "discovery-experiment-setup"})
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
            "evidence": evidence_text(r), "warnings": sorted(str(f.get("flag")) for f in (r.get("flags") or []) if isinstance(f, dict) and f.get("flag")),
            "next_skill": next_skills.get(r.get("verdict"), next_skills["default"]) if per_rule
            else "discovery-rule-audit",
            "status": "open", "found_on": today(a).isoformat(),
        })
        added.append(fid)
    order = {"high": 0, "medium": 1, "low": 2}
    h["findings"].sort(key=lambda f: (f["status"] != "open", order.get(f["priority"], 3), int(f["id"][1:])))
    save(h, a.handoff, a)
    print(json.dumps({"ok": True, "added": added, "already_there": sorted(skipped),
                      "left_out": "only verdicts in finding_verdicts (use --all for every rule)" if not a.all else None},
                     indent=2))


def findings_from_file(a):
    """Findings the assistant wrote from a skill's result, in the format's findings shape. Everything is checked:
    targets are type and ID (plain text), evidence is shortened to one line, money must be a number."""
    h = read_handoff(a.handoff)
    if not a.source:
        fail("--from-file needs --source, the skill whose result the findings come from.")
    data = load_json(a.from_file, "findings file")
    items = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(items, list):
        fail(f"{a.from_file} needs a findings list.")
    have = {(f["source"], f["target"]) for f in h["findings"]}
    added, skipped = [], []
    for i, x in enumerate(items, 1):
        if not isinstance(x, dict):
            fail(f"{a.from_file}: finding {i} isn't an object.")
        target = str(x.get("target") or "").strip()
        if not PLAIN.match(target):
            fail(f"{a.from_file}: finding {i} target {target[:60]!r} must be plain text, type and ID (e.g. 'flow 123', "
                 "'query file 2'), never a name from the data.")
        if x.get("priority") not in PRIORITIES:
            fail(f"{a.from_file}: finding {i} priority must be one of {', '.join(PRIORITIES)}.")
        nxt = x.get("next_skill")
        if nxt is not None and not SKILL_NAME.match(str(nxt)):
            fail(f"{a.from_file}: finding {i} next_skill {nxt!r} isn't a skill name.")
        money = x.get("money_at_stake")
        if money is not None:
            try:
                money = str(Decimal(str(money)).quantize(Decimal("0.01")))
            except InvalidOperation:
                fail(f"{a.from_file}: finding {i} money_at_stake {money!r} isn't a number.")
        verdict = x.get("verdict")
        if verdict is not None and not PLAIN.match(str(verdict)):
            fail(f"{a.from_file}: finding {i} verdict must be plain text.")
        if (a.source, target) in have:
            skipped.append(target)
            continue
        fid = next_id(h["findings"], "F")
        h["findings"].append({
            "id": fid, "source": a.source, "target": target, "rule_id": None, "verdict": verdict,
            "priority": x["priority"], "money_at_stake": money, "currency": x.get("currency") if PLAIN.match(str(x.get("currency") or "x")) else None,
            "evidence": flat(x.get("evidence") or ""), "warnings": [], "next_skill": nxt,
            "status": "open", "found_on": today(a).isoformat(),
        })
        have.add((a.source, target))
        added.append(fid)
    order = {"high": 0, "medium": 1, "low": 2}
    h["findings"].sort(key=lambda f: (f["status"] != "open", order.get(f["priority"], 3), int(f["id"][1:])))
    save(h, a.handoff, a)
    print(json.dumps({"ok": True, "added": added, "already_there": sorted(skipped)}, indent=2))


def cmd_choose(a):
    h = read_handoff(a.handoff)
    f = next((x for x in h["findings"] if x["id"] == a.finding), None)
    if f is None:
        fail(f"No finding {a.finding} in {a.handoff}.")
    if a.status == "chosen" and any(x["status"] == "chosen" and x["id"] != a.finding for x in h["findings"]):
        fail("Another finding is already chosen. A run tests one change at a time: mark that one done or "
             "dismissed first, or start a new run.")
    f["status"] = a.status
    save(h, a.handoff, a)
    print(json.dumps({"ok": True, "finding": a.finding, "status": a.status}))


# --- changes -----------------------------------------------------------------------------------------

def check_context(h, plan, path):
    ctx = h["context"]
    engagement_plan = plan.get("project_id") is not None
    if engagement_plan and ctx["product"] == "discovery":
        fail(f"{path} is an Engagement plan, but this run is for Discovery only.")
    if not engagement_plan and ctx["product"] == "engagement":
        fail(f"{path} isn't an Engagement plan (it has no project_id), but this run is for Engagement only.")
    keys = ("project_id",) if engagement_plan else ("account", "environment", "site_group_id")
    for k in keys:
        if k != "site_group_id" and plan.get(k) is None:
            fail(f"{path} has no {k}, so it can't be tied to this run.")
        theirs, ours = plan.get(k), ctx.get(k)
        if (theirs is not None or ours is not None) and str(theirs) != str(ours):
            fail(f"{path} is for {k} {theirs!r}, but this run is for {ours!r}. "
                 "Record it in the hand-off file of the run it belongs to.")


def finding_arg(h, fid):
    if fid is None:
        chosen = [f["id"] for f in h["findings"] if f["status"] == "chosen"]
        return chosen[0] if len(chosen) == 1 else None
    if not any(f["id"] == fid for f in h["findings"]):
        fail(f"No finding {fid} in the hand-off file.")
    return fid


def id_target(target, n):
    """The type and ID part of a plan's target ("rule 7001 (Brand boost)" -> "rule 7001"). Names are data:
    they stay out of the change log, and anything that isn't plain text is replaced by the plan step."""
    m = re.match(r"^([A-Za-z][A-Za-z _-]*?\s[\w.:-]*\d[\w.:-]*)(?=$|[\s(,;'\"])", str(target or "").strip())
    return m.group(1) if m and PLAIN.match(m.group(1)) else f"plan step {n}"


def upsert_change(h, entry, keep=()):
    for c in h["changes"]:
        if entry.get("plan_n") is None and c.get("plan_n") is None and all(
                c.get(k) == entry.get(k) for k in ("source", "kind", "target", "tool")):
            entry["id"] = c["id"]
            for k in keep:
                entry[k] = c.get(k)
            c.update(entry)
            return c["id"], False
        if c["source"] == entry["source"] and c.get("plan_n") == entry.get("plan_n") \
                and c.get("plan_file") == entry.get("plan_file") and c["target"] == entry["target"] \
                and entry.get("plan_n") is not None:
            entry["id"] = c["id"]
            if entry["result"] == "unverified":  # re-adding a plan without its verify result keeps the checked one
                entry["result"] = c["result"]
            for k in keep:  # not given this time: keep what was recorded (the live date is the change day)
                entry[k] = c.get(k)
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
        verified = {r.get("n"): r for r in v["results"] if isinstance(r, dict)}
        for x in v.get("not_checked") or []:
            n = x.get("n") if isinstance(x, dict) else x
            verified.setdefault(n, {"result": "not_checked"})
    fid = finding_arg(h, a.finding)
    live_on = (a.live_on or today(a)).isoformat()
    added, updated = [], []
    for c in sorted(plan["changes"], key=lambda c: c.get("n", 0)):
        if c.get("status") != "ready":
            continue
        v = verified.get(c.get("n"), {})
        same = "target" not in v or str(v["target"]) == str(c.get("target"))
        result = (v.get("result") or v.get("state") or "unverified") if same else "unverified"
        if same and str(v.get("action") or "").startswith("none"):
            result = "not_needed"  # a conditional step whose read-back showed nothing to do: no write was made
        if result not in RESULTS:
            result = "unverified"
        entry = {
            "source": a.source, "finding": fid, "plan_file": Path(a.plan).name, "plan_n": c.get("n"),
            "kind": c.get("kind"), "target": id_target(c.get("target"), c.get("n")), "tool": c.get("tool"),
            "live_impact": c.get("live_impact"), "result": result, "live_on": live_on,
            "undo": c.get("undo") or [], "undo_note": c.get("undo_note"),
        }
        cid, new = upsert_change(h, entry, keep=[k for k, given in (("live_on", a.live_on), ("finding", a.finding)) if not given])
        (added if new else updated).append(cid)
    save(h, a.handoff, a)
    print(json.dumps({"ok": True, "added": added, "updated": updated,
                      "made": sum(made(c) for c in h["changes"])}, indent=2))


def cmd_change(a):
    h = read_handoff(a.handoff)
    entry = {"source": a.source, "finding": finding_arg(h, a.finding), "plan_file": None, "plan_n": None,
             "kind": a.kind, "target": a.target, "tool": a.tool, "live_impact": a.live_impact,
             "result": a.result, "live_on": (a.live_on or today(a)).isoformat(), "undo": [],
             "undo_note": a.undo_note}
    cid, _ = upsert_change(h, entry, keep=[k for k, given in (("live_on", a.live_on), ("finding", a.finding)) if not given])
    save(h, a.handoff, a)
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
    if a.status is None and a.outcome is None and a.not_before is None and not a.file:
        fail("Nothing to record: give --status, --outcome, --not-before or --file.")
    if a.outcome in RULES.get("wait_outcomes", []):
        if a.status != "in_progress" or a.not_before is None:
            fail(f"{a.outcome} means the stage isn't finished: record it with --status in_progress and "
                 "--not-before <the date to come back>.")
    elif a.status == "done" and a.outcome is None and rule.get("outcomes"):
        fail(f"Record stage {a.name} done with its --outcome ({', '.join(rule['outcomes'])}).")
    s = stage_record(h, a.name)
    d = today(a).isoformat()
    if a.status is not None:
        s["status"] = a.status
        if a.status in ("in_progress", "done") and not s["started_on"]:
            s["started_on"] = d
        s["done_on"] = d if a.status in ("done", "skipped") else None
    if a.outcome is not None:
        s["outcome"] = a.outcome
    if a.not_before is not None:
        s["not_before"] = a.not_before.isoformat()
    for f in a.file:
        name = Path(f).name
        if name not in s["files"]:
            s["files"].append(name)
    s["files"].sort()
    save(h, a.handoff, a)
    print(json.dumps({"ok": True, "stage": a.name, "status": s["status"], "outcome": s["outcome"],
                      "not_before": s["not_before"]}))


# --- status ------------------------------------------------------------------------------------------

def earliest(h, rule):
    nb = rule.get("not_before")
    if not nb:
        return None
    after = stage_record(h, nb["after_stage"])
    if after["status"] != "done" or not after.get("done_on"):
        return None
    return date.fromisoformat(after["done_on"]) + timedelta(days=int(RULES[nb["days"]]))


def next_step(h, now):
    """The first stage not finished, with why and when."""
    previous = None
    for rule in stages_for(h["playbook"]):
        s = stage_record(h, rule["name"])
        if s["status"] in ("done", "skipped"):
            previous = s
            continue
        skip = None
        if previous is not None and previous["status"] == "skipped":
            skip = f"the {previous['name']} stage before it was skipped."
        for cond in rule.get("skip_when", []):
            other = stage_record(h, cond["stage"])
            if other["outcome"] in cond["outcomes"]:
                skip = cond["reason"]
        dates = [d for d in (earliest(h, rule), s.get("not_before") and date.fromisoformat(s["not_before"])) if d]
        when = max(dates) if dates else None
        return {"stage": rule["name"], "skill": rule["skill"], "writes": rule["writes"], "do": rule["do"],
                "status": s["status"], "not_before": when.isoformat() if when else None,
                "ready": when is None or now >= when, "suggest_skip": skip}
    return None


def flat(v):
    """Print a value from the file on one line: no line breaks or table bars, so it can't add rows or a Next line."""
    return re.sub(r"[\r\n|`*]+", " ", str(v))[:200]


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
        print(f"| {s['name']} | {s['skill']} | {s['status'].replace('_', ' ')} | {flat(s['outcome'] or '')} | {flat(s['done_on'] or '')} |")
    if out["open_findings"]:
        print("\n**Findings to act on:**")
        for f in out["open_findings"]:
            print(f"- {flat(f['id'])} ({flat(f['status'])}, {flat(f.get('priority'))}): {flat(f.get('target'))} "
                  f"{flat(f.get('verdict'))}; {flat(f.get('evidence'))}. Next: {flat(f.get('next_skill'))}")
    if h["changes"]:
        print("\n**Changes made in this run:**")
        for c in h["changes"]:
            print(f"- {flat(c.get('id'))}: {flat(c.get('kind'))} {flat(c.get('target'))} on {flat(c.get('live_on'))} "
                  f"({flat(c.get('result')).replace('_', ' ')}{', live' if c.get('live_impact') == 'live' and made(c) else ''})")
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


def cmd_list(a):
    """Every *.handoff.json in a folder, from any playbook: what's next and when, and the changes made."""
    now = today(a)
    try:
        files = sorted(p for p in Path(a.dir).glob("*.handoff.json") if p.is_file())
    except OSError as e:
        fail(f"Can't read {a.dir}: {e}")
    runs, changes = [], []
    for p in files:
        try:
            with open(p, encoding="utf-8") as f:
                h = json.load(f)
        except (OSError, ValueError):
            runs.append({"file": p.name, "error": "can't be read as a hand-off file"})
            continue
        if not isinstance(h, dict) or h.get("format") != FORMAT:
            runs.append({"file": p.name, "error": "not a hand-off file"})
            continue
        stages = [s for s in h.get("stages") or [] if isinstance(s, dict)]
        nxt = h.get("next") if isinstance(h.get("next"), dict) else None
        due = None
        if nxt and nxt.get("not_before"):
            try:
                due = date.fromisoformat(str(nxt["not_before"]))
            except ValueError:
                due = None
        made_here = [c for c in h.get("changes") or [] if isinstance(c, dict) and made(dict(CHANGE_DEFAULTS, **c))]
        finished = nxt is None and stages and all(s.get("status") in ("done", "skipped") for s in stages)
        runs.append({
            "file": p.name, "playbook": flat(h.get("playbook")), "subject": flat((h.get("subject") or {}).get("kind")),
            "subject_value": flat((h.get("subject") or {}).get("value"))[:80], "started_on": flat(h.get("started_on")),
            "stages_done": sum(s.get("status") in ("done", "skipped") for s in stages), "stages": len(stages),
            "next_stage": None if not nxt else flat(nxt.get("stage")), "next_skill": None if not nxt else flat(nxt.get("skill")),
            "not_before": due.isoformat() if due else None, "due": bool(nxt) and (due is None or now >= due),
            "suggest_skip": bool(nxt and nxt.get("suggest_skip")), "finished": bool(finished),
            "last_outcome": next((flat(s.get("outcome")) for s in reversed(stages) if s.get("outcome")), None),
            "open_findings": sum(isinstance(f, dict) and f.get("status") in ("open", "chosen") for f in h.get("findings") or []),
            "changes_made": len(made_here),
        })
        for c in made_here:
            live = str(c.get("live_on") or "")
            if a.since and (not live or live < a.since.isoformat()):
                continue
            changes.append({"file": p.name, "playbook": flat(h.get("playbook")), "id": flat(c.get("id")),
                            "kind": flat(c.get("kind")), "target": flat(c.get("target")), "live_on": flat(live),
                            "source": flat(c.get("source"))})
    changes.sort(key=lambda c: (c["live_on"], c["file"], c["id"]))
    if a.json:
        print(json.dumps({"ok": True, "today": now.isoformat(), "runs": runs, "changes": changes}, indent=2, ensure_ascii=False))
        return
    if not runs:
        print(f"No *.handoff.json files in {a.dir}.")
        return
    print("| Run | Playbook | Subject | Progress | Next | Due |")
    print("|---|---|---|---|---|---|")
    for r in runs:
        if "error" in r:
            print(f"| {flat(r['file'])} | | | {r['error']} | | |")
            continue
        nxt = "finished" if r["finished"] else (f"{r['next_stage']} ({r['next_skill']})" + (", can be skipped" if r["suggest_skip"] else "")
                                                 if r["next_stage"] else "")
        due = "" if r["finished"] or not r["next_stage"] else ("now" if r["due"] else f"from {r['not_before']}")
        print(f"| {flat(r['file'])} | {r['playbook']} | {r['subject']} | {r['stages_done']}/{r['stages']} stages | {nxt} | {due} |")
    if a.changes:
        print(f"\n**Changes made{' since ' + a.since.isoformat() if a.since else ''}:**")
        for c in changes:
            print(f"- {c['live_on']}: {c['kind']} {c['target']} ({c['playbook']}, {c['file']})")
        if not changes:
            print("- none")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="start a hand-off file for one playbook run")
    p.add_argument("--playbook", required=True, help="playbook name, a key of playbooks in references/rules.json")
    p.add_argument("--subject-kind", required=True, choices=SUBJECT_KINDS, help="what the run is about")
    p.add_argument("--subject", type=plain_arg, help="an ID or plain label (never a query or name from the data)")
    p.add_argument("--subject-file", help="a text file holding the subject (a search query, name) exactly as typed")
    p.add_argument("--account", type=plain_arg, help="Discovery account name")
    p.add_argument("--environment", choices=["production", "staging"], help="Discovery environment")
    p.add_argument("--site-group-id", type=plain_arg, help="Discovery site group ID, when the account has sites")
    p.add_argument("--project-id", type=plain_arg, help="Engagement project ID")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.add_argument("--out", required=True, help="the hand-off file to create, in your working folder")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("findings", help="add findings from a findings file or a saved rule_impact.py result")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--from-file", help="a JSON file with a findings list in the hand-off format's findings shape")
    p.add_argument("--source", type=plain_arg, help="with --from-file: the skill whose result the findings come from")
    p.add_argument("--from-rule-impact", help="rule_impact.py output saved with --out")
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
    p.add_argument("--result", default="unverified", choices=RESULTS,
                   help="what the skill's read-back showed (default unverified): in_place once it confirmed the change")
    p.add_argument("--undo-note", type=plain_arg, help="how a person undoes it, in plain words")
    p.add_argument("--finding", help="the finding it acts on (default: the chosen one)")
    p.add_argument("--live-on", type=day_arg, help="date it went live, YYYY-MM-DD (default: today)")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_change)

    p = sub.add_parser("stage", help="record a stage's progress")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--name", required=True, help="stage name")
    p.add_argument("--status", choices=["in_progress", "done", "skipped"], help="new status (leave out to keep it)")
    p.add_argument("--not-before", type=day_arg, help="don't do this stage before this date, YYYY-MM-DD "
                   "(the agreed test end date, or when to come back after a waiting outcome)")
    p.add_argument("--outcome", help="the stage's outcome, one of its outcomes in references/rules.json")
    p.add_argument("--file", action="append", default=[], help="a file the stage saved in the working folder; repeat")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_stage)

    p = sub.add_parser("status", help="print what's done and what's next")
    p.add_argument("--handoff", required=True, help="the hand-off file")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("list", help="list every run in a folder, from any playbook")
    p.add_argument("--dir", default=".", help="the folder holding the *.handoff.json files (default: the current folder)")
    p.add_argument("--changes", action="store_true", help="also list the changes the runs made")
    p.add_argument("--since", type=day_arg, help="with --changes: only changes live on or after this date")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--today", type=day_arg, help="today's date, YYYY-MM-DD (default: today in UTC)")
    p.set_defaults(fn=cmd_list)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
