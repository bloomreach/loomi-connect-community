#!/usr/bin/env python3
"""Summarise Bloomreach Discovery catalog feed and index jobs for a freshness check.

Usage:
  python3 discovery_jobs_summary.py [--now 2026-01-31T12:00:00Z] jobs_page1.json [jobs_page2.json ...]

Each input file is the raw JSON returned by search_discovery_catalog_jobs (list mode).
The tool's `status` filter may be ignored by the server, so this script filters locally.

Prints JSON with, for each job kind (feed:products, index:update, suggest, ...):
the latest job, the latest success, hours since that success, failures in the window,
warnings in status messages, and product-count changes between index jobs.
Also prints a suggested red/amber/green status for the catalog, using the thresholds in
references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, shared with apps that rate the same jobs.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
FAILED = set(RULES["failed_statuses"])
SUCCESS = RULES["success_status"]
CORE = tuple(RULES["core_kinds"])


def ts(v):
    """ISO date or time; a time with no offset (or a date alone) is taken as UTC."""
    if not v:
        return None
    t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load(paths):
    jobs = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for d in (data, data.get("result") if isinstance(data, dict) else None):
            if isinstance(d, dict) and d.get("success") is False:
                fail(f"{p}: Loomi Connect returned an error: {d.get('error') or d.get('message') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(data.get("result"), dict):
            data = data["result"]
        for j in data.get("data") or []:
            jobs[j["id"]] = j
    return sorted(jobs.values(), key=lambda j: j.get("created_at") or "", reverse=True)


def message(j):
    """A job's status message; blank or whitespace is none."""
    return str(j.get("status_message") or "").strip()


def kind(j):
    props = j.get("properties") or {}
    t = j.get("type") or "other"
    if t == "feed":
        return f"feed:{props.get('feed_data_type') or 'unknown'}"
    if t == "index":
        return f"index:{props.get('index_mode') or 'unknown'}"
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--now", help="ISO timestamp to measure age against (default: current UTC time)")
    ap.add_argument("--stale-hours", type=float, default=RULES["stale_hours"],
                    help="age of last product feed or index that counts as red (default: references/rules.json)")
    a = ap.parse_args()
    try:
        now = ts(a.now) if a.now else datetime.now(timezone.utc)
    except ValueError:
        ap.error(f"--now must be an ISO date or time, like 2026-01-31 or 2026-01-31T12:00:00Z (got {a.now!r})")

    jobs = load(a.jobs)
    kinds = {}
    for j in jobs:
        kinds.setdefault(kind(j), []).append(j)

    out, reasons = {}, {"red": [], "amber": []}
    for k, js in kinds.items():
        ok = [j for j in js if j.get("status") == SUCCESS]
        bad = [j for j in js if j.get("status") in FAILED]
        warn = [j for j in ok if message(j)]
        last_ok = ok[0] if ok else None
        age = None
        if last_ok:
            end = ts(last_ok.get("stopped_at") or last_ok.get("created_at"))
            age = round((now - end).total_seconds() / 3600, 1)
        counts = [(j.get("created_at"), (j.get("stats") or {}).get("product_doc_count")) for j in ok
                  if (j.get("stats") or {}).get("product_doc_count") is not None]
        out[k] = {
            "jobs_in_window": len(js),
            "latest": {f: js[0].get(f) for f in ("id", "status", "status_message", "created_at", "stopped_at")},
            "latest_success_at": last_ok and (last_ok.get("stopped_at") or last_ok.get("created_at")),
            "hours_since_success": age,
            "failures": [{f: j.get(f) for f in ("id", "status", "status_message", "created_at")} for j in bad],
            "warnings": sorted({message(j) for j in warn}),
            "product_doc_counts": counts[:5],
        }
        core = k in CORE
        if js[0].get("status") in FAILED:
            reasons["red" if core else "amber"].append(f"latest {k} job {js[0].get('status')}")
        elif bad:
            reasons["amber"].append(f"{len(bad)} failed {k} job(s) in window")
        if out[k]["warnings"]:
            reasons["amber"].append(f"{k} warnings: {'; '.join(out[k]['warnings'])[:200]}")
        if len(counts) >= 2 and counts[1][1]:
            drop = (counts[1][1] - counts[0][1]) / counts[1][1] * 100
            if drop >= RULES["count_drop_amber_pct"]:
                reasons["red" if drop >= RULES["count_drop_red_pct"] else "amber"].append(f"{k} product count fell {drop:.0f}%")

    fresh = [out[k]["hours_since_success"] for k in CORE
             if k in out and out[k]["hours_since_success"] is not None]
    if not fresh:
        reasons["red"].append("no successful product feed or index job in the window")
    elif min(fresh) > a.stale_hours:
        reasons["red"].append(f"last product feed or index success {min(fresh):.0f}h ago")
    elif min(fresh) > a.stale_hours * RULES["aging_share"]:
        reasons["amber"].append(f"last product feed or index success {min(fresh):.0f}h ago")

    status = "red" if reasons["red"] else "amber" if reasons["amber"] else "green"
    json.dump({"now": now.isoformat(), "status": status, "reasons": reasons["red"] + reasons["amber"],
               "kinds": out}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
