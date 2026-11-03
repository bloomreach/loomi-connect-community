#!/usr/bin/env python3
"""Join a campaign calendar with message check findings into one go/no-go list of upcoming sends.

Usage:
  python3 preflight_report.py --calendar week1.json [--calendar week2.json ...] --findings findings.json
         [--findings more.json ...] [--from 2026-11-03T00:00:00Z] [--to 2026-11-10T00:00:00Z]
         [--include-drafts] [--include-webhooks] [--out preflight.json]

--calendar is a saved get_campaign_calendar result (one per week; the same format engagement-send-collision-check
reads). --findings is the output of message_checks.py run over every campaign and scenario in the calendar.
Give the scenarios to message_checks.py as whole scenarios fetched with include_node_designs=true, so each
step's findings carry the scenario ID (parent_id) and can be matched to its calendar entry.

Prints JSON: one row per scheduled send (a campaign, or one step of a scenario), soonest first, with its
sends in the window, the worst verdict across its variants, finding counts and the top findings; sends
the checks didn't cover ("not checked"); and totals. Drafts, inactive and finished campaigns are left out
unless --include-drafts. Standard library only; no network access.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone

INACTIVE = {"draft", "inactive", "finished", "stopped"}
SEVERITIES = ("blocker", "warning", "nitpick")
CHECKABLE = {"email", "sms", "pushmob", "push"}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(d, dict) and d.get("ok") is False:
            fail(f"{path}: the message checks failed: {d.get('error')}")
    return data


def calendar_entries(path):
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and data.get("error"):
        fail(f"{path}: the calendar call failed ({data['error']}). Retry with a narrower window.")
    return data.get("campaigns", []) if isinstance(data, dict) else data


def ts(v):
    """ISO date or time as Unix seconds; no offset means UTC."""
    if v is None:
        return None
    try:
        t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date or time: {v!r}")
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def verdict(counts):
    if counts is None:
        return "NOT CHECKED"
    return "NO-GO" if counts["blocker"] else "GO WITH CAUTION" if counts["warning"] else "GO"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold emoji; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calendar", action="append", required=True, help="saved get_campaign_calendar result (repeat per week)")
    ap.add_argument("--findings", action="append", required=True, help="message_checks.py output (repeat for several runs)")
    ap.add_argument("--from", dest="start", type=ts, help="ISO start of the window (default: no lower limit)")
    ap.add_argument("--to", dest="end", type=ts, help="ISO end of the window (default: no upper limit)")
    ap.add_argument("--include-drafts", action="store_true", help="keep draft, inactive and finished campaigns")
    ap.add_argument("--include-webhooks", action="store_true", help="keep webhook steps (they're never checked)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    start, end = a.start, a.end

    by_step, by_campaign, skipped_steps = {}, {}, {}
    for path in a.findings:
        f = read_json(path)
        for m in f.get("messages", []):
            if m["source"] == "scenario":
                by_step.setdefault((m.get("parent_id"), m["id"]), []).append(m)
            else:
                by_campaign.setdefault(m.get("parent_id") or m["id"], []).append(m)
        for s in f.get("not_checked", []):
            skipped_steps[(s.get("parent_id"), s.get("id"))] = s

    rows, left_out = {}, Counter()
    for path in a.calendar:
        for c in calendar_entries(path):
            status = str(c.get("status") or "").lower()
            channel = str(c.get("channel") or "").lower()
            if status in INACTIVE and not a.include_drafts:
                left_out[f"{status} sends"] += 1
                continue
            if channel == "webhook" and not a.include_webhooks:
                left_out["webhook steps"] += 1
                continue
            times = sorted(t["start"] for t in c.get("times") or [] if t.get("start") is not None
                           and (start is None or t["start"] >= start) and (end is None or t["start"] < end))
            if not times:
                continue
            key = (c.get("campaign_id"), c.get("action_id"))
            row = rows.setdefault(key, {"campaign_id": key[0], "action_id": key[1], "campaign": c.get("campaign_name"),
                                        "step": c.get("action_name"), "channel": channel, "status": status,
                                        "trigger": c.get("trigger"), "times": set(),
                                        "reach": (c.get("results") or {}).get("reach") or (c.get("results") or {}).get("potential_reach")})
            row["times"].update(times)

    out_rows = []
    for (cid, aid), row in rows.items():
        msgs = by_step.get((cid, aid)) or by_campaign.get(cid) or []
        counts = None
        reason = None
        if msgs:
            counts = Counter({s: 0 for s in SEVERITIES})
            for m in msgs:
                counts.update(m["counts"])
            counts = dict(counts)
        elif (cid, aid) in skipped_steps or row["channel"] not in CHECKABLE:
            reason = f"{row['channel']} isn't covered by the message checks; check it by hand"
        else:
            reason = "no findings for this send: fetch it and run message_checks.py on it"
        top = sorted((dict(f, variant=m.get("variant") or m.get("language")) for m in msgs for f in m["findings"]),
                     key=lambda f: SEVERITIES.index(f["severity"]))[:5]
        times = sorted(row.pop("times"))
        out_rows.append(dict(row, first_send=iso(times[0]), sends_in_window=len(times), messages=len(msgs),
                             verdict=verdict(counts), counts=counts, top_findings=top, not_checked_reason=reason))
    out_rows.sort(key=lambda r: (r["first_send"], r["campaign"] or "", r["step"] or ""))
    totals = Counter(r["verdict"] for r in out_rows)
    overall = ("NO-GO" if totals["NO-GO"] else "GO WITH CAUTION" if totals["GO WITH CAUTION"] or totals["NOT CHECKED"]
               else "GO" if out_rows else "NOTHING SCHEDULED")
    out = {"ok": True, "window": {"from": iso(start) if start is not None else None, "to": iso(end) if end is not None else None}, "overall": overall,
           "totals": {k: totals[k] for k in ("NO-GO", "GO WITH CAUTION", "GO", "NOT CHECKED")},
           "left_out": dict(left_out), "sends": out_rows}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
