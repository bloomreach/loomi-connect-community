#!/usr/bin/env python3
"""Audit saved Bloomreach Engagement recommendation engine responses.

Standard library only. No network access. It reads JSON responses the
assistant has already saved and prints audit findings:

  --engines     search_recommendations detail responses (one per file, or a list)
  --catalogs    a search_catalogs list response
  --jobs        list_catalog_jobs responses; name each file so it contains the
                catalog ID (e.g. jobs_<catalogId>.json), or prefix it as
                <catalogId>:file.json
  --placements  any placement responses (scenario details, scenario nodes,
                email campaign details, banner details) to search for engine IDs

It never prints placement content, editor names or catalog item values: only
engine names and IDs, placement names, types and statuses.

Usage:
    python3 audit_engines.py --engines e1.json e2.json --catalogs catalogs.json \
        --jobs jobs_<id>.json --placements scenario_*.json email_*.json banner_*.json \
        [--now UNIX_TS] [--stale-days 7] [--unused-days 90]
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

TEST_NAMES = re.compile(r"\b(test|testing|copy|old|dev|poc|qa|sandbox|tmp|temp|draft)\b", re.I)
HEX_ID = re.compile(r"[0-9a-f]{24}")
TYPE_HINTS = {
    "recently_viewed": re.compile(r"recent", re.I),
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def unwrap(obj):
    """Return a list of records from a list or detail response."""
    while isinstance(obj, dict) and ("result" in obj or "data" in obj) and not obj.get("_id"):
        obj = obj.get("result", obj.get("data"))
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def canon(value):
    return json.dumps(value, sort_keys=True, default=str)


def summarise(engine):
    d = engine.get("definition") or {}
    mapping = d.get("mapping") or {}
    event = d.get("event") or {}
    attr = (event.get("attribute") or {}).get("property")
    date = d.get("date_filter") or {}
    lookback = None
    if date.get("enabled"):
        dur = date.get("duration") or {}
        lookback = f"{dur.get('count')} {dur.get('units')}" if dur else "absolute range"
    return {
        "id": engine.get("_id"),
        "name": engine.get("name") or "(unnamed)",
        "status": engine.get("status") or d.get("status"),
        "archived": bool(engine.get("archived")),
        "edited": engine.get("edited") or engine.get("created"),
        "type": d.get("type"),
        "catalog": mapping.get("catalog"),
        "catalog_filters": mapping.get("filter") or [],
        "event": f"{event.get('event_type')}.{attr}" if event else None,
        "event_filter": d.get("event_filter") or [],
        "lookback": lookback,
        "lookback_raw": date if date.get("enabled") else None,
        "exclusions": bool(d.get("blacklist_enabled")),
        "exclusion_rules": d.get("blacklist_rules") or [],
        "dynamic_filters": bool(d.get("dynamic_catalog_filter_enabled")),
        "preferences": bool(d.get("customer_preferences_enabled")),
        "pinning": bool(d.get("pinning_pid_enabled") or d.get("pinning_attribute_filter_enabled")),
    }


def lookback_days(raw):
    dur = (raw or {}).get("duration") or {}
    per = {"days": 1, "weeks": 7, "months": 30, "quarters": 91, "years": 365, "hours": 1 / 24}
    try:
        return float(dur.get("count")) * per.get(dur.get("units"), 1)
    except (TypeError, ValueError):
        return None


def placement_label(rec, path):
    name = rec.get("name") or rec.get("scenario_name") or os.path.basename(path)
    status = rec.get("status") or "?"
    kind = "placement"
    if "scenario_id" in rec or "nodes" in rec or "node" in rec:
        kind = "scenario"
    elif "variants" in rec and "trigger" in rec:
        kind = "web layer"
    elif "ab_split" in rec or "consent_category" in rec or "email" in canon(rec.get("type", "")):
        kind = "email campaign"
    return f"{name} ({kind}, {status})"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engines", nargs="+", required=True)
    ap.add_argument("--catalogs")
    ap.add_argument("--jobs", nargs="*", default=[])
    ap.add_argument("--placements", nargs="*", default=[])
    ap.add_argument("--now", type=float, default=time.time())
    ap.add_argument("--stale-days", type=float, default=7)
    ap.add_argument("--unused-days", type=float, default=90)
    a = ap.parse_args()

    engines = []
    for p in a.engines:
        for rec in unwrap(load(p)):
            if rec.get("_id"):
                engines.append(summarise(rec))
    if not engines:
        print("No engines found in the input.")
        return 0
    by_id = {e["id"]: e for e in engines}

    catalogs = {}
    if a.catalogs:
        for c in unwrap(load(a.catalogs)):
            catalogs[c.get("_id")] = c

    # Catalog freshness from saved jobs.
    freshness = {}
    for spec in a.jobs:
        cat_id, _, path = spec.rpartition(":") if ":" in spec else ("", "", spec)
        if not cat_id:
            m = HEX_ID.search(os.path.basename(path))
            cat_id = m.group(0) if m else None
        data = load(path)
        if isinstance(data, dict) and data.get("success") is False:
            freshness[cat_id] = f"unknown ({data.get('error') or 'no jobs'})"
            continue
        jobs = unwrap(data)
        if not jobs:
            freshness[cat_id] = "no update history"
            continue
        jobs.sort(key=lambda j: j.get("created") or 0, reverse=True)
        latest = jobs[0]
        ok = [j for j in jobs if j.get("state") == "success"]
        age = (a.now - ok[0]["created"]) / 86400 if ok and ok[0].get("created") else None
        if latest.get("state") == "fail":
            freshness[cat_id] = f"FAILING (latest {latest.get('type')} job failed)"
        elif age is None:
            freshness[cat_id] = "no successful job"
        elif age > a.stale_days:
            freshness[cat_id] = f"STALE (last success {age:.0f} days ago)"
        else:
            freshness[cat_id] = f"fresh (last success {age:.1f} days ago)"

    # Placement references: search each saved response for engine IDs.
    used_in = defaultdict(list)
    for p in a.placements:
        for rec in unwrap(load(p)):
            text = canon(rec)
            for eid in by_id:
                if eid and eid in text:
                    used_in[eid].append(placement_label(rec, p))

    # Engine table.
    print("## Engines")
    print("| Engine | Status | Type | Catalog (freshness) | Learns from | Look-back | Filters / exclusions | Used in |")
    print("|---|---|---|---|---|---|---|---|")
    for e in engines:
        cat = e["catalog"]
        cname = (catalogs.get(cat) or {}).get("name", cat) if catalogs else cat
        if catalogs and cat not in catalogs:
            cname = f"{cat} (NOT FOUND)"
        version = (catalogs.get(cat) or {}).get("catalog_version")
        fresh = freshness.get(cat) or ("unknown (v1 catalog)" if version == "v1" else "not checked")
        filt = []
        if e["catalog_filters"]:
            filt.append(f"{len(e['catalog_filters'])} catalog")
        if e["event_filter"]:
            filt.append(f"{len(e['event_filter'])} event")
        if e["exclusions"]:
            filt.append("exclusions")
        if e["dynamic_filters"]:
            filt.append("dynamic")
        if e["pinning"]:
            filt.append("pinning")
        uses = "; ".join(sorted(set(used_in.get(e["id"], [])))) or "not found"
        print(f"| {e['name']} | {e['status']}{' (archived)' if e['archived'] else ''} | {e['type']} | "
              f"{cname} ({fresh}) | {e['event']} | {e['lookback'] or 'all history'} | "
              f"{', '.join(filt) or 'none'} | {uses} |")

    print("\n## Findings")
    findings = []
    live = [e for e in engines if not e["archived"]]

    # Near-duplicates.
    groups = defaultdict(list)
    for e in live:
        key = (e["type"], e["catalog"], e["event"], canon(e["catalog_filters"]),
               canon(e["event_filter"]), e["exclusions"], canon(e["exclusion_rules"]))
        groups[key].append(e)
    for members in groups.values():
        if len(members) > 1:
            names = ", ".join(m["name"] for m in members)
            looks = {m["lookback"] or "all history" for m in members}
            diff = f"; differ only in look-back ({', '.join(sorted(looks))})" if len(looks) > 1 else ""
            findings.append(("Review", f"Near-duplicates: {names} (same type, catalog, event and filters{diff})"))

    for e in live:
        cat = e["catalog"]
        fresh = freshness.get(cat, "")
        used = bool(used_in.get(e["id"]))
        if catalogs and cat not in catalogs:
            findings.append(("Action", f"{e['name']}: catalog {cat} not found (deleted?)"))
        if fresh.startswith(("FAILING", "STALE")):
            findings.append(("Action" if used else "Review", f"{e['name']}: catalog is {fresh}"))
        if used and e["status"] and e["status"] != "running":
            findings.append(("Action", f"{e['name']}: status {e['status']} but used in an active placement"))
        if not e["catalog_filters"] and not e["exclusions"] and not e["dynamic_filters"]:
            findings.append(("Review", f"{e['name']}: no catalog filter and no exclusions"))
        days = lookback_days(e["lookback_raw"])
        if len(e["catalog_filters"]) >= 3 or (days is not None and days < 7) or e["pinning"]:
            findings.append(("Review", f"{e['name']}: possibly too restrictive "
                                       f"({len(e['catalog_filters'])} catalog filters, look-back {e['lookback'] or 'all'}, "
                                       f"pinning {'on' if e['pinning'] else 'off'})"))
        hint = TYPE_HINTS.get(e["type"] or "")
        if hint and not hint.search(e["name"]):
            findings.append(("Review", f"{e['name']}: name doesn't match type {e['type']}"))
        if a.placements and not used:
            age = (a.now - e["edited"]) / 86400 if e["edited"] else None
            sev = "Cleanup" if age is None or age > a.unused_days else "Review"
            findings.append((sev, f"{e['name']}: not found in the placements searched"
                                  f"{f' (last edited {age:.0f} days ago)' if age else ''}; may still be called through the API"))
        if TEST_NAMES.search(e["name"]):
            findings.append(("Review" if used else "Cleanup", f"{e['name']}: test-like name"))

    order = {"Action": 0, "Review": 1, "Cleanup": 2}
    for sev, text in sorted(findings, key=lambda f: order.get(f[0], 9)):
        print(f"- **{sev}:** {text}")
    if not findings:
        print("- No findings.")
    if not a.placements:
        print("\nPlacements weren't supplied, so usage wasn't checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
