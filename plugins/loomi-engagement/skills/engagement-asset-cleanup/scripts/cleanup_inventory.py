#!/usr/bin/env python3
"""Turn saved Bloomreach Engagement list responses into a cleanup list.

Standard library only. No network access. It reads JSON list responses the
assistant has already saved (search_scenarios, search_email_campaigns,
search_segmentations, search_aggregates, ...) and prints findings grouped by
asset type, each with a suggested action: delete, archive or review with owner.
It never prints editor names or email addresses.

Usage:
    python3 cleanup_inventory.py [--now UNIX_TS] [--draft-days 90]
        [--inactive-days 180] [--active-days 365] KIND:FILE [KIND:FILE ...]

Kinds: scenario, email, sms, segmentation, event_segmentation, aggregate,
running_aggregate, expression, customer_filter, report, funnel, trend,
dashboard. Pass several files of the same kind for paginated lists.
"""
import json
import re
import sys
import time

KINDS = {
    "scenario": "Scenarios", "email": "Email campaigns", "sms": "SMS campaigns",
    "segmentation": "Segmentations", "event_segmentation": "Event segmentations",
    "aggregate": "Aggregates", "running_aggregate": "Running aggregates",
    "expression": "Expressions", "customer_filter": "Customer filters",
    "report": "Reports", "funnel": "Funnels", "trend": "Trends", "dashboard": "Dashboards",
}
CAMPAIGNS = {"scenario", "email", "sms"}
INITIATIVE_KINDS = {"scenario", "email", "report", "funnel", "trend"}

TEST = re.compile(
    r"(\bcopy of\b|\(copy\)|\bcopy\b|\btest(ing)?\b|\btmp\b|\btemp\b|\bold\b|\bbackup\b|"
    r"\bdraft\b|\bdev\b|\bqa\b|\bpoc\b|\bsandbox\b|\bdo not use\b|\bdnu\b|\bdelete\b)", re.I)
MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
DATED = re.compile(
    r"(\b20\d\d[-_/.]\d{1,2}[-_/.]\d{1,2}\b|\b\d{1,2}[-_/.]\d{1,2}[-_/.](20)?\d\d\b|"
    r"\bq[1-4][ -]?20\d\d\b|\b" + MONTHS + r"[ -]?(20)?\d\d\b|\b(bf|cm|xmas)[ -]?20\d\d\b)", re.I)
ARCHIVED_LABEL = re.compile(r"^\s*(\[?archived\]?|zz+|xx+)\b", re.I)
REFERENCE = re.compile(r"\[(ref|template)\]|\btemplate\b", re.I)
NORMALISE = re.compile(r"(\[[^\]]*\]|\(\d+\)|\bv\d+\b|\bnew\b|\bcopy of\b|\bcopy\b|\btest\b|\bold\b)", re.I)


