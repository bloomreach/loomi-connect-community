#!/usr/bin/env python3
"""Work out the preflight window: the get_campaign_calendar calls to make, and the live flows to check.

Usage:
  python3 send_window.py [--days 7] [--now 2026-11-03T09:00:00Z] [--scenarios scenarios.json ...]
         [--edited-days 7] [--out window.json]

Prints JSON with:
  - from / to: the window as ISO times, to pass to preflight_report.py --from and --to;
  - calendar_calls: one {from_ts, to_ts} pair (Unix seconds) per week of the window, for get_campaign_calendar;
  - recently_edited / not_recent: when --scenarios is given (saved search_scenarios list results for active,
    event-triggered scenarios), the ones edited within --edited-days of now, and the others' names.

The day lengths come from references/rules.json (window_days, edited_days). Standard library only; no network access.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "preflight-rules.json").read_text(encoding="utf-8"))


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def when(v):
    try:
        t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date or time: {v!r}")
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scenarios(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data.get("data", []) if isinstance(data, dict) else data


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=RULES["window_days"], help="length of the window in days (default: rules)")
    ap.add_argument("--now", type=when, help="ISO start of the window (default: the current UTC time)")
    ap.add_argument("--scenarios", action="append", default=[], help="saved search_scenarios list result (repeat per page)")
    ap.add_argument("--edited-days", type=int, default=RULES["edited_days"], help="a live flow edited within this many days is checked")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if a.days < 1:
        fail("--days must be at least 1")
    now = a.now or datetime.now(timezone.utc)
    end = now + timedelta(days=a.days)
    calls, start = [], now
    while start < end:
        stop = min(start + timedelta(days=7), end)
        calls.append({"from_ts": int(start.timestamp()), "to_ts": int(stop.timestamp()), "from": iso(start), "to": iso(stop)})
        start = stop
    out = {"ok": True, "from": iso(now), "to": iso(end), "calendar_calls": calls}
    if a.scenarios:
        cutoff = (now - timedelta(days=a.edited_days)).timestamp()
        recent, old = [], []
        for path in a.scenarios:
            for s in scenarios(path):
                if str(s.get("status") or "").lower() != "active" or s.get("archived"):
                    continue
                edited = s.get("edited") or s.get("created") or 0
                (recent if edited >= cutoff else old).append({"id": s.get("_id"), "name": s.get("name"),
                                                               "edited": iso(datetime.fromtimestamp(edited, timezone.utc))})
        out["recently_edited"] = sorted(recent, key=lambda s: s["edited"], reverse=True)
        out["not_recent"] = sorted(s["name"] or s["id"] for s in old)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
