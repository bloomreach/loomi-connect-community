#!/usr/bin/env python3
"""Render a peak readiness checklist from a list of checked items.

Usage:
    python3 render_checklist.py items.json --event "Black Friday" \
        --window "2026-11-27 to 2026-12-01" [--today 2026-10-08] [--event-start 2026-11-27]

items.json is a JSON list. Each item:
    {"area": "Search", "check": "\\"black friday\\" query", "status": "RED",
     "evidence": "auto-corrected to 'black frisky'", "fix": "Add a redirect",
     "owner": "Merchandiser", "lead_time": "same day"}

status is RED, AMBER, GREEN or NOT CHECKED (any case). lead_time is optional.
Blockers (RED) come first, then AMBER, by area order: Data, Merchandising,
Search, Marketing, On-site (area matched in any case). Prints a Markdown checklist and a
verdict: NO-GO, GO WITH FIXES, INCOMPLETE (nothing failed, but something wasn't
checked) or GO (everything checked and GREEN).
Standard library only; no network access.
"""
import argparse
import datetime as dt
import json
import sys

AREAS = ["Data", "Merchandising", "Landing pages", "Search", "Marketing", "On-site"]
CRITICAL_AREAS = {"Data", "Search", "Landing pages"}


def area_key(a):
    return AREAS.index(a) if a in AREAS else len(AREAS)


def canonical_area(a):
    """The area as named in AREAS, whatever its case; other areas unchanged."""
    text = str(a or "").strip()
    return next((x for x in AREAS if x.lower() == text.lower()), text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("items")
    ap.add_argument("--event", required=True)
    ap.add_argument("--window", required=True)
    ap.add_argument("--today", help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--event-start", help="YYYY-MM-DD, to print days to go")
    a = ap.parse_args()

    with open(a.items, encoding="utf-8") as f:
        items = json.load(f)
    for i in items:
        i["status"] = str(i.get("status") or "NOT CHECKED").strip().upper()
        i["area"] = canonical_area(i.get("area"))

    red = sorted([i for i in items if i["status"] == "RED"], key=lambda i: area_key(i.get("area")))
    amber = sorted([i for i in items if i["status"] == "AMBER"], key=lambda i: area_key(i.get("area")))
    green = [i for i in items if i["status"] == "GREEN"]
    unchecked = [i for i in items if i["status"] not in ("RED", "AMBER", "GREEN")]

    no_events = any("send" in (i.get("check") or "").lower() and i.get("area") == "Marketing" for i in red)
    if any(i.get("area") in CRITICAL_AREAS for i in red) or no_events:
        verdict = "NO-GO"
    elif red or amber:
        verdict = "GO WITH FIXES"
    elif unchecked or not green:
        verdict = "INCOMPLETE"
    else:
        verdict = "GO"

    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    togo = ""
    if a.event_start:
        togo = f"; {(dt.date.fromisoformat(a.event_start) - today).days} days to go"

    print(f"## Peak readiness: {a.event}, {a.window}")
    print(f"Checked {today.isoformat()}{togo}.\n")
    print(f"**Verdict:** {verdict}: {len(red)} blocker(s), {len(amber)} amber, {len(green)} green, "
          f"{len(unchecked)} not checked.\n")

    def table(rows, title):
        if not rows:
            return
        print(f"### {title}")
        print("| # | Area | Check | Evidence | Fix | Owner |")
        print("|---|---|---|---|---|---|")
        for n, i in enumerate(rows, 1):
            print(f"| {n} | {i.get('area', '')} | {i.get('check', '')} | {i.get('evidence', '')} | "
                  f"{i.get('fix', '')} | {i.get('owner', '')} |")
        print()

    table(red, "Blockers (fix before the event)")
    table(amber, "Amber (fix or accept)")
    if green:
        print("### Green")
        by_area = {}
        for i in green:
            by_area.setdefault(i.get("area", "Other"), []).append(i.get("check", ""))
        for area in sorted(by_area, key=area_key):
            print(f"- **{area}:** {'; '.join(by_area[area])}")
        print()
    if unchecked:
        print("**Not checked:** " + "; ".join(f"{i.get('area')}: {i.get('check')} ({i.get('evidence', 'no access')})"
                                             for i in unchecked))
    slow = [i for i in red + amber if (i.get("lead_time") or "").lower() not in ("", "same day", "minutes")]
    if slow:
        print("**Lead times:** " + "; ".join(f"{i.get('check')}: {i.get('lead_time')}" for i in slow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