def records(obj, path):
    for o in (obj, obj.get("result") if isinstance(obj, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(obj, dict) and "result" in obj:
        obj = obj["result"]
    if isinstance(obj, dict) and "data" in obj:
        obj = obj["data"]
    if isinstance(obj, dict):
        return [obj]
    return [x for x in obj if isinstance(x, dict)] if isinstance(obj, list) else []


def age_days(rec, now):
    ts = rec.get("edited") or rec.get("created")
    try:
        return int((now - float(ts)) / 86400)
    except (TypeError, ValueError):
        return None


def base(name):
    n = NORMALISE.sub(" ", name or "")
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    now, draft_d, inactive_d, active_d = time.time(), 90, 180, 365
    args, files = argv[1:], []
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    i = 0
    while i < len(args):
        flag = args[i]
        if flag in ("--now", "--draft-days", "--inactive-days", "--active-days"):
            val = float(args[i + 1])
            if flag == "--now":
                now = val
            elif flag == "--draft-days":
                draft_d = int(val)
            elif flag == "--inactive-days":
                inactive_d = int(val)
            else:
                active_d = int(val)
            i += 2
            continue
        files.append(flag)
        i += 1
    if not files:
        print(__doc__)
        return 2

    items = {}
    for f in files:
        if ":" not in f or f.split(":", 1)[0] not in KINDS:
            print(f"Skipping {f}: prefix it with a kind, e.g. scenario:{f}")
            continue
        kind, path = f.split(":", 1)
        with open(path, encoding="utf-8") as fh:
            for r in records(json.load(fh), path):
                rid = r.get("_id") or r.get("id") or r.get("name")
                items.setdefault(kind, {})[str(rid)] = r

    # Expressions bind aggregates by ID or name; collect both to treat them as used.
    bound = set()
    for r in items.get("expression", {}).values():
        bound.update(re.findall(r"[0-9a-f]{24}", json.dumps(r)))

    totals = {"Delete": 0, "Archive": 0, "Review with owner": 0}
    print("| Asset type | Checked | Delete | Archive | Review |\n|---|---|---|---|---|")
    sections = []
    for kind, label in KINDS.items():
        recs = [r for r in items.get(kind, {}).values() if not r.get("archived")]
        if kind not in items:
            continue
        findings = []
        filed = sum(1 for r in recs if r.get("initiative_id"))
        uses_initiatives = kind in INITIATIVE_KINDS and recs and filed / len(recs) >= 0.66
        groups = {}
        for r in recs:
            name = (r.get("name") or "?").strip()
            groups.setdefault(base(name), []).append(name)
            status = r.get("status")
            age = age_days(r, now)
            is_test = bool(TEST.search(name)) and not REFERENCE.search(name)
            used_by = r.get("used_by")
            exposed = r.get("all_exposing_properties")
            unused = used_by is not None and not used_by and not exposed and str(r.get("_id")) not in bound
            active = status == "active"
            old = f"{age}d" if age is not None else "?"

            action = why = None
            if ARCHIVED_LABEL.search(name):
                action, why = "Archive", "named as archived but isn't"
            elif is_test and active:
                action, why = "Review with owner", "active, but named like a test or copy"
            elif is_test and (unused or (kind in CAMPAIGNS and status != "active")):
                action, why = "Delete", ("test or copy, not active" if kind in CAMPAIGNS
                                         else "test or copy, nothing references it")
            elif is_test:
                action, why = "Review with owner", "test or copy, but referenced or usage unknown"
            elif kind in CAMPAIGNS and status == "draft" and age is not None and age > draft_d:
                action, why = "Archive", f"draft never launched, last edited {old} ago"
            elif kind in CAMPAIGNS and status in ("inactive", "paused") and age is not None and age > inactive_d:
                action, why = "Archive", f"{status}, last edited {old} ago"
            elif kind in CAMPAIGNS and active and age is not None and age > active_d:
                action, why = "Review with owner", f"active but untouched for {old}; confirm it's current"
            elif unused and age is not None and age > inactive_d:
                action, why = "Archive", f"nothing references it; last edited {old} ago"
            elif unused:
                action, why = "Review with owner", "nothing tracked references it"
            elif DATED.search(name) and not active and kind in CAMPAIGNS:
                action, why = "Archive", "dated name, not active"
            elif uses_initiatives and not r.get("initiative_id"):
                action, why = "Review with owner", "not filed in an initiative"
            if action:
                findings.append((action, name, status or "-", old, why))

        for names in groups.values():
            if len(names) > 1:
                findings.append(("Review with owner", " / ".join(names[:4]), "-", "-",
                                 f"{len(names)} items with near-identical names"))

        counts = {a: sum(1 for f in findings if f[0] == a) for a in totals}
        for a in totals:
            totals[a] += counts[a]
        print(f"| {label} | {len(recs)} | {counts['Delete']} | {counts['Archive']} | {counts['Review with owner']} |")
        if kind in ("expression", "customer_filter"):
            findings.append(("Info", "-", "-", "-", "usage not checkable (no used_by field)"))
        if findings:
            sections.append((label, findings))

    order = {"Review with owner": 0, "Delete": 1, "Archive": 2, "Info": 3}
    for label, findings in sections:
        print(f"\n### {label}\n| Name | Status | Age | Finding | Suggested action |\n|---|---|---|---|---|")
        for action, name, status, old, why in sorted(findings, key=lambda f: order[f[0]]):
            print(f"| {name} | {status} | {old} | {why} | {action} |")
    print(f"\n**Summary:** {totals['Delete']} to delete, {totals['Archive']} to archive, "
          f"{totals['Review with owner']} to review with owner.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
