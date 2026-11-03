#!/usr/bin/env python3
"""Check Bloomreach Discovery rules against an event window.

Reads rule listings you have already saved from Loomi Connect and flags rules
that would misbehave during a sale, launch or peak event: event rules that
start late, end early, are disabled, never synced or never end; any rule that
expires or starts mid-event; leftovers from past events; and rules locked by a
running A/B test. It never calls the network. Standard library only.

Usage:
    python3 check_rule_windows.py --rules ranking.json --rules media.json ... \
        --start 2026-11-27T00:00:00Z --end 2026-12-01T23:59:59Z \
        [--keywords "black friday,bf,cyber,sale"] [--experiments running.json] \
        [--format markdown|json]

Each --rules file is a saved response from list_site_search_ranking_rules,
list_category_ranking_rules, list_ranking_rules_global,
list_site_search_media_rules, list_category_media_rules,
list_global_media_rules or search_redirects (the whole response, or just its
"data" list; a top-level "result" wrapper is fine). --experiments is a saved
search_discovery_experiments listing (RUNNING, or all statuses).

Prints one row per finding with a suggested status (RED or AMBER), the
evidence and the fix, then a summary line.
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys

DEFAULT_KEYWORDS = "black friday,cyber,bfcm,sale,deal,deals,gift,gifts,holiday,christmas,xmas,clearance,promo"


def load(path, as_json=False):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or d.get('message') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            if as_json:
                print(json.dumps({"ok": False, "error": msg}))
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    if isinstance(doc, dict):
        doc = doc.get("data", doc)
    return doc if isinstance(doc, list) else []


def to_ms(text, end_of_day=False):
    """ISO date or time to epoch ms (UTC if no offset). A date alone means the whole day:
    00:00:00 as a start, 23:59:59 as an end."""
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T23:59:59" if end_of_day else "T00:00:00"
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp() * 1000)


def fmt(ms):
    if not ms:
        return "none"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def kind(rule):
    rt = {"campaign": "media", "ranking": "ranking", "redirect": "redirect", "facet": "facet"}.get(
        rule.get("ruleType"), rule.get("ruleType") or "rule")
    qts = {q.get("queryType") or "" for q in rule.get("queries") or []}
    scope = "global" if any("global" in t for t in qts) else ("category" if "category" in qts else "search")
    return f"{scope} {rt}"


def label(rule):
    name = (rule.get("name") or "").strip()
    qs = ", ".join(str(q.get("query")) for q in (rule.get("queries") or [])[:3])
    shown = f'"{name}" ' if name else ""
    return f"{rule.get('id')} {shown}[{qs}]"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", action="append", required=True)
    ap.add_argument("--start", required=True, help="event start, ISO 8601 (UTC if no offset; a date alone means 00:00)")
    ap.add_argument("--end", required=True, help="event end, ISO 8601 (a date alone means 23:59:59 that day)")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="comma-separated event vocabulary")
    ap.add_argument("--experiments")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a = ap.parse_args()

    try:
        start, end = to_ms(a.start), to_ms(a.end, end_of_day=True)
    except ValueError:
        ap.error(f"--start and --end must be ISO dates or times, like 2026-11-27 or 2026-11-27T00:00:00Z "
                 f"(got {a.start!r} and {a.end!r})")
    if end < start:
        ap.error(f"--end ({a.end}) is before --start ({a.start})")
    as_json = a.format == "json"
    words = [w.strip().lower() for w in a.keywords.split(",") if w.strip()]
    pattern = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)

    rules, seen = [], set()
    for path in a.rules:
        for r in load(path, as_json):
            if r.get("id") not in seen and r.get("ruleType") != "facet":
                seen.add(r.get("id"))
                rules.append(r)

    def is_event(r):
        text = " ".join([r.get("name") or ""] + [str(q.get("query")) for q in r.get("queries") or []])
        return bool(pattern.search(text))

    event_rules = [r for r in rules if is_event(r)]
    # How many enabled event rules cover each (type, query) - to decide RED vs AMBER.
    coverage = collections.Counter()
    for r in event_rules:
        if r.get("enabled"):
            for q in r.get("queries") or []:
                coverage[(r.get("ruleType"), str(q.get("query")).lower())] += 1

    def only_one(r):
        return all(coverage[(r.get("ruleType"), str(q.get("query")).lower())] <= 1 for q in r.get("queries") or [])

    findings = []

    def add(status, r, check, evidence, fix, owner="Merchandiser"):
        findings.append({"status": status, "rule": label(r), "type": kind(r), "check": check,
                         "evidence": evidence, "fix": fix, "owner": owner})

    for r in rules:
        ev, on = is_event(r), bool(r.get("enabled"))
        s, e, tag = r.get("startedAt"), r.get("endedAt"), r.get("durationTag")
        if r.get("isAbTestLive"):
            add("AMBER", r, "In a running A/B test", "isAbTestLive: true",
                "Can't change until the test ends; agree the end date with the test owner", "Test owner")
        if ev and r.get("syncStatus") is None:
            add("RED", r, "Event rule never synced", "syncStatus: null", "Finish and publish it, or delete it")
            continue
        if ev and not on:
            covered = any(coverage[(r.get("ruleType"), str(q.get("query")).lower())] for q in r.get("queries") or [])
            add("AMBER" if covered else "RED", r, "Event rule disabled",
                f"enabled: false; dates {fmt(s)} to {fmt(e)}", "Enable it with the event dates, or remove it")
            continue
        if not on:
            continue
        if tag == "expired" or (e and e < start):
            add("AMBER", r, "Leftover from a past event" if ev else "Expired but still on",
                f"ended {fmt(e)}", "Disable it so it can't be re-enabled by mistake")
            continue
        if ev and s and s > start:
            add("RED" if only_one(r) else "AMBER", r, "Event rule starts late",
                f"starts {fmt(s)}, event starts {fmt(start)}", "Move the start date to the event start (or earlier)")
        elif not ev and s and start < s <= end:
            add("AMBER", r, "Starts mid-event", f"starts {fmt(s)}", "Confirm this is intended")
        if e and start <= e < end:
            add("RED" if ev else "AMBER", r, "Expires mid-event" if not ev else "Event rule ends early",
                f"ends {fmt(e)}, event ends {fmt(end)}",
                "Extend the end date to cover the event" if ev else "Confirm it should stop mid-event; extend it if not")
        if ev and tag == "unscheduled" and not e:
            add("AMBER", r, "Event rule never ends", "durationTag: unscheduled",
                "Add an end date just after the event")

    if not event_rules:
        findings.append({"status": "AMBER", "rule": "-", "type": "-", "check": "No event rules found",
                         "evidence": f"no rule name or query matches: {', '.join(words)}",
                         "fix": "Confirm the vocabulary; if rules were planned, create and schedule them",
                         "owner": "Merchandiser"})

    if a.experiments:
        for x in load(a.experiments, as_json):
            if x.get("experimentStatus") != "RUNNING":
                continue
            ends = x.get("endedAt")
            if ends and ends < start:
                continue
            findings.append({"status": "AMBER", "rule": f"experiment {x.get('id')} \"{x.get('experimentName')}\"",
                             "type": "experiment", "check": "A/B test running into the event",
                             "evidence": f"started {fmt(x.get('startedAt'))}, ends {fmt(ends)}",
                             "fix": "Rule changes in its scope are blocked; end it before the event or freeze event rules now (RED if event rules still need changes)",
                             "owner": "Test owner"})

    order = {"RED": 0, "AMBER": 1}
    findings.sort(key=lambda f: (order[f["status"]], f["type"], f["rule"]))
    summary = {"rules_checked": len(rules), "event_rules": len(event_rules),
               "red": sum(f["status"] == "RED" for f in findings),
               "amber": sum(f["status"] == "AMBER" for f in findings),
               "window": f"{fmt(start)} to {fmt(end)}"}

    if a.format == "json":
        json.dump({"summary": summary, "findings": findings}, sys.stdout, indent=2)
        print()
        return 0
    print(f"Rules checked: {summary['rules_checked']} ({summary['event_rules']} match the event vocabulary). "
          f"Window: {summary['window']}. Findings: {summary['red']} RED, {summary['amber']} AMBER.\n")
    print("| Status | Rule | Type | Check | Evidence | Fix | Owner |")
    print("|---|---|---|---|---|---|---|")
    for f in findings:
        print(f"| {f['status']} | {f['rule']} | {f['type']} | {f['check']} | {f['evidence']} | {f['fix']} | {f['owner']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
