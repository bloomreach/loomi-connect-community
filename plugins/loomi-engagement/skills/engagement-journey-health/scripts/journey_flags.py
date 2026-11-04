#!/usr/bin/env python3
"""Turn the scenario x step x status cross-tab of the `campaign` event into flags.

Standard library only. No network access. It reads tool results the assistant
has already saved and prints Markdown (and, with --out, writes JSON).

Inputs:
  current       Saved `execute_analytics_eql` result for the current period, from
                the query in references/queries.md (rows: campaign_id, then
                action_id; columns: status).
  --previous    The same query for the previous period (optional). Enables the
                drop and "lost share rose" checks.
  --scenarios   Saved `search_scenarios` list result (optional). Adds scenario
                names, and lists active scenarios with no campaign events.

For each step it works out:
  reached   = attempts + held back + not queued, where
              attempts = max(enqueued, delivered + bounces)
  lost      = reached - delivered
  errors    = not queued + bounces
  enqueued  = the largest of the enqueued statuses (`enqueued`, `sent`), so a
              step that records both isn't counted twice
When a step has enqueued messages but no delivered or bounce statuses at all
(SMS and push record `sent` and no `delivered`), delivery is "unknown" and lost
counts only held back and not queued.

Cells that aren't numbers ("NA", "-") are treated as missing, not as 0, and
counted. Names come from the project and are untrusted: they are escaped before
they go into the Markdown table.

Thresholds and status groups come from references/rules.json.

Usage:
  python3 journey_flags.py current.json --previous previous.json --scenarios scenarios.json --out flags.json
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
SEVERITY_ORDER = {"high": 0, "medium": 1}
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}


def fail(msg):
    print("journey_flags.py: " + msg, file=sys.stderr)
    sys.exit(1)


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as e:
        fail("%s: can't read the file (%s)." % (path, e.strerror or e))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fail("%s: not valid JSON (%s)." % (path, e))


try:
    RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError) as _e:
    fail("%s: can't read the rules (%s)." % (RULES_PATH, _e))


def unwrap(doc, path):
    """Return the payload, failing on an error returned as data."""
    if isinstance(doc, dict) and "result" in doc and isinstance(doc["result"], dict):
        doc = doc["result"]
    if isinstance(doc, dict) and doc.get("success") is False:
        fail("%s: Loomi Connect returned an error: %s. This check couldn't run; don't treat it as "
             "'nothing found'." % (path, doc.get("error") or "no error text"))
    return doc


def number(value):
    """A count from a cell, or None when it's missing or not a number ("NA")."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str) or value.strip().lower() in MISSING:
        return None
    try:
        n = float(value.strip().replace(",", ""))
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def md(text):
    """Make an untrusted name safe for one Markdown table cell."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")
    text = text.replace("![", "!\\[").replace("<", "&lt;")
    return text


def header_value(cell):
    if isinstance(cell, dict):
        if cell.get("type") == "other":
            return "other"
        return cell.get("value")
    return cell


def parse_crosstab(doc, path):
    """Return ({(campaign_id, action_id): {status: count}}, zero_rows, missing_cells)."""
    doc = unwrap(doc, path)
    data = doc.get("data", doc) if isinstance(doc, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        fail("%s: no EQL rows found; save the execute_analytics_eql result of query 2." % path)
    try:
        return _crosstab(data)
    except (AttributeError, TypeError, IndexError) as e:
        fail("%s: not the cross-tab from query 2 (%s)." % (path, e))


def _crosstab(data):
    columns = []
    for col in data.get("columns") or []:
        cell = col[0] if isinstance(col, list) and col else col
        columns.append(header_value(cell))
    steps, zero_rows, missing = {}, 0, 0
    for row in data.get("rows") or []:
        heads = [header_value(h) for h in row.get("headers") or []]
        values = row.get("values") or []
        if not heads:
            continue
        cid = None if heads[0] is None else str(heads[0])
        aid = heads[1] if len(heads) > 1 else None
        if isinstance(aid, float) and aid.is_integer():
            aid = int(aid)
        counts = {}
        for status, value in zip(columns, values):
            n = number(value)
            if n is None:
                if value is not None:
                    missing += 1
                continue
            if n:
                key = "other" if status is None else str(status)
                counts[key] = counts.get(key, 0) + n
        if not counts:
            zero_rows += 1
            continue
        key = (cid, aid)
        merged = steps.setdefault(key, {})
        for status, n in counts.items():
            merged[status] = merged.get(status, 0) + n
    return steps, zero_rows, missing


def parse_scenarios(doc, path):
    doc = unwrap(doc, path)
    items = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(items, dict):
        items = items.get("data", [])
    if not isinstance(items, list):
        fail("%s: no scenario list found; save the search_scenarios result." % path)
    out = {}
    for s in items or []:
        if isinstance(s, dict) and s.get("_id"):
            out[str(s["_id"])] = {"name": s.get("name") or "(no name)", "status": s.get("status")}
    return out


def total(counts, statuses):
    return sum(counts.get(s, 0) for s in statuses)


def measure(counts):
    delivered = total(counts, RULES["delivered_statuses"])
    enqueued = max([counts.get(s, 0) for s in RULES["enqueued_statuses"]] or [0])
    held = total(counts, RULES["held_back_statuses"])
    not_queued = total(counts, RULES["not_queued_statuses"])
    bounces = total(counts, RULES["bounce_statuses"])
    attempts = max(enqueued, delivered + bounces)
    reached = attempts + held + not_queued
    unknown_delivery = enqueued > 0 and delivered == 0 and bounces == 0
    lost = held + not_queued if unknown_delivery else reached - delivered
    errors = not_queued + bounces
    known = set().union(*[RULES[k] for k in ("delivered_statuses", "enqueued_statuses", "held_back_statuses",
                                              "not_queued_statuses", "bounce_statuses", "engagement_statuses")])
    losses = {s: counts[s] for s in counts
              if s in RULES["held_back_statuses"] or s in RULES["not_queued_statuses"] or s in RULES["bounce_statuses"]}
    main_loss = max(losses, key=losses.get) if losses else None
    return {
        "reached": reached, "delivered": delivered, "lost": lost, "errors": errors,
        "lost_share": lost / reached if reached else None,
        "error_share": errors / reached if reached else None,
        "main_loss": main_loss, "unknown_delivery": unknown_delivery,
        "unknown_statuses": sorted(s for s in counts if s not in known),
    }


def judge(cur, prev):
    """Return a list of (severity, text) flags for one step."""
    flags = []
    if cur["reached"] >= RULES["min_reached"] and cur["lost_share"] is not None:
        share = cur["lost_share"]
        if share >= RULES["lost_share_high"]:
            flags.append(("high", "%.0f%% not delivered (mostly %s)" % (share * 100, cur["main_loss"])))
        elif share >= RULES["lost_share_medium"]:
            flags.append(("medium", "%.0f%% not delivered (mostly %s)" % (share * 100, cur["main_loss"])))
        elif cur["error_share"] >= RULES["error_share_medium"]:
            flags.append(("medium", "%.1f%% errors" % (cur["error_share"] * 100)))
    if prev:
        if prev["delivered"] >= RULES["drop_min_previous"] and cur["delivered"] <= RULES["drop_ratio"] * prev["delivered"]:
            sev = "high" if cur["delivered"] == 0 else "medium"
            change = (cur["delivered"] - prev["delivered"]) / prev["delivered"] * 100
            flags.append((sev, "delivered %s → %s (%+.0f%%)" % (fmt(prev["delivered"]), fmt(cur["delivered"]), change)))
        if (cur["reached"] >= RULES["min_reached"] and prev["reached"] >= RULES["min_reached"]
                and cur["lost_share"] is not None and prev["lost_share"] is not None
                and (cur["lost_share"] - prev["lost_share"]) * 100 >= RULES["lost_share_rise_points"]):
            flags.append(("medium", "not-delivered share rose %.0f → %.0f%%" % (prev["lost_share"] * 100, cur["lost_share"] * 100)))
    return flags


def fmt(n):
    return "{:,}".format(int(round(n)))


def pct(x):
    return "—" if x is None else "%.1f%%" % (x * 100)


def build(current, previous=None, scenarios=None, paths=("current", "previous", "scenarios")):
    cur_steps, zero_rows, missing = parse_crosstab(current, paths[0])
    prev_steps, _, prev_missing = parse_crosstab(previous, paths[1]) if previous is not None else ({}, 0, 0)
    names = parse_scenarios(scenarios, paths[2]) if scenarios is not None else {}
    keys = sorted(set(cur_steps) | set(prev_steps), key=lambda k: (str(k[0]), str(k[1])))
    steps, unknown = [], set()
    for key in keys:
        cur = measure(cur_steps.get(key, {}))
        prev = measure(prev_steps[key]) if key in prev_steps else None
        unknown.update(cur["unknown_statuses"])
        flags = judge(cur, prev)
        severity = min((f[0] for f in flags), key=SEVERITY_ORDER.get) if flags else None
        info = names.get(key[0], {})
        steps.append({
            "campaign_id": key[0], "action_id": key[1],
            "scenario": info.get("name"), "scenario_status": info.get("status"),
            "current": cur, "previous": prev,
            "severity": severity, "flags": [f[1] for f in flags],
        })
    sending = {s["campaign_id"] for s in steps if s["current"]["reached"] > 0}
    silent = [{"campaign_id": cid, "scenario": v["name"]} for cid, v in sorted(names.items())
              if v.get("status") == "active" and cid not in sending]
    not_listed = sorted({s["campaign_id"] for s in steps if names and s["campaign_id"] not in names and s["current"]["reached"] > 0})
    flagged = sorted([s for s in steps if s["severity"]],
                     key=lambda s: (SEVERITY_ORDER[s["severity"]], -s["current"]["lost"], -(s["previous"] or {}).get("delivered", 0)))
    return {"flagged": flagged, "steps": steps, "silent_active_scenarios": silent,
            "sending_but_not_in_list": not_listed, "zero_rows_dropped": zero_rows,
            "unknown_statuses": sorted(unknown), "missing_cells": missing + prev_missing}


def markdown(result):
    lines = ["| Severity | Scenario | Step | Reached | Delivered | Not delivered | Previous delivered | Flags |",
             "|---|---|---|---|---|---|---|---|"]
    for s in result["flagged"][:RULES["top"]]:
        cur, prev = s["current"], s["previous"]
        name = s["scenario"] or s["campaign_id"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            s["severity"], md(name), md(s["action_id"]), fmt(cur["reached"]),
            "unknown" if cur["unknown_delivery"] else fmt(cur["delivered"]),
            pct(cur["lost_share"]), fmt(prev["delivered"]) if prev else "—", "; ".join(s["flags"])))
    if len(result["flagged"]) > RULES["top"]:
        lines.append("")
        lines.append("%d more flagged steps not shown." % (len(result["flagged"]) - RULES["top"]))
    if not result["flagged"]:
        lines.append("| — | No step crossed a threshold | | | | | | |")
    lines.append("")
    if result["silent_active_scenarios"]:
        lines.append("Active scenarios with no campaign events in the period: " +
                     "; ".join("%s (%s)" % (md(s["scenario"]), md(s["campaign_id"])) for s in result["silent_active_scenarios"]))
    if result["sending_but_not_in_list"]:
        lines.append("Sending, but not in the scenario list (a standalone campaign or an inactive scenario): " +
                     ", ".join(md(c) for c in result["sending_but_not_in_list"]))
    if result["unknown_statuses"]:
        lines.append("Statuses not in rules.json, not counted: " + ", ".join(md(u) for u in result["unknown_statuses"]))
    if result["missing_cells"]:
        lines.append("Cells that weren't numbers, treated as missing: %d" % result["missing_cells"])
    lines.append("Rows with only zeros dropped: %d" % result["zero_rows_dropped"])
    return "\n".join(lines)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("current", help="saved execute_analytics_eql result for the current period")
    ap.add_argument("--previous", help="saved result for the previous period")
    ap.add_argument("--scenarios", help="saved search_scenarios list result")
    ap.add_argument("--out", help="write the full result as JSON to this path")
    args = ap.parse_args(argv)
    result = build(load(args.current),
                   load(args.previous) if args.previous else None,
                   load(args.scenarios) if args.scenarios else None,
                   paths=(args.current, args.previous, args.scenarios))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2, sort_keys=True)
        except OSError as e:
            fail("%s: can't write the file (%s)." % (args.out, e.strerror or e))
    print(markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
